"""AI Coding node - orchestrates SubAgent coding tasks across repositories.

Reads a confirmed technical plan from the upstream approval node, groups tasks
by repository, dispatches parallel SubAgent coding sessions, and creates MRs for
successful repositories.

D1 解耦：纯结果通知改由下游 ``notify_feishu_im`` 节点承担——本节点仅在显式配置
``chat_id`` 时作为可选回退推送结果卡片。分支确认卡片（HITL，需挂起等待用户确认
分支名）仍保留在本节点。

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

from repositories.models import Repository
from services.git_credentials import aresolve_git_token
from services.git_platform import MRCreateRequest, MRCreateResult, get_git_platform_client
from services.git_platform.models import MergeRequestLookupFailed
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
        raise ProviderConfigError(f"ANTHROPIC_BASE_URL 缺少 host：{stripped!r}")
    return stripped


@register_node
class AICodingNode(SubStepMixin, BaseNode):
    """AI 编码执行节点。

    从上游审批节点读取已确认技术方案，按仓库分组并行分发 SubAgent 编码任务，
    编码完成后为每个成功仓库创建 MR。

    D1 解耦：纯「结果通知」已交由下游 `notify_feishu_im` 节点承担——本节点不再
    强依赖结果卡片推送（`chat_id` 留空即不推送，仅作可选回退）。**分支确认卡片
    （HITL）仍保留在本节点**，它需要挂起 `waiting_event` 等待用户确认分支名，
    与结果通知性质不同。

    Flow:
    1. 提取上游技术方案数据
    2. 按 repository_id 分组任务
    3. 解析/确认分支名（无法确定时发分支确认卡片进入 waiting_event，HITL）
    4. 并行分发 SubAgent（每仓库一个）+ 容器回调驱动恢复
    5. 为成功仓库并行创建 MR
    6.（可选回退）配置了 chat_id 时发送飞书编码结果卡片；否则由下游通知节点推送
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
                "description": (
                    "飞书群 ID，用于发送分支确认卡片（HITL）。"
                    "编码结果通知已解耦到下游 notify_feishu_im 节点；"
                    "此处留空则不推送结果（仅作可选回退）。"
                ),
                "default": "",
            },
            "write_back": {
                "type": "boolean",
                "title": "回写飞书工作项",
                "description": (
                    "编码完成（MR 结果已知）后将执行结果回写到绑定的飞书工作项（评论）。"
                    "需要工作流上游绑定了工作项；未绑定时自动跳过。"
                ),
                "default": True,
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
                    return await self._execute_with_branch(context, confirmed_branch, log)

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

        # 4.5 拓扑分层（消费 execution_plan[].dependencies = task id；wave 状态走 DB 不存内存，
        #     不另造调度——wave N→N+1 由容器回调 _schedule_workflow_resume 触发节点重入自驱）。
        from services.process_runtime import build_repo_dep_edges, build_repo_waves

        repo_waves, cycle = build_repo_waves(execution_plan)
        if cycle is not None:
            # 依赖环 fail-fast：不进 dispatch（复用 plan_validator 三色 DFS，半可信 DoS 防御）。
            log.warning("ai_coding_dependency_cycle", detail=cycle)
            return NodeResult(
                status="failed",
                error="依赖环：" + str(cycle),
                output={"error": cycle},
                next_handle="error",
            )

        # 5.0 解析 Anthropic 凭证（dispatch 循环外一次性完成，避免每 repo 重复 DB 往返）
        resolved_api_key, validated_base_url = await self._resolve_anthropic_credentials(
            context, log
        )

        # 5. 分发（按 wave 分批；wave N 全终态才推 N+1）
        from workflows.models.execution import SubStepStatus

        await self.emit_sub_step(context, "coding_execute", SubStepStatus.RUNNING)

        config = context.node_config

        node_execution_id = ""
        if context.node_execution:
            node_execution_id = str(context.node_execution.id)

        # Phase 103 AGENT-01：解析派发发起用户（triggered_by）。有 user → 逐仓 mint 任务级
        # 短 TTL token；None（背景触发）→ 下游省略 env_FRIDAY_TASK_USER_TOKEN（降级不挂）。
        dispatch_user = await self._resolve_dispatch_user(context)

        # wave 接线：plan_version 可解析且分层完整覆盖时建 RepoCodingTask 行（INV-6 单一写入），
        # 仅 dispatch 当前（最小）wave；否则退化为现有全并行 dispatch 全部仓（零回归命门）。
        plan_version_id = plan_data.get("artifact_version_id")
        plan_version = None
        if plan_version_id:
            from delivery.models import ArtifactVersion  # lazy import 防循环

            plan_version = await ArtifactVersion.objects.filter(id=plan_version_id).afirst()

        service = None
        tasks_by_repo = None
        # 分层须完整覆盖全部待编码仓（legacy/非 canonical plan_data 任务无 id → repo_waves
        # 不覆盖该仓）才进 wave 模式，否则回退全并行保既有非编排路径零回归。
        wave_mode = (
            plan_version is not None
            and bool(repo_waves)
            and all(rid in repo_waves for rid in repo_groups)
        )
        if wave_mode:
            from delivery.services import RepoCodingTaskService

            service = RepoCodingTaskService()
            repo_edges = build_repo_dep_edges(execution_plan)
            tasks_by_repo = await service.create_tasks_for_plan(
                plan_version, repo_waves, repo_edges
            )
            # 首发恒为最小 wave（空 deps → 全仓 wave=0 → 一次性 dispatch 全部 = 现行为等价）
            current_wave = min(repo_waves.values())
            dispatch_repo_ids = [rid for rid in repo_groups if repo_waves.get(rid) == current_wave]
        else:
            if plan_version_id:
                log.warning("repo_coding_task_skipped_no_plan_version")
            dispatch_repo_ids = list(repo_groups.keys())

        waiting_sessions, failed = await self._dispatch_wave(
            repo_ids=dispatch_repo_ids,
            repo_groups=repo_groups,
            repositories=repositories,
            branch_name=branch_name,
            base_branch=base_branch,
            global_context=global_context,
            config=config,
            node_execution_id=node_execution_id,
            anthropic_api_key=resolved_api_key,
            anthropic_base_url=validated_base_url,
            dispatch_user=dispatch_user,
            tasks_by_repo=tasks_by_repo,
            service=service,
            log=log,
        )

        log.info(
            "ai_coding_dispatch_complete",
            waiting=len(waiting_sessions),
            failed=len(failed),
        )

        # 7. 如果有 waiting_event，挂起 workflow（仅传无状态 plan_version_id 锚，wave 状态走 DB）
        if waiting_sessions:
            return NodeResult(
                status="waiting_event",
                output=self._build_waiting_output(
                    waiting_sessions=waiting_sessions,
                    failed=failed,
                    plan_data=plan_data,
                    branch_name=branch_name,
                    base_branch=base_branch,
                    plan_title=plan_title,
                    repositories=repositories,
                    plan_version_id=str(plan_version_id) if wave_mode else "",
                ),
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

    async def _resolve_anthropic_credentials(
        self, context: ExecutionContext, log: Any
    ) -> tuple[str, str]:
        """解析 Anthropic 凭证，返回 ``(api_key, validated_base_url)``。

        优先「Claude Code 编码配置」（admin 设置页绑定的凭证）——所有启动 Claude Code
        容器的路径统一以 CC 配置为准；未配置（api_key 为空）时回退四层解析
        （node → project → system），保持向后兼容。首发与 wave 推进共用（不造两套）。
        """
        from services.provider_config import (
            ProviderConfigService,
            ProviderMissingError,
            aget_claude_code_config,
            aget_claude_code_runtime_config,
        )

        resolved_api_key = ""
        resolved_base_url = ""
        credential_source = ""

        # 仅当显式绑定了 credential_id 才走 CC 分支 —— runtime_config 未配置时内部回退
        # 系统默认凭证，直接判 api_key 会让未配置 CC 的实例绕过节点/空间级凭证（四层契约回归）。
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
                we = await WorkflowExecution.objects.select_related("workflow__space").aget(
                    id=context.workflow_execution.id
                )
                project = we.workflow.space if we.workflow else None

            # 强制 provider_type="anthropic"（防止上游 node_config 漂移到非 Anthropic
            # Provider；AICodingNode 容器永久 Anthropic-only）
            anthropic_node_config = {
                **(context.node_config or {}),
                "provider_type": "anthropic",
            }
            resolved = await ProviderConfigService.aresolve_or_error(
                node_config=anthropic_node_config,
                conversation=None,  # AICodingNode 无 conversation 上下文
                project=project,
            )
            if isinstance(resolved, ProviderMissingError):
                raise ProviderConfigError(resolved.recommended_action or "Anthropic 凭证缺失")
            # resolved: ResolvedProviderConfig —— api_key / base_url 为明文
            resolved_api_key = resolved.api_key
            resolved_base_url = resolved.base_url
            credential_source = resolved.source

        validated_base_url = _validate_anthropic_base_url(resolved_base_url)

        # 只记 boolean / source，不记 api_key 明文值（security mitigation 缓解；另有 P5
        # redact_credentials structlog processor 对 api_key 字段名兜底脱敏）。
        log.info(
            "anthropic_credential_resolved",
            source=credential_source,
            has_base_url=bool(validated_base_url),
            has_api_key=bool(resolved_api_key),
        )
        return resolved_api_key, validated_base_url

    async def _resolve_wave_project_contexts(
        self,
        *,
        repo_ids: list[str],
        repositories: dict[str, Repository],
        branch_name: str,
        config: dict[str, Any],
        dispatch_user: Any,
        log: Any,
    ) -> dict[str, str]:
        """按 (project, branch) 解析一次项目上下文，逐仓复用（Phase 103 AGENT-04）。

        项目定位：``ProjectBranch`` 反查优先（共享 helper），无绑定时按 config
        ``work_item_id`` 经 ``ProjectWorkItemLink`` fallback（多命中取首个 fail-soft）。
        召回按 ``str(project.id)`` 去重缓存——branch 在单次 wave 内恒定，project 维度
        去重即达成"按 (project, branch) 解析一次逐仓复用"，同 project 多仓不重复召回。

        project / dispatch_user 任一 None、召回空、任何异常 → 该仓空串（fail-soft，
        dispatch 与现状逐字一致，绝不阻断派发）。
        """
        contexts: dict[str, str] = {}
        if not repo_ids:
            return contexts

        from services.project_context_packer import (
            apack_dispatch_context,
            aresolve_project_for_repo_branch,
        )

        packed_by_project: dict[str, str] = {}
        for repo_id in repo_ids:
            text = ""
            try:
                repo = repositories[repo_id]
                project = await aresolve_project_for_repo_branch(
                    repository_id=repo.id, branch_name=branch_name
                )
                if project is None:
                    work_item_id = str(config.get("work_item_id", "") or "")
                    if work_item_id:
                        from initiatives.models import (  # lazy import 防循环
                            ProjectWorkItemLink,
                        )

                        link = await (
                            ProjectWorkItemLink.objects.filter(
                                work_item__work_item_id=work_item_id
                            )
                            .select_related("project")
                            .afirst()
                        )
                        project = link.project if link is not None else None
                if project is not None and dispatch_user is not None:
                    key = str(project.id)
                    if key not in packed_by_project:
                        packed_by_project[key] = await apack_dispatch_context(
                            project, dispatch_user, query=branch_name
                        )
                    text = packed_by_project[key]
            except Exception as exc:  # noqa: BLE001 — 召回 fail-soft，绝不阻断 dispatch
                log.warning(
                    "wave_project_context_failed",
                    repository_id=repo_id,
                    error_type=type(exc).__name__,
                    component="workflows",
                    category="sampling",
                )
                text = ""
            contexts[repo_id] = text
        return contexts

    async def _dispatch_wave(
        self,
        *,
        repo_ids: list[str],
        repo_groups: dict[str, list[dict[str, Any]]],
        repositories: dict[str, Repository],
        branch_name: str,
        base_branch: str,
        global_context: str,
        config: dict[str, Any],
        node_execution_id: str,
        anthropic_api_key: str,
        anthropic_base_url: str,
        dispatch_user: Any,
        tasks_by_repo: dict[str, Any] | None,
        service: Any,
        log: Any,
        upstream_artifacts_by_repo: dict[str, list[dict]] | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """dispatch 指定一批仓（单 wave），返回 ``(waiting_sessions, failed)``。

        首发与 wave 推进共用此 helper（不造两套）。保留单仓异常隔离
        （``asyncio.gather(..., return_exceptions=True)``）。wave 模式（service /
        tasks_by_repo 非空）：dispatch 成功仓经 ``service.mark_running`` 回填 RUNNING +
        subagent_session；dispatch 失败仓经 ``service.mark_failed`` 标终态——否则该仓无容器
        回调，wave 永挂（liveness）。

        ``upstream_artifacts_by_repo``（ARTIFACT-02）默认 None → 首发 wave 0 各仓注入 [] →
        prompt 与 Phase 44 逐字一致（零回归命门，首发 ``_execute_with_branch`` 不传该参）。
        """
        # ── Phase 51 GATE-01：dispatch 前 openspec gate（fail-closed + 单仓隔离，D-51-2）──
        # 仅 wave 模式实际执行；legacy/非 wave 短路零回归。被拦截仓经 mark_gate_blocked 标
        # 终态并移出 dispatch 列表，并入 failed 返回（经 aadvance 传递闭包阻断下游）。
        repo_ids, gate_blocked_failed = await self._apply_openspec_gate(
            repo_ids=repo_ids,
            repositories=repositories,
            tasks_by_repo=tasks_by_repo,
            service=service,
            log=log,
        )

        # ── Phase 103 AGENT-04：dispatch 前按 (project, branch) 解析一次项目上下文，
        # 逐仓复用传入 _run_repo_coding（prompt prepend + env 注入与 chat 路径一致）。
        # 解析失败/无项目/无 user → 空串 no-op（fail-soft，dispatch 与现状逐字一致）。
        project_contexts = await self._resolve_wave_project_contexts(
            repo_ids=repo_ids,
            repositories=repositories,
            branch_name=branch_name,
            config=config,
            dispatch_user=dispatch_user,
            log=log,
        )

        by_repo = upstream_artifacts_by_repo or {}
        coding_tasks = [
            self._run_repo_coding(
                repository=repositories[repo_id],
                tasks=repo_groups[repo_id],
                branch_name=branch_name,
                base_branch=base_branch,
                global_context=global_context,
                config=config,
                node_execution_id=node_execution_id,
                anthropic_api_key=anthropic_api_key,
                anthropic_base_url=anthropic_base_url,
                dispatch_user=dispatch_user,
                project_context=project_contexts.get(repo_id, ""),
                upstream_artifacts=by_repo.get(repo_id, []),
                # GATE-02：仅「通过 gate 且 follow_openspec=True」的仓（天然 = approved SDD 仓）
                # 注入 env（默认 False 保非 wave/legacy 零回归）。
                follow_openspec=(
                    bool(getattr(tasks_by_repo.get(repo_id), "follow_openspec", False))
                    if tasks_by_repo
                    else False
                ),
            )
            for repo_id in repo_ids
        ]
        results: list[dict[str, Any] | BaseException] = await asyncio.gather(
            *coding_tasks, return_exceptions=True
        )

        waiting_sessions: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        failed_repo_ids: list[str] = []

        for i, result in enumerate(results):
            repo_id = repo_ids[i]
            repo = repositories[repo_id]

            if isinstance(result, BaseException):
                failed.append(
                    {
                        "repository_id": str(repo.id),
                        "repository_name": repo.name,
                        "error": _truncate(str(result), _MAX_ERROR_LENGTH),
                    }
                )
                failed_repo_ids.append(repo_id)
            elif isinstance(result, dict):
                if result.get("status") == "error":
                    failed.append(
                        {
                            "repository_id": str(repo.id),
                            "repository_name": repo.name,
                            "error": _truncate(result.get("error", "未知错误"), _MAX_ERROR_LENGTH),
                        }
                    )
                    failed_repo_ids.append(repo_id)
                else:
                    waiting_sessions.append(result)

        # wave 模式：子任务级状态回填只经 service（INV-6）。
        if service is not None and tasks_by_repo is not None:
            from subagent.models import SubAgentSession

            for s in waiting_sessions:
                task = tasks_by_repo.get(s["repository_id"])
                if task is None:
                    continue
                sess = await SubAgentSession.objects.filter(session_id=s["session_id"]).afirst()
                if sess is not None:
                    await service.mark_running(task, sess)
            for rid in failed_repo_ids:
                task = tasks_by_repo.get(rid)
                if task is not None:
                    await service.mark_failed(task, {"reason": "dispatch_failed"})

        # gate 拦截仓并入 failed 返回（首发「全拦截无 waiting」与 waiting_output failed_repos
        # 展示一致；被拦截仓 task 已 failed → 后续 aadvance 传递闭包阻断其下游）。
        failed.extend(gate_blocked_failed)
        return waiting_sessions, failed

    async def _apply_openspec_gate(
        self,
        *,
        repo_ids: list[str],
        repositories: dict[str, Repository],
        tasks_by_repo: dict[str, Any] | None,
        service: Any,
        log: Any,
    ) -> tuple[list[str], list[dict[str, Any]]]:
        """编码前置 openspec gate（GATE-01，fail-closed + 单仓隔离，D-51-2/D-51-5）。

        返回 ``(passed_repo_ids, gate_blocked_failed)``：

        - ``follow_openspec=False`` 仓直接放行（非 SDD/legacy 零回归，**不触发任何 SddSpec
          查询**）。
        - ``follow_openspec=True`` 仓校验关联 ``SddSpec``（按 plan_version_id × repository_id）已
          ``APPROVED``：已批准放行；未批准（无 spec / 非 approved）经
          ``service.mark_gate_blocked(task, "spec_not_approved", <status|missing>)`` 拦截。
        - 单仓 gate 校验抛异常 → 保守 fail-closed（``mark_gate_blocked(task, "gate_error",
          "unknown")`` + log.warning），异常绝不向外冒泡、不波及其余仓 dispatch（绝不崩整 wave）。

        仅当 ``service`` 与 ``tasks_by_repo`` 均非空（wave 模式）实际执行 gate，否则原样返回
        ``repo_ids`` + 空 failed（零回归短路命门）。async ORM 安全：用 ``task.artifact_version_id``
        / ``task.repository_id`` 标量 + ``afirst``，绝不裸 lazy-FK（D-51-6）。
        """
        # 零回归短路：legacy / 非 wave 路径完全不经 gate（D-51-5 命门）。
        if service is None or tasks_by_repo is None:
            return list(repo_ids), []

        from delivery.models import SddSpec, SddSpecStatus  # lazy import 防循环

        passed_repo_ids: list[str] = []
        gate_blocked_failed: list[dict[str, Any]] = []

        for repo_id in repo_ids:
            task = tasks_by_repo.get(repo_id)
            # 无 task（理论不应发生）或 follow_openspec=False → 放行（非 SDD 零回归，不查 spec）。
            if task is None or not getattr(task, "follow_openspec", False):
                passed_repo_ids.append(repo_id)
                continue

            blocked_reason = "spec_not_approved"
            spec_status = "missing"
            try:
                spec = (
                    await SddSpec.objects.filter(
                        artifact_version_id=task.artifact_version_id,
                        repository_id=task.repository_id,
                    )
                    .order_by("-updated_at")
                    .afirst()
                )
                if spec is not None and spec.status == SddSpecStatus.APPROVED:
                    passed_repo_ids.append(repo_id)
                    continue
                # 未批准（无 spec / draft / in_review / 其它非 approved）→ 拦截。
                spec_status = str(spec.status) if spec is not None else "missing"
            except Exception as exc:  # noqa: BLE001 — gate fail-closed 隔离，绝不崩整 wave
                # 仅记 repo_id / error 字符串，绝不记 spec 正文（T-51-FAILOPEN）。
                log.warning("coding_openspec_gate_error", repo_id=repo_id, error=str(exc))
                blocked_reason = "gate_error"
                spec_status = "unknown"

            # WR-01：拦截写入也纳入单仓隔离边界——写入抖动绝不向外冒泡牵连整 wave。
            # 写入失败时仍把该仓计入 gate_blocked_failed（本轮 fail-closed 不 dispatch、
            # 下游照常阻断）；DB 态短暂留 pending 由后续 aadvance 重算兜底。
            try:
                await service.mark_gate_blocked(task, blocked_reason, spec_status)
            except Exception as exc:  # noqa: BLE001 — 拦截写入 fail-closed 隔离，绝不崩整 wave
                log.warning(
                    "coding_openspec_gate_block_write_failed",
                    repo_id=repo_id,
                    error=str(exc),
                )
            repo = repositories.get(repo_id)
            gate_blocked_failed.append(
                {
                    "repository_id": str(repo.id) if repo is not None else repo_id,
                    "repository_name": repo.name if repo is not None else repo_id,
                    "error": blocked_reason,
                }
            )

        return passed_repo_ids, gate_blocked_failed

    def _build_waiting_output(
        self,
        *,
        waiting_sessions: list[dict[str, Any]],
        failed: list[dict[str, Any]],
        plan_data: dict[str, Any] | None,
        branch_name: str,
        base_branch: str,
        plan_title: str,
        repositories: dict[str, Repository],
        plan_version_id: str,
    ) -> dict[str, Any]:
        """构建 waiting_event 的 output_data（wave 状态走 DB，仅传无状态 plan_version_id 锚）。"""
        return {
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
            "repositories": {
                str(r.id): {"name": r.name, "id": str(r.id)} for r in repositories.values()
            },
            # wave 推进锚（无状态——resume 段从 DB 重算 wave）；legacy 模式为空串。
            "plan_version_id": plan_version_id,
        }

    async def _resume_after_containers(
        self,
        context: ExecutionContext,
        output_data: dict[str, Any],
        log: Any,
    ) -> NodeResult:
        """容器完成后恢复 workflow 执行（wave 推进 / 单 wave 收尾分流）。

        - **wave 模式**（output_data 带非空 plan_version_id）：经 ``aadvance_coding_waves``
          判 gate → dispatch 下一 wave（再 waiting_event）或部分成功收尾。
        - **legacy 模式**（无 plan_version_id：分支确认 / 非编排路径）：走现有一次性收尾。
        """
        plan_version_id = output_data.get("plan_version_id")
        if plan_version_id:
            return await self._resume_wave(context, output_data, plan_version_id, log)
        return await self._resume_legacy(context, output_data, log)

    async def _resume_legacy(
        self,
        context: ExecutionContext,
        output_data: dict[str, Any],
        log: Any,
    ) -> NodeResult:
        """单 wave 收尾（无 plan_version_id 的既有路径，零回归）。

        检查所有 pending_sessions 的状态，为成功的仓库创建 MR。
        """
        pending_sessions = output_data.get("pending_sessions", [])
        failed_repos = output_data.get("failed_repos", [])
        branch_name = output_data.get("branch_name", "")
        base_branch = output_data.get("base_branch", "")
        plan_title = output_data.get("plan_title", "")
        plan_data = output_data.get("plan_data")

        # 查询每个 session 的结果
        from subagent.models import SubAgentSession, TaskResult

        succeeded: list[dict[str, Any]] = []
        completed_session_ids: list[str] = []
        # LOOP-03（101-03）：session → repository 映射，供完工闭环按仓取 mr_url。
        session_repo_map: dict[str, str] = {}

        for session_info in pending_sessions:
            session_id = session_info["session_id"]
            repo_id = session_info["repository_id"]
            repo_name = session_info["repository_name"]

            try:
                session = await SubAgentSession.objects.filter(
                    session_id=session_id,
                ).afirst()

                if not session:
                    failed_repos.append(
                        {
                            "repository_id": repo_id,
                            "repository_name": repo_name,
                            "error": "Session 不存在",
                        }
                    )
                    continue

                if session.status == SubAgentSession.Status.COMPLETED:
                    completed_session_ids.append(session_id)
                    session_repo_map[session_id] = str(repo_id)
                    # 获取 TaskResult
                    task_result = await TaskResult.objects.filter(
                        session=session,
                    ).afirst()

                    if task_result:
                        succeeded.append(
                            {
                                "repository_id": repo_id,
                                "repository_name": repo_name,
                                "tasks_completed": [],  # 从 task_result 解析
                                "output": task_result.raw_output,
                                "mr_url": task_result.pr_url,
                                "mr_id": "",
                                "files_changed": len(task_result.modified_files)
                                if task_result.modified_files
                                else 0,
                                "insertions": 0,  # 从 raw_output 解析
                                "deletions": 0,
                            }
                        )
                    else:
                        succeeded.append(
                            {
                                "repository_id": repo_id,
                                "repository_name": repo_name,
                                "tasks_completed": [],
                                "output": {},
                                "mr_url": "",
                                "mr_id": "",
                                "files_changed": 0,
                                "insertions": 0,
                                "deletions": 0,
                            }
                        )

                elif session.status in (
                    SubAgentSession.Status.ERROR,
                    SubAgentSession.Status.TIMEOUT,
                ):
                    failed_repos.append(
                        {
                            "repository_id": repo_id,
                            "repository_name": repo_name,
                            "error": session.last_error or f"容器状态: {session.status}",
                        }
                    )

            except Exception as e:
                log.exception("session_check_error", session_id=session_id)
                failed_repos.append(
                    {
                        "repository_id": repo_id,
                        "repository_name": repo_name,
                        "error": str(e),
                    }
                )

        log.info(
            "resume_sessions_checked",
            succeeded=len(succeeded),
            failed=len(failed_repos),
        )

        return await self._finalize_and_notify(
            context=context,
            succeeded=succeeded,
            failed_repos=failed_repos,
            completed_session_ids=completed_session_ids,
            branch_name=branch_name,
            base_branch=base_branch,
            plan_title=plan_title,
            plan_data=plan_data,
            log=log,
            session_repo_map=session_repo_map,
        )

    async def _resume_wave(
        self,
        context: ExecutionContext,
        output_data: dict[str, Any],
        plan_version_id: Any,
        log: Any,
    ) -> NodeResult:
        """wave 推进：经 ``aadvance_coding_waves`` 判 gate → 推下一 wave 或部分成功收尾。

        aadvance 异常不外抛，绝不让节点重入异常回灌使容器回调 5xx（对齐 Pitfall 4；
        ``_schedule_workflow_resume`` 本身 fire-and-forget 不改契约）——但也**不再当作
        正常收尾**：推进失败说明 wave 状态机没走完（可能仍有仓 RUNNING、或下一 wave
        未派发），此时仍走 ``_finalize_wave`` 保住已 done 仓的 MR，随后把 NodeResult
        显式降级为 ``failed``，避免「表面成功、实际丢步骤」。

        wave N→N+1 由下一轮容器回调重入驱动（**不另造调度**：无轮询 / 无 sleep /
        无定时器）。

        有限收敛 ``for`` 循环（非调度循环）仅处理「本 wave 全 dispatch 失败（无容器回调可
        驱动）」时**当轮**再 advance 阻断下游并收敛——每次 continue 都使一批 task 转终态，
        迭代数 ≤ 本 plan_version 的 task 总数，必终止。
        """
        from delivery.models import RepoCodingTask
        from services.process_runtime import aadvance_coding_waves

        # 收敛上界 = task 总数（每次 continue 至少使一批 pending→failed，严格收敛）。
        max_passes = (
            await RepoCodingTask.objects.filter(artifact_version_id=plan_version_id).acount() + 1
        )
        for _ in range(max_passes):
            try:
                result = await aadvance_coding_waves(plan_version_id)
            except Exception as exc:  # noqa: BLE001 — 不回灌回调 5xx，但必须标失败
                # 推进失败意味着 wave 状态机没走完：可能仍有仓在 RUNNING、或下一 wave
                # 根本没派发。此前这里直接 _finalize_wave 收尾，节点会以「完成」示人并
                # 触发 MR / 通知 / 经验沉淀——用户看到流程成功，实际编码没做完。
                #
                # 仍然收尾（已 done 的仓该出的 MR 不能丢），但把结果显式降级为 failed，
                # 让「部分完成」在 UI 与后续判断里可见。不 raise 是刻意的：这条路径由
                # 容器回调驱动，抛异常会让回调 5xx 触发重试风暴（Pitfall 4）。
                log.error("coding_wave_advance_failed", error=str(exc))
                partial = await self._finalize_wave(context, output_data, plan_version_id, log)
                return NodeResult(
                    status="failed",
                    output=partial.output,
                    error=(
                        f"wave 推进失败，已按当前 DB 状态收尾（可能有仓未完成或未派发）: {exc}"
                    ),
                )

            # waiting：仍有 RUNNING 在途 task（aadvance 仅在 RUNNING 时返回 waiting）→ 重挂起
            # 等下一次容器回调，绝不当作收尾触发（waiting != finalize）。
            if result.get("waiting"):
                log.info("coding_wave_still_running", plan_version_id=str(plan_version_id))
                return self._resuspend_wave(output_data)

            # dispatch：下一 wave 待派发 → dispatch + mark_running + 再 waiting_event 挂起。
            if result.get("dispatch"):
                waiting_sessions = await self._dispatch_next_wave(context, output_data, result, log)
                if waiting_sessions:
                    return NodeResult(
                        status="waiting_event",
                        output=self._build_resume_waiting_output(
                            output_data, waiting_sessions, str(plan_version_id)
                        ),
                    )
                # 本 wave 全 dispatch 失败（已标 failed）→ 当轮再 advance 阻断下游 / 收尾。
                continue

            # all_terminal（或无更多在途）→ 收尾。
            return await self._finalize_wave(context, output_data, plan_version_id, log)

        # 兜底（理论不可达：max_passes 已覆盖最坏全失败链）→ 收尾，绝不悬挂。
        return await self._finalize_wave(context, output_data, plan_version_id, log)

    async def _dispatch_next_wave(
        self,
        context: ExecutionContext,
        output_data: dict[str, Any],
        result: dict[str, Any],
        log: Any,
    ) -> list[dict[str, Any]]:
        """dispatch aadvance 返回的下一 wave 仓（复用 _dispatch_wave），返回 waiting_sessions。"""
        from delivery.services import RepoCodingTaskService
        from workflows.models.execution import SubStepStatus

        dispatch_tasks = result.get("dispatch", [])
        tasks_by_repo = {str(t.repository_id): t for t in dispatch_tasks}
        dispatch_repo_ids = list(tasks_by_repo.keys())

        plan_data = output_data.get("plan_data") or {}
        execution_plan: list[dict[str, Any]] = plan_data.get("execution_plan", [])
        global_context: str = plan_data.get("global_context", "")
        branch_name = output_data.get("branch_name", "")
        base_branch = output_data.get("base_branch", "")

        repo_groups = self._group_by_repository(execution_plan)
        repositories = await self._fetch_repositories(set(dispatch_repo_ids))

        service = RepoCodingTaskService()

        # 仓被删 → 标 failed（避免该 task 永 pending 致 while 循环重派死循环，liveness）。
        missing_ids = [rid for rid in dispatch_repo_ids if rid not in repositories]
        for rid in missing_ids:
            await service.mark_failed(tasks_by_repo[rid], {"reason": "repository_not_found"})

        resolved_api_key, validated_base_url = await self._resolve_anthropic_credentials(
            context, log
        )
        node_execution_id = ""
        if context.node_execution:
            node_execution_id = str(context.node_execution.id)
        dispatch_user = await self._resolve_dispatch_user(context)

        await self.emit_sub_step(context, "coding_execute", SubStepStatus.RUNNING)

        # ── ARTIFACT-02：唯一注入收集点（D-07）——沿直接 depends_on 收集上游产物 ──
        # 逐仓 fail-soft：单仓收集异常 → warning → 仅该仓注入空段（零回归降级），不波及其余仓
        # 已收集产物，绝不让容器回调 5xx 致重试风暴（T-45-08）。仅记 repo_id / error 字符串，
        # 绝不记产物正文（T-45-07）。
        upstream_by_repo: dict[str, list[dict]] = {}
        from services.process_runtime.artifact_injection import (
            acollect_upstream_artifacts,
        )

        for repo_id, task in tasks_by_repo.items():
            try:
                upstream_by_repo[repo_id] = await acollect_upstream_artifacts(task)
            except Exception as exc:  # noqa: BLE001 — 单仓注入降级，绝不阻塞 wave 推进 / 回调主流程
                upstream_by_repo[repo_id] = []
                log.warning("coding_upstream_collect_failed", repo_id=repo_id, error=str(exc))

        waiting_sessions, failed = await self._dispatch_wave(
            repo_ids=[rid for rid in dispatch_repo_ids if rid in repositories],
            repo_groups=repo_groups,
            repositories=repositories,
            branch_name=branch_name,
            base_branch=base_branch,
            global_context=global_context,
            config=context.node_config,
            node_execution_id=node_execution_id,
            anthropic_api_key=resolved_api_key,
            anthropic_base_url=validated_base_url,
            dispatch_user=dispatch_user,
            tasks_by_repo=tasks_by_repo,
            service=service,
            log=log,
            upstream_artifacts_by_repo=upstream_by_repo,
        )
        log.info(
            "coding_wave_next_dispatched",
            wave=result.get("wave"),
            waiting=len(waiting_sessions),
            failed=len(failed),
        )
        return waiting_sessions

    def _resuspend_wave(self, output_data: dict[str, Any]) -> NodeResult:
        """仍有在途容器 → 重挂起（清除回调控制键），等下一次回调重入。"""
        clean = {
            k: v
            for k, v in output_data.items()
            if k not in ("_resume_from_callback", "_all_containers_completed", "_session_results")
        }
        return NodeResult(status="waiting_event", output=clean)

    def _build_resume_waiting_output(
        self,
        output_data: dict[str, Any],
        waiting_sessions: list[dict[str, Any]],
        plan_version_id: str,
    ) -> dict[str, Any]:
        """下一 wave 挂起 output：复用既有无状态上下文，刷新 pending_sessions。"""
        return {
            "pending_sessions": [
                {
                    "session_id": s["session_id"],
                    "container_id": s["container_id"],
                    "repository_id": s["repository_id"],
                    "repository_name": s["repository_name"],
                }
                for s in waiting_sessions
            ],
            "failed_repos": output_data.get("failed_repos", []),
            "plan_data": output_data.get("plan_data"),
            "branch_name": output_data.get("branch_name", ""),
            "base_branch": output_data.get("base_branch", ""),
            "plan_title": output_data.get("plan_title", ""),
            "repositories": output_data.get("repositories", {}),
            "plan_version_id": plan_version_id,
        }

    async def _finalize_wave(
        self,
        context: ExecutionContext,
        output_data: dict[str, Any],
        plan_version_id: Any,
        log: Any,
    ) -> NodeResult:
        """wave 全终态收尾：从 DB（RepoCodingTask）重算 done/failed 仓，复用收尾段。

        done 仓出 MR；failed 仓如实标注（``error.reason=upstream_failed`` 的为下游阻断仓）；
        不自动回滚（v0.8 显式非目标，已成功仓分支 / 产物不回退）。
        """
        from delivery.models import RepoCodingTask, RepoCodingTaskStatus
        from repositories.models import Repository
        from subagent.models import SubAgentSession, TaskResult

        branch_name = output_data.get("branch_name", "")
        base_branch = output_data.get("base_branch", "")
        plan_title = output_data.get("plan_title", "")
        plan_data = output_data.get("plan_data")

        succeeded: list[dict[str, Any]] = []
        failed_repos: list[dict[str, Any]] = []
        completed_session_ids: list[str] = []
        # LOOP-03（101-03）：session → repository 映射，供完工闭环按仓取 mr_url。
        session_repo_map: dict[str, str] = {}

        async for task in RepoCodingTask.objects.filter(artifact_version_id=plan_version_id):
            repo_id = str(task.repository_id)
            repo = await Repository.objects.filter(id=repo_id).afirst()
            repo_name = repo.name if repo else repo_id

            if task.status == RepoCodingTaskStatus.DONE:
                task_result = None
                sid = task.subagent_session_id
                if sid:
                    sess = await SubAgentSession.objects.filter(id=sid).afirst()
                    if sess is not None:
                        completed_session_ids.append(sess.session_id)
                        session_repo_map[sess.session_id] = repo_id
                        task_result = await TaskResult.objects.filter(session=sess).afirst()
                if task_result is not None:
                    succeeded.append(
                        {
                            "repository_id": repo_id,
                            "repository_name": repo_name,
                            "tasks_completed": [],
                            "output": task_result.raw_output,
                            "mr_url": task_result.pr_url,
                            "mr_id": "",
                            "files_changed": (
                                len(task_result.modified_files) if task_result.modified_files else 0
                            ),
                            "insertions": 0,
                            "deletions": 0,
                        }
                    )
                else:
                    succeeded.append(
                        {
                            "repository_id": repo_id,
                            "repository_name": repo_name,
                            "tasks_completed": [],
                            "output": {},
                            "mr_url": "",
                            "mr_id": "",
                            "files_changed": 0,
                            "insertions": 0,
                            "deletions": 0,
                        }
                    )
            elif task.status == RepoCodingTaskStatus.FAILED:
                err = task.error if isinstance(task.error, dict) else {}
                if err.get("reason") == "upstream_failed":
                    upstream = ", ".join(err.get("upstream", []))
                    msg = f"上游失败被阻断（upstream_failed）：{upstream}"
                else:
                    msg = str(err.get("error") or err.get("message") or err or "编码失败")
                failed_repos.append(
                    {
                        "repository_id": repo_id,
                        "repository_name": repo_name,
                        "error": _truncate(msg, _MAX_ERROR_LENGTH),
                    }
                )

        log.info(
            "coding_wave_finalize",
            succeeded=len(succeeded),
            failed=len(failed_repos),
        )

        return await self._finalize_and_notify(
            context=context,
            succeeded=succeeded,
            failed_repos=failed_repos,
            completed_session_ids=completed_session_ids,
            branch_name=branch_name,
            base_branch=base_branch,
            plan_title=plan_title,
            plan_data=plan_data,
            log=log,
            session_repo_map=session_repo_map,
        )

    async def _finalize_and_notify(
        self,
        *,
        context: ExecutionContext,
        succeeded: list[dict[str, Any]],
        failed_repos: list[dict[str, Any]],
        completed_session_ids: list[str],
        branch_name: str,
        base_branch: str,
        plan_title: str,
        plan_data: dict[str, Any] | None,
        log: Any,
        session_repo_map: dict[str, str] | None = None,
    ) -> NodeResult:
        """收尾段（单 wave / wave 全终态共用，不造两套）：done 仓出 MR + 飞书卡片 + 构建输出。"""
        # 为成功仓库创建 MR
        mr_results: list[dict[str, Any]] = []
        if succeeded:
            from repositories.models import Repository

            for result in succeeded:
                repo_id = result["repository_id"]
                repo = await Repository.objects.filter(id=repo_id).afirst()
                if repo:
                    dispatch_user = await self._resolve_dispatch_user(context)
                    mr_result = await self._create_mr_for_repo(
                        repository=repo,
                        branch_name=branch_name,
                        base_branch=base_branch,
                        plan_title=plan_title,
                        tasks_completed=result.get("tasks_completed", []),
                        changes_summary=result.get("output", {}),
                        user=dispatch_user,
                    )
                    mr_results.append({**result, **mr_result})

        # PR-02：成功创建 MR 的仓 ≥ 2 时，对成功名单回写描述追加「## 关联 PR」cross-ref 段
        # （兄弟仓链接，排除自身）+「## 关联方案 / 工作项」追溯段。整段 fail-soft——回写在
        # 容器回调链路执行，任一异常仅 warning 降级、绝不上抛回灌 5xx（T-46-04，Pitfall 1）。
        successful_mrs = [r for r in mr_results if r.get("mr_url") and not r.get("error")]
        if len(successful_mrs) >= 2:
            try:
                from workflows.services.pr_cross_reference import add_cross_references

                await add_cross_references(
                    successful_mrs,
                    plan_version_id=(plan_data or {}).get("plan_version_id"),
                )
            except Exception as exc:  # noqa: BLE001 — cross-ref 增强 fail-soft
                log.warning("coding_cross_reference_failed", error=str(exc))

        # LINK-01（52-01，D-52-3）：spec↔实现 PR 回填。逐 successful_mr best-effort 调
        # SddSpecService.link_implementation_pr——SDD 仓回填 PR + 转 implemented，非 SDD
        # 仓 no-op（零回归）。整段 try/except 吞为 warning，绝不阻断 PR 创建/通知/节点完成
        # （镜像上方 cross-ref fail-soft 范式）。plan_version_id 缺失则跳过（与 cross-ref 同锚）。
        link_plan_version_id = (plan_data or {}).get("plan_version_id")
        if link_plan_version_id and successful_mrs:
            try:
                from delivery.services import SddSpecService  # lazy import 防循环

                spec_service = SddSpecService()
                for mr in successful_mrs:
                    await spec_service.link_implementation_pr(
                        artifact_version_id=link_plan_version_id,
                        repository_id=mr["repository_id"],
                        pr_url=mr["mr_url"],
                    )
            except Exception as exc:  # noqa: BLE001 — spec↔PR 回填 fail-soft
                log.warning("sdd_spec_pr_link_failed", error=str(exc))

        # INGEST-02（14-06）：MR 创建之后的完成锚点（时序防线：归档不挂容器回调）。
        # 先持久化后投递：mr_results 序列化写进 node_execution.output_data，task_result
        # normalizer 后台经 session.node_execution 重读（workflow 路径 mr_url 权威源）；
        # 持久化失败 warning 降级，不阻塞投递与节点完成。
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

        # LOOP-02/03（101-03）：完工闭环——MR 结果已知锚点的公共回写 + learning case
        # 提炼调度。整块 fail-soft（镜像上方 cross-ref 范式）：任何异常仅 warning
        # 降级，绝不影响 NodeResult / 节点收尾（STATE 约束：锚点不挂容器回调）。
        try:
            await self._run_completion_loop(
                context=context,
                mr_results=mr_results,
                failed_repos=failed_repos,
                completed_session_ids=completed_session_ids,
                branch_name=branch_name,
                base_branch=base_branch,
                plan_title=plan_title,
                plan_data=plan_data,
                session_repo_map=session_repo_map or {},
                log=log,
            )
        except Exception as exc:  # noqa: BLE001 — 完工闭环 fail-soft
            log.warning("coding_completion_loop_failed", error=str(exc))

        from workflows.models.execution import SubStepStatus

        await self.emit_sub_step(context, "create_mr", SubStepStatus.COMPLETED)

        # 发送飞书结果卡片（D1 解耦：可选回退——仅当显式配置了 chat_id 时推送；
        # 默认结果通知由下游 notify_feishu_im 节点承担，本节点不强依赖）。
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

    async def _run_completion_loop(
        self,
        *,
        context: ExecutionContext,
        mr_results: list[dict[str, Any]],
        failed_repos: list[dict[str, Any]],
        completed_session_ids: list[str],
        branch_name: str,
        plan_title: str,
        plan_data: dict[str, Any] | None,
        session_repo_map: dict[str, str],
        log: Any,
        base_branch: str = "",
    ) -> None:
        """完工闭环（LOOP-02/03/05）：三元组反查 → write_back 守门回写 → 提炼调度
        → 可选 PR review 沉淀调度。

        write_back 三态守门（P3 锁定，T-101-03-01）：
        - 键存在且 False → 完全跳过回写（用户显式关）；
        - 键存在且 True → 有三元组才回写，无三元组记 ``writeback_skipped``（caller）；
        - **键不存在（存量工作流）→ 有三元组才回写，无三元组静默跳过（debug 级，
          零行为变化——不产 warning/caller 事件）**。

        提炼调度与回写互不依赖：回写跳过不影响提炼（提炼有自己的 kill switch 与
        质量门）。经 ``run_in_background`` 后台线程 loop 调度、不 await Future——
        绝不阻塞节点收尾（T-101-03-03）。
        """
        # lazy import 防循环。
        from delivery.services.coding_completion import (
            CompletionWritebackService,
            RepoResult,
            WorkItemTriple,
            aresolve_triple_from_plan_version,
        )

        # 触发用户归因（T-101-03-04）：workflow 链用 triggered_by_id 标量。
        triggered_by: str | None = None
        if context.workflow_execution is not None and context.workflow_execution.triggered_by_id:
            triggered_by = str(context.workflow_execution.triggered_by_id)

        # 三元组反查：主链 plan_version 反查优先于 trigger fallback（T-101-03-02）。
        triple = await aresolve_triple_from_plan_version((plan_data or {}).get("plan_version_id"))
        if triple is None:
            project_key = context.get_trigger_data("feishu_project_key")
            raw_item_id = context.get_trigger_data("feishu_work_item_id")
            item_type = context.get_trigger_data("feishu_work_item_type")
            if project_key and raw_item_id and item_type:
                try:
                    item_id = int(raw_item_id)
                except (TypeError, ValueError):
                    item_id = None
                if item_id is not None:
                    triple = WorkItemTriple(
                        feishu_project_key=str(project_key),
                        work_item_type=str(item_type),
                        work_item_id=item_id,
                        title=plan_title,
                    )

        # 回写守门（三态）。
        raw_config = context.node_config or {}
        if "write_back" in raw_config:
            write_back_enabled = bool(raw_config.get("write_back"))
            if write_back_enabled and triple is None:
                log.info(
                    "writeback_skipped",
                    reason="no_work_item",
                    category="caller",
                    component="workflow",
                    initiated_by_user_id=triggered_by or "system",
                )
            do_write_back = write_back_enabled and triple is not None
        else:
            # legacy fallback（存量工作流缺键）：反查不到静默跳过——零行为变化。
            if triple is None:
                log.debug("writeback_skipped_legacy_no_binding")
            do_write_back = triple is not None

        if do_write_back and triple is not None:
            results = [
                RepoResult(
                    repo_name=str(r.get("repository_name") or ""),
                    status="failed" if r.get("error") else "completed",
                    branch_name=branch_name,
                    mr_url=str(r.get("mr_url") or ""),
                    error=str(r.get("error") or ""),
                )
                for r in mr_results
            ] + [
                RepoResult(
                    repo_name=str(r.get("repository_name") or ""),
                    status="failed",
                    error=str(r.get("error") or ""),
                )
                for r in failed_repos
            ]
            await CompletionWritebackService().awrite_back(
                feishu_project_key=triple.feishu_project_key,
                work_item_type=triple.work_item_type,
                work_item_id=triple.work_item_id,
                title=plan_title or triple.title,
                results=results,
                space_id=triple.space_id,
                initiated_by_user_id=triggered_by,
            )

        # 提炼调度（LOOP-03 锚点）：不 await Future，不阻塞节点收尾。
        if completed_session_ids:
            from mcp_tools.learning_case_extraction import (  # lazy import 防循环
                aextract_for_session,
            )
            from services.background_runner import run_in_background

            mr_url_by_repo = {
                str(r.get("repository_id") or ""): str(r.get("mr_url") or "") for r in mr_results
            }
            for sid in completed_session_ids:
                pr_url = mr_url_by_repo.get(session_repo_map.get(sid, ""), "")
                run_in_background(
                    lambda sid=sid, pr_url=pr_url: aextract_for_session(
                        sid,
                        requirement_text=plan_title,
                        work_item_type=triple.work_item_type if triple else "",
                        work_item_id=triple.work_item_id if triple else None,
                        pr_url=pr_url,
                        initiated_by_user_id=triggered_by,
                    ),
                    name=f"learning-case-{sid}",
                    initiated_by_user_id=triggered_by,
                )

        # PR review 沉淀调度（LOOP-05 锚点，101-04）：开关默认关——关闭时不调度
        # 后台任务（零 LLM 调用零后台成本；模块内开关/幂等还有兜底）。取不到对应
        # completed session 的仓跳过（无幂等键源）。同样不 await Future。
        successful_mrs = [r for r in mr_results if r.get("mr_url") and not r.get("error")]
        if successful_mrs:
            try:
                from system.models import SettingKeys
                from system.settings_service import aget_bool_setting

                review_enabled = await aget_bool_setting(
                    SettingKeys.PR_REVIEW_CAPTURE, default=False
                )
            except Exception:  # noqa: BLE001 — 开关读取失败视为关（fail-soft）
                review_enabled = False
            if review_enabled:
                from mcp_tools.pr_review_capture import acapture_pr_review  # lazy import
                from services.background_runner import run_in_background

                repo_session_map = {v: k for k, v in session_repo_map.items()}
                for mr in successful_mrs:
                    repo_id = str(mr.get("repository_id") or "")
                    sid = repo_session_map.get(repo_id, "")
                    if not sid:
                        continue
                    mr_url = str(mr.get("mr_url") or "")
                    run_in_background(
                        lambda repo_id=repo_id, sid=sid, mr_url=mr_url: acapture_pr_review(
                            repository_id=repo_id,
                            source_branch=branch_name,
                            target_branch=base_branch,
                            pr_url=mr_url,
                            session_id=sid,
                            requirement_text=plan_title,
                            work_item_type=triple.work_item_type if triple else "",
                            work_item_id=triple.work_item_id if triple else None,
                            initiated_by_user_id=triggered_by,
                        ),
                        name=f"pr-review-{sid}",
                        initiated_by_user_id=triggered_by,
                    )

    # ------------------------------------------------------------------
    # 方案解析
    # ------------------------------------------------------------------

    def _extract_plan_data(self, context: ExecutionContext) -> dict[str, Any] | None:
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

    async def _fetch_repositories(self, repo_ids: set[str]) -> dict[str, Repository]:
        """批量获取仓库对象。"""
        return {
            str(r.id): r async for r in Repository.objects.filter(id__in=repo_ids, is_deleted=False)
        }

    # ------------------------------------------------------------------
    # 分支名解析
    # ------------------------------------------------------------------

    def _resolve_branch_name(self, plan_data: dict[str, Any], context: ExecutionContext) -> str:
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

                    we = await WorkflowExecution.objects.select_related("workflow__space").aget(
                        id=context.workflow_execution.id
                    )
                    project = we.workflow.space if we.workflow else None

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

    async def _resolve_dispatch_user(self, context: ExecutionContext):
        """解析派发发起用户（Phase 103 AGENT-01，替换机会性 PAT 透传）。

        读 ``context.workflow_execution.triggered_by_id``（先例：triggers/manual.py
        的 executor 解析；fields_cache 已缓存 triggered_by 时直用，否则按 id 反查）。
        有 user 就 mint 任务级短 TTL token（``_run_repo_coding`` 内），不再依赖
        请求头明文 ContextVar 透传——PAT-02 底线不变：mint 是新签发，明文仅内存
        直进容器 env，绝不从 AccessToken/DB 反取明文。

        返回 None（背景/无触发用户）→ 下游省略 env_FRIDAY_TASK_USER_TOKEN，
        task 侧不挂知识 MCP server（降级不挂，向后兼容）。
        """
        execution = context.workflow_execution
        if execution is None:
            return None
        triggered_by_id = getattr(execution, "triggered_by_id", None)
        if not triggered_by_id:
            return None
        cached_user = execution._state.fields_cache.get("triggered_by")
        if cached_user is not None:
            return cached_user
        from django.contrib.auth import get_user_model

        return await get_user_model().objects.filter(pk=triggered_by_id).afirst()

    async def _run_repo_coding(
        self,
        repository: Repository,
        tasks: list[dict[str, Any]],
        branch_name: str,
        base_branch: str,
        global_context: str,
        config: dict[str, Any],
        node_execution_id: str = "",
        anthropic_api_key: str = "",  # work item W-1：Task 2 前置签名扩展；Task 3 在 metadata 中消费
        anthropic_base_url: str = "",  # work item W-1：Task 2 前置签名扩展；Task 3 在 metadata 中消费
        dispatch_user=None,  # Phase 103 AGENT-01：发起用户（User | None）——非 None 时 mint 任务级短 TTL token（替换机会性 PAT 透传）
        project_context: str = "",  # Phase 103 AGENT-04：wave 层解析的项目上下文（默认空 → 非 wave/legacy 调用路径零回归）
        upstream_artifacts: list[dict]
        | None = None,  # ARTIFACT-02：上游产物注入（默认 None → 零回归）
        follow_openspec: bool = False,  # GATE-02：approved SDD 仓注入 openspec env（默认 False 保非 wave/legacy 零回归）
    ) -> dict[str, Any]:
        """通过 TaskDispatcher 分发编码任务到 Runner。"""
        log = logger.bind(
            repository_id=str(repository.id),
            repository_name=repository.name,
        )

        prompt = self._build_coding_prompt(
            tasks,
            global_context,
            branch_name,
            upstream_artifacts=upstream_artifacts,
            repository_id=str(repository.id),
        )

        # Phase 103 AGENT-04：项目上下文注入（镜像 chat dispatch_coding_task 两件套——
        # prompt prepend + env_FRIDAY_TASK_PROJECT_CONTEXT）。空 → 与现状逐字一致。
        context_env: dict[str, str] = {}
        if project_context:
            from services.project_context_packer import prepend_project_context

            prompt = prepend_project_context(prompt, project_context)
            context_env["env_FRIDAY_TASK_PROJECT_CONTEXT"] = project_context

        from runners.dispatcher import DispatchTask, get_dispatcher
        from subagent.models import SubAgentSession, generate_execution_id

        session_id = generate_execution_id()

        # Git 凭证（Phase 26 REPO-01：统一经解析器取 token，无 per-repo token 时按 host 用实例凭证）
        # token 非空才注入 access_token（与既有「无凭证」行为一致，绝不 log token）。
        # WR-01：ssl_verify 逐键对齐 chat 权威基线 build_dispatch_metadata
        # （coding_session_service.py:175，token 认证恒 "false"）。绝不访问 repository.credential
        # —— 它是 GitCredential 的反向 OneToOne，生产异步路径未 select_related 会触发
        # SynchronousOnlyOperation，且 GitCredential 模型本就无 ssl_verify 字段（AttributeError）。
        git_credentials = {}
        token = await aresolve_git_token(repository)
        if token:
            git_credentials = {
                "access_token": token,
                "ssl_verify": "false",
            }

        # PF-06：逐键对齐 chat 路径 build_dispatch_metadata（coding_session_service.py:170-187）。
        # 既有 nested git_credentials dict 被 runner 忽略（只 TrimPrefix 顶层 env_ string 键，见
        # runner/internal/docker/executor.go），故必须额外注入顶层 env_FRIDAY_TASK_GIT_* 键，
        # 否则私有仓 clone 走默认（无 token）失败。nested dict 原样保留以零回归。
        repo_url = repository.git_url
        git_env: dict[str, str] = {}
        if token:
            git_env["env_FRIDAY_TASK_GIT_ACCESS_TOKEN"] = token
            git_env["env_FRIDAY_TASK_GIT_AUTH_TYPE"] = "token"
            # 对齐 chat 权威基线硬编码 "false"（Open Q1 RESOLVED）；runner 仅透传非空 string。
            git_env["env_FRIDAY_TASK_GIT_SSL_VERIFY"] = "false"
            # SSH URL -> HTTPS（token 认证需要 HTTPS）；正则锚定 git@host:path 无注入面。
            if repo_url.startswith("git@"):
                m = re.match(r"git@([^:]+):(.+?)(?:\.git)?$", repo_url)
                if m:
                    repo_url = f"https://{m.group(1)}/{m.group(2)}.git"

        # 分支 env（多仓 per-repo）：BRANCH_STRATEGY=本次调用的工作分支、TARGET_BRANCH=base 分支。
        # 无条件注入——容器侧 branch_strategy 为空会回退默认 friday/task-{id}（PF-06 落默认分支根因）。
        branch_env: dict[str, str] = {
            "env_FRIDAY_TASK_BRANCH_STRATEGY": branch_name,
            "env_FRIDAY_TASK_TARGET_BRANCH": base_branch,
            # Phase 124 DIFF-03：权威仓库 UUID 进容器，供 detect_changes 自查指引内联。
            "env_FRIDAY_TASK_REPOSITORY_ID": str(repository.id),
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

        # RTOOL-03 + Phase 103 AGENT-01/02：RemoteTool / 知识 MCP 链路注入。
        #   - tools endpoint 强制由 settings.FRIDAY_BASE_URL 推导（拼 /api/tools/execute/），
        #     绝不用 runner callback_url（Pitfall 1：错用会打到 runner 中转 → 工具调用 404）。
        #     契约：空 base_url 不注入该键（向后兼容降级——task 侧无 endpoint → 不挂 MCP server）。
        #   - 任务级短 TTL token（替换机会性 PAT 透传）：dispatch_user 非 None 时经
        #     mint_task_token 新签发并注入 env_FRIDAY_TASK_USER_TOKEN；明文仅本函数
        #     内存直进 env，绝不落盘/进日志（PAT-02 底线不变——mint 是新签发，非 DB 反取）。
        #     None → 不注入该键（降级不挂，不阻塞 dispatch）。
        #   - 知识端点（AGENT-02 服务端注入面）：base 不带路径（task 侧自行拼
        #     /api/mcp/tools/{name}/），空 FRIDAY_BASE_URL 不注入。
        from django.conf import settings

        tools_env: dict[str, str] = {}
        base = getattr(settings, "FRIDAY_BASE_URL", "").rstrip("/")
        if base:
            tools_env["env_FRIDAY_TASK_TOOLS_ENDPOINT"] = f"{base}/api/tools/execute/"
            tools_env["env_FRIDAY_TASK_KNOWLEDGE_ENDPOINT"] = base
        if dispatch_user is not None:
            from access_tokens.services import mint_task_token

            # session_id 即本函数生成的 execution id（与预建 SubAgentSession.session_id
            # 一致），终态吊销按此定位。
            plaintext = await mint_task_token(
                dispatch_user, session_id, config.get("timeout_seconds", 1800)
            )
            tools_env["env_FRIDAY_TASK_USER_TOKEN"] = plaintext
            # 31u：**非敏感**发起用户 id 随派发快照落库（不是凭证）。派发经 durable 队列后
            # 任务体只按 redacted 快照重建，rehydrate 据此键重铸 USER_TOKEN——不落则
            # workflow 编码容器首派就挂不上知识工具（回归）。
            tools_env["task_token_user_id"] = str(dispatch_user.id)

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

        # GATE-02（D-51-4）：approved SDD 仓注入 openspec 布尔信号（对齐 PF-06 逐键 env 范式，
        # 不改既有键）；follow_openspec=False / legacy 仓不含该键 → 与 v0.8 metadata 逐字一致（零回归）。
        openspec_env: dict[str, str] = {}
        if follow_openspec:
            openspec_env["env_FRIDAY_TASK_FOLLOW_OPENSPEC"] = "true"

        dispatch_task = DispatchTask(
            task_id=session_id,
            task_type="coding",
            tags=["coding"],
            # 固定使用 runner 配置的默认 task 镜像（FRIDAY_RUNNER_IMAGE / FRIDAY_TASK_IMAGE）；
            # 不再支持节点级镜像覆盖。空字符串 → runner 回退到部署配置的默认镜像。
            image="",
            repo_url=repo_url,  # PF-06：SSH→HTTPS 改写后（token 认证需 HTTPS），不再直传 repository.git_url
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
                **git_env,  # PF-06：env_FRIDAY_TASK_GIT_ACCESS_TOKEN/AUTH_TYPE/SSL_VERIFY（token 非空时）
                **branch_env,  # PF-06：env_FRIDAY_TASK_BRANCH_STRATEGY/TARGET_BRANCH（多仓 per-repo）
                **anthropic_env,  # env_FRIDAY_TASK_CLAUDE_API_KEY + env_FRIDAY_TASK_CLAUDE_BASE_URL
                **tools_env,  # RTOOL-03 + Phase 103：TOOLS/KNOWLEDGE_ENDPOINT + 任务级 env_FRIDAY_TASK_USER_TOKEN
                **exclude_env,  # Phase 22-04：env_FRIDAY_TASK_EXCLUDE_PATTERNS（容器侧 prune）
                **openspec_env,  # Phase 51 GATE-02：env_FRIDAY_TASK_FOLLOW_OPENSPEC（仅 approved SDD 仓）
                **context_env,  # Phase 103 AGENT-04：env_FRIDAY_TASK_PROJECT_CONTEXT（wave 层解析逐仓复用）
            },
        )

        # 预创建 SubAgentSession（PENDING 状态）
        async def _create_session() -> None:
            from agents.models import AgentSession

            # 查找关联的 main_session
            main_session = None
            if node_execution_id:
                from workflows.models import NodeExecution

                node_exec = (
                    await NodeExecution.objects.filter(
                        id=node_execution_id,
                    )
                    .select_related("workflow_execution")
                    .afirst()
                )
                if node_exec and node_exec.workflow_execution:
                    main_session = await AgentSession.objects.filter(
                        metadata__workflow_execution_id=str(node_exec.workflow_execution.id),
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
                has_git_token=bool(token),
                has_tools_endpoint=bool(base),
                has_user_token=dispatch_user is not None,
            )
        except Exception as e:
            log.error("task_dispatch_failed", error=str(e))
            # IN-01（103 审查）：dispatch 失败无终态回调兜底吊销 → best-effort 立即
            # 吊销已铸任务 token（arevoke_task_tokens 自身吞异常不反噬主流程）。
            if dispatch_user is not None:
                from access_tokens.services import arevoke_task_tokens

                await arevoke_task_tokens(session_id)
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
        upstream_artifacts: list[dict] | None = None,
        repository_id: str = "",
    ) -> str:
        """构建 SubAgent 编码 prompt。

        合并该仓库所有任务的编码指令。``upstream_artifacts`` 为 ARTIFACT-02 上游产物注入
        （默认 None → 首发 wave 0 / 无上游 → 注入段不渲染 → 与 Phase 44 现行为逐字一致，
        零回归命门）。``repository_id`` 为 Friday 仓 UUID（Phase 124 DIFF-03），供
        detect_changes 自查；默认空 → 分支段与现状逐字一致。
        """
        from services.process_runtime.artifact_injection import (
            render_upstream_artifacts_section,
        )

        parts: list[str] = []

        if global_context:
            parts.append(f"# 项目背景\n\n{global_context}")

        # ── ARTIFACT-02：上游产物段（D-08：global_context 之后、分支信息之前）──
        # 空段（无上游 / 空产物）→ render 返回 "" → 守卫不 append（逐字对齐既有
        # `if files_section:`，绝不让空段进 parts 否则多一个 "\n\n---\n\n" 分隔，零回归）。
        upstream_section = render_upstream_artifacts_section(upstream_artifacts or [])
        if upstream_section:
            parts.append(upstream_section)

        branch_lines = [f"目标分支: `{branch_name}`"]
        rid = (repository_id or "").strip()
        if rid:
            branch_lines.append(f"仓库 ID: `{rid}`")
        parts.append("# 分支信息\n\n" + "\n".join(branch_lines))

        # 编码指令
        if len(tasks) == 1:
            task = tasks[0]
            task_name = task.get("name", "编码任务")
            instruction = task.get("coding_instruction", "") or task.get("description", "")
            parts.append(f"# 编码任务: {task_name}\n\n{instruction}")
        else:
            instructions: list[str] = []
            for i, task in enumerate(tasks, 1):
                task_name = task.get("name", f"任务 {i}")
                instruction = task.get("coding_instruction", "") or task.get("description", "")
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
        user: Any | None = None,
    ) -> dict[str, Any]:
        """为单个仓库创建 MR。

        复用 CreatePRNode._create_pr_for_repository 的模式。
        """
        log = logger.bind(
            repository_id=str(repository.id),
            repository_name=repository.name,
        )

        # Phase 26 REPO-01：统一经解析器取 token（per-repo 优先 → 同 host 实例凭证池 fallback）
        token = await aresolve_git_token(repository)
        if not token:
            log.warning("mr_creation_no_credential")
            return {
                "mr_url": "",
                "mr_id": "",
                "has_conflicts": False,
                "error": "仓库未配置访问凭证",
            }

        client = get_git_platform_client(repository, token)

        # 构建 MR 描述
        task_checklist = "\n".join(f"- [x] {name}" for name in tasks_completed if name)
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

        # PR-01：各仓 target_branch 优先用各仓自己的 default_branch，base_branch 降为
        # node 级兜底（对齐 mr_service.create_mr_for_task 范式，per D-01）。
        resolved_target = repository.default_branch or base_branch or "main"

        # Phase 124 DIFF-04：fail-soft 影响面段（与 pr_cross_reference 同姿态；D-06/D-09）
        try:
            from services.code_graph.impact_report import (
                append_impact_report,
                build_impact_report_section,
            )

            section = await build_impact_report_section(
                repository=repository,
                user=user,
                compare=branch_name,
                base_ref=resolved_target,
            )
            body = append_impact_report(body, section)
        except Exception as exc:  # noqa: BLE001 — 最后兜底；helper 内应已吞
            try:
                logger.warning(
                    "impact_report_shell_failed",
                    component="workflows",
                    category="caller",
                    repository_id=str(getattr(repository, "id", "") or ""),
                    error=str(exc)[:200],
                )
            except Exception:  # noqa: BLE001 — 观测永不反噬
                pass

        # Phase 127 TAINT-02：fail-soft 安全扫描 pending stub（异步回填；D-04/D-06）
        # enqueue 放在建 MR 成功后（mr_key=平台 MR id）；此处仅挂 stub。
        try:
            from services.code_graph.security_scan_report import (
                append_security_scan,  # noqa: F401 — D-06 dual-link 合同字面量
                attach_security_scan_pending,
            )

            body = await attach_security_scan_pending(
                body,
                repository=repository,
                source_branch=branch_name,
                target_branch=resolved_target,
                user=user,
                mr_key=branch_name,
                enqueue=False,
            )
        except Exception as exc:  # noqa: BLE001 — 最后兜底；helper 内应已吞
            try:
                logger.warning(
                    "security_scan_shell_failed",
                    component="workflows",
                    category="caller",
                    repository_id=str(getattr(repository, "id", "") or ""),
                    error=str(exc)[:200],
                )
            except Exception:  # noqa: BLE001 — 观测永不反噬
                pass

        request = MRCreateRequest(
            source_branch=branch_name,
            target_branch=resolved_target,
            title=plan_title,
            description=body,
            reviewer_usernames=[],
        )

        # IDEMP-02：创建前查同 source→target 的 open MR/PR，命中则复用不重复创建。
        # 查重失败不能当「无命中」继续创建——那正是重复 MR 的来源。显式失败交给
        # 重试兜底：重试时查重恢复就会命中既有 MR，不会留下重复件。
        try:
            existing = await client.find_open_merge_request(branch_name, resolved_target)
        except MergeRequestLookupFailed as e:
            log.warning("mr_dedup_lookup_failed", error=str(e))
            return {
                "mr_url": "",
                "mr_id": "",
                "has_conflicts": False,
                "error": f"MR 去重查询失败，为避免重复创建已中止（可重试）: {e}",
            }
        if existing and existing.success:
            log.info(
                "mr_dedup_reuse_existing",
                mr_url=existing.mr_url,
                mr_id=existing.mr_id,
            )
            # 复用既有 MR 时仍 fire-and-forget 入队扫描（D-04）
            try:
                from services.code_graph.semgrep_enqueue import enqueue_semgrep_scan

                initiated_by = (
                    str(user.id)
                    if user is not None and getattr(user, "id", None) is not None
                    else "system"
                )
                await enqueue_semgrep_scan(
                    str(getattr(repository, "id", "") or ""),
                    mr_key=str(existing.mr_id or branch_name),
                    source_sha="",
                    target_sha="",
                    branch_name=branch_name,
                    initiated_by_user_id=initiated_by,
                )
            except Exception:  # noqa: BLE001 — enqueue 失败不反噬复用路径
                pass
            return {
                "mr_url": existing.mr_url,
                "mr_id": existing.mr_id,
                "has_conflicts": False,
                # PR-02：保留 body 供 cross-ref 回写拼接；deduplicated 标记复用路径。
                "description": body,
                "deduplicated": True,
            }

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
            # Phase 127：建 MR 成功后再 enqueue（mr_key=平台 MR id；D-04 stub-then-async）
            try:
                from services.code_graph.semgrep_enqueue import enqueue_semgrep_scan

                initiated_by = (
                    str(user.id)
                    if user is not None and getattr(user, "id", None) is not None
                    else "system"
                )
                await enqueue_semgrep_scan(
                    str(getattr(repository, "id", "") or ""),
                    mr_key=str(result.mr_id or ""),
                    source_sha="",
                    target_sha="",
                    branch_name=branch_name,
                    initiated_by_user_id=initiated_by,
                )
            except Exception as exc:  # noqa: BLE001 — enqueue 失败不反噬已建 MR
                try:
                    logger.warning(
                        "security_scan_shell_failed",
                        component="workflows",
                        category="caller",
                        repository_id=str(getattr(repository, "id", "") or ""),
                        error=str(exc)[:200],
                    )
                except Exception:  # noqa: BLE001
                    pass
            return {
                "mr_url": result.mr_url,
                "mr_id": result.mr_id,
                "has_conflicts": result.has_conflicts,
                # PR-02：保留原 body 供 cross-ref 回写时拼接（追加兄弟链接 + 追溯段）。
                "description": body,
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
        """发送飞书编码结果卡片（D1 解耦后为可选回退）。

        结果通知的主路径是下游 `notify_feishu_im` 节点；本方法仅在节点显式配置了
        `chat_id` 时作为回退推送，留空（默认）即跳过——不再是编码节点的硬依赖。
        """
        chat_id = context.get_config("chat_id", "")
        if not chat_id:
            # 默认路径：不推送（由下游 notify_feishu_im 承担），非错误。
            log.debug("result_notification_skipped_decoupled")
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

            we = await WE2.objects.select_related("workflow__space").aget(
                id=context.workflow_execution.id
            )
            project = we.workflow.space if we.workflow else None

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
