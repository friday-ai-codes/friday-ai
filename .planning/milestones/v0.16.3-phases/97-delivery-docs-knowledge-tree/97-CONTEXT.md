# Phase 97: 交付文档知识树视图 - Context

**Gathered:** 2026-07-01
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous — grey areas auto-decided，决策原则「优雅、好用」，用户已授权不逐项确认)

<domain>
## Phase Boundary

在 `/knowledge` 知识树页提供一棵**并行**的「交付文档」树（项目 → 工件类型 → 工件），与现有代码能力树（PageIndex）切换/并列，可树内搜索、点叶子查看工件。

1. KDEP-04：知识树页新增「交付文档」树视图（项目→类型→工件），与代码能力树切换/并列，**不改动 PageIndex 能力树数据**。
2. KDEP-05：交付文档树支持树内搜索/过滤 + 点击叶子查看工件（复用 Phase 96 的查看弹窗 / 飞书 / 外链），空态优雅、层级清晰。
3. KDEP-06：后端提供交付文档树数据 API（按用户可见 project 聚合 `Artifact`，分组 项目→类型→工件），带权限过滤（access_scope）与节点上限保护。

**边界内**：并行树视图（前端）、树数据 API（后端）、树内搜索 + 叶子查看。
**边界外**：工件↔仓库/能力建边（Phase 98）、星图/交叉入口（Phase 99）、修改 PageIndex 能力树。
</domain>

<decisions>
## Implementation Decisions

### 视图组织与切换（KDEP-04）
- 交付文档树是**独立并行视图**，不塞进 PageIndex 能力树（research §2.3 锁定：能力树代码派生、语义「仓库能做什么」；交付文档「项目交付了什么」，混用会互相污染且能力树重建会冲掉外部节点）。
- 在知识树页（`KnowledgeTreePanel.vue` 所在 tree Tab）加一个**视图切换**（segmented control / tabs）：「代码能力树」｜「交付文档」。默认仍是代码能力树（保持既有行为不变），切到「交付文档」渲染新树。切换状态可存 URL query（`?tab=tree&view=docs`）便于分享/回跳。
- 树层级固定三层：项目（顶层分组）→ 工件类型（`ArtifactType`）→ 工件（叶子，显示 title + 载体图标）。项目/类型节点显示计数。
- 复用现有树组件与视觉（缩进、展开箭头、hover、选中态）——最少新增面积、与能力树观感一致。若能力树组件可参数化数据源则复用，否则抽轻量共享树渲染组件。

### 树内搜索、查看与空态（KDEP-05）
- 树内搜索框：输入即过滤（客户端过滤已加载树），命中高亮 + 自动展开命中路径的祖先节点，无命中显示「无匹配」空态。沿用 Dashboard 的即时搜索观感。
- 点击叶子工件 → 复用 Phase 96 已建的查看能力：文字载体（feishu_doc/markdown）走 markdown 查看弹窗（`ArtifactView`），external_link 新标签打开。查看入口与 Phase 96 搜索结果项行为一致（同一 helper/组件）。
- 空态优雅：整棵树为空时展示引导文案 + 指向作战室「外部依赖」维护入口；某项目/类型下无工件则不渲染该空分组（避免噪声）。
- 层级清晰：类型节点带类型徽标（复用 Phase 96 徽标）；叶子带载体图标 + 更新时间；节点计数右对齐。

### 树数据 API（KDEP-06）
- 新增后端接口 `GET /api/knowledge/artifacts/tree/`：按当前用户可见 project 聚合 `Artifact`，返回嵌套结构 项目→类型→工件（或扁平 + 前端组装，取更简洁者；倾向后端直接返回嵌套树，前端零拼装最「优雅」）。
- 权限：强制走 `access_scope`（`resolve_allowed_project_ids` → 按 `project__space_id` 过滤，复用 Phase 96 已核实口径），越权项目/工件不可见。
- 节点上限保护：项目数 / 每项目类型数 / 每类型工件数分别 clamp（沿用 `max_nodes`/limit 思路），超限截断并在响应标注 `truncated=true`，前端提示「已截断，请用搜索缩小范围」。
- 单次请求返回整棵可见树（数据量受上限保护）；前端一次加载 + 客户端搜索/展开，避免逐节点懒加载的复杂度（数据规模小，简单即优雅）。
- 观测：接口结构化 started/completed/failed + `duration_ms`、category=caller、component=knowledge；best-effort 不反噬。

### 横切
- async ORM 一律 `sync_to_async`；不改 PageIndex 能力树数据/接口。
- 前端类型安全（TS 类型定义树节点）；i18n 文案默认中文接入 `vue-i18n`；新用到的动态 lucide 图标记得 safelist。
- 与 Phase 96 复用一致：类型徽标、查看 helper、`web/src/api/knowledge.ts` 追加 `fetchArtifactTree` 方法。

### Claude's Discretion
- 树节点数据结构字段、后端嵌套 vs 扁平、切换控件具体形态、组件拆分粒度由 plan/execute 按既有约定自定，遵循「优雅、好用」：复用能力树组件与样式令牌、最少新增、最一致。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- 前端：`web/src/pages/knowledge/index.vue`（tree Tab）、`web/src/components/knowledge/KnowledgeTreePanel.vue`（PageIndex 能力树渲染，视图切换/树组件复用参考）、`web/src/components/knowledge/KnowledgeDashboard.vue`（Phase 96 区块 + 即时搜索模式）、`web/src/api/knowledge.ts`（Phase 96 已加 overview 方法）、Phase 96 查看 helper / 类型徽标（`index.vue` 搜索结果项）。
- 后端：Phase 96 `server/knowledge/api/artifact_overview.py`（access_scope 过滤 + 类型分组聚合 + 截断保护的成熟范式，可直接借鉴到 tree 接口）、`server/knowledge/api/urls.py`、`server/knowledge/access_scope.py`、`initiatives.Artifact` + `ArtifactType`。

### Established Patterns
- 知识接口挂 `server/knowledge/api/`；access_scope fail-closed（allowed 空则零查询）；SQL annotate 计数；截断保护。
- 前端知识页 Tab + URL query 状态；即时客户端搜索；结构化 kv 观测。

### Integration Points
- 树 Tab 视图切换：`index.vue` / `KnowledgeTreePanel.vue`。
- 新树数据接口挂 `knowledge/api/`（`artifact_tree.py` + `urls.py`）；前端 `knowledge.ts` 加方法。
- 查看叶子复用 Phase 96 查看能力（同一组件/helper）。
</code_context>

<specifics>
## Specific Ideas

- 明确「并行树」不污染 PageIndex 能力树（research §2.3、KDEP-04 硬约束）。
- 后端直接返回嵌套树，前端零拼装（更优雅）。
- 数据规模小 → 一次加载 + 客户端搜索/展开，避免懒加载复杂度。
</specifics>

<deferred>
## Deferred Ideas

- 工件↔仓库/能力/关键词建边与可查询 → Phase 98。
- 星图纳入 artifact / 实体详情关联 / 作战室交叉入口 → Phase 99。
- 树节点懒加载 / 超大规模分页 → 若未来数据量爆炸再评估（当前上限保护足够）。
</deferred>
