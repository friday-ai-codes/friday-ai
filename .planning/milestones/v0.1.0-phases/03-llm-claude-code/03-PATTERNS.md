# Phase 3 — Patterns (new files → closest analog)

| New file | Closest existing analog | Pattern to mirror |
|----------|-------------------------|-------------------|
| `server/services/provider_health.py` 内 `health_check_config()` | 同文件 `health_check()` / `_ping_anthropic` | 无状态探活，复用 `_PING_DISPATCH`，错误经 `_safe_error` 脱敏，不做 `aupdate` |
| `server/system/views.py` 内 `ProviderSetupWizardView` | 同文件 `ClaudeCodeConfigView` / `ProviderCredentialViewSet.set_default` | adrf APIView async，`IsSuperUser`，`sync_to_async` 包同步 ORM/serializer，原子事务设默认 |
| `server/system/serializers.py` 内 `ProviderSetupWizardSerializer` | 同文件 `ProviderCredentialCreateSerializer` | DRF Serializer 字段校验；config 加密由 view 走 `encrypt_value` |
| `server/system/urls_providers.py` 新增 path | 同文件 `claude-code-config/` path | 静态 path 置于 `*router.urls` 之前 |
| `server/tests/test_provider_setup_wizard.py` | `tests/test_provider_health.py` + `tests/test_setup_gate.py` | respx mock httpx + DRF APIClient.force_authenticate(superuser) |
| `web/src/lib/providerPresets.ts` | `web/src/lib/providerBrandColors.ts` | 纯常量模块 + 类型导出 |
| `web/src/components/setup/SetupProviderStep.vue` | `web/src/pages/setup.vue`（表单部分）/ `components/providers/ProviderCredentialForm.vue` | vee-validate + zod + `~/components/ui/*` + i18n |
| `web/src/api/setup.ts` 内 `setupProvider()` | 同文件 `initSetup()` / `api/providerCredentials.ts` | `post()` 封装相对路径 |
| `web/src/locales/zh-CN.json` `setup.provider.*` | 同文件 `setup.*` | 命名空间扩展 |
| 前端测试 | `api/__tests__/setup.spec.ts` | `vi.mock('~/api/client')` |
