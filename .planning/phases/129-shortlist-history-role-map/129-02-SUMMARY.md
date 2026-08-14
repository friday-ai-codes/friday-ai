---
phase: 129-shortlist-history-role-map
plan: 02
subsystem: process_runtime
tags: [history_prior, shortlist, retrieval, observability]

requires:
  - phase: 112
    provides: ascore_history_match / delivery knowledge 检索
provides:
  - asplit_history_priors（demand/launch 分桶 + force_include ∩ team_core）
affects:
  - 129-04 Blueprint shortlist force-include 接线

tech-stack:
  added: []
  patterns:
    - 可注入 _aretrieve_history_hits 便于单测
    - HISTORY_FORCE_SCORE_THRESHOLD 模块顶常数

key-files:
  created:
    - server/services/process_runtime/history_prior.py
    - server/tests/services/process_runtime/test_history_prior.py
  modified: []

key-decisions:
  - "demand=tech_plan；launch=document|code_change"
  - "force_include 严格 ∩ team_core（剔除 out_of_team）"
  - "无 actor/检索失败 fail-soft，不阻断 shortlist"

patterns-established:
  - "HistoryPriorResult + history_prior_* sampling 事件"

requirements-completed: [LIST-03]

duration: 10min
completed: 2026-08-14
---

# Phase 129 Plan 02: 历史先验分桶 Summary

**需求史/上线史分桶后与 team_core 求交，产出 shortlist 可消费的 force-include。**

## Performance

- **Duration:** ~10 min
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- `asplit_history_priors` 分桶 + reasons（history_demand|history_launch）
- fail-soft：no_acting_user / retrieval_error
- 既有 blueprint_route_breakdown 50 用例不回归

## Task Commits

1. **Task 1: RED** - `6793aa3e` (test)
2. **Task 2: GREEN** - `14766002` (feat)

## Files Created/Modified

- `server/services/process_runtime/history_prior.py`
- `server/tests/services/process_runtime/test_history_prior.py`

## Deviations from Plan

None — `blueprint_route_history.py` 无需改动即可复用边归因与 kinds；新模块薄封装。

## Verification

`test_history_prior.py` + `test_blueprint_route_breakdown.py` → 53 passed

## Self-Check: PASSED
