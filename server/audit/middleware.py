"""审计上下文 ASGI/WSGI 双模中间件 -- 从 HTTP 请求中提取 actor 信息并注入 contextvars。

ASGI 模式（生产）：遵循 ``(app) -> __call__(scope, receive, send)`` 签名，
内部使用 async 处理；与 ``runners/middleware.py`` 和 ``core/middleware.py`` 模式一致。

WSGI 模式（测试兼容）：当 Django 测试客户端以 WSGI 方式调用 ``__call__(self, request)``
时，自动退化为同步中间件，仅设置 contextvar 并透传。

注册位置：``MIDDLEWARE`` 列表中 ``AuthenticationMiddleware`` 之后。
Django 的 ``AuthenticationMiddleware`` 在 scope/request 中填充 ``user``，
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
    """从 HTTP 请求 scope/request 提取 actor，设置到 contextvars。

    - JWT 认证：``scope["user"]`` 为已认证 User 实例
    - PAT 认证：``scope["auth"]`` 为 AccessToken 实例（有 ``token_hash`` 属性）
    - 未认证：``scope["user"]`` 为 AnonymousUser 或 ``is_authenticated=False``

    中间件在 ``finally`` 块中清理 contextvar，确保异常时也不泄漏。

    支持 ASGI 和 WSGI 两种调用模式：
    - ASGI: ``__call__(scope, receive, send)`` -- 生产环境，返回 coroutine
    - WSGI: ``__call__(request)`` -- Django 测试客户端兼容，返回 Response
    """

    def __init__(self, app: Callable[..., Any]) -> None:
        self.app = app

    def __call__(self, scope_or_request: Any, *args: Any) -> Any:
        # ASGI 模式：3 个参数 (scope, receive, send)
        if len(args) == 2:
            return self._asgi_call(scope_or_request, args[0], args[1])

        # WSGI 模式：1 个参数 (request)
        return self._wsgi_call(scope_or_request)

    async def _asgi_call(
        self, scope: dict[str, Any], receive: Callable, send: Callable
    ) -> Any:
        """ASGI 模式处理路径。"""
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

    def _wsgi_call(self, request: Any) -> Any:
        """WSGI 模式：从 HttpRequest 对象提取 actor，设置 contextvar。"""
        token = _NO_TOKEN
        try:
            actor = self._extract_actor_wsgi(request)
            token = set_current_actor(actor)
            return self.app(request)
        finally:
            if token is not _NO_TOKEN:
                reset_current_actor(token)

    @staticmethod
    def _extract_actor_wsgi(request: Any) -> AuditActor:
        """从 WSGI HttpRequest 提取 actor 信息。"""
        user = getattr(request, "user", None)
        ip_address = None
        if hasattr(request, "META"):
            x_forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
            if x_forwarded:
                ip_address = x_forwarded.split(",")[0].strip()
            else:
                ip_address = request.META.get("REMOTE_ADDR")

        if user is not None and getattr(user, "is_authenticated", False):
            return AuditActor(
                actor_type="user",
                actor_id=str(user.pk),
                actor_display=getattr(user, "username", "") or "",
                ip_address=ip_address,
                request_id="",
            )

        return AuditActor(
            actor_type="system",
            actor_id="anonymous",
            actor_display="anonymous",
            ip_address=ip_address,
            request_id="",
        )

    # ------------------------------------------------------------------
    # 内部方法（ASGI 模式）
    # ------------------------------------------------------------------

    def _extract_actor(self, scope: dict[str, Any]) -> AuditActor:
        """从 ASGI scope 提取 actor 信息。"""
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
