"""Test configuration and fixtures for Django REST Framework tests."""
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
User = get_user_model
@pytest.fixture
def api_client:
 """Create an unauthenticated API client."""
 return APIClient
@pytest.fixture
def user(db):
 """Create a test user."""
 return User.objects.create_user(
 username="testuser",
 email="test@example.com",
 password="testpassword123",
 )
@pytest.fixture
def authenticated_client(api_client, user):
 """Create an authenticated API client."""
 api_client.force_authenticate(user=user)
 return api_client
@pytest.fixture
def repository(db):
 """Create a test repository."""
 from projects.models import Repository
 return Repository.objects.create(
 name="Test Repo",
 git_url="https://github.com/test/repo.git",
 git_platform="github",
 default_branch="main",
 )
@pytest.fixture
def project(db, repository):
 """Create a test project with associated repository."""
 from projects.models import Project
 project = Project.objects.create(
 name="Test Project",
 description="A test project",
 feishu_project_key="test-project-key",
 feishu_webhook_token="test-webhook-token",
 )
 project.repositories.add(repository)
 return project
@pytest.fixture
def task(db, project):
 """Create a test task."""
 from tasks.models import Task
 return Task.objects.create(
 project=project,
 title="Test Task",
 description="A test task description",
 work_item_id="12345",
 status="pending",
 )
