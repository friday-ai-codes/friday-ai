"""Serializers for chat API."""
from rest_framework import serializers
class ChatMessageSerializer(serializers.Serializer):
 """Serializer for chat message."""
 role = serializers.ChoiceField(choices=["user", "assistant", "system"])
 content = serializers.CharField
class ChatCompletionRequestSerializer(serializers.Serializer):
 """Serializer for chat completion request."""
 model = serializers.CharField(help_text="模型 ID")
 messages = ChatMessageSerializer(many=True, help_text="消息列表")
 source = serializers.ChoiceField(
 choices=["system", "project"],
 default="system",
 help_text="配置来源",
 )
 project_id = serializers.IntegerField(
 required=False,
 allow_null=True,
 help_text="项目 ID（当 source=project 时必填）",
 )
 api_key = serializers.CharField(
 required=False,
 allow_null=True,
 allow_blank=True,
 help_text="临时 API Key（用于测试未保存的配置）",
 )
 base_url = serializers.CharField(
 required=False,
 allow_null=True,
 allow_blank=True,
 help_text="临时 Base URL（用于测试未保存的配置）",
 )
 max_tokens = serializers.IntegerField(
 default=4096,
 min_value=1,
 max_value=100000,
 help_text="最大 token 数",
 )
 def validate(self, attrs):
 """Validate the request."""
 if attrs.get("source") == "project" and not attrs.get("project_id"):
 # Check if temporary credentials are provided
 if not attrs.get("api_key"):
 raise serializers.ValidationError(
 {"project_id": "使用项目配置时必须提供 project_id 或临时 api_key"}
 )
 return attrs
class ModelsRequestSerializer(serializers.Serializer):
 """Serializer for models list request."""
 source = serializers.ChoiceField(
 choices=["system", "project"],
 default="system",
 help_text="配置来源",
 )
 project_id = serializers.IntegerField(
 required=False,
 allow_null=True,
 help_text="项目 ID（当 source=project 时必填）",
 )
 api_key = serializers.CharField(
 required=False,
 allow_null=True,
 allow_blank=True,
 help_text="临时 API Key（用于测试未保存的配置）",
 )
 base_url = serializers.CharField(
 required=False,
 allow_null=True,
 allow_blank=True,
 help_text="临时 Base URL（用于测试未保存的配置）",
 )
 def validate(self, attrs):
 """Validate the request."""
 if attrs.get("source") == "project" and not attrs.get("project_id"):
 if not attrs.get("api_key"):
 raise serializers.ValidationError(
 {"project_id": "使用项目配置时必须提供 project_id 或临时 api_key"}
 )
 return attrs
class ModelSerializer(serializers.Serializer):
 """Serializer for model info."""
 id = serializers.CharField
 name = serializers.CharField
 created = serializers.IntegerField(allow_null=True)
class ModelsResponseSerializer(serializers.Serializer):
 """Serializer for models list response."""
 models = ModelSerializer(many=True)
class ChatCompletionResponseSerializer(serializers.Serializer):
 """Serializer for chat completion response."""
 content = serializers.CharField
 model = serializers.CharField
 usage = serializers.DictField(child=serializers.IntegerField, allow_null=True)
