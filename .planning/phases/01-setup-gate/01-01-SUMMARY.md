---
phase: 01-setup-gate
plan: "01"
subsystem: backend
tags: [setup-gate, permissions, auth, api, SETUP-02, SETUP-03, SETUP-04]
dependency_graph:
  requires: []
  provides: [setup-status-api, setup-init-api, SetupNotInitialized-permission]
  affects: [server/accounts/views.py, server/accounts/urls.py, server/accounts/permissions.py, server/accounts/serializers.py]
tech_stack:
  added: []
  patterns: [adrf-async-view, sync_to_async-orm-bridge, drf-permission-class, transaction-atomic-double-check]
key_files:
  created:
    - server/accounts/permissions.py
    - server/tests/test_setup_gate.py
  modified:
    - server/accounts/serializers.py
    - server/accounts/views.py
    - server/accounts/urls.py
decisions:
  - "authentication_classes=[] on SetupInitView to ensure 403 not 401 for anonymous requests"
  - "SetupNotInitialized reusable permission class in accounts/permissions.py"
  - "_atomic_create_superuser with transaction.atomic() + double-check, no select_for_update (SQLite incompatible)"
metrics:
  duration: "~25 min"
  completed: "2026-06-08"
  tasks_completed: 2
  files_changed: 5
---

# Phase 01 Plan 01: 后端门禁层实现 Summary

**One-liner:** JWT-free setup gate with `SetupNotInitialized` permission + atomic double-check via `transaction.atomic()`, exposing `GET /api/auth/setup/status/` (AllowAny) and `POST /api/auth/setup/` (fail-closed, 403 when initialized).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | 后端测试先行（RED 阶段） | `4498c478` | `server/tests/test_setup_gate.py` |
| 2 | 实现后端门禁层（GREEN 阶段） | `37c131dc` | `permissions.py`, `serializers.py`, `views.py`, `urls.py` |

## What Was Built

### `server/accounts/permissions.py` (新建)
- `SetupNotInitialized(BasePermission)`：fail-closed 门禁，`has_permission` 同步查询 `User.objects.filter(is_superuser=True).exists()`，存在即返回 `False`（403）。可复用于 Phase 2 管理员创建接口。

### `server/accounts/serializers.py` (追加)
- `SetupInitSerializer`：请求体校验，`username`（min_length=1）、`password`（min_length=6）、`display_name`（可选，默认"系统管理员"）。`validate_username` 在 `sync_to_async` 线程中安全查重。

### `server/accounts/views.py` (追加)
- `SetupStatusView`（GET）：`AllowAny`，异步返回 `{is_initialized, needs_setup}`，不泄露用户信息（SETUP-02）。
- `_atomic_create_superuser`：`transaction.atomic()` 内 double-check + `create_superuser`，返回 `None` 表示已存在，`IntegrityError` 作最终兜底（SETUP-04）。
- `SetupInitView`（POST）：`authentication_classes=[]` + `[AllowAny, SetupNotInitialized]`，防止 DRF 返回 401 而非 403（SETUP-03）。

### `server/accounts/urls.py` (追加)
- `GET /api/auth/setup/status/` → `SetupStatusView`（`name="setup-status"`）
- `POST /api/auth/setup/` → `SetupInitView`（`name="setup-init"`）

### `server/tests/test_setup_gate.py` (新建)
- `TestSetupStatusView`：3 个测试（未初始化、已初始化、无认证可访问）
- `TestSetupInitView`：5 个测试（成功 201、已初始化 403、重复请求 403、缺密码 400、短密码 400）
- 全部 8 个测试 PASSED

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] authentication_classes=[] 确保 SetupInitView 返回 403 而非 401**
- **Found during:** Task 2 GREEN 阶段验证
- **Issue:** DRF `permission_denied()` 检查 `request.authenticators`：若存在 authenticator（默认 JWT/Session）但无成功认证，抛 `NotAuthenticated (401)` 而非 `PermissionDenied (403)`。`AllowAny` 不影响此路径。
- **Fix:** 在 `SetupInitView` 上设置 `authentication_classes = []`，清空 authenticator 列表，使 permission 拒绝时直接返回 403。
- **Files modified:** `server/accounts/views.py`
- **Commit:** `37c131dc`（包含在 GREEN 提交中）

## Verification Results

```
cd server && uv run pytest tests/test_setup_gate.py -q
8 passed, 11 warnings in 7.52s

cd server && uv run ruff check accounts/permissions.py accounts/serializers.py accounts/views.py accounts/urls.py
All checks passed!
```

## Known Stubs

None — all endpoints are fully wired and tested.

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| ✅ T-1-01 mitigated | `accounts/permissions.py` | `SetupNotInitialized` fail-closed: 存在任意 is_superuser=True 用户即 403 |
| ✅ T-1-02 mitigated | `accounts/views.py` | `transaction.atomic()` + double-check + IntegrityError 捕获 |
| ✅ T-1-03 mitigated | `accounts/views.py` | `SetupStatusView` 仅返回 `{needs_setup, is_initialized}` 布尔字段 |

## Key Decisions

1. **`authentication_classes = []` on SetupInitView** — 必要补丁，确保匿名请求被 `SetupNotInitialized` 拒绝时返回 403 而非 DRF 默认的 401。CONTEXT 中仅描述了意图（返回 403），实现细节由 executor 自主决定。
2. **`SetupNotInitialized` 放于独立文件 `accounts/permissions.py`** — 按 CONTEXT 决策 B，保证单一门禁来源，供 Phase 2 复用。
3. **不用 `select_for_update()`** — SQLite 不支持，会抛 `NotSupportedError`；以事务内 double-check + UNIQUE 约束兜底实现并发安全。

## Self-Check: PASSED

| Item | Status |
|------|--------|
| `server/accounts/permissions.py` | FOUND |
| `server/accounts/views.py` | FOUND |
| `server/tests/test_setup_gate.py` | FOUND |
| commit `4498c478` (RED) | FOUND |
| commit `37c131dc` (GREEN) | FOUND |
| pytest 8 passed | VERIFIED |
| ruff check all passed | VERIFIED |
