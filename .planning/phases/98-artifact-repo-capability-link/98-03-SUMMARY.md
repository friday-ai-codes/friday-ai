---
phase: 98-artifact-repo-capability-link
plan: 03
subsystem: knowledge
tags: [graph-query, access-scope, api, read-only, KDEP-09]
requires:
  - "knowledge.graph_store.graph_store.neighbors"
  - "knowledge.access_scope.resolve_allowed_project_ids / resolve_allowed_repository_ids"
  - "98-01/98-02 契约: RELATES_TO 边 metadata.source in (artifact, repo_association)"
provides:
  - "ArtifactAssociationService（正向 get_artifact_associations + 反向 find_artifacts_by_repository/capability/keyword）"
  - "GET /api/knowledge/artifacts/{id}/associations/（JWT + access_scope）"
affects:
  - server/knowledge/artifact_associations.py
  - server/knowledge/api/artifact_associations.py
  - server/knowledge/api/urls.py
tech-stack:
  added: []
  patterns: [graph-store-collection, fail-closed-access-scope, best-effort-fail-soft, thin-adrf-view]
key-files:
  created:
    - server/knowledge/artifact_associations.py
    - server/knowledge/api/artifact_associations.py
    - server/tests/knowledge/test_artifact_associations_service.py
    - server/tests/knowledge/test_artifact_associations_api.py
  modified:
    - server/knowledge/api/urls.py
decisions:
  - "二次 space 过滤复用 resolve_allowed_project_ids（async）产出的可见 space id 传入 sync hydrate，避免自建 Project/Space id 集合与既有权限收口分叉"
  - "端点仅暴露正向查询（最小面积）；反向查询留服务层供 Phase 99 消费"
  - "查询仅认 metadata.source==\"artifact\" 的工件路由边（不含 repo_association 派生边）"
metrics:
  duration: ~25m
  completed: 2026-07-01
---

# Phase 98 Plan 03: 工件↔仓库/能力/关键词双向查询服务 + 只读端点 Summary

KDEP-09：让 98-01/98-02 建立的关联可查询。提供可复用服务层双向查询（查询走 `graph_store.neighbors`
单跳收口），关键词/能力从边 metadata 读取（不查实体表）；暴露最小只读端点 `GET
/api/knowledge/artifacts/{id}/associations/`。查询强制 `access_scope` fail-closed。

## What Was Built

### Task 1 — ArtifactAssociationService（双向查询）
新建 `server/knowledge/artifact_associations.py`：
- `get_artifact_associations(artifact_id, *, user)`（正向）：document 实体 `space_id` 经
  `resolve_allowed_project_ids` 校验可见（不可见 → None）；`neighbors(entity, RELATES_TO, out)`
  过滤 `metadata.source=="artifact"`，返回 `{repositories:[{repository_id, repo_name, node_paths,
  keywords, score}], capabilities:[去重 node_paths], keywords:[去重 keywords]}`。
- `find_artifacts_by_repository(repository_id, *, user, capability_path=None, keyword=None)`（反向）：
  `resolve_allowed_repository_ids(user, [id])` 校验仓库可见（不可见 → []）；`neighbors(repo_node,
  RELATES_TO, in)` 过滤 source==artifact + capability_path（成员/前缀双向）+ keyword；补全 Artifact
  标题/类型/project 并按 `project__space_id` 二次 `resolve_allowed_project_ids` 过滤（fail-closed 双维）。
- `find_artifacts_by_capability` / `find_artifacts_by_keyword`：在 `resolve_allowed_repository_ids(user)`
  可见仓库集合内逐仓复用反向查询，按 artifact_id 去重（有界）。
- fail-closed：无 user/无可见范围 → None/[]；异常 best-effort 返回空 + `artifact_associations_query_failed`。
  观测 `artifact_associations_queried`（caller/knowledge, +方向/命中数/duration_ms）。async ORM 经 `sync_to_async`。

### Task 2 — 只读端点
- 新建 `server/knowledge/api/artifact_associations.py::ArtifactAssociationsView`（adrf `APIView`,
  `IsAuthenticated`, `@extend_schema(tags=["knowledge"])`），`get(request, artifact_id)` 薄委托服务层正向查询：
  None → 404「工件不存在或无权访问」；否则 200 + payload。观测 `artifact_associations_api_started/completed`。
- `urls.py` 新增 `path("artifacts/<uuid:artifact_id>/associations/", ..., name="knowledge-artifact-associations")`。

## Verification

- `test_artifact_associations_service.py`：10 passed（正向 repositories/capabilities/keywords / 不可见 None /
  缺失 None / 反向仓库 / capability 过滤 / keyword 过滤 / 不可见仓库 [] / by_capability / by_keyword / no-user 空）。
- `test_artifact_associations_api.py`：4 passed（可见 200 / 越权 404 / 缺失 404 / 未认证 401）。
- `python -c "... hasattr(S,'get_artifact_associations') and hasattr(S,'find_artifacts_by_repository')"` → ok。
- `reverse('knowledge-artifact-associations', ...)` → `/api/knowledge/artifacts/{id}/associations/`。
- lint：无错误。

## Deviations from Plan

**None** — plan 执行如写。反查工件的二次 space 过滤实现为「async 层用 `resolve_allowed_project_ids` 取可见
space id → 传入 sync hydrate 过滤 `project__space_id__in`」，与 plan「按 project__space_id 二次 access_scope 过滤」
语义一致（复用既有权限收口，未自建权限集合）。

## Contract for downstream (Phase 99)

- 服务方法：`get_artifact_associations` / `find_artifacts_by_repository` / `find_artifacts_by_capability` /
  `find_artifacts_by_keyword`（无状态，可直接复用）。
- 正向 payload：`{repositories:[{repository_id, repo_name, node_paths, keywords, score}], capabilities:[...], keywords:[...]}`。

## Self-Check: PASSED
- server/knowledge/artifact_associations.py — FOUND（ArtifactAssociationService）
- server/knowledge/api/artifact_associations.py — FOUND（ArtifactAssociationsView）
- server/knowledge/api/urls.py — FOUND（knowledge-artifact-associations）
- server/tests/knowledge/test_artifact_associations_service.py — FOUND
- server/tests/knowledge/test_artifact_associations_api.py — FOUND
