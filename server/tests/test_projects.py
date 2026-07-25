"""项目端点测试。

使用 pytest + pytest-django 风格，提供更好的表达力和可维护性。
"""

import uuid

import pytest
from rest_framework import status

from projects.models import RepositoryPermission, SpaceRepository

# ============================================================================
# 项目列表和创建测试
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestProjectListCreate:
    """项目列表和创建接口测试。"""

    def test_list_projects_empty(self, authenticated_admin_client, urls):
        """测试空项目列表。"""
        response = authenticated_admin_client.get(urls.space_list)

        assert response.status_code == status.HTTP_200_OK
        assert response.data == []

    def test_list_projects_with_data(self, authenticated_admin_client, project, urls):
        """测试有数据的项目列表。"""
        response = authenticated_admin_client.get(urls.space_list)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]["name"] == "Test Space"

    def test_create_project(self, authenticated_admin_client, urls):
        """测试创建项目。"""
        response = authenticated_admin_client.post(
            urls.space_list,
            {
                "name": "New Space",
                "description": "A new project",
                "feishu_project_key": "new-project-key",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["name"] == "New Space"
        assert "id" in response.data
        assert "webhook_token" in response.data

    def test_create_project_unauthenticated(self, api_client, urls):
        """测试未认证用户无法创建项目。"""
        response = api_client.post(
            urls.space_list,
            {"name": "New Space"},
            format="json",
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


# ============================================================================
# 项目详情测试
# ============================================================================


@pytest.mark.django_db
class TestProjectDetail:
    """项目详情接口测试。"""

    def test_get_project(self, authenticated_admin_client, project, urls):
        """测试获取单个项目。"""
        response = authenticated_admin_client.get(urls.space_detail(project.id))

        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == "Test Space"
        assert response.data["feishu_project_key"] == "test-project-key"

    def test_get_project_not_found(self, authenticated_admin_client, urls):
        """测试获取不存在的项目。"""
        response = authenticated_admin_client.get(urls.space_detail(uuid.uuid4()))

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_update_project(self, authenticated_admin_client, project, urls):
        """测试更新项目。"""
        response = authenticated_admin_client.patch(
            urls.space_detail(project.id),
            {"name": "Updated Space"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == "Updated Space"

    def test_delete_project(self, authenticated_admin_client, project, urls):
        """测试删除项目。"""
        response = authenticated_admin_client.delete(urls.space_detail(project.id))

        assert response.status_code == status.HTTP_204_NO_CONTENT

        # 验证已删除
        response = authenticated_admin_client.get(urls.space_detail(project.id))
        assert response.status_code == status.HTTP_404_NOT_FOUND


# ============================================================================
# 项目-仓库关联测试
# ============================================================================


@pytest.mark.django_db
class TestProjectRepositoryAssociation:
    """项目-仓库关联接口测试。

    当前契约（``projects/urls.py`` + ``projects/views.py``）：

    - ``GET  /api/spaces/{space_id}/repositories/`` → 200，返回 ``SpaceRepository``
      关联记录列表（不是 ``Repository`` 本体），仓库信息扁平展开为
      ``repository_id`` / ``repository_name``。
    - ``POST /api/spaces/{space_id}/repositories/`` body ``{"repository_ids": [...]}``
      → 201 ``{"created": [...], "skipped": [...]}``，批量关联且幂等。
    - ``DELETE /api/spaces/{space_id}/repositories/{pk}/`` → 204，其中 ``pk`` 是
      ``SpaceRepository`` 关联记录的自增主键，**不是** ``Repository`` 的 UUID。
    """

    def test_list_project_repositories(
        self, authenticated_admin_client, project, repository, urls
    ):
        """列表返回关联记录，仓库信息以 repository_id/repository_name 展开。"""
        response = authenticated_admin_client.get(urls.space_repositories(project.id))

        assert response.status_code == status.HTTP_200_OK
        # project fixture 已关联一个仓库
        assert len(response.data) == 1
        link = response.data[0]
        assert link["repository_id"] == str(repository.id)
        assert link["repository_name"] == "Test Repo"
        # 默认权限级别为读写，且返回的 id 是关联记录主键而非仓库主键
        assert link["permission_level"] == RepositoryPermission.READ_WRITE
        assert link["id"] == SpaceRepository.objects.get(
            space=project, repository=repository
        ).pk

    def test_link_repository(
        self, authenticated_admin_client, project_without_repo, repository, urls
    ):
        """批量关联仓库到空间，返回新建的关联记录。"""
        response = authenticated_admin_client.post(
            urls.space_repositories(project_without_repo.id),
            {"repository_ids": [str(repository.id)]},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["skipped"] == []
        assert len(response.data["created"]) == 1
        created = response.data["created"][0]
        assert created["repository_id"] == str(repository.id)
        assert created["repository_name"] == "Test Repo"
        assert created["permission_level"] == RepositoryPermission.READ_WRITE

        # 验证已关联
        assert repository in project_without_repo.repositories.all()

    def test_link_repository_is_idempotent(
        self, authenticated_admin_client, project, repository, urls
    ):
        """重复关联走 skipped 分支，不产生重复关联记录。"""
        response = authenticated_admin_client.post(
            urls.space_repositories(project.id),
            {"repository_ids": [str(repository.id)]},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["created"] == []
        assert response.data["skipped"] == [str(repository.id)]
        assert SpaceRepository.objects.filter(space=project, repository=repository).count() == 1

    def test_unlink_repository(self, authenticated_admin_client, project, repository, urls):
        """按关联记录主键取消关联。"""
        link = SpaceRepository.objects.get(space=project, repository=repository)

        response = authenticated_admin_client.delete(
            urls.space_unlink_repository(project.id, link.pk)
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not SpaceRepository.objects.filter(pk=link.pk).exists()
        assert repository not in project.repositories.all()

    def test_unlink_with_repository_uuid_returns_404_not_500(
        self, authenticated_admin_client, project, repository, urls
    ):
        """误传 Repository UUID（旧 API 用法）应干净 404，不得 500 吐堆栈。

        本端点的 pk 是 SpaceRepository 自增主键；路由为 ``<str:pk>``，UUID 会一路进到
        ORM，``int()`` 转换失败抛 ValueError → 500。调用方从旧 API 升级时极易踩到。
        同时断言关联未被误删。
        """
        response = authenticated_admin_client.delete(
            urls.space_unlink_repository(project.id, repository.id)
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert SpaceRepository.objects.filter(space=project, repository=repository).exists()

    def test_patch_with_repository_uuid_returns_404_not_500(
        self, authenticated_admin_client, project, repository, urls
    ):
        """PATCH 同一端点误传 UUID 同样应 404（与 DELETE 对称，避免只修一半）。"""
        response = authenticated_admin_client.patch(
            urls.space_unlink_repository(project.id, repository.id),
            {"permission_level": "read"},
            format="json",
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


# ============================================================================
# implementation（contract/contract）：v8.1 /api/projects/<id>/claude-config/ 端点硬删；
# TestProjectClaudeConfig 整类删除。契约 404 由 tests/test_claude_config_endpoint_removed.py 覆盖。
# ============================================================================
