"""内置 process_type 注册（Chassis v2 · P2）。

注册两个 ``ProcessDefinition``：

- ``technical_plan``：跨仓技术方案编排（``decompose → route → recall → clarify → research
  → merge``），等价于原写死状态机的语义但**数据化**（transitions 表 + handler 复用既有
  adapters）；merge handler 经 ``ArtifactService`` 落 ``technical_plan`` ArtifactVersion。
- ``echo``：trivial 流程（``draft → __done__``），产出 ``echo`` artifact_type——仅供测试，
  证明 stage graph 可配置/可泛化（同一 ``ProcessEngine`` 跑完全不同的 stage 图）。

每个 stage 的 handler 是 ``async (session, engine) -> StageOutcome``：跑 adapter / 业务逻辑，
返回转移 event（engine 据 ``StageDef.transitions`` 落库），**不自行 transition**（engine 纯度）。
"""

from __future__ import annotations

from typing import Any

import structlog

from delivery.artifacts.registry import register_artifact_type
from delivery.services.event_taxonomy import (
    EVENT_KNOWLEDGE_RECALLING,
    EVENT_REPO_ROUTING,
)
from services.process_runtime.engine import StageOutcome
from services.process_runtime.registry import (
    STAGE_DONE,
    STAGE_FAILED,
    ProcessDefinition,
    StageDef,
    register_process_type,
)

logger = structlog.get_logger(__name__)

# 与 ArchitectMergeAdapter.MAX_MERGE_RETRIES 一致（限次回退上限，超限落 failed 终态）。
MAX_MERGE_RETRIES = 1


# ======================= technical_plan stage handlers =======================


async def _h_decompose(session: Any, engine: Any) -> StageOutcome:
    """LLM 跨仓拆分 + fail-soft 回退：需求文本 → 结构化 decomposition。"""
    from services.process_runtime.decompose_segments import (
        agenerate_decomposition_segments,
    )

    existing = session.decomposition or {}
    requirement_text = existing.get("requirement_text", "")
    if not requirement_text and session.work_item_id is not None:
        from delivery.models import WorkItem

        wi = await WorkItem.objects.filter(id=session.work_item_id).afirst()
        requirement_text = wi.title if wi is not None else ""
    include_repos = existing.get("include_repos", [])

    result = await agenerate_decomposition_segments(
        requirement_text=requirement_text, include_repos=include_repos
    )
    if result:
        segments: list[Any] = result
    else:
        segments = [line.strip() for line in requirement_text.splitlines() if line.strip()]
        logger.info(
            "plan_decompose_fallback_splitlines",
            category="sampling",
            component="process_runtime",
            segment_count=len(segments),
        )
    decomposition = {
        "requirement_text": requirement_text,
        "include_repos": include_repos,
        "segments": segments,
    }
    return StageOutcome(event="decomposed", stage_state_update={"decomposition": decomposition})


async def _h_route(session: Any, engine: Any) -> StageOutcome:
    """路由 stage：调注入 router 取候选仓 → 落 stage_state.routing + emit repo.routing。"""
    result = await engine.deps.router.route(session)
    candidates = (result.get("candidates") or []) if isinstance(result, dict) else []
    trace = {
        "candidates": [
            {"repo_id": c.get("repo_id"), "confidence": c.get("confidence")} for c in candidates
        ]
    }
    await engine.session_service._emit_event(EVENT_REPO_ROUTING, session, trace)
    return StageOutcome(event="routed", stage_state_update={"routing": result})


async def _h_recall(session: Any, engine: Any) -> StageOutcome:
    """召回 stage：调注入 recall 取召回上下文 → 落 stage_state.recall_context + emit。"""
    result = await engine.deps.recall.recall(session)
    hits = result.get("hits", []) if isinstance(result, dict) else (result or [])
    trace = {
        "query": result.get("query", "") if isinstance(result, dict) else "",
        "kinds": result.get("kinds", []) if isinstance(result, dict) else [],
        "hits": len(hits),
    }
    await engine.session_service._emit_event(EVENT_KNOWLEDGE_RECALLING, session, trace)
    return StageOutcome(event="recalled", stage_state_update={"recall_context": hits})


async def _h_clarify(session: Any, engine: Any) -> StageOutcome:
    """澄清 stage：调注入 ClarifyProtocol 据判定返回 needs_clarification / clarified。"""
    result = await engine.deps.clarify.clarify(session)
    needs = result.get("needs_clarification") if isinstance(result, dict) else False
    return StageOutcome(event="needs_clarification" if needs else "clarified")


async def _h_research(session: Any, engine: Any) -> StageOutcome:
    """调研 stage：dispatch fan-out；全部终态 → research_complete，否则 research_dispatched（挂起）。"""
    from services.process_runtime.research_aggregation import aall_research_tasks_terminal

    await engine.deps.research.dispatch(session)
    if await aall_research_tasks_terminal(session.id):
        return StageOutcome(event="research_complete")
    return StageOutcome(event="research_dispatched")


async def _h_merge(session: Any, engine: Any) -> StageOutcome:
    """融合 stage：调注入 merge adapter，据结果返回转移 event（passed/失败回退/exhausted）。"""
    result = await engine.deps.merge.merge(session)
    status = result.get("validation_status") if isinstance(result, dict) else None
    attempt = result.get("attempt", 0) if isinstance(result, dict) else 0

    if status == "passed":
        return StageOutcome(
            event="merged",
            current_artifact_version=result.get("artifact_version_id"),
        )
    if attempt >= MAX_MERGE_RETRIES:
        return StageOutcome(
            event="exhausted",
            error={
                "stage": "merge",
                "reason": "merge_validation_exhausted",
                "report": result.get("report", {}) if isinstance(result, dict) else {},
            },
        )
    back_target = (
        result.get("back_target", "clarify") if isinstance(result, dict) else "clarify"
    )
    if back_target == "research":
        return StageOutcome(event="validation_failed_reresearch")
    return StageOutcome(event="validation_failed_reclarify")


_TECHNICAL_PLAN_STAGES = {
    "decompose": StageDef(
        key="decompose",
        handler=_h_decompose,
        transitions={"decomposed": "route"},
    ),
    "route": StageDef(
        key="route",
        handler=_h_route,
        transitions={"routed": "recall"},
    ),
    "recall": StageDef(
        key="recall",
        handler=_h_recall,
        transitions={"recalled": "clarify"},
    ),
    "clarify": StageDef(
        key="clarify",
        handler=_h_clarify,
        transitions={"clarified": "research", "needs_clarification": "clarify"},
        pausable=True,
        wait_status="waiting_clarification",
    ),
    "research": StageDef(
        key="research",
        handler=_h_research,
        transitions={"research_dispatched": "research", "research_complete": "merge"},
        pausable=True,
        wait_status="waiting_event",
    ),
    "merge": StageDef(
        key="merge",
        handler=_h_merge,
        transitions={
            "merged": STAGE_DONE,
            "validation_failed_reclarify": "clarify",
            "validation_failed_reresearch": "research",
            "exhausted": STAGE_FAILED,
        },
    ),
}


# ============================== echo (test-only) ==============================

ARTIFACT_TYPE_ECHO = "echo"


def _validate_echo(content: dict) -> tuple[bool, str | None]:
    """echo content 校验：须为含字符串 ``message`` 键的 dict（仅供测试泛化证明）。"""
    if not isinstance(content, dict):
        return False, "echo content 须为 dict"
    if not isinstance(content.get("message"), str):
        return False, "echo content 须含字符串 message 键"
    return True, None


register_artifact_type(ARTIFACT_TYPE_ECHO, validator=_validate_echo)


async def _h_echo_draft(session: Any, engine: Any) -> StageOutcome:
    """echo draft stage：把 stage_state.echo_input 落为 echo ArtifactVersion → __done__。"""
    from delivery.models import WorkItem
    from delivery.services import ArtifactService

    raw = (session.stage_state or {}).get("echo_input")
    content = raw if isinstance(raw, dict) and isinstance(raw.get("message"), str) else {
        "message": str((raw or {}).get("message", "")) if isinstance(raw, dict) else ""
    }
    work_item = None
    if session.work_item_id is not None:
        work_item = await WorkItem.objects.filter(id=session.work_item_id).afirst()
    artifact = await ArtifactService().create(
        ARTIFACT_TYPE_ECHO,
        content,
        title=content.get("message", "")[:80],
        work_item=work_item,
        produced_by_session_id=str(session.id),
        produced_by_ref="echo.draft",
    )
    return StageOutcome(event="drafted", current_artifact_version=artifact.current_version_id)


_ECHO_STAGES = {
    "draft": StageDef(
        key="draft",
        handler=_h_echo_draft,
        transitions={"drafted": STAGE_DONE},
    ),
}


# =============================== registration ================================

register_process_type(
    ProcessDefinition(
        process_type="technical_plan",
        artifact_type="technical_plan",
        initial_stage="decompose",
        stages=_TECHNICAL_PLAN_STAGES,
    )
)

register_process_type(
    ProcessDefinition(
        process_type="echo",
        artifact_type=ARTIFACT_TYPE_ECHO,
        initial_stage="draft",
        stages=_ECHO_STAGES,
    )
)
