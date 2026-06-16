---
phase: 43-env-resume
plan: 02
subsystem: plan_orchestration
tags: [resume, plan-session, async-orm, engine-driver, hitl-clarification]

# Dependency graph
requires:
  - phase: 38-41 plan_orchestration
    provides: PlanOrchestrationEngine, build_orchestration_engine, aall_research_tasks_terminal, PlanSessionService.transition
provides:
  - "入口无关的共享续驱 helper adrive_plan_session_to_pause_or_terminal(engine, session, *, max_steps=20)"
  - "barrel re-export via services.plan_orchestration"
  - "四路径单测：终态返回 / researching 在途短路 / clarifying 在途短路 / step 上限 fail"
affects: [43-03 chat plan resume 接线, 43-04 既有调用方改造 (plan_research node/tool)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "入口无关续驱 helper：engine 由调用方传入，不新建第二个 engine 工厂"
    - "engine 纯度（INV-6）：状态只经 engine.session_service.transition，绝不直接写 session.status"
    - "重挂起短路：clarifying-pending（HITL 守护）+ researching-in-flight，行为等价于节点/工具 _maybe_suspend"

key-files:
  created:
    - server/services/plan_orchestration/resume.py
    - server/tests/services/test_plan_resume_driver.py
  modified:
    - server/services/plan_orchestration/__init__.py

key-decisions:
  - "helper 只负责入口无关的 advance 续驱与短路；入口私有的挂起 marker 映射（NodeResult/ToolResult）仍由各入口保留"
  - "clarifying 短路照搬 _maybe_suspend 的 answered_at__isnull=True query，保证澄清 HITL 行为等价"
  - "max_steps 默认 20，超限经 transition(fail, reason=advance_step_limit) 退出（防死循环 T-43-DOS-LOOP）"

patterns-established:
  - "共享续驱地基（contract-first）：本 plan 只建 helper + 单测，不接线、不改既有调用方"

requirements-completed: [RESUME-01]

# Metrics
duration: ~10min
completed: 2026-06-16
---

# Phase 43 Plan 02: 通用 resume 回流地基（共享续驱 helper）Summary

**入口无关的 `adrive_plan_session_to_pause_or_terminal(engine, session, *, max_steps=20)` 共享续驱 helper：advance PlanSession 至终态或重挂起短路点，clarifying-pending / researching-in-flight 双短路保护 HITL，step 上限经 transition(fail) fail-soft 退出，状态只经 session_service.transition。**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-06-16T10:18Z
- **Completed:** 2026-06-16T10:22Z
- **Tasks:** 2
- **Files modified:** 3（2 created, 1 modified）

## Accomplishments
- 抽出工作流节点（`plan_research.py:142-167`）与 chat 工具（`plan_research_tools.py:124-153`）两处逐行同构的 advance 循环为单一入口无关 helper，杜绝「两套续驱循环」。
- 双重重挂起短路：`CLARIFYING` 且有未答 `Clarification`（`answered_at` 为空）→ 立即返回（保护澄清 HITL，等价 `_maybe_suspend`）；`RESEARCHING` 且 `aall_research_tasks_terminal` 为 False → 立即返回（等容器回调）。
- `max_steps` 上限经 `engine.session_service.transition(session, "fail", error={"reason": "advance_step_limit"})` fail-soft 退出，防 engine 配置异常致死循环。
- 四路径单测全绿；barrel re-export 经 `services.plan_orchestration` 可导入、无 import 环。

## Task Commits

Each task was committed atomically:

1. **Task 1: 新建 resume.py 共享续驱 helper + barrel re-export** - `12d40e5f` (feat)
2. **Task 2: 新建 test_plan_resume_driver.py 四路径单测** - `94a74001` (test)

## Files Created/Modified
- `server/services/plan_orchestration/resume.py` - 新建共享续驱 helper（advance 循环 + clarifying/researching 短路 + step 上限 fail）
- `server/services/plan_orchestration/__init__.py` - barrel re-export `adrive_plan_session_to_pause_or_terminal`（加入 `__all__`）
- `server/tests/services/test_plan_resume_driver.py` - 5 个用例覆盖四条路径（终态含「已 DONE」与「advance 一步到 DONE」两例）

## Decisions Made
- helper 入口无关：engine 由调用方传入，不在 helper 内新建第二个 engine 工厂（对齐 `entrypoint.py`「驱动是入口私有」精神）。
- clarifying 短路 query 照搬节点/工具 `_maybe_suspend`（`answered_at__isnull=True`），保证澄清 HITL 行为等价——避免 helper 不短路时一路 advance 到 `max_steps` 被错误 FAILED（红线回归 `test_clarifying_suspends_waiting_event`）。
- 状态转移只经 `engine.session_service.transition`，helper 绝不直接写 `session.status`（INV-6 / engine 纯度）。
- 验证命令 `uv run python -c "..."` 需 Django 配置；以 `DJANGO_SETTINGS_MODULE=friday.settings` + `django.setup()` 运行确认导入成功（不算逻辑缺陷，仅 Django app 初始化前置）。

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- 回归套件 `tests/services/` 有 1 个预存失败 `test_dependency_cache.py::TestGetVolumeName::test_get_volume_name_format`，与 `plan_orchestration` 无关（Docker dependency-cache 卷名格式），非本 plan 改动引入。已记入 `deferred-items.md`，按执行器 scope boundary 不修复。本 plan 新增 5 个单测全绿，`tests/services/` 其余 619 passed / 1 skipped。

## Next Phase Readiness
- 共享 helper 地基就绪，43-03 可在 `subagent/api/callbacks.py` 接线 chat 入口续驱（`_schedule_chat_plan_resume` → `adrive_plan_session_to_pause_or_terminal`）。
- 43-04 可将既有 `plan_research.py` / `plan_research_tools.py` 的 advance 循环替换为本 helper（挂起 marker 映射保留，行为须等价）。
- 本 plan 未接线任何现有调用方（在 43-03/43-04 范围），无回归风险。

## Self-Check: PASSED

- FOUND: server/services/plan_orchestration/resume.py
- FOUND: server/tests/services/test_plan_resume_driver.py
- FOUND: .planning/phases/43-env-resume/43-02-SUMMARY.md
- FOUND commit: 12d40e5f (Task 1)
- FOUND commit: 94a74001 (Task 2)

---
*Phase: 43-env-resume*
*Completed: 2026-06-16*
