"""Settings serializers。"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, SecretStr
from pydantic import ValidationError as PydanticValidationError
from rest_framework import serializers

from common.encryption import decrypt_value, encrypt_value
from services.model_modalities import infer_model_modalities

from .models import ProviderCredential, SystemLogEntry, SystemSetting


class SystemSettingSerializer(serializers.ModelSerializer):
    """Serializer for SystemSetting model."""

    has_value = serializers.SerializerMethodField()

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


class SystemLogEntrySerializer(serializers.ModelSerializer):
    """系统日志条目只读序列化器（LOG-01 查询）。

    暴露落库的全部可读字段；``payload`` / ``correlation`` 已在 71-02 写入前脱敏，
    此处只读直出，绝不含明文凭证（脱敏契约）。全字段 read_only（查询端点不写）。
    """

    class Meta:
        model = SystemLogEntry
        fields = [
            "id",
            "ts",
            "level",
            "component",
            "category",
            "event",
            "message",
            "user_id",
            "source",
            "trace_id",
            "request_id",
            "payload",
            "correlation",
        ]
        read_only_fields = fields


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
# implementation contract：ProviderCredential 三件套 Serializer（Read / Create / Update）
# ============================================================================

# implementation 既锁定的 5 种 ProviderType；Serializer 层 ChoiceField 做白名单防御
_PROVIDER_TYPE_CHOICES = [
    "anthropic",
    "openai_responses",
    "openai_chat",
    "gemini",
    "ollama",
]


def _normalize_available_models(
    value: Any,
    *,
    provider_type: str | None = None,
) -> list[dict[str, Any]]:
    """把前端/上游模型清单统一成 [{id, display_name, ...}] 并去重。"""
    if not isinstance(value, list):
        raise serializers.ValidationError("available_models 必须是数组")

    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, str):
            model_id = item.strip()
            model: dict[str, Any] = {"id": model_id, "display_name": model_id}
        elif isinstance(item, dict):
            raw_id = item.get("id") or item.get("name")
            model_id = str(raw_id or "").strip()
            model = {
                "id": model_id,
                "display_name": str(
                    item.get("display_name") or item.get("name") or model_id
                ).strip(),
            }
            for key in (
                "context_length",
                "supports_tools",
                "supports_vision",
                "input_modalities",
                "output_modalities",
                "capability_source",
            ):
                if key in item:
                    model[key] = item[key]
        else:
            raise serializers.ValidationError("available_models 每一项必须是模型 ID 字符串或对象")

        if not model_id:
            raise serializers.ValidationError("available_models 中存在空模型 ID")
        modalities, source = infer_model_modalities(
            provider_type=provider_type,
            model_id=model_id,
            raw_model=model,
        )
        model["input_modalities"] = modalities
        model["supports_vision"] = "image" in modalities
        model["capability_source"] = str(model.get("capability_source") or source)
        if model_id in seen:
            continue
        seen.add(model_id)
        normalized.append(model)

    return normalized


def _validate_bound_models(
    *,
    available_models: list[dict[str, Any]],
    default_model: str,
) -> None:
    """校验 Provider 至少绑定一个模型，且默认模型来自绑定清单。"""
    if not available_models:
        raise serializers.ValidationError(
            {"available_models": "每个 Provider 必须至少绑定一个模型"}
        )
    if not default_model.strip():
        raise serializers.ValidationError({"default_model": "每个 Provider 必须选择一个默认模型"})
    model_ids = {str(m.get("id") or "") for m in available_models}
    if default_model.strip() not in model_ids:
        raise serializers.ValidationError(
            {"default_model": "默认模型必须来自该 Provider 的模型列表"}
        )


def _pydantic_to_jsonable(model: BaseModel) -> dict[str, Any]:
    """把 Pydantic 校验结果转回 plain dict，SecretStr 字段 unwrap 为明文。

    model_dump(mode="python") 对 SecretStr 字段保留 SecretStr 对象（避免被序列化为
    "**********"），Serializer 层需显式 .get_secret_value() 拿回明文再交给 encrypt_value。
    """
    data = model.model_dump(mode="python")
    for key, value in data.items():
        if isinstance(value, SecretStr):
            data[key] = value.get_secret_value()
    return data


def _read_decrypted_config(obj: ProviderCredential) -> dict[str, Any]:
    """解密 encrypted_config 并 JSON 解析；失败返回空 dict（不泄漏异常细节）。"""
    try:
        plaintext = decrypt_value(obj.encrypted_config)
        parsed = json.loads(plaintext) if plaintext else {}
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


# Read 序列化器明文回显白名单（base_url / organization_id 等非密字段任意读者可见）。
_NON_SECRET_CONFIG_KEYS = frozenset({"base_url", "organization_id"})
# 严格秘密字段：仅写权限用户（superuser 或 project MEMBER+）才能拿到明文。
_SECRET_CONFIG_KEYS = frozenset({"api_key", "bearer_token"})


def _user_can_reveal_secrets(request: Any, obj: ProviderCredential) -> bool:
    """判断 request.user 是否对 obj 拥有写权限（=可看明文 api_key/bearer_token）。

    与 ProviderCredentialPermission.has_object_permission 写分支保持一致：
    - superuser → True
    - scope='system' 非 superuser → False（系统级写仅 superuser 可达）
    - scope='project' → 校验 PermissionService.has_project_access(MEMBER+)
    """
    if request is None:
        return False
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    if obj.scope == "project" and obj.scope_id:
        from permissions.models import ProjectRole
        from permissions.services import PermissionService
        from projects.models import Project

        project = Project.objects.filter(id=obj.scope_id).first()
        if project is None:
            return False
        return PermissionService.has_project_access(user, project, ProjectRole.MEMBER)
    return False


def _format_pydantic_errors(exc: PydanticValidationError) -> list[str]:
    """把 Pydantic ValidationError 展开成字符串列表，便于 DRF ValidationError 承载。

    Pydantic .errors() 返回 list[dict]（含 loc/msg/type），但 DRF ValidationError 嵌套
    字典要求叶子节点是 str 或 str 列表。本函数统一成 [f"{loc}: {msg}"] 列表格式，
    前端 toast 可直接 join 展示；不含 input 明文（implementation hide_input_in_errors=True 保证）。
    """
    formatted: list[str] = []
    for err in exc.errors():
        loc_parts = err.get("loc", ())
        loc = ".".join(str(part) for part in loc_parts) if loc_parts else "config"
        msg = err.get("msg", "校验失败")
        formatted.append(f"{loc}: {msg}")
    return formatted or ["config 字段校验失败"]


class ProviderCredentialSerializer(serializers.ModelSerializer):
    """Provider 凭证读序列化器（retrieve / list）。

    config 字段策略（Pitfall 3 重新校准）：
    - 非密字段（base_url / organization_id）：所有可读用户均回显，编辑表单需要回显校对。
    - 密字段（api_key / bearer_token）：仅"对该凭证有写权限"的用户才能拿到明文，
      与 ProviderCredentialPermission 写分支判定一致；其他读者仍只能拿到 api_key_last4。
    场景：admin/providers 编辑表单需要把已配置的 base_url / api_key 回显进 input，
    所以契约从"严禁回显明文"放宽为"按写权限分级回显"，写权限即等价于"本来就可改回该值"，
    不引入新的越权读取面（详见 _user_can_reveal_secrets）。
    """

    api_key_last4 = serializers.SerializerMethodField()
    has_api_key = serializers.SerializerMethodField()
    config = serializers.SerializerMethodField()
    available_models = serializers.SerializerMethodField()

    class Meta:
        model = ProviderCredential
        fields = [
            "id",
            "provider_type",
            "name",
            "scope",
            "scope_id",
            "is_active",
            "is_default",
            "default_model",
            "max_concurrency",
            "last_health_check_at",
            "last_health_check_status",
            "last_health_check_error",
            "available_models",
            "api_key_last4",
            "has_api_key",
            "config",
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

    def get_available_models(self, obj: ProviderCredential) -> list[dict[str, Any]]:
        """读路径统一返回对象数组，兼容历史 string[] 数据。"""
        try:
            return _normalize_available_models(
                obj.available_models or [],
                provider_type=obj.provider_type,
            )
        except serializers.ValidationError:
            return []

    def get_config(self, obj: ProviderCredential) -> dict[str, Any]:
        """按写权限分级回显已解密 config。

        - 始终包含 _NON_SECRET_CONFIG_KEYS（base_url / organization_id 等）。
        - 仅当 _user_can_reveal_secrets 判定为 True 时附加 _SECRET_CONFIG_KEYS。
        - 解密失败、字段不存在均按"无该 key"处理，不抛异常。
        """
        decrypted = _read_decrypted_config(obj)
        if not decrypted:
            return {}
        result: dict[str, Any] = {
            key: decrypted[key] for key in _NON_SECRET_CONFIG_KEYS if key in decrypted
        }
        request = self.context.get("request")
        if _user_can_reveal_secrets(request, obj):
            for key in _SECRET_CONFIG_KEYS:
                if key in decrypted:
                    result[key] = decrypted[key]
        return result


class ProviderCredentialCreateSerializer(serializers.Serializer):
    """Provider 凭证创建序列化器。

    contract schema-driven：按 provider_type dispatch PROVIDER_REGISTRY[type].credential_schema
    做 Pydantic v2 校验，统一承载 5 种 Provider 凭证字段约束 + SecretStr 脱敏。
    校验通过后，config dict 经 encrypt_value(json.dumps(...)) 写入 encrypted_config 字段，
    严禁落盘明文（implementation 加密契约）。

    Pitfall 7：需显式声明 `id` read_only 字段。DRF 默认用本 Serializer 序列化
    POST 201 响应；若缺少 `id`，前端 store 把响应数据插入列表后该凭证无 id，
    后续编辑 / toggle / 测试连接等操作均会因 id 缺失而 URL 变成 /undefined/。
    """

    id = serializers.UUIDField(read_only=True)
    provider_type = serializers.ChoiceField(choices=_PROVIDER_TYPE_CHOICES)
    name = serializers.CharField(max_length=64)
    scope = serializers.ChoiceField(choices=["system", "project"])
    scope_id = serializers.UUIDField(required=False, allow_null=True)
    # write_only：`config` 只用于请求体校验与加密写库，不在 POST 201 response.data 中回显
    # （ProviderCredential 实例无 `config` 属性，get_success_headers 读 serializer.data 会触发
    # AttributeError；同时契约上也严禁明文回显）。
    config = serializers.DictField(write_only=True)
    is_active = serializers.BooleanField(default=True)
    is_default = serializers.BooleanField(required=False, default=False)
    default_model = serializers.CharField(max_length=128, required=True, allow_blank=False)
    available_models = serializers.JSONField(required=True)
    # CONC-02：该凭证 LLM 并发上限（0=不限，默认 50）
    max_concurrency = serializers.IntegerField(required=False, default=50, min_value=0)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """scope 一致性 + Pydantic credential_schema dispatch 校验 + default_model 必填。"""
        scope = attrs["scope"]
        scope_id = attrs.get("scope_id")

        # scope 与 scope_id 互斥一致性
        if scope == "project" and not scope_id:
            raise serializers.ValidationError({"scope_id": "scope='project' 时 scope_id 必填"})
        if scope == "system" and scope_id:
            raise serializers.ValidationError({"scope_id": "scope='system' 时 scope_id 必须为空"})

        # contract / context contract 硬性契约：系统级凭证的写动作仅允许 superuser
        # （ViewSet 当前走 DRF Router 的同步路径，perform_acreate async 钩子不触发；
        #   在 Serializer.validate 统一做 system 级 scope 写权限校验，保证 contract 层 3 覆盖）
        request = self.context.get("request")
        if (
            scope == "system"
            and request is not None
            and not getattr(request.user, "is_superuser", False)
        ):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("仅系统管理员可创建系统级凭证")

        available_models = _normalize_available_models(
            attrs.get("available_models"),
            provider_type=str(attrs.get("provider_type") or ""),
        )
        default_model = str(attrs.get("default_model") or "").strip()
        _validate_bound_models(
            available_models=available_models,
            default_model=default_model,
        )
        attrs["available_models"] = available_models
        attrs["default_model"] = default_model

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
            # implementation 已锁 ConfigDict(hide_input_in_errors=True)，errors() 不含明文输入
            # 把 Pydantic 的 list[dict] errors 转成字段化 dict 以符合 DRF ValidationError 结构
            raise serializers.ValidationError({"config": _format_pydantic_errors(exc)}) from exc

        # 把 Pydantic 校验过的结构化 config（SecretStr unwrap）写入额外字段，供 create() 使用
        attrs["_validated_config"] = _pydantic_to_jsonable(validated)
        return attrs

    def create(self, validated_data: dict[str, Any]) -> ProviderCredential:
        """把 _validated_config dict Fernet 加密后入库。"""
        config_dict = validated_data.pop("_validated_config")
        validated_data.pop("config", None)  # 严禁写明文 config 字段
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

    Pitfall 7：需显式声明 `id` read_only 字段。DRF 默认用本 Serializer 序列化
    PATCH 200 响应；若缺少 `id`，前端 store 把响应数据替换列表项后 id 丢失，
    后续编辑操作 URL 变成 /undefined/。
    """

    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(max_length=64, required=False)
    scope = serializers.ChoiceField(choices=["system", "project"], required=False)
    scope_id = serializers.UUIDField(required=False, allow_null=True)
    config = serializers.DictField(required=False, allow_null=True)
    is_active = serializers.BooleanField(required=False)
    is_default = serializers.BooleanField(required=False)
    default_model = serializers.CharField(max_length=128, required=False, allow_blank=True)
    available_models = serializers.JSONField(required=False)
    # CONC-02：该凭证 LLM 并发上限（0=不限）
    max_concurrency = serializers.IntegerField(required=False, min_value=0)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """含 config 时按 instance.provider_type dispatch Pydantic 校验 + default_model 非空。"""
        instance: ProviderCredential = self.instance  # type: ignore[assignment]
        new_config = attrs.get("config")
        if new_config:
            from services.provider_config import PROVIDER_REGISTRY, ProviderType

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
                raise serializers.ValidationError({"config": _format_pydantic_errors(exc)}) from exc

            attrs["_validated_config"] = _pydantic_to_jsonable(validated)

        models_were_provided = "available_models" in attrs
        if models_were_provided:
            attrs["available_models"] = _normalize_available_models(
                attrs.get("available_models"),
                provider_type=str(instance.provider_type or ""),
            )

        # default_model / available_models 任一变化时，校验二者仍然绑定一致。
        if "default_model" in attrs:
            default_model = str(attrs.get("default_model") or "").strip()
            attrs["default_model"] = default_model
        else:
            default_model = instance.default_model or ""

        if "default_model" in attrs or models_were_provided:
            bound_models = (
                attrs["available_models"]
                if models_were_provided
                else _normalize_available_models(
                    instance.available_models or [],
                    provider_type=str(instance.provider_type or ""),
                )
            )
            _validate_bound_models(
                available_models=bound_models,
                default_model=default_model,
            )

        return attrs

    def update(
        self,
        instance: ProviderCredential,
        validated_data: dict[str, Any],
    ) -> ProviderCredential:
        """按字段分派：_validated_config 走 encrypt_value 重写，其余字段原地赋值。"""
        if "_validated_config" in validated_data:
            new_config = validated_data.pop("_validated_config")
            instance.encrypted_config = encrypt_value(json.dumps(new_config, ensure_ascii=False))

        # config 明文字段不入库（已由 _validated_config 代替）
        validated_data.pop("config", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance


# ============================================================================
# 首启向导：供应商一键配置编排序列化器（Phase 3）
# ============================================================================


class SetupProviderModelSerializer(serializers.Serializer):
    """首启向导单个模型入参（多模型模式）。"""

    id = serializers.CharField(max_length=128, allow_blank=False)
    context_length = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    supports_vision = serializers.BooleanField(required=False, default=False)


class ProviderSetupWizardSerializer(serializers.Serializer):
    """首启向导供应商配置入参（Phase 3 PROV-01/02/03/04/05）。

    仅承载请求体字段校验；凭证加密落库由 view 走既有 `encrypt_value` 路径完成，
    本序列化器不持久化、不回显 api_key。provider_type 固定 anthropic（Claude Code
    必备 anthropic 兼容凭证），DeepSeek/MiMo/Kimi 等预设以 base_url 覆盖 + 指定 model 接入。
    """

    api_key = serializers.CharField(write_only=True, trim_whitespace=False, allow_blank=False)
    base_url = serializers.CharField(allow_blank=False)
    # 兼容旧单模型入参；多模型模式下可省略（由 default_model + models 提供）。
    model = serializers.CharField(max_length=128, required=False, allow_blank=True)
    name = serializers.CharField(max_length=64, required=False, default="default")
    context_length = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    supports_vision = serializers.BooleanField(required=False, default=False)
    # 多模型模式：default_model 为默认模型，models 为该供应商可用模型清单。
    default_model = serializers.CharField(max_length=128, required=False, allow_blank=True)
    models = SetupProviderModelSerializer(many=True, required=False)

    def validate_base_url(self, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise serializers.ValidationError("请填写接口地址（Base URL）")
        return cleaned

    def validate(self, attrs: dict) -> dict:
        """归一化：保证存在一个非空默认模型，并把 models 收敛为去重清单。

        - default_model 优先取 default_model，其次 model；两者皆空时报错。
        - models 为空时用默认模型兜底成单元素清单（兼容旧入参）。
        - 确保 default_model ∈ models。
        """
        default_model = (attrs.get("default_model") or attrs.get("model") or "").strip()
        if not default_model:
            raise serializers.ValidationError({"default_model": "请填写默认模型"})

        raw_models = attrs.get("models") or []
        normalized: list[dict] = []
        seen: set[str] = set()
        for item in raw_models:
            mid = (item.get("id") or "").strip()
            if not mid or mid in seen:
                continue
            seen.add(mid)
            normalized.append(
                {
                    "id": mid,
                    "context_length": item.get("context_length"),
                    "supports_vision": bool(item.get("supports_vision", False)),
                }
            )

        if default_model not in seen:
            normalized.insert(
                0,
                {
                    "id": default_model,
                    "context_length": attrs.get("context_length"),
                    "supports_vision": bool(attrs.get("supports_vision", False)),
                },
            )

        attrs["default_model"] = default_model
        attrs["model"] = default_model
        attrs["models"] = normalized
        return attrs


# ============================================================================
# Provider 类型元信息 Serializer（schema-driven 前端数据源）
# ============================================================================


class ProviderTypeMetaSerializer(serializers.Serializer):
    """GET /api/providers/types/ 单项序列化。

    每个 Provider 元信息 + credential_schema 的 Pydantic JSON Schema 一次性返回，
    前端 ProviderCredentialForm.vue 据此动态渲染字段（contract schema-driven），
    新增 Provider 时仅需更新后端 PROVIDER_REGISTRY，前端无需改代码。
    """

    provider_type = serializers.CharField()
    display_name = serializers.CharField()
    langchain_prefix = serializers.CharField()
    api_format = serializers.CharField()
    credential_type = serializers.CharField()
    default_base_url = serializers.CharField(allow_blank=True)
    # PROVIDER_REGISTRY 无统一 default_model；前端 ChatInput fallback 仍可用 cred.default_model，
    # 该字段允许为空，仅当后端登记了类型级默认模型时回显。
    default_model = serializers.CharField(allow_blank=True, required=False)
    supports_thinking = serializers.BooleanField()
    supports_reasoning = serializers.BooleanField()
    supports_vision = serializers.BooleanField()
    supports_function_calling = serializers.BooleanField()
    supports_streaming = serializers.BooleanField()
    # Pydantic BaseModel.model_json_schema() 输出：通常含 properties / required / $defs
    credential_schema_json_schema = serializers.DictField()


# ============================================================================
# Claude Code 编码容器配置：Claude Code 编码容器配置序列化器
# ============================================================================


class ClaudeCodeModelMappingSerializer(serializers.Serializer):
    """opus/sonnet/haiku 三档模型映射（值为模型 id 字符串，可空）。"""

    opus = serializers.CharField(allow_blank=True, required=False, default="")
    sonnet = serializers.CharField(allow_blank=True, required=False, default="")
    haiku = serializers.CharField(allow_blank=True, required=False, default="")


class ClaudeCodeConfigSerializer(serializers.Serializer):
    """Claude Code 配置读写序列化器。

    credential_id 可为空（未选则回退系统默认 anthropic 凭证）；
    model_mapping 为 opus/sonnet/haiku 三档映射。绝不回显 api_key。
    """

    credential_id = serializers.CharField(allow_blank=True, allow_null=True, required=False)
    model_mapping = ClaudeCodeModelMappingSerializer(required=False)
