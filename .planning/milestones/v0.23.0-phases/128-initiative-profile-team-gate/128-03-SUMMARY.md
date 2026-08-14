---
phase: 128-initiative-profile-team-gate
plan: 03
subsystem: process_runtime
tags: [funnel, team-gate, blueprint-route, mcp, repo-association]

requires:
  - phase: 128-01
    provides: build_profile / select_profile_corpus
  - phase: 128-02
    provides: resolve_team_core / apply_team_gate
provides:
  - BlueprintRouteAdapter 漏斗画像+团队硬门禁
  - RepoAssociationService clarify(empty_team_core) + 画像语料 query
  - arun_route_stage / MCP space_id|team_id|primary_team 门禁
  - filter_indexed_repository_ids（TEAM-03 全无索引）
affects:
  - Phase 129 shortlist / 历史先验

tech-stack:
  added: []
  patterns:
    - "漏斗路径 repository_ids=team_core；缺团队 clarify 不调全库 V2"
    - "裸 RepoRouterV2.grouping 仍 annotate-only"

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
  - "include_repository_ids 视为显式团队范围，可越过 missing_team 短路（sandbox stub 测）"
  - "MCP 增加 space_id/team_id/primary_team 入参"

patterns-established:
  - "三入口统一 clarify 载荷：status/clarify_reason/candidates=[]/offer"

requirements-completed: [PROF-01, PROF-02, PROF-03, TEAM-01, TEAM-02, TEAM-03]

duration: 40min
completed: 2026-08-14
---

# Phase 128 Plan 03 Summary

## What shipped
- Blueprint 路由：pin 后 → `build_profile` → `resolve_team_core` + 索引过滤 → clarify 短路或 `repository_ids=team_core` 再调 V2。
- RepoAssociation：空/无索引 Space → `status=clarify`；query 走 `select_profile_corpus`（剔除 acceptance）。
- MCP/sandbox：无团队 → `missing_team`；可传 space/team；offer.spaces 可枚举。
- 测试：`test_funnel_team_gate.py` + 既有 sandbox/association 回归。

## Verification
`uv run pytest` 相关 41 条全绿（见 VERIFICATION.md）。

## Deferred
shortlist / 角色图 / 放置单元 / 反思 / 高三回归 → 129–132。
