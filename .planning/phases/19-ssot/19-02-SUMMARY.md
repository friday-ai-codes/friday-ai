---
phase: 19-ssot
plan: 02
subsystem: database
tags: [django-migration, workflows, data-migration, idempotent, node-type]

# Dependency graph
requires:
  - phase: 19-ssot
    provides: 前端幽灵节点 fetch_project_info 收敛为真实节点 fetch_space_info（D-03）
provides:
  - 幂等数据迁移 0026：存量 WorkflowNode.node_type='fetch_project_info' → 'fetch_space_info'
affects: [workflows, node-registry, workflow-loading]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "RunPython 数据迁移 + RunPython.noop reverse（analog 0010_rename_node_types）"
    - "filter().update() 实现幂等批量重命名（0 行无副作用，可重入）"

key-files:
  created:
    - server/workflows/migrations/0026_rename_fetch_project_info_nodes.py
  modified: []

key-decisions:
  - "采用 filter+update 而非逐行 save：单条 UPDATE、0 行无副作用、天然幂等"
  - "reverse=noop：避免误回滚把已对齐数据破坏（T-19-03 缓解）"
  - "仅改 node_type 字符串，不触碰 edge/handle/config，保证句柄不变"

patterns-established:
  - "幽灵节点改名在数据态闭环：前端收敛 + 后端幂等迁移成对落地"

requirements-completed: [SSOT-01]

# Metrics
duration: 4min
completed: 2026-06-13
---

# Phase 19 Plan 02: 幽灵节点存量数据幂等迁移 Summary

**幂等 Django 数据迁移 0026，把存量 `WorkflowNode.node_type='fetch_project_info'` 重写为真实节点 `fetch_space_info`，使老工作流收敛后仍能正确解析（D-03）。**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-06-13T09:42:55Z
- **Completed:** 2026-06-13T09:44:30Z
- **Tasks:** 1
- **Files modified:** 1 (created)

## Accomplishments
- 核查当前开发 DB 存量：`node_type='fetch_project_info'` 计数为 **0**（本机无幽灵节点，但迁移仍为其它部署兜底）
- 新增 `0026_rename_fetch_project_info_nodes.py`，仿 `0010_rename_node_types.py` 范式，`dependencies` 指向最新迁移 `0025_alert_rules`
- forward 用 `filter(node_type='fetch_project_info').update(node_type='fetch_space_info')`，reverse 为 `RunPython.noop`
- 验证幂等：首次 `migrate` 应用 OK，再次 `migrate` 报 "No migrations to apply"；迁移后存量计数仍为 0
- `makemigrations workflows --check` 干净（无 schema 漂移）；`migrate --plan` 正确列出 0026

## Task Commits

Each task was committed atomically:

1. **Task 1: 核查存量 + 幂等数据迁移 0026** - `68b35264e` (feat)

## Files Created/Modified
- `server/workflows/migrations/0026_rename_fetch_project_info_nodes.py` - 幂等幽灵节点数据迁移，含中文注释说明 D-03 对齐与幂等/noop 设计

## Decisions Made
- 用 `filter().update()` 而非逐行 `save()`：单条 UPDATE 高效、命中 0 行无副作用、天然可重入。
- `reverse=migrations.RunPython.noop`：迁移本质是数据对齐，回滚无意义且回滚成旧字符串会重新制造幽灵节点（缓解 T-19-03 数据完整性威胁）。
- 仅改 `node_type` 字符串，不触碰 edge/handle/config，保证图结构与句柄不变。

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None. 计划内的全部 verify 与 acceptance criteria 一次性通过。

## Known Stubs
None.

## User Setup Required
None - no external service configuration required. 部署升级时随常规 `manage.py migrate` 自动应用。

## Verification Evidence
- `makemigrations workflows --check --dry-run` → "No changes detected in app 'workflows'"（exit 0）
- `migrate workflows --plan` → 含 `workflows.0026_rename_fetch_project_info_nodes`
- `migrate workflows` → "Applying workflows.0026_rename_fetch_project_info_nodes... OK"
- 再次 `migrate workflows` → "No migrations to apply."（幂等）
- 迁移后 `WorkflowNode.objects.filter(node_type='fetch_project_info').count()` == 0
- `rg "fetch_project_info|fetch_space_info|RunPython.noop" 0026...py` → 三者全部命中

## Next Phase Readiness
- 幽灵节点改名在数据态闭环；老工作流打开后该节点不再退化为 fallback baseNode。
- 无阻塞项。

---
*Phase: 19-ssot*
*Completed: 2026-06-13*

## Self-Check: PASSED
- FOUND: server/workflows/migrations/0026_rename_fetch_project_info_nodes.py
- FOUND commit: 68b35264e
