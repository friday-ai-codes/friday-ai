"""AI 节点 config_schema 验证测试。
验证 AIPromptNode、AIVariableExtractorNode、AIAgentBaseNode 的 config_schema
是否包含 max_thinking_tokens 和 max_budget_usd 配置字段。
"""
import pytest
from workflows.nodes.ai.base_agent import AIAgentBaseNode
from workflows.nodes.ai.prompt import AIPromptNode
from workflows.nodes.ai.variable_extractor import AIVariableExtractorNode
# ============================================================================
# AIPromptNode config_schema 测试
# ============================================================================
class TestAIPromptNodeConfig:
 """AIPromptNode config_schema 字段验证。"""
 def test_config_has_max_thinking_tokens(self) -> None:
 """AIPromptNode.config_schema 包含 max_thinking_tokens 字段。"""
 props = AIPromptNode.config_schema["properties"]
 assert "max_thinking_tokens" in props
 assert props["max_thinking_tokens"]["type"] == "integer"
 def test_config_has_max_budget_usd(self) -> None:
 """AIPromptNode.config_schema 包含 max_budget_usd 字段。"""
 props = AIPromptNode.config_schema["properties"]
 assert "max_budget_usd" in props
 assert props["max_budget_usd"]["type"] == "number"
 def test_max_thinking_tokens_bounds(self) -> None:
 """max_thinking_tokens 有合理的 min/max 约束。"""
 field = AIPromptNode.config_schema["properties"]["max_thinking_tokens"]
 assert field.get("minimum", 0) >= 1024
 assert field.get("maximum", 0) <= 128000
 def test_max_budget_usd_bounds(self) -> None:
 """max_budget_usd 有合理的 min/max 约束。"""
 field = AIPromptNode.config_schema["properties"]["max_budget_usd"]
 assert field.get("minimum", 0) >= 0.01
 assert field.get("maximum", 0) <= 100.0
# ============================================================================
# AIVariableExtractorNode config_schema 测试
# ============================================================================
class TestAIVariableExtractorNodeConfig:
 """AIVariableExtractorNode config_schema 字段验证。"""
 def test_config_has_max_thinking_tokens(self) -> None:
 """AIVariableExtractorNode.config_schema 包含 max_thinking_tokens 字段。"""
 props = AIVariableExtractorNode.config_schema["properties"]
 assert "max_thinking_tokens" in props
 assert props["max_thinking_tokens"]["type"] == "integer"
 def test_config_has_max_budget_usd(self) -> None:
 """AIVariableExtractorNode.config_schema 包含 max_budget_usd 字段。"""
 props = AIVariableExtractorNode.config_schema["properties"]
 assert "max_budget_usd" in props
 assert props["max_budget_usd"]["type"] == "number"
# ============================================================================
# AIAgentBaseNode config_schema 测试
# ============================================================================
class TestAIAgentBaseNodeConfig:
 """AIAgentBaseNode config_schema 字段验证。"""
 def test_config_has_max_thinking_tokens(self) -> None:
 """AIAgentBaseNode.config_schema 包含 max_thinking_tokens 字段。"""
 props = AIAgentBaseNode.config_schema["properties"]
 assert "max_thinking_tokens" in props
 assert props["max_thinking_tokens"]["type"] == "integer"
 def test_config_has_max_budget_usd(self) -> None:
 """AIAgentBaseNode.config_schema 包含 max_budget_usd 字段。"""
 props = AIAgentBaseNode.config_schema["properties"]
 assert "max_budget_usd" in props
 assert props["max_budget_usd"]["type"] == "number"
