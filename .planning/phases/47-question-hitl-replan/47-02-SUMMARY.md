---
phase: 47-question-hitl-replan
plan: 02
subsystem: server
tags: [hitl, question, routing, wave-resume, no-replan, reuse-first, fail-soft]

# Dependency graph
requires:
  - phase: 43-env-resume
    provides: "_schedule_workflow_resume + _resolve_notification_chat_id（双路由 chat_id 解析）"
  - phase: 44-repocodingtask
    provides: "aadvance_coding_waves（RUNNING 视为在途 waiting，回填→阻断→决策）"
provides:
  - "send_question_card_enhanced 经 _resolve_notification_chat_id 解析 chat_id（main_session + node_execution 双路由，async 安全）"
  - "HITL 服务端守护测试：路由 / e2e（waiting→answer→resume）/ no-replan guard"
affects: [coding-hitl]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "复用既有 _resolve_notification_chat_id 统一解析 question 卡片 chat_id，消除直接 session.main_session 的 async lazy-FK 风险"
    - "遇阻续跑只走 Phase 43/44：等待期容器 RUNNING → aadvance waiting，回答 completed → 既有 resume 推进，无新 resume 通路"

key-files:
  created:
    - server/tests/test_coding_question_hitl.py
  modified:
    - server/subagent/question_handler.py

key-decisions:
  - "send_question_card_enhanced 改为统一委派 _resolve_notification_chat_id（而非新增分支）——既零回归 chat 路径（仍优先 main_session.metadata.chat_id），又补 node_execution fallback，且修复原 async 裸访问 lazy-FK 的 SynchronousOnlyOperation 风险"
  - "唯一生产改动在 server——question 接收/回答回灌/resume 全部既有可复用，本 plan 仅补卡片路由 + 以测试坐实既有 resume 通路正确承接 HITL"
  - "no-replan 守护用 spy 断言 research 聚合入口零调用，证明编码遇阻只抛人不重规划"

patterns-established:
  - "wave 编码遇阻 question → 容器 RUNNING 保活 → aadvance waiting（不 dead-end）→ 回答后既有 wave 推进续跑"

requirements-completed: [HITL-01]

# Metrics
duration: 10min
completed: 2026-06-17
---

# Phase 47 Plan 02: server 侧 wave question 路由 + HITL resume 守护 Summary

**server 侧 question 接收/回答回灌/resume 全部既有可复用——唯一缺口是 `send_question_card_enhanced` 只认 `main_session.metadata.chat_id`，wave 编码任务（node_execution）取不到 chat_id 不发卡。改为统一经 `_resolve_notification_chat_id` 解析（既零回归 chat 路径、又 fallback node 级 chat_id、并修复原直接访问 `session.main_session` 的 async lazy-FK 风险），并以测试坐实「遇阻 RUNNING → aadvance waiting（不 dead-end）→ 回答 completed → Phase 44 推进」与「no-replan 守护」。**

## Performance
- **Duration:** ~10 min
- **Completed:** 2026-06-17
- **Tasks:** 2
- **Files:** 1 created, 1 modified

## Accomplishments
- `send_question_card_enhanced`：删除直接 `session.main_session` 访问（async lazy-FK 风险），统一 `chat_id = await _resolve_notification_chat_id(session)`（lazy import 防环）——main_session.metadata.chat_id 优先（行为等价既有），fallback node_execution.node.config.chat_id；缺失仍 `log.warning + return None` fail-soft。
- 新建 `test_coding_question_hitl.py`（9 测）：
  - 路由：node_execution chat_id fallback 生效 / 缺 chat_id fail-soft / main_session chat_id 零回归。
  - e2e：遇阻 A RUNNING + pending_question → `aadvance_coding_waves` 返回 `{"waiting": True}`（A 未失败、下游 B 未阻断/派发，不 dead-end）；回答后 A `COMPLETED`+TaskResult → 再 aadvance 回填 A done 并 `dispatch` B（wave1）。
  - no-replan 守护：spy `amaybe_complete_research`，HITL 全流程零调用。
- 9/9 新测 + 既有 question_loop_integration 3/3 + test_coding_wave 7/7 + 飞书 question 卡片/回调 20/20 全绿；ruff line 100 通过。

## Task Commits
1. **Plan 02（server 侧路由 + 测试）** - `a4da9f81` (feat)

## Files Created/Modified
- `server/tests/test_coding_question_hitl.py` - HITL 服务端守护测试（新）
- `server/subagent/question_handler.py` - chat_id 解析统一委派 _resolve_notification_chat_id

## Decisions Made
- 委派既有 `_resolve_notification_chat_id` 而非新增分支：reuse-first + 修复 async lazy-FK 风险 + 零回归。
- 续跑零新通路：仅靠等待期 RUNNING 保活让既有 Phase 43/44 通路天然承接。
- no-replan 守护以 spy 断言坐实非目标。

## Deviations from Plan
- 计划原拟「保留 main_session 第一分支 + fallback」，实施时发现该直接访问在 async 下有 SynchronousOnlyOperation 风险（且 main_session_id NOT NULL），改为整体委派 `_resolve_notification_chat_id`——行为等价、更安全、更少代码（仍属最小 diff 与 reuse-first 方向）。

## Issues Encountered
- 初版测试漏建 main_session（SubAgentSession.main_session NOT NULL）→ 补 `_make_main_session` helper 后全绿。

## User Setup Required
None.

## Next Phase Readiness
- HITL-01 全链路（task 发起 + server 路由 + 既有 resume 续跑 + no-replan 守护）就绪，v0.8.0 末 phase 完成。
- 真实 runner + Docker 容器端到端 HITL 验收仍 deferred（本地无法闭环）。

## Self-Check: PASSED
- FOUND: server/subagent/question_handler.py（`_resolve_notification_chat_id`）
- FOUND: server/tests/test_coding_question_hitl.py
- FOUND commit: a4da9f81 (feat)
- TESTS: 9/9 + 既有 question/wave 回归全绿

---
*Phase: 47-question-hitl-replan*
*Completed: 2026-06-17*
