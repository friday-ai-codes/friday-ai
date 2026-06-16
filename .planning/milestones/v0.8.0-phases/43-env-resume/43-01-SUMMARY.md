---
phase: 43-env-resume
plan: 01
subsystem: api
tags: [dispatch-metadata, git-credentials, env-injection, ssh-to-https, workflow-coding, pf-06]

# Dependency graph
requires:
  - phase: 26-git-credentials
    provides: aresolve_git_token 统一 token 解析入口（per-repo → host 实例池 fallback）
  - phase: 42-chat-entry
    provides: chat coding_session_service.build_dispatch_metadata（PF-06 对齐权威基线）
provides:
  - _run_repo_coding 注入对称顶层 env_FRIDAY_TASK_GIT_*（token 非空时）
  - env_FRIDAY_TASK_BRANCH_STRATEGY(=branch_name)/TARGET_BRANCH(=base_branch) 多仓 per-repo 注入
  - token 认证时 git@ SSH URL → HTTPS DispatchTask.repo_url 改写
  - PF-06 dispatch metadata env 键集合守护测试（含 token 不泄漏 + 零回归断言）
affects: [44-wave-scheduling, 45-artifact-injection, 46-fusion-pr, callback-driven-coding]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "env_ 前缀顶层 metadata 注入（runner TrimPrefix 契约，nested dict 不被消费）"
    - "凭证脱敏日志：仅记 has_git_token 布尔，token 绝不入日志"
    - "TDD RED-first：真实 _run_repo_coding + IO 边界 mock 断言 DispatchTask"

key-files:
  created: []
  modified:
    - server/workflows/nodes/ai/coding.py
    - server/tests/test_coding_node.py

key-decisions:
  - "env_FRIDAY_TASK_GIT_SSL_VERIFY 硬编码 \"false\" 对齐 chat 权威基线（Open Q1 RESOLVED），不取 per-repo credential.ssl_verify"
  - "BRANCH_STRATEGY/TARGET_BRANCH 取本次调用的 branch_name/base_branch 参数（多仓 per-repo），非单仓 execution_spec"
  - "既有 nested git_credentials dict 原样保留（零回归），新增顶层 env_ 键才是真正生效路径"

patterns-established:
  - "PF-06 逐键对齐 chat build_dispatch_metadata：git token env + SSH→HTTPS 正则改写 + 分支 env"
  - "RED-first TDD：6 断言中 4 个新行为先红、2 个零回归守护先绿，证明断言真实生效"

requirements-completed: [PF-06]

# Metrics
duration: ~20min
completed: 2026-06-16
---

# Phase 43 Plan 01: 编码 env 对齐（PF-06）Summary

**workflow 编码路径 `_run_repo_coding` 逐键对齐 chat 基线——注入顶层 `env_FRIDAY_TASK_GIT_*` + `BRANCH_STRATEGY`/`TARGET_BRANCH` 并改写 SSH→HTTPS repo_url，使私有仓 clone 成功且用正确目标分支**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-06-16T10:08:00Z
- **Completed:** 2026-06-16T10:18:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- `_run_repo_coding` 注入对称顶层 `env_FRIDAY_TASK_GIT_ACCESS_TOKEN`/`AUTH_TYPE`("token")/`SSL_VERIFY`("false")（token 非空时），修复 nested `git_credentials` dict 不被 runner 消费（dead payload）导致的私有仓 clone 失败。
- 无条件注入 `env_FRIDAY_TASK_BRANCH_STRATEGY`(=本仓 `branch_name`)/`env_FRIDAY_TASK_TARGET_BRANCH`(=`base_branch`)，修复容器侧落默认 `friday/task-{id}` 分支根因。
- token 认证时 `git@host:path` → `https://host/path.git` 改写 `DispatchTask.repo_url`（照搬 chat 基线正则）。
- token 为空降级不回退（不注入 access_token 键、不改写 repo_url）；nested `git_credentials` dict 零回归保留；dispatch 日志追加 `has_git_token` 布尔，token 绝不入日志。
- 新增 6 个 PF-06 守护测试，全部经 chat 权威基线键集合断言。

## Task Commits

Each task was committed atomically:

1. **Task 1: PF-06 dispatch metadata env 键断言（先红）** - `4d824b85` (test)
2. **Task 2: _run_repo_coding 注入对称 git token env + branch env + SSH→HTTPS 改写** - `43e92bae` (feat)

## Files Created/Modified
- `server/workflows/nodes/ai/coding.py` - `_run_repo_coding` 新增 `git_env`/`branch_env` dict + SSH→HTTPS 改写局部 `repo_url`，并入 `DispatchTask.metadata`（`git_credentials` 保留）；`DispatchTask(repo_url=<改写后>)`；dispatch 日志加 `has_git_token=bool(token)`。
- `server/tests/test_coding_node.py` - 新增 `TestRunRepoCodingPF06`（6 测）：调用真实 `_run_repo_coding`，仅 mock `aresolve_git_token` + dispatcher + 真实 DB session 写入；断言 git token env / branch env / SSH→HTTPS / 无 token 降级 / 无 token 泄漏（structlog capture）/ nested 零回归。

## Decisions Made
- `env_FRIDAY_TASK_GIT_SSL_VERIFY` 硬编码 `"false"` 对齐 chat 权威基线（Open Q1 RESOLVED），不取 per-repo `credential.ssl_verify`——既有 nested dict 仍取 per-repo 值用于零回归保留，但真正生效的顶层 env 键对齐基线。
- `BRANCH_STRATEGY`/`TARGET_BRANCH` 取本次调用的 `branch_name`/`base_branch` 参数（多仓 fan-out per-repo），区别于 chat 单仓 `execution_spec`（A3 假设）。
- 不改 task/runner 侧——容器 env 消费契约只读核对（runner `executor.go` `env_` TrimPrefix + task `config.py` `env_prefix="FRIDAY_TASK_"`），注入键名已对齐既有契约。

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- TDD RED 阶段初次运行时，`ssh_https`/`no_token_leak` 两测因测试函数名不含 plan `<automated>` 的 `-k` 关键字子串而被 deselect。重命名为 `test_ssh_https_rewrite_when_token_present` / `test_no_token_leak_in_dispatch_logs`，使 6 测全部被验证命令选中。非生产代码问题。

## Verification

- `cd server && uv run pytest tests/test_coding_node.py -k "git_env or branch_strategy or ssh_https or no_token_leak or nested or no_token"` → **6 passed**（RED→GREEN）。
- `cd server && uv run pytest tests/test_coding_node.py` → **12 passed, 1 xfailed**（无既有用例回归）。
- 兄弟 dispatch 测试 `tests/chat/test_coding_exclusion_env.py` + `tests/test_coding_anthropic_base_url_passthrough.py` → **16 passed**（零回归）。
- 人工核对（只读）：runner `executor.go` 顶层 `env_` TrimPrefix 契约 + task `config.py` `env_prefix="FRIDAY_TASK_"` 映射，确认注入键名落到 `git_access_token`/`branch_strategy`/`target_branch`（无需改 task/runner）。

## Next Phase Readiness
- PF-06 env 对齐完成——callback 驱动多 wave 编码（Phase 44+）的容器 dispatch env 与 chat 路径同一基线，私有仓 + 正确分支可用。
- 真实 runner + Docker 容器端到端 resume 验收沿用既有 deferred（本地无法闭环，见 STATE.md Deferred Items）。
- 本 plan 不涉 RESUME-01（Phase 43 后续 plan 处理）。

## Self-Check: PASSED

- FOUND: `server/workflows/nodes/ai/coding.py`
- FOUND: `server/tests/test_coding_node.py`
- FOUND: `.planning/phases/43-env-resume/43-01-SUMMARY.md`
- FOUND commit `4d824b85` (Task 1 test)
- FOUND commit `43e92bae` (Task 2 feat)

---
*Phase: 43-env-resume*
*Completed: 2026-06-16*
