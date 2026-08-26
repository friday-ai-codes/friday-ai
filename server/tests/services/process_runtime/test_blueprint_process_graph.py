"""technical_blueprint stage graph + 十个 handler + 蓝图续驱判据测试（112-05；113-06/114-03 扩）。

本文件守以下几件事（第一条最重要）：

1. **既有 technical_plan 链路零扰动**：``_TECHNICAL_PLAN_STAGES`` 的 stage key 集合、每个
   stage 的 ``transitions`` / ``pausable`` / ``wait_status`` 逐字等于字面快照——任何改动即红。
   113-06 追加两 stage 后另有一条断言：旧链 ``merge.exhausted`` 仍指向 ``STAGE_FAILED``。
2. ``technical_blueprint`` 注册项存在：十 stage（112 的七个 + 113 的
   ``repo_plan`` / ``merge`` + 114-03 的 ``ai_review``）、``initial_stage == "intake"``、
   每个 ``StageDef.key`` 等于 dict 键、所有 transition target 合法、十个 stage 从
   ``intake`` 全部可达。
2c. ⭐ **114 接续点已接续**：蓝图链 ``merge.merged == "ai_review"``，而旧链
   ``merge.merged`` 仍是 stage 终态（正反并列，证明只改了蓝图链）；``ai_review`` 的
   ``review_exhausted`` 指 stage 终态而非 failed 终态。
2b. ⭐ **蓝图链零 failed 出边**（W3，遍历全图值集合的运行时断言）+ 旧链正向对照
   （证明 ``STAGE_FAILED`` 可被检出、断言非恒真）。
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
    PartialPlan,
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

# 112-05 注册的前七个 stage（阶段 0/1）——**等价性回归的对象**：113 只允许在其后追加。
BLUEPRINT_STAGE_KEYS_112 = (
    "intake",
    "decompose",
    "spec_gate",
    "route",
    "repo_research",
    "reroute",
    "repo_confirmation",
)

# 113-06 追加的阶段 2/3。
BLUEPRINT_STAGE_KEYS_113 = ("repo_plan", "merge")

# 114-03 追加的阶段 4（AI 对抗审查）。
BLUEPRINT_STAGE_KEYS_114 = ("ai_review",)

BLUEPRINT_STAGE_KEYS = (
    set(BLUEPRINT_STAGE_KEYS_112) | set(BLUEPRINT_STAGE_KEYS_113) | set(BLUEPRINT_STAGE_KEYS_114)
)

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


def test_blueprint_definition_registered_with_all_stages() -> None:
    definition = get_process_definition("technical_blueprint")
    assert definition is not None
    assert definition.initial_stage == "intake"
    assert definition.artifact_type == "technical_plan"
    assert set(definition.stages) == BLUEPRINT_STAGE_KEYS
    # 113 是**只加不改**：112 的七个 stage 一个不少（少一个即红）
    assert set(BLUEPRINT_STAGE_KEYS_112) <= set(definition.stages)
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


def test_confirmed_edge_enters_stage_two() -> None:
    """116 重排：确认门通过先过规格门（带调研上下文的澄清），``spec_locked`` 才进阶段 2。

    用户裁定的新顺序：拆解 → 路由调研 → 仓库集确认门（人修正仓库集）→ 规格门（澄清）
    → 分仓方案。规格门不再是流程入口的第一道闸。
    """
    stages = get_process_definition("technical_blueprint").stages
    assert stages["decompose"].transitions["decomposed"] == "route"
    assert stages["repo_confirmation"].transitions["confirmed"] == "spec_gate"
    assert stages["spec_gate"].transitions["spec_locked"] == "repo_plan"


def test_merge_merged_is_the_114_handoff_point() -> None:
    """114 接续点**已接续**（114-03）：``merge.merged`` 现指 ``ai_review``。

    配一条**正向对照**：旧 ``technical_plan`` 链的 ``merge.merged`` 仍是 stage 终态 ——
    证明本 plan 只改了蓝图链那一行，旧链零感知（断言非恒真）。
    """
    stages = get_process_definition("technical_blueprint").stages
    assert stages["merge"].transitions["merged"] == "ai_review"
    assert bp._TECHNICAL_PLAN_STAGES["merge"].transitions["merged"] == STAGE_DONE, (
        "旧 technical_plan 链的 merge.merged 被误改"
    )
    # 超界不走单独的 exhausted 出边（handler 把它映射成 merged）；若真有该 event，
    # 它也绝不许指向 failed 终态。
    assert stages["merge"].transitions.get("exhausted") != STAGE_FAILED
    assert stages["repo_plan"].transitions["plan_complete"] == "merge"
    # 审查超界的出口是 stage 终态（携未决清单进人审），**绝不是** failed 终态。
    assert stages["ai_review"].transitions["review_exhausted"] == STAGE_DONE


def test_blueprint_chain_has_no_failed_edge_but_old_chain_still_does() -> None:
    """⭐ W3：蓝图链**任一** stage 引入 failed 出边即红；旧链仍有 ⇒ 断言非恒真。

    「超界不落 failed」是本相位最容易被后续 plan 悄悄改掉的一条纪律（T-113-37）：
    它不是某个字面量，而是**整张图的性质**，所以断言写成对全部 transitions 值集合的
    扫描（与行号 / diff 无关）。配一条正向对照：旧链 ``_TECHNICAL_PLAN_STAGES`` 的
    ``merge.exhausted`` 仍是 ``STAGE_FAILED`` —— 证明 ``STAGE_FAILED`` 确实可被检出。
    """
    blueprint = bp._TECHNICAL_BLUEPRINT_STAGES
    offenders = [
        key for key, stage in blueprint.items() if STAGE_FAILED in set(stage.transitions.values())
    ]
    assert not offenders, f"蓝图链引入了 failed 出边：{offenders}"
    assert STAGE_FAILED in set(bp._TECHNICAL_PLAN_STAGES["merge"].transitions.values()), (
        "正向对照失效：上面那条断言变成恒真了"
    )


def test_old_chain_merge_exhausted_still_lands_failed() -> None:
    """旧链未被误改：直接 import ``registry.STAGE_FAILED`` 比对，不猜字面量。"""
    assert bp._TECHNICAL_PLAN_STAGES["merge"].transitions["exhausted"] == STAGE_FAILED


def test_pausable_stages_have_legal_wait_status_and_self_loop() -> None:
    stages = get_process_definition("technical_blueprint").stages
    pausable = {key for key, stage in stages.items() if stage.pausable}
    assert pausable == {
        "spec_gate",
        "repo_research",
        "repo_confirmation",
        "repo_plan",
        "merge",
        "ai_review",
    }
    for key in pausable:
        stage = stages[key]
        assert stage.wait_status in ("waiting_clarification", "waiting_event")
        assert key in stage.transitions.values(), f"{key} 缺 self-loop 边"


def test_every_stage_is_reachable_from_the_initial_stage() -> None:
    """全图可达性：从 ``intake`` 出发九个 stage 全部可达，且每个出边目标都已定义。

    「登记了未定义的 event 目标」会在运行到那一步时才 ``ValueError`` —— 那时会话已跑了
    半小时。这条把它提前到 import 期。
    """
    definition = get_process_definition("technical_blueprint")
    stages = definition.stages
    seen: set[str] = set()
    frontier = [definition.initial_stage]
    while frontier:
        node = frontier.pop()
        if node in seen or node not in stages:
            continue
        seen.add(node)
        frontier.extend(stages[node].transitions.values())
    assert seen == BLUEPRINT_STAGE_KEYS, f"不可达 stage：{BLUEPRINT_STAGE_KEYS - seen}"
    allowed = BLUEPRINT_STAGE_KEYS | {STAGE_DONE, STAGE_FAILED}
    for key, stage in stages.items():
        for event, target in stage.transitions.items():
            assert target in allowed, f"{key}.{event} 指向未定义的 target {target}"


def test_handler_count_and_registration_count() -> None:
    source = Path(bp.__file__).read_text(encoding="utf-8")
    # 7（112-05 阶段 0/1）+ 2（113-06 阶段 2/3）+ 1（114-03 阶段 4）= 10
    assert len(re.findall(r"^async def _h_bp_", source, re.MULTILINE)) == 10
    assert len(re.findall(r"^register_process_type\(", source, re.MULTILINE)) == 3


def test_reroute_bound_constant_lives_in_the_zero_dependency_module() -> None:
    """MN-07：轮次上界的定义在零依赖 ``constants``，adapter 只再导出（同一数值单一来源）。"""
    from services.process_runtime.blueprint_research_adapter import MAX_REROUTE_ROUNDS
    from services.process_runtime.constants import MAX_REROUTE_ROUNDS as SHARED

    assert MAX_REROUTE_ROUNDS == SHARED


def test_blueprint_modules_emit_events_through_the_public_api_only() -> None:
    """MN-05：蓝图链的事件写入统一走 ``aemit_event``，不直调私有钩子、不裸建 ORM 行。"""
    server_dir = Path(bp.__file__).resolve().parents[2]
    watched = [
        "services/process_runtime/blueprint_route.py",
        "services/process_runtime/blueprint_confirm_gate.py",
        "services/process_runtime/blueprint_research_adapter.py",
        "services/process_runtime/blueprint_spec_gate.py",
        "delivery/services/blueprint_lifecycle_service.py",
    ]
    violations = []
    for rel in watched:
        text = (server_dir / rel).read_text(encoding="utf-8")
        for pattern in ("._emit_event(", "ConvergenceSessionEvent.objects.acreate("):
            if pattern in text:
                violations.append(f"{rel}: {pattern}")
    assert not violations, "事件写入必须经 ConvergenceSessionService.aemit_event：" + str(
        violations
    )


def test_process_registration_does_not_import_heavy_adapter_at_module_scope() -> None:
    """process 注册模块不得为一个数字把重型 adapter 拉进 import 期（循环 import 触发点）。"""
    source = Path(bp.__file__).read_text(encoding="utf-8")
    assert "from services.process_runtime.blueprint_research_adapter import" not in source
    assert "MAX_BLUEPRINT_REROUTE_ROUNDS" not in source, "无消费方的再导出常量应删除"


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
    assert {"repo_plan", "merge"} <= deps_names, "阶段 2/3 的 adapter 未注入即恒 pass-through"
    for name in deps_names:
        assert getattr(engine.deps, name) is not None


def test_blueprint_deps_roster_matches_the_factory_docstring() -> None:
    """P-9 第三方：docstring 名单 == SimpleNamespace 属性名 == handler getattr 取名。

    名单写错不报错、只会永远 pass-through，所以三方必须逐字一致地被断言（docstring 是
    唯一的人类可读来源，漂移了下一个人就会照错的那份写 handler）。
    """
    from services.process_runtime import entrypoint as ep

    doc = build_blueprint_engine.__doc__ or ""
    deps_names = {name for name in vars(build_blueprint_engine().deps) if not name.startswith("_")}
    for name in deps_names:
        assert f"``{name}``" in doc, f"deps 属性 {name} 未登记进 build_blueprint_engine docstring"
    source = Path(ep.__file__).read_text(encoding="utf-8")
    factory = source[source.index("def build_blueprint_engine") :]
    for name in deps_names:
        assert f"{name}=" in factory


def test_two_chains_do_not_pollute_each_other() -> None:
    blueprint_deps = set(vars(build_blueprint_engine().deps))
    plan_deps = set(vars(build_orchestration_engine().deps))
    assert "confirm_gate" not in plan_deps
    assert "spec_gate" not in plan_deps
    assert "repo_plan" not in plan_deps
    assert "clarify" not in blueprint_deps
    assert "classify" not in blueprint_deps
    assert "router" not in blueprint_deps
    # ⚠️ `merge` 两条链都有，但是**两个不同的 adapter**：旧链 ArchitectMergeAdapter、
    # 蓝图链 BlueprintMergeAdapter。同名不同物，所以这里断言类型而不是键的存在性。
    assert type(build_blueprint_engine().deps.merge) is not type(
        build_orchestration_engine().deps.merge
    )


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


@pytestmark_db
@pytest.mark.asyncio
async def test_decompose_handler_syncs_existing_spec_when_content_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """幂等拆解不产新版本时，调研仍必须读到既有需求目标与功能点。"""
    content = _stage1_blueprint()
    content["requirement_spec"] = {
        "goal": [{"block_id": "goal", "type": "paragraph", "text": "高三提分专项"}],
        "feature_points": [
            {
                "id": "fp_entry",
                "title": "极速提分营入口",
                "intent": "brownfield",
                "description": [
                    {"block_id": "fp", "type": "paragraph", "text": "按课程包权益展示入口"}
                ],
                "acceptance_criteria": ["有权益展示，无权益隐藏"],
                "test_cases": [],
            }
        ],
    }
    artifact = await ArtifactService().create(
        "technical_plan", content, created_by_user_id="tester"
    )
    session = await _make_session(
        "decompose",
        {"decomposition": {"requirement_text": "高三提分专项"}},
        artifact=artifact,
    )

    from services.process_runtime import blueprint_intake

    monkeypatch.setattr(
        blueprint_intake,
        "adecompose_feature_points",
        AsyncMock(return_value=None),
    )

    outcome = await bp._h_bp_decompose(session, _engine())

    assert outcome.event == "decomposed"
    assert outcome.current_artifact_version == artifact.current_version_id
    assert outcome.stage_state_update == {"requirement_spec": content["requirement_spec"]}


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
        # MN-07：repo_plan 与 merge 同口径 —— 返 `plan_dispatched` 会 self-loop 到
        # `waiting_event` 却没派出任何容器、也没阻塞线程（静默悬挂）。
        (bp._h_bp_repo_plan, "needs_clarification"),
        # D-W4：merge 缺依赖既不自旋（remerge）也不假装成功（merged），停在本 stage 等人。
        (bp._h_bp_merge, "needs_clarification"),
        # D-W4 同款：审查缺依赖既不自旋也不假装通过（review_passed = 零 finding 落库却
        # 判「待人审通过」，人审面板上什么都看不到 —— 最坏的静默失败）。
        (bp._h_bp_ai_review, "needs_clarification"),
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
async def test_repo_plan_needs_clarification_pauses_without_step_limit() -> None:
    """8/8 方案已齐但仍有 blocking 线程时，只推进一次并停在澄清态。"""
    from services.process_runtime.blueprint_repo_plan import BlueprintRepoPlanAdapter
    from services.process_runtime.blueprint_resume import (
        adrive_blueprint_session_to_pause_or_terminal,
    )

    artifact = await _make_artifact()
    repo = await _make_repo()
    content = _stage1_blueprint()
    content["repo_associations"] = [
        {
            "repository_id": str(repo.id),
            "repository_name": repo.name,
            "role": "direct",
        }
    ]
    version = await ArtifactService().add_version(artifact, content)
    session = await _make_session("repo_plan", artifact=artifact)
    await ConvergenceSession.objects.filter(id=session.id).aupdate(
        status=ConvergenceSessionStatus.WAITING_EVENT,
        current_artifact_version_id=version.id,
    )
    session = await ConvergenceSession.objects.aget(id=session.id)
    task = await RepoResearchTask.objects.acreate(
        session=session,
        repository=repo,
        status=RepoResearchTaskStatus.DONE,
    )
    await PartialPlan.objects.acreate(
        research_task=task,
        content={
            "repository_id": str(repo.id),
            "repo_plan": {
                "repository_id": str(repo.id),
                "role": "direct",
                "impl_items": [],
            },
        },
        content_hash="ready",
        valid=True,
    )
    # 零实现项只是人审占位，不得再伪装成仓级方案已交付；阻塞线程负责把流程停在人审。
    assert not await BlueprintRepoPlanAdapter().aall_repo_plans_ready(session)
    await BlueprintLifecycleService().open_thread(
        artifact,
        kind=ThreadKind.AI_CLARIFICATION,
        blocking=True,
        question="请补充降级方案的人工裁决",
        return_stage="repo_plan",
    )

    real_engine = _engine(repo_plan=SimpleNamespace())
    advance = AsyncMock(side_effect=real_engine.advance)
    engine = SimpleNamespace(advance=advance, session_service=real_engine.session_service)

    result = await adrive_blueprint_session_to_pause_or_terminal(engine, session, max_steps=3)

    assert advance.await_count == 1
    assert result.current_stage == "repo_plan"
    assert result.status == ConvergenceSessionStatus.WAITING_CLARIFICATION
    assert result.error == {}


@pytestmark_db
@pytest.mark.asyncio
async def test_repo_plan_blocking_gate_ignores_prior_ai_review_findings() -> None:
    """旧审查 BLOCKER 是本轮重做输入，不能反向阻止 repo_plan 推进。"""
    artifact = await _make_artifact()
    session = await _make_session("repo_plan", artifact=artifact)
    lifecycle = BlueprintLifecycleService()
    await lifecycle.open_thread(
        artifact,
        kind=ThreadKind.AI_REVIEW_FINDING,
        severity="blocker",
        blocking=True,
        question="上一轮审查发现",
        return_stage="ai_reviewing",
    )

    assert await bp._abp_has_open_blocking_threads(session) is False

    await lifecycle.open_thread(
        artifact,
        kind=ThreadKind.AI_CLARIFICATION,
        blocking=True,
        question="本轮仓级方案待确认",
        return_stage="repo_plan",
    )
    assert await bp._abp_has_open_blocking_threads(session) is True


@pytestmark_db
@pytest.mark.asyncio
async def test_repo_plan_plan_dispatched_still_waits_for_event() -> None:
    """event-specific 澄清态不能把正常容器派发自环也改成 waiting_clarification。"""
    session = await _make_session("repo_plan")
    adapter = SimpleNamespace(
        aplan_waves=AsyncMock(return_value={}),
        dispatch_plans=AsyncMock(
            return_value={
                "dispatched": 1,
                "synthesized": 0,
                "pending": 1,
                "completed": [],
                "repositories": ["repo-a"],
            }
        ),
        aexpire_stale_waiters=AsyncMock(return_value=[]),
        acollect_repo_plans=AsyncMock(return_value={}),
        aall_repo_plans_ready=AsyncMock(return_value=False),
        build_stage_state=lambda **_kwargs: {},
    )

    await _engine(repo_plan=adapter).advance(session)

    fresh = await ConvergenceSession.objects.aget(id=session.id)
    assert fresh.current_stage == "repo_plan"
    assert fresh.status == ConvergenceSessionStatus.WAITING_EVENT


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
async def test_transition_without_a_new_version_keeps_the_artifact_pointer() -> None:
    """⭐ 不产版本的转移**不得**抹掉 ``session.current_artifact_version``。

    engine 曾把 ``StageOutcome.current_artifact_version``（默认 None）无条件透传给
    service，而 service 用 ``_UNSET`` 哨兵区分「不改」与「显式置 None」—— 于是每一次
    不产版本的转移都把指针清成 NULL。后果是所有「按会话指针找 artifact」的判据（蓝图
    状态映射 / 阻塞线程探测 / 阶段 2 仓集 / 阶段 3 融合基线）在第一次转移后就静默读到
    None（它们都 best-effort 吞异常，所以一声不响）。
    """
    artifact = await _make_artifact()
    session = await _make_session("route", artifact=artifact)
    assert session.current_artifact_version_id is not None
    engine = _engine(route=SimpleNamespace(route=AsyncMock(return_value=_ROUTING_SUMMARY)))

    await engine.advance(session)

    fresh = await ConvergenceSession.objects.aget(id=session.id)
    assert fresh.current_stage == "repo_research"
    assert fresh.current_artifact_version_id == artifact.current_version_id, (
        "handler 没产版本 ⇒ 指针必须原样保留"
    )


@pytestmark_db
@pytest.mark.asyncio
async def test_transition_with_a_new_version_advances_the_artifact_pointer() -> None:
    """反向对照：handler 真产版本时指针必须推进（证明上一条不是把功能关掉了）。"""
    artifact = await _make_artifact()
    session = await _make_session("merge", artifact=artifact)
    newer = await ArtifactService().add_version(artifact, _stage1_blueprint())
    adapter = SimpleNamespace(
        merge=AsyncMock(
            return_value={"validation_status": "passed", "artifact_version_id": str(newer.id)}
        )
    )

    await _engine(merge=adapter).advance(session)

    fresh = await ConvergenceSession.objects.aget(id=session.id)
    assert str(fresh.current_artifact_version_id) == str(newer.id)


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
async def test_resume_short_circuit_refreshes_confirm_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-02：确认门开着、调研已 done、旧 options 残留 ``task_status=failed`` —— resume 在
    「blocked + 无待调研」短路**之前**必须 refresh，把快照刷成最新（advance 仍为 0）。"""
    from services.process_runtime.blueprint_confirm_gate import (
        BlueprintConfirmGateAdapter,
        iter_snapshot_repos,
    )
    from services.process_runtime.blueprint_resume import (
        adrive_blueprint_session_to_pause_or_terminal,
    )

    session, _artifact, thread, repo = await _confirmation_gate_session(pending_task_status=None)
    # 旧快照残留 failed（模拟门开着期间调研先失败落进 options 的存量）。
    from delivery.models import BlueprintThread

    await BlueprintThread.objects.filter(id=thread.id).aupdate(
        options=[{"repository_id": str(repo.id), "task_status": "failed"}]
    )

    # 让 fitness 聚合确定性地返回 done（避免依赖真实 PartialPlan 装配）。
    monkeypatch.setattr(
        BlueprintConfirmGateAdapter,
        "_acollect_fitness",
        AsyncMock(
            return_value={
                str(repo.id): {
                    "verdict": "suitable",
                    "role_suggestion": "direct",
                    "responsibility": "负责生成接口",
                    "findings": [],
                    "task_status": "done",
                }
            }
        ),
    )

    advance = AsyncMock()
    engine = SimpleNamespace(advance=advance, session_service=ConvergenceSessionService())

    await adrive_blueprint_session_to_pause_or_terminal(engine, session, max_steps=1)

    assert advance.await_count == 0, "无待调研仓 → advance 仍为 0"
    fresh = await BlueprintThread.objects.aget(id=thread.id)
    entry = next(
        e for e in iter_snapshot_repos(fresh.options) if e["repository_id"] == str(repo.id)
    )
    assert entry["task_status"] == "done", "resume 短路前必须把陈旧 failed 刷成最新 done"


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
