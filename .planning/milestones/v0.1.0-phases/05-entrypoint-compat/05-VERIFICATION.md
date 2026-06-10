---
phase: 05-entrypoint-compat
verified: 2026-06-08T17:34:40+08:00
status: passed
score: 4/4 must-haves verified
overrides_applied: 0
---

# Phase 05: 入口迁移与向后兼容 Verification Report

**Phase Goal:** entrypoint 默认不再自动建管理员（改由向导承担），保留运维兜底命令，已有部署升级后行为不回退、不出现向导。
**Verified:** 2026-06-08T17:34:40+08:00
**Status:** passed（4/4 成功标准通过代码/命令/测试验证；无人工待办、无 gap）

---

## Goal Achievement

### Observable Truths

| # | Truth (Success Criterion) | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1 | `server/entrypoint.sh` 默认不再调用 `init_superuser` 自动建管理员（COMPAT-01） | ✓ VERIFIED | `grep -E "^[[:space:]]*python manage\.py init_superuser" server/entrypoint.sh` 无匹配；仅保留中文注释说明（不再自动建号 + 运维兜底）。`bash -n` 语法 OK；migrate/bootstrap/collectstatic/gunicorn 步骤保留。k8s 等价 `migration-job.yaml` 亦移除该调用。 |
| 2 | `init_superuser` 与 `reset_superuser_password` 命令保留，仍可手动建/重置（COMPAT-02） | ✓ VERIFIED | 两命令文件存在且本阶段零改动（`git log` 命令目录最近提交早于 Phase 5）；`uv run python manage.py help` 同时列出 `init_superuser` 与 `reset_superuser_password`；env 驱动用法（`FRIDAY_ADMIN_*`）未变。 |
| 3 | 已存在 superuser 的部署升级后不出现向导、行为不回退（COMPAT-03） | ✓ VERIFIED | 未改门禁：`SetupStatusView.is_initialized = User.objects.filter(is_superuser=True).exists()`（`accounts/views.py:445`）。已有 superuser → `is_initialized=true` → 向导 403/关闭（Phase 1 行为）。`uv run pytest tests/test_setup_gate.py -q` → **14 passed**（门禁未回退）。`init_superuser` 仍 fail-closed（存在 superuser 即跳过），保留亦幂等。 |
| 4 | 仅全新部署（无 superuser）升级后才进入首启向导 | ✓ VERIFIED | 同一门禁：无 superuser → `is_initialized=false` → `needs_setup=true` → 进向导（Phase 1，`test_setup_gate.py` 覆盖 `test_status_not_initialized` 等）。Phase 5 未引入任何绕过向导的隐式 env 自动建号路径。 |

**Score:** 4/4 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `server/entrypoint.sh` | 移除 init_superuser 调用 + 中文注释 | ✓ VERIFIED | 无可执行调用；注释说明原因与运维兜底命令 |
| `deploy/helm/friday/templates/migration-job.yaml` | 移除 init_superuser 调用 + 失效 admin env | ✓ VERIFIED | Job 仅留 migrate + 注释；`FRIDAY_ADMIN_*` env 移除；YAML 结构完整 |
| `scripts/verify-runner-e2e.sh` | 健康检查后显式 init_superuser | ✓ VERIFIED | `:93 docker exec friday-server python manage.py init_superuser`，修复 `User.objects.first()` 断链 |
| `scripts/setup.sh` | 提示/注释同步 | ✓ VERIFIED | 密码提示语 + `# 管理员配置` 注释更新；env 照写 |
| `.env.example` | `FRIDAY_ADMIN_*` 注释为命令兜底用途 | ✓ VERIFIED | 注释明确启动期不再自动建号 |
| `docs/guide/quick-start.md` / `docs/guide/admin.md` | 文案改为向导 + 命令兜底 | ✓ VERIFIED | 无遗留"首次启动自动创建管理员"误导文案 |
| `init_superuser.py` / `reset_superuser_password.py` | 保留不改动 | ✓ VERIFIED | 存在、注册、Phase 5 未改 |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| entrypoint 无可执行建号调用 | `grep -E "^\s*python manage.py init_superuser" server/entrypoint.sh` | 无匹配 | ✓ PASS |
| entrypoint 语法 | `bash -n server/entrypoint.sh` | OK | ✓ PASS |
| 命令仍注册 | `uv run python manage.py help \| grep -E "init_superuser\|reset_superuser_password"` | 两命令均列出 | ✓ PASS |
| Phase 1 门禁回归 | `cd server && uv run pytest tests/test_setup_gate.py -q` | `14 passed` | ✓ PASS |
| e2e 脚本语法 | `bash -n scripts/verify-runner-e2e.sh` | OK | ✓ PASS |

---

### Requirements Coverage

| Requirement | Source Plan | Status | Evidence |
| ----------- | ---------- | ------ | -------- |
| COMPAT-01 | 05-01 | ✓ SATISFIED | entrypoint + helm migration-job 去除 init_superuser 自动调用 |
| COMPAT-02 | 05-01 | ✓ SATISFIED | 两命令保留、注册、env 驱动用法不变 |
| COMPAT-03 | 05-01 | ✓ SATISFIED | Phase 1 门禁未改 + 14 测试回归通过；无绕过向导的新路径 |

---

### Anti-Patterns Found

无 TBD/FIXME/桩代码。`docs/guide/quick-start.md` 本地开发段保留 Django 内置 `createsuperuser`（有意，非误导：本地开发手动建号步骤）。`docker-compose.yaml` 的 `FRIDAY_ADMIN_*` env 有意保留（启动期 inert，支撑 `docker exec ... init_superuser` 运维兜底，零回退）。

---

### Gaps Summary

无自动化可检测 gap。4/4 成功标准均由代码/命令/测试验证；纯 shell/yaml/docs 改动，无需新增自动化测试；向后兼容由 Phase 1 门禁天然保证并经回归确认。

---

*Verified: 2026-06-08T17:34:40+08:00*
