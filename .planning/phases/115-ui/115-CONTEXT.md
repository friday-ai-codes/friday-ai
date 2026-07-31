# Phase 115: 前端查看器与知识库（结构化阅读 + 批注 + 管理面） - Context

**Gathered:** 2026-07-31
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous，全部采用推荐项，用户预授权「用 smart discuss 结果，不要提问」）

<domain>
## Phase Boundary

蓝图第一次对人可见：结构化查看器（六段渲染 / 11 态徽标 / 阶段时间线 / 版本切换与 block 级 diff）、飞书式划线批注层与线程侧栏、引用二级预览弹层、知识库「技术方案」tab 与项目关联展示、人审终审（通过 / 驳回）在查看器内闭环。

**只做前端可见面 + 为其供数的只读端点**：不做飞书导出与「未确认」水印（116 / VIEW-05）、不做入口收编与 MCP 异步澄清协议（116 / GATE-01）、不做既有触点升级（`ArtifactTimeline` / `TechPlanCard` / `NodeDataTab`，归 0.19 同步点 2 之后的 116）、不做澄清提醒的渠道投递（通知面，同步点 1 后）。

**⚠️ 实测前提（本相位的起点）**：`rg -ni "blueprint" web/src` **零命中** —— 前端侧是彻底的绿地，111–114 的全部能力（含 `blueprint-gate/` 八端点、`blueprint-review/` 七端点）目前**没有任何界面可达**。

权威设计输入：`.planning/technical-blueprint/DESIGN.md` §3.2（Block/Citation 基元）/§6（线程模型与权限）/§7（引用来源与图谱物化）/§8（前端设计三节）/§13.2（并行边界纪律）；契约输入：`.planning/phases/114-ai/114-05-SUMMARY.md` 七端点契约表 + `114-REVIEW.md` Fix Log（CR-01 / MJ-01~04）；`.planning/STATE.md` 的「115 必读三条」与 Pending Todos。

</domain>

<decisions>
## Implementation Decisions

### 信息架构与查看器骨架

- **入口形态取「独立路由页」为唯一权威渲染面**：新增 `web/src/pages/knowledge/blueprints/[id].vue`（`/knowledge/blueprints/:artifactId`），所有入口（知识库 tab / 项目物料 / 后续 chat 卡片）一律 `RouterLink` 深链跳过来，**不做「全屏 Dialog 形态」的第二套实现**。决定性理由：DESIGN §8.3 要求引用预览是「查看器之上再弹一层」，若查看器本身是 Dialog 则预览成为**嵌套 Dialog**（§8.3 自己也承认现状代码库无先例、需要新造 z-index/焦点管理封装）；改成路由页后，引用预览就是**第一层** `Dialog`，直接复用既有 `components/ui/dialog/`（`Dialog` + `DialogScrollContent`，`pages/knowledge/index.vue` 已在用）零新封装。
- **三栏布局**：左「六段目录导航」（每段带批注数 / 完成度徽标）+ 中「结构化正文」+ 右「线程侧栏」（可折叠）。窄屏（<1280px）右栏收成抽屉，复用既有 `components/ui/sheet/`；左栏收成顶部下拉。对齐 DESIGN §8.1。
- **锚定坐标系双键、且与后端同源**：块级 DOM `id` 用 `block_id`（111 保证版本间稳定：编辑保留、新增才生成），段级导航 key 用段名（`repo_associations` / `current_state_analysis` / …）；`section_path`（111 `iter_blocks` 的「点分 + `[标识]`」约定）**只作降级定位与失锚回显文案**，不另立第三套坐标。理由：114 的重锚定判据就是 `block_id → quoted_text → orphaned`，前端若自造 DOM 标识必然与重锚定结果错位。
- **确认门（阶段 1）UI 纳入本相位，作为查看器内的 `BlueprintGatePanel`**（消费既有 `artifacts/<id>/blueprint-gate/` 快照 + 七动作端点：confirm / remove-repo / add-repo / reclassify-role / edit-responsibility / rejected-to-boundary / upgrade-research）。理由：112 只交付了后端，全仓零前端 ⇒ 不做则 FLOW-03 在 UI 上**不可达**、用户永远走不到 113 的阶段 2，整条链在界面上断在第一关。范围控制：七个动作**每个都是一次 POST + 重取快照**，与人审操作栏共用同一「动作条 + 二次确认」范式；`add-repo` 复用既有 `components/workflow/RepositoryPicker.vue`。**显式登记这是相对 ROADMAP SC 的范围增量** —— 若 plan-checker 判定超载，拆成本相位最后一个可独立顺延的 plan，不得混进查看器主干 plan。

### 批注层与线程交互

- **划线粒度 = block 内字符区间**：以 block 为最小渲染单元，按 `anchor.start_offset` / `end_offset` 在该 block 的纯文本上切分并用 `<mark>` 包裹（飞书式下划线高亮，颜色按 `kind` × `severity` × `status` 分档）。offset 越界 / block 不存在 ⇒ 降级为整块左侧色条，并计入失锚呈现。**不引入 tiptap/ProseMirror 只读实例**：只读渲染面不需要编辑器内核，装饰层的复杂度远高于自己切区间。
- **线程以右侧侧栏为主，不做 inline 气泡**：侧栏按 `open` / `answered` / `resolved+dismissed` 三组折叠，组内按 severity（blocker → warning → info）再按时间排序；点击正文划线滚动并选中侧栏条目，反向亦然。选区评论用 floating popover（`@floating-ui/vue` 已在依赖）浮出「发起评论」。
- **⛔ 线程动作按 `kind` 硬分流（本相位最不能错的一条，来自 114 CR-01）**：
  - `kind == ai_review_finding` 的线程侧栏**不渲染「回复」输入框**，只给「已修复」/「误报忽略」两个动作，各自弹出**必填 `reason`** 的确认框，分别调 `threads/<id>/resolve/` 与 `threads/<id>/dismiss/`（后端把结论写成 `[已修复|误报忽略] {reason}（处置人：{uid}）`）。
  - 只有 `ai_clarification` / `human_comment` / `repo_confirmation` 走 `threads/<id>/answer/`。
  - 理由：114 对 finding 走 answer 通道**一律 400**，且回灌链 `REFLOW_KINDS` fail-closed 过滤。UI 若给统一输入框再按 kind 切端点，必然稳定撞 400 或误处置；分流做在**渲染层**（压根不给错的入口）而非提交层。
  - 附带纪律：approve 返回 409 时，响应体的 `unresolved_blocker_thread_ids` 要渲染成**可点击跳转到对应 finding 线程**的清单 —— 那是超界死锁的唯一解药入口（114-05 原话），只显示「不可确认」等于把人锁死。
- **未决 / 失锚常驻可见**：顶栏三个计数徽标（未决 BLOCKER / 待澄清 / 失锚）。失锚线程单列「失锚批注」分组，**直接渲染快照的 `orphaned_threads` 不再前端过滤**（114 MJ-02 已保证里面只有真失锚），条目展示 `anchor.quoted_text` 快照 + 「原文已变更，无法定位」说明，且仍可回复 / 处置。

### 数据面、版本 diff 与实时生成态

- **新增只读「蓝图正文」端点（本相位唯一必须新增的后端读面）**：`GET /api/delivery/artifacts/<uuid:artifact_id>/blueprint/`，可选 `?version_id=`（缺省取 current），返回 `{version_id, version_no, is_current, produced_by_ref, created_at, content, quality}`。必须**照挂 114 的 `_aassert_project_scope`**（MJ-03 明令：新增任何蓝图读写端点都要挂；非成员中性 404、读不到 `meta.project_id` 400）。
  - 理由：实测 `blueprint-review/` 的 GET 快照**不返回 content**（它只在内部读 content 取 `meta.project_id`），而 `ArtifactTimelineView` 给的是 `current_version_markdown` 渲染串 —— **结构已丢，做不了 block 锚定与 block 级 diff**。没有这个端点，SC-1/SC-2 无法实现。
  - **不把 content 内联进 GET 快照**：快照要被高频重取（线程/状态轮询），每次拖一整份文档是纯浪费。
  - `quality` 键顺带消费 `blueprint_quality` 的三项 DB 统计（`ai_rejection_rate` / `human_edit_volume` / `clarification_rounds`），**无数据回 `None` ⇒ UI 显示「暂无数据」而不是 0** —— 这同时闭掉 STATE 登记的 114 review MN-05「三项统计零消费方」（人审面板正是它明确指定的正确消费面）。
- **版本列表复用既有端点，diff 在前端算**：版本轨直接用 `deliveryArtifacts.getArtifactTimeline(artifactId)`（已给 `version_no` / `produced_by_ref` / `supersedes_id` / `is_current`），**不新增版本列表端点**。版本原因徽标由 `produced_by_ref` 四前缀映射：`human_edit:` → 人工编辑、`ai_review_reflow:` → 澄清回灌、`human_block_restore:` → 人工块保护、`blueprint_review_reject:` → 人审驳回，其余归「AI 产出」。
- **diff 呈现**：取两版 content（同一新端点带 `version_id`），按 `block_id` 求差得「新增 / 删除」，`block_id` 相同而内容变化得「修改」；块内文本用**已在依赖**的 `diff`（`diffWords`），范式与颜色令牌对齐既有 `components/prompts/PromptVersionDiff.vue`（它已用 `diffLines`）。默认单栏 inline 标记，可切左右并排。**不为 diff 新增后端端点**（111 的 `diff_blueprint_blocks` 是服务端纯函数，为它开 REST 属净新增面且与前端两版都在手的现实重复）。
- **实时进展走「只读事件端点 + 状态驱动轮询」，绝不新建推送通道**：新增 `GET /api/delivery/artifacts/<uuid:artifact_id>/blueprint/events/`，查 `ConvergenceSessionEvent` 且**只取 `blueprint_*` 事件类型**（既有类型/字段只读不改，§13.2 第 3 条），供「阶段时间线」与「各段生成中进展」两处消费；同样挂 `_aassert_project_scope`。前端在 `researching` / `drafting` / `ai_reviewing` 三态开启轮询（TanStack Query `refetchInterval`，节奏对齐既有 `composables/usePolling.ts` 惯例），进入人审态/终态自动停。
  - 理由（实测）：`ConvergenceSessionEvent` 全仓**既无 REST 也无 WS**；唯一现成的 WS 是 `ws/projects/{id}/` 的 `apush_project_event`，要用它就必须在蓝图 stage handler 里新增 emit —— 那是往 §13.2 的受限面上加推送侧写，且「事件时间线契约」的归属方是 v0.19.0 Phase 110（同步点 2 才成立，晚于本相位）。轮询是唯一**既不新建通道、又不侵入 0.19 契约面**的选择；同步点 2 之后若 0.19 的推送契约就位，换掉 `refetchInterval` 即可（消费点已收敛在一个 composable 内）。
- **加载 / 空 / 错误四态**：生成中**按段渲染骨架屏**（`components/ui/skeleton` 已有），已产出的段立即实渲 —— 增量填充而非全页 loading（SC-1「生成中各段展示实时进展」的字面要求）。错误态按状态码分档，全部读 `ApiError.status`（`web/src/api/client.ts` 已带 `status` + `detail` + `body`）：**404 一律渲染中性的「无权限或不存在」**（不区分，对齐 114 MJ-03 的中性 404 语义，前端不得反推存在性）；**409** 渲染带解药的提示（approve 的未决清单可点跳转；reject 冲突显示 `version_no` 提示刷新重试）；**400** 原样回显后端 `detail`。

### 知识库 tab、引用预览与人审终审

- **tab 落位复用既有机制**：扩 `web/src/pages/knowledge/index.vue` 的 `KnowledgeTab` 联合类型与 `TABS` 数组加 `'blueprints'` —— 该文件的 `?tab=` 双向同步、`normalizeTab` 兜底、`TabsList`/`TabsContent` 结构已就绪，属**纯追加零新机制**；列表项 `RouterLink` 到 `/knowledge/blueprints/:artifactId`（深链直达查看器，SC-4）。
- **列表另起独立只读端点，不改 `ArtifactListView`**：新增 `GET /api/delivery/blueprints/`，支持 `?project_id=` / `?blueprint_status=` / `?repository_id=` / `?q=`（标题+摘要 icontains）+ 分页，返回状态 / 项目 / 涉及仓库 / 批注数 / 更新时间。
  - 决定性理由：MJ-03 要求蓝图读端点挂项目成员闸，而 `ArtifactListView` 是通用面且已被 `components/delivery/ArtifactTimeline.vue` 消费 —— **往它身上挂闸会改既有面的行为**。独立端点天然 fail-closed（只列调用者可见项目的蓝图），且符合「前端只新建」的边界纪律精神。
  - **不用 `searchDeliveryKnowledge`**：那是向量召回，做不了状态精确筛选与稳定分页。语义搜索留 116/Future。
- **项目关联双向可查（SC-4）**：项目侧在 `ProjectMaterialsPanel` 新增一张**只读**「技术方案蓝图」卡（列该项目蓝图 + 状态 + 跳查看器），走同一 `/delivery/blueprints/?project_id=` —— 复用该面板既有的 `defineAsyncComponent` 扁平分区范式，是新建组件不是改既有组件。蓝图侧在查看器「关联」区复用 `knowledgeApi.getRelated` / `getArtifactAssociations` 展示互引与知识关联。
- **引用预览统一走一个 `CitationPreviewDialog`，按 `source_type` 分发到已有读取面**（不为每类新建端点）：
  - `knowledge_entity` → `knowledgeApi.getEntity`
  - `repo_file` / `rag_chunk` → 既有 `repository-chunk-at`（v0.5.0 的 `file:line → chunk` 反查，天然带行号），行高亮取 `locator.line_start/line_end`，代码渲染复用既有 CodeMirror 只读封装
  - `repo_charter` → 既有 `repository-charter`
  - `blueprint` / `artifact_version` → 本相位新增的蓝图正文端点（迷你只读渲染）
  - `work_item` / `feishu_doc` / `url` → 外链新标签
  - **兜底不留白**：任何来源取不到时，渲染 citation 自带的 `title` / `quote` 快照 + 「原始来源不可达」提示。
- **仓库关联卡**：`role` 徽标（direct/indirect 双色）+ rationale 可展开（带 citation chip）+ **直接跳转 `/repositories/:id`**（SC-3）。`fitness.verdict == unsuitable` 时的「替代建议」**按 `fitness.reasons` 自由文本原样展示，不补 schema 字段** —— 这条同时定夺 STATE 登记的「Phase 112 残留 PARTIAL / FLOW-02 替代建议无结构化字段」：前端只是呈现方，为呈现去改已锁定的 schema 不划算。
- **人审终审的防误触**：「通过」「驳回」独立成顶栏右侧操作区，与阅读/编辑动作视觉分离；两者均走二次确认（复用既有 `composables/useConfirmDialog.ts` + `GlobalConfirmDialog.vue`）；**驳回的 `comment` 必填非空**（可来自选区评论，也可在确认弹窗内写），符合「驳回带划线评论」的字面要求。按钮可用性由 `current_status` 驱动：非 `pending_review` 一律禁用并给出 tooltip 说明原因。
- **可编辑状态白名单前置到 UI（114 MJ-04）**：`current_status ∈ {confirmed, implementing, implemented, archived, superseded, failed}` 时，**隐藏**「编辑 block」入口与澄清作答输入框，并提示「已确认的蓝图不可直接改写，要改请先驳回」。理由：这两条路径后端一律 400，UI 不反映等于把用户送进死路。
- **前端不自建权限判断（同时定夺 111 review 跳过项 MN-12）**：不做「只读模式 / 可编辑模式」二态，**一律以后端状态码为准**（成员即全权，§6.4；非成员在列表里根本看不到、直链一律中性 404）。
- **动作后的状态一律以响应体 `current_status` 为准并重取快照**（114 MJ-01 第二点：service 侧取值在续驱之前，后端已改为续驱之后重读）；前端**不得**自行乐观推断下一状态。

### Claude's Discretion

- 组件文件切分与命名、Tailwind 类与颜色令牌选取、图标选择、i18n key 层级（`knowledge.blueprints.*` 之下自定）、TanStack Query 的 queryKey 结构与缓存时长、骨架屏形状、测试组织与 `data-testid` 命名，均自行决定，遵循 `web/` 既有惯例（`@antfu/eslint-config`、`~/` 别名、`pages/` 文件路由、中文内联注释解释「为什么」）。
- 新增三个只读端点的序列化器切分、查询优化（`select_related` / `annotate` 批注数）、以及它们的测试组织自行决定，遵循 111–114 已建立的 `blueprint_*` 模块与 `delivery/api/` 风格。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets（`web/src/` 实测）

- `components/ui/dialog/`（`Dialog` / `DialogScrollContent` / `DialogHeader` …）—— 引用预览弹层的现成基座；`pages/knowledge/index.vue` 的工件查看弹窗即现成用法范式。
- `components/ui/`：`sheet`（窄屏线程抽屉）、`skeleton`（生成中骨架）、`tabs`（tab 扩展）、`badge`、`popover`、`command`、`scroll-area`、`table`、`tooltip`、`pagination`。
- `components/project/warroom/MermaidDiagram.vue` —— mermaid 渲染 + 渲染失败回退源码 + 放大查看，**交互流程段可直接复用**（`mermaid@^11` 已在依赖）。
- `components/prompts/PromptVersionDiff.vue` —— 版本 diff 的现成范式（`diff` 包的 `diffLines`，`diff` 已在依赖）。
- `components/repository/IndexProgressTimeline.vue` / `components/knowledge/EntityVersionTimeline.vue` —— 阶段时间线与版本轨的视觉范式。
- `components/spec/SddSpecStatusBadge.vue` + `pages/specs/[id].vue` —— **状态徽标 + 状态流转动作 + 评审时间线**的治理页范式，11 态徽标与人审操作栏照此。
- `components/workflow/RepositoryPicker.vue` / `components/chat/RepoMultiSelector.vue` —— 确认门 add-repo 的仓库选择器。
- `api/deliveryArtifacts.ts` —— `getArtifactTimeline`（版本轨，已含 `produced_by_ref` / `supersedes_id` / `is_current`）、`listArtifacts`、`getArtifactVersionDownstream`，**版本切换器零新端点**。
- `api/knowledge.ts` —— `getEntity` / `getRelated` / `getArtifactAssociations` / `searchDeliveryKnowledge`（引用预览与「关联」区）。
- `api/client.ts` 的 `ApiError`（`status` + `detail` + `body`）—— 404/409/400 分档处理的基础。
- `composables/`：`usePolling`、`useConfirmDialog`、`useErrorHandler`、`useMarkdownRenderer`、`useToast`、`usePermission`。
- 既有 REST 读面：`repository-chunk-at`（file:line → chunk，含行号）、`repository-charter`、`/repositories/:id` 路由页。

### Established Patterns

- 页面用文件路由（`unplugin-vue-router`）+ `definePage({ meta })`；服务端态一律 TanStack Query，客户端态 Pinia；`?tab=` / `?view=` 与 ref 双向同步 + `normalize*` 兜底（`pages/knowledge/index.vue` 是标准样板）。
- 大组件用 `defineAsyncComponent` 懒加载（`ProjectMaterialsPanel` 全用此法）。
- i18n：`web/src/locales/zh-CN.json` 顶层按域分节（`knowledge` / `specs` / `projects` / …），默认中文；个别只读展示组件有内联中文先例（`ArtifactTimeline.vue`），但新页面走 i18n。
- 后端：`delivery/api/` 用 adrf 异步 View + `IsAuthenticated`；蓝图端点统一挂 `_aassert_project_scope`；`urls.py` 纯追加。

### Integration Points

- 查看器正文 ← 新增 `artifacts/<id>/blueprint/`（content + quality）；版本轨 ← 既有 `getArtifactTimeline`。
- 批注层 / 人审 ← 114 的七端点（`blueprint-review/` 前缀）；确认门 ← 112 的八端点（`blueprint-gate/` 前缀）。
- 阶段时间线与生成中进展 ← 新增 `artifacts/<id>/blueprint/events/`（只读 `ConvergenceSessionEvent` 的 `blueprint_*` 子集）。
- 知识库 tab / 项目物料卡 ← 新增 `/delivery/blueprints/` 列表端点。
- 引用预览 ← 既有 `getEntity` / `repository-chunk-at` / `repository-charter` / 蓝图正文端点。
- Phase 116 消费本相位：飞书导出的「未确认」水印、入口收编后的跳转目标、触点升级（同步点 2 后）全部指向 `/knowledge/blueprints/:id`。

</code_context>

<specifics>
## Specific Ideas

- **「不新建推送通道」的落地形态必须写死在 plan 里**：消费点收敛到**一个** composable（如 `useBlueprintLive`），内部只做「按 `current_status` 决定是否 `refetchInterval`」。同步点 2 之后要换成 0.19 的推送契约时，改这一个文件即可 —— 这是本相位对并行纪律最实际的交代。
- **本相位最容易做错、必须能证伪的三条**（建议逐条写成断言用例）：
  1. finding 线程的侧栏**渲染不出**「回复」输入框（变异：把 finding 也渲成可回复 ⇒ 用例应转红）；
  2. `current_status` 处于不可编辑白名单外时，编辑入口与作答框**不存在于 DOM**（不是 disabled，是不渲染）；
  3. approve 409 时，`unresolved_blocker_thread_ids` 每一项都渲染成可点跳转的处置入口（只显示一句「不可确认」即视为不合格）。
- **404 不得被前端"翻译"成两种文案**：非成员与不存在共用同一句中性提示 —— 这是后端 MJ-03 刻意不泄露存在性的对称面，前端多一句「该蓝图不存在」就把闸门破了。
- 六段渲染的组件切分建议一段一件（`RepoAssociationsSection` / `CurrentStateSection` / `ImplementationOverviewSection` / `ApiContractsSection` / `ImpactMatrixSection` / `InteractionFlowsSection`），共用一个 `BlueprintBlock` 渲染件承载「block 类型分发（paragraph/pseudocode/table/list/mermaid）+ citation chip + 批注高亮」三件事 —— 批注层与引用层只在这一个组件里实现，六段各自不重复。
- 质量指标三项在人审面板以「暂无数据 / 具体值」二态呈现，**绝不把 `None` 显示成 0** —— 那正是 114-05 三态并列用例要防的口径事故。

</specifics>

<deferred>
## Deferred Ideas

- **既有触点升级**（项目页 `ArtifactTimeline` 点击打开查看器、Chat `TechPlanCard` 升级为蓝图摘要卡、工作流 `NodeDataTab` 补 `ai_plan_research`）→ Phase 116，**同步点 2 之后**（§13.2 第 4 条：这些组件归 v0.19.0）。
- **飞书导出 + 未确认水印**（VIEW-05）→ Phase 116。
- **澄清提醒的渠道投递**（飞书卡片重推 / 站内通知）→ 通知面，同步点 1 之后；本相位只做「待澄清」状态与计数的界面可感知（STATE Pending Todo：114-05 只落事件与周期锚点，用户收不到实际通知）。
- **蓝图列表的语义搜索**（向量召回）→ Future；本相位只做标题/摘要精确检索 + 结构化筛选。
- **确认门七动作若被判超载**：拆为本相位最后一个可独立顺延的 plan（顺延目标 116），但**不得**把它默默丢掉 —— 丢掉等于 FLOW-03 永远无界面。
- **block 正文编辑（`edit-blocks/` 端点的前端面）** → Phase 116（UI-SPEC §0.1 硬边界第 3 条 / §0.2 判定 7 登记）。ROADMAP 的五条 SC 无一涉及「改写 block 正文」；`edit-blocks/` 的 `ops` 是块级补丁语义，完整实现需要行内编辑器、脏态管理、并发冲突提示与 `human_edit:` 版本产出链，属另一个相位的体量。**本相位的写路径穷举为三条**：澄清/评论作答、选区评论建线程、finding 处置（另加终审两动作与确认门七动作）。上文 Implementation Decisions 里「隐藏『编辑 block』入口」一句因此升级为**该入口本相位根本不存在**（比隐藏更强，同向不冲突）；`readonly` 白名单仍照常约束作答输入框与选区评论入口。
- **`content.execution_plan` 段的呈现** → 116+。它是确认后确定性派生的执行计划（形状对齐 `technical_plan` schema），呈现面归属实施链路，在只读评审面渲染会与 `TechPlanCard`（§13.2 禁区）职责重叠。UI-SPEC §6.1 的「content 顶层键去向总表」已逐键登记。
- **母子蓝图编排拆分 / 段级细粒度编辑权限 / golden set 弱标签扩样** → REQUIREMENTS Future Requirements，本相位不碰。
- **`ConvergenceSessionService.areopen_stage` 的「人审驳回导致会话复位」是否进事件时间线**（114 review 可再议项，需新增 `blueprint.review.session_reopened` 事件常量）→ 同步点 2 后与 0.19 的时间线契约一并定；本相位时间线先不呈现该动作。

</deferred>
