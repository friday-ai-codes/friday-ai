---
phase: 4
slug: security-integrations
created: 2026-06-08
---

# Phase 4 — Patterns（新文件 → 最近似既有范式）

| 新增/改动 | 类型 | 最近似既有范式（照抄结构） |
|-----------|------|---------------------------|
| `server/system/setup_views.py` | 新建 | `server/system/views.py` 的 `ProviderSetupWizardView`（adrf APIView + IsSuperUser + sync_to_async ORM 写 + 结构化日志） |
| `SetupSecurityCheckView`（GET 只读） | 新视图 | `system/views.py:SystemInfoView`（IsSuperUser 只读 + 返回脱敏字典，绝不回显密钥明文） |
| `SetupFeishuWizardView` / `SetupRagWizardView`（POST 写设置） | 新视图 | `bootstrap_system_settings`（encrypt_value + is_encrypted 写法）+ `ProviderSetupWizardView`（请求体校验 + sync_to_async upsert） |
| `server/system/setup_serializers.py`（或并入 serializers.py） | 新建 | `system/serializers.py:ProviderSetupWizardSerializer`（DRF Serializer + 字段 strip 校验） |
| `system/urls_system.py` 追加 3 path | 改动 | `system/urls_providers.py`（path 注册范式） |
| `server/tests/test_setup_integrations.py` | 新建 | `tests/test_provider_setup_wizard.py`（APIClient + force_authenticate + 密文断言 + 权限断言） |
| `web/src/api/setup.ts` 新增 3 函数 | 改动 | 同文件既有 `setupProvider`（`post('/providers/setup-wizard/', data)` 封装 + 类型接口） |
| `web/src/components/setup/SetupSecurityStep.vue` | 新建 | `SetupProviderStep.vue`（step 组件 + emit + i18n + 提交/错误态） |
| `web/src/components/setup/SetupFeishuStep.vue` | 新建 | `SetupProviderStep.vue`（vee-validate/zod 表单 + 提交 + 跳过 emit） |
| `web/src/components/setup/SetupRagStep.vue` | 新建 | `SetupProviderStep.vue`（同上，末步 done/skip 进首页） |
| `web/src/pages/setup.vue` 步骤机扩展 | 改动 | 自身（Phase 3 已是 `step:'admin'|'provider'` ref + `<SetupProviderStep @done @skip>`） |
| `web/src/locales/zh-CN.json` `setup.*` 扩展 | 改动 | 自身既有 `setup.provider.*` 子树结构 |
| `web/src/**/__tests__/Setup*Step.spec.ts` + `api/__tests__/setup.spec.ts` 扩展 | 新建/改动 | `SetupProviderStep.spec.ts` / `setup.spec.ts` |

## 复用红线（不得违反）
- 加密只用 `common.encryption.encrypt_value`；键名只用 `system.models.SettingKeys.*`。
- 不新建任何凭证/设置存储表；不绕过 `IsSuperUser`。
- 安全校验端点只读、非阻塞、不回显密钥明文。
- 不改 Phase 1 路由守卫 / Phase 2 自动登录 / Phase 3 provider 端点与组件对外契约。
