"""Galaxy API 端到端测试 —— implementation 全覆盖。

E1  galaxy 模块可正常 import
E2  aggregate() 返回 5 类节点统一格式
E3  GET /api/codegraph/galaxy/ → 200 nodes+edges+meta
E4  GET /api/codegraph/galaxy/search/?q=xxx → top-20 按 degree 排序
E5  GET /api/codegraph/galaxy/nodes/{id}/ → node + neighbors + references + called_by
E6  max_nodes=1, 3 节点 → sampled=True + per_repo_hint
"""

from __future__ import annotations

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from code_relations.models import ChunkEdge, ChunkRegistry, EdgeType
from codegraph.galaxy import GalaxyAggregator
from codegraph.models import (
    ApiCallSite,
    ApiWrapper,
    CrossRepoApiCall,
    Endpoint,
    Symbol,
)
from repositories.models import Repository

User = get_user_model()

GALAXY_URL = "/api/codegraph/galaxy/"
SEARCH_URL = "/api/codegraph/galaxy/search/"


def make_user(username: str = "e2e-user") -> User:
    return User.objects.create_user(username=username, password="pass")  # type: ignore[return-value]


def make_repo(name: str = "e2e-repo") -> Repository:
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


@pytest.mark.django_db
class TestE1GalaxyImport(TestCase):
    """E1: work item — galaxy 子模块可正常 import。"""

    def test_module_importable(self) -> None:
        from codegraph.galaxy import GalaxyAggregator, GalaxyEdge, GalaxyMeta, GalaxyNode

        assert GalaxyAggregator is not None
        assert GalaxyNode is not None
        assert GalaxyEdge is not None
        assert GalaxyMeta is not None


@pytest.mark.django_db
class TestE2GalaxyAggregate5NodeTypes(TestCase):
    """E2: work item — aggregate() 包含 5 类节点统一格式。"""

    def test_aggregate_all_node_types(self) -> None:
        repo = make_repo()

        # chunk_registry
        make_chunk(repo, "a.py", 0)

        # symbol
        Symbol.objects.create(
            repository=repo,
            name="my_func",
            symbol_type="FUNCTION",
            file_path="mod.py",
            start_line=1,
            end_line=10,
            signature="def my_func()",
        )

        # endpoint
        Endpoint.objects.create(
            repository=repo,
            http_method="GET",
            url_path="/api/test",
            handler_name="handle_test",
            view_type="FUNCTION_VIEW",
            file_path="handler.go",
            line_number=5,
        )

        # api_wrapper
        wrapper = ApiWrapper.objects.create(
            repository=repo,
            file_path="api.ts",
            function_symbol="fetchTest",
            http_method="GET",
            url_path_raw="/api/test",
            url_path_pattern="/api/test",
            line_number=10,
        )

        # api_call_site
        ApiCallSite.objects.create(
            repository=repo,
            api_wrapper=wrapper,
            caller_file="page.vue",
            caller_function="setup",
            line_number=20,
        )

        result = GalaxyAggregator.aggregate(repo_ids=[repo.id])

        node_types_present = {n["type"] for n in result["nodes"]}
        assert "chunk_registry" in node_types_present
        assert "symbol" in node_types_present
        assert "endpoint" in node_types_present
        assert "api_wrapper" in node_types_present
        assert "api_call_site" in node_types_present

        # 验证 node schema 字段完整
        for node in result["nodes"]:
            assert "id" in node
            assert "type" in node
            assert "label" in node
            assert "repository_id" in node
            assert "file_path" in node
            assert "degree" in node


@pytest.mark.django_db
class TestE3GalaxyListEndpoint(TestCase):
    """E3: work item — GET /api/codegraph/galaxy/ 返回 nodes+edges+meta。"""

    def test_galaxy_list_response_structure(self) -> None:
        user = make_user()
        repo = make_repo()
        c1 = make_chunk(repo, "a.py", 0)
        c2 = make_chunk(repo, "b.py", 1)
        ChunkEdge.objects.create(
            source_chunk_id=c1.chunk_id,
            target_chunk_id=c2.chunk_id,
            edge_type=EdgeType.CALL,
            weight=0.7,
            repository=repo,
        )

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(GALAXY_URL, {"repo_ids": str(repo.id)})

        assert response.status_code == 200
        data = response.json()
        assert "nodes" in data
        assert "edges" in data
        assert "meta" in data
        assert len(data["nodes"]) >= 2
        assert len(data["edges"]) >= 1

        # 验证 edge schema
        edge = data["edges"][0]
        assert "id" in edge
        assert "source" in edge
        assert "target" in edge
        assert "edge_type" in edge
        assert "weight" in edge


@pytest.mark.django_db
class TestE4GalaxySearch(TestCase):
    """E4: work item — search 返回按 degree 排序结果。"""

    def test_search_top20_degree_sorted(self) -> None:
        user = make_user()
        repo = make_repo()

        # 创建多个 symbol，给一个更高的 degree
        high_degree_sym = Symbol.objects.create(
            repository=repo,
            name="search_target_high",
            symbol_type="FUNCTION",
            file_path="core.py",
            start_line=1,
            end_line=10,
            signature="def search_target_high()",
        )
        low_degree_sym = Symbol.objects.create(
            repository=repo,
            name="search_target_low",
            symbol_type="FUNCTION",
            file_path="helper.py",
            start_line=1,
            end_line=5,
            signature="def search_target_low()",
        )

        # 为 high_degree_sym 添加调用边（提高 degree）
        from codegraph.models import CallEdge

        CallEdge.objects.create(
            repository=repo,
            caller_symbol=high_degree_sym,
            callee_name="some_func",
            call_type="DIRECT",
            line_number=3,
        )

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(SEARCH_URL, {"q": "search_target", "node_types": "symbol"})

        assert response.status_code == 200
        data = response.json()
        assert data["count"] >= 2

        # 检查 degree 排序
        degrees = [r["degree"] for r in data["results"]]
        assert degrees == sorted(degrees, reverse=True)


@pytest.mark.django_db
class TestE5GalaxyNodeDetail(TestCase):
    """E5: work item — node detail + neighbors + references + called_by。"""

    def test_chunk_node_with_neighbors(self) -> None:
        user = make_user()
        repo = make_repo()
        c1 = make_chunk(repo, "a.py", 0)
        c2 = make_chunk(repo, "b.py", 1)
        ChunkEdge.objects.create(
            source_chunk_id=c1.chunk_id,
            target_chunk_id=c2.chunk_id,
            edge_type=EdgeType.IMPORT,
            weight=0.6,
            repository=repo,
        )

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(f"{GALAXY_URL}nodes/chunk:{c1.chunk_id}/")

        assert response.status_code == 200
        data = response.json()
        assert data["node"]["id"] == f"chunk:{c1.chunk_id}"
        assert len(data["neighbors"]) == 1
        neighbor = data["neighbors"][0]
        assert neighbor["direction"] == "outgoing"
        assert neighbor["node"]["id"] == f"chunk:{c2.chunk_id}"

    def test_endpoint_node_with_references(self) -> None:
        user = make_user()
        repo_fe = make_repo("fe")
        repo_be = make_repo("be")

        wrapper = ApiWrapper.objects.create(
            repository=repo_fe,
            file_path="api.ts",
            function_symbol="fetchUsers",
            http_method="GET",
            url_path_raw="/api/users",
            url_path_pattern="/api/users",
            line_number=10,
        )
        cs = ApiCallSite.objects.create(
            repository=repo_fe,
            api_wrapper=wrapper,
            caller_file="page.vue",
            caller_function="setup",
            line_number=20,
        )
        ep = Endpoint.objects.create(
            repository=repo_be,
            http_method="GET",
            url_path="/api/users",
            handler_name="GetUsers",
            view_type="FUNCTION_VIEW",
            file_path="handler.go",
            line_number=5,
        )
        CrossRepoApiCall.objects.create(
            call_site=cs,
            endpoint=ep,
            match_confidence=1.0,
        )

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(f"{GALAXY_URL}nodes/endpoint:{ep.id}/")

        assert response.status_code == 200
        data = response.json()
        assert len(data["references"]) == 1
        ref = data["references"][0]
        assert ref["type"] == "api_call_site"
        assert ref["match_confidence"] == 1.0


@pytest.mark.django_db
class TestE6GalaxyDegreeBasedSampling(TestCase):
    """E6: work item — max_nodes=1, 3 节点 → sampled=True + per_repo_hint=True。"""

    def test_sampling_triggered_with_3_nodes(self) -> None:
        user = make_user()
        repo = make_repo()
        c1 = make_chunk(repo, "a.py", 0)
        c2 = make_chunk(repo, "b.py", 1)
        c3 = make_chunk(repo, "c.py", 2)

        # c1 → c2 边（c1 有最高 degree）
        ChunkEdge.objects.create(
            source_chunk_id=c1.chunk_id,
            target_chunk_id=c2.chunk_id,
            edge_type=EdgeType.CALL,
            weight=0.9,
            repository=repo,
        )

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(
            GALAXY_URL,
            {"repo_ids": str(repo.id), "node_types": "chunk_registry", "max_nodes": "1"},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["nodes"]) == 1
        assert data["meta"]["sampled"] is True
        assert data["meta"]["per_repo_hint"] is True
        assert data["meta"]["total_nodes"] == 3
