---
phase: 133-commit-v0-22-baseline
plan: 03
subsystem: testing
tags: [benchmark, eval, metrics, bucketing, macro-aggregation, pure-function, pytest]

# Dependency graph
requires:
  - phase: 133-commit-v0-22-baseline
    provides: "Plan 01 graph_bench_eval.py：GoldCase/GoldDataset/RunIdentity/build_run_identity + 四闭集常量"
provides:
  - "graph_bench_eval.py 空结果标记常量：NO_GOLD/NOT_APPLICABLE/SEED_MISSING/NODE_NOT_IN_GRAPH/INSUFFICIENT_DATA/BUCKET_OK + MIN_BUCKET_SAMPLES=3"
  - "六个逐 case scorer（BENCH-04）：score_symbol_recall/score_process_recall/rank_process_candidates/score_edge_pr/score_impact_precision/score_trace"
  - "CaseOutcome + evaluate_case 折算（含 cold_ms/warm_ms/tokens，error 单 case 容错）"
  - "分桶/聚合/报告（BENCH-05+BENCH-03）：bucket_status/bucket_metrics/aggregate_report/build_report（macro + INSUFFICIENT_DATA 隔离 + 受保护桶单列 + 零回归门字段）"
affects: [133-04, 140]

# Tech tracking
tech-stack:
  added: []
  patterns: [纯函数零 I/O 指标模块（复刻 repo_route_recall_eval 的 macro 聚合，剔除 compare/tolerance 语义；空 gold 记 NO_GOLD 而非满分）]

key-files:
  created:
    - server/tests/codegraph/test_graph_bench_eval.py
  modified:
    - server/codegraph/services/graph_bench_eval.py

key-decisions:
  - "空结果标记显式单列绝不进分母/平均：空 gold→NO_GOLD、无预测→N/A、seed 缺失→SEED_MISSING、node_not_in_graph 单列（T-133-06 缓解）"
  - "聚合用 macro（按 case 平均）且 overall 仅聚合 status==OK 且非受保护桶；INSUFFICIENT_DATA 稀疏桶与受保护桶分别单列（T-133-07 缓解）"
  - "报告与各函数零回归门/目标值/容差/比对字段，阈值决策权移交 Phase 140（T-133-08 缓解）"
  - "trace 路径一致性判定：gold 可附 expected_path 精确比对，缺省退化为 source/target 端点比对，无路径细节时 found 即视为一致"

patterns-established:
  - "Pattern 1: 空结果规则顺序敏感——impact 按 seed_in_graph→无预测→空 gold 优先级短路（SEED_MISSING > N/A > NO_GOLD）"
  - "Pattern 2: macro 聚合跳过标记——_macro 仅对 float 求平均，分母=该指标数值 case 数，无数值记 NO_GOLD"

requirements-completed: [BENCH-03, BENCH-04, BENCH-05]

# Metrics
duration: 13min
completed: 2026-08-24
status: complete
---

# Phase 133 Plan 03: 逐 case 指标 + 分桶 + macro 聚合 + 无阈值报告 Summary

**在 Plan 01 纯函数地基上补齐 BENCH-04 指标集（锁定分母 + 空结果规则）与 BENCH-05 分桶/INSUFFICIENT_DATA/macro 聚合，产出 BENCH-03 要求的无阈值原始报告——全部零 I/O 纯函数，可在默认 --disable-socket 套件单测，模块零回归门字段**

## Performance

- **Duration:** 13 min
- **Started:** 2026-08-24T09:50:48Z
- **Completed:** 2026-08-24T10:04:38Z
- **Tasks:** 3
- **Files modified:** 2

## Accomplishments

- **空结果标记常量齐备**：`NO_GOLD`/`NOT_APPLICABLE`/`SEED_MISSING`/`NODE_NOT_IN_GRAPH`/`INSUFFICIENT_DATA`/`BUCKET_OK` + `MIN_BUCKET_SAMPLES=3`，统一原则「空 gold ≠ 满分、无预测 ≠ 满分」显式落为模块常量
- **六个逐 case scorer（BENCH-04）**：`score_symbol_recall`（分母=gold symbol 数，uid 集合命中）、`score_process_recall`（process_key 精确匹配，禁名称模糊命中）、`rank_process_candidates`（按与 retrieved 交集数降序 + process_key 升序确定性排序）、`score_edge_pr`（(caller,callee) 二元组，precision 分母=预测边数/recall 分母=gold 边数）、`score_impact_precision`（分母=预测受影响数，seed_in_graph=False→SEED_MISSING）、`score_trace`（found/no_path/node_not_in_graph 三态，node_not_in_graph 单列不进成功率分母）
- **CaseOutcome + evaluate_case**：arrival set 折算成逐 case 结果，symbol 取 top5、process 取确定性排序 top3；含 `cold_ms`/`warm_ms`/`tokens`（仅记录不聚合）；`error` 非空时指标置空字符串但不中断其它 case（单 case 容错）
- **分桶/聚合/报告（BENCH-05+BENCH-03）**：`bucket_status`（n<3→INSUFFICIENT_DATA）、`bucket_metrics`（按 language×framework×entry_type 分组，macro 跳过标记）、`aggregate_report`（overall 仅聚合 OK 非保护桶，稀疏桶与受保护桶分别单列）、`build_report`（echo identity 五元组 + watermark + 空结果图例 legend，零回归门字段）
- **40 条单测全绿**；模块零 I/O（grep 无 qdrant/.objects./import django）、零回归门字段（grep tolerance/threshold/compare_to_baseline/target_value==0）；ruff + mypy 全绿；Plan 01 测试（watermark 10 + gold_schema 18）不回归（合计 68 passed）

## Task Commits

Each task was committed atomically (TDD: RED test → GREEN feat):

1. **Task 1 RED: BENCH-04 指标 scorer 失败测试** - `d31a7b52` (test)
2. **Task 1 GREEN: 六个指标 scorer + 空结果规则** - `539bd3df` (feat)
3. **Task 2 RED: evaluate_case/CaseOutcome 失败测试** - `f3d791b8` (test)
4. **Task 2 GREEN: CaseOutcome + evaluate_case 折算** - `c5e94c7c` (feat)
5. **Task 3 RED: 分桶/聚合/报告失败测试** - `0e50ac87` (test)
6. **Task 3 GREEN: 分桶/INSUFFICIENT_DATA/macro/无阈值报告** - `1ef9dc7a` (feat)

## Files Created/Modified

- `server/codegraph/services/graph_bench_eval.py` - 追加指标/分桶/报告段：空结果标记常量 + 六 scorer + CaseOutcome/evaluate_case + bucket/aggregate/build_report（在 Plan 01 identity/水位/gold schema 之上，仍零 I/O）
- `server/tests/codegraph/test_graph_bench_eval.py` - BENCH-03/04/05 单测（40 用例，默认套件可跑）

## Decisions Made

- **空结果规则顺序敏感**：`score_impact_precision` 按 `seed_in_graph=False → SEED_MISSING` → `无预测 → N/A` → `空 gold → NO_GOLD` 的优先级短路，确保「seed 缺失」与「无影响」「无预测」三类永不混淆（PITFALLS B0）
- **overall 排除受保护桶**：受保护桶（含 protected=true case）一律单列展示且不参与 overall 平均，使其退化无法被大桶提升抵消（PITFALLS Pitfall 3）；`INSUFFICIENT_DATA` 稀疏桶同样隔离
- **trace 路径一致性三档判定**：gold 附 `expected_path` 时精确比对；缺省退化为 result.path 首尾须等于 gold 的 source/target；两者皆无路径细节时 `found` 即视为一致（无从判错）——在 gold schema（仅 source/target）下保持确定性且可测
- **process 候选映射为测量映射而非生产检索器**：`rank_process_candidates` 仅把检索结果映射到 Process 候选以记分，生产 Process 检索属 Phase 136

## Deviations from Plan

None - plan executed exactly as written.

三个 task 均按计划 RED→GREEN 节奏提交；全部验收命令（pytest / grep 计数 / ruff / mypy / Plan 01 回归）首次即通过，无 auto-fix。

## TDD Gate Compliance

三个 task 均为 `tdd="true"`，RED/GREEN 门齐全且顺序正确：

- Task 1: RED `d31a7b52` (test) → GREEN `539bd3df` (feat)
- Task 2: RED `f3d791b8` (test) → GREEN `c5e94c7c` (feat)
- Task 3: RED `0e50ac87` (test) → GREEN `1ef9dc7a` (feat)

每个 RED 提交在实现前均因 import 失败而确为失败（collection error），非「意外通过」。

## Issues Encountered

- 无。本机 `uv run` 直接可用（沿袭 Plan 02 的环境执行方式），三个 task 的 pytest/ruff/mypy 均一次通过。

## User Setup Required

None - no external service configuration required.

## Threat Flags

无新增威胁面。本 plan 只向纯函数模块追加算术逻辑与单测，不引入网络端点、auth 路径、文件访问或 schema 信任边界变更。threat_model 中 T-133-06/07/08 已通过空结果标记显式单列、macro+INSUFFICIENT_DATA 隔离+受保护桶单列、零回归门字段落地为代码约束；T-133-SC（supply-chain）零新增依赖不触发。

## Next Phase Readiness

- Plan 04（薄 command）可直接 import 本模块的 `evaluate_case`/`build_report`/`build_run_identity`/`validate_watermark`/`validate_gold_dataset`，注入真实 arrival set（hybrid_search/analyze_impact/trace_path 的输出）端到端跑 baseline 并序列化报告
- 报告字段（identity/watermark/split/per_case/per_bucket/overall/protected_buckets/insufficient_buckets/legend）已固定，供 Plan 04 序列化与 Phase 140 同条件复用；**不含**任何阈值字段，Phase 140 在此原始分布上独立评审回归门
- 无 blocker；真实冻结仓选定与完整独立标注为评测者后续动作（见 Plan 02 README runbook）

## Self-Check: PASSED

- `server/codegraph/services/graph_bench_eval.py` — FOUND（含 aggregate_report/build_report）
- `server/tests/codegraph/test_graph_bench_eval.py` — FOUND（40 用例）
- commit `d31a7b52` / `539bd3df` / `f3d791b8` / `c5e94c7c` / `0e50ac87` / `1ef9dc7a` — 均 FOUND in git log

---
*Phase: 133-commit-v0-22-baseline*
*Completed: 2026-08-24*
