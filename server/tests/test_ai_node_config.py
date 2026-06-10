"""implementation Wave（task）：AI 节点 config_schema JSON Schema 验证测试。

覆盖范围（implementation plan Task 3 <action> 6 测试函数）：

- test_base_agent_config_schema_has_provider_credential_id
  AIAgentBaseNode.config_schema 含 provider_credential_id 字段（type=string, format=uuid）
- test_ai_prompt_node_config_schema_has_provider_credential_id
  AIPromptNode 同上
- test_variable_extractor_node_config_schema_has_provider_credential_id
  AIVariableExtractorNode 同上
- test_provider_credential_id_is_optional
  默认空字符串不触发 required
- test_provider_credential_id_accepts_valid_uuid_string
  jsonschema 校验合法 UUID 字符串通过
- test_max_budget_usd_preserved_in_all_three_nodes
  work item 守护：max_budget_usd 字段在 3 节点保留

task 已把 provider_credential_id 追加到 3 节点 config_schema；
本 implementation plan Task 3 在 JSON Schema 层面守护字段契约不被后续 plan 误删。
"""

from __future__ import annotations

import jsonschema
import pytest


# ============================================================================
# Test 1-3：3 节点 config_schema 含 provider_credential_id
# ============================================================================


def test_base_agent_config_schema_has_provider_credential_id() -> None:
    """AIAgentBaseNode.config_schema 含 provider_credential_id 字段。"""
    from workflows.nodes.ai.base_agent import AIAgentBaseNode

    props = AIAgentBaseNode.config_schema.get("properties", {})
    assert "provider_credential_id" in props, (
        "AIAgentBaseNode.config_schema 缺失 provider_credential_id 字段"
    )
    field = props["provider_credential_id"]
    assert field["type"] == "string", f"type 应为 string，实际 {field.get('type')}"
    assert field.get("format") == "uuid", (
        f"format 应为 uuid，实际 {field.get('format')}"
    )
    assert field.get("default", "") == "", (
        f"default 应为空字符串，实际 {field.get('default')}"
    )


def test_ai_prompt_node_config_schema_has_provider_credential_id() -> None:
    """AIPromptNode.config_schema 含 provider_credential_id 字段。"""
    from workflows.nodes.ai.prompt import AIPromptNode

    props = AIPromptNode.config_schema.get("properties", {})
    assert "provider_credential_id" in props, (
        "AIPromptNode.config_schema 缺失 provider_credential_id 字段"
    )
    field = props["provider_credential_id"]
    assert field["type"] == "string"
    assert field.get("format") == "uuid"


def test_variable_extractor_node_config_schema_has_provider_credential_id() -> None:
    """AIVariableExtractorNode.config_schema 含 provider_credential_id 字段。"""
    from workflows.nodes.ai.variable_extractor import AIVariableExtractorNode

    props = AIVariableExtractorNode.config_schema.get("properties", {})
    assert "provider_credential_id" in props, (
        "AIVariableExtractorNode.config_schema 缺失 provider_credential_id 字段"
    )
    field = props["provider_credential_id"]
    assert field["type"] == "string"
    assert field.get("format") == "uuid"


# ============================================================================
# Test 4：provider_credential_id 为 optional（不在 required 列表）
# ============================================================================


def test_provider_credential_id_is_optional() -> None:
    """provider_credential_id 默认空字符串不触发 required（3 节点共同契约）。"""
    from workflows.nodes.ai.base_agent import AIAgentBaseNode
    from workflows.nodes.ai.prompt import AIPromptNode
    from workflows.nodes.ai.variable_extractor import AIVariableExtractorNode

    for cls in (AIAgentBaseNode, AIPromptNode, AIVariableExtractorNode):
        required = cls.config_schema.get("required", [])
        assert "provider_credential_id" not in required, (
            f"{cls.__name__}.config_schema['required'] 不应包含 provider_credential_id；"
            f"实际 required={required}"
        )


# ============================================================================
# Test 5：JSON Schema 校验合法 UUID 字符串通过
# ============================================================================


def test_provider_credential_id_accepts_valid_uuid_string() -> None:
    """jsonschema 校验合法 UUID 字符串通过（3 节点 schema 对齐 JSON Schema 规范）。"""
    from workflows.nodes.ai.base_agent import AIAgentBaseNode
    from workflows.nodes.ai.prompt import AIPromptNode
    from workflows.nodes.ai.variable_extractor import AIVariableExtractorNode

    valid_uuid = "550e8400-e29b-41d4-a716-446655440000"

    for cls in (AIAgentBaseNode, AIPromptNode, AIVariableExtractorNode):
        props = cls.config_schema["properties"]
        # 仅针对 provider_credential_id 字段做 schema 校验（避开其他 required 字段）
        sub_schema = {"type": "string", **props["provider_credential_id"]}
        # 合法 UUID 通过
        jsonschema.validate(valid_uuid, sub_schema)
        # 空字符串也通过（format=uuid 在未使用 FORMAT_CHECKER 时不强制校验）
        jsonschema.validate("", sub_schema)


# ============================================================================
# Test 6：work item 守护 —— max_budget_usd 在 3 节点保留
# ============================================================================


def test_max_budget_usd_preserved_in_all_three_nodes() -> None:
    """work item 守护：max_budget_usd 字段在 3 节点 config_schema 保留不变。

    该字段 implementation contract 激活（成本追踪 Dashboard），禁止本 phase 删除。
    """
    from workflows.nodes.ai.base_agent import AIAgentBaseNode
    from workflows.nodes.ai.prompt import AIPromptNode
    from workflows.nodes.ai.variable_extractor import AIVariableExtractorNode

    for cls in (AIAgentBaseNode, AIPromptNode, AIVariableExtractorNode):
        props = cls.config_schema.get("properties", {})
        assert "max_budget_usd" in props, (
            f"{cls.__name__} 缺少 max_budget_usd 字段（work item 违反）"
        )
        field = props["max_budget_usd"]
        assert field["type"] == "number", (
            f"{cls.__name__}.max_budget_usd.type 应为 number"
        )


# ============================================================================
# Test 7（派生）：AIVariableExtractorNode 不含 max_output_tokens（Anti-pattern H 守护）
# ============================================================================


def test_variable_extractor_has_no_max_output_tokens() -> None:
    """Anti-pattern H / contract 守护：AIVariableExtractorNode 不含 max_output_tokens 字段。

    contract 字段矩阵明确：max_output_tokens 在 AIAgentBaseNode / AIPromptNode 加；
    AIVariableExtractorNode 单 turn 简单提取，capabilities 默认 max_output_tokens 足够。
    """
    from workflows.nodes.ai.variable_extractor import AIVariableExtractorNode

    props = AIVariableExtractorNode.config_schema.get("properties", {})
    assert "max_output_tokens" not in props, (
        f"AIVariableExtractorNode 不应含 max_output_tokens 字段（Anti-pattern H 违反）；"
        f"实际 properties keys={list(props.keys())}"
    )


# ============================================================================
# Test 8（派生）：3 节点 config_schema top-level type == "object"
# ============================================================================


def test_three_node_config_schema_shape_is_object() -> None:
    """JSON Schema 顶层结构：type='object' + properties dict + required list。"""
    from workflows.nodes.ai.base_agent import AIAgentBaseNode
    from workflows.nodes.ai.prompt import AIPromptNode
    from workflows.nodes.ai.variable_extractor import AIVariableExtractorNode

    for cls in (AIAgentBaseNode, AIPromptNode, AIVariableExtractorNode):
        schema = cls.config_schema
        assert schema.get("type") == "object", (
            f"{cls.__name__}.config_schema.type 应为 object"
        )
        assert isinstance(schema.get("properties"), dict), (
            f"{cls.__name__}.config_schema.properties 应为 dict"
        )
        assert isinstance(schema.get("required", []), list), (
            f"{cls.__name__}.config_schema.required 应为 list"
        )
