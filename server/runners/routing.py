"""Runner WebSocket URL 路由。"""
from django.urls import re_path
from .consumers import RunnerConsumer
from .middleware import RunnerTokenAuthMiddleware
websocket_urlpatterns = [
 re_path(r"ws/v1/runner/$", RunnerTokenAuthMiddleware(RunnerConsumer.as_asgi)),
]
