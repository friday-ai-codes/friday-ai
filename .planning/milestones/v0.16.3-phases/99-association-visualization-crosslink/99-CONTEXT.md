# Phase 99: 关联可视化与交叉入口 - Context

**Gathered:** 2026-07-01
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous — grey areas auto-decided，决策原则「优雅、好用」，用户已授权不逐项确认)

<domain>
## Phase Boundary

把 Phase 98 建立的工件↔仓库/能力/关键词关联**可视化**到星图与知识图谱，并在作战室外部依赖区与知识体系之间打通**双向交叉入口**（收官阶段）。

1. KDEP-10：项目关系星图 `_build_project_galaxy` 扩展纳入 `artifact` 节点与边（`HAS_ARTIFACT` / `ARTIFACT_REPO` / `ARTIFACT_CAPABILITY`）；关联仓库来源并入 `RepoAssociation`（不再仅来自 MR）。
2. KDEP-11：知识实体图 / 实体详情页展示工件↔仓库/能力/关键词关联；仓库/能力视角反向展示相关交付文档（交叉入口，双向可导航）。
3. KDEP-12：作战室「外部依赖」区与知识体系打通——查看工件处可跳转到其知识实体 / 关联视图，形成「作战室 ↔ 知识」闭环。

**边界内**：星图扩展、实体图/详情关联展示（复用 Phase 98 查询）、作战室↔知识跳转。
**边界外**：新建关联真相源（Phase 98 已完成，本阶段只读展示）；改向量 schema。
</domain>

<decisions>
## Implementation Decisions

### 星图纳入 artifact（KDEP-10）
- 扩展 `_build_project_galaxy`（`server/initiatives/views.py`）：在既有 project↔feature↔work_item↔MR↔repo 聚合基础上，纳入 `artifact` 节点（每个可见工件一节点，带 type/carrier/title）与边：`HAS_ARTIFACT`（project→artifact）、`ARTIFACT_REPO`（artifact→repo，来源 Phase 98 的 RELATES_TO 边）、`ARTIFACT_CAPABILITY`（artifact→能力节点路径，来源边 metadata.node_paths）。
- 关联仓库来源并入 `RepoAssociation`（verified）：星图的 project↔repo 关联不再仅来自 MR，读 Phase 98 同步的派生边 / RepoAssociation verified（与图谱一致）。
- 复用 Phase 98 查询服务（`ArtifactAssociationService` / `graph_store.neighbors`）取关联，不重复实现遍历；节点上限保护沿用 `max_nodes`（artifact 节点纳入总预算，超限截断并标注）。
- 权限：星图聚合走既有 access_scope / 项目可见性，越权工件/仓库不出现。
- 观测：聚合扩展 best-effort，artifact 分支异常吞掉不反噬既有星图；结构化 kv + duration_ms + 纳入的 artifact/边计数。

### 实体图 / 详情页关联展示（KDEP-11）
- 知识实体详情页（`web/src/pages/knowledge/entities/[id].vue`）+ 实体关系图：当实体为 document（工件）时，展示其关联的仓库 / 能力（node_paths）/ 关键词（读 Phase 98 关联查询：`GET /api/knowledge/artifacts/{id}/associations/`）。
- 反向：仓库 / 能力视角实体详情反向展示「相关交付文档」（复用 Phase 98 反向查询服务，必要时补一个反查接口 `GET /api/knowledge/repositories/{id}/artifacts/` 或复用现有实体图遍历——取最小面积优雅方案）。
- 双向可导航：关联项均为可点击链接，工件→实体详情、仓库/能力→其详情，形成闭环。
- 展示复用既有实体详情的关联区块 / 关系图组件样式，类型徽标复用 Phase 96、载体图标复用 Phase 97，视觉一致；空态优雅（无关联时简洁提示，不显示空块）。

### 作战室 ↔ 知识交叉入口（KDEP-12）
- 作战室「外部依赖」区（`DependenciesSection.vue` / `ProjectMaterialsPanel`）的每个工件查看处，加一个「知识」入口：跳转到该工件的知识实体详情 / 关联视图（携带 artifact 对应 entity id）。
- 反向已由 KDEP-11 覆盖（知识实体 → 可回看工件）。形成「作战室 ↔ 知识」双向闭环。
- 入口样式低调优雅：与既有「查看 / 飞书打开」按钮并列的次级操作（图标 + tooltip），不喧宾夺主。
- 工件→entity id 映射复用 Phase 96/98 的 `generate_entity_id`（document 实体 id 规则），前端拿 artifact_id 拼实体路由或后端 view 响应带 entity_id（取更优雅者）。

### 横切
- 本阶段**只读展示**，不新建/改写关联真相源（Phase 98 已收口）；不改向量 schema。
- async ORM `sync_to_async`；星图/查询 access_scope 权限一致；节点上限保护。
- 前端类型安全、i18n 默认中文、新动态图标 safelist、复用 Phase 96/97/98 的 helper 与样式令牌。
- 观测：新增/扩展接口 category=caller、component=knowledge/initiatives，started/completed/failed + duration_ms，best-effort。

### Claude's Discretion
- 星图 artifact 节点视觉（颜色/形状/大小）、是否新增反查接口 vs 复用实体图遍历、作战室入口具体图标与落点、entity_id 暴露方式由 plan/execute 按既有约定自定，遵循「优雅、好用」：复用既有可视化组件与查询服务、最少新增、最一致、闭环顺滑。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- 星图：`server/initiatives/views.py`（`_build_project_galaxy` / `ProjectGalaxyView`，读时聚合 project↔feature↔work_item↔MR↔repo）；前端 3D 星图（`3d-force-graph` + `three`，`KnowledgeDashboard` 已用）。
- 关联查询（Phase 98）：`server/knowledge/artifact_associations.py`（`ArtifactAssociationService` 正/反向 + access_scope）、`GET /api/knowledge/artifacts/{id}/associations/`、`graph_store.neighbors`。
- 图谱边（Phase 98）：`KnowledgeEdge(RELATES_TO, metadata{source,artifact_id,node_paths,keywords,score})` + verified RepoAssociation 派生边。
- 实体详情：`web/src/pages/knowledge/entities/[id].vue`（元数据/版本时间线/关联图）；类型徽标（Phase 96）、载体图标（Phase 97）、查看 helper（`artifactsApi.view`）。
- 作战室外部依赖：`web/src/components/project/workbench/DependenciesSection.vue`（`ProjectMaterialsPanel` 复用，已有查看/飞书打开按钮）。
- 权限：`server/knowledge/access_scope.py`；entity id 规则 `generate_entity_id`。

### Established Patterns
- 星图读时聚合 + max_nodes 保护；知识接口挂 `server/knowledge/api/`；前端知识页/实体页 + api/knowledge.ts；结构化 kv 观测 + best-effort。

### Integration Points
- 星图扩展：`_build_project_galaxy`（后端）。
- 实体详情关联区块 + 反查：`entities/[id].vue` + `knowledge/api/`（复用/补反查）+ `api/knowledge.ts`。
- 作战室入口：`DependenciesSection.vue`（跳知识实体）。
</code_context>

<specifics>
## Specific Ideas

- 星图关联仓库来源并入 RepoAssociation（不再仅 MR）——KDEP-10 硬约束，与 Phase 98 派生边一致。
- 本阶段只读展示，复用 Phase 98 查询服务，不重复遍历实现。
- 交叉入口双向闭环：作战室→知识实体、知识实体/仓库/能力→相关工件。
</specifics>

<deferred>
## Deferred Ideas

- 关键词/能力升级为一等实体（独立节点可视化）→ v2（KDEPX-01）。
- 关联编辑/人工订正 UI → 未来里程碑（本阶段只读）。
- 星图超大规模布局性能优化 → 若数据量爆炸再评估（当前 max_nodes 保护足够）。
</deferred>
