---
phase: 140-threshold-policy
plan: 03
subsystem: codegraph-observability
tags: [structlog, sampling, redaction, ast-guard, graph-query]

requires:
  - phase: 140-threshold-policy
    provides: Plan 140-01/02 的冻结身份、内容寻址报告与门禁审计基础
provides:
  - GraphQueryService 唯一 caller 生命周期行为契约
  - resolver、Process、lane 与 impact 的低基数 sampling 汇总
  - 覆盖 code_graph 与 retrieval 的日志正文泄漏和 INFO-loop AST 守卫
affects: [140-04, graph-query, retrieval, observability]

tech-stack:
  added: []
  patterns: [唯一 caller 生命周期, debug sampling 汇总, best-effort 观测, AST 日志泄漏守卫]

key-files:
  created:
    - server/tests/services/code_graph/test_query_observability.py
    - server/tests/services/code_graph/test_graph_query_sampling.py
  modified:
    - server/services/code_graph/query_service.py
    - server/codegraph/resolver/symbol_resolver.py
    - server/services/code_graph/process_trace.py
    - server/services/code_graph/process_index.py
    - server/services/retrieval/rag_search.py
    - server/services/retrieval/hybrid_search.py
    - server/tests/services/code_graph/test_access.py
    - server/tests/services/retrieval/test_hybrid_structured_logging.py

key-decisions:
  - "GraphQueryService 是 graph query 唯一 caller 生命周期边界；resolver、Process、lane 与 impact 只发 debug/sampling 汇总。"
  - "所有 retrieval 日志禁止自然语言 query 正文；异常统一在埋点处调用 redact_secrets_in_text。"
  - "静态守卫显式纳入 rag_search.py 与 hybrid_search.py，并拒绝 query kwargs/slice、未脱敏 error 与循环 INFO。"

patterns-established:
  - "Caller/sampling 分层：入口记录 started/completed/failed，内部步骤每次调用至多一条低基数摘要。"
  - "Observability best-effort：日志故障不改变成功、partial/degradation 或原始异常语义。"
  - "Leakage guard：AST 扫描面有存在性正向断言，不能通过缩小文件集合获得绿灯。"

requirements-completed: [OBS-01, OBS-02]

duration: 15min
completed: 2026-08-25
---

# Phase 140 Plan 03: Graph Query 可观测性收口 Summary

**以唯一 caller 生命周期、低噪声内部 sampling、统一异常脱敏和跨 retrieval AST 守卫收口 graph query 可观测边界。**

## Performance

- **Duration:** 15 min
- **Started:** 2026-08-24T17:45:08Z
- **Completed:** 2026-08-24T18:00:15Z
- **Tasks:** 2
- **Files modified:** 10

## Accomplishments

- `GraphQueryService` 对非空查询只产生一组可归因的 caller started/completed/failed 生命周期；空查询零事件，日志故障不反噬业务。
- Resolver 按 language/call_shape/status 聚合，Process build/index/search、Symbol/Process lane 与 impact 使用低基数 debug/sampling 摘要。
- RAG/Hybrid retrieval 删除 query 截断正文，异常通过 `redact_secrets_in_text` 脱敏，wave INFO 下沉为 sampling/debug。
- AST 守卫覆盖 code_graph、既有 siblings 及两个 retrieval 文件，机械禁止正文、未脱敏异常和循环 INFO。

## Task Commits

每个 TDD 任务按 RED → GREEN 原子提交：

1. **Task 1 RED: 固定 GraphQueryService caller 生命周期契约** - `8bb4c053`（test）
2. **Task 1 GREEN: 收口唯一 caller 生命周期与 lane sampling** - `3f49be56`（feat）
3. **Task 2 RED: 固定内部 sampling 与日志静态红线** - `ac8372dd`（test）
4. **Task 2 GREEN: 统一内部 sampling 与 retrieval 脱敏** - `3baa41c6`（feat）
5. **Task 2 回归: 对齐既有 retrieval 结构化日志测试** - `a6731aa3`（test）

## Files Created/Modified

- `server/services/code_graph/query_service.py` - 唯一 caller 生命周期及 Symbol/Process lane sampling。
- `server/codegraph/resolver/symbol_resolver.py` - language/call_shape/status 分组 resolver batch 摘要。
- `server/services/code_graph/process_trace.py` - Process rebuild 单一 outcome sampling。
- `server/services/code_graph/process_index.py` - encode/upsert 与 search sampling 汇总。
- `server/services/code_graph/impact.py` - 复用既有单条 impact sampling 契约，无需源代码改动。
- `server/services/retrieval/rag_search.py` - 删除 query 日志并统一异常脱敏。
- `server/services/retrieval/hybrid_search.py` - wave/lifecycle 下沉 sampling/debug，移除 query 正文。
- `server/tests/services/code_graph/test_query_observability.py` - 生命周期、归因、脱敏与 best-effort 行为测试。
- `server/tests/services/code_graph/test_graph_query_sampling.py` - resolver、Process search 与 impact sampling 行为测试。
- `server/tests/services/code_graph/test_access.py` - retrieval 扫描面与日志泄漏/放大 AST 守卫。
- `server/tests/services/retrieval/test_hybrid_structured_logging.py` - 对齐 debug sampling 及无 query 契约。

## Decisions Made

- `component=codegraph` 保留给解析/抽取侧，查询服务及 retrieval 使用 `component=code_graph`。
- `rebuild_process_index` 保留 caller 生命周期、`initiated_by_user_id` system fallback 和 `bind_task_context`；encode/upsert 只增加内部 sampling。
- 不自造脱敏规则；异常文本统一通过项目现有 `redact_secrets_in_text`。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] 更新既有 Hybrid structured logging 契约**
- **Found during:** Task 2 完整回归
- **Issue:** 既有测试仅捕获 INFO 且明确要求 query 正文，与本计划的 debug/sampling 和无正文安全契约冲突。
- **Fix:** 使用测试记录器捕获 debug 事件，改为断言 sampling/component 与 query 字段缺失。
- **Files modified:** `server/tests/services/retrieval/test_hybrid_structured_logging.py`
- **Verification:** retrieval 专项 15 tests passed。
- **Committed in:** `a6731aa3`

---

**Total deviations:** 1 auto-fixed（1 bug）
**Impact on plan:** 修复直接由安全日志级别调整触发的回归，无范围扩张。

## Issues Encountered

- 初始测试尝试连接外部数据库；改用临时 SQLite 并显式禁用 Redis 后实现零外部依赖验证。
- `structlog.testing.capture_logs()` 默认不合并 contextvars；行为测试显式加入 `merge_contextvars` processor。
- retrieval 既有结构化日志测试只捕获 INFO；按计划下沉 debug 后改用可记录全部级别的测试 logger。

## TDD Gate Compliance

- Task 1：`8bb4c053`（RED）→ `3f49be56`（GREEN）。
- Task 2：`ac8372dd`（RED）→ `3baa41c6`（GREEN），随后 `a6731aa3` 修复既有回归契约。

## Known Stubs

无。本计划未新增占位实现、空数据源或 TODO/FIXME。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- OBS-01/02 已有行为与静态双重门禁，可供 Plan 140-04 做最终验证与收口。
- 无新增依赖、网络端点、认证路径、文件访问或 schema 变更。

## Self-Check: PASSED

- 2 个新增测试文件与 8 个修改文件均存在。
- 5 个 TDD/回归 commit 均存在。
- 计划专项 58 tests passed；受影响 retrieval 回归 15 tests passed；Ruff checks passed。
- 禁止的 quick results JSON 未 add、未 commit、未删除。

---
*Phase: 140-threshold-policy*
*Completed: 2026-08-25*
