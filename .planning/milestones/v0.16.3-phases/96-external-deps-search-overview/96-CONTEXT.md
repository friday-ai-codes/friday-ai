# Phase 96: 外部依赖进检索与总览 - Context

**Gathered:** 2026-07-01
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous — grey areas auto-decided，决策原则「优雅、好用」，用户已授权不逐项确认)

<domain>
## Phase Boundary

让全部类型的外部依赖工件（`initiatives.Artifact`：PRD/需求文档、feature list、研发 Spec、UI 稿、UI 评审、埋点文档、埋点评审、复盘）都能在「知识」体系里被**发现**：

1. 全部 `ArtifactType` 登记为可发现条目（ragable 走既有 `delivery_knowledge` 向量摄取；非 ragable 至少登记 title/type/url 进关键词可搜索层）。
2. `/knowledge` 搜索 Tab 命中工件时标注类型 + 一键跳查看，跨项目按 `access_scope` 过滤。
3. `KnowledgeDashboard` 增加「交付文档 / 外部依赖」区块（按类型计数 + 入口 + 即时搜索）。

**边界内**：登记/摄取补全、搜索结果呈现、总览区块。
**边界外**（后续阶段）：知识树视图（Phase 97）、工件↔仓库/能力关联建边（Phase 98）、星图/交叉入口可视化（Phase 99）。
</domain>

<decisions>
## Implementation Decisions

### 非 ragable 工件的可发现登记（KDEP-01）
- 非 ragable 类型（UI 稿 external_link 等无正文可 embed）在摄取入口 `ArtifactService` 落一条**轻量知识实体登记**：建/更 `KnowledgeEntity(kind="document")` + `REFERENCES → project` 边，承载 title/type/carrier/url 元数据，但**不进 Qdrant 向量**（无正文）。保证总览计数、搜索关键词层、后续树视图都能覆盖全部类型、零遗漏。
- 复用既有 `knowledge/sources/artifact.py` normalizer，扩展为：ragable → 实体 + chunk + embed（不变）；非 ragable → 仅实体 + 元数据（新增分支）。**单一写入入口**（INV-6）、`call_source` 观测、fail-soft 不反噬主流程。
- 搜索关键词层命中：`ProjectSearchService._keyword_search` 已 grep `Artifact.title/content_ref`；知识全局搜索侧补 title/type/url 关键字命中（非 ragable 无向量，靠关键词兜底，召回弱属预期，已记录）。
- 幂等：以 `artifact_id` 为准 upsert，重复摄取不产生重复实体/边。

### 搜索结果呈现（KDEP-02）
- 搜索结果项对工件来源统一加**类型徽标**（PRD / 埋点评审 / UI…，取 `ArtifactType.name`）+ 来源图标，视觉与现有知识搜索结果项一致（复用现有卡片样式，仅加 badge slot）。
- 一键跳转查看：复用 `ArtifactViewView` 语义——feishu_doc/markdown 走「查看」弹窗（markdown 渲染）、external_link 直接新标签打开飞书/外链。结果项主操作按载体自适应（「查看」或「打开飞书」）。
- 跨项目过滤：搜索链路强制走 `knowledge/access_scope.py`，只返回当前用户可见 project 的工件（`access_scope`），越权不可见。
- 结果项标注所属项目名（跨项目搜索时用户能分辨归属）。

### 知识总览「交付文档」区块（KDEP-03）
- 在 `KnowledgeDashboard.vue` 新增独立区块「交付文档 / 外部依赖」，与现有「仓库 / 域指标」区块并列、风格一致（同一卡片/网格系统、同一图标语言）。
- 内容：按 `ArtifactType` 分组的计数（如 PRD ×N、埋点 ×M）+ 每类入口（点击进搜索预筛该类型 / 或后续树视图）+ 区块内即时搜索框（沿用 Dashboard 现有 Fuse.js 即时搜索模式，客户端过滤已加载条目）。
- 计数与列表数据走**新增后端聚合接口**（按用户可见 project 聚合 Artifact 按类型分组计数），带权限过滤；前端 `web/src/api/knowledge.ts` 加对应方法。避免前端逐项目拉全量。
- 空态优雅：无交付文档时展示引导文案 + 指向作战室「外部依赖」维护入口，不显示空网格。

### 权限、观测与兼容（横切）
- 全部聚合/搜索走 `access_scope`，与既有知识权限模型一致；跨项目聚合分页/截断保护（沿用 `max_nodes`/limit 思路）。
- 观测：新增摄取分支、聚合接口、搜索命中赋 `call_source` 与 `component`，结构化 started/completed/failed + `duration_ms`，category=caller（接口）/sampling（高频摄取步骤）。
- async ORM 一律 `sync_to_async`；不改 `delivery_knowledge` 向量 schema（只加实体/元数据/边）。i18n 文案默认中文，接入既有 `vue-i18n`。

### Claude's Discretion
- 后端聚合接口的具体 URL 命名、序列化字段、前端组件拆分粒度、徽标配色映射由 plan/execute 阶段按既有约定自定，遵循「优雅、好用」：复用现有组件与样式令牌，最少新增面积、最一致的视觉。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- 后端摄取：`initiatives/services/artifact_service.py`（`_maybe_schedule_ingestion`，写入唯一入口 INV-6）、`knowledge/sources/artifact.py`（normalizer，`sources/__init__.py` 已注册 `artifact`）。
- 后端搜索：`DeliveryKnowledgeSearchService`（`knowledge/retrieval.py` + `vector_recall.py`，hybrid + 强制 is_latest + 权限 filter）；`ProjectSearchService._keyword_search`（已 grep Artifact）。
- 图谱写入收口：`ProjectKnowledgeGraphService` + `knowledge/graph_store.py`（`add_edge` / `EdgeSpec`）；`KnowledgeEntity.kind="document"`、`KnowledgeEdge.relation="REFERENCES"`。
- 权限：`knowledge/access_scope.py`。
- 工件在线查看：`ArtifactViewView` / `initiatives/.../artifact_view.py`。
- 前端：`web/src/pages/knowledge/index.vue`（Tab overview/tree/ingest/search）、`KnowledgeDashboard.vue`、`web/src/api/knowledge.ts`、`web/src/api/artifacts.ts`、`web/src/components/project/workbench/DependenciesSection.vue`（查看/飞书打开按钮参考）。

### Established Patterns
- 摄取经 durable 调度 `aschedule_ingestion(source_kind="artifact")`；normalizer 注册表模式。
- 知识搜索走 `GET /api/knowledge/search/`；Dashboard 前端 Fuse.js 即时搜索聚合。
- REST：`/api/projects/{id}/artifacts/` + `.../artifacts/{id}/view/`。
- 结构化日志 kv + `call_source`/`component`；async ORM `sync_to_async`。

### Integration Points
- 摄取分支扩展点：`ArtifactService._maybe_schedule_ingestion` / `knowledge/sources/artifact.py`。
- 新增聚合接口挂 `server/knowledge/`（或 initiatives 知识子路由）+ 前端 `knowledge.ts`。
- 总览区块挂 `KnowledgeDashboard.vue`；搜索结果项改 `/knowledge` search Tab 结果渲染。
</code_context>

<specifics>
## Specific Ideas

- 「总览」明确指 `/knowledge` 的 `KnowledgeDashboard`（用户已确认，见 research §2.2）。
- 非 ragable 无正文 → 关键词层仅 title/type/url，搜索命中弱属预期（research §4）。
- 尽量不改向量 schema，本阶段以「补登记 + 搜索呈现 + 总览区块」为主。
</specifics>

<deferred>
## Deferred Ideas

- 交付文档知识树视图 → Phase 97。
- 工件↔仓库/能力/关键词建边 → Phase 98。
- 星图/实体详情/作战室交叉入口可视化 → Phase 99。
- 关键词/能力升级为一等实体表（KDEPX-01）→ v2 再评估。
</deferred>
