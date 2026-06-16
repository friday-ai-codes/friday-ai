---
phase: 43-env-resume
plan: 03
subsystem: subagent-callbacks
tags: [resume, plan-session, barrier, chat-entry, async-orm, fire-and-forget]

# Dependency graph
requires:
  - phase: 43-02 plan_orchestration resume helper
    provides: adrive_plan_session_to_pause_or_terminal（入口无关续驱 helper）
  - phase: 38-42 plan_orchestration
    provides: build_orchestration_engine, aall_research_tasks_terminal, BarrierManager.task_completed, BlockingTaskResult
provides:
  - "_schedule_chat_plan_resume：chat 入口 plan_research 全终态 → engine 续驱到 done + barrier 回灌（消化 D-2 a/b）"
  - "_schedule_agent_session_resume 的 plan_research 分支接线（委派到新函数，entrypoint==CHAT 守门）"
affects: [44 wave 调度（callback 驱动多 wave 的回流地基已就位）]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "fire-and-forget + 幂等 + fail-soft 续驱：mirror _schedule_workflow_resume 尾部 loop.create_task / asyncio.run 范式"
    - "barrier 回灌 task_id 用 str(plan_session.id)（chat barrier 注册键），而非 session.session_id（Pitfall 3）"
    - "T-43-TAMPER 守门：以服务端权威字段 PlanSession.entrypoint==CHAT 守门，不信 runner 可改字段"

key-files:
  created: []
  modified:
    - server/subagent/api/callbacks.py
    - server/tests/services/test_research_completion_callback.py

key-decisions:
  - "续驱与回灌严格按时序（同协程顺序，Pitfall 4）：先 adrive_plan_session_to_pause_or_terminal 续驱到终态，再用终态 status 构建 BlockingTaskResult 回灌 barrier"
  - "engine 由 build_orchestration_engine 单一工厂构造（无 node_execution_id，chat 入口），绝不新建第二个 engine 工厂"
  - "barrier 回灌 task_id=str(plan_session.id)；成功 output=current_plan_version 文本、失败 output=''（A2，复用 deep_analysis 回灌通道）"
  - "分支接线保持薄：守门在 _schedule_chat_plan_resume 内做（步骤 b），_schedule_agent_session_resume 分支仅判定 source==plan_research 即委派，不重复查询"
  - "Task 1 import 验证命令 uv run python -c 需 Django 配置；以 DJANGO_SETTINGS_MODULE=friday.settings + django.setup() 运行确认（沿用 43-02 处理，非逻辑缺陷）"

patterns-established:
  - "chat 入口 deep-research 容器在途完成 → callback 续驱 + barrier 回灌闭环（与工作流入口共享 43-02 同源 helper，不造两套）"

requirements-completed: [RESUME-01]

# Metrics
duration: ~12min
completed: 2026-06-16
---

# Phase 43 Plan 03: chat 入口 plan_research 续驱 + barrier 回灌接线 Summary

**新增 `_schedule_chat_plan_resume`（mirror `_schedule_workflow_resume`：fire-and-forget + 幂等 + fail-soft），把 `_schedule_agent_session_resume` 的 `plan_research` 分支当前的提前 `return` 改为「entrypoint==CHAT 守门 → 经 43-02 同源 helper 续驱 engine 到 done → BarrierManager.task_completed(str(plan_session.id)) 回灌主方案」，一举消化 v0.7 audit D-2 两处缺口（a: chat barrier 从不被通知；b: chat 入口此后无消费者驱动 engine.advance 到 done）。**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-06-16T18:30Z
- **Completed:** 2026-06-16T18:42Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- 新增 `_schedule_chat_plan_resume`：从 `session.last_output["plan_session_id"]` 取 `PlanSession` → `entrypoint==CHAT` 守门（T-43-TAMPER）→ `aall_research_tasks_terminal` 幂等短路 → `build_orchestration_engine()` 构造 chat 入口 engine → `adrive_plan_session_to_pause_or_terminal` 续驱到终态 → 构建 `BlockingTaskResult` → `get_barrier_manager().task_completed(str(plan_session.id), result)` 回灌。
- 接线 `_schedule_agent_session_resume` 的 `plan_research` 分支（`callbacks.py` 原 121-134）：由 `log.debug(...); return` 改为 `_schedule_chat_plan_resume(session, log)` 委派——`_handle_completed`（completed）与 `_handle_failed`（failed）两路天然覆盖；保留「绝不在此触发 SDKAgentRunner resume（幽灵 agent 风险）」语义。
- 续驱与回灌严格时序：**先**续驱到终态、**再**用终态 `status` 构建 `success=(status==DONE)` 的 result（Pitfall 4 同协程顺序）；barrier 回灌 `task_id` 用 `str(plan_session.id)` 而非 `session.session_id`（Pitfall 3，chat barrier 注册键）。
- fail-soft：整个 `_resume()` 协程独立 `try/except` swallow + `log.warning("chat_plan_resume_error")`，绝不让回调主流程 5xx；日志仅记 plan_session_id / status / barrier_satisfied 非敏感字段（T-43-INFO，对齐 `barrier_task_notified` 范式）。
- 扩展 `test_research_completion_callback.py`：新增 6 个集成用例覆盖闭环 / 回归 / 幂等 / fail-soft / 失败路径，全文件 14 passed，无回归。

## Task Commits

Each task was committed atomically:

1. **Task 1: 新增 _schedule_chat_plan_resume + 接线 plan_research 分支** - `989c80aa` (feat)
2. **Task 2: 扩展 test_research_completion_callback.py 闭环 + 回归 + 幂等 + fail-soft + 失败路径** - `8901c8d1` (test)

## Files Created/Modified
- `server/subagent/api/callbacks.py` - 新增 `_schedule_chat_plan_resume`（续驱 + barrier 回灌）；`_schedule_agent_session_resume` 的 plan_research 分支委派到新函数（+91/-1）。
- `server/tests/services/test_research_completion_callback.py` - 新增 6 个集成用例（+288/-2）：
  - `chat_resume_drives_to_done_and_notifies_barrier`：唯一调研完成 → 续驱 done + barrier 回灌（D-2 a/b 闭环）。
  - `workflow_entry_session_skips_chat_resume`：工作流入口（有 node_execution）不走 chat 续驱（回归守护）。
  - `chat_resume_guards_non_chat_entrypoint`：`entrypoint` 权威字段守门（T-43-TAMPER）。
  - `chat_resume_idempotent_when_research_in_flight`：多仓在途短路（幂等 no-op）。
  - `chat_resume_swallows_internal_error_returns_200`：续驱异常 fail-soft swallow。
  - `chat_resume_failed_research_notifies_barrier_success_false`：失败路径 barrier `success=False` 不卡死。

## Decisions Made
- engine 由 `build_orchestration_engine` 单一工厂构造（无 `node_execution_id` 即 chat 入口），绝不新建第二个 engine 工厂——对齐 `entrypoint.py`「底层 engine 复用、不造两套」精神。
- 续驱 → 回灌严格时序：先 `adrive_plan_session_to_pause_or_terminal` 续驱到终态，再用终态 `status` 构建 `BlockingTaskResult`（`success=(status==DONE)`，成功 `output=current_plan_version` 文本、失败 `output=""`，复用 deep_analysis 回灌通道）。
- barrier 回灌 `task_id=str(plan_session.id)`（chat barrier 注册键，见 `plan_research_tools.py:249`），barrier 自带去重（`task_id in results` → no-op），幂等安全。
- 分支接线保持薄：守门统一在 `_schedule_chat_plan_resume` 内（步骤 b），`_schedule_agent_session_resume` 分支仅判定 `source=="plan_research"` 即委派，避免重复查询。
- Task 1 `<automated>` 验证命令 `uv run python -c "..."` 需 Django 配置；以 `DJANGO_SETTINGS_MODULE=friday.settings` + `django.setup()` 运行确认导入成功（沿用 43-02 处理，仅 Django app 初始化前置，非逻辑缺陷）。

## Deviations from Plan

None - plan executed exactly as written.

## Threat Model Compliance
- **T-43-TAMPER**（Tampering / Elevation）：`_schedule_chat_plan_resume` 以服务端权威字段 `PlanSession.entrypoint == CHAT` 守门，绝不信 runner 可经 progress 篡改的字段；`workflow_entry_session_skips_chat_resume` + `chat_resume_guards_non_chat_entrypoint` 双守护。
- **T-43-DOS**（Denial of Service）：fire-and-forget + 独立 try/except swallow + warning，绝不让回调 5xx；barrier/transition 幂等去重防重放；`chat_resume_swallows_internal_error_returns_200` + `chat_resume_idempotent_when_research_in_flight` 守护。
- **T-43-INFO**（Information Disclosure）：续驱日志仅记 plan_session_id / status / barrier_satisfied 非敏感字段（对齐 `barrier_task_notified` 范式）。

## Verification Results
- ✅ Task 1 import：`DJANGO_SETTINGS_MODULE=friday.settings uv run python -c "import django; django.setup(); from subagent.api.callbacks import _schedule_chat_plan_resume"` → `import-ok`。
- ✅ Task 2 集成测试：`cd server && uv run pytest tests/services/test_research_completion_callback.py -x` → **14 passed**（新增 6 + 既有 8，无回归）。

## Next Phase Readiness
- chat / workflow 两入口 resume 回流通路均已闭环，共享 43-02 同源续驱 helper——callback 驱动多 wave 调度（wave N done → wave N+1）的回流地基就位，留 Phase 44。
- 43-04 可将既有 `plan_research.py` / `plan_research_tools.py` 的 advance 循环替换为本 helper（行为须等价）。

## Self-Check: PASSED

- FOUND: server/subagent/api/callbacks.py (`_schedule_chat_plan_resume` defined + 分支委派)
- FOUND: server/tests/services/test_research_completion_callback.py (6 新用例)
- FOUND: .planning/phases/43-env-resume/43-03-SUMMARY.md
- FOUND commit: 989c80aa (Task 1)
- FOUND commit: 8901c8d1 (Task 2)

---
*Phase: 43-env-resume*
*Completed: 2026-06-16*
