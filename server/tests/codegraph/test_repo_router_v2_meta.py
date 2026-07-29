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

    # 合法新配置：domain 0.15→0.20（网格内；text 保持 0.55 为最大项，
    # 非文本权重和 0.45 <= 0.5×1.00，MJ-03 后的 INV-R2 口径成立）
    await _write_setting(
        SettingKeys.REPO_ROUTER_WEIGHT_CONFIG,
        {
            "weights": {
                "text": 0.55,
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


async def test_last_commit_aggregation_cached_across_routes(monkeypatch) -> None:
    """MJ-05：同一批候选仓的 last_commit 聚合在 TTL 内只查一次 DB。

    该聚合要读候选仓的全部 FileIndex 行算 Max（数千文件 × 数十仓），落在正在压
    延迟的路由热路径上——短 TTL 缓存 + 覆盖索引（迁移 0040）两手都要。
    """
    big, small, bare = await _make_repos()
    _install_search_stack(
        monkeypatch,
        hybrid_hits=_hybrid_hits(big, small, bare),
        dense_hits=_dense_hits(big, small),
    )
    db_calls = {"n": 0}
    orig_filter = None

    from repositories.models import FileIndex

    orig_filter = FileIndex.objects.filter

    def counting_filter(*args, **kwargs):
        if "repository_id__in" in kwargs:
            db_calls["n"] += 1
        return orig_filter(*args, **kwargs)

    monkeypatch.setattr(FileIndex.objects, "filter", counting_filter)

    first = await RepoRouterV2.route(QUERY, use_llm=False)
    second = await RepoRouterV2.route(QUERY, use_llm=False)

    assert first.candidates and second.candidates
    assert db_calls["n"] == 1  # 第二次路由命中缓存，零额外聚合查询
    # 活跃度信号未因缓存而丢失（两次路由 breakdown 一致）
    assert _by_repo(first)[big].breakdown["activity"] == pytest.approx(
        _by_repo(second)[big].breakdown["activity"]
    )


async def test_dirty_repository_id_only_degrades_itself(monkeypatch) -> None:
    """MN-01：payload 混入非 UUID 的 repository_id 只影响自身活跃度来源。

    修复前实现是 ``except ValidationError: return {}``——一条脏 payload 让全部
    候选的 last_commit_at 变成 None，全体退化为枚举回退。
    """
    big, small, bare = await _make_repos()
    hits = _hybrid_hits(big, small, bare)
    hits.append(_hit("dirty0", "not-a-uuid", 0.01, facets=_FACETS_SMALL))
    _install_search_stack(
        monkeypatch, hybrid_hits=hits, dense_hits=_dense_hits(big, small)
    )

    result = await RepoRouterV2.route(QUERY, use_llm=False, top_k=5)

    repo_meta = result.snapshot["repo_meta"]
    # 干净仓的 last_commit_at 仍来自 DB 聚合（未被脏值牵连）
    assert repo_meta[big]["last_commit_at"] is not None
    assert repo_meta[small]["last_commit_at"] is not None
    # 脏仓自身查不到聚合行 → 该信号不可用（活跃度走枚举回退）
    assert repo_meta["not-a-uuid"]["last_commit_at"] is None


async def test_t2_cold_start_uses_batch_warm_and_respects_budget(monkeypatch) -> None:
    """MJ-06：T2 冷启动走一次批量预热，逐值不再串行 embedding。"""
    from codegraph.services import repo_router_metadata

    repo_router_metadata._facet_vec_local_cache.clear()
    big, small, bare = await _make_repos()
    calls = _install_search_stack(
        monkeypatch,
        hybrid_hits=_hybrid_hits(big, small, bare),
        dense_hits=_dense_hits(big, small),
        emb_configured=True,
    )
    batch_calls: list[list[str]] = []

    async def fake_batch(texts):
        batch_calls.append(list(texts))
        return [[0.1] * 8 for _ in texts]

    monkeypatch.setattr(EmbeddingService, "generate_embeddings_batch", fake_batch)

    result = await RepoRouterV2.route(QUERY, use_llm=False)

    assert result.candidates
    # 恰一次批量预热覆盖全部候选仓的 domain/stack 值（技术栈已按 "/" 拆分）
    assert len(batch_calls) == 1
    assert "学习工具" in batch_calls[0]
    assert "Vue" in batch_calls[0]
    # query embedding 1 次（Stage 0 检索用），facet 值不再逐个单条 embedding
    assert calls["embed"] == 1


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


# ---------------------------------------------------------------------------
# 6. 呈现字段契约（107-03 Task 1）：additive-safe 默认值 + to_dict 键集合
# ---------------------------------------------------------------------------


_LEGACY_CANDIDATE_KEYS = {
    "repo_id",
    "repo_name",
    "score",
    "confidence",
    "reasoning",
    "sub_project",
    "sub_project_paths",
    "matched_node_paths",
    "breakdown",
    "criticality",
}
_PRESENTATION_CANDIDATE_KEYS = {"group", "trust", "cross_group_note", "score_ranked"}


def test_candidate_positional_construction_keeps_new_fields_default() -> None:
    """5 个位置参数构造仍成立（既有测试替身不炸）→ 四个呈现字段取默认值。"""
    from codegraph.services.repo_router_v2 import RepoRouteCandidateV2

    c = RepoRouteCandidateV2("r1", "n1", 0.5, "high", "why")

    assert c.group == ""
    assert c.trust == ""
    assert c.cross_group_note == ""
    assert c.score_ranked is None


def test_candidate_to_dict_key_set_includes_presentation_fields() -> None:
    """``to_dict()`` 键集合 == 既有键 ∪ 四个呈现键（机制断言，非人工核对）。"""
    from codegraph.services.repo_router_v2 import RepoRouteCandidateV2

    c = RepoRouteCandidateV2("r1", "n1", 0.5, "high", "why")

    assert set(c.to_dict()) == _LEGACY_CANDIDATE_KEYS | _PRESENTATION_CANDIDATE_KEYS


def test_candidate_to_dict_score_ranked_none_stays_none() -> None:
    """``score_ranked`` 为 None 时原样输出 None（「未重排」与「重排分为 0」语义不同）。"""
    from codegraph.services.repo_router_v2 import RepoRouteCandidateV2

    unranked = RepoRouteCandidateV2("r1", "n1", 0.5, "high", "why")
    ranked_zero = RepoRouteCandidateV2("r2", "n2", 0.5, "high", "why", score_ranked=0.0)

    assert unranked.to_dict()["score_ranked"] is None
    assert ranked_zero.to_dict()["score_ranked"] == 0.0


def test_result_construction_defaults_block_order_and_degrade_reason() -> None:
    """结果新字段 additive-safe：三个必填参数构造 → block_order/degrade_reason 取默认。"""
    from codegraph.services.repo_router_v2 import RepoRouteResultV2

    r = RepoRouteResultV2(candidates=[], router_version="v2", auto_selected=False)

    assert r.block_order == []
    assert r.degrade_reason == ""


def test_ranking_conf_clamps_illegal_settings(settings) -> None:
    """settings 给出非法值时 ``_ranking_conf()`` 返回 clamp 后合法三元组且不抛（T-107-05）。"""
    from codegraph.services.repo_router_v2 import _ranking_conf

    settings.REPO_ROUTER_GROUP_DELTA = -1.0
    settings.REPO_ROUTER_STAGE1_ALPHA = 2.0
    settings.REPO_ROUTER_STAGE1_RANK_BUDGET_K = -3

    delta, alpha, k = _ranking_conf()

    assert delta == 0.0
    assert alpha == 1.0
    assert k == 0


def test_ranking_conf_reads_settings_at_call_time(settings) -> None:
    """调用时读取（改配置即生效）：合法值原样透出，不被导入时快照钉住。"""
    from codegraph.services.repo_router_v2 import _ranking_conf

    settings.REPO_ROUTER_GROUP_DELTA = 0.25
    settings.REPO_ROUTER_STAGE1_ALPHA = 0.5
    settings.REPO_ROUTER_STAGE1_RANK_BUDGET_K = 4

    assert _ranking_conf() == (0.25, 0.5, 4)


# ---------------------------------------------------------------------------
# 7. 分组标注 / block_order 接线（107-03 Task 2）
# ---------------------------------------------------------------------------


def _install_stage0(monkeypatch: pytest.MonkeyPatch, hits: list[dict[str, Any]]) -> None:
    """轻量 Stage 0 seam（与 test_repo_router_v2_degraded 同款）：分数可精确构造，
    且候选仓 id 非 UUID → last_commit 聚合查不到行 → 活跃度走枚举、无时间依赖，
    两次调用分数逐位相同（SC-2 机制断言的前提）。"""

    async def _fake_search(query: str, repository_ids: list[str] | None) -> list[dict[str, Any]]:
        return hits

    monkeypatch.setattr(RepoRouterV2, "_stage0_node_search", _fake_search)


def _two_repo_hits() -> list[dict[str, Any]]:
    """repo-a 碾压 repo-b（首位确定性 high，margin 远超 θ_margin）。"""
    hits = [
        _hit(f"a{i}", "repo-a", 0.032 - i * 0.002, facets={"活跃度": "活跃开发"}) for i in range(6)
    ]
    hits.append(_hit("b0", "repo-b", 0.010))
    return hits


def _cand(
    rid: str,
    score: float,
    *,
    confidence: str = "medium",
    score_ranked: float | None = None,
) -> Any:
    from codegraph.services.repo_router_v2 import RepoRouteCandidateV2

    return RepoRouteCandidateV2(rid, rid, score, confidence, "why", score_ranked=score_ranked)


def test_rank_value_prefers_score_ranked_including_zero() -> None:
    """`_rank_value` 是排序比较值的唯一所有者：缺旁路分回退 `score`，
    旁路分为 0.0 时返回 0.0（None 与 0.0 语义不同，绝不能被 falsy 判断吞掉）。"""
    from codegraph.services.repo_router_v2 import _rank_value

    assert _rank_value(_cand("a", 0.5)) == 0.5
    assert _rank_value(_cand("a", 0.5, score_ranked=0.0)) == 0.0
    assert _rank_value(_cand("a", 0.5, score_ranked=0.9)) == 0.9


async def test_route_no_project_context_all_global_block_order(monkeypatch) -> None:
    """无项目上下文（MCP / REST / skill_steps 入口）→ 全部 global 且不报错。"""
    _install_stage0(monkeypatch, _two_repo_hits())

    result = await RepoRouterV2.route("高三提分专项需求", use_llm=False, top_k=3)

    assert result.candidates
    assert {c.group for c in result.candidates} == {"global"}
    assert {c.trust for c in result.candidates} == {"needs_confirmation"}
    # 无上下文时不写跨组说明——此时「跨组」无意义，标了反而误导
    assert {c.cross_group_note for c in result.candidates} == {""}
    assert result.block_order == ["global"]


async def test_route_grouping_annotates_two_groups(monkeypatch) -> None:
    """传分组依据 → 命中仓 in_project/trusted，其余 global/needs_confirmation。"""
    from codegraph.services.repo_router_ranking import CROSS_GROUP_NOTE

    _install_stage0(monkeypatch, _two_repo_hits())

    result = await RepoRouterV2.route(
        "高三提分专项需求", use_llm=False, top_k=3, grouping_repository_ids=["repo-a"]
    )

    by_repo = _by_repo(result)
    assert (by_repo["repo-a"].group, by_repo["repo-a"].trust) == ("in_project", "trusted")
    assert by_repo["repo-a"].cross_group_note == ""
    assert (by_repo["repo-b"].group, by_repo["repo-b"].trust) == (
        "global",
        "needs_confirmation",
    )
    assert by_repo["repo-b"].cross_group_note == CROSS_GROUP_NOTE
    assert len(result.block_order) == 2
    # 快照携带呈现字段与分区顺序（回放比对用）
    snap_cand = {c["repo_id"]: c for c in result.snapshot["candidates"]}
    assert snap_cand["repo-a"]["group"] == "in_project"
    assert result.snapshot["block_order"] == result.block_order


async def test_route_grouping_with_empty_in_project_group(monkeypatch) -> None:
    """某组为空（分组依据全不命中）→ block_order 仍长度 2 且首元素 global。"""
    _install_stage0(monkeypatch, _two_repo_hits())

    result = await RepoRouterV2.route(
        "高三提分专项需求", use_llm=False, top_k=3, grouping_repository_ids=["zzz"]
    )

    assert {c.group for c in result.candidates} == {"global"}
    assert len(result.block_order) == 2
    assert result.block_order[0] == "global"


def test_presentation_hysteresis_at_delta_threshold() -> None:
    """迟滞：跨组分差达 delta 才置顶全局组，差一点点不翻转（幂等与体验前提）。"""
    from codegraph.services.repo_router_v2 import _apply_presentation

    def block_order_for(global_top: float) -> list[str]:
        _, order = _apply_presentation(
            [_cand("p0", 0.50), _cand("g0", global_top)],
            grouping_repository_ids=["p0"],
            delta=0.15,
            top_k=3,
        )
        return order

    assert block_order_for(0.50 + 0.16)[0] == "global"
    assert block_order_for(0.50 + 0.14)[0] == "in_project"


def test_presentation_per_group_top_k_and_global_descending() -> None:
    """分组启用时按组各取 top_k 后并集，扁平列表按比较值全局降序。"""
    from codegraph.services.repo_router_v2 import _apply_presentation

    in_project = [_cand(f"p{i}", 0.90 - i * 0.10) for i in range(5)]
    global_group = [_cand(f"g{i}", 0.85 - i * 0.10) for i in range(5)]

    merged, order = _apply_presentation(
        in_project + global_group,
        grouping_repository_ids=[c.repo_id for c in in_project],
        delta=0.15,
        top_k=3,
    )

    assert len(merged) == 6
    assert [c.repo_id for c in merged] == ["p0", "g0", "p1", "g1", "p2", "g2"]
    assert len(order) == 2


def test_presentation_flat_top_is_global_max_regardless_of_block_order() -> None:
    """置顶是呈现层的事：block_order 首位与扁平列表首位所属组可以不同。"""
    from codegraph.services.repo_router_v2 import _apply_presentation

    merged, order = _apply_presentation(
        [_cand("p0", 0.50), _cand("g0", 0.60, confidence="high"), _cand("g1", 0.10)],
        grouping_repository_ids=["p0"],
        delta=0.15,
        top_k=3,
    )

    # 分差 0.10 < delta → 本项目组仍置顶；但扁平首位是全局最高分的跨组候选
    assert order[0] == "in_project"
    assert merged[0].repo_id == "g0"
    assert merged[0].group == "global"


async def test_score_and_breakdown_identical_with_and_without_grouping(monkeypatch) -> None:
    """SC-2 机制断言：组别绝不进分数——同一候选在传/不传分组依据两次调用下
    `score` 与 `breakdown` 逐键相等。"""
    _install_stage0(monkeypatch, _two_repo_hits())

    without = await RepoRouterV2.route("高三提分专项需求", use_llm=False, top_k=3)
    with_grouping = await RepoRouterV2.route(
        "高三提分专项需求", use_llm=False, top_k=3, grouping_repository_ids=["repo-a"]
    )

    left = _by_repo(without)
    right = _by_repo(with_grouping)
    assert set(left) == set(right)
    for rid, cand in left.items():
        assert cand.score == right[rid].score
        assert cand.breakdown == right[rid].breakdown
        # 旁路排序分本 plan 不写（107-05 才写）→ 两侧同为未重排
        assert cand.score_ranked is None and right[rid].score_ranked is None


async def test_auto_selected_is_independent_of_block_order(monkeypatch) -> None:
    """`auto_selected` 只由扁平首位（全局最高分候选）驱动，与 block_order 无关
    ——否则组别就间接进了编排决策路径。"""
    _install_stage0(monkeypatch, _two_repo_hits())

    orders: list[list[str]] = []
    for grouping in (None, ["repo-a"], ["repo-b"]):
        result = await RepoRouterV2.route(
            "高三提分专项需求", use_llm=False, top_k=3, grouping_repository_ids=grouping
        )
        orders.append(result.block_order)
        assert result.candidates[0].repo_id == "repo-a"  # 扁平首位恒为全局最高分
        assert result.candidates[0].confidence == "high"
        assert result.auto_selected is True

    # 三种分组上下文给出三种分区顺序，auto_selected 却恒为 True
    assert orders == [["global"], ["in_project", "global"], ["global", "in_project"]]
