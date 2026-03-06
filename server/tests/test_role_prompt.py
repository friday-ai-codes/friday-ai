"""角色化 System Prompt 测试。
测试 _build_system_prompt 函数的角色差异化行为。
纯函数测试，不需要数据库。
"""
from chat.conversation_service import ROLE_PROMPTS, _build_system_prompt
class TestBuildSystemPrompt:
 """_build_system_prompt 角色化 prompt 测试。"""
 def test_developer_role_contains_tech_keywords(self):
 """developer 角色包含技术相关关键词。"""
 prompt = _build_system_prompt("MyProject", role="developer")
 assert "代码" in prompt
 assert "技术" in prompt
 assert "架构" in prompt
 def test_pm_role_contains_management_keywords(self):
 """pm 角色包含管理相关关键词。"""
 prompt = _build_system_prompt("MyProject", role="pm")
 assert "进度" in prompt
 assert "风险" in prompt
 assert "优先级" in prompt
 def test_designer_role_contains_ux_keywords(self):
 """designer 角色包含交互设计相关关键词。"""
 prompt = _build_system_prompt("MyProject", role="designer")
 assert "交互" in prompt
 assert "视觉" in prompt
 assert "用户" in prompt
 def test_qa_role_contains_testing_keywords(self):
 """qa 角色包含测试相关关键词。"""
 prompt = _build_system_prompt("MyProject", role="qa")
 assert "测试" in prompt
 assert "边界" in prompt
 assert "缺陷" in prompt
 def test_general_role_is_balanced(self):
 """general 角色平衡各维度。"""
 prompt = _build_system_prompt("MyProject", role="general")
 assert "全能" in prompt
 assert "灵活" in prompt
 def test_default_role_is_developer(self):
 """默认角色为 developer。"""
 prompt_default = _build_system_prompt("MyProject")
 prompt_dev = _build_system_prompt("MyProject", role="developer")
 assert prompt_default == prompt_dev
 def test_invalid_role_falls_back_to_general(self):
 """无效角色回退到 general。"""
 prompt_invalid = _build_system_prompt("MyProject", role="unknown_role")
 prompt_general = _build_system_prompt("MyProject", role="general")
 assert prompt_invalid == prompt_general
 def test_project_name_included(self):
 """prompt 包含项目名称。"""
 prompt = _build_system_prompt("TestProject", role="developer")
 assert "TestProject" in prompt
 def test_all_roles_have_reasonable_length(self):
 """所有角色 prompt 长度在合理范围内（80-500 字符）。"""
 for role in ROLE_PROMPTS:
 prompt = _build_system_prompt("P", role=role)
 assert 80 < len(prompt) < 500, (
 f"Role '{role}' prompt length {len(prompt)} out of range"
 )
 def test_all_five_roles_defined(self):
 """确认定义了 5 种角色。"""
 expected_roles = {"developer", "pm", "designer", "qa", "general"}
 assert set(ROLE_PROMPTS.keys) == expected_roles
 def test_roles_are_distinct(self):
 """不同角色的 prompt 内容不同。"""
 prompts = {
 role: _build_system_prompt("P", role=role) for role in ROLE_PROMPTS
 }
 # 两两不同
 roles = list(prompts.keys)
 for i in range(len(roles)):
 for j in range(i + 1, len(roles)):
 assert prompts[roles[i]] != prompts[roles[j]], (
 f"Role '{roles[i]}' and '{roles[j]}' have identical prompts"
 )
