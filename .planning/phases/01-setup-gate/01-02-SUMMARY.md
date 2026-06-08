---
phase: 01-setup-gate
plan: "02"
subsystem: frontend
tags: [setup-gate, router-guard, i18n, auth-store, api, SETUP-01, SETUP-02, SETUP-03]
dependency_graph:
  requires: [01-01]
  provides: [setup-router-guard, setup-api-module, auth-store-setup-state, zh-CN-i18n]
  affects:
    - web/src/api/setup.ts
    - web/src/api/index.ts
    - web/src/stores/auth.ts
    - web/src/locales/zh-CN.json
    - web/src/main.ts
    - web/src/pages/setup.vue
    - web/src/api/__tests__/setup.spec.ts
tech_stack:
  added: []
  patterns: [vue-i18n-messages-inject, router-beforeEach-setup-guard, fail-safe-catch, pinia-ref-extend]
key_files:
  created:
    - web/src/api/setup.ts
    - web/src/locales/zh-CN.json
    - web/src/api/__tests__/setup.spec.ts
  modified:
    - web/src/api/index.ts
    - web/src/stores/auth.ts
    - web/src/main.ts
    - web/src/pages/setup.vue
decisions:
  - "getSetupStatus placed before initAuth() in router.beforeEach to prevent /me 401 refresh loop on fresh deployments (T-1-06)"
  - "fail-safe catch sets needsSetup=false to protect existing instances from being redirected to setup wizard (T-1-04)"
  - "setup.vue POST kept as raw fetch to avoid 403 triggering global auth:forbidden redirect (T-1-05)"
  - "needsSetup + setupStatusChecked as new refs in auth store, not overloading isInitialized (naming correctness)"
  - "zh-CN messages injected manually via createI18n messages field, not relying on unplugin-vue-i18n auto-loading"
metrics:
  duration: "~30 min"
  completed: "2026-06-08"
  tasks_completed: 3
  files_changed: 7
---

# Phase 01 Plan 02: 前端路由守卫与向导外壳改造 Summary

**One-liner:** Frontend setup guard with fail-safe status fetch, `needsSetup`/`setupStatusChecked` in auth store, zh-CN i18n injection, and `setup.vue` i18n-ified—wired to the Plan 01-01 `GET /api/auth/setup/status/` endpoint.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Setup API 模块 + Auth Store 扩展 + i18n 文案 | `db2f5084` | `setup.ts`, `index.ts`, `auth.ts`, `zh-CN.json` |
| 2 | router.beforeEach setup 分支 + setup.vue 外壳改造 | `e6f2daaa` | `main.ts`, `setup.vue` |
| 3 | 前端单元测试 — setup API 模块 | `4952b961` | `setup.spec.ts` |

## What Was Built

### `web/src/api/setup.ts` (新建)
- `getSetupStatus(): Promise<SetupStatus>` — AllowAny GET 封装，路由守卫在 `initAuth()` 前调用
- `initSetup(data: SetupInitRequest): Promise<void>` — POST 封装，供外部消费方和测试使用
- 内联接口定义 `SetupStatus` 和 `SetupInitRequest`，JSDoc 说明 fail-safe 语义

### `web/src/api/index.ts` (追加)
- 追加 `export { default as setupApi } from './setup'` 和 `export * from './setup'`

### `web/src/stores/auth.ts` (三处追加)
- State 区块追加 `needsSetup = ref(false)` 和 `setupStatusChecked = ref(false)`
- `$reset()` 追加两行重置
- `return` 导出对象追加两个 ref

### `web/src/locales/zh-CN.json` (新建)
- `setup.*` 命名空间 9 个叶节点键：title, subtitle, loading, cta, submitting, fields.username, fields.password, fields.confirmPassword, error.connection, error.default

### `web/src/main.ts` (修改两处)
- 注入 `zhCN` messages 到 `createI18n`
- `router.beforeEach` 中在 `initAuth()` 之前插入 setup 状态检测块：
  - `!setupStatusChecked` → `getSetupStatus()` → 写 `needsSetup`（catch: fail-safe=false）→ `setupStatusChecked=true`
  - `needsSetup && to.path !== '/setup'` → `next('/setup')` (SETUP-01)
  - `!needsSetup && to.path === '/setup'` → `next('/login')` (SETUP-03 前端侧)
  - `publicPages` 加入 `/setup`

### `web/src/pages/setup.vue` (修改)
- 追加 `const { t } = useI18n()`
- 替换硬编码文案：title → `t('setup.title')`，subtitle → `t('setup.subtitle')`，字段标签，按钮文字
- POST 成功后设置 `authStore.needsSetup = false; authStore.setupStatusChecked = true`，路由跳转改为 `/login`

### `web/src/api/__tests__/setup.spec.ts` (新建)
- 4 个测试全部 PASSED：`getSetupStatus` 正常返回、网络异常；`initSetup` 成功调用、后端错误

## Verification Results

```
cd web && pnpm vitest run src/api/__tests__/setup.spec.ts
✓ src/api/__tests__/setup.spec.ts (4 tests) 4ms
Test Files  1 passed (1)
     Tests  4 passed (4)

TypeScript check: no new errors from plan files
(pre-existing errors in unrelated test specs remain — out of scope)
```

## Deviations from Plan

### Auto-fixed Issues

None — plan executed as written with one clarification:

**Clarification: setup.vue POST success redirect changed to `/login` (not `/`)**
- **Found during:** Task 2 review
- **Issue:** Original setup.vue routed POST success to `router.push('/')` and set `authStore.user = data.user`, but the backend `POST /api/auth/setup/` returns `{"detail": "管理员账户创建成功"}` (no user object, no cookie set in Phase 1)
- **Fix:** Changed to `router.push('/login')` and removed invalid `data.user` assignment; set `needsSetup=false, setupStatusChecked=true` so guard doesn't loop back to `/setup`
- **Impact:** UX correct — user creates admin then is prompted to log in (Phase 2 will add auto-login)

## Known Stubs

- `setup.vue` `onMounted` still runs its own `fetch('/api/auth/setup/status/')` redundantly (in addition to the router guard check). This is intentional for Phase 1 — the guard caches state in the store, the onMounted provides a component-level fallback. No correctness impact.

## Threat Flags

None — all mitigations from plan threat model applied:
- ✅ T-1-04: fail-safe catch sets `needsSetup=false`
- ✅ T-1-05: setup.vue POST uses raw `fetch`, not `api/client.ts post()`
- ✅ T-1-06: setup branch placed before `initAuth()` call (getSetupStatus at line 62, initAuth at line 85)

## Key Decisions

1. **setup 分支严格置于 initAuth() 之前** — 防止全新部署 /me 401 → token 刷新失败 → auth:logout → $reset → setupStatusChecked=false 无限循环（Pitfall 2）
2. **fail-safe 按已初始化处理** — 保护生产实例，宁可不进向导（D-C 决策 + T-1-04）
3. **原始 fetch 保留在 setup.vue** — 避免 403 触发 auth:forbidden 全局跳转 /403（D-D 决策 + T-1-05）
4. **needsSetup/setupStatusChecked 独立于 isInitialized** — 语义清晰，不混淆认证初始化与系统 setup 状态（RESEARCH Pitfall 1）
5. **POST 成功跳转 /login 而非 /** — Phase 1 后端不发 cookie/session，需用户主动登录（Phase 2 将添加自动登录）

## Self-Check: PASSED

| Item | Status |
|------|--------|
| `web/src/api/setup.ts` | FOUND |
| `web/src/locales/zh-CN.json` | FOUND |
| `web/src/api/__tests__/setup.spec.ts` | FOUND |
| commit `db2f5084` (Task 1) | FOUND |
| commit `e6f2daaa` (Task 2) | FOUND |
| commit `4952b961` (Task 3) | FOUND |
| vitest 4 passed | VERIFIED |
| needsSetup in auth.ts (3 occurrences) | VERIFIED (grep -c = 3) |
| setupStatusChecked in main.ts | VERIFIED |
| getSetupStatus before initAuth (line 62 vs 85) | VERIFIED |
