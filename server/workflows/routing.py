"""WebSocket routing for workflows app."""
from django.urls import re_path
from .consumers import WorkflowExecutionConsumer
websocket_urlpatterns = [
 re_path(
 r"ws/workflow-executions/(?P<execution_id>[0-9a-f-]+)/$",
 WorkflowExecutionConsumer.as_asgi,
 ),
]
