"""Runner Token 自定义认证。"""

from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from .models import Runner, hash_token


class RunnerTokenAuthentication(BaseAuthentication):
    """通过 Bearer token 认证 Runner。

    返回 (None, runner) — request.user 为 None，request.auth 为 Runner 实例。
    """

    def authenticate(self, request):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith("Bearer "):
            return None

        token = auth_header[7:]
        if not token:
            return None

        token_hashed = hash_token(token)
        try:
            runner = Runner.objects.get(token_hash=token_hashed, is_active=True)
        except Runner.DoesNotExist:
            raise AuthenticationFailed("无效的 Runner Token")

        return (None, runner)
