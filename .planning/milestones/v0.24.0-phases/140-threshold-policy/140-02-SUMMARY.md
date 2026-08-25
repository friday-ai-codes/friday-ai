---
phase: 140-threshold-policy
plan: 02
subsystem: codegraph-benchmark
tags: [benchmark, threshold-policy, comparator, audit, django-command]

requires:
  - phase: 140-threshold-policy
    provides: Plan 140-01 的冻结 run/comparison/system identity 与内容寻址报告
provides:
  - 严格验证、只读且内容寻址的 threshold policy loader
  - identity/hash/case/bucket/cell 严格配对的四态 comparator
  - 只读 compare management command 与可回放审计报告
affects: [140-03, 140-04, benchmark-gating, release-evidence]

tech-stack:
  added: []
  patterns: [纯函数 comparator, raw-byte SHA-256, 四态 fail-closed gate, best-effort 结构化日志]

key-files:
  created:
    - server/codegraph/services/graph_bench_compare.py
    - server/codegraph/management/commands/compare_graph_bench.py
    - server/tests/codegraph/test_graph_bench_policy.py
    - server/tests/codegraph/test_graph_bench_compare.py
    - server/tests/codegraph/test_compare_graph_bench_command.py
  modified: []

key-decisions:
  - "真实 v0.22 baseline 仍不存在，因此不创建正式 graph_query_threshold_policy.v1.json，数值验证保持 human_needed。"
  - "比较命令只接受 baseline、candidate、policy 三份输入；baseline manifest hash 使用 policy 的冻结 pin，并保留纯 comparator 入口供持有 manifest bytes 的调用方复核。"
  - "INVALID 优先于任何局部 gate 结果；仅 optional sparse 可产生 INSUFFICIENT_DATA。"

patterns-established:
  - "Policy fail-closed：所有方向、容差、required/protected、identity 与 hash 均显式声明且严格验证。"
  - "Command thin I/O：读取原始 bytes、计算 hash、调用纯 comparator、写新报告，绝不写回输入。"
  - "Observability best-effort：caller 生命周期日志脱敏且日志故障不改变业务 verdict。"

requirements-completed: [BENCH-06, BENCH-07, EDGE-06]

duration: 36min
completed: 2026-08-25
---

# Phase 140 Plan 02: Threshold Policy 与四态 Comparator Summary

**以严格内容寻址和配对校验实现只读 threshold policy、四态 benchmark comparator 及可回放审计命令，同时在缺少真实 baseline 时拒绝生成伪正式 policy。**

## Performance

- **Duration:** 36 min
- **Started:** 2026-08-24T16:58:00Z
- **Completed:** 2026-08-24T17:34:14Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- Policy loader 对 schema、闭集字段、placeholder/hash、identity、gate 完整性及重复项实行 fail-closed 验证。
- Comparator 严格配对 case、bucket 与 resolver cell，并按 `INVALID > FAIL > INSUFFICIENT_DATA > PASS` 判定方向感知 gate。
- Compare command 保持输入 bytes 不变，输出三 hash、两类 identity、复现命令与逐层 diff，非 PASS 均非零退出。
- 生命周期日志满足 `caller`、`codegraph`、`system`、`duration_ms` 与异常脱敏要求，且观测失败不反噬业务。

## Task Commits

每个 TDD 任务按 RED → GREEN 原子提交：

1. **Task 1 RED: 固定 policy 与 comparator 契约** - `dbd2da5e`（test）
2. **Task 1 GREEN: 实现 policy loader 与四态 comparator** - `b5e1be0c`（feat）
3. **Task 2 RED: 固定 compare command I/O 与观测契约** - `5602d97d`（test）
4. **Task 2 GREEN: 实现只读 compare 审计命令** - `9c316487`（feat）

## Files Created/Modified

- `server/codegraph/services/graph_bench_compare.py` - Policy schema/loader、内容哈希、严格配对及四态纯 comparator。
- `server/codegraph/management/commands/compare_graph_bench.py` - 三输入只读 I/O、审计报告与 caller 生命周期日志。
- `server/tests/codegraph/test_graph_bench_policy.py` - Policy 缺键、闭集、hash、marker、重复 gate 等契约测试。
- `server/tests/codegraph/test_graph_bench_compare.py` - Identity/hash/pairing、方向边界、sparse 与 verdict 优先级测试。
- `server/tests/codegraph/test_compare_graph_bench_command.py` - 命令成功/失败退出、输入不可变、报告与日志集成测试。

## Decisions Made

- 不存在真实冻结 baseline 时，正式 policy 路径保持不存在；测试仅使用临时合成 artifact，不将其升级为基线证据。
- Required/protected gate 的 marker 或样本不足直接 `FAIL`；仅 optional sparse 返回 `INSUFFICIENT_DATA`。
- `PASS` 除全部 required gate 通过外，还要求 policy 声明的 primary quality metric 至少一项严格改善。

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- 初始测试使用错误的数据库环境变量并触发 Redis 默认连接等待；改用 `DATABASE_URL` 指向临时 SQLite，并显式禁用 Redis channel/cache 后恢复零外部依赖测试。
- RED 阶段如期因 command/module 尚不存在而失败；GREEN 阶段修正一个缺键错误类型与一组 `lower_is_better` 边界测试数据后通过。

## TDD Gate Compliance

- Task 1：`dbd2da5e`（RED）→ `b5e1be0c`（GREEN）。
- Task 2：`5602d97d`（RED）→ `9c316487`（GREEN）。

## Known Stubs

无。正式 policy 缺失是有意的 fail-closed 状态，并非 stub；真实 baseline 数值与外部采样验证继续标记为 `human_needed`。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Policy/comparator/command 契约已可供 Plan 140-03/04 的门禁与收口验证复用。
- 真实 v0.22 baseline、paired raw trials 延迟容差与 token 稳定归因仍需外部证据，必须保持 `human_needed`，不得由 candidate/holdout 或合成测试推导。

## Self-Check: PASSED

- 5 个创建文件均存在。
- 4 个 TDD task commit 均存在。
- 正式 `graph_query_threshold_policy.v1.json` 不存在，未提交占位或伪造数值。
- 禁止的 quick results JSON 未 add、未 commit、未删除。

---
*Phase: 140-threshold-policy*
*Completed: 2026-08-25*
