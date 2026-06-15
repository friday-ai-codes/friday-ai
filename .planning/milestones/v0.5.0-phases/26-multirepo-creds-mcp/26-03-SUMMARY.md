---
phase: 26-multirepo-creds-mcp
plan: 03
subsystem: auth
tags: [git-credentials, gitlab, merge-request, dispatch, diff-archive, sync_to_async]

# Dependency graph
requires:
  - phase: 26-multirepo-creds-mcp
    plan: 01
    provides: services/git_credentials.py 解析器（resolve_git_token_sync / aresolve_git_token）
provides:
  - git 平台 MR/PR 客户端、编码容器 dispatch token 注入、diff archive 拉取五处取 token 路径统一经凭证解析器
  - git 平台守护测试（同 host 多仓共享实例凭证 + per-repo 优先 + 缺凭证报错不回退 + 不泄漏）
affects: [26-04]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Wave 2 接线：所有 git 平台 client 构造 / dispatch token 注入 / diff 拉取取 token 统一调解析器，禁止内联 GitCredential→decrypt_value"
    - "async 上下文统一用 aresolve_git_token；解析器返回 None 时各调用方保留既有缺凭证报错/降级（行为不回退）"

key-files:
  created:
    - server/tests/test_git_credential_platform_wiring.py
  modified:
    - server/mcp_tools/merge_request_service.py
    - server/workflows/services/mr_service.py
    - server/workflows/nodes/ai/coding.py
    - server/chat/coding_session_service.py
    - server/knowledge/diff_archive.py
    - server/tests/test_coding_session_service.py

key-decisions:
  - "五处取 token 路径全为 async 上下文，统一用 aresolve_git_token（无需 sync 入口）"
  - "coding.py dispatch 的 ssl_verify 仍优先取 per-repo credential（存在时），纯靠实例池时默认 'true'，仅 token 非空才注入 access_token"
  - "diff_archive 的「无 credential 行 → 早返回 None 警告」与「credential 空 token」两分支统一收敛为「解析器返回 None → 早返回」，语义更紧（消除空 token 仍构造 client 的边界）"

patterns-established:
  - "git 平台 / dispatch / diff 取 token 单一来源：解析器 per-repo 优先 → host 实例池 fallback → None"
  - "token 仅传 get_git_platform_client / 进 dispatch payload（既有明文通道）；接线零新增 token 日志（威胁 T-26-09/10）"

requirements-completed: [REPO-01]

# Metrics
duration: ~25min
completed: 2026-06-15
---

# Phase 26 Plan 03: 多仓凭证统一接线（git 平台 / dispatch / diff archive） Summary

**把 26-01 解析器接入「git 平台 MR/PR 客户端 + 编码容器 dispatch 的 git token 注入 + diff archive 拉取」五处取 token 路径，无 per-repo token 的同 host 多仓改为按 host 复用实例凭证，per-repo token 仍优先（向后兼容）；token 绝不进日志**

## Performance

- **Duration:** ~25 min
- **Tasks:** 3
- **Files modified:** 7（1 created + 6 modified，含 1 测试更新）

## Accomplishments
- **Task 1（git 平台 MR/PR 客户端）：** 三处 client 构造统一经 `aresolve_git_token(repository)` —— `mcp_tools/merge_request_service._get_client`（缺凭证仍 raise `MergeRequestToolError("仓库缺少 Git 平台访问凭据")`）、`workflows/services/mr_service.create_mr_for_task`（None → 保留 `MRCreateResult(success=False, error="No API token configured for repository")`）、`coding.py` MR 创建段（None → 保留 log warning + 空 mr_url 早返回）。
- **Task 2（dispatch token 注入 + diff archive）：** `coding.py` dispatch git_credentials 经解析器，仅 token 非空才注入 `access_token`，`ssl_verify` 优先 per-repo credential 否则默认 `"true"`；`coding_session_service` 两处（`build_dispatch_metadata` / `dispatch_coding_task`）经解析器；`diff_archive` 拉取经解析器，无凭证早返回不回退。
- **Task 3（守护测试）：** 新建 `test_git_credential_platform_wiring.py`，patch `merge_request_service.get_git_platform_client` 捕获传入 token，驱动真实接线入口 `_get_client`，四测覆盖同 host 共享 / per-repo 优先 / 缺凭证报错不回退 / token 不泄漏。
- 消除了所有散落的内联 `GitCredential → decrypt_value` 取 token 逻辑（连同 26-02 共完成 D-02 接线）。

## Task Commits

1. **Task 1: git 平台 MR/PR 客户端取 token 统一经解析器** - `a4ff3965a` (refactor)
2. **Task 2: 编码 dispatch 与 diff archive 取 token 统一经解析器** - `061c3a9f2` (refactor)
3. **Task 3: git 平台客户端取 token 接线守护测试** - `b592debac` (test)

## Files Created/Modified
- `server/mcp_tools/merge_request_service.py` - `_get_client` 经 `aresolve_git_token`；去掉内联 `GitCredential`/`decrypt_value` 导入
- `server/workflows/services/mr_service.py` - `create_mr_for_task` 经解析器；去掉 `decrypt_value` 导入
- `server/workflows/nodes/ai/coding.py` - dispatch git_credentials + MR 创建段经解析器；去掉 `decrypt_value` 导入
- `server/chat/coding_session_service.py` - `build_dispatch_metadata` / `dispatch_coding_task` 两处经解析器
- `server/knowledge/diff_archive.py` - diff 拉取经解析器
- `server/tests/test_git_credential_platform_wiring.py` - git 平台取 token 接线守护测试（4 测）
- `server/tests/test_coding_session_service.py` - `with_token` 用例改 mock 统一解析器（接线变更随动）

## Decisions Made
- 五处取 token 全在 async 上下文（含两处 `@sync_to_async` 外的 async 函数体），统一用 `aresolve_git_token`，无需 `resolve_git_token_sync`。
- `coding.py` dispatch 的 `ssl_verify`：保留「存在 per-repo credential 时取其 `ssl_verify`」语义，纯实例池场景取既有默认 `"true"`（小写布尔字符串），仅 token 非空才构造 `git_credentials`。
- `diff_archive` 收敛分支：原「无 credential 行 → return None」与「credential 空 token → 仍构造 client('')」两路统一为「解析器 None → return None + 既有警告」，去掉空 token 仍打平台 API 的无效边界（更安全，非行为回退）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] 更新随接线失效的既有用例 `test_build_dispatch_metadata_with_token`**
- **Found during:** Task 3 回归
- **Issue:** 该用例 mock 旧接线内部（`repositories.models.GitCredential` + `common.encryption.decrypt_value`）。接线改走解析器后，旧 mock 不再生效，token 未注入 → 断言失败。
- **Fix:** 改为 mock 统一解析器 `services.git_credentials.aresolve_git_token` 返回明文 token，保留原断言意图；同步移除随之未用的 `MagicMock` 导入。
- **Files modified:** `server/tests/test_coding_session_service.py`
- **Commit:** `b592debac`

_注：计划 verification 引用的回归文件路径为 `tests/mcp_tools/test_mr_tools.py`（实际存在）与 `tests/test_coding_session_service.py`（实际存在），均已跑通；过程中一次 shell cwd 漂移导致路径误判，已纠正。_

## Issues Encountered
None（功能层面）。

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- git 平台 / dispatch / diff archive 三大类取 token 路径已全部经解析器；连同 26-02 的 clone/index/mirror/graph，D-02「统一经解析器取 token」接线完成。
- 26-04 可专注实例凭证 REST + 前端 CRUD；一经写入 `GitInstanceCredential`，存量同 host 多仓的平台调用 / 编码派发 / diff 拉取即自动复用，无需逐仓配 token。

## Threat Coverage
- T-26-09（平台 client token 泄漏）：mitigate —— token 仅传 `get_git_platform_client`，接线零新增 token 日志；`test_token_not_in_logs` 守护。
- T-26-10（dispatch git_credentials 泄漏）：mitigate —— 仅 token 非空注入 `access_token`，既有 dispatch 明文通道不扩大，不 log。
- T-26-11（host fallback 错配）：mitigate —— 复用 26-01 host 唯一匹配。
- T-26-12（缺凭证行为）：accept —— 解析器 None 时各调用方保留既有明确报错/降级，不静默。

## Self-Check: PASSED

- 文件全部存在：merge_request_service.py / mr_service.py / coding.py / coding_session_service.py / diff_archive.py（modified）、test_git_credential_platform_wiring.py（created）、26-03-SUMMARY.md
- 提交全部存在：`a4ff3965a`、`061c3a9f2`、`b592debac`
- 验证：5 接线文件 + 2 测试文件 `ruff check` 干净；`pytest test_git_credential_platform_wiring.py` 4 passed；回归 `test_mr_tools.py` + `test_coding_session_service.py` 22 passed；`test_diff_archive.py` + `test_git_credentials.py` + `test_git_credential_clone_wiring.py` 34 passed

---
*Phase: 26-multirepo-creds-mcp*
*Completed: 2026-06-15*
