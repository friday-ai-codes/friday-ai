---
phase: 01-setup-gate
fixed_at: 2026-06-08T16:09:00+08:00
review_path: .planning/phases/01-setup-gate/01-REVIEW.md
iteration: 1
findings_in_scope: 2
fixed: 2
skipped: 0
status: all_fixed
---

# Phase 01: Code Review Fix Report

**Fixed at:** 2026-06-08T16:09:00+08:00
**Source review:** .planning/phases/01-setup-gate/01-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 2（WR-01、WR-02；scope=critical_warning，Info 级别不纳入）
- Fixed: 2
- Skipped: 0

## Fixed Issues

### WR-01: Postgres READ COMMITTED 下不同用户名并发可创建两个 superuser

**Files modified:** `server/accounts/migrations/0006_add_single_superuser_constraint.py`
**Commit:** `1707c3ce`
**Applied fix:**
新增 migration `0006_add_single_superuser_constraint.py`，通过 `RunSQL` 在 `users` 表上创建 partial unique index：
```sql
CREATE UNIQUE INDEX IF NOT EXISTS accounts_user_single_superuser
ON users (is_superuser)
WHERE is_superuser = TRUE;
```
SQLite 3.8.9+ 与 Postgres 均支持 partial unique index。第二个并发事务提交时触发 `IntegrityError`，由 `SetupInitView` 现有的 `except IntegrityError → HTTP 409` 兜底逻辑处理，无需修改 views.py。

**验证结果（在实际 main 分支上运行）：**
```
uv run python manage.py makemigrations --check → exit 0，No changes detected
uv run pytest tests/test_setup_gate.py -q      → 8 passed
uv run ruff check accounts/                    → 1 pre-existing I001（0005_backfill_user_source.py），
                                                  被修改文件 0 错误
```

---

### WR-02: `setup.vue` onMounted 使用硬编码 raw fetch 而非 API 工具函数

**Files modified:** `web/src/pages/setup.vue`
**Commit:** `aa85dcc4`
**Applied fix:**
`onMounted` 中的 `fetch('/api/auth/setup/status/')` + 手动 `res.json()` 替换为 `await getSetupStatus()`（已在 `<script setup>` 中 import）。响应字段 `setupStatus.needs_setup` 与原逻辑一致；`onSubmit` 的 raw fetch 保持不变（有意为之，避免触发全局 `auth:forbidden` 重定向）。

**验证结果（在实际 main 分支上运行）：**
```
pnpm vitest run src/api/__tests__/setup.spec.ts → 4 passed
```

---

## Skipped Issues

无。

---

_Fixed: 2026-06-08T16:09:00+08:00_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
