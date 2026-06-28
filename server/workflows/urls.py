"""Workflows app URL configuration."""

from adrf.routers import DefaultRouter
from django.urls import path

from workflows.api.analytics import (
    AnalyticsOverviewView,
    DurationDistributionView,
    NodePerformanceView,
    TokenCostView,
    TrendView,
)
from workflows.api.tool_endpoint import ToolInvokeView
from workflows.api.views import (
    ActionLogDetailView,
    AlertRuleExecutionViewSet,
    AlertRuleViewSet,
    CodingTaskViewSet,
    ExecutionContextView,
    LLMModelsView,
    LLMSystemConfigView,
    NodeExecutionActionView,
    NodeExecutionViewSet,
    NodeResolvedProviderView,
    NodeSchemaListView,
    NodeSubStepListView,
    NodeTypeViewSet,
    WebhookConfigViewSet,
    WebhookLogViewSet,
    WebhookTriggerView,
    WorkflowExecutionViewSet,
    WorkflowTriggerViewSet,
    WorkflowViewSet,
)

router = DefaultRouter()
router.register(r"workflows", WorkflowViewSet, basename="workflow")
router.register(r"workflow-executions", WorkflowExecutionViewSet, basename="workflow-execution")
router.register(r"node-executions", NodeExecutionViewSet, basename="node-execution")
router.register(r"node-types", NodeTypeViewSet, basename="node-type")
router.register(r"webhook-configs", WebhookConfigViewSet, basename="webhook-config")
router.register(r"webhook-logs", WebhookLogViewSet, basename="webhook-log")
router.register(r"workflow-triggers", WorkflowTriggerViewSet, basename="workflow-trigger")
router.register(r"coding-tasks", CodingTaskViewSet, basename="coding-task")
router.register(r"alert-rules", AlertRuleViewSet, basename="alert-rule")
router.register(r"alert-rule-executions", AlertRuleExecutionViewSet, basename="alert-rule-execution")

urlpatterns = router.urls + [
    # Webhook trigger endpoint (public, outside router)
    path(
        "webhook/<path:path>/",
        WebhookTriggerView.as_view(),
        name="webhook-trigger",
    ),
    # P9「工作流即端点」：工具调用入口（tool_name == WorkflowTrigger.token）
    path(
        "workflows/tools/<str:tool_name>/invoke/",
        ToolInvokeView.as_view(),
        name="workflow-tool-invoke",
    ),
    # Execution context endpoint
    path(
        "workflow-executions/<uuid:execution_id>/context/",
        ExecutionContextView.as_view(),
        name="execution-context",
    ),
    # implementation contract contract：workflow 节点四层 Provider 解析链
    path(
        "workflows/<uuid:workflow_id>/nodes/<uuid:node_id>/resolved-provider/",
        NodeResolvedProviderView.as_view(),
        name="node-resolved-provider",
    ),
    # Node schemas endpoint
    path(
        "nodes/schemas/",
        NodeSchemaListView.as_view(),
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
    # Nested sub-steps under node execution
    path(
        "node-executions/<uuid:node_execution_id>/sub-steps/",
        NodeSubStepListView.as_view(),
        name="node-execution-sub-steps",
    ),
    # LLM models query endpoint
    path(
        "workflows/llm/models/",
        LLMModelsView.as_view(),
        name="llm-models",
    ),
    # LLM system config endpoint
    path(
        "workflows/llm/config/",
        LLMSystemConfigView.as_view(),
        name="llm-config",
    ),
    # Node execution action endpoint (manual intervention)
    path(
        "workflow-executions/<uuid:execution_id>/nodes/<uuid:node_id>/<str:action_type>/",
        NodeExecutionActionView.as_view(),
        name="node-execution-action",
    ),
    # ActionLog detail endpoint
    path(
        "action-logs/<int:pk>/",
        ActionLogDetailView.as_view(),
        name="action-log-detail",
    ),
    # NodeSubStep list endpoint (nested under node-executions)
    path(
        "node-executions/<uuid:node_execution_id>/sub-steps/",
        NodeSubStepListView.as_view(),
        name="node-execution-sub-steps",
    ),
    # Analytics endpoints
    path("analytics/overview/", AnalyticsOverviewView.as_view(), name="analytics-overview"),
    path("analytics/trends/", TrendView.as_view(), name="analytics-trends"),
    path("analytics/duration-distribution/", DurationDistributionView.as_view(), name="analytics-duration-distribution"),
    path("analytics/token-cost/", TokenCostView.as_view(), name="analytics-token-cost"),
    path("analytics/node-performance/", NodePerformanceView.as_view(), name="analytics-node-performance"),
]
