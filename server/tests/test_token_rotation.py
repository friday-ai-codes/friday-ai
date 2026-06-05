"""JWT Token 旋转与废弃测试。

验证 Refresh Token 每次刷新后签发新 Token 并废弃旧 Token，
旧 Token 无法重复使用（work item）。
"""

import pytest
from rest_framework import status


@pytest.mark.django_db
class TestTokenRotation:
    """Refresh Token 旋转机制测试。"""

    def _login(self, api_client, urls):
        """辅助方法：登录并返回 (access_token, refresh_cookie_value)。"""
        response = api_client.post(
            urls.login,
            {"username": "testuser", "password": "testpassword123"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        access_token = response.data["access_token"]
        refresh_cookie = response.cookies["refresh_token"].value
        return access_token, refresh_cookie

    def test_refresh_returns_new_tokens(self, api_client, user, urls):
        """刷新后返回新的 access_token，响应 Cookie 中有新的 refresh_token。"""
        _, refresh_cookie = self._login(api_client, urls)

        # 刷新 Token
        api_client.cookies["refresh_token"] = refresh_cookie
        response = api_client.post(urls.refresh)

        assert response.status_code == status.HTTP_200_OK
        assert "access_token" in response.data
        assert "refresh_token" in response.cookies

    def test_old_refresh_token_rejected_after_rotation(self, api_client, user, urls):
        """使用已刷新过的旧 refresh_token 再次刷新，返回 401。"""
        _, old_refresh = self._login(api_client, urls)

        # 第一次刷新成功
        api_client.cookies["refresh_token"] = old_refresh
        response = api_client.post(urls.refresh)
        assert response.status_code == status.HTTP_200_OK

        # 用旧 token 再次刷新应该失败（已被 blacklist）
        api_client.cookies["refresh_token"] = old_refresh
        response = api_client.post(urls.refresh)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_new_refresh_token_works(self, api_client, user, urls):
        """使用新 refresh_token 可以成功刷新，获取新的 access_token。"""
        _, old_refresh = self._login(api_client, urls)

        # 第一次刷新获取新 refresh token
        api_client.cookies["refresh_token"] = old_refresh
        response = api_client.post(urls.refresh)
        assert response.status_code == status.HTTP_200_OK
        new_refresh = response.cookies["refresh_token"].value

        # 用新 token 刷新应该成功
        api_client.cookies["refresh_token"] = new_refresh
        response = api_client.post(urls.refresh)
        assert response.status_code == status.HTTP_200_OK
        assert "access_token" in response.data

    def test_refresh_without_cookie_returns_401(self, api_client, urls):
        """未携带 refresh_token Cookie 时返回 401。"""
        response = api_client.post(urls.refresh)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_refresh_with_invalid_token_returns_401(self, api_client, urls):
        """携带无效 refresh_token 时返回 401 并清除 Cookie。"""
        api_client.cookies["refresh_token"] = "invalid-token-value"
        response = api_client.post(urls.refresh)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_token_rotation_chain(self, api_client, user, urls):
        """验证连续多次旋转的链路：每次刷新后旧 token 不可用，新 token 可用。"""
        _, current_refresh = self._login(api_client, urls)

        for i in range(3):
            # 用当前 token 刷新
            api_client.cookies["refresh_token"] = current_refresh
            response = api_client.post(urls.refresh)
            assert response.status_code == status.HTTP_200_OK, f"第 {i + 1} 次刷新失败"

            old_refresh = current_refresh
            current_refresh = response.cookies["refresh_token"].value

            # 旧 token 不可用
            api_client.cookies["refresh_token"] = old_refresh
            response = api_client.post(urls.refresh)
            assert response.status_code == status.HTTP_401_UNAUTHORIZED, (
                f"第 {i + 1} 次旋转后旧 token 仍可用"
            )

    def test_refreshed_access_token_works_for_api(self, api_client, user, urls):
        """刷新后的 access_token 可以正常访问受保护的 API。"""
        _, refresh_cookie = self._login(api_client, urls)

        # 刷新获取新 access token
        api_client.cookies["refresh_token"] = refresh_cookie
        response = api_client.post(urls.refresh)
        assert response.status_code == status.HTTP_200_OK
        new_access_token = response.data["access_token"]

        # 用新 access token 访问 /me
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {new_access_token}")
        response = api_client.get(urls.me)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["username"] == "testuser"
