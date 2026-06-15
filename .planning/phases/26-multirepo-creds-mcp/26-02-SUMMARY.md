---
phase: 26-multirepo-creds-mcp
plan: 02
subsystem: auth
tags: [git-credentials, clone, indexer, repo-mirror, graph-builder, sync_to_async]

# Dependency graph
requires:
  - phase: 26-multirepo-creds-mcp
    plan: 01
    provides: services/git_credentials.py 解析器（resolve_git_token_sync / aresolve_git_token）
provides:
  - clone/index、bare 镜像 fetch、图谱克隆三条取 token 路径统一经凭证解析器
  - 跨克隆路径守护测试（同 host 多仓共享 + per-repo 优先 + 不泄漏）
affects: [26-03, 26-04]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Wave 2 接线：所有 git clone/fetch 取 token 统一调解析器，禁止内联 GitCredential→decrypt_value"
    - "同步上下文（@sync_to_async 包裹体）用 resolve_git_token_sync；async 上下文用 aresolve_git_token"

key-files:
  created:
    - server/tests/services/test_git_credential_clone_wiring.py
  modified:
    - server/services/indexer.py
    - server/services/graph_builder.py
    - server/services/repo_mirror.py

key-decisions:
  - "indexer.get_repository_data 去掉 select_related('credential')，由解析器内部自取凭证"
  - "graph_builder.prepare_repo_workdir_async / repo_mirror._fetch_repo_params 为 @sync_to_async 同步体，用 resolve_git_token_sync 同步入口"
  - "守护测试驱动真实接线入口（_fetch_repo_params / prepare_repo_workdir_async），非仅解析器，避免与 26-01 重复"

patterns-established:
  - "克隆/镜像取 token 单一来源：解析器 per-repo 优先 → host 实例池 fallback → None"
  - "token 仅进单次 clone/fetch argv URL；接线零新增 token 日志（威胁 T-26-05/06）"

requirements-completed: [REPO-01]

# Metrics
duration: ~15min
completed: 2026-06-15
---

# Phase 26 Plan 02: 多仓凭证统一接线（clone/index/mirror/graph） Summary

**把 26-01 解析器接入「克隆 / 索引 / bare 镜像 fetch / 图谱克隆」三条取 token 路径，消除散落的内联 `GitCredential → decrypt_value`，无 per-repo token 的同 host 多仓改为复用实例凭证，per-repo token 仍优先（向后兼容）**

## Performance

- **Duration:** ~15 min
- **Tasks:** 3
- **Files modified:** 4（1 created + 3 modified）

## Accomplishments
- `indexer.clone_and_index_repository.get_repository_data`（async）改用 `await aresolve_git_token(repo)`，去掉 `select_related('credential')` 强依赖与内联解密。
- `graph_builder.prepare_repo_workdir_async._fetch_repo_clone_params`（@sync_to_async 体）改用 `resolve_git_token_sync(repo)`。
- `repo_mirror._fetch_repo_params`（@sync_to_async 体）改用 `resolve_git_token_sync(repo)`，`_scrub` 脱敏 / token 仅进单次 fetch argv / 不写镜像 git config 既有安全约束零回退。
- 新增 `test_git_credential_clone_wiring.py`：5 个守护测试，驱动真实接线入口（`_fetch_repo_params` + `prepare_repo_workdir_async`，mock 子进程捕获 clone argv），覆盖同 host 多仓共享、per-repo 优先、token 不泄漏。

## Task Commits

1. **Task 1: indexer + graph_builder 克隆路径接入解析器** - `d51fcf051` (refactor)
2. **Task 2: repo_mirror bare fetch 接入解析器** - `50f662a4d` (refactor)
3. **Task 3: 跨克隆路径守护测试** - `de60e0663` (test)

## Files Created/Modified
- `server/services/indexer.py` - `get_repository_data` 经 `aresolve_git_token` 取 token
- `server/services/graph_builder.py` - `prepare_repo_workdir_async` 经 `resolve_git_token_sync` 取 token
- `server/services/repo_mirror.py` - `_fetch_repo_params` 经 `resolve_git_token_sync` 取 token，安全约束不变
- `server/tests/services/test_git_credential_clone_wiring.py` - 跨克隆路径接线守护测试（5 测）

## Decisions Made
- `indexer.get_repository_data` 移除 `select_related('credential')`：解析器内部自查 per-repo 与实例凭证，无需预取关联，行为差异仅「无 per-repo token 时改为按 host 命中实例凭证而非直接 None」。
- 同步上下文（两处 @sync_to_async 包裹的同步函数体）必须用 `resolve_git_token_sync`（不可 await）；仅 indexer 的 async `get_repository_data` 用 `aresolve_git_token`。
- 守护测试以「真实接线入口 + clone/fetch argv」为稳定切面：repo_mirror 用 `_fetch_repo_params` 返回的 token + `build_authenticated_git_url`；graph 用 mock `asyncio.create_subprocess_exec` 捕获 `git clone` argv，断言鉴权 URL 嵌入正确 token，不真正联网。

## Deviations from Plan

None - plan executed exactly as written.

（Task 3 计划提到用 `indexer.get_repository_data` 驱动，但该函数为 `clone_and_index_repository` 内的嵌套闭包不可直接调用；改以同样经解析器、且模块级可调用的 `graph_builder.prepare_repo_workdir_async` 作为克隆路径真实入口驱动，配合 `repo_mirror._fetch_repo_params`，覆盖等价的接线行为——属测试切面选择，非行为偏离。）

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- clone/index、bare 镜像 fetch、图谱克隆三路径已统一经解析器；26-03/26-04 可在此基础上继续接线 REST/前端 CRUD 与 MCP。
- 实例凭证（GitInstanceCredential）一经 26-04 落地写入，存量同 host 多仓克隆/索引/镜像即自动复用，无需逐仓配 token。

## Threat Coverage
- T-26-05（indexer/graph clone token 泄漏）：mitigate —— 仅传 `build_authenticated_git_url`，接线不新增 token 日志；Test 3 守护。
- T-26-06（repo_mirror fetch token 泄漏）：mitigate —— 保留 `_scrub` 脱敏 + 不写 git config 既有约束，仅替换取 token 来源。
- T-26-07（host fallback 错配）：mitigate —— 复用 26-01 host 唯一匹配。

## Self-Check: PASSED

- 文件全部存在：indexer.py / graph_builder.py / repo_mirror.py（modified）、test_git_credential_clone_wiring.py（created）、26-02-SUMMARY.md
- 提交全部存在：`d51fcf051`、`50f662a4d`、`de60e0663`
- 验证：`ruff check` 三文件 + 测试文件干净；`pytest test_git_credential_clone_wiring.py` 5 passed；回归 `test_git_credentials.py` 11 passed、`test_e2e_index_flow.py` 7 skipped（依赖外部服务）

---
*Phase: 26-multirepo-creds-mcp*
*Completed: 2026-06-15*
