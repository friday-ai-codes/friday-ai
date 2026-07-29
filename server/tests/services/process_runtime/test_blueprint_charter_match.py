"""章程分量单测（CHARTER-02，112-03 Task 1）。

守四件事：

1. **`owned_domains` 三档语义**：implemented 命中 > planned 命中 > 0——`planned` 严格
   为正这条断言直接锁住「规划中领域也能把仓推进候选」的机制（高三提分 case 前提）。
2. **禁区判负与 evolution 降权**：`boundaries` 命中使总分为负，且能抵消 owned 正分；
   `maintenance_only` / `deprecated` 各自降权并在 `penalty_reasons` 留证据。
3. **畸形章程不抛**：非 list / item 非 dict / 非法 status / 缺 domain 全部按回退处理；
   多命中正分被 clamp 到 1.0（防「章程写越长分越高」）。
4. **ORM 读的 best-effort 与收窄**：`aload_charters` 一次取多仓且缺章程仓不出现；
   `acollect_charter_candidates` 能凭 `status=planned` 产出补入候选、尊重 exclude 与
   `repository_ids` 收窄。
"""

from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async

from repositories.models import RepoCharter, Repository
from services.process_runtime.blueprint_charter_match import (
    DEFAULT_CHARTER_RULES,
    acollect_charter_candidates,
    aload_charters,
    score_charter_match,
)

# 高三提分专项语料：培优/学习提分领域 + 权益鉴权禁区（DESIGN §5.7 实证语料）
_TERMS = ["培优课入口改造", "高三提分专项学习页", "专项练习组卷"]


def _charter(**overrides) -> dict:
    base = {
        "owned_domains": [],
        "boundaries": [],
        "evolution": "active",
        "source": "human_confirmed",
        "version": 2,
    }
    base.update(overrides)
    return base


# ── 纯函数：owned_domains 三档 ────────────────────────────────────────────


def test_owned_implemented_scores_higher_than_planned() -> None:
    """implemented 命中 > planned 命中 > 0，且两者都记进 matched_domains。"""
    implemented = score_charter_match(
        _charter(owned_domains=[{"domain": "培优/学习提分", "status": "implemented"}]),
        query_terms=_TERMS,
    )
    planned = score_charter_match(
        _charter(owned_domains=[{"domain": "培优/学习提分", "status": "planned"}]),
        query_terms=_TERMS,
    )

    assert implemented.score > planned.score > 0.0
    assert implemented.matched_domains == [{"domain": "培优/学习提分", "status": "implemented"}]
    assert planned.matched_domains == [{"domain": "培优/学习提分", "status": "planned"}]


def test_planned_domain_scores_strictly_positive() -> None:
    """planned 命中严格 > 0 —— 「规划中领域也能把仓推进候选」的机制锁。"""
    result = score_charter_match(
        _charter(owned_domains=[{"domain": "培优/学习提分", "status": "planned"}]),
        query_terms=_TERMS,
    )

    assert result.score == pytest.approx(DEFAULT_CHARTER_RULES["owned_planned"])
    assert result.score > 0.0


def test_sentence_style_boundary_rule_matches_via_ngram() -> None:
    """无分隔符整句禁区规则也能命中连写需求文本（CJK 3-gram 交集路径）。

    章程禁区常写成整句「不承接课程权益鉴权」，需求也是连写长句——两侧互不包含，
    片段子串判定必然漏判；漏判会让「命中禁区应降权」这条机制在生产上静默失效。
    """
    result = score_charter_match(
        _charter(boundaries=[{"rule": "不承接课程权益鉴权"}]),
        query_terms=["在专项学习页展示课程内容与权益鉴权状态"],
    )

    assert result.violated_boundaries == ["不承接课程权益鉴权"]
    assert result.score < 0.0


def test_unrelated_sentence_rule_does_not_match() -> None:
    """无关整句规则不误判（3-gram 交集为空 → 不降权）。"""
    result = score_charter_match(
        _charter(boundaries=[{"rule": "不承接支付结算与发票开具"}]),
        query_terms=["在专项学习页展示课程内容与权益鉴权状态"],
    )

    assert result.violated_boundaries == []
    assert result.score == 0.0


def test_single_generic_ngram_overlap_is_not_a_boundary_hit() -> None:
    """MJ-06：只共享一个通用 3-gram（"配置下"）不判命中。

    命中后果是重的（boundary_hit=-1.0 单条即可把满分 owned 压回 0，并污染确认门快照的
    violated_boundaries 与 115 呈现面），单个通用 3-gram 偶然重合不足以承担它。
    """
    result = score_charter_match(
        _charter(boundaries=[{"rule": "不承接服务端配置下发"}]),
        query_terms=["新增查询配置下拉框"],
    )

    assert result.violated_boundaries == []
    assert result.score == 0.0


def test_multi_ngram_overlap_still_hits_after_threshold() -> None:
    """阈值不得反噬真命中：多个 3-gram 重合的整句禁区仍判命中（回归护栏）。"""
    result = score_charter_match(
        _charter(boundaries=[{"rule": "不承接课程权益鉴权"}]),
        query_terms=["展示课程内容与权益鉴权状态"],
    )

    assert result.violated_boundaries == ["不承接课程权益鉴权"]
    assert result.score < 0.0


def test_no_domain_match_scores_zero() -> None:
    """章程存在但 owned_domains 不命中 → 0 分（不倒扣）。"""
    result = score_charter_match(
        _charter(owned_domains=[{"domain": "支付结算", "status": "implemented"}]),
        query_terms=_TERMS,
    )

    assert result.score == 0.0
    assert result.matched_domains == []


# ── 纯函数：禁区与 evolution ──────────────────────────────────────────────


def test_boundary_hit_makes_score_negative() -> None:
    """boundaries 命中使总分为负并记 violated_boundaries。"""
    result = score_charter_match(
        _charter(boundaries=[{"rule": "不承接培优课入口改造"}]),
        query_terms=_TERMS,
    )

    assert result.score < 0.0
    assert result.violated_boundaries == ["不承接培优课入口改造"]
    assert any("boundary_hit" in reason for reason in result.penalty_reasons)


def test_boundary_offsets_owned_positive() -> None:
    """owned 命中 + boundary 命中 → 正分被抵消到 <= 0 且 violated_boundaries 非空。"""
    result = score_charter_match(
        _charter(
            owned_domains=[{"domain": "培优/学习提分", "status": "implemented"}],
            boundaries=[{"rule": "不承接培优课入口改造"}],
        ),
        query_terms=_TERMS,
    )

    assert result.score <= 0.0
    assert result.violated_boundaries
    assert result.matched_domains


@pytest.mark.parametrize(
    ("evolution", "reason"),
    [
        ("maintenance_only", "evolution_maintenance_only"),
        ("deprecated", "evolution_deprecated"),
    ],
)
def test_evolution_penalties_recorded(evolution: str, reason: str) -> None:
    """maintenance_only / deprecated 各自降权且降权理由进 penalty_reasons。"""
    baseline = score_charter_match(
        _charter(owned_domains=[{"domain": "培优/学习提分", "status": "implemented"}]),
        query_terms=_TERMS,
    )
    penalized = score_charter_match(
        _charter(
            owned_domains=[{"domain": "培优/学习提分", "status": "implemented"}],
            evolution=evolution,
        ),
        query_terms=_TERMS,
    )

    assert penalized.score < baseline.score
    assert reason in penalized.penalty_reasons
    assert penalized.evolution == evolution


def test_deprecated_penalty_exceeds_maintenance_only() -> None:
    """deprecated 降权强度严格大于 maintenance_only。"""
    maintenance = score_charter_match(
        _charter(
            owned_domains=[{"domain": "培优/学习提分", "status": "implemented"}],
            evolution="maintenance_only",
        ),
        query_terms=_TERMS,
    )
    deprecated = score_charter_match(
        _charter(
            owned_domains=[{"domain": "培优/学习提分", "status": "implemented"}],
            evolution="deprecated",
        ),
        query_terms=_TERMS,
    )

    assert deprecated.score < maintenance.score


# ── 纯函数：无章程与畸形输入 ──────────────────────────────────────────────


@pytest.mark.parametrize("charter", [None, {}])
def test_missing_charter_is_zero_with_reason(charter) -> None:
    """无章程 → 0.0 + penalty_reasons==["no_charter"]（无证据，不是负分）。"""
    result = score_charter_match(charter, query_terms=_TERMS)

    assert result.score == 0.0
    assert result.penalty_reasons == ["no_charter"]
    assert result.matched_domains == []


@pytest.mark.parametrize(
    "malformed",
    [
        {"owned_domains": "not-a-list"},
        {"owned_domains": ["not-a-dict", 42, None]},
        {"owned_domains": [{"status": "planned"}]},  # 缺 domain
        {"boundaries": "not-a-list"},
        {"boundaries": [{"decided_by": "human"}]},  # 缺 rule
        {"evolution": 123},
        {"version": "abc"},
    ],
)
def test_malformed_charter_does_not_raise(malformed: dict) -> None:
    """畸形章程逐项跳过、不抛、分数落在合法区间。"""
    result = score_charter_match(_charter(**malformed), query_terms=_TERMS)

    assert -1.0 <= result.score <= 1.0


def test_illegal_status_falls_back_to_implemented() -> None:
    """非法 status 按 implemented 处理（与 normalize_charter_draft 回退一致）。"""
    result = score_charter_match(
        _charter(owned_domains=[{"domain": "培优/学习提分", "status": "sort-of-done"}]),
        query_terms=_TERMS,
    )

    assert result.matched_domains == [{"domain": "培优/学习提分", "status": "implemented"}]
    assert result.score == pytest.approx(DEFAULT_CHARTER_RULES["owned_implemented"])


def test_positive_score_clamped_to_one() -> None:
    """多条 owned 命中的正分被 clamp 到 1.0（章程写越长分越高的漏洞被堵）。"""
    result = score_charter_match(
        _charter(
            owned_domains=[
                {"domain": "培优/学习提分", "status": "implemented"},
                {"domain": "专项学习页", "status": "implemented"},
                {"domain": "专项练习组卷", "status": "implemented"},
            ]
        ),
        query_terms=_TERMS,
    )

    assert result.score == pytest.approx(1.0)
    assert len(result.matched_domains) == 3


def test_evidence_carries_source_and_version() -> None:
    """证据带 charter_source / charter_version（T-112-11：115 能标注草案依据）。"""
    result = score_charter_match(
        _charter(
            owned_domains=[
                {"domain": "培优/学习提分", "status": "planned", "citations": ["cit_a", "cit_a"]}
            ],
            source="ai_draft",
            version=3,
        ),
        query_terms=_TERMS,
    )

    assert result.charter_source == "ai_draft"
    assert result.charter_version == 3
    assert result.citation_ids == ["cit_a"]


def test_empty_query_terms_never_match() -> None:
    """空 query_terms 不命中任何领域/禁区（避免空需求把所有仓都拉进来）。"""
    result = score_charter_match(
        _charter(
            owned_domains=[{"domain": "培优/学习提分", "status": "implemented"}],
            boundaries=[{"rule": "不承接培优课入口改造"}],
        ),
        query_terms=[],
    )

    assert result.score == 0.0
    assert result.matched_domains == []
    assert result.violated_boundaries == []


# ── ORM 读：aload_charters / acollect_charter_candidates ──────────────────


async def _make_repo(name: str) -> Repository:
    return await Repository.objects.acreate(
        name=name,
        git_url=f"https://example.com/{name}.git",
        git_platform="github",
        default_branch="main",
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


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_aload_charters_batch_and_skips_missing() -> None:
    """一次取多仓章程；无章程的仓不出现在结果里。"""
    with_charter = await _make_repo("onion-learning")
    without_charter = await _make_repo("study-plan")
    await _make_charter(
        with_charter,
        owned_domains=[{"domain": "培优/学习提分", "status": "planned"}],
        source=RepoCharter.Source.AI_DRAFT,
        version=2,
    )

    charters = await aload_charters([str(with_charter.id), str(without_charter.id)])

    assert set(charters) == {str(with_charter.id)}
    row = charters[str(with_charter.id)]
    assert row["owned_domains"] == [{"domain": "培优/学习提分", "status": "planned"}]
    assert row["source"] == "ai_draft"
    assert row["version"] == 2


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_aload_charters_empty_input_returns_empty() -> None:
    """空入参不打库、返回空 dict（形状恒定）。"""
    assert await aload_charters([]) == {}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_collect_charter_candidates_returns_planned_owner() -> None:
    """章程 owned_domains(status=planned) 命中的仓被作为补入候选返回（高三提分机制）。"""
    repo = await _make_repo("onion-learning")
    await _make_charter(repo, owned_domains=[{"domain": "培优/学习提分", "status": "planned"}])

    candidates = await acollect_charter_candidates(query_terms=_TERMS, exclude_repository_ids=set())

    assert [c["repository_id"] for c in candidates] == [str(repo.id)]
    assert candidates[0]["repository_name"] == "onion-learning"
    assert candidates[0]["charter_match_raw"] > 0.0
    assert candidates[0]["source"] == "charter_supplement"
    assert candidates[0]["matched_domains"] == [{"domain": "培优/学习提分", "status": "planned"}]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_collect_charter_candidates_respects_exclusion() -> None:
    """已在候选里的仓被 exclude_repository_ids 排除（避免重复补入）。"""
    repo = await _make_repo("onion-learning")
    await _make_charter(repo, owned_domains=[{"domain": "培优/学习提分", "status": "planned"}])

    candidates = await acollect_charter_candidates(
        query_terms=_TERMS, exclude_repository_ids={str(repo.id)}
    )

    assert candidates == []


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_collect_charter_candidates_respects_repository_scope() -> None:
    """repository_ids 收窄生效：范围外的仓即便命中也不补入。"""
    in_scope = await _make_repo("onion-learning")
    out_of_scope = await _make_repo("legacy-learning")
    for repo in (in_scope, out_of_scope):
        await _make_charter(repo, owned_domains=[{"domain": "培优/学习提分", "status": "planned"}])

    candidates = await acollect_charter_candidates(
        query_terms=_TERMS,
        exclude_repository_ids=set(),
        repository_ids=[str(in_scope.id)],
    )

    assert [c["repository_id"] for c in candidates] == [str(in_scope.id)]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_collect_charter_candidates_orders_and_limits() -> None:
    """按 charter_match_raw 降序取前 limit（implemented 命中优先于 planned）。"""
    planned_repo = await _make_repo("onion-learning")
    implemented_repo = await _make_repo("study-course")
    await _make_charter(
        planned_repo, owned_domains=[{"domain": "培优/学习提分", "status": "planned"}]
    )
    await _make_charter(
        implemented_repo,
        owned_domains=[{"domain": "培优/学习提分", "status": "implemented"}],
    )

    candidates = await acollect_charter_candidates(
        query_terms=_TERMS, exclude_repository_ids=set(), limit=1
    )

    assert [c["repository_id"] for c in candidates] == [str(implemented_repo.id)]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_collect_charter_candidates_empty_terms_short_circuits() -> None:
    """空 query_terms 不打库、返回空（不把全库仓拉进候选）。"""
    repo = await _make_repo("onion-learning")
    await _make_charter(repo, owned_domains=[{"domain": "培优/学习提分", "status": "planned"}])

    assert await acollect_charter_candidates(query_terms=[], exclude_repository_ids=set()) == []
