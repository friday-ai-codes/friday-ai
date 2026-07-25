"""Repository.auto_build_graph_enabled 字段三层断言。

测试覆盖（work item-01）：
1. test_field_default_is_true：模型字段默认值字面值 True（向后兼容）。
2. test_create_repository_default_true：新建 Repository 实例不传字段时
   ORM 层 `repo.auto_build_graph_enabled is True`。
3. test_serializer_exposes_field_readwrite：直接实例化 RepositorySerializer
   既能在 .data 读出又能 partial=True 写入。
4. test_field_not_in_read_only_fields：字段必须可写——不能被加入
   Meta.read_only_fields，否则 PATCH 端点会被静默忽略。
5. test_patch_endpoint_writes_and_reads：PATCH /api/repositories/{id}/ 端到端
   写入 false 后 GET 回读 false（双向幂等）。

注：本 plan 仅落模型字段 + serializer 暴露，不承担 indexer 双重判断
（双重判断在 plan 落地——见 work-item.md decisions 段）。
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from repositories.models import Repository
from repositories.serializers import RepositorySerializer


@pytest.fixture
def graph_repo(db, user) -> Repository:
    """供本 plan 测试关联的独立 Repository 实例（避免与全局 fixture 串污染）。

    自带独立空间 + user 的 MEMBER 成员关系：仓库可见性按空间成员过滤（#9/#11），
    孤儿仓库仅超管可见，否则本文件用普通用户走 REST 链路会 404。
    """
    from permissions.models import SpaceMembership, SpaceRole
    from projects.models import Space

    repo = Repository.objects.create(
        name="auto-build-graph-repo",
        git_url="https://github.com/test/auto-build-graph-repo.git",
        git_platform="github",
        default_branch="main",
    )
    space = Space.objects.create(name="auto-build-graph-space")
    space.repositories.add(repo)
    SpaceMembership.objects.create(user=user, space=space, role=SpaceRole.MEMBER)
    return repo


@pytest.mark.django_db
def test_field_default_is_true() -> None:
    """Repository._meta 上 auto_build_graph_enabled 字段 default 必须为字面值 True。

    向后兼容关键不变量：迁移后既有仓库自动构图行为不变。
    """
    field = Repository._meta.get_field("auto_build_graph_enabled")
    assert field.default is True


@pytest.mark.django_db
def test_create_repository_default_true(graph_repo: Repository) -> None:
    """ORM 创建实例不显式传字段时，实例 attribute 必须取 True。"""
    assert graph_repo.auto_build_graph_enabled is True


@pytest.mark.django_db
def test_serializer_exposes_field_readwrite(graph_repo: Repository) -> None:
    """RepositorySerializer 必须在 .data 暴露字段，且 partial=True 校验可写入 False。"""
    data = RepositorySerializer(graph_repo).data
    assert "auto_build_graph_enabled" in data
    assert data["auto_build_graph_enabled"] is True

    serializer = RepositorySerializer(
        graph_repo,
        data={"auto_build_graph_enabled": False},
        partial=True,
    )
    assert serializer.is_valid(), serializer.errors


@pytest.mark.django_db
def test_field_not_in_read_only_fields() -> None:
    """字段必须可写——不能落入 Meta.read_only_fields，否则 PATCH 端点静默忽略写入。"""
    read_only_fields = RepositorySerializer.Meta.read_only_fields
    assert "auto_build_graph_enabled" not in read_only_fields


@pytest.mark.django_db
def test_patch_endpoint_writes_and_reads(
    authenticated_client: APIClient,
    graph_repo: Repository,
) -> None:
    """PATCH /api/repositories/{id}/ 写入 False 后 GET 回读必须 == False。

    覆盖完整 REST 写读链路：DRF 反序列化 → ORM update → DB → ORM fetch → 序列化输出。
    """
    url = f"/api/repositories/{graph_repo.id}/"

    patch_response = authenticated_client.patch(
        url,
        data={"auto_build_graph_enabled": False},
        format="json",
    )
    assert patch_response.status_code == 200, patch_response.data
    assert patch_response.data["auto_build_graph_enabled"] is False

    get_response = authenticated_client.get(url)
    assert get_response.status_code == 200
    assert get_response.data["auto_build_graph_enabled"] is False

    graph_repo.refresh_from_db()
    assert graph_repo.auto_build_graph_enabled is False
