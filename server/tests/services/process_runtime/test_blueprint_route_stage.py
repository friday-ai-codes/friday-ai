"""BlueprintRouteAdapter 机制级行为测试（CHARTER-02 / FLOW-04 / ROADMAP SC2）。

守六件事：

1. **高三提分专项机制**：`onion-learning` 靠章程 `owned_domains(status=planned)` 进候选
   （`router_base == 0.0`、`charter_match > 0`）——不因能力树无培优节点被淘汰。
2. **禁区降权**：命中 `boundaries` 的候选 `charter_match < 0`，同 `router_base` 下总分更低。
3. **禁区候选必须有显式理由（SC2 后半）**：三种上游情形（router 有 reasoning / 靠单次
   sanity-check LLM 补 / LLM 不可得）各断言一次，外加「有理由 或 有标记」总不变量。
4. **`stage_state["routing"]` 契约**：顶层 8 键 + 候选七键（112-04 分桶与 112-05 快照的
   唯一读取面，漏字段即打破下游）。
5. **降级语义**：history 不可得写显式原因而非静默 0 分；章程读失败仍返回候选。
6. **空需求短路**：不调路由器、`router_version == "skipped"`、形状不变。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async

from delivery.models import ConvergenceSession, ConvergenceSessionEntrypoint
from repositories.models import RepoCharter, Repository
from services.process_runtime.blueprint_charter_match import score_charter_match
from services.process_runtime.blueprint_route import BlueprintRouteAdapter, _aload_route_context
from services.process_runtime.blueprint_route_history import HistoryMatchResult
from tests.helpers.fake_chat_model import FakeChatModel

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

_EXPLAIN = "services.process_runtime.blueprint_route._aexplain_boundary_overrides"
_EMIT = "delivery.services.convergence_session_service.ConvergenceSessionService._emit_event"
_ARESOLVE = "services.provider_config.ProviderConfigService.aresolve"
_BUILD = "agents.llm_factory.build_chat_model"

_GOAL = "高三学员可从培优课入口进入专项学习页完成学习并开始专项练习。"
_TOP_LEVEL_KEYS = {
    "router_version",
    "auto_selected",
    "intent",
    "weights_used",
    "charter_supplement_count",
    "unjustified_boundary_hit_count",
    "candidates",
}
_CANDIDATE_KEYS = {
    "repository_id",
    "repository_name",
    "role_suggestion",
    "confidence",
    "total",
    "breakdown",
    "evidence",
}


# ── 工厂 ──────────────────────────────────────────────────────────────────


def _point(point_id: str, title: str, intent: str, description: str) -> dict:
    return {
        "id": point_id,
        "title": title,
        "intent": intent,
        "description": [{"block_id": f"blk_{point_id}", "type": "paragraph", "text": description}],
    }


def _spec(points: list[dict]) -> dict:
    return {
        "goal": [{"block_id": "blk_goal", "type": "paragraph", "text": _GOAL}],
        "feature_points": points,
    }


_GREENFIELD_POINTS = [
    _point("fp_02", "专项学习页", "greenfield", "新增高三提分专项学习页，展示专项课程内容。")
]


async def _make_session(spec: dict | None) -> ConvergenceSession:
    stage_state = (
        {"blueprint": {"requirement_spec": spec, "primary_team": "路由测试团队"}}
        if spec is not None
        else {}
    )
    return await ConvergenceSession.objects.acreate(
        process_type="technical_blueprint",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="route",
        stage_state=stage_state,
    )


async def _make_repo(name: str) -> Repository:
    return await Repository.objects.acreate(
        name=name,
        git_url=f"https://example.com/{name}.git",
        git_platform="github",
        default_branch="main",
        facets={"团队归属": "路由测试团队"},
        index_status="indexed",
    )


async def _make_charter(repo: Repository, **fields) -> RepoCharter:
    payload = {
        "owned_domains": [],
        "boundaries": [],
        "evolution": "active",
        "source": RepoCharter.Source.HUMAN_CONFIRMED,
        "version": 1,
    }
    payload.update(fields)
    return await sync_to_async(RepoCharter.objects.create)(repository=repo, **payload)


def _rv2_candidate(
    repository_id: str,
    name: str,
    score: float,
    *,
    confidence: str = "medium",
    reasoning: str = "命中能力节点: apps/study/page",
    matched_node_paths: list[str] | None = None,
) -> SimpleNamespace:
    """`RepoRouteCandidateV2` 的逐字段替身（字段名取 RESEARCH-ROUTING §1.3 实测清单）。"""
    return SimpleNamespace(
        repo_id=str(repository_id),
        repo_name=name,
        score=score,
        confidence=confidence,
        reasoning=reasoning,
        sub_project="",
        sub_project_paths=[],
        matched_node_paths=matched_node_paths if matched_node_paths is not None else ["apps/study"],
    )


def _router(
    candidates: list[SimpleNamespace],
    *,
    router_version: str = "v2",
    auto_selected: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        route=AsyncMock(
            return_value=SimpleNamespace(
                candidates=candidates,
                router_version=router_version,
                auto_selected=auto_selected,
            )
        )
    )


def _history(result: HistoryMatchResult | None = None) -> AsyncMock:
    return AsyncMock(return_value=result or HistoryMatchResult())


def _adapter(router, history: AsyncMock | None = None) -> BlueprintRouteAdapter:
    return BlueprintRouteAdapter(router=router, history=history or _history())


# ── 正常路径与短路 ────────────────────────────────────────────────────────


async def test_normal_path_orders_by_total_and_emits_event() -> None:
    """两候选按 total 降序、每候选 breakdown 三分量齐、事件 emit 一次且含 router_version。"""
    session = await _make_session(_spec(_GREENFIELD_POINTS))
    high = await _make_repo("study-course")
    low = await _make_repo("onion-practice")
    router = _router(
        [
            _rv2_candidate(str(low.id), "onion-practice", 0.30),
            _rv2_candidate(str(high.id), "study-course", 0.90, confidence="high"),
        ]
    )

    with patch(_EMIT, new=AsyncMock()) as emit:
        result = await _adapter(router).route(session)

    assert router.route.await_count == 2  # shortlist signal + placement
    assert [c["repository_id"] for c in result["candidates"]] == [str(high.id), str(low.id)]
    assert result["candidates"][0]["total"] > result["candidates"][1]["total"]
    for candidate in result["candidates"]:
        assert set(candidate["breakdown"]) == {"router_base", "charter_match", "history_match"}

    scored = [call for call in emit.call_args_list if call.args[0] == "blueprint.route.scored"]
    assert len(scored) == 1
    assert scored[0].args[2]["router_version"] == "v2"
    assert scored[0].args[2]["candidate_count"] == 2


async def test_empty_query_short_circuits_router() -> None:
    """无需求文本 → 不调路由器、router_version == "skipped"、候选为空。"""
    session = await _make_session(None)
    router = _router([])

    result = await _adapter(router).route(session)

    assert router.route.await_count == 0
    assert result["router_version"] == "skipped"
    assert result["candidates"] == []
    assert _TOP_LEVEL_KEYS <= set(result)


async def test_breakdown_total_equals_component_sum_end_to_end() -> None:
    """端到端：每候选 total 逐位等于三分量之和（恒等式不被 adapter 组装破坏）。"""
    session = await _make_session(_spec(_GREENFIELD_POINTS))
    repo = await _make_repo("study-course")
    router = _router([_rv2_candidate(str(repo.id), "study-course", 0.7)])
    history = _history(HistoryMatchResult(scores={str(repo.id): 0.5}))

    result = await _adapter(router, history).route(session)

    candidate = result["candidates"][0]
    components = candidate["breakdown"]
    assert abs(candidate["total"] - sum(components.values())) < 1e-9


# ── 高三提分专项：章程补入 + planned 计正分 ────────────────────────────────


async def test_charter_planned_team_owner_remains_candidate() -> None:
    """可信 Team owner 即使能力树未召回也保留，planned 章程仍贡献正分。

    这条断言同时锁 SC2 的两个机制：**章程补入** + **planned 计正分**。
    """
    session = await _make_session(_spec(_GREENFIELD_POINTS))
    routed = await _make_repo("study-course")
    supplement = await _make_repo("onion-learning")
    await _make_charter(
        supplement,
        owned_domains=[{"domain": "培优/学习提分", "status": "planned", "citations": ["cit_x"]}],
    )
    # 能力树里没有培优节点 → 路由器不返回 onion-learning
    router = _router([_rv2_candidate(str(routed.id), "study-course", 0.85)])

    result = await _adapter(router).route(session)

    by_id = {c["repository_id"]: c for c in result["candidates"]}
    assert str(supplement.id) in by_id, "章程 owned(planned) 命中的仓必须被补入候选"
    entered = by_id[str(supplement.id)]
    assert entered["breakdown"]["charter_match"] > 0
    assert {"domain": "培优/学习提分", "status": "planned"} in entered["evidence"][
        "matched_domains"
    ]
    assert entered["role_suggestion"] == "candidate"
    assert entered["confidence"] == "low"


async def test_charter_supplement_produces_repo_charter_citation() -> None:
    """章程被引用 → 产 source_type=repo_charter 的 citation 条目（115 消费）。"""
    session = await _make_session(_spec(_GREENFIELD_POINTS))
    supplement = await _make_repo("onion-learning")
    await _make_charter(
        supplement, owned_domains=[{"domain": "培优/学习提分", "status": "planned"}]
    )
    router = _router([])

    result = await _adapter(router).route(session)

    charter_citations = [c for c in result["citations"] if c["source_type"] == "repo_charter"]
    assert charter_citations
    assert charter_citations[0]["source_id"] == str(supplement.id)
    assert charter_citations[0]["locator"] == {"domain": "培优/学习提分"}


async def test_charter_component_fully_explains_ranking_difference() -> None:
    """同 router_base 下排序差异可完全归因章程分量（可拆解，CHARTER-02）。"""
    session = await _make_session(_spec(_GREENFIELD_POINTS))
    owned = await _make_repo("study-course")
    plain = await _make_repo("onion-practice")
    await _make_charter(owned, owned_domains=[{"domain": "专项学习页", "status": "implemented"}])
    router = _router(
        [
            _rv2_candidate(str(owned.id), "study-course", 0.5),
            _rv2_candidate(str(plain.id), "onion-practice", 0.5),
        ]
    )

    result = await _adapter(router).route(session)

    by_id = {c["repository_id"]: c for c in result["candidates"]}
    owned_c, plain_c = by_id[str(owned.id)], by_id[str(plain.id)]
    assert owned_c["total"] > plain_c["total"]
    assert owned_c["breakdown"]["router_base"] == pytest.approx(plain_c["breakdown"]["router_base"])
    # 差值恰等于章程分量差 → 排序差异**仅**由章程贡献
    assert owned_c["total"] - plain_c["total"] == pytest.approx(
        owned_c["breakdown"]["charter_match"] - plain_c["breakdown"]["charter_match"]
    )


# ── 禁区降权与 evolution 降权 ────────────────────────────────────────────


async def test_boundary_hit_candidate_is_penalized_not_dropped() -> None:
    """命中禁区的候选只降权不淘汰：charter_match < 0、总分低于同 router_base 的对照仓。"""
    session = await _make_session(_spec(_GREENFIELD_POINTS))
    blocked = await _make_repo("study-plan")
    control = await _make_repo("onion-practice")
    await _make_charter(blocked, boundaries=[{"rule": "不承接专项学习页与课程权益鉴权"}])
    router = _router(
        [
            _rv2_candidate(str(blocked.id), "study-plan", 0.9),
            _rv2_candidate(str(control.id), "onion-practice", 0.9),
        ]
    )

    result = await _adapter(router).route(session)

    by_id = {c["repository_id"]: c for c in result["candidates"]}
    assert str(blocked.id) in by_id, "命中禁区只降权，不得淘汰候选"
    penalized = by_id[str(blocked.id)]
    assert penalized["breakdown"]["charter_match"] < 0
    assert penalized["evidence"]["violated_boundaries"]
    assert penalized["total"] < by_id[str(control.id)]["total"]


async def test_maintenance_only_candidate_gets_extra_penalty() -> None:
    """evolution=maintenance_only 被额外降权且 penalty_reasons 可见。"""
    session = await _make_session(_spec(_GREENFIELD_POINTS))
    legacy = await _make_repo("legacy-course")
    active = await _make_repo("study-course")
    domains = [{"domain": "专项学习页", "status": "implemented"}]
    await _make_charter(legacy, owned_domains=domains, evolution="maintenance_only")
    await _make_charter(active, owned_domains=domains, evolution="active")
    router = _router(
        [
            _rv2_candidate(str(legacy.id), "legacy-course", 0.6),
            _rv2_candidate(str(active.id), "study-course", 0.6),
        ]
    )

    result = await _adapter(router).route(session)

    by_id = {c["repository_id"]: c for c in result["candidates"]}
    assert by_id[str(legacy.id)]["total"] < by_id[str(active.id)]["total"]
    assert "evolution_maintenance_only" in by_id[str(legacy.id)]["evidence"]["penalty_reasons"]


# ── 禁区候选的显式保留理由（SC2 后半，三情形 + 总不变量） ──────────────────


async def _boundary_session_and_router(
    *, reasoning: str
) -> tuple[ConvergenceSession, SimpleNamespace, Repository]:
    session = await _make_session(_spec(_GREENFIELD_POINTS))
    blocked = await _make_repo("study-plan")
    await _make_charter(blocked, boundaries=[{"rule": "不承接专项学习页与课程权益鉴权"}])
    router = _router([_rv2_candidate(str(blocked.id), "study-plan", 0.9, reasoning=reasoning)])
    return session, router, blocked


async def test_router_reasoning_does_not_substitute_for_boundary_reason() -> None:
    """MJ-05 情形 1：router reasoning 非空**也**要走 sanity-check；LLM 不可得即打标记。

    reasoning 是能力树命中说明（对召回候选恒非空），拿它冒充禁区保留理由会让
    sanity-check 成为死路径、`unjustified_boundary_hit` 几乎永远为 False。
    """
    session, router, blocked = await _boundary_session_and_router(
        reasoning="命中能力节点: apps/study/entitlement"
    )

    with patch(_EXPLAIN, new=AsyncMock(return_value={})) as explain:
        result = await _adapter(router).route(session)

    candidate = result["candidates"][0]
    assert candidate["repository_id"] == str(blocked.id)
    assert explain.await_count == 1, "禁区命中候选必须全部进 sanity-check 批次"
    assert candidate["evidence"]["boundary_override_reason"] == ""
    assert candidate["evidence"]["unjustified_boundary_hit"] is True
    assert result["unjustified_boundary_hit_count"] == 1
    # 路由说明仍作展示字段留在 evidence 里，只是不参与判定
    assert candidate["evidence"]["reasoning"] == "命中能力节点: apps/study/entitlement"


async def test_sanity_check_llm_supplies_reason_in_single_call() -> None:
    """情形 2：reasoning 空 → 单次 sanity-check LLM 补理由（多候选合成一批，只调一次）。"""
    session = await _make_session(_spec(_GREENFIELD_POINTS))
    first = await _make_repo("study-plan")
    second = await _make_repo("legacy-plan")
    for repo in (first, second):
        await _make_charter(repo, boundaries=[{"rule": "不承接专项学习页与课程权益鉴权"}])
    router = _router(
        [
            _rv2_candidate(str(first.id), "study-plan", 0.9, reasoning=""),
            _rv2_candidate(str(second.id), "legacy-plan", 0.8, reasoning="   "),
        ]
    )
    reply = json.dumps(
        {
            str(first.id): "该仓虽在禁区清单内，但本次需求的写入面落在其 owned 领域",
            str(second.id): "历史同类需求最终合入该仓",
        },
        ensure_ascii=False,
    )

    profile_reply = json.dumps(
        {
            "product_form": "",
            "domains": [],
            "change_kind": "brownfield",
            "capability_clusters": [],
            "non_goals": [],
            "reuse_summary": "",
        }
    )
    with (
        patch(_ARESOLVE, new=AsyncMock(return_value=SimpleNamespace(extra={"default_model": "m"}))),
        patch(_BUILD, return_value=FakeChatModel(responses=[profile_reply, reply])) as build,
    ):
        result = await _adapter(router).route(session)

    assert build.call_count == 2, "画像一次，多个禁区候选合并为一次解释调用"
    for candidate in result["candidates"]:
        assert candidate["evidence"]["boundary_override_reason"]
        assert candidate["evidence"]["unjustified_boundary_hit"] is False
    assert result["unjustified_boundary_hit_count"] == 0


async def test_llm_unavailable_flags_unjustified_boundary_hit() -> None:
    """情形 3：reasoning 空 + LLM 不可得 → 不抛、候选仍返回、被打 unjustified 标记并计数。"""
    session, router, blocked = await _boundary_session_and_router(reasoning="")

    with (
        patch(_ARESOLVE, new=AsyncMock(return_value=SimpleNamespace(extra={"default_model": "m"}))),
        patch(_BUILD, side_effect=RuntimeError("provider down")),
    ):
        result = await _adapter(router).route(session)

    candidate = result["candidates"][0]
    assert candidate["repository_id"] == str(blocked.id)
    assert candidate["evidence"]["unjustified_boundary_hit"] is True
    assert candidate["evidence"]["boundary_override_reason"] == ""
    assert result["unjustified_boundary_hit_count"] == 1


async def test_boundary_candidates_always_carry_reason_or_flag() -> None:
    """总不变量：凡命中禁区的候选，必有理由 或 有 unjustified 标记（绝无静默保留）。"""
    session = await _make_session(_spec(_GREENFIELD_POINTS))
    with_reason = await _make_repo("study-plan")
    without_reason = await _make_repo("legacy-plan")
    for repo in (with_reason, without_reason):
        await _make_charter(repo, boundaries=[{"rule": "不承接专项学习页与课程权益鉴权"}])
    router = _router(
        [
            _rv2_candidate(str(with_reason.id), "study-plan", 0.9, reasoning="命中能力节点: a"),
            _rv2_candidate(str(without_reason.id), "legacy-plan", 0.8, reasoning=""),
        ]
    )

    with patch(_EXPLAIN, new=AsyncMock(return_value={})):
        result = await _adapter(router).route(session)

    hits = [c for c in result["candidates"] if c["evidence"]["violated_boundaries"]]
    assert len(hits) == 2
    for candidate in hits:
        evidence = candidate["evidence"]
        assert evidence["boundary_override_reason"] or evidence["unjustified_boundary_hit"]
        assert bool(evidence["boundary_override_reason"]) != evidence["unjustified_boundary_hit"]


# ── stage_state["routing"] 契约（B4） ────────────────────────────────────


async def test_routing_contract_keys_present() -> None:
    """路由只产候选，不在代码调研前裁定 direct/indirect。"""
    session = await _make_session(_spec(_GREENFIELD_POINTS))
    high = await _make_repo("study-course")
    low = await _make_repo("onion-practice")
    router = _router(
        [
            _rv2_candidate(str(high.id), "study-course", 0.9, confidence="high"),
            _rv2_candidate(str(low.id), "onion-practice", 0.2, confidence="low"),
        ]
    )

    result = await _adapter(router).route(session)

    assert _TOP_LEVEL_KEYS <= set(result)
    assert "citations" in result
    assert set(result["weights_used"]) == {"router_base", "charter_match", "history_match"}
    for candidate in result["candidates"]:
        assert _CANDIDATE_KEYS <= set(candidate)
        assert candidate["role_suggestion"] == "candidate"


async def test_route_confidence_and_charter_do_not_decide_role() -> None:
    """high confidence/章程命中都只是候选证据，角色由后续逐仓调研决定。"""
    session = await _make_session(_spec(_GREENFIELD_POINTS))
    high_conf = await _make_repo("study-course")
    charter_owned = await _make_repo("onion-learning")
    plain = await _make_repo("onion-practice")
    await _make_charter(
        charter_owned, owned_domains=[{"domain": "培优/学习提分", "status": "planned"}]
    )
    router = _router(
        [
            _rv2_candidate(str(high_conf.id), "study-course", 0.9, confidence="high"),
            _rv2_candidate(str(charter_owned.id), "onion-learning", 0.4, confidence="low"),
            _rv2_candidate(str(plain.id), "onion-practice", 0.4, confidence="low"),
        ]
    )

    result = await _adapter(router).route(session)

    by_id = {c["repository_id"]: c for c in result["candidates"]}
    assert {item["role_suggestion"] for item in by_id.values()} == {"candidate"}


async def test_confirmed_team_repositories_survive_semantic_top_ten() -> None:
    """Top 10 是初筛预算；可信 Team 中低语义分仓仍可进入 placement/research。"""
    session = await _make_session(_spec(_GREENFIELD_POINTS))
    repositories = [await _make_repo(f"team-repo-{index}") for index in range(12)]
    router = _router(
        [
            _rv2_candidate(str(repo.id), repo.name, 1 - index / 20)
            for index, repo in enumerate(repositories[:10])
        ]
    )

    result = await _adapter(router).route(session)

    assert result["shortlist_count"] == 12
    assert set(result["hard_scope"]) == {str(repo.id) for repo in repositories}


async def test_route_context_preserves_provenance_without_hardening_references() -> None:
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_blueprint",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="route",
        stage_state={
            "decomposition": {
                "feature_meta": {
                    "prd": "高三专项",
                    "test_cases": ["完成课程后可练习"],
                    "access_token": "must-not-enter-routing",
                    "client_secret": "must-not-enter-routing",
                },
                "extra_evidence": [{"source": "technical_doc", "text": "调用 study-course"}],
            }
        },
    )

    context = await _aload_route_context(session)

    assert [entry["source_type"] for entry in context] == ["feature_meta", "extra_evidence"]
    assert all(entry["hard_constraint"] is False for entry in context)
    assert "must-not-enter-routing" not in str(context)


async def test_intent_recorded_from_feature_points() -> None:
    """主导 intent 取自 feature_points；混合需求平票取保守 brownfield。"""
    session = await _make_session(
        _spec(
            [
                _point("fp_01", "培优课入口改造", "brownfield", "改造既有培优课占位入口。"),
                _point("fp_02", "专项学习页", "greenfield", "新增专项学习页。"),
            ]
        )
    )
    repo = await _make_repo("study-course")
    router = _router([_rv2_candidate(str(repo.id), "study-course", 0.5)])

    result = await _adapter(router).route(session)

    assert result["intent"] == "brownfield"
    assert result["weights_used"]["router_base"] == pytest.approx(0.60)


# ── 降级语义 ──────────────────────────────────────────────────────────────


async def test_history_unavailable_is_explicit_not_silent_zero() -> None:
    """history 不可得 → 该项贡献 0 且 evidence 写 no_acting_user（不伪装成无命中）。"""
    session = await _make_session(_spec(_GREENFIELD_POINTS))
    repo = await _make_repo("study-course")
    router = _router([_rv2_candidate(str(repo.id), "study-course", 0.6)])
    history = _history(HistoryMatchResult(unavailable_reason="no_acting_user"))

    result = await _adapter(router, history).route(session)

    candidate = result["candidates"][0]
    assert candidate["breakdown"]["history_match"] == 0.0
    assert candidate["evidence"]["history_match_unavailable"] == "no_acting_user"


async def test_charter_load_failure_does_not_break_routing() -> None:
    """章程读抛异常 → 仍返回候选（章程分量全 0），不上抛。"""
    session = await _make_session(_spec(_GREENFIELD_POINTS))
    repo = await _make_repo("study-course")
    router = _router([_rv2_candidate(str(repo.id), "study-course", 0.6)])
    charter = SimpleNamespace(
        aload_charters=AsyncMock(side_effect=RuntimeError("db down")),
        acollect_charter_candidates=AsyncMock(return_value=[]),
        score_charter_match=score_charter_match,
    )
    adapter = BlueprintRouteAdapter(router=router, charter=charter, history=_history())

    result = await adapter.route(session)

    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["breakdown"]["charter_match"] == 0.0


async def test_history_failure_marks_retrieval_error() -> None:
    """history 分量抛异常 → 标 retrieval_error 并继续（best-effort 不阻断路由）。"""
    session = await _make_session(_spec(_GREENFIELD_POINTS))
    repo = await _make_repo("study-course")
    router = _router([_rv2_candidate(str(repo.id), "study-course", 0.6)])
    history = AsyncMock(side_effect=RuntimeError("qdrant down"))

    result = await _adapter(router, history).route(session)

    assert result["candidates"][0]["evidence"]["history_match_unavailable"] == "retrieval_error"


async def test_v1_fallback_router_version_is_visible_in_evidence() -> None:
    """v1_fallback（matched_node_paths 恒空）时 router_version 进 evidence，降级可解释。"""
    session = await _make_session(_spec(_GREENFIELD_POINTS))
    repo = await _make_repo("study-course")
    router = _router(
        [_rv2_candidate(str(repo.id), "study-course", 0.6, matched_node_paths=[])],
        router_version="v1_fallback",
    )

    result = await _adapter(router).route(session)

    assert result["router_version"] == "v1_fallback"
    assert result["candidates"][0]["evidence"]["router_version"] == "v1_fallback"
    assert result["candidates"][0]["evidence"]["matched_node_paths"] == []


async def test_missing_team_clarifies_before_unscoped_routing() -> None:
    """没有可信 Team 时必须先澄清，不能以空候选为由退化到全库路由。"""
    session = await _make_session(_spec(_GREENFIELD_POINTS))
    router = _router([], router_version="v2_stage0_only")

    result = await _adapter(router).route(session)

    assert result["candidates"] == []
    assert result["router_version"] == "clarify"
    assert result["clarify_reason"] == "missing_team"
    assert _TOP_LEVEL_KEYS <= set(result)
