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
from workflows.models import NodeExecution, NodeExecutionStatus
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
