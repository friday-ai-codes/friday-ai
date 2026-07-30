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


# ── 阶段 2/3 的蓝图状态口径（B3）：进入这两个 stage 即 `drafting` ──────────────
#
# 一律经 `BlueprintLifecycleService.transition`（INV-6），**绝不裸改 blueprint_status**。
# 两个 helper 都是 best-effort：状态映射是展示面，映射失败绝不阻断 stage 推进
# （与 `blueprint_resume._amap_blueprint_status` 同一纪律）。


async def _abp_load_artifact(session: Any) -> Any:
    """会话钉住的版本 → 其 artifact（无版本指针即 None）。"""
    from delivery.models import ArtifactVersion

    version_id = getattr(session, "current_artifact_version_id", None)
    if not version_id:
        return None
    version = await (
        ArtifactVersion.objects.select_related("artifact").filter(id=version_id).afirst()
    )
    return getattr(version, "artifact", None)


async def _abp_mark_drafting(session: Any) -> None:
    """把蓝图状态转 ``drafting``（阶段 2/3 的状态口径，B3）；已是该态则跳过（幂等）。

    ``blueprint_status`` 为空串（还没进状态机）时先补一跳 ``researching`` —— 状态机的
    入口边只有 ``"" → researching``，直接跳 ``drafting`` 是非法边。
    """
    from delivery.models import BlueprintStatus
    from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService

    try:
        artifact = await _abp_load_artifact(session)
        if artifact is None:
            return
        current = str(artifact.blueprint_status or "")
        if current == BlueprintStatus.DRAFTING:
            return
        lifecycle = BlueprintLifecycleService()
        initiated_by = str(getattr(session, "initiated_by_user_id", "") or "") or "system"
        if not current:
            await lifecycle.transition(
                artifact,
                BlueprintStatus.RESEARCHING,
                initiated_by_user_id=initiated_by,
                session=session,
            )
        await lifecycle.transition(
            artifact,
            BlueprintStatus.DRAFTING,
            initiated_by_user_id=initiated_by,
            session=session,
        )
    except Exception as exc:  # noqa: BLE001 — 状态映射是展示面，绝不阻断 stage 推进
        logger.warning(
            "blueprint_stage_drafting_map_skipped",
            category="sampling",
            component="process_runtime",
            session_id=str(getattr(session, "id", "")),
            current_stage=str(getattr(session, "current_stage", "")),
            error=str(exc),
        )


async def _abp_has_open_blocking_threads(session: Any) -> bool:
    """该会话蓝图是否仍有 open+blocking 线程（决定 stage 是否停在 needs_clarification）。

    探测失败按 **False** 处理（放行推进）：续驱侧 ``blueprint_resume`` 自己有一道
    fail-closed 的同款探测，这里再 fail-closed 会让 DB 抖动直接把 stage 钉死在澄清态。
    """
    from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService

    try:
        artifact = await _abp_load_artifact(session)
        if artifact is None:
            return False
        return bool(await BlueprintLifecycleService().ahas_open_blocking_threads(artifact))
    except Exception:  # noqa: BLE001 — 探测失败放行（续驱侧另有 fail-closed 判据）
        return False


async def _h_bp_repo_plan(session: Any, engine: Any) -> StageOutcome:
    """repo_plan stage（阶段 2 分仓方案）：按波次派发 direct 容器 / 合成 indirect。

    **自写完成判据**：调 ``adapter.aall_repo_plans_ready``（读各仓 ``PartialPlan`` 有无
    ``repo_plan`` 段），**绝不复用** ``aall_research_tasks_terminal`` —— 阶段 1 与阶段 2
    共用同一 ``RepoResearchTask``，派发前的 ``mark_stale`` 会让「全部终态」类判据短暂为
    假，两 stage barrier 同源即互相打断（113-RESEARCH OQ-2）。

    **barrier 续驱**：每次进入清一次超龄 waiter 并把清出的仓重派（113-04 只提供方法，
    挂载点在此）—— 不清的话「等的 key 永远不出现」的仓会永久卡住整个会话。

    ⭐ 进入本 stage 即把蓝图状态转 ``drafting``（B3，经 lifecycle service，幂等 +
    best-effort）。event 走**三元白名单**，不透传 adapter 的返回值。
    """
    from services.process_runtime.blueprint_repo_plan import STAGE_STATE_KEY

    adapter = getattr(getattr(engine, "deps", None), "repo_plan", None)
    if adapter is None:
        return StageOutcome(event="plan_dispatched")

    await _abp_mark_drafting(session)

    prearrange = await adapter.aplan_waves(session)
    prearrange = prearrange if isinstance(prearrange, dict) else {}
    result = await adapter.dispatch_plans(session)
    result = result if isinstance(result, dict) else {}

    # waiter 回收与重派（best-effort：清理失败不该把 stage 打成 failed）
    try:
        expired = await adapter.aexpire_stale_waiters(session)
        if expired:
            await adapter.aredispatch_waiting_repos(session, expired)
    except Exception as exc:  # noqa: BLE001 — waiter 维护不反噬 barrier
        logger.warning(
            "blueprint_repo_plan_waiter_maintenance_skipped",
            category="sampling",
            component="process_runtime",
            session_id=str(getattr(session, "id", "")),
            error=str(exc),
        )

    plans = await adapter.acollect_repo_plans(session)
    ready = await adapter.aall_repo_plans_ready(session)
    completed = set(result.get("completed") or [])
    # 本轮尚未产出 repo_plan 段的仓：`dispatch_plans` 的 `pending` 是计数不是清单，故由
    # 「锁定仓集 - 已完成集」推出（`build_stage_state` 内部还会再减去 ready 集）。
    outstanding = [rid for rid in (result.get("repositories") or []) if rid not in completed]
    stage_state = adapter.build_stage_state(
        plans=plans if isinstance(plans, dict) else {},
        dispatched=outstanding,
        pending=outstanding,
        waves=prearrange.get("stage_state_summary"),
    )

    if await _abp_has_open_blocking_threads(session):
        event = "needs_clarification"
    else:
        event = "plan_complete" if ready else "plan_dispatched"
    # 绝不写半截键：摘要为空时整体不写（半截 `repo_plan` 键会让下游把「没派发」
    # 误当成「派发了但零产出」）。
    return StageOutcome(
        event=event,
        stage_state_update={STAGE_STATE_KEY: stage_state} if stage_state else None,
    )


async def _h_bp_merge(session: Any, engine: Any) -> StageOutcome:
    """merge stage（阶段 3 融合装配）：六段装配 + 强制门 + 归因回退。

    ⭐ **本蓝图链首个回填 ``StageOutcome.current_artifact_version`` 的 handler**（阶段
    0/1 的 stage 都不产主产物版本）。⭐ 进入即把蓝图状态转 ``drafting``（B3）。

    出边映射是**白名单**（adapter 的 ``validation_status`` 再怪也只能落到已登记 event，
    否则 engine 直接 ``ValueError``）：

    - ``passed`` / ``exhausted`` → ``merged``（⇒ stage 终态）。**``exhausted`` 也走
      ``merged``**：超界是「蓝图已成形但引用覆盖率未达标、待人审」，不是流程失败；
      版本已落、未决项已进 ``stage_state``，绝不落 failed 终态（OQ-3 / T-113-37）。
    - ``retry`` → ``repo_rework``（单仓证据缺口回该仓 ``repo_plan``）或 ``remerge``。
    - 其余（``needs_clarification`` / ``failed`` / 未知值）→ ``needs_clarification``，
      停在本 stage 等澄清或重试。

    **D-W4（登记在案的纪律例外）**：``deps.merge`` 缺失时返回 ``needs_clarification``，
    而不是像其它 handler 那样返回「本 stage 的良性推进 event」。三条备选的取舍：

    - 返 ``remerge`` → transitions 指回 ``merge`` 自身 ⇒ **引擎自旋**（每次 advance 重进
      同一 handler、依赖仍缺、永不收敛，且每轮都写事件）。
    - 返 ``merged`` → 直达 stage 终态 ⇒ **假装成功**：零蓝图产出、
      ``current_artifact_version`` 为空，却把会话判成完成，114 会拿到空输入 ——
      这是最坏的静默失败。
    - 返 ``needs_clarification`` → 停在 ``merge`` 且 ``wait_status =
      waiting_clarification``，人工可见、可处置、可续驱，语义与「融合能力未就位」一致。
    """
    adapter = getattr(getattr(engine, "deps", None), "merge", None)
    if adapter is None:
        return StageOutcome(event="needs_clarification")

    await _abp_mark_drafting(session)

    result = await adapter.merge(session)
    result = result if isinstance(result, dict) else {}
    status = str(result.get("validation_status") or "")
    stage_state_update = result.get("stage_state") or None

    if status in ("passed", "exhausted"):
        return StageOutcome(
            event="merged",
            stage_state_update=stage_state_update,
            current_artifact_version=result.get("artifact_version_id") or None,
        )
    if status == "retry":
        event = "repo_rework" if str(result.get("back_target") or "") == "repo_plan" else "remerge"
        return StageOutcome(event=event, stage_state_update=stage_state_update)
    return StageOutcome(event="needs_clarification", stage_state_update=stage_state_update)


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
            # 113 接续点**已接续**（113-06）：阶段 1 出口硬门通过后进阶段 2 分仓方案。
            # 下一个接续点在 merge.merged（见该 stage 的注释）。
            "confirmed": "repo_plan",
        },
        pausable=True,
        wait_status="waiting_clarification",
    ),
    # ── 阶段 2/3（Phase 113-06 追加；上面七个 stage 一字未动）──────────────
    "repo_plan": StageDef(
        key="repo_plan",
        handler=_h_bp_repo_plan,
        transitions={
            # 波次推进：当前波次派完后 self-loop 挂 waiting_event 等容器回调，
            # barrier 续驱再进本 handler 时下一波自然变成「当前波次」。
            "plan_dispatched": "repo_plan",
            "plan_complete": "merge",
            # 有 open+blocking 线程时停在本 stage 等人处置（不推进也不失败）。
            "needs_clarification": "repo_plan",
        },
        pausable=True,
        wait_status="waiting_event",
    ),
    "merge": StageDef(
        key="merge",
        handler=_h_bp_merge,
        transitions={
            # 114 接续点：追加 ai_review stage 时把该值改为 "ai_review" 即可
            # （transitions 是数据，无需改 engine——与 112-05 留给 113 的形状一致）。
            # ⚠️ 覆盖率超界也走这条边（handler 把 exhausted 映射成 merged）：超界是
            # 「待人审」不是「流程失败」，本 stage 的 transitions **不含 failed 出边**。
            "merged": STAGE_DONE,
            "repo_rework": "repo_plan",
            "remerge": "merge",
            "needs_clarification": "merge",
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
