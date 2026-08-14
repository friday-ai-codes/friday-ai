---
phase: 129-shortlist-history-role-map
plan: 04
subsystem: process_runtime
tags: [funnel, shortlist, role_map, blueprint_route, observability]

requires:
  - phase: 129-01
    provides: build_shortlist
  - phase: 129-02
    provides: asplit_history_priors
  - phase: 129-03
    provides: build_role_map
provides:
  - Blueprint 漏斗中段 shortlist+role_map 接线
  - RepoAssociation shortlist 收窄
affects:
  - 130 放置单元（消费 placement_defaults / role_map）

tech-stack:
  added: []
  patterns:
    - team_gate → history_prior → shortlist → role_map → V2/融合 ⊆ shortlist
    - role_map clarify 提前返回空候选

key-files:
  created:
    - server/tests/services/process_runtime/test_funnel_shortlist.py
  modified:
    - server/services/process_runtime/blueprint_route.py
    - server/initiatives/services/repo_association_service.py

key-decisions:
  - "V2 仅在 shortlist ids 上细排；信号阶段 use_llm=False 粗分"
  - "association 只做 shortlist 收窄，不写满 role_map（discretion）"
  - "stage_sandbox 经 Adapter 自动获得中段能力"

patterns-established:
  - "_aapply_shortlist_role_map 中段编排可单测注入"

requirements-completed: [LIST-01, LIST-02, LIST-03, LIST-04, ROLE-01, ROLE-02, ROLE-03]

duration: 15min
completed: 2026-08-14
---

# Phase 129 Plan 04: 漏斗接线 Summary

**Blueprint 主路径接入 shortlist+角色图；融合候选硬限制在 shortlist；RepoAssociation 收窄；未改 V2。**

## Performance

- **Duration:** ~15 min
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Adapter 返回 `shortlist` / `role_map` / `placement_defaults`
- `unmapped_role` clarify 不塞全库候选
- Phase 128 funnel_team_gate 5 测不回归；本 plan 4 测 + Wave1 14 测全绿（共 23）

## Task Commits

1. **Task 1: RED** - `d4a0c30d` (test)
2. **Task 2: GREEN** - `ef9445d2` (feat)

## Deviations from Plan

- **[Rule 3]** `stage_sandbox.py` 未单独改：MCP 已走 `BlueprintRouteAdapter.route`，中段能力自动生效。
- association 仅 shortlist 收窄（计划 discretion：Blueprint 写满 role_map）。

## Verification

`test_funnel_shortlist` + `test_funnel_team_gate` + Wave1 模块测 → 23 passed

## Self-Check: PASSED
