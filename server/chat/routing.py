"""chat 会话实时同步 WebSocket URL 路由。"""

from django.urls import re_path

from notifications.middleware import JWTCookieAuthMiddleware

from .consumers import ChatConsumer

websocket_urlpatterns = [
    re_path(r"ws/chat/$", JWTCookieAuthMiddleware(ChatConsumer.as_asgi())),
]
