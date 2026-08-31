---
phase: 144-capture
plan: "04"
subsystem: api
tags: [mcp, chat, session-capture, retrieval-trace, qdrant]
requires:
  - phase: 144-02
    provides: session_capture 来源闭集与共享检索 helper
  - phase: 144-03
    provides: 默认分支关联防错与 lookup binding_source 契约
provides:
  - MCP search_session_knowledge 仓库优先检索入口
  - Chat search_session_knowledge 薄封装
  - MCP/Chat 无正文汇总 RetrievalTrace
  - 53 工具服务端与 npm 跨面对齐契约
affects: [144-05, session-capture-replay, mcp-package]
tech-stack:
  added: []
  patterns: [共享检索 helper, 汇总 RetrievalTrace, 仓库必填项目可选 AND 收窄]
key-files:
  created: []
  modified:
    - server/mcp_tools/views.py
    - server/mcp_tools/serializers.py
    - server/mcp_tools/urls.py
    - server/agents/tools/knowledge_read_tools.py
    - server/agents/chat_runner.py
    - mcp/src/tools.ts
    - mcp/tests/server.test.ts
    - server/tests/mcp_tools/test_search_session_knowledge.py
    - server/tests/mcp_tools/test_schema_snapshot.py
    - server/tests/mcp_tools/test_mcp_package_alignment.py
key-decisions:
  - "MCP 在调用共享 helper 前执行仓库与可选项目权限收口，未授权统一返回空结果。"
  - "MCP 与 Chat 留痕仅保存标识、计数、分数和耗时，空命中仍写一条 CHUNK trace。"
patterns-established:
  - "会话知识两入口只委托 knowledge.session_capture_retrieval.search_session_knowledge。"
  - "新增 MCP 工具必须同步 serializer、snapshot、URL、npm schema 与 annotations。"
requirements-completed: [RECALL-01, OBS-03]
duration: 7min
completed: 2026-08-28
---

# Phase 144 Plan 04: MCP 与 Chat 会话知识检索 Summary

**MCP 与 Chat 共享仓库优先的 session_capture 检索入口，并以无正文汇总留痕冻结 53 工具跨面契约**

## Performance

- **Duration:** 7 分钟
- **Started:** 2026-08-28T12:08:32Z
- **Completed:** 2026-08-28T12:15:10Z
- **Tasks:** 2
- **Files modified:** 10

## Accomplishments

- 新增 MCP `search_session_knowledge`，校验必填仓库、可选项目 AND 收窄与 `top_k` 边界。
- 新增 Chat 同名工具，复用共享 helper、会话 owner fail-closed，并加入 `_INDEXED_TOOL_NAMES`。
- 两条链空命中也写一条 best-effort `RetrievalTrace.Kind.CHUNK`，payload 不含 query 或正文。
- 服务端 snapshot、URL、npm `FRIDAY_TOOLS` 与只读 annotations 对齐到恰好 53 个工具。

## Task Commits

1. **Task 1 RED：冻结跨面检索契约** - `f68d011b1`（test）
2. **Task 1 GREEN：提供 MCP 会话知识检索** - `86edc2ace`（feat）
3. **Task 2：接入 Chat 薄封装** - `b44aeee65`（feat）

子模块提交：

- `0d38ffd`：npm RED 契约
- `21e0ff5`：npm 搜索工具实现

## Files Created/Modified

- `server/mcp_tools/views.py` - MCP 权限收口、共享召回与汇总 trace。
- `server/mcp_tools/serializers.py` - 请求 serializer 与 schema snapshot。
- `server/mcp_tools/urls.py` - MCP 工具路由。
- `server/agents/tools/knowledge_read_tools.py` - Chat 工具、生命周期日志与 best-effort trace。
- `server/agents/chat_runner.py` - 索引工具白名单。
- `mcp/src/tools.ts` - 第 53 个只读工具及 annotations。
- `mcp/tests/server.test.ts` - 53 工具与只读 annotations 守卫。
- `server/tests/mcp_tools/test_search_session_knowledge.py` - MCP 行为和留痕契约。
- `server/tests/mcp_tools/test_schema_snapshot.py` - 完整 snapshot。
- `server/tests/mcp_tools/test_mcp_package_alignment.py` - serializer/snapshot/npm 三面对齐。

## Decisions Made

- `project_id` 不替代 `repository_id`，仅参与权限与检索的 AND 收窄。
- 未授权仓库不进入共享 helper，返回 HTTP 200 空结果，避免仓库枚举。
- trace 空项目与空最高分采用闭集标量 `""` 与 `0`，不记录 query、标题或正文。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] 修正 forwarding 测试缺少授权空间**
- **Found during:** Task 1（MCP 检索）
- **Issue:** RED 测试使用随机项目和孤儿仓库，权限收口会正确短路，无法验证 helper 参数透传。
- **Fix:** 改用真实项目与 `repository_in_user_space` fixture，使测试同时满足授权前提和 AND 透传目标。
- **Files modified:** `server/tests/mcp_tools/test_search_session_knowledge.py`
- **Verification:** Phase 144-04 服务端 25 项测试全绿。
- **Committed in:** `86edc2ace`

---

**Total deviations:** 1 auto-fixed（1 个 Rule 1）
**Impact on plan:** 仅修正测试前置条件，不放宽生产权限或改变检索契约。

## Issues Encountered

- Friday 对 `main` 分支召回到不相关项目，符合 Phase 144 已知默认分支历史缺陷；本次未采信该上下文，也未向该项目回写知识或 API 状态。
- pytest teardown 偶发报告测试库仍有一个连接；全部 25 项断言已通过，未影响结果。

## User Setup Required

无需外部配置。

## Verification

- `server`: 25 passed。
- `mcp`: 13 passed。
- `ruff`: 所有改动 Python 文件通过。
- IDE diagnostics：无新增错误。

## Known Stubs

无。默认空字符串仅用于可选请求参数与闭集 trace 标量，不是未接数据源。

## Next Phase Readiness

- 53 工具契约已冻结，可由 144-05 单独新增 `get_session_capture` 并推进到 54。
- `test_get_session_capture_schema_pending.py` 未纳入本计划验证，也未提前实现。

## Self-Check: PASSED

- Summary 文件存在。
- `f68d011b1`、`86edc2ace`、`b44aeee65` 三个主仓任务提交均可定位。
- npm 子模块 RED/GREEN 提交已由主仓指针提交引用。

---
*Phase: 144-capture*
*Completed: 2026-08-28*
