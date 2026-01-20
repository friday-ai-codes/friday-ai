"""项目端点测试。
使用 pytest + pytest-django 风格，提供更好的表达力和可维护性。
"""
import uuid
import pytest
from rest_framework import status
# ============================================================================
# 项目列表和创建测试
# ============================================================================
@pytest.mark.django_db
class TestProjectListCreate:
 """项目列表和创建接口测试。"""
 def test_list_projects_empty(self, authenticated_client, urls):
 """测试空项目列表。"""
 response = authenticated_client.get(urls.project_list)
 assert response.status_code == status.HTTP_200_OK
 assert response.data ==
 def test_list_projects_with_data(self, authenticated_client, project, urls):
 """测试有数据的项目列表。"""
 response = authenticated_client.get(urls.project_list)
 assert response.status_code == status.HTTP_200_OK
 assert len(response.data) == 1
 assert response.data[0]["name"] == "Test Project"
 def test_create_project(self, authenticated_client, urls):
 """测试创建项目。"""
 response = authenticated_client.post(
 urls.project_list,
 {
 "name": "New Project",
 "description": "A new project",
 "feishu_project_key": "new-project-key",
 },
 format="json",
 )
 assert response.status_code == status.HTTP_201_CREATED
 assert response.data["name"] == "New Project"
 assert "id" in response.data
 assert "webhook_token" in response.data
 def test_create_project_unauthenticated(self, api_client, urls):
 """测试未认证用户无法创建项目。"""
 response = api_client.post(
 urls.project_list,
 {"name": "New Project"},
 format="json",
 )
 assert response.status_code == status.HTTP_401_UNAUTHORIZED
# ============================================================================
# 项目详情测试
# ============================================================================
@pytest.mark.django_db
class TestProjectDetail:
 """项目详情接口测试。"""
 def test_get_project(self, authenticated_client, project, urls):
 """测试获取单个项目。"""
 response = authenticated_client.get(urls.project_detail(project.id))
 assert response.status_code == status.HTTP_200_OK
 assert response.data["name"] == "Test Project"
 assert response.data["feishu_project_key"] == "test-project-key"
 def test_get_project_not_found(self, authenticated_client, urls):
 """测试获取不存在的项目。"""
 response = authenticated_client.get(urls.project_detail(uuid.uuid4))
 assert response.status_code == status.HTTP_404_NOT_FOUND
 def test_update_project(self, authenticated_client, project, urls):
 """测试更新项目。"""
 response = authenticated_client.patch(
 urls.project_detail(project.id),
 {"name": "Updated Project"},
 format="json",
 )
 assert response.status_code == status.HTTP_200_OK
 assert response.data["name"] == "Updated Project"
 def test_delete_project(self, authenticated_client, project, urls):
 """测试删除项目。"""
 response = authenticated_client.delete(urls.project_detail(project.id))
 assert response.status_code == status.HTTP_204_NO_CONTENT
 # 验证已删除
 response = authenticated_client.get(urls.project_detail(project.id))
 assert response.status_code == status.HTTP_404_NOT_FOUND
# ============================================================================
# 项目-仓库关联测试
# ============================================================================
@pytest.mark.django_db
class TestProjectRepositoryAssociation:
 """项目-仓库关联接口测试。"""
 def test_list_project_repositories(self, authenticated_client, project, urls):
 """测试列出项目仓库。"""
 response = authenticated_client.get(urls.project_repositories(project.id))
 assert response.status_code == status.HTTP_200_OK
 # project fixture 已关联一个仓库
 assert len(response.data) == 1
 assert response.data[0]["name"] == "Test Repo"
 def test_link_repository(self, authenticated_client, project_without_repo, repository, urls):
 """测试关联仓库到项目。"""
 response = authenticated_client.post(
 urls.project_link_repository(project_without_repo.id, repository.id)
 )
 assert response.status_code in [status.HTTP_200_OK, status.HTTP_201_CREATED]
 # 验证已关联
 assert repository in project_without_repo.repositories.all
 def test_unlink_repository(self, authenticated_client, project, repository, urls):
 """测试取消关联仓库。"""
 response = authenticated_client.delete(
 urls.project_unlink_repository(project.id, repository.id)
 )
 assert response.status_code == status.HTTP_204_NO_CONTENT
# ============================================================================
# 项目 Claude 配置测试
# ============================================================================
@pytest.mark.django_db
class TestProjectClaudeConfig:
 """项目 Claude 配置接口测试。"""
 def test_get_claude_config_default(self, authenticated_client, project, urls):
 """测试获取默认 Claude 配置。"""
 response = authenticated_client.get(urls.project_claude_config(project.id))
 assert response.status_code == status.HTTP_200_OK
 assert response.data["has_api_key"] is False
 assert response.data["source"] == "system"
 def test_set_claude_config(self, authenticated_client, project, urls):
 """测试设置 Claude 配置。"""
 response = authenticated_client.put(
 urls.project_claude_config(project.id),
 {"api_key": "sk-test-key-12345", "base_url": "https://api.example.com"},
 format="json",
 )
 assert response.status_code == status.HTTP_200_OK
 assert response.data["has_api_key"] is True
 assert response.data["base_url"] == "https://api.example.com"
 assert response.data["source"] == "project"
 def test_delete_claude_config(self, authenticated_client, project, urls):
 """测试删除 Claude 配置。"""
 # 先设置
 authenticated_client.put(
 urls.project_claude_config(project.id),
 {"api_key": "sk-test-key"},
 format="json",
 )
 # 再删除
 response = authenticated_client.delete(urls.project_claude_config(project.id))
 assert response.status_code == status.HTTP_204_NO_CONTENT
