"""WebSocket 安全中间件。"""
from typing import Any, Callable
import structlog
from django.conf import settings
logger = structlog.get_logger(__name__)
class WSSEnforcementMiddleware:
 """在生产模式下强制 WebSocket 使用 TLS (wss://)。
 当 WEBSOCKET_REQUIRE_TLS=True（默认在 DEBUG=False 时启用）时，
 拒绝非 TLS 的 WebSocket 连接（close code 4003）。
 开发模式（DEBUG=True）下默认允许 ws:// 连接。
 """
 def __init__(self, app: Callable[..., Any]) -> None:
 self.app = app
 async def __call__(self, scope: dict[str, Any], receive: Callable, send: Callable) -> None:
 if scope["type"] != "websocket":
 await self.app(scope, receive, send)
 return
 # 检查是否强制 TLS
 require_tls: bool = getattr(settings, "WEBSOCKET_REQUIRE_TLS", not settings.DEBUG)
 if require_tls:
 scheme = scope.get("scheme", "ws")
 if scheme != "wss":
 logger.warning(
 "websocket_insecure_rejected",
 scheme=scheme,
 path=scope.get("path", ""),
 client=scope.get("client"),
 )
 # 拒绝 WebSocket 握手
 await send({"type": "websocket.close", "code": 4003})
 return
 await self.app(scope, receive, send)
