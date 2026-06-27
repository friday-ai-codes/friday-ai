# Phase 93: 插槽编辑器（前端）- Context

**Gathered:** 2026-06-27
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous，用户逐 phase 定夺）
**UI hint:** yes（plan 前先经 `gsd-ui-phase` 产 UI-SPEC 设计契约）

<domain>
## Phase Boundary

工作流编辑器（@vue-flow）支持「能力契约」磁吸拼接：前端按端口契约判定连接合法性 + 兼容插槽高亮 + 吸附；
澄清节点作为方案节点的「附着子节点」可视编组，并可下接吃 `feishu_message`/`feishu_document` 的原子节点。

覆盖：SLOT-03（前端形状磁吸 isValidConnection + 高亮 + 吸附）、SLOT-04（附着子节点编组 + 下接发群/文档/通知）。

</domain>

<decisions>
## Implementation Decisions

### A. 前端契约匹配（前端直接判定）
- **前端权威判定连接合法性**：前端从 `/api/node-types/` 直接拿到端口契约（Phase 92 写入 schema），
  `useConnectionValidator` 增「契约兼容」判定——用户拖拽时即时可见能否匹配（不必等后端保存）。后端校验作为兜底。
- **磁吸视觉**：拖拽时**兼容插槽高亮** + 距离阈值**吸附**（复用现有 snap-grid / `useAlignmentGuides` 思路）；
  **不兼容形状不可连** + 禁止态视觉反馈。

### B. 附着子节点编组（SLOT-04）
- 澄清节点作为方案节点的「**附着子节点**」可视编组——表达「生命周期绑定」（澄清随方案节点存在），
  视觉上成组/连体，而非孤立节点 + 普通连线。
- 澄清节点的 `feishu_message` 出口可下接「发送飞书群聊 / 通知」等节点。

### C. 节点能力分类（用户要求：仔细规划现有节点归类 + 可接通知/文档/澄清）
> 据全量节点清单（`server/workflows/nodes/`）归类，指导端口契约与可连关系；UI-SPEC 细化视觉。

- **触发器（Trigger，流程起点，无入口、不接澄清）**：`manual_trigger`、`webhook_trigger`、`feishu_event_trigger`。
- **执行器（Executor，确定性，无不确定性 → 不接澄清；但其成功/失败事件可接「通知」，产物可接「文档」）**：
  - 飞书/集成：`fetch_work_item`、`fetch_space_info`、`fetch_group_chat`、`join_group_chat`、
    `create_group_chat`、`create_work_item_chat`、`create_project`、`board_split`、`mcp_deploy`、`http_request`、
    `notify_feishu_im`、`notify_feishu`、`feishu_doc_create`。
  - Git：`create_pr`、`merge_pr`、`create_branch`。
  - 数据/控制：`variable_extractor`、`aggregate`、`condition`、`delay`、`parallel`、`join`、`foreach`、
    `wait_feishu_field`；`ai_variable_extractor`、`context_retrieval`、`delivery_knowledge_search`
    （AI 但确定性，归执行器，不接澄清）。
- **AI 操作（带不确定性 → 可接「澄清」能力插槽）**：`ai_plan_research`、`ai_coding`、`ai_coding_dispatcher`；
  `ai_plan_generation`（deprecated，Phase 94 移出节点库）；`ai_prompt`（候选，按 plan-phase 判定是否给澄清槽）。
- **审批（Approval）**：`human_approval`（方案审批）——其结果可接「AI 文档生成 / 通知」。

### D. 可连「能力」生态（原子化，UI-SPEC + 92 契约支撑）
- **通知能力（feishu_message）**：几乎所有节点的成功/失败事件都可经连线接到「飞书通知」（告知群内用户某事件触发）。
  失败出口同样可接通知。
- **文档能力（feishu_document）**：产出「技术方案 / 编码指派 / AI 编码结果 / 审批结果」的节点可接
  `feishu_doc_create` 生成飞书文档；`feishu_doc_create` 产物又可接「推送/通知到群」。
- **IM 能力门控**：当工作流含 `create_group_chat` / `create_work_item_chat` 时即具备「IM 能力」（有 chat_id 目标），
  发群/通知到群端口可用；若无这类节点提供 chat_id 来源，IM 相关端口/能力**降级为空**（不可用/隐藏）。

### Claude's Discretion
- 「附着子节点编组」的具体视觉实现（Vue Flow parent/child node、分组容器、连体卡片等）由 UI-SPEC + plan 定。
- 吸附阈值、高亮配色、禁止态交互细节由 UI-SPEC 定（遵循现有 glassmorphism + 语义色：default 绿/error 红/澄清 琥珀）。
- `ai_prompt` 是否给澄清槽、IM 门控的 UI 呈现（禁用 vs 隐藏）由 plan-phase 定。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- 编辑器：`web/src/pages/workflows/[id].vue`、`web/src/components/workflow/editor/WorkflowCanvas.vue`
  （`:is-valid-connection`、`snap-to-grid`、`ConnectionMode.Strict`）。
- 校验：`web/src/components/workflow/editor/composables/useConnectionValidator.ts`
  （现：防自连 + 四元组重复 + BFS 防环；**无契约判定**）。
- 节点渲染：`BaseWorkflowNode.vue`（Handle 渲染从 `useNodeTypesStore` 读 inputs/outputs；语义色 default/error/need_clarification）、
  `BranchNode.vue`。
- 吸附/对齐：`composables/useAlignmentGuides.ts`（SNAP_THRESHOLD=5）、WorkflowCanvas snap-grid。
- 端口 SSOT：`web/src/stores/useNodeTypesStore.ts`（`GET /api/node-types/`）。
- 节点库：`web/src/components/workflow/sidebar/NodePalette.vue`、`NodeInsertMenu.vue`、`useDragAndDrop.ts`。
- 边：`edges/GradientEdge.vue`、`CustomConnectionLine.vue`、`utils/edgeRouting.ts`（L→R bezier curvature 0.16）。

### Established Patterns
- 端口契约新增在后端 schema（92），前端从 `/node-types/` 读，渲染/校验消费。
- 工作流/澄清前端文案当前多硬编码中文；i18n 覆盖薄（如需新文案就地加）。
- Vue 3 `<script setup>` + TS + Tailwind 4；`~/components/ui/*`（reka-ui/shadcn-vue）；画布节点用 `@vue-flow/core`。

### Integration Points
- `isValidConnection` ← 契约兼容；`onConnect` 写 store edge。
- 附着子节点 ← Vue Flow parent/child 或分组容器（UI-SPEC 定）。

</code_context>

<specifics>
## Specific Ideas

- 用户：前端能直接拿到形状/契约来判定匹配；子节点生态丰富——通知（成功/失败都可接）、飞书文档生成
  （技术方案/编码指派/AI 编码/审批结果都可接，文档再接推送）；节点原子化；
  「创建群聊」「创建工作项群聊」赋予 IM 能力，缺失则 IM 相关置空。要求仔细规划节点归类并完全完善。

</specifics>

<deferred>
## Deferred Ideas

- 通用「带槽节点 + 适配拼图」生态推广（SLOTX-01，v2）。
- 流式方案卡片（STREAM v2）。

</deferred>
