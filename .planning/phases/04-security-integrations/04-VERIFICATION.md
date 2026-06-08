---
phase: 4
slug: security-integrations
status: complete
verified: 2026-06-08
gaps_found: 0
must_haves_met: 4
must_haves_total: 4
human_needed: 1
---

# Phase 4 — Verification (goal-backward)

**Goal:** 向导对加密/安全密钥做健康校验与风险提示（不阻塞），并提供可一键跳过的飞书集成与向量检索
配置步骤，写入与既有路径一致。

**Status: COMPLETE** — 4/4 must-have 成功标准达成，0 gaps。

## Success Criteria

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | 向导检测 `SECRET_KEY`/`FRIDAY_ENCRYPTION_KEY` 是否安全（非默认、相互独立），给风险提示但**不阻塞**完成 | ✅ MET | `SetupSecurityCheckView`（只读判定 secret_key_secure/encryption_key_set/keys_independent + risks）；前端 `SetupSecurityStep.vue`「继续」按钮任何态不 disable；测试 `test_reports_insecure_defaults/secure/keys_not_independent` + `SetupSecurityStep.spec`（风险态/失败态仍可继续） |
| 2 | 可配置飞书（App ID/Secret）或**一键跳过**，写入与既有 `SystemSetting`/`bootstrap_system_settings` 路径一致 | ✅ MET | `SetupFeishuWizardView` 用 `SettingKeys.FEISHU_APP_ID/SECRET` + `encrypt_value` upsert；`SetupFeishuStep.vue` 跳过=不调端点；测试 `test_encrypts_secret_and_aligns_keys`、`SetupFeishuStep.spec`（done/skip） |
| 3 | 可配置向量检索（Qdrant URL/Key、Embedding）或**一键跳过**，配置项与既有 `SettingKeys`（QDRANT_URL/EMBEDDING_*）对齐 | ✅ MET | `SetupRagWizardView` 键名严格 `SettingKeys.QDRANT_URL/QDRANT_API_KEY/EMBEDDING_*`，敏感项 `encrypt_value`；`SetupRagStep.vue` 跳过=不调端点；测试 `test_aligns_settingkeys_and_encrypts`、`SetupRagStep.spec` |
| 4 | 跳过的可选步骤可稍后在既有设置页补充，不影响向导完成 | ✅ MET | 写入既有 `SystemSetting` 键，既有设置页 `FeishuIMConfigSection`/`VectorIndexSettings` 读写同键；跳过推进下一步、末步进首页，向导照常完成（步骤机 admin→provider→security→feishu→rag→`/`） |

## Requirements coverage
- SEC-01 ✅（只读安全校验 + 风险提示，非阻塞）
- FEISHU-01 ✅（可选飞书步骤，可一键跳过）
- FEISHU-02 ✅（写既有 SystemSetting/bootstrap 路径，App Secret Fernet 密文）
- RAG-01 ✅（可选向量检索步骤，可一键跳过）
- RAG-02 ✅（键名对齐 SettingKeys，敏感项 Fernet 密文）

## Reuse compliance（关键约束）
- ✅ 复用 `common.encryption.encrypt_value`（Fernet 唯一入口）——未自建凭证/设置存储。
- ✅ 复用 `system.models.SystemSetting` + `SettingKeys.*` 常量——未硬编码键名。
- ✅ 加密写法与 `bootstrap_system_settings` 完全一致（非敏感明文 / 敏感 `encrypt_value`+`is_encrypted=True`）。
- ✅ 既有读路径（`feishu/websocket_client`、`services/feishu_im`、`services/qdrant_service`、`repositories/index_views`）
  按 `is_encrypted`/`decrypt_value` 兼容密文，加密落库对读取透明。
- ✅ 复用 `permissions.api_permissions.IsSuperUser`。
- ✅ 安全校验**确为非阻塞**：端点只读、只返回布尔+风险码，前端「继续」按钮在任何校验结果下都可点击（测试断言无 disabled）。
- ✅ 未回退 Phase 1 fail-closed 守卫 / Phase 2 自动登录 / Phase 3 供应商端点与组件契约。

## Tests
- Backend: `tests/test_setup_integrations.py` → 14 passed；回归 `test_provider_setup_wizard.py`+`test_security_baseline.py`+`test_bootstrap_system_settings.py` → 17 passed。
- Frontend: `api/__tests__/setup.spec.ts`(9) + `SetupSecurityStep.spec.ts`(3) + `SetupFeishuStep.spec.ts`(3) + `SetupRagStep.spec.ts`(3) + 回归 `SetupProviderStep.spec.ts`(5) → 23 passed。

## Human-needed (manual UAT — 1 项)
- **端到端浏览器真机流程**：自动化以 vi.mock/override_settings 桩替代。需人工在浏览器跑：全新部署 → 建管理员（自动登录）
  → 供应商 → 安全校验页（默认开发环境应显示风险提示且「继续」可点）→ 飞书步骤（填或跳过）→ 向量检索步骤（填或跳过）
  → 进入首页；并在设置页确认飞书 App Secret / Qdrant Key 以密文落库、跳过项可补填。（属 human_verify_mode=end-of-phase 既定人工项）

## Gaps
- 无。
