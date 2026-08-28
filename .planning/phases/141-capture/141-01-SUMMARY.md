---
phase: 141-capture
plan: 01
subsystem: testing
tags: [pytest, django, capture, inv-6, observability, redaction]

requires:
  - phase: 140
    provides: 图查询观测与安全测试范式
provides:
  - CaptureService 持久化、挂钩、幂等、脱敏与账本分离 RED 契约
  - SessionCapture INV-6 唯一 writer 与 deferred sink 禁止守卫
  - caller 生命周期、日志无正文与观测 best-effort RED 契约
affects: [141-02, 141-03, 141-04, CaptureService, SessionCapture]

tech-stack:
  added: []
  patterns: [tests-first RED wave, INV-6 source guard, structlog capture_logs]

key-files:
  created:
    - server/tests/initiatives/test_capture_service.py
    - server/tests/initiatives/test_capture_inv6_guard.py
    - server/tests/initiatives/test_capture_observability.py
  modified:
    - .planning/phases/141-capture/141-VALIDATION.md

key-decisions:
  - "Wave 0 仅建立失败测试，不提前实现 SessionCapture 或 CaptureService。"
  - "缺失 session_id 固定使用 unspecified；仓库歧义、项目单挂与项目仓库不匹配均以命名用例锁定。"
  - "SessionCapture 写入只允许 initiatives/services/capture_service.py，且 Phase 141 writer 禁止接入评估、入图、Memory 与分支项目解析入口。"

patterns-established:
  - "Capture 行为测试统一经 CaptureService.persist 调用，禁止以旁路 ORM create 作为生产路径测试习惯。"
  - "观测测试同时验证 caller 生命周期、正文不入日志与 logger 故障不反噬落库。"

requirements-completed: [STORE-01, STORE-02, STORE-03, STORE-04, STORE-05, OBS-01, OBS-02]

duration: 3 min
completed: 2026-08-28
---

# Phase 141 Plan 01: Capture Wave 0 RED 契约 Summary

**三个 tests-first 模块已钉死 Capture 永不丢失、唯一写入、挂钩权限与 caller 观测契约，并保持生产实现缺失时预期 RED。**

## Performance

- **Duration:** 3 min
- **Started:** 2026-08-28T07:25:01Z
- **Completed:** 2026-08-28T07:28:00Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- 新增 14 个 CaptureService 行为场景，覆盖无锚落库、unknown 标量、脱敏归因、三层分离、幂等及授权挂钩。
- 新增 INV-6 静态守卫，扫描 ORM create/update、直接实例化与 save，并验证唯一 writer 实际写表且不调用 deferred sinks。
- 新增 caller 生命周期、失败脱敏、无正文、无提前 eval/ingest sampling 及 logger best-effort 观测契约。
- VALIDATION Wave 0 文件与四个硬性命名用例均标记为已创建、当前 RED；`wave_0_complete` 与 `nyquist_compliant` 保持 false。

## Task Commits

1. **Task 1: CaptureService 行为测试骨架** - `0bf71276`（test）
2. **Task 2: INV-6 与观测测试骨架 + VALIDATION Wave 0** - `793c4e49`（test）

## Files Created/Modified

- `server/tests/initiatives/test_capture_service.py` - STORE-01..05 持久化、幂等、挂钩、权限与脱敏 RED 契约。
- `server/tests/initiatives/test_capture_inv6_guard.py` - SessionCapture 唯一 writer 与禁止 deferred sink 静态守卫。
- `server/tests/initiatives/test_capture_observability.py` - OBS-01/02 caller 生命周期、日志隔离与 best-effort RED 契约。
- `.planning/phases/141-capture/141-VALIDATION.md` - Wave 0 文件及命名用例落地状态。

## Decisions Made

- 遵循计划保留纯 RED 波次，不添加任何生产模型、服务、MCP、UI 或依赖。
- `test_missing_session_id_uses_unspecified` 同时锁定字面后备值与缺失会话下的幂等行为。
- 项目仓库不匹配测试让同一 actor 在两个项目空间均有权限，以隔离验证 mismatch，而非误测 unauthorized。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] 修正旧版 STATE 位置格式导致的推进失败**

- **Found during:** 计划收尾
- **Issue:** `state.advance-plan` 无法解析 `Plan: —`，而 `state.update-progress` 仅更新计数，未同步 frontmatter 百分比与 Current Position。
- **Fix:** 保留 SDK 已写入的进度、指标、决策和 session 数据，并手动同步 Phase 141 的 plan 位置、25% 进度与下一计划焦点。
- **Files modified:** `.planning/STATE.md`
- **Verification:** STATE 显示 `Plan: 1 of 4`、`Status: In progress`、`percent: 25`。
- **Committed in:** 计划 metadata commit

**Total deviations:** 1 auto-fixed（1 blocking）
**Impact on plan:** 仅修复 GSD 状态台账兼容性，不改变测试或产品范围。

## Issues Encountered

pytest 如预期因 `SessionCapture` / `CaptureService` 尚未实现而 RED；INV-6 扫描本身通过，writer 存在性与实际写入断言按计划失败。GSD 状态推进器无法解析旧的 `Plan: —`，已按上方 deviation 修正台账。

## Verification

- `uv run ruff check tests/initiatives/test_capture_service.py tests/initiatives/test_capture_inv6_guard.py tests/initiatives/test_capture_observability.py`：通过。
- `uv run pytest tests/initiatives/test_capture_service.py -x -q`：预期 RED，收集阶段因 `SessionCapture` 尚未导出失败。
- `uv run pytest tests/initiatives/test_capture_inv6_guard.py -q`：预期 RED，1 passed / 2 failed；旁路扫描通过，缺失唯一 writer 导致失败。
- Capture 三模块组合命令：预期 RED，因生产模型尚未实现而收集失败。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- 已准备进入 141-02，实现 SessionCapture、migration、核心 persist 与 INV-6 writer。
- 141-03 可直接以四个硬性命名用例和其余 link/unauthorized 测试驱动挂钩状态机。
- 141-04 可直接以观测模块驱动完整 caller 生命周期与 LOGGING-SPEC 收口。

## Self-Check: PASSED

- 三个新增测试文件与更新后的 VALIDATION 文件均存在。
- Task commits `0bf71276`、`793c4e49` 均存在且只包含本计划文件。
- 用户指定的无关脏文件、`skills` 状态与 debug 记录未被暂存、提交或修改。

---
*Phase: 141-capture*
*Completed: 2026-08-28*
