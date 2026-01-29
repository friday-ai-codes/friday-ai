"""pytest-django 测试配置和 fixtures。
使用 pytest + pytest-django 风格，提供更好的表达力和可维护性。
"""
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from projects.models import Project
from repositories.models import Repository
User = get_user_model
# ============================================================================
# API Client Fixtures
# ============================================================================
@pytest.fixture
def api_client:
 """创建未认证的 API 客户端。"""
 return APIClient
@pytest.fixture
def authenticated_client(api_client, user):
 """创建已认证的 API 客户端。"""
 api_client.force_authenticate(user=user)
 return api_client
# ============================================================================
# User Fixtures
# ============================================================================
@pytest.fixture
def user(db):
 """创建测试用户。"""
 return User.objects.create_user(
 username="testuser",
 email="test@example.com",
 password="testpassword123",
 )
@pytest.fixture
def admin_user(db):
 """创建管理员用户。"""
 return User.objects.create_superuser(
 username="admin",
 email="admin@example.com",
 password="adminpassword123",
 )
# ============================================================================
# Repository Fixtures
# ============================================================================
@pytest.fixture
def repository(db):
 """创建测试仓库。"""
 return Repository.objects.create(
 name="Test Repo",
 git_url="https://github.com/test/repo.git",
 git_platform="github",
 default_branch="main",
 )
@pytest.fixture
def repository_with_credential(db, repository):
 """创建带凭据的测试仓库。"""
 from common.encryption import encrypt_value
 from repositories.models import GitCredential, AuthType
 GitCredential.objects.create(
 repository=repository,
 auth_type=AuthType.ACCESS_TOKEN,
 encrypted_token=encrypt_value("GITHUB_TOKEN_PLACEHOLDER"),
 )
 return repository
# ============================================================================
# Project Fixtures
# ============================================================================
@pytest.fixture
def project(db, repository):
 """创建测试项目（关联仓库）。"""
 proj = Project.objects.create(
 name="Test Project",
 description="A test project",
 feishu_project_key="test-project-key",
 feishu_webhook_token="test-webhook-token",
 )
 proj.repositories.add(repository)
 return proj
@pytest.fixture
def project_without_repo(db):
 """创建无仓库的测试项目。"""
 return Project.objects.create(
 name="Project Without Repo",
 feishu_project_key="no-repo-project-key",
 )
# ============================================================================
# URL Helper Fixtures
# ============================================================================
@pytest.fixture
def urls:
 """提供常用 URL 的辅助 fixture。"""
 from django.urls import reverse
 class URLs:
 # Auth URLs
 login = reverse("login")
 logout = reverse("logout")
 refresh = reverse("refresh")
 me = reverse("me")
 change_password = reverse("change-password")
 # Health
 health = reverse("health")
 # Settings
 settings_list = reverse("settings-list")
 @staticmethod
 def settings_detail(key):
 return reverse("settings-detail", args=[key])
 # Projects
 project_list = reverse("project-list")
 @staticmethod
 def project_detail(project_id):
 return reverse("project-detail", args=[project_id])
 @staticmethod
 def project_repositories(project_id):
 return f"/api/projects/{project_id}/repositories"
 @staticmethod
 def project_link_repository(project_id, repo_id):
 return f"/api/projects/{project_id}/repositories/{repo_id}"
 @staticmethod
 def project_unlink_repository(project_id, repo_id):
 return f"/api/projects/{project_id}/repositories/{repo_id}"
 @staticmethod
 def project_claude_config(project_id):
 return f"/api/projects/{project_id}/claude-config"
 # Repositories
 repository_list = reverse("repository-list")
 @staticmethod
 def repository_detail(repo_id):
 return reverse("repository-detail", args=[repo_id])
 @staticmethod
 def repository_credential(repo_id):
 return reverse("repository-credential", args=[repo_id])
 # Feishu webhooks
 feishu_webhook = "/api/feishu/webhook"
 return URLs
