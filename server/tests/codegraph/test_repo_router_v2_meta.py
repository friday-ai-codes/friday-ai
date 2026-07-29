"""RepoRouterV2 六信号生产接线集成测试（Phase 106-06，ROUTE-03/04/05/06）。

覆盖四个行为面：

1. **repo_meta 组装 + 打分注入**：全量 meta 可用时候选 breakdown 出现
   domain/stack 贡献键且 Σ==score；criticality 旁路字段有值；快照携带
   weight_config（生效全值）/ repo_meta（per-候选）/ stage0.scored_at。
2. **降级矩阵**（四行独立用例）：dense 查询异常 → S_top 回退 RRF；
   nr_snapshot 缺失 → n_bar None（breadth denom=1.0）；embedding 未配置 →
   facet 全走 T1；weight_config 行非法 → loader 回退默认——四种降级下
   路由全部可用（真值 5）。
3. **保存即生效（ROUTE-06 / SC-4）**：写入新权重配置后（无重启）下一次
   route() 按新值打分，快照 weight_set_version 与 breakdown 随之变化。
4. **免 N+1 守护**：一次路由恰 2 次 Qdrant 查询（hybrid + dense）+ 恰 1 次
   FileIndex 聚合；repo_meta 组装整体异常 → 回退 legacy 三信号（永不反噬）。

mock 面：QdrantService.hybrid/dense_search_by_name、SparseEncoderService.encode、
EmbeddingService.generate_embedding/get_config 全部 patch（沿用
test_repo_router_v2_degraded 的 seam 风格）；Stage 1 一律 use_llm=False
（Stage 0 行为聚焦）。DB 面走真实 ORM：``django_db(transaction=True)``——
route() 内 loader / FileIndex 聚合经 ``sync_to_async(thread_sensitive=False)``
在独立连接执行，普通 rollback 事务的数据对其不可见（106-02 已踩过）。
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any

import pytest
from asgiref.sync import sync_to_async
from django.core.cache import cache

from codegraph.services.repo_router_scoring import DEFAULT_WEIGHT_CONFIG, WEIGHT_SET_VERSION
from codegraph.services.repo_router_v2 import STAGE0_REPO_K, RepoRouterV2
from services.embedding import EmbeddingService
from services.qdrant_service import QdrantService
from services.sparse_encoder import SparseEncoderService
from system.models import SettingKeys, SystemSetting
from system.settings_service import _cache_key

# transaction=True：route() 的配置 loader / FileIndex 聚合在
# thread_sensitive=False 的独立线程连接上执行，测试写入必须真实提交才可见
# （与 test_repo_router_adapter 同理由）。
pytestmark = pytest.mark.django_db(transaction=True)

QUERY = "学习工具 的 Python 高三提分需求"


@pytest.fixture(autouse=True)
def _clear_setting_cache():
    """settings_service 缓存跨用例共享（locmem 不随事务回滚），前后各清一次。"""
    keys = (
        SettingKeys.REPO_ROUTER_WEIGHT_CONFIG,
        SettingKeys.REPO_ROUTER_NR_SNAPSHOT,
        SettingKeys.REPO_ROUTER_ALIAS_DICT,
    )
    for key in keys:
        cache.delete(_cache_key(key))
    yield
    for key in keys:
        cache.delete(_cache_key(key))


# ---------------------------------------------------------------------------
# fixture：3 仓（大仓多命中 / 小仓单命中 / 无 facets 仓）复现尺寸偏置场景
# ---------------------------------------------------------------------------


@sync_to_async
def _make_repos() -> tuple[str, str, str]:
    """建 3 个 Repository + 2 条 FileIndex（bare 仓无行 → 活跃度枚举回退）。"""
    from repositories.models import FileIndex, Repository

    big = Repository.objects.create(name="big-repo", git_url="https://e.com/big.git")
    small = Repository.objects.create(name="small-repo", git_url="https://e.com/small.git")
    bare = Repository.objects.create(name="bare-repo", git_url="https://e.com/bare.git")
    FileIndex.objects.create(
        repository=big,
        file_path="src/a.py",
        file_hash="h1",
        last_commit_authored_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    FileIndex.objects.create(
        repository=small,
        file_path="src/b.py",
        file_hash="h2",
        last_commit_authored_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
    )
    return str(big.id), str(small.id), str(bare.id)


@sync_to_async
def _write_setting(key: str, payload: dict[str, Any]) -> None:
    """写 SystemSetting 行（post_save signal 自动失效 60s 读缓存 → 保存即生效）。"""
    SystemSetting.objects.update_or_create(
        key=key, defaults={"value": json.dumps(payload, ensure_ascii=False)}
    )


_FACETS_FULL = {
    "活跃度": "活跃开发",
    "业务线/产品线": "学习工具",
    "技术栈": "Python/Vue",
    "关键程度": "核心",
}
_FACETS_SMALL = {
    "活跃度": "活跃开发",
    "业务线/产品线": "学习工具",
    "技术栈": "Python",
    "关键程度": "重要",
}


def _hit(
    node_id: str,
    rid: str,
    score: float,
    *,
    facets: dict[str, str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "node_id": node_id,
        "repository_id": rid,
        "repo_name": rid,
        "node_path": f"root/能力/{node_id}",
        "built_at": "2026-07-29T00:00:00Z",
    }
    if facets is not None:
        payload["facets"] = json.dumps(facets, ensure_ascii=False)
    return {"id": node_id, "score": score, "payload": payload}


def _hybrid_hits(big: str, small: str, bare: str) -> list[dict[str, Any]]:
    """大仓 6 命中（衰减分）/ 小仓 1 强命中 / bare 仓 1 弱命中。"""
    hits = [_hit(f"b{i}", big, 0.032 - i * 0.002, facets=_FACETS_FULL) for i in range(6)]
    hits.append(_hit("s0", small, 0.032, facets=_FACETS_SMALL))
    hits.append(_hit("x0", bare, 0.012))
    return hits


def _dense_hits(big: str, small: str) -> list[dict[str, Any]]:
    """dense-only 查询返回（score 即余弦）；bare 仓不在 dense top-50（Pitfall 6）。"""
    return [
        {"id": "s0", "score": 0.62, "payload": {"repository_id": small}},
        {"id": "b0", "score": 0.55, "payload": {"repository_id": big}},
        {"id": "b1", "score": 0.48, "payload": {"repository_id": big}},
    ]


def _install_search_stack(
    monkeypatch: pytest.MonkeyPatch,
    *,
    hybrid_hits: list[dict[str, Any]],
    dense_hits: list[dict[str, Any]] | None = None,
    dense_raises: bool = False,
    emb_configured: bool = False,
) -> dict[str, Any]:
    """patch 检索/编码五件套，返回调用计数（免 N+1 断言用）。"""
    calls: dict[str, Any] = {"hybrid": 0, "dense": 0, "embed": 0, "dense_filters": None}

    def fake_hybrid(collection_name, query_dense, query_sparse, top_k=50, filters=None):
        calls["hybrid"] += 1
        return hybrid_hits

    def fake_dense(collection_name, query_dense, *, top_k=50, filters=None):
        calls["dense"] += 1
        calls["dense_filters"] = filters
        if dense_raises:
            raise RuntimeError("qdrant dense down")
        return list(dense_hits or [])

    def fake_sparse(query):
        return {"indices": [1, 2], "values": [0.5, 0.5]}

    async def fake_embed(text):
        calls["embed"] += 1
        return [0.1] * 8

    async def fake_get_config():
        return {
            "api_url": "http://emb.local" if emb_configured else None,
            "api_key": None,
            "model": "test-embed-model",
            "dimension": 8,
        }

    monkeypatch.setattr(QdrantService, "hybrid_search_by_name", fake_hybrid)
    monkeypatch.setattr(QdrantService, "dense_search_by_name", fake_dense)
    monkeypatch.setattr(SparseEncoderService, "encode", fake_sparse)
    monkeypatch.setattr(EmbeddingService, "generate_embedding", fake_embed)
    monkeypatch.setattr(EmbeddingService, "get_config", fake_get_config)
    return calls


def _spy_latest_commits(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """包一层 _load_latest_commits：记录每次调用的 rid 列表（免 N+1 守护）。"""
    calls: list[list[str]] = []
    orig = RepoRouterV2._load_latest_commits

    def spy(repository_ids: list[str]) -> dict[str, str | None]:
        calls.append(list(repository_ids))
        return orig(repository_ids)

    monkeypatch.setattr(RepoRouterV2, "_load_latest_commits", staticmethod(spy))
    return calls


def _by_repo(result: Any) -> dict[str, Any]:
    return {c.repo_id: c for c in result.candidates}


# ---------------------------------------------------------------------------
# 1. 全量 meta 可用：breakdown 新键 / criticality / 快照契约
# ---------------------------------------------------------------------------


async def test_full_meta_breakdown_criticality_and_snapshot(monkeypatch) -> None:
    """全量 meta：domain/stack 键入 breakdown 且 Σ==score；criticality 有值；
    快照 weight_config/repo_meta/scored_at 齐备且 repo_meta 仓数受限。"""
    big, small, bare = await _make_repos()
    await _write_setting(
        SettingKeys.REPO_ROUTER_NR_SNAPSHOT,
        {
            "n_r_by_repo": {big: 620, small: 30, bare: 40},
            "n_bar": 60.0,
            "generated_at": "2026-07-29T00:00:00Z",
        },
    )
    _install_search_stack(
        monkeypatch,
        hybrid_hits=_hybrid_hits(big, small, bare),
        dense_hits=_dense_hits(big, small),
        emb_configured=True,
    )

    result = await RepoRouterV2.route(QUERY, use_llm=False, top_k=3)

    assert result.router_version == "v2_stage0_only"
    assert result.candidates
    top = result.candidates[0]
    # SC-2：需求提到业务域/技术栈 → domain/stack 贡献键出现且 Σ==score；
    # 需求未提团队 → team 键不出现（条件信号缺失重归一化）。
    assert "domain" in top.breakdown and "stack" in top.breakdown
    assert "team" not in top.breakdown
    assert abs(math.fsum(top.breakdown.values()) - top.score) < 1e-9
    # criticality 旁路字段：核心 → 1.0（不进 breakdown）
    by_repo = _by_repo(result)
    assert by_repo[big].criticality == 1.0
    assert by_repo[big].to_dict()["criticality"] == 1.0
    assert "criticality" not in top.breakdown

    snap = result.snapshot
    # weight_config：本次生效全值（默认配置 → 当前 WEIGHT_SET_VERSION）
    wc = snap["weight_config"]
    assert wc["weight_set_version"] == WEIGHT_SET_VERSION
    assert wc["constants"]["n_bar"] == 60.0
    # 锚点表随快照（MJ-01）：外置锚点若不进快照，回放的 tie-break 顺序不可复现
    assert wc["criticality_anchors"] == DEFAULT_WEIGHT_CONFIG["criticality_anchors"]
    assert isinstance(wc["alias_dict_hash"], str) and len(wc["alias_dict_hash"]) == 64
    assert wc["embedding_model_id"] == "test-embed-model"
    # repo_meta：记全部分桶仓（BL-02 自包含性——回放按全量 node_hits 重算，
    # 缺 meta 的仓会拿到缺失红利并污染比对；体积护栏落在 node_hits 上）
    repo_meta = snap["repo_meta"]
    assert set(repo_meta) == {big, small, bare}
    assert len(snap["candidates"]) <= STAGE0_REPO_K
    assert repo_meta[big]["n_r"] == 620
    assert repo_meta[big]["dense_cos_max"] == 0.55
    assert repo_meta[big]["last_commit_at"].startswith("2026-07-01")
    assert repo_meta[big]["facet_scores"]["domain"] == {"score": 1.0, "layer": "t1"}
    assert repo_meta[big]["criticality_value"] == "核心"
    # bare 仓：不在 dense top-50 → dense_cos_max None（S_top 回退 RRF，Pitfall 6）
    assert repo_meta[bare]["dense_cos_max"] is None
    # scored_at：ISO 字符串（活跃度衰减时间锚点，106-07 回放消费）
    scored_at = snap["stage0"]["scored_at"]
    assert datetime.fromisoformat(scored_at).tzinfo is not None
    # versions 与 weight_config 同源（占位换真，SC-4）
    assert snap["versions"]["weight_set_version"] == WEIGHT_SET_VERSION


# ---------------------------------------------------------------------------
# 2. 降级矩阵（四行独立用例）——路由全部可用
# ---------------------------------------------------------------------------


async def test_degraded_dense_failure_falls_back_rrf(monkeypatch) -> None:
    """dense 查询抛异常 → 全仓 dense_cos_max=None（S_top 回退 RRF s_hat），路由成功。"""
    big, small, bare = await _make_repos()
    _install_search_stack(
        monkeypatch,
        hybrid_hits=_hybrid_hits(big, small, bare),
        dense_raises=True,
    )

    result = await RepoRouterV2.route(QUERY, use_llm=False)

    assert result.candidates
    repo_meta = result.snapshot["repo_meta"]
    assert all(m["dense_cos_max"] is None for m in repo_meta.values())
    # 文本主干仍有贡献（RRF fallback 生效）
    assert result.candidates[0].breakdown["text"] > 0.0


async def test_degraded_nr_snapshot_missing(monkeypatch) -> None:
    """nr_snapshot 缺失 → n_bar=None（breadth denom=1.0 降级），路由成功。"""
    big, small, bare = await _make_repos()
    _install_search_stack(
        monkeypatch,
        hybrid_hits=_hybrid_hits(big, small, bare),
        dense_hits=_dense_hits(big, small),
    )

    result = await RepoRouterV2.route(QUERY, use_llm=False)

    assert result.candidates
    assert result.snapshot["weight_config"]["constants"]["n_bar"] is None
    assert all(m["n_r"] is None for m in result.snapshot["repo_meta"].values())


async def test_degraded_embedding_unconfigured_t1_only(monkeypatch) -> None:
    """embedding 未配置 → facet_scores 全走 T1（无 t2 层），且无额外 embedding 调用。"""
    big, small, bare = await _make_repos()
    calls = _install_search_stack(
        monkeypatch,
        hybrid_hits=_hybrid_hits(big, small, bare),
        dense_hits=_dense_hits(big, small),
        emb_configured=False,
    )

    result = await RepoRouterV2.route(QUERY, use_llm=False)

    assert result.candidates
    layers = {
        entry["layer"]
        for meta in result.snapshot["repo_meta"].values()
        for entry in meta["facet_scores"].values()
    }
    assert "t2" not in layers
    assert "t1" in layers  # query 提到「学习工具」/「Python」→ T1 命中
    # 零额外 embedding：仅 stage0 的 query embedding 一次
    assert calls["embed"] == 1


async def test_degraded_invalid_weight_config_row(monkeypatch) -> None:
    """weight_config 行非法（网格外权重）→ loader 回退默认，路由成功。"""
    big, small, bare = await _make_repos()
    await _write_setting(
        SettingKeys.REPO_ROUTER_WEIGHT_CONFIG,
        {
            "weights": {
                "text": 0.55,
                "domain": 0.13,  # 不在离散网格 → validate 拒绝 → 回退 DEFAULT
                "activity": 0.12,
                "stack": 0.08,
                "team": 0.05,
            },
            "weight_set_version": "should-not-take-effect",
        },
    )
    _install_search_stack(
        monkeypatch,
        hybrid_hits=_hybrid_hits(big, small, bare),
        dense_hits=_dense_hits(big, small),
    )

    result = await RepoRouterV2.route(QUERY, use_llm=False)

    assert result.candidates
    assert result.snapshot["weight_config"]["weight_set_version"] == WEIGHT_SET_VERSION


# ---------------------------------------------------------------------------
# 3. 保存即生效（ROUTE-06 / SC-4）
# ---------------------------------------------------------------------------


async def test_save_takes_effect_without_restart(monkeypatch) -> None:
    """写入新权重配置后（无重启）下一次 route() 按新值打分：版本换新 + breakdown 变化。"""
    big, small, bare = await _make_repos()
    _install_search_stack(
        monkeypatch,
        hybrid_hits=_hybrid_hits(big, small, bare),
        dense_hits=_dense_hits(big, small),
    )

    first = await RepoRouterV2.route(QUERY, use_llm=False)
    assert first.snapshot["weight_config"]["weight_set_version"] == WEIGHT_SET_VERSION
    first_domain = _by_repo(first)[big].breakdown["domain"]

    # 合法新配置：domain 0.15→0.20、text 0.55→0.40（均在网格内，INV-R2 成立）
    await _write_setting(
        SettingKeys.REPO_ROUTER_WEIGHT_CONFIG,
        {
            "weights": {
                "text": 0.40,
                "domain": 0.20,
                "activity": 0.12,
                "stack": 0.08,
                "team": 0.05,
            },
            "weight_set_version": "test-v2",
        },
    )

    second = await RepoRouterV2.route(QUERY, use_llm=False)

    assert second.snapshot["weight_config"]["weight_set_version"] == "test-v2"
    assert second.snapshot["versions"]["weight_set_version"] == "test-v2"
    second_domain = _by_repo(second)[big].breakdown["domain"]
    assert second_domain > first_domain  # 权重上调 → domain 贡献变大


# ---------------------------------------------------------------------------
# 4. 免 N+1 守护 + 整体回退
# ---------------------------------------------------------------------------


async def test_one_route_query_budget_no_nplus1(monkeypatch) -> None:
    """一次路由恰 2 次 Qdrant 查询（hybrid + dense）+ 恰 1 次 FileIndex 聚合。"""
    big, small, bare = await _make_repos()
    calls = _install_search_stack(
        monkeypatch,
        hybrid_hits=_hybrid_hits(big, small, bare),
        dense_hits=_dense_hits(big, small),
    )
    agg_calls = _spy_latest_commits(monkeypatch)

    result = await RepoRouterV2.route(QUERY, use_llm=False)

    assert result.candidates
    assert calls["hybrid"] == 1
    assert calls["dense"] == 1
    assert len(agg_calls) == 1  # 一次聚合覆盖全部候选仓——无循环内查询
    assert sorted(agg_calls[0]) == sorted([big, small, bare])
    # dense 查询按分桶候选仓过滤（与 hybrid 同款 repository_id 构造）
    assert sorted(calls["dense_filters"]["repository_id"]) == sorted([big, small, bare])


async def test_meta_overall_failure_falls_back_legacy(monkeypatch) -> None:
    """repo_meta 组装整体异常 → 回退 legacy 三信号路径成功（观测永不反噬路由）。"""
    big, small, bare = await _make_repos()
    _install_search_stack(
        monkeypatch,
        hybrid_hits=_hybrid_hits(big, small, bare),
        dense_hits=_dense_hits(big, small),
    )

    async def boom(node_hits, query, query_dense, config):
        raise RuntimeError("meta pipeline exploded")

    monkeypatch.setattr(RepoRouterV2, "_load_repo_meta", boom)

    result = await RepoRouterV2.route(QUERY, use_llm=False)

    assert result.candidates
    top = result.candidates[0]
    # legacy 三信号 breakdown：无 domain/stack/team 键
    assert set(top.breakdown) <= {"text", "breadth", "activity"}
    assert abs(math.fsum(top.breakdown.values()) - top.score) < 1e-9
    # legacy 回退不写新快照节（106-07 以「缺 weight_config 节」识别 legacy 快照）
    assert "weight_config" not in result.snapshot
    assert "repo_meta" not in result.snapshot
    assert result.snapshot["versions"]["weight_set_version"]  # 版本位仍有值


# ---------------------------------------------------------------------------
# 5. 尺寸偏置：breadth 反向倾斜在生产链路成立（SC-1 机制的路由侧印证）
# ---------------------------------------------------------------------------


async def test_size_bias_breadth_inverse_tilt_in_production_chain(monkeypatch) -> None:
    """N_r 大的仓（620 节点、6 命中）breadth 贡献 <= N_r 小的仓（30 节点、1 命中）
    ——pivoted size normalization 在生产 route() 链路生效（golden 侧归 106-08）。"""
    big, small, bare = await _make_repos()
    await _write_setting(
        SettingKeys.REPO_ROUTER_NR_SNAPSHOT,
        {
            "n_r_by_repo": {big: 620, small: 30, bare: 40},
            "n_bar": 60.0,
            "generated_at": "2026-07-29T00:00:00Z",
        },
    )
    _install_search_stack(
        monkeypatch,
        hybrid_hits=_hybrid_hits(big, small, bare),
        dense_hits=_dense_hits(big, small),
    )

    result = await RepoRouterV2.route(QUERY, use_llm=False, top_k=3)

    by_repo = _by_repo(result)
    # big/small 两仓 facets 形态一致（同 D）——breadth 贡献可直接比较：
    # 大仓 6 命中被 pivoted denom（620/60）压制，小仓单命中反而更高。
    assert by_repo[small].breakdown["breadth"] > by_repo[big].breakdown["breadth"]
