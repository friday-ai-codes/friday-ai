# Phase 34: 评论入图 + 片段→需求反查 - Context

**Gathered:** 2026-06-15
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous — recommendations auto-accepted)

<domain>
## Phase Boundary

把评论摄取进 knowledge 投影（评论入图），并提供 code chunk/模块 → 需求/文档的反查 API/MCP，依赖 v0.5 已交付的 `ChunkRegistry` 行号回填（`find_chunk_at`）。

覆盖需求：RREF-01（给定 code chunk/模块 → 反查关联需求/文档，片段→需求反查 API/MCP）、RREF-02（评论摄取进知识投影，可被检索关联到 WorkItem）。反查结果经 MCP/REST 暴露给 agent/客户端。
依赖：Phase 28（WorkItem）、Phase 29（评论事件流 + project_comment_tree）、v0.5 行号回填（`find_chunk_at`，已交付）。
不变量：INV-3（knowledge 是检索投影；`EntityKind` 字面值锁定，不新增枚举）、INV-6（操作态经 service，评论事件已在 Phase 29 收口）。
</domain>

<decisions>
## Implementation Decisions

### 片段→需求反查（Grey Area 1，RREF-01）
- 反查链路（复用既有图谱边 + chunk 反查，不新建底层）：
  1. 入参 (repository, file_path, line) 或 (chunk_id) 或模块/文件 → `services.chunk_lookup.find_chunk_at`（v0.5，fail-closed 排除）解析出 `chunk_id`(s)。
  2. `graph_store.chunk_in_edges(chunk_id)` 取指向该 chunk 的 `MODIFIES_CHUNK` 入边 → `code_change` 实体。
  3. 经 `graph_store.neighbors`/`traverse` 反向多跳：`code_change` ←`IMPLEMENTED_BY` `tech_plan` ←`HAS_PLAN` `work_item`；以及 `work_item` →`REFERENCES` `document`。收敛出关联的 **需求(work_item) / 文档(document)** 集合。
  4. **as-of 默认当前视图**（复用 Phase 33 bi-temporal：默认排除 `invalid_at` 已置位的过期 `MODIFIES_CHUNK` 边，历史边不污染当前反查）。
- 安全：沿用 `find_chunk_at` 的 fail-closed 排除（被排除文件不泄漏 chunk/行位置）；反查只读，不写库。
- 暴露面（RREF-01 成功标准 3）：① REST 端点（IsAuthenticated）；② MCP 工具（agent 可调，注册进既有 mcp_tools 体系，对齐既有 work_item_context / merge_request 等 MCP service 范式）。入参/出参结构化（chunk 标识 → [{work_item}, {document}] + 关联路径/relation）。

### 评论入图（Grey Area 2，RREF-02）
- `EntityKind` 字面值锁定（work_item/tech_plan/code_change/document，改名=数据迁移）——**不新增 comment 实体枚举**。
- 评论入图采用**enrich work_item 投影**：评论摄取进 knowledge 时，把 Phase 29 `project_comment_tree(work_item)` 投影出的当前评论树文本**并入 work_item 知识实体的投影内容**（作为 work_item 快照的评论段），使评论可被既有检索召回且天然关联到 WorkItem（INV-3：knowledge 投影，操作态评论事件仍在 Phase 29 的 `WorkItemCommentEvent` 事实源）。
- 触发：新增/扩展评论摄取路径（如 `feishu_comment` normalizer 或扩展 `feishu_work_item` 投影纳入评论段）——经既有 `get_normalizer` 注册表 + ingestion 管线（复用 Phase 30 normalizer 范式）。评论事件流更新后重投影 work_item 快照（hash 相等不翻版本，沿用既有范式）。
- 降级：评论投影缺料/失败 → work_item 快照缺评论段 + warning，不抛、不回滚（§1.4 范式）。
- 可测：评论入库后经既有检索能召回评论文本并关联到对应 work_item（RREF-02）。

### 接线与暴露（Grey Area 3）
- 反查 service 落 knowledge 或 delivery（Claude's Discretion，倾向 knowledge 检索面，因纯读图谱投影）；REST 端点沿用既有 delivery/knowledge api 风格；MCP 工具注册沿用 mcp_tools 既有 service + views + urls 范式。
- 反查结果对 agent/客户端暴露：MCP 工具返回结构化 {chunks, related_work_items, related_documents, paths}；REST 同形。

### 范围守护（Grey Area 4）
- 本 phase 是**复用既有图谱 + chunk 反查 + 评论投影**，不新建底层图谱/检索/chunk 机制；不新增 EntityKind；不做评论触发方案再生成（v0.7）。
- 反查依赖图谱边已存在（MODIFIES_CHUNK 由 diff 归档产、HAS_PLAN/IMPLEMENTED_BY 由方案/编码产）——本 phase 提供反查**查询**能力，不补建历史边。

### 异步 / 测试（Claude's Discretion 范围内）
- async-first；ORM `sync_to_async`；复用 graph_store async 遍历 + find_chunk_at。
- 测试：pytest-django + factory-boy + pytest-socket（图谱/chunk 反查既有测试范式，参考 tests/knowledge、test_chunk_lookup / find_chunk_at 测试）。守护：① (repo,file,line)/chunk → 反查到关联 work_item/document（RREF-01），含多跳路径；② 被排除文件 fail-closed 不泄漏（沿用 find_chunk_at 安全边界）；③ 过期 MODIFIES_CHUNK 边（invalid_at）默认不进当前反查（衔接 Phase 33 as-of）；④ 评论入图后检索召回评论文本 + 关联 work_item（RREF-02）；⑤ 评论投影降级缺段不缺实体；⑥ MCP/REST 端点结构化返回 + 鉴权。

### Claude's Discretion
- 反查 service 文件/命名、入参形态（(repo,file,line) vs chunk_id vs 模块路径）、多跳遍历用 neighbors 逐跳还是 traverse、评论段并入 work_item 投影的具体拼接、MCP 工具名、REST 路径 —— 由实现按既有约定决定。
- 评论入图走独立 `feishu_comment` normalizer 还是扩展 `feishu_work_item` 投影 —— 取最少改动且不破坏既有 work_item 快照者。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/services/chunk_lookup.py find_chunk_at(repo, file, line, *, branch_name)`（v0.5 IDX-02，fail-closed 排除，仅读 ChunkRegistry）—— 片段定位 chunk_id 入口。
- `server/knowledge/graph_store.py`：`chunk_in_edges`（chunk 入边）、`neighbors`（单跳）、`traverse`（多跳，bi-temporal as-of）、`invalidate_edge`——反查遍历。
- `server/knowledge/models.py`：`EntityKind`(locked: work_item/tech_plan/code_change/document)、`EdgeRelation`(HAS_PLAN/IMPLEMENTED_BY/REFERENCES/RELATES_TO/MODIFIES_CHUNK)、`generate_entity_id`。
- Phase 29 `project_comment_tree(work_item)`（当前评论树投影）+ `WorkItemCommentEvent`（评论事实源）—— 评论入图取材。
- Phase 30 `feishu_document` normalizer + `knowledge.sources.get_normalizer` 注册表 + ingestion 管线（hash 相等不翻版本）—— 评论投影范式。
- `server/mcp_tools/`（views/urls/service 范式：work_item_context_service / merge_request_service）—— MCP 工具注册。
- Phase 33 bi-temporal as-of（`amodifies_chunk_edges` business-only as-of，过期边默认排除）—— 反查当前视图。

### Established Patterns
- knowledge 检索投影只读、fail-closed 排除（rag_search / find_chunk_at）；EntityKind 锁定不新增。
- normalizer 注册 + ingestion + hash 不翻版本；缺料降级 + warning。
- MCP service + views + urls 范式；REST adrf + IsAuthenticated。
- ruff line 100；中文 docstring；async + sync_to_async。

### Integration Points
- `server/knowledge/`（反查 service + 评论投影 normalizer）或 `server/delivery/`（反查 API）。
- `server/mcp_tools/`（反查 MCP 工具 + 注册）。
- 复用 find_chunk_at / graph_store / project_comment_tree / get_normalizer。
- 下游：Phase 35 截图识别复用反查/召回；v0.7 评论触发方案再生成（消费评论投影 + approval 事件）。
</code_context>

<specifics>
## Specific Ideas

- 反查路径：chunk ←MODIFIES_CHUNK code_change ←IMPLEMENTED_BY tech_plan ←HAS_PLAN work_item；work_item →REFERENCES document。
- 评论入图 = 评论树文本并入 work_item 知识实体投影（不新增 EntityKind），检索可召回 + 关联 work_item。
- 衔接 Phase 33：反查默认当前视图（排除 invalid_at 过期边）。
- 安全：find_chunk_at fail-closed 排除贯穿反查，被排除文件不泄漏。
</specifics>

<deferred>
## Deferred Ideas

- 评论触发方案再生成 —— v0.7（本 phase 仅评论入图 + 反查）。
- 历史图谱边补建（MODIFIES_CHUNK/HAS_PLAN 缺失时回填）—— 非本 phase（提供查询，不补建）。
- 截图识别复用反查 —— Phase 35。
- 新增 comment EntityKind / 评论独立知识实体 —— 不做（EntityKind 锁定）。
- 真实图谱数据下的端到端反查人工验收 —— human-UAT。
</deferred>

---

*Phase: 34-reverse-lookup*
*Context gathered: 2026-06-15 via smart discuss (autonomous)*
