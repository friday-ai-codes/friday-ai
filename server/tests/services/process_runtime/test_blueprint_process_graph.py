"""technical_blueprint stage graph + 七个 handler + 蓝图续驱判据测试（Phase 112-05 Task 3）。

本文件守以下几件事（第一条最重要）：

1. **既有 technical_plan 链路零扰动**：``_TECHNICAL_PLAN_STAGES`` 的 stage key 集合、每个
   stage 的 ``transitions`` / ``pausable`` / ``wait_status`` 逐字等于字面快照——任何改动即红。
2. ``technical_blueprint`` 注册项存在：七 stage、``initial_stage == "intake"``、
   每个 ``StageDef.key`` 等于 dict 键、所有 transition target 合法。
3. ``reroute.transitions["exhausted"] == "repo_confirmation"`` 且 ``!= STAGE_FAILED``
   （CONTEXT「绝不静默失败」硬约束）。
4. ``repo_confirmation.transitions["research_required"] == "repo_research"`` 回边存在，
   且从 ``repo_confirmation`` 出发存在到 ``repo_research`` 的路径（防后续误删该边）。
5. ``_h_bp_route`` 写入的 ``stage_state["routing"]`` 字段清单与 112-04 的读取面一致；
   adapter 未注入时 ``stage_state_update is None``（绝不写半截 ``routing`` 键）。
6. ``_h_bp_repo_confirmation`` 的出边判定与**判定顺序**（有待调研仓时压过未确认）。
7. handler 四类必测：deps 未注入 / ``engine.deps`` 整体 None / 正常落 stage_state /
   adapter 抛异常经 engine 兜底落 ``failed`` 且 ``error["stage"]`` 为该 stage 名。
8. ``stage_state`` 浅合并：``_h_bp_reroute`` 回写后既有 ``routing`` 键仍在。
9. ``blueprint_resume`` 的短路判据：有阻塞线程且**无**待调研仓 → 零 advance；有待调研仓
   → **放行**（合取第二项若被漏写这条即红）；线程 resolve 后会 advance；步数超限落
   ``advance_step_limit``。
10. ``build_blueprint_engine`` 的 deps 属性名集合与七个 handler ``getattr`` 取名集合相等
    （防「注册了但 handler 恒 pass-through」的静默空转），且两条链的 deps 互不污染。
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from delivery.models import (
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ConvergenceSessionStatus,
    RepoResearchTask,
    RepoResearchTaskStatus,
    ThreadKind,
)
from delivery.services import ArtifactService, ConvergenceSessionService
from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService
from repositories.models import Repository
from services.process_runtime import builtin_processes as bp
from services.process_runtime.engine import ProcessEngine
from services.process_runtime.entrypoint import (
    build_blueprint_engine,
    build_orchestration_engine,
)
from services.process_runtime.registry import (
    STAGE_DONE,
    STAGE_FAILED,
    get_process_definition,
)
from tests.helpers.blueprint_samples import make_blueprint

BLUEPRINT_STAGE_KEYS = {
    "intake",
    "decompose",
    "spec_gate",
    "route",
    "repo_research",
    "reroute",
    "repo_confirmation",
}

# ── technical_plan 冻结快照（改动即红）──────────────────────────────────────
_TECHNICAL_PLAN_SNAPSHOT: dict[str, dict[str, Any]] = {
    "decompose": {
        "transitions": {"decomposed": "route"},
        "pausable": False,
        "wait_status": "waiting_event",
    },
    "route": {
        "transitions": {"routed": "recall"},
        "pausable": False,
        "wait_status": "waiting_event",
    },
    "recall": {
        "transitions": {"recalled": "classify"},
        "pausable": False,
        "wait_status": "waiting_event",
    },
    "classify": {
        "transitions": {"classified": "clarify"},
        "pausable": False,
        "wait_status": "waiting_event",
    },
    "clarify": {
        "transitions": {"clarified": "research", "needs_clarification": "clarify"},
        "pausable": True,
        "wait_status": "waiting_clarification",
    },
    "research": {
        "transitions": {"research_dispatched": "research", "research_complete": "merge"},
        "pausable": True,
        "wait_status": "waiting_event",
    },
    "merge": {
        "transitions": {
            "merged": STAGE_DONE,
            "validation_failed_reclarify": "clarify",
            "validation_failed_reresearch": "research",
            "exhausted": STAGE_FAILED,
        },
        "pausable": False,
        "wait_status": "waiting_event",
    },
}

_ROUTING_SUMMARY: dict[str, Any] = {
    "router_version": "v2",
    "auto_selected": False,
    "intent": "greenfield",
    "weights_used": {"router_base": 0.4, "charter_match": 0.35, "history_match": 0.25},
    "charter_supplement_count": 1,
    "unjustified_boundary_hit_count": 0,
    "candidates": [
        {
            "repository_id": "repo-a",
            "repository_name": "onion-learning",
            "role_suggestion": "direct",
            "confidence": "high",
            "total": 0.7,
            "breakdown": {"router_base": 0.4, "charter_match": 0.3, "history_match": 0.0},
            "evidence": {"router_version": "v2", "matched_domains": []},
        }
    ],
    "citations": [],
}


# ═══════════════════════════════════════════════════════════════════════════
# 1. 既有 technical_plan 链路冻结
# ═══════════════════════════════════════════════════════════════════════════


def test_technical_plan_stage_graph_is_frozen() -> None:
    stages = bp._TECHNICAL_PLAN_STAGES
    assert set(stages) == set(_TECHNICAL_PLAN_SNAPSHOT)
    for key, expected in _TECHNICAL_PLAN_SNAPSHOT.items():
        stage = stages[key]
        assert stage.key == key
        assert stage.transitions == expected["transitions"], f"{key} transitions 被改动"
        assert stage.pausable is expected["pausable"], f"{key} pausable 被改动"
        assert stage.wait_status == expected["wait_status"], f"{key} wait_status 被改动"


def test_technical_plan_definition_still_registered() -> None:
    definition = get_process_definition("technical_plan")
    assert definition is not None
    assert definition.initial_stage == "decompose"
    assert set(definition.stages) == set(_TECHNICAL_PLAN_SNAPSHOT)


# ═══════════════════════════════════════════════════════════════════════════
# 2-4. technical_blueprint 注册项与关键边
# ═══════════════════════════════════════════════════════════════════════════


def test_blueprint_definition_registered_with_seven_stages() -> None:
    definition = get_process_definition("technical_blueprint")
    assert definition is not None
    assert definition.initial_stage == "intake"
    assert definition.artifact_type == "technical_plan"
    assert set(definition.stages) == BLUEPRINT_STAGE_KEYS
    for key, stage in definition.stages.items():
        assert stage.key == key, f"StageDef.key({stage.key}) 必须等于 dict 键({key})"


def test_blueprint_transition_targets_are_all_resolvable() -> None:
    stages = get_process_definition("technical_blueprint").stages
    allowed = BLUEPRINT_STAGE_KEYS | {STAGE_DONE, STAGE_FAILED}
    for key, stage in stages.items():
        for event, target in stage.transitions.items():
            assert target in allowed, f"{key}.{event} 指向未知 target {target}"


def test_reroute_exhausted_escalates_to_confirmation_not_failed() -> None:
    stages = get_process_definition("technical_blueprint").stages
    assert stages["reroute"].transitions["exhausted"] == "repo_confirmation"
    assert stages["reroute"].transitions["exhausted"] != STAGE_FAILED
    assert STAGE_FAILED not in stages["reroute"].transitions.values()


def test_research_required_back_edge_exists_and_is_reachable() -> None:
    stages = get_process_definition("technical_blueprint").stages
    assert stages["repo_confirmation"].transitions["research_required"] == "repo_research"

    # 图连通性：从 repo_confirmation 出发能走到 repo_research（防后续误删该边）
    seen, frontier = set(), ["repo_confirmation"]
    while frontier:
        node = frontier.pop()
        if node in seen or node not in stages:
            continue
        seen.add(node)
        frontier.extend(stages[node].transitions.values())
    assert "repo_research" in seen


def test_confirmed_edge_points_at_terminal_for_now() -> None:
    """113 接续点：把该值改为 ``"repo_plan"`` 并追加两个 StageDef 即可（transitions 是数据）。"""
    stages = get_process_definition("technical_blueprint").stages
    assert stages["repo_confirmation"].transitions["confirmed"] == STAGE_DONE


def test_pausable_stages_have_legal_wait_status_and_self_loop() -> None:
    stages = get_process_definition("technical_blueprint").stages
    pausable = {key for key, stage in stages.items() if stage.pausable}
    assert pausable == {"spec_gate", "repo_research", "repo_confirmation"}
    for key in pausable:
        stage = stages[key]
        assert stage.wait_status in ("waiting_clarification", "waiting_event")
        assert key in stage.transitions.values(), f"{key} 缺 self-loop 边"


def test_handler_count_and_registration_count() -> None:
    source = Path(bp.__file__).read_text(encoding="utf-8")
    assert len(re.findall(r"^async def _h_bp_", source, re.MULTILINE)) == 7
    assert len(re.findall(r"^register_process_type\(", source, re.MULTILINE)) == 3


def test_reroute_bound_constant_is_shared_with_research_adapter() -> None:
    from services.process_runtime.blueprint_research_adapter import MAX_REROUTE_ROUNDS

    assert bp.MAX_BLUEPRINT_REROUTE_ROUNDS == MAX_REROUTE_ROUNDS


# ═══════════════════════════════════════════════════════════════════════════
# 5. build_blueprint_engine 的 deps 名单与 handler getattr 名单相等
# ═══════════════════════════════════════════════════════════════════════════


def _handler_dep_names() -> set[str]:
    source = Path(bp.__file__).read_text(encoding="utf-8")
    blueprint_section = source[source.index("_h_bp_intake") :]
    return set(
        re.findall(r'getattr\(getattr\(engine, "deps", None\), "(\w+)", None\)', blueprint_section)
    )


def test_blueprint_engine_deps_match_handler_getattr_names() -> None:
    engine = build_blueprint_engine()
    deps_names = {name for name in vars(engine.deps) if not name.startswith("_")}
    assert deps_names == _handler_dep_names(), (
        "deps 名单与 handler getattr 取名漂移 → handler 会恒 pass-through（静默空转）"
    )
    for name in deps_names:
        assert getattr(engine.deps, name) is not None


def test_two_chains_do_not_pollute_each_other() -> None:
    blueprint_deps = set(vars(build_blueprint_engine().deps))
    plan_deps = set(vars(build_orchestration_engine().deps))
    assert "confirm_gate" not in plan_deps
    assert "spec_gate" not in plan_deps
    assert "clarify" not in blueprint_deps
    assert "merge" not in blueprint_deps


# ═══════════════════════════════════════════════════════════════════════════
# handler 级测试（DB）
# ═══════════════════════════════════════════════════════════════════════════

pytestmark_db = pytest.mark.django_db(transaction=True)


def _stage1_blueprint() -> dict[str, Any]:
    return make_blueprint(
        current_state_analysis=[],
        implementation_overview={
            "requirement_narrative": [
                {"block_id": "blk_narr", "type": "paragraph", "text": "阶段 1 尚未产出。"}
            ],
            "items": [],
        },
        api_contracts=[],
        interaction_flows=[],
        repo_associations=[],
    )


async def _make_session(stage: str, stage_state: dict | None = None, *, artifact=None):
    return await ConvergenceSession.objects.acreate(
        process_type="technical_blueprint",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage=stage,
        stage_state=stage_state or {},
        current_artifact_version_id=getattr(artifact, "current_version_id", None),
    )


async def _make_artifact():
    return await ArtifactService().create(
        "technical_plan", _stage1_blueprint(), created_by_user_id="tester"
    )


async def _make_repo() -> Repository:
    name = f"r-{uuid.uuid4().hex[:8]}"
    return await Repository.objects.acreate(
        name=name,
        git_url=f"https://example.com/{name}.git",
        git_platform="github",
        default_branch="main",
    )


def _engine(**deps: Any) -> ProcessEngine:
    return ProcessEngine(
        session_service=ConvergenceSessionService(), deps=SimpleNamespace(**deps) if deps else None
    )


# ── 5. stage_state["routing"] 契约（B4）──────────────────────────────────────


@pytestmark_db
@pytest.mark.asyncio
async def test_route_handler_writes_full_routing_contract() -> None:
    session = await _make_session("route")
    router = AsyncMock(return_value=_ROUTING_SUMMARY)
    engine = _engine(route=SimpleNamespace(route=router))

    outcome = await bp._h_bp_route(session, engine)

    assert outcome.event == "routed"
    assert "routing" in outcome.stage_state_update

    await engine.advance(session)
    fresh = await ConvergenceSession.objects.aget(id=session.id)
    assert fresh.current_stage == "repo_research"
    routing = fresh.stage_state["routing"]
    assert {"router_version", "intent", "weights_used", "candidates"} <= set(routing)
    candidate = routing["candidates"][0]
    assert {
        "repository_id",
        "role_suggestion",
        "confidence",
        "total",
        "breakdown",
        "evidence",
    } <= set(candidate)


@pytestmark_db
@pytest.mark.asyncio
async def test_route_handler_writes_no_half_routing_key_without_adapter() -> None:
    session = await _make_session("route")

    outcome = await bp._h_bp_route(session, _engine())

    assert outcome.event == "routed"
    assert outcome.stage_state_update is None


# ── 6. repo_confirmation 出边判定与顺序（B1②）────────────────────────────────


async def _pending_confirmation_session(status: str):
    artifact = await _make_artifact()
    repo = await _make_repo()
    session = await _make_session(
        "repo_confirmation",
        {
            "routing": {"candidates": []},
            "confirmation": {"repos": [{"repository_id": str(repo.id), "pending_research": True}]},
        },
        artifact=artifact,
    )
    await RepoResearchTask.objects.acreate(session=session, repository=repo, status=status)
    return session, repo, artifact


@pytestmark_db
@pytest.mark.asyncio
async def test_confirmation_handler_prefers_research_required_over_self_loop() -> None:
    session, _repo, _artifact = await _pending_confirmation_session(RepoResearchTaskStatus.PENDING)
    gate = SimpleNamespace(open_gate=AsyncMock(return_value={"event": "awaiting_confirmation"}))
    engine = _engine(confirm_gate=gate)

    outcome = await bp._h_bp_repo_confirmation(session, engine)

    assert outcome.event == "research_required"
    assert gate.open_gate.await_count == 0, "有待调研仓时不该再走开门路径"


@pytestmark_db
@pytest.mark.asyncio
async def test_confirmation_handler_does_not_trigger_when_tasks_are_done() -> None:
    session, _repo, _artifact = await _pending_confirmation_session(RepoResearchTaskStatus.DONE)
    gate = SimpleNamespace(open_gate=AsyncMock(return_value={"event": "awaiting_confirmation"}))

    outcome = await bp._h_bp_repo_confirmation(session, _engine(confirm_gate=gate))

    assert outcome.event == "awaiting_confirmation", "标记遗留但 task 已终态 → 合取判据为假"


@pytestmark_db
@pytest.mark.asyncio
async def test_confirmation_handler_returns_confirmed_from_adapter() -> None:
    session = await _make_session("repo_confirmation")
    gate = SimpleNamespace(
        open_gate=AsyncMock(return_value={"event": "confirmed", "stage_state": None})
    )

    outcome = await bp._h_bp_repo_confirmation(session, _engine(confirm_gate=gate))

    assert outcome.event == "confirmed"


# ── 7. handler 四类必测 ─────────────────────────────────────────────────────


@pytestmark_db
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler", "expected"),
    [
        (bp._h_bp_intake, "intaken"),
        (bp._h_bp_decompose, "decomposed"),
        (bp._h_bp_spec_gate, "spec_locked"),
        (bp._h_bp_route, "routed"),
        (bp._h_bp_repo_research, "research_complete"),
        (bp._h_bp_reroute, "converged"),
        (bp._h_bp_repo_confirmation, "awaiting_confirmation"),
    ],
)
async def test_handlers_pass_through_without_deps(handler: Any, expected: str) -> None:
    session = await _make_session("intake")
    stages = get_process_definition("technical_blueprint").stages

    for engine in (_engine(), ProcessEngine(deps=None)):
        outcome = await handler(session, engine)
        assert outcome.event == expected
        assert any(expected in stage.transitions for stage in stages.values())


@pytestmark_db
@pytest.mark.asyncio
async def test_spec_gate_handler_maps_needs_clarification_and_persists_stage_state() -> None:
    session = await _make_session("spec_gate")
    adapter = SimpleNamespace(
        run=AsyncMock(
            return_value={
                "event": "needs_clarification",
                "stage_state": {"spec_gate": {"round": 1, "pending": True}},
            }
        )
    )
    engine = _engine(spec_gate=adapter)

    await engine.advance(session)

    fresh = await ConvergenceSession.objects.aget(id=session.id)
    assert fresh.current_stage == "spec_gate"
    assert fresh.status == ConvergenceSessionStatus.WAITING_CLARIFICATION
    assert fresh.stage_state["spec_gate"]["round"] == 1


@pytestmark_db
@pytest.mark.asyncio
async def test_self_loop_advances_do_not_overwrite_each_others_stage_state() -> None:
    """MJ-04：两路并发续驱在 self-loop 挂起边上写不同 stage_state 键，两份增量都必须保住。

    self-loop 时 ``new_stage == from_stage``，``current_stage`` 的 CAS 对两个并发写者
    **同时成立**（都 ``updated == 1``）——若合并基准取内存里那份陈旧 session，后写者会把
    先写者的 ``stage_state`` 整份覆盖掉（GAP-1 刚建立的「排除集永久累积」性质在并发下即失效）。
    """
    session = await _make_session("repo_confirmation", {"routing": {"candidates": []}})
    # 两个写者各自持有「同一时刻」读到的 session（真实并发的最短复现）
    writer_a = await ConvergenceSession.objects.aget(id=session.id)
    writer_b = await ConvergenceSession.objects.aget(id=session.id)

    engine_a = _engine(
        confirm_gate=SimpleNamespace(
            open_gate=AsyncMock(
                return_value={
                    "event": "awaiting_confirmation",
                    "stage_state": {"confirmation": {"repos": ["A"]}},
                }
            )
        )
    )
    engine_b = _engine(
        confirm_gate=SimpleNamespace(
            open_gate=AsyncMock(
                return_value={
                    "event": "awaiting_confirmation",
                    "stage_state": {"reroute": {"excluded": ["B"]}},
                }
            )
        )
    )

    await engine_a.advance(writer_a)
    await engine_b.advance(writer_b)

    fresh = await ConvergenceSession.objects.aget(id=session.id)
    assert fresh.stage_state["confirmation"] == {"repos": ["A"]}, "先写者的增量被覆盖了"
    assert fresh.stage_state["reroute"] == {"excluded": ["B"]}
    assert "routing" in fresh.stage_state, "既有键不得被增量写清空"


@pytestmark_db
@pytest.mark.asyncio
async def test_adapter_exception_lands_failed_with_stage_name() -> None:
    session = await _make_session("route")
    engine = _engine(route=SimpleNamespace(route=AsyncMock(side_effect=RuntimeError("boom"))))

    await engine.advance(session)

    fresh = await ConvergenceSession.objects.aget(id=session.id)
    assert fresh.status == ConvergenceSessionStatus.FAILED
    assert fresh.error["stage"] == "route"


# ── 8. stage_state 浅合并 ───────────────────────────────────────────────────


@pytestmark_db
@pytest.mark.asyncio
async def test_reroute_handler_keeps_existing_stage_state_keys() -> None:
    session = await _make_session(
        "reroute", {"routing": _ROUTING_SUMMARY, "decomposition": {"requirement_text": "x"}}
    )
    merged = {
        "routing": _ROUTING_SUMMARY,
        "decomposition": {"requirement_text": "x"},
        "reroute": {"count": 1, "excluded": ["repo-a"], "last_reason": "unsuitable_repos_excluded"},
    }
    adapter = SimpleNamespace(
        aadvance_reroute=AsyncMock(
            return_value={
                "event": "exhausted",
                "stage_state_update": merged,
                "escalation": {"reason": "reroute_exhausted", "repos": []},
                "decision": {},
            }
        )
    )
    engine = _engine(research=adapter)

    await engine.advance(session)

    fresh = await ConvergenceSession.objects.aget(id=session.id)
    assert fresh.current_stage == "repo_confirmation", "exhausted 必须升确认门而非落 failed"
    assert fresh.status != ConvergenceSessionStatus.FAILED
    assert "routing" in fresh.stage_state
    assert "decomposition" in fresh.stage_state
    assert fresh.stage_state["escalation"]["reason"] == "reroute_exhausted"


# ── 9. blueprint_resume 短路判据（合取式）────────────────────────────────────


async def _confirmation_gate_session(*, pending_task_status: str | None):
    from services.process_runtime.blueprint_confirm_gate import STAGE_STATE_KEY

    artifact = await _make_artifact()
    repo = await _make_repo()
    stage_state: dict[str, Any] = {"routing": {"candidates": []}}
    if pending_task_status is not None:
        stage_state[STAGE_STATE_KEY] = {
            "repos": [{"repository_id": str(repo.id), "pending_research": True}]
        }
    session = await _make_session("repo_confirmation", stage_state, artifact=artifact)
    await ConvergenceSession.objects.filter(id=session.id).aupdate(
        status=ConvergenceSessionStatus.WAITING_CLARIFICATION
    )
    session = await ConvergenceSession.objects.aget(id=session.id)
    thread = await BlueprintLifecycleService().open_thread(
        artifact,
        kind=ThreadKind.REPO_CONFIRMATION,
        blocking=True,
        question="请确认仓库集",
        options=[{"repository_id": str(repo.id)}],
    )
    if pending_task_status is not None:
        await RepoResearchTask.objects.acreate(
            session=session, repository=repo, status=pending_task_status
        )
    return session, artifact, thread, repo


@pytestmark_db
@pytest.mark.asyncio
async def test_resume_short_circuits_when_blocked_and_nothing_to_research() -> None:
    from services.process_runtime.blueprint_resume import (
        adrive_blueprint_session_to_pause_or_terminal,
    )

    session, _artifact, _thread, _repo = await _confirmation_gate_session(pending_task_status=None)
    advance = AsyncMock()
    engine = SimpleNamespace(advance=advance, session_service=ConvergenceSessionService())

    result = await adrive_blueprint_session_to_pause_or_terminal(engine, session)

    assert advance.await_count == 0, "有 open+blocking 线程且无待调研仓 → 必须短路"
    assert result.id == session.id


@pytestmark_db
@pytest.mark.asyncio
async def test_resume_lets_advance_through_when_research_is_pending() -> None:
    """合取第二项若被漏写（只看线程就短路），这条即红 —— SC-4 最容易断的一环。"""
    from services.process_runtime.blueprint_resume import (
        adrive_blueprint_session_to_pause_or_terminal,
    )

    session, _artifact, _thread, _repo = await _confirmation_gate_session(
        pending_task_status=RepoResearchTaskStatus.PENDING
    )
    advance = AsyncMock()
    engine = SimpleNamespace(advance=advance, session_service=ConvergenceSessionService())

    await adrive_blueprint_session_to_pause_or_terminal(engine, session, max_steps=1)

    assert advance.await_count >= 1


@pytestmark_db
@pytest.mark.asyncio
async def test_resume_advances_after_thread_resolved() -> None:
    from services.process_runtime.blueprint_resume import (
        adrive_blueprint_session_to_pause_or_terminal,
    )

    session, _artifact, thread, _repo = await _confirmation_gate_session(pending_task_status=None)
    await BlueprintLifecycleService().resolve_thread(thread)
    advance = AsyncMock()
    engine = SimpleNamespace(advance=advance, session_service=ConvergenceSessionService())

    await adrive_blueprint_session_to_pause_or_terminal(engine, session, max_steps=1)

    assert advance.await_count >= 1


@pytestmark_db
@pytest.mark.asyncio
async def test_resume_step_limit_lands_advance_step_limit() -> None:
    from services.process_runtime.blueprint_resume import (
        adrive_blueprint_session_to_pause_or_terminal,
    )

    session = await _make_session("repo_confirmation")
    engine = SimpleNamespace(advance=AsyncMock(), session_service=ConvergenceSessionService())

    await adrive_blueprint_session_to_pause_or_terminal(engine, session, max_steps=1)

    fresh = await ConvergenceSession.objects.aget(id=session.id)
    assert fresh.status == ConvergenceSessionStatus.FAILED
    assert fresh.error["reason"] == "advance_step_limit"


@pytestmark_db
@pytest.mark.asyncio
async def test_resume_after_gate_action_swallows_driver_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.process_runtime import blueprint_resume

    session = await _make_session("repo_confirmation")
    monkeypatch.setattr(
        blueprint_resume,
        "adrive_blueprint_session_to_pause_or_terminal",
        AsyncMock(side_effect=RuntimeError("boom")),
    )

    result = await blueprint_resume.aresume_after_gate_action(
        session, initiated_by_user_id="tester"
    )

    assert result.id == session.id, "续驱失败必须返回传入 session，绝不上抛"


@pytestmark_db
@pytest.mark.asyncio
async def test_resume_refuses_to_drive_non_blueprint_session() -> None:
    """CR-01 守卫：蓝图 engine 绝不驱动别的 process 的会话（deps 名单对不上会把它打成 FAILED）。"""
    from services.process_runtime.blueprint_resume import (
        adrive_blueprint_session_to_pause_or_terminal,
    )

    session = await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="route",
        status=ConvergenceSessionStatus.RUNNING,
    )
    advance = AsyncMock()
    engine = SimpleNamespace(advance=advance, session_service=ConvergenceSessionService())

    result = await adrive_blueprint_session_to_pause_or_terminal(engine, session, max_steps=1)

    assert advance.await_count == 0, "非蓝图会话必须 no-op"
    assert result.id == session.id
    fresh = await ConvergenceSession.objects.aget(id=session.id)
    assert fresh.status == ConvergenceSessionStatus.RUNNING, "no-op 不得把无关会话落终态"
