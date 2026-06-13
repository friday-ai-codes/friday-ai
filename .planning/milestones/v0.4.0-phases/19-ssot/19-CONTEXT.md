# Phase 19: 节点定义单一事实源 - Context

**Gathered:** 2026-06-13
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous——orchestrator 基于代码勘察提出 grey-area 决策并采纳）

<domain>
## Phase Boundary

后端节点 `NodeRegistry` 成为唯一事实源——前端节点面板（palette）、配置表单 schema、默认 config、画布输入/输出 Handle 全部由 `GET /api/node-types/` 驱动，删除前端硬编码 `NODE_REGISTRY` / `portConfig` 漂移，并以自动化守护防止前后端节点定义再次漂移。

**In scope（SSOT-01/02/03）：**
- 前端 palette / 表单 schema / 默认 config 改由 API 驱动；删除硬编码 `NODE_REGISTRY` legacy 区块
- 幽灵节点 `fetch_project_info` 全量对齐为真实后端节点 `fetch_space_info`
- 画布 Handle 由后端 `inputs`/`outputs`（NodePort）渲染，替换 `portConfig.ts` 硬编码端口推断
- 后端 `NodeTypeSerializer` 补齐前端驱动所需字段（`ui_schema`、`default_config`）
- 前后端一致性 CI 守护（修正现有对账测试/脚本，连后端 schema 对账）

**Out of scope（明确不做）：**
- 不改节点的执行语义/业务逻辑（Phase 18 已收口引擎）
- 不重构节点配置组件（custom `configComponent`）的内部实现，仅改其"定义来源"
- 不改 `node-definitions.json` 构建期注入后端 `ui_schema` 的既有机制（保留）
</domain>

<decisions>
## Implementation Decisions

### D-01 [单一事实源策略] 运行时 API 驱动 + 后端补字段
前端运行时全部由 `GET /api/node-types/` 驱动（palette、表单 schema、默认 config、Handle）。后端 `NodeTypeSerializer` 扩展暴露两个缺失字段：
- `ui_schema`（`get_schema()` 已产出 `cls._get_ui_schema()`，序列化器未暴露——补上）
- `default_config`（从 `config_schema.properties.*.default` 提取为独立顶层字段，省去前端 `schema.parse({})` 反推）
保留 `node-definitions.json` 构建期注入后端 `ui_schema` 的现有链路（它是后端 ui_schema 的来源，不是前端运行时来源）。

### D-02 [删除硬编码] NODE_REGISTRY legacy 与 portConfig 推断删除/降级
- `web/src/types/workflow/registry.ts` 的 legacy 硬编码区块（L86–276）删除；`getNodeDefinition`/`getDefaultConfig`/`validateNodeConfig` 改为读 `useNodeTypesStore`（运行时缓存）。
- `portConfig.ts` 的 `getDefaultPortsForNodeType` 硬编码分支替换为"按 store 的 `inputs`/`outputs` 渲染 Handle"；`TRIGGER_NODE_TYPES`/`APPROVAL_NODE_TYPES`/`ERROR_OUTPUT_NODE_TYPES` 由后端字段（`category`/端口集）派生。
- `migratePortId`（存量工作流端口 ID 迁移）**保留**——兼容已存数据，禁删。

### D-03 [幽灵节点] fetch_project_info → fetch_space_info 全量对齐
前端所有 `fetch_project_info` 出现点（registry.ts、schemas.ts、NodePalette.vue、nodeVisuals.ts、IntegrationNode.vue、配置组件、node-sync.test.ts）改名/指向真实后端 `fetch_space_info`。配置组件文件可保留文件名但类型/节点 key 对齐 `fetch_space_info`（避免大规模重命名风险，文件改名为可选）。

### D-04 [画布 Handle 来源] 由 API inputs/outputs 渲染
`BaseWorkflowNode.vue` 的 Handle 渲染改为消费 `useNodeTypesStore` 的 `inputs`/`outputs`；store 未就绪（首帧/离线）时用最小回退（单 in/单 out + default 端口），不再用 `portConfig` 全表推断。`ai_coding` 显示 `plan` 输入、`ai_code_review` 显示 `coding_result` 输入、审批节点显示 `approved`/`rejected` 输出——以后端 NodePort 为准。

### D-05 [一致性守护] 连后端对账的 CI 测试（修正现有，不新造体系）
- 修正 `web/scripts/validate-node-definitions.ts` 的错误 API 路径（`/api/workflows/node-types/` → `/api/node-types/`）。
- 重写 `node-sync.test.ts`：从"硬编码 EXPECTED_NODES 静态对账"改为"以后端 registry 节点 type/端口全集为基准"对账前端残留硬编码（理想终态：前端无硬编码节点表，测试退化为'确认无遗留硬编码节点 map'）。
- 守护形式优先 **Vitest 单测**（CI 已跑 `pnpm test`），后端 schema 可用 fixture 快照（避免 CI 强依赖在线后端）；快照由脚本从后端生成、纳入版本库。

### Claude's Discretion
- 具体文件拆分/wave 划分、回退渲染的精确实现、fixture 快照的生成方式、配置组件文件是否物理改名——交由 planner/executor 依代码现状定夺。
- `icon` 后端 lucide 名 vs 前端 iconify class 的映射策略（建立一张映射或后端直接产出前端可用值）——执行期定。
</decisions>

<code_context>
## Existing Code Insights（勘察结论，详见 RESEARCH 将进一步展开）

**后端：**
- `GET /api/node-types/` = `NodeTypeViewSet`（`server/workflows/api/views.py` L1348–1369），数据源 `NodeRegistry.get_all_schemas()` → `BaseNode.get_schema()`（`base.py` L592–627）。
- `get_schema()` 已产出 `ui_schema`，但 `NodeTypeSerializer`（`serializers.py` L785–809）**未暴露** `ui_schema` 与 `default_config`。
- 备用端点 `GET /api/nodes/schemas/`（含 ui_schema）前端未用。
- 真实节点 `fetch_space_info`（`server/workflows/nodes/data/fetch_space_info.py`）。

**前端（三套并行源，需收敛）：**
- `node-definitions/`（18 节点，构建期产 `node-definitions.json` 供后端读 ui_schema）。
- `NODE_REGISTRY`（`registry.ts`，legacy 硬编码 L86–276，含幽灵 `fetch_project_info` L182–192）——主要删除目标。
- `useNodeTypesStore`（`stores/useNodeTypesStore.ts`，唯一正式消费 `/node-types/` 的 store）——扩为前端运行时唯一源。
- `portConfig.ts`（画布端口全硬编码）——替换为 API 驱动。
- `schemas.ts` L377–394 `NODE_CONFIG_SCHEMAS`（第二套硬编码，含幽灵节点 L386）。

**消费硬编码 NODE_REGISTRY 的文件**：useNodeMeta.ts、useDragAndDrop.ts、nodes/index.ts、WorkflowDataTable.vue、WorkflowMiniMap.vue、GradientEdge.vue、CreateWorkflowModal.vue、NodeConfigPanel.vue（uiSchema 来源）。
**消费 portConfig 的文件**：BaseWorkflowNode.vue、pages/workflows/[id].vue、useWorkflowsStore.ts。

**一致性测试现状**：`node-sync.test.ts`（静态、EXPECTED_NODES 过时含幽灵节点）、`validate-node-definitions.ts`（API URL 错误）、`validate-nodes.test.ts`/`definitions.test.ts`（不连后端）、后端 `test_api.py`（无字段级对账）。
</code_context>

<specifics>
## Specific Ideas

- 终态验收：删除 `NODE_REGISTRY` legacy 后画布编辑（拖放/默认 config/显示名/连线校验）不回退；palette 不再出现 `fetch_project_info`，出现真实 `fetch_space_info`。
- `ai_coding` 画布显示 `plan` 输入、`ai_code_review` 显示 `coding_result` 输入、审批节点显示 `approved`/`rejected` 输出（与 Phase 18 引擎 target_handle 语义一致）。
- CI：前后端节点 type/端口漂移时测试失败（fixture 快照与后端 registry 对账）。
</specifics>

<deferred>
## Deferred Ideas

- 配置组件（custom `configComponent`）改为后端 ui_schema 完全声明式渲染——本阶段只统一"定义来源"，不重写组件渲染体系。
- 后端 `icon` 直接产出前端 iconify class 的统一规范——可在本阶段做最小映射，完整规范化延后。
</deferred>

---

*Phase: 19-ssot*
*Context gathered: 2026-06-13 via smart discuss (autonomous)*
