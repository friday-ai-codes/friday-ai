---
phase: 130-placement-units-wiring
plan: 02
subsystem: process_runtime
tags: [place-units, hard-scope, repo-router-v2, placement-defaults, unit-02, unit-03]

requires:
  - phase: 130-placement-units-wiring
    provides: PlacementUnit / build_placement_units
  - phase: 129-shortlist-history-role-map
    provides: role_map / placement_defaults / shortlist
provides:
  - place_units async 细落点
  - hard_scope 守卫与 UnitPlacement 契约
affects:
  - 130-03 Blueprint / Association 主路径接线
  - 131 GATE/REFL placements 消费

tech-stack:
  added: []
  patterns:
    - V2 只取分且 repository_ids=hard_scope
    - placement_defaults / forbidden 覆盖分数偏好

key-files:
  created:
    - server/services/process_runtime/place_units.py
    - server/tests/services/process_runtime/test_place_units.py
  modified: []

key-decisions:
  - "reuse host 仅从 role_map.practice_reuse_host ∩ team 解析，不硬编码 UUID"
  - "learning_state hint 时强制避开 app_shell primary（有替代仓时）"

patterns-established:
  - "UnitPlacement: primary_repo/supporting_repos/confidence/evidence/open_questions"
  - "resolve_hard_scope 可复用"

requirements-completed: [UNIT-02, UNIT-03]

duration: 15min
completed: 2026-08-14
---

# Phase 130 Plan 02: place_units 细落点 Summary

**`place_units` 在 shortlist∪reuse hosts 内产出可解释 primary/supporting，V2 调用硬限 hard_scope**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-08-14T06:12:00Z
- **Completed:** 2026-08-14T06:16:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- 单元级落点契约完整（confidence/evidence/open_questions）
- V2 `repository_ids` 硬限制可测；scope 外 primary 丢弃
- defaults/forbidden 生效

## Task Commits

1. **Task 1: RED — place_units 行为单测** - `4b79e4e4` (test)
2. **Task 2: GREEN — 实现 place_units** - `1c3a3378` (feat)

## Files Created/Modified

- `server/services/process_runtime/place_units.py` — 细落点与 hard_scope
- `server/tests/services/process_runtime/test_place_units.py` — UNIT-02/03（6 passed）

## Decisions Made

- 角色信号作 bump，非唯一决策；最终仍以 hard_scope 守卫为准
- 无 practice host 时不捏造 UUID，记 `missing_practice_reuse_host`

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- 可被 Plan 03 Adapter/Association 接线
- 未改 `repo_router_v2.py`

## Self-Check: PASSED

- FOUND: `server/services/process_runtime/place_units.py`
- FOUND: `server/tests/services/process_runtime/test_place_units.py`
- FOUND: commits `4b79e4e4`, `1c3a3378`

---
*Phase: 130-placement-units-wiring*
*Completed: 2026-08-14*
