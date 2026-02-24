"""Approval card callback handler for plan approval workflow node.
Handles approve/reject callbacks from approval cards.
Unlike plan_callback.py, this does NOT resume agent sessions.
Instead, it directly updates NodeExecution and continues the workflow
via engine.approve_node / engine.reject_node.
"""
import json
from typing import Any
import structlog
from feishu.cards.approval_card import (
 build_approval_approved_card,
 build_approval_rejected_card,
)
from feishu.views import CardCallback, register_card_callback
from workflows.engine.scheduler import WorkflowEngine, _run_in_thread
from workflows.models.execution import NodeExecution, NodeExecutionStatus
logger = structlog.get_logger(__name__)
@register_card_callback("approval_approve")
def handle_approval_approve(callback: CardCallback) -> dict[str, Any] | None:
 """Handle approval approve button click.
 Updates NodeExecution to completed + next_handle=approved,
 then triggers _continue_after_node to resume workflow.
 Args:
 callback: Card callback data with action_value containing
 execution_id and node_id
 Returns:
 Updated card JSON showing approved state, or None
 """
 data = _extract_callback_data(callback)
 if not data:
 return None
 execution_id = data.get("execution_id", "")
 node_id = data.get("node_id", "")
 if not execution_id or not node_id:
 logger.warning("approval_callback_missing_ids", data=data)
 return None
 logger.info("approval_approved", execution_id=execution_id, node_id=node_id)
 # Schedule async workflow resume (Feishu callback must respond within 3 seconds)
 _schedule_approval_completion(
 execution_id=execution_id,
 node_id=node_id,
 approved=True,
 approver_id=callback.user_open_id,
 )
 # Get plan info for the response card
 plan_title, document_url = _get_plan_info(execution_id, node_id)
 return build_approval_approved_card(
 plan_title=plan_title,
 document_url=document_url,
 )
@register_card_callback("approval_reject")
def handle_approval_reject(callback: CardCallback) -> dict[str, Any] | None:
 """Handle approval reject form submission.
 Extracts reject reason from form, updates NodeExecution to
 completed + next_handle=rejected, then resumes workflow.
 Args:
 callback: Card callback data with action_value containing
 execution_id, node_id, and form data
 Returns:
 Updated card JSON showing rejected state with reason, or None
 """
 data = _extract_callback_data(callback)
 if not data:
 return None
 execution_id = data.get("execution_id", "")
 node_id = data.get("node_id", "")
 reject_reason = _extract_reject_reason(callback)
 if not execution_id or not node_id:
 logger.warning("approval_callback_missing_ids", data=data)
 return None
 if not reject_reason:
 logger.warning("approval_reject_missing_reason", execution_id=execution_id)
 # Return None to not update card (user needs to fill in reason)
 return None
 logger.info(
 "approval_rejected",
 execution_id=execution_id,
 node_id=node_id,
 reason_preview=reject_reason[:50],
 )
 _schedule_approval_completion(
 execution_id=execution_id,
 node_id=node_id,
 approved=False,
 approver_id=callback.user_open_id,
 reject_reason=reject_reason,
 )
 plan_title, document_url = _get_plan_info(execution_id, node_id)
 return build_approval_rejected_card(
 plan_title=plan_title,
 document_url=document_url,
 reject_reason=reject_reason,
 )
def _extract_callback_data(callback: CardCallback) -> dict[str, Any]:
 """Extract data dict from callback action_value.
 The action_value may be a dict (parsed by CardCallbackView) or a string.
 Args:
 callback: Card callback data
 Returns:
 Parsed data dict, or empty dict if parsing fails
 """
 action_value = callback.action_value
 if isinstance(action_value, dict):
 return action_value
 elif isinstance(action_value, str):
 try:
 data = json.loads(action_value)
 return data if isinstance(data, dict) else {}
 except json.JSONDecodeError:
 return {}
 return {}
def _extract_reject_reason(callback: CardCallback) -> str:
 """Extract reject reason from form submission callback.
 Form values are in action_value dict under various keys depending
 on the Feishu card callback format.
 Args:
 callback: Card callback data
 Returns:
 Reject reason text, or empty string if not found
 """
 action_value = callback.action_value
 if isinstance(action_value, dict):
 # Check for form input value directly
 reason: str = action_value.get("reject_reason", "")
 if not reason:
 # Fallback: check nested form_value
 form_value = action_value.get("form_value", {})
 if isinstance(form_value, dict):
 reason = form_value.get("reject_reason", "")
 return reason
 return ""
def _get_plan_info(execution_id: str, node_id: str) -> tuple[str, str]:
 """Get plan title and document URL from NodeExecution's approval_data.
 Args:
 execution_id: Workflow execution ID
 node_id: Node ID (WorkflowNode UUID)
 Returns:
 Tuple of (plan_title, document_url)
 """
 try:
 node_execution = NodeExecution.objects.filter(
 workflow_execution_id=execution_id,
 node_id=node_id,
 ).first
 if not node_execution:
 return ("技术方案", "")
 approval_data = node_execution.approval_data or {}
 plan_data = approval_data.get("plan", {})
 plan_title: str = ""
 if isinstance(plan_data, dict):
 plan_title = plan_data.get("title", "技术方案")
 else:
 plan_title = "技术方案"
 document_url: str = approval_data.get("document_url", "")
 return (plan_title, document_url)
 except Exception as e:
 logger.warning("get_plan_info_failed", error=str(e))
 return ("技术方案", "")
def _schedule_approval_completion(
 execution_id: str,
 node_id: str,
 approved: bool,
 approver_id: str,
 reject_reason: str = "",
) -> None:
 """Schedule async approval completion in background thread.
 Uses _run_in_thread pattern to avoid blocking the Feishu callback
 (must respond within 3 seconds).
 Args:
 execution_id: Workflow execution ID
 node_id: Node ID (WorkflowNode UUID)
 approved: Whether the plan was approved
 approver_id: Feishu user open_id of the approver
 reject_reason: Reason for rejection (only used when approved=False)
 """
 async def _do_approval -> None:
 from workflows.models.execution import ExecutionStatus
 try:
 # Find the NodeExecution
 node_execution = await NodeExecution.objects.filter(
 workflow_execution_id=execution_id,
 node_id=node_id,
 status__in=[
 NodeExecutionStatus.WAITING_EVENT,
 NodeExecutionStatus.WAITING_APPROVAL,
 ],
 ).select_related("workflow_execution").afirst
 if not node_execution:
 logger.warning(
 "approval_node_not_found",
 execution_id=execution_id,
 node_id=node_id,
 )
 return
 # select_related 已预加载 workflow_execution
 workflow_execution = node_execution.workflow_execution
 if workflow_execution.status == ExecutionStatus.SUSPENDED:
 workflow_execution.status = ExecutionStatus.RUNNING
 await workflow_execution.asave(update_fields=["status"])
 engine = WorkflowEngine
 # Create a simple approver object with required attributes
 class _FeishuApprover:
 def __init__(self, open_id: str) -> None:
 self.id = open_id
 self.username = f"feishu:{open_id}"
 def __str__(self) -> str:
 return self.username
 approver = _FeishuApprover(approver_id)
 if approved:
 await engine.approve_node(node_execution, approver, "")
 else:
 await engine.reject_node(node_execution, approver, reject_reason)
 logger.info(
 "approval_completion_done",
 execution_id=execution_id,
 node_id=node_id,
 approved=approved,
 )
 except Exception as e:
 logger.exception(
 "approval_completion_error",
 execution_id=execution_id,
 node_id=node_id,
 error=str(e),
 )
 _run_in_thread(_do_approval)
