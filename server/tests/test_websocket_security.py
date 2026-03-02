"""WebSocket WSS 强制策略测试。
验证 WSSEnforcementMiddleware 在不同模式下的行为：
- 生产模式（WEBSOCKET_REQUIRE_TLS=True）：拒绝 ws:// 连接
- 开发模式（WEBSOCKET_REQUIRE_TLS=False）：允许 ws:// 连接
"""
import pytest
from channels.testing import WebsocketCommunicator
from django.test import override_settings
from core.middleware import WSSEnforcementMiddleware
# 简单的测试 ASGI 应用，接受所有 WebSocket 连接
async def echo_app(scope, receive, send):
 """测试用 ASGI 应用，接受 WebSocket 连接并立即关闭。"""
 if scope["type"] == "websocket":
 await send({"type": "websocket.accept"})
 # 等待 disconnect
 msg = await receive
 if msg["type"] == "websocket.disconnect":
 return
@pytest.mark.asyncio
class TestWSSEnforcement:
 """WSS 强制中间件测试。"""
 async def test_wss_enforcement_rejects_ws_in_production(self):
 """生产模式下 ws:// 连接被拒绝（close code 4003）。"""
 app = WSSEnforcementMiddleware(echo_app)
 communicator = WebsocketCommunicator(app, "/ws/test/")
 communicator.scope["scheme"] = "ws"
 with override_settings(WEBSOCKET_REQUIRE_TLS=True):
 connected, code = await communicator.connect
 assert not connected
 assert code == 4003
 await communicator.disconnect
 async def test_wss_enforcement_allows_wss_in_production(self):
 """生产模式下 wss:// 连接正常接受。"""
 app = WSSEnforcementMiddleware(echo_app)
 communicator = WebsocketCommunicator(app, "/ws/test/")
 communicator.scope["scheme"] = "wss"
 with override_settings(WEBSOCKET_REQUIRE_TLS=True):
 connected, _ = await communicator.connect
 assert connected
 await communicator.disconnect
 async def test_wss_enforcement_allows_ws_in_debug(self):
 """开发模式下 ws:// 连接正常接受。"""
 app = WSSEnforcementMiddleware(echo_app)
 communicator = WebsocketCommunicator(app, "/ws/test/")
 communicator.scope["scheme"] = "ws"
 with override_settings(WEBSOCKET_REQUIRE_TLS=False):
 connected, _ = await communicator.connect
 assert connected
 await communicator.disconnect
 async def test_wss_enforcement_explicit_disable(self):
 """WEBSOCKET_REQUIRE_TLS=False 显式关闭时，ws:// 连接正常接受。"""
 app = WSSEnforcementMiddleware(echo_app)
 communicator = WebsocketCommunicator(app, "/ws/test/")
 communicator.scope["scheme"] = "ws"
 with override_settings(WEBSOCKET_REQUIRE_TLS=False, DEBUG=False):
 connected, _ = await communicator.connect
 assert connected
 await communicator.disconnect
