"""ProviderConfigService 测试 — 四层配置优先级解析和凭据验证。
覆盖,,,,, 需求。
"""
import pytest
from agents.llm.providers import ProviderType
from system.models import SettingKeys, SystemSetting
# ============================================================================
# Fixtures
# ============================================================================
@pytest.fixture
def system_setting_anthropic(db):
 """创建 Anthropic 系统级配置。"""
 SystemSetting.objects.create(
 key=SettingKeys.DEFAULT_PROVIDER_TYPE,
 value="anthropic",
 )
 SystemSetting.objects.create(
 key=SettingKeys.ANTHROPIC_API_KEY,
 value="sk-ant-test-key",
 )
 SystemSetting.objects.create(
 key=SettingKeys.ANTHROPIC_BASE_URL,
 value="https://api.anthropic.com",
 )
@pytest.fixture
def project_with_provider(db):
 """创建带 default_provider_type 的项目。"""
 from projects.models import Project
 return Project.objects.create(
 name="Test Provider Project",
 default_provider_type="anthropic",
 )
@pytest.fixture
def conversation_with_provider(db, project_with_provider):
 """创建带 provider_type 的对话。"""
 from chat.models import Conversation
 return Conversation.objects.create(
 project=project_with_provider,
 title="Test Conversation",
 provider_type="anthropic",
 )
# ============================================================================
# Plan: ProviderConfigService 核心测试
# ============================================================================
class TestProviderConfigServiceResolve:
 """测试 ProviderConfigService 四层配置优先级解析。"""
 @pytest.mark.django_db
 def test_resolve_system_level(self, system_setting_anthropic):
 """系统级：前三层都无时，使用系统级 DEFAULT_PROVIDER_TYPE。"""
 from services.provider_config import ProviderConfigService
 result = ProviderConfigService.resolve
 assert result.provider_type == ProviderType.ANTHROPIC
 assert result.api_key == "sk-ant-test-key"
 assert result.source == "system"
 @pytest.mark.django_db
 def test_resolve_project_level(self, system_setting_anthropic, project_with_provider):
 """项目级：project.default_provider_type 优先于系统级。"""
 from services.provider_config import ProviderConfigService
 result = ProviderConfigService.resolve(project=project_with_provider)
 assert result.provider_type == ProviderType.ANTHROPIC
 assert result.source == "project"
 @pytest.mark.django_db
 def test_resolve_conversation_level(
 self, system_setting_anthropic, conversation_with_provider
 ):
 """对话级：conversation.provider_type 优先于项目级和系统级。"""
 from services.provider_config import ProviderConfigService
 result = ProviderConfigService.resolve(
 conversation=conversation_with_provider,
 project=conversation_with_provider.project,
 )
 assert result.provider_type == ProviderType.ANTHROPIC
 assert result.source == "conversation"
 @pytest.mark.django_db
 def test_resolve_node_level(self, system_setting_anthropic):
 """节点级：node_config 的 provider_type 优先于所有其他层级。"""
 from services.provider_config import ProviderConfigService
 result = ProviderConfigService.resolve(
 node_config={"provider_type": "anthropic"},
 )
 assert result.provider_type == ProviderType.ANTHROPIC
 assert result.source == "node"
 @pytest.mark.django_db
 def test_resolve_priority_node_over_conversation(
 self, system_setting_anthropic, conversation_with_provider
 ):
 """节点级优先于对话级。"""
 from services.provider_config import ProviderConfigService
 result = ProviderConfigService.resolve(
 node_config={"provider_type": "anthropic"},
 conversation=conversation_with_provider,
 )
 assert result.provider_type == ProviderType.ANTHROPIC
 assert result.source == "node"
 @pytest.mark.django_db
 def test_resolve_priority_conversation_over_project(
 self, system_setting_anthropic, conversation_with_provider
 ):
 """对话级优先于项目级。"""
 from services.provider_config import ProviderConfigService
 result = ProviderConfigService.resolve(
 conversation=conversation_with_provider,
 project=conversation_with_provider.project,
 )
 assert result.provider_type == ProviderType.ANTHROPIC
 assert result.source == "conversation"
 @pytest.mark.django_db
 def test_resolve_no_provider_type_anywhere_raises(self, db):
 """四层都没有 provider_type 时抛出 ProviderConfigError。"""
 from services.provider_config import ProviderConfigError, ProviderConfigService
 with pytest.raises(ProviderConfigError, match="未找到 Provider 配置"):
 ProviderConfigService.resolve
 @pytest.mark.django_db
 def test_resolve_missing_credential_raises(self, db):
 """provider_type 有值但对应凭据为空时抛出 ProviderConfigError。"""
 from services.provider_config import ProviderConfigError, ProviderConfigService
 SystemSetting.objects.create(
 key=SettingKeys.DEFAULT_PROVIDER_TYPE,
 value="anthropic",
 )
 # 没有配置 ANTHROPIC_API_KEY
 with pytest.raises(ProviderConfigError, match="Anthropic Claude"):
 ProviderConfigService.resolve
 @pytest.mark.django_db
 def test_resolve_api_key_credential(self, system_setting_anthropic):
 """Anthropic Provider 正确查找 anthropic_api_key。"""
 from services.provider_config import ProviderConfigService
 result = ProviderConfigService.resolve
 assert result.api_key == "sk-ant-test-key"
 @pytest.mark.django_db
 def test_resolve_returns_default_base_url(self, system_setting_anthropic):
 """返回 PROVIDER_REGISTRY 中的 default_base_url。"""
 from services.provider_config import ProviderConfigService
 result = ProviderConfigService.resolve
 assert result.base_url == "https://api.anthropic.com"
 @pytest.mark.django_db
 def test_resolve_skips_none_conversation(self, system_setting_anthropic):
 """conversation 参数为 None 时跳过对话级。"""
 from services.provider_config import ProviderConfigService
 result = ProviderConfigService.resolve(conversation=None)
 assert result.provider_type == ProviderType.ANTHROPIC
 assert result.source == "system"
 @pytest.mark.django_db
 def test_resolve_skips_none_project(self, system_setting_anthropic):
 """project 参数为 None 时跳过项目级。"""
 from services.provider_config import ProviderConfigService
 result = ProviderConfigService.resolve(project=None)
 assert result.provider_type == ProviderType.ANTHROPIC
 assert result.source == "system"
class TestProviderConfigServiceAresolve:
 """测试 ProviderConfigService 异步版本。"""
 @pytest.mark.django_db(transaction=True)
 @pytest.mark.asyncio
 async def test_aresolve_system_level(self, system_setting_anthropic):
 """异步版本：系统级解析正确。"""
 from services.provider_config import ProviderConfigService
 result = await ProviderConfigService.aresolve
 assert result.provider_type == ProviderType.ANTHROPIC
 assert result.api_key == "sk-ant-test-key"
 assert result.source == "system"
 @pytest.mark.django_db(transaction=True)
 @pytest.mark.asyncio
 async def test_aresolve_node_level(self, system_setting_anthropic):
 """异步版本：节点级解析正确。"""
 from services.provider_config import ProviderConfigService
 result = await ProviderConfigService.aresolve(
 node_config={"provider_type": "anthropic"},
 )
 assert result.provider_type == ProviderType.ANTHROPIC
 assert result.source == "node"
 @pytest.mark.django_db(transaction=True)
 @pytest.mark.asyncio
 async def test_aresolve_no_provider_raises(self):
 """异步版本：四层都无 provider_type 时抛出错误。"""
 from services.provider_config import ProviderConfigError, ProviderConfigService
 with pytest.raises(ProviderConfigError, match="未找到 Provider 配置"):
 await ProviderConfigService.aresolve
 @pytest.mark.django_db(transaction=True)
 @pytest.mark.asyncio
 async def test_aresolve_missing_credential_raises(self):
 """异步版本：凭据缺失时抛出包含 Provider 名称的错误。"""
 from asgiref.sync import sync_to_async
 from services.provider_config import ProviderConfigError, ProviderConfigService
 await sync_to_async(SystemSetting.objects.create)(
 key=SettingKeys.DEFAULT_PROVIDER_TYPE,
 value="anthropic",
 )
 with pytest.raises(ProviderConfigError, match="Anthropic Claude"):
 await ProviderConfigService.aresolve
