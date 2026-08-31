---
phase: 143-eval
plan: 01
subsystem: testing
tags: [pytest, session-capture, evaluator, cas, knowledge-ingestion, redaction]

requires:
  - phase: 141
    provides: SessionCapture 账本、CaptureService persist 与 INV-6 唯一 writer
  - phase: 142
    provides: persist-first MCP 接受语义与 Capture 挂钩
provides:
  - Friday LLM 三档评估、用量与失败保留 RED 契约
  - CaptureService CAS、resume 不递增 attempt 与独立 retry 元数据 RED 契约
  - session_capture DOCUMENT 精华-only 与无锚不丢 RED 契约
affects: [143-03, 143-04, 143-05, knowledge ingestion, session capture eval]

tech-stack:
  added: []
  patterns:
    - tests-first RED wave
    - lazy import so missing production modules stay collectable
    - CaptureService public methods drive state; legacy evaluated fixtures only

key-files:
  created:
    - server/tests/initiatives/test_session_capture_eval.py
    - server/tests/knowledge/test_session_capture_source.py
  modified:
    - server/tests/test_model_usage_call_source.py
    - server/tests/initiatives/test_capture_service.py

key-decisions:
  - "Wave 0 只写可收集 RED 测试，不改生产枚举、CAS writer 或 session_capture normalizer。"
  - "状态转移测试经 CaptureService 公共方法串联；legacy evaluated 仅在测试中模拟存量行。"
  - "不勾选 REQUIREMENTS.md 产品完成态：EVAL-01~05 仍待后续实现计划变绿。"

patterns-established:
  - "评估失败不得默认 low；call_source 目标为 session_capture_eval。"
  - "claim 递增 attempt，resume 不递增；eval 与 ingest retry 元数据独立。"
  - "medium/high 仅投影脱敏 distilled_essence；low/未完成评估无 IngestionEvent；无锚仍产 DOCUMENT。"

requirements-completed: [EVAL-01, EVAL-02, EVAL-03, EVAL-04, EVAL-05]

duration: 16min
completed: 2026-08-28
---

# Phase 143 Plan 01: 评估、CAS 与精华投影 RED 契约 Summary

**Friday 三档评估、CaptureService CAS 与 session_capture 精华-only DOCUMENT 投影已钉成可收集 tracer，生产符号缺失时预期 RED。**

## Performance

- **Duration:** 16 min（续跑 Task 2/3；Task 1 已在先前 executor 提交 `074daaa1`）
- **Started:** 2026-08-28T10:11:12Z
- **Completed:** 2026-08-28T10:27:00Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments

- 锁定 high/medium/low 严格 JSON、非空精华、非法输出失败不降 low、用量 `session_capture_eval` 与禁止质量门/Memory 旁路。
- 锁定 `pending_eval|eval_failed → evaluating`、`evaluating → evaluated_low|ingest_pending`、ingest claim/resume/fail/ingested、并发只递增一次、legacy `evaluated` 不可 claim。
- 锁定 DOCUMENT/MCP/`session_capture` 仅投影脱敏精华，payload 只有标量；low/缺失/未完成评估无事件；无锚 medium/high 仍可入统一知识库。

## Task Commits

Each task was committed atomically:

1. **Task 1: 建立 Friday LLM 评估与用量 RED 契约** - `074daaa1` (test)
2. **Task 2: 扩展 CaptureService 状态机 RED 契约** - `935a78de` (test)
3. **Task 3: 建立 session_capture normalizer RED 契约** - `ad18d950` (test)

**Plan metadata:** pending docs commit after this SUMMARY

## Files Created/Modified

- `server/tests/initiatives/test_session_capture_eval.py` - 三档评估、失败保留、用量与静态隔离契约。
- `server/tests/test_model_usage_call_source.py` - CallSource 闭集含 `initiative_profile` 与待实现 `session_capture_eval`。
- `server/tests/initiatives/test_capture_service.py` - CAS、resume、retry 元数据、闭集档位与存量 pending_eval 原文。
- `server/tests/knowledge/test_session_capture_source.py` - 精华-only DOCUMENT、low 空事件、无锚不丢与项目 REFERENCES。

## Decisions Made

- 续跑时保留 Task 1 提交，不重做、不回退；不触碰 Plan 02 拥有的 `test_capture_observability.py`。
- 新状态准备走 CaptureService 公共方法；legacy `evaluated` 用测试内 `aupdate` 模拟存量行，因为新 writer 不以它为目标。
- 不勾选 REQUIREMENTS.md：本计划只交付 tracer。

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

续跑时 `gsd-tools` 不在 PATH，改用 `.cursor/gsd-core/bin/gsd-tools.cjs`。并行 pytest 会争用 Django 测试库，验证改为串行。Task 3 部分用例当前先因缺失 `claim_evaluation` RED，Plan 03 落地后应变为缺失 `session_capture` normalizer/注册表。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- 143-03 可按 CAS/字段测试实现 additive migration 与唯一 writer。
- 143-04 可按 evaluator/用量测试实现 Friday JSON 评估器。
- 143-05 可按 normalizer 测试实现精华-only DOCUMENT 投影。
- Nyquist 保持未合规，直到 Wave 0 两边 tracer 与后续实现门禁都绿。
- 无新增依赖（T-143-SC accept）。

## Self-Check: PASSED

---
*Phase: 143-eval*
*Completed: 2026-08-28*
