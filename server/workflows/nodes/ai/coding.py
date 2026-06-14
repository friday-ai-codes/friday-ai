"""AI Coding node - orchestrates SubAgent coding tasks across repositories.

Reads a confirmed technical plan from upstream PlanApprovalNode, groups tasks
by repository, dispatches parallel SubAgent coding sessions, creates MRs for
successful repositories, and sends a Feishu result card.

Architecture decision: AICodingNode inherits BaseNode (NOT AIAgentBaseNode).
The orchestrator pattern (multiple SubAgents + polling + MR creation) is
fundamentally different from AIAgentBaseNode's single SDK agent model.

"""

import asyncio
import json
import re
import uuid
from typing import Any, ClassVar, Literal
from urllib.parse import urlparse

import structlog

from common.encryption import decrypt_value
from repositories.models import Repository
from services.git_platform import MRCreateRequest, MRCreateResult, get_git_platform_client
from services.provider_config import ProviderConfigError
from workflows.nodes.ai.sub_step_mixin import SubStepMixin
from workflows.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeCategory,
    NodePort,
    NodeResult,
    PortType,
)
from workflows.nodes.registry import register_node

logger = structlog.get_logger(__name__)

# 错误摘要最大长度
_MAX_ERROR_LENGTH = 200


def _truncate(text: str, max_length: int) -> str:
    """截断文本并添加省略标记。"""
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."


def _slugify(text: str, max_length: int = 30) -> str:
    """将标题转为 kebab-case 分支名片段。

    仅保留 ASCII 字母、数字和连字符。
    """
    # 移除非 ASCII 字符，替换空格为连字符
    slug = re.sub(r"[^a-zA-Z0-9\s-]", "", text)
    slug = re.sub(r"[\s_]+", "-", slug).strip("-").lower()
    return slug[:max_length] if slug else "task"


def _validate_anthropic_base_url(url: str) -> str:
    """contract 锁定的最小校验：scheme 白名单（http/https）+ 非空 + 去首尾空格。

    work item 允许用户自部署的 Anthropic 兼容网关（Moonshot / LiteLLM / OpenRouter 等）；
    空输入直接返回空字符串（调用方按 contract 不注入 metadata env_FRIDAY_TASK_CLAUDE_BASE_URL 键）。

    Args:
        url: 用户填写的 base_url（来自 ResolvedProviderConfig.base_url）。

    Returns:
        trimmed 后的合法 URL 字符串，或空串。

    Raises:
        ProviderConfigError: scheme 不在 {http, https} 白名单 或 缺少 host
            （security mitigation 缓解：阻断 javascript: / file:// 等注入容器）。
    """
    stripped = (url or "").strip()
    if not stripped:
        return ""
    parsed = urlparse(stripped)
    if parsed.scheme not in {"http", "https"}:
        raise ProviderConfigError(
            f"ANTHROPIC_BASE_URL scheme 必须是 http 或 https，实际：{parsed.scheme!r}"
        )
    if not parsed.netloc:
        raise ProviderConfigError(
            f"ANTHROPIC_BASE_URL 缺少 host：{stripped!r}"
        )
    return stripped


@register_node
class AICodingNode(SubStepMixin, BaseNode):
    """AI 编码执行节点。

    从上游 PlanApprovalNode 读取已确认技术方案，按仓库分组并行分发
    SubAgent 编码任务，编码完成后为每个成功仓库创建 MR，最终通过
    飞书结果卡片通知用户。

    Flow:
    1. 提取上游技术方案数据
    2. 按 repository_id 分组任务
    3. 解析/确认分支名（可能进入 waiting_event）
    4. 并行分发 SubAgent（每仓库一个）+ 轮询等待
    5. 为成功仓库并行创建 MR
    6. 发送飞书编码结果卡片
    7. 构建输出并返回
    """

    node_type: ClassVar[str] = "ai_coding"
    display_name: ClassVar[str] = "AI 编码执行"
    description: ClassVar[str] = "AI 自动编码并创建 MR"
    icon: ClassVar[str] = "terminal"
    category: ClassVar[NodeCategory] = NodeCategory.AI
    execution_mode: ClassVar[Literal["server_local", "runner_dispatched"]] = "runner_dispatched"
    is_blocking: ClassVar[bool] = True

    sub_steps: ClassVar[list[tuple[str, str]]] = [
        ("prepare_plan", "准备方案"),
        ("coding_execute", "编码执行"),
        ("create_mr", "创建MR"),
        ("send_notification", "发送通知"),
    ]

    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "container_image": {
                "type": "string",
                "title": "容器镜像",
                "description": "SubAgent 容器镜像",
                "default": "friday/claude-code:latest",
            },
            "timeout_seconds": {
                "type": "integer",
                "title": "编码超时（秒）",
                "description": "单个仓库编码超时（秒）",
                "default": 1800,
                "minimum": 300,
                "maximum": 7200,
            },
            "chat_id": {
                "type": "string",
                "title": "Chat ID",
                "description": "飞书群 ID，用于发送结果通知和分支确认",
                "default": "",
            },
            "polling_interval": {
                "type": "integer",
                "title": "轮询间隔（秒）",
                "description": "SubAgent 状态轮询间隔（秒）",
                "default": 15,
                "minimum": 5,
                "maximum": 60,
            },
        },
        "required": [],
    }

    inputs: ClassVar[list[NodePort]] = [
        NodePort(
            name="plan",
            label="技术方案",
            port_type=PortType.OBJECT,
            required=True,
            description="上游已确认的技术方案",
        ),
    ]

    outputs: ClassVar[list[NodePort]] = [
        NodePort(
            name="default",
            label="编码结果",
            port_type=PortType.OBJECT,
            description="编码结果，包含 merge_requests, branches, changes_summary",
            schema={
                "type": "object",
                "properties": {
                    "merge_requests": {
                        "type": "array",
                        "description": "成功创建的 MR 列表",
                    },
                    "branches": {
                        "type": "object",
                        "description": "分支信息",
                    },
                    "changes_summary": {
                        "type": "object",
                        "description": "变更统计",
                    },
                    "failed_details": {
                        "type": "array",
                        "description": "失败仓库详情",
                    },
                },
            },
        ),
        NodePort(
            name="error",
            label="错误",
            port_type=PortType.OBJECT,
            description="失败时的错误信息",
        ),
    ]

    # ------------------------------------------------------------------
    # execute
    # ------------------------------------------------------------------

    async def execute(self, context: ExecutionContext) -> NodeResult:
        """执行 AI 编码节点。"""
        from workflows.models.execution import SubStepStatus

        log = logger.bind(
            execution_id=context.execution_id,
            node_id=context.node_id,
        )

        # 0. 检查是否从 waiting_event 恢复
        if context.node_execution:
            output_data = getattr(context.node_execution, "output_data", None)
            if isinstance(output_data, dict):
                # 检查是否有恢复标记（容器完成后）
                if output_data.get("_resume_from_callback"):
                    # 恢复路径：不重复 init，直接从 create_mr 开始
                    await self.emit_sub_step(context, "create_mr", SubStepStatus.RUNNING)
                    return await self._resume_after_containers(context, output_data, log)

                # 分支确认恢复（保持不变）
                confirmed_branch = output_data.get("_confirmed_branch_name", "")
                if confirmed_branch:
                    # 继续正常执行流程
                    return await self._execute_with_branch(
                        context, confirmed_branch, log
                    )

        # 首次执行：初始化子步骤
        await self._init_sub_steps(context)
        await self.emit_sub_step(context, "prepare_plan", SubStepStatus.RUNNING)

        # 1. 提取方案数据
        plan_data = self._extract_plan_data(context)
        if not plan_data:
            return NodeResult(
                status="failed",
                error="缺少技术方案数据",
                next_handle="error",
            )

        plan_title: str = plan_data.get("title", "技术方案")
        execution_plan: list[dict[str, Any]] = plan_data.get("execution_plan", [])
        _global_context: str = plan_data.get("global_context", "")

        if not execution_plan:
            return NodeResult(
                status="failed",
                error="execution_plan 为空，至少需要一个执行任务",
                next_handle="error",
            )

        log.info(
            "ai_coding_start",
            plan_title=plan_title,
            task_count=len(execution_plan),
        )

        # 2. 按 repository_id 分组
        repo_groups = self._group_by_repository(execution_plan)

        # 3. 预取仓库信息
        repo_ids = set(repo_groups.keys())
        repositories = await self._fetch_repositories(repo_ids)

        missing = repo_ids - set(repositories.keys())
        if missing:
            return NodeResult(
                status="failed",
                error=f"仓库不存在: {', '.join(missing)}",
                next_handle="error",
            )

        # 4. 解析分支名
        branch_name = self._resolve_branch_name(plan_data, context)

        if not branch_name:
            # 无法确定分支名，发送飞书确认卡片
            candidate = self._generate_candidate_branch(plan_data, context)
            return await self._send_branch_confirmation(
                context, candidate, plan_title, plan_data, log
            )

        await self.emit_sub_step(context, "prepare_plan", SubStepStatus.COMPLETED)

        return await self._execute_with_branch(context, branch_name, log)

    async def _execute_with_branch(
        self,
        context: ExecutionContext,
        branch_name: str,
        log: Any,
    ) -> NodeResult:
        """使用已确认的分支名执行编码任务。"""
        # 从 context 重新获取方案数据
        plan_data = self._extract_plan_data(context)
        if not plan_data:
            return NodeResult(
                status="failed",
                error="缺少技术方案数据",
                next_handle="error",
            )

        plan_title: str = plan_data.get("title", "技术方案")
        execution_plan: list[dict[str, Any]] = plan_data.get("execution_plan", [])
        global_context: str = plan_data.get("global_context", "")

        # 重新获取仓库信息
        repo_groups = self._group_by_repository(execution_plan)
        repo_ids = set(repo_groups.keys())
        repositories = await self._fetch_repositories(repo_ids)

        # 确定 base branch（取第一个仓库的 default_branch）
        first_repo = next(iter(repositories.values()))
        base_branch: str = first_repo.default_branch or "main"

        log.info(
            "ai_coding_branch_resolved",
            branch_name=branch_name,
            base_branch=base_branch,
            repo_count=len(repo_groups),
        )

        # 5.0 解析 Anthropic 凭证
        #     在 _run_repo_coding 分发循环之前外层一次性完成，避免每 repo 重复 DB 往返
        #     （RESEARCH Open Question #1 推荐外层加载）。
        #
        #     优先级：「Claude Code 编码配置」（admin 设置页绑定的凭证）优先 ——
        #     所有启动 Claude Code 容器的路径统一以 CC 配置为准；未配置（api_key 为空）
        #     时回退原四层解析（node → project → system），保持向后兼容。
        from services.provider_config import (
            ProviderConfigService,
            ProviderMissingError,
            aget_claude_code_config,
            aget_claude_code_runtime_config,
        )

        resolved_api_key = ""
        resolved_base_url = ""
        credential_source = ""

        # 仅当显式绑定了 credential_id 才走 CC 分支 ——
        # runtime_config 未配置时内部回退系统默认凭证，直接判 api_key
        # 会让未配置 CC 的实例绕过节点/空间级凭证（四层契约回归）。
        cc_bound = bool((await aget_claude_code_config()).get("credential_id"))
        cc = await aget_claude_code_runtime_config() if cc_bound else None
        if cc is not None and cc["api_key"]:
            resolved_api_key = cc["api_key"]
            resolved_base_url = cc["base_url"]
            credential_source = "claude_code_config"
        else:
            from workflows.models import WorkflowExecution

            project = None
            if context.workflow_execution:
                we = await WorkflowExecution.objects.select_related(
                    "workflow__project"
                ).aget(id=context.workflow_execution.id)
                project = we.workflow.project if we.workflow else None

            # 强制 provider_type="anthropic"（Pitfall 5 缓解：防止上游 node_config 漂移
            # 到非 Anthropic Provider；AICodingNode 容器永久 Anthropic-only）
            anthropic_node_config = {
                **(context.node_config or {}),
                "provider_type": "anthropic",
            }
            resolved = await ProviderConfigService.aresolve_or_error(
                node_config=anthropic_node_config,
                conversation=None,              # AICodingNode 无 conversation 上下文
                project=project,
            )
            if isinstance(resolved, ProviderMissingError):
                raise ProviderConfigError(
                    resolved.recommended_action or "Anthropic 凭证缺失"
                )
            # resolved: ResolvedProviderConfig —— api_key / base_url 为明文
            resolved_api_key = resolved.api_key
            resolved_base_url = resolved.base_url
            credential_source = resolved.source

        validated_base_url = _validate_anthropic_base_url(resolved_base_url)

        # 只记 boolean / source，不记 api_key 明文值（security mitigation 缓解 + Pitfall 4 硬规则；
        # 另有 implementation P5 redact_credentials structlog processor 对 api_key 字段名兜底脱敏）
        log.info(
            "anthropic_credential_resolved",
            source=credential_source,
            has_base_url=bool(validated_base_url),
            has_api_key=bool(resolved_api_key),
        )

        # 5. 并行分发（通过 TaskDispatcher → Runner）
        from workflows.models.execution import SubStepStatus

        await self.emit_sub_step(context, "coding_execute", SubStepStatus.RUNNING)

        config = context.node_config

        node_execution_id = ""
        if context.node_execution:
            node_execution_id = str(context.node_execution.id)

        # RTOOL-03 机会性 PAT：仅解析「当前实时请求线程的明文 PAT」（绝不查 AccessToken/DB）。
        # 无明文来源（背景/飞书触发）→ 返回 ""，下游省略 env_FRIDAY_TASK_USER_TOKEN（PAT-02）。
        user_pat = await self._resolve_user_pat(context)

        coding_tasks = [
            self._run_repo_coding(
                repository=repositories[repo_id],
                tasks=tasks,
                branch_name=branch_name,
                base_branch=base_branch,
                global_context=global_context,
                config=config,
                node_execution_id=node_execution_id,
                anthropic_api_key=resolved_api_key,
                anthropic_base_url=validated_base_url,
                user_pat=user_pat,
            )
            for repo_id, tasks in repo_groups.items()
        ]
        results: list[dict[str, Any] | BaseException] = await asyncio.gather(
            *coding_tasks, return_exceptions=True
        )

        # 6. 分离 waiting_event / error
        waiting_sessions: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []

        group_keys = list(repo_groups.keys())
        for i, result in enumerate(results):
            repo_id = group_keys[i]
            repo = repositories[repo_id]

            if isinstance(result, BaseException):
                failed.append({
                    "repository_id": str(repo.id),
                    "repository_name": repo.name,
                    "error": _truncate(str(result), _MAX_ERROR_LENGTH),
                })
            elif isinstance(result, dict):
                if result.get("status") == "error":
                    failed.append({
                        "repository_id": str(repo.id),
                        "repository_name": repo.name,
                        "error": _truncate(result.get("error", "未知错误"), _MAX_ERROR_LENGTH),
                    })
                elif result.get("status") == "waiting_event":
                    waiting_sessions.append(result)
                else:
                    # 兼容旧模式（如果有）
                    waiting_sessions.append(result)

        log.info(
            "ai_coding_dispatch_complete",
            waiting=len(waiting_sessions),
            failed=len(failed),
        )

        # 7. 如果有 waiting_event，挂起 workflow
        if waiting_sessions:
            return NodeResult(
                status="waiting_event",
                output={
                    "pending_sessions": [
                        {
                            "session_id": s["session_id"],
                            "container_id": s["container_id"],
                            "repository_id": s["repository_id"],
                            "repository_name": s["repository_name"],
                        }
                        for s in waiting_sessions
                    ],
                    "failed_repos": failed,
                    "plan_data": plan_data,
                    "branch_name": branch_name,
                    "base_branch": base_branch,
                    "plan_title": plan_title,
                    # 保存用于恢复后 MR 创建
                    "repositories": {str(r.id): {"name": r.name, "id": str(r.id)} for r in repositories.values()},
                },
            )

        # 8. 如果全部失败，立即返回错误
        if not waiting_sessions and failed:
            return NodeResult(
                status="failed",
                error="所有仓库容器启动失败",
                output={"failed_details": failed},
                next_handle="error",
            )

        # 正常流程不会到达这里（waiting_event 会先返回）
        return NodeResult(
            status="failed",
            error="意外的执行路径",
            next_handle="error",
        )

    async def _resume_after_containers(
        self,
        context: ExecutionContext,
        output_data: dict[str, Any],
        log: Any,
    ) -> NodeResult:
        """容器完成后恢复 workflow 执行。

        检查所有 pending_sessions 的状态，为成功的仓库创建 MR。
        """
        pending_sessions = output_data.get("pending_sessions", [])
        failed_repos = output_data.get("failed_repos", [])
        branch_name = output_data.get("branch_name", "")
        base_branch = output_data.get("base_branch", "")
        plan_title = output_data.get("plan_title", "")
        plan_data = output_data.get("plan_data")
        _repositories_info = output_data.get("repositories", {})

        # 查询每个 session 的结果
        from subagent.models import SubAgentSession, TaskResult

        succeeded: list[dict[str, Any]] = []
        completed_session_ids: list[str] = []

        for session_info in pending_sessions:
            session_id = session_info["session_id"]
            repo_id = session_info["repository_id"]
            repo_name = session_info["repository_name"]

            try:
                session = await SubAgentSession.objects.filter(
                    session_id=session_id,
                ).afirst()

                if not session:
                    failed_repos.append({
                        "repository_id": repo_id,
                        "repository_name": repo_name,
                        "error": "Session 不存在",
                    })
                    continue

                if session.status == SubAgentSession.Status.COMPLETED:
                    completed_session_ids.append(session_id)
                    # 获取 TaskResult
                    task_result = await TaskResult.objects.filter(
                        session=session,
                    ).afirst()

                    if task_result:
                        succeeded.append({
                            "repository_id": repo_id,
                            "repository_name": repo_name,
                            "tasks_completed": [],  # 从 task_result 解析
                            "output": task_result.raw_output,
                            "mr_url": task_result.pr_url,
                            "mr_id": "",
                            "files_changed": len(task_result.modified_files) if task_result.modified_files else 0,
                            "insertions": 0,  # 从 raw_output 解析
                            "deletions": 0,
                        })
                    else:
                        succeeded.append({
                            "repository_id": repo_id,
                            "repository_name": repo_name,
                            "tasks_completed": [],
                            "output": {},
                            "mr_url": "",
                            "mr_id": "",
                            "files_changed": 0,
                            "insertions": 0,
                            "deletions": 0,
                        })

                elif session.status in (
                    SubAgentSession.Status.ERROR,
                    SubAgentSession.Status.TIMEOUT,
                ):
                    failed_repos.append({
                        "repository_id": repo_id,
                        "repository_name": repo_name,
                        "error": session.last_error or f"容器状态: {session.status}",
                    })

            except Exception as e:
                log.exception("session_check_error", session_id=session_id)
                failed_repos.append({
                    "repository_id": repo_id,
                    "repository_name": repo_name,
                    "error": str(e),
                })

        log.info(
            "resume_sessions_checked",
            succeeded=len(succeeded),
            failed=len(failed_repos),
        )

        # 为成功仓库创建 MR
        mr_results: list[dict[str, Any]] = []
        if succeeded:
            from repositories.models import Repository

            for result in succeeded:
                repo_id = result["repository_id"]
                repo = await Repository.objects.filter(id=repo_id).afirst()
                if repo:
                    mr_result = await self._create_mr_for_repo(
                        repository=repo,
                        branch_name=branch_name,
                        base_branch=base_branch,
                        plan_title=plan_title,
                        tasks_completed=result.get("tasks_completed", []),
                        changes_summary=result.get("output", {}),
                    )
                    mr_results.append({**result, **mr_result})

        # INGEST-02（14-06）：MR 创建之后的完成锚点（时序防线：归档不挂容器回调）。
        # 修订定案——先持久化后投递：mr_results 序列化写进 node_execution.output_data，
        # task_result normalizer 后台经 session.node_execution 重读（workflow 路径
        # mr_url 权威源）；持久化失败 warning 降级（normalizer 侧 mr_url 降级空串），
        # 不阻塞投递与节点完成。
        if completed_session_ids:
            serialized_mr_results = [
                {
                    "repository_id": str(r.get("repository_id", "")),
                    "mr_url": r.get("mr_url", ""),
                    "mr_id": str(r.get("mr_id", "") or ""),
                    "success": not r.get("error"),
                }
                for r in mr_results
            ]
            try:
                node_execution = context.node_execution
                if node_execution is not None:
                    # 合并不覆盖既有键（_resume_from_callback 等回调写入的状态保留）
                    merged = dict(node_execution.output_data or {})
                    merged["mr_results"] = serialized_mr_results
                    node_execution.output_data = merged
                    await node_execution.asave(update_fields=["output_data"])
            except Exception as exc:
                log.warning("mr_results_persist_failed", error=str(exc))

            from knowledge import ingestion  # lazy import 防循环

            for completed_session_id in completed_session_ids:
                await ingestion.aschedule_ingestion(
                    ingestion.IngestionRequest(
                        "task_result", completed_session_id, "workflow_coding_completed"
                    )
                )

        from workflows.models.execution import SubStepStatus

        await self.emit_sub_step(context, "create_mr", SubStepStatus.COMPLETED)

        # 发送飞书结果卡片
        await self.emit_sub_step(context, "send_notification", SubStepStatus.RUNNING)

        await self._send_result_notification(
            context=context,
            plan_title=plan_title,
            succeeded_repos=mr_results,
            failed_repos=failed_repos,
            branch_name=branch_name,
            base_branch=base_branch,
            log=log,
        )

        await self.emit_sub_step(context, "send_notification", SubStepStatus.COMPLETED)

        # 构建输出
        output = self._build_output(
            mr_results=mr_results,
            failed_repos=failed_repos,
            branch_name=branch_name,
            base_branch=base_branch,
            plan_data=plan_data,
        )

        if not mr_results:
            return NodeResult(
                status="failed",
                output=output,
                error="所有仓库编码均失败",
                next_handle="error",
            )

        return NodeResult(
            status="completed",
            output=output,
            next_handle="default",
        )

    # ------------------------------------------------------------------
    # 方案解析
    # ------------------------------------------------------------------

    def _extract_plan_data(
        self, context: ExecutionContext
    ) -> dict[str, Any] | None:
        """从上游输入提取技术方案数据。"""
        plan_data = context.get_input("plan")
        if plan_data and isinstance(plan_data, dict):
            return plan_data

        # 回退：整个 input_data 如果有 summary 字段
        if isinstance(context.input_data, dict) and "summary" in context.input_data:
            return context.input_data

        return None

    def _group_by_repository(
        self, execution_plan: list[dict[str, Any]]
    ) -> dict[str, list[dict[str, Any]]]:
        """按 repository_id 分组任务。"""
        groups: dict[str, list[dict[str, Any]]] = {}
        for task in execution_plan:
            repo_id: str = task.get("repository_id", "")
            if repo_id:
                groups.setdefault(repo_id, []).append(task)
        return groups

    async def _fetch_repositories(
        self, repo_ids: set[str]
    ) -> dict[str, Repository]:
        """批量获取仓库对象。"""
        return {
            str(r.id): r
            async for r in Repository.objects.filter(
                id__in=repo_ids, is_deleted=False
            )
        }

    # ------------------------------------------------------------------
    # 分支名解析
    # ------------------------------------------------------------------

    def _resolve_branch_name(
        self, plan_data: dict[str, Any], context: ExecutionContext
    ) -> str:
        """从方案数据或 trigger 上下文解析分支名。

        Returns:
            分支名字符串，无法确定时返回空字符串
        """
        # 优先从 plan_data 直接读取
        branch = plan_data.get("branch_name", "")
        if branch:
            return branch

        # 其次从 branches 字段读取
        branches = plan_data.get("branches", {})
        if isinstance(branches, dict):
            branch = branches.get("branch_name", "")
            if branch:
                return branch

        # 尝试自动生成
        return self._generate_candidate_branch(plan_data, context)

    def _generate_candidate_branch(
        self, plan_data: dict[str, Any], context: ExecutionContext
    ) -> str:
        """生成候选分支名。

        格式: feat/xxxx-m{work_item_id}-{description}
        """
        work_item_id = context.get_trigger_data("payload.work_item_id", "")
        if not work_item_id:
            work_item_id = context.get_trigger_data("payload.id", "")

        title = plan_data.get("title", "")
        description_slug = _slugify(title)

        if work_item_id:
            return f"feat/xxxx-m{work_item_id}-{description_slug}"

        # 无 work_item_id 时返回空，触发飞书确认流程
        return ""

    # ------------------------------------------------------------------
    # 分支确认（飞书卡片 + waiting_event）
    # ------------------------------------------------------------------

    async def _send_branch_confirmation(
        self,
        context: ExecutionContext,
        candidate: str,
        plan_title: str,
        plan_data: dict[str, Any],
        log: Any,
    ) -> NodeResult:
        """发送分支确认卡片并进入 waiting_event。"""
        chat_id = context.get_config("chat_id", "")

        # 提供一个默认候选名
        if not candidate:
            candidate = f"feat/ai-coding-{uuid.uuid4().hex[:8]}"

        if chat_id:
            try:
                from feishu.cards.coding_result_card import (
                    build_branch_confirmation_card,
                )

                card = build_branch_confirmation_card(
                    candidate_branch_name=candidate,
                    plan_title=plan_title,
                    execution_id=context.execution_id,
                    node_id=context.node_id,
                )

                # 获取 project 的飞书配置
                if context.workflow_execution:
                    from workflows.models import WorkflowExecution

                    we = await WorkflowExecution.objects.select_related(
                        "workflow__project"
                    ).aget(id=context.workflow_execution.id)
                    project = we.workflow.project if we.workflow else None

                    if project:
                        from agents.tools.feishu_doc_tools import (
                            create_feishu_doc_client_for_project,
                        )
                        from services.feishu_im import FeishuIMClient

                        doc_client = await create_feishu_doc_client_for_project(project)
                        im_client = FeishuIMClient(
                            app_id=doc_client.app_id,
                            app_secret=doc_client.app_secret,
                        )

                        await im_client.send_card(
                            receive_id=chat_id,
                            receive_id_type="chat_id",
                            card=card,
                        )

                        log.info(
                            "branch_confirmation_sent",
                            chat_id=chat_id,
                            candidate=candidate,
                        )

            except Exception as e:
                log.warning(
                    "branch_confirmation_send_failed",
                    error=str(e),
                )
        else:
            log.warning("branch_confirmation_no_chat_id")

        return NodeResult(
            status="waiting_event",
            output={
                "pending_branch_name": candidate,
                "plan_data": plan_data,
                "approval_status": "pending_branch_confirmation",
            },
        )

    # ------------------------------------------------------------------
    # SubAgent 分发（回调驱动模式）
    # ------------------------------------------------------------------

    async def _resolve_user_pat(self, context: ExecutionContext) -> str:
        """解析机会性 PAT 明文（RTOOL-03 / Open Q1 Option C + 机会性 B）。

        唯一合法明文来源：**带 PAT 的实时认证请求线程**——仅在该上下文内可拿到明文。
        本方法**绝不**从 AccessToken / 任何 DB 表读取明文
        （PAT-02：明文绝不落盘、不可从 DB 取；AccessToken 仅存 sha256 哈希）。
        明文亦绝不进日志（调用方只记 has_user_token=bool）。

        实现（RTOOL follow-up 已接入）：明文经 ``access_tokens.context`` 的请求级
        ContextVar 在触发边界（``WorkflowViewSet.execute``）捕获，由
        ``WorkflowEngine.start_execution`` 显式跨线程下传至本 ``ExecutionContext``
        的瞬态字段 ``user_pat_plaintext``。此处仅读该内存字段，**绝不**从
        AccessToken / 任何 DB 表读取（PAT-02），亦绝不进日志。

        无实时明文来源（背景/飞书/定时触发、或 JWT 会话手动触发）时该字段为空串，
        返回 "" → 下游省略 env_FRIDAY_TASK_USER_TOKEN，task 侧不挂 MCP server
        （向后兼容降级，无回归）。
        """
        return getattr(context, "user_pat_plaintext", "") or ""

    async def _run_repo_coding(
        self,
        repository: Repository,
        tasks: list[dict[str, Any]],
        branch_name: str,
        base_branch: str,
        global_context: str,
        config: dict[str, Any],
        node_execution_id: str = "",
        anthropic_api_key: str = "",        # work item W-1：Task 2 前置签名扩展；Task 3 在 metadata 中消费
        anthropic_base_url: str = "",        # work item W-1：Task 2 前置签名扩展；Task 3 在 metadata 中消费
        user_pat: str = "",                  # RTOOL-03 机会性 PAT：仅实时请求线程明文，绝不落盘/绝不从 DB 取（PAT-02 + Open Q1 Option C）
    ) -> dict[str, Any]:
        """通过 TaskDispatcher 分发编码任务到 Runner。"""
        log = logger.bind(
            repository_id=str(repository.id),
            repository_name=repository.name,
        )

        prompt = self._build_coding_prompt(tasks, global_context, branch_name)

        from runners.dispatcher import DispatchTask, get_dispatcher
        from subagent.models import SubAgentSession, generate_execution_id

        session_id = generate_execution_id()

        # Git 凭证
        git_credentials = {}
        if repository.credential and repository.credential.encrypted_token:
            token = decrypt_value(repository.credential.encrypted_token)
            git_credentials = {
                "access_token": token,
                "ssl_verify": str(repository.credential.ssl_verify).lower(),
            }

        # 构造 env_FRIDAY_TASK_CLAUDE_* 字段（contract 纠偏命名；Runner Docker executor
        # `env_` 前缀自动 TrimPrefix 约定，见 runner/internal/docker/executor.go:84-95）
        #   - api_key 非空时写入 env_FRIDAY_TASK_CLAUDE_API_KEY
        #   - base_url 非空时写入 env_FRIDAY_TASK_CLAUDE_BASE_URL（contract：空 base_url 不注入该键，
        #     容器内沿用 claude-agent-sdk 默认 https://api.anthropic.com 官方端点）
        anthropic_env: dict[str, str] = {}
        if anthropic_api_key:
            anthropic_env["env_FRIDAY_TASK_CLAUDE_API_KEY"] = anthropic_api_key
        if anthropic_base_url:
            anthropic_env["env_FRIDAY_TASK_CLAUDE_BASE_URL"] = anthropic_base_url

        # RTOOL-03：RemoteTool 链路注入。
        #   - tools endpoint 强制由 settings.FRIDAY_BASE_URL 推导（拼 /api/tools/execute/），
        #     绝不用 runner callback_url（Pitfall 1：错用会打到 runner 中转 → 工具调用 404）。
        #     契约：空 base_url 不注入该键（向后兼容降级——task 侧无 endpoint → 不挂 MCP server）。
        #   - 机会性 PAT：仅当实时请求线程提供明文时注入 env_FRIDAY_TASK_USER_TOKEN（见下），
        #     无来源则省略该键（PAT-02：明文绝不落盘/不可从 DB 取）。
        from django.conf import settings

        tools_env: dict[str, str] = {}
        base = getattr(settings, "FRIDAY_BASE_URL", "").rstrip("/")
        if base:
            tools_env["env_FRIDAY_TASK_TOOLS_ENDPOINT"] = f"{base}/api/tools/execute/"
        # 机会性 PAT：仅当上游解析出实时请求线程明文时注入（无来源 → 不注入该键，不阻塞 dispatch）。
        if user_pat:
            tools_env["env_FRIDAY_TASK_USER_TOKEN"] = user_pat

        # 排除规则下传（Phase 22-04 / EXCL-02 容器读取面，T-22-13/14）：与 chat 派发路径
        # 一致地无条件注入有效排除规则（即便仅 builtin），容器侧 clone 后据此物理删除被排除
        # 文件。不下传 = 容器内 agent 直接读到密钥/敏感文件（裸奔）。仅下传规则模式，无凭证。
        from services.exclusion import serialize_rules_for_repo

        exclude_env: dict[str, str] = {
            "env_FRIDAY_TASK_EXCLUDE_PATTERNS": json.dumps(
                await serialize_rules_for_repo(str(repository.id)),
                ensure_ascii=False,
            ),
        }

        dispatch_task = DispatchTask(
            task_id=session_id,
            task_type="coding",
            tags=["coding"],
            image=config.get("container_image", "friday/claude-code:latest"),
            repo_url=repository.git_url,
            branch=base_branch,
            target_branch=branch_name,
            prompt=prompt,
            timeout=config.get("timeout_seconds", 1800),
            node_execution_id=node_execution_id,
            session_id=session_id,
            metadata={
                "repository_id": str(repository.id),
                "repository_name": repository.name,
                "work_item_id": config.get("work_item_id", ""),
                "git_credentials": git_credentials,
                **anthropic_env,   # env_FRIDAY_TASK_CLAUDE_API_KEY + env_FRIDAY_TASK_CLAUDE_BASE_URL
                **tools_env,       # RTOOL-03：env_FRIDAY_TASK_TOOLS_ENDPOINT + 机会性 env_FRIDAY_TASK_USER_TOKEN
                **exclude_env,     # Phase 22-04：env_FRIDAY_TASK_EXCLUDE_PATTERNS（容器侧 prune）
            },
        )

        # 预创建 SubAgentSession（PENDING 状态）
        async def _create_session() -> None:
            from agents.models import AgentSession

            # 查找关联的 main_session
            main_session = None
            if node_execution_id:
                from workflows.models import NodeExecution

                node_exec = await NodeExecution.objects.filter(
                    id=node_execution_id,
                ).select_related("workflow_execution").afirst()
                if node_exec and node_exec.workflow_execution:
                    main_session = await AgentSession.objects.filter(
                        metadata__workflow_execution_id=str(
                            node_exec.workflow_execution.id
                        ),
                    ).afirst()

            # main_session 是必需 FK，无法找到时创建占位
            if not main_session:
                main_session = await AgentSession.objects.acreate(
                    metadata={"placeholder": True, "session_id": session_id},
                )

            await SubAgentSession.objects.aupdate_or_create(
                session_id=session_id,
                defaults={
                    "main_session": main_session,
                    "status": SubAgentSession.Status.PENDING,
                    "task_type": "coding",
                    "repo_url": repository.git_url,
                    "work_item_id": config.get("work_item_id", ""),
                    "target_branch": branch_name,
                    "node_execution_id": node_execution_id or None,
                },
            )

        try:
            await _create_session()
            await get_dispatcher().dispatch(dispatch_task)
            # 仅记 boolean，绝不记敏感值（PAT 明文/endpoint 明文不入日志，per Pitfall 4）
            log.info(
                "task_dispatched_to_runner",
                session_id=session_id,
                has_tools_endpoint=bool(base),
                has_user_token=bool(user_pat),
            )
        except Exception as e:
            log.error("task_dispatch_failed", error=str(e))
            return {
                "status": "error",
                "error": f"任务分发失败: {e}",
                "repository_id": str(repository.id),
                "repository_name": repository.name,
            }

        return {
            "status": "waiting_event",
            "session_id": session_id,
            "container_id": "",
            "repository_id": str(repository.id),
            "repository_name": repository.name,
        }

    def _build_coding_prompt(
        self,
        tasks: list[dict[str, Any]],
        global_context: str,
        branch_name: str,
    ) -> str:
        """构建 SubAgent 编码 prompt。

        合并该仓库所有任务的编码指令。
        """
        parts: list[str] = []

        if global_context:
            parts.append(f"# 项目背景\n\n{global_context}")

        parts.append(f"# 分支信息\n\n目标分支: `{branch_name}`")

        # 编码指令
        if len(tasks) == 1:
            task = tasks[0]
            task_name = task.get("name", "编码任务")
            instruction = task.get("coding_instruction", "") or task.get(
                "description", ""
            )
            parts.append(f"# 编码任务: {task_name}\n\n{instruction}")
        else:
            instructions: list[str] = []
            for i, task in enumerate(tasks, 1):
                task_name = task.get("name", f"任务 {i}")
                instruction = task.get("coding_instruction", "") or task.get(
                    "description", ""
                )
                instructions.append(f"## 任务 {i}: {task_name}\n\n{instruction}")
            parts.append("# 编码任务\n\n" + "\n\n---\n\n".join(instructions))

        # 文件列表
        files_section = self._build_files_section(tasks)
        if files_section:
            parts.append(files_section)

        # 要求
        parts.append(
            "# 要求\n\n"
            "- 确保类型检查通过\n"
            "- 确保单元测试通过\n"
            "- 每个任务至少一个 commit，commit message 清晰描述变更"
        )

        return "\n\n---\n\n".join(parts)

    def _build_files_section(self, tasks: list[dict[str, Any]]) -> str:
        """构建涉及的文件列表。"""
        files_by_action: dict[str, list[str]] = {
            "create": [],
            "modify": [],
            "delete": [],
        }

        for task in tasks:
            for file_info in task.get("files", []):
                if isinstance(file_info, dict):
                    action = file_info.get("action", "modify")
                    path = file_info.get("path", "")
                    if path and action in files_by_action:
                        files_by_action[action].append(path)

        if not any(files_by_action.values()):
            return ""

        lines = ["# 涉及文件"]
        for action, label in [
            ("create", "创建"),
            ("modify", "修改"),
            ("delete", "删除"),
        ]:
            if files_by_action[action]:
                lines.append(f"\n## {label}")
                for path in files_by_action[action]:
                    lines.append(f"- `{path}`")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # MR 创建
    # ------------------------------------------------------------------

    async def _create_mr_for_repo(
        self,
        repository: Repository,
        branch_name: str,
        base_branch: str,
        plan_title: str,
        tasks_completed: list[str],
        changes_summary: dict[str, Any],
    ) -> dict[str, Any]:
        """为单个仓库创建 MR。

        复用 CreatePRNode._create_pr_for_repository 的模式。
        """
        log = logger.bind(
            repository_id=str(repository.id),
            repository_name=repository.name,
        )

        # 获取 credential 并解密 token
        repo_with_cred = await Repository.objects.select_related(
            "credential"
        ).aget(id=repository.id)
        credential = repo_with_cred.credential
        if not credential or not credential.encrypted_token:
            log.warning("mr_creation_no_credential")
            return {
                "mr_url": "",
                "mr_id": "",
                "has_conflicts": False,
                "error": "仓库未配置访问凭证",
            }

        token = decrypt_value(credential.encrypted_token)
        client = get_git_platform_client(repository, token)

        # 构建 MR 描述
        task_checklist = "\n".join(
            f"- [x] {name}" for name in tasks_completed if name
        )
        summary_text = ""
        if isinstance(changes_summary, dict):
            files = changes_summary.get("files_changed", 0)
            adds = changes_summary.get("insertions", 0)
            dels = changes_summary.get("deletions", 0)
            if files or adds or dels:
                summary_text = f"{files} 文件变更 | +{adds} -{dels}"

        body = (
            f"## {plan_title}\n\n"
            f"### 任务清单\n{task_checklist}\n\n"
            f"### 变更摘要\n{summary_text}\n\n"
            f"---\n*由 Friday AI 自动创建*"
        )

        request = MRCreateRequest(
            source_branch=branch_name,
            target_branch=base_branch,
            title=plan_title,
            description=body,
            reviewer_usernames=[],
        )

        try:
            result: MRCreateResult = await client.create_merge_request(request)
        except Exception as e:
            log.error("mr_creation_error", error=str(e))
            return {
                "mr_url": "",
                "mr_id": "",
                "has_conflicts": False,
                "error": str(e),
            }

        if result.success:
            log.info(
                "mr_created",
                mr_url=result.mr_url,
                mr_id=result.mr_id,
            )
            return {
                "mr_url": result.mr_url,
                "mr_id": result.mr_id,
                "has_conflicts": result.has_conflicts,
            }
        else:
            log.warning("mr_creation_failed", error=result.error)
            return {
                "mr_url": "",
                "mr_id": "",
                "has_conflicts": False,
                "error": result.error or "MR 创建失败",
            }

    # ------------------------------------------------------------------
    # 飞书通知
    # ------------------------------------------------------------------

    async def _send_result_notification(
        self,
        context: ExecutionContext,
        plan_title: str,
        succeeded_repos: list[dict[str, Any]],
        failed_repos: list[dict[str, Any]],
        branch_name: str,
        base_branch: str,
        log: Any,
    ) -> None:
        """发送飞书编码结果卡片。"""
        chat_id = context.get_config("chat_id", "")
        if not chat_id:
            log.warning("result_notification_no_chat_id")
            return

        try:
            from feishu.cards.coding_result_card import build_coding_result_card

            # 计算总变更统计
            total_files = sum(r.get("files_changed", 0) for r in succeeded_repos)
            total_insertions = sum(r.get("insertions", 0) for r in succeeded_repos)
            total_deletions = sum(r.get("deletions", 0) for r in succeeded_repos)

            changes_summary = {
                "total_files": total_files,
                "total_insertions": total_insertions,
                "total_deletions": total_deletions,
            }

            card = build_coding_result_card(
                plan_title=plan_title,
                succeeded_repos=succeeded_repos,
                failed_repos=failed_repos,
                branch_name=branch_name,
                changes_summary=changes_summary,
            )

            # 获取 project 的飞书配置
            if not context.workflow_execution:
                log.warning("result_notification_no_workflow_execution")
                return

            from workflows.models import WorkflowExecution as WE2

            we = await WE2.objects.select_related(
                "workflow__project"
            ).aget(id=context.workflow_execution.id)
            project = we.workflow.project if we.workflow else None

            if not project:
                log.warning("result_notification_no_project")
                return

            from agents.tools.feishu_doc_tools import (
                create_feishu_doc_client_for_project,
            )
            from services.feishu_im import FeishuIMClient

            doc_client = await create_feishu_doc_client_for_project(project)
            im_client = FeishuIMClient(
                app_id=doc_client.app_id,
                app_secret=doc_client.app_secret,
            )

            await im_client.send_card(
                receive_id=chat_id,
                receive_id_type="chat_id",
                card=card,
            )

            log.info(
                "result_card_sent",
                chat_id=chat_id,
                succeeded=len(succeeded_repos),
                failed=len(failed_repos),
            )

        except Exception as e:
            # 卡片发送失败不阻塞主流程
            log.warning("result_card_send_failed", error=str(e))

    # ------------------------------------------------------------------
    # 输出构建
    # ------------------------------------------------------------------

    def _build_output(
        self,
        mr_results: list[dict[str, Any]],
        failed_repos: list[dict[str, Any]],
        branch_name: str,
        base_branch: str,
        plan_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """构建节点输出数据。"""
        merge_requests = [
            {
                "repository_id": r.get("repository_id", ""),
                "repository_name": r.get("repository_name", ""),
                "mr_url": r.get("mr_url", ""),
                "mr_id": r.get("mr_id", ""),
                "tasks_completed": r.get("tasks_completed", []),
                "files_changed": r.get("files_changed", 0),
                "insertions": r.get("insertions", 0),
                "deletions": r.get("deletions", 0),
            }
            for r in mr_results
        ]

        total_files = sum(r.get("files_changed", 0) for r in mr_results)
        total_insertions = sum(r.get("insertions", 0) for r in mr_results)
        total_deletions = sum(r.get("deletions", 0) for r in mr_results)

        return {
            "coding_result": {
                "merge_requests": merge_requests,
                "branches": {
                    "branch_name": branch_name,
                    "base_branch": base_branch,
                },
                "changes_summary": {
                    "total_repos": len(mr_results) + len(failed_repos),
                    "succeeded_repos": len(mr_results),
                    "failed_repos": len(failed_repos),
                    "total_files_changed": total_files,
                    "total_insertions": total_insertions,
                    "total_deletions": total_deletions,
                },
                "failed_details": failed_repos,
            },
            "merge_requests": merge_requests,
            "plan": plan_data,
        }

    # ------------------------------------------------------------------
    # 取消处理
    # ------------------------------------------------------------------

    async def on_cancel(self, context: ExecutionContext) -> None:
        """取消执行时的清理操作。

        注意：无法取消已提交的 SubAgent 任务（已知限制，
        SubAgent 容器有自己的超时机制作为兜底）。
        """
        logger.info(
            "ai_coding_cancelled",
            execution_id=context.execution_id,
            node_id=context.node_id,
        )
