"""审计上下文 ASGI 中间件 -- 从 HTTP 请求中提取 actor 信息并注入 contextvars。

遵循 Django ASGI 中间件签名 ``(app) -> async __call__(scope, receive, send)``，
与 ``runners/middleware.py`` 和 ``core/middleware.py`` 模式一致。

注册位置：``MIDDLEWARE`` 列表中 ``AuthenticationMiddleware`` 之后。
Django 的 ``AuthenticationMiddleware`` 在 scope 中填充 ``user`` 和 ``auth``，
本中间件在此基础上区分 JWT / PAT / 未认证。
"""

from __future__ import annotations

from typing import Any, Callable

import structlog

from .context import AuditActor, reset_current_actor, set_current_actor

logger = structlog.get_logger("audit")

# Sentinel object for "no token was set" (avoids catching unrelated LookupError).
_NO_TOKEN = object()


class AuditContextMiddleware:
    """从 HTTP 请求 scope 提取 actor，设置到 contextvars。

    - JWT 认证：``scope["user"]`` 为已认证 User 实例，``scope["auth"]`` 不是 AccessToken
    - PAT 认证：``scope["auth"]`` 为 AccessToken 实例（有 ``token_hash`` 属性）
    - 未认证：``scope["user"]`` 为 AnonymousUser 或 ``is_authenticated=False``

    中间件在 ``finally`` 块中清理 contextvar，确保异常时也不泄漏。
    """

    def __init__(self, app: Callable[..., Any]) -> None:
        self.app = app

    async def __call__(
        self, scope: dict[str, Any], receive: Callable, send: Callable
    ) -> Any:
        # 仅处理 HTTP 请求（跳过 WebSocket / lifespan 等）
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)

        token = _NO_TOKEN
        try:
            actor = self._extract_actor(scope)
            token = set_current_actor(actor)
            return await self.app(scope, receive, send)
        finally:
            if token is not _NO_TOKEN:
                reset_current_actor(token)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _extract_actor(self, scope: dict[str, Any]) -> AuditActor:
        """从 scope 提取 actor 信息。"""
        user = scope.get("user")
        auth = scope.get("auth")
        ip_address = self._extract_ip(scope)
        request_id = self._extract_request_id(scope)

        # PAT 认证：auth 对象有 token_hash 属性
        if auth is not None and hasattr(auth, "token_hash"):
            return AuditActor(
                actor_type="pat",
                actor_id=str(auth.token_hash),
                actor_display=getattr(auth, "name", "") or "",
                ip_address=ip_address,
                request_id=request_id,
            )

        # JWT 认证：user 已认证
        if user is not None and getattr(user, "is_authenticated", False):
            return AuditActor(
                actor_type="user",
                actor_id=str(user.pk),
                actor_display=getattr(user, "username", "") or "",
                ip_address=ip_address,
                request_id=request_id,
            )

        # 未认证请求
        return AuditActor(
            actor_type="system",
            actor_id="anonymous",
            actor_display="anonymous",
            ip_address=ip_address,
            request_id=request_id,
        )

    @staticmethod
    def _extract_ip(scope: dict[str, Any]) -> str | None:
        """从 scope["client"] 提取 IP 地址（(host, port) tuple 取 host）。"""
        client = scope.get("client")
        if client and isinstance(client, (tuple, list)) and len(client) >= 1:
            return str(client[0])
        return None

    @staticmethod
    def _extract_request_id(scope: dict[str, Any]) -> str:
        """从 scope["headers"] 提取 x-request-id。"""
        headers = scope.get("headers", [])
        for key, value in headers:
            if isinstance(key, bytes):
                key = key.decode("latin-1")
            if key.lower() == "x-request-id":
                return value.decode("latin-1") if isinstance(value, bytes) else str(value)
        return ""
