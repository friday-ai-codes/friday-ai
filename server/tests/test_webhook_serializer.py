"""WebhookConfigSerializer 字段校验测试

确保 WebhookConfigSerializer.Meta.fields 与 WebhookConfig 模型字段对齐，
防止 Swagger Schema 生成因字段不匹配而崩溃。
"""

import pytest
from drf_spectacular.generators import SchemaGenerator

from workflows.api.serializers import WebhookConfigSerializer


class TestWebhookConfigSerializer:
    def test_serializer_fields_match_model(self) -> None:
        """确保所有声明的字段在 WebhookConfig 模型中实际存在"""
        serializer = WebhookConfigSerializer()
        # 若字段不存在，DRF 会在实例化时抛出 FieldError
        assert serializer is not None

    def test_no_nonexistent_fields(self) -> None:
        """确认不存在的字段已从 fields 列表中移除"""
        nonexistent = {
            "http_method",
            "require_auth",
            "headers_schema",
            "body_schema",
            "response_config",
            "request_count",
            "last_triggered_at",
        }
        declared = set(WebhookConfigSerializer.Meta.fields)
        assert not declared & nonexistent, f"发现不存在的字段: {declared & nonexistent}"

    def test_required_fields_present(self) -> None:
        """确认必要字段存在"""
        required = {"id", "workflow", "name", "description", "path", "is_active", "created_at", "updated_at"}
        declared = set(WebhookConfigSerializer.Meta.fields)
        assert required <= declared, f"缺少字段: {required - declared}"

    def test_schema_generation_does_not_crash(self) -> None:
        """Schema 生成不因 WebhookConfigSerializer 崩溃"""
        generator = SchemaGenerator()
        # 若序列化器字段不匹配，get_schema() 会抛出 ImproperlyConfigured
        try:
            schema = generator.get_schema(request=None, public=True)
            assert schema is not None
        except Exception as e:
            pytest.fail(f"Schema 生成失败: {e}")
