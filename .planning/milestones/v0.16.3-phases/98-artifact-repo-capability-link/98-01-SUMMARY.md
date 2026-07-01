---
phase: 98-artifact-repo-capability-link
plan: 01
subsystem: knowledge
tags: [graph, ingestion, routing, edge-metadata, KDEP-07]
requires:
  - "codegraph.services.repo_router_v2.RepoRouterV2.route"
  - "knowledge.ingestion.EdgeSpec / apply_edge_specs"
  - "initiatives.services.knowledge_graph.ProjectKnowledgeGraphService.ensure_repository_node"
  - "agents.call_source.CallSource.AUX_REPO_ROUTER"
provides:
  - "graph_store.update_edge_metadata（活跃边 metadata 就地覆盖原语）"
  - "apply_edge_specs 实体边 metadata 携带 + 幂等 upsert 语义"
  - "artifact→repo KnowledgeEdge(RELATES_TO) + metadata{source,artifact_id,node_paths,keywords,score}"
affects:
  - server/knowledge/graph_store.py
  - server/knowledge/ingestion.py
  - server/knowledge/sources/artifact.py
tech-stack:
  added: []
  patterns: [best-effort-fail-soft, idempotent-upsert, single-write-entry, use-call-source]
key-files:
  created:
    - server/tests/knowledge/test_edge_metadata_upsert.py
    - server/tests/knowledge/test_artifact_repo_routing.py
  modified:
    - server/knowledge/graph_store.py
    - server/knowledge/ingestion.py
    - server/knowledge/sources/artifact.py
decisions:
  - "update_edge_metadata 未加入模块 __all__：它是 GraphStore 方法（同 add_edge/invalidate_edge），非模块级符号；加入会破坏 from graph_store import *（偏离 plan 指令，见 Deviations）"
  - "keywords 由 matched_node_paths 叶子段派生去重保序（RepoRouterV2 不直接返回 keywords）"
metrics:
  duration: ~35m
  completed: 2026-07-01
---

# Phase 98 Plan 01: 工件正文路由建边 + 边 metadata 幂等 upsert 收口 Summary

KDEP-07：为 ragable 文字工件在摄取时经 `RepoRouterV2` 路由正文，对每个命中仓库落一条
`artifact→repo` 的 `KnowledgeEdge(RELATES_TO)`，关键词/能力/score 全承载在边 metadata（无独立实体表）；
建边全走 `EdgeSpec → apply_edge_specs → graph_store` 单一写入入口，幂等 upsert，fail-soft 绝不反噬摄取。

## What Was Built

### Task 1 — 边 metadata 幂等 upsert 收口
- `graph_store.py`：新增 `update_edge_metadata(edge_id, *, metadata)`（Protocol + `RelationalGraphStore` 两处）。
  仅对当前有效边（`invalid_at IS NULL AND expired_at IS NULL`）就地 `aupdate(metadata=...)`；边不存在
  → `raise KnowledgeEdge.DoesNotExist`（响亮），边已失效/作废 → warning 幂等返回；**绝不触碰四时间戳**
  （不改写 bi-temporal 历史，T-12-04）。事件 `knowledge_edge_metadata_updated` / `_skipped`。
- `ingestion.py::apply_edge_specs` 实体边分支：由「已存在同 target 活跃边 → continue」改为定位该活跃边——
  `spec.metadata is not None` → `update_edge_metadata` 覆盖后 continue；`metadata is None` → 保持跳过
  （既有 REFERENCES/HAS_PLAN 零回归）。建新边补传 `metadata=spec.metadata`。

### Task 2 — 工件正文 RepoRouterV2 路由 → RELATES_TO 边
- `sources/artifact.py`：新增 best-effort 后置步骤 `_route_artifact_body_edges`：仅 `vectorize` 且正文非空时
  执行；经 `sync_to_async` 取 `space.repositories` id 收窄候选范围（为空跳过）；`use_call_source(AUX_REPO_ROUTER)`
  包裹 `RepoRouterV2.route(query[:4000], top_k=5, repository_ids=..., use_llm=True)`；对每个命中 candidate
  按 `repo_id` 取 `Repository`、`ensure_repository_node`、构造 `EdgeSpec(RELATES_TO, target=repo_node,
  metadata={source,artifact_id,node_paths,keywords,score})`。keywords 由 `matched_node_paths` 叶子段去重保序派生。
  整体 `try/except`（`# noqa: BLE001`）吞掉一切，异常返回空 tuple，`event` 照常返回。
- 观测：`artifact_repo_route_started/completed/failed`（category=sampling, component=knowledge, +duration_ms
  +matched_repo_count/node_path_count/keyword_count/router_version），异常 reason 经 `redact_secrets_in_text`。
- normalizer 只声明 EdgeSpec，写入由既有 `apply_edge_specs`（Task 1 已让其携带并覆盖 metadata）统一处理。

## Verification

- `test_edge_metadata_upsert.py`：7 passed。
- `test_artifact_repo_routing.py`：5 passed（命中建边 / 幂等覆盖不重复 / 非 ragable 跳过 / 无仓库跳过 / route 异常 fail-soft）。
- 回归：`test_artifact_source.py` + `test_graph_store.py`（含 grep 审计 raw SQL 收口）+ `test_ingestion.py` → 合计 **65 passed, 1 deselected**。
- `python -c "... hasattr(graph_store,'update_edge_metadata')"` → ok。
- lint：无错误。

## Deviations from Plan

**1. [Rule 1 - Bug] `update_edge_metadata` 未加入模块 `__all__`**
- **Found during:** Task 1
- **Issue:** plan action 要求「把 `update_edge_metadata` 加入模块 `__all__`」，但它是 `GraphStore`/`RelationalGraphStore`
  的方法（与 `add_edge`/`invalidate_edge` 同类，均不在 `__all__`），并非模块级函数。把不存在的模块级符号写入 `__all__`
  会让 `from knowledge.graph_store import *` 抛 `AttributeError`。
- **Fix:** 不修改 `__all__`（保持只列模块级符号 `graph_store`/`invalidate_entity_version`/`require_aware` 等）。方法通过
  `graph_store.update_edge_metadata` 单例访问，功能完全就位；验证 `hasattr(graph_store,'update_edge_metadata')` 通过。
- **Files modified:** server/knowledge/graph_store.py（仅方法新增，`__all__` 未动）

## Contract for downstream (98-02 / 98-03 / Phase 99)

- `artifact→repo` `KnowledgeEdge(RELATES_TO)`，`metadata={source:"artifact", artifact_id, node_paths:[...], keywords:[...], score}`。
- `graph_store.update_edge_metadata(edge_id, *, metadata)` 可复用于 98-02 派生边 metadata 覆盖。

## Self-Check: PASSED
- server/knowledge/graph_store.py — FOUND（update_edge_metadata 定义）
- server/knowledge/sources/artifact.py — FOUND（_route_artifact_body_edges）
- server/tests/knowledge/test_edge_metadata_upsert.py — FOUND
- server/tests/knowledge/test_artifact_repo_routing.py — FOUND
