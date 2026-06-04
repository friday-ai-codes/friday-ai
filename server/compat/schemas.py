"""OpenAI 协议兼容层请求/响应序列化器。"""
from rest_framework import serializers
class _MessageSerializer(serializers.Serializer):
 role = serializers.ChoiceField(choices=["system", "user", "assistant", "tool", "developer"])
 content = serializers.JSONField
 name = serializers.CharField(required=False, allow_blank=True)
 def validate_content(self, value):
 """Accept OpenAI string content or text/image_url content parts arrays."""
 if isinstance(value, str):
 return value
 if not isinstance(value, list):
 raise serializers.ValidationError("content 必须是字符串或 content parts 数组")
 for idx, part in enumerate(value):
 if not isinstance(part, dict):
 raise serializers.ValidationError(f"content[{idx}] 必须是对象")
 part_type = part.get("type")
 if part_type == "text":
 if not isinstance(part.get("text", ""), str):
 raise serializers.ValidationError(f"content[{idx}].text 必须是字符串")
 continue
 if part_type == "image_url":
 image_url = part.get("image_url")
 if isinstance(image_url, str):
 url = image_url
 elif isinstance(image_url, dict):
 url = image_url.get("url", "")
 else:
 url = ""
 if not isinstance(url, str) or not url:
 raise serializers.ValidationError(f"content[{idx}].image_url.url 必须是字符串")
 continue
 raise serializers.ValidationError(f"不支持的 content part type: {part_type}")
 return value
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
