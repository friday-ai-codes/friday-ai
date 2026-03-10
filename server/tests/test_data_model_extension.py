"""Phase: 数据模型扩展测试。
覆盖 至 需求：验证模型字段定义、SettingKeys 更新、迁移兼容性。
"""
import pytest
from agents.llm.providers import ProviderType
from system.models import SettingKeys
class TestConversationProviderType:
 """: Conversation 模型有 provider_type 字段。"""
 def test_field_exists_and_nullable(self):
 """provider_type 字段存在且可为空。"""
 from chat.models import Conversation
 field = Conversation._meta.get_field("provider_type")
 assert field.null is True
 assert field.blank is True
 assert field.max_length == 50
 def test_field_type_is_char(self):
 """provider_type 是 CharField（非 JSONField）。"""
 from chat.models import Conversation
 field = Conversation._meta.get_field("provider_type")
 assert field.get_internal_type == "CharField"
class TestSettingKeysUpdate:
 """: SettingKeys 新增配置键。"""
 def test_new_keys_exist(self):
 """新配置键存在且值正确。"""
 assert SettingKeys.DEFAULT_PROVIDER_TYPE == "default_provider_type"
 def test_removed_keys_no_longer_exist(self):
 """已移除的 OpenAI/Google 配置键不再存在。"""
 assert not hasattr(SettingKeys, "OPENAI_API_KEY")
 assert not hasattr(SettingKeys, "GOOGLE_API_KEY")
 assert not hasattr(SettingKeys, "GOOGLE_SERVICE_ACCOUNT_JSON")
 def test_old_keys_removed(self):
 """旧配置键已删除。"""
 assert not hasattr(SettingKeys, "PROVIDER_TYPE")
 assert not hasattr(SettingKeys, "LLM_PROVIDER_TYPE")
 def test_existing_keys_preserved(self):
 """现有配置键未受影响。"""
 assert SettingKeys.ANTHROPIC_API_KEY == "anthropic_api_key"
 assert SettingKeys.ANTHROPIC_BASE_URL == "anthropic_base_url"
 assert SettingKeys.ANTHROPIC_MODEL == "anthropic_model"
class TestProjectProviderFields:
 """: Project 模型新增 default_provider_type 和 default_model。"""
 def test_default_provider_type_field(self):
 """default_provider_type 字段存在且可为空。"""
 from projects.models import Project
 field = Project._meta.get_field("default_provider_type")
 assert field.null is True
 assert field.blank is True
 assert field.max_length == 50
 def test_default_model_field(self):
 """default_model 字段存在且可为空。"""
 from projects.models import Project
 field = Project._meta.get_field("default_model")
 assert field.null is True
 assert field.blank is True
 assert field.max_length == 200
 def test_old_claude_fields_preserved(self):
 """旧的 claude_* 字段仍然存在。"""
 from projects.models import Project
 # 确保旧字段未被删除或修改
 Project._meta.get_field("claude_api_key_encrypted")
 Project._meta.get_field("claude_base_url")
 Project._meta.get_field("claude_default_model")
class TestMigrationBackwardCompatible:
 """: 迁移向后兼容。"""
 def test_all_new_fields_nullable(self):
 """所有新增字段都是可选的（null=True）。"""
 from chat.models import Conversation
 from projects.models import Project
 from workflows.models.execution import NodeExecution, WorkflowExecution
 fields_to_check = [
 (Conversation, "provider_type"),
 (Project, "default_provider_type"),
 (Project, "default_model"),
 (WorkflowExecution, "provider_type"),
 (NodeExecution, "provider_type"),
 ]
 for model, field_name in fields_to_check:
 field = model._meta.get_field(field_name)
 assert field.null is True, f"{model.__name__}.{field_name} must be nullable"
 assert field.blank is True, f"{model.__name__}.{field_name} must be blankable"
class TestWorkflowExecutionProviderType:
 """: WorkflowExecution 和 NodeExecution 记录 provider_type。"""
 def test_workflow_execution_has_provider_type(self):
 """WorkflowExecution 有 provider_type 字段。"""
 from workflows.models.execution import WorkflowExecution
 field = WorkflowExecution._meta.get_field("provider_type")
 assert field.null is True
 assert field.max_length == 50
 def test_node_execution_has_provider_type(self):
 """NodeExecution 有独立的 provider_type 字段（非 JSON）。"""
 from workflows.models.execution import NodeExecution
 field = NodeExecution._meta.get_field("provider_type")
 assert field.null is True
 assert field.max_length == 50
 # 确保是独立字段，非 JSONField
 assert field.get_internal_type == "CharField"
 def test_provider_type_fields_are_independent(self):
 """WorkflowExecution 和 NodeExecution 的 provider_type 是各自独立的字段。"""
 from workflows.models.execution import NodeExecution, WorkflowExecution
 we_field = WorkflowExecution._meta.get_field("provider_type")
 ne_field = NodeExecution._meta.get_field("provider_type")
 # 确认是不同的字段对象
 assert we_field is not ne_field
