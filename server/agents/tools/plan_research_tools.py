"""start_plan_research chat agent 工具 —— Chat 入口薄封装（ENTRY-02）。

给对话加一层**薄入口**：LLM 识别「做多仓技术方案 / 跨仓方案编排」意图时调本工具，经共享
helper（``start_orchestration`` + ``build_orchestration_engine``）建 ``entrypoint=chat`` 的
``PlanSession`` 并驱动**与工作流节点完全相同的** ``PlanOrchestrationEngine``——不并行造两套
编排（SC-1）。

薄封装铁律：本工具**绝不写新编排逻辑**，只做：① 建 session（INV-2：自然语言需求
``work_item=None`` 显式可追溯，entrypoint=chat 标记）；② 复用同一 engine 驱动 advance；
③ 终态 / 挂起映射。澄清 / 调研挂起复用 chat 既有 HITL（``ask_clarification`` interrupt /
``deep_analysis`` fire-and-forget marker），**不重实现**；engine 状态全持久化 → 跨轮次 / 容器
回调由既有 chat 机制 resume（真实 LLM/容器端到端 resume E2E 沿用既有 deferred）。

**async ORM 防裸 lazy-FK**（规避 Phase 38 CR-01 类）：用 ``*_id`` 标量 / ``.values()`` /
``afirst`` / ``aget``，绝不裸访问同步 lazy-FK。所有 delivery/engine import 用函数内 lazy
import 规避 chat→delivery 循环（对齐 coding_tools）。
"""

from __future__ import annotations

from typing import Any

import structlog

from agents.tools.base import ToolResult, tool

logger = structlog.get_logger(__name__)

# 驱动循环最大步数（防 advance 不前进死循环，T-42-03；mirror 工作流节点 _MAX_ADVANCE_STEPS）
_MAX_ADVANCE_STEPS = 20


@tool(
    name="start_plan_research",
    description=(
        "发起多仓 / 跨仓技术方案编排（方案调研）。当对话中识别用户想「做一个跨多个仓库的"
        "技术方案 / 跨仓方案编排 / 多仓协同改造方案」意图时调用。\n"
        "本工具复用与工作流入口完全相同的方案编排引擎："
        "拆分→路由→召回→澄清→并行调研→融合，产出 canonical 跨仓主方案（MergedPlan）。\n"
        "若需要澄清会暂停并向用户提问；若需要深入调研会启动远程容器，完成后自动回流继续融合。"
    ),
    category="PROJECT",
    parameters={
        "type": "object",
        "properties": {
            "requirement_text": {
                "type": "string",
                "description": "自然语言需求文本（用户想实现的跨仓需求描述）。",
            },
            "include_repos": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "可选：限定候选仓库 UUID 列表（不传则按召回 / 路由自动选取）。"
                ),
            },
            "space_id": {
                "type": "string",
                "description": "空间 UUID (auto-injected)",
            },
            "conversation_id": {
                "type": "string",
                "description": "会话 UUID (auto-injected)",
            },
        },
        "required": ["requirement_text", "space_id", "conversation_id"],
    },
)
async def start_plan_research(
    requirement_text: str,
    space_id: str,
    conversation_id: str,
    include_repos: list[str] | None = None,
) -> ToolResult:
    """Chat 入口薄封装：建 entrypoint=chat session + 复用同一 engine 驱动方案编排到终态 / 挂起。"""
    # 0. 空需求 fail-closed 守护（与工作流节点 _create_session missing_requirement 对称）：
    #    requirement_text 属半可信输入（chat LLM → 工具，见 threat model），空 / 纯空白即拒绝，
    #    不建 session、不驱动 engine——避免浪费一次编排并落语义空洞的 PlanSession（WR-02）。
    if not requirement_text or not requirement_text.strip():
        logger.warning(
            "start_plan_research_missing_requirement",
            space_id=space_id,
            conversation_id=conversation_id,
        )
        return ToolResult(
            success=False,
            error="缺少需求文本（requirement_text）",
        )

    from delivery.models import PlanSession, PlanSessionStatus
    from services.plan_orchestration import (
        build_orchestration_engine,
        start_orchestration,
    )

    logger.info(
        "start_plan_research_requested",
        space_id=space_id,
        conversation_id=conversation_id,
        include_repos_count=len(include_repos or []),
    )

    # 1. 解析 created_by（召回 stage 权限 actor）：从 Conversation.created_by 取用户对象；
    #    解析失败 / 为空 → None（recall stage 对 None actor fail-closed 返回空召回，文档化降级）。
    created_by = await _resolve_actor(conversation_id)

    # 2. include_repos best-effort 过滤到属于 space 的仓库 UUID（与工作流节点对称，不做新路由）。
    filtered_repos = await _filter_repos_in_space(space_id, include_repos)

    # 3. 建 session：work_item=None 即 INV-2 自然语言需求显式标记（entrypoint=chat 可追溯）。
    session = await start_orchestration(
        entrypoint="chat",
        requirement_text=requirement_text,
        work_item=None,
        created_by=created_by,
        include_repos=filtered_repos,
    )

    # 4. 构建 engine：与工作流节点同一 build_orchestration_engine（无 node_execution_id；
    #    chat resume 走既有 deep_analysis / clarification 机制，不依赖 node_execution）。
    engine = build_orchestration_engine()

    # 5. 驱动循环（mirror 工作流节点：终态集合 {DONE, FAILED} + 步数上限防死循环）。
    terminal = {PlanSessionStatus.DONE, PlanSessionStatus.FAILED}
    steps = 0
    while session.status not in terminal:
        steps += 1
        if steps > _MAX_ADVANCE_STEPS:
            logger.warning(
                "start_plan_research_advance_step_limit", session_id=str(session.id)
            )
            await engine.session_service.transition(
                session, "fail", error={"reason": "advance_step_limit", "steps": steps}
            )
            session = await PlanSession.objects.aget(id=session.id)
            break

        await engine.advance(session)
        session = await PlanSession.objects.aget(id=session.id)

        # 挂起复用 chat 既有 HITL（ask_clarification interrupt / deep_analysis fire-and-forget）
        suspend = await _maybe_suspend(session, conversation_id)
        if suspend is not None:
            logger.info(
                "start_plan_research_suspended",
                session_id=str(session.id),
                status=session.status,
            )
            return suspend

    # 6. 终态映射
    return _map_terminal(session)


async def _resolve_actor(conversation_id: str) -> Any:
    """从 ``Conversation.created_by`` 解析发起用户（async 安全，不裸 lazy-FK）。

    取 ``created_by`` 标量再按 id 取 User 对象；conversation 不存在 / created_by 为空 → None
    （None actor 下召回 stage fail-closed 返回空召回，文档化降级，不报错）。
    """
    if not conversation_id:
        return None
    from chat.models import Conversation

    row = (
        await Conversation.objects.filter(id=conversation_id)
        .values("created_by")
        .afirst()
    )
    if not row or not row.get("created_by"):
        return None
    from accounts.models import User

    return await User.objects.filter(id=row["created_by"]).afirst()


async def _filter_repos_in_space(
    space_id: str, include_repos: list[str] | None
) -> list[str]:
    """include_repos best-effort 过滤到属于 space 的仓库 UUID（透传，不做新路由）。

    非法 UUID / 查询异常一律降级为空列表（best-effort，不阻断编排发起）。
    """
    if not include_repos:
        return []
    from repositories.models import Repository

    try:
        return [
            str(rid)
            async for rid in Repository.objects.filter(
                id__in=include_repos, projects__id=space_id, is_deleted=False
            ).values_list("id", flat=True)
        ]
    except Exception:  # noqa: BLE001 — best-effort 过滤，非法 UUID 等降级为空
        logger.warning("start_plan_research_repo_filter_failed", space_id=space_id)
        return []


async def _maybe_suspend(session: Any, conversation_id: str) -> ToolResult | None:
    """clarifying（pending）/ researching（在途）处复用 chat 既有 HITL 返回挂起 marker。"""
    from delivery.models import Clarification, PlanSessionStatus
    from services.plan_orchestration import aall_research_tasks_terminal

    if session.status == PlanSessionStatus.CLARIFYING:
        pending = await (
            Clarification.objects.filter(
                session_id=session.id, answered_at__isnull=True
            )
            .values("id", "question")
            .afirst()
        )
        if pending is not None:
            # 复用 chat 既有 ask_clarification interrupt（orchestration.graph 据 marker 识别挂起）
            from agents.tools.clarification import CLARIFICATION_PENDING_MARKER

            return ToolResult(
                success=True,
                output={
                    "clarification_id": str(pending["id"]),
                    "pending": True,
                    "marker": CLARIFICATION_PENDING_MARKER,
                    "question": pending["question"],
                    "options": [],
                    "allow_freeform": True,
                    "session_id": str(session.id),
                },
            )

    if session.status == PlanSessionStatus.RESEARCHING:
        if not await aall_research_tasks_terminal(session.id):
            # 复用 chat 既有 deep_analysis fire-and-forget marker（容器完成后既有机制 resume）
            from agents.tools.blocking_task_registry import register_blocking_task

            blocking_info: dict[str, Any] = {
                "task_id": str(session.id),
                "task_type": "plan_research",
                "params": {"session_id": str(session.id)},
            }
            await register_blocking_task(conversation_id, blocking_info)
            return ToolResult(
                success=True,
                output={
                    "__blocking_task__": True,
                    "task_type": "plan_research",
                    "task_id": str(session.id),
                    "session_id": str(session.id),
                    "params": {"session_id": str(session.id)},
                    "placeholder": (
                        f"已启动方案编排调研（session={session.id}），"
                        "调研完成后将自动继续融合并返回主方案。"
                    ),
                },
            )
    return None


def _map_terminal(session: Any) -> ToolResult:
    """done → success + canonical plan_version_id；failed → 失败（取 session.error 消息）。"""
    from delivery.models import PlanSessionStatus

    if session.status == PlanSessionStatus.DONE:
        return ToolResult(
            success=True,
            output={
                "session_id": str(session.id),
                "plan_version_id": (
                    str(session.current_plan_version)
                    if session.current_plan_version
                    else None
                ),
                "status": "done",
                "message": "跨仓方案编排已完成，已产出 canonical 主方案（MergedPlan）。",
            },
        )
    error = session.error if isinstance(session.error, dict) else {}
    return ToolResult(
        success=False,
        error=str(error.get("message") or error.get("reason") or "plan session failed"),
    )


__all__ = ["start_plan_research"]
