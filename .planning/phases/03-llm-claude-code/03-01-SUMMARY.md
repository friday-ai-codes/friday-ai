---
phase: 3
plan: "03-01"
status: complete
completed: 2026-06-08
requirements: [PROV-01, PROV-04, PROV-05, SEC-02]
---

# Plan 03-01 Summary — 后端供应商配置编排端点

## Delivered
- `services/provider_health.py`：新增 `health_check_config(provider_type, cfg, model)` —— 无状态健康校验，复用既有 `_PING_DISPATCH` / `_safe_error` 脱敏，**无 DB 副作用**（落库前连通/鉴权门）。
- `system/serializers.py`：新增 `ProviderSetupWizardSerializer`（api_key/base_url/model/name/context_length/supports_vision 校验）。
- `system/views.py`：新增 `ProviderSetupWizardView`（`POST /api/providers/setup-wizard/`，`IsSuperUser`），编排：Pydantic 校验 → 落库前健康校验（失败 400 + 可操作中文提示、不落库）→ `encrypt_value` Fernet 加密 `update_or_create` 系统级 anthropic 凭证 → 原子设 `is_default` → `aset_claude_code_config` 绑定三档。
- `system/urls_providers.py`：注册 `setup-wizard/` 路由（置于 router.urls 前）。
- `tests/test_provider_setup_wizard.py`：7 用例全绿（成功密文落库+设默认+绑 CC、健康失败不落库、错误脱敏、幂等重试、superuser/匿名权限、缺字段 400）。

## Reuse verification（关键约束达成）
- ✅ 凭证加密：复用 `common.encryption.encrypt_value`（与 `ProviderCredentialCreateSerializer.create` 同一 Fernet 路径），未自建存储。
- ✅ 健康校验：复用 `provider_health._PING_DISPATCH[anthropic]=_ping_anthropic`（count_tokens）。
- ✅ Claude Code 绑定：复用 `services.provider_config.aset_claude_code_config`。
- ✅ 默认凭证：复用 `set_default` 同一原子语义 + DB 约束。
- ✅ 权限：复用 `permissions.api_permissions.IsSuperUser`。

## Tests
- `pytest tests/test_provider_setup_wizard.py` → 7 passed。
- 回归 `test_provider_health.py` + `test_setup_gate.py` + `test_provider_credential_api.py` → 47 passed。

## Notes
- 文件内既有 E402（SystemInfoView 段中部 import）为 pre-existing，未触碰。
