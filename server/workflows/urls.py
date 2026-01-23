"""Workflows app URL configuration."""
from django.urls import path
from rest_framework.routers import DefaultRouter
from workflows.api.views import (
 NodeExecutionViewSet,
 NodeTypeViewSet,
 WebhookConfigViewSet,
 WebhookLogViewSet,
 WebhookTriggerView,
 WorkflowExecutionViewSet,
 WorkflowViewSet,
)
router = DefaultRouter
router.register(r"workflows", WorkflowViewSet, basename="workflow")
router.register(r"workflow-executions", WorkflowExecutionViewSet, basename="workflow-execution")
router.register(r"node-executions", NodeExecutionViewSet, basename="node-execution")
router.register(r"node-types", NodeTypeViewSet, basename="node-type")
router.register(r"webhook-configs", WebhookConfigViewSet, basename="webhook-config")
router.register(r"webhook-logs", WebhookLogViewSet, basename="webhook-log")
urlpatterns = router.urls + [
 # Webhook trigger endpoint (public, outside router)
 path(
 "webhook/<path:path>/",
 WebhookTriggerView.as_view,
 name="webhook-trigger",
 ),
]
