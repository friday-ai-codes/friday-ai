"""项目实时推送 WebSocket URL 路由。"""

from django.urls import re_path

from initiatives.consumers import ProjectConsumer
from notifications.middleware import JWTCookieAuthMiddleware

websocket_urlpatterns = [
    re_path(
        r"ws/projects/(?P<project_id>[^/]+)/$",
        JWTCookieAuthMiddleware(ProjectConsumer.as_asgi()),
    ),
]
