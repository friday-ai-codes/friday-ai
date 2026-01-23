"""Task API compatibility views.
This module provides backward-compatible views that proxy requests
to the Workflow API while maintaining the Task API response format.
"""
import structlog
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from core.feature_flags import feature_flags
from tasks.compat import task_to_response, workflow_execution_to_task_response
from workflows.models import NodeExecutionStatus, WorkflowExecution
logger = structlog.get_logger
class TaskCompatViewSet(viewsets.ViewSet):
 """Task API compatibility layer - transparently proxies to Workflow.
 This ViewSet provides backward compatibility for the /api/tasks/ endpoint
 by querying WorkflowExecution data and converting it to Task format.
 Deprecation headers are added to all responses to signal API sunset.
 """
 def add_deprecation_headers(self, response: Response) -> Response:
 """Add deprecation warning headers to response."""
 response["Deprecation"] = "true"
 response["Sunset"] = "Sun, 01 Jun 2025 00:00:00 GMT"
 response["Link"] = '</api/workflow-executions/>; rel="successor-version"'
 return response
 def list(self, request):
 """GET /api/tasks/ - List tasks (from both Workflow and legacy Task)."""
 if not feature_flags.enable_task_compat_api:
 return Response(
 {"detail": "Task API is disabled. Use /api/workflow-executions/ instead."},
 status=status.HTTP_410_GONE,
 )
 project_id = request.query_params.get("project_id")
 status_filter = request.query_params.get("status")
 limit = int(request.query_params.get("limit", 50))
 results =
 # 1. Query WorkflowExecutions (code_generation template)
 wf_queryset = WorkflowExecution.objects.filter(
 workflow__metadata__template_id="code_generation"
 ).select_related("workflow").prefetch_related(
 "node_executions__node"
 ).order_by("-created_at")
 if project_id:
 wf_queryset = wf_queryset.filter(workflow__project_id=project_id)
 for execution in wf_queryset[:limit]:
 try:
 results.append(workflow_execution_to_task_response(execution))
 except Exception as e:
 logger.warning(
 "compat_conversion_failed",
 execution_id=str(execution.id),
 error=str(e),
 )
 # 2. Query legacy Tasks that haven't been migrated
 try:
 from tasks.models import Task
 # Get IDs of migrated tasks
 migrated_task_ids = WorkflowExecution.objects.filter(
 context__has_key="legacy_task_id"
 ).values_list("context__legacy_task_id", flat=True)
 task_queryset = Task.objects.exclude(
 id__in=[tid for tid in migrated_task_ids if tid]
 ).order_by("-created_at")
 if project_id:
 task_queryset = task_queryset.filter(project_id=project_id)
 remaining_limit = limit - len(results)
 if remaining_limit > 0:
 for task in task_queryset[:remaining_limit]:
 results.append(task_to_response(task))
 except Exception as e:
 logger.warning("legacy_task_query_failed", error=str(e))
 # Sort by created_at descending
 results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
 response = Response(results[:limit])
 return self.add_deprecation_headers(response)
 def retrieve(self, request, pk=None):
 """GET /api/tasks/{id}/ - Get task details."""
 if not feature_flags.enable_task_compat_api:
 return Response(
 {"detail": "Task API is disabled. Use /api/workflow-executions/ instead."},
 status=status.HTTP_410_GONE,
 )
 # Try WorkflowExecution first
 try:
 execution = (
 WorkflowExecution.objects.select_related("workflow")
 .prefetch_related("node_executions__node")
 .get(id=pk)
 )
 data = workflow_execution_to_task_response(execution)
 response = Response(data)
 return self.add_deprecation_headers(response)
 except (WorkflowExecution.DoesNotExist, ValueError):
 pass
 # Fallback to legacy Task
 try:
 from tasks.models import Task
 task = Task.objects.get(id=pk)
 data = task_to_response(task)
 response = Response(data)
 return self.add_deprecation_headers(response)
 except Exception:
 pass
 return Response(
 {"detail": "Not found."},
 status=status.HTTP_404_NOT_FOUND,
 )
 @action(detail=True, methods=["post"])
 def approve(self, request, pk=None):
 """POST /api/tasks/{id}/approve/ - Approve current pending node."""
 if not feature_flags.enable_task_compat_api:
 return Response(
 {"detail": "Task API is disabled."},
 status=status.HTTP_410_GONE,
 )
 comment = request.data.get("comment", "")
 try:
 execution = WorkflowExecution.objects.get(id=pk)
 except WorkflowExecution.DoesNotExist:
 return Response(
 {"detail": "Not found or not a workflow task."},
 status=status.HTTP_404_NOT_FOUND,
 )
 # Find pending approval node
 pending_node = execution.node_executions.filter(
 status=NodeExecutionStatus.WAITING_APPROVAL
 ).first
 if not pending_node:
 return Response(
 {"detail": "No pending approval found."},
 status=status.HTTP_400_BAD_REQUEST,
 )
 # Approve the node
 from workflows.engine.scheduler import WorkflowEngine
 engine = WorkflowEngine
 import asyncio
 loop = asyncio.new_event_loop
 try:
 loop.run_until_complete(
 engine.approve_node(pending_node, request.user, comment)
 )
 finally:
 loop.close
 response = Response({"status": "approved"})
 return self.add_deprecation_headers(response)
 @action(detail=True, methods=["post"])
 def reject(self, request, pk=None):
 """POST /api/tasks/{id}/reject/ - Reject current pending node."""
 if not feature_flags.enable_task_compat_api:
 return Response(
 {"detail": "Task API is disabled."},
 status=status.HTTP_410_GONE,
 )
 comment = request.data.get("comment", "")
 try:
 execution = WorkflowExecution.objects.get(id=pk)
 except WorkflowExecution.DoesNotExist:
 return Response(
 {"detail": "Not found or not a workflow task."},
 status=status.HTTP_404_NOT_FOUND,
 )
 pending_node = execution.node_executions.filter(
 status=NodeExecutionStatus.WAITING_APPROVAL
 ).first
 if not pending_node:
 return Response(
 {"detail": "No pending approval found."},
 status=status.HTTP_400_BAD_REQUEST,
 )
 from workflows.engine.scheduler import WorkflowEngine
 engine = WorkflowEngine
 import asyncio
 loop = asyncio.new_event_loop
 try:
 loop.run_until_complete(
 engine.reject_node(pending_node, request.user, comment)
 )
 finally:
 loop.close
 response = Response({"status": "rejected"})
 return self.add_deprecation_headers(response)
