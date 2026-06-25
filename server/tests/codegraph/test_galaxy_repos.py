"""GalaxyAggregator.aggregate_repos + GalaxyReposView 测试 —— L2 仓库节点视图。

覆盖：
R1  空库 aggregate_repos() → nodes=[], edges=[]
R2  仓库节点 = 未软删的 Repository，含 metadata 字段
R3  space_id 过滤：仅返回该 Space 关联的仓库
R4  多条 CrossRepoApiCall 同 (caller_repo, callee_repo) 聚合成 1 条 REPO_API_CALL 边
R5  自环（call_site / endpoint 同仓）跳过
R6  软删仓库不返回
R7  GET /api/codegraph/galaxy/repos/ 无认证 → 401
R8  GET /api/codegraph/galaxy/repos/ 空库 → 200 nodes=[], edges=[]
R9  GET /api/codegraph/galaxy/repos/?space_id=<uuid> 过滤
R10 GET /api/codegraph/galaxy/repos/?space_id=invalid → 400
"""

from __future__ import annotations

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from codegraph.galaxy.aggregator import GalaxyAggregator
from codegraph.models import (
    ApiCallSite,
    ApiWrapper,
    CrossRepoApiCall,
    Endpoint,
)
from projects.models import Space, SpaceRepository
from repositories.models import Repository

User = get_user_model()

REPOS_URL = "/api/codegraph/galaxy/repos/"


def make_user(username: str = "testuser"):
    return User.objects.create_user(username=username, password="pass")


def make_repo(name: str = "test-repo", platform: str = "gitlab") -> Repository:
    return Repository.objects.create(
        name=name,
        git_url=f"https://example.com/{name}.git",
        default_branch="main",
        git_platform=platform,
    )


def make_project(name: str = "space-a") -> Space:
    return Space.objects.create(name=name)


def link_repo_to_project(project: Space, repo: Repository) -> SpaceRepository:
    return SpaceRepository.objects.create(space=project, repository=repo)


def make_cross_call(
    repo_fe: Repository,
    repo_be: Repository,
    url_path: str = "/api/users",
    method: str = "GET",
    confidence: float = 1.0,
) -> CrossRepoApiCall:
    """造一条 repo_fe → repo_be 的跨仓 API 调用记录（含完整链路）。"""
    wrapper = ApiWrapper.objects.create(
        repository=repo_fe,
        file_path=f"api/{url_path.strip('/').replace('/', '_')}.ts",
        function_symbol=f"call{url_path.strip('/').replace('/', '_')}",
        http_method=method,
        url_path_raw=url_path,
        url_path_pattern=url_path,
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
        http_method=method,
        url_path=url_path,
        handler_name="HandlerFn",
        view_type="FUNCTION_VIEW",
        file_path="handler.go",
        line_number=5,
    )
    return CrossRepoApiCall.objects.create(
        call_site=call_site,
        endpoint=endpoint,
        match_confidence=confidence,
    )


# ============================================================================
# Aggregator 单元测试
# ============================================================================


@pytest.mark.django_db
class TestAggregateReposEmpty(TestCase):
    """R1: 空库返回空 payload。"""

    def test_empty_db(self) -> None:
        result = GalaxyAggregator.aggregate_repos()
        assert result["nodes"] == []
        assert result["edges"] == []
        meta = result["meta"]
        assert meta["total_nodes"] == 0
        assert meta["total_edges"] == 0
        assert meta["sampled"] is False
        assert meta["by_node_type"] == {"repository": 0}


@pytest.mark.django_db
class TestAggregateReposNodes(TestCase):
    """R2: 仓库节点结构正确。"""

    def test_repo_node_shape(self) -> None:
        repo = make_repo("frontend", platform="github")
        proj = make_project("space-a")
        link_repo_to_project(proj, repo)

        result = GalaxyAggregator.aggregate_repos()
        assert len(result["nodes"]) == 1
        node = result["nodes"][0]
        assert node["id"] == f"repo:{repo.id}"
        assert node["type"] == "repository"
        assert node["label"] == "frontend"
        assert node["repository_id"] == str(repo.id)
        assert node["metadata"]["git_platform"] == "github"
        assert node["metadata"]["space_ids"] == [str(proj.id)]
        assert node["metadata"]["endpoint_count"] == 0
        assert node["metadata"]["callsite_count"] == 0
        assert node["degree"] == 0


@pytest.mark.django_db
class TestAggregateReposSpaceFilter(TestCase):
    """R3: space_id 过滤。"""

    def test_filter_by_space(self) -> None:
        repo_a = make_repo("repo-a")
        repo_b = make_repo("repo-b")
        repo_c = make_repo("repo-c")  # 未关联到任何 project
        proj_x = make_project("space-x")
        proj_y = make_project("space-y")
        link_repo_to_project(proj_x, repo_a)
        link_repo_to_project(proj_x, repo_b)
        link_repo_to_project(proj_y, repo_c)

        result_x = GalaxyAggregator.aggregate_repos(space_id=proj_x.id)
        labels_x = {n["label"] for n in result_x["nodes"]}
        assert labels_x == {"repo-a", "repo-b"}

        result_y = GalaxyAggregator.aggregate_repos(space_id=proj_y.id)
        assert {n["label"] for n in result_y["nodes"]} == {"repo-c"}

        result_all = GalaxyAggregator.aggregate_repos()
        assert {n["label"] for n in result_all["nodes"]} == {"repo-a", "repo-b", "repo-c"}


@pytest.mark.django_db
class TestAggregateReposEdgeAggregation(TestCase):
    """R4: 多条 CrossRepoApiCall 同 (caller_repo, callee_repo) 聚合成 1 条边。"""

    def test_multiple_calls_aggregate_to_one_edge(self) -> None:
        repo_fe = make_repo("fe")
        repo_be = make_repo("be")
        make_cross_call(repo_fe, repo_be, "/api/users")
        make_cross_call(repo_fe, repo_be, "/api/orders")
        make_cross_call(repo_fe, repo_be, "/api/products", confidence=0.5)

        result = GalaxyAggregator.aggregate_repos()
        edges = result["edges"]
        assert len(edges) == 1
        edge = edges[0]
        assert edge["edge_type"] == "REPO_API_CALL"
        assert edge["source"] == f"repo:{repo_fe.id}"
        assert edge["target"] == f"repo:{repo_be.id}"
        assert edge["weight"] == 3.0
        assert edge["metadata"]["call_count"] == 3
        # avg = (1.0 + 1.0 + 0.5) / 3
        assert abs(edge["metadata"]["avg_confidence"] - (2.5 / 3)) < 1e-6
        assert edge["repository_id"] == str(repo_fe.id)
        assert edge["target_repository_id"] == str(repo_be.id)


@pytest.mark.django_db
class TestAggregateReposSelfLoop(TestCase):
    """R5: 自环（call_site / endpoint 同仓）跳过。"""

    def test_self_loop_skipped(self) -> None:
        repo = make_repo("monolith")
        make_cross_call(repo, repo, "/api/internal")

        result = GalaxyAggregator.aggregate_repos()
        assert len(result["nodes"]) == 1
        assert result["edges"] == []


@pytest.mark.django_db
class TestAggregateReposSoftDelete(TestCase):
    """R6: 软删仓库不返回。"""

    def test_soft_deleted_excluded(self) -> None:
        repo_alive = make_repo("alive")
        repo_dead = make_repo("dead")
        repo_dead.is_deleted = True
        repo_dead.save(update_fields=["is_deleted"])

        result = GalaxyAggregator.aggregate_repos()
        labels = {n["label"] for n in result["nodes"]}
        assert labels == {"alive"}


# ============================================================================
# View 集成测试
# ============================================================================


@pytest.mark.django_db
class TestGalaxyReposViewAuth(TestCase):
    """R7: 无认证返回 401。"""

    def test_unauthenticated(self) -> None:
        client = APIClient()
        response = client.get(REPOS_URL)
        assert response.status_code == 401


@pytest.mark.django_db
class TestGalaxyReposViewEmpty(TestCase):
    """R8: 空库 → 200 nodes=[], edges=[]。"""

    def test_empty(self) -> None:
        user = make_user()
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(REPOS_URL)
        assert response.status_code == 200
        data = response.json()
        assert data["nodes"] == []
        assert data["edges"] == []


@pytest.mark.django_db
class TestGalaxyReposViewSpaceFilter(TestCase):
    """R9: ?space_id 过滤。"""

    def test_space_filter_via_query(self) -> None:
        repo_a = make_repo("repo-a")
        repo_b = make_repo("repo-b")
        proj = make_project("space-x")
        link_repo_to_project(proj, repo_a)

        user = make_user()
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(REPOS_URL, {"space_id": str(proj.id)})
        assert response.status_code == 200
        data = response.json()
        labels = {n["label"] for n in data["nodes"]}
        assert labels == {"repo-a"}


@pytest.mark.django_db
class TestGalaxyReposViewBadSpaceId(TestCase):
    """R10: 非法 space_id → 400。"""

    def test_bad_uuid(self) -> None:
        user = make_user()
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(REPOS_URL, {"space_id": "not-a-uuid"})
        assert response.status_code == 400
