---
phase: 4
slug: security-integrations
reviewed: 2026-06-08
depth: standard
verdict: clean
high: 0
medium: 0
low: 0
---

# Phase 4 — Code Review

**Scope:** 14 files changed (+1440/-124)。后端 3 视图 + 2 序列化器 + 路由 + 测试；前端 3 步组件 +
api/setup.ts + setup.vue 步骤机 + i18n + 测试。

**Verdict: CLEAN** — 无 high/medium/low 阻塞项。

## Security
- ✅ 敏感项（`FEISHU_APP_SECRET`/`QDRANT_API_KEY`/`EMBEDDING_API_KEY`）经 `encrypt_value` 密文落库 + `is_encrypted=True`，
  与 `bootstrap_system_settings` 一致；测试断言密文非明文 + `decrypt_value` 还原。
- ✅ 安全校验端点只读，响应仅含布尔 + 风险码，**不回显任何密钥明文**（测试断言 SECRET_KEY 字符串不在响应 JSON 中）。
- ✅ 结构化日志仅记 `user_id` / `written_keys`（键名），不记 app_secret / api_key 值。
- ✅ 三端点均 `IsSuperUser`；普通用户 403、匿名 401/403（测试覆盖）。
- ✅ 前端敏感字段 `type="password"` + `autocomplete="off"`；write_only 序列化器字段不回读。

## Correctness
- ✅ `update_or_create` 幂等（向导可重试），测试覆盖二次提交仅一行。
- ✅ RAG 仅写"已提供且非空"字段（部分写入测试覆盖），键名严格 `SettingKeys.*`。
- ✅ 安全判定逻辑与 `friday/settings.py` / `common/encryption.py` 对齐（默认值、独立性）。
- ✅ 安全校验非阻塞：前端「继续」按钮在通过/有风险/读取失败三态下均可点击（测试断言无 disabled + 可 emit continue）。

## Reuse / Boundaries
- ✅ 未自建任何存储；复用 `SystemSetting`/`SettingKeys`/`encrypt_value`/`IsSuperUser`。
- ✅ 未回退 Phase 1 守卫 / Phase 2 自动登录 / Phase 3 provider 端点与组件契约（仅改 provider done/skip 目标步骤）。
- ✅ 既有读路径（websocket_client / feishu_im / qdrant_service / index_views）按 `is_encrypted`/`decrypt_value` 兼容密文。

## Quality
- ✅ adrf async + `sync_to_async` ORM 写，与 `ProviderSetupWizardView` 一致。
- ✅ ruff format/check 干净（行宽 100）；eslint --fix 干净。
- ⓘ 注：`bg-gradient-to-br` / `flex-shrink-0` 为 Tailwind v4 类名建议级 warning，与既有 Phase 1-3 组件写法一致，
  未统一改动以保持一致（非 eslint 错误，不阻塞）。

## Tests
- Backend: `test_setup_integrations.py` 14 passed；回归 17 passed。
- Frontend: 23 passed（含回归 SetupProviderStep 5）。

**Action:** 无需 fix。
