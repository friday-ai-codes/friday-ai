"""Tests for project endpoints."""
import pytest
from rest_framework import status
@pytest.mark.django_db
class TestProjectEndpoints:
 """Test project CRUD endpoints."""
 def test_list_projects_empty(self, authenticated_client):
 """Test listing projects when empty."""
 response = authenticated_client.get("/api/projects/")
 assert response.status_code == status.HTTP_200_OK
 assert response.data ==
 def test_list_projects(self, authenticated_client, project):
 """Test listing projects."""
 response = authenticated_client.get("/api/projects/")
 assert response.status_code == status.HTTP_200_OK
 assert len(response.data) == 1
 assert response.data[0]["name"] == "Test Project"
 def test_create_project(self, authenticated_client):
 """Test creating a project."""
 response = authenticated_client.post(
 "/api/projects/",
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
 def test_get_project(self, authenticated_client, project):
 """Test getting a single project."""
 response = authenticated_client.get(f"/api/projects/{project.id}")
 assert response.status_code == status.HTTP_200_OK
 assert response.data["name"] == "Test Project"
 assert response.data["feishu_project_key"] == "test-project-key"
 def test_get_project_not_found(self, authenticated_client):
 """Test getting a nonexistent project."""
 import uuid
 response = authenticated_client.get(f"/api/projects/{uuid.uuid4}")
 assert response.status_code == status.HTTP_404_NOT_FOUND
 def test_update_project(self, authenticated_client, project):
 """Test updating a project."""
 response = authenticated_client.patch(
 f"/api/projects/{project.id}",
 {"name": "Updated Project"},
 format="json",
 )
 assert response.status_code == status.HTTP_200_OK
 assert response.data["name"] == "Updated Project"
 def test_delete_project(self, authenticated_client, project):
 """Test deleting a project."""
 response = authenticated_client.delete(f"/api/projects/{project.id}")
 assert response.status_code == status.HTTP_204_NO_CONTENT
 # Verify deleted
 response = authenticated_client.get(f"/api/projects/{project.id}")
 assert response.status_code == status.HTTP_404_NOT_FOUND
@pytest.mark.django_db
class TestProjectRepositoryAssociation:
 """Test project-repository association endpoints."""
 def test_list_project_repositories(self, authenticated_client, project):
 """Test listing project repositories (project fixture has one repo)."""
 response = authenticated_client.get(f"/api/projects/{project.id}/repositories")
 assert response.status_code == status.HTTP_200_OK
 # Project fixture already has a repository linked
 assert len(response.data) == 1
 assert response.data[0]["name"] == "Test Repo"
 def test_link_repository(self, authenticated_client, project):
 """Test linking a new repository to a project."""
 from projects.models import Repository
 # Create a new repository
 new_repo = Repository.objects.create(
 name="New Repo",
 git_url="https://github.com/test/new-repo.git",
 git_platform="github",
 default_branch="main",
 )
 response = authenticated_client.post(
 f"/api/projects/{project.id}/repositories/{new_repo.id}"
 )
 # Already linked returns 200, new link returns 200 or 201
 assert response.status_code in [status.HTTP_200_OK, status.HTTP_201_CREATED]
 # Verify linked - should have 2 repos now
 response = authenticated_client.get(f"/api/projects/{project.id}/repositories")
 assert len(response.data) == 2
 def test_unlink_repository(self, authenticated_client, project, repository):
 """Test unlinking a repository from a project."""
 # First link
 authenticated_client.post(
 f"/api/projects/{project.id}/repositories/{repository.id}"
 )
 # Then unlink
 response = authenticated_client.delete(
 f"/api/projects/{project.id}/repositories/{repository.id}"
 )
 assert response.status_code == status.HTTP_204_NO_CONTENT
@pytest.mark.django_db
class TestProjectClaudeConfig:
 """Test project Claude configuration endpoints."""
 def test_get_claude_config(self, authenticated_client, project):
 """Test getting Claude configuration."""
 response = authenticated_client.get(f"/api/projects/{project.id}/claude-config")
 assert response.status_code == status.HTTP_200_OK
 assert response.data["has_api_key"] is False
 assert response.data["source"] == "system"
 def test_set_claude_config(self, authenticated_client, project):
 """Test setting Claude configuration."""
 response = authenticated_client.put(
 f"/api/projects/{project.id}/claude-config",
 {"api_key": "sk-test-key-12345", "base_url": "https://api.example.com"},
 format="json",
 )
 assert response.status_code == status.HTTP_200_OK
 assert response.data["has_api_key"] is True
 assert response.data["base_url"] == "https://api.example.com"
 assert response.data["source"] == "project"
 def test_delete_claude_config(self, authenticated_client, project):
 """Test deleting Claude configuration."""
 # First set
 authenticated_client.put(
 f"/api/projects/{project.id}/claude-config",
 {"api_key": "sk-test-key"},
 format="json",
 )
 # Then delete
 response = authenticated_client.delete(f"/api/projects/{project.id}/claude-config")
 assert response.status_code == status.HTTP_204_NO_CONTENT
