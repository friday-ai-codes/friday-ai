# P4 技术方案：项目级关系星图

**所属里程碑：** 项目作战室 / 工作区大盘（见 `MILESTONE-PROPOSAL.md`）
**Phase：** P4（Wave 3）
**产出方式：** Cursor 技术方案（非 GSD）
**定稿：** 2026-06-27 · 状态：Ready to execute（可与 P2/P3 并行）

---

## 1. 目标

在大盘上呈现一张**项目级关系星图**：展示 feature ↔ work item ↔ 仓库 ↔ 依赖 ↔ 知识 ↔ 文档 的关联；点击节点看详情/跳转；可聚焦某 feature 看它关联了什么。新建独立后端端点（已确认 D），前端复用现有力导可视化。

## 2. 范围

**做：** 新建 `GET /projects/{id}/galaxy/` 聚合端点 + 序列化 + 权限/采样/观测；前端 `projectGalaxy` API + 星图卡片(可放大) + 节点详情/跳转/聚焦 + a11y 兜底。
**不做：** 改动 codegraph galaxy / KLINK 既有端点、迭代、编辑（P5）。
**不破坏：** 现有 `/codegraph/galaxy/`、`/projects/{id}/graph/`。

## 3. 现状基线（已核对）

- 代码级星图：`/codegraph/galaxy/`（`web/src/api/galaxy.ts`：node/edge/detail/search，类型完备）+ `3d-force-graph` + `three`。
- 项目知识关联：`/projects/{id}/graph/`（`projectsApi.graph`，KnowledgeEdge/ProjectRelation，KLINK-02）。
- 项目数据源（聚合用）：feature-list（模块→功能点→验收项）、work-items(含状态)、项目关联仓库、依赖(artifacts/links)、`ProjectRelation`/`KnowledgeEdge`、ProjectDoc(5 文件)。
- 后端项目路由：`server/initiatives/urls.py`（已有 graph/feature-list/work-items/workspace 等）。

## 4. 任务分解（文件级）

### T1 — 后端端点
- `server/initiatives/urls.py`：新增
  `path("<uuid:project_id>/galaxy/", ProjectGalaxyView.as_view(), name="project-galaxy")`。
- `server/initiatives/api/views.py`：`ProjectGalaxyView`（adrf，IsAuthenticated + 项目成员 fail-closed）：
  - 聚合 nodes（type ∈ `project|feature|work_item|repository|dependency|knowledge|doc`），edges（feature→work_item 派生、work_item→repository 关联、project→repository/dependency、KnowledgeEdge 知识、feature→knowledge、doc 关联）。
  - 复用既有 service：feature-list 构建、work-items、仓库关联、依赖、`ProjectRelation`/`KnowledgeEdge`、ProjectDoc 列表。
  - 规模控制：`max_nodes`（默认/上限）+ 采样 + `meta{total_nodes,total_edges,sampled}`（仿 `GalaxyMeta`）。
- 序列化：`ProjectGalaxyNodeSerializer{id,type,label,ref_id,meta}` / `ProjectGalaxyEdgeSerializer{source,target,relation,weight?}` / `ProjectGalaxyMetaSerializer`。
- 观测：`caller` started/completed/failed + `duration_ms` + `component=projects.galaxy` + 绑定 user；若聚合触发 RAG 召回则写 `RetrievalTrace`（纯结构化关联则无需）。

### T2 — 前端 API
- `web/src/api/projectGalaxy.ts`（或并入 projectWorkspace）：`getGalaxy(projectId, {maxNodes?}) -> ProjectGalaxyResponse`；类型对齐后端 snake_case。

### T3 — 星图卡片组件
- `web/src/components/project/warroom/ProjectGalaxyCard.vue`：
  - 复用 `3d-force-graph`（或现有 galaxy 可视化封装，若有 `GalaxyGraph` 组件优先复用）。
  - 节点按 type 配色（沿用现有 design token 语义色，不引入新色板）/ 形状/大小(degree)。
  - 交互：hover 高亮 1-hop；点击 → 详情面板（名称/类型/关联列表）+ 跳转（feature→Feature 区、repo→仓库、doc→文档区、work_item→工作项区）；支持"聚焦某 feature"过滤其 1~2 hop 子图。
  - 放大：Dialog 全屏（z-100）。
- 嵌入 P1 大盘"关系星图"占位卡。

### T4 — 性能与可访问性
- 力导：节点数超阈值采样 + 冷却/暂停；`prefers-reduced-motion` 时禁初始抖动、给静态布局。
- a11y：图非屏幕阅读器友好 → 提供"节点列表/文本摘要"兜底视图（`screen-reader-summary`）；空态("暂无关联")/加载骨架/错误重试。
- 防 CLS：卡片固定高度/aspect-ratio。

### T5 — i18n
- `projects.warroom.galaxy.*`：标题、节点类型名、详情面板标签、聚焦/重置、空态/错误、放大 aria-label。

### T6 — 测试
- 后端：聚合 nodes/edges 类型正确；非成员 403/404；采样/`max_nodes` 生效；观测事件。
- 前端：渲染/空态/加载/错误；节点点击详情 + 跳转；聚焦过滤；reduced-motion 兜底。

## 5. 验收标准
- 大盘展示项目关系星图，含 feature/work item/仓库/依赖/知识/文档节点与关联边。
- 点击节点出详情并可跳转到对应分区；可聚焦某 feature 看其关联。
- 大数据量采样不卡；reduced-motion 有静态兜底 + 文本摘要。
- 权限 fail-closed；新增测试通过；沿用现有 design token。

## 6. 风险与缓解
- **聚合口径/规模**：先定节点类型与边来源白名单，超限采样；避免 N+1（批量预取）。
- **可视化库复杂度**：优先复用现有 galaxy 封装；无则最小封装 3d-force-graph。
- **跳转一致性**：节点 ref_id → 大盘分区滚动/高亮，保持 back-path 清晰。

## 7. 衔接
- 上游：无（可并行）。下游：大盘集成（P1 占位卡）。

---
*P4 完成后回填 `MILESTONE-PROPOSAL.md` §11 P4 状态。*
