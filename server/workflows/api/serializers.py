"""Workflows API serializers."""
from rest_framework import serializers
from workflows.models import (
 CodingTask,
 NodeExecution,
 TriggerEventType,
 WebhookConfig,
 WebhookLog,
 Workflow,
 WorkflowEdge,
 WorkflowExecution,
 WorkflowNode,
 WorkflowTrigger,
)
from workflows.nodes.registry import NodeRegistry
# =============================================================================
# Trigger Serializers
# =============================================================================
class WorkflowTriggerSerializer(serializers.ModelSerializer):
 """Serializer for WorkflowTrigger."""
 event_type_display = serializers.CharField(source="get_event_type_display", read_only=True)
 class Meta:
 model = WorkflowTrigger
 fields = [
 "id",
 "workflow",
 "event_type",
 "event_type_display",
 "filter_config",
 "input_schema",
 "is_active",
 "name",
 "description",
 "created_at",
 "updated_at",
 ]
 read_only_fields = ["id", "created_at", "updated_at"]
 def validate_event_type(self, value: str) -> str:
 """Validate event type is a valid choice."""
 valid_types = [choice.value for choice in TriggerEventType]
 if value not in valid_types:
 raise serializers.ValidationError(
 f"Invalid event type: {value}. Valid types: {valid_types}"
 )
 return value
class WorkflowTriggerCreateSerializer(serializers.ModelSerializer):
 """Serializer for creating WorkflowTrigger."""
 class Meta:
 model = WorkflowTrigger
 fields = [
 "event_type",
 "filter_config",
 "input_schema",
 "is_active",
 "name",
 "description",
 ]
class ManualTriggerSerializer(serializers.Serializer):
 """Serializer for manual workflow trigger."""
 event_type = serializers.ChoiceField(
 choices=[choice.value for choice in TriggerEventType],
 required=False,
 allow_null=True,
 )
 input_data = serializers.JSONField(default=dict)
class ExecutionContextSerializer(serializers.Serializer):
 """Serializer for execution context snapshot."""
 execution_id = serializers.UUIDField
 status = serializers.CharField
 progress = serializers.FloatField
 is_manual_trigger = serializers.BooleanField
 trigger_data = serializers.JSONField
 input_data = serializers.JSONField
 global_params = serializers.JSONField
 node_outputs = serializers.JSONField
# =============================================================================
# CodingTask Serializers
# =============================================================================
class CodingTaskSerializer(serializers.ModelSerializer):
 """Serializer for CodingTask."""
 repository_name = serializers.CharField(source="repository.name", read_only=True)
 status_display = serializers.CharField(source="get_status_display", read_only=True)
 duration = serializers.FloatField(read_only=True)
 class Meta:
 model = CodingTask
 fields = [
 "id",
 "workflow_execution",
 "repository",
 "repository_name",
 "name",
 "prompt",
 "description",
 "status",
 "status_display",
 "session_id",
 "plan_output",
 "human_feedback",
 "branch_name",
 "commit_sha",
 "pr_url",
 "error_message",
 "retry_count",
 "metadata",
 "duration",
 "created_at",
 "updated_at",
 "started_at",
 "completed_at",
 ]
 read_only_fields = [
 "id",
 "workflow_execution",
 "repository",
 "created_at",
 "updated_at",
 "started_at",
 "completed_at",
 ]
class CodingTaskListSerializer(serializers.ModelSerializer):
 """Lightweight serializer for coding task list."""
 repository_name = serializers.CharField(source="repository.name", read_only=True)
 class Meta:
 model = CodingTask
 fields = [
 "id",
 "name",
 "repository",
 "repository_name",
 "status",
 "pr_url",
 "created_at",
 ]
class CodingTaskUpdateSerializer(serializers.ModelSerializer):
 """Serializer for updating CodingTask."""
 class Meta:
 model = CodingTask
 fields = [
 "status",
 "human_feedback",
 "branch_name",
 "commit_sha",
 "pr_url",
 ]
 extra_kwargs = {field: {"required": False} for field in fields}
# =============================================================================
# Node Serializers
# =============================================================================
class WorkflowNodeSerializer(serializers.ModelSerializer):
 """Serializer for WorkflowNode."""
 class Meta:
 model = WorkflowNode
 fields = [
 "id",
 "short_id",
 "node_type",
 "name",
 "description",
 "position_x",
 "position_y",
 "config",
 "timeout",
 "retry_count",
 "retry_delay",
 "run_condition",
 "metadata",
 "created_at",
 "updated_at",
 ]
 read_only_fields = ["id", "short_id", "created_at", "updated_at"]
 def validate_node_type(self, value: str) -> str:
 """Validate node type exists in registry."""
 if not NodeRegistry.get(value):
 available = ", ".join(NodeRegistry.list_types)
 raise serializers.ValidationError(
 f"Unknown node type: {value}. Available types: {available}"
 )
 return value
 def validate(self, attrs: dict) -> dict:
 """Validate node configuration against schema."""
 node_type = attrs.get("node_type") or (self.instance.node_type if self.instance else None)
 config = attrs.get("config", {})
 if node_type:
 node_class = NodeRegistry.get(node_type)
 if node_class:
 errors = node_class.validate_config(config)
 if errors:
 raise serializers.ValidationError({"config": errors})
 return attrs
class WorkflowNodeCreateSerializer(serializers.ModelSerializer):
 """Serializer for creating WorkflowNode."""
 class Meta:
 model = WorkflowNode
 fields = [
 "node_type",
 "name",
 "description",
 "position_x",
 "position_y",
 "config",
 "timeout",
 "retry_count",
 "retry_delay",
 "run_condition",
 "metadata",
 ]
 def validate_node_type(self, value: str) -> str:
 if not NodeRegistry.get(value):
 raise serializers.ValidationError(f"Unknown node type: {value}")
 return value
# =============================================================================
# Edge Serializers
# =============================================================================
class WorkflowEdgeSerializer(serializers.ModelSerializer):
 """Serializer for WorkflowEdge."""
 # Return UUID for internal operations
 source_node = serializers.CharField(source="source_node_id", read_only=True)
 target_node = serializers.CharField(source="target_node_id", read_only=True)
 class Meta:
 model = WorkflowEdge
 fields = [
 "id",
 "source_node",
 "target_node",
 "source_handle",
 "target_handle",
 "condition",
 "label",
 "style",
 "created_at",
 ]
 read_only_fields = ["id", "created_at"]
class WorkflowEdgeCreateSerializer(serializers.Serializer):
 """Serializer for creating WorkflowEdge."""
 source_node_id = serializers.UUIDField
 target_node_id = serializers.UUIDField
 source_handle = serializers.CharField(default="default")
 target_handle = serializers.CharField(default="default")
 condition = serializers.JSONField(required=False, allow_null=True)
 label = serializers.CharField(required=False, allow_blank=True, default="")
 style = serializers.JSONField(required=False, default=dict)
# =============================================================================
# Workflow Serializers
# =============================================================================
class WorkflowSerializer(serializers.ModelSerializer):
 """Serializer for Workflow with nested nodes and edges."""
 nodes = WorkflowNodeSerializer(many=True, read_only=True)
 edges = WorkflowEdgeSerializer(many=True, read_only=True)
 project_name = serializers.CharField(source="project.name", read_only=True)
 created_by_name = serializers.CharField(
 source="created_by.username", read_only=True, allow_null=True
 )
 execution_count = serializers.SerializerMethodField
 last_execution = serializers.SerializerMethodField
 class Meta:
 model = Workflow
 fields = [
 "id",
 "name",
 "description",
 "icon",
 "project",
 "project_name",
 "created_by",
 "created_by_name",
 "trigger_type",
 "trigger_config",
 "is_active",
 "is_template",
 "max_concurrent_executions",
 "default_timeout",
 "metadata",
 "nodes",
 "edges",
 "execution_count",
 "last_execution",
 "created_at",
 "updated_at",
 ]
 read_only_fields = ["id", "created_by", "created_at", "updated_at"]
 def get_execution_count(self, obj: Workflow) -> int:
 return obj.executions.count
 def get_last_execution(self, obj: Workflow) -> dict | None:
 last = obj.executions.order_by("-created_at").first
 if last:
 return {
 "id": str(last.id),
 "status": last.status,
 "created_at": last.created_at.isoformat,
 }
 return None
class WorkflowListSerializer(serializers.ModelSerializer):
 """Lightweight serializer for workflow list."""
 project_name = serializers.CharField(source="project.name", read_only=True)
 node_count = serializers.SerializerMethodField
 execution_count = serializers.SerializerMethodField
 last_execution = serializers.SerializerMethodField
 class Meta:
 model = Workflow
 fields = [
 "id",
 "name",
 "description",
 "icon",
 "project",
 "project_name",
 "trigger_type",
 "is_active",
 "is_template",
 "node_count",
 "execution_count",
 "last_execution",
 "created_at",
 "updated_at",
 ]
 def get_node_count(self, obj: Workflow) -> int:
 return obj.nodes.count
 def get_execution_count(self, obj: Workflow) -> int:
 return obj.executions.count
 def get_last_execution(self, obj: Workflow) -> dict | None:
 last = obj.executions.order_by("-created_at").first
 if last:
 return {
 "id": str(last.id),
 "status": last.status,
 "created_at": last.created_at.isoformat,
 }
 return None
class WorkflowCreateSerializer(serializers.ModelSerializer):
 """Serializer for creating Workflow."""
 nodes = WorkflowNodeCreateSerializer(many=True, required=False)
 edges = WorkflowEdgeCreateSerializer(many=True, required=False)
 class Meta:
 model = Workflow
 fields = [
 "name",
 "description",
 "icon",
 "project",
 "trigger_type",
 "trigger_config",
 "is_active",
 "is_template",
 "max_concurrent_executions",
 "default_timeout",
 "metadata",
 "nodes",
 "edges",
 ]
 def create(self, validated_data: dict) -> Workflow:
 nodes_data = validated_data.pop("nodes", )
 edges_data = validated_data.pop("edges", )
 # Create workflow
 validated_data["created_by"] = self.context["request"].user
 workflow = Workflow.objects.create(**validated_data)
 # Create nodes and build ID mapping for temp IDs
 node_id_mapping: dict[str, str] = {}
 for i, node_data in enumerate(nodes_data):
 temp_id = node_data.pop("temp_id", f"temp_{i}")
 node = WorkflowNode.objects.create(workflow=workflow, **node_data)
 node_id_mapping[temp_id] = str(node.id)
 # Create edges
 for edge_data in edges_data:
 source_id = str(edge_data.pop("source_node_id"))
 target_id = str(edge_data.pop("target_node_id"))
 # Map temp IDs to real IDs if needed
 source_id = node_id_mapping.get(source_id, source_id)
 target_id = node_id_mapping.get(target_id, target_id)
 WorkflowEdge.objects.create(
 workflow=workflow,
 source_node_id=source_id,
 target_node_id=target_id,
 **edge_data,
 )
 return workflow
class WorkflowUpdateSerializer(serializers.ModelSerializer):
 """Serializer for updating Workflow."""
 class Meta:
 model = Workflow
 fields = [
 "name",
 "description",
 "icon",
 "trigger_type",
 "trigger_config",
 "is_active",
 "max_concurrent_executions",
 "default_timeout",
 "metadata",
 ]
 extra_kwargs = {field: {"required": False} for field in fields}
class WorkflowImportSerializer(serializers.Serializer):
 """Serializer for importing workflow from JSON."""
 data = serializers.JSONField
 def validate_data(self, value: dict) -> dict:
 if "workflow" not in value:
 raise serializers.ValidationError("Missing 'workflow' key in import data")
 if "nodes" not in value:
 raise serializers.ValidationError("Missing 'nodes' key in import data")
 return value
# =============================================================================
# Execution Serializers
# =============================================================================
class NodeExecutionSerializer(serializers.ModelSerializer):
 """Serializer for NodeExecution."""
 node_name = serializers.CharField(source="node.name", read_only=True)
 node_type = serializers.CharField(source="node.node_type", read_only=True)
 duration = serializers.FloatField(read_only=True)
 class Meta:
 model = NodeExecution
 fields = [
 "id",
 "node",
 "node_name",
 "node_type",
 "status",
 "input_data",
 "output_data",
 "error_message",
 "error_traceback",
 "attempt",
 "approval_data",
 "container_id",
 "container_logs",
 "duration",
 "created_at",
 "started_at",
 "completed_at",
 ]
 read_only_fields = [
 "id",
 "node",
 "status",
 "input_data",
 "output_data",
 "error_message",
 "created_at",
 "started_at",
 "completed_at",
 ]
class NodeExecutionListSerializer(serializers.ModelSerializer):
 """Lightweight serializer for node execution list."""
 node_name = serializers.CharField(source="node.name", read_only=True)
 node_type = serializers.CharField(source="node.node_type", read_only=True)
 class Meta:
 model = NodeExecution
 fields = [
 "id",
 "node",
 "node_name",
 "node_type",
 "status",
 "attempt",
 "started_at",
 "completed_at",
 ]
class WorkflowExecutionSerializer(serializers.ModelSerializer):
 """Serializer for WorkflowExecution with node executions."""
 workflow_name = serializers.CharField(source="workflow.name", read_only=True)
 triggered_by_name = serializers.CharField(
 source="triggered_by.username", read_only=True, allow_null=True
 )
 node_executions = NodeExecutionSerializer(many=True, read_only=True)
 duration = serializers.FloatField(read_only=True)
 progress = serializers.FloatField(read_only=True)
 trigger_log_id: serializers.PrimaryKeyRelatedField = serializers.PrimaryKeyRelatedField(
 source="trigger_log", read_only=True, allow_null=True
 )
 workflow_definition: serializers.JSONField = serializers.JSONField(read_only=True)
 class Meta:
 model = WorkflowExecution
 fields = [
 "id",
 "workflow",
 "workflow_name",
 "status",
 "trigger_type",
 "triggered_by",
 "triggered_by_name",
 "trigger_data",
 "trigger_log_id",
 "workflow_definition",
 "context",
 "input_data",
 "output_data",
 "error_message",
 "error_node_id",
 "total_nodes",
 "completed_nodes",
 "failed_nodes",
 "skipped_nodes",
 "node_executions",
 "duration",
 "progress",
 "created_at",
 "started_at",
 "completed_at",
 "timeout_at",
 ]
 read_only_fields = [
 "id",
 "workflow",
 "status",
 "triggered_by",
 "trigger_data",
 "context",
 "output_data",
 "error_message",
 "workflow_definition",
 "created_at",
 "started_at",
 "completed_at",
 ]
class WorkflowExecutionListSerializer(serializers.ModelSerializer):
 """Lightweight serializer for execution list."""
 workflow_name = serializers.CharField(source="workflow.name", read_only=True)
 triggered_by_name = serializers.CharField(
 source="triggered_by.username", read_only=True, allow_null=True
 )
 duration = serializers.FloatField(read_only=True)
 progress = serializers.FloatField(read_only=True)
 trigger_log_id: serializers.PrimaryKeyRelatedField = serializers.PrimaryKeyRelatedField(
 source="trigger_log", read_only=True, allow_null=True
 )
 class Meta:
 model = WorkflowExecution
 fields = [
 "id",
 "workflow",
 "workflow_name",
 "status",
 "trigger_type",
 "triggered_by_name",
 "trigger_log_id",
 "total_nodes",
 "completed_nodes",
 "failed_nodes",
 "duration",
 "progress",
 "created_at",
 "started_at",
 "completed_at",
 ]
class WorkflowExecuteSerializer(serializers.Serializer):
 """Serializer for executing a workflow."""
 input_data = serializers.JSONField(required=False, default=dict)
 trigger_data = serializers.JSONField(required=False, default=dict)
class NodeApproveSerializer(serializers.Serializer):
 """Serializer for approving a node."""
 comment = serializers.CharField(required=False, allow_blank=True, default="")
class NodeRejectSerializer(serializers.Serializer):
 """Serializer for rejecting a node."""
 comment = serializers.CharField(required=False, allow_blank=True, default="")
# =============================================================================
# Node Type Serializers
# =============================================================================
class NodePortSerializer(serializers.Serializer):
 """Serializer for node port definition."""
 name = serializers.CharField
 label = serializers.CharField
 type = serializers.CharField
 required = serializers.BooleanField
 description = serializers.CharField
 schema = serializers.JSONField(required=False, allow_null=True)
class NodeTypeSerializer(serializers.Serializer):
 """Serializer for node type definition (for frontend node palette)."""
 node_type = serializers.CharField
 display_name = serializers.CharField
 description = serializers.CharField
 icon = serializers.CharField
 category = serializers.CharField
 config_schema = serializers.JSONField
 inputs = NodePortSerializer(many=True)
 outputs = NodePortSerializer(many=True)
 requires_container = serializers.BooleanField
 is_blocking = serializers.BooleanField
 execution_mode = serializers.CharField
# =============================================================================
# Webhook Serializers
# =============================================================================
class WebhookConfigSerializer(serializers.ModelSerializer):
 """Serializer for WebhookConfig."""
 class Meta:
 model = WebhookConfig
 fields = [
 "id",
 "workflow",
 "name",
 "description",
 "path",
 "is_active",
 "created_at",
 "updated_at",
 ]
 read_only_fields = ["id", "created_at", "updated_at"]
class WebhookLogSerializer(serializers.ModelSerializer):
 """Serializer for WebhookLog."""
 class Meta:
 model = WebhookLog
 fields = [
 "id",
 "webhook_config",
 "execution",
 "request_method",
 "request_headers",
 "request_body",
 "request_ip",
 "response_status",
 "response_body",
 "success",
 "error_message",
 "created_at",
 ]
 read_only_fields = ["id", "created_at"]
