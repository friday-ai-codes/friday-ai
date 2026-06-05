"""Galaxy API Views 集成测试 —— implementation/04/05。

覆盖：
V1  GET /galaxy/ 无认证 → 401
V2  GET /galaxy/ 空库 → 200 nodes=[], edges=[]
V3  GET /galaxy/ repo_ids 过滤
V4  GET /galaxy/ max_nodes=1, 2 节点 → sampled=True
V5  GET /galaxy/search/ q 缺失 → 400
V6  GET /galaxy/search/?q=foo 空库 → 200 results=[]
V7  GET /galaxy/search/?q=foo 有匹配 → 200 非空
V8  GET /galaxy/nodes/bad_id/ 格式非法 → 400
V9  GET /galaxy/nodes/chunk:not-uuid/ UUID 非法 → 400
V10 GET /galaxy/nodes/chunk:<valid_uuid>/ 不存在 → 404
V11 GET /galaxy/nodes/chunk:<valid_uuid>/ 存在 → 200 node+neighbors
"""

from __future__ import annotations

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from code_relations.models import ChunkEdge, ChunkRegistry, EdgeType
from codegraph.models import Symbol
from repositories.models import Repository

User = get_user_model()

GALAXY_URL = "/api/codegraph/galaxy/"
SEARCH_URL = "/api/codegraph/galaxy/search/"


def make_user(username: str = "testuser") -> User:
    return User.objects.create_user(username=username, password="pass")  # type: ignore[return-value]


def make_repo(name: str = "test-repo") -> Repository:
    return Repository.objects.create(
        name=name,
        git_url=f"https://example.com/{name}.git",
        default_branch="main",
    )


def make_chunk(repo: Repository, file_path: str = "a.py", chunk_index: int = 0) -> ChunkRegistry:
    return ChunkRegistry.objects.create(
        chunk_id=uuid.uuid4(),
        content_hash="abc",
        repository=repo,
        file_path=file_path,
        chunk_index=chunk_index,
        line_start=1,
        line_end=50,
    )


@pytest.mark.django_db
class TestGalaxyViewAuth(TestCase):
    """V1: 无认证返回 401。"""

    def test_unauthenticated_returns_401(self) -> None:
        client = APIClient()
        response = client.get(GALAXY_URL)
        assert response.status_code == 401


@pytest.mark.django_db
class TestGalaxyViewEmpty(TestCase):
    """V2: 空库返回空 payload。"""

    def test_empty_db_returns_200_with_empty_payload(self) -> None:
        user = make_user()
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(GALAXY_URL)
        assert response.status_code == 200
        data = response.json()
        assert data["nodes"] == []
        assert data["edges"] == []
        assert "meta" in data
        assert data["meta"]["sampled"] is False


@pytest.mark.django_db
class TestGalaxyViewRepoFilter(TestCase):
    """V3: repo_ids 过滤只返回对应仓库数据。"""

    def test_repo_ids_filter(self) -> None:
        user = make_user()
        repo1 = make_repo("repo1")
        repo2 = make_repo("repo2")
        make_chunk(repo1, "a.py")
        make_chunk(repo2, "b.py")

        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(GALAXY_URL, {"repo_ids": str(repo1.id)})
        assert response.status_code == 200
        data = response.json()
        repo_ids_in_nodes = {n["repository_id"] for n in data["nodes"]}
        assert str(repo2.id) not in repo_ids_in_nodes
        assert str(repo1.id) in repo_ids_in_nodes


@pytest.mark.django_db
class TestGalaxyViewSampling(TestCase):
    """V4: max_nodes=1 时 sampled=True。"""

    def test_sampling_flag_in_meta(self) -> None:
        user = make_user()
        repo = make_repo()
        c1 = make_chunk(repo, "a.py", 0)
        c2 = make_chunk(repo, "b.py", 1)
        # 给 c1 加出边提高 degree
        ChunkEdge.objects.create(
            source_chunk_id=c1.chunk_id,
            target_chunk_id=c2.chunk_id,
            edge_type=EdgeType.CALL,
            weight=0.8,
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
        assert data["meta"]["total_nodes"] == 2


@pytest.mark.django_db
class TestGalaxySearchViewMissingQ(TestCase):
    """V5: q 缺失 → 400。"""

    def test_missing_q_returns_400(self) -> None:
        user = make_user()
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(SEARCH_URL)
        assert response.status_code == 400
        assert "q" in response.json().get("detail", "")


@pytest.mark.django_db
class TestGalaxySearchViewEmptyResult(TestCase):
    """V6: q=foo 空库 → 200 results=[]。"""

    def test_search_empty_db(self) -> None:
        user = make_user()
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(SEARCH_URL, {"q": "foobar"})
        assert response.status_code == 200
        data = response.json()
        assert data["results"] == []
        assert data["count"] == 0
        assert data["query"] == "foobar"


@pytest.mark.django_db
class TestGalaxySearchViewWithResults(TestCase):
    """V7: search 有匹配 → 200 非空。"""

    def test_search_finds_symbol(self) -> None:
        user = make_user()
        repo = make_repo()
        Symbol.objects.create(
            repository=repo,
            name="my_search_function",
            symbol_type="FUNCTION",
            file_path="mod.py",
            start_line=1,
            end_line=10,
            signature="def my_search_function()",
        )

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(SEARCH_URL, {"q": "my_search"})
        assert response.status_code == 200
        data = response.json()
        assert data["count"] > 0
        types = [r["type"] for r in data["results"]]
        assert "symbol" in types


@pytest.mark.django_db
class TestGalaxyNodeDetailInvalidFormat(TestCase):
    """V8: 格式非法的 node_id → 400。"""

    def test_bad_format_returns_400(self) -> None:
        user = make_user()
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(f"{GALAXY_URL}nodes/badformat/")
        assert response.status_code == 400


@pytest.mark.django_db
class TestGalaxyNodeDetailInvalidUUID(TestCase):
    """V9: node_id UUID 部分非法 → 400。"""

    def test_invalid_uuid_returns_400(self) -> None:
        user = make_user()
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(f"{GALAXY_URL}nodes/chunk:not-a-uuid/")
        assert response.status_code == 400


@pytest.mark.django_db
class TestGalaxyNodeDetailNotFound(TestCase):
    """V10: 节点不存在 → 404。"""

    def test_nonexistent_node_returns_404(self) -> None:
        user = make_user()
        client = APIClient()
        client.force_authenticate(user=user)
        fake_id = uuid.uuid4()
        response = client.get(f"{GALAXY_URL}nodes/chunk:{fake_id}/")
        assert response.status_code == 404


@pytest.mark.django_db
class TestGalaxyNodeDetailFound(TestCase):
    """V11: 节点存在 → 200 包含 node + neighbors。"""

    def test_existing_chunk_node(self) -> None:
        user = make_user()
        repo = make_repo()
        chunk = make_chunk(repo, "main.py", 0)

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(f"{GALAXY_URL}nodes/chunk:{chunk.chunk_id}/")
        assert response.status_code == 200
        data = response.json()
        assert "node" in data
        assert "neighbors" in data
        assert "references" in data
        assert "called_by" in data
        assert data["node"]["id"] == f"chunk:{chunk.chunk_id}"
        assert data["node"]["type"] == "chunk_registry"
        assert data["neighbors"] == []  # 无邻居
