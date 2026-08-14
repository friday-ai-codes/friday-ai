---
phase: 128-initiative-profile-team-gate
plan: 03
subsystem: process_runtime
tags: [funnel, team-gate, blueprint, mcp, d1, d3]

requires:
  - phase: 128-01
    provides: build_profile / InitiativeProfile
  - phase: 128-02
    provides: resolve_team_core / apply_team_gate
provides:
  - BlueprintRouteAdapter 漏斗 hard gate
  - RepoAssociationService 画像 corpus query + empty clarify
  - MCP arun_route_stage missing_team clarify + space/team 入参
affects:
  - 129 shortlist / 角色图
  - 132 高三提分回归

tech-stack:
  added: []
  patterns:
    - "漏斗路径 repository_ids=team_core∩indexed；clarify 载荷 additive"
    - "裸 RepoRouterV2.route 保持 annotate-only 兼容"

key-files:
  created:
    - server/tests/services/process_runtime/test_funnel_team_gate.py
  modified:
    - server/services/process_runtime/blueprint_route.py
    - server/services/process_runtime/stage_sandbox.py
    - server/services/process_runtime/team_gate.py
    - server/initiatives/services/repo_association_service.py
    - server/mcp_tools/views.py
    - server/mcp_tools/serializers.py
    - server/tests/services/process_runtime/test_stage_sandbox.py
    - server/tests/initiatives/test_repo_association_service.py

key-decisions:
  - "门禁在 Blueprint/MCP/RepoAssociation 漏斗层，不改 V2 内核"
  - "挂载仓经 index_status=indexed 过滤；全无索引 → empty_team_core"

patterns-established:
  - "routing 摘要 additive：status/clarify_reason/team_core/profile"

requirements-completed: [PROF-01, PROF-02, PROF-03, TEAM-01, TEAM-02, TEAM-03]

duration: 45min
completed: 2026-08-14
---

# Phase 128 Plan 03: 漏斗三入口接线 Summary

**Blueprint / RepoAssociation / MCP 漏斗路径具备画像+团队硬门禁；无团队 clarify，禁止静默全库 primary（D1/D3）。**

## Performance

- **Duration:** ~45min
- **Started:** 2026-08-14T04:52:00Z
- **Completed:** 2026-08-14T05:40:00Z
- **Tasks:** 3/3
- **Files modified:** 9

## Accomplishments

- `BlueprintRouteAdapter.route`：pin 后画像+gate；clarify 短路；ok 时 `repository_ids=team_core`
- `RepoAssociationService`：corpus 拼 query；空 Space / 无索引 → `status=clarify`
- `arun_route_stage` + MCP：无团队 clarify（可带 `offer.spaces`）；支持 `space_id`/`team_id`/`primary_team`

## Task Commits

1. **Task 1–3 RED:** `33063f5a` — test(128-03): 添加漏斗三入口团队门禁用例
2. **Task 1–3 GREEN:** `6e6a455e` — feat(128-03): 漏斗三入口接线画像与团队硬门禁

## Files Created/Modified

- `blueprint_route.py` / `stage_sandbox.py` / `repo_association_service.py` — 漏斗接线
- `team_gate.py` — `filter_indexed_repository_ids`
- `mcp_tools/views.py` + `serializers.py` — 团队入参
- `test_funnel_team_gate.py` — 集成守卫

## Decisions Made

- 不重写 RepoRouterV2；grouping 仍 annotate-only
- 画像 degrade 不阻断门禁；门禁 clarify 优先于噪声路由

## Deviations from Plan

**1. [Rule 2 - Missing critical] sandbox stub 测试需显式 include**
- **Found during:** Task 2 回归
- **Issue:** 无团队提前 clarify 使 stub session 测试拿不到 adapter 调用
- **Fix:** 测试补 `include_repository_ids` 越过 missing_team，专注 created_by
- **Commit:** `33063f5a`

## Verification

```text
# 21 passed（画像/门禁/漏斗单测）
uv run pytest tests/services/process_runtime/test_{funnel_team_gate,initiative_profile,team_gate}.py -q

# 16 passed（association + sandbox route；--create-db）
uv run pytest tests/initiatives/test_repo_association_service.py \
  tests/services/process_runtime/test_stage_sandbox.py -k 'not research and not spec_stage' -q --create-db
```

## Self-Check: PASSED

- FOUND: `test_funnel_team_gate.py`, `33063f5a`, `6e6a455e`
