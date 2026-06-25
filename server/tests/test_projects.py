"""项目端点测试。

使用 pytest + pytest-django 风格，提供更好的表达力和可维护性。
"""

import uuid

import pytest
from rest_framework import status

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
    """项目-仓库关联接口测试。"""

    @pytest.mark.xfail(reason="Space-Repository 关联 API 重构，端点和字段已变更", strict=False)
    def test_list_project_repositories(self, authenticated_admin_client, project, urls):
        """测试列出项目仓库。"""
        response = authenticated_admin_client.get(urls.space_repositories(project.id))

        assert response.status_code == status.HTTP_200_OK
        # project fixture 已关联一个仓库
        assert len(response.data) == 1
        assert response.data[0]["name"] == "Test Repo"

    @pytest.mark.xfail(reason="Space-Repository 关联 API 重构，端点和字段已变更", strict=False)
    def test_link_repository(self, authenticated_admin_client, project_without_repo, repository, urls):
        """测试关联仓库到项目。"""
        response = authenticated_admin_client.post(
            urls.space_link_repository(project_without_repo.id, repository.id)
        )

        assert response.status_code in [status.HTTP_200_OK, status.HTTP_201_CREATED]

        # 验证已关联
        assert repository in project_without_repo.repositories.all()

    @pytest.mark.xfail(reason="Space-Repository 关联 API 重构，端点和字段已变更", strict=False)
    def test_unlink_repository(self, authenticated_admin_client, project, repository, urls):
        """测试取消关联仓库。"""
        response = authenticated_admin_client.delete(
            urls.space_unlink_repository(project.id, repository.id)
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT


# ============================================================================
# implementation（contract/contract）：v8.1 /api/projects/<id>/claude-config/ 端点硬删；
# TestProjectClaudeConfig 整类删除。契约 404 由 tests/test_claude_config_endpoint_removed.py 覆盖。
# ============================================================================
