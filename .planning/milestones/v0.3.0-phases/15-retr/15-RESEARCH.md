# Phase 15: 时间感知混合检索 — Lightweight Research

**Researched:** 2026-06-12
**Confidence:** HIGH（时间衰减为检索后 rerank 标准模式；其余能力均来自 Phase 12–14 既有资产）
**Mode:** ROADMAP 研究标记轻量补全（非 Level 2 全量调研）

## Scope

本阶段交付 `DeliveryKnowledgeSearchService` 统一检索收口：向量 hybrid 召回 + 1–2 跳图扩散 + 时间衰减 rerank + LLM 二阶段分级 + PG 纯轨迹查询。不在本阶段：MCP/chat/workflow 入口（Phase 16）。

## Time Decay Parameters（ROADMAP 研究标记）

### 推荐公式（检索后 rerank，不写进向量）

```
age_days = max(0, (reference_time - event_time).total_seconds() / 86400)
recency = exp(-ln(2) * age_days / half_life_days)
final_score = alpha * norm":"score_norm + beta * recency
```

- **half_life_days = 90**（ROADMAP / CONTEXT 锁定默认）：90 天前事件 recency=0.5；180 天前 ≈ 0.25。
- **alpha = 0.7, beta = 0.3**（规划定案，可 env 覆盖）：向量相关性为主、新近性为辅；与 RepoRouter 0.6/0.4 同量级，知识检索更偏语义故 alpha 略高。
- **reference_time**：默认 `timezone.now()`；`as_of` 参数传入时用 as_of（与 GraphStore as_of 语义对齐，P2）。
- **vector_score_norm**：Qdrant RRF 分路分数 min-max 归一化到 [0,1]；单候选退化时 score_norm=1.0。
- **状态类 vs 事件类**：`event_time` 来自 payload（collection.py 已索引）；code_change / work_item 均适用；无 event_time 时 recency=0.5 中性缺省（不阻塞主链路）。

### 配置落点

`server/friday/settings.py` 新增（SystemSetting 后续可扩展，本阶段 settings + env 足够）：

| 键 | 默认 | env |
|----|------|-----|
| `KNOWLEDGE_RETRIEVAL_ALPHA` | 0.7 | `KNOWLEDGE_RETRIEVAL_ALPHA` |
| `KNOWLEDGE_RETRIEVAL_BETA` | 0.3 | `KNOWLEDGE_RETRIEVAL_BETA` |
| `KNOWLEDGE_RETRIEVAL_HALF_LIFE_DAYS` | 90 | `KNOWLEDGE_RETRIEVAL_HALF_LIFE_DAYS` |
| `KNOWLEDGE_RETRIEVAL_GRAPH_MAX_HOPS` | 2 | `KNOWLEDGE_RETRIEVAL_GRAPH_MAX_HOPS` |
| `KNOWLEDGE_RETRIEVAL_LLM_RERANK_ENABLED` | True | `KNOWLEDGE_RETRIEVAL_LLM_RERANK_ENABLED` |

## Vector Recall Architecture

### 强制 filter（P1 / P6 防线，不可 bypass）

Qdrant `must` 条件（参照 `reconcile_delivery_knowledge.py` scroll filter 写法）：

1. `is_latest=true`（P1 检索侧兜底，CONTEXT 强制）
2. `project_id` ∈ allowed_project_ids（从 PermissionService 解析；空集合 → 直接返回 []，fail-closed）
3. 可选：`entity_kind` ∈ caller 参数；caller `project_ids` 只能**收窄** allowed 集合

### 分路召回 + RRF（P5 防单类型刷屏）

两路独立 hybrid query（dense+sparse RRF，复用 `QdrantService.hybrid_search_by_name`）：

| 路径 | entity_kind filter | 默认配额 |
|------|-------------------|----------|
| demand/plan | work_item, tech_plan | top_k * 0.7 |
| code | code_change | top_k * 0.3 |

跨路 RRF 融合（chunk 级 dedupe by entity_id，保留最高分 chunk）。

### Embedding 路径

复用 `EmbeddingService.generate_embedding` + `SparseEncoderService.encode`（与 `RepoRouter` / `search_rag` 同链）。

## Graph Enrichment

- Anchor = 向量命中 entity_id（dedupe 后）
- `graph_store.traverse(anchor, max_hops=2, relations=[HAS_PLAN, IMPLEMENTED_BY, RELATES_TO], as_of=...)`
- **Phase 12 预留**：`direction="both"` 多跳本阶段实现（RETR-02 双向上下游）
- 图节点 enrich 结果：关联 tech_plan / code_change / MR 链接经 PG hydrate（KnowledgeEntity + CodeChangeArchive.mr_url）
- GraphStore 内置有效性过滤（P2）；不重复手写 invalid_at 条件

## PG Trajectory（RETR-03 / P10）

- `get_timeline(entity_id)`：**零 Qdrant 调用**
- `KnowledgeEntityVersion.objects.filter(entity_id=...).order_by("version")`
- 挂接 code_change：`graph_store.neighbors` / 边表 IMPLEMENTED_BY 反查，按 event_time 排序
- `include_superseded=false` 时 queryset 过滤 `is_latest=True` 或 `invalid_at IS NULL`（与 CONTEXT 一致）

## LLM Second-Stage（ENH-02）

- 复用 `services/provider_config` 解析默认 chat 模型（非 RerankerService——需 structured 分级输出）
- 输出 JSON：`[{entity_id, grade: duplicate|related|unrelated, reason: str}]`
- 失败降级：log warning + 保持 vector+time 排序（不 raise）
- Prompt 中文；每候选 title+摘要 ≤500 字截断

## Eval Fixture（20–50 queries）

- 路径：`server/tests/knowledge/fixtures/retr_eval_queries.json`
- 本阶段**合成 fixture**（entity_factory 预置 3–5 条 work_item 链 + 中文 query 文本）
- 断言：召回非空、is_latest filter 生效、越权 0 结果、timeline 版本序单调
- 真实生产 query 后续 Phase 16 前补（不在本阶段阻塞）

## Architectural Responsibility Map

| 能力 | 模块 | 说明 |
|------|------|------|
| DTO / 契约 | `knowledge/retrieval_types.py` | Pydantic/dataclass，Phase 16 入口消费 |
| 权限 scope | `knowledge/access_scope.py` | PermissionService → project_id 集合 |
| 时间衰减 | `knowledge/recency.py` | 纯函数，可单测 |
| 向量召回 | `knowledge/vector_recall.py` | Qdrant hybrid + 分路 RRF |
| 图扩散 hydrate | `knowledge/graph_enrichment.py` | traverse + PG 补全 |
| 编排收口 | `knowledge/retrieval.py` | DeliveryKnowledgeSearchService |
| LLM 分级 | `knowledge/llm_grader.py` | ENH-02 |
| 轨迹/关联 | `knowledge/retrieval.py` | get_timeline / get_related |
| GraphStore 扩展 | `knowledge/graph_store.py` | direction=both 多跳 |

## Package Legitimacy Audit

无新 pip/npm 依赖。LLM 走既有 provider SDK。

## Security Domain

| 威胁 | 处置 |
|------|------|
| 越权检索（P6） | service 强制 user；Qdrant filter + PG queryset 双收窄 |
| is_latest bypass（P1） | filter 封装在 vector_recall 内部，无 raw Qdrant 出口 |
| Prompt 注入（ENH-02） | 候选文本截断；结构化 JSON 输出；失败降级 |
| 图扩散泄漏失效边（P2） | GraphStore 默认过滤 + as_of 显式参数 |

## Common Pitfalls（本阶段必守）

- **P1**：is_latest filter 不可 bypass（must_haves + grep 审计）
- **P2**：as_of / event_time 必须 timezone-aware
- **P5**：分路 RRF 防 work_item 刷屏
- **P6**：project_id payload filter + fail-closed 空 allowed
- **P10**：get_timeline 禁止 import Qdrant

## Sources

- `.planning/phases/15-retr/15-CONTEXT.md`（locked decisions）
- `.planning/research/PITFALLS.md` P1/P2/P5/P6/P10
- `server/knowledge/collection.py`, `graph_store.py`, `services/retrieval/hybrid_search.py`
- `server/knowledge/management/commands/reconcile_delivery_knowledge.py`（is_latest filter 先例）
