"""AI Coding Dispatcher node for dispatching coding tasks from technical plans.

Strict Mode Implementation:
This dispatcher parses execution_plan from upstream AIPlanGenerationNode output
and creates CodingTasks directly without LLM analysis. Tasks targeting the
same repository and branch strategy are merged into a single CodingTask.

Clarification capability (Chassis v2 · P3)：当技术方案引用的目标仓库无法解析（``missing_repos``）
时，本节点不再直接 ``failed``，而是**挂起发起 HITL 澄清**——参照 ``ai_plan_research`` 的
``clarify``(out, shape=clarification_request)/``resume``(in, shape=clarification_answer) 端口
声明，复用既有发卡（``build_clarification_card`` + ``clarify_card_answer`` 路由）/回调
（``clarify_card_callback`` 的 ai_coding_dispatcher 分支）/续推（``_resume_from_callback`` 标记
经 ``_continue_after_node`` 节点重入），**不造两套**。回答回流后据答复把缺失仓引用重映射到目标
仓再派发；已澄清过仍缺失则 ``failed``（不再二次追问，防无限挂起）。
"""

import asyncio
from datetime import timedelta
from time import perf_counter
from typing import Any

import structlog
from django.utils import timezone

from common.logging import redact_secrets_in_text
from feishu.cards.chat_question_card import build_clarification_card
from repositories.models import Repository
from services.feishu_im import FeishuIMClient
from workflows.models.coding_task import CodingTask, CodingTaskStatus
from workflows.models.execution import WorkflowEventSubscription
from workflows.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeCategory,
    NodePort,
    NodeResult,
    PortType,
)
from workflows.nodes.integrations.chat_question import _get_feishu_credentials
from workflows.nodes.registry import register_node
from workflows.schemas.technical_plan import validate_technical_plan

logger = structlog.get_logger()

_COMPONENT = "workflow_node"


@register_node
class AICodingDispatcherNode(BaseNode):
    """AI 编码指派器节点 (严格模式)

    从上游 AIPlanGenerationNode 解析 execution_plan，
    直接创建 CodingTask 记录，无需 LLM 分析。

    特性:
    - 验证技术方案的 execution_plan 结构
    - 合并同一仓库/分支策略的任务
    - 并行创建 CodingTask 记录
    - 支持部分成功状态
    """

    node_type = "ai_coding_dispatcher"
    display_name = "AI 编码指派器"
    description = "从技术方案创建编码任务"
    icon = "git-branch"
    category = NodeCategory.AI
    execution_mode = "server_local"

    config_schema = {
        "type": "object",
        "properties": {
            "merge_same_branch": {
                "type": "boolean",
                "title": "合并同分支任务",
                "description": "是否将目标相同仓库/分支的任务合并为单个 CodingTask",
                "default": True,
            },
            "enable_clarification": {
                "type": "boolean",
                "title": "缺失仓库时发起澄清",
                "description": "目标仓库无法解析时挂起发起 HITL 澄清（而非直接失败）；关闭则直接失败",
                "default": True,
            },
            "chat_id": {
                "type": "string",
                "title": "澄清群聊 ID",
                "description": "发送澄清卡的目标群聊 ID（支持模板变量；缺省回退工作流上下文 chat_id）",
                "default": "",
            },
        },
    }

    inputs = [
        NodePort(
            name="plan",
            label="技术方案",
            port_type=PortType.OBJECT,
            required=True,
            description="上游 AIPlanGenerationNode 输出的技术方案",
        ),
        # SLOT-02：澄清回流「插槽端口」声明（凸点，shape=clarification_answer）——供编辑器形状
        # 磁吸 + validator 契约识别。**仅端口声明**：resume 续推钥匙是本节点 NodeExecution
        # output_data 的 `_resume_from_callback` 标记 + `clarification_answers`（由
        # clarify_card_callback 写入 + _continue_after_node 节点重入），execute 不读取本端口。
        NodePort(
            name="resume",
            label="澄清答复",
            port_type=PortType.OBJECT,
            required=False,
            shape="clarification_answer",
            description="回流澄清答案续推（凸点）",
        ),
    ]

    outputs = [
        NodePort(
            name="default",
            label="任务列表",
            port_type=PortType.OBJECT,
            description="创建的编码任务列表",
        ),
        # SLOT-02：澄清请求「插槽端口」声明（凹槽，shape=clarification_request）——目标仓缺失时
        # 吐澄清请求供形状磁吸 + validator 契约识别。**仅端口声明**：execute 不经本 handle 路由
        # （NodeResult.next_handle 仍只走 default/error；挂起逻辑在 _suspend_for_clarification）。
        NodePort(
            name="clarify",
            label="澄清请求",
            port_type=PortType.OBJECT,
            shape="clarification_request",
            description="目标仓库无法解析时吐出澄清请求（凹槽）",
        ),
        NodePort(
            name="error",
            label="失败",
            port_type=PortType.OBJECT,
            description="处理失败时的错误信息",
        ),
    ]

    async def execute(self, context: ExecutionContext) -> NodeResult:
        """解析技术方案并创建编码任务（目标仓缺失时挂起澄清 / 据答复重映射后派发）。"""
        config = context.node_config
        merge_same_branch = config.get("merge_same_branch", True)
        enable_clarification = config.get("enable_clarification", True)

        try:
            # 1. 获取上游技术方案数据
            plan_data = self._get_plan_data(context)
            if not plan_data:
                return NodeResult(
                    status="failed",
                    error="缺少技术方案输入，请确保上游 AIPlanGenerationNode 已执行",
                    next_handle="error",
                )

            # 2. 验证技术方案结构
            is_valid, error_msg = validate_technical_plan(plan_data)
            if not is_valid:
                return NodeResult(
                    status="failed",
                    error=f"技术方案验证失败: {error_msg}",
                    next_handle="error",
                )

            # 3. 检查 execution_plan 非空
            execution_plan = plan_data.get("execution_plan", [])
            if not execution_plan:
                return NodeResult(
                    status="failed",
                    error="execution_plan 为空，技术方案必须包含至少一个执行项",
                    next_handle="error",
                )

            # 3.5 澄清续推：若本节点是「澄清回答后节点重入」（output_data 带回流标记），据答复把
            #     缺失仓引用重映射到目标仓（resume 路径，与首跑物理隔离：首跑无回流标记）。
            is_resume, repo_overrides = self._resolve_resume_overrides(context)
            if repo_overrides:
                execution_plan = self._apply_repo_overrides(execution_plan, repo_overrides)

            # 4. 预取仓库以避免 N+1
            repo_ids = {task["repository_id"] for task in execution_plan}
            repositories = await self._fetch_repositories(repo_ids)

            # 5. 验证所有仓库存在；缺失则发起澄清挂起（首跑且启用且有执行上下文），否则失败。
            missing_repos = repo_ids - set(repositories.keys())
            if missing_repos:
                missing_refs = sorted(missing_repos)
                if (
                    enable_clarification
                    and not is_resume
                    and context.workflow_execution is not None
                    and context.node_execution is not None
                ):
                    return await self._suspend_for_clarification(context, missing_refs)
                # 已澄清过仍缺失（或未启用 / 无执行上下文）→ 失败，不再二次追问（防无限挂起）。
                return NodeResult(
                    status="failed",
                    error=f"仓库不存在: {', '.join(missing_refs)}",
                    next_handle="error",
                )

            # 6. 分组任务
            if merge_same_branch:
                task_groups = self._group_tasks(execution_plan)
            else:
                # 每个任务单独一组
                task_groups = {
                    (task["repository_id"], task["branch_strategy"]): [task]
                    for task in execution_plan
                }

            # 7. 获取全局上下文
            global_context = plan_data.get("global_context", "")

            # 8. 并行创建 CodingTasks
            create_coroutines = [
                self._create_coding_task(
                    context, repositories[repo_id], tasks, global_context
                )
                for (repo_id, _), tasks in task_groups.items()
            ]
            results = await asyncio.gather(*create_coroutines, return_exceptions=True)

            # 9. 处理结果
            return self._process_results(results, task_groups)

        except Exception as e:
            logger.error("coding_dispatcher_failed", error=str(e))
            return NodeResult(
                status="failed",
                error=str(e),
                next_handle="error",
            )

    def _get_plan_data(self, context: ExecutionContext) -> dict[str, Any] | None:
        """从上下文获取技术方案数据"""
        # 首先尝试从输入端口获取
        plan_data = context.get_previous_output("plan")
        if plan_data and isinstance(plan_data, dict):
            return plan_data

        # 尝试从全局参数获取 (向后兼容)
        plan_data = context.get_global_param("technical_plan")
        if plan_data and isinstance(plan_data, dict):
            return plan_data

        return None

    # ===== 澄清回流（resume）解析 =====

    def _resolve_resume_overrides(
        self, context: ExecutionContext
    ) -> tuple[bool, dict[str, str]]:
        """据本节点 ``NodeExecution.output_data`` 解析「澄清回答后重入」标记 + 缺失仓重映射。

        续推与首跑物理隔离：仅当 output_data 带 ``clarification_answered`` 回流标记时才视为
        resume。重映射按 ``missing_repo_refs[i]`` ↔ ``clarification_answers[i]`` 顺序对齐
        （发卡侧 questions_meta 与回调侧 _build_answers 同序，见模块 docstring）：每题答复取
        ``selected``（single=str / multi 取首项）或 ``freeform_text`` 作为目标仓 ID。

        返回 ``(is_resume, {missing_ref: target_repo_id})``；非 resume → ``(False, {})``。
        """
        node_execution = getattr(context, "node_execution", None)
        prior = getattr(node_execution, "output_data", None) if node_execution else None
        if not isinstance(prior, dict) or not prior.get("clarification_answered"):
            return False, {}
        missing_refs = prior.get("missing_repo_refs") or []
        answers = prior.get("clarification_answers") or []
        overrides: dict[str, str] = {}
        for idx, ref in enumerate(missing_refs):
            ans = answers[idx] if idx < len(answers) and isinstance(answers[idx], dict) else {}
            chosen = ans.get("selected")
            if isinstance(chosen, (list, tuple)):
                chosen = chosen[0] if chosen else None
            if not chosen:
                chosen = ans.get("freeform_text")
            chosen_str = str(chosen).strip() if chosen else ""
            if chosen_str:
                overrides[str(ref)] = chosen_str
        return True, overrides

    @staticmethod
    def _apply_repo_overrides(
        execution_plan: list[dict[str, Any]], overrides: dict[str, str]
    ) -> list[dict[str, Any]]:
        """把 execution_plan 中命中 ``overrides`` 的 ``repository_id`` 重映射为目标仓（不就地改）。"""
        remapped: list[dict[str, Any]] = []
        for task in execution_plan:
            rid = task.get("repository_id")
            if rid in overrides:
                remapped.append({**task, "repository_id": overrides[rid]})
            else:
                remapped.append(task)
        return remapped

    # ===== 缺失仓澄清挂起（复用既有发卡 / 回调 / 续推，不造两套） =====

    async def _suspend_for_clarification(
        self, context: ExecutionContext, missing_refs: list[str]
    ) -> NodeResult:
        """目标仓缺失 → 发飞书澄清卡（best-effort）+ 建 ClarifyCardCallback 订阅 → waiting_event。

        复用 ``ClarificationCardNode`` 的 transient 澄清范式：``build_clarification_card`` 携
        ``action="clarify_card_answer"`` 路由到 ``clarify_card_callback``（其 ai_coding_dispatcher
        分支据 ``_resume_from_callback`` 标记经 ``_continue_after_node`` 重入本节点）。挂起 output
        携 ``missing_repo_refs`` / ``questions_meta``（与答复回流按 order 对齐）。
        """
        started = perf_counter()
        initiated_by_user_id = self._resolve_initiator(context)
        log = logger.bind(
            execution_id=context.execution_id,
            node_id=context.node_id,
            component=_COMPONENT,
            category="caller",
            initiated_by_user_id=initiated_by_user_id,
        )

        config = context.node_config or {}
        chat_id = self._resolve_chat_id(context)
        card_questions = [
            {
                "question": redact_secrets_in_text(
                    f"技术方案引用的仓库 `{ref}` 无法解析，请填写正确的目标仓库 ID。"
                ),
                "type": "single",
                "options": [],
                "recommended": [],
            }
            for ref in missing_refs
        ]
        # questions_meta 与 missing_refs 同序：回调 _build_answers 按 order 枚举 → answers[i] ↔
        # missing_refs[i]（_resolve_resume_overrides 据此 zip 重映射）。
        questions_meta = [
            {"id": "", "order": idx, "qtype": "single"} for idx, _ in enumerate(missing_refs)
        ]

        card = build_clarification_card(
            card_questions,
            execution_id=context.execution_id,
            node_id=context.node_id,
            clarification_id="",
            action="clarify_card_answer",
            title=redact_secrets_in_text(str(config.get("title", "") or "编码任务派发")),
            reason="部分目标仓库无法解析，请补充正确的仓库以继续派发编码任务。",
        )

        # 发卡：整段 best-effort try/except（失败仍挂起，绝不反噬）。
        card_sent = False
        message_id = ""
        try:
            if chat_id:
                app_id, app_secret = await _get_feishu_credentials(context)
                im_client = FeishuIMClient(app_id=app_id, app_secret=app_secret)
                message_id = await im_client.send_card(
                    receive_id=chat_id, receive_id_type="chat_id", card=card
                )
                card_sent = True
                log.info("coding_dispatcher_clarify_card_sent", chat_id=chat_id)
        except Exception as exc:  # noqa: BLE001 — 发卡 best-effort，绝不反噬挂起
            log.warning(
                "coding_dispatcher_clarify_card_send_failed",
                error=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
            )

        # 建订阅（超时兜底，mirror ClarificationCardNode；不包 try/except）。
        await WorkflowEventSubscription.objects.acreate(
            workflow_execution=context.workflow_execution,
            node_execution=context.node_execution,
            event_type="ClarifyCardCallback",
            project_key=context.workflow_context.get("project_key", ""),
            timeout_at=timezone.now() + timedelta(minutes=60),
            timeout_action="fail",
        )

        log.info(
            "coding_dispatcher_clarification_suspended",
            missing_count=len(missing_refs),
            card_sent=card_sent,
            duration_ms=round((perf_counter() - started) * 1000, 2),
        )
        return NodeResult(
            status="waiting_event",
            output={
                "kind": "clarification",
                "clarification_id": "",
                "missing_repo_refs": missing_refs,
                "question_count": len(missing_refs),
                "questions_meta": questions_meta,
                "chat_id": chat_id,
                "card_sent": card_sent,
                "message_id": message_id,
            },
        )

    @staticmethod
    def _resolve_chat_id(context: ExecutionContext) -> str:
        """解析澄清群聊 ID：节点 config.chat_id（模板）→ 工作流上下文 chat_id 回退。"""
        raw = str((context.node_config or {}).get("chat_id", "") or "")
        chat_id = context.render_template(raw).strip() if raw else ""
        if not chat_id:
            chat_id = str((context.workflow_context or {}).get("chat_id", "") or "").strip()
        return chat_id

    @staticmethod
    def _resolve_initiator(context: ExecutionContext) -> str:
        """取工作流触发用户 id（缺记 system，观测约束：后台/外部触发带 initiated_by_user_id）。"""
        execution = context.workflow_execution
        if execution is not None:
            triggered_by_id = getattr(execution, "triggered_by_id", None)
            if triggered_by_id:
                return str(triggered_by_id)
        return "system"

    async def _fetch_repositories(
        self, repo_ids: set[str]
    ) -> dict[str, Repository]:
        """批量获取仓库对象"""
        return {
            str(r.id): r
            async for r in Repository.objects.filter(id__in=repo_ids, is_deleted=False)
        }

    def _group_tasks(
        self, execution_plan: list[dict[str, Any]]
    ) -> dict[tuple[str, str], list[dict[str, Any]]]:
        """按 (repository_id, branch_strategy) 分组任务"""
        groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for task in execution_plan:
            key = (task["repository_id"], task["branch_strategy"])
            groups.setdefault(key, []).append(task)
        return groups

    async def _create_coding_task(
        self,
        context: ExecutionContext,
        repository: Repository,
        tasks: list[dict[str, Any]],
        global_context: str,
    ) -> CodingTask:
        """创建单个 CodingTask (可能合并多个执行计划任务)"""
        workflow_execution = context.workflow_execution
        if not workflow_execution:
            raise ValueError("缺少 workflow_execution 上下文")

        # 提取任务 ID 列表
        execution_plan_ids = [task["id"] for task in tasks]

        # 构建任务名称
        if len(tasks) == 1:
            name = tasks[0].get("name", "未命名任务")
            description = tasks[0].get("description", "")
        else:
            name = f"合并任务: {repository.name} ({len(tasks)} 项)"
            description = "合并的任务:\n" + "\n".join(
                f"- {task.get('name', '未命名')}" for task in tasks
            )

        # 构建编码指令 (合并多个任务的指令)
        coding_instruction = self._build_merged_instruction(tasks)

        # 构建文件列表
        files_list = self._build_files_list(tasks)

        # 组合完整 Prompt
        prompt = self._compose_prompt(global_context, coding_instruction, files_list)

        # 创建 CodingTask
        coding_task = await CodingTask.objects.acreate(
            workflow_execution=workflow_execution,
            repository=repository,
            name=name,
            prompt=prompt,
            description=description,
            status=CodingTaskStatus.PENDING,
            execution_plan_ids=execution_plan_ids,
            global_context_snapshot=global_context,
            metadata={
                "branch_strategy": tasks[0].get("branch_strategy", "feature"),
                "task_count": len(tasks),
                "estimated_hours": sum(
                    task.get("estimated_hours", 0) for task in tasks
                ),
            },
        )

        logger.info(
            "coding_task_created",
            task_id=str(coding_task.id),
            repository=repository.name,
            merged_count=len(tasks),
        )

        return coding_task

    def _build_merged_instruction(self, tasks: list[dict[str, Any]]) -> str:
        """构建合并后的编码指令"""
        if len(tasks) == 1:
            return tasks[0].get("coding_instruction", "") or tasks[0].get(
                "description", ""
            )

        instructions = []
        for i, task in enumerate(tasks, 1):
            task_name = task.get("name", f"任务 {i}")
            instruction = task.get("coding_instruction", "") or task.get(
                "description", ""
            )
            instructions.append(f"## 任务 {i}: {task_name}\n\n{instruction}")

        return "\n\n---\n\n".join(instructions)

    def _build_files_list(self, tasks: list[dict[str, Any]]) -> str:
        """构建涉及的文件列表"""
        files_by_action: dict[str, list[str]] = {
            "create": [],
            "modify": [],
            "delete": [],
        }

        for task in tasks:
            for file_info in task.get("files", []):
                action = file_info.get("action", "modify")
                path = file_info.get("path", "")
                if path and action in files_by_action:
                    files_by_action[action].append(path)

        if not any(files_by_action.values()):
            return ""

        lines = ["## 涉及文件"]
        for action, label in [
            ("create", "创建"),
            ("modify", "修改"),
            ("delete", "删除"),
        ]:
            if files_by_action[action]:
                lines.append(f"\n### {label}")
                for path in files_by_action[action]:
                    lines.append(f"- `{path}`")

        return "\n".join(lines)

    def _compose_prompt(
        self, global_context: str, coding_instruction: str, files_list: str
    ) -> str:
        """组合完整的 AI 编码 Prompt"""
        parts = []

        if global_context:
            parts.append(f"# 项目背景\n\n{global_context}")

        if coding_instruction:
            parts.append(f"# 编码任务\n\n{coding_instruction}")

        if files_list:
            parts.append(files_list)

        return "\n\n---\n\n".join(parts)

    def _process_results(
        self,
        results: list[CodingTask | BaseException],
        task_groups: dict[tuple[str, str], list[dict[str, Any]]],
    ) -> NodeResult:
        """处理并行创建结果，支持部分成功"""
        successful_tasks: list[CodingTask] = []
        failed_details: list[dict[str, Any]] = []
        group_keys = list(task_groups.keys())

        for i, result in enumerate(results):
            repo_id, branch_strategy = group_keys[i]
            if isinstance(result, BaseException):
                failed_details.append(
                    {
                        "repository_id": repo_id,
                        "branch_strategy": branch_strategy,
                        "error": str(result),
                    }
                )
            else:
                successful_tasks.append(result)

        success_count = len(successful_tasks)
        failed_count = len(failed_details)
        total_count = success_count + failed_count

        # 构建输出
        output = {
            "tasks": [
                {
                    "id": str(task.id),
                    "name": task.name,
                    "repository_id": str(task.repository_id),
                    "status": task.status,
                    "execution_plan_ids": task.execution_plan_ids,
                }
                for task in successful_tasks
            ],
            "task_count": success_count,
            "success_count": success_count,
            "failed_count": failed_count,
        }

        if failed_details:
            output["failed_details"] = failed_details

        # 决定返回状态
        if failed_count == total_count:
            # 全部失败
            return NodeResult(
                status="failed",
                error=f"所有 {total_count} 个任务创建失败",
                output=output,
                next_handle="error",
            )
        elif failed_count > 0:
            # 部分成功
            logger.warning(
                "coding_tasks_partial_success",
                success_count=success_count,
                failed_count=failed_count,
            )
            return NodeResult(
                status="partial_success",
                output=output,
                next_handle="default",
            )
        else:
            # 全部成功
            logger.info(
                "coding_tasks_created",
                task_count=success_count,
            )
            return NodeResult(
                status="completed",
                output=output,
                next_handle="default",
            )
