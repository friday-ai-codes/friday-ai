"""OpenAI 协议兼容层请求/响应序列化器。"""
from rest_framework import serializers
class _MessageSerializer(serializers.Serializer):
 role = serializers.ChoiceField(choices=["system", "user", "assistant", "tool", "developer"])
 content = serializers.CharField(allow_blank=True)
 name = serializers.CharField(required=False, allow_blank=True)
class _StreamOptionsSerializer(serializers.Serializer):
 include_usage = serializers.BooleanField(default=False)
class ChatCompletionsRequestSerializer(serializers.Serializer):
 model = serializers.CharField
 messages = _MessageSerializer(many=True)
 stream = serializers.BooleanField(default=False)
 stream_options = _StreamOptionsSerializer(required=False)
 temperature = serializers.FloatField(required=False, min_value=0.0, max_value=2.0)
 max_tokens = serializers.IntegerField(required=False, min_value=1)
 # 扩展字段：指定检索范围
 repository_ids = serializers.ListField(
 child=serializers.UUIDField,
 required=False,
 default=list,
 )
 project_id = serializers.UUIDField(required=False, allow_null=True)
