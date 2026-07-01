---
phase: 96-external-deps-search-overview
plan: 02
subsystem: knowledge-retrieval
tags: [knowledge, search, artifact, serialization, access-scope, KDEP-02]
requires: []
provides:
  - EntityMetadata.artifact 元数据载体字段
  - hydrate 批量补全工件 type_name/carrier/url/artifact_id/project_id/project_name
  - serialize_search_result 输出 origin/source_kind/artifact
  - KnowledgeSearchView 启用 document 召回
affects:
  - server/knowledge/retrieval_types.py
  - server/knowledge/metadata_hydrate.py
  - server/knowledge/exposure.py
  - server/knowledge/api/views.py
tech-stack:
  added: []
  patterns: [batch-hydrate-no-n+1, lazy-cross-app-import, access-scope-fail-closed]
key-files:
  created: []
  modified:
    - server/knowledge/retrieval_types.py
    - server/knowledge/metadata_hydrate.py
    - server/knowledge/exposure.py
    - server/knowledge/api/views.py
    - server/tests/knowledge/test_knowledge_api.py
decisions:
  - document-kind 实体纳入 /knowledge 搜索召回（include_document_kind=True），权限闸不放宽
  - 工件元数据批量解析（ArtifactType.key→name、Project.id→name）避免 N+1
  - 序列化仅暴露受控元数据（type/carrier/url/artifact_id/project 名），不回传正文/凭证
metrics:
  duration: ~25min
  completed: 2026-07-01
---

# Phase 96 Plan 02: 后端召回 + 序列化 Summary

让 `/knowledge` 搜索命中工件时携带足够元数据供前端标类型徽标 + 一键查看：①document-kind 工件实体进入搜索召回（此前默认被过滤）；②检索结果 DTO/序列化补全工件专有元数据（type_name/carrier/url/artifact_id/所属项目 id+名称），跨项目按 access_scope 过滤。

## What Changed

### Task 1 — EntityMetadata 承载工件元数据 + hydrate 批量补全 + 序列化
- `retrieval_types.py`：`EntityMetadata` 追加 `artifact: dict | None = None`（frozen+slots 兼容，带默认非破坏）。仅 origin=="artifact" 时填充。
- `metadata_hydrate.py`：新增 `_resolve_artifact_maps(type_keys, project_ids)`（惰性导入 `initiatives.models.ArtifactType/Project`，批量 `values_list` 解析 type_name/project_name 映射，fail-soft）+ `_build_artifact_meta(entity, payload, ...)`（origin=artifact → 工件 dict，payload 缺字段置 None）。`hydrate_many` 在 build 循环前一次性批量解析映射（避免 N+1）；`hydrate_entity_metadata`（单条）同款支持。
- `exposure.py`：`serialize_search_result` 输出补 `origin`/`source_kind`/`artifact`（经 `_jsonable`，None 时前端忽略）。

### Task 2 — KnowledgeSearchView 启用 document 召回 + API 测试
- `api/views.py::KnowledgeSearchView.get`：`search_similar(..., include_document_kind=True)`。权限不放宽（recall 仍受 allowed_project_ids/allowed_repository_ids 收口）；注明取舍：feishu_document/project_doc/project_memory 等 document 实体一并进全局搜索（属预期，均受权限过滤）。
- 测试：`test_search_artifact_hit_carries_metadata`（mock recall 返回 origin=artifact 命中，断言 origin/source_kind/artifact.{type_name,type_key,carrier,url,artifact_id,project_name} + include_document_kind=True + allowed_project_ids 含当前用户可见 Space）；`test_search_non_member_no_visible_artifacts`（越权：非成员无可见 project → 空结果，recall 断言不触达）。

## Verification Results
- `uv run pytest tests/knowledge/test_exposure.py tests/knowledge/test_knowledge_api.py -q` → **13 passed**
- `uv run ruff check` 目标文件 → All checks passed
- 手工核对：搜索响应工件项含 `origin`/`source_kind`/`artifact.{type_name,carrier,url,artifact_id,project_id,project_name}`；越权用例他项目工件不可见。

## Deviations from Plan
- 越权用例实现取舍：因本地测试环境无 Qdrant（`--disable-socket`），无法真跑向量召回验证「他项目工件被 filter 过滤」，改为断言 access_scope fail-closed 闸门（非成员无可见 project → 空结果，recall 不触达）+ 正例断言 recall 收到的 `allowed_project_ids` 含当前用户可见 Space。等价守护 access_scope 收口，无 Qdrant 依赖。

## Known Stubs
None —— 均接真实 DB hydrate 与序列化，无占位数据。

## Self-Check: PASSED
- `EntityMetadata.artifact` 字段存在（FOUND）
- `hydrate_many`/`hydrate_entity_metadata` 批量补全工件元数据（FOUND）
- `serialize_search_result` 输出 origin/source_kind/artifact（FOUND）
- `KnowledgeSearchView` include_document_kind=True（FOUND）
- 测试 13 passed（FOUND）
