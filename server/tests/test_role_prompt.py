"""角色化 System Prompt 测试。
测试 _build_system_prompt 函数的角色差异化行为。
Phase Task 7: async 化 + autouse fixture 强制 fallback 路径（避免测试依赖 DB seed 状态）。
"""
from __future__ import annotations
import pytest
from chat.conversation_service import ROLE_PROMPTS, _build_system_prompt
@pytest.mark.asyncio
class TestBuildSystemPrompt:
 """_build_system_prompt 角色化 prompt 测试（异步版 Phase）。
 每个测试通过 monkeypatch 强制 fallback 路径，不依赖 DB seed。
 """
 @pytest.fixture(autouse=True)
 def _force_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
 """强制 PROMPT_CENTER_DISABLED_KEYS 覆盖所有 chat fragment slug。"""
 disabled = ",".join([
 "chat.system.developer",
 "chat.system.pm",
 "chat.system.designer",
 "chat.system.qa",
 "chat.system.general",
 "chat.strategy.default",
 "chat.strategy.deep_analysis",
 "chat.coding_guidance",
 ])
 monkeypatch.setenv("PROMPT_CENTER_DISABLED_KEYS", disabled)
 async def test_developer_role_contains_tech_keywords(self) -> None:
 """developer 角色包含技术相关关键词。"""
 prompt = await _build_system_prompt("MyProject", "proj-1", role="developer")
 assert "代码" in prompt
 assert "技术" in prompt
 assert "架构" in prompt
 async def test_pm_role_contains_management_keywords(self) -> None:
 """pm 角色包含管理相关关键词。"""
 prompt = await _build_system_prompt("MyProject", "proj-1", role="pm")
 assert "进度" in prompt
 assert "风险" in prompt
 assert "优先级" in prompt
 async def test_designer_role_contains_ux_keywords(self) -> None:
 """designer 角色包含交互设计相关关键词。"""
 prompt = await _build_system_prompt("MyProject", "proj-1", role="designer")
 assert "交互" in prompt
 assert "视觉" in prompt
 assert "用户" in prompt
 async def test_qa_role_contains_testing_keywords(self) -> None:
 """qa 角色包含测试相关关键词。"""
 prompt = await _build_system_prompt("MyProject", "proj-1", role="qa")
 assert "测试" in prompt
 assert "边界" in prompt
 assert "缺陷" in prompt
 async def test_general_role_is_balanced(self) -> None:
 """general 角色平衡各维度。"""
 prompt = await _build_system_prompt("MyProject", "proj-1", role="general")
 assert "全能" in prompt
 assert "灵活" in prompt
 async def test_default_role_is_developer(self) -> None:
 """默认角色为 developer。"""
 prompt_default = await _build_system_prompt("MyProject", "proj-1")
 prompt_dev = await _build_system_prompt("MyProject", "proj-1", role="developer")
 assert prompt_default == prompt_dev
 async def test_invalid_role_falls_back_to_general(self) -> None:
 """无效角色回退到 general。"""
 prompt_invalid = await _build_system_prompt("MyProject", "proj-1", role="unknown_role")
 prompt_general = await _build_system_prompt("MyProject", "proj-1", role="general")
 assert prompt_invalid == prompt_general
 async def test_project_name_included(self) -> None:
 """prompt 包含项目名称。"""
 prompt = await _build_system_prompt("TestProject", "proj-1", role="developer")
 assert "TestProject" in prompt
 async def test_all_roles_have_reasonable_length(self) -> None:
 """所有角色 prompt 长度在合理范围内。
 Phase 在 developer / strategy / coding_guidance 各
 追加「准确性优先」段后，整体长度从 ~1100 增长到 ~3000+；上限同步
 放宽至 5000 留足后续 INTENT/RELEV phase 增量注入空间。
 """
 for role in ROLE_PROMPTS:
 prompt = await _build_system_prompt("P", "proj-1", role=role)
 assert 80 < len(prompt) < 5000, (
 f"Role '{role}' prompt length {len(prompt)} out of range"
 )
 async def test_all_five_roles_defined(self) -> None:
 """确认定义了 5 种角色。"""
 expected_roles = {"developer", "pm", "designer", "qa", "general"}
 assert set(ROLE_PROMPTS.keys) == expected_roles
 async def test_roles_are_distinct(self) -> None:
 """不同角色的 prompt 内容不同。"""
 prompts: dict[str, str] = {}
 for role in ROLE_PROMPTS:
 prompts[role] = await _build_system_prompt("P", "proj-1", role=role)
 # 两两不同
 roles = list(prompts.keys)
 for i in range(len(roles)):
 for j in range(i + 1, len(roles)):
 assert prompts[roles[i]] != prompts[roles[j]], (
 f"Role '{roles[i]}' and '{roles[j]}' have identical prompts"
 )
