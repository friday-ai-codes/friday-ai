"""Workflows API serializers."""

from rest_framework import serializers

from projects.models import Space
from workflows.models import (
    CodingTask,
    NodeExecution,
    NodeSubStep,
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
    endpoint_path = serializers.CharField(read_only=True)

    class Meta:
        model = WorkflowTrigger
        fields = [
            "id",
            "workflow",
            "node_id",
            "token",
            "endpoint_path",
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
        read_only_fields = ["id", "token", "endpoint_path", "created_at", "updated_at"]

    def validate_event_type(self, value: str) -> str:
        """Validate event type is a valid choice（允许留空——新版按 token 路由）。"""
        if value == "":
            return value
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

    execution_id = serializers.UUIDField()
    status = serializers.CharField()
    progress = serializers.FloatField()
    is_manual_trigger = serializers.BooleanField()
    trigger_data = serializers.JSONField()
    input_data = serializers.JSONField()
    global_params = serializers.JSONField()
    node_outputs = serializers.JSONField()


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
            "on_error",
            "retry_times",
            "retry_delay",
            "node_timeout_seconds",
            "fallback_values",
            "run_condition",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "short_id", "created_at", "updated_at"]

    def validate_node_type(self, value: str) -> str:
        """Validate node type exists in registry."""
        if not NodeRegistry.get(value):
            # registry 无列举方法（Pitfall 7），用 get_all().keys() 枚举已注册类型
            available = ", ".join(NodeRegistry.get_all().keys())
            raise serializers.ValidationError(
                f"Unknown node type: {value}. Available types: {available}"
            )
        return value

    def validate_on_error(self, value: str) -> str:
        """Validate on_error strategy."""
        valid = ["abort", "retry", "ignore"]
        if value not in valid:
            raise serializers.ValidationError(f"Invalid on_error: {value}. Must be one of {valid}")
        return value

    def validate(self, attrs: dict) -> dict:
        """Validate node configuration against schema."""
        # bulk-update 路径由 WorkflowGraphValidator 统一做 config 校验并产出结构化
        # {errors:[...]}（VAL-02），跳过此处的单字段校验以免提前以 {"config":...}
        # 形态拦截；单节点 node_detail 路径不传该 context，校验照常生效。
        if self.context.get("skip_config_validation"):
            return attrs

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
            "on_error",
            "retry_times",
            "retry_delay",
            "node_timeout_seconds",
            "fallback_values",
            "run_condition",
            "metadata",
        ]

    def validate_node_type(self, value: str) -> str:
        if not NodeRegistry.get(value):
            raise serializers.ValidationError(f"Unknown node type: {value}")
        return value

    def validate(self, attrs: dict) -> dict:
        """校验节点 config 是否符合 schema（闭合 create 路径缺口）。

        与 WorkflowNodeSerializer.validate 同源：复用 BaseNode.validate_config
        （jsonschema）。create 路径 node_type 恒在 attrs 中。bulk-update 路径传
        ``skip_config_validation`` context，改由 WorkflowGraphValidator 统一校验。
        """
        if self.context.get("skip_config_validation"):
            return attrs

        node_type = attrs.get("node_type")
        config = attrs.get("config", {})

        if node_type:
            node_class = NodeRegistry.get(node_type)
            if node_class:
                errors = node_class.validate_config(config)
                if errors:
                    raise serializers.ValidationError({"config": errors})

        return attrs


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

    source_node_id = serializers.UUIDField()
    target_node_id = serializers.UUIDField()
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
    project = serializers.PrimaryKeyRelatedField(
        queryset=Space.objects.all(), source="space"
    )
    space_name = serializers.CharField(source="space.name", read_only=True)
    created_by_name = serializers.CharField(
        source="created_by.username", read_only=True, allow_null=True
    )
    execution_count = serializers.SerializerMethodField()
    last_execution = serializers.SerializerMethodField()

    class Meta:
        model = Workflow
        fields = [
            "id",
            "name",
            "description",
            "icon",
            "project",
            "space_name",
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
        return obj.executions.count()

    def get_last_execution(self, obj: Workflow) -> dict | None:
        last = obj.executions.order_by("-created_at").first()
        if last:
            return {
                "id": str(last.id),
                "status": last.status,
                "created_at": last.created_at.isoformat(),
            }
        return None


class WorkflowListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for workflow list."""

    project = serializers.PrimaryKeyRelatedField(
        queryset=Space.objects.all(), source="space"
    )
    space_name = serializers.CharField(source="space.name", read_only=True)
    node_count = serializers.SerializerMethodField()
    execution_count = serializers.SerializerMethodField()
    last_execution = serializers.SerializerMethodField()
    node_summary = serializers.SerializerMethodField()
    edge_summary = serializers.SerializerMethodField()

    class Meta:
        model = Workflow
        fields = [
            "id",
            "name",
            "description",
            "icon",
            "project",
            "space_name",
            "trigger_type",
            "is_active",
            "is_template",
            "node_count",
            "execution_count",
            "last_execution",
            "node_summary",
            "edge_summary",
            "created_at",
            "updated_at",
        ]

    def get_node_count(self, obj: Workflow) -> int:
        return obj.nodes.count()

    def get_execution_count(self, obj: Workflow) -> int:
        return obj.executions.count()

    def get_last_execution(self, obj: Workflow) -> dict | None:
        last = obj.executions.order_by("-created_at").first()
        if last:
            return {
                "id": str(last.id),
                "status": last.status,
                "created_at": last.created_at.isoformat(),
            }
        return None

    def get_node_summary(self, obj: Workflow) -> list[dict]:
        return list(
            obj.nodes.order_by("created_at").values(
                "id", "node_type", "name", "position_x", "position_y"
            )
        )

    def get_edge_summary(self, obj: Workflow) -> list[dict]:
        return list(
            obj.edges.order_by("created_at").values(
                "source_node_id", "target_node_id"
            )
        )


class WorkflowCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating Workflow."""

    nodes = WorkflowNodeCreateSerializer(many=True, required=False)
    edges = WorkflowEdgeCreateSerializer(many=True, required=False)
    from_import = serializers.BooleanField(required=False, default=False, write_only=True)
    project = serializers.PrimaryKeyRelatedField(
        queryset=Space.objects.all(), source="space"
    )

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
            "from_import",
        ]

    def validate(self, attrs: dict) -> dict:
        """Validate node types when importing from JSON."""
        nodes_data = attrs.get("nodes", [])
        is_import = attrs.pop("from_import", False)

        if is_import and nodes_data:
            unknown_types: set[str] = set()
            for node_data in nodes_data:
                node_type = node_data.get("node_type")
                if node_type and not NodeRegistry.get(node_type):
                    unknown_types.add(node_type)

            if unknown_types:
                # registry 无列举方法（Pitfall 7），用 get_all().keys() 枚举已注册类型
                available = ", ".join(NodeRegistry.get_all().keys())
                raise serializers.ValidationError(
                    {
                        "nodes": [
                            f"Unknown node type(s): {', '.join(sorted(unknown_types))}. "
                            f"Available types: {available}"
                        ]
                    }
                )

        return attrs

    def create(self, validated_data: dict) -> Workflow:
        nodes_data = validated_data.pop("nodes", [])
        edges_data = validated_data.pop("edges", [])

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

    data = serializers.JSONField()

    def validate_data(self, value: dict) -> dict:
        if "workflow" not in value:
            raise serializers.ValidationError("Missing 'workflow' key in import data")
        if "nodes" not in value:
            raise serializers.ValidationError("Missing 'nodes' key in import data")
        return value


# =============================================================================
# Execution Serializers
# =============================================================================


class NodeSubStepSerializer(serializers.ModelSerializer):
    """Serializer for NodeSubStep."""

    class Meta:
        model = NodeSubStep
        fields = [
            "id",
            "name",
            "step_type",
            "step_order",
            "status",
            "input_data",
            "output_data",
            "started_at",
            "completed_at",
        ]


class NodeExecutionSerializer(serializers.ModelSerializer):
    """Serializer for NodeExecution."""

    node_name = serializers.CharField(source="node.name", read_only=True)
    node_type = serializers.CharField(source="node.node_type", read_only=True)
    duration = serializers.FloatField(read_only=True)
    sub_step_progress = serializers.SerializerMethodField()

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
            "logs",
            "error_code",
            "attempt",
            "approval_data",
            "container_id",
            "container_logs",
            "duration",
            "sub_step_progress",
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

    def get_sub_step_progress(self, obj: NodeExecution) -> dict | None:
        """返回子步骤进度摘要，无子步骤时返回 None。"""
        if obj.sub_step_total_count == 0:
            return None
        return {
            "completed": obj.sub_step_completed_count,
            "total": obj.sub_step_total_count,
        }


class NodeExecutionListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for node execution list."""

    node_name = serializers.CharField(source="node.name", read_only=True)
    node_type = serializers.CharField(source="node.node_type", read_only=True)
    sub_step_progress = serializers.SerializerMethodField()

    class Meta:
        model = NodeExecution
        fields = [
            "id",
            "node",
            "node_name",
            "node_type",
            "status",
            "attempt",
            "sub_step_progress",
            "started_at",
            "completed_at",
        ]

    def get_sub_step_progress(self, obj: NodeExecution) -> dict | None:
        """返回子步骤进度摘要，无子步骤时返回 None。"""
        if obj.sub_step_total_count == 0:
            return None
        return {
            "completed": obj.sub_step_completed_count,
            "total": obj.sub_step_total_count,
        }


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
    resumed_from = serializers.UUIDField(
        source="resumed_from_id", read_only=True, allow_null=True
    )

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
            "resumed_from",
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
            "is_debug",
            "debug_paused_at_node",
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
    resumed_from = serializers.UUIDField(
        source="resumed_from_id", read_only=True, allow_null=True
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
            "resumed_from",
            "total_nodes",
            "completed_nodes",
            "failed_nodes",
            "duration",
            "progress",
            "created_at",
            "started_at",
            "completed_at",
            "is_debug",
        ]


class WorkflowExecuteSerializer(serializers.Serializer):
    """Serializer for executing a workflow."""

    input_data = serializers.JSONField(required=False, default=dict)
    trigger_data = serializers.JSONField(required=False, default=dict)
    debug_mode = serializers.BooleanField(required=False, default=False)
    stop_before_node_id = serializers.CharField(required=False, allow_blank=True, default="")


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

    name = serializers.CharField()
    label = serializers.CharField()
    type = serializers.CharField()
    required = serializers.BooleanField()
    description = serializers.CharField()
    schema = serializers.JSONField(required=False, allow_null=True)
    # SLOT-03：能力契约形状标识（与 NodePort.shape: str = "" 同口径，空串=通配）。
    # 未声明则 DRF 静默剥离 get_schema() 写入的 shape，致前端 resolvePortShape 恒 undefined。
    shape = serializers.CharField(required=False, allow_blank=True, default="")


class NodeTypeSerializer(serializers.Serializer):
    """Serializer for node type definition (for frontend node palette)."""

    node_type = serializers.CharField()
    display_name = serializers.CharField()
    description = serializers.CharField()
    icon = serializers.CharField()
    category = serializers.CharField()
    config_schema = serializers.JSONField()
    ui_schema = serializers.JSONField(required=False, allow_null=True)
    default_config = serializers.JSONField(required=False)
    inputs = NodePortSerializer(many=True)
    outputs = NodePortSerializer(many=True)
    requires_container = serializers.BooleanField()
    is_blocking = serializers.BooleanField()
    execution_mode = serializers.CharField()


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


# =============================================================================
# ActionLog Serializers
# =============================================================================


class ActionLogSummarySerializer(serializers.ModelSerializer):
    """ActionLog 摘要 serializer（react-steps 列表用）。

    返回元数据和 payload 前 200 字符摘要，不包含完整 payload。
    """

    payload_summary: serializers.SerializerMethodField = serializers.SerializerMethodField()

    class Meta:
        from subagent.models import ActionLog

        model = ActionLog
        fields = [
            "id",
            "action_type",
            "sequence",
            "duration_ms",
            "timestamp",
            "payload_summary",
        ]

    def get_payload_summary(self, obj) -> str:
        """返回 payload 的摘要（前 200 字符）"""
        import json

        payload_str = json.dumps(obj.payload, ensure_ascii=False)
        if len(payload_str) <= 200:
            return payload_str
        return payload_str[:200] + "..."


class ActionLogDetailSerializer(serializers.ModelSerializer):
    """ActionLog 完整详情 serializer。"""

    class Meta:
        from subagent.models import ActionLog

        model = ActionLog
        fields = [
            "id",
            "session",
            "action_type",
            "sequence",
            "duration_ms",
            "timestamp",
            "payload",
            "created_at",
        ]


# =============================================================================
# AlertRule Serializers
# =============================================================================


class AlertRuleSerializer(serializers.ModelSerializer):
    """告警规则序列化器。"""

    workflow_name = serializers.CharField(source="workflow.name", read_only=True)
    project = serializers.PrimaryKeyRelatedField(
        queryset=Space.objects.all(), source="space"
    )
    space_name = serializers.CharField(source="space.name", read_only=True)
    condition_type_display = serializers.CharField(
        source="get_condition_type_display", read_only=True
    )
    action_type_display = serializers.CharField(
        source="get_action_type_display", read_only=True
    )

    class Meta:
        from workflows.models import AlertRule

        model = AlertRule
        fields = [
            "id",
            "workflow",
            "workflow_name",
            "project",
            "space_name",
            "name",
            "enabled",
            "condition_type",
            "condition_type_display",
            "condition_config",
            "action_type",
            "action_type_display",
            "action_config",
            "cooldown_seconds",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_condition_type(self, value: str) -> str:
        from workflows.models import AlertRule
        valid = [choice[0] for choice in AlertRule.CONDITION_TYPES]
        if value not in valid:
            raise serializers.ValidationError(
                f"无效的条件类型: {value}. 可选: {valid}"
            )
        return value

    def validate_action_type(self, value: str) -> str:
        from workflows.models import AlertRule
        valid = [choice[0] for choice in AlertRule.ACTION_TYPES]
        if value not in valid:
            raise serializers.ValidationError(
                f"无效的动作类型: {value}. 可选: {valid}"
            )
        return value

    def validate_action_config(self, value: dict) -> dict:
        action_type = self.initial_data.get("action_type")
        if action_type == "feishu_notification":
            if not value.get("chat_id"):
                raise serializers.ValidationError(
                    {"chat_id": "飞书通知动作必须提供 chat_id"}
                )
        elif action_type == "webhook":
            url = value.get("url", "")
            if not url:
                raise serializers.ValidationError(
                    {"url": "Webhook 动作必须提供 url"}
                )
            if not url.startswith(("http://", "https://")):
                raise serializers.ValidationError(
                    {"url": "Webhook URL 必须以 http:// 或 https:// 开头"}
                )
        return value


class AlertRuleExecutionSerializer(serializers.ModelSerializer):
    """告警规则执行记录序列化器（只读）。"""

    alert_rule_name = serializers.CharField(source="alert_rule.name", read_only=True)
    workflow_name = serializers.CharField(
        source="workflow_execution.workflow.name", read_only=True
    )

    class Meta:
        from workflows.models import AlertRuleExecution

        model = AlertRuleExecution
        fields = [
            "id",
            "alert_rule",
            "alert_rule_name",
            "workflow_execution",
            "workflow_name",
            "triggered_at",
            "status",
            "response_data",
            "error_message",
            "triggered_event",
        ]
        read_only_fields = fields
