---
phase: 144-capture
plan: "03"
subsystem: api
tags: [django, mcp, branch-matching, capture]

requires:
  - phase: 144-01
    provides: 默认分支、Capture 写路径与 schema 的 RED 契约
provides:
  - 默认分支识别纯函数
  - lookup 第三源默认分支候选守卫
  - lookup binding_source 响应契约
affects: [144-04, 144-05, friday-dev]

tech-stack:
  added: []
  patterns: [弱仓关联证据在默认分支只返回候选, 显式绑定与 work item 保持优先]

key-files:
  created: []
  modified:
    - server/services/branch_parsing.py
    - server/mcp_tools/views.py
    - server/mcp_tools/serializers.py

key-decisions:
  - "main、master、develop 与仓库 default_branch 使用大小写敏感精确匹配。"
  - "默认分支上的 RepoAssociation 仅作为候选，不进入 merged，也不调用 pack_project_context。"

patterns-established:
  - "默认分支弱证据守卫：候选可见但不自动绑定项目或打包上下文。"

requirements-completed: [RECALL-04]

duration: 3min
completed: 2026-08-28
---

# Phase 144 Plan 03: 默认分支项目匹配防错 Summary

**默认分支上的唯一仓关联不再自动注入项目上下文，同时 Capture 仍保留真实仓库挂钩并正常接受。**

## Performance

- **Duration:** 3 min
- **Started:** 2026-08-28T12:00:56Z
- **Completed:** 2026-08-28T12:03:35Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- 新增 `is_default_branch` 纯函数，覆盖约定默认分支和仓库配置默认分支。
- lookup 第三源在默认分支仅返回仓关联候选，保持 `matched=false`、空上下文且不调用 packer。
- 保持显式 `ProjectBranch`、可解析 work item 与非默认人工分支的既有命中行为。
- 验证默认分支 Capture 写路径仍 `accepted=true`、保留仓库 FK 且不推断项目 FK。

## Task Commits

1. **Task 1: 增加 is_default_branch 并守卫 lookup 第三源** - `3f9ef4d46`（fix）
2. **Task 2: 锁定 Capture 写路径不因默认分支仓关联绑项目** - 无新增提交；复用 `950e6b19a` 已提交的 Wave 0 回归并完成验证。

## Files Created/Modified

- `server/services/branch_parsing.py` - 提供大小写敏感的默认分支判断。
- `server/mcp_tools/views.py` - 在 RepoAssociation 第三源进入上下文打包前执行默认分支守卫。
- `server/mcp_tools/serializers.py` - 将 `binding_source` 纳入 lookup 响应 snapshot。

## Decisions Made

- 默认分支守卫只约束 RepoAssociation 第三源，不能禁用 work item 或显式分支绑定。
- 跳过自动绑定时继续返回候选项目，并用 `repo_association_skipped_default_branch` 明确说明来源。

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- 共享 PostgreSQL 测试库正被并发计划占用，初次测试无法重建；改用独立 SQLite 测试数据库后完成全部目标回归。

## Known Stubs

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- RECALL-04 默认分支读写边界已冻结，可供后续会话检索与 Capture 回放计划复用。
- Plan 02 并发修改的 retrieval/packer 范围未触碰。

## Self-Check: PASSED

- `server/services/branch_parsing.py`、`server/mcp_tools/views.py`、`server/mcp_tools/serializers.py` 均存在。
- 任务提交 `3f9ef4d46` 存在。
- 目标回归 44 项通过，Ruff 检查通过。

---
*Phase: 144-capture*
*Completed: 2026-08-28*
