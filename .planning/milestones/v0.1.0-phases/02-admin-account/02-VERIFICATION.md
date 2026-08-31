---
phase: 02-admin-account
verified: 2026-06-08T16:32:00+08:00
status: human_needed
score: 4/4 must-haves verified
overrides_applied: 0
human_verification:

  - test: "全新部署 E2E 浏览器自动登录流程：空 DB 启动后端 + pnpm dev，访问任意页面被导向 /setup，填强口令提交"
    expected: "提交 201 后无需再次登录，浏览器直接进入系统首页 /；刷新后仍登录；再访问 /setup 被重定向到 /login"
    why_human: "完整浏览器导航 + cookie 会话 + 路由渲染无法由 grep/单测覆盖；后端会话下发与前端 store 写入已分别通过测试断言"
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  status: human_needed
---

# Phase 02: 管理员账号创建与自动登录 Verification Report

**Phase Goal:** 用户在向导填用户名 + 密码（强度校验 + 二次确认）提交后即时创建 superuser 并自动建立会话直达首页；不触发 must_change_password；账号随后可正常登录，向导按 Phase 1 门禁对后续访问者关闭。
**Verified:** 2026-06-08T16:32:00+08:00
**Status:** human_needed（仅剩 E2E 浏览器流程需人工确认）

---

## Goal Achievement

### Observable Truths

| # | Truth (Success Criterion) | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1 | 用户填用户名+密码（含强度校验与二次确认）后可提交（ADMIN-01） | ✓ VERIFIED | 后端 `SetupInitSerializer.validate_password` 调 Django 四校验器，`test_numeric_password_rejected`/`test_common_password_rejected`/`test_password_similar_to_username_rejected`/`test_short_password` 全 400；前端 `setup.vue` zod（min8+非纯数字+两次一致）+ 强度指示（弱/中/强）；`pnpm vitest` 4 passed |
| 2 | 提交成功创建 superuser 并即时生效，不触发 must_change_password（ADMIN-02） | ✓ VERIFIED | `test_init_post_success` 201 + DB 存在 is_superuser=True；`test_create_does_not_force_password_change` 断言响应与 DB `must_change_password is False`；`test_created_admin_can_login` 创建后 `POST /api/auth/login/` 200 |
| 3 | 创建成功后自动建立会话，无需再次登录直接进首页（ADMIN-03） | ✓ VERIFIED | `SetupInitView` 成功后 `RefreshToken.for_user` + 下发 `refresh_token`/`access_token` cookie，返回 `{access_token,user,must_change_password}`；`test_session_cookies_set` 断言 cookie + 响应体；前端 `applySetupSession(data.user)` + `router.push('/')`（store 写 isAuthenticated/isInitialized/needsSetup=false）；E2E 渲染需人工 |
| 4 | 账号可正常登录，向导按 Phase 1 门禁对所有访问者关闭 | ✓ VERIFIED | `test_created_admin_can_login` 200；`test_init_post_403_when_initialized` + `test_duplicate_post_rejected` 证明存在 superuser 后端 403 不回退；前端守卫 `!needsSetup && path==='/setup' → /login`（Phase 1，未改动） |

**Score:** 4/4 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `server/accounts/serializers.py` | `SetupInitSerializer.validate_password` + min_length=8 | ✓ VERIFIED | `validate_password` 调 `dj_validate_password(value, user=User(username=...))`，min_length=8 |
| `server/accounts/views.py` | 创建后下发 cookie-JWT 会话 + LoginResponseSerializer 体 | ✓ VERIFIED | `RefreshToken.for_user` + 两段 `set_cookie`（refresh/access），201 返回 LoginResponseSerializer.data |
| `server/tests/test_setup_gate.py` | 强度/不改密/会话/可登录/门禁不回退 | ✓ VERIFIED | 14 用例，`pytest tests/test_setup_gate.py -q` → 14 passed |
| `web/src/stores/auth.ts` | `applySetupSession(user)` action | ✓ VERIFIED | 定义 + return 导出；写入 user/isAuthenticated/isInitialized/mustChangePassword=false/needsSetup=false/setupStatusChecked=true |
| `web/src/locales/zh-CN.json` | strength/validation/success 文案 | ✓ VERIFIED | 新增 `success`、`fields.passwordPlaceholder`、`strength.*`、`validation.*`；JSON 有效 |
| `web/src/pages/setup.vue` | 强度指示 + 校验增强 + 自动登录直达首页 | ✓ VERIFIED | passwordStrength computed + 3 段强度条；onSubmit 成功 → applySetupSession + fetchMe + push('/')；保持原始 fetch |

---

### Key Link Verification

| From | To | Via | Status |
| ---- | -- | --- | ------ |
| `server/accounts/views.py` | `server/accounts/serializers.py` | `SetupInitSerializer.validate_password` | ✓ WIRED |
| `server/accounts/views.py` | `rest_framework_simplejwt` | `RefreshToken.for_user(user)`（复用 LoginView 路径） | ✓ WIRED |
| `web/src/pages/setup.vue` | `web/src/stores/auth.ts` | `authStore.applySetupSession(data.user)` | ✓ WIRED |
| `web/src/pages/setup.vue` | `web/src/locales/zh-CN.json` | `t('setup.strength.*')` / `t('setup.success')` | ✓ WIRED |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| 后端 setup 门禁+管理员测试 | `cd server && uv run pytest tests/test_setup_gate.py -q` | `14 passed` | ✓ PASS |
| 后端 auth 回归 | `cd server && uv run pytest tests/test_auth.py -q` | `11 passed` | ✓ PASS |
| ruff 风格 | `cd server && uv run ruff check accounts/serializers.py accounts/views.py tests/test_setup_gate.py` | `All checks passed!` | ✓ PASS |
| 前端 setup 单测 | `cd web && pnpm vitest run src/api/__tests__/setup.spec.ts` | `4 passed` | ✓ PASS |
| 前端类型检查（Phase 2 文件） | `cd web && pnpm tsc --noEmit`（过滤 setup/auth/locales） | 零错误（其余为既有无关 spec） | ✓ PASS |

---

### Requirements Coverage

| Requirement | Source Plan | Status | Evidence |
| ----------- | ---------- | ------ | -------- |
| ADMIN-01 | 02-01 + 02-02 | ✓ SATISFIED | 后端 Django 校验器强度校验 + 前端 zod/强度指示/二次确认 |
| ADMIN-02 | 02-01 | ✓ SATISFIED | create_superuser 即时生效，must_change_password=False，创建后可登录 |
| ADMIN-03 | 02-01 + 02-02 | ✓ SATISFIED | 后端下发 cookie-JWT 会话 + 前端 applySetupSession 直达 `/` |

---

### Anti-Patterns Found

无 TBD/FIXME/桩代码/空实现。`setup.vue` 的 `confirmPassword` 占位符与错误兜底字符串为 Phase 1 既有（info 级，文案与 i18n 版本一致），非本阶段引入。

---

### Human Verification Required

#### 1. ADMIN-03 端对端浏览器自动登录

**Test:** 空 DB 启动后端 + `pnpm dev`，访问 `http://localhost:5173/` → 被导向 `/setup`，填强口令（如 `Str0ng!Passw0rd`）+ 二次确认并提交。
**Expected:** 201 后**无需再次登录**直接进入系统首页 `/`；刷新仍保持登录；再访问 `/setup` 被重定向到 `/login`。
**Why human:** 浏览器导航 + cookie 会话 + 路由渲染无法由单测覆盖；后端会话下发与前端 store 写入已分别通过测试断言。

---

### Gaps Summary

无自动化可检测 gap。4/4 成功标准通过代码与测试验证；唯一未闭合项为 ADMIN-03 的 E2E 浏览器流程（Manual-Only），不阻塞阶段目标判定。

---

*Verified: 2026-06-08T16:32:00+08:00*
