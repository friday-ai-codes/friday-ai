---
phase: 02-admin-account
plan: "01"
subsystem: backend
tags: [setup, admin, auth, session, password-strength, ADMIN-01, ADMIN-02, ADMIN-03]
dependency_graph:
  requires: [setup-init-api, SetupNotInitialized-permission]
  provides: [setup-session-cookies, setup-password-strength]
  affects: [server/accounts/serializers.py, server/accounts/views.py, server/tests/test_setup_gate.py]
tech_stack:
  added: []
  patterns: [django-password-validators, cookie-jwt-session, adrf-async-view, sync_to_async-orm-bridge]
key_files:
  created: []
  modified:
    - server/accounts/serializers.py
    - server/accounts/views.py
    - server/tests/test_setup_gate.py
decisions:
  - "复用 settings.AUTH_PASSWORD_VALIDATORS（4 校验器）做强度校验，传入临时 User 使相似度校验生效"
  - "password min_length 6 → 8，与 MinimumLengthValidator 默认对齐；既有成功路径测试改用强口令"
  - "创建成功后复用 LoginView 的 cookie-JWT 路径下发 refresh_token/access_token，返回 LoginResponseSerializer 体"
  - "不显式置 must_change_password（create_superuser 默认 False）"
metrics:
  completed: "2026-06-08"
  tasks_completed: 3
  files_changed: 3
---

# Phase 02 Plan 01: 后端管理员会话 + 密码强度 Summary

**One-liner:** 在同一 `POST /api/auth/setup/` 端点上增强 —— Django 校验器做密码强度校验（ADMIN-01）、创建 superuser 后复用 cookie-JWT 路径下发会话并返回 `{access_token,user,must_change_password}`（ADMIN-03）、不强制改密（ADMIN-02）；Phase 1 门禁/防重入不回退。

## Tasks Completed

| Task | Name | Files |
|------|------|-------|
| 1 | SetupInitSerializer 密码强度校验 | `server/accounts/serializers.py` |
| 2 | SetupInitView 创建后下发 cookie-JWT 会话 | `server/accounts/views.py` |
| 3 | 扩展后端测试覆盖 ADMIN-01/02/03 | `server/tests/test_setup_gate.py` |

提交：`028e4d09`（feat(02): backend admin setup session + password strength）

## What Was Built

### `server/accounts/serializers.py`
- 导入 Django `validate_password`（别名 `dj_validate_password`）与 `ValidationError`。
- `SetupInitSerializer.password` min_length 由 6 改为 8（文案「密码至少 8 位」）。
- 新增 `validate_password(self, value)`：以未保存的 `User(username=...)` 调用 Django 校验器，捕获 `DjangoValidationError` → 转为中文字段错误（透传 zh-hans 消息）。`validate_username` 不变。

### `server/accounts/views.py`
- `SetupInitView.post` 成功分支：`RefreshToken.for_user(user)`（`sync_to_async`）+ `sub` claim，返回 `LoginResponseSerializer({access_token,user,must_change_password})`（201），并 `set_cookie` 下发 `refresh_token`（7天）与 `access_token`（ACCESS_TOKEN_LIFETIME），flags 复用 `settings.COOKIE_*`，与 `LoginView` 一致。
- 门禁、`_atomic_create_superuser`、IntegrityError/并发 409 分支保持不变。

### `server/tests/test_setup_gate.py`
- 既有成功路径改用 `STRONG_PASSWORD`；`test_short_password` 改述为「<8 位 400」。
- 新增：`test_numeric_password_rejected`、`test_common_password_rejected`、`test_password_similar_to_username_rejected`（ADMIN-01）；`test_create_does_not_force_password_change`（ADMIN-02）；`test_session_cookies_set`（ADMIN-03）；`test_created_admin_can_login`（ADMIN-02）。

## Deviations from Plan

None — 按计划实现。`LoginResponseSerializer` 已在 views.py 导入列表中，无需新增导入。

## Verification Results

```
cd server && uv run pytest tests/test_setup_gate.py -q
14 passed, 17 warnings in 7.56s

cd server && uv run pytest tests/test_auth.py -q
11 passed (无回归)

cd server && uv run ruff check accounts/serializers.py accounts/views.py tests/test_setup_gate.py
All checks passed!
```

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| ✅ T-2-02 mitigated | `accounts/serializers.py` | 后端 Django 四校验器为权威强度校验，min_length=8 |
| ✅ T-2-03 mitigated | `accounts/views.py` | 会话 cookie 复用 settings.COOKIE_* 与 LoginView 完全一致 |
| ✅ ADMIN-02 | `accounts/views.py` | must_change_password 保持默认 False，有测试断言 |

## Self-Check: PASSED

| Item | Status |
|------|--------|
| serializers.py validate_password | FOUND |
| views.py set_cookie + RefreshToken.for_user | FOUND |
| test_setup_gate.py must_change_password/refresh_token/login | FOUND |
| pytest 14 passed | VERIFIED |
| ruff all passed | VERIFIED |
