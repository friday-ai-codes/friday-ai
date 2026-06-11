"""认证端点速率限制测试。

conftest 全局将 throttle THROTTLE_RATES 放宽至 1000/min 以保护其他测试。
本模块通过 fixture 将 THROTTLE_RATES 恢复为严格限速来验证限速行为。

登录限流语义（防爆破且不误伤共享出口 IP 的团队）：
- auth_login 按「IP+用户名」计数，登录成功即清零 → 只拦截对单一账号的连续失败；
- auth_login_ip 按纯 IP 计数，作为防批量扫描的宽松兜底；
- login / refresh 的 cache key 带 scope 前缀，互不串数。
"""

import pytest
from django.core.cache import cache
from rest_framework import status

WRONG = {"username": "testuser", "password": "wrong-password"}
CORRECT = {"username": "testuser", "password": "testpassword123"}


@pytest.fixture()
def strict_throttle():
    """将 throttle 恢复为严格限速。

    直接修改 THROTTLE_RATES 类变量，因为 SimpleRateThrottle 在 __init__
    时从类变量读取 rate，不会重新查询 settings。
    auth_login_ip 保持宽松（100/min），避免干扰按用户名计数的测试。
    """
    from accounts.throttles import (
        LoginIPRateThrottle,
        LoginRateThrottle,
        RefreshRateThrottle,
    )

    strict_rates = {
        "auth_login": "5/min",
        "auth_login_ip": "100/min",
        "auth_refresh": "5/min",
    }
    for cls in (LoginRateThrottle, LoginIPRateThrottle, RefreshRateThrottle):
        cls.THROTTLE_RATES = strict_rates
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
class TestLoginThrottle:
    """登录端点「IP+用户名」级速率限制测试。"""

    @pytest.fixture(autouse=True)
    def _setup(self, strict_throttle):
        pass

    def test_failed_attempts_blocked_after_limit(self, api_client, user, urls):
        """对同一账号连续失败 5 次后，第 6 次请求返回 429（即使密码正确）。"""
        for _ in range(5):
            response = api_client.post(urls.login, WRONG, format="json")
            assert response.status_code == status.HTTP_400_BAD_REQUEST

        response = api_client.post(urls.login, CORRECT, format="json")
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert "Retry-After" in response

    def test_successful_logins_not_throttled(self, api_client, user, urls):
        """连续成功登录不触发限速（成功即清零，正常切换用户不受影响）。"""
        for i in range(8):
            response = api_client.post(urls.login, CORRECT, format="json")
            assert response.status_code == status.HTTP_200_OK, f"第 {i + 1} 次成功登录不应被限速"

    def test_success_resets_failure_count(self, api_client, user, urls):
        """登录成功后清空失败计数，之后的少量失败不会被拦。"""
        for _ in range(4):
            api_client.post(urls.login, WRONG, format="json")

        response = api_client.post(urls.login, CORRECT, format="json")
        assert response.status_code == status.HTTP_200_OK

        # 计数已清零：再失败 4 次仍不触发 429
        for i in range(4):
            response = api_client.post(urls.login, WRONG, format="json")
            assert response.status_code == status.HTTP_400_BAD_REQUEST, (
                f"清零后第 {i + 1} 次失败不应返回 429"
            )

    def test_throttle_isolated_per_username(self, api_client, user, admin_user, urls):
        """限流桶按用户名隔离：A 账号被爆破不影响同 IP 下 B 账号登录。"""
        for _ in range(5):
            api_client.post(urls.login, WRONG, format="json")

        # testuser 桶已满
        response = api_client.post(urls.login, CORRECT, format="json")
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS

        # 同一 IP 的 admin 账号不受影响
        response = api_client.post(
            urls.login,
            {"username": "admin", "password": "adminpassword123"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK

    def test_refresh_does_not_consume_login_quota(self, api_client, user, urls):
        """回归测试：login / refresh 桶不共用 cache key。

        旧实现的 cache key 是裸 IP（无 scope 前缀），页面刷新触发的
        token refresh 会消耗登录配额，导致"切换用户就 429"。
        """
        for _ in range(5):
            api_client.post(urls.refresh, format="json")

        response = api_client.post(urls.login, CORRECT, format="json")
        assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestLoginIPThrottle:
    """登录端点纯 IP 维度兜底限速测试。"""

    @pytest.fixture(autouse=True)
    def _setup(self, strict_throttle):
        from accounts.throttles import LoginIPRateThrottle

        # 收紧 IP 兜底以便测试（每个用户名的失败都 <5 次，不触发 auth_login）
        LoginIPRateThrottle.THROTTLE_RATES = {
            **LoginIPRateThrottle.THROTTLE_RATES,
            "auth_login_ip": "5/min",
        }
        cache.clear()

    def test_blocks_cross_username_scanning(self, api_client, db, urls):
        """单 IP 批量扫描多个不同账号时被兜底限速拦截。"""
        for i in range(5):
            response = api_client.post(
                urls.login,
                {"username": f"scan-user-{i}", "password": "x"},
                format="json",
            )
            assert response.status_code != status.HTTP_429_TOO_MANY_REQUESTS

        response = api_client.post(
            urls.login,
            {"username": "scan-user-final", "password": "x"},
            format="json",
        )
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert "Retry-After" in response


@pytest.mark.django_db
class TestRefreshThrottle:
    """Token 刷新端点速率限制测试。"""

    @pytest.fixture(autouse=True)
    def _setup(self, strict_throttle):
        pass

    def test_allows_within_limit(self, api_client, urls):
        """5 次以内刷新请求不触发限速（返回 401 因无 cookie，但不是 429）。"""
        for i in range(5):
            response = api_client.post(urls.refresh, format="json")
            assert response.status_code != status.HTTP_429_TOO_MANY_REQUESTS, (
                f"第 {i + 1} 次请求不应返回 429"
            )

    def test_blocks_after_limit(self, api_client, urls):
        """第 6 次刷新请求返回 429。"""
        for _ in range(5):
            api_client.post(urls.refresh, format="json")

        response = api_client.post(urls.refresh, format="json")
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert "Retry-After" in response
