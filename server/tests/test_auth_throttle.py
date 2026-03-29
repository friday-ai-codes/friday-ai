"""认证端点速率限制测试。"""
import pytest
from django.core.cache import cache
from rest_framework import status
@pytest.mark.django_db
class TestLoginThrottle:
 """登录端点速率限制测试。"""
 @pytest.fixture(autouse=True)
 def clear_cache(self):
 cache.clear
 yield
 cache.clear
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
 def clear_cache(self):
 cache.clear
 yield
 cache.clear
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
