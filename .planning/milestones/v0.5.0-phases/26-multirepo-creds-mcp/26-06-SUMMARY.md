---
phase: 26-multirepo-creds-mcp
plan: 06
subsystem: auth
tags: [git-credentials, gitlab, merge-request, dispatch, sync_to_async, gap-closure]

# Dependency graph
requires:
  - phase: 26-multirepo-creds-mcp
    plan: 01
    provides: services/git_credentials.py 解析器（resolve_git_token_sync / aresolve_git_token）
provides:
  - 残留 6 文件 ≥8 处内联 decrypt_value(encrypted_token) 取 token 全部改经统一解析器（D-02 缺口闭合）
  - 实例池-only 同 host 仓库在 PR 创建/cross-ref/冲突预检/code review diff/两处容器 dispatch/既有仓库测试连接全路径可解析 token
  - gap 守护测试（dispatch 注入 + git 平台 client 两类代表入口，实例池-only 解析 + per-repo 优先 + 缺凭证不回退 + token 不泄漏）
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "所有 git-token 读取（平台 client / 容器 dispatch / 测试连接既有仓库分支）统一经 aresolve_git_token，禁止内联 GitCredential→decrypt_value"
    - "解析器返回 None 时各调用方保留既有缺凭证报错/降级文案（行为不回退）"

key-files:
  created:
    - server/tests/test_git_credential_gap_wiring.py
  modified:
    - server/workflows/nodes/git/pr.py
    - server/orchestration/coding_graph.py
    - server/workflows/nodes/ai/code_review.py
    - server/repositories/summary_service.py
    - server/agents/tools/chat_tools.py
    - server/repositories/views.py

key-decisions:
  - "六处全为 async 上下文 → 统一用 aresolve_git_token；TestConnection 仅『既有仓库（repository_id）』分支接解析器，『用户当场输入 token』分支保持不变"
  - "code_review.py 去掉已无用的 select_related('credential')（解析器自行查 GitCredential/GitInstanceCredential）"
  - "coding_graph PR 创建分支由 try/except DoesNotExist 收敛为『解析器 None → 既有 Git 凭据未配置报错』，语义不变"

patterns-established:
  - "git-token 单一来源贯穿全部平台/派发/校验路径：per-repo 优先 → host 实例池 fallback → None"

requirements-completed: [REPO-01]

# Metrics
duration: ~20min
completed: 2026-06-15
---

# Phase 26 Plan 06: 多仓凭证统一接线缺口闭合（D-02） Summary

**把 26-VERIFICATION 标记的残留 6 文件 ≥8 处内联 `decrypt_value(credential.encrypted_token)` 取 token 全部改经统一解析器 `aresolve_git_token`，使仅靠实例凭证池（无 per-repo token）的同 host 仓库在 PR 创建/cross-reference/冲突预检/code review diff 拉取/两处容器 dispatch/既有仓库测试连接路径不再失败或注入空 token**

## Performance

- **Duration:** ~20 min
- **Completed:** 2026-06-15
- **Tasks:** 2（实现 + 守护测试）
- **Files modified:** 7（6 modified + 1 created）

## Accomplishments

- **平台 client 路径（3 文件）：** `workflows/nodes/git/pr.py` PR 创建 + cross-reference 更新、`orchestration/coding_graph.py` 冲突预检 `compare_branches` + PR 创建、`workflows/nodes/ai/code_review.py` `get_merge_request_diff` 三处均经 `aresolve_git_token(repository)`，缺凭证保留各自既有文案（`No access token configured for repository` / `Git 凭据未配置，无法创建 PR` / `仓库未配置访问凭证`）。
- **容器 dispatch token 注入（2 文件）：** `repositories/summary_service._build_env_metadata`、`agents/tools/chat_tools` explore 派发两处经解析器，仅 token 非空才注入 `env_FRIDAY_TASK_GIT_ACCESS_TOKEN`（不再注入空 token）。
- **既有仓库测试连接（1 文件）：** `repositories/views.TestConnectionView` `repository_id` 既有仓库分支经解析器；`else` 用户当场输入 token 分支保持不变。
- **清理：** 移除随接线失效的 `decrypt_value` / `GitCredential` 内联导入（pr.py / code_review.py / views.py / 三处 lazy import），去掉 code_review.py 已无用的 `select_related("credential")`。
- **守护测试：** 新建 `test_git_credential_gap_wiring.py`（6 测），驱动两类真实入口（dispatch 注入 via `summary_service._build_env_metadata`、平台 client via `CreatePRNode._create_pr_for_repository`），覆盖实例池-only 解析 / per-repo 优先 / 缺凭证文案不回退 / token 不进日志。
- **grep 确认：** 全 `server/`（除 tests 与解析器自身实现）已无 resolver-bypassing 的 `decrypt_value(...encrypted_token)` 取 token。

## Task Commits

1. **Task 1: 残留内联取 token 统一经凭证解析器** - `b76a9f1d6` (refactor)
2. **Task 2: 残留取 token 路径接线守护测试** - `39d351ad7` (test)

## Files Created/Modified

- `server/workflows/nodes/git/pr.py` - PR 创建 + cross-reference 两处经 `aresolve_git_token`；去 `decrypt_value` / `GitCredential` 导入
- `server/orchestration/coding_graph.py` - 冲突预检 + PR 创建两处经解析器（lazy import 改 `aresolve_git_token`）
- `server/workflows/nodes/ai/code_review.py` - `get_merge_request_diff` 经解析器；去 `decrypt_value` 导入 + 无用 `select_related`
- `server/repositories/summary_service.py` - 容器 dispatch git token 注入经解析器
- `server/agents/tools/chat_tools.py` - explore 派发 git token 注入经解析器
- `server/repositories/views.py` - TestConnection 既有仓库分支经解析器；去 `decrypt_value` 导入
- `server/tests/test_git_credential_gap_wiring.py` - gap 守护测试（6 测）

## Decisions Made

- 六处均 async → 统一 `aresolve_git_token`，无需 `resolve_git_token_sync`。
- TestConnection 严格区分两分支：既有仓库走解析器、用户当场输入 token 不变（符合 VERIFICATION `missing` 指示）。
- coding_graph PR 创建由 `GitCredential.objects.aget` + `except DoesNotExist` 收敛为「解析器 None → 既有报错」，删除冗余 try/except，行为等价。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] 移除 code_review.py 失效的 `select_related("credential")`**
- **Found during:** Task 1（code_review.py 接线）
- **Issue:** 接线改走解析器后不再访问 `repository.credential`，`select_related("credential")` 成为无用 join。
- **Fix:** 改为普通 `Repository.objects.filter(...)`。
- **Files modified:** `server/workflows/nodes/ai/code_review.py`
- **Verification:** ruff clean；模块 import OK；guard 测试经平台 client 路径全绿
- **Committed in:** `b76a9f1d6`

---

**Total deviations:** 1 auto-fixed（1 bug/cleanup）
**Impact on plan:** 纯机械替换 + 死代码清理，无新设计、无 scope creep。

## Issues Encountered

None（功能层面）。

## Verification

- `ruff check`（6 接线文件 + 1 测试）干净；6 模块 `django.setup()` import OK。
- `pytest tests/test_git_credential_gap_wiring.py` → 6 passed。
- 回归 `pytest tests/services/test_git_credentials.py tests/services/test_git_credential_clone_wiring.py tests/test_git_credential_platform_wiring.py tests/repositories/test_git_instance_credentials.py tests/test_coding_session_service.py tests/test_git_credential_gap_wiring.py` → 49 passed。
- `grep -rn 'decrypt_value(...encrypted_token)' server --glob '!**/tests/**'` → 仅 `services/git_credentials.py` 解析器自身两处。

## Next Phase Readiness

- D-02「所有 git 平台 API / 容器 dispatch 取 token 路径统一经解析器」缺口闭合，REPO-01 成功标准 1「同一 GitLab 实例多仓可复用同一凭证」全路径达成。
- Phase 26 可重新评估 verification → v0.5.0 收口。

## Self-Check: PASSED

- 文件全部存在：pr.py / coding_graph.py / code_review.py / summary_service.py / chat_tools.py / views.py（modified）、test_git_credential_gap_wiring.py（created）、26-06-SUMMARY.md
- 提交全部存在：`b76a9f1d6`、`39d351ad7`

---
*Phase: 26-multirepo-creds-mcp*
*Completed: 2026-06-15*
