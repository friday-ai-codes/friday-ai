"""pytest-django 测试配置和 fixtures。
使用 pytest + pytest-django 风格，提供更好的表达力和可维护性。
"""
# adrf 0.1.12 兼容性补丁（需在 Django 加载前执行）
from core.patches import patch_asyncio_iscoroutinefunction
patch_asyncio_iscoroutinefunction
import pytest # noqa: E402
from django.contrib.auth import get_user_model # noqa: E402
from rest_framework.test import APIClient # noqa: E402
from permissions.models import ProjectMembership, ProjectRole # noqa: E402
from projects.models import Project # noqa: E402
from repositories.models import Repository # noqa: E402
# Register E2E mock fixtures for auto-discovery
pytest_plugins = [
 "tests.e2e.fixtures.mock_services",
]
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
 from repositories.models import AuthType, GitCredential
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
 return f"/api/projects/{project_id}/repositories/"
 @staticmethod
 def project_link_repository(project_id, repo_id):
 return f"/api/projects/{project_id}/repositories/{repo_id}/"
 @staticmethod
 def project_unlink_repository(project_id, repo_id):
 return f"/api/projects/{project_id}/repositories/{repo_id}/"
 @staticmethod
 def project_claude_config(project_id):
 return f"/api/projects/{project_id}/claude-config/"
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
# ============================================================================
# Multi-Role User Fixtures (Phase: 权限引擎)
# ============================================================================
@pytest.fixture
def member_user(db):
 """创建 member 角色测试用户。"""
 return User.objects.create_user(
 username="member_user",
 email="member@example.com",
 password="memberpassword123",
 )
@pytest.fixture
def viewer_user(db):
 """创建 viewer 角色测试用户。"""
 return User.objects.create_user(
 username="viewer_user",
 email="viewer@example.com",
 password="viewerpassword123",
 )
@pytest.fixture
def other_user(db):
 """创建非任何项目成员的用户。"""
 return User.objects.create_user(
 username="other_user",
 email="other@example.com",
 password="otherpassword123",
 )
@pytest.fixture
def second_project(db):
 """创建第二个测试项目。"""
 return Project.objects.create(
 name="Second Project",
 description="A second test project",
 feishu_project_key="second-project-key",
 )
@pytest.fixture
def project_memberships(db, project, user, member_user, viewer_user):
 """创建项目成员关系。
 - user → project admin
 - member_user → project member
 - viewer_user → project viewer
 - admin_user 是 superuser，不需要 membership
 """
 admin_membership = ProjectMembership.objects.create(
 user=user, project=project, role=ProjectRole.ADMIN
 )
 member_membership = ProjectMembership.objects.create(
 user=member_user, project=project, role=ProjectRole.MEMBER
 )
 viewer_membership = ProjectMembership.objects.create(
 user=viewer_user, project=project, role=ProjectRole.VIEWER
 )
 return {
 "admin": admin_membership,
 "member": member_membership,
 "viewer": viewer_membership,
 }
@pytest.fixture
def authenticated_member_client(api_client, member_user):
 """创建 member 角色已认证客户端。"""
 client = APIClient
 client.force_authenticate(user=member_user)
 return client
@pytest.fixture
def authenticated_viewer_client(api_client, viewer_user):
 """创建 viewer 角色已认证客户端。"""
 client = APIClient
 client.force_authenticate(user=viewer_user)
 return client
@pytest.fixture
def authenticated_admin_client(api_client, admin_user):
 """创建 superuser 已认证客户端。"""
 client = APIClient
 client.force_authenticate(user=admin_user)
 return client
