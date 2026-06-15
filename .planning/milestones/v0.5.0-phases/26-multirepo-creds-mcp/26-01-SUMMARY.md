---
phase: 26-multirepo-creds-mcp
plan: 01
subsystem: auth
tags: [git-credentials, fernet, gitlab, sync_to_async, django-orm]

# Dependency graph
requires:
  - phase: 21-provider-credentials
    provides: common.encryption Fernet 加密路径（encrypt_value/decrypt_value）
provides:
  - GitInstanceCredential 实例级 Git 凭证模型（host 唯一 + Fernet 加密 token）
  - 迁移 0036（仅建表、不回填）
  - services/git_credentials.py 单一凭证解析器（per-repo 优先 → 实例池 host fallback → None）
affects: [26-02, 26-03, 26-04]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "单一凭证解析入口：Wave 2 接线统一调 resolve_git_token_sync / aresolve_git_token，禁止各自重写取 token 逻辑"
    - "host 归一：SSH/HTTPS 双格式解析出同一小写 host（含端口），unique 约束防错配"

key-files:
  created:
    - server/repositories/migrations/0036_git_instance_credential.py
    - server/services/git_credentials.py
    - server/tests/services/test_git_credentials.py
  modified:
    - server/repositories/models.py

key-decisions:
  - "实例凭证落在既有 repositories app（与 GitCredential 同层），表名 git_instance_credentials"
  - "_extract_git_host 复用 git_platform.extract_gitlab_url 的 SSH/HTTPS 口径，保留端口"
  - "per-repo 凭证存在但 token 为空（如 SSH key）时落到实例池，避免无 token 凭证阻断 fallback"

patterns-established:
  - "凭证解析优先级：per-repo 显式 token（向后兼容）→ host 实例池 → None（调用方保留既有缺凭证报错）"
  - "token 安全：仅记 has_token/source 布尔，明文绝不进日志（威胁 T-26-02）"

requirements-completed: [REPO-01]

# Metrics
duration: ~20min
completed: 2026-06-15
---

# Phase 26 Plan 01: 多仓凭证统一数据与解析地基 Summary

**GitInstanceCredential 按 host 维度集中存 Fernet 加密 token，配套单一解析器 per-repo 优先 → 实例池 host fallback，多仓复用一份凭证且向后兼容**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-06-15T00:14:00Z
- **Completed:** 2026-06-15T00:34:00Z
- **Tasks:** 2
- **Files modified:** 4（3 created + 1 modified）

## Accomplishments
- 新增 `GitInstanceCredential` 实例级凭证模型：host 唯一、provider（默认 gitlab，可扩展）、Fernet 加密 `encrypted_token`、label、时间戳；`__str__` 仅含 `provider:host`，绝不泄漏 token。
- 迁移 0036（依赖 0035）：单一 CreateModel，仅建表、不回填，`makemigrations --check` 干净。
- `services/git_credentials.py` 单一解析器：`resolve_git_token_sync` / `aresolve_git_token` + `_extract_git_host`，per-repo token 优先、实例池 host fallback、无凭证返回 None。
- 11 个守护单测全绿（含 plan 指定的 Test A–F）。

## Task Commits

1. **Task 1: GitInstanceCredential 模型 + 迁移 0036** - `160f32905` (feat)
2. **Task 2 (RED): 解析器守护测试** - `202650f98` (test)
3. **Task 2 (GREEN): resolve_git_token 解析器** - `6f40cdce8` (feat)

_TDD：Task 2 走 RED（test）→ GREEN（feat）双提交；无 refactor。_

## Files Created/Modified
- `server/repositories/models.py` - 新增 `GitInstanceCredential` 模型（host 唯一 + 加密 token）
- `server/repositories/migrations/0036_git_instance_credential.py` - 建表迁移（仅建表、不回填）
- `server/services/git_credentials.py` - 凭证解析器 + host 归一化
- `server/tests/services/test_git_credentials.py` - host 解析 + 解析优先级 + 不泄漏守护测试

## Decisions Made
- 实例凭证模型落在既有 `repositories` app（与 `GitCredential` 同层），表名 `git_instance_credentials`。
- `_extract_git_host` 复用 `git_platform.extract_gitlab_url` 的 SSH 正则 + urlparse netloc 口径，保留端口、去掉认证段、归一小写。
- per-repo 凭证存在但 `encrypted_token` 为空（如 SSH key 类型）时，解析器落到实例池——避免无 token 的 per-repo 凭证误判为「已配置」而阻断 fallback（额外补一条守护测试）。

## Deviations from Plan

None - plan executed exactly as written.

（实现中额外补了一条测试 `test_per_repo_credential_without_token_falls_through` 覆盖「per-repo 凭证存在但无 token」边界，属测试加固，非行为偏离。）

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Wave 2（26-02 mirror / 26-03 indexer / 26-04 REST+前端）可直接引用 `resolve_git_token_sync` / `aresolve_git_token`，无需重写取 token 逻辑。
- 迁移 0036 已就绪，部署侧 `migrate` 后实例凭证表可用；REST/前端 CRUD 由 26-04 落地。

## Self-Check: PASSED

- 文件全部存在：models.py、migration 0036、git_credentials.py、test_git_credentials.py、26-01-SUMMARY.md
- 提交全部存在：`160f32905`（model+migration）、`202650f98`（RED test）、`6f40cdce8`（GREEN 解析器）
- 验证：`makemigrations --check` 干净；`pytest tests/services/test_git_credentials.py` 11 passed；`ruff check` 干净

---
*Phase: 26-multirepo-creds-mcp*
*Completed: 2026-06-15*
