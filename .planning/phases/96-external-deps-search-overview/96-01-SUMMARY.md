---
phase: 96-external-deps-search-overview
plan: 01
subsystem: knowledge-ingestion
tags: [knowledge, ingestion, artifact, metadata-only, KDEP-01]
requires: []
provides:
  - IngestionEvent.vectorize 开关（元数据-only 登记语义）
  - artifact normalizer 非 ragable → vectorize=False 事件分支
  - ArtifactService 全类型工件调度摄取
affects:
  - server/knowledge/ingestion.py
  - server/knowledge/sources/artifact.py
  - server/initiatives/services/artifact_service.py
tech-stack:
  added: []
  patterns: [metadata-only-ingestion, content-hash-idempotency, fail-soft]
key-files:
  created: []
  modified:
    - server/knowledge/ingestion.py
    - server/knowledge/sources/artifact.py
    - server/initiatives/services/artifact_service.py
    - server/tests/knowledge/test_artifact_source.py
    - server/tests/initiatives/test_artifact_service.py
decisions:
  - 非 ragable 工件走元数据-only 登记（KnowledgeEntity(document)+REFERENCES 边，零 Qdrant 向量）
  - vectorize=False 版本以 vector_synced=True 落库，天然走 skipped 短路实现幂等
  - ragable↔非 ragable 翻转时 best-effort tombstone+delete 旧向量点
metrics:
  duration: ~30min
  completed: 2026-07-01
---

# Phase 96 Plan 01: 外部依赖全类型登记 Summary

让**全部** `ArtifactType` 的工件都在知识体系登记为可发现实体：ragable 文字工件行为零回归（仍 chunk+embed 进 delivery_knowledge），非 ragable 工件（UI 稿 external_link 等）落一条 `vectorize=False` 的轻量 `KnowledgeEntity(kind=document)` + `REFERENCES→项目节点` 边，承载 title/type/carrier/url 元数据但不进 Qdrant 向量。

## What Changed

### Task 1 — `IngestionEvent.vectorize` 开关 + `ingest_events` 元数据-only 分支
- `IngestionEvent` 新增 `vectorize: bool = True`（默认 True 保既有 normalizer 零回归）。
- `ingest_events` 阶段 A：`vectorize=False` 时跳过 `ensure_delivery_knowledge_collection()`（不依赖 Qdrant 可用性）、跳过 `chunk/embed`（chunks/dense/sparse 皆空），补 `knowledge_ingest_metadata_only`（category=sampling, component=knowledge）观测。
- 阶段 C 向量序：`not event.vectorize` 分支 best-effort tombstone+delete `old_point_ids`（清理 ragable→非 ragable 翻转残留旧向量，失败仅 error 不上抛），随后 continue。

### Task 2 — artifact normalizer 非 ragable 分支 + `_persist_sync` 尊重 vectorize
- `knowledge/sources/artifact.py::normalize`：删除「非 ragable → return []」；改为按 `ragable + 文字载体` 决定 `vectorize`。非 ragable 分支 content 为确定性元数据文本（title/type.name/carrier/url 拼接，经 `redact_secrets_in_text`）作 content_hash 幂等锚，产 `IngestionEvent(vectorize=False)`（含 REFERENCES→项目节点 边，payload 与 ragable 分支同构）。
- `knowledge/ingestion.py::_persist_sync`：新版本落库时 `not event.vectorize` → `qdrant_point_ids=[]`、`toc_tree=[]`、`vector_synced=True`；否则维持既有。
- 实体 id 仍走 `generate_entity_id(DOCUMENT, "artifact", artifact_id)` —— ragable↔非 ragable 切换共用同一实体，无重复。

### Task 3 — `ArtifactService` 全类型调度 + 守护测试
- `_maybe_schedule_ingestion` 移除 `_should_ingest` 预筛短路，改为**对全部工件调度** `aschedule_ingestion(source_kind="artifact")`；normalizer 内部决定向量 vs 元数据-only。`artifact_rag_scheduled` 事件补 `ragable` 字段。
- 删除不再引用的 `_should_ingest` 与 `TEXT_CARRIERS` 导入（避免死代码）。
- 保留 best-effort try/except 永不反噬工件写入。

## Verification Results
- `uv run pytest tests/knowledge/test_ingestion.py tests/knowledge/test_artifact_source.py -x -q` → **27 passed**
- `uv run pytest tests/initiatives/test_artifact_service.py -q` → pass
- 手工核对语义：非 ragable 工件摄取后 `qdrant_point_ids == []`、`vector_synced is True`、无 upsert 调用（新测试 `test_graphic_artifact_metadata_only_registered` 断言覆盖）。

## Deviations from Plan

### Test assertion updates（计划内语义变更的连带更新）
- **`test_artifact_source.py::test_graphic_artifact_metadata_only_no_ingestion`** → 重写为 `test_graphic_artifact_metadata_only_registered`（计划明确要求）：断言 produce 1 event、实体+边存在、`qdrant_point_ids==[]`、`vector_synced is True`、payload 正确、无 upsert。
- **[Rule 1 - 连带] `test_artifact_service.py::test_graphic_artifact_skips_ingestion`** → 重写为 `test_graphic_artifact_schedules_metadata_only_ingestion`。该用例守护旧「非 ragable 不调度」行为，与 KDEP-01「覆盖全部类型不遗漏」冲突，按新语义改为断言仍调度。

### Deferred（out-of-scope，见 deferred-items.md）
- `test_artifact_inv6_guard.py::test_inv6_no_bypass_artifact_write` 预存在失败（干净树同样失败，flag 的是 `delivery` app 的同名模型，与本阶段无关）。
- `knowledge/ingestion.py` 预存在 `ruff I001`（本阶段未改动的 import 块），不修以避免无关 diff。

## Self-Check: PASSED
- `server/knowledge/ingestion.py` — vectorize 字段 + 分支存在（FOUND）
- `server/knowledge/sources/artifact.py` — vectorize=False 分支存在（FOUND）
- `server/initiatives/services/artifact_service.py` — 全类型调度（FOUND）
- 相关测试 27 passed（FOUND）
