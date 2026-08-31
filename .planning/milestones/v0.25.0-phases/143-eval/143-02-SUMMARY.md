---
phase: 143-eval
plan: 02
subsystem: testing
tags: [pytest, durable, session-capture, inv-6, observability, sampling, redaction]

requires:
  - phase: 142
    provides: report_session_knowledge persist-first MCP 与 Capture 账本
  - phase: 141
    provides: CaptureService persist caller 观测与 INV-6 writer 守卫
provides:
  - 双 durable eval/ingest 任务、稳定 key、退避新 job 与 stale 恢复 RED 契约
  - persist-first accepted 与 fail-soft enqueue RED 契约
  - INV-6 禁止 Capture/Memory/background_runner 旁路的静态红线
  - eval/normalize/ingest sampling 生命周期与恢复扫描观测 RED 契约
affects: [143-03, 143-04, 143-06, 143-07, durable workers, session capture eval]

tech-stack:
  added: []
  patterns:
    - tests-first RED wave
    - AST source guards for sampling lifecycle
    - persist-first enqueue fail-soft
    - stable idempotency key plus attempt-specific backoff jobs

key-files:
  created:
    - server/tests/initiatives/test_session_capture_eval_tasks.py
  modified:
    - server/tests/mcp_tools/test_report_session_knowledge.py
    - server/tests/initiatives/test_capture_inv6_guard.py
    - server/tests/initiatives/test_capture_observability.py
    - .planning/phases/143-eval/143-VALIDATION.md

key-decisions:
  - "Wave 0 仅建立失败测试，不提前实现 eval/ingest worker 或 enqueue helper。"
  - "Phase 141 persist 路径仍禁止提前发出 eval/ingest/normalize sampling；Phase 143 sampling 契约改为对尚未落地源文件做 AST 白名单。"
  - "VALIDATION Task ID 按 143-01（评估/CAS/normalizer）与 143-02（durable/MCP/INV-6/sampling）拆分；wave_0_complete 与 nyquist_compliant 保持 false。"

patterns-established:
  - "durable payload 仅 capture_id/attempt/initiated_by_user_id；worker 入口 bind_task_context(user or system, source=durable, component=knowledge)。"
  - "sampling 事件 category=sampling、component=knowledge，completed/failed 带 duration_ms；正文与 token 不得入日志；观测失败 swallow。"
  - "恢复扫描逐行 debug，周期仅一条 sampling 汇总。"

requirements-completed: [EVAL-01, EVAL-03, EVAL-04, EVAL-05, OBS-04]

duration: 8min
completed: 2026-08-28
---

# Phase 143 Plan 02: durable 投递与 sampling RED 契约 Summary

**persist-first 双 durable 任务、INV-6 旁路红线与 eval/normalize/ingest sampling 生命周期已钉成可收集 tracer，生产符号缺失时预期 RED。**

## Performance

- **Duration:** 8 min（续跑 Task 3；Task 1/2 已在先前 executor 提交）
- **Started:** 2026-08-28T10:11:20Z
- **Completed:** 2026-08-28T10:18:00Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments

- 锁定 `QUEUE_KNOWLEDGE`、eval/ingest 双任务同名、纯标量 payload、稳定 idempotency key、退避新 job、stale evaluating/ingesting 恢复与 actor rebind。
- 锁定 MCP persist 后才 enqueue、enqueue 失败仍 `accepted=true`，并扩展 INV-6 禁止 Memory/`aschedule_ingestion`/`background_runner` 旁路。
- 用 Phase 143 sampling started/completed/failed 白名单替换 `test_no_eval_sampling_events`；persist 路径仍不得提前发出 eval sampling。
- Validation 表映射到 143-01/143-02；143-02 Wave 0 文件标为已建 tracer、期望 RED；frontmatter 保持 draft / `wave_0_complete=false` / `nyquist_compliant=false`。

## Task Commits

Each task was committed atomically:

1. **Task 1: 建立双任务 durable 与恢复 RED 契约** - `48fa2459` (test)
2. **Task 2: 建立 persist-first MCP 与隔离守卫 RED 契约** - `f7d83094` (test)
3. **Task 3: 建立 sampling 观测契约并同步 Validation** - `9a1602ba` (test)

**Plan metadata:** pending docs commit after this SUMMARY

## Files Created/Modified

- `server/tests/initiatives/test_session_capture_eval_tasks.py` - 双任务、退避、恢复扫描与 actor rebind RED 契约。
- `server/tests/mcp_tools/test_report_session_knowledge.py` - persist-first enqueue 与 fail-soft accepted。
- `server/tests/initiatives/test_capture_inv6_guard.py` - eval/enqueue/worker/normalizer 旁路静态红线。
- `server/tests/initiatives/test_capture_observability.py` - sampling 生命周期、禁正文、best-effort 与 persist 隔离。
- `.planning/phases/143-eval/143-VALIDATION.md` - Task ID/Plan/Wave 映射与 Wave 0 文件归属。

## Decisions Made

- 续跑时保留已提交的 Task 1/2，不重做、不回退。
- 观测 RED 以「目标文件尚未建立」失败，而不是改 persist 行为去造假绿。
- 不勾选 REQUIREMENTS.md 产品完成态：本计划只交付 tracer，EVAL/OBS 实现仍在后续 PLAN。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] 保留 persist 路径禁止提前 eval sampling**
- **Found during:** Task 3（恢复中断的观测测试）
- **Issue:** 直接删除 `test_no_eval_sampling_events` 会丢掉 Phase 141「persist 不得提前评估」契约。
- **Fix:** 新增 `test_persist_does_not_emit_eval_sampling_events`，同时用 AST 白名单锁定 Phase 143 sampling 生命周期。
- **Files modified:** `server/tests/initiatives/test_capture_observability.py`
- **Verification:** persist 用例 PASSED；`test_eval_normalize_ingest_sampling_lifecycle` 因缺失 `session_capture_eval.py` 期望 FAILED；ruff 通过。
- **Committed in:** `9a1602ba` (Task 3)

---

**Total deviations:** 1 auto-fixed (1 missing critical)
**Impact on plan:** 补回 persist 隔离，未扩大实现范围。

## Issues Encountered

续跑前工作区已有 Task 3 半成品；并行 Plan 01 在 `test_capture_service.py` 与 `test_session_capture_source.py` 留下未提交改动，已刻意不纳入本计划提交。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- 143-02 Wave 0 tracer 齐备，后续 143-06/07 可按这些失败用例实现 durable 与 MCP 接线。
- 143-01 的 CAS 扩展与 `session_capture` normalizer tracer 仍可能未完成；Nyquist 保持未合规直到两边 Wave 0 与实现门禁都绿。
- 无新增依赖（T-143-SC accept）。

## Self-Check: PASSED

---
*Phase: 143-eval*
*Completed: 2026-08-28*
