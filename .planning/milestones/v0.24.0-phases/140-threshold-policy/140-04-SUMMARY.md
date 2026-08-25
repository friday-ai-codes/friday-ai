---
phase: 140-threshold-policy
plan: 04
subsystem: milestone-closure
tags: [closure, regression, benchmark, human-needed, packaging]

requires:
  - phase: 140-threshold-policy
    provides: Plans 140-01/02/03 的可比身份、四态 comparator 与可观测契约
provides:
  - Phase 133–140 跨阶段 closure regression
  - server、task 与 npm MCP 全组件回归证据
  - 真实 benchmark 依赖缺失时的 HUMAN_NEEDED 边界
affects: [v0.24.0-audit, graph-query, task, mcp]

tech-stack:
  added: []
  patterns: [跨消费面内容寻址门禁, 外部证据显式递延, 全组件发布回归]

key-files:
  created:
    - server/tests/codegraph/test_graph_bench_closure.py
  modified:
    - task/core/executor.py

key-decisions:
  - "仓内 closure 与外部数值 claim 分离：前者自动闭合，后者缺真实依赖时只允许 HUMAN_NEEDED。"
  - "没有真实 v0.22 baseline 时不创建 threshold policy、candidate 或 compare artifact。"
  - "全量回归发现的 Task 非字符串 repository_id 健壮性问题直接修复并复验。"

requirements-completed: [BENCH-06, BENCH-07, EDGE-06, OBS-01, OBS-02]

duration: 27min
completed: 2026-08-25
---

# Phase 140 Plan 04: Threshold Policy 与整体收口 Summary

**建立跨 Phase 133–140 的单一 closure gate，完成 server/task/npm MCP 全组件回归，并把缺失真实 baseline 的数值验证诚实递延为 HUMAN_NEEDED。**

## Performance

- **Duration:** 27 min
- **Started:** 2026-08-24T18:06:42Z
- **Completed:** 2026-08-24T18:33:42Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- 新增跨阶段 closure 测试，锁住 canonical manifest raw-byte hash、contract/response/ranking versions、service/task/npm MCP 消费面、权限/exclusion 入口、mixed watermark、partial/degradation、impact 安全措辞与后台触发用户传播。
- 默认仓内证据明确断言真实目标仓、Qdrant、独立 gold、v0.22 baseline 与 threshold policy 缺失时状态为 `HUMAN_NEEDED`，且不产生 metrics、伪 policy 或 `PASS`。
- server 图查询组合回归 493 项通过；Task 全量 291 项通过（3 个既有可选场景 skip，不作为本计划验收依据）；npm MCP 29 项测试、typecheck、build、prepack、`npm pack --dry-run` 全部通过。
- 修复 Task 全量测试发现的非字符串 `repository_id` 健壮性问题，避免 UUID 正则收到测试替身或异常配置对象时抛 `TypeError`。

## Task Commits

1. **Task 1: 建立跨阶段图查询收口门禁** - `f33c34ed`（test）
2. **Task 2: 修复全量回归发现的 Task 类型边界** - `5253d644`（fix）

## Files Created/Modified

- `server/tests/codegraph/test_graph_bench_closure.py` - 跨消费面身份、生产连接点、后台用户归因、外部证据状态与无 skip 逃生口门禁。
- `task/core/executor.py` - 仅对字符串 `repository_id` 做 strip/UUID 校验，其他类型安全回退到环境提示。

## Verification Evidence

- Closure 组合：`61 passed`。
- Server 全量选择器：`493 passed, 3 deselected`。
- Task 全量：`291 passed, 3 skipped`；本计划新增/修改测试零 skip，验收结论不依赖 skip。
- npm MCP：`3 files / 29 tests passed`，`tsc --noEmit`、build、prepack、pack dry-run 通过。
- Ruff：closure 与 Task 修复文件 lint/format 通过。
- 真仓 integration 状态机：`1 passed`，走 `human_needed` 分支且未产生 metrics。

## External Verification Debt

以下真实依赖当前不可用，因此 BENCH-06/07 与 EDGE-06 的数值提升 claim 递延：

- 已索引真实目标仓 UUID、branch 与冻结 commit SHA；
- 可用 Qdrant/embedding 环境；
- 非占位、非 seed 的独立 gold（含 final-only holdout）；
- 未修改 v0.22 的 baseline report、run manifest 与内容 hash；
- 基于真实 baseline 独立审查后生成的 threshold policy；
- 同 comparison identity 的 v0.24 candidate 与 compare artifacts。

复现入口：

```bash
GRAPH_BENCH_REPOSITORY_ID=<uuid> \
GRAPH_BENCH_COMMIT_SHA=<sha> \
GRAPH_BENCH_QDRANT_URL=<url> \
GRAPH_BENCH_V022_BASELINE_ARTIFACT=<path> \
uv run pytest tests/codegraph/test_graph_bench_integration.py -m integration -q
```

真实依赖齐全后先运行 `locked_test` compare；仅在其通过后用显式 `--final-acceptance` 打开 holdout。当前未生成 threshold 数字、正式 policy、candidate、compare report 或 PASS claim。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Task 配置替身的 repository_id 触发 UUID 校验 TypeError**
- **Found during:** Task 全量回归。
- **Issue:** `_detect_changes_guidance()` 对任意 truthy 配置值直接 `.strip()` 并传给 `re.fullmatch`，非字符串对象会中断 SDK options 构造。
- **Fix:** 先以 `isinstance(configured_id, str)` 收窄，再执行 strip/UUID 校验；其他类型走安全 fallback。
- **Verification:** Task 全量 `291 passed`；专项 `1 passed`；Ruff 通过。
- **Committed in:** `5253d644`

---

**Total deviations:** 1 auto-fixed（1 bug）
**Impact on plan:** 修复由强制全量回归直接发现，未扩大产品范围。

## Known Stubs

无新增代码 stub。仓内 gold 仍是明确标注的 seed/占位 fixture，只用于 harness 契约测试，不作为真实性能证据。

## User Setup Required

真实数值验收需要 External Verification Debt 所列环境与 artifacts；仓内功能与回归无需额外配置。

## Self-Check: PASSED WITH HUMAN_NEEDED DEBT

- 2 个计划提交存在，所有仓内自动化门禁通过。
- 缺失外部证据被显式分类为 `HUMAN_NEEDED`，未用 mock/seed/skip/tokens=0 冒充通过。
- 指定 quick results JSON 保持未跟踪、未修改、未提交。

---
*Phase: 140-threshold-policy*
*Completed: 2026-08-25*
