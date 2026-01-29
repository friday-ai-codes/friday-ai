"""Feishu to Workflow bridge service.
This module provides the bridge layer that converts Feishu webhook events
to Workflow operations, enabling gradual migration from Task to Workflow.
"""
import uuid as uuid_lib
from typing import Any
import jsonschema
import structlog
from asgiref.sync import sync_to_async
from django.utils import timezone
from core.feature_flags import feature_flags
from workflows.models import (
 NodeExecution,
 NodeExecutionStatus,
 WorkflowExecution,
 WorkflowExecutionStatus,
 WorkflowTrigger,
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
 )
 .select_related("node")
 .first
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
 # ============ Event Dispatching ============
 async def dispatch_event(
 self,
 event_type: str,
 project,
 payload: dict,
 trigger_log=None,
 ) -> list[WorkflowExecution]:
 """Dispatch a Feishu event to matching workflow triggers.
 Args:
 event_type: The Feishu event type (e.g., "WorkitemStatusEvent")
 project: The project instance
 payload: The webhook payload
 trigger_log: Optional TriggerLog instance
 Returns:
 List of created WorkflowExecution instances
 """
 # Find matching triggers for this project and event type
 triggers = await sync_to_async(
 lambda: list(
 WorkflowTrigger.objects.filter(
 workflow__project=project,
 event_type=event_type,
 is_active=True,
 workflow__is_active=True,
 ).select_related("workflow")
 )
 )
 if not triggers:
 logger.debug(
 "no_matching_triggers",
 event_type=event_type,
 project_id=str(project.id),
 )
 return
 executions =
 for trigger in triggers:
 # Check filter conditions
 if not self._matches_filter(trigger.filter_config, payload):
 logger.debug(
 "trigger_filter_not_matched",
 trigger_id=str(trigger.id),
 event_type=event_type,
 )
 continue
 # Validate input schema
 errors = self._validate_input(payload, trigger.input_schema)
 if errors:
 logger.warning(
 "trigger_input_validation_failed",
 trigger_id=str(trigger.id),
 errors=errors,
 )
 continue
 # Start workflow execution
 try:
 execution = await self._start_workflow(
 workflow=trigger.workflow,
 event_type=event_type,
 payload=payload,
 trigger_log=trigger_log,
 project=project,
 )
 executions.append(execution)
 logger.info(
 "workflow_triggered_by_event",
 execution_id=str(execution.id),
 workflow_id=str(trigger.workflow.id),
 trigger_id=str(trigger.id),
 event_type=event_type,
 )
 except Exception as e:
 logger.error(
 "workflow_trigger_failed",
 trigger_id=str(trigger.id),
 error=str(e),
 )
 return executions
 def _matches_filter(self, filter_config: dict, payload: dict) -> bool:
 """Check if payload matches all filter conditions.
 Args:
 filter_config: Filter configuration dict
 payload: The webhook payload
 Returns:
 True if all conditions match
 """
 if not filter_config:
 return True
 for key, expected_value in filter_config.items:
 actual_value = self._get_nested_value(payload, key)
 if isinstance(expected_value, list):
 # List match: actual_value should be in expected_value
 if actual_value not in expected_value:
 return False
 elif actual_value != expected_value:
 return False
 return True
 def _get_nested_value(self, data: dict, key: str) -> Any:
 """Get nested value from dict using dot-separated path.
 Args:
 data: The data dict
 key: Dot-separated key path (e.g., "cur_work_item_status.state_key")
 Returns:
 The value or None if not found
 """
 keys = key.split(".")
 current = data
 for k in keys:
 if isinstance(current, dict):
 current = current.get(k)
 else:
 return None
 return current
 def _validate_input(self, payload: dict, schema: dict) -> list[str]:
 """Validate payload against JSON Schema.
 Args:
 payload: The input data
 schema: JSON Schema to validate against
 Returns:
 List of validation error messages
 """
 if not schema:
 return
 errors =
 try:
 jsonschema.validate(payload, schema)
 except jsonschema.ValidationError as e:
 errors.append(str(e.message))
 except jsonschema.SchemaError as e:
 errors.append(f"Schema error: {e.message}")
 return errors
 async def _start_workflow(
 self,
 workflow,
 event_type: str,
 payload: dict,
 trigger_log,
 project,
 ) -> WorkflowExecution:
 """Start a workflow execution from an event.
 Args:
 workflow: The Workflow instance
 event_type: Event type string
 payload: The webhook payload
 trigger_log: Optional TriggerLog instance
 project: The project instance
 Returns:
 Created WorkflowExecution instance
 """
 from workflows.engine.scheduler import WorkflowEngine
 # Extract common fields from payload
 work_item_id = payload.get("id", "")
 project_key = payload.get("project_key", "") or payload.get("project_simple_name", "")
 event_uuid = str(uuid_lib.uuid4)
 # Prepare input data
 input_data = {
 "event_type": event_type,
 "event_uuid": event_uuid,
 "work_item_id": work_item_id,
 "project_key": project_key,
 "payload": payload,
 }
 # Prepare trigger data
 trigger_data = {
 "event_type": event_type,
 "trigger_log_id": str(trigger_log.id) if trigger_log else None,
 "triggered_at": timezone.now.isoformat,
 }
 # Prepare initial context
 initial_context = {
 "project_id": str(project.id),
 "trigger_type": "feishu_webhook",
 "event_type": event_type,
 }
 # Create execution
 execution = await sync_to_async(WorkflowExecution.objects.create)(
 workflow=workflow,
 trigger_type="feishu_webhook",
 trigger_data=trigger_data,
 trigger_log=trigger_log,
 input_data=input_data,
 context=initial_context,
 is_manual_trigger=False,
 )
 # Start the workflow engine
 engine = WorkflowEngine
 await engine.start_execution(
 workflow=workflow,
 input_data=input_data,
 trigger_type="feishu_webhook",
 trigger_data=trigger_data,
 execution=execution,
 )
 return execution
 async def manual_trigger(
 self,
 workflow,
 event_type: str | None,
 input_data: dict,
 triggered_by=None,
 ) -> WorkflowExecution:
 """Manually trigger a workflow execution.
 Args:
 workflow: The Workflow instance
 event_type: Optional event type to simulate
 input_data: Input data for the workflow
 triggered_by: User who triggered the execution
 Returns:
 Created WorkflowExecution instance
 """
 from workflows.engine.scheduler import WorkflowEngine
 # Add manual trigger metadata
 enriched_input = {
 **input_data,
 "_manual_trigger": True,
 "_triggered_by": str(triggered_by.id) if triggered_by else None,
 "_triggered_at": timezone.now.isoformat,
 }
 if event_type:
 enriched_input["event_type"] = event_type
 # Validate against workflow's triggers' input_schema if any
 triggers = await sync_to_async(lambda: list(workflow.triggers.filter(is_active=True)))
 for trigger in triggers:
 if trigger.input_schema:
 errors = self._validate_input(input_data, trigger.input_schema)
 if errors:
 raise ValueError(f"Input validation failed: {', '.join(errors)}")
 # Prepare trigger data
 trigger_data = {
 "event_type": event_type or "manual",
 "is_manual": True,
 "triggered_by": str(triggered_by.id) if triggered_by else None,
 "triggered_at": timezone.now.isoformat,
 }
 # Create execution
 execution = await sync_to_async(WorkflowExecution.objects.create)(
 workflow=workflow,
 trigger_type="manual",
 triggered_by=triggered_by,
 trigger_data=trigger_data,
 input_data=enriched_input,
 context={
 "project_id": str(workflow.project_id),
 "trigger_type": "manual",
 },
 is_manual_trigger=True,
 )
 # Start the workflow engine
 engine = WorkflowEngine
 await engine.start_execution(
 workflow=workflow,
 input_data=enriched_input,
 trigger_type="manual",
 trigger_data=trigger_data,
 execution=execution,
 )
 logger.info(
 "workflow_manually_triggered",
 execution_id=str(execution.id),
 workflow_id=str(workflow.id),
 triggered_by=str(triggered_by.id) if triggered_by else None,
 )
 return execution
