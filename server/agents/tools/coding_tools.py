"""编码会话工具 — create_coding_plan / update_coding_plan @tool。

工具落库切换到 `CodingPlan` 独立领域；返回 payload 同时携带
`coding_plan_id` 和 `coding_session_id`（兼容期保留旧 `session_id` alias）。

**SPINE-02（Phase 109）**：两个工具的**创作半边已在 schema 层砍掉** —— 入参不再有
`tech_plan` / `affected_files`，模型在结构上无法只凭对话提交方案正文。正文只能来自
完整编排链路产出的 `ArtifactVersion`，经 `chat.plan_projection_service` 这个唯一写
入口投影/re-bind 进来。执行半边（推荐仓库解析、返回 payload 键形）原样保留。

守护见 `tests/agents/test_coding_tools_schema_guard.py`（正向不变量 + 键集合枚举）。
"""

from __future__ import annotations

import structlog

from agents.tools.base import ToolResult, tool

logger = structlog.get_logger(__name__)

# 无来源 / 越权的创作尝试留痕事件（CONTEXT「schema 层移除后的调用尝试需留痕」）。
_AUTHORING_REJECTED_EVENT = "coding_plan_authoring_attempt_rejected"


def _log_authoring_rejected(*, conversation_id: str, reason: str) -> None:
    """记录一次被拒绝的创作/投影尝试（best-effort，绝不反噬业务）。

    ``reason`` 可能来自异常文本 ⇒ 先过 ``redact_secrets_in_text`` 再落日志。
    """
    try:
        from common.logging import redact_secrets_in_text

        logger.warning(
            _AUTHORING_REJECTED_EVENT,
            category="caller",
            component="agents",
            conversation_id=conversation_id or "",
            reason=redact_secrets_in_text(reason),
        )
    except Exception:  # noqa: BLE001 — 观测 best-effort，绝不反噬业务
        pass


def _context_user_id() -> str:
    """从请求 / 任务上下文取权威触发用户 id；取不到返回空串。

    来源是 `common.log_context` 在 DRF 认证后**由服务端**写入的 contextvars，
    模型不可控。``"system"`` 占位视同取不到 —— 归属判定绝不接受哨兵身份放行。
    """
    try:
        raw = str(structlog.contextvars.get_contextvars().get("user_id") or "").strip()
    except Exception:  # noqa: BLE001 — 取上下文绝不反噬业务
        return ""
    return "" if raw in ("", "system") else raw


@tool(
    name="create_coding_plan",
    description=(
        "把**已由编排链路产出**的技术方案版本投影为可执行的编码方案。"
        "本工具不接受方案正文 —— 正文只能来自完整编排链路"
        "（`start_plan_research` / `start_feature_solution` / 工作流方案节点）"
        "产出的方案版本。若尚无方案版本，先调 `start_plan_research` 发起编排。"
        "\n\n"
        "**coding-plan workflow**：本工具只产 CodingPlan 与推荐仓库列表，"
        "不再创建 CodingSession。session 由前端在 UI 选定仓库后通过 fan-out "
        "endpoint `POST /api/chat/coding-plans/{plan_id}/sessions/` 创建。"
        "\n\n"
        "**implementation**：可选传 `recommended_repository_ids` 预填本方案"
        "在 fan-out 时建议的相关仓库列表。不传时 Server 端自动从 conversation 最近一条"
        "RepositoryRoutingTrace 取 `selected_by_user_final=True` 的仓库（来自之前的"
        "analyze_repository_relevance 工具调用 / deep_analysis cross_repo_relevance）。"
    ),
    category="PROJECT",
    parameters={
        "type": "object",
        "properties": {
            "space_id": {
                "type": "string",
                "description": "空间 UUID (auto-injected)",
            },
            "conversation_id": {
                "type": "string",
                "description": "会话 UUID (auto-injected)",
            },
            "repository_id": {
                "type": "string",
                "description": (
                    "可选；当 LLM 已经明确锁定主仓库时填入。"
                    "传入将被合并进 recommended_repository_ids（置顶），"
                    "不再用于创建 CodingSession（coding-plan workflow）。"
                ),
            },
            "artifact_version_id": {
                "type": "string",
                "description": (
                    "编排产出的方案版本 UUID（`start_plan_research` / "
                    "`start_feature_solution` 的返回值）。方案正文只能来自该版本，"
                    "本工具不接受任何形式的正文入参。"
                ),
            },
            "recommended_repository_ids": {
                "type": "array",
                "items": {"type": "string", "format": "uuid"},
                "description": (
                    "implementation：AI 已经识别相关的仓库 UUID 列表"
                    "（来自 analyze_repository_relevance / deep_analysis"
                    "cross_repo_relevance metadata）。不传则 Server 自动从"
                    "conversation 最近一条 RepositoryRoutingTrace 推断"
                    "（取 selected_by_user_final=True 的仓库）。"
                ),
            },
        },
        "required": [
            "space_id",
            "conversation_id",
            "artifact_version_id",
        ],
    },
)
async def create_coding_plan(
    space_id: str,
    conversation_id: str,
    artifact_version_id: str,
    repository_id: str = "",
    recommended_repository_ids: list[str] | None = None,
) -> ToolResult:
    """把编排产出的方案版本投影为 CodingPlan（SPINE-02 收窄后的执行半边）。

    落库统一走 ``chat.plan_projection_service.PlanProjectionService`` —— 工具与
    HTTP 投影端点共用**同一个写入口**，因此也共享 service 内的归属判定
    （``artifact_version_forbidden``）。本工具**不再**调
    ``CodingPlan.aget_or_create_for_conversation``。

    本工具不创建 CodingSession：session 由前端在 UI 选定仓库后通过
    ``POST /api/chat/coding-plans/{plan_id}/sessions/`` (fan-out endpoint)
    创建，是 coding-plan workflow fan-out 设计的唯一 session 创建源。

    ``recommended_repository_ids`` 可选 ——

    - LLM 显式传：校验全部属于该 space + 未软删 → 覆盖写入
      CodingPlan.recommended_repository_ids。
    - LLM 不传：Server 自动从 conversation 最近一条 RepositoryRoutingTrace
      取 ``selected_by_user_final=True`` 的 repository_id 列表（含 manual
      override 覆盖；按 created_at desc 自然拿到「用户最新意图」）。
    - 都无：**保留**投影从 ``execution_plan[].repository_id`` 聚合出的值，不用空
      列表清空它 —— 编排来源本身就带目标仓，空列表覆盖等于把 fan-out 目标抹掉。

    ``repository_id`` 可选：传入时校验属于 space，并被合并进
    ``recommended_repository_ids`` 列表（置顶）。**不再用于创建 session。**
    """
    from chat.models import Conversation, RepositoryRoutingTrace
    from chat.plan_projection_service import (
        PlanProjectionError,
        PlanProjectionService,
        filter_valid_uuids,
    )
    from projects.models import Space
    from repositories.models import Repository

    logger.info(
        "create_coding_plan_requested",
        space_id=space_id,
        repository_id=repository_id or None,
        artifact_version_id=artifact_version_id or None,
    )

    if not str(artifact_version_id or "").strip():
        _log_authoring_rejected(
            conversation_id=conversation_id,
            reason="missing_artifact_version_id",
        )
        return ToolResult(
            success=False,
            error=(
                "缺少 artifact_version_id：编码方案的正文只能来自编排链路产出的方案版本。"
                "请先调用 start_plan_research 发起编排，拿到方案版本后再调用本工具。"
            ),
        )

    try:
        project = await Space.objects.aget(id=space_id)
    except Space.DoesNotExist:
        return ToolResult(
            success=False,
            error=f"Space not found: {space_id}",
        )

    # repository_id 可选：传入则校验属于 space，仅作为推荐仓库 hint 合并
    primary_repo: Repository | None = None
    if repository_id:
        try:
            primary_repo = await Repository.objects.aget(id=repository_id)
        except Repository.DoesNotExist:
            return ToolResult(
                success=False,
                error=f"Repository not found: {repository_id}",
            )
        repo_in_project = await project.repositories.filter(id=repository_id).aexists()
        if not repo_in_project:
            return ToolResult(
                success=False,
                error=(f"Repository {repository_id} does not belong to space {space_id}"),
            )

    try:
        conversation = await Conversation.objects.aget(id=conversation_id)
    except Conversation.DoesNotExist:
        return ToolResult(
            success=False,
            error=f"Conversation not found: {conversation_id}",
        )

    # 归属主体：① 请求上下文（中间件在 DRF 认证后权威写入）；② 退回服务端**注入**的
    # conversation 的创建者 —— chat_runner 把 conversation_id 从模型可见入参里剔除后
    # 闭包注入，模型改不了它，且 chat SSE 入口本身有 owner gate。两个来源都是真实身份，
    # 不是哨兵；两者都取不到时**拒绝**（绝不退化为 "system" 放行）。
    actor_user_id = _context_user_id() or str(conversation.created_by_id or "")
    if not actor_user_id:
        _log_authoring_rejected(
            conversation_id=conversation_id,
            reason="actor_user_unresolved",
        )
        return ToolResult(
            success=False,
            error="无法确定当前操作用户，拒绝投影编码方案。",
        )

    # 解析 recommended_repository_ids（显式 / trace 推断 / 空）
    recommended_source: str
    final_recommended: list[str] = []
    recommended_repositories: list[dict[str, str]] = []
    if recommended_repository_ids:
        valid_repos = [
            r
            async for r in Repository.objects.filter(
                id__in=recommended_repository_ids,
                spaces=project,
                is_deleted=False,
            )
        ]
        valid_ids = [str(r.id) for r in valid_repos]
        invalid = set(map(str, recommended_repository_ids)) - set(valid_ids)
        if invalid:
            return ToolResult(
                success=False,
                error=(
                    f"recommended_repository_ids contains repos not in space "
                    f"{space_id}: {sorted(invalid)}"
                ),
            )
        final_recommended = valid_ids
        recommended_repositories = [{"id": str(r.id), "name": r.name} for r in valid_repos]
        recommended_source = "explicit"
    else:
        latest_trace = (
            await RepositoryRoutingTrace.objects.filter(
                conversation_id=conversation_id,
            )
            .order_by("-created_at")
            .afirst()
        )
        if latest_trace is None:
            final_recommended = []
            recommended_source = "empty"
        else:
            final_recommended = [
                c["repository_id"]
                for c in (latest_trace.candidates or [])
                if c.get("selected_by_user_final")
            ]
            recommended_repositories = [
                {
                    "id": str(c.get("repository_id", "")),
                    "name": str(c.get("repository_name", "")),
                }
                for c in (latest_trace.candidates or [])
                if c.get("selected_by_user_final")
            ]
            recommended_source = "trace_inferred"

    # workflow update：repository_id 显式传入时合并到 recommended（置顶）
    if primary_repo is not None:
        primary_id = str(primary_repo.id)
        if primary_id not in final_recommended:
            final_recommended = [primary_id, *final_recommended]
            recommended_repositories = [
                {"id": primary_id, "name": primary_repo.name},
                *recommended_repositories,
            ]
            if recommended_source == "empty":
                recommended_source = "primary_repo"

    # 落库走投影 service（与 HTTP 端点共用的唯一写入口 + 同一道归属判定）。
    try:
        plan, plan_created = await PlanProjectionService().aproject(
            artifact_version_id=str(artifact_version_id).strip(),
            actor_user_id=actor_user_id,
        )
    except PlanProjectionError as exc:
        _log_authoring_rejected(conversation_id=conversation_id, reason=exc.code)
        # error 只回显机器码与固定引导语，**绝不**回显他人方案正文的任何片段。
        return ToolResult(
            success=False,
            error=(
                f"无法从方案版本 {artifact_version_id} 投影编码方案（{exc.code}）。"
                "请确认该方案版本由当前会话的编排链路产出。"
            ),
        )

    # 把推荐仓库列表写入 plan（覆盖既有值 —— 同 plan 多次调用以最新一次为准）。
    # 取舍：解析结果为空时**保留**投影从 execution_plan[].repository_id 聚合的值，
    # 不用空列表清空 —— 编排来源自带目标仓，清空等于把 fan-out 目标抹掉。
    if final_recommended:
        if list(plan.recommended_repository_ids or []) != final_recommended:
            plan.recommended_repository_ids = final_recommended
            await plan.asave(update_fields=["recommended_repository_ids", "updated_at"])
    else:
        # 半可信来源的 id 过筛与投影端点共用同一道筛子（各写一份必然漂移）。
        projected_ids = filter_valid_uuids(plan.recommended_repository_ids)
        if projected_ids:
            final_recommended = projected_ids
            # 按 space 过滤，与上方「LLM 显式传 id」分支同一口径 —— 两条分支的可见性
            # 口径不一致，日后很容易被当成「这里不需要过滤」的先例。
            # 只影响**名字回显**：final_recommended 保留全部合法 id（编排来源自带目标
            # 仓，用 space 交集覆盖等于把跨 space 的 fan-out 目标抹掉）。
            recommended_repositories = [
                {"id": str(r.id), "name": r.name}
                async for r in project.repositories.filter(id__in=projected_ids)
            ]
            recommended_source = "projected"

    # Chassis v2 · P2：移除 chat→delivery TechnicalPlan eager 投影（canonical_plan_id 软链
    # 与 delivery TechnicalPlanService 已删除；技术方案产物统一走 ConvergenceSession +
    # ArtifactService，chat CodingPlan 不再耦合 delivery 产物脊柱）。

    logger.info(
        "create_coding_plan_completed",
        coding_plan_id=str(plan.id),
        created=plan_created,
        recommended_count=len(final_recommended),
        recommended_source=recommended_source,
    )

    return ToolResult(
        success=True,
        output={
            "coding_plan_id": str(plan.id),
            # workflow update：工具不再产 session；保留 key 为 None 避免下游 KeyError
            "coding_session_id": None,
            "session_id": None,
            "repository_id": str(primary_repo.id) if primary_repo else "",
            "repository_name": primary_repo.name if primary_repo else "",
            "status": "plan_only",
            "branch_name": "",
            "recommended_repository_ids": final_recommended,
            "recommended_repositories": recommended_repositories,
            "recommended_source": recommended_source,
            # 109-REVIEW HI-02：正文与来源标志随工具结果一起给全。
            # SPINE-02 收窄 schema 后 tool input 里已无 tech_plan，前端方案卡只剩
            # `runtime.coding_plan` 一条来源，而它的语义是「对话内**最近**一条
            # CodingPlan」⇒ 会话里一旦有第二份方案，第一张卡就同时丢正文（显示
            # 「（暂无方案正文）」）和 provenance（落保守分支、被误挂「未经代码调研」）。
            # 三者都已在手（plan 就是投影返回的实例），零额外查询。
            "tech_plan": plan.tech_plan or "",
            "affected_files": list(plan.affected_files or []),
            "provenance": plan.provenance,
            "message": (
                f"编排方案已投影为编码方案，plan_id={plan.id}。请在 UI 选择目标仓库后开始编码。"
            ),
        },
    )


@tool(
    name="update_coding_plan",
    description=(
        "把既有编码方案**重新指向一个新的编排方案版本**（re-bind）。"
        "本工具不接受方案正文 —— 新正文由指定的方案版本渲染而来，"
        "模型无法通过本工具改写任意内容。"
        "若需要一份新方案，先调 `start_plan_research` / `start_feature_solution` "
        "走完整编排链路产出新的方案版本，再用本工具切换指向。"
    ),
    category="PROJECT",
    parameters={
        "type": "object",
        "properties": {
            "conversation_id": {
                "type": "string",
                "description": "会话 UUID (auto-injected)",
            },
            "coding_plan_id": {
                "type": "string",
                "description": "CodingPlan UUID（coding-plan workflow 起首选）",
            },
            "session_id": {
                "type": "string",
                "description": "CodingSession UUID（legacy 兼容路径，已 deprecated）",
            },
            "artifact_version_id": {
                "type": "string",
                "description": (
                    "新的编排方案版本 UUID（`start_plan_research` / "
                    "`start_feature_solution` 的返回值）。"
                ),
            },
        },
        # coding_plan_id / session_id 二选一（在 handler 内校验）
        "required": ["conversation_id", "artifact_version_id"],
    },
)
async def update_coding_plan(
    conversation_id: str,
    artifact_version_id: str,
    coding_plan_id: str = "",
    session_id: str = "",
) -> ToolResult:
    """把既有 CodingPlan re-bind 到新的编排方案版本 + 同步 draft session 兼容字段。

    正文一律经 ``PlanProjectionService.arebind`` 从来源版本渲染 —— 工具与 HTTP 端点
    共用同一 service，也共享 service 内的归属判定（``artifact_version_forbidden``）。

    ``conversation_id`` 是 chat_runner 闭包注入的服务端值（从模型可见 schema 里剔除，
    见 ``agents/chat_runner.py::_build_tool_specs``），承担两件事：解析归属主体，以及
    校验「被改写的 plan / session 确实属于本次会话」—— 后者让模型无法通过挑他人的
    ``coding_plan_id`` / ``session_id`` 自选身份或污染他人数据。
    """
    from chat.models import CodingPlan, CodingSession, Conversation
    from chat.plan_projection_service import PlanProjectionError, PlanProjectionService

    logger.info(
        "update_coding_plan_requested",
        coding_plan_id=coding_plan_id,
        session_id=session_id,
        artifact_version_id=artifact_version_id or None,
    )

    if not coding_plan_id and not session_id:
        return ToolResult(
            success=False,
            error="必须提供 coding_plan_id 或 session_id",
        )

    if not str(artifact_version_id or "").strip():
        _log_authoring_rejected(
            conversation_id="",
            reason="missing_artifact_version_id",
        )
        return ToolResult(
            success=False,
            error=(
                "缺少 artifact_version_id：编码方案的正文只能来自编排链路产出的方案版本。"
                "请先调用 start_plan_research 发起编排，拿到新的方案版本后再调用本工具。"
            ),
        )

    try:
        conversation = await Conversation.objects.aget(id=conversation_id)
    except Conversation.DoesNotExist:
        return ToolResult(
            success=False,
            error=f"Conversation not found: {conversation_id}",
        )

    # 归属主体：① 请求上下文（中间件在 DRF 认证后权威写入，SSE 生成器体内重绑）；
    # ② 退回服务端**注入**的 conversation 的创建者。
    #
    # 🔴 为什么退回 conversation 而不是「被改写 plan 的会话创建者」：后者的定位入参
    # （coding_plan_id / session_id）由模型提供，退回它等于让攻击者挑他人 plan_id 自
    # 选身份（EoP）。而 conversation_id 是 chat_runner 从模型可见入参里剔除后闭包注入
    # 的，模型改不了，且 chat SSE 入口本身有 owner gate ⇒ 是真实身份而非哨兵。
    # 109-REVIEW BL-01：只取 contextvars 会在生产恒空（中间件写的是 "system" 占位），
    # 让本工具每次调用都早退；补上这条服务端注入的退路后归属强度与 create 一致。
    actor_user_id = _context_user_id() or str(conversation.created_by_id or "")
    if not actor_user_id:
        _log_authoring_rejected(conversation_id=conversation_id, reason="actor_user_unresolved")
        return ToolResult(
            success=False,
            error="无法确定当前操作用户，拒绝改写编码方案。",
        )

    # 路由：优先按 coding_plan_id 走新签名；旧 session_id 走兼容路径
    plan: CodingPlan | None = None
    # REVIEW M-1：legacy session_id 路径下补回 plan 的 session id（用于
    # fan-out 同步阶段跳过它，避免重复 write）
    legacy_session_to_skip: str | None = None
    if coding_plan_id:
        try:
            plan = await CodingPlan.objects.aget(id=coding_plan_id)
        except CodingPlan.DoesNotExist:
            return ToolResult(
                success=False,
                error=f"CodingPlan not found: {coding_plan_id}",
            )
        # 会话一致性：模型报的 plan 必须属于本次注入的会话。措辞与「不存在」逐字一致，
        # 不泄漏存在性（沿用 service 侧 `_assert_owner` 已建立的纪律）。
        if str(plan.conversation_id or "") != str(conversation.id):
            _log_authoring_rejected(
                conversation_id=conversation_id,
                reason="artifact_version_forbidden",
            )
            return ToolResult(
                success=False,
                error=f"CodingPlan not found: {coding_plan_id}",
            )
    else:
        try:
            session = await CodingSession.objects.select_related(
                "coding_plan", "conversation"
            ).aget(id=session_id)
        except CodingSession.DoesNotExist:
            return ToolResult(
                success=False,
                error=f"CodingSession not found: {session_id}",
            )
        # 🔴 109-REVIEW MN-04：归属判定必须早于下面的 legacy 补 FK 两次写。判定放到
        # arebind 之后等于「拒绝了，但已经在他人会话下建出 CodingPlan 并改写了他人
        # CodingSession.coding_plan」——与投影端点刻意用只读前置解析所要避免的形状同款。
        if str(session.conversation_id or "") != str(conversation.id):
            _log_authoring_rejected(
                conversation_id=conversation_id,
                reason="artifact_version_forbidden",
            )
            return ToolResult(
                success=False,
                error=f"CodingSession not found: {session_id}",
            )
        if session.coding_plan_id is None:
            # 旧数据未迁移：临时建/拿 plan 并把反向 FK 补回去。正文沿用 session 的
            # 既有值（不是模型入参）—— 真正的新正文由下方 arebind 从来源版本渲染。
            plan, _created = await CodingPlan.aget_or_create_for_conversation(
                conversation=session.conversation,
                tech_plan=session.tech_plan,
                affected_files=session.affected_files or [],
                title="",
            )
            session.coding_plan = plan
            await session.asave(update_fields=["coding_plan", "updated_at"])
            legacy_session_to_skip = str(session.id)
        else:
            plan = session.coding_plan

    assert plan is not None  # 已被前面分支覆盖

    # re-bind：正文只能来自新的编排方案版本（归属判定在 service 内，工具与端点同门）。
    try:
        plan = await PlanProjectionService().arebind(
            plan=plan,
            artifact_version_id=str(artifact_version_id).strip(),
            actor_user_id=actor_user_id,
        )
    except PlanProjectionError as exc:
        _log_authoring_rejected(
            conversation_id=str(plan.conversation_id or ""),
            reason=exc.code,
        )
        # error 只回显机器码与固定引导语，绝不回显他人方案正文的任何片段。
        return ToolResult(
            success=False,
            error=(
                f"无法把编码方案重新指向方案版本 {artifact_version_id}（{exc.code}）。"
                "请确认该方案版本由当前会话的编排链路产出，且未被其它编码方案占用。"
            ),
        )

    tech_plan = plan.tech_plan
    normalized_files = list(plan.affected_files or [])

    # 同步关联的 draft session 的兼容字段（不污染 running/completed）。
    # REVIEW M-1：若刚刚通过 legacy session_id 路径补回过 plan，这条 session
    # 已经在补回的同一事务里写入了 plan 的最新内容，跳过避免重复 write。
    synced = 0
    async for s in plan.coding_sessions.filter(  # type: ignore[attr-defined]
        status=CodingSession.Status.DRAFT
    ).aiterator():
        if legacy_session_to_skip is not None and str(s.id) == legacy_session_to_skip:
            # legacy 路径补回时已把目标值写进 session（见下方 fix block），跳过
            continue
        s.tech_plan = tech_plan
        s.affected_files = normalized_files
        await s.asave(update_fields=["tech_plan", "affected_files", "updated_at"])
        synced += 1

    # legacy 路径下，把 update 后的目标值合并写到刚补回 plan 的 session
    if legacy_session_to_skip is not None:
        await CodingSession.objects.filter(id=legacy_session_to_skip).aupdate(
            tech_plan=tech_plan,
            affected_files=normalized_files,
        )
        synced += 1

    logger.info(
        "update_coding_plan_completed",
        coding_plan_id=str(plan.id),
        synced_sessions_count=synced,
    )

    return ToolResult(
        success=True,
        output={
            "coding_plan_id": str(plan.id),
            "synced_sessions_count": synced,
            # 109-REVIEW HI-02：与 create 同形 —— update 同样渲染 TechPlanCard，
            # 缺这三个键时它的卡片会走上同一条「无正文 + 误挂草稿横幅」的失效面。
            "tech_plan": tech_plan or "",
            "affected_files": list(normalized_files),
            "provenance": plan.provenance,
            "message": (
                f"编码方案已重新指向方案版本 {artifact_version_id}（plan_id={plan.id}）；"
                f"同步刷新了 {synced} 个 draft session 的兼容字段。"
            ),
        },
    )
