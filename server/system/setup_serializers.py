"""首启向导 Phase 4：飞书 / 向量检索可选配置的请求体序列化器。

仅承载请求体字段校验；落库由 view 走既有 `SystemSetting` + `encrypt_value` 路径完成，
本模块不持久化、不回显敏感值（app_secret / api_key 均 write_only / 不回读）。
"""

from __future__ import annotations

from rest_framework import serializers


class SetupFeishuSerializer(serializers.Serializer):
    """飞书集成配置入参（FEISHU-01/02）。"""

    app_id = serializers.CharField(allow_blank=False)
    app_secret = serializers.CharField(write_only=True, trim_whitespace=False, allow_blank=False)

    def validate_app_id(self, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise serializers.ValidationError("请填写飞书 App ID")
        return cleaned

    def validate_app_secret(self, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise serializers.ValidationError("请填写飞书 App Secret")
        return cleaned


class SetupRagSerializer(serializers.Serializer):
    """向量检索配置入参（RAG-01/02）。

    仅 `qdrant_url` 必填；其余字段可选（留空即不写入对应设置）。敏感项的加密落库由 view 处理。
    """

    qdrant_url = serializers.CharField(allow_blank=False)
    qdrant_api_key = serializers.CharField(
        write_only=True, trim_whitespace=False, required=False, allow_blank=True
    )
    embedding_api_url = serializers.CharField(required=False, allow_blank=True)
    embedding_api_key = serializers.CharField(
        write_only=True, trim_whitespace=False, required=False, allow_blank=True
    )
    embedding_model = serializers.CharField(required=False, allow_blank=True)
    embedding_dimension = serializers.IntegerField(required=False, allow_null=True, min_value=1)

    def validate_qdrant_url(self, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise serializers.ValidationError("请填写 Qdrant 地址")
        return cleaned
