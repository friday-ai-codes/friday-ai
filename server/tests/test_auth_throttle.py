"""认证端点速率限制测试。
conftest 全局将 throttle THROTTLE_RATES 放宽至 1000/min 以保护其他测试。
本模块通过 fixture 将 THROTTLE_RATES 恢复为严格的 5/min 来验证限速行为。
"""
import pytest
from django.core.cache import cache
from rest_framework import status
@pytest.fixture
def strict_throttle:
 """将 throttle 恢复为严格的 5/min 限速。
 直接修改 THROTTLE_RATES 类变量，因为 SimpleRateThrottle 在 __init__
 时从类变量读取 rate，不会重新查询 settings。
 """
 from accounts.throttles import LoginRateThrottle, RefreshRateThrottle
 strict_rates = {"auth_login": "5/min", "auth_refresh": "5/min"}
 LoginRateThrottle.THROTTLE_RATES = strict_rates
 RefreshRateThrottle.THROTTLE_RATES = strict_rates
 cache.clear
 yield
 cache.clear
@pytest.mark.django_db
class TestLoginThrottle:
 """登录端点速率限制测试。"""
 @pytest.fixture(autouse=True)
 def _setup(self, strict_throttle):
 pass
 def test_allows_within_limit(self, api_client, user, urls):
 """5 次以内登录请求正常通过。"""
 for i in range(5):
 response = api_client.post(
 urls.login,
 {"username": "testuser", "password": "testpassword123"},
 format="json",
 )
 assert response.status_code == status.HTTP_200_OK, f"第 {i+1} 次请求应返回 200"
 def test_blocks_after_limit(self, api_client, user, urls):
 """第 6 次登录请求返回 429。"""
 for _ in range(5):
 api_client.post(
 urls.login,
 {"username": "testuser", "password": "testpassword123"},
 format="json",
 )
 response = api_client.post(
 urls.login,
 {"username": "testuser", "password": "testpassword123"},
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
 f"第 {i+1} 次请求不应返回 429"
 )
 def test_blocks_after_limit(self, api_client, urls):
 """第 6 次刷新请求返回 429。"""
 for _ in range(5):
 api_client.post(urls.refresh, format="json")
 response = api_client.post(urls.refresh, format="json")
 assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
 assert "Retry-After" in response
