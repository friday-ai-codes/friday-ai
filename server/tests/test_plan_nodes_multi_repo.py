"""Unit tests for multi-repo plan generation nodes.
Tests GeneratePlanNode and TechnicalPlanNode with multi-repository
configuration and codebase context inputs.
"""
import json
from typing import Any
from workflows.nodes.ai.plan import GeneratePlanNode
from workflows.nodes.ai.technical_plan import TechnicalPlanNode
class MockExecutionContext:
 """Mock ExecutionContext for testing."""
 def __init__(
 self,
 node_config: dict[str, Any] | None = None,
 global_params: dict[str, Any] | None = None,
 ):
 self.node_config = node_config or {}
 self._global_params = global_params or {}
 self.input_data: dict[str, Any] = {}
 self.workflow_execution = None
 def render_template(self, template: str) -> str:
 """Simple template rendering for tests."""
 if not template:
 return ""
 # Handle {{global.xxx}} pattern
 for key, value in self._global_params.items:
 pattern = f"{{{{global.{key}}}}}"
 if pattern in template:
 if isinstance(value, (list, dict)):
 template = template.replace(pattern, json.dumps(value))
 else:
 template = template.replace(pattern, str(value))
 return template
 def get_global_param(self, key: str, default: Any = None) -> Any:
 """Get global parameter."""
 return self._global_params.get(key, default)
class TestGeneratePlanNodeConfigSchema:
 """Tests for GeneratePlanNode config schema."""
 def test_config_schema_has_repositories(self) -> None:
 """Test that config_schema includes repositories property."""
 node = GeneratePlanNode
 assert "repositories" in node.config_schema["properties"]
 def test_config_schema_has_codebase_context(self) -> None:
 """Test that config_schema includes codebase_context property."""
 node = GeneratePlanNode
 assert "codebase_context" in node.config_schema["properties"]
 def test_repositories_supports_array(self) -> None:
 """Test that repositories supports array type."""
 node = GeneratePlanNode
 repos_schema = node.config_schema["properties"]["repositories"]
 assert "oneOf" in repos_schema
 array_option = repos_schema["oneOf"][0]
 assert array_option["type"] == "array"
 def test_repositories_supports_template_string(self) -> None:
 """Test that repositories supports string type for templates."""
 node = GeneratePlanNode
 repos_schema = node.config_schema["properties"]["repositories"]
 assert "oneOf" in repos_schema
 string_option = repos_schema["oneOf"][1]
 assert string_option["type"] == "string"
class TestGeneratePlanNodePrompt:
 """Tests for GeneratePlanNode prompt building."""
 def test_build_prompt_with_repositories(self) -> None:
 """Test that prompt includes repository listing when provided."""
 node = GeneratePlanNode
 repositories = [
 {"id": "repo-1", "name": "frontend", "description": "Vue app"},
 {"id": "repo-2", "name": "backend", "description": "Django API"},
 ]
 prompt = node._build_plan_prompt(
 requirements="Build user login",
 codebase_info="",
 constraints="",
 detail_level="standard",
 include_tests=True,
 repositories=repositories,
 codebase_context="",
 )
 assert "## 可用代码仓库" in prompt
 assert "frontend" in prompt
 assert "backend" in prompt
 assert "repo-1" in prompt
 assert "repo-2" in prompt
 def test_build_prompt_with_codebase_context(self) -> None:
 """Test that prompt includes codebase context when provided."""
 node = GeneratePlanNode
 context = """
# File: src/auth/login.py
def authenticate(username, password):
 pass
"""
 prompt = node._build_plan_prompt(
 requirements="Improve login",
 codebase_info="",
 constraints="",
 detail_level="standard",
 include_tests=True,
 repositories=None,
 codebase_context=context,
 )
 assert "## 相关代码上下文" in prompt
 assert "authenticate" in prompt
 assert "从各仓库检索到的相关代码" in prompt
 def test_build_prompt_without_optional_params(self) -> None:
 """Test that prompt builds correctly without optional params."""
 node = GeneratePlanNode
 prompt = node._build_plan_prompt(
 requirements="Simple task",
 codebase_info="",
 constraints="",
 detail_level="standard",
 include_tests=False,
 repositories=None,
 codebase_context="",
 )
 assert "## 需求" in prompt
 assert "Simple task" in prompt
 assert "## 可用代码仓库" not in prompt
 assert "## 相关代码上下文" not in prompt
class TestTechnicalPlanNodeConfigSchema:
 """Tests for TechnicalPlanNode config schema."""
 def test_config_schema_has_codebase_context(self) -> None:
 """Test that config_schema includes codebase_context property."""
 node = TechnicalPlanNode
 assert "codebase_context" in node.config_schema["properties"]
 def test_codebase_context_has_default_empty(self) -> None:
 """Test that codebase_context has empty string default."""
 node = TechnicalPlanNode
 ctx_schema = node.config_schema["properties"]["codebase_context"]
 assert ctx_schema.get("default") == ""
class TestTechnicalPlanNodePrompt:
 """Tests for TechnicalPlanNode prompt building."""
 def test_build_prompt_with_codebase_context(self) -> None:
 """Test that prompt includes codebase context section."""
 node = TechnicalPlanNode
 repositories = [{"id": "1", "name": "main-repo", "description": "Main"}]
 context = """
# Retrieved from main-repo
class UserService:
 def get_user(self, user_id: int):
 pass
"""
 prompt = node._build_plan_prompt(
 work_item_name="Add user profile",
 description="Add profile page",
 prd_url="",
 repositories=repositories,
 detail_level="standard",
 include_tests=True,
 codebase_context=context,
 )
 assert "## 相关代码上下文" in prompt
 assert "UserService" in prompt
 assert "从各仓库检索到的相关代码" in prompt
 def test_build_prompt_has_cross_repo_instruction(self) -> None:
 """Test that prompt includes cross-repo interaction instruction."""
 node = TechnicalPlanNode
 prompt = node._build_plan_prompt(
 work_item_name="Feature",
 description="Description",
 prd_url="",
 repositories=,
 detail_level="standard",
 include_tests=True,
 codebase_context="some context",
 )
 assert "当涉及多个仓库间的交互" in prompt
 assert "coding_instruction 中明确引用相关仓库的代码" in prompt
 def test_build_prompt_without_codebase_context(self) -> None:
 """Test that prompt builds correctly without codebase context."""
 node = TechnicalPlanNode
 prompt = node._build_plan_prompt(
 work_item_name="Simple feature",
 description="Simple description",
 prd_url="",
 repositories=,
 detail_level="standard",
 include_tests=True,
 codebase_context="",
 )
 assert "## 需求信息" in prompt
 assert "## 相关代码上下文" not in prompt
