# Phase 15: 时间感知混合检索 - Context

**Gathered:** 2026-06-12
**Status:** Ready for planning
**Mode:** Smart discuss — autonomous auto-accept（全部推荐答案采纳）

<domain>
## Phase Boundary

任意新需求文本都能召回相似历史交付及完整迭代轨迹，结果始终是最新有效版本、带出处与时间限定，且按权限过滤。

本阶段交付（RETR-01..07, ENH-02）：
- `DeliveryKnowledgeSearchService`（或等价命名）：统一检索 service，向量召回 + 1–2 跳图扩散 + 时间衰减重排
- 相似需求召回 top-K，附带关联技术方案、代码变更与 MR 链接
- 二阶段 LLM 复评分级（重复/相关/无关）+ 一句话理由（ENH-02）
- 从任一实体双向查看关联上下游（需求→方案→diff→MR）
- 完整迭代轨迹查询（方案 v1→vN + 各次编码时间线），纯 PG 版本链、不依赖向量库
- 默认仅命中 `is_latest=true`；被取代内容需显式 `include_superseded` 才返回并标注 `superseded by vN`
- 每条结果附出处 metadata；权限过滤在 service 层内强制（user → 可见 project/repo 集合）

不在本阶段：MCP/chat/workflow 入口暴露（Phase 16）、前端只读页（Phase 16）。

</domain>

<decisions>
## Implementation Decisions

### 检索 Service 契约
- 新建 `server/knowledge/retrieval.py`（或 `server/knowledge/search_service.py`）作为检索唯一收口；REST/MCP/chat 入口 Phase 16 只调用此 service
- 核心方法：`search_similar(query, *, user, top_k, entity_kinds, project_ids, as_of, include_superseded)` + `get_related(entity_id, *, user, direction, max_hops)` + `get_timeline(entity_id, *, user)`
- 返回结构化 Pydantic/dataclass DTO（非裸 dict），含 score、entity、version、metadata、provenance_links、superseded_hint
- fail-closed：无 user 或 user 无可见 project → 空结果（非 AllowAny 兜底）

### 向量召回路径
- 查询 `delivery_knowledge` collection（`DELIVERY_KNOWLEDGE_COLLECTION`），复用 `EmbeddingService` + `QdrantService` hybrid dense+sparse
- **强制** Qdrant filter：`is_latest=true`（P1 防线，不可绕过）；叠加 user 可见 `project_id`/`repository_id` payload filter（P6）
- 默认 `entity_kind` 过滤偏向 `work_item`（相似需求召回），但参数可扩；分路召回：work_item/tech_plan 一路、code_change 一路，RRF 融合（P5 防单类型刷屏），每路独立 top-k 配额
- 复用既有 `Fusion.RRF` 模式（参照 `services/retrieval/` 与 qdrant hybrid query）

### 图扩散与时间重排
- 向量命中实体作为 anchor，经 `graph_store.traverse` / `neighbors` 做 1–2 跳扩散（HAS_PLAN / IMPLEMENTED_BY / RELATES_TO），深度默认 2、可配
- 图遍历只走 GraphStore（有效性过滤内置，P2）；`as_of` 参数透传 GraphStore `as_of` 语义
- 时间衰减作为**检索后 re-rank** 显式项：`final_score = α·vector_score + β·recency(event_time)`，半衰期默认 90 天、α/β 集中配置（`friday/settings.py` 或 SystemSetting），不写进向量
- 已失效实体/边由 GraphStore 默认过滤；`include_superseded=false` 时 PG 侧也过滤 `is_latest=false`

### 迭代轨迹（RETR-03）
- `get_timeline` 纯 PG：`KnowledgeEntityVersion` 按 version 升序 + 关联 `KnowledgeEdge` 挂接的 code_change 按 `event_time` 排序
- 不查 Qdrant；版本链经 `entity_id` + `version` 字段；输出时间线节点含 kind、version、title 摘要、valid 区间、source 链接

### LLM 二阶段复评（ENH-02）
- 向量+图融合 top-K 之后、返回前，对候选做轻量 LLM 分级（duplicate / related / unrelated）+ 一句话理由
- 复用既有 provider 解析（`services/provider_config`），模型可配；LLM 失败降级为仅向量分数排序（不阻塞主链路）
- prompt 中文；输入截断（每候选 title+摘要 ≤500 字）

### 权限与 metadata（RETR-06/07）
- service 签名强制 `user: User`；内部调用 `PermissionService`（或既有 project/repo 可见性 helper）解析 allowed project_ids
- Qdrant filter + PG queryset 双重收窄；调用方传入的 project_ids 只能**收窄**不能放宽
- metadata 必含：entity_kind、version、valid_at/invalid_at、source_kind、source_id、origin、event_time、feishu_url/mr_url/session_link（按 kind 填充）

### Claude's Discretion
- 具体类名/文件拆分、RRF 配额比例、评测夹具位置由 planner/executor 按 codebase 惯例决定
- 跨语言摘要向量（P5 建议）本阶段可选增强：若工期紧可先用 entity_kind 分路召回 + RRF，摘要在 Phase 16 前补

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `knowledge/collection.py`：payload schema 单一事实源（`is_latest`/`project_id`/`event_time` 等索引字段）
- `knowledge/graph_store.py`：`traverse`/`neighbors`/`chunk_in_edges`，`as_of` 支持，有效性过滤内置
- `knowledge/models.py`：EntityKind、EdgeRelation、KnowledgeEntityVersion 版本链
- `knowledge/vector_ops.py`：写路径参考；读路径应对称走 QdrantService
- `services/retrieval/hybrid_search.py`：HybridSearch 编排范式（wave 并发、RRF、budget trim）
- `services/retrieval/token_budget.py`：`trim_to_budget`/`split_budget`（diff 结果裁剪）
- `services/qdrant_service.py`：hybrid query、payload filter、Fusion.RRF
- `services/indexer.py` / `EmbeddingService`：向量生成

### Established Patterns
- 知识路径写操作收口（vector_ops、graph_store）；检索应同样单一 service 收口
- 测试：knowledge 套件 + mock Qdrant + 图 fixture；越权用例 A 用户查 B 项目 → 0 结果
- structlog 事件命名：`knowledge_search_*`

### Integration Points
- Phase 16 将接线 MCP/chat/workflow/npm skill——本阶段只交付 service + 可选内部 REST（如 `knowledge/api/`）供测试
- `graph_store` keyword-only 参数已预留 project scope 扩展位

</code_context>

<specifics>
## Specific Ideas

- ROADMAP 研究标记：时间衰减半衰期默认 90 天，需 20–50 条评测 query 夹具（可先用合成 fixture，真实数据后续补）
- PITFALLS P1/P2/P5/P6 防线必须在 plan 中显式列为 must_haves

</specifics>

<deferred>
## Deferred Ideas

- MCP/chat/workflow/npm 四入口暴露 → Phase 16
- 前端只读详情页与时间线 UI → Phase 16
- as-of 工具参数对外暴露 → Phase 16（service 层本阶段实现 `as_of` 参数即可）

</deferred>
