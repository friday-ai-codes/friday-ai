---
phase: 98-artifact-repo-capability-link
plan: 02
subsystem: initiatives
tags: [graph, repo-association, derived-edge, single-source-of-truth, KDEP-08]
requires:
  - "knowledge.graph_store.graph_store (add_edge/invalidate_edge/update_edge_metadata/neighbors)"
  - "initiatives.models.RepoAssociation / RepoAssociationStatus"
provides:
  - "ProjectKnowledgeGraphService.link_repository(metadata=...) + unlink_repository + sync_relations_from_operational verified 派生"
  - "RepoAssociationService._sync_association_graph（verified/unverified 单一同步 hook, best-effort）"
  - "project→repo KnowledgeEdge(RELATES_TO) + metadata{source:repo_association, association_id, score, confidence, matched_node_paths}"
affects:
  - server/initiatives/services/knowledge_graph.py
  - server/initiatives/services/repo_association_service.py
tech-stack:
  added: []
  patterns: [unidirectional-derivation, single-source-of-truth, best-effort-fail-soft, idempotent-upsert]
key-files:
  created:
    - server/tests/initiatives/test_repo_association_graph_sync.py
  modified:
    - server/initiatives/services/knowledge_graph.py
    - server/initiatives/services/repo_association_service.py
decisions:
  - "record_verdict 在 async 层复算 _sanitize_verdict(verdict).fit 决定 verified/unverified，_record_verdict_sync 返回 bool 契约不变（最小改动，不破坏既有调用方）"
  - "hook 单一入口 _sync_association_graph 覆盖三个状态流转收口（record_verdict/accept_mismatch/reopen_candidates），不散落图谱写入"
  - "RepoAssociation 唯一真相源：本 service 只读关联、只写 KnowledgeEdge，绝不写回真相源"
metrics:
  duration: ~25m
  completed: 2026-07-01
---

# Phase 98 Plan 02: verified RepoAssociation → 项目↔仓库派生边 Summary

KDEP-08：把 `RepoAssociation(status=verified)` 单向派生为 `project→repo` 的 `KnowledgeEdge(RELATES_TO)`，
在关联状态机到/离开 verified 的收口处挂单一 best-effort 同步 hook。RepoAssociation 保持唯一真相源，
图谱边单向派生（真相变则边随之增删），幂等、fail-soft 绝不反噬状态流转。

## What Was Built

### Task 1 — ProjectKnowledgeGraphService 派生/失效
- `_add_edge_idempotent` 新增 `metadata: dict | None = None`：建新边携带 metadata；命中已有活跃出边且
  `metadata is not None` → `graph_store.update_edge_metadata` 覆盖后返回 False（既有无 metadata 路径行为不变）。
- `link_repository` 新增 `metadata` 参数透传（KDEP-08 契约字段）。
- 新增 `unlink_repository`：`graph_store.neighbors(project_node, RELATES_TO, out)` 定位命中仓库节点的活跃边，
  逐条 `invalidate_edge` 失效置位；无匹配 → 幂等返回 False。事件 `project_graph_repository_unlinked`。
- `sync_relations_from_operational` 扩展：在 space + related_projects 派生之后，`sync_to_async` 取
  `RepoAssociation.objects.filter(project=project, status=verified).select_related("repository")`，逐条
  `link_repository(metadata=...)` 累加 `verified_repo_edges`（日志字段）。延迟 import `RepoAssociation/Status`
  避免循环依赖。新增 helper `_association_edge_metadata`。

### Task 2 — RepoAssociationService 单一同步 hook
- 新增 `async def _sync_association_graph(*, association_id, verified, initiated_by_user_id=None)`：
  `sync_to_async` 载入关联（select_related project/repository），`verified=True` → `link_repository(metadata=...)`；
  `verified=False` → `unlink_repository`。整体 `try/except`（`# noqa: BLE001`）吞掉 + `repo_association_graph_sync_failed`
  （reason 经 `redact_secrets_in_text`），成功记 `repo_association_graph_synced`。绝不反噬状态流转。
- 三个收口挂 hook（单一入口）：
  - `record_verdict`：`_record_verdict_sync` 返回 True 后，async 层复算 `_sanitize_verdict(verdict).fit`——
    `fit` → verified=True，`mismatch` → verified=False，`unknown` 不触发。
  - `accept_mismatch`：sync 返回 True（→verified）→ verified=True。
  - `reopen_candidates`：sync 返回 True（→proposed）→ verified=False（曾 verified 则失效派生边，否则 unlink 幂等 no-op）。

## Verification

- `test_repo_association_graph_sync.py`：9 passed（link metadata / 覆盖不重复 / unlink 幂等 / sync 派生 verified 且 proposed 不派生 /
  record_verdict fit 派生 / mismatch 失效 / accept_mismatch 派生 / reopen 失效 / hook 异常不打断 verdict 落库）。
- 回归：`test_project_knowledge_graph.py` + `test_repo_association_output.py` → 8 passed。
- `python -c "... hasattr(S,'unlink_repository')"` → ok。
- lint：无错误。

## Deviations from Plan

**None** — plan 执行如写。plan 提供的 `_record_verdict_sync` 返回 `(applied, fit)` 或 async 层复算 fit 二选一，
本实现选「async 层复算 `_sanitize_verdict(verdict).fit`」（最小改动，保持 sync 方法 bool 返回契约与幂等语义不变）。

## Contract for downstream (98-03 / Phase 99)

- `project→repo` `KnowledgeEdge(RELATES_TO)`，`metadata={source:"repo_association", association_id, score, confidence, matched_node_paths}`。
- 离开 verified → 派生边 `invalid_at` 置位（失效），图谱与真相源最终一致。

## Self-Check: PASSED
- server/initiatives/services/knowledge_graph.py — FOUND（unlink_repository / _association_edge_metadata）
- server/initiatives/services/repo_association_service.py — FOUND（_sync_association_graph）
- server/tests/initiatives/test_repo_association_graph_sync.py — FOUND
