"""Feishu to Workflow bridge service.
This module provides the bridge layer that converts Feishu webhook events
to Workflow operations, enabling gradual migration from Task to Workflow.
"""
import structlog
from asgiref.sync import sync_to_async
from core.feature_flags import feature_flags
from workflows.models import (
 NodeExecution,
 NodeExecutionStatus,
 WorkflowExecution,
 WorkflowExecutionStatus,
)
logger = structlog.get_logger
class FeishuWorkflowBridge:
 """Bridge service for Feishu events to Workflow operations.
 This class handles the conversion of Feishu webhook events into
 Workflow operations, supporting the Task -> Workflow migration.
 """
 DEFAULT_TEMPLATE = "code_generation"
 async def on_workitem_create(
 self,
 project,
 work_item_id: str,
 title: str,
 description: str,
 ) -> WorkflowExecution:
 """Handle Feishu work item creation by creating and starting a Workflow.
 Args:
 project: The project instance
 work_item_id: Feishu work item ID
 title: Work item title
 description: Work item description
 Returns:
 The created WorkflowExecution instance
 """
 from workflows.engine.scheduler import WorkflowEngine
 from workflows.templates.loader import acreate_workflow_from_template
 # Get repository path if available
 repository_path = None
 repos = await sync_to_async(lambda: list(project.repositories.all[:1]))
 if repos:
 repository_path = repos[0].local_path
 # Create workflow from template
 workflow = await acreate_workflow_from_template(
 project_id=str(project.id),
 template_id=feature_flags.default_workflow_template or self.DEFAULT_TEMPLATE,
 name=title,
 description=description,
 )
 # Create execution instance
 execution = await sync_to_async(WorkflowExecution.objects.create)(
 workflow=workflow,
 trigger_type="feishu_webhook",
 input_data={
 "title": title,
 "description": description,
 "work_item_id": work_item_id,
 },
 context={
 "work_item_id": work_item_id,
 "project_id": str(project.id),
 "repository_path": repository_path,
 },
 )
 # Start execution
 engine = WorkflowEngine
 await engine.start_execution(
 workflow=workflow,
 input_data={
 "title": title,
 "description": description,
 "work_item_id": work_item_id,
 },
 trigger_type="feishu_webhook",
 trigger_data={"work_item_id": work_item_id},
 )
 logger.info(
 "workflow_started_from_feishu",
 execution_id=str(execution.id),
 workflow_id=str(workflow.id),
 work_item_id=work_item_id,
 )
 return execution
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
 ).select_related("node").first
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
 async def _find_active_execution(
 self, work_item_id: str
 ) -> WorkflowExecution | None:
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
 async def get_execution_status(self, work_item_id: str) -> dict | None:
 """Get workflow execution status for a work item.
 Returns status information that can be displayed in Feishu.
 """
 execution = await self._find_active_execution(work_item_id)
 if not execution:
 return None
 # Get current node status
 current_node = await sync_to_async(
 lambda: NodeExecution.objects.filter(
 workflow_execution=execution,
 status__in=[
 NodeExecutionStatus.RUNNING,
 NodeExecutionStatus.WAITING_APPROVAL,
 ],
 ).select_related("node").first
 )
 return {
 "execution_id": str(execution.id),
 "workflow_id": str(execution.workflow_id),
 "status": execution.status,
 "current_node": current_node.node.name if current_node else None,
 "current_node_status": current_node.status if current_node else None,
 "completed_nodes": execution.completed_nodes,
 "total_nodes": execution.total_nodes,
 }
