"""Runner auth boundary tests for verify/unregister endpoints."""
from __future__ import annotations
import pytest
from rest_framework import status
from runners.models import Runner, hash_token
@pytest.fixture
def runner_token_pair(db):
 token = "runner-secret-token"
 runner = Runner.objects.create(
 name="test-runner",
 token_hash=hash_token(token),
 token_prefix=token[:8],
 scope=Runner.Scope.GLOBAL,
 concurrent=1,
 status=Runner.Status.ONLINE,
 is_active=True,
 )
 return runner, token
@pytest.mark.django_db
def test_runner_verify_missing_token_returns_403(api_client):
 response = api_client.get("/api/runners/verify/")
 assert response.status_code == status.HTTP_403_FORBIDDEN
@pytest.mark.django_db
def test_runner_verify_invalid_token_returns_auth_error(api_client):
 api_client.credentials(HTTP_AUTHORIZATION="Bearer invalid-token")
 response = api_client.get("/api/runners/verify/")
 assert response.status_code in (
 status.HTTP_401_UNAUTHORIZED,
 status.HTTP_403_FORBIDDEN,
 )
@pytest.mark.django_db
def test_runner_verify_valid_token_returns_200(api_client, runner_token_pair):
 runner, token = runner_token_pair
 api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
 response = api_client.get("/api/runners/verify/")
 assert response.status_code == status.HTTP_200_OK
 assert response.data["id"] == str(runner.id)
@pytest.mark.django_db
def test_runner_unregister_missing_token_returns_403(api_client):
 response = api_client.delete("/api/runners/unregister/")
 assert response.status_code == status.HTTP_403_FORBIDDEN
@pytest.mark.django_db
def test_runner_unregister_invalid_token_returns_auth_error(api_client):
 api_client.credentials(HTTP_AUTHORIZATION="Bearer invalid-token")
 response = api_client.delete("/api/runners/unregister/")
 assert response.status_code in (
 status.HTTP_401_UNAUTHORIZED,
 status.HTTP_403_FORBIDDEN,
 )
@pytest.mark.django_db
def test_runner_unregister_valid_token_returns_204(api_client, runner_token_pair):
 runner, token = runner_token_pair
 api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
 response = api_client.delete("/api/runners/unregister/")
 runner.refresh_from_db
 assert response.status_code == status.HTTP_204_NO_CONTENT
 assert runner.is_active is False
