"""Feishu serializers."""

from rest_framework import serializers

from .models import TriggerLog


class TriggerLogSerializer(serializers.ModelSerializer):
    """Serializer for TriggerLog list view."""

    space_id = serializers.UUIDField(source="project_id", read_only=True)
    space_name = serializers.SerializerMethodField()
    space_key = serializers.CharField(source="project_key", read_only=True)
    execution_status = serializers.SerializerMethodField()
    first_execution_id = serializers.SerializerMethodField()

    class Meta:
        model = TriggerLog
        fields = [
            "id",
            "created_at",
            "space_id",
            "space_name",
            "space_key",
            "event_type",
            "work_item_id",
            "work_item_name",
            "status",
            "prd_url",
            "description",
            "tech_doc_url",
            "execution_status",
            "first_execution_id",
        ]

    def get_space_name(self, obj):
        return obj.space.name if obj.space else None

    def get_execution_status(self, obj):
        """Get the latest workflow execution status."""
        latest = obj.workflow_executions.order_by("-created_at").first()
        return latest.status if latest else None

    def get_first_execution_id(self, obj) -> str | None:
        """Get the latest workflow execution ID for cross-navigation."""
        latest = obj.workflow_executions.order_by("-created_at").first()
        return str(latest.id) if latest else None


class TriggerLogDetailSerializer(TriggerLogSerializer):
    """Serializer for TriggerLog detail view."""

    webhook_raw_request_parsed = serializers.SerializerMethodField()
    work_item_raw_response_parsed = serializers.SerializerMethodField()
    workflow_executions = serializers.SerializerMethodField()

    class Meta(TriggerLogSerializer.Meta):
        fields = TriggerLogSerializer.Meta.fields + [
            "event_uuid",
            "work_item_type",
            "error_message",
            "webhook_raw_request_parsed",
            "work_item_raw_response_parsed",
            "workflow_executions",
        ]

    def get_webhook_raw_request_parsed(self, obj):
        """Parse webhook raw request JSON."""
        import json

        if not obj.webhook_raw_request:
            return None
        try:
            return json.loads(obj.webhook_raw_request)
        except (json.JSONDecodeError, TypeError):
            return None

    def get_work_item_raw_response_parsed(self, obj):
        """Parse work item raw response JSON."""
        import json

        if not obj.work_item_raw_response:
            return None
        try:
            return json.loads(obj.work_item_raw_response)
        except (json.JSONDecodeError, TypeError):
            return None

    def get_workflow_executions(self, obj):
        """Get related workflow executions."""
        executions = obj.workflow_executions.select_related("workflow").all()[:5]
        return [
            {
                "id": str(ex.id),
                "workflow_id": str(ex.workflow.id),
                "workflow_name": ex.workflow.name,
                "status": ex.status,
                "created_at": ex.created_at.isoformat(),
            }
            for ex in executions
        ]


class TriggerLogRawSerializer(serializers.Serializer):
    """Serializer for raw trigger log data."""

    webhook_request = serializers.JSONField()
    work_item_response = serializers.JSONField()


class FeishuConfigSerializer(serializers.Serializer):
    """Serializer for Feishu configuration."""

    project_key = serializers.CharField(source="feishu_project_key", read_only=True)
    plugin_id = serializers.CharField(source="feishu_plugin_id", read_only=True)
    user_key = serializers.CharField(source="feishu_user_key", read_only=True)
    has_plugin_secret = serializers.SerializerMethodField()
    is_configured = serializers.SerializerMethodField()

    def get_has_plugin_secret(self, obj):
        return bool(obj.feishu_plugin_secret_encrypted)

    def get_is_configured(self, obj):
        return obj.has_feishu_config()


class FeishuConfigCreateSerializer(serializers.Serializer):
    """Serializer for creating/updating Feishu configuration."""

    plugin_id = serializers.CharField()
    plugin_secret = serializers.CharField(write_only=True)
    user_key = serializers.CharField(required=False, allow_blank=True)


class WebhookTokenSerializer(serializers.Serializer):
    """Serializer for webhook token."""

    webhook_token = serializers.CharField()


class WebhookTokenUpdateSerializer(serializers.Serializer):
    """Serializer for updating webhook token."""

    token = serializers.CharField(max_length=32)
