"""OpenAI 协议兼容层请求/响应序列化器（contract）。"""

from rest_framework import serializers


class _MessageSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=["system", "user", "assistant", "tool", "developer"])
    content = serializers.JSONField()
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
    model = serializers.CharField()
    messages = _MessageSerializer(many=True)
    stream = serializers.BooleanField(default=False)
    stream_options = _StreamOptionsSerializer(required=False)
    temperature = serializers.FloatField(required=False, min_value=0.0, max_value=2.0)
    max_tokens = serializers.IntegerField(required=False, min_value=1)
    # work item 扩展字段：指定检索范围
    repository_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        default=list,
    )
    project_id = serializers.UUIDField(required=False, allow_null=True)


class _AnthropicMessageSerializer(serializers.Serializer):
    """Anthropic Messages 单条消息：role 仅 user/assistant（system 走顶层字段）。"""

    role = serializers.ChoiceField(choices=["user", "assistant"])
    content = serializers.JSONField()

    def validate_content(self, value):
        """接受 string content 或 text/image_url content parts 数组。

        镜像 ``_MessageSerializer.validate_content``：Anthropic text block 形状
        ``{"type":"text","text":...}`` 与 OpenAI 一致；保留 zh-CN 错误文案。
        """
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


class AnthropicMessagesRequestSerializer(serializers.Serializer):
    """Anthropic Messages API 请求校验（POST /v1/messages）。

    与 OpenAI ``ChatCompletionsRequestSerializer`` 平行：``max_tokens`` 为
    Anthropic 必填字段（缺失/<1 → 400）；``system`` 为顶层可选字段（string 或
    content blocks 数组）；``messages`` role 仅 user/assistant。复用 work item 扩展
    字段 ``repository_ids`` / ``project_id`` 指定检索范围。
    """

    model = serializers.CharField()
    messages = _AnthropicMessageSerializer(many=True)
    max_tokens = serializers.IntegerField(required=True, min_value=1)
    system = serializers.JSONField(required=False)
    stream = serializers.BooleanField(default=False)
    temperature = serializers.FloatField(required=False, min_value=0.0, max_value=1.0)
    # 复用 work item 扩展字段：指定检索范围
    repository_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        default=list,
    )
    project_id = serializers.UUIDField(required=False, allow_null=True)
