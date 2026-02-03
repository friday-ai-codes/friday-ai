"""Node execution callback API for container-based nodes.
This module provides the callback endpoint that containers call when
execution completes. It updates the node execution status and triggers
the workflow engine to continue.
"""
import structlog
from asgiref.sync import sync_to_async
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from workflows.models import CodingTask, NodeExecution, NodeExecutionStatus
logger = structlog.get_logger
class NodeExecutionCallbackView(APIView):
 """Container execution callback endpoint.
 This endpoint is called by containers when they complete execution.
 It is unauthenticated since it's called from within Docker containers.
 """
 # Allow unauthenticated access (called from containers)
 authentication_classes =
 permission_classes =
 async def post(self, request):
 """Handle container execution callback.
 Expected payload:
 {
 "node_execution_id": "uuid",
 "success": bool,
 "output": {...},
 "error": "string or null",
 "logs": "string"
 }
 """
 node_execution_id = request.data.get("node_execution_id")
 success = request.data.get("success", False)
 output = request.data.get("output", {})
 error = request.data.get("error")
 logs = request.data.get("logs", "")
 if not node_execution_id:
 return Response(
 {"error": "node_execution_id is required"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 try:
 node_execution = await NodeExecution.objects.select_related(
 "workflow_execution", "node"
 ).aget(id=node_execution_id)
 except NodeExecution.DoesNotExist:
 logger.warning(
 "callback_node_execution_not_found",
 node_execution_id=node_execution_id,
 )
 return Response(
 {"error": "NodeExecution not found"},
 status=status.HTTP_404_NOT_FOUND,
 )
 # Update node execution status
 if success:
 node_execution.status = NodeExecutionStatus.COMPLETED
 node_execution.output_data = output
 else:
 node_execution.status = NodeExecutionStatus.FAILED
 node_execution.error_message = error or "Unknown error"
 # Store logs in output_data
 if logs:
 if not node_execution.output_data:
 node_execution.output_data = {}
 node_execution.output_data["container_logs"] = logs
 await sync_to_async(node_execution.save)
 logger.info(
 "node_callback_processed",
 node_execution_id=str(node_execution_id),
 node_type=node_execution.node.node_type,
 success=success,
 )
 # Trigger workflow engine to continue execution
 await self._resume_workflow_execution(node_execution)
 return Response({"status": "ok"})
 async def _resume_workflow_execution(self, node_execution: NodeExecution):
 """Resume workflow execution after node callback.
 Updates workflow statistics and triggers continuation or failure handling.
 """
 from workflows.engine.scheduler import WorkflowEngine
 workflow_execution = node_execution.workflow_execution
 # Update workflow execution statistics
 if node_execution.status == NodeExecutionStatus.COMPLETED:
 workflow_execution.completed_nodes += 1
 elif node_execution.status == NodeExecutionStatus.FAILED:
 workflow_execution.failed_nodes += 1
 await sync_to_async(workflow_execution.save)
 # Get or create engine instance and continue execution
 engine = WorkflowEngine
 if node_execution.status == NodeExecutionStatus.COMPLETED:
 # Continue with next nodes
 await engine._continue_after_node(workflow_execution, node_execution)
 else:
 # Handle failure
 await engine._handle_node_failure(workflow_execution, node_execution)
 logger.info(
 "workflow_resumed_after_callback",
 workflow_execution_id=str(workflow_execution.id),
 node_execution_id=str(node_execution.id),
 node_status=node_execution.status,
 )
class CodingTaskCallbackView(APIView):
 """CodingTask status callback endpoint.
 This endpoint is called by task containers when they report status updates.
 Handles push_complete to trigger MR creation with dual-channel failure reporting.
 """
 # Allow unauthenticated access (called from containers)
 authentication_classes =
 permission_classes =
 async def post(self, request):
 """Handle CodingTask status callback.
 Expected payload:
 {
 "task_id": "uuid",
 "status": "push_complete" | "failed" | ...,
 "details": {
 "branch_name": "string",
 "commit_sha": "string",
 "modified_files": ["file1.py", "file2.py"]
 },
 "error": "string or null"
 }
 """
 task_id = request.data.get("task_id")
 callback_status = request.data.get("status")
 details = request.data.get("details", {})
 error = request.data.get("error")
 if not task_id:
 return Response(
 {"error": "task_id is required"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 if not callback_status:
 return Response(
 {"error": "status is required"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 try:
 coding_task = await CodingTask.objects.select_related(
 "workflow_execution", "repository"
 ).aget(id=task_id)
 except CodingTask.DoesNotExist:
 logger.warning("callback_coding_task_not_found", task_id=task_id)
 return Response(
 {"error": "CodingTask not found"},
 status=status.HTTP_404_NOT_FOUND,
 )
 log = logger.bind(task_id=str(task_id), callback_status=callback_status)
 if callback_status == "push_complete":
 return await self._handle_push_complete(coding_task, details, log)
 elif callback_status == "failed":
 await self._handle_failed(coding_task, error or "Unknown error", log)
 return Response({"status": "ok"})
 else:
 log.info("callback_status_received")
 return Response({"status": "ok"})
 async def _handle_push_complete(self, coding_task: CodingTask, details: dict, log) -> Response:
 """Handle push_complete status - create MR with dual-channel failure reporting.
 This implements the dual-channel reporting requirement:
 - Channel 1: Update task status (frontend displays error)
 - Channel 2: Post failure comment to Feishu work item
 """
 from workflows.services.mr_service import create_mr_for_task, report_feishu_failure
 branch_name = details.get("branch_name", "")
 commit_sha = details.get("commit_sha", "")
 modified_files = details.get("modified_files", )
 if not branch_name:
 return Response(
 {"error": "branch_name is required in details"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 log.info("push_complete_received", branch=branch_name, commit=commit_sha)
 # Create MR asynchronously
 result = await create_mr_for_task(
 task=coding_task,
 branch_name=branch_name,
 commit_sha=commit_sha,
 modified_files=modified_files,
 )
 if result.success:
 # Update task with MR URL and mark code_review
 await sync_to_async(coding_task.mark_code_review)(
 branch_name=branch_name,
 commit_sha=commit_sha,
 pr_url=result.mr_url,
 )
 # Add conflict warning to metadata if present
 if result.has_conflicts:
 coding_task.metadata = coding_task.metadata or {}
 coding_task.metadata["mr_has_conflicts"] = True
 await sync_to_async(coding_task.save)(update_fields=["metadata"])
 log.info("mr_created_successfully", mr_url=result.mr_url)
 return Response({
 "status": "ok",
 "mr_url": result.mr_url,
 "mr_id": result.mr_id,
 })
 else:
 # MR creation failed - partial success
 error_msg = f"Push succeeded but MR creation failed: {result.error}"
 # Channel 1: Update task status (frontend will display this)
 await sync_to_async(coding_task.mark_partial_success)(
 branch_name=branch_name,
 commit_sha=commit_sha,
 error=error_msg,
 )
 # Channel 2: Post failure to Feishu work item (dual-channel reporting)
 await report_feishu_failure(
 task=coding_task,
 error=result.error or "Unknown error",
 branch_name=branch_name,
 )
 log.warning("mr_creation_failed", error=result.error)
 return Response({
 "status": "partial_success",
 "error": error_msg,
 "branch_name": branch_name,
 "commit_sha": commit_sha,
 })
 async def _handle_failed(self, coding_task: CodingTask, error: str, log) -> None:
 """Handle failed status - mark task as failed."""
 await sync_to_async(coding_task.mark_failed)(error)
 log.error("task_failed", error=error)
