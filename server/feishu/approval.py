"""Feishu approval handling for workflow executions.
This module provides approval handling for Feishu comments that trigger
workflow node approvals or rejections.
"""
import structlog
from asgiref.sync import sync_to_async
from workflows.models import (
 NodeExecution,
 NodeExecutionStatus,
 WorkflowExecution,
 WorkflowExecutionStatus,
)
logger = structlog.get_logger
class FeishuApprovalHandler:
 """Handles Feishu approval comments for workflow executions.
 This class processes approval/rejection comments from Feishu
 and applies them to waiting workflow nodes.
 """
 async def on_approval_comment(
 self,
 work_item_id: str,
 approved: bool,
 comment: str,
 approver=None,
 ) -> bool:
 """Handle Feishu approval comment by triggering node approval.
 Args:
 work_item_id: Feishu work item ID
 approved: Whether the comment is an approval
 comment: The comment text
 approver: The user who made the comment
 Returns:
 True if approval was processed, False if no matching execution found
 """
 from workflows.engine.scheduler import WorkflowEngine
 # Find active execution for this work item
 execution = await self._find_active_execution(work_item_id)
 if not execution:
 logger.warning(
 "no_active_execution_for_workitem",
 work_item_id=work_item_id,
 )
 return False
 # Find node waiting for approval
 node_execution = await sync_to_async(
 lambda: NodeExecution.objects.filter(
 workflow_execution=execution,
 status=NodeExecutionStatus.WAITING_APPROVAL,
 )
 .select_related("node")
 .first
 )
 if not node_execution:
 logger.warning(
 "no_pending_approval",
 execution_id=str(execution.id),
 work_item_id=work_item_id,
 )
 return False
 # Process approval
 engine = WorkflowEngine
 if approved:
 await engine.approve_node(node_execution, approver, comment)
 else:
 await engine.reject_node(node_execution, approver, comment)
 logger.info(
 "feishu_approval_processed",
 node_execution_id=str(node_execution.id),
 work_item_id=work_item_id,
 approved=approved,
 )
 return True
 async def _find_active_execution(self, work_item_id: str) -> WorkflowExecution | None:
 """Find active WorkflowExecution by work_item_id.
 Searches in both context and input_data for the work_item_id.
 """
 # Try to find by context first
 execution = await sync_to_async(
 lambda: WorkflowExecution.objects.filter(
 context__work_item_id=work_item_id,
 status__in=[
 WorkflowExecutionStatus.PENDING,
 WorkflowExecutionStatus.RUNNING,
 WorkflowExecutionStatus.PAUSED,
 ],
 ).first
 )
 if execution:
 return execution
 # Try input_data as fallback
 execution = await sync_to_async(
 lambda: WorkflowExecution.objects.filter(
 input_data__work_item_id=work_item_id,
 status__in=[
 WorkflowExecutionStatus.PENDING,
 WorkflowExecutionStatus.RUNNING,
 WorkflowExecutionStatus.PAUSED,
 ],
 ).first
 )
 return execution
