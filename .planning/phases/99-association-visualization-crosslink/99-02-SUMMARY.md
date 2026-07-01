---
phase: 99-association-visualization-crosslink
plan: 02
subsystem: knowledge.api / initiatives.serializers
tags: [KDEP-11, KDEP-12, reverse-query, entity_id, read-only]
requires: [98-03 ArtifactAssociationService, generate_entity_id]
provides:
  - "GET /api/knowledge/repositories/{id}/artifacts/（反查，每项带 entity_id）"
  - "ArtifactSerializer.entity_id 确定性派生字段"
affects: [99-03 前端反向卡, 99-04 作战室跨入口]
tech-stack:
  patterns: [adrf APIView 薄委托, access_scope fail-closed, SerializerMethodField 函数内 import]
key-files:
  created:
    - server/knowledge/api/repository_artifacts.py
    - server/tests/knowledge/test_repository_artifacts_api.py
    - server/tests/initiatives/test_artifact_serializer_entity_id.py
  modified:
    - server/knowledge/api/urls.py
    - server/initiatives/serializers.py
decisions:
  - "反查端点薄委托 find_artifacts_by_repository，不重复遍历；每项在视图层补 entity_id"
  - "entity_id 用后端派生（前端零 uuid5 计算），SerializerMethodField 函数内 import 避免顶层耦合"
metrics:
  duration_min: 12
  completed: 2026-07-01
---

# Phase 99 Plan 02: 反查端点 + entity_id Summary

补齐关联可视化的后端反向面与跳转锚点：新增 `GET /api/knowledge/repositories/{id}/artifacts/` 反查端点（薄委托 Phase 98 `find_artifacts_by_repository`，access_scope fail-closed，每项带确定性 `entity_id`），并在 `ArtifactSerializer` 暴露 `entity_id`（= document 实体 id），供 99-03 反向卡与 99-04 作战室跨入口消费。

## Tasks

1. **反查端点**：新建 `RepositoryArtifactsView`（`server/knowledge/api/repository_artifacts.py`）——镜像 `ArtifactAssociationsView`（adrf APIView + IsAuthenticated + @extend_schema + started/completed 观测），委托 `find_artifacts_by_repository(repository_id, user=...)`，每项补 `entity_id=generate_entity_id(DOCUMENT, "artifact", artifact_id)`，返回 `{artifacts:[...]}`。路由 `repositories/<uuid>/artifacts/` 命名 `knowledge-repository-artifacts`。
2. **ArtifactSerializer.entity_id**：新增 `SerializerMethodField`，`get_entity_id` 函数内 import 派生 document 实体 id，加入 `Meta.fields`（read_only_fields=fields 自动覆盖）。

## Deviations from Plan

None - plan executed exactly as written.（测试各多加一条 unknown-repo → 空列表用例，覆盖更细。）

## Verification

- `uv run pytest tests/knowledge/test_repository_artifacts_api.py tests/initiatives/test_artifact_serializer_entity_id.py` → 5 passed
- `uv run pytest tests/initiatives/test_artifact_api.py tests/knowledge/test_artifact_associations_api.py` → 11 passed（零回归）
- `reverse('knowledge-repository-artifacts', ...)` → `/api/knowledge/repositories/{id}/artifacts/`
- `uv run ruff check ...` → All checks passed

## Self-Check: PASSED
- server/knowledge/api/repository_artifacts.py — FOUND
- server/knowledge/api/urls.py — FOUND（路由已注册）
- server/initiatives/serializers.py — FOUND（entity_id 已暴露）
- 两处测试文件 — FOUND
