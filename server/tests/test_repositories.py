"""仓库端点测试。
使用 pytest + pytest-django 风格，提供更好的表达力和可维护性。
"""
import pytest
from django.urls import reverse
from rest_framework import status
# ============================================================================
# 仓库列表和创建测试
# ============================================================================
@pytest.mark.django_db
class TestRepositoryListCreate:
 """仓库列表和创建接口测试。"""
 def test_list_repositories_empty(self, authenticated_client, urls):
 """测试空仓库列表。"""
 response = authenticated_client.get(urls.repository_list)
 assert response.status_code == status.HTTP_200_OK
 assert response.data ==
 def test_list_repositories_with_data(self, authenticated_client, repository, urls):
 """测试有数据的仓库列表。"""
 response = authenticated_client.get(urls.repository_list)
 assert response.status_code == status.HTTP_200_OK
 assert len(response.data) == 1
 assert response.data[0]["name"] == "Test Repo"
 def test_create_repository_with_token(self, authenticated_client, urls):
 """测试使用 token 创建仓库。"""
 response = authenticated_client.post(
 urls.repository_list,
 {
 "name": "New Repo",
 "git_url": "https://github.com/test/new-repo.git",
 "git_platform": "github",
 "default_branch": "main",
 "access_token": "GITHUB_TOKEN_PLACEHOLDER",
 },
 format="json",
 )
 assert response.status_code == status.HTTP_201_CREATED
 assert response.data["name"] == "New Repo"
 assert response.data["has_credential"] is True
 def test_create_repository_empty_token(self, authenticated_client, urls):
 """测试使用空 token 创建仓库失败。"""
 response = authenticated_client.post(
 urls.repository_list,
 {
 "name": "No Token Repo",
 "git_url": "https://github.com/test/repo.git",
 "access_token": " ",
 },
 format="json",
 )
 assert response.status_code == status.HTTP_400_BAD_REQUEST
 def test_create_repository_rejects_ssh_git_url(self, authenticated_client, urls):
 """测试创建仓库时拒绝 SSH URL。"""
 response = authenticated_client.post(
 urls.repository_list,
 {
 "name": "SSH Repo",
 "git_url": "git@github.com:test/repo.git",
 "access_token": "GITHUB_TOKEN_PLACEHOLDER",
 },
 format="json",
 )
 assert response.status_code == status.HTTP_400_BAD_REQUEST
 assert "仅支持 HTTPS" in str(response.data)
 def test_create_repository_unauthenticated(self, api_client, urls):
 """测试未认证用户无法创建仓库。"""
 response = api_client.post(
 urls.repository_list,
 {"name": "New Repo", "git_url": "https://github.com/test/repo.git"},
 format="json",
 )
 assert response.status_code == status.HTTP_401_UNAUTHORIZED
# ============================================================================
# 仓库详情测试
# ============================================================================
@pytest.mark.django_db
class TestRepositoryDetail:
 """仓库详情接口测试。"""
 def test_get_repository(self, authenticated_client, repository, urls):
 """测试获取单个仓库。"""
 response = authenticated_client.get(urls.repository_detail(repository.id))
 assert response.status_code == status.HTTP_200_OK
 assert response.data["name"] == "Test Repo"
 assert "projects" in response.data
 def test_update_repository(self, authenticated_client, repository, urls):
 """测试更新仓库。"""
 response = authenticated_client.patch(
 urls.repository_detail(repository.id),
 {"name": "Updated Repo"},
 format="json",
 )
 assert response.status_code == status.HTTP_200_OK
 assert response.data["name"] == "Updated Repo"
 def test_update_repository_rejects_ssh_git_url(
 self, authenticated_client, repository, urls
 ):
 """测试更新仓库时拒绝 SSH URL。"""
 response = authenticated_client.patch(
 urls.repository_detail(repository.id),
 {"git_url": "git@github.com:test/repo.git"},
 format="json",
 )
 assert response.status_code == status.HTTP_400_BAD_REQUEST
 assert "仅支持 HTTPS" in str(response.data)
 def test_delete_repository(self, authenticated_client, repository, urls):
 """测试删除仓库。"""
 response = authenticated_client.delete(urls.repository_detail(repository.id))
 assert response.status_code == status.HTTP_204_NO_CONTENT
# ============================================================================
# 仓库凭据测试
# ============================================================================
@pytest.mark.django_db
class TestRepositoryCredential:
 """仓库凭据接口测试。"""
 def test_get_credential(self, authenticated_client, urls):
 """测试获取仓库凭据。"""
 # 创建带凭据的仓库
 create_response = authenticated_client.post(
 urls.repository_list,
 {
 "name": "Repo With Cred",
 "git_url": "https://github.com/test/repo.git",
 "access_token": "test_token",
 },
 format="json",
 )
 repo_id = create_response.data["id"]
 response = authenticated_client.get(urls.repository_credential(repo_id))
 assert response.status_code == status.HTTP_200_OK
 assert response.data["has_access_token"] is True
 assert response.data["auth_type"] == "access_token"
 def test_get_credential_not_found(self, authenticated_client, repository, urls):
 """测试获取不存在的凭据。"""
 response = authenticated_client.get(urls.repository_credential(repository.id))
 # API returns 200 with null when credential doesn't exist
 assert response.status_code == status.HTTP_200_OK
 assert response.data is None
 def test_delete_credential(self, authenticated_client, urls):
 """测试删除仓库凭据。"""
 # 创建带凭据的仓库
 create_response = authenticated_client.post(
 urls.repository_list,
 {
 "name": "Repo To Delete Cred",
 "git_url": "https://github.com/test/repo.git",
 "access_token": "test_token",
 },
 format="json",
 )
 repo_id = create_response.data["id"]
 response = authenticated_client.delete(urls.repository_credential(repo_id))
 assert response.status_code == status.HTTP_204_NO_CONTENT
 # 验证已删除 - API returns 200 with null when credential doesn't exist
 response = authenticated_client.get(urls.repository_credential(repo_id))
 assert response.status_code == status.HTTP_200_OK
 assert response.data is None
@pytest.mark.django_db
class TestRepositoryConnection:
 """仓库连接测试接口。"""
 def test_test_connection_rejects_ssh_git_url(self, authenticated_client):
 """测试连接接口拒绝 SSH URL。"""
 response = authenticated_client.post(
 reverse("test-connection"),
 {
 "git_url": "git@github.com:test/repo.git",
 "access_token": "GITHUB_TOKEN_PLACEHOLDER",
 },
 format="json",
 )
 assert response.status_code == status.HTTP_400_BAD_REQUEST
 assert response.data["success"] is False
 assert "仅支持 HTTPS" in response.data["error"]
