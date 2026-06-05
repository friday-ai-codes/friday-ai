"""Runner WebSocket URL 路由。"""

from django.urls import re_path

from .consumers import MonitorConsumer, RunnerConsumer
from .middleware import RunnerTokenAuthMiddleware

websocket_urlpatterns = [
    re_path(r"ws/v1/runner/$", RunnerTokenAuthMiddleware(RunnerConsumer.as_asgi())),
    re_path(r"ws/v1/runners/monitor/$", MonitorConsumer.as_asgi()),
]
