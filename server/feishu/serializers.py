"""Feishu serializers."""
from rest_framework import serializers
from .models import TriggerLog
class TriggerLogSerializer(serializers.ModelSerializer):
 """Serializer for TriggerLog list view."""
 project_name = serializers.SerializerMethodField
 class Meta:
 model = TriggerLog
 fields = [
 "id",
 "created_at",
 "project_id",
 "project_name",
 "project_key",
 "event_type",
 "work_item_id",
 "work_item_name",
 "status",
 "prd_url",
 "description",
 "tech_doc_url",
 ]
 def get_project_name(self, obj):
 return obj.project.name if obj.project else None
class TriggerLogDetailSerializer(TriggerLogSerializer):
 """Serializer for TriggerLog detail view."""
 class Meta(TriggerLogSerializer.Meta):
 fields = TriggerLogSerializer.Meta.fields + [
 "event_uuid",
 "work_item_type",
 "error_message",
 ]
class TriggerLogRawSerializer(serializers.Serializer):
 """Serializer for raw trigger log data."""
 webhook_request = serializers.JSONField
 work_item_response = serializers.JSONField
class FeishuConfigSerializer(serializers.Serializer):
 """Serializer for Feishu configuration."""
 project_key = serializers.CharField(source="feishu_project_key", read_only=True)
 plugin_id = serializers.CharField(source="feishu_plugin_id", read_only=True)
 user_key = serializers.CharField(source="feishu_user_key", read_only=True)
 has_plugin_secret = serializers.SerializerMethodField
 is_configured = serializers.SerializerMethodField
 def get_has_plugin_secret(self, obj):
 return bool(obj.feishu_plugin_secret_encrypted)
 def get_is_configured(self, obj):
 return obj.has_feishu_config
class FeishuConfigCreateSerializer(serializers.Serializer):
 """Serializer for creating/updating Feishu configuration."""
 plugin_id = serializers.CharField
 plugin_secret = serializers.CharField(write_only=True)
 user_key = serializers.CharField(required=False, allow_blank=True)
class WebhookTokenSerializer(serializers.Serializer):
 """Serializer for webhook token."""
 webhook_token = serializers.CharField
class WebhookTokenUpdateSerializer(serializers.Serializer):
 """Serializer for updating webhook token."""
 token = serializers.CharField(max_length=32)
