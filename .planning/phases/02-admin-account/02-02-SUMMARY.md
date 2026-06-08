---
phase: 02-admin-account
plan: "02"
subsystem: frontend
tags: [setup, admin, form, password-strength, auto-login, i18n, ADMIN-01, ADMIN-03]
dependency_graph:
  requires: [setup-session-cookies]
  provides: [setup-form-strength-ui, auto-login-to-home]
  affects: [web/src/stores/auth.ts, web/src/locales/zh-CN.json, web/src/pages/setup.vue]
tech_stack:
  added: []
  patterns: [vee-validate-zod, vue-i18n, pinia-action, raw-fetch-setup]
key_files:
  created: []
  modified:
    - web/src/stores/auth.ts
    - web/src/locales/zh-CN.json
    - web/src/pages/setup.vue
decisions:
  - "新增 auth store action applySetupSession(user) 集中写入会话状态并关闭 setup 守卫"
  - "提交成功后直达首页 router.push('/')（替换 Phase 1 的 /login），调用 fetchMe() 拉取扩展信息"
  - "密码强度为前端 UX 提示（4 维度评分→弱/中/强），最终以后端 Django 校验器为准"
  - "保持原始 fetch 提交（不走 api/client.ts），解析新增的 user 字段并回填后端字段错误"
metrics:
  completed: "2026-06-08"
  tasks_completed: 3
  files_changed: 3
---

# Phase 02 Plan 02: 前端管理员表单 + 自动登录 Summary

**One-liner:** `setup.vue` 表单增强密码强度指示与即时校验（ADMIN-01），提交成功后经 `applySetupSession` 写入会话并 `router.push('/')` 直达首页，无需二次登录（ADMIN-03）；保持 Phase 1 的原始 fetch 提交约束。

## Tasks Completed

| Task | Name | Files |
|------|------|-------|
| 1 | auth store applySetupSession + i18n 文案 | `web/src/stores/auth.ts`, `web/src/locales/zh-CN.json` |
| 2 | setup.vue 强度指示 + 校验增强 + 自动登录直达首页 | `web/src/pages/setup.vue` |
| 3 | 前端测试无回归 | `web/src/api/__tests__/setup.spec.ts`（沿用，4 passed） |

提交：`cbd9a93d`（feat(02): frontend admin form strength + auto-login to home）

## What Was Built

### `web/src/stores/auth.ts`
- 新增 `applySetupSession(sessionUser)`：设 `user / isAuthenticated=true / isInitialized=true / mustChangePassword=false / needsSetup=false / setupStatusChecked=true`；在 return 列表导出。避免守卫把刚创建的管理员弹回 `/login`。

### `web/src/locales/zh-CN.json`
- 在 `setup.*` 新增：`success`、`fields.passwordPlaceholder`、`strength.{label,weak,medium,strong}`、`validation.{usernameRequired,passwordMin,passwordNumeric,passwordMismatch}`。保留 Phase 1 既有键。

### `web/src/pages/setup.vue`
- zod schema 改用 `t()` 文案：username 必填、password min 8 + 非纯数字 refine、confirmPassword 两次一致。
- `useForm` 暴露 `values`，新增 `passwordStrength` computed（长度≥8 / 含字母 / 含数字 / 含符号或≥12 四维度 → 弱/中/强 + 颜色档位 destructive/amber/primary）。
- 密码字段下渲染 3 段强度条 + `text-xs` 等级文字。
- `onSubmit` 成功：解析 `data.user` → `authStore.applySetupSession` → `fetchMe()`（忽略错误）→ `router.push('/')`。
- `onSubmit` 失败：`firstFieldError()` 提取后端 password/username 字段中文错误，回退 `data.detail` / `t('setup.error.default')`。
- 保持原始 `fetch('/api/auth/setup/', { credentials:'include' })`、`onMounted` 守卫、`route meta.layout:false`、glass 卡片结构不变。

## Deviations from Plan

None — 按计划实现。`confirmPassword` 占位符沿用 Phase 1 既有写法（未在 UI-SPEC 增列键），不扩大范围。

## Verification Results

```
cd web && node -e "JSON.parse(...zh-CN.json)" → json valid
cd web && pnpm tsc --noEmit → Phase 2 文件（setup.vue/auth.ts/locales）零错误
  （其余报错均为既有无关 spec 文件 chat/codegraph/prompts/repository，非本阶段引入）
cd web && pnpm vitest run src/api/__tests__/setup.spec.ts → 4 passed
cd web && pnpm eslint src/pages/setup.vue src/stores/auth.ts → 无 error
```

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| ✅ T-2-05 mitigated | `pages/setup.vue` | 保持原始 fetch，不走 api/client.ts（沿用 T-1-05） |
| ✅ T-2-06 mitigated | `stores/auth.ts` | applySetupSession 显式设 isAuthenticated/isInitialized/needsSetup=false 后再 push('/') |

## Self-Check: PASSED

| Item | Status |
|------|--------|
| auth.ts applySetupSession（定义 + return） | FOUND |
| zh-CN.json strength/validation/success | FOUND |
| setup.vue applySetupSession + router.push('/') + 强度块 | FOUND |
| setup.vue 仍含原始 fetch('/api/auth/setup/') | FOUND |
| tsc 无 Phase 2 文件错误 | VERIFIED |
| setup.spec.ts 4 passed | VERIFIED |
