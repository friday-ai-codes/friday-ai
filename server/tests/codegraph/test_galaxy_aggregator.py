"""GalaxyAggregator 单元测试 —— initial implementation/02/06。

覆盖：
T1  空库 aggregate() → nodes=[], edges=[], sampled=False
T2  单个 ChunkRegistry 节点聚合
T3  ChunkEdge CALL 边聚合
T4  ChunkEdge API_CALLS 边（target_repository_id 非空）
T5  max_nodes=1, 2 节点 → sampled=True
T6  node_types=["symbol"] 过滤
T7  edge_types=["CALL"] 过滤
T8  Symbol degree 来自 outgoing_calls
T9  CrossRepoApiCall → API_CALLS 边
T10 采样后边过滤（两端不在保留集的边被移除）
"""

from __future__ import annotations

import uuid

import pytest
from django.test import TestCase

from code_relations.models import ChunkEdge, ChunkRegistry, EdgeType
from codegraph.galaxy.aggregator import GalaxyAggregator, _apply_sampling, _parse_node_id
from codegraph.galaxy.serializers import GalaxyNode
from codegraph.models import (
    ApiCallSite,
    ApiWrapper,
    CrossRepoApiCall,
    Endpoint,
    Symbol,
)
from repositories.models import Repository


def make_repo(name: str = "test-repo") -> Repository:
    return Repository.objects.create(
        name=name,
        git_url=f"https://example.com/{name}.git",
        default_branch="main",
    )


def make_chunk(repo: Repository, file_path: str = "a.py", chunk_index: int = 0) -> ChunkRegistry:
    return ChunkRegistry.objects.create(
        chunk_id=uuid.uuid4(),
        content_hash="abc123",
        repository=repo,
        file_path=file_path,
        chunk_index=chunk_index,
        line_start=1,
        line_end=50,
    )


@pytest.mark.django_db
class TestGalaxyAggregatorEmpty(TestCase):
    """T1: 空库 aggregate() 返回空结果。"""

    def test_empty_db_returns_empty_payload(self) -> None:
        result = GalaxyAggregator.aggregate()
        assert result["nodes"] == []
        assert result["edges"] == []
        meta = result["meta"]
        assert meta["total_nodes"] == 0
        assert meta["total_edges"] == 0
        assert meta["sampled"] is False
        assert meta["per_repo_hint"] is False


@pytest.mark.django_db
class TestGalaxyAggregatorChunkRegistry(TestCase):
    """T2: 单个 ChunkRegistry 节点聚合。"""

    def test_single_chunk_node(self) -> None:
        repo = make_repo()
        chunk = make_chunk(repo, "src/main.py", 0)

        result = GalaxyAggregator.aggregate(repo_ids=[repo.id])
        assert len(result["nodes"]) == 1
        node = result["nodes"][0]
        assert node["id"] == f"chunk:{chunk.chunk_id}"
        assert node["type"] == "chunk_registry"
        assert node["label"] == "src/main.py:0"
        assert node["repository_id"] == str(repo.id)
        assert node["file_path"] == "src/main.py"
        assert node["line_start"] == 1
        assert node["line_end"] == 50
        assert node["degree"] == 0


@pytest.mark.django_db
class TestGalaxyAggregatorChunkEdge(TestCase):
    """T3: ChunkEdge CALL 边聚合。"""

    def test_call_edge_aggregated(self) -> None:
        repo = make_repo()
        src = make_chunk(repo, "a.py", 0)
        tgt = make_chunk(repo, "b.py", 0)
        ChunkEdge.objects.create(
            source_chunk_id=src.chunk_id,
            target_chunk_id=tgt.chunk_id,
            edge_type=EdgeType.CALL,
            weight=0.8,
            repository=repo,
        )

        result = GalaxyAggregator.aggregate(repo_ids=[repo.id])
        chunk_edges = [e for e in result["edges"] if e["edge_type"] == "CALL"]
        assert len(chunk_edges) == 1
        edge = chunk_edges[0]
        assert edge["source"] == f"chunk:{src.chunk_id}"
        assert edge["target"] == f"chunk:{tgt.chunk_id}"
        assert edge["weight"] == 0.8


@pytest.mark.django_db
class TestGalaxyAggregatorApiCallsEdge(TestCase):
    """T4: ChunkEdge API_CALLS 边（target_repository_id 非空）。"""

    def test_api_calls_edge_target_repository_id(self) -> None:
        repo1 = make_repo("frontend")
        repo2 = make_repo("backend")
        src = make_chunk(repo1, "api.ts", 0)
        tgt = make_chunk(repo2, "handler.go", 0)
        ChunkEdge.objects.create(
            source_chunk_id=src.chunk_id,
            target_chunk_id=tgt.chunk_id,
            edge_type=EdgeType.API_CALLS,
            weight=1.0,
            repository=repo1,
            target_repository_id=repo2.id,
        )

        result = GalaxyAggregator.aggregate()
        api_edges = [e for e in result["edges"] if e["edge_type"] == "API_CALLS"]
        assert len(api_edges) == 1
        edge = api_edges[0]
        assert edge["target_repository_id"] == str(repo2.id)


@pytest.mark.django_db
class TestGalaxyAggregatorSampling(TestCase):
    """T5: max_nodes=1, 2 节点 → sampled=True。"""

    def test_sampling_reduces_nodes(self) -> None:
        repo = make_repo()
        src = make_chunk(repo, "a.py", 0)
        tgt = make_chunk(repo, "b.py", 1)
        # 给 src 加一条出边，让其 degree > tgt
        ChunkEdge.objects.create(
            source_chunk_id=src.chunk_id,
            target_chunk_id=tgt.chunk_id,
            edge_type=EdgeType.CALL,
            weight=0.5,
            repository=repo,
        )

        result = GalaxyAggregator.aggregate(
            repo_ids=[repo.id],
            node_types=["chunk_registry"],
            max_nodes=1,
        )
        assert len(result["nodes"]) == 1
        assert result["meta"]["sampled"] is True
        assert result["meta"]["total_nodes"] == 2


@pytest.mark.django_db
class TestGalaxyAggregatorNodeTypeFilter(TestCase):
    """T6: node_types=["symbol"] 过滤。"""

    def test_node_type_filter(self) -> None:
        repo = make_repo()
        make_chunk(repo)
        Symbol.objects.create(
            repository=repo,
            name="my_func",
            symbol_type="FUNCTION",
            file_path="mod.py",
            start_line=1,
            end_line=10,
            signature="def my_func()",
        )

        result = GalaxyAggregator.aggregate(
            repo_ids=[repo.id],
            node_types=["symbol"],
        )
        assert all(n["type"] == "symbol" for n in result["nodes"])
        assert len(result["nodes"]) == 1


@pytest.mark.django_db
class TestGalaxyAggregatorEdgeTypeFilter(TestCase):
    """T7: edge_types=["CALL"] 过滤。"""

    def test_edge_type_filter(self) -> None:
        repo = make_repo()
        src = make_chunk(repo, "a.py", 0)
        tgt = make_chunk(repo, "b.py", 0)
        ChunkEdge.objects.create(
            source_chunk_id=src.chunk_id,
            target_chunk_id=tgt.chunk_id,
            edge_type=EdgeType.CALL,
            weight=0.8,
            repository=repo,
        )
        ChunkEdge.objects.create(
            source_chunk_id=src.chunk_id,
            target_chunk_id=tgt.chunk_id,
            edge_type=EdgeType.IMPORT,
            weight=0.5,
            repository=repo,
        )

        result = GalaxyAggregator.aggregate(
            repo_ids=[repo.id],
            edge_types=["CALL"],
        )
        assert all(e["edge_type"] == "CALL" for e in result["edges"])


@pytest.mark.django_db
class TestGalaxyAggregatorSymbolDegree(TestCase):
    """T8: Symbol degree = outgoing_calls 数。"""

    def test_symbol_degree_from_outgoing_calls(self) -> None:
        repo = make_repo()
        sym = Symbol.objects.create(
            repository=repo,
            name="caller",
            symbol_type="FUNCTION",
            file_path="mod.py",
            start_line=1,
            end_line=10,
            signature="def caller()",
        )
        # 添加 2 个 outgoing calls
        from codegraph.models import CallEdge
        CallEdge.objects.create(
            repository=repo,
            caller_symbol=sym,
            callee_name="func_a",
            call_type="DIRECT",
            line_number=5,
        )
        CallEdge.objects.create(
            repository=repo,
            caller_symbol=sym,
            callee_name="func_b",
            call_type="METHOD",
            line_number=7,
        )

        result = GalaxyAggregator.aggregate(
            repo_ids=[repo.id],
            node_types=["symbol"],
        )
        assert len(result["nodes"]) == 1
        assert result["nodes"][0]["degree"] == 2


@pytest.mark.django_db
class TestGalaxyAggregatorCrossRepoEdge(TestCase):
    """T9: CrossRepoApiCall → API_CALLS 边（source=callsite:..., target=endpoint:...）。"""

    def test_cross_repo_api_calls_edge(self) -> None:
        repo_fe = make_repo("fe")
        repo_be = make_repo("be")

        wrapper = ApiWrapper.objects.create(
            repository=repo_fe,
            file_path="api.ts",
            function_symbol="fetchUser",
            http_method="GET",
            url_path_raw="/api/users",
            url_path_pattern="/api/users",
            line_number=10,
        )
        call_site = ApiCallSite.objects.create(
            repository=repo_fe,
            api_wrapper=wrapper,
            caller_file="page.vue",
            caller_function="setup",
            line_number=20,
        )
        endpoint = Endpoint.objects.create(
            repository=repo_be,
            http_method="GET",
            url_path="/api/users",
            handler_name="GetUsers",
            view_type="FUNCTION_VIEW",
            file_path="handler.go",
            line_number=5,
        )
        cross_call = CrossRepoApiCall.objects.create(
            call_site=call_site,
            endpoint=endpoint,
            match_confidence=1.0,
        )

        result = GalaxyAggregator.aggregate(
            node_types=["api_call_site", "endpoint"],
        )
        api_edges = [e for e in result["edges"] if e["edge_type"] == "API_CALLS"]
        assert len(api_edges) == 1
        edge = api_edges[0]
        assert edge["source"] == f"callsite:{call_site.id}"
        assert edge["target"] == f"endpoint:{endpoint.id}"
        assert edge["target_repository_id"] == str(repo_be.id)


@pytest.mark.django_db
class TestGalaxyAggregatorSamplingEdgeFilter(TestCase):
    """T10: 采样后边过滤——不在保留集的边被移除。"""

    def test_edges_filtered_after_sampling(self) -> None:
        repo = make_repo()
        c1 = make_chunk(repo, "a.py", 0)
        c2 = make_chunk(repo, "b.py", 1)
        c3 = make_chunk(repo, "c.py", 2)

        # c1 → c2 边（c1 degree 更高，应被保留）
        ChunkEdge.objects.create(
            source_chunk_id=c1.chunk_id,
            target_chunk_id=c2.chunk_id,
            edge_type=EdgeType.CALL,
            weight=0.8,
            repository=repo,
        )
        # c2 → c3 边（c3 应被丢弃，因为 c3 degree 最低）
        ChunkEdge.objects.create(
            source_chunk_id=c2.chunk_id,
            target_chunk_id=c3.chunk_id,
            edge_type=EdgeType.IMPORT,
            weight=0.5,
            repository=repo,
        )

        result = GalaxyAggregator.aggregate(
            repo_ids=[repo.id],
            node_types=["chunk_registry"],
            max_nodes=2,
        )
        assert len(result["nodes"]) == 2
        assert result["meta"]["sampled"] is True
        # c3 degree=0（最低）应被丢弃，c2→c3 边应被过滤
        kept_ids = {n["id"] for n in result["nodes"]}
        for edge in result["edges"]:
            assert edge["source"] in kept_ids
            assert edge["target"] in kept_ids


class TestParseNodeId(TestCase):
    """_parse_node_id 单元测试。"""

    def test_valid_format(self) -> None:
        prefix, uid = _parse_node_id("chunk:550e8400-e29b-41d4-a716-446655440000")
        assert prefix == "chunk"
        assert uid == "550e8400-e29b-41d4-a716-446655440000"

    def test_invalid_format_no_colon(self) -> None:
        with pytest.raises(ValueError):
            _parse_node_id("invalid-format")

    def test_colon_in_uuid_part(self) -> None:
        prefix, uid = _parse_node_id("symbol:a:b")
        assert prefix == "symbol"
        assert uid == "a:b"  # split(1) 保留后面的冒号


class TestApplySampling(TestCase):
    """_apply_sampling 单元测试。"""

    def _make_node(self, nid: str, degree: int) -> GalaxyNode:
        return GalaxyNode(
            id=nid,
            type="chunk_registry",
            label=nid,
            repository_id="repo-1",
            file_path="f.py",
            line_start=None,
            line_end=None,
            metadata=None,
            degree=degree,
        )

    def test_no_sampling_needed(self) -> None:
        nodes = [self._make_node("n1", 10), self._make_node("n2", 5)]
        kept, edges, sampled = _apply_sampling(nodes, [], max_nodes=5)
        assert len(kept) == 2
        assert sampled is False

    def test_sampling_keeps_top_n_by_degree(self) -> None:
        nodes = [
            self._make_node("n1", 1),
            self._make_node("n2", 3),
            self._make_node("n3", 2),
        ]
        kept, edges, sampled = _apply_sampling(nodes, [], max_nodes=2)
        assert sampled is True
        kept_ids = {n["id"] for n in kept}
        assert "n2" in kept_ids  # degree 3
        assert "n3" in kept_ids  # degree 2
        assert "n1" not in kept_ids  # degree 1
