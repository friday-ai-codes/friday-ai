"""work item: GET /api/providers/types/ schema 端点契约测试。

验证 schema-driven 前端数据源契约：
- 返回 5 Provider 元信息
- 每项含 `provider_type` + `credential_schema_json_schema`
- 各 Provider schema properties 字段集合符合 Pydantic credential_schema 约定
- 敏感字段（api_key / bearer_token）标注 SecretStr（format=password 或 anyOf 含 password）

本测试文件纯契约测试，消费 task-01 的 `system_admin_user` fixture；
DRF APIClient + force_authenticate 同步路径（与既有 test_provider_credential_permissions 一致）。
"""
from __future__ import annotations

import pytest
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_types_endpoint_returns_5_providers(system_admin_user) -> None:
    """GET /api/providers/types/ 返回 5 个 Provider 元信息。"""
    client = APIClient()
    client.force_authenticate(user=system_admin_user)
    resp = client.get("/api/providers/types/")
    assert resp.status_code == 200, resp.content
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 5

    provider_types = {item["provider_type"] for item in data}
    assert provider_types == {
        "anthropic",
        "openai_responses",
        "openai_chat",
        "gemini",
        "ollama",
    }, f"provider_types 不匹配: {provider_types}"


def _field_format_is_password(prop: dict) -> bool:
    """判断字段 schema 是否标注 SecretStr（format=password 或 anyOf 中含 format=password）。"""
    if prop.get("format") == "password":
        return True
    any_of = prop.get("anyOf", [])
    return any(
        isinstance(sub, dict) and sub.get("format") == "password" for sub in any_of
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "provider_type,expected_props,password_fields",
    [
        ("anthropic", {"api_key", "base_url"}, {"api_key"}),
        (
            "openai_responses",
            {"api_key", "base_url", "organization_id"},
            {"api_key"},
        ),
        ("openai_chat", {"api_key", "base_url", "organization_id"}, {"api_key"}),
        ("gemini", {"api_key"}, {"api_key"}),
        ("ollama", {"base_url", "bearer_token"}, {"bearer_token"}),
    ],
)
def test_types_endpoint_schema_properties(
    provider_type: str,
    expected_props: set,
    password_fields: set,
    system_admin_user,
) -> None:
    """各 Provider JSON Schema properties 集合包含预期字段 + SecretStr 字段标注为 password。"""
    client = APIClient()
    client.force_authenticate(user=system_admin_user)
    resp = client.get("/api/providers/types/")
    assert resp.status_code == 200, resp.content
    items = resp.json()
    meta = next((i for i in items if i["provider_type"] == provider_type), None)
    assert meta is not None, f"{provider_type} 元信息缺失"

    schema = meta["credential_schema_json_schema"]
    assert "properties" in schema, f"{provider_type} schema 缺 properties 键"

    actual_props = set(schema["properties"].keys())
    missing = expected_props - actual_props
    assert not missing, (
        f"{provider_type} schema 缺字段: {missing} (实际: {actual_props})"
    )

    # SecretStr 字段（api_key / bearer_token）必须标注 format=password
    for field in password_fields:
        prop = schema["properties"][field]
        assert _field_format_is_password(prop), (
            f"{provider_type}.{field} 应为 SecretStr（format=password），实际: {prop}"
        )
