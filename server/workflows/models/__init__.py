"""Workflows models package."""
from workflows.models.workflow import Workflow
from workflows.models.node import WorkflowNode, WorkflowEdge
from workflows.models.execution import (
 WorkflowExecution,
 NodeExecution,
 ExecutionStatus,
 NodeExecutionStatus,
)
from workflows.models.webhook import WebhookConfig, WebhookLog
# Alias for compatibility
WorkflowExecutionStatus = ExecutionStatus
__all__ = [
 "Workflow",
 "WorkflowNode",
 "WorkflowEdge",
 "WorkflowExecution",
 "NodeExecution",
 "ExecutionStatus",
 "WorkflowExecutionStatus",
 "NodeExecutionStatus",
 "WebhookConfig",
 "WebhookLog",
]
