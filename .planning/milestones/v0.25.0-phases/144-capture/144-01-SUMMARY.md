---
phase: 144-capture
plan: "01"
subsystem: testing
tags: [pytest, vitest, session-capture, retrieval-trace, wave-0]
requires:
  - phase: 143-eval
    provides: medium/high SessionCapture DOCUMENT 入图与可恢复状态机
provides:
  - 仓库优先会话知识检索与 Capture 回放 RED 契约
  - Chat/MCP 双链 RetrievalTrace 标量留痕 RED 契约
  - 默认分支第三源与 source_kind 闭集过滤 RED 契约
affects: [144-02, 144-03, 144-04, 144-05]
tech-stack:
  added: []
  patterns: [tracer-first Wave 0, test-only RED contracts, scalar-only retrieval traces]
key-files:
  created:
    - server/tests/mcp_tools/test_search_session_knowledge.py
    - server/tests/mcp_tools/test_get_session_capture.py
    - server/tests/agents/tools/test_search_session_knowledge.py
    - server/tests/mcp_tools/test_get_session_capture_schema_pending.py
  modified:
    - server/tests/knowledge/test_vector_recall.py
    - server/tests/services/test_project_context_packer.py
    - server/tests/mcp_tools/test_lookup_project_by_branch.py
    - server/tests/mcp_tools/test_report_session_knowledge.py
    - server/tests/mcp_tools/test_schema_snapshot.py
key-decisions:
  - "Wave 0 只落测试，不修改生产代码、npm 工具定义或依赖。"
  - "repository_id 为必填主作用域，project_id 只能形成 AND 收窄。"
  - "回放正文只允许来自 SessionCapture，未授权与不存在统一返回中性 404。"
patterns-established:
  - "缺失路由/helper 以运行时 RED 表达，不用 skip 掩盖。"
  - "召回留痕 payload 仅允许标量、计数、分数与作用域标识。"
requirements-completed: [RECALL-01, RECALL-02, RECALL-03, RECALL-04, OBS-03]
duration: 4min
completed: 2026-08-28
---

# Phase 144 Plan 01: Wave 0 RED 契约 Summary

**以 98 项可收集 pytest 契约冻结仓库召回、Capture 回放、默认分支防错与双链标量留痕，生产缺口保持可观测 RED。**

## Performance

- **Duration:** 4 min
- **Started:** 2026-08-28T11:54:49Z
- **Completed:** 2026-08-28T11:58:56Z
- **Tasks:** 3
- **Files modified:** 9

## Accomplishments

- 新增 MCP 会话检索与 Capture 只读回放测试，锁定仓库必填、AND 项目、防枚举和 Ledger 隔离。
- 新增 Chat 共享 helper、Qdrant `source_kind MatchAny`、packer inclusion 与 trace best-effort 契约。
- 锁定默认分支第三源不自动命中，并保持 npm `FRIDAY_TOOLS` 52 项、12 个 vitest 全绿。

## Task Commits

1. **Task 1: MCP 会话检索与 Capture 回放 RED 契约** - `3bbfab085` (test)
2. **Task 2: Chat、向量 filter 与 packer inclusion RED 契约** - `a17c7dcb9` (test)
3. **Task 3: 默认分支第三源与分波 schema RED 契约** - `950e6b19a` (test)

## Files Created/Modified

- `server/tests/mcp_tools/test_search_session_knowledge.py` - MCP 检索、权限与空命中 trace 契约。
- `server/tests/mcp_tools/test_get_session_capture.py` - Capture allowlist、404 防枚举与纯只读契约。
- `server/tests/agents/tools/test_search_session_knowledge.py` - Chat 共享 helper、钳位与留痕降级契约。
- `server/tests/knowledge/test_vector_recall.py` - `source_kinds` 闭集 MatchAny 与空列表短路契约。
- `server/tests/services/test_project_context_packer.py` - 项目收窄且同时纳入 Capture/项目文档的 inclusion 契约。
- `server/tests/mcp_tools/test_lookup_project_by_branch.py` - 默认分支第三源跳过与显式证据零回归契约。
- `server/tests/mcp_tools/test_report_session_knowledge.py` - 默认分支仍保留真实仓库 FK 的写路径契约。
- `server/tests/mcp_tools/test_schema_snapshot.py` - lookup `binding_source` 响应键契约。
- `server/tests/mcp_tools/test_get_session_capture_schema_pending.py` - 独立 get-only 待实现 schema 快照。

## Verification

- `pytest --collect-only`：98 tests collected。
- `npm test -- tests/server.test.ts`：12 passed，工具计数仍为 52。
- 代表性 RED：缺少 MCP 路由返回 404、vector filter 不接受 `source_kinds`、snapshot 缺少 `get_session_capture`。
- `ruff check`：所有 9 个计划测试文件通过。
- Git 范围检查：仅修改计划列出的 9 个测试文件，无生产代码或 npm 文件变更。

## Decisions Made

- 遵循 Context 决议：仓库是主作用域，项目只能收窄；默认分支不能仅凭 RepoAssociation 自动匹配。
- 回放响应固定省略 `client`、内部错误、评估精华与幂等哈希，且不得读取 Interaction Ledger 补齐。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] 兼容旧 STATE.md 位置格式**
- **Found during:** 计划收口
- **Issue:** `state.advance-plan` 无法解析 `Plan: Not started`，未更新 Phase 144 执行位置。
- **Fix:** 保留其余 SDK 更新结果，按当前 1/5 计划状态手动同步 STATE 的 focus、position 与 session。
- **Files modified:** `.planning/STATE.md`
- **Verification:** ROADMAP 显示 `1/5 plans executed`，STATE 显示 `Plan: 1 of 5 complete`。
- **Committed in:** 计划 metadata 提交

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** 仅修复 GSD 元数据兼容性，不影响 test-only 产品范围。

## Issues Encountered

None. 代表性 pytest 失败是本 Wave 有意保留的 RED，不是执行故障。

## Known Stubs

None. 本计划只有测试契约；对应生产实现按计划由 144-02 至 144-05 转绿。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Wave 0 契约已可供 144-02 至 144-05 按依赖顺序实现。
- 当前 RED 均指向预期缺口：新检索/回放入口、`source_kinds` 过滤和 schema 注册。

## Self-Check: PASSED

- 9 个计划测试文件均存在。
- 3 个原子任务提交均可在 git 历史中定位。

---
*Phase: 144-capture*
*Completed: 2026-08-28*
