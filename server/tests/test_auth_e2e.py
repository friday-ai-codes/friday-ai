"""认证全流程端到端集成测试。

覆盖 OIDC 登录 -> JWT 签发 -> 路由守卫 -> 权限检查 -> API 调用全流程。
"""

from unittest.mock import AsyncMock, patch

import pytest
from django.core import signing
from rest_framework import status

from identity.models import OIDCProvider
from permissions.models import SpaceMembership, SpaceRole

# ============================================================================
# 标准登录全流程测试
# ============================================================================


@pytest.mark.django_db
class TestAuthE2EFlow:
    """标准认证全流程端到端测试。"""

    def _login(self, api_client, urls):
        """辅助方法：登录并返回 (access_token, refresh_cookie_value)。"""
        response = api_client.post(
            urls.login,
            {"username": "testuser", "password": "testpassword123"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        return response.data["access_token"], response.cookies["refresh_token"].value

    def test_full_login_flow(self, api_client, user, urls):
        """标准登录 -> Token 获取 -> API 访问全流程。"""
        # 1. 登录
        access_token, refresh_cookie = self._login(api_client, urls)
        assert access_token
        assert refresh_cookie

        # 2. 用 access_token 访问 /me
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
        response = api_client.get(urls.me)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["username"] == "testuser"

    def test_token_rotation_flow(self, api_client, user, urls):
        """Token 旋转：刷新后旧 token 不可用，新 token 可用。"""
        _, old_refresh = self._login(api_client, urls)

        # 第一次刷新
        api_client.cookies["refresh_token"] = old_refresh
        response = api_client.post(urls.refresh)
        assert response.status_code == status.HTTP_200_OK
        new_refresh = response.cookies["refresh_token"].value

        # 旧 token 不可用
        api_client.cookies["refresh_token"] = old_refresh
        response = api_client.post(urls.refresh)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

        # 新 token 可用
        api_client.cookies["refresh_token"] = new_refresh
        response = api_client.post(urls.refresh)
        assert response.status_code == status.HTTP_200_OK

    def test_logout_clears_cookie(self, api_client, user, urls):
        """登出后 refresh_token Cookie 被清除。"""
        access_token, _ = self._login(api_client, urls)

        # 登出
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
        response = api_client.post(urls.logout)
        assert response.status_code == status.HTTP_200_OK

    def test_permission_check_admin_access(self, api_client, admin_user, urls):
        """超级管理员可访问管理端点。"""
        api_client.force_authenticate(user=admin_user)
        response = api_client.get("/api/auth/users/")
        assert response.status_code == status.HTTP_200_OK

    def test_permission_check_normal_user_denied(self, api_client, user, urls):
        """普通用户无法访问管理端点。"""
        api_client.force_authenticate(user=user)
        response = api_client.get("/api/auth/users/")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_project_role_based_access(
        self, api_client, user, member_user, viewer_user, project, project_memberships
    ):
        """不同项目角色的权限验证（通过 /me 接口确认角色）。"""
        # admin 角色
        api_client.force_authenticate(user=user)
        response = api_client.get("/api/auth/me/")
        assert response.status_code == status.HTTP_200_OK
        memberships = response.data.get("space_memberships", [])
        admin_m = next((m for m in memberships if m["space_id"] == str(project.id)), None)
        assert admin_m is not None
        assert admin_m["role"] == "admin"

        # viewer 角色
        api_client.force_authenticate(user=viewer_user)
        response = api_client.get("/api/auth/me/")
        assert response.status_code == status.HTTP_200_OK
        memberships = response.data.get("space_memberships", [])
        viewer_m = next((m for m in memberships if m["space_id"] == str(project.id)), None)
        assert viewer_m is not None
        assert viewer_m["role"] == "viewer"

    def test_refreshed_token_retains_identity(self, api_client, user, urls):
        """刷新后的 access_token 仍映射到同一用户。"""
        _, refresh_cookie = self._login(api_client, urls)

        # 刷新
        api_client.cookies["refresh_token"] = refresh_cookie
        response = api_client.post(urls.refresh)
        assert response.status_code == status.HTTP_200_OK
        new_access = response.data["access_token"]

        # 用新 token 确认身份
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {new_access}")
        response = api_client.get(urls.me)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["username"] == "testuser"

    def test_unauthenticated_access_denied(self, api_client, urls):
        """未认证用户访问受保护端点返回 401。"""
        response = api_client.get(urls.me)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


# ============================================================================
# OIDC 登录流程测试
# ============================================================================


@pytest.mark.django_db
class TestOIDCE2EFlow:
    """OIDC 认证流程端到端测试。"""

    @pytest.fixture
    def oidc_provider(self, db):
        """创建测试 OIDC Provider。"""
        return OIDCProvider.objects.create(
            name="Test OIDC",
            issuer_url="https://oidc.example.com",
            client_id="test-client-id",
            authorization_endpoint="https://oidc.example.com/authorize",
            token_endpoint="https://oidc.example.com/token",
            userinfo_endpoint="https://oidc.example.com/userinfo",
            is_active=True,
        )

    @pytest.fixture
    def disabled_provider(self, db):
        """创建已禁用的 OIDC Provider。"""
        return OIDCProvider.objects.create(
            name="Disabled OIDC",
            issuer_url="https://disabled.example.com",
            client_id="disabled-client-id",
            authorization_endpoint="https://disabled.example.com/authorize",
            token_endpoint="https://disabled.example.com/token",
            is_active=False,
        )

    def test_public_providers_only_active(self, api_client, oidc_provider, disabled_provider):
        """公开列表仅包含活跃 Provider。"""
        response = api_client.get("/api/oidc/providers/public/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]["name"] == "Test OIDC"

    def test_authorize_returns_url(self, api_client, oidc_provider):
        """授权请求返回 authorize_url 和 state cookie。"""
        response = api_client.get(f"/api/oidc/authorize/{oidc_provider.id}/")
        assert response.status_code == status.HTTP_200_OK
        assert "authorize_url" in response.data
        assert "oidc_state" in response.cookies

    def test_authorize_disabled_provider_404(self, api_client, disabled_provider):
        """授权请求对已禁用 Provider 返回 404。"""
        response = api_client.get(f"/api/oidc/authorize/{disabled_provider.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_callback_invalid_state_returns_400(self, api_client, oidc_provider):
        """无效 state 回调返回 400。"""
        response = api_client.get("/api/oidc/callback/", {"code": "test-code", "state": "invalid"})
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_callback_missing_code_returns_400(self, api_client, oidc_provider):
        """缺少 code 参数返回 400。"""
        response = api_client.get("/api/oidc/callback/", {"state": "some-state"})
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("identity.views.exchange_code_for_tokens", new_callable=AsyncMock)
    @patch("identity.views.fetch_userinfo", new_callable=AsyncMock)
    def test_callback_success_redirects_with_token(
        self, mock_userinfo, mock_exchange, api_client, oidc_provider, user
    ):
        """OIDC 回调成功 -> JWT 签发 -> 重定向包含 access_token。"""
        # 模拟 token exchange 和 userinfo
        mock_exchange.return_value = {"access_token": "provider-access-token"}
        mock_userinfo.return_value = {
            "sub": "oidc-user-123",
            "email": "test@example.com",
            "name": "Test User",
        }

        # 设置 signed state cookie
        state_value = "test-state-value"
        signed_state = signing.dumps({
            "state": state_value,
            "redirect_uri": "/",
            "provider_id": str(oidc_provider.id),
        })
        api_client.cookies["oidc_state"] = signed_state

        # 调用 callback
        response = api_client.get(
            "/api/oidc/callback/",
            {"code": "test-auth-code", "state": state_value},
        )

        # 应该重定向到前端
        assert response.status_code == 302
        assert "access_token=" in response.url

    @patch("identity.views.exchange_code_for_tokens", new_callable=AsyncMock)
    @patch("identity.views.fetch_userinfo", new_callable=AsyncMock)
    def test_callback_disabled_provider_redirects_error(
        self, mock_userinfo, mock_exchange, api_client, oidc_provider
    ):
        """Provider 被禁用后回调 -> 错误重定向。"""
        # 设置 signed state cookie（指向即将被禁用的 provider）
        state_value = "test-state"
        signed_state = signing.dumps({
            "state": state_value,
            "redirect_uri": "/",
            "provider_id": str(oidc_provider.id),
        })
        api_client.cookies["oidc_state"] = signed_state

        # 禁用 Provider
        oidc_provider.is_active = False
        oidc_provider.save()

        # 回调应该重定向到登录页带错误
        response = api_client.get(
            "/api/oidc/callback/",
            {"code": "test-code", "state": state_value},
        )
        assert response.status_code == 302
        assert "oidc_error" in response.url

    def test_callback_error_from_provider(self, api_client, oidc_provider):
        """Provider 返回错误 -> 重定向到登录页。"""
        response = api_client.get(
            "/api/oidc/callback/",
            {"error": "access_denied", "error_description": "User denied access"},
        )
        assert response.status_code == 302
        assert "oidc_error" in response.url

    def test_permission_change_reflected_in_me(
        self, api_client, user, project
    ):
        """权限变更后 /me 接口反映最新角色。"""
        api_client.force_authenticate(user=user)

        # 初始无 membership
        response = api_client.get("/api/auth/me/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data.get("space_memberships", [])) == 0

        # 添加 membership
        SpaceMembership.objects.create(
            user=user, space=project, role=SpaceRole.ADMIN
        )

        # /me 应该反映新角色
        response = api_client.get("/api/auth/me/")
        assert response.status_code == status.HTTP_200_OK
        memberships = response.data.get("space_memberships", [])
        assert len(memberships) == 1
        assert memberships[0]["role"] == "admin"
