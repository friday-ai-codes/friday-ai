"""``GraphRagStatusView`` 的 ``?branch=`` 合并计数测试（implementation，work item）。

GET /api/repositories/{id}/index/graphrag-status/?branch=<分支>

覆盖 branch-aware ChunkEdge 计数三条核心口径：
- feature 分支 → base + overlay 合并计数（不同 branch 返回不同值）。
- 缺省不传 branch → 干净 base 计数，存量纯 base 仓库 ≡ 旧全表 count（向后兼容，Pitfall B）。
- 传 base_branch 名（==base）→ 与缺省同走 ``branch_name=""`` 路径。
"""

from __future__ import annotations

import uuid

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from repositories.models import Repository, RepositoryBranchIndex


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def user(db: object) -> object:
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(
        username="graphrag_branch_user",
        email="graphrag_branch@example.com",
        password="graphragpass123",
    )


@pytest.fixture
def auth_client(api_client: APIClient, user: object) -> APIClient:
    api_client.force_authenticate(user=user)
    return api_client


@pytest.fixture
def repo(db: object) -> Repository:
    return Repository.objects.create(
        name="GraphRAG Branch Repo",
        git_url="https://github.com/test/graphrag-branch-repo.git",
        git_platform="github",
        default_branch="main",
    )


def _url(repository_id: uuid.UUID | str) -> str:
    return f"/api/repositories/{repository_id}/index/graphrag-status/"


def _make_edges(repo: Repository, n: int, branch_name: str = "") -> None:
    """在指定分支维度构造 n 条 ChunkEdge（branch_name="" 即 base）。"""
    from code_relations.models import ChunkEdge
    from code_relations.utils import generate_chunk_id

    prefix = branch_name or "base"
    for i in range(n):
        ChunkEdge.objects.create(
            source_chunk_id=generate_chunk_id(str(repo.id), f"{prefix}_a{i}.py", 0),
            target_chunk_id=generate_chunk_id(str(repo.id), f"{prefix}_b{i}.py", 0),
            edge_type="CALL",
            weight=0.5,
            repository=repo,
            branch_name=branch_name,
        )


def _enable_branch_index(repo: Repository, feature: str) -> None:
    """开启分支索引模型——resolve_branch_for_query 依赖 base 记录存在才归一化。"""
    RepositoryBranchIndex.objects.create(
        repository=repo,
        branch_name=repo.default_branch,
        is_base_branch=True,
    )
    RepositoryBranchIndex.objects.create(
        repository=repo,
        branch_name=feature,
        is_base_branch=False,
    )


@pytest.mark.django_db
def test_branch_merges_base_and_overlay(
    auth_client: APIClient, repo: Repository
) -> None:
    """work item：feature 分支返回 base+overlay 合并计数，不同 branch 返回不同值。"""
    _enable_branch_index(repo, feature="feat-x")
    _make_edges(repo, 3, branch_name="")  # base
    _make_edges(repo, 2, branch_name="feat-x")  # overlay

    # feature 分支：base(3) + overlay(2) = 5
    resp_feat = auth_client.get(_url(repo.id), {"branch": "feat-x"})
    assert resp_feat.status_code == status.HTTP_200_OK
    assert resp_feat.data["edge_count"] == 5

    # 缺省不传 branch：仅 base = 3（与 feature 计数不同，证明 branch 维度生效）
    resp_default = auth_client.get(_url(repo.id))
    assert resp_default.status_code == status.HTTP_200_OK
    assert resp_default.data["edge_count"] == 3
    assert resp_default.data["edge_count"] != resp_feat.data["edge_count"]


@pytest.mark.django_db
def test_default_backward_compat(auth_client: APIClient, repo: Repository) -> None:
    """work item 核心回归（Pitfall B）：存量纯 base 仓库不传 branch ≡ 旧全表 count。

    未开启分支索引模型的存量仓库，所有 ChunkEdge 均 branch_name=""（293 迁移），
    缺省口径用 branch_name="" 过滤等价于旧全表 count，不漂移。
    """
    _make_edges(repo, 4, branch_name="")  # 存量纯 base

    resp = auth_client.get(_url(repo.id))

    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["edge_count"] == 4, "缺省口径必须等价旧全表 count"
    assert resp.data["status"] == "completed"


@pytest.mark.django_db
def test_base_branch_equals_base(
    auth_client: APIClient, repo: Repository
) -> None:
    """work item：传 base_branch 名（==base）走 branch_name="" 路径，排除 feature 边。"""
    _enable_branch_index(repo, feature="feat-x")
    _make_edges(repo, 3, branch_name="")  # base
    _make_edges(repo, 2, branch_name="feat-x")  # overlay

    # 传 base 分支名 main（==base）→ 与缺省同结果，只算 base 3 条
    resp = auth_client.get(_url(repo.id), {"branch": "main"})

    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["edge_count"] == 3, "==base 必须走 branch_name=\"\" 路径"


@pytest.mark.django_db
def test_404_for_missing_repo(auth_client: APIClient) -> None:
    """不存在的仓库返回 404（branch 参数不改变 404 语义）。"""
    resp = auth_client.get(_url(uuid.uuid4()), {"branch": "feat-x"})
    assert resp.status_code == status.HTTP_404_NOT_FOUND
