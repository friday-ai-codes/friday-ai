---
phase: 141-capture
plan: 04
subsystem: observability
tags: [structlog, capture, redaction, pytest, nyquist]

# Dependency graph
requires:
  - phase: 141-capture
    provides: SessionCapture 独立账本、CaptureService 唯一写入与仓库项目挂钩
provides:
  - Session Capture 持久化 caller 生命周期字段白名单回归
  - LOGGING-SPEC 中的 session_capture_persist 三事件目录
  - Phase 141 Wave 0 与 Nyquist 验证收口
affects: [143-capture-evaluation, observability, session-capture]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - structlog caller 生命周期使用 started/completed/failed 三事件
    - Capture 日志只记录非敏感审计元数据且观测失败不反噬业务

key-files:
  created:
    - .planning/phases/141-capture/141-04-SUMMARY.md
  modified:
    - server/tests/initiatives/test_capture_observability.py
    - .planning/observability/LOGGING-SPEC.md
    - .planning/phases/141-capture/141-VALIDATION.md

key-decisions:
  - "Phase 141 只登记 Capture persist caller 生命周期，不新增 session_capture_eval CallSource 或 sampling 事件。"
  - "日志字段采用闭集白名单，问答正文、git_url 与 token 不进入事件。"

patterns-established:
  - "Capture caller 事件：started 无 duration_ms，completed/failed 带 duration_ms。"
  - "观测字段测试以精确 key 集合锁定，防止后续误加敏感正文。"

requirements-completed: [STORE-01, OBS-01, OBS-02]

# Metrics
duration: 5min
completed: 2026-08-28
---

# Phase 141 Plan 04: Capture 可观测性收口 Summary

**Session Capture 持久化 caller 三事件、元数据白名单、账本分离回归与 Nyquist 验证全部收口。**

## Performance

- **Duration:** 5 分钟
- **Started:** 2026-08-28T07:51:53Z
- **Completed:** 2026-08-28T07:56:59Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- 加固 `session_capture_persist_started/completed/failed` 的精确字段白名单与成功审计标记断言。
- 在 `LOGGING-SPEC.md` 登记 Capture persist caller 生命周期，并明确评估/入图留待 Phase 143。
- 验证 Capture 不写 `ProjectMemory` 或 Interaction Ledger，旧 `report_project_knowledge` 语义保持不变。
- 将 Phase 141 的 Wave 0 与 Nyquist 验证状态更新为完成。

## Task Commits

1. **Task 1: caller 生命周期日志 best-effort（OBS-01/02）** - `69b27537`（test）
2. **Task 2: LOGGING-SPEC 登记 + 分离账本回归 + VALIDATION 收口** - `c79b3c17`（docs）

## Files Created/Modified

- `server/tests/initiatives/test_capture_observability.py` - 锁定生命周期事件字段闭集与成功审计标记。
- `.planning/observability/LOGGING-SPEC.md` - 登记 Session Capture persist 三事件。
- `.planning/phases/141-capture/141-VALIDATION.md` - 标记任务验证、Wave 0 与 Nyquist 已完成。
- `.planning/phases/141-capture/141-04-SUMMARY.md` - 记录本计划执行结果。

## Decisions Made

- 沿用 Plan 141-02 已实现的 best-effort 日志路径，不做无意义源码改写。
- Phase 141 不新增 eval/ingest sampling 事件，也不修改 `CallSource`。
- completed/failed 事件仅允许计划定义的审计元数据，字段扩展必须先更新契约测试。

## Deviations from Plan

None - 计划要求的 `CaptureService` 三事件实现已由前序计划落地且现有测试直接通过；本计划按职责完成契约加固、目录登记和回归收口。

## Issues Encountered

- PostgreSQL 测试库 teardown 报告仍有一个连接占用的既有 warning；39 项目标回归均通过，未影响结果。

## Known Stubs

None.

## TDD Gate Compliance

- RED 契约由 Phase 141-01 的 `793c4e49` 建立。
- GREEN 实现由 Phase 141-02 的 `35ea6708` 落地。
- 本计划在既有 RED/GREEN 基础上增加字段闭集回归，未重复制造失败测试。

## Verification

- `uv run pytest tests/initiatives/test_capture_observability.py -x -q`：5 passed。
- `uv run pytest tests/initiatives/test_capture_service.py tests/initiatives/test_capture_inv6_guard.py tests/initiatives/test_capture_observability.py tests/initiatives/test_memory_inv6_guard.py tests/mcp_tools/test_report_project_knowledge.py -q`：39 passed。
- IDE lint：无新增诊断。

## User Setup Required

None - 无外部服务配置或新依赖。

## Next Phase Readiness

- Capture 持久化、挂钩、幂等、脱敏与 caller 可观测契约已齐备，可供 Phase 142/143 接入。
- Phase 143 才可新增评估/入图 sampling 生命周期与相应 `CallSource`。

## Self-Check: PASSED

---
*Phase: 141-capture*
*Completed: 2026-08-28*
