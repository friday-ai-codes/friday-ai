"""Settings serializers。"""
from __future__ import annotations
import json
from typing import Any
from pydantic import BaseModel, SecretStr
from pydantic import ValidationError as PydanticValidationError
from rest_framework import serializers
from common.encryption import decrypt_value, encrypt_value
from .models import ProviderCredential, SystemSetting
class SystemSettingSerializer(serializers.ModelSerializer):
 """Serializer for SystemSetting model."""
 has_value = serializers.SerializerMethodField
 class Meta:
 model = SystemSetting
 fields = [
 "key",
 "value",
 "has_value",
 "is_encrypted",
 "description",
 "updated_at",
 ]
 read_only_fields = ["updated_at"]
 def get_has_value(self, obj):
 return bool(obj.value)
class SystemSettingCreateSerializer(serializers.ModelSerializer):
 """Serializer for creating SystemSetting."""
 class Meta:
 model = SystemSetting
 fields = ["key", "value", "is_encrypted", "description"]
class SystemSettingUpdateSerializer(serializers.Serializer):
 """Serializer for updating SystemSetting."""
 value = serializers.CharField(allow_blank=True, allow_null=True, required=False)
 is_encrypted = serializers.BooleanField(required=False)
 description = serializers.CharField(allow_blank=True, allow_null=True, required=False)
# ============================================================================
# Phase：ProviderCredential 三件套 Serializer（Read / Create / Update）
# ============================================================================
# Phase 既锁定的 5 种 ProviderType；Serializer 层 ChoiceField 做白名单防御
_PROVIDER_TYPE_CHOICES = [
 "anthropic",
 "openai_responses",
 "openai_chat",
 "gemini",
 "ollama",
]
def _pydantic_to_jsonable(model: BaseModel) -> dict[str, Any]:
 """把 Pydantic 校验结果转回 plain dict，SecretStr 字段 unwrap 为明文。
 model_dump(mode="python") 对 SecretStr 字段保留 SecretStr 对象（避免被序列化为
 "**********"），Serializer 层需显式 .get_secret_value 拿回明文再交给 encrypt_value。
 """
 data = model.model_dump(mode="python")
 for key, value in data.items:
 if isinstance(value, SecretStr):
 data[key] = value.get_secret_value
 return data
def _read_decrypted_config(obj: ProviderCredential) -> dict[str, Any]:
 """解密 encrypted_config 并 JSON 解析；失败返回空 dict（不泄漏异常细节）。"""
 try:
 plaintext = decrypt_value(obj.encrypted_config)
 parsed = json.loads(plaintext) if plaintext else {}
 return parsed if isinstance(parsed, dict) else {}
 except Exception:
 return {}
def _format_pydantic_errors(exc: PydanticValidationError) -> list[str]:
 """把 Pydantic ValidationError 展开成字符串列表，便于 DRF ValidationError 承载。
 Pydantic .errors 返回 list[dict]（含 loc/msg/type），但 DRF ValidationError 嵌套
 字典要求叶子节点是 str 或 str 列表。本函数统一成 [f"{loc}: {msg}"] 列表格式，
 前端 toast 可直接 join 展示；不含 input 明文（Phase hide_input_in_errors=True 保证）。
 """
 formatted: list[str] =
 for err in exc.errors:
 loc_parts = err.get("loc", )
 loc = ".".join(str(part) for part in loc_parts) if loc_parts else "config"
 msg = err.get("msg", "校验失败")
 formatted.append(f"{loc}: {msg}")
 return formatted or ["config 字段校验失败"]
class ProviderCredentialSerializer(serializers.ModelSerializer):
 """Provider 凭证读序列化器（retrieve / list）。
 严禁回显 encrypted_config 明文（Pitfall 3 防御）；派生字段仅暴露 api_key_last4
 末 4 位 + has_api_key 布尔，供前端编辑弹层显示"当前已配置密钥"提示。
 """
 api_key_last4 = serializers.SerializerMethodField
 has_api_key = serializers.SerializerMethodField
 class Meta:
 model = ProviderCredential
 fields = [
 "id",
 "provider_type",
 "name",
 "scope",
 "scope_id",
 "is_active",
 "last_health_check_at",
 "last_health_check_status",
 "last_health_check_error",
 "available_models",
 "api_key_last4",
 "has_api_key",
 "created_at",
 "updated_at",
 ]
 read_only_fields = fields
 def get_api_key_last4(self, obj: ProviderCredential) -> str:
 """返回 api_key（或 bearer_token）末 4 位；解密失败或字段不存在返回空串。"""
 config = _read_decrypted_config(obj)
 key = config.get("api_key") or config.get("bearer_token") or ""
 if not isinstance(key, str) or len(key) < 4:
 return ""
 return f"...{key[-4:]}"
 def get_has_api_key(self, obj: ProviderCredential) -> bool:
 """是否已配置 api_key / bearer_token；Ollama 无鉴权场景可为 False。"""
 config = _read_decrypted_config(obj)
 return bool(config.get("api_key") or config.get("bearer_token"))
class ProviderCredentialCreateSerializer(serializers.Serializer):
 """Provider 凭证创建序列化器。
 schema-driven：按 provider_type dispatch PROVIDER_REGISTRY[type].credential_schema
 做 Pydantic v2 校验，统一承载 5 种 Provider 凭证字段约束 + SecretStr 脱敏。
 校验通过后，config dict 经 encrypt_value(json.dumps(...)) 写入 encrypted_config 字段，
 严禁落盘明文（Phase 加密契约）。
 """
 provider_type = serializers.ChoiceField(choices=_PROVIDER_TYPE_CHOICES)
 name = serializers.CharField(max_length=64)
 scope = serializers.ChoiceField(choices=["system", "project"])
 scope_id = serializers.UUIDField(required=False, allow_null=True)
 config = serializers.DictField
 is_active = serializers.BooleanField(default=True)
 def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
 """scope 一致性 + Pydantic credential_schema dispatch 校验。"""
 scope = attrs["scope"]
 scope_id = attrs.get("scope_id")
 # scope 与 scope_id 互斥一致性
 if scope == "project" and not scope_id:
 raise serializers.ValidationError(
 {"scope_id": "scope='project' 时 scope_id 必填"}
 )
 if scope == "system" and scope_id:
 raise serializers.ValidationError(
 {"scope_id": "scope='system' 时 scope_id 必须为空"}
 )
 # Pydantic credential_schema 按 provider_type dispatch 校验
 from services.provider_config import PROVIDER_REGISTRY, ProviderType
 provider_type = attrs["provider_type"]
 try:
 provider_enum = ProviderType(provider_type)
 except ValueError as exc:
 raise serializers.ValidationError(
 {"provider_type": f"不支持的 Provider 类型：{provider_type}"}
 ) from exc
 meta = PROVIDER_REGISTRY.get(provider_enum)
 if meta is None:
 raise serializers.ValidationError(
 {"provider_type": f"不支持的 Provider 类型：{provider_type}"}
 )
 try:
 validated = meta.credential_schema.model_validate(attrs["config"])
 except PydanticValidationError as exc:
 # Phase 已锁 ConfigDict(hide_input_in_errors=True)，errors 不含明文输入
 # 把 Pydantic 的 list[dict] errors 转成字段化 dict 以符合 DRF ValidationError 结构
 raise serializers.ValidationError(
 {"config": _format_pydantic_errors(exc)}
 ) from exc
 # 把 Pydantic 校验过的结构化 config（SecretStr unwrap）写入额外字段，供 create 使用
 attrs["_validated_config"] = _pydantic_to_jsonable(validated)
 return attrs
 def create(self, validated_data: dict[str, Any]) -> ProviderCredential:
 """把 _validated_config dict Fernet 加密后入库。"""
 config_dict = validated_data.pop("_validated_config")
 validated_data.pop("config", None) # 严禁写明文 config 字段
 encrypted = encrypt_value(json.dumps(config_dict, ensure_ascii=False))
 return ProviderCredential.objects.create(
 encrypted_config=encrypted,
 **validated_data,
 )
class ProviderCredentialUpdateSerializer(serializers.Serializer):
 """Provider 凭证部分更新序列化器（PATCH 语义）。
 config 字段 Pitfall 3 防御：
 - 请求体不含 config 键 → 保留原 encrypted_config 不变
 - config=None → 同上
 - config={...} 完整字段 → 按 instance.provider_type Pydantic 校验后重新加密写入
 PUT（完整替换）语义由 DRF ViewSet 根据 action 路由，本 Serializer 同时承担
 update / partial_update 两种场景，通过 required=False 的字段表达。
 """
 name = serializers.CharField(max_length=64, required=False)
 scope = serializers.ChoiceField(choices=["system", "project"], required=False)
 scope_id = serializers.UUIDField(required=False, allow_null=True)
 config = serializers.DictField(required=False, allow_null=True)
 is_active = serializers.BooleanField(required=False)
 def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
 """含 config 时按 instance.provider_type dispatch Pydantic 校验。"""
 new_config = attrs.get("config")
 if new_config:
 from services.provider_config import PROVIDER_REGISTRY, ProviderType
 instance: ProviderCredential = self.instance # type: ignore[assignment]
 provider_type = instance.provider_type
 try:
 provider_enum = ProviderType(provider_type)
 except ValueError as exc:
 raise serializers.ValidationError(
 {"provider_type": f"不支持的 Provider 类型：{provider_type}"}
 ) from exc
 meta = PROVIDER_REGISTRY.get(provider_enum)
 if meta is None:
 raise serializers.ValidationError(
 {"provider_type": f"不支持的 Provider 类型：{provider_type}"}
 )
 try:
 validated = meta.credential_schema.model_validate(new_config)
 except PydanticValidationError as exc:
 raise serializers.ValidationError(
 {"config": _format_pydantic_errors(exc)}
 ) from exc
 attrs["_validated_config"] = _pydantic_to_jsonable(validated)
 return attrs
 def update(
 self,
 instance: ProviderCredential,
 validated_data: dict[str, Any],
 ) -> ProviderCredential:
 """按字段分派：_validated_config 走 encrypt_value 重写，其余字段原地赋值。"""
 if "_validated_config" in validated_data:
 new_config = validated_data.pop("_validated_config")
 instance.encrypted_config = encrypt_value(
 json.dumps(new_config, ensure_ascii=False)
 )
 # config 明文字段不入库（已由 _validated_config 代替）
 validated_data.pop("config", None)
 for attr, value in validated_data.items:
 setattr(instance, attr, value)
 instance.save
 return instance
# ============================================================================
# Phase：Provider 类型元信息 Serializer（schema-driven 前端数据源）
# ============================================================================
class ProviderTypeMetaSerializer(serializers.Serializer):
 """GET /api/providers/types/ 单项序列化。
 每个 Provider 元信息 + credential_schema 的 Pydantic JSON Schema 一次性返回，
 前端 ProviderCredentialForm.vue 据此动态渲染字段（ schema-driven），
 新增 Provider 时仅需更新后端 PROVIDER_REGISTRY，前端无需改代码。
 """
 provider_type = serializers.CharField
 display_name = serializers.CharField
 langchain_prefix = serializers.CharField
 api_format = serializers.CharField
 credential_type = serializers.CharField
 default_base_url = serializers.CharField(allow_blank=True)
 supports_thinking = serializers.BooleanField
 supports_reasoning = serializers.BooleanField
 supports_vision = serializers.BooleanField
 supports_function_calling = serializers.BooleanField
 supports_streaming = serializers.BooleanField
 # Pydantic BaseModel.model_json_schema 输出：通常含 properties / required / $defs
 credential_schema_json_schema = serializers.DictField
