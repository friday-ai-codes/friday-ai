"""站内信 WebSocket 鉴权中间件：从 cookie 读取 access_token 填充 scope["user"]。

Web 登录走 HttpOnly cookie JWT（见 ``common.authentication.CookieJWTAuthentication``），
而 channels 默认的 ``AuthMiddlewareStack`` 只认 Django session，无法识别 JWT cookie。
本中间件从 WS 握手的 ``cookie`` header 中解析 ``access_token``，用 SimpleJWT 校验后把对应
``accounts.User`` 注入 ``scope["user"]``；校验失败则置为 ``AnonymousUser``，由 consumer 拒绝。
"""

from __future__ import annotations

from http.cookies import SimpleCookie

from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser


@database_sync_to_async
def _get_user(validated_token):
    from rest_framework_simplejwt.settings import api_settings

    from accounts.models import User

    user_id = validated_token.get(api_settings.USER_ID_CLAIM)
    if user_id is None:
        return AnonymousUser()
    try:
        return User.objects.get(**{api_settings.USER_ID_FIELD: user_id})
    except User.DoesNotExist:
        return AnonymousUser()


def _extract_access_token(scope) -> str | None:
    """从 scope headers 的 cookie 中取出 access_token。"""
    headers = dict(scope.get("headers") or [])
    raw_cookie = headers.get(b"cookie")
    if not raw_cookie:
        return None
    cookie = SimpleCookie()
    try:
        cookie.load(raw_cookie.decode("latin-1"))
    except Exception:  # noqa: BLE001 — 非法 cookie 视为未认证
        return None
    morsel = cookie.get("access_token")
    return morsel.value if morsel else None


class JWTCookieAuthMiddleware:
    """从 cookie 解析 JWT access_token，将 scope["user"] 设为认证用户或 AnonymousUser。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "websocket":
            return await self.app(scope, receive, send)

        scope = dict(scope)
        scope["user"] = await self._authenticate(scope)
        return await self.app(scope, receive, send)

    async def _authenticate(self, scope):
        from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
        from rest_framework_simplejwt.tokens import AccessToken

        token = _extract_access_token(scope)
        if not token:
            return AnonymousUser()
        try:
            validated = AccessToken(token)
        except (InvalidToken, TokenError):
            return AnonymousUser()
        return await _get_user(validated)
