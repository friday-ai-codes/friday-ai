---
phase: 99-association-visualization-crosslink
plan: 01
subsystem: initiatives.galaxy
tags: [KDEP-10, galaxy, artifact, visualization, read-only]
requires: [98-03 ArtifactAssociationService]
provides:
  - "_build_project_galaxy artifact/capability 节点 + HAS_ARTIFACT/ARTIFACT_REPO/ARTIFACT_CAPABILITY 边"
  - "verified RepoAssociation → project→repo USES_REPO 边（去重）"
  - "ProjectGalaxyView 异步聚合工件关联 + artifact 计数观测"
affects: [99-04 galaxy 前端渲染]
tech-stack:
  patterns: [best-effort fail-soft, sync_to_async, max_nodes 预算截断, edge dedup]
key-files:
  modified:
    - server/initiatives/views.py
  created:
    - server/tests/initiatives/test_project_galaxy_artifacts.py
decisions:
  - "关联图遍历不在 sync builder 内重复实现：由 _agather_artifact_assocs 异步经 Phase 98 服务预取后传入"
  - "USES_REPO 引入 (source,target,relation) 去重集，MR 来源与 verified RepoAssociation 来源统一去重"
  - "meta.artifact_nodes/artifact_edges 从截断后的最终列表计算，反映实际返回"
metrics:
  duration_min: 20
  completed: 2026-07-01
---

# Phase 99 Plan 01: 星图纳入 artifact 节点/边 Summary

把 Phase 98 的工件↔仓库/能力关联可视化进项目关系星图：`_build_project_galaxy` 新增 `artifact`/`capability` 节点与 `HAS_ARTIFACT`/`ARTIFACT_REPO`/`ARTIFACT_CAPABILITY` 边，项目↔仓库来源并入 verified `RepoAssociation`（不再仅 MR），关联图遍历复用 Phase 98 `ArtifactAssociationService`（不重复遍历），全程 best-effort 绝不反噬既有星图。

## Tasks

1. **`_build_project_galaxy` 扩展**（`server/initiatives/views.py`）：签名加 `*, artifact_assocs=None`；引入 `add_edge` + `edge_seen` 去重；artifact 分支整体 `try/except`（best-effort），逐工件建 `artifact:{id}` 节点 + `HAS_ARTIFACT`，按 `artifact_assocs` 建 `ARTIFACT_REPO`/`ARTIFACT_CAPABILITY`（capability label 取路径末段）；verified `RepoAssociation` 建 project→repo `USES_REPO`（与 MR 来源统一去重）；`meta` 增 `artifact_nodes`/`artifact_edges`；max_nodes 截断天然纳入 artifact 节点。
2. **`ProjectGalaxyView` + `_agather_artifact_assocs`**：模块级 async helper 逐工件调 `get_artifact_associations(aid, user=...)`（access_scope fail-closed），聚合为 dict 传入 sync builder；helper best-effort 失败返回 `{}` 记 `project_galaxy_artifact_assoc_failed`（category=sampling）；`project_galaxy_built` 日志新增 `artifact_nodes`/`artifact_edges` kv。
3. **测试**（`server/tests/initiatives/test_project_galaxy_artifacts.py`）：5 用例——节点/边完整性、verified repo 边去重、仅关联来源、fail-soft、预算截断。

## Deviations from Plan

- **[Rule 3 - 增强] USES_REPO 去重扩展到全部边**：计划要求把 MR 来源 USES_REPO 纳入同一去重集，实现上把所有 `edges.append` 统一改走 `add_edge`（对 `(source,target,relation)` 去重）。既满足契约又消除既有代码中多 MR 同 repo 的重复 USES_REPO 边，无行为回退（既有 galaxy 测试全绿）。
- 计划测试 3 组，实测拆为 5 组（增「仅关联来源」独立用例），覆盖更细。

## Verification

- `uv run pytest tests/initiatives/test_project_galaxy_artifacts.py -x` → 5 passed
- `uv run pytest tests/test_project_galaxy.py` → 3 passed（既有 galaxy 零回归）
- `uv run ruff check initiatives/views.py` → All checks passed

## Self-Check: PASSED
- server/initiatives/views.py — FOUND（`_build_project_galaxy` / `_agather_artifact_assocs` 已扩展）
- server/tests/initiatives/test_project_galaxy_artifacts.py — FOUND
