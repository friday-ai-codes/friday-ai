"""Tests for repository endpoints."""
import pytest
from rest_framework import status
@pytest.mark.django_db
class TestRepositoryEndpoints:
 """Test repository CRUD endpoints."""
 def test_list_repositories_empty(self, authenticated_client):
 """Test listing repositories when empty."""
 response = authenticated_client.get("/api/repositories/")
 assert response.status_code == status.HTTP_200_OK
 assert response.data ==
 def test_list_repositories(self, authenticated_client, repository):
 """Test listing repositories."""
 response = authenticated_client.get("/api/repositories/")
 assert response.status_code == status.HTTP_200_OK
 assert len(response.data) == 1
 assert response.data[0]["name"] == "Test Repo"
 def test_create_repository(self, authenticated_client):
 """Test creating a repository with credential."""
 response = authenticated_client.post(
 "/api/repositories/",
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
 def test_create_repository_empty_token(self, authenticated_client):
 """Test creating a repository with empty token."""
 response = authenticated_client.post(
 "/api/repositories/",
 {
 "name": "No Token Repo",
 "git_url": "https://github.com/test/repo.git",
 "access_token": " ",
 },
 format="json",
 )
 assert response.status_code == status.HTTP_400_BAD_REQUEST
 def test_get_repository(self, authenticated_client, repository):
 """Test getting a single repository."""
 response = authenticated_client.get(f"/api/repositories/{repository.id}")
 assert response.status_code == status.HTTP_200_OK
 assert response.data["name"] == "Test Repo"
 assert "projects" in response.data
 def test_update_repository(self, authenticated_client, repository):
 """Test updating a repository."""
 response = authenticated_client.patch(
 f"/api/repositories/{repository.id}",
 {"name": "Updated Repo"},
 format="json",
 )
 assert response.status_code == status.HTTP_200_OK
 assert response.data["name"] == "Updated Repo"
 def test_delete_repository(self, authenticated_client, repository):
 """Test deleting a repository."""
 response = authenticated_client.delete(f"/api/repositories/{repository.id}")
 assert response.status_code == status.HTTP_204_NO_CONTENT
@pytest.mark.django_db
class TestRepositoryCredentials:
 """Test repository credential endpoints."""
 def test_get_credential(self, authenticated_client):
 """Test getting credential for repository."""
 # Create repo with credential
 create_response = authenticated_client.post(
 "/api/repositories/",
 {
 "name": "Repo With Cred",
 "git_url": "https://github.com/test/repo.git",
 "access_token": "test_token",
 },
 format="json",
 )
 repo_id = create_response.data["id"]
 response = authenticated_client.get(f"/api/repositories/{repo_id}/credential")
 assert response.status_code == status.HTTP_200_OK
 assert response.data["has_access_token"] is True
 assert response.data["auth_type"] == "access_token"
 def test_get_credential_not_found(self, authenticated_client, repository):
 """Test getting nonexistent credential."""
 response = authenticated_client.get(f"/api/repositories/{repository.id}/credential")
 assert response.status_code == status.HTTP_404_NOT_FOUND
 def test_delete_credential(self, authenticated_client):
 """Test deleting credential."""
 # Create repo with credential
 create_response = authenticated_client.post(
 "/api/repositories/",
 {
 "name": "Repo To Delete Cred",
 "git_url": "https://github.com/test/repo.git",
 "access_token": "test_token",
 },
 format="json",
 )
 repo_id = create_response.data["id"]
 response = authenticated_client.delete(f"/api/repositories/{repo_id}/credential")
 assert response.status_code == status.HTTP_204_NO_CONTENT
 # Verify deleted
 response = authenticated_client.get(f"/api/repositories/{repo_id}/credential")
 assert response.status_code == status.HTTP_404_NOT_FOUND
