"""编码会话工具 — create_coding_plan / update_coding_plan @tool。

工具落库切换到 `CodingPlan` 独立领域；返回 payload 同时携带
`coding_plan_id` 和 `coding_session_id`（兼容期保留旧 `session_id` alias）。
"""

from __future__ import annotations

import structlog

from agents.tools.base import ToolResult, tool

logger = structlog.get_logger(__name__)


def _normalize_affected_files(
    raw: list[dict[str, str]],
) -> list[dict[str, str]]:
    """统一 affected_files schema 为 ``{file_path, change_type}``。

    - 兼容旧 schema：``path`` 键自动迁移到 ``file_path``
    - 未知键名透传保留（不主动 strip 避免误删元数据）
    - 缺 ``change_type`` 时回退 ``modify``
    """
    normalized: list[dict[str, str]] = []
    for entry in raw:
        item: dict[str, str] = dict(entry)
        if "file_path" not in item and "path" in item:
            item["file_path"] = item.pop("path")
        item.setdefault("change_type", "modify")
        normalized.append(item)
    return normalized


@tool(
    name="create_coding_plan",
    description=(
        "创建编码技术方案。当用户描述了具体的代码变更需求时调用。"
        "传入结构化技术方案（影响文件列表 + 实现步骤），后端创建 CodingPlan 记录。"
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
            "tech_plan": {
                "type": "string",
                "description": "Markdown 格式的技术方案，包含影响文件列表和分步实现步骤",
            },
            "affected_files": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string"},
                        "change_type": {
                            "type": "string",
                            "enum": ["add", "modify", "delete"],
                        },
                    },
                    "required": ["file_path", "change_type"],
                },
                "description": (
                    "影响文件列表（schema: [{file_path: str, "
                    "change_type: 'add'|'modify'|'delete'}]）"
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
            "tech_plan",
            "affected_files",
        ],
    },
)
async def create_coding_plan(
    space_id: str,
    conversation_id: str,
    tech_plan: str,
    affected_files: list[dict[str, str]],
    repository_id: str = "",
    recommended_repository_ids: list[str] | None = None,
) -> ToolResult:
    """创建编码技术方案，生成 CodingPlan 记录（coding-plan workflow）。

    本工具不再创建 CodingSession：session 由前端在 UI 选定仓库后通过
    ``POST /api/chat/coding-plans/{plan_id}/sessions/`` (fan-out endpoint)
    创建，是 coding-plan workflow fan-out 设计的唯一 session 创建源。

    ``recommended_repository_ids`` 可选 ——

    - LLM 显式传：校验全部属于该 space + 未软删 → 持久化到
      CodingPlan.recommended_repository_ids。
    - LLM 不传：Server 自动从 conversation 最近一条 RepositoryRoutingTrace
      取 ``selected_by_user_final=True`` 的 repository_id 列表（含 manual
      override 覆盖；按 created_at desc 自然拿到「用户最新意图」）。
    - 都无：写空列表，返回 metadata ``recommended_source='empty'``。

    ``repository_id`` 可选：传入时校验属于 space，并被合并进
    ``recommended_repository_ids`` 列表（置顶）。**不再用于创建 session。**
    """
    from chat.models import CodingPlan, Conversation, RepositoryRoutingTrace
    from projects.models import Space
    from repositories.models import Repository

    logger.info(
        "create_coding_plan_requested",
        space_id=space_id,
        repository_id=repository_id or None,
        affected_files_count=len(affected_files),
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

    # contract schema 归一化（兼容旧 path 入参）
    normalized_files = _normalize_affected_files(affected_files)

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

    # 先 get/create CodingPlan
    plan, plan_created = await CodingPlan.aget_or_create_for_conversation(
        conversation=conversation,
        tech_plan=tech_plan,
        affected_files=normalized_files,
        title="",
    )

    # 把推荐仓库列表写入 plan（覆盖既有值 —— 同 plan 多次
    # 调用以最新一次为准；空列表也写以清空旧值）
    if list(plan.recommended_repository_ids or []) != final_recommended:
        plan.recommended_repository_ids = final_recommended
        await plan.asave(update_fields=["recommended_repository_ids", "updated_at"])

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
            "message": (f"技术方案已创建，plan_id={plan.id}。请在 UI 选择目标仓库后开始编码。"),
        },
    )


@tool(
    name="update_coding_plan",
    description=(
        "更新编码技术方案。当用户要求调整方案时调用。"
        "传入更新后的方案内容；后端更新 CodingPlan，所有关联的 draft CodingSession 同步刷新。"
    ),
    category="PROJECT",
    parameters={
        "type": "object",
        "properties": {
            "coding_plan_id": {
                "type": "string",
                "description": "CodingPlan UUID（coding-plan workflow 起首选）",
            },
            "session_id": {
                "type": "string",
                "description": "CodingSession UUID（legacy 兼容路径，已 deprecated）",
            },
            "tech_plan": {
                "type": "string",
                "description": "更新后的 Markdown 技术方案",
            },
            "affected_files": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string"},
                        "change_type": {
                            "type": "string",
                            "enum": ["add", "modify", "delete"],
                        },
                    },
                    "required": ["file_path", "change_type"],
                },
                "description": (
                    "更新后的影响文件列表（schema: [{file_path: str, change_type: str}]）"
                ),
            },
        },
        # coding_plan_id / session_id 二选一（在 handler 内校验）
        "required": ["tech_plan", "affected_files"],
    },
)
async def update_coding_plan(
    tech_plan: str,
    affected_files: list[dict[str, str]],
    coding_plan_id: str = "",
    session_id: str = "",
) -> ToolResult:
    """更新 CodingPlan + 同步 draft session 的 deprecated 字段（implementation）。"""
    from chat.models import CodingPlan, CodingSession

    logger.info(
        "update_coding_plan_requested",
        coding_plan_id=coding_plan_id,
        session_id=session_id,
    )

    if not coding_plan_id and not session_id:
        return ToolResult(
            success=False,
            error="必须提供 coding_plan_id 或 session_id",
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
        if session.coding_plan_id is None:
            # 旧数据未迁移：临时建/拿 plan 并把反向 FK 补回去
            plan, _created = await CodingPlan.aget_or_create_for_conversation(
                conversation=session.conversation,
                tech_plan=session.tech_plan,
                affected_files=session.affected_files or [],
                title="",
            )
            # REVIEW M-1：补回 plan 时合并写入更新后的 tech_plan / affected_files，
            # 否则下一段 fan-out 同步会重复写一次（无谓 IO + updated_at 被刷两次）。
            # 这里先暂存目标值，等下方归一化完成后一并写入。
            session.coding_plan = plan
            await session.asave(update_fields=["coding_plan", "updated_at"])
            legacy_session_to_skip = str(session.id)
        else:
            plan = session.coding_plan

    assert plan is not None  # 已被前面分支覆盖

    normalized_files = _normalize_affected_files(affected_files)
    await plan.aupdate_plan(tech_plan=tech_plan, affected_files=normalized_files)

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
            "message": (
                f"技术方案已更新（plan_id={plan.id}）；"
                f"同步刷新了 {synced} 个 draft session 的兼容字段。"
            ),
        },
    )
