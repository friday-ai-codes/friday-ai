---
phase: 130-placement-units-wiring
plan: 03
subsystem: process_runtime
tags: [funnel, blueprint-route, repo-association, placements, int-01]

requires:
  - phase: 130-01
    provides: build_placement_units
  - phase: 130-02
    provides: place_units / hard_scope
  - phase: 129-shortlist-history-role-map
    provides: shortlist / role_map 漏斗中段
provides:
  - BlueprintRouteAdapter placements 接线
  - RepoAssociationService feature-list 漏斗 placements
  - stage_sandbox hard_scope 守卫
affects:
  - 131 GATE/REFL placements 消费
  - 132 高三提分回归

tech-stack:
  added: []
  patterns:
    - role_map 后 placement → place；三分量降为排序信号
    - placement 失败 fail-soft 保留 shortlist，不回退全库

key-files:
  created:
    - server/tests/services/process_runtime/test_funnel_placement.py
  modified:
    - server/services/process_runtime/blueprint_route.py
    - server/initiatives/services/repo_association_service.py
    - server/services/process_runtime/stage_sandbox.py

key-decisions:
  - "有 placements 时用其推导候选种子，跳过整篇唯一 V2 决策"
  - "Association 入围由 placements 决定，融合分仅排序"

patterns-established:
  - "summary.placements / placement_unit_count / hard_scope 载荷"
  - "sandbox 出口 hard_scope 二次守卫"

requirements-completed: [INT-01, UNIT-02, UNIT-03]

duration: 25min
completed: 2026-08-14
---

# Phase 130 Plan 03: 主路径接线 Summary

**蓝图路由与项目选仓主路径接入 placement units → place_units；三分量不再唯一决策**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-08-14T06:16:00Z
- **Completed:** 2026-08-14T06:24:00Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Adapter.route 在 role_map 后写入 placements / hard_scope
- RepoAssociation propose/refine 返回 placements；候选 ⊆ hard_scope
- 129 funnel shortlist/team_gate 不回归；V2 内核未改

## Task Commits

1. **Task 1: RED — 漏斗放置接线守卫测** - `eb08707f` (test)
2. **Task 2: GREEN — Adapter / Association / sandbox 接线** - `d7a59c35` (feat)

## Files Created/Modified

- `server/tests/services/process_runtime/test_funnel_placement.py` — INT-01 接线守卫
- `server/services/process_runtime/blueprint_route.py` — `_aapply_placement_funnel`
- `server/initiatives/services/repo_association_service.py` — 漏斗 placements
- `server/services/process_runtime/stage_sandbox.py` — hard_scope 守卫

## Decisions Made

- placement 产出非空候选时跳过整篇 V2 作为唯一决策源；空则 hard_scope 内 fail-soft 回退
- Association 合并时 placements 定入围、融合 score 定排序

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Association 融合排序回归**
- **Found during:** Task 2（`test_propose_fuses_charter_and_history_signals`）
- **Issue:** placements 按 primary 序覆盖候选后，三分量高分仓不再排第一
- **Fix:** 入围仍由 placements，合并后按 fusion `score` 降序
- **Files modified:** `repo_association_service.py`
- **Committed in:** `d7a59c35`

## Issues Encountered

None beyond the auto-fix above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 131 可消费 `placements` 做 GATE/REFL
- **未启动** Phase 131（`--no-transition`）
- 未改 `repo_router_v2.py`

## Self-Check: PASSED

- FOUND: `test_funnel_placement.py`, blueprint_route / association / stage_sandbox 改动
- FOUND: commits `eb08707f`, `d7a59c35`
- FOUND: `git show` 不含 `repo_router_v2.py`

---
*Phase: 130-placement-units-wiring*
*Completed: 2026-08-14*
