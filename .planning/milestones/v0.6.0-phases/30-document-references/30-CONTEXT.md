# Phase 30: Document + REFERENCES 边 - Context

**Gathered:** 2026-06-15
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous — recommendations auto-accepted)

<domain>
## Phase Boundary

区分外部飞书文档与内部生成文档，落独立 `Document`/`DocumentVersion` 操作态实体（delivery app）；新增 `feishu_document` normalizer 把飞书 docx（PRD/技术方案）摄取入库并建 `REFERENCES` 边（knowledge 投影）关联到对应 `WorkItem`；给定带 `prd_url` 的 `WorkItem` 可经 Document 实体检索到其 PRD 正文快照。

覆盖需求：DOC-01（区分 external_feishu/internal_generated + PRD/技术方案落独立 Document）、DOC-02（feishu_document normalizer 摄取 docx + REFERENCES 边关联 WorkItem）。
依赖：Phase 28（Document.work_item FK 关联脊柱 + REFERENCES 操作态对应）。
不变量：INV-3（knowledge 是投影；Document 操作态实体在 delivery，REFERENCES 边在 knowledge 投影）、INV-6（Document 落库经 delivery 服务入口）。
</domain>

<decisions>
## Implementation Decisions

### Document/DocumentVersion 模型归属与字段（Grey Area 1，DOMAIN §3/§12.5）
- 操作态实体落 **delivery app**（`server/delivery/models/document.py`），re-export 于 `models/__init__.py`——与 WorkItem 脊柱同 app（DOMAIN §0：操作态聚合在 delivery）。
- `Document`：`id(UUID)`、`document_type(choices: prd|tech_plan|release_note|sdd_spec|other)`、`source_kind(choices: external_feishu|internal_generated)`、`external_ref(CharField blank)`（飞书 doc token）、`canonical_url(URLField blank)`、`content_storage(choices: snapshot|reference|both)`、`current_version FK(DocumentVersion, null, SET_NULL)`、`last_synced_at(DateTimeField null)`、`writeback_allowed(Bool default False)`、`work_item FK(delivery.WorkItem, null, SET_NULL)`、`feishu_tenant(CharField blank)`（多租户区分，如 acme）、`created_at`/`updated_at`。
- `DocumentVersion`：`id(UUID)`、`document FK(CASCADE)`、`version(Int)`、`supersedes FK(self, null, SET_NULL)`、`content(TextField)`、`content_hash(CharField)`、`created_at`。`unique_together(document, version)`。
- 去重/幂等键：external_feishu 文档按 `(feishu_tenant, external_ref)`（doc token）唯一定位；内部生成按自身规则。版本：内容 hash 相等不产生新版本（沿用 knowledge 既有"hash 相等不翻版本"范式）。

### DOC-01 区分外部/内部 + PRD/技术方案落独立实体（Grey Area 2）
- PRD（`prd_url` 别名字段 / field_000001）→ `Document(document_type=prd, source_kind=external_feishu, content_storage=both)`；技术方案 → `document_type=tech_plan`。
- 内部生成文档（上线说明/SDD spec）：`source_kind=internal_generated`、可 `writeback_allowed`——本 phase **只立模型字段位**，实际内部生成文档产出是后续里程碑（v0.7+），本 phase 不造内部文档。
- content_storage：external 飞书文档存 `both`（快照 + canonical_url 引用），飞书为权威。

### feishu_document normalizer + REFERENCES 边（Grey Area 3，DOC-02）
- 新增 `server/knowledge/sources/feishu_document.py` normalizer，注册进既有 `knowledge.sources.get_normalizer` 注册表（与 feishu_work_item / coding_plan 等同款）。
- 摄取输入：work item 三元组（或 doc token + work item 锚），从 work item 的 `prd_url`/`tech_doc_url` 提取 doc token（复用既有 `_extract_doc_token`），经既有 `create_feishu_doc_client_for_project` + `get_document_content(token)` 拉正文（复用 feishu_work_item normalizer 既有取材路径，不重写）。
- 产出：① **操作态** Document/DocumentVersion 落库（经 delivery DocumentService 单一入口，INV-6）+ `work_item` FK 关联；② **knowledge 投影** `KnowledgeEntity(kind=document)` + `KnowledgeEdge(relation=REFERENCES)` 连 work_item 实体 → document 实体（复用既有 `EntityKind.DOCUMENT`/`EdgeRelation.REFERENCES`，已在 knowledge/models.py 定义）。
- 降级范式：doc 拉取失败 → 快照缺正文段 + warning，事件照常产出（沿用 §1.4 / feishu_work_item `_fetch_doc_body` 降配，不抛、不回滚）。

### 操作态写入入口（Grey Area 4，INV-6）
- Document/DocumentVersion 落库经 delivery 服务单一入口（如 `DocumentService.upsert_from_feishu(work_item, doc_token, document_type, ...)`），禁旁路写表；可加 INV-6 grep 守护（沿用 Phase 28/29 范式，精确锚定无误伤）。
- 与 WorkItemService 关系：Document 关联 work_item，但 Document 写入独立 service；WorkItemSyncState 的 `prd_body`/`tech_doc` facet 在文档摄取成功时记 complete（对齐 §1.4 facet 完整度）。

### 检索 PRD 正文快照（Grey Area 5，DOC-02 成功标准）
- 给定带 `prd_url` 的 WorkItem，可经 Document 实体取 PRD 正文快照：提供查询路径（`Document.objects.filter(work_item=..., document_type=prd)` → current_version.content）+ 最小只读 REST（IsAuthenticated，沿用 delivery REST 风格）。

### 与既有 feishu_work_item normalizer 的关系（Grey Area 6，INV-3）
- 既有 `feishu_work_item` normalizer 把 PRD/技术方案正文**内联进 work item 快照**——保留不动（INV-3，不破坏既有投影）。
- 本 phase 新增的 Document 实体是**独立操作态实体**（可版本化、可被 REFERENCES 边引用、可写回），与 work item 快照内联正文并存；不强行迁移既有内联正文。后续 phase（32 一键摄取）可经 Document 路径摄取。

### 异步 / 测试（Claude's Discretion 范围内）
- async-first，ORM `sync_to_async`；摄取沿用 background runner / ingestion 注册表范式。
- 测试：pytest-django + factory-boy + respx（mock get_document_content / feishu doc client）+ pytest-socket。守护：① external/internal 区分 + PRD/技术方案落独立 Document（DOC-01）；② feishu_document normalizer 建 Document + REFERENCES 边关联 work_item（DOC-02）；③ 给定 prd_url 的 work_item 经 Document 取到 PRD 正文快照；④ doc 拉取失败降配缺段不缺实体；⑤ 内容 hash 相等不翻新版本；⑥ INV-6 Document 旁路写表守护。

### Claude's Discretion
- DocumentService 命名/拆分、normalizer 输入签名（三元组 vs doc token + 锚）、内容 hash 算法（复用 knowledge 既有 content_hash 方式）、REST 端点形状、内部生成文档字段是否本 phase 全建（建模型位即可）—— 由实现按既有约定决定。
- 多租户 feishu_tenant 的取值来源（doc URL host 派生 vs 配置）—— 取能稳定区分租户者。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/knowledge/models.py`：`EntityKind.DOCUMENT`、`EdgeRelation.REFERENCES` 已定义；`generate_entity_id` 确定性实体 id 唯一入口；KnowledgeEntity/KnowledgeEdge/版本化（hash 相等不翻版本）范式。
- `server/knowledge/sources/feishu_work_item.py`：`_extract_doc_token`（剥 query 取 token）、`_fetch_doc_body`（拉正文降级）、doc client 取材路径 —— 直接复用。
- `agents/tools/feishu_doc_tools.create_feishu_doc_client_for_project` + `get_document_content(token)` —— 飞书 docx 正文拉取（开放平台/租户域，凭证经既有 service）。
- `server/knowledge/ingestion.py`：`get_normalizer(source_kind)` 注册表 + `IngestionRequest`/`IngestionEvent` + background 摄取范式 —— 新 normalizer 注册于此。
- Phase 28 `server/delivery/`（models/ 包 + service + api + migration + INV-6 grep 守护范式）+ WorkItem 模型（work_item FK）+ WorkItemSyncState（prd_body/tech_doc facet）。

### Established Patterns
- knowledge normalizer 注册 + 降配不 raise + warning；hash 相等不翻版本（needs_revector）。
- delivery app models/ + service 单一写入 + REST + migration（Phase 28/29 模板）。
- async DRF + sync_to_async；ruff line 100；中文 docstring；structlog。

### Integration Points
- `server/delivery/models/`（新增 document）+ migration；`server/delivery/services/`（DocumentService）；`server/delivery/api/`（PRD 快照只读端点）。
- `server/knowledge/sources/feishu_document.py`（新 normalizer）+ 注册到 `knowledge/sources/__init__.py`。
- KnowledgeEdge(relation=REFERENCES) 连 work_item↔document 实体。
- 下游：Phase 32 一键摄取经 Document 路径摄取 PRD/技术方案；Phase 34 文档反查。
</code_context>

<specifics>
## Specific Ideas

- DOMAIN §3 / §12.5 是 Document/DocumentVersion 建模权威；§16 实测：PRD=field_000001(alias prd_url)→`<tenant>.feishu.cn/docx/<doc_token>`，多租户（acme 等）经开放平台 token，与项目 plugin token 不同域。
- REFERENCES 边语义：work_item →(REFERENCES)→ document（引用文档），knowledge 投影。
- INV-3：Document 是 delivery 操作态实体（带 work_item FK），REFERENCES 边是 knowledge 投影——两层并存不混淆。
</specifics>

<deferred>
## Deferred Ideas

- 内部生成文档（上线说明/SDD spec）的实际产出 + writeback 回写飞书 —— v0.7+（本 phase 仅建模型字段位）。
- 一键摄取编排经 Document 路径 —— Phase 32。
- 文档反查（片段→文档/需求）—— Phase 34。
- 既有 feishu_work_item 内联正文迁移到 Document 实体 —— 非本 phase（并存，不强迁）。
- 飞书文档真实多租户凭证/端点正确性人工验收 —— human-UAT（需真实开放平台凭证）。
</deferred>

---

*Phase: 30-document-references*
*Context gathered: 2026-06-15 via smart discuss (autonomous)*
