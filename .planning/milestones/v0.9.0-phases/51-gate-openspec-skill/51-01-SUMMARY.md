---
phase: 51-gate-openspec-skill
plan: 01
subsystem: delivery
tags: [openspec, sdd, gate, repo-coding-task, inv6, follow_openspec]

requires:
  - phase: 44-multi-repo-wave-coding
    provides: RepoCodingTask 模型 + RepoCodingTaskService 单一写入入口（follow_openspec v0.8 预留位）
  - phase: 48-repo-methodology
    provides: Repository.facets.methodology=="SDD" 标记
provides:
  - create_tasks_for_plan 按仓库 SDD 标记置位 follow_openspec（首次消费 v0.8 预留位）
  - mark_gate_blocked gate 拦截唯一写入入口（条件 pending→failed + 结构化 error）
affects: [51-02, 52-spec-pr-link]

tech-stack:
  added: []
  patterns:
    - "service 条件更新 + 影响行数判定幂等（镜像 mark_blocked）"
    - "follow_openspec 漂移回填合并到同一 save 的 update_fields"

key-files:
  created: []
  modified:
    - server/delivery/services/repo_coding_task_service.py
    - server/tests/delivery/test_repo_coding_task_service.py
    - server/tests/delivery/test_repo_coding_task_inv6_guard.py

key-decisions:
  - "facets 在 _create_tasks_sync 同步块内按标量查（async 安全，禁裸 lazy-FK）"
  - "mark_gate_blocked 逐字镜像 mark_blocked，仅 error payload 不同（reason+spec_status）"

patterns-established:
  - "gate 判定结果落库 + follow_openspec 标记来源收口唯一 service（INV-6）"

requirements-completed: [GATE-01]

duration: ~10min
completed: 2026-06-17
---

# Phase 51 Plan 01: gate service 底座 Summary

**RepoCodingTaskService 首次消费 follow_openspec（按 Repository.facets.methodology==SDD 置位 + 漂移回填）并新增 mark_gate_blocked gate 拦截唯一写入入口（条件 pending→failed + {reason, spec_status} 结构化诊断）**

## Performance

- **Duration:** ~10 min
- **Tasks:** 2 (TDD)
- **Files modified:** 3

## Accomplishments
- `create_tasks_for_plan`：SDD 仓 `follow_openspec=True`、非 SDD=False；已存在 task 的 wave/follow_openspec 漂移合并回填（幂等，相等不写）
- `mark_gate_blocked(task, reason, spec_status)`：仅 pending→failed + `error={reason, spec_status}`，非 pending / 重复 no-op
- INV-6 grep 守护补正向断言 `mark_gate_blocked` 经 service 定义

## Task Commits

1. **Task 1: create_tasks_for_plan 置位 follow_openspec** - `73fedef1b` (feat, TDD: RED→GREEN)
2. **Task 2: 新增 mark_gate_blocked** - `827c30701` (feat, TDD: RED→GREEN)

## Files Created/Modified
- `server/delivery/services/repo_coding_task_service.py` - follow_openspec 置位/漂移回填 + mark_gate_blocked
- `server/tests/delivery/test_repo_coding_task_service.py` - follow_openspec 三组断言 + mark_gate_blocked 条件更新/幂等
- `server/tests/delivery/test_repo_coding_task_inv6_guard.py` - 正向断言 mark_gate_blocked 经 service

## Decisions Made
None - followed plan as specified.

## Deviations from Plan
None - plan executed exactly as written.

## Issues Encountered
None.

## Next Phase Readiness
- 51-02 可消费 `mark_gate_blocked` 作为 gate 拦截唯一写入入口；`follow_openspec` 已可按仓读取。

---
*Phase: 51-gate-openspec-skill*
*Completed: 2026-06-17*
