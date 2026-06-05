"""认证端点 IP 级速率限制。"""

from rest_framework.request import Request
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView


class LoginRateThrottle(SimpleRateThrottle):
    """登录端点 IP 级速率限制。"""

    scope = "auth_login"

    def get_cache_key(self, request: Request, view: APIView) -> str | None:
        return self.get_ident(request)


class RefreshRateThrottle(SimpleRateThrottle):
    """Token 刷新端点 IP 级速率限制。"""

    scope = "auth_refresh"

    def get_cache_key(self, request: Request, view: APIView) -> str | None:
        return self.get_ident(request)
