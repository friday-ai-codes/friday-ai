---
phase: 143-eval
plan: "03"
subsystem: database
tags: [django, session-capture, cas, state-machine, migration]

requires:
  - phase: 143-01
    provides: Capture 评估字段与 CAS 行为 RED 契约
provides:
  - 向后兼容的 Capture 评估与摄取状态字段迁移
  - high/medium/low 价值档位闭集
  - CaptureService 评估与摄取 CAS 唯一写入 API
affects: [143-04, 143-05, durable evaluation, knowledge ingestion]

tech-stack:
  added: []
  patterns:
    - Django filter(status__in).update CAS
    - 评估与摄取 attempt/retry 元数据隔离

key-files:
  created:
    - server/initiatives/migrations/0016_session_capture_evaluation.py
  modified:
    - server/initiatives/models/session_capture.py
    - server/initiatives/models/__init__.py
    - server/initiatives/services/capture_service.py

key-decisions:
  - "保留 legacy evaluated 状态，但新 writer 不写入、claim 或 resume 该状态。"
  - "处理中状态允许 durable 重放 resume，只有 pending/failed 到 processing 的 CAS 递增对应 attempt。"
  - "评估成功统一清理错误与 retry；摄取失败不修改评估 attempt 或回退评估状态。"

patterns-established:
  - "所有 SessionCapture 状态写入继续只经 CaptureService。"
  - "非法档位或空精华返回 no-op，不得默认写成 low。"

requirements-completed: [EVAL-01, EVAL-04, EVAL-05]

duration: 7min
completed: 2026-08-28
---

# Phase 143 Plan 03: Capture 可恢复评估状态机 Summary

**SessionCapture 现具备 additive 评估/摄取字段、恢复索引与独立 retry 元数据，CaptureService 通过条件更新提供幂等 CAS 状态流。**

## Performance

- **Duration:** 7 min
- **Started:** 2026-08-28T10:32:28Z
- **Completed:** 2026-08-28T10:39:31Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- 新增严格 `high`/`medium`/`low` 档位、处理中/失败/终态以及 default-safe 评估字段。
- 生成仅含 `AddField`、`AlterField`、`AddIndex` 的 `0016` migration，存量 `pending_eval` 问答不改写。
- 实现评估和摄取 claim/resume/result/failure CAS，attempt 与 retry 元数据不跨阶段覆盖。

## Task Commits

1. **Task 1: 添加向后兼容的 Capture 评估字段与 migration** - `d3339670` (feat)
2. **Task 2: 实现 CaptureService CAS 状态机** - `040f66da` (feat)

**Plan metadata:** pending docs commit after this SUMMARY

_TDD RED 契约由 Wave 0 提交 `935a78de` 提供，本计划两个 GREEN 提交使字段与 CAS 测试通过。_

## Files Created/Modified

- `server/initiatives/models/session_capture.py` - 扩展状态、价值档位与恢复字段。
- `server/initiatives/models/__init__.py` - 导出 `SessionCaptureValueTier`。
- `server/initiatives/migrations/0016_session_capture_evaluation.py` - additive schema migration 与恢复索引。
- `server/initiatives/services/capture_service.py` - Capture 状态机唯一 writer CAS API。

## Decisions Made

- legacy `evaluated` 只保留兼容，不作为任何新转换目标或可 claim 状态。
- 评估结果必须同时通过闭集档位和非空精华校验，非法输入保持当前状态。
- claim 仅在 pending/failed 转 processing 时增加 attempt；processing 重放只 resume。

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- 完整 `test_capture_inv6_guard.py` 中 2 个跨计划守卫仍 RED：它们要求 Plan 04/05 将创建的 `session_capture_eval.py`、`session_capture_enqueue.py` 与 `knowledge/sources/session_capture.py` 已存在。本计划拥有的 3 个 INV-6 守卫及全部 37 个 CaptureService 测试通过，未创建越界占位文件。
- pytest teardown 偶发报告 `test_friday` 仍有一个连接；测试断言均已完成且不影响结果。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 04 可直接使用评估 claim/result/failure API 与独立 retry 字段。
- Plan 05 可直接使用摄取 claim/result/failure API，legacy/low 终态不会被误 claim。
- 跨计划 INV-6 两项将在 evaluator、enqueue 与 normalizer 文件落地后转绿。

## Self-Check: PASSED

---
*Phase: 143-eval*
*Completed: 2026-08-28*
