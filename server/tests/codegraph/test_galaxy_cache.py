"""GalaxyGraphCache 文件缓存测试。

覆盖：
- 签名：数据写入后变化、稳定性
- aggregate_cached：miss → 落盘；hit → 不再走全量聚合；数据变化 → 自动重建
- 内存过滤/采样与 meta 口径
- refresh_repo：清理含该仓库的过期缓存并重建
- GALAXY_CACHE_ENABLED=False 逃生舱
"""

from __future__ import annotations

import uuid
from unittest import mock

import pytest
from django.test import TestCase, override_settings

from code_relations.models import ChunkEdge, ChunkRegistry, EdgeType
from codegraph.galaxy.aggregator import GalaxyAggregator
from codegraph.galaxy.cache import GalaxyGraphCache, _cache_dir
from repositories.models import Repository


def make_repo(name: str = "cache-repo") -> Repository:
    return Repository.objects.create(
        name=name,
        git_url=f"https://example.com/{name}.git",
        default_branch="main",
    )


def make_chunk(repo: Repository, file_path: str = "main.py", idx: int = 0) -> ChunkRegistry:
    return ChunkRegistry.objects.create(
        chunk_id=uuid.uuid4(),
        content_hash="xyz",
        repository=repo,
        file_path=file_path,
        chunk_index=idx,
        line_start=1,
        line_end=50,
    )


def make_edge(repo: Repository, source: ChunkRegistry, target: ChunkRegistry) -> ChunkEdge:
    return ChunkEdge.objects.create(
        repository=repo,
        source_chunk_id=source.chunk_id,
        target_chunk_id=target.chunk_id,
        edge_type=EdgeType.CALL,
        weight=0.5,
    )


@pytest.mark.django_db
class TestSignature(TestCase):
    """签名计算：稳定且对写入敏感。"""

    def test_signature_stable_without_changes(self) -> None:
        repo = make_repo()
        make_chunk(repo)
        sig_a = GalaxyGraphCache.compute_signature([repo.id])
        sig_b = GalaxyGraphCache.compute_signature([repo.id])
        assert sig_a == sig_b

    def test_signature_changes_on_insert(self) -> None:
        repo = make_repo()
        make_chunk(repo)
        sig_before = GalaxyGraphCache.compute_signature([repo.id])
        make_chunk(repo, idx=1)
        sig_after = GalaxyGraphCache.compute_signature([repo.id])
        assert sig_before != sig_after

    def test_signature_changes_on_delete(self) -> None:
        repo = make_repo()
        chunk = make_chunk(repo)
        make_chunk(repo, idx=1)
        sig_before = GalaxyGraphCache.compute_signature([repo.id])
        chunk.delete()
        sig_after = GalaxyGraphCache.compute_signature([repo.id])
        assert sig_before != sig_after

    def test_signature_scoped_to_repo(self) -> None:
        repo_a = make_repo("repo-a")
        repo_b = make_repo("repo-b")
        make_chunk(repo_a)
        sig_before = GalaxyGraphCache.compute_signature([repo_a.id])
        # 写入另一个仓库不影响 repo_a 的签名
        make_chunk(repo_b)
        sig_after = GalaxyGraphCache.compute_signature([repo_a.id])
        assert sig_before == sig_after


@pytest.mark.django_db
class TestAggregateCached(TestCase):
    """aggregate_cached：miss/hit/失效语义。"""

    def test_miss_writes_file_then_hit(self) -> None:
        repo = make_repo()
        c1 = make_chunk(repo)
        c2 = make_chunk(repo, idx=1)
        make_edge(repo, c1, c2)

        result_miss = GalaxyGraphCache.aggregate_cached(repo_ids=[repo.id])
        assert result_miss["meta"]["cache_hit"] is False
        assert len(result_miss["nodes"]) == 2
        assert len(result_miss["edges"]) == 1
        assert len(list(_cache_dir().glob("*.json"))) == 1

        # 第二次：签名一致 → 命中，且不再调用全量聚合
        with mock.patch.object(
            GalaxyAggregator, "aggregate", wraps=GalaxyAggregator.aggregate
        ) as spy:
            result_hit = GalaxyGraphCache.aggregate_cached(repo_ids=[repo.id])
            assert spy.call_count == 0
        assert result_hit["meta"]["cache_hit"] is True
        assert {n["id"] for n in result_hit["nodes"]} == {n["id"] for n in result_miss["nodes"]}

    def test_data_change_invalidates_cache(self) -> None:
        repo = make_repo()
        make_chunk(repo)
        GalaxyGraphCache.aggregate_cached(repo_ids=[repo.id])

        make_chunk(repo, idx=1)
        result = GalaxyGraphCache.aggregate_cached(repo_ids=[repo.id])
        assert result["meta"]["cache_hit"] is False
        assert len(result["nodes"]) == 2

    def test_hit_applies_type_filter_and_sampling(self) -> None:
        repo = make_repo()
        c1 = make_chunk(repo)
        c2 = make_chunk(repo, idx=1)
        c3 = make_chunk(repo, idx=2)
        make_edge(repo, c1, c2)
        make_edge(repo, c1, c3)

        GalaxyGraphCache.aggregate_cached(repo_ids=[repo.id])  # 预热

        # 命中路径上做采样
        sampled = GalaxyGraphCache.aggregate_cached(repo_ids=[repo.id], max_nodes=1)
        assert sampled["meta"]["cache_hit"] is True
        assert sampled["meta"]["sampled"] is True
        assert len(sampled["nodes"]) == 1
        # degree 最高的 c1 被保留
        assert sampled["nodes"][0]["id"] == f"chunk:{c1.chunk_id}"
        # 边的另一端被采样掉 → 边也被过滤
        assert sampled["edges"] == []

        # 命中路径上做类型过滤
        filtered = GalaxyGraphCache.aggregate_cached(repo_ids=[repo.id], node_types=["symbol"])
        assert filtered["meta"]["cache_hit"] is True
        assert filtered["nodes"] == []
        assert filtered["edges"] == []

        # 边类型过滤
        no_call = GalaxyGraphCache.aggregate_cached(repo_ids=[repo.id], edge_types=["IMPORT"])
        assert no_call["edges"] == []
        assert len(no_call["nodes"]) == 3

    def test_cache_disabled_passthrough(self) -> None:
        repo = make_repo()
        make_chunk(repo)
        with override_settings(GALAXY_CACHE_ENABLED=False):
            result = GalaxyGraphCache.aggregate_cached(repo_ids=[repo.id])
            assert result["meta"]["cache_hit"] is False
            assert len(result["nodes"]) == 1
            # 不落盘
            assert list(_cache_dir().glob("*.json")) == []


@pytest.mark.django_db
class TestRefreshRepo(TestCase):
    """refresh_repo：主动刷新 + 多仓组合缓存清理。"""

    def test_refresh_rebuilds_single_repo_cache(self) -> None:
        repo = make_repo()
        make_chunk(repo)
        GalaxyGraphCache.aggregate_cached(repo_ids=[repo.id])

        # 数据更新后主动刷新
        make_chunk(repo, idx=1)
        GalaxyGraphCache.refresh_repo(repo.id)

        # 刷新后的缓存应直接命中且含新数据
        with mock.patch.object(
            GalaxyAggregator, "aggregate", wraps=GalaxyAggregator.aggregate
        ) as spy:
            result = GalaxyGraphCache.aggregate_cached(repo_ids=[repo.id])
            assert spy.call_count == 0
        assert result["meta"]["cache_hit"] is True
        assert len(result["nodes"]) == 2

    def test_refresh_evicts_combo_and_all_caches(self) -> None:
        repo_a = make_repo("repo-a")
        repo_b = make_repo("repo-b")
        make_chunk(repo_a)
        make_chunk(repo_b)

        GalaxyGraphCache.aggregate_cached(repo_ids=[repo_a.id, repo_b.id])  # 组合缓存
        GalaxyGraphCache.aggregate_cached(repo_ids=None)  # "all" 缓存
        GalaxyGraphCache.aggregate_cached(repo_ids=[repo_b.id])  # 不相关单仓缓存
        assert len(list(_cache_dir().glob("*.json"))) == 3

        GalaxyGraphCache.refresh_repo(repo_a.id)

        remaining = {p.stem for p in _cache_dir().glob("*.json")}
        # 组合缓存与 all 缓存被清理；repo_b 单仓缓存保留；repo_a 单仓缓存被重建
        from codegraph.galaxy.cache import _cache_key

        assert _cache_key([repo_a.id]) in remaining
        assert _cache_key([repo_b.id]) in remaining
        assert _cache_key([repo_a.id, repo_b.id]) not in remaining
        assert "all" not in remaining


@pytest.mark.django_db
class TestGalaxyViewCacheIntegration(TestCase):
    """GalaxyView 走缓存路径的端到端验证。"""

    def test_view_returns_cache_hit_meta(self) -> None:
        from django.contrib.auth import get_user_model
        from rest_framework.test import APIClient

        user = get_user_model().objects.create_user(username="cache-user", password="pass")
        client = APIClient()
        client.force_authenticate(user=user)

        repo = make_repo()
        make_chunk(repo)

        url = f"/api/codegraph/galaxy/?repo_ids={repo.id}"
        first = client.get(url)
        assert first.status_code == 200
        assert first.json()["meta"]["cache_hit"] is False

        second = client.get(url)
        assert second.status_code == 200
        assert second.json()["meta"]["cache_hit"] is True
        assert second.json()["nodes"] == first.json()["nodes"]
