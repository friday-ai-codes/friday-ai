---
phase: 143-eval
plan: "04"
subsystem: llm-evaluation
tags: [session-capture, langchain, model-usage, structlog]

requires:
  - phase: 143-01
    provides: Session Capture evaluator 与 CallSource RED 契约
  - phase: 143-03
    provides: Capture 可恢复评估状态机与三档闭集
provides:
  - Friday 默认 LLM 驱动的严格 high/medium/low 价值评估器
  - 可脱离会话理解且再次脱敏的 distilled_essence
  - session_capture_eval 用量归因与评估采样生命周期合同
affects: [143-05, 143-06, session capture worker, delivery knowledge]

tech-stack:
  added: []
  patterns:
    - 严格完整 JSON object 与闭集档位校验
    - LLM 成功失败统一 best-effort ModelUsageRecord
    - evaluator 无 ORM 写入并与 ProjectMemory 隔离

key-files:
  created:
    - server/initiatives/services/session_capture_eval.py
  modified:
    - server/agents/call_source.py
    - .planning/observability/LOGGING-SPEC.md

key-decisions:
  - "评估器只使用 resolved.extra.default_model；缺失时抛可重试错误，不使用 legacy 或硬编码 fallback。"
  - "模型响应必须恰好包含 value_tier 与 distilled_essence，任何非法结构均失败而不降级为 low。"
  - "评估器只返回 frozen 强类型结果；Capture 状态与知识摄取继续由后续 worker 经唯一 writer 处理。"

patterns-established:
  - "所有 session_capture_eval LLM 调用在 use_call_source 作用域内执行。"
  - "采样日志仅记录 capture_id、tier、status、attempt、duration 与触发用户，不记录问答或精华正文。"

requirements-completed: [EVAL-01, EVAL-02, EVAL-05, OBS-04]

duration: 3min
completed: 2026-08-28
---

# Phase 143 Plan 04: Session Capture 三档价值评估 Summary

**Friday 默认 LLM 现可严格输出 high/medium/low 与脱敏可检索精华，所有模型调用按 session_capture_eval 归因且失败保持可重试。**

## Performance

- **Duration:** 3 min
- **Started:** 2026-08-28T10:41:22Z
- **Completed:** 2026-08-28T10:44:24Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- 将 `session_capture_eval` 注册为第 47 个受控 `CallSource`，并同步完整观测合同。
- 实现不写 ORM 的 frozen 强类型 evaluator，严格拒绝非法 JSON、非法档位、空精华与缺失默认模型。
- 成功路径记录 token、TTFT、duration，失败路径记录上游状态码；日志和错误文本均脱敏且观测 best-effort。

## Task Commits

1. **Task 1: 注册 session_capture_eval 用量与日志合同** - `e970a1394` (feat)
2. **Task 2: 实现严格 Friday LLM 三档 evaluator** - `43a741af2` (feat)

**Plan metadata:** `d499935cf` (docs)

_Task 2 的 TDD RED 契约由 Plan 143-01 提交提供，本计划提交 GREEN 实现。_

## Files Created/Modified

- `server/initiatives/services/session_capture_eval.py` - 严格三档评估、脱敏结果、用量与采样日志。
- `server/agents/call_source.py` - 注册 `SESSION_CAPTURE_EVAL` 并对齐 47 值说明。
- `.planning/observability/LOGGING-SPEC.md` - 登记第 47 个调用来源及 eval/normalize/ingest/recovery 生命周期。

## Decisions Made

- 非流式 `ainvoke` 的首个完整响应耗时同时作为 TTFT，完整调用耗时作为 duration。
- LLM 已成功响应但结构非法时仍记录本次实际模型用量，随后把评估判为可重试失败。
- 输入校验或默认模型缺失发生在真实模型调用前，不伪造 provider、model 或 token 用量。

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- 并发 Plan 05 在工作区创建了 normalizer 文件；本计划未读取、修改、暂存或提交该文件。
- 并发测试共享 PostgreSQL 测试库，pytest teardown 报告仍有一个连接；20 项断言与 ruff 均通过。
- Friday 对通用 `main` 分支返回了与本仓 Phase 143 无关的项目映射，因此执行仅采用本地计划、上下文与前序 Summary。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 05/06 可直接调用 `SessionCaptureEvaluator.evaluate` 并由 CaptureService 唯一 writer 落状态。
- evaluator 不包含 ProjectMemory、质量门、仓库 confidence 或 normalizer 依赖。

## Known Stubs

None.

## Self-Check: PASSED

---
*Phase: 143-eval*
*Completed: 2026-08-28*
