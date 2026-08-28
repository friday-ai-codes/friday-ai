---
phase: 143-eval
plan: "07"
subsystem: durable-knowledge
tags: [django, mcp, session-capture, durable, observability, nyquist]

requires:
  - phase: 143-02
    provides: MCP/durable/INV-6/观测 Wave 0 tracer
  - phase: 143-06
    provides: Session Capture eval/ingest durable 双任务与恢复 helper
provides:
  - MCP Capture 提交后的 fail-soft durable eval 生产接线
  - 终态跳过与 pending/failed 幂等补投语义
  - Phase 143 隔离、观测和 183 项 Nyquist 总门禁证据
affects: [144-retrieval, 145-hooks, session capture pipeline]

tech-stack:
  added: []
  patterns:
    - persist-first post-commit enqueue with database recovery
    - terminal-state guard before durable helper invocation
    - sampling lifecycle verification across direct and wrapped loggers

key-files:
  created:
    - .planning/phases/143-eval/143-07-SUMMARY.md
  modified:
    - server/mcp_tools/views.py
    - server/tests/initiatives/test_capture_observability.py
    - .planning/phases/143-eval/143-VALIDATION.md

key-decisions:
  - "CaptureService.persist 返回即为提交边界；view 直接 await durable helper，不在同步 on_commit callback 中桥接 async。"
  - "MCP 只为 pending_eval/eval_failed 调 helper，终态不重派；helper/队列异常不改变 accepted 响应。"
  - "观测静态门禁同时识别直接 logger 调用与统一 _log 封装，并验证封装固定 sampling/knowledge 字段。"

patterns-established:
  - "accepted=true 仅由 Capture 持久化事实决定，所有后续队列副作用 fail-soft。"
  - "Phase 143 自动门禁使用 mock 外部服务；真实 Postgres worker、Provider、Qdrant 保持 manual-only。"

requirements-completed: [EVAL-01, EVAL-02, EVAL-03, EVAL-04, EVAL-05, OBS-04]

duration: 11min
completed: 2026-08-28
---

# Phase 143 Plan 07: MCP durable eval 集成与 Nyquist 收口 Summary

**MCP 接受的 Session Capture 现已在提交后获得 durable eval 投递机会，队列故障不回滚七键 accepted 响应，183 项阶段回归证明三档评估、精华入图、恢复、归因和 Memory 隔离。**

## Performance

- **Duration:** 11 min
- **Started:** 2026-08-28T11:02:04Z
- **Completed:** 2026-08-28T11:13:18Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- 在 `ReportSessionKnowledgeView.post` 的 Capture 提交后接入 `enqueue_session_capture_eval`，传递 Capture 主键和持久化的触发用户。
- pending/failed Capture 可经稳定 key 补投，evaluated_low/ingested/legacy evaluated 等终态不调用 helper；enqueue 异常仍返回既有七键 200 `accepted=true`。
- INV-6 和 sampling 门禁通过，证明唯一 Capture writer、无 ProjectMemory/旁路摄取、actor/system rebind、脱敏和 logger best-effort。
- Phase 143 指定的 11 个测试文件共 183 passed，生产文件 ruff 全部通过，`143-VALIDATION.md` 已置为 validated/Nyquist compliant。

## Task Commits

1. **Task 1: 接线 persist-first MCP durable eval 投递** - `830015d66` (feat)
2. **Task 2: 收紧 INV-6、sampling 与全阶段门禁** - `d01b48d4d` (test)

**Plan metadata:** pending docs commit after this SUMMARY

## Files Created/Modified

- `server/mcp_tools/views.py` - Capture 提交后的可恢复状态守卫与 fail-soft durable eval 投递。
- `server/tests/initiatives/test_capture_observability.py` - 同时覆盖直接 logger 和统一 `_log` 封装的 sampling 生命周期。
- `.planning/phases/143-eval/143-VALIDATION.md` - 全任务转绿、实测时长、自动证据与 manual-only 边界。
- `.planning/phases/143-eval/143-07-SUMMARY.md` - 计划执行结果与验证记录。

## Decisions Made

- 不使用 `transaction.on_commit` 内的 async-to-sync 嵌套；`CaptureService.persist` 内部 atomic 在返回前已提交，直接 await helper 是明确的 post-commit 边界。
- view 在调用 helper 前执行状态白名单，避免测试替身或未来 helper 漂移导致终态重派；helper 自身仍保留相同守卫作为纵深保护。
- 无 repository/project 的 Capture 不跳过投递，后续 medium/high 仍可形成无锚 DOCUMENT 事件。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Test Contract] 修正观测门禁遗漏统一日志封装**
- **Found during:** Task 2
- **Issue:** Wave 0 静态扫描只识别直接 `logger.info/warning`，无法识别评估器既有的 `self._log` 生命周期调用，误报 eval 无事件。
- **Fix:** 扫描 `_log` 调用，并额外验证封装本身固定 `category="sampling"`、`component=_COMPONENT` 和 `_COMPONENT="knowledge"`。
- **Files modified:** `server/tests/initiatives/test_capture_observability.py`
- **Verification:** INV-6/观测 16 passed；全阶段门禁 183 passed。
- **Committed in:** `d01b48d4d`

---

**Total deviations:** 1 auto-fixed（1 test contract bug）
**Impact on plan:** 修复 tracer 与现行 best-effort 日志封装的错配，未扩大生产范围。

## Issues Encountered

- PostgreSQL 测试库 teardown 仍提示有一个其他 session 占用 `test_friday`；本次目标和全阶段套件均以退出码 0 完成，不构成失败，未修改阶段外测试基础设施。
- Friday 的 `main` 分支映射到无关项目，本计划未向该项目回写知识或 API 状态。

## TDD Gate Compliance

- Task 1 的 RED tracer 已由 143-02 提前提交；本计划先确认 4 个 enqueue 契约按预期失败，再以 `830015d66` 完成 GREEN，目标套件最终 20 passed。

## User Setup Required

None - no external service configuration required.

## Known Stubs

None.

## Next Phase Readiness

- Phase 144 可在不改变 Capture 账本语义的前提下实现 `session_capture` 检索、回放、白名单与 RetrievalTrace。
- Phase 145 可接入 Cursor / Claude Code hooks；MCP 到 durable eval/ingest 的生产路径已经闭合。
- 真实 Postgres + Procrastinate worker、Provider 与 Qdrant 冒烟仍按 Validation 标记为 manual-only。

## Self-Check: PASSED

---
*Phase: 143-eval*
*Completed: 2026-08-28*
