"""URL configuration for container callback endpoints (Phase)."""

from django.urls import path

from subagent.api.callbacks import ContainerCallbackView
from subagent.api.interactions import (
    AgentSessionAnswerView,
    InteractionAnswerView,
    NodeInteractionLogsView,
)

urlpatterns = [
    path("callback/", ContainerCallbackView.as_view(), name="container-callback"),
    path(
        "node-executions/<uuid:node_execution_id>/interactions/",
        NodeInteractionLogsView.as_view(),
        name="node-interaction-logs",
    ),
    path(
        "interactions/<int:interaction_id>/answer/",
        InteractionAnswerView.as_view(),
        name="interaction-answer",
    ),
    path(
        "agent-sessions/<str:session_id>/answer/",
        AgentSessionAnswerView.as_view(),
        name="agent-session-answer",
    ),
]
