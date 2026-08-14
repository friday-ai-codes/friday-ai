---
phase: 129-shortlist-history-role-map
plan: 01
subsystem: process_runtime
tags: [shortlist, team_gate, routing, observability]

requires:
  - phase: 128-initiative-profile-team-gate
    provides: team_core 硬门禁与 InitiativeProfile
provides:
  - build_shortlist + ShortlistResult（可解释短名单）
  - force_include_ids 钩子供历史先验注入
affects:
  - 129-02 history prior
  - 129-04 Blueprint 漏斗接线

tech-stack:
  added: []
  patterns:
    - 信号注入 stub（activity/capability/charter）便于单测
    - force-include ∩ 宇宙且拒绝 out_of_team

key-files:
  created:
    - server/services/process_runtime/shortlist.py
    - server/tests/services/process_runtime/test_shortlist.py
  modified: []

key-decisions:
  - "三路信号等权合成进 breakdown"
  - "DEFAULT_TOP_N=10，force-include 可突破上界"
  - "禁止日志写入需求原文"

patterns-established:
  - "ShortlistResult dataclass + shortlist_started/completed/failed sampling 观测"

requirements-completed: [LIST-01, LIST-02, LIST-04]

duration: 12min
completed: 2026-08-14
---

# Phase 129 Plan 01: Shortlist 生成器 Summary

**在 team_core∪合法 adjacent 内合成 activity/capability/charter 短名单，planned 强制拉入且剔除 out_of_team。**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-08-14T05:50:26Z
- **Completed:** 2026-08-14T05:52:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- 可单测 `build_shortlist`：排序、breakdown、force_include 钩子
- LIST-02 planned charter 在能力粗分 0 时仍进短名单
- 观测 `shortlist_*` 仅记 count/duration，无需求原文

## Task Commits

1. **Task 1: RED — shortlist 行为单测** - `b53e78be` (test)
2. **Task 2: GREEN — 实现 build_shortlist** - `a588eb30` (feat)

## Files Created/Modified

- `server/services/process_runtime/shortlist.py` — build_shortlist + ShortlistResult
- `server/tests/services/process_runtime/test_shortlist.py` — LIST-01/02/04 单测

## Decisions Made

- 信号等权；宇宙外 force/planned 一律丢弃（T-129-02）
- 不改 RepoRouterV2；能力分可注入

## Deviations from Plan

None - plan executed exactly as written.

## Verification

`uv run pytest tests/services/process_runtime/test_shortlist.py -q` → 5 passed

## Self-Check: PASSED
