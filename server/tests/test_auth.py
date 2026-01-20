"""Tests for authentication endpoints."""
import pytest
from django.urls import reverse
from rest_framework import status
@pytest.mark.django_db
class TestAuthEndpoints:
 """Test authentication endpoints."""
 def test_login_success(self, api_client, user):
 """Test successful login."""
 response = api_client.post(
 "/api/auth/login",
 {"username": "testuser", "password": "testpassword123"},
 format="json",
 )
 assert response.status_code == status.HTTP_200_OK
 assert "access_token" in response.data
 assert "user" in response.data
 assert response.data["user"]["username"] == "testuser"
 # Check refresh token cookie is set
 assert "refresh_token" in response.cookies
 def test_login_invalid_credentials(self, api_client, user):
 """Test login with invalid credentials."""
 response = api_client.post(
 "/api/auth/login",
 {"username": "testuser", "password": "wrongpassword"},
 format="json",
 )
 assert response.status_code == status.HTTP_400_BAD_REQUEST
 def test_login_nonexistent_user(self, api_client):
 """Test login with nonexistent user."""
 response = api_client.post(
 "/api/auth/login",
 {"username": "nouser", "password": "password"},
 format="json",
 )
 assert response.status_code == status.HTTP_400_BAD_REQUEST
 def test_logout(self, api_client):
 """Test logout."""
 response = api_client.post("/api/auth/logout")
 assert response.status_code == status.HTTP_200_OK
 assert response.data["message"] == "登出成功"
 def test_me_authenticated(self, authenticated_client, user):
 """Test getting current user info when authenticated."""
 response = authenticated_client.get("/api/auth/me")
 assert response.status_code == status.HTTP_200_OK
 assert response.data["username"] == "testuser"
 def test_me_unauthenticated(self, api_client):
 """Test getting current user info when not authenticated."""
 response = api_client.get("/api/auth/me")
 assert response.status_code == status.HTTP_401_UNAUTHORIZED
 def test_change_password_success(self, authenticated_client, user):
 """Test changing password successfully."""
 response = authenticated_client.post(
 "/api/auth/change-password",
 {"old_password": "testpassword123", "new_password": "newpassword456"},
 format="json",
 )
 assert response.status_code == status.HTTP_200_OK
 assert response.data["message"] == "密码修改成功"
 # Verify new password works
 user.refresh_from_db
 assert user.check_password("newpassword456")
 def test_change_password_wrong_old_password(self, authenticated_client):
 """Test changing password with wrong old password."""
 response = authenticated_client.post(
 "/api/auth/change-password",
 {"old_password": "wrongpassword", "new_password": "newpassword456"},
 format="json",
 )
 assert response.status_code == status.HTTP_400_BAD_REQUEST
@pytest.mark.django_db
class TestHealthCheck:
 """Test health check endpoint."""
 def test_health_check(self, api_client):
 """Test health check returns ok."""
 response = api_client.get("/health")
 assert response.status_code == status.HTTP_200_OK
 assert response.data["status"] == "ok"
 assert response.data["service"] == "friday"
