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

import json
from typing import Any

import structlog

from common.logging import redact_secrets_in_text
from delivery.artifacts.registry import register_artifact_type
from delivery.services.event_taxonomy import (
    EVENT_FEATURE_CLASSIFIED,
    EVENT_KNOWLEDGE_RECALLING,
    EVENT_REPO_ROUTING,
)
from interactions.redaction import redact_for_ledger
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


def _routing_snapshot_payload(routing: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    """组装 repo.routing 完整快照 payload（ROUTE-09，RESEARCH Pattern 3 形状）。

    候选（含 score/breakdown）取自 ``snapshot["candidates"]``（router ``to_dict``
    产物），stage0/stage1/versions 原样透传；router_version/degraded/auto_selected
    取自 adapter 精简 dict。整体经 ``redact_for_ledger`` 脱敏后返回（T-105-15）；
    payload 序列化后 < 64KB 由 snapshot node_hits 最小字段集保证（T-105-16）。
    """
    snap_candidates = snapshot.get("candidates") or []
    payload: dict[str, Any] = {
        "candidates": [
            {
                "repo_id": c.get("repo_id"),
                "confidence": c.get("confidence"),
                "score": c.get("score"),
                "breakdown": c.get("breakdown") or {},
            }
            for c in snap_candidates
            if isinstance(c, dict)
        ],
        "router_version": routing.get("router_version", ""),
        "degraded": bool(routing.get("degraded", False)),
        # RELY-03：降级**原因**与 degraded 同批出参。少了它，编排链路上的降级提示
        # 只能说「本次未经 LLM 推理」而说不出为什么——受控闭集里的六个值本身就是
        # 给用户看的（``classify_degrade_reason``），留在 trace 里等于没有。
        "degrade_reason": str(routing.get("degrade_reason") or ""),
        "auto_selected": bool(routing.get("auto_selected", False)),
        "stage0": snapshot.get("stage0") or {},
        "stage1": snapshot.get("stage1") or {},
        "versions": snapshot.get("versions") or {},
    }
    # Phase 106 新节（106-07 replay 的回放材料）：weight_config 生效全值 +
    # per-候选 repo_meta——仅在 router 产出时透传（legacy 快照不加空节），
    # 同样整体经 redact_for_ledger 脱敏（T-106-15）。
    for extra_key in ("weight_config", "repo_meta"):
        if isinstance(snapshot.get(extra_key), dict):
            payload[extra_key] = snapshot[extra_key]
    return redact_for_ledger(payload)


async def _h_route(session: Any, engine: Any) -> StageOutcome:
    """路由 stage：调注入 router 取候选仓 → 落 stage_state.routing + emit repo.routing。

    快照落盘（ROUTE-09）：router 结果携带 ``snapshot`` 材料（stage0 输入 + 脱敏
    stage1 材料 + 每候选 breakdown + 版本四元组）时，组装完整快照 payload 经
    ``_emit_event`` 写入——复用既有 ``repo.routing`` 事件名（event taxonomy 零改动，
    写入单一入口 INV-6）。snapshot 缺失（skipped / stub router / v1_fallback 无
    stage0 材料）时保持现状精简 payload（best-effort，绝不阻断编排）。
    ``snapshot`` 键在 routing 落库前剔除——session.routing 保持精简。
    """
    result = await engine.deps.router.route(session)
    routing = result if isinstance(result, dict) else {}
    # snapshot 仅供组快照 payload——落 stage_state 前 pop 剔除，防 session.routing 膨胀
    snapshot = routing.pop("snapshot", None)
    candidates = routing.get("candidates") or []
    trace: dict[str, Any] = {
        "candidates": [
            {"repo_id": c.get("repo_id"), "confidence": c.get("confidence")} for c in candidates
        ],
        # RELY-03：降级三键在**精简 payload 上也必须在场**。快照分支的门是
        # ``snapshot["stage0"]`` 非空，而 v1_fallback 的 snapshot 只有 stage1
        # （``codegraph/services/repo_router_v2.py:1847``）、skipped 与 stub router
        # 根本没有 snapshot ——三者全部落到这条精简分支。键缺失时前端的
        # ``payload.degraded === true`` 恒为假，于是「降级」这个事实恰好在
        # **真降级**的 v1_fallback 上永不出现。补键而不是让前端按 router_version
        # 猜：降级是后端算好的事实，前端不推断（与 110-05 的既有纪律一致）。
        "router_version": str(routing.get("router_version") or ""),
        "degraded": bool(routing.get("degraded", False)),
        "degrade_reason": str(routing.get("degrade_reason") or ""),
    }
    if isinstance(snapshot, dict) and snapshot.get("stage0"):
        trace = _routing_snapshot_payload(routing, snapshot)
        try:  # 观测 best-effort（LOGGING-SPEC）：payload 组装完成记大小，绝不反噬编排
            logger.debug(
                "repo_router_v2_snapshot_emitted",
                payload_bytes=len(json.dumps(trace, ensure_ascii=False).encode("utf-8")),
                degraded=trace.get("degraded", False),
                category="sampling",
                component="process_runtime",
            )
        except Exception:  # noqa: BLE001
            pass
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
    back_target = result.get("back_target", "clarify") if isinstance(result, dict) else "clarify"
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
    content = (
        raw
        if isinstance(raw, dict) and isinstance(raw.get("message"), str)
        else {"message": str((raw or {}).get("message", "")) if isinstance(raw, dict) else ""}
    )
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
    """intake stage：蓝图链的**生产起点** —— 建初始 ``Artifact`` + ``blueprint/v1`` v1 骨架。

    三件产出（落库全在 ``blueprint_intake.aseed_blueprint_artifact``，handler 只返
    ``StageOutcome`` —— 纪律②）：``ArtifactService.create`` 建 Artifact + v1 骨架、
    ``BlueprintLifecycleService`` 把 ``blueprint_status`` 跳 ``researching``（INV-6，形状
    照 :func:`_abp_mark_drafting`）、版本指针带回会话。

    ⭐ **``current_artifact_version`` 必须显式带回**（``engine.py:108-119``）：engine 只在
    非 None 时透传（无条件透传会把每次不产版本的转移都把指针抹成 NULL）⇒ handler 不带回
    就没有第二个人会带 ⇒ ``session.current_artifact_version_id`` 恒 None，
    ``blueprint_spec_gate._aload_current_version`` 取不到版本即判 ``needs_clarification``
    + ``blueprint_spec_gate_no_artifact_version`` warning，会话**卡死在 spec_gate**；
    ``_amap_blueprint_status`` 与两个 ``_aload_artifact`` 同时静默降级。

    **幂等**：会话已有 ``current_artifact_version_id``（重入 / 重放）⇒ 不重复建 artifact，
    直接把既有指针原样带回。

    ⛔ **本 handler 不抛**：engine 的通用 ``except`` 会把会话落 FAILED、抹掉可诊断信息。
    ``project_id`` 缺失（正常链路上不可能 —— ``start_blueprint_orchestration`` 已在建会话
    **之前**挡住）时**不建 artifact**、只落一条 caller 事件并**不带指针**返回，随后
    spec_gate 会因无版本而判需澄清 —— 那是正确的**可见**失败。
    """
    from services.process_runtime.blueprint_intake import aseed_blueprint_artifact

    existing = str(getattr(session, "current_artifact_version_id", "") or "")
    if existing:
        return StageOutcome(event="intaken", current_artifact_version=existing)

    decomposition = (session.stage_state or {}).get("decomposition") or {}
    initiated_by = str(getattr(session, "initiated_by_user_id", "") or "") or "system"
    project_id = str(decomposition.get("project_id") or "")
    if project_id:
        artifact = await aseed_blueprint_artifact(
            session=session,
            requirement_text=str(decomposition.get("requirement_text") or ""),
            project_id=project_id,
            title=str(decomposition.get("blueprint_title") or ""),
            created_by_user_id=str(getattr(session, "initiated_by_user_id", "") or ""),
        )
        return StageOutcome(
            event="intaken",
            current_artifact_version=artifact.current_version_id,
            # stage_state **只写自己的桶**（114-03 纪律：engine 顶层浅合并，写别人的桶会互相覆盖）。
            stage_state_update={"intake": {"artifact_id": str(artifact.id)}},
        )

    logger.warning(
        "blueprint_intake_missing_project",
        category="caller",
        component="process_runtime",
        session_id=str(getattr(session, "id", "")),
        reason="project_unresolved",
        initiated_by_user_id=initiated_by,
    )
    # ⛔ 不带指针：随后 spec_gate 因无版本判需澄清 —— 那是正确的**可见**失败。
    return StageOutcome(event="intaken")


async def _h_bp_decompose(session: Any, engine: Any) -> StageOutcome:
    """decompose stage：把需求拆成 ``requirement_spec.feature_points`` 并落新版本。

    两条路径（实现在 ``blueprint_intake.adecompose_feature_points``）：
    ``stage_state.decomposition.feature_segments`` 非空 ⇒ **直采、零 LLM**（feature list
    入口；确定性 id ⇒ 同一 segments 重跑得同一 ``content_hash`` ⇒ ``add_version`` 复用
    current、**不翻版本**）；否则走 LLM 并复用**已注册**的 ``CallSource.BLUEPRINT_DECOMPOSE``
    （⛔ 零新增枚举），LLM 不可得 ⇒ **fail-soft** 保留空 ``feature_points`` + warning，
    ⛔ 不落 FAILED（规格门本就会因信息不足而开澄清，那是正确的下一步）。

    ⭐ **三种分支都显式带回 ``current_artifact_version``**：产了新版本带新版本 id，
    没产版本带会话**既有**指针。engine 只在非 None 时透传（``engine.py:108-119``），
    统一带回让「本 stage 之后指针一定指向最新版本」成为可断言的事实，⛔ 不依赖读者去
    推断哪条分支会不会动指针。
    """
    from services.process_runtime.blueprint_intake import adecompose_feature_points

    artifact = await _abp_load_artifact(session)
    if artifact is not None:
        decomposition = (session.stage_state or {}).get("decomposition") or {}
        segments = decomposition.get("feature_segments")
        version = await adecompose_feature_points(
            session=session,
            artifact=artifact,
            requirement_text=str(decomposition.get("requirement_text") or ""),
            feature_segments=segments if isinstance(segments, list) else None,
        )
        if version is None:
            # 无新版本不等于「无规格」。直采幂等命中、内容 hash 未变化时，service 会返回
            # None；既有版本里仍可能已经有完整 requirement_spec。若这里只带回版本指针而不
            # 同步规格，后续调研 prompt 会把需求目标/功能点渲染成（无），最终让确认门只能
            # 展示仓库自身能力，无法解释「本需求的哪些功能点由该仓承载」。
            current_id = getattr(session, "current_artifact_version_id", None)
            from delivery.models import ArtifactVersion

            current = (
                await ArtifactVersion.objects.filter(id=current_id).afirst() if current_id else None
            )
            spec = (current.content or {}).get("requirement_spec") if current is not None else {}
            spec = spec if isinstance(spec, dict) else {}
            return StageOutcome(
                event="decomposed",
                current_artifact_version=current_id,
                stage_state_update={"requirement_spec": spec} if spec else None,
            )
        spec = (version.content or {}).get("requirement_spec") or {}
        # ⭐ 把 requirement_spec 快照同步挂进 stage_state 顶层：调研/拟方案容器的 prompt
        # 经 `_requirement_spec_from_state`（blueprint_research_adapter）读的就是这里——
        # 只写计数不写本体时，容器 prompt 的「需求目标/功能点」恒为（无），agent 只能盲评
        # （实测四仓调研全返 partial + 空结论）。规格门锁定后会用澄清后的规格覆盖本快照。
        return StageOutcome(
            event="decomposed",
            current_artifact_version=version.id,
            stage_state_update={
                "decompose": {
                    "point_count": len(spec.get("feature_points") or []),
                    "version_no": int(version.version_no),
                },
                **({"requirement_spec": spec} if spec else {}),
            },
        )

    # intake 未落产物（project_id 缺失分支）⇒ 原样穿过，⛔ 不写半截 stage_state。
    return StageOutcome(event="decomposed")


async def _h_bp_spec_gate(session: Any, engine: Any) -> StageOutcome:
    """spec_gate stage：跑 112-02 的规格门 adapter，按其 ``event`` 决定转移。

    ⭐ 116 重排后位于 ``repo_confirmation`` 之后：澄清带着调研结论问。
    ``needs_clarification`` → self-loop 挂起（``waiting_clarification``）；
    ``spec_locked`` → 进 repo_plan。deps 未注入时 pass-through 放行（不把未接线当成需澄清）。
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

    ⭐ **deps 类型身份自检（116-01）**：``research`` 是两个工厂唯一同名的两个 dep 之一 ⇒
    用错工厂时这里拿到的是旧链的 ``ResearchDispatchAdapter``。它有 ``dispatch``、也不抛，
    会一路穿到 ``reroute`` 撞 ``AttributeError: 'ResearchDispatchAdapter' object has no
    attribute 'aadvance_reroute'`` 落 FAILED（Wave 0 探针实测）。自检把这条静默污染拦在
    第一步：``needs_clarification`` 出边 + 阻塞线程，人工可见可处置。
    """
    from services.process_runtime.research_aggregation import aall_research_tasks_terminal

    adapter = getattr(getattr(engine, "deps", None), "research", None)
    if adapter is None:
        return StageOutcome(event="research_complete")
    # 类型身份自检（116-01）：不是蓝图 research adapter ⇒ 落 blueprint_stage_wrong_adapter
    # + 阻塞线程 + needs_clarification 出边，⛔ 绝不把旧链 adapter 跑起来。
    if _abp_dep_is_foreign_adapter(adapter, *_BP_RESEARCH_ADAPTER):
        return await _abp_reject_wrong_adapter(session, adapter, stage="repo_research")
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
            error=redact_secrets_in_text(str(exc)),
        )


async def _abp_mark_ai_reviewing(session: Any) -> None:
    """把蓝图状态转 ``ai_reviewing``（阶段 4 的状态口径，114-03）；已是该态则跳过（幂等）。

    与 :func:`_abp_mark_drafting` 的差异点：合法边**只有** ``DRAFTING → AI_REVIEWING``
    （``blueprint_lifecycle_service.py:89-121``），故当前态不是 ``drafting`` 时**先补一跳
    ``drafting``**（``""`` 时 :func:`_abp_mark_drafting` 内部会再先补 ``researching``），
    复用它完成全部前置。状态映射是展示面，失败绝不阻断 stage 推进。
    """
    from delivery.models import BlueprintStatus
    from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService

    try:
        artifact = await _abp_load_artifact(session)
        if artifact is None:
            return
        if str(artifact.blueprint_status or "") == BlueprintStatus.AI_REVIEWING:
            return
        if str(artifact.blueprint_status or "") != BlueprintStatus.DRAFTING:
            await _abp_mark_drafting(session)
            await artifact.arefresh_from_db()
            if str(artifact.blueprint_status or "") != BlueprintStatus.DRAFTING:
                return
        await BlueprintLifecycleService().transition(
            artifact,
            BlueprintStatus.AI_REVIEWING,
            initiated_by_user_id=str(getattr(session, "initiated_by_user_id", "") or "")
            or "system",
            session=session,
        )
    except Exception as exc:  # noqa: BLE001 — 状态映射是展示面，绝不阻断 stage 推进
        logger.warning(
            "blueprint_stage_ai_reviewing_map_skipped",
            category="sampling",
            component="process_runtime",
            session_id=str(getattr(session, "id", "")),
            current_stage=str(getattr(session, "current_stage", "")),
            error=redact_secrets_in_text(str(exc)),
        )


async def _abp_has_open_blocking_threads(session: Any) -> bool:
    """该会话蓝图是否仍有 repo_plan 阶段的 open+blocking 线程。

    探测失败按 **False** 处理（放行推进）：续驱侧 ``blueprint_resume`` 自己有一道
    fail-closed 的同款探测，这里再 fail-closed 会让 DB 抖动直接把 stage 钉死在澄清态。

    必须按 ``return_stage=repo_plan`` 收窄：重跑仓级方案时，上一轮 AI 审查留下的 BLOCKER
    正是本轮要修复的输入，若按全 Artifact 查询，它会反过来阻止 repo_plan 开始/完成。
    """
    from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService

    try:
        artifact = await _abp_load_artifact(session)
        if artifact is None:
            return False
        return bool(
            await BlueprintLifecycleService().ahas_open_blocking_threads(
                artifact,
                return_stage="repo_plan",
            )
        )
    except Exception:  # noqa: BLE001 — 探测失败放行（续驱侧另有 fail-closed 判据）
        return False


async def _abp_ensure_blocking_clarification(session: Any, *, stage: str, reason: str) -> None:
    """确保该蓝图上存在 open+blocking 澄清线程（有则不叠开，幂等）。

    ⚠️ **这是「绝不静默失败」的最后一道防线**：``needs_clarification`` 是 self-loop 出边，
    而续驱 helper 只在「有 open+blocking 线程」时才在 ``waiting_clarification`` 上短路。
    handler 返回 ``needs_clarification`` 却没有线程 ⇒ 续驱一路 advance 到 ``max_steps``
    ⇒ 会话被落 ``advance_step_limit`` **FAILED** —— 明明只是「缺条件、等人处置」，却成了
    流程失败，蓝图成果一起报废。

    ``return_stage`` 传本 stage（B3）：漏传会让人审恢复后退回阶段 1。问题文本只含 stage 名
    与**枚举化的 reason**，绝不夹带方案正文（T-113-42）。
    """
    from delivery.models import BlueprintThread, ThreadKind, ThreadStatus
    from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService

    try:
        artifact = await _abp_load_artifact(session)
        if artifact is None:
            return
        exists = await BlueprintThread.objects.filter(
            artifact_id=artifact.id, blocking=True, status=ThreadStatus.OPEN
        ).aexists()
        if exists:
            return
        await BlueprintLifecycleService().open_thread(
            artifact,
            kind=ThreadKind.AI_CLARIFICATION,
            blocking=True,
            question=(
                f"自动推进在 {stage} 阶段停下了（原因：{reason or 'unknown'}），"
                "需要你处置后再继续。"
            ),
            initiated_by_user_id=str(getattr(session, "initiated_by_user_id", "") or "")
            or "system",
            return_stage=stage,
        )
    except Exception as exc:  # noqa: BLE001 — 开不出线程也不上抛（stage 仍停在原地）
        logger.warning(
            "blueprint_stage_clarification_open_failed",
            category="caller",
            component="process_runtime",
            session_id=str(getattr(session, "id", "")),
            stage=stage,
            initiated_by_user_id=str(getattr(session, "initiated_by_user_id", "") or "")
            or "system",
            error=redact_secrets_in_text(str(exc)),
        )


# ── deps 类型身份自检（116-01，T-116-03）─────────────────────────────────────
#
# 两个 engine 工厂的 deps 名单有**两个同名属性**：`research` 与 `merge`
# （`entrypoint.py:128-137` vs `:173-181`），而十个 `_h_bp_*` 一律 `getattr(..., name, None)`
# 软取 ⇒ 用错工厂**不会报错**。最坏形态是 `ArchitectMergeAdapter.merge` 经
# `ArtifactService.create` 往蓝图会话落一份 **v0 形状 content**
# （`architect_merge_adapter.py:252-259`），把产物指针钉到一份非 `blueprint/v1` 的版本上
# —— 同时废掉 SC-3 的渲染判别与 SC-4 的入图门控，且全程无异常。
#
# ⭐ 判据是**类型身份**（`__module__` + `__name__`）而不是「有没有某个方法」：后者会被
# 鸭子类型绕过，且 `ResearchDispatchAdapter` 恰好也有 `dispatch`。
#
# ⚠️ 判据的作用域**限定在 `services.process_runtime` 自己拥有的类型**：本包内的任何
# 「不是本 stage 期望的那个 adapter」一律拒（含将来新增的第三个 adapter，比两项黑名单更
# 严），而包外对象（既有 handler 用例的 `SimpleNamespace` / `AsyncMock` 替身）维持既有
# pass-through 语义不变 —— 那些用例文件在本相位的 §13.2 边界之外，不得改动。
_PROCESS_RUNTIME_PKG = "services.process_runtime."
_BP_RESEARCH_ADAPTER = (
    "services.process_runtime.blueprint_research_adapter",
    "BlueprintResearchAdapter",
)
_BP_MERGE_ADAPTER = ("services.process_runtime.blueprint_merge", "BlueprintMergeAdapter")


def _abp_dep_is(dep: Any, expected_module: str, expected_name: str) -> bool:
    """dep 的类型身份是否恰为 ``expected_module.expected_name``。

    用 ``type(dep).__module__`` / ``__name__`` 而不是 ``isinstance`` + 顶层 import：本文件
    的既有纪律是重依赖一律懒 import，991 行的 handler 模块不该为两个自检把两个重型
    adapter 提到模块级。
    """
    cls = type(dep)
    return (
        str(getattr(cls, "__module__", "")) == expected_module
        and str(getattr(cls, "__name__", "")) == expected_name
    )


def _abp_dep_is_foreign_adapter(dep: Any, expected_module: str, expected_name: str) -> bool:
    """dep 是否是本包里**另一个** adapter（= 调用方用错了 engine 工厂）。"""
    if dep is None or _abp_dep_is(dep, expected_module, expected_name):
        return False
    return str(getattr(type(dep), "__module__", "")).startswith(_PROCESS_RUNTIME_PKG)


async def _abp_reject_wrong_adapter(session: Any, dep: Any, *, stage: str) -> StageOutcome:
    """自检不通过的统一出口：响亮事件 + 阻塞线程 + ``needs_clarification`` 出边。

    ⛔ **绝不把旧链 adapter 跑起来**。事件只记三个标量（``session_id`` / ``stage`` /
    ``got``）——本文件在 ``test_blueprint_log_redaction_guard._SCANNED_MODULES`` 十二项之内，
    ⛔ 不得出现任何异常文本实参。
    """
    logger.warning(
        "blueprint_stage_wrong_adapter",
        category="caller",
        component="process_runtime",
        session_id=str(getattr(session, "id", "")),
        stage=stage,
        got=type(dep).__name__,
    )
    await _abp_ensure_blocking_clarification(session, stage=stage, reason="wrong_adapter")
    return StageOutcome(event="needs_clarification")


async def _abp_repo_plan_is_stuck(session: Any, result: dict) -> bool:
    """本轮一个仓也没动、且没有在途调研容器 ⇒ 再 advance 一次也不会有进展。

    ⚠️ ``aall_research_tasks_terminal`` 在此**只作「有无在途容器」的活性探测**，
    绝不是阶段 2 的完成判据（那条是 ``aall_repo_plans_ready``，读 ``repo_plan`` 段的
    存在性）—— 两 stage 共用同一 ``RepoResearchTask``，把它当完成判据会被
    ``mark_stale`` 打成短暂为假（OQ-2）。
    """
    from services.process_runtime import aall_research_tasks_terminal

    if int(result.get("dispatched") or 0) or int(result.get("synthesized") or 0):
        return False
    try:
        return bool(await aall_research_tasks_terminal(getattr(session, "id", None)))
    except Exception:  # noqa: BLE001 — 探测失败按「有在途」处理（宁可多等一轮，不误开线程）
        return False


async def _h_bp_repo_plan(session: Any, engine: Any) -> StageOutcome:
    """repo_plan stage（阶段 2 分仓方案）：按波次派发 direct 容器 / 合成 indirect。

    **自写完成判据**：调 ``adapter.aall_repo_plans_ready``（读各仓 ``PartialPlan`` 有无
    ``repo_plan`` 段），**绝不复用** ``aall_research_tasks_terminal`` —— 阶段 1 与阶段 2
    共用同一 ``RepoResearchTask``，派发前的 ``mark_stale`` 会让「全部终态」类判据短暂为
    假，两 stage barrier 同源即互相打断（113-RESEARCH OQ-2）。

    **barrier 续驱**：每次进入清一次超龄 waiter 并把清出的仓重派（113-04 只提供方法，
    挂载点在此）—— 不清的话「等的 key 永远不出现」的仓会永久卡住整个会话。全波容器都以
    ``waiting_context`` 退出时本 handler 不可达，那条死路由回调侧的
    ``callbacks._amaintain_blueprint_waiters`` 兜（MJ-03）。

    ⭐ **阻塞线程探测在最前**（MN-06 + MJ-02 门控）：有 open+blocking 线程时整轮**不 mark
    drafting、不派发**直接返回 ``needs_clarification`` —— ① 先刷 ``drafting`` 再返回
    ``needs_clarification`` 会让展示态与语义矛盾（用户看到「起草中」，其实在等他回答）；
    ② 互等环/连续失败已交人裁决，此时重派只会再撞同一个环并烧容器额度，「裁决前不重派」
    必须是**显式门控**而不是让 task 卡在非终态来物理阻止（MJ-02）。

    ⭐ 通过门控后即把蓝图状态转 ``drafting``（B3，经 lifecycle service，幂等 +
    best-effort）。event 走**三元白名单**，不透传 adapter 的返回值。

    **依赖缺失出口与 ``_h_bp_merge`` 对齐**（MN-07）：``deps.repo_plan`` 缺失时返回
    ``plan_dispatched`` 会 self-loop 回本 stage 且 ``wait_status="waiting_event"``，但没有
    任何容器被派出、也没有阻塞线程 ⇒ 会话静默挂在等事件态（正是 ``_h_bp_merge`` 的 D-W4
    逐条论证否掉的形态）。改为先确保有阻塞线程再返 ``needs_clarification``。
    """
    from services.process_runtime.blueprint_repo_plan import STAGE_STATE_KEY

    adapter = getattr(getattr(engine, "deps", None), "repo_plan", None)
    if adapter is None:
        await _abp_ensure_blocking_clarification(
            session, stage="repo_plan", reason="deps_unavailable"
        )
        return StageOutcome(event="needs_clarification")

    if await _abp_has_open_blocking_threads(session):
        return StageOutcome(event="needs_clarification")

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
            error=redact_secrets_in_text(str(exc)),
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
    elif ready:
        event = "plan_complete"
    elif await _abp_repo_plan_is_stuck(session, result):
        # 一个仓也没派出去、也没有在途容器、判据又不满足 ⇒ 再 advance 一次结果一样。
        # 不拦下来的话 `plan_dispatched` self-loop 会被续驱推到步数上限然后落 FAILED。
        await _abp_ensure_blocking_clarification(
            session, stage="repo_plan", reason="no_dispatchable_repo_plan"
        )
        event = "needs_clarification"
    else:
        event = "plan_dispatched"
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

    ⭐ **deps 类型身份自检（116-01，T-116-03 的唯一手段）**：``merge`` 是两个工厂唯一同名的
    两个 dep 之二 ⇒ 用错工厂时这里拿到的是 ``ArchitectMergeAdapter``，它的 ``_handle_pass``
    会经 ``ArtifactService.create(ARTIFACT_TYPE_TECHNICAL_PLAN, merged, ...)``
    （``architect_merge_adapter.py:252-259``）往**蓝图会话**落一份 v0 形状 content 并回传
    ``artifact_version_id``，本 handler 据此把 ``current_artifact_version`` 钉到一份非
    ``blueprint/v1`` 的版本上 —— 同时废掉 SC-3 的渲染判别与 SC-4 的入图门控，且全程无异常。
    自检是唯一能挡住这条的手段：⛔ **绝不把旧链 adapter 跑起来**。
    """
    adapter = getattr(getattr(engine, "deps", None), "merge", None)
    if adapter is None:
        return StageOutcome(event="needs_clarification")
    # 类型身份自检（116-01）：不是蓝图 merge adapter ⇒ 落 blueprint_stage_wrong_adapter
    # + 阻塞线程 + needs_clarification 出边。这是唯一能挡住 ArchitectMergeAdapter 往蓝图
    # 会话落一份 v0 形状 content 的手段（architect_merge_adapter.py:252-259）。
    if _abp_dep_is_foreign_adapter(adapter, *_BP_MERGE_ADAPTER):
        return await _abp_reject_wrong_adapter(session, adapter, stage="merge")

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
    # 停在 merge 前先确保有阻塞线程：没有线程的 needs_clarification self-loop 会被续驱
    # 一路 advance 到步数上限，然后落 FAILED（见 `_abp_ensure_blocking_clarification`）。
    await _abp_ensure_blocking_clarification(
        session,
        stage="merge",
        reason=str((result.get("report") or {}).get("reason") or status or "merge_incomplete"),
    )
    return StageOutcome(event="needs_clarification", stage_state_update=stage_state_update)


async def _h_bp_ai_review(session: Any, engine: Any) -> StageOutcome:
    """ai_review stage（阶段 4 AI 对抗审查）：判定内核 → 分级线程 → 有界回退 / 升人审。

    ⭐ 进入即把蓝图状态转 ``ai_reviewing``（经 lifecycle，幂等 + best-effort）。

    出边映射是**白名单**（adapter 的 ``review_status`` 再怪也只能落到已登记 event，
    否则 engine 直接 ``ValueError``）：

    - ``passed`` / ``exhausted`` → ``review_passed`` / ``review_exhausted``（⇒ stage
      终态）。**``exhausted`` 也走终态**：超界是「蓝图已成形但审查未清、待人审」，不是
      流程失败；未决清单已进 ``stage_state``，**绝不落 failed 终态**（与 merge 同纪律）。
    - ``retry`` → ``repo_rework``（仓级 BLOCKER 回该仓 ``repo_plan``）或 ``remerge``。
    - 其余（``needs_clarification`` / 未知值）→ ``needs_clarification``，停在本 stage。

    **D-W4 同款（依赖缺失出口）**：``deps.review`` 缺失时返回 ``needs_clarification``，
    而不是本 stage 的良性推进 event。三条备选的取舍：

    - 返 ``needs_clarification`` **但不建线程** → transitions 指回 ``ai_review`` 自身
      ⇒ **引擎自旋**：续驱每次 advance 重进同一 handler、依赖仍缺，被推到 ``max_steps``
      后落 FAILED（明明只是「审查能力未就位」，蓝图成果却一起报废）。
    - 返 ``review_passed`` → 直达 stage 终态 ⇒ **假装成功**：零 findings 落库、蓝图未过
      审却被判「待人审通过」，人审面板上看不到任何 finding —— 这是最坏的静默失败。
    - 返 ``needs_clarification`` **且先 ensure 阻塞线程** → 停在 ``ai_review`` 且
      ``wait_status = waiting_clarification``，人工可见、可处置、可续驱，语义与「审查
      未完成」一致。**本 handler 取第三条**。
    """
    adapter = getattr(getattr(engine, "deps", None), "review", None)
    if adapter is None:
        await _abp_ensure_blocking_clarification(
            session, stage="ai_review", reason="deps_unavailable"
        )
        return StageOutcome(event="needs_clarification")

    await _abp_mark_ai_reviewing(session)

    result = await adapter.review(session)
    result = result if isinstance(result, dict) else {}
    status = str(result.get("review_status") or "")
    # 绝不写半截键：stage_state 为空时传 None（半截键会让下游把「没审」误当成「审了但空」）。
    stage_state_update = result.get("stage_state") or None

    if status == "passed":
        return StageOutcome(
            event="review_passed",
            stage_state_update=stage_state_update,
            current_artifact_version=result.get("artifact_version_id") or None,
        )
    if status == "exhausted":
        return StageOutcome(
            event="review_exhausted",
            stage_state_update=stage_state_update,
            current_artifact_version=result.get("artifact_version_id") or None,
        )
    if status == "retry":
        event = "repo_rework" if str(result.get("back_target") or "") == "repo_plan" else "remerge"
        return StageOutcome(event=event, stage_state_update=stage_state_update)
    # 停在 ai_review 前先确保有阻塞线程：没有线程的 needs_clarification self-loop 会被
    # 续驱一路 advance 到步数上限，然后落 FAILED（见 `_abp_ensure_blocking_clarification`）。
    await _abp_ensure_blocking_clarification(
        session,
        stage="ai_review",
        reason=str((result.get("report") or {}).get("reason") or status or "review_incomplete"),
    )
    return StageOutcome(event="needs_clarification", stage_state_update=stage_state_update)


_TECHNICAL_BLUEPRINT_STAGES = {
    "intake": StageDef(
        key="intake",
        handler=_h_bp_intake,
        transitions={"intaken": "decompose"},
    ),
    # ⭐ 流程重排（116 用户裁定）：拆解后**直接进路由调研**，规格门（澄清）挪到
    # 仓库集确认门**之后** —— 澄清带着调研结论问（而不是两眼一抹黑先问一轮），
    # 用户在确认门修正完仓库集、答完澄清才进入分仓方案。
    # 依赖上是安全的：路由只吃 feature_points[].intent，而 decompose 两条路径都已写入
    # 合法枚举值（`blueprint_intake._normalize_intent`），不需要规格门先跑。
    "decompose": StageDef(
        key="decompose",
        handler=_h_bp_decompose,
        transitions={"decomposed": "route"},
    ),
    # 规格门现位于 repo_confirmation → repo_plan 之间（定义顺序不影响 engine，仅为可读性）。
    "spec_gate": StageDef(
        key="spec_gate",
        handler=_h_bp_spec_gate,
        transitions={"spec_locked": "repo_plan", "needs_clarification": "spec_gate"},
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
            # 116-01 追加（deps 类型身份自检的落点）：拿到旧链 adapter 时停在本 stage 等
            # 人处置。⚠️ 未登记的 event 会让 `transition` 直接 raise ValueError 冲出
            # engine 的 handler try 块、打穿续驱器与 REST —— 自检必须有登记的出边才成立。
            "needs_clarification": "repo_research",
        },
        pausable=True,
        wait_status="waiting_event",
        event_wait_statuses={"needs_clarification": "waiting_clarification"},
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
            # ⭐ 116 重排：确认门通过后先过规格门（带调研上下文的澄清），
            # spec_locked 才进阶段 2 分仓方案。下一个接续点在 merge.merged。
            "confirmed": "spec_gate",
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
        event_wait_statuses={"needs_clarification": "waiting_clarification"},
    ),
    "merge": StageDef(
        key="merge",
        handler=_h_bp_merge,
        transitions={
            # 114 接续点**已接续**（114-03）：融合完成先过 AI 对抗审查再升人审
            # （transitions 是数据，无需改 engine——与 112-05 留给 113 的形状一致）。
            # ⚠️ 覆盖率超界也走这条边（handler 把 exhausted 映射成 merged）：超界是
            # 「待人审」不是「流程失败」，本 stage 的 transitions **不含 failed 出边**。
            "merged": "ai_review",
            "repo_rework": "repo_plan",
            "remerge": "merge",
            "needs_clarification": "merge",
        },
        pausable=True,
        wait_status="waiting_clarification",
    ),
    # ── 阶段 4 AI 对抗审查（Phase 114-03 追加；上面九个 stage 除 merge.merged 一行外一字未动）──
    "ai_review": StageDef(
        key="ai_review",
        handler=_h_bp_ai_review,
        # ⚠️ **不含 `failed` 出边**——与 `merge` 同纪律：超界是「待人审」不是「流程失败」。
        transitions={
            "review_passed": STAGE_DONE,  # 全清 / 仅 WARNING+INFO → pending_review
            "review_exhausted": STAGE_DONE,  # 超 max_rounds 轮 → pending_review 携未决 BLOCKER
            "repo_rework": "repo_plan",  # 仓级 BLOCKER 归因打回
            "remerge": "merge",  # 融合级 BLOCKER 打回
            "needs_clarification": "ai_review",  # self-loop 等澄清
        },
        pausable=True,
        wait_status="waiting_clarification",
    ),
}


# =============================== registration ================================

# ⭐ 旧 technical_plan process 的**退役标记**（同步点 2 收尾）。
#
# 116-01 落地时这里只是「退役观察期」的一段注释：旧链仍是四个入口的默认，本相位只
# 靠 `technical_plan_entry_used` 事件（按 entry_key 分桶，⛔ 不是 entrypoint）观察残余
# 流量。收口条件在同步点 2 才具备，现已兑现 —— `DEFAULT_ENTRY_SWITCH` 四键全部翻到
# `technical_blueprint`，**旧链不再是任何入口的默认**。
#
# ⛔ **退役 ≠ 注销**：定义仍然注册，且必须注册 ——
#   - 在途会话（升级前建的 `process_type="technical_plan"` 行）靠它续驱，注销即崩；
#   - 运维可把 `blueprint.entry.switch` 的某个键显式置成 `"technical_plan"` 做单入口
#     回滚，那条路径也要它在。
# 换句话说：**此后落到这条 process 上的流量一律是显式 override，不是任何默认。**
#
# ⛔ 六个 technical_plan 冻结文件（decompose_segments / research_adapter /
# architect_merge_adapter / merged_plan / clarify_adapter / render）一行不改。
#
# 本标记进 `ProcessDefinition.config`（既有字段，零迁移）⇒ 「它退役了」这件事**可被程序
# 查到**，而不是只写在注释里：`get_process_definition("technical_plan").config` 即可读。
TECHNICAL_PLAN_RETIREMENT: dict[str, Any] = {
    "retired": True,
    "retired_in": "v0.20.0",
    "successor": "technical_blueprint",
    # 为什么保留注册（写进数据，避免下一个人「顺手清理」）。
    "retained_reason": "in_flight_sessions_and_explicit_rollback_override",
    # 残余流量的观察口径（116-01 落的埋点，按 entry_key 分桶）。
    "residual_traffic_event": "technical_plan_entry_used",
}

register_process_type(
    ProcessDefinition(
        process_type="technical_plan",
        artifact_type="technical_plan",
        initial_stage="decompose",
        stages=_TECHNICAL_PLAN_STAGES,
        config=TECHNICAL_PLAN_RETIREMENT,
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
