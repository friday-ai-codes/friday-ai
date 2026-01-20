"""认证端点测试。
使用 pytest + pytest-django 风格，提供更好的表达力和可维护性。
"""
import pytest
from rest_framework import status
# ============================================================================
# 登录测试
# ============================================================================
@pytest.mark.django_db
class TestLogin:
 """登录接口测试。"""
 def test_login_success(self, api_client, user, urls):
 """测试正确的用户名密码可以成功登录。"""
 response = api_client.post(
 urls.login,
 {"username": "testuser", "password": "testpassword123"},
 format="json",
 )
 assert response.status_code == status.HTTP_200_OK
 assert "access_token" in response.data
 assert "user" in response.data
 assert response.data["user"]["username"] == "testuser"
 assert "refresh_token" in response.cookies
 def test_login_invalid_password(self, api_client, user, urls):
 """测试错误密码登录失败。"""
 response = api_client.post(
 urls.login,
 {"username": "testuser", "password": "wrongpassword"},
 format="json",
 )
 assert response.status_code == status.HTTP_400_BAD_REQUEST
 def test_login_nonexistent_user(self, api_client, urls):
 """测试不存在的用户登录失败。"""
 response = api_client.post(
 urls.login,
 {"username": "nouser", "password": "password"},
 format="json",
 )
 assert response.status_code == status.HTTP_400_BAD_REQUEST
 def test_login_missing_fields(self, api_client, user, urls):
 """测试缺少必填字段登录失败。"""
 response = api_client.post(
 urls.login,
 {"username": "testuser"},
 format="json",
 )
 assert response.status_code == status.HTTP_400_BAD_REQUEST
# ============================================================================
# 登出测试
# ============================================================================
@pytest.mark.django_db
class TestLogout:
 """登出接口测试。"""
 def test_logout_success(self, api_client, urls):
 """测试登出成功。"""
 response = api_client.post(urls.logout)
 assert response.status_code == status.HTTP_200_OK
 assert response.data["message"] == "登出成功"
# ============================================================================
# 获取当前用户信息测试
# ============================================================================
@pytest.mark.django_db
class TestMe:
 """获取当前用户信息接口测试。"""
 def test_me_authenticated(self, authenticated_client, user, urls):
 """测试已认证用户可以获取自己的信息。"""
 response = authenticated_client.get(urls.me)
 assert response.status_code == status.HTTP_200_OK
 assert response.data["username"] == "testuser"
 def test_me_unauthenticated(self, api_client, urls):
 """测试未认证用户无法获取用户信息。"""
 response = api_client.get(urls.me)
 assert response.status_code == status.HTTP_401_UNAUTHORIZED
# ============================================================================
# 修改密码测试
# ============================================================================
@pytest.mark.django_db
class TestChangePassword:
 """修改密码接口测试。"""
 def test_change_password_success(self, authenticated_client, user, urls):
 """测试正确的旧密码可以修改密码。"""
 response = authenticated_client.post(
 urls.change_password,
 {"old_password": "testpassword123", "new_password": "newpassword456"},
 format="json",
 )
 assert response.status_code == status.HTTP_200_OK
 assert response.data["message"] == "密码修改成功"
 # 验证新密码生效
 user.refresh_from_db
 assert user.check_password("newpassword456")
 def test_change_password_wrong_old_password(self, authenticated_client, urls):
 """测试错误的旧密码无法修改密码。"""
 response = authenticated_client.post(
 urls.change_password,
 {"old_password": "wrongpassword", "new_password": "newpassword456"},
 format="json",
 )
 assert response.status_code == status.HTTP_400_BAD_REQUEST
 def test_change_password_unauthenticated(self, api_client, urls):
 """测试未认证用户无法修改密码。"""
 response = api_client.post(
 urls.change_password,
 {"old_password": "testpassword123", "new_password": "newpassword456"},
 format="json",
 )
 assert response.status_code == status.HTTP_401_UNAUTHORIZED
# ============================================================================
# 健康检查测试
# ============================================================================
@pytest.mark.django_db
class TestHealthCheck:
 """健康检查接口测试。"""
 def test_health_check_returns_ok(self, api_client, urls):
 """测试健康检查返回正常状态。"""
 response = api_client.get(urls.health)
 assert response.status_code == status.HTTP_200_OK
 assert response.data["status"] == "ok"
 assert response.data["service"] == "friday"
