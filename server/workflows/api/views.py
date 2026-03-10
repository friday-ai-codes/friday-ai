"""Workflows API views."""
import uuid
import structlog
from adrf.views import APIView
from adrf.viewsets import ModelViewSet, ReadOnlyModelViewSet
from asgiref.sync import sync_to_async
from django.db import transaction
from django.shortcuts import aget_object_or_404
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from common.exceptions import TriggerValidationError
from workflows.api.permissions import (
 ApprovalPermission,
 ExecutionPermission,
 WorkflowPermission,
)
from workflows.api.serializers import (
 ActionLogDetailSerializer,
 ActionLogSummarySerializer,
 CodingTaskListSerializer,
 CodingTaskSerializer,
 CodingTaskUpdateSerializer,
 ExecutionContextSerializer,
 NodeApproveSerializer,
 NodeExecutionSerializer,
 NodeSubStepSerializer,
 NodeRejectSerializer,
 NodeSubStepSerializer,
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
 WorkflowTriggerCreateSerializer,
 WorkflowTriggerSerializer,
 WorkflowUpdateSerializer,
)
from workflows.engine.scheduler import ResumeExecutionNotSupportedError, WorkflowEngine
from workflows.models import (
 CodingTask,
 NodeExecution,
 NodeExecutionStatus,
 NodeSubStep,
 WebhookConfig,
 WebhookLog,
 Workflow,
 WorkflowEdge,
 WorkflowExecution,
 WorkflowNode,
 WorkflowTrigger,
)
from workflows.nodes.registry import NodeRegistry
from workflows.triggers.context import TriggerContext
from workflows.triggers.dispatcher import TriggerDispatcher
logger = structlog.get_logger
async def async_sync_workflow_triggers(workflow: Workflow) -> None:
 """Sync feishu_event_trigger nodes to WorkflowTrigger table.
 This ensures that trigger nodes configured in the workflow canvas
 are automatically registered for webhook event matching.
 """
 # Get all feishu_event_trigger nodes from the workflow
 configured_triggers: list[dict] =
 async for node in workflow.nodes.filter(node_type="feishu_event_trigger"):
 config = node.config or {}
 event_types = config.get("event_types", )
 filter_config = {}
 # Build filter config from node config
 if config.get("filter_project_key"):
 filter_config["project_key"] = config["filter_project_key"]
 if config.get("filter_work_item_type"):
 filter_config["work_item_type_key"] = config["filter_work_item_type"]
 if config.get("filter_status"):
 filter_config["cur_work_item_status.state_key"] = config["filter_status"]
 for event_type in event_types:
 if not event_type:
 continue
 configured_triggers.append(
 {
 "event_type": event_type,
 "filter_config": filter_config,
 "node_id": str(node.id),
 "node_name": node.name,
 }
 )
 # Get existing triggers for this workflow
 existing_triggers = {t.event_type: t async for t in workflow.triggers.all}
 # Sync triggers
 seen_event_types = set
 for trigger_config in configured_triggers:
 event_type = trigger_config["event_type"]
 seen_event_types.add(event_type)
 if event_type in existing_triggers:
 # Update existing trigger
 trigger = existing_triggers[event_type]
 trigger.filter_config = trigger_config["filter_config"]
 trigger.is_active = True
 trigger.name = trigger_config["node_name"] or f"触发器: {event_type}"
 await trigger.asave
 else:
 # Create new trigger
 await WorkflowTrigger.objects.acreate(
 workflow=workflow,
 event_type=event_type,
 filter_config=trigger_config["filter_config"],
 is_active=True,
 name=trigger_config["node_name"] or f"触发器: {event_type}",
 )
 # Deactivate triggers for removed event types
 for event_type, trigger in existing_triggers.items:
 if event_type not in seen_event_types:
 trigger.is_active = False
 await trigger.asave
 logger.info(
 "workflow_triggers_synced",
 workflow_id=str(workflow.id),
 trigger_count=len(configured_triggers),
 event_types=list(seen_event_types),
 )
def _bulk_update_nodes_and_edges(
 workflow: Workflow,
 nodes_data: list,
 edges_data: list,
 delete_orphans: bool = False,
) -> None:
 """同步事务函数 -- bulk update nodes and edges。
 提取为独立函数，后续 async 迁移时只需
 await sync_to_async(_bulk_update_nodes_and_edges)(...) 即可。
 """
 with transaction.atomic:
 existing_node_ids: set[str] = set
 for node_data in nodes_data:
 node_id = node_data.get("id")
 if node_id:
 node = WorkflowNode.objects.filter(id=node_id, workflow=workflow).first
 if node:
 serializer = WorkflowNodeSerializer(node, data=node_data, partial=True)
 serializer.is_valid(raise_exception=True)
 serializer.save
 else:
 serializer = WorkflowNodeCreateSerializer(data=node_data)
 serializer.is_valid(raise_exception=True)
 node = WorkflowNode.objects.create(
 id=node_id, workflow=workflow, **serializer.validated_data
 )
 existing_node_ids.add(str(node_id))
 else:
 serializer = WorkflowNodeCreateSerializer(data=node_data)
 serializer.is_valid(raise_exception=True)
 node = WorkflowNode.objects.create(
 workflow=workflow, **serializer.validated_data
 )
 existing_node_ids.add(str(node.id))
 if delete_orphans:
 workflow.nodes.exclude(id__in=existing_node_ids).delete
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
# =============================================================================
# Workflow ViewSet
# =============================================================================
class WorkflowViewSet(ModelViewSet):
 """ViewSet for Workflow CRUD and execution."""
 queryset = Workflow.objects.all
 serializer_class = WorkflowSerializer
 permission_classes = [IsAuthenticated, WorkflowPermission]
 async def perform_acreate(self, serializer):
 # KEEP: serializer 继承自 rest_framework，不支持 asave
 await sync_to_async(serializer.save)
 async def perform_aupdate(self, serializer):
 # KEEP: serializer 继承自 rest_framework，不支持 asave
 await sync_to_async(serializer.save)
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
 async def retrieve(self, request: Request, *args, **kwargs) -> Response:
 """Get workflow with nodes and edges."""
 instance = await self.aget_object
 serializer = self.get_serializer(instance)
 return Response(serializer.data)
 @action(detail=True, methods=["post"])
 async def execute(self, request: Request, pk=None) -> Response:
 """Trigger workflow execution via TriggerDispatcher."""
 workflow = await self.aget_object
 trace_id = str(uuid.uuid4)
 log = logger.bind(trace_id=trace_id)
 log.info(
 "manual_trigger_start",
 workflow_id=str(workflow.id),
 user_id=str(request.user.id),
 )
 serializer = WorkflowExecuteSerializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 context = TriggerContext(
 trigger_type="manual",
 raw_payload=serializer.validated_data.get("input_data", {}),
 workflow=workflow,
 triggered_by=request.user,
 metadata={"trace_id": trace_id},
 )
 dispatcher = TriggerDispatcher
 execution = await dispatcher.dispatch_single(context)
 if not execution:
 raise TriggerValidationError("Failed to start workflow execution")
 log.info("manual_trigger_complete", execution_id=str(execution.id))
 return Response(
 {
 "workflow_id": str(execution.workflow_id),
 "workflow_name": await sync_to_async(lambda: execution.workflow.name),
 "execution_id": str(execution.id),
 "status": execution.status,
 "triggered_at": execution.created_at.isoformat,
 },
 status=status.HTTP_201_CREATED,
 )
 @action(detail=True, methods=["post"])
 async def duplicate(self, request: Request, pk=None) -> Response:
 """Duplicate workflow."""
 workflow = await self.aget_object
 new_name = request.data.get("name", f"{workflow.name} (副本)")
 new_project_id = request.data.get("project_id")
 new_project = None
 if new_project_id:
 from projects.models import Project
 new_project = await aget_object_or_404(Project, id=new_project_id)
 new_workflow = await workflow.aclone(new_project=new_project, new_name=new_name)
 new_workflow.created_by = request.user
 await new_workflow.asave
 # WorkflowSerializer.data 触发 FK 懒加载，需要在线程中执行
 data = await sync_to_async(lambda: WorkflowSerializer(new_workflow).data)
 return Response(
 data,
 status=status.HTTP_201_CREATED,
 )
 @action(detail=True, methods=["get"])
 async def export(self, request: Request, pk=None) -> Response:
 """Export workflow as JSON."""
 workflow = await self.aget_object
 data = await workflow.ato_json
 return Response(data)
 @action(detail=False, methods=["post"], url_path="import")
 async def import_workflow(self, request: Request) -> Response:
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
 project = await aget_object_or_404(Project, id=project_id)
 try:
 workflow = await Workflow.afrom_json(
 data=serializer.validated_data["data"],
 project=project,
 created_by=request.user,
 )
 # WorkflowSerializer.data 触发 FK 懒加载，需要在线程中执行
 data = await sync_to_async(lambda: WorkflowSerializer(workflow).data)
 return Response(
 data,
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
 async def nodes(self, request: Request, pk=None) -> Response:
 """List or create nodes for a workflow."""
 workflow = await self.aget_object
 if request.method == "GET":
 nodes_list = [n async for n in workflow.nodes.all]
 serializer = WorkflowNodeSerializer(nodes_list, many=True)
 return Response(serializer.data)
 # POST - Create node
 serializer = WorkflowNodeCreateSerializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 node = await WorkflowNode.objects.acreate(workflow=workflow, **serializer.validated_data)
 return Response(
 WorkflowNodeSerializer(node).data,
 status=status.HTTP_201_CREATED,
 )
 @action(
 detail=True,
 methods=["get", "put", "patch", "delete"],
 url_path=r"nodes/(?P<node_id>[^/.]+)",
 )
 async def node_detail(self, request: Request, pk=None, node_id=None) -> Response:
 """Get, update, or delete a specific node."""
 workflow = await self.aget_object
 node = await aget_object_or_404(WorkflowNode, id=node_id, workflow=workflow)
 if request.method == "GET":
 return Response(WorkflowNodeSerializer(node).data)
 if request.method == "DELETE":
 await node.adelete
 return Response(status=status.HTTP_204_NO_CONTENT)
 # PUT or PATCH
 partial = request.method == "PATCH"
 serializer = WorkflowNodeSerializer(node, data=request.data, partial=partial)
 serializer.is_valid(raise_exception=True)
 # KEEP: serializer 继承自 rest_framework，不支持 asave
 await sync_to_async(serializer.save)
 return Response(serializer.data)
 # =========================================================================
 # Edge Management (nested under workflow)
 # =========================================================================
 @action(detail=True, methods=["get", "post"], url_path="edges")
 async def edges(self, request: Request, pk=None) -> Response:
 """List or create edges for a workflow."""
 workflow = await self.aget_object
 if request.method == "GET":
 edges_list = [e async for e in workflow.edges.all]
 serializer = WorkflowEdgeSerializer(edges_list, many=True)
 return Response(serializer.data)
 # POST - Create edge
 serializer = WorkflowEdgeCreateSerializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 data = serializer.validated_data
 source_id = data.pop("source_node_id")
 target_id = data.pop("target_node_id")
 # Verify nodes belong to this workflow
 source = await aget_object_or_404(WorkflowNode, id=source_id, workflow=workflow)
 target = await aget_object_or_404(WorkflowNode, id=target_id, workflow=workflow)
 edge = await WorkflowEdge.objects.acreate(
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
 async def edge_detail(self, request: Request, pk=None, edge_id=None) -> Response:
 """Get, update, or delete a specific edge."""
 workflow = await self.aget_object
 edge = await aget_object_or_404(WorkflowEdge, id=edge_id, workflow=workflow)
 if request.method == "GET":
 return Response(WorkflowEdgeSerializer(edge).data)
 if request.method == "DELETE":
 await edge.adelete
 return Response(status=status.HTTP_204_NO_CONTENT)
 # PUT or PATCH
 partial = request.method == "PATCH"
 serializer = WorkflowEdgeSerializer(edge, data=request.data, partial=partial)
 serializer.is_valid(raise_exception=True)
 # KEEP: serializer 继承自 rest_framework，不支持 asave
 await sync_to_async(serializer.save)
 return Response(serializer.data)
 @action(detail=True, methods=["put"], url_path="bulk-update")
 async def bulk_update(self, request: Request, pk=None) -> Response:
 """Bulk update nodes and edges for a workflow.
 Uses UUID as primary identifier for nodes.
 short_id is only for user display and template variables.
 """
 workflow = await self.aget_object
 nodes_data = request.data.get("nodes", )
 edges_data = request.data.get("edges", )
 delete_orphans = request.data.get("delete_orphans", False)
 # KEEP: 包含 transaction.atomic + 多个 serializer + 批量 CRUD，完全 async 化复杂度高
 await sync_to_async(_bulk_update_nodes_and_edges)(workflow, nodes_data, edges_data, delete_orphans)
 # Return updated workflow
 await workflow.arefresh_from_db
 # Sync triggers from feishu_event_trigger nodes
 await async_sync_workflow_triggers(workflow)
 # KEEP: WorkflowSerializer 内部 get_execution_count/get_last_execution 触发 DB 查询
 data = await sync_to_async(lambda: WorkflowSerializer(workflow).data)
 return Response(data)
 # =========================================================================
 # Template Actions
 # =========================================================================
 @action(detail=False, methods=["get"])
 async def templates(self, request: Request) -> Response:
 """List available workflow templates."""
 from workflows.templates.loader import list_templates
 return Response(list_templates)
 @action(detail=False, methods=["post"], url_path="from-template")
 async def from_template(self, request: Request) -> Response:
 """Create a workflow from a template."""
 from workflows.templates.loader import acreate_workflow_from_template
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
 workflow = await acreate_workflow_from_template(
 project_id=project_id,
 template_id=template_id,
 name=name,
 description=description,
 created_by=request.user,
 )
 # WorkflowSerializer.data 触发 FK 懒加载，需要在线程中执行
 data = await sync_to_async(lambda: WorkflowSerializer(workflow).data)
 return Response(
 data,
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
 http_method_names = ["get", "post", "delete", "head", "options"] # No create/update, post for actions
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
 async def pause(self, request: Request, pk=None) -> Response:
 """Pause execution."""
 execution = await self.aget_object
 try:
 engine = WorkflowEngine
 await engine.pause_execution(execution)
 return Response({"status": "paused", "message": "执行已暂停"})
 except ValueError as e:
 return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
 @action(detail=True, methods=["post"])
 async def resume(self, request: Request, pk=None) -> Response:
 """Resume execution."""
 execution = await self.aget_object
 try:
 engine = WorkflowEngine
 await engine.resume_execution(execution)
 return Response({"status": "running", "message": "执行已恢复"})
 except ResumeExecutionNotSupportedError as e:
 return Response(
 {"detail": str(e)},
 status=status.HTTP_501_NOT_IMPLEMENTED,
 )
 except ValueError as e:
 return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
 @action(detail=True, methods=["post"])
 async def cancel(self, request: Request, pk=None) -> Response:
 """Cancel execution."""
 execution = await self.aget_object
 try:
 engine = WorkflowEngine
 await engine.cancel_execution(execution)
 return Response({"status": "cancelled", "message": "执行已取消"})
 except ValueError as e:
 return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
 @action(detail=True, methods=["post"])
 async def retry(self, request: Request, pk=None) -> Response:
 """用原始触发数据重新执行工作流。"""
 execution = await self.aget_object
 if execution.status not in ("failed", "cancelled"):
 return Response(
 {"detail": "只能重试失败或已取消的执行"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 workflow = await Workflow.objects.aget(pk=execution.workflow_id)
 trigger_data = execution.trigger_data or {}
 raw_payload = trigger_data.get("raw_payload", execution.input_data.get("raw_payload", {}))
 context = TriggerContext(
 trigger_type=execution.trigger_type or "manual",
 raw_payload=raw_payload,
 event_type=execution.input_data.get("event_type"),
 workflow=workflow,
 triggered_by=request.user,
 metadata={"retry_from": str(execution.id)},
 )
 dispatcher = TriggerDispatcher
 new_execution = await dispatcher.dispatch_single(context)
 if not new_execution:
 return Response(
 {"detail": "重试失败：无法启动工作流执行"},
 status=status.HTTP_500_INTERNAL_SERVER_ERROR,
 )
 return Response(
 {
 "execution_id": str(new_execution.id),
 "status": new_execution.status,
 "retry_from": str(execution.id),
 },
 status=status.HTTP_201_CREATED,
 )
 @action(detail=True, methods=["post"], url_path="resume-from-failed")
 async def resume_from_failed(self, request: Request, pk=None) -> Response:
 """从失败节点继续执行（创建新的部分重执行实例）。"""
 execution = await self.aget_object
 node_id = request.data.get("node_id")
 if not node_id:
 return Response(
 {"detail": "必须提供 node_id 参数"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 if execution.status not in ("failed", "cancelled", "timeout"):
 return Response(
 {"detail": "只能从失败、已取消或超时的执行继续"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 # 验证指定节点确实是失败的
 failed_ne = await NodeExecution.objects.filter(
 workflow_execution=execution,
 node_id=node_id,
 status=NodeExecutionStatus.FAILED,
 ).afirst
 if not failed_ne:
 return Response(
 {"detail": "指定节点不存在或不是失败状态"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 try:
 engine = WorkflowEngine
 new_execution = await engine.resume_from_node(
 original_execution=execution,
 failed_node_id=node_id,
 triggered_by=request.user,
 )
 return Response(
 {
 "execution_id": str(new_execution.id),
 "status": new_execution.status,
 "resumed_from": str(execution.id),
 },
 status=status.HTTP_201_CREATED,
 )
 except ValueError as e:
 error_msg = str(e)
 if "已修改" in error_msg:
 return Response(
 {"detail": error_msg, "code": "definition_changed"},
 status=status.HTTP_409_CONFLICT,
 )
 return Response(
 {"detail": error_msg},
 status=status.HTTP_400_BAD_REQUEST,
 )
 @action(detail=True, methods=["get"], url_path="check-definition-changed")
 async def check_definition_changed(self, request: Request, pk=None) -> Response:
 """检查工作流定义是否在执行后发生变更。"""
 execution = await self.aget_object
 if not execution.workflow_definition:
 return Response({"changed": False})
 execution = await WorkflowExecution.objects.select_related("workflow").aget(
 pk=execution.pk
 )
 engine = WorkflowEngine
 changed = await engine._compare_workflow_definitions(
 execution.workflow_definition,
 execution.workflow,
 )
 return Response({"changed": changed})
 @action(detail=True, methods=["get"])
 async def nodes(self, request: Request, pk=None) -> Response:
 """List node executions for this execution."""
 execution = await self.aget_object
 node_executions_list = [
 ne async for ne in execution.node_executions.select_related("node").all
 ]
 serializer = NodeExecutionSerializer(node_executions_list, many=True)
 return Response(serializer.data)
 @action(detail=True, methods=["get"], url_path="cost-breakdown")
 async def cost_breakdown(self, request: Request, pk=None) -> Response:
 """获取执行的成本拆分（按节点 > 模型双层拆分）。"""
 from decimal import Decimal
 execution = await self.aget_object
 total_input = 0
 total_output = 0
 total_cache_read = 0
 total_cache_write = 0
 total_cost = Decimal("0")
 model_distribution: dict[str, Decimal] = {}
 node_costs =
 async for ne in (
 NodeExecution.objects
 .filter(workflow_execution=execution)
 .select_related("node")
 ):
 models_breakdown: dict = {}
 async for session in ne.subagent_sessions.all:
 async for usage in session.token_usages.all:
 model_name = usage.model
 if model_name not in models_breakdown:
 models_breakdown[model_name] = {
 "input_tokens": 0,
 "output_tokens": 0,
 "cache_read_tokens": 0,
 "cache_write_tokens": 0,
 "total_cost_usd": "0",
 }
 mb = models_breakdown[model_name]
 mb["input_tokens"] += usage.input_tokens
 mb["output_tokens"] += usage.output_tokens
 mb["cache_read_tokens"] += usage.cache_read_tokens
 mb["cache_write_tokens"] += usage.cache_write_tokens
 mb["total_cost_usd"] = str(
 Decimal(mb["total_cost_usd"]) + usage.total_cost_usd
 )
 # 更新总计
 total_input += usage.input_tokens
 total_output += usage.output_tokens
 total_cache_read += usage.cache_read_tokens
 total_cache_write += usage.cache_write_tokens
 total_cost += usage.total_cost_usd
 model_distribution[model_name] = (
 model_distribution.get(model_name, Decimal("0"))
 + usage.total_cost_usd
 )
 node_costs.append({
 "node_id": str(ne.node_id),
 "node_name": ne.node.name,
 "node_type": ne.node.node_type,
 "models": models_breakdown,
 })
 return Response({
 "nodes": node_costs,
 "summary": {
 "total_input_tokens": total_input,
 "total_output_tokens": total_output,
 "total_cache_read_tokens": total_cache_read,
 "total_cache_write_tokens": total_cache_write,
 "total_tokens": total_input + total_output,
 "total_cost_usd": str(total_cost),
 "model_distribution": {
 k: str(v) for k, v in model_distribution.items
 },
 },
 })
 @action(detail=True, methods=["get"], url_path="timeline")
 async def timeline(self, request: Request, pk=None) -> Response:
 """获取执行的时序数据（含瓶颈标识和摘要统计）。"""
 execution = await self.aget_object
 nodes_data: list[dict] =
 async for ne in (
 NodeExecution.objects
 .filter(workflow_execution=execution)
 .select_related("node")
 .order_by("started_at")
 ):
 nodes_data.append({
 "node_id": str(ne.node_id),
 "node_name": ne.node.name,
 "node_type": ne.node.node_type,
 "status": ne.status,
 "started_at": ne.started_at.isoformat if ne.started_at else None,
 "completed_at": ne.completed_at.isoformat if ne.completed_at else None,
 "duration_seconds": ne.duration,
 "is_bottleneck": False,
 "bottleneck_level": None,
 })
 # 瓶颈标识：按耗时降序取 Top3
 timed = [n for n in nodes_data if n["duration_seconds"] is not None]
 timed.sort(key=lambda n: n["duration_seconds"], reverse=True)
 for i, node in enumerate(timed[:3]):
 node["is_bottleneck"] = True
 node["bottleneck_level"] = "critical" if i == 0 else "warning"
 # 摘要统计
 durations = [n["duration_seconds"] for n in nodes_data if n["duration_seconds"] is not None]
 total_duration = execution.duration
 return Response({
 "nodes": nodes_data,
 "summary": {
 "total_duration_seconds": total_duration,
 "total_nodes": len(nodes_data),
 "avg_node_duration_seconds": (
 sum(durations) / len(durations) if durations else None
 ),
 "bottleneck_nodes": len(timed[:3]),
 },
 })
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
 async def approve(self, request: Request, pk=None) -> Response:
 """Approve a node waiting for approval."""
 node_execution = await self.aget_object
 if node_execution.status not in [
 NodeExecutionStatus.WAITING_APPROVAL,
 NodeExecutionStatus.WAITING_EVENT,
 ]:
 return Response(
 {"detail": "节点不在等待审批状态"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 serializer = NodeApproveSerializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 comment = serializer.validated_data.get("comment", "")
 try:
 engine = WorkflowEngine
 await engine.approve_node(node_execution, request.user, comment)
 return Response({"status": "approved", "message": "审批已通过"})
 except ValueError as e:
 return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
 @action(
 detail=True,
 methods=["post"],
 permission_classes=[IsAuthenticated, ApprovalPermission],
 )
 async def reject(self, request: Request, pk=None) -> Response:
 """Reject a node waiting for approval."""
 node_execution = await self.aget_object
 if node_execution.status not in [
 NodeExecutionStatus.WAITING_APPROVAL,
 NodeExecutionStatus.WAITING_EVENT,
 ]:
 return Response(
 {"detail": "节点不在等待审批状态"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 serializer = NodeRejectSerializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 comment = serializer.validated_data.get("comment", "")
 try:
 engine = WorkflowEngine
 await engine.reject_node(node_execution, request.user, comment)
 return Response({"status": "rejected", "message": "审批已拒绝"})
 except ValueError as e:
 return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
 @action(detail=True, methods=["post"])
 async def trigger(self, request: Request, pk=None) -> Response:
 """Trigger a pending manual_trigger node."""
 node_execution = await self.aget_object
 if node_execution.status != NodeExecutionStatus.PENDING:
 return Response(
 {"detail": "节点不在等待触发状态"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 node = await WorkflowNode.objects.aget(pk=node_execution.node_id)
 if node.node_type != "manual_trigger":
 return Response(
 {"detail": "只有手动触发节点可以被触发"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 input_data = request.data.get("input_data", {})
 try:
 engine = WorkflowEngine
 await engine.trigger_manual_node(node_execution, input_data)
 return Response({"status": "triggered", "message": "节点已触发"})
 except ValueError as e:
 return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
 except Exception as e:
 logger.exception("manual_trigger_error", node_execution_id=str(pk))
 return Response(
 {"detail": f"触发失败: {e}"},
 status=status.HTTP_500_INTERNAL_SERVER_ERROR,
 )
 @action(detail=True, methods=["get"], url_path="react-steps")
 async def react_steps(self, request: Request, pk=None) -> Response:
 """获取节点执行的 AI 推理步骤列表（摘要模式）。"""
 from subagent.models import ActionLog
 node_execution = await self.aget_object
 action_logs = ActionLog.objects.filter(
 session__node_execution=node_execution
 ).order_by("sequence")
 logs_list = [log async for log in action_logs]
 serializer = ActionLogSummarySerializer(logs_list, many=True)
 return Response(serializer.data)
# =============================================================================
# ActionLog Detail View
# =============================================================================
class ActionLogDetailView(APIView):
 """单条 ActionLog 完整详情端点。"""
 permission_classes = [IsAuthenticated]
 async def get(self, request: Request, pk: int) -> Response:
 """获取单条 ActionLog 的完整数据（含完整 payload）。"""
 from subagent.models import ActionLog
 action_log = await aget_object_or_404(ActionLog, pk=pk)
 serializer = ActionLogDetailSerializer(action_log)
 return Response(serializer.data)
# =============================================================================
# Node Type ViewSet
# =============================================================================
class NodeTypeViewSet(ReadOnlyModelViewSet):
 """ViewSet for listing available node types."""
 serializer_class = NodeTypeSerializer
 permission_classes = [IsAuthenticated]
 def get_queryset(self):
 node_types = NodeRegistry.get_all_schemas
 # Optionally filter by category
 category = self.request.query_params.get("category")
 if category:
 node_types = [nt for nt in node_types if nt["category"] == category]
 return node_types
 def get_object(self):
 pk = self.kwargs.get("pk")
 node_class = NodeRegistry.get(pk)
 if not node_class:
 from rest_framework.exceptions import NotFound
 raise NotFound(f"未知的节点类型: {pk}")
 return node_class.get_schema
# =============================================================================
# Webhook Views
# =============================================================================
class WebhookTriggerView(APIView):
 """View for handling external webhook triggers."""
 permission_classes = [AllowAny]
 async def post(self, request: Request, path: str) -> Response:
 """Handle incoming webhook via TriggerDispatcher."""
 trace_id = str(uuid.uuid4)
 log = logger.bind(trace_id=trace_id, webhook_path=path)
 log.info("webhook_trigger_start")
 # Read body before accessing request.data (DRF consumes the stream)
 try:
 request_body = request.body
 except Exception:
 request_body = b""
 context = TriggerContext(
 trigger_type="webhook",
 raw_payload=request.data if request.data else {},
 metadata={
 "trace_id": trace_id,
 "webhook_path": path,
 "signature": request.headers.get("X-Signature", ""),
 "request_body": request_body,
 "request_headers": dict(request.headers),
 "request_method": request.method,
 },
 )
 dispatcher = TriggerDispatcher
 executions = await dispatcher.dispatch(context)
 log.info("webhook_trigger_complete", execution_count=len(executions))
 if not executions:
 return Response(
 {"status": "no_workflows", "message": "No matching workflows found"},
 status=status.HTTP_200_OK,
 )
 return Response(
 [
 {
 "workflow_id": str(e.workflow.id),
 "workflow_name": e.workflow.name,
 "execution_id": str(e.id),
 "status": e.status,
 "triggered_at": e.created_at.isoformat,
 }
 for e in executions
 ],
 status=status.HTTP_201_CREATED,
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
# =============================================================================
# Trigger Management ViewSet
# =============================================================================
class WorkflowTriggerViewSet(ModelViewSet):
 """ViewSet for WorkflowTrigger CRUD."""
 queryset = WorkflowTrigger.objects.all
 serializer_class = WorkflowTriggerSerializer
 permission_classes = [IsAuthenticated]
 def get_serializer_class(self):
 if self.action == "create":
 return WorkflowTriggerCreateSerializer
 return WorkflowTriggerSerializer
 def get_queryset(self):
 queryset = WorkflowTrigger.objects.select_related("workflow")
 workflow_id = self.kwargs.get("workflow_id") or self.request.query_params.get("workflow_id")
 if workflow_id:
 queryset = queryset.filter(workflow_id=workflow_id)
 is_active = self.request.query_params.get("is_active")
 if is_active is not None:
 queryset = queryset.filter(is_active=is_active.lower == "true")
 return queryset.order_by("-created_at")
 async def perform_create(self, serializer):
 workflow_id = self.kwargs.get("workflow_id")
 if workflow_id:
 workflow = await aget_object_or_404(Workflow, id=workflow_id)
 # KEEP: serializer 继承自 rest_framework，不支持 asave
 await sync_to_async(serializer.save)(workflow=workflow)
 else:
 # KEEP: serializer 继承自 rest_framework，不支持 asave
 await sync_to_async(serializer.save)
# =============================================================================
# Execution Context View
# =============================================================================
# =============================================================================
# NodeSubStep View
# =============================================================================
class NodeSubStepListView(APIView):
 """列出指定 NodeExecution 的所有子步骤（只读）。
 GET /api/node-executions/{node_execution_id}/sub-steps/
 不分页，直接返回全部子步骤（数量通常少于 20）。
 """
 permission_classes = [IsAuthenticated]
 async def get(self, request: Request, node_execution_id: uuid.UUID) -> Response:
 """获取指定 NodeExecution 的所有子步骤，按 step_order 排序。"""
 node_execution = await NodeExecution.objects.filter(id=node_execution_id).afirst
 if not node_execution:
 return Response(
 {"detail": "未找到指定的节点执行记录。"},
 status=status.HTTP_404_NOT_FOUND,
 )
 sub_steps = [
 s
 async for s in NodeSubStep.objects.filter(
 node_execution_id=node_execution_id
 ).order_by("step_order")
 ]
 serializer = NodeSubStepSerializer(sub_steps, many=True)
 return Response(serializer.data)
class ExecutionContextView(APIView):
 """View for getting execution context snapshot."""
 permission_classes = [IsAuthenticated]
 async def get(self, request: Request, execution_id) -> Response:
 """Get execution context snapshot."""
 execution = await aget_object_or_404(WorkflowExecution, id=execution_id)
 context_snapshot = execution.get_context_snapshot
 serializer = ExecutionContextSerializer(context_snapshot)
 return Response(serializer.data)
# =============================================================================
# Node Schema View
# =============================================================================
class NodeSchemaListView(APIView):
 """View for listing all node schemas."""
 permission_classes = [IsAuthenticated]
 async def get(self, request: Request) -> Response:
 """Get all node schemas from registry."""
 schemas = NodeRegistry.get_all_schemas
 # Optionally filter by category
 category = request.query_params.get("category")
 if category:
 schemas = [s for s in schemas if s.get("category") == category]
 return Response(schemas)
# =============================================================================
# LLM Models Query View
# =============================================================================
class LLMModelsView(APIView):
 """View for querying available LLM models from an API endpoint."""
 permission_classes = [IsAuthenticated]
 async def post(self, request: Request) -> Response:
 """Query available models from an OpenAI-compatible API.
 Request body:
 base_url: str - API base URL (e.g., https://api.openai.com/v1)
 api_key: str - API key (optional for some local deployments)
 use_system: bool - If true, use system config (ignore base_url/api_key)
 Returns:
 List of model objects with id and other metadata.
 """
 use_system = request.data.get("use_system", False)
 if use_system:
 from services.claude_config import aget_claude_config
 config = await aget_claude_config
 if not config.api_key:
 return Response(
 {"detail": "系统未配置 API Key"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 base_url = config.base_url or "https://api.anthropic.com"
 api_key = config.api_key
 else:
 base_url = request.data.get("base_url", "").strip
 api_key = request.data.get("api_key", "").strip
 if not base_url:
 return Response(
 {"detail": "base_url 不能为空"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 base_url = base_url.rstrip("/")
 if not base_url.endswith("/v1"):
 base_url = f"{base_url}/v1"
 try:
 import httpx
 headers = {"Content-Type": "application/json"}
 if api_key:
 headers["Authorization"] = f"Bearer {api_key}"
 async with httpx.AsyncClient(timeout=30) as client:
 response = await client.get(f"{base_url}/models", headers=headers)
 if response.status_code != 200:
 return Response(
 {"detail": f"API 请求失败: {response.status_code} - {response.text}"},
 status=status.HTTP_502_BAD_GATEWAY,
 )
 data = response.json
 models = data.get("data", )
 models.sort(key=lambda m: m.get("id", ""))
 return Response(
 {
 "models": models,
 "count": len(models),
 }
 )
 except httpx.TimeoutException:
 return Response(
 {"detail": "请求超时，请检查 API 地址是否正确"},
 status=status.HTTP_504_GATEWAY_TIMEOUT,
 )
 except httpx.RequestError as e:
 return Response(
 {"detail": f"网络请求错误: {e}"},
 status=status.HTTP_502_BAD_GATEWAY,
 )
 except Exception as e:
 logger.exception("llm_models_query_error", base_url=base_url)
 return Response(
 {"detail": f"查询模型失败: {e}"},
 status=status.HTTP_500_INTERNAL_SERVER_ERROR,
 )
class LLMSystemConfigView(APIView):
 """View for getting system LLM configuration (for display in frontend)."""
 permission_classes = [IsAuthenticated]
 async def get(self, request: Request) -> Response:
 from services.claude_config import aget_claude_config
 config = await aget_claude_config
 return Response(
 {
 "base_url": config.base_url or "https://api.anthropic.com",
 "model": config.model,
 "has_api_key": bool(config.api_key),
 "source": config.source,
 }
 )
# =============================================================================
# CodingTask ViewSet
# =============================================================================
class CodingTaskViewSet(ModelViewSet):
 """ViewSet for CodingTask."""
 queryset = CodingTask.objects.all
 serializer_class = CodingTaskSerializer
 permission_classes = [IsAuthenticated]
 def get_serializer_class(self):
 if self.action == "list":
 return CodingTaskListSerializer
 if self.action in ["update", "partial_update"]:
 return CodingTaskUpdateSerializer
 return CodingTaskSerializer
 def get_queryset(self):
 queryset = CodingTask.objects.select_related("workflow_execution", "repository")
 # Filter by execution
 execution_id = self.kwargs.get("execution_id") or self.request.query_params.get(
 "execution_id"
 )
 if execution_id:
 queryset = queryset.filter(workflow_execution_id=execution_id)
 # Filter by status
 task_status = self.request.query_params.get("status")
 if task_status:
 queryset = queryset.filter(status=task_status)
 # Filter by repository
 repository_id = self.request.query_params.get("repository_id")
 if repository_id:
 queryset = queryset.filter(repository_id=repository_id)
 return queryset.order_by("-created_at")
 @action(detail=True, methods=["post"])
 async def approve_plan(self, request: Request, pk=None) -> Response:
 """Approve coding task plan and move to executing."""
 task = await self.aget_object
 if task.status != "plan_review":
 return Response(
 {"detail": "任务不在方案评审状态"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 await task.amark_executing
 return Response({"status": task.status, "message": "方案已批准，开始执行"})
 @action(detail=True, methods=["post"])
 async def reject_plan(self, request: Request, pk=None) -> Response:
 """Reject coding task plan and request revision."""
 task = await self.aget_object
 if task.status != "plan_review":
 return Response(
 {"detail": "任务不在方案评审状态"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 feedback = request.data.get("feedback", "")
 await task.aadd_feedback(feedback)
 await task.amark_planning
 return Response({"status": task.status, "message": "方案已驳回，重新规划"})
 @action(detail=True, methods=["post"])
 async def approve_code(self, request: Request, pk=None) -> Response:
 """Approve coding task code and mark as merged."""
 task = await self.aget_object
 if task.status != "code_review":
 return Response(
 {"detail": "任务不在代码评审状态"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 await task.amark_merged
 return Response({"status": task.status, "message": "代码已批准合并"})
 @action(detail=True, methods=["post"])
 async def reject_code(self, request: Request, pk=None) -> Response:
 """Reject coding task code and request revision."""
 task = await self.aget_object
 if task.status != "code_review":
 return Response(
 {"detail": "任务不在代码评审状态"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 feedback = request.data.get("feedback", "")
 await task.aadd_feedback(feedback)
 await task.amark_executing
 return Response({"status": task.status, "message": "代码已驳回，继续开发"})
# =============================================================================
# Node Execution Action View (Manual Intervention)
# =============================================================================
class NodeExecutionActionView(APIView):
 """节点执行操作视图 - 支持手动干预等待中的节点"""
 permission_classes = [IsAuthenticated]
 async def post(self, request: Request, execution_id, node_id, action_type) -> Response:
 """执行节点操作
 支持的 action_type:
 - skip-wait: 跳过等待，继续执行
 - trigger-resume: 手动触发唤醒
 """
 execution = await aget_object_or_404(WorkflowExecution, id=execution_id)
 node_execution = await aget_object_or_404(
 NodeExecution,
 workflow_execution=execution,
 id=node_id,
 )
 if action_type == "skip-wait":
 return await self._skip_wait(request, execution, node_execution)
 elif action_type == "trigger-resume":
 return await self._trigger_resume(request, execution, node_execution)
 else:
 return Response(
 {"detail": f"未知的操作类型: {action_type}"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 async def _skip_wait(
 self, request: Request, execution: WorkflowExecution, node_execution: NodeExecution
 ) -> Response:
 """跳过等待，继续执行"""
 from django.utils import timezone
 from workflows.models.execution import WorkflowEventSubscription
 if node_execution.status != NodeExecutionStatus.WAITING_EVENT:
 return Response(
 {"detail": "节点不在等待事件状态"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 await WorkflowEventSubscription.objects.filter(
 node_execution=node_execution,
 is_active=True,
 ).aupdate(is_active=False)
 node_execution.status = NodeExecutionStatus.COMPLETED
 node_execution.completed_at = timezone.now
 node_execution.output_data = {
 "skipped": True,
 "skip_reason": "用户手动跳过",
 "skipped_by": request.user.username if request.user.is_authenticated else "anonymous",
 "skipped_at": timezone.now.isoformat,
 }
 await node_execution.asave(update_fields=["status", "completed_at", "output_data"])
 # 更新执行统计
 execution.completed_nodes += 1
 await execution.asave(update_fields=["completed_nodes"])
 engine = WorkflowEngine
 await engine._continue_after_node(execution, node_execution)
 logger.info(
 "node_wait_skipped",
 execution_id=str(execution.id),
 node_id=str(node_execution.id),
 user=request.user.username if request.user.is_authenticated else "anonymous",
 )
 return Response({
 "status": "success",
 "message": "已跳过等待，工作流继续执行",
 })
 async def _trigger_resume(
 self, request: Request, execution: WorkflowExecution, node_execution: NodeExecution
 ) -> Response:
 """手动触发唤醒（模拟事件匹配）"""
 from django.utils import timezone
 from workflows.models.execution import WorkflowEventSubscription
 if node_execution.status != NodeExecutionStatus.WAITING_EVENT:
 return Response(
 {"detail": "节点不在等待事件状态"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 subscription = await WorkflowEventSubscription.objects.filter(
 node_execution=node_execution,
 is_active=True,
 ).afirst
 if subscription:
 await subscription.amark_matched({"manual_trigger": True})
 node_execution.status = NodeExecutionStatus.COMPLETED
 node_execution.completed_at = timezone.now
 node_execution.output_data = {
 "matched": True,
 "manual_trigger": True,
 "triggered_by": request.user.username if request.user.is_authenticated else "anonymous",
 "triggered_at": timezone.now.isoformat,
 }
 await node_execution.asave(update_fields=["status", "completed_at", "output_data"])
 execution.completed_nodes += 1
 await execution.asave(update_fields=["completed_nodes"])
 engine = WorkflowEngine
 await engine._continue_after_node(execution, node_execution)
 logger.info(
 "node_manually_resumed",
 execution_id=str(execution.id),
 node_id=str(node_execution.id),
 user=request.user.username if request.user.is_authenticated else "anonymous",
 )
 return Response({
 "status": "success",
 "message": "已手动触发唤醒，工作流继续执行",
 })
