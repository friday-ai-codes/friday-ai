"""内置 process_type 注册（Chassis v2 · P2）。

注册三个 ``ProcessDefinition``：

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
    EVENT_FEATURE_CLASSIFIED,
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
    """LLM 跨仓拆分 + fail-soft 回退：需求文本 → 结构化 decomposition。

    **feature list 入口短路**：feature 树本身已是「模块 → 功能点」的结构化拆分，调用方经
    ``feature_segments`` 直接给出即可——再让 LLM 拆一遍既浪费一次调用，又会把用户写好的
    功能点边界揉散（下游分类/确认/落点都以功能点为单位对齐）。仅当 ``feature_segments``
    为空时才回落既有 LLM 拆分路径。
    """
    from services.process_runtime.decompose_segments import (
        agenerate_decomposition_segments,
    )

    existing = session.decomposition or {}
    requirement_text = existing.get("requirement_text", "")

    feature_segments = existing.get("feature_segments") or []
    if existing.get("mode") == "feature_list" and feature_segments:
        decomposition = {
            **existing,
            "requirement_text": requirement_text,
            "segments": feature_segments,
        }
        logger.info(
            "plan_decompose_from_feature_list",
            category="sampling",
            component="process_runtime",
            segment_count=len(feature_segments),
        )
        return StageOutcome(event="decomposed", stage_state_update={"decomposition": decomposition})

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
    # feature list 会话即便退到 LLM 拆分（feature_segments 为空），mode 也必须带下去——
    # 否则下游 classify stage 会误判为普通入口而 pass-through，分类与强制确认整段失效。
    if existing.get("mode"):
        decomposition["mode"] = existing["mode"]
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


async def _h_classify(session: Any, engine: Any) -> StageOutcome:
    """分类 stage：feature list 入口判定各功能点新增/改造；**其余入口 pass-through**。

    该 stage 是 feature list 方案编排专用扩展点。非 ``feature_list`` 模式（既有飞书 /
    对话 / MCP 入口）必须**零副作用穿过**：不调 deps、不发 LLM、不检索、不产
    stage_state——保证既有链路行为逐字不变。deps 未注入 classify（旧构造）时同样
    pass-through，不报错。
    """
    decomposition = session.decomposition if isinstance(session.decomposition, dict) else {}
    if decomposition.get("mode") != "feature_list":
        return StageOutcome(event="classified")

    classifier = getattr(getattr(engine, "deps", None), "classify", None)
    if classifier is None:
        return StageOutcome(event="classified")

    result = await classifier.classify(session)
    classification = result if isinstance(result, dict) else {}
    await engine.session_service._emit_event(
        EVENT_FEATURE_CLASSIFIED,
        session,
        {
            "summary": classification.get("summary", {}),
            "evidence_hits": classification.get("evidence_hits", 0),
        },
    )
    return StageOutcome(event="classified", stage_state_update={"classification": classification})


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
        transitions={"recalled": "classify"},
    ),
    "classify": StageDef(
        key="classify",
        handler=_h_classify,
        transitions={"classified": "clarify"},
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


# ==================== technical_blueprint stage handlers =====================
#
# 阶段 0（规格门）+ 阶段 1（调研与确认门）的七个 handler（Phase 112-05）。
#
# 三条纪律（与既有 handler 同源）：
# ① **软取依赖**：`getattr(getattr(engine, "deps", None), "<name>", None)`；缺依赖直接
#    返回默认 pass-through outcome，**不报错**（新 process 注册不得让旧链或裸 engine 崩）。
#    属性名清单与 `entrypoint.build_blueprint_engine` 组装的 deps 逐字一致（同一 plan 内
#    两处写同一份名单，避免「注册了但 handler 恒 pass-through」的静默空转）。
# ② **绝不自行 transition**：handler 只返回 `StageOutcome`，落库由 engine 承担（engine 纯度）。
# ③ **事件不重复 emit**：四个蓝图 adapter 各自已 emit 自己的 `blueprint.*` 事件
#    （112-02/03/04/05），handler 再 emit 会把计数打成两倍；engine 的 `transition` 本身
#    也会记一条 `convergence_session_event`。故本组 handler 不另发事件。


async def _h_bp_intake(session: Any, engine: Any) -> StageOutcome:
    """intake stage：显式起点。会话建立时入口已把需求写进 ``stage_state``，本 stage 零副作用。"""
    return StageOutcome(event="intaken")


async def _h_bp_decompose(session: Any, engine: Any) -> StageOutcome:
    """decompose stage：蓝图 ``requirement_spec`` 由入口/规格门装配，本 stage 直通。

    （功能点拆分在 116 入口切换时接线；此处保持零副作用穿过，避免半截 stage_state。）
    """
    return StageOutcome(event="decomposed")


async def _h_bp_spec_gate(session: Any, engine: Any) -> StageOutcome:
    """spec_gate stage：跑 112-02 的规格门 adapter，按其 ``event`` 决定转移。

    ``needs_clarification`` → self-loop 挂起（``waiting_clarification``）；
    ``spec_locked`` → 进 route。deps 未注入时 pass-through 放行（不把未接线当成需澄清）。
    """
    adapter = getattr(getattr(engine, "deps", None), "spec_gate", None)
    if adapter is None:
        return StageOutcome(event="spec_locked")
    result = await adapter.run(session)
    result = result if isinstance(result, dict) else {}
    event = "needs_clarification" if result.get("event") == "needs_clarification" else "spec_locked"
    return StageOutcome(event=event, stage_state_update=result.get("stage_state") or None)


async def _h_bp_route(session: Any, engine: Any) -> StageOutcome:
    """route stage：**``stage_state["routing"]`` 的唯一写入方**（112-03 契约）。

    ``stage_state_update={"routing": <route() 返回值原样>}``——摘要字段清单逐字取
    112-03 契约表（顶层 ``router_version`` / ``auto_selected`` / ``intent`` /
    ``weights_used`` / ``charter_supplement_count`` / ``unjustified_boundary_hit_count`` /
    ``candidates`` / ``citations``；``candidates[]`` 每项 ``repository_id`` /
    ``repository_name`` / ``role_suggestion`` / ``confidence`` / ``total`` / ``breakdown`` /
    ``evidence``），与 112-04 ``dispatch`` 的读取处**同一份清单**，不得裁剪或改名。

    adapter 缺依赖时 pass-through 且 ``stage_state_update=None``——**绝不写半截
    ``routing`` 键**（半截键会让下游把「没跑路由」误当成「跑了但零候选」）。
    """
    adapter = getattr(getattr(engine, "deps", None), "route", None)
    if adapter is None:
        return StageOutcome(event="routed")
    routing = await adapter.route(session)
    return StageOutcome(event="routed", stage_state_update={"routing": routing})


async def _h_bp_repo_research(session: Any, engine: Any) -> StageOutcome:
    """repo_research stage：112-04 的**增量** dispatch（首轮入口 + 重调研复用入口）。

    候选来源 = ``stage_state["routing"].candidates`` ∪ ``stage_state["confirmation"]`` 内
    ``pending_research`` 仓；只派发 ``PENDING`` / ``STALE``，已完成仓不重跑（结论保留）。
    派发后 ``research_dispatched`` self-loop 挂 ``waiting_event`` 等容器回调；全部 task
    终态则 ``research_complete`` 进 reroute。
    """
    from services.process_runtime.research_aggregation import aall_research_tasks_terminal

    adapter = getattr(getattr(engine, "deps", None), "research", None)
    if adapter is None:
        return StageOutcome(event="research_complete")
    await adapter.dispatch(session)
    if await aall_research_tasks_terminal(session.id):
        return StageOutcome(event="research_complete")
    return StageOutcome(event="research_dispatched")


async def _h_bp_reroute(session: Any, engine: Any) -> StageOutcome:
    """reroute stage：112-04 的有界重路由判定（``converged`` / ``reroute_needed`` / ``exhausted``）。

    ``stage_state_update`` 用 ``aadvance_reroute`` 返回的**整份浅合并结果**（它已是
    ``{**state, ...}``，只取增量会清空 ``routing`` / ``decomposition``）；``escalation``
    非空时一并落 ``stage_state``，供确认门快照读「带全部现状升门」的理由与逐仓结论。
    """
    adapter = getattr(getattr(engine, "deps", None), "research", None)
    if adapter is None:
        return StageOutcome(event="converged")
    result = await adapter.aadvance_reroute(session)
    result = result if isinstance(result, dict) else {}
    update = result.get("stage_state_update")
    update = dict(update) if isinstance(update, dict) else {}
    escalation = result.get("escalation")
    if isinstance(escalation, dict) and escalation:
        update["escalation"] = escalation
    return StageOutcome(
        event=str(result.get("event") or "converged"), stage_state_update=update or None
    )


async def _h_bp_repo_confirmation(session: Any, engine: Any) -> StageOutcome:
    """repo_confirmation stage：阶段 1 出口硬门 + **五动作驱动重调研的出边判定**。

    判定顺序**固定**为「先 research_required 再 awaiting_confirmation」——否则
    ``add_repo`` 后会被 self-loop 挂起而永远到不了调研（SC-4 断链）。

    待调研判据取 ``blueprint_confirm_gate.acollect_pending_research_repos``（**模块级
    单一实现**，语义 = 快照内 ``pending_research is True`` **且**其
    ``RepoResearchTask.status ∈ {pending, stale}``，两条件合取使标记无需清位、不会死循环）。
    ``blueprint_resume`` 的 pause 短路读的是**同一个函数**——本 handler 内绝不另写一份，
    两份实现漂移即 SC-4 断链。
    """
    from services.process_runtime.blueprint_confirm_gate import (
        STAGE_STATE_KEY,
        acollect_confirmation_state,
        acollect_pending_research_repos,
    )

    pending = await acollect_pending_research_repos(session)
    if pending:
        # 回 repo_research 增量派发新增/待重调研仓；同时把最新快照刷进 stage_state——
        # 112-04 的 dispatch 只认 stage_state["confirmation"]，不刷就派不到新仓。
        state = await acollect_confirmation_state(session)
        return StageOutcome(
            event="research_required",
            stage_state_update={STAGE_STATE_KEY: state} if state else None,
        )

    adapter = getattr(getattr(engine, "deps", None), "confirm_gate", None)
    if adapter is None:
        return StageOutcome(event="awaiting_confirmation")
    result = await adapter.open_gate(session)
    result = result if isinstance(result, dict) else {}
    event = "confirmed" if result.get("event") == "confirmed" else "awaiting_confirmation"
    return StageOutcome(event=event, stage_state_update=result.get("stage_state") or None)


# 与 112-04 同源的重路由轮次上界（两处各写一个字面量会让「有界」在演进中失效，故复用
# 其常量而非复制数值）。模块中段 import 是为守「本文件纯追加」纪律：既有 import 块一字不动。
from services.process_runtime.blueprint_research_adapter import (  # noqa: E402
    MAX_REROUTE_ROUNDS as _MAX_REROUTE_ROUNDS,
)

MAX_BLUEPRINT_REROUTE_ROUNDS = _MAX_REROUTE_ROUNDS

_TECHNICAL_BLUEPRINT_STAGES = {
    "intake": StageDef(
        key="intake",
        handler=_h_bp_intake,
        transitions={"intaken": "decompose"},
    ),
    "decompose": StageDef(
        key="decompose",
        handler=_h_bp_decompose,
        transitions={"decomposed": "spec_gate"},
    ),
    "spec_gate": StageDef(
        key="spec_gate",
        handler=_h_bp_spec_gate,
        transitions={"spec_locked": "route", "needs_clarification": "spec_gate"},
        pausable=True,
        wait_status="waiting_clarification",
    ),
    "route": StageDef(
        key="route",
        handler=_h_bp_route,
        transitions={"routed": "repo_research"},
    ),
    "repo_research": StageDef(
        key="repo_research",
        handler=_h_bp_repo_research,
        transitions={
            "research_dispatched": "repo_research",
            "research_complete": "reroute",
        },
        pausable=True,
        wait_status="waiting_event",
    ),
    "reroute": StageDef(
        key="reroute",
        handler=_h_bp_reroute,
        transitions={
            "reroute_needed": "repo_research",
            "converged": "repo_confirmation",
            # 超限**升确认门交人裁决**，绝不落 STAGE_FAILED（CONTEXT「绝不静默失败」）：
            # 不收敛是「需要人裁决」，不是「流程失败」。上界由 MAX_REROUTE_ROUNDS 约束。
            "exhausted": "repo_confirmation",
        },
    ),
    "repo_confirmation": StageDef(
        key="repo_confirmation",
        handler=_h_bp_repo_confirmation,
        transitions={
            "awaiting_confirmation": "repo_confirmation",
            # 回边（B1①）：add_repo / reclassify_role(indirect→direct) /
            # edit_responsibility(rerun) / upgrade_research 驱动的重调研靠它回到
            # repo_research；没有这条边，未登记的 event 会直接 ValueError，
            # ROADMAP SC-4「用户加仓/改判驱动对应重调研」不可能为真。
            # 它与 repo_research → reroute → repo_confirmation 构成确认门的**有界回路**，
            # 边界由 MAX_REROUTE_ROUNDS 与「已完成仓不重派」共同约束。
            "research_required": "repo_research",
            # 113 接续点：把该值改为 "repo_plan" 并追加两个 StageDef 即可
            # （transitions 是数据，无需改 engine）。
            "confirmed": STAGE_DONE,
        },
        pausable=True,
        wait_status="waiting_clarification",
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

# 蓝图链（Phase 112-05）：artifact_type 复用 Phase 111 的 technical_plan —— blueprint/v1
# 按 content.schema_version 判别校验器（DESIGN §3.1：不新增 artifact_type），见
# delivery/artifacts/builtin_types.py 的判别分支。
register_process_type(
    ProcessDefinition(
        process_type="technical_blueprint",
        artifact_type="technical_plan",
        initial_stage="intake",
        stages=_TECHNICAL_BLUEPRINT_STAGES,
    )
)
