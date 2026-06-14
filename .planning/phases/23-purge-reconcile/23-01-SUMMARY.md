---
phase: 23-purge-reconcile
plan: 01
subsystem: infra
tags: [purge, qdrant, overlay, chunk-registry, codegraph, file-index, indexer, async-orm]

# Dependency graph
requires:
  - phase: 22-fail-closed
    provides: services/exclusion.py 排除判定单一源（后续排除/敏感清理复用 purge_file）
provides:
  - 统一文件删除入口 purge_file(repository_id, rel_path) + PurgeResult（services/purge.py）
  - Qdrant 主+overlay / FileIndex / ChunkRegistry(+ChunkEdge) / codegraph 五面一次删净，幂等
  - PF-03 收口：run_incremental_index / run_git_diff_index 删除路径收敛到 purge_file
  - PF-05 收口：overlay collection 随 file_path 删除（枚举 RepositoryBranchIndex.collection_name）
affects: [23-02-purge-modes, 23-03-reconcile, 23-04-purge-api, sensitive-cleanup]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "单一删除入口：三条索引删除路径 + 未来排除/敏感清理共用 purge_file"
    - "best-effort 逐面隔离：单面失败记 PurgeResult.failures，不阻断其余面（T-23-04）"
    - "ChunkRegistry 删除走 queryset.adelete() 触发 pre_delete 信号联动清边（不绕过信号）"

key-files:
  created:
    - server/services/purge.py
    - server/tests/services/test_purge_file.py
  modified:
    - server/services/indexer.py

key-decisions:
  - "purge_file 落点为新建 services/purge.py（而非并入 indexer.py），避免循环依赖且供清理面共用"
  - "codegraph 按 base(\"\") + 各 feature 分支逐分支 adelete_for_files；保留 indexer 既有归一化孤儿清理块（幂等不冲突）"
  - "overlay 枚举走 RepositoryBranchIndex 非空 collection_name；codegraph 分支枚举 base 恒归一为 \"\""

patterns-established:
  - "PurgeResult 暴露各面计数/失败标记，调用方据 result.ok 判定是否全净，不静默假装"
  - "Qdrant 同步客户端调用经 sync_to_async 包裹，ORM 访问经 sync_to_async（async 约束）"

requirements-completed: [EXCL-04]

# Metrics
duration: ~30min
completed: 2026-06-14
---

# Phase 23 Plan 01: 统一删除入口 purge_file Summary

**统一文件删除入口 purge_file 一次删净 Qdrant 主+overlay / FileIndex / ChunkRegistry(+ChunkEdge) / codegraph 五面，三条索引删除路径收敛收口 PF-03 + PF-05，删后无残留 + 幂等有守护测试证明。**

## Performance

- **Duration:** ~30 min
- **Completed:** 2026-06-14
- **Tasks:** 2
- **Files modified:** 3（2 created + 1 modified）

## Accomplishments
- 新建 `services/purge.py`：`purge_file(repository_id, rel_path) -> PurgeResult`，覆盖五个派生数据面，幂等、best-effort 逐面隔离。
- PF-05 收口：枚举该 repo 所有非空 `RepositoryBranchIndex.collection_name`，对每个 overlay collection 按 `file_path` 删点。
- PF-03 收口：`run_incremental_index` 与 `run_git_diff_index` 的 `DiffAction.DELETE` 分支统一改调 `purge_file`，消除增量路径「只删 Qdrant 不删 FileIndex/ChunkRegistry」的孤儿残留；移除增量路径冗余 FileIndex 删除循环。
- ChunkRegistry 删除经 queryset `.adelete()` 逐实例触发既有 `pre_delete` 信号，联动清掉指向被删 chunk 的 ChunkEdge。
- 守护测试：删后五面（含 overlay + ChunkEdge + codegraph base/feature）无残留 + 幂等（二次 purge 计数归 0）+ 从未索引文件不抛异常 + 增量删除路径收敛断言。

## Task Commits

1. **Task 1 (RED): 失败守护测试** - `6b481a8cf` (test)
2. **Task 1 (GREEN): 实现 purge_file 统一删除入口** - `d6ccf931b` (feat)
3. **Task 2: 索引删除路径收敛 purge_file + 收敛守护测试** - `972b720d5` (feat)

_TDD：Task 1 先 RED（test）后 GREEN（feat）；Task 2 收敛 indexer 并补收敛测试。_

## Files Created/Modified
- `server/services/purge.py` - 统一删除入口 `purge_file` + `PurgeResult` + `_overlay_collection_names` / `_branch_names` 辅助。
- `server/tests/services/test_purge_file.py` - 删后五面无残留 / 幂等 / 未索引文件 / 增量删除路径收敛守护测试。
- `server/services/indexer.py` - 两条删除路径（git_diff + incremental）DELETE 分支收敛到 `purge_file`；移除增量冗余 FileIndex 删除循环；codegraph 归一化孤儿清理块保留（注释标注幂等）。

## Decisions Made
- `purge_file` 落点为新建 `services/purge.py`，而非并入 `indexer.py`（D-01 赋予的 Claude 自由度），供索引删除与后续清理面共用、避免循环依赖。
- codegraph 删除在 `purge_file` 内对 base(`""`) + 各已索引 feature 分支逐分支 `adelete_for_files`；indexer 内既有按 `_write_branch` 精确单分支的归一化孤儿清理块保留不动（重复 adelete 为 no-op，二者幂等不冲突），以免破坏分支归一化语义。

## Deviations from Plan
None - plan executed exactly as written.

## Issues Encountered
None. 本计划在前序会话已完成 Task 1（含 RED/GREEN 提交）与 Task 2 的 `indexer.py` 收敛代码（未提交）；本次执行验证测试全绿（10 passed）、ruff 干净、`grep -c purge_file`（非注释）= 3 ≥ 2，随后将 Task 2 收敛改动原子提交。

## Next Phase Readiness
- `purge_file` 作为「删后无残留」单一可验证入口已就绪，供 23-02（普通/敏感两模式清理）、23-03（对账）、23-04（清理 API）复用。
- 无外部服务配置需求。

## Self-Check: PASSED

- FOUND: server/services/purge.py
- FOUND: server/tests/services/test_purge_file.py
- FOUND: server/services/indexer.py
- FOUND: .planning/phases/23-purge-reconcile/23-01-SUMMARY.md
- FOUND commits: 6b481a8cf (test), d6ccf931b (feat), 972b720d5 (feat)
- Tests: 10 passed (test_purge_file.py + test_indexer_exclusion.py); ruff clean; `grep -c purge_file`(非注释)=3 ≥ 2

---
*Phase: 23-purge-reconcile*
*Completed: 2026-06-14*
