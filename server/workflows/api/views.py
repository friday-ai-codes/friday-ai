"""Workflows API views."""
import asyncio
from typing import Any
import structlog
from asgiref.sync import async_to_sync
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet
from workflows.api.permissions import (
 ApprovalPermission,
 ExecutionPermission,
 WorkflowPermission,
)
from workflows.api.serializers import (
 NodeApproveSerializer,
 NodeExecutionSerializer,
 NodeRejectSerializer,
 NodeTypeSerializer,
 WebhookConfigSerializer,
 WebhookLogSerializer,
 WorkflowCreateSerializer,
 WorkflowEdgeCreateSerializer,
 WorkflowEdgeSerializer,
 WorkflowExecuteSerializer,
 WorkflowExecutionListSerializer,
 WorkflowExecutionSerializer,
 WorkflowImportSerializer,
 WorkflowListSerializer,
 WorkflowNodeCreateSerializer,
 WorkflowNodeSerializer,
 WorkflowSerializer,
 WorkflowUpdateSerializer,
)
from workflows.engine.scheduler import WorkflowEngine
from workflows.models import (
 NodeExecution,
 NodeExecutionStatus,
 WebhookConfig,
 WebhookLog,
 Workflow,
 WorkflowEdge,
 WorkflowExecution,
 WorkflowNode,
)
from workflows.nodes.registry import NodeRegistry
logger = structlog.get_logger
def run_async(coro):
 """Run async coroutine in sync context."""
 return asyncio.run(coro)
# =============================================================================
# Workflow ViewSet
# =============================================================================
class WorkflowViewSet(ModelViewSet):
 """ViewSet for Workflow CRUD and execution."""
 queryset = Workflow.objects.all
 serializer_class = WorkflowSerializer
 permission_classes = [IsAuthenticated, WorkflowPermission]
 def get_serializer_class(self):
 if self.action == "create":
 return WorkflowCreateSerializer
 if self.action in ["update", "partial_update"]:
 return WorkflowUpdateSerializer
 if self.action == "list":
 return WorkflowListSerializer
 if self.action == "import_workflow":
 return WorkflowImportSerializer
 if self.action == "execute":
 return WorkflowExecuteSerializer
 return WorkflowSerializer
 def get_queryset(self):
 queryset = Workflow.objects.select_related("project", "created_by")
 # Filter by project
 project_id = self.request.query_params.get("project_id")
 if project_id:
 queryset = queryset.filter(project_id=project_id)
 # Filter by active status
 is_active = self.request.query_params.get("is_active")
 if is_active is not None:
 queryset = queryset.filter(is_active=is_active.lower == "true")
 # Filter by template status
 is_template = self.request.query_params.get("is_template")
 if is_template is not None:
 queryset = queryset.filter(is_template=is_template.lower == "true")
 # Filter by trigger type
 trigger_type = self.request.query_params.get("trigger_type")
 if trigger_type:
 queryset = queryset.filter(trigger_type=trigger_type)
 return queryset.order_by("-updated_at")
 def retrieve(self, request: Request, *args, **kwargs) -> Response:
 """Get workflow with nodes and edges."""
 instance = self.get_object
 serializer = self.get_serializer(instance)
 return Response(serializer.data)
 @action(detail=True, methods=["post"])
 def execute(self, request: Request, pk=None) -> Response:
 """Trigger workflow execution."""
 workflow = self.get_object
 if not workflow.is_active:
 return Response(
 {"detail": "工作流已禁用，无法执行"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 serializer = WorkflowExecuteSerializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 input_data = serializer.validated_data.get("input_data", {})
 trigger_data = serializer.validated_data.get("trigger_data", {})
 try:
 engine = WorkflowEngine
 execution = run_async(
 engine.start_execution(
 workflow=workflow,
 input_data=input_data,
 triggered_by=request.user,
 trigger_type="manual",
 trigger_data=trigger_data,
 )
 )
 return Response(
 {
 "execution_id": str(execution.id),
 "status": execution.status,
 "message": "工作流执行已启动",
 },
 status=status.HTTP_201_CREATED,
 )
 except ValueError as e:
 return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
 except Exception as e:
 logger.exception("workflow_execute_error", workflow_id=str(pk))
 return Response(
 {"detail": f"执行失败: {e}"},
 status=status.HTTP_500_INTERNAL_SERVER_ERROR,
 )
 @action(detail=True, methods=["post"])
 def duplicate(self, request: Request, pk=None) -> Response:
 """Duplicate workflow."""
 workflow = self.get_object
 new_name = request.data.get("name", f"{workflow.name} (副本)")
 new_project_id = request.data.get("project_id")
 new_project = None
 if new_project_id:
 from projects.models import Project
 new_project = get_object_or_404(Project, id=new_project_id)
 new_workflow = workflow.clone(new_project=new_project, new_name=new_name)
 new_workflow.created_by = request.user
 new_workflow.save
 return Response(
 WorkflowSerializer(new_workflow).data,
 status=status.HTTP_201_CREATED,
 )
 @action(detail=True, methods=["get"])
 def export(self, request: Request, pk=None) -> Response:
 """Export workflow as JSON."""
 workflow = self.get_object
 return Response(workflow.to_json)
 @action(detail=False, methods=["post"], url_path="import")
 def import_workflow(self, request: Request) -> Response:
 """Import workflow from JSON."""
 serializer = WorkflowImportSerializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 project_id = request.data.get("project_id")
 if not project_id:
 return Response(
 {"detail": "必须指定 project_id"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 from projects.models import Project
 project = get_object_or_404(Project, id=project_id)
 try:
 workflow = Workflow.from_json(
 data=serializer.validated_data["data"],
 project=project,
 created_by=request.user,
 )
 return Response(
 WorkflowSerializer(workflow).data,
 status=status.HTTP_201_CREATED,
 )
 except Exception as e:
 logger.exception("workflow_import_error")
 return Response(
 {"detail": f"导入失败: {e}"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 # =========================================================================
 # Node Management (nested under workflow)
 # =========================================================================
 @action(detail=True, methods=["get", "post"], url_path="nodes")
 def nodes(self, request: Request, pk=None) -> Response:
 """List or create nodes for a workflow."""
 workflow = self.get_object
 if request.method == "GET":
 nodes = workflow.nodes.all
 serializer = WorkflowNodeSerializer(nodes, many=True)
 return Response(serializer.data)
 # POST - Create node
 serializer = WorkflowNodeCreateSerializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 node = WorkflowNode.objects.create(workflow=workflow, **serializer.validated_data)
 return Response(
 WorkflowNodeSerializer(node).data,
 status=status.HTTP_201_CREATED,
 )
 @action(
 detail=True,
 methods=["get", "put", "patch", "delete"],
 url_path=r"nodes/(?P<node_id>[^/.]+)",
 )
 def node_detail(self, request: Request, pk=None, node_id=None) -> Response:
 """Get, update, or delete a specific node."""
 workflow = self.get_object
 node = get_object_or_404(WorkflowNode, id=node_id, workflow=workflow)
 if request.method == "GET":
 return Response(WorkflowNodeSerializer(node).data)
 if request.method == "DELETE":
 node.delete
 return Response(status=status.HTTP_204_NO_CONTENT)
 # PUT or PATCH
 partial = request.method == "PATCH"
 serializer = WorkflowNodeSerializer(node, data=request.data, partial=partial)
 serializer.is_valid(raise_exception=True)
 serializer.save
 return Response(serializer.data)
 # =========================================================================
 # Edge Management (nested under workflow)
 # =========================================================================
 @action(detail=True, methods=["get", "post"], url_path="edges")
 def edges(self, request: Request, pk=None) -> Response:
 """List or create edges for a workflow."""
 workflow = self.get_object
 if request.method == "GET":
 edges = workflow.edges.all
 serializer = WorkflowEdgeSerializer(edges, many=True)
 return Response(serializer.data)
 # POST - Create edge
 serializer = WorkflowEdgeCreateSerializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 data = serializer.validated_data
 source_id = data.pop("source_node_id")
 target_id = data.pop("target_node_id")
 # Verify nodes belong to this workflow
 source = get_object_or_404(WorkflowNode, id=source_id, workflow=workflow)
 target = get_object_or_404(WorkflowNode, id=target_id, workflow=workflow)
 edge = WorkflowEdge.objects.create(
 workflow=workflow,
 source_node=source,
 target_node=target,
 **data,
 )
 return Response(
 WorkflowEdgeSerializer(edge).data,
 status=status.HTTP_201_CREATED,
 )
 @action(
 detail=True,
 methods=["get", "put", "patch", "delete"],
 url_path=r"edges/(?P<edge_id>[^/.]+)",
 )
 def edge_detail(self, request: Request, pk=None, edge_id=None) -> Response:
 """Get, update, or delete a specific edge."""
 workflow = self.get_object
 edge = get_object_or_404(WorkflowEdge, id=edge_id, workflow=workflow)
 if request.method == "GET":
 return Response(WorkflowEdgeSerializer(edge).data)
 if request.method == "DELETE":
 edge.delete
 return Response(status=status.HTTP_204_NO_CONTENT)
 # PUT or PATCH
 partial = request.method == "PATCH"
 serializer = WorkflowEdgeSerializer(edge, data=request.data, partial=partial)
 serializer.is_valid(raise_exception=True)
 serializer.save
 return Response(serializer.data)
 @action(detail=True, methods=["put"], url_path="bulk-update")
 def bulk_update(self, request: Request, pk=None) -> Response:
 """Bulk update nodes and edges for a workflow."""
 workflow = self.get_object
 nodes_data = request.data.get("nodes", )
 edges_data = request.data.get("edges", )
 with transaction.atomic:
 # Update or create nodes
 existing_node_ids = set
 for node_data in nodes_data:
 node_id = node_data.get("id")
 if node_id:
 # Try to find existing node
 node = WorkflowNode.objects.filter(id=node_id, workflow=workflow).first
 if node:
 # Update existing
 serializer = WorkflowNodeSerializer(node, data=node_data, partial=True)
 serializer.is_valid(raise_exception=True)
 serializer.save
 else:
 # Create new node with specified ID
 serializer = WorkflowNodeCreateSerializer(data=node_data)
 serializer.is_valid(raise_exception=True)
 node = WorkflowNode.objects.create(
 id=node_id, workflow=workflow, **serializer.validated_data
 )
 existing_node_ids.add(str(node_id))
 else:
 # Create new node with auto-generated ID
 serializer = WorkflowNodeCreateSerializer(data=node_data)
 serializer.is_valid(raise_exception=True)
 node = WorkflowNode.objects.create(
 workflow=workflow, **serializer.validated_data
 )
 existing_node_ids.add(str(node.id))
 # Delete removed nodes
 delete_orphans = request.data.get("delete_orphans", False)
 if delete_orphans:
 workflow.nodes.exclude(id__in=existing_node_ids).delete
 # Recreate edges
 if edges_data:
 workflow.edges.all.delete
 for edge_data in edges_data:
 serializer = WorkflowEdgeCreateSerializer(data=edge_data)
 serializer.is_valid(raise_exception=True)
 data = serializer.validated_data
 WorkflowEdge.objects.create(
 workflow=workflow,
 source_node_id=data.pop("source_node_id"),
 target_node_id=data.pop("target_node_id"),
 **data,
 )
 # Return updated workflow
 workflow.refresh_from_db
 return Response(WorkflowSerializer(workflow).data)
 # =========================================================================
 # Template Actions
 # =========================================================================
 @action(detail=False, methods=["get"])
 def templates(self, request: Request) -> Response:
 """List available workflow templates."""
 from workflows.templates.loader import list_templates
 return Response(list_templates)
 @action(detail=False, methods=["post"], url_path="from-template")
 def from_template(self, request: Request) -> Response:
 """Create a workflow from a template."""
 from workflows.templates.loader import create_workflow_from_template
 template_id = request.data.get("template_id")
 project_id = request.data.get("project_id")
 name = request.data.get("name")
 description = request.data.get("description")
 if not template_id or not project_id:
 return Response(
 {"detail": "template_id and project_id are required"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 try:
 workflow = create_workflow_from_template(
 project_id=project_id,
 template_id=template_id,
 name=name,
 description=description,
 created_by=request.user,
 )
 return Response(
 WorkflowSerializer(workflow).data,
 status=status.HTTP_201_CREATED,
 )
 except ValueError as e:
 return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
 except Exception as e:
 logger.exception("create_from_template_error", template_id=template_id)
 return Response(
 {"detail": f"Failed to create workflow: {e}"},
 status=status.HTTP_500_INTERNAL_SERVER_ERROR,
 )
# =============================================================================
# Execution ViewSet
# =============================================================================
class WorkflowExecutionViewSet(ModelViewSet):
 """ViewSet for WorkflowExecution."""
 queryset = WorkflowExecution.objects.all
 serializer_class = WorkflowExecutionSerializer
 permission_classes = [IsAuthenticated, ExecutionPermission]
 http_method_names = ["get", "delete", "head", "options"] # No create/update
 def get_serializer_class(self):
 if self.action == "list":
 return WorkflowExecutionListSerializer
 return WorkflowExecutionSerializer
 def get_queryset(self):
 queryset = WorkflowExecution.objects.select_related(
 "workflow", "triggered_by"
 ).prefetch_related("node_executions")
 # Filter by workflow
 workflow_id = self.request.query_params.get("workflow_id")
 if workflow_id:
 queryset = queryset.filter(workflow_id=workflow_id)
 # Filter by project
 project_id = self.request.query_params.get("project_id")
 if project_id:
 queryset = queryset.filter(workflow__project_id=project_id)
 # Filter by status
 exec_status = self.request.query_params.get("status")
 if exec_status:
 queryset = queryset.filter(status=exec_status)
 return queryset.order_by("-created_at")
 @action(detail=True, methods=["post"])
 def pause(self, request: Request, pk=None) -> Response:
 """Pause execution."""
 execution = self.get_object
 try:
 engine = WorkflowEngine
 run_async(engine.pause_execution(execution))
 return Response({"status": "paused", "message": "执行已暂停"})
 except ValueError as e:
 return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
 @action(detail=True, methods=["post"])
 def resume(self, request: Request, pk=None) -> Response:
 """Resume execution."""
 execution = self.get_object
 try:
 engine = WorkflowEngine
 run_async(engine.resume_execution(execution))
 return Response({"status": "running", "message": "执行已恢复"})
 except ValueError as e:
 return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
 @action(detail=True, methods=["post"])
 def cancel(self, request: Request, pk=None) -> Response:
 """Cancel execution."""
 execution = self.get_object
 try:
 engine = WorkflowEngine
 run_async(engine.cancel_execution(execution))
 return Response({"status": "cancelled", "message": "执行已取消"})
 except ValueError as e:
 return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
 @action(detail=True, methods=["get"])
 def nodes(self, request: Request, pk=None) -> Response:
 """List node executions for this execution."""
 execution = self.get_object
 node_executions = execution.node_executions.select_related("node").all
 serializer = NodeExecutionSerializer(node_executions, many=True)
 return Response(serializer.data)
# =============================================================================
# Node Execution ViewSet
# =============================================================================
class NodeExecutionViewSet(ReadOnlyModelViewSet):
 """ViewSet for NodeExecution (read-only + approval actions)."""
 queryset = NodeExecution.objects.all
 serializer_class = NodeExecutionSerializer
 permission_classes = [IsAuthenticated]
 def get_queryset(self):
 queryset = NodeExecution.objects.select_related("node", "workflow_execution")
 # Filter by execution
 execution_id = self.request.query_params.get("execution_id")
 if execution_id:
 queryset = queryset.filter(workflow_execution_id=execution_id)
 # Filter by status
 node_status = self.request.query_params.get("status")
 if node_status:
 queryset = queryset.filter(status=node_status)
 return queryset.order_by("created_at")
 @action(
 detail=True,
 methods=["post"],
 permission_classes=[IsAuthenticated, ApprovalPermission],
 )
 def approve(self, request: Request, pk=None) -> Response:
 """Approve a node waiting for approval."""
 node_execution = self.get_object
 if node_execution.status != NodeExecutionStatus.WAITING_APPROVAL:
 return Response(
 {"detail": "节点不在等待审批状态"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 serializer = NodeApproveSerializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 comment = serializer.validated_data.get("comment", "")
 try:
 engine = WorkflowEngine
 run_async(engine.approve_node(node_execution, request.user, comment))
 return Response({"status": "approved", "message": "审批已通过"})
 except ValueError as e:
 return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
 @action(
 detail=True,
 methods=["post"],
 permission_classes=[IsAuthenticated, ApprovalPermission],
 )
 def reject(self, request: Request, pk=None) -> Response:
 """Reject a node waiting for approval."""
 node_execution = self.get_object
 if node_execution.status != NodeExecutionStatus.WAITING_APPROVAL:
 return Response(
 {"detail": "节点不在等待审批状态"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 serializer = NodeRejectSerializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 comment = serializer.validated_data.get("comment", "")
 try:
 engine = WorkflowEngine
 run_async(engine.reject_node(node_execution, request.user, comment))
 return Response({"status": "rejected", "message": "审批已拒绝"})
 except ValueError as e:
 return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
# =============================================================================
# Node Type ViewSet
# =============================================================================
class NodeTypeViewSet(ReadOnlyModelViewSet):
 """ViewSet for listing available node types."""
 serializer_class = NodeTypeSerializer
 permission_classes = [IsAuthenticated]
 def get_queryset(self):
 # Return empty - we use list directly
 return
 def list(self, request: Request) -> Response:
 """List all available node types."""
 node_types = NodeRegistry.get_all_schemas
 data = [NodeTypeSerializer(nt).data for nt in node_types]
 # Optionally filter by category
 category = request.query_params.get("category")
 if category:
 data = [d for d in data if d["category"] == category]
 return Response(data)
 def retrieve(self, request: Request, pk=None) -> Response:
 """Get a specific node type."""
 node_class = NodeRegistry.get(pk)
 if not node_class:
 return Response(
 {"detail": f"未知的节点类型: {pk}"},
 status=status.HTTP_404_NOT_FOUND,
 )
 return Response(NodeTypeSerializer(node_class.get_schema).data)
# =============================================================================
# Webhook Views
# =============================================================================
class WebhookTriggerView(APIView):
 """View for handling external webhook triggers."""
 permission_classes = [AllowAny]
 def post(self, request: Request, path: str) -> Response:
 """Handle incoming webhook."""
 # Find webhook config by path
 try:
 webhook_config = WebhookConfig.objects.select_related("workflow").get(
 path=path,
 is_active=True,
 )
 except WebhookConfig.DoesNotExist:
 return Response(
 {"detail": "Webhook not found"},
 status=status.HTTP_404_NOT_FOUND,
 )
 # Check HTTP method
 if request.method.upper != webhook_config.http_method.upper:
 return Response(
 {"detail": f"Method not allowed. Expected: {webhook_config.http_method}"},
 status=status.HTTP_405_METHOD_NOT_ALLOWED,
 )
 # Validate auth if required
 if webhook_config.require_auth:
 auth_header = request.headers.get("Authorization")
 expected_token = webhook_config.workflow.trigger_config.get("webhook_token")
 if not auth_header or auth_header != f"Bearer {expected_token}":
 return Response(
 {"detail": "Unauthorized"},
 status=status.HTTP_401_UNAUTHORIZED,
 )
 # Create webhook log
 import time
 start_time = time.time
 log = WebhookLog.objects.create(
 webhook_config=webhook_config,
 request_method=request.method,
 request_path=path,
 request_headers=dict(request.headers),
 request_body=request.data if request.data else {},
 )
 # Trigger workflow
 try:
 engine = WorkflowEngine
 execution = run_async(
 engine.start_execution(
 workflow=webhook_config.workflow,
 input_data=request.data if request.data else {},
 trigger_type="webhook",
 trigger_data={
 "webhook_config_id": str(webhook_config.id),
 "path": path,
 "headers": dict(request.headers),
 },
 )
 )
 # Update log with success
 processing_time = int((time.time - start_time) * 1000)
 log.execution = execution
 log.response_status = 200
 log.response_body = {"execution_id": str(execution.id)}
 log.processing_time_ms = processing_time
 log.save
 # Update webhook stats
 from django.utils import timezone
 webhook_config.request_count += 1
 webhook_config.last_triggered_at = timezone.now
 webhook_config.save(update_fields=["request_count", "last_triggered_at"])
 return Response(
 {
 "status": "triggered",
 "execution_id": str(execution.id),
 },
 status=status.HTTP_200_OK,
 )
 except Exception as e:
 # Update log with error
 processing_time = int((time.time - start_time) * 1000)
 log.response_status = 500
 log.error_message = str(e)
 log.processing_time_ms = processing_time
 log.save
 logger.exception("webhook_trigger_error", path=path)
 return Response(
 {"detail": f"Failed to trigger workflow: {e}"},
 status=status.HTTP_500_INTERNAL_SERVER_ERROR,
 )
class WebhookConfigViewSet(ModelViewSet):
 """ViewSet for WebhookConfig."""
 queryset = WebhookConfig.objects.all
 serializer_class = WebhookConfigSerializer
 permission_classes = [IsAuthenticated]
 def get_queryset(self):
 queryset = WebhookConfig.objects.select_related("workflow")
 workflow_id = self.request.query_params.get("workflow_id")
 if workflow_id:
 queryset = queryset.filter(workflow_id=workflow_id)
 return queryset.order_by("-created_at")
class WebhookLogViewSet(ReadOnlyModelViewSet):
 """ViewSet for WebhookLog (read-only)."""
 queryset = WebhookLog.objects.all
 serializer_class = WebhookLogSerializer
 permission_classes = [IsAuthenticated]
 def get_queryset(self):
 queryset = WebhookLog.objects.select_related("webhook_config", "execution")
 webhook_config_id = self.request.query_params.get("webhook_config_id")
 if webhook_config_id:
 queryset = queryset.filter(webhook_config_id=webhook_config_id)
 execution_id = self.request.query_params.get("execution_id")
 if execution_id:
 queryset = queryset.filter(execution_id=execution_id)
 return queryset.order_by("-created_at")
