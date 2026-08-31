---
phase: 01-setup-gate
verified: 2026-06-08T15:51:00+08:00
status: human_needed
score: 4/4 must-haves verified
overrides_applied: 0
human_verification:

  - test: "全新部署 E2E 浏览器重定向测试：启动无 superuser 的后端实例，访问任意非 /setup 页面"
    expected: "浏览器自动跳转到 /setup，显示「首次设置」向导界面；完成设置后跳转到 /login；再次访问 /setup 被重定向到 /login"
    why_human: "路由守卫逻辑已通过单元断言验证，但完整 E2E 流程（前端 fetch 到后端 + 路由跳转渲染）需要真实浏览器环境；01-VALIDATION.md 已登记此 Manual-Only 条目"
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  status: human_needed
---

# Phase 01: Setup Gate Verification Report

**Phase Goal:** 全新部署（无 superuser）首次访问被自动导向首启向导外壳；已初始化实例（存在 superuser）被 fail-closed 拒之门外；初始化门禁防重入（并发/重复请求一律拒绝）。
**Verified:** 2026-06-08T15:51:00+08:00
**Status:** human_needed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1 | 无 superuser 的全新部署访问任意页面被自动重定向进入首启初始化向导 | ✓ VERIFIED | `main.ts:60-76` — `!setupStatusChecked` 时调用 `getSetupStatus()`；`needsSetup && to.path !== '/setup'` → `next('/setup')`；`publicPages` 含 `/setup`；后端 8/8 + 前端 4/4 测试通过 |
| 2 | 后端 is_initialized 只读接口可被前端无认证调用，前端路由守卫据此放行/拦截 | ✓ VERIFIED | `SetupStatusView.permission_classes = [AllowAny]`；返回 `{is_initialized, needs_setup}` 布尔字段；`test_no_auth_required` PASSED；`main.ts` 在 `initAuth()` 之前（行 62 vs 85）调用 `getSetupStatus()` |
| 3 | 一旦存在 superuser，初始化接口返回 403/重定向、向导界面不再出现 | ✓ VERIFIED | `SetupInitView.authentication_classes=[]` + `permission_classes=[AllowAny, SetupNotInitialized]`，superuser 存在时 `has_permission` 返回 `False` → DRF 返回 403；`test_init_post_403_when_initialized` PASSED；`main.ts:77-79` `!needsSetup && to.path === '/setup'` → `next('/login')` |
| 4 | 并发/重复请求初始化接口时存在 superuser 即一律被拒绝，无法用于重置或接管已有实例 | ✓ VERIFIED | `_atomic_create_superuser`：`transaction.atomic()` 内 double-check（`User.objects.filter(is_superuser=True).exists()` 返回 `None`）+ `IntegrityError` 兜底（UNIQUE 约束）；`test_duplicate_post_rejected` PASSED（首次 201，再次 403）；`SetupNotInitialized` 在权限层拦截所有 superuser 已存在的请求 |

**Score:** 4/4 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `server/accounts/permissions.py` | `SetupNotInitialized` 可复用权限类 | ✓ VERIFIED | 存在，`class SetupNotInitialized(BasePermission)` + `has_permission` 同步 ORM 查询，被 `views.py` 导入使用 |
| `server/accounts/views.py` | `SetupStatusView` + `SetupInitView` + `_atomic_create_superuser` | ✓ VERIFIED | 存在且实质性：`SetupStatusView.get` 异步返回 `{is_initialized, needs_setup}`；`_atomic_create_superuser` 含 `transaction.atomic()` double-check；`SetupInitView` 含 `authentication_classes=[]` 关键配置 |
| `server/accounts/serializers.py` | `SetupInitSerializer`（追加末尾） | ✓ VERIFIED | `class SetupInitSerializer(serializers.Serializer)` 存在于文件末尾；含 `validate_username` 查重方法；`password` 含 `min_length=6` |
| `server/accounts/urls.py` | `setup/status/` + `setup/` 路由 | ✓ VERIFIED | `path("setup/status/", SetupStatusView.as_view(), name="setup-status")` 和 `path("setup/", SetupInitView.as_view(), name="setup-init")` 均存在；通过 `friday/urls.py` 挂载到 `/api/auth/` |
| `server/tests/test_setup_gate.py` | `TestSetupStatusView` + `TestSetupInitView` 全覆盖 | ✓ VERIFIED | 8 个测试，`cd server && uv run pytest tests/test_setup_gate.py -q` → `8 passed` |
| `web/src/api/setup.ts` | `getSetupStatus()` + `initSetup()` API 函数 | ✓ VERIFIED | 存在，两函数均导出，含 JSDoc fail-safe 说明，通过 `~/api/index.ts` 重新导出 |
| `web/src/stores/auth.ts` | `needsSetup` + `setupStatusChecked` refs（State/reset/return 三处） | ✓ VERIFIED | State 区声明（行 23-24）、`$reset()` 重置（行 291-292）、`return` 导出（行 305-306），`grep -c needsSetup` ≥ 3 |
| `web/src/locales/zh-CN.json` | `setup.*` 命名空间 ≥9 个叶节点 | ✓ VERIFIED | 10 个叶节点：title, subtitle, loading, cta, submitting, fields.username, fields.password, fields.confirmPassword, error.connection, error.default |
| `web/src/main.ts` | `router.beforeEach` setup 分支（在 `initAuth` 之前）+ publicPages 含 `/setup` | ✓ VERIFIED | `setupStatusChecked` 检测在行 60，`initAuth()` 在行 85；`publicPages` 含 `'/setup'`；`getSetupStatus` 导入路径正确 |
| `web/src/pages/setup.vue` | i18n 外壳（无硬编码中文文案） | ✓ VERIFIED | 标题/副标题/字段标签/按钮文案全部通过 `t()` 取用；POST 成功后设置 `needsSetup=false; setupStatusChecked=true` 并跳转 `/login` |
| `web/src/api/__tests__/setup.spec.ts` | `getSetupStatus` + `initSetup` 单元测试 | ✓ VERIFIED | 4 个测试，`pnpm vitest run src/api/__tests__/setup.spec.ts` → `4 passed` |

---

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| `server/accounts/views.py` | `server/accounts/permissions.py` | `from .permissions import SetupNotInitialized` | ✓ WIRED | 行 17：`from .permissions import SetupNotInitialized`；`SetupInitView.permission_classes = [AllowAny, SetupNotInitialized]` |
| `server/accounts/views.py` | `_atomic_create_superuser` | `await sync_to_async(_atomic_create_superuser)(...)` | ✓ WIRED | 行 490：`user = await sync_to_async(_atomic_create_superuser)(...)` |
| `server/accounts/urls.py` | `server/friday/urls.py` | `include('accounts.urls')` 挂载到 `/api/auth/` | ✓ WIRED | `friday/urls.py:24`：`path("auth/", include("accounts.urls"))` |
| `web/src/main.ts` | `web/src/api/setup.ts` | `import { getSetupStatus } from '~/api/setup'` | ✓ WIRED | 行 12：`import { getSetupStatus } from '~/api/setup'`；守卫中实际调用 |
| `web/src/main.ts` | `web/src/stores/auth.ts` | `authStore.needsSetup / authStore.setupStatusChecked` | ✓ WIRED | 行 57-78：读写 `authStore.needsSetup` 和 `authStore.setupStatusChecked` |
| `web/src/pages/setup.vue` | `web/src/locales/zh-CN.json` | `const { t } = useI18n(); t('setup.title')` | ✓ WIRED | `setup.vue:19`：`const { t } = useI18n()`；模板中 `t('setup.title')`, `t('setup.subtitle')` 等调用均存在 |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| `SetupStatusView.get` | `is_initialized` | `User.objects.filter(is_superuser=True).exists()` (ORM DB 查询) | ✓ 是 | ✓ FLOWING |
| `SetupInitView.post` | `user` 对象 | `_atomic_create_superuser` → `User.objects.create_superuser(...)` (ORM 写入) | ✓ 是 | ✓ FLOWING |
| `main.ts` router guard | `needsSetup` | `getSetupStatus()` → `GET /api/auth/setup/status/` → 后端 ORM 查询 | ✓ 是 | ✓ FLOWING |
| `setup.vue` onSubmit | `response` | `fetch('/api/auth/setup/', ...)` → 后端 `SetupInitView` | ✓ 是 | ✓ FLOWING |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| 后端 8 个测试全部通过 | `cd server && uv run pytest tests/test_setup_gate.py -q` | `8 passed, 11 warnings in 12.17s` | ✓ PASS |
| 前端 4 个测试全部通过 | `cd web && pnpm vitest run src/api/__tests__/setup.spec.ts` | `4 tests — 1 passed (1)` | ✓ PASS |
| ruff 风格检查通过 | `cd server && uv run ruff check accounts/permissions.py accounts/views.py accounts/serializers.py accounts/urls.py tests/test_setup_gate.py` | `All checks passed!` | ✓ PASS |

---

### Probe Execution

Step 7c: SKIPPED（本阶段无 `scripts/*/tests/probe-*.sh` 文件；功能验证通过 pytest + vitest 完成）

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ---------- | ----------- | ------ | -------- |
| SETUP-01 | 01-02 | 系统检测到不存在任何超级管理员时，用户首次访问 Web 自动进入首启初始化向导 | ✓ SATISFIED | `main.ts` router guard + `getSetupStatus()` + `needsSetup → next('/setup')` 实现自动重定向；E2E 需人工验证 |
| SETUP-02 | 01-01 (backend) + 01-02 (frontend) | 后端提供只读「初始化状态」接口，前端路由守卫据此放行 | ✓ SATISFIED | `SetupStatusView` AllowAny GET，前端 `getSetupStatus()` 在 `initAuth()` 前调用 |
| SETUP-03 | 01-01 (backend 403) + 01-02 (frontend redirect) | 向导完成后初始化接口与界面对所有访问者关闭 | ✓ SATISFIED | 后端 `SetupNotInitialized` 返回 403；前端守卫 `!needsSetup && to.path === '/setup' → next('/login')` |
| SETUP-04 | 01-01 | 初始化接口 fail-closed，防重入/并发保护 | ✓ SATISFIED | `transaction.atomic()` + double-check + `IntegrityError` 捕获；`test_duplicate_post_rejected` PASSED |

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| `web/src/pages/setup.vue` | 69 | `'设置失败，请重试'` 硬编码中文（错误回退值） | ℹ️ Info | i18n 约束轻微偏差：`t('setup.error.default')` 已在 zh-CN.json 定义且内容相同；此处为 `catch (e: unknown)` 中 `e instanceof Error` 为 false 时的兜底字符串，仅在极少数非 Error 异常时触发；用户体验与 i18n 版本一致，无功能影响 |

无 TBD / FIXME / XXX 标记；无桩代码；无空实现；无孤立文件。

---

### Human Verification Required

#### 1. SETUP-01 端对端浏览器重定向

**Test:** 在本地启动后端（空 DB，无 superuser），然后启动前端（`pnpm dev`），以浏览器访问 `http://localhost:5173/` 或任意受保护页面（如 `/settings`）
**Expected:**

1. 页面自动跳转到 `http://localhost:5173/setup`，显示「首次设置」向导界面（标题「首次设置」，副标题显示正确，表单可填写）
2. 填写用户名/密码/确认密码并提交，等待 201 响应后自动跳转 `/login`
3. 登录后再次访问 `/setup` → 自动跳转到 `/login`（向导不再出现）
4. 刷新任意页面，不再进入向导

**Why human:** 完整浏览器导航流程（网络请求 + 路由渲染 + cookie + 历史记录）无法通过 grep/单元测试覆盖；01-VALIDATION.md 已登记此 Manual-Only 条目

---

### Gaps Summary

无自动化可检测的 gap。所有 4 条成功标准通过代码验证。唯一未闭合项为人工验证所需的 E2E 浏览器流程（SETUP-01），这是正常的 Manual-Only 验证项，不阻塞阶段目标判定。

---

*Verified: 2026-06-08T15:51:00+08:00*
*Verifier: Claude (gsd-verifier)*
