"""Phase Plan：aresolve_or_error Result 模式 + 四层优先级测试。
覆盖 Requirement:,
威胁参考: T- (credential cache 污染), T- (ValidationError 泄漏)
"""
from __future__ import annotations
import dataclasses
import json
from typing import Any
import pytest
from asgiref.sync import sync_to_async
from common.encryption import encrypt_value
from services.provider_config import (
 PROVIDER_REGISTRY,
 ProviderConfigError,
 ProviderConfigService,
 ProviderMissingError,
 ProviderType,
 ResolvedProviderConfig,
)
from system.models import ProviderCredential, SettingKeys, SystemSetting
# ============================================================================
# Helpers
# ============================================================================
def _make_credential(
 provider_type: str = "anthropic",
 config_dict: dict[str, Any] | None = None,
 **overrides: Any,
) -> ProviderCredential:
 """创建 ProviderCredential（参照 PATTERNS.md ）。"""
 payload = config_dict if config_dict is not None else {
 "api_key": "sk-ant-test",
 "base_url": "https://api.anthropic.com",
 }
 defaults: dict[str, Any] = dict(
 provider_type=provider_type,
 name="default",
 scope="system",
 scope_id=None,
 encrypted_config=encrypt_value(json.dumps(payload)),
 base_url="",
 default_model="",
 is_active=True,
 )
 defaults.update(overrides)
 return ProviderCredential.objects.create(**defaults)
# ============================================================================
# Task 1 契约：ProviderMissingError dataclass + 向后兼容字段
# ============================================================================
class TestProviderMissingErrorShape:
 """：ProviderMissingError 结构化契约（锁死字段 / 默认值 / frozen）。"""
 def test_provider_missing_error_default_code(self) -> None:
 """code 默认值锁死 'provider_credential_missing'（Phase 前端分支依赖）。"""
 err = ProviderMissingError(missing_provider="openai_chat")
 assert err.code == "provider_credential_missing"
 assert err.missing_provider == "openai_chat"
 assert err.recommended_action == ""
 assert err.source_attempted == ""
 def test_provider_missing_error_frozen(self) -> None:
 """frozen dataclass 修改字段抛 FrozenInstanceError（防上层污染返回值）。"""
 err = ProviderMissingError(missing_provider="anthropic")
 with pytest.raises(dataclasses.FrozenInstanceError):
 err.code = "other" # type: ignore[misc]
class TestResolvedProviderConfigBackwardCompat:
 """：ResolvedProviderConfig 新字段向后兼容（不传 credential_id / extra 能构造）。"""
 def test_resolved_provider_config_extended_fields_optional(self) -> None:
 """不传 credential_id / extra 仍能构造（ChatAnthropicRunner 零改动契约）。"""
 resolved = ResolvedProviderConfig(
 provider_type=ProviderType.ANTHROPIC,
 api_key="sk-ant-x",
 base_url="https://api.anthropic.com",
 source="system",
 )
 assert resolved.credential_id is None
 assert resolved.extra == {}
 def test_resolved_provider_config_backward_compat_attrs(self) -> None:
 """老调用方（ChatAnthropicRunner）访问 api_key / base_url / source 仍可用。"""
 resolved = ResolvedProviderConfig(
 provider_type=ProviderType.ANTHROPIC,
 api_key="sk-x",
 base_url="https://api.anthropic.com",
 source="node",
 )
 assert resolved.api_key == "sk-x"
 assert resolved.base_url == "https://api.anthropic.com"
 assert resolved.source == "node"
# ============================================================================
# Task 2 契约：aresolve_or_error 四层优先级 + SystemSetting 降级 + Pydantic 校验
# ============================================================================
@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestAResolveOrError:
 """ +：Result 模式入口行为契约。"""
 async def test_returns_resolved_when_anthropic_credential_exists(self) -> None:
 """系统级 ProviderCredential 存在 → 返回 ResolvedProviderConfig。"""
 cred = await sync_to_async(_make_credential)(
 provider_type="anthropic",
 config_dict={
 "api_key": "sk-ant-resolved",
 "base_url": "https://api.anthropic.com",
 },
 )
 result = await ProviderConfigService.aresolve_or_error
 assert isinstance(result, ResolvedProviderConfig), (
 f"expected ResolvedProviderConfig, got {type(result).__name__}"
 )
 assert result.api_key == "sk-ant-resolved"
 assert result.source == "system"
 assert result.credential_id == cred.id
 assert result.provider_type == ProviderType.ANTHROPIC
 async def test_returns_missing_when_no_credential_and_no_systemsetting(
 self,
 ) -> None:
 """DB 无 OpenAI 凭证 + SystemSetting 亦无 → ProviderMissingError（不降级）。"""
 result = await ProviderConfigService.aresolve_or_error(
 node_config={"provider_type": "openai_chat"},
 )
 assert isinstance(result, ProviderMissingError)
 assert result.missing_provider == "openai_chat"
 assert "OpenAI" in result.recommended_action
 assert result.source_attempted == "system"
 assert result.code == "provider_credential_missing"
 async def test_systemsetting_fallback_only_for_anthropic(self) -> None:
 """无 ProviderCredential 但 SystemSetting.ANTHROPIC_API_KEY 存在 → 降级返回（legacy 路径）。"""
 await sync_to_async(SystemSetting.objects.create)(
 key=SettingKeys.ANTHROPIC_API_KEY,
 value="sk-ant-legacy",
 )
 result = await ProviderConfigService.aresolve_or_error
 assert isinstance(result, ResolvedProviderConfig)
 assert result.api_key == "sk-ant-legacy"
 assert result.source == "system"
 assert result.credential_id is None # 降级路径不带 credential_id
 async def test_no_systemsetting_fallback_for_non_anthropic(self) -> None:
 """node_config 选 openai_chat + 仅 Anthropic SystemSetting → 不降级。"""
 await sync_to_async(SystemSetting.objects.create)(
 key=SettingKeys.ANTHROPIC_API_KEY,
 value="sk-ant-x",
 )
 result = await ProviderConfigService.aresolve_or_error(
 node_config={"provider_type": "openai_chat"},
 )
 assert isinstance(result, ProviderMissingError)
 assert result.missing_provider == "openai_chat"
 async def test_priority_node_over_system(self) -> None:
 """节点级 provider_type 优先（ Happy Path）。"""
 # 同时存在 Anthropic + OpenAI 系统级凭证
 await sync_to_async(_make_credential)(
 provider_type="anthropic",
 config_dict={"api_key": "sk-ant-sys"},
 )
 openai_cred = await sync_to_async(_make_credential)(
 provider_type="openai_chat",
 config_dict={"api_key": "sk-openai-sys"},
 )
 result = await ProviderConfigService.aresolve_or_error(
 node_config={"provider_type": "openai_chat"},
 )
 assert isinstance(result, ResolvedProviderConfig)
 assert result.api_key == "sk-openai-sys"
 assert result.credential_id == openai_cred.id
 assert result.provider_type == ProviderType.OPENAI_CHAT
 async def test_validation_error_no_credential_leak_T225_05(
 self, caplog: Any
 ) -> None:
 """凭证 schema 校验失败 → ProviderMissingError + 日志不回显 raw api_key。"""
 # encrypted_config 缺 api_key 必填字段 → Pydantic ValidationError
 await sync_to_async(_make_credential)(
 provider_type="anthropic",
 config_dict={"base_url": "https://api.anthropic.com"},
 )
 result = await ProviderConfigService.aresolve_or_error
 assert isinstance(result, ProviderMissingError)
 assert result.missing_provider == "anthropic"
 # 断言日志中**不**出现任何 raw 字段值泄漏
 log_text = "\n".join(rec.message for rec in caplog.records)
 assert "sk-ant-" not in log_text, f"日志含 raw api_key: {log_text}"
 async def test_extra_field_populated_for_openai_organization_id(self) -> None:
 """OpenAI organization_id 字段通过 extra 传递（非 api_key/base_url 字段）。"""
 await sync_to_async(_make_credential)(
 provider_type="openai_chat",
 config_dict={
 "api_key": "sk-openai-org",
 "base_url": "https://api.openai.com/v1",
 "organization_id": "org-test-123",
 },
 )
 result = await ProviderConfigService.aresolve_or_error(
 node_config={"provider_type": "openai_chat"},
 )
 assert isinstance(result, ResolvedProviderConfig)
 assert result.api_key == "sk-openai-org"
 assert result.extra.get("organization_id") == "org-test-123"
@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestAResolveLegacy:
 """ 向后兼容：aresolve 旧 API 仍抛 ProviderConfigError。"""
 async def test_aresolve_still_raises_provider_config_error_when_missing(
 self,
 ) -> None:
 """ChatAnthropicRunner / coding_graph 现有调用方零改动契约。"""
 with pytest.raises(ProviderConfigError):
 await ProviderConfigService.aresolve(
 node_config={"provider_type": "openai_chat"},
 )
 async def test_aresolve_returns_resolved_on_success(self) -> None:
 """凭证存在时 aresolve 返回 ResolvedProviderConfig（正常路径）。"""
 await sync_to_async(_make_credential)(
 provider_type="anthropic",
 config_dict={"api_key": "sk-ant-happy"},
 )
 result = await ProviderConfigService.aresolve
 assert isinstance(result, ResolvedProviderConfig)
 assert result.api_key == "sk-ant-happy"
 assert result.source == "system"
# ============================================================================
# PROVIDER_REGISTRY 基础自检（保证 Plan 交付未被本 Plan 破坏）
# ============================================================================
def test_registry_contains_five_providers_still -> None:
 assert len(PROVIDER_REGISTRY) == 5
 for pt in (
 ProviderType.ANTHROPIC,
 ProviderType.OPENAI_CHAT,
 ProviderType.OPENAI_RESPONSES,
 ProviderType.GEMINI,
 ProviderType.OLLAMA,
 ):
 assert pt in PROVIDER_REGISTRY
