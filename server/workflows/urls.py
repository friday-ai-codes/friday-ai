"""Workflows app URL configuration."""
from django.urls import path
from adrf.routers import DefaultRouter
from workflows.api.views import (
 CodingTaskViewSet,
 ExecutionContextView,
 LLMModelsView,
 LLMSystemConfigView,
 NodeExecutionActionView,
 NodeExecutionViewSet,
 NodeSchemaListView,
 NodeTypeViewSet,
 WebhookConfigViewSet,
 WebhookLogViewSet,
 WebhookTriggerView,
 WorkflowExecutionViewSet,
 WorkflowTriggerViewSet,
 WorkflowViewSet,
)
router = DefaultRouter
router.register(r"workflows", WorkflowViewSet, basename="workflow")
router.register(r"workflow-executions", WorkflowExecutionViewSet, basename="workflow-execution")
router.register(r"node-executions", NodeExecutionViewSet, basename="node-execution")
router.register(r"node-types", NodeTypeViewSet, basename="node-type")
router.register(r"webhook-configs", WebhookConfigViewSet, basename="webhook-config")
router.register(r"webhook-logs", WebhookLogViewSet, basename="webhook-log")
router.register(r"workflow-triggers", WorkflowTriggerViewSet, basename="workflow-trigger")
router.register(r"coding-tasks", CodingTaskViewSet, basename="coding-task")
urlpatterns = router.urls + [
 # Webhook trigger endpoint (public, outside router)
 path(
 "webhook/<path:path>/",
 WebhookTriggerView.as_view,
 name="webhook-trigger",
 ),
 # Execution context endpoint
 path(
 "workflow-executions/<uuid:execution_id>/context/",
 ExecutionContextView.as_view,
 name="execution-context",
 ),
 # Node schemas endpoint
 path(
 "nodes/schemas/",
 NodeSchemaListView.as_view,
 name="node-schemas",
 ),
 # Nested triggers under workflow
 path(
 "workflows/<uuid:workflow_id>/triggers/",
 WorkflowTriggerViewSet.as_view({"get": "list", "post": "create"}),
 name="workflow-triggers-list",
 ),
 path(
 "workflows/<uuid:workflow_id>/triggers/<uuid:pk>/",
 WorkflowTriggerViewSet.as_view(
 {"get": "retrieve", "put": "update", "patch": "partial_update", "delete": "destroy"}
 ),
 name="workflow-triggers-detail",
 ),
 # Nested coding tasks under execution
 path(
 "workflow-executions/<uuid:execution_id>/coding-tasks/",
 CodingTaskViewSet.as_view({"get": "list"}),
 name="execution-coding-tasks",
 ),
 # LLM models query endpoint
 path(
 "workflows/llm/models/",
 LLMModelsView.as_view,
 name="llm-models",
 ),
 # LLM system config endpoint
 path(
 "workflows/llm/config/",
 LLMSystemConfigView.as_view,
 name="llm-config",
 ),
 # Node execution action endpoint (manual intervention)
 path(
 "workflow-executions/<uuid:execution_id>/nodes/<uuid:node_id>/<str:action_type>/",
 NodeExecutionActionView.as_view,
 name="node-execution-action",
 ),
]
