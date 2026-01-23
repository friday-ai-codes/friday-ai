"""Task to Workflow compatibility utilities.
This module provides conversion utilities between WorkflowExecution
and Task API formats, enabling backward compatibility during migration.
"""
from workflows.models import (
 NodeExecution,
 NodeExecutionStatus,
 WorkflowExecution,
)
# Workflow status + current node -> Task status mapping
def _get_task_status(workflow_status: str, current_node_type: str | None) -> str:
 """Map workflow execution state to Task status."""
 if workflow_status == "pending":
 return "pending"
 if workflow_status == "completed":
 return "merged"
 if workflow_status == "failed":
 return "failed"
 if workflow_status == "cancelled":
 return "failed"
 # For running status, determine based on current node
 if current_node_type is None:
 return "pending"
 node_to_status = {
 "generate_plan": "planning",
 "human_approval": "plan_review", # Could be plan_review or code_review
 "code_implement": "executing",
 "create_pr": "executing",
 }
 return node_to_status.get(current_node_type, "pending")
def workflow_execution_to_task_response(execution: WorkflowExecution) -> dict:
 """Convert WorkflowExecution to Task API response format.
 This enables the /api/tasks/ endpoint to return Workflow data
 in a format compatible with existing frontend code.
 """
 # Find active node
 active_node = (
 execution.node_executions.filter(
 status__in=[
 NodeExecutionStatus.RUNNING,
 NodeExecutionStatus.WAITING_APPROVAL,
 ]
 )
 .select_related("node")
 .first
 )
 current_node_type = active_node.node.node_type if active_node else None
 # Determine if this is plan_review or code_review for approval nodes
 if current_node_type == "human_approval":
 # Check if code_implement has completed
 code_completed = execution.node_executions.filter(
 node__node_type="code_implement",
 status=NodeExecutionStatus.COMPLETED,
 ).exists
 task_status = "code_review" if code_completed else "plan_review"
 else:
 task_status = _get_task_status(execution.status, current_node_type)
 # Extract context data
 context = execution.context or {}
 input_data = execution.input_data or {}
 # Get plan output from generate_plan node
 plan_node = execution.node_executions.filter(
 node__node_type="generate_plan",
 status=NodeExecutionStatus.COMPLETED,
 ).first
 plan_output = ""
 if plan_node and plan_node.output_data:
 plan_output = plan_node.output_data.get("plan_markdown", "")
 # Get code implementation results
 code_node = execution.node_executions.filter(
 node__node_type="code_implement",
 status=NodeExecutionStatus.COMPLETED,
 ).first
 branch_name = context.get("branch_name")
 commit_sha = context.get("commit_sha")
 pr_url = context.get("pr_url")
 if code_node and code_node.output_data:
 branch_name = branch_name or code_node.output_data.get("branch_name")
 commit_sha = commit_sha or code_node.output_data.get("commit_sha")
 # Get PR URL from create_pr node
 pr_node = execution.node_executions.filter(
 node__node_type="create_pr",
 status=NodeExecutionStatus.COMPLETED,
 ).first
 if pr_node and pr_node.output_data:
 pr_url = pr_url or pr_node.output_data.get("pr_url")
 return {
 "id": str(execution.id),
 "project_id": str(execution.workflow.project_id),
 "work_item_id": context.get("work_item_id", ""),
 "title": input_data.get("title", execution.workflow.name),
 "description": input_data.get("description", ""),
 "status": task_status,
 "branch_name": branch_name,
 "commit_sha": commit_sha,
 "pr_url": pr_url,
 "plan_output": plan_output,
 "error_message": execution.error_message or "",
 "created_at": execution.created_at.isoformat,
 "updated_at": execution.updated_at.isoformat,
 # Workflow-specific fields (prefixed with underscore)
 "_workflow_execution_id": str(execution.id),
 "_workflow_id": str(execution.workflow_id),
 "_is_workflow": True,
 }
def task_to_response(task) -> dict:
 """Convert legacy Task model to API response format."""
 return {
 "id": str(task.id),
 "project_id": str(task.project_id),
 "work_item_id": getattr(task, "work_item_id", "") or "",
 "title": task.title,
 "description": task.description or "",
 "status": task.status,
 "branch_name": getattr(task, "branch_name", None),
 "commit_sha": getattr(task, "commit_sha", None),
 "pr_url": getattr(task, "pr_url", None),
 "plan_output": getattr(task, "plan_output", "") or "",
 "error_message": getattr(task, "error_message", "") or "",
 "created_at": task.created_at.isoformat,
 "updated_at": task.updated_at.isoformat,
 "_is_workflow": False,
 }
