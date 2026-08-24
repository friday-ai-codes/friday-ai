---
phase: 140-threshold-policy
plan: 01
subsystem: codegraph-benchmark
tags: [benchmark, resolver, identity, evidence, holdout]

# Dependency graph
requires:
  - phase: 133-graph-benchmark
    provides: 冻结 gold、无阈值 scorer 与 benchmark command
  - phase: 137-unified-graph-query
    provides: graph query manifest 与稳定 hash
provides:
  - resolver language × framework × call_shape 三态 cell 指标
  - comparison identity 与 system identity 分离的 benchmark 证据链
  - canonical case-set/evaluator/report hash、raw latency trials 与 token availability
  - holdout final-acceptance 审计和真实环境 human_needed 前置证据
affects: [140-02-threshold-policy, BENCH-07, EDGE-06]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - 纯函数评分与 Django command 薄 I/O 分层
    - canonical JSON SHA-256 证据关联
    - 外部证据缺失时 fail-closed human_needed

key-files:
  created:
    - server/tests/codegraph/test_graph_bench_resolver_metrics.py
  modified:
    - server/codegraph/services/graph_bench_eval.py
    - server/codegraph/management/commands/evaluate_graph_bench.py
    - server/tests/codegraph/test_evaluate_graph_bench_command.py
    - server/tests/codegraph/test_graph_bench_integration.py
    - server/tests/fixtures/graph_bench/manifest.json

key-decisions:
  - "comparison identity 只保存两次 run 必须相同的被测条件，system identity 单列允许 baseline/candidate Friday revision 不同。"
  - "Python from-import gold 映射到 resolver 实际产出的 import_alias，并将 gold_version 递增到 2。"
  - "无稳定 token 归因时输出 unavailable/INSUFFICIENT_DATA，整数 0 不再构成成功证据。"

patterns-established:
  - "Resolver cell 直接消费 ResolveResult 三态，禁止从 nullable callee 字段反推。"
  - "holdout 默认关闭，仅 --final-acceptance 开启并记录 opened_at。"

requirements-completed: [BENCH-07, EDGE-06]

# Metrics
duration: 35min
completed: 2026-08-25
---

# Phase 140 Plan 01: Threshold Policy 证据边界 Summary

**建立可机械配对的 benchmark 双身份与 hash 证据链，并补齐 resolver edge-level 三态 cell 测量。**

## Performance

- **Duration:** 35 min
- **Started:** 2026-08-25T00:29:00+08:00
- **Completed:** 2026-08-25T01:04:03+08:00
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments

- 按 language × framework × call_shape 输出 resolved、ambiguous、unresolved、precision、recall 与分母校验，TS/JS/Python required、Go report-only。
- run manifest/report 同时记录 comparison/system identity、case-set/evaluator/query-manifest/report hash、raw latency trials 与 token 可用状态。
- holdout 默认拒读，final-acceptance 显式开启时留下审计元数据；缺失真实仓、Qdrant 或 v0.22 artifact 时仅产出 human_needed 前置证据。

## Task Commits

1. **Task 1 RED：resolver 三态指标失败测试** - `f95744ea`
2. **Task 1 GREEN：resolver 三态 cell 契约** - `564f838a`
3. **Task 2 RED：benchmark 证据链失败测试** - `f4bbf24a`
4. **Task 2 GREEN：同条件 run identity 与证据链** - `b7579911`
5. **Task 2 修正：artifact hash 关联** - `75315c25`

## Files Created/Modified

- `server/codegraph/services/graph_bench_eval.py` - comparison/system identity、canonical case-set hash、resolver cell 与 token/trial schema。
- `server/codegraph/management/commands/evaluate_graph_bench.py` - 系统参数、ResolveResult 重放、holdout 审计、artifact hash 和 human_needed preflight。
- `server/tests/codegraph/test_graph_bench_resolver_metrics.py` - resolver 三态、marker、分母和语言门回归。
- `server/tests/codegraph/test_evaluate_graph_bench_command.py` - 双身份、hash、token、holdout 与 INVALID 短路测试。
- `server/tests/codegraph/test_graph_bench_integration.py` - 真仓可用时执行，否则验证无数值 human_needed 证据。
- `server/tests/fixtures/graph_bench/manifest.json` - gold_version 更新为 2。
- `server/tests/fixtures/graph_bench/locked_test.json` - Python from-import call shape 对齐为 import_alias。
- `server/tests/fixtures/graph_bench/README.md` - 记录 taxonomy 映射与版本变更。

## Decisions Made

- comparison identity 不包含可预期变化的 Friday revision；release/ranking/response/index identity 归入 system identity。
- evaluator hash 仅覆盖 scorer/schema 源文件，不使用整个 runner revision。
- resolver callsite 必须按 caller UID、文件和行号唯一命中；多命中或零命中 fail-closed。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] 增加 report artifact hash**
- **Found during:** Task 2 threat register 自检
- **Issue:** 双身份和 manifest hash 已记录，但缺少最终 report payload 的防篡改关联。
- **Fix:** 对 canonical report payload 计算 SHA-256 并写入 run manifest；INVALID 路径显式为 null。
- **Files modified:** `server/codegraph/management/commands/evaluate_graph_bench.py`
- **Verification:** command 专项测试与 Ruff 通过。
- **Committed in:** `75315c25`

---

**Total deviations:** 1 auto-fixed（1 missing critical）
**Impact on plan:** 补齐 T-140-03 的证据关联，无功能扩张或写索引路径。

## Issues Encountered

- pytest 初始化默认环境会连接不可用的外部数据库；验证命令显式使用本地 SQLite，并关闭 Redis channel/cache 后稳定完成。
- 当前未提供真实 `GRAPH_BENCH_REPOSITORY_ID`、`GRAPH_BENCH_COMMIT_SHA`、`GRAPH_BENCH_QDRANT_URL` 与 `GRAPH_BENCH_V022_BASELINE_ARTIFACT`。集成测试返回并验证 `human_needed`，未生成 baseline 数字、阈值或 PASS。

## Verification

- Task 1 指定套件：65 passed。
- Task 2 指定套件：15 passed，1 integration marker deselected。
- 显式 integration preflight：1 passed，确认缺环境时为 human_needed 且无 metrics。
- Ruff：All checks passed。

## User Setup Required

真实 baseline/candidate 接受测试仍需提供已索引目标仓、对应 commit、Qdrant 和 v0.22 artifact。可复现命令已由 preflight 输出；本计划未伪造替代数据。

## Next Phase Readiness

- BENCH-07 与 EDGE-06 的证据 schema 已可供 140-02 threshold policy 直接消费。
- 真实 baseline 数值仍为 `human_needed`，在外部环境齐备前不得据此声明阈值通过。

## Self-Check: PASSED

- 计划要求的实现、测试与 fixture 文件存在。
- 五个任务/TDD 提交均存在。
- 未添加、提交或删除 `.planning/quick/260811-gaosan-route-5rounds/route-5rounds-results.json`。

---
*Phase: 140-threshold-policy*
*Completed: 2026-08-25*
