---
phase: 02-admin-account
reviewed: 2026-06-08
status: clean
files_reviewed:
  - server/accounts/serializers.py
  - server/accounts/views.py
  - server/tests/test_setup_gate.py
  - web/src/stores/auth.ts
  - web/src/locales/zh-CN.json
  - web/src/pages/setup.vue
findings:
  critical: 0
  high: 0
  medium: 0
  low: 0
---

# Phase 02 Code Review

**Status:** clean — 无 critical/high/medium/low 问题，无需运行 `--fix`。

## Scope

仅审查 Phase 2 改动的源文件（同一 setup 端点 + 前端向导表单的增强），不审查 Phase 1 既有逻辑。

## Findings

### 正确性
- 后端 `SetupInitView.post` 仅在 `_atomic_create_superuser` 返回非 None（创建成功）后才下发会话，门禁 `SetupNotInitialized` 与原子防重入分支保持不变 —— Phase 1 fail-closed 不回退。✅
- 会话下发逻辑逐行对齐 `LoginView`（`RefreshToken.for_user` + `sub` claim + 两段 `set_cookie`，flags/max_age 用 `settings.COOKIE_*` / `SIMPLE_JWT`），无新 cookie 策略。✅
- `must_change_password` 取 `user.must_change_password`（`create_superuser` 默认 False），未被置位 —— ADMIN-02 满足，且有测试断言。✅
- `validate_password` 传入未保存 `User(username=...)` 使相似度校验生效；`DjangoValidationError.messages` 透传为字段错误（zh-hans 中文）。✅

### 安全
- 会话只在「无 superuser → 创建首个管理员成功」路径下发，符合预期（创建者即首个管理员）。无越权风险。✅
- 前端保持原始 fetch 提交，避免 `api/client.ts` 的全局 403/401 重定向副作用（沿用 T-1-05）。✅
- 密码强度后端权威（Django 四校验器），前端仅 UX 提示，不可绕过。✅

### 质量
- 注释中文、`ruff check` 通过（行宽 100）；前端 `tsc` 对 Phase 2 文件零错误、`eslint` 无 error。✅
- 复用既有 store action 模式与 i18n 命名空间，无重复造轮子。✅

### 异步约束
- 所有 ORM/JWT 同步 API 经 `sync_to_async` 包装；`serializer.is_valid` 在 `sync_to_async` 内执行（含 `validate_password` 的校验器 DB 访问）。✅

## Pre-existing (out of scope, not introduced by Phase 2)
- `web/` 其余 `__tests__/*.spec.ts`（chat/codegraph/prompts/repository）的 tsc 类型告警为既有问题，与本阶段无关。
- `setup.vue` 模板中 `bg-gradient-to-br` / `flex-shrink-0` 的 Tailwind class 写法 WARNING 为 Phase 1 既有，非本阶段引入。

## Verdict

clean — 跳过 `--fix`。
