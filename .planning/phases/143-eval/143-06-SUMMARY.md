---
phase: 143-eval
plan: "06"
subsystem: durable-knowledge
tags: [django, durable, session-capture, retry, recovery, ingestion]

requires:
  - phase: 143-03
    provides: Capture 可恢复评估与摄取 CAS 状态机
  - phase: 143-04
    provides: 严格三档 Session Capture LLM 评估器
  - phase: 143-05
    provides: medium/high 精华-only knowledge normalizer
provides:
  - 独立 knowledge 队列与 eval/ingest 双后端任务注册
  - 基于稳定 key/lock 的纯标量投递和数据库行恢复
  - 六次上限指数退避、状态域隔离和 at-least-once 重放幂等
affects: [143-07, session capture MCP enqueue, durable workers, delivery knowledge]

tech-stack:
  added: []
  patterns:
    - Capture row as durable source of truth
    - stable recovery key with attempt-specific retry jobs
    - CAS claim/resume across independent eval and ingest workers

key-files:
  created:
    - server/initiatives/services/session_capture_enqueue.py
  modified:
    - server/durable/queues.py
    - server/durable/tasks.py
    - server/durable/tasks_impl.py
    - server/durable/handlers.py
    - server/tests/initiatives/test_session_capture_eval_tasks.py

key-decisions:
  - "首次投递和 stranded recovery 使用稳定 capture-eval/capture-ingest key 与同值 lock，worker 退避新 job 仅保留 lock/run_at。"
  - "processing 行恢复时保留 evaluating/ingesting，不回退 pending；CAS resume 不增加对应 attempt。"
  - "ingest 返回零事件按可重试失败处理，摄取失败只进入 ingest_failed，绝不重新调用 evaluator。"

patterns-established:
  - "durable payload 只携带 capture_id/attempt，触发用户由 DurableTaskService 注入并在 worker 入口重新绑定。"
  - "恢复扫描逐行隔离，行级事件使用 debug，每个 sweep 仅发一条 sampling 汇总。"

requirements-completed: [EVAL-01, EVAL-03, EVAL-04, EVAL-05, OBS-04]

duration: 11min
completed: 2026-08-28
---

# Phase 143 Plan 06: Session Capture durable 双任务 Summary

**Session Capture 现由独立 eval/ingest durable worker 驱动，稳定恢复键、CAS resume 与有界退避共同保证重启恢复和失败域隔离，ingest 重试不会重复 LLM。**

## Performance

- **Duration:** 11 min
- **Started:** 2026-08-28T10:49:14Z
- **Completed:** 2026-08-28T11:00:04Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments

- 新增 `QUEUE_KNOWLEDGE`、Procrastinate 包壳、in-process adapter 与五分钟周期恢复任务。
- 首次投递和恢复只传 `capture_id/attempt`，使用稳定 idempotency key/lock；恢复覆盖 due pending/failed 与 stale processing，并跳过 active/终态。
- eval worker 只负责 LLM 与结果落账，medium/high 再投 ingest；ingest worker 直接调用统一 `ingest`，失败不回到评估域。
- 两个 worker 均重新绑定触发用户，错误脱敏，最多自动尝试六次，并以 `5 * 2**attempt` 秒退避、300 秒封顶。

## Task Commits

1. **Task 1: 建立 knowledge 队列、双后端任务与投递/恢复 helper** - `08bebd5c3` (feat)
2. **Task 2: 实现独立 eval 与 ingest worker** - `e78a06e79` (feat)

**Plan metadata:** pending docs commit after this SUMMARY

## Files Created/Modified

- `server/initiatives/services/session_capture_enqueue.py` - 稳定投递、due/stale 扫描、active key 守卫与逐行隔离恢复。
- `server/durable/queues.py` - 登记 knowledge 逻辑队列。
- `server/durable/tasks.py` - 注册两个 keyword-only 包壳和周期恢复任务。
- `server/durable/tasks_impl.py` - 独立 eval/ingest worker、用户重绑定、退避和失败域隔离。
- `server/durable/handlers.py` - 为 in-process fallback 注册 `**payload` adapters。
- `server/tests/initiatives/test_session_capture_eval_tasks.py` - 对齐现行 durable 后端布局与精确 evaluator 隔离断言。

## Decisions Made

- 达到六次自动上限的失败行保持原状，周期恢复不再自动投递；显式 enqueue helper 仍允许人工重试失败态。
- retry job 不使用首次稳定 idempotency key，避免已完成 todo 去重吞掉合法重试；同 Capture 仍用稳定 doing lock 串行。
- normalizer 零产出视为 ingest 失败，防止错误标记 `ingested`。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Test Contract] 修正 Wave 0 对现行 durable 后端和 ingest trigger 的错误假设**
- **Found during:** Task 2
- **Issue:** RED 测试引用不存在的 `durable/backends/*.py` 拆分文件，并用 `session_capture_eval` 子串禁止断言误伤计划明确要求的 ingest trigger。
- **Fix:** 改为检查现行 `durable/backends.py`，并只禁止实际 evaluator 调用/类型；CAS resume 静态断言改查真实私有实现。
- **Files modified:** `server/tests/initiatives/test_session_capture_eval_tasks.py`
- **Verification:** 任务测试 34 项全部通过。
- **Committed in:** `e78a06e79`

**2. [Rule 2 - Observability] 收口恢复扫描为单条 sampling 汇总**
- **Found during:** Task 2 联合观测检查
- **Issue:** Task 1 初版在 periodic wrapper 与 helper 各记录一次汇总，且行级失败使用 warning，不符合高频恢复扫描纪律。
- **Fix:** 行级成功/失败统一 debug，helper 每次 sweep 只发一条带耗时的 sampling 汇总，wrapper 仅委托。
- **Files modified:** `server/initiatives/services/session_capture_enqueue.py`, `server/durable/tasks.py`
- **Verification:** recovery 日志契约通过；ruff 通过。
- **Committed in:** `e78a06e79`

**3. [Rule 1 - State Metadata] 修正 SDK 写入的进度与续做位置**
- **Found during:** 计划状态收口
- **Issue:** `state.update-progress` 返回 93%，但把 STATE frontmatter 写成 40%，并保留了 143-05 的 stale activity/wave 文案。
- **Fix:** 按 14/15 已完成计划修正为 93%，并把续做位置更新为 143-07 / Wave 4。
- **Files modified:** `.planning/STATE.md`
- **Verification:** STATE 与 ROADMAP 的 6/7 Phase 143 进度一致。
- **Committed in:** pending plan metadata commit

---

**Total deviations:** 3 auto-fixed（2 bugs，1 observability）
**Impact on plan:** 均用于修正阻塞契约或落实既定日志纪律，未扩大产品范围。

## Issues Encountered

- 计划目标测试 `test_session_capture_eval_tasks.py` 为 34 passed，scoped ruff 与禁止路径扫描通过。
- 扩大到 101 项 Phase 143 联合回归时，断言累计 100 passed，但既有测试后台 workspace provisioning 与共享 PostgreSQL `test_friday` teardown 相互污染，产生 1 failed/23 teardown errors（外键引用已回滚 user）；该故障不来自本计划改动，未越界修改后台 runner 或测试基础设施。
- Friday `main` 分支映射到无关项目，本计划未把执行知识回写到错误项目。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 143-07 可在 MCP persist 成功后调用 `enqueue_session_capture_eval`，队列故障仍由 Capture 行和周期恢复兜底。
- Phase 143 目标 task suite 与静态安全守卫已通过；跨目录共享测试库污染需由测试基础设施后续独立处理。

## Known Stubs

None.

## Self-Check: PASSED

---
*Phase: 143-eval*
*Completed: 2026-08-28*
