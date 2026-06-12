---
phase: 15-retr
verified: 2026-06-12T03:15:00Z
status: passed
score: 5/5 plans complete
human_verification: []
---

# Phase 15: 时间感知混合检索 Verification Report

**Phase Goal:** 交付 `DeliveryKnowledgeSearchService`：向量召回 + 图扩散 + 时间衰减 + LLM 二阶段分级；PG 轨迹/关联查询；fail-closed 权限
**Verified:** 2026-06-12（HEAD `958fcdb6`）
**Status:** passed

## Test Results

| Suite | Result |
|-------|--------|
| `tests/knowledge/test_access_scope.py` | 6 passed |
| `tests/knowledge/test_recency.py` | 5 passed |
| `tests/knowledge/test_graph_store.py` (both) | 3 new + existing green |
| `tests/knowledge/test_vector_recall.py` | 9 passed |
| `tests/knowledge/test_timeline.py` | 5 passed |
| `tests/knowledge/test_related.py` | 5 passed |
| `tests/knowledge/test_hybrid_search.py` | 5 passed |
| `tests/knowledge/test_llm_grader.py` | 4 passed |
| `tests/knowledge/test_delivery_search.py` | 30 passed (22 eval parametrized) |
| **Phase 15 knowledge total** | **91 passed** |
| `manage.py check` | 0 issues |

## Plan Completion

| Plan | Commit | Key Deliverables |
|------|--------|------------------|
| 15-01 | `741bbe7a` | retrieval_types, access_scope, recency, settings, GraphStore both |
| 15-02 | `ecae3c91` | vector_recall, metadata_hydrate |
| 15-03 | `9f11396d` | timeline, related |
| 15-04 | `6d04b16d` | graph_enrichment, DeliveryKnowledgeSearchService |
| 15-05 | `958fcdb6` | llm_grader, REST `/api/knowledge/*`, eval fixture |

## Must-Have Verification

| Truth | Status | Evidence |
|-------|--------|----------|
| P1 is_latest filter 不可绕过 | ✓ | `_build_knowledge_must_filter` + test_vector_is_latest_filter |
| P2 as_of / naive datetime | ✓ | recency ValueError + graph_store both invalidated edge |
| P5 分路 RRF | ✓ | demand 70% / code 30% quotas in test_vector_route_quotas |
| P6 fail-closed 双维权限 | ✓ | access_scope + cross-project test_delivery_search |
| P10 timeline 零 Qdrant | ✓ | test_timeline_zero_qdrant_calls; timeline/related 无 Qdrant import |
| ENH-02 LLM 分级降级 | ✓ | test_llm_grader_* |
| eval ≥20 query | ✓ | retr_eval_queries.json 22 条 parametrized smoke |

## Implemented Files

**New modules:** `server/knowledge/retrieval_types.py`, `access_scope.py`, `recency.py`, `vector_recall.py`, `metadata_hydrate.py`, `timeline.py`, `related.py`, `graph_enrichment.py`, `retrieval.py`, `llm_grader.py`, `api/views.py`, `api/urls.py`

**Modified:** `server/knowledge/graph_store.py`, `server/friday/settings.py`, `server/friday/urls.py`

**Tests:** `test_access_scope.py`, `test_recency.py`, `test_graph_store.py` (both), `test_vector_recall.py`, `test_timeline.py`, `test_related.py`, `test_hybrid_search.py`, `test_llm_grader.py`, `test_delivery_search.py`, `fixtures/retr_eval_queries.json`

## Blockers / Deferred

- 无执行阻塞项
- Phase 16 入口（MCP/chat/workflow/前端）未在本 phase 范围
- LLM 分级默认 `KNOWLEDGE_RETRIEVAL_LLM_RERANK_ENABLED=False`；生产启用需配置 provider

## Self-Check: PASSED
