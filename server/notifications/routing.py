"""站内信 WebSocket URL 路由。"""

from django.urls import re_path

from .consumers import NotificationConsumer
from .middleware import JWTCookieAuthMiddleware

websocket_urlpatterns = [
    re_path(r"ws/notifications/$", JWTCookieAuthMiddleware(NotificationConsumer.as_asgi())),
]
