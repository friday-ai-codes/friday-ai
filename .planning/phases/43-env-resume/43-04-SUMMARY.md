---
phase: 43-env-resume
plan: 04
subsystem: plan_orchestration
tags: [resume, plan-session, engine-driver, dedup, hitl-clarification, truthful-copy]

# Dependency graph
requires:
  - phase: 43-02 plan_orchestration resume helper
    provides: adrive_plan_session_to_pause_or_terminal（入口无关续驱 helper）
  - phase: 43-03 chat 入口续驱 + barrier 回灌接线
    provides: chat 入口自动回流通路（占位文案如实更新的前置）
  - phase: 41-42 plan_research node/tool
    provides: AIPlanResearchNode.execute / start_plan_research 内联 advance 循环（被复用对象）
provides:
  - "工作流节点 plan_research advance 循环复用共享 helper（不再内联 while）"
  - "chat 工具 start_plan_research advance 循环复用同一共享 helper"
  - "start_plan_research 占位文案/description 如实更新为「调研完成后自动融合回流」"
affects: [44 wave 调度（三处续驱逻辑真正同源一份，多 wave 续驱地基收敛完成）]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "三处同源（节点/工具/回调消费者）复用 adrive_plan_session_to_pause_or_terminal，杜绝两套续驱循环"
    - "入口私有挂起 marker 映射保留：helper 短路返回后各入口再跑一次 _maybe_suspend（NodeResult/ToolResult）"
    - "文案如实表述（接通即更新）：43-03 已接通自动回流，去掉「尚未接入」否定表述"

key-files:
  created: []
  modified:
    - server/workflows/nodes/ai/plan_research.py
    - server/agents/tools/plan_research_tools.py

key-decisions:
  - "节点/工具均保留入口私有 _maybe_suspend(session) 调用——helper 短路返回后再判一次即得正确 waiting_event/挂起 marker，行为等价"
  - "step 上限 fail 完全交由 helper 内部处理（transition(fail) + 返回 FAILED session → _map_terminal 走 failed 分支），各入口不再内联 step 计数"
  - "execute 内不再需要 terminal 集合/PlanSession.aget，移除冗余 local import（PlanSessionStatus/PlanSession）"
  - "工具文案改肯定表述但只改文案，不动 marker/挂起协议（__blocking_task__ + register_blocking_task + CLARIFICATION_PENDING_MARKER 全保留）"

patterns-established:
  - "RESUME-01「不造两套」最终态：底层续驱 engine 逻辑同源一份，三入口复用"

requirements-completed: [RESUME-01]

# Metrics
duration: ~12min
completed: 2026-06-16
---

# Phase 43 Plan 04: RESUME-01「不造两套」收尾（advance 循环复用共享 helper）Summary

**把工作流节点（`plan_research.py`）与 chat 工具（`plan_research_tools.py`）两处逐行同构的内联 advance 循环，重构为复用 43-02 的共享 helper `adrive_plan_session_to_pause_or_terminal`——使节点 / 工具 / 43-03 回调消费者三处真正同源一份续驱逻辑；入口私有挂起 marker 映射（NodeResult / ToolResult via `_maybe_suspend`）各自保留，行为零回归；同步把 `start_plan_research` 占位文案 / 工具 description 由「自动回流尚未接入」如实更新为「调研完成后自动融合并返回 canonical 主方案」（43-03 已接通）。**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-06-16T10:46Z
- **Completed:** 2026-06-16T10:58Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- `AIPlanResearchNode.execute`：内联 `while session.status not in terminal` 循环（含 step 计数 / transition(fail) / 逐步 `_maybe_suspend`）替换为单次 `session = await adrive_plan_session_to_pause_or_terminal(engine, session, max_steps=_MAX_ADVANCE_STEPS)` + 一次 `_maybe_suspend(session)` + `_map_terminal(session)`。
- `start_plan_research`：同形替换内联循环为同一共享 helper 调用 + 一次 `_maybe_suspend(session, conversation_id)`（含 `register_blocking_task`）+ `_map_terminal(session)`。
- 行为等价保证：helper 在 clarifying-未答（`answered_at__isnull=True`）/ researching-在途（`aall_research_tasks_terminal` False）处短路返回 → 各入口再跑一次 `_maybe_suspend` 即得正确的 waiting_event（节点）/ 挂起 marker（工具）；终态直返 `_map_terminal`；step 上限由 helper 内部 `transition(fail)` 退出。
- 文案如实更新：工具 description（约 `:41`）与 `_maybe_suspend` researching 占位文案（约 `:262`）去掉「自动回流尚未接入 / 当前不会自动继续」否定表述，改为「调研完成后将自动融合并返回 canonical 主方案」肯定表述；仅改文案，挂起协议与 marker 不动。

## Task Commits

Each task was committed atomically:

1. **Task 1: 工作流节点 advance 循环复用共享 helper（行为零变更）** - `7b662428` (refactor)
2. **Task 2: chat 工具复用 helper + 占位文案/description 如实更新** - `76e1996f` (refactor)

## Files Created/Modified
- `server/workflows/nodes/ai/plan_research.py` - 节点 `execute` 复用共享 helper（-28/+21）；移除内联 while 循环 + 冗余 local import（PlanSession/PlanSessionStatus），保留 `_maybe_suspend` / `_map_terminal`。
- `server/agents/tools/plan_research_tools.py` - 工具 `start_plan_research` 复用共享 helper（-35/+24）；移除内联 while 循环 + 冗余 PlanSession import；description + researching 占位文案如实更新。

## Decisions Made
- 节点 / 工具均保留入口私有 `_maybe_suspend` 调用——helper 只负责入口无关续驱与短路，挂起 marker 映射（`NodeResult` waiting_event / `ToolResult` __blocking_task__）仍由各入口私有保留（对齐 `entrypoint.py`「驱动是入口私有」精神）。
- step 上限处理完全下沉到 helper（`transition(session, "fail", error={"reason": "advance_step_limit"})` 后返回 FAILED session），各入口不再内联 step 计数；终态 FAILED 经 `_map_terminal` 走 failed 分支，语义等价于原内联 break。
- `execute` 不再引用 terminal 集合 / `PlanSession.aget`，移除冗余 local import（`PlanSessionStatus` / `PlanSession`），保持最小残留。
- 工具文案改为肯定表述但严格只改文案——marker（`CLARIFICATION_PENDING_MARKER` / `__blocking_task__`）、`register_blocking_task` 注册、挂起协议字段全部保留不动。

## Deviations from Plan

None - plan executed exactly as written.

## Threat Model Compliance
- **T-43-REGRESS**（Tampering / state integrity）：helper 同时短路 clarifying-未答 + researching-在途，入口私有 `_maybe_suspend` marker 映射保留，status 仍只经 `session_service.transition`；既有节点/工具测试（含 `test_clarifying_suspends_waiting_event`）守护零回归——全绿。
- **T-43-MISLEAD**（Repudiation / UX，disposition=accept）：43-03 接通后文案如实更新为「调研完成后自动融合并返回 canonical 主方案」，消除「尚未接入」误导。

## Verification Results
- ✅ Task 1：`uv run pytest tests/workflows/test_plan_research_node.py -x` → **5 passed**（含 `test_clarifying_suspends_waiting_event`：clarifying-pending 仍返回 `waiting_event` / kind=clarification / `session.status==CLARIFYING`，不被 FAILED）。
- ✅ Task 2：`uv run pytest tests/agents/test_start_plan_research_tool.py -x` → **6 passed**（挂起/终态/fail-closed 行为零回归；既有用例无硬断言旧文案，无需改断言）。
- ✅ Plan verification：`uv run pytest tests/workflows/test_plan_research_node.py tests/agents/test_start_plan_research_tool.py` → **11 passed**。
- ✅ helper 消费者回归：`tests/services/test_plan_resume_driver.py`（5 passed）+ `tests/services/test_research_completion_callback.py`（14 passed）无回归。

## Next Phase Readiness
- RESUME-01「不造两套」收尾完成：节点 / 工具 / 回调消费者三处复用同一共享续驱 helper，底层续驱 engine 逻辑同源一份——Phase 44 callback 驱动多 wave 调度（wave N done → wave N+1）的续驱地基已收敛完成，无两套循环漂移风险。
- 工具文案如实反映自动回流已接入，对话发起编排不再误导用户。

## Self-Check: PASSED

- FOUND: server/workflows/nodes/ai/plan_research.py (复用 adrive_plan_session_to_pause_or_terminal)
- FOUND: server/agents/tools/plan_research_tools.py (复用 helper + 文案更新)
- FOUND: .planning/phases/43-env-resume/43-04-SUMMARY.md
- FOUND commit: 7b662428 (Task 1)
- FOUND commit: 76e1996f (Task 2)

---
*Phase: 43-env-resume*
*Completed: 2026-06-16*
