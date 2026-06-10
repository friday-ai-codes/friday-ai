# Phase 3 — Code Review

**Reviewed:** 2026-06-08
**Scope:** Plan 03-01（后端编排端点）+ 03-02（前端两步向导）改动文件
**Depth:** standard
**Verdict:** PASS（无 high/medium 阻塞项）

## Files reviewed
- `server/services/provider_health.py`（+`health_check_config`）
- `server/system/serializers.py`（+`ProviderSetupWizardSerializer`）
- `server/system/views.py`（+`ProviderSetupWizardView`）
- `server/system/urls_providers.py`（+`setup-wizard/`）
- `server/tests/test_provider_setup_wizard.py`
- `web/src/lib/providerPresets.ts`、`web/src/api/setup.ts`、`web/src/components/setup/SetupProviderStep.vue`、`web/src/pages/setup.vue`、`web/src/locales/zh-CN.json` + 对应测试

## Findings

### Security — PASS
- 凭证仅经 `encrypt_value`（Fernet）落库；测试断言 `encrypted_config` 不含明文 api_key 且可解回（SEC-02）。
- 健康校验错误经既有 `_safe_error`/`redact_secrets_in_text` 脱敏；端点 `detail` 透传的是脱敏后的 `result.error`；测试断言上游含 `sk-ant-*` 的 body 被脱敏。
- 端点 `IsSuperUser`；普通用户 403、匿名 401/403（测试覆盖）。
- 日志仅记 `credential_id`/`provider`/`latency_ms`，不记 api_key。

### Correctness — PASS
- 落库前健康校验失败即返回 400 且不落任何凭证（测试覆盖 DB 无凭证）。
- `update_or_create((scope=system, provider_type=anthropic, name))` 幂等，重试不撞唯一约束（测试覆盖）。
- 设默认在 `transaction.atomic` 内先清零后置位，DB partial unique 约束兜底。
- `aset_claude_code_config` 在凭证落库（available_models 含所选 model）后调用，三档映射校验通过（测试覆盖 CC 写入）。
- async/sync 边界正确：同步 ORM/serializer 经 `sync_to_async`；异步 ORM/CC 绑定直接 `await`。

### Quality — PASS
- 复用既有 service 层（Fernet/health/Claude Code/IsSuperUser/`_normalize_available_models`），未自建凭证存储、未绕过加密与权限。
- 前端复用既有 `ui/*` 表单范式 + vee-validate/zod + `api/client`；两步切换走组件内部状态，未改动 Phase 1 路由守卫 fail-closed 语义。
- 文案中文、注释中文；后端 ruff format 已应用。

## Minor notes (non-blocking)
- 预设 base_url/model 为各供应商 Anthropic 兼容端点的公开约定，字段可编辑纠错（健康校验把关）。
- 前端残留 Tailwind 4 类名提示（`bg-gradient-to-br`/`flex-shrink-0`）与既有 `setup.vue` 一致，未改以保持风格统一（warning 非 error）。
- `views.py` 既有 E402（SystemInfoView 段中部 import）为 pre-existing，未在本阶段引入。

## Fix actions
- 无需 `--fix`（无 high/medium 发现）。
