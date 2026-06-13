# Phase 19: 节点定义单一事实源 (ssot) - Research

**Researched:** 2026-06-13
**Domain:** 前后端节点定义契约收敛（Django DRF serializer + Vue 3/Pinia 运行时驱动 + Vitest/pytest 一致性守护）
**Confidence:** HIGH（全部结论基于本仓库代码核实，无外部依赖；少量数据态结论标 MEDIUM）

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-01 [单一事实源策略] 运行时 API 驱动 + 后端补字段**
前端运行时全部由 `GET /api/node-types/` 驱动（palette、表单 schema、默认 config、Handle）。后端 `NodeTypeSerializer` 扩展暴露两个缺失字段：
- `ui_schema`（`get_schema()` 已产出 `cls._get_ui_schema()`，序列化器未暴露——补上）
- `default_config`（从 `config_schema.properties.*.default` 提取为独立顶层字段，省去前端 `schema.parse({})` 反推）
保留 `node-definitions.json` 构建期注入后端 `ui_schema` 的现有链路（它是后端 ui_schema 的来源，不是前端运行时来源）。

**D-02 [删除硬编码] NODE_REGISTRY legacy 与 portConfig 推断删除/降级**
- `web/src/types/workflow/registry.ts` 的 legacy 硬编码区块（L86–276）删除；`getNodeDefinition`/`getDefaultConfig`/`validateNodeConfig` 改为读 `useNodeTypesStore`（运行时缓存）。
- `portConfig.ts` 的 `getDefaultPortsForNodeType` 硬编码分支替换为"按 store 的 `inputs`/`outputs` 渲染 Handle"；`TRIGGER_NODE_TYPES`/`APPROVAL_NODE_TYPES`/`ERROR_OUTPUT_NODE_TYPES` 由后端字段（`category`/端口集）派生。
- `migratePortId`（存量工作流端口 ID 迁移）**保留**——兼容已存数据，禁删。

**D-03 [幽灵节点] fetch_project_info → fetch_space_info 全量对齐**
前端所有 `fetch_project_info` 出现点改名/指向真实后端 `fetch_space_info`。配置组件文件可保留文件名但类型/节点 key 对齐 `fetch_space_info`（文件物理改名为可选）。

**D-04 [画布 Handle 来源] 由 API inputs/outputs 渲染**
`BaseWorkflowNode.vue` 的 Handle 渲染改为消费 `useNodeTypesStore` 的 `inputs`/`outputs`；store 未就绪（首帧/离线）时用最小回退（单 in/单 out + default 端口），不再用 `portConfig` 全表推断。`ai_coding` 显示 `plan` 输入、`ai_code_review` 显示 `coding_result` 输入、审批节点显示 `approved`/`rejected` 输出——以后端 NodePort 为准。

**D-05 [一致性守护] 连后端对账的 CI 测试（修正现有，不新造体系）**
- 修正 `web/scripts/validate-node-definitions.ts` 的错误 API 路径（`/api/workflows/node-types/` → `/api/node-types/`）。
- 重写 `node-sync.test.ts`：从"硬编码 EXPECTED_NODES 静态对账"改为"以后端 registry 节点 type/端口全集为基准"对账前端残留硬编码（理想终态：前端无硬编码节点表，测试退化为'确认无遗留硬编码节点 map'）。
- 守护形式优先 **Vitest 单测**（CI 已跑前端单测），后端 schema 可用 fixture 快照（避免 CI 强依赖在线后端）；快照由脚本从后端生成、纳入版本库。

### Claude's Discretion
- 具体文件拆分/wave 划分、回退渲染的精确实现、fixture 快照的生成方式、配置组件文件是否物理改名——交由 planner/executor 依代码现状定夺。
- `icon` 后端 lucide 名 vs 前端 iconify class 的映射策略（建立一张映射或后端直接产出前端可用值）——执行期定。

### Deferred Ideas (OUT OF SCOPE)
- 配置组件（custom `configComponent`）改为后端 ui_schema 完全声明式渲染——本阶段只统一"定义来源"，不重写组件渲染体系。
- 后端 `icon` 直接产出前端 iconify class 的统一规范——可在本阶段做最小映射，完整规范化延后。
- 不改节点执行语义/业务逻辑（Phase 18 已收口引擎）。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SSOT-01 | 前端 palette / 表单 schema / 默认 config 全部以 `GET /api/node-types/` 为准，删除硬编码 `NODE_REGISTRY`（含幽灵 `fetch_project_info`→`fetch_space_info`） | §1 后端补 `ui_schema`/`default_config`；§2 8 消费方收敛到 `useNodeTypesStore` + 前端仅保留 `configComponent`/视觉两张图；§4 幽灵节点全量对齐点清单 |
| SSOT-02 | 画布节点输入/输出 Handle 按后端 NodePort 渲染（`plan`/`coding_result`/`approved`/`rejected`），替换 `portConfig.ts` 硬编码 | §3 `BaseWorkflowNode.vue` 从 store inputs/outputs 渲染 + 最小回退；`TRIGGER/APPROVAL/ERROR_OUTPUT` 由 `category`/端口集派生；`migratePortId` 兼容保留 |
| SSOT-03 | 前后端节点定义一致性自动化守护 | §5 Vitest fixture 快照对账（离线，进 CI）+ 修正 `validate-node-definitions.ts` URL + 重写 `node-sync.test.ts`；§Validation Architecture 双侧测试矩阵 |
</phase_requirements>

## Summary

本阶段是一次**契约收敛重构**：后端 `NodeRegistry`（自动发现的 ~29 个节点）已经是事实上的权威源，`BaseNode.get_schema()` 也早已产出 `ui_schema`，只是 `NodeTypeSerializer` 没把 `ui_schema`/`default_config` 暴露出来；前端则并行维护着三套硬编码源（`NODE_REGISTRY` legacy 区块、`portConfig.ts` 端口推断、`schemas.ts` 的 `NODE_CONFIG_SCHEMAS`），与后端漂移，且夹带一个后端根本不存在的幽灵节点 `fetch_project_info`（后端真实节点是 `fetch_space_info`）。`useNodeTypesStore` 是唯一正式消费 `/api/node-types/` 的 store，已具备 `inputs/outputs/config_schema` 形态，扩为前端唯一运行时源即可。

关键架构识别：前端 `NODE_REGISTRY` 实际承载**三类**数据——(a) 纯数据（displayName/description/category/config_schema/defaultConfig/inputs/outputs/uiSchema），可由 API 取代；(b) `configComponent`（节点专属配置面板的懒加载 Vue 组件），**API 无法提供**，必须保留为前端 `nodeType → () => import()` 映射；(c) 视觉（icon 组件 + Tailwind 渐变色），画布侧本已由 `nodeVisuals.ts` 提供，无需依赖 `NODE_REGISTRY`。因此"删除硬编码"不是删光，而是把 (a) 迁到 store、保留 (b) 的精简映射、确认 (c) 已独立。

一致性守护必须用 **Vitest fixture 快照**而非在线请求：CI（`ci.yaml` L204 `pnpm test:unit:coverage`）只跑前端单测、**不启动后端**，现有 `validate-node-definitions.ts`（在线 fetch）既不在 CI、URL 还写错。fixture 由脚本从后端 `NodeRegistry` dump、纳入版本库，单测对账前端残留硬编码 ⊆ 后端全集。

**Primary recommendation:** 后端在 `get_schema()` 补 `default_config` 派生字段、`NodeTypeSerializer` 暴露 `ui_schema`+`default_config`（纯增量、零回归）；前端把 `getNodeDefinition/getDefaultConfig/getNodesByCategory/validateNodeConfig` 全部改为 `useNodeTypesStore` 适配器、删 `NODE_REGISTRY` legacy、保留独立 `configComponent` 映射与 `nodeVisuals`；`BaseWorkflowNode.vue` 改读 store inputs/outputs 渲染 Handle（带最小回退）；`fetch_project_info` 全量改名 `fetch_space_info`；以 Vitest fixture 快照（+ 后端 pytest 字段级断言）守护漂移。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 节点元数据权威定义（type/名称/描述/分类/端口/config_schema/默认值/ui_schema） | API / Backend (`NodeRegistry`+`BaseNode.get_schema`) | — | 后端已自动发现并产出全量 schema，引擎执行也以此为准，唯一不漂移的源 |
| 节点元数据传输契约 | API serializer (`NodeTypeSerializer`) | — | 补 `ui_schema`/`default_config` 两字段即闭合前端所需 |
| 运行时缓存 + 前端读取入口 | Frontend store (`useNodeTypesStore`) | — | 已是唯一 `/node-types/` 消费方，扩为前端唯一运行时源 |
| 配置面板组件（`configComponent` 懒加载） | Browser / Client（前端专属映射） | — | Vue 组件无法序列化下发，必须留前端；本阶段不重写其内部（deferred） |
| 节点视觉（icon 组件 + 渐变色） | Browser / Client (`nodeVisuals.ts`) | API 的 `icon`(lucide 名) 作映射输入 | 画布 Handle/图标渲染是纯前端关注点；后端 icon 是 lucide 字符串、color 后端不产出 |
| 画布 Handle 端口渲染 | Browser / Client (`BaseWorkflowNode.vue`) | API inputs/outputs（数据源） | 渲染是前端职责，端口集来自后端 NodePort |
| 一致性守护 | CI (Vitest 离线 fixture) | pytest（后端字段级断言） | CI 不起后端，离线快照是唯一可进 CI 的对账形式 |

## Standard Stack

本阶段**不引入任何新依赖**——纯用既有栈完成收敛。

### Core（已在用，本阶段使用）
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `djangorestframework` / `adrf` | 既有 | `NodeTypeSerializer` 扩字段、`NodeTypeViewSet` 返回 | 现有 API 层，增量改 serializer 字段 |
| `pinia` | 既有 | `useNodeTypesStore` 运行时缓存 | 已是唯一 `/node-types/` 消费方 |
| `vue` (`<script setup>`) + `@vue-flow/core` | 既有 | `BaseWorkflowNode.vue` Handle 渲染 | 画布编辑器框架不换（Out of Scope） |
| `zod` | 既有 | 现存前端 schema/校验（收敛过程中逐步弱化对其依赖） | 见 §Common Pitfalls 关于客户端校验的取舍 |
| `vitest` + `@vue/test-utils` + `happy-dom` | 既有 | fixture 快照对账 + 组件渲染测试 | CI 已跑 `test:unit:coverage` |
| `pytest` + `pytest-django` | 既有 | 后端 serializer 字段级断言 | `test_api.py::TestNodeTypeAPI` 已存在，扩展即可 |
| `tsx` | 既有 | fixture/生成脚本运行器 | `generate-node-definitions.ts`/`validate-node-definitions.ts` 已用 |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Vitest 离线 fixture 快照 | `validate-node-definitions.ts` 在线 fetch 后端 | 在线对账更"真"，但 CI 无后端、需 401 鉴权、网络不稳；只能当本地/手动工具 — **不选为 CI 守护** |
| 前端 `configComponent` 保留懒加载映射 | 后端 ui_schema 完全声明式渲染（删 configComponent） | 声明式渲染是 Deferred Idea，本阶段不重写组件体系 — **不做** |
| 前端 JSON-Schema 校验（ajv）替代 zod `validateNodeConfig` | 引入 ajv | 新增依赖且与 Phase 20 后端统一校验重叠 — **不引入**，见 Pitfall 5 |

**Installation:** 无新增包。`npm view` / `pip index` 校验：N/A（不安装外部包）。

## Package Legitimacy Audit

**N/A —— 本阶段不安装任何外部 npm/PyPI 包**，全部使用仓库既有依赖。无需 slopcheck / 注册表校验。

## Architecture Patterns

### System Architecture Diagram

```text
                       ┌────────────────────────────────────────────┐
   后端唯一事实源        │  NodeRegistry (auto-discover ~29 nodes)      │
                       │  _auto_discover() → BaseNode 子类             │
                       │  get_all_schemas() → [BaseNode.get_schema()] │
                       └───────────────┬──────────────────────────────┘
                                       │ get_schema() 产出:
                                       │  node_type/display_name/description/
                                       │  icon(lucide名)/category/config_schema/
                                       │  ui_schema(已产出)/inputs/outputs/...
                                       │  ★新增 default_config(从config_schema.
                                       │     properties.*.default 派生)
                                       ▼
                     ┌──────────────────────────────────────────┐
                     │ NodeTypeSerializer (api/serializers.py)   │
                     │  ★补字段: ui_schema + default_config       │
                     └───────────────┬──────────────────────────┘
                                     │ GET /api/node-types/  (IsAuthenticated)
                                     ▼
                     ┌──────────────────────────────────────────┐
                     │ useNodeTypesStore (Pinia, 唯一运行时源)     │
                     │  nodeTypes[] / nodeTypesByCategory /       │
                     │  getNodeType(type)                         │
                     │  ★扩接口: + ui_schema + default_config       │
                     └───┬───────────────┬───────────────┬───────┘
   前端纯数据消费 ────────┘               │               └──────── 画布 Handle
   (palette/表单/默认config)             │               (BaseWorkflowNode.vue:
   - useNodeMeta(适配器)                  │                inputs/outputs→Handle,
   - getNodeDefinition/getDefaultConfig   │                空时最小回退)
   - getNodesByCategory/validateNodeConfig│
   - WorkflowDataTable/MiniMap/GradientEdge (display_name)
   - CreateWorkflowModal (存在性校验)
                                         │
        前端专属、非 API 可提供（保留）     │
        ┌────────────────────────────────┴───────────────────────┐
        │ (b) configComponent 映射: nodeType → () => import(*.vue) │
        │ (c) nodeVisuals.ts: nodeType → {icon: Component, color}  │
        └──────────────────────────────────────────────────────────┘

   构建期旁路（D-01 保留，勿动）:
     node-definitions/*.ts → generate-node-definitions.ts
       → node-definitions.json → registry._load_node_definitions_json()
       → 后端 ui_schema 来源 (NOT 前端运行时来源)

   一致性守护（离线，进 CI）:
     脚本 dump NodeRegistry → fixture(node_type+ports+category) 入库
       → vitest: 前端残留硬编码 ⊆ fixture; palette types ⊆ fixture; 无幽灵节点
```

### Component Responsibilities（核实后的代码地图）

| 关注点 | 文件 | 现状 | 本阶段动作 |
|--------|------|------|-----------|
| 后端节点权威 schema | `server/workflows/nodes/base.py` L591-627 `get_schema()` | 已含 `ui_schema`，**无** `default_config` | 补 `default_config` 派生（`config_schema.properties.*.default`） |
| 传输契约 | `server/workflows/api/serializers.py` L796-809 `NodeTypeSerializer` | **未暴露** `ui_schema`/`default_config` | 增 2 字段（`ui_schema` allow_null、`default_config`） |
| 端点 | `server/workflows/api/views.py` L1348-1369 `NodeTypeViewSet`；`server/workflows/urls.py` L39 | 路由 = `/api/node-types/`（urls 挂 `path("", include("workflows.urls"))` 于 `api/`） | 无需改 |
| 真实节点 | `server/workflows/nodes/data/fetch_space_info.py` | `node_type="fetch_space_info"`, `category=ACTION`, `icon="folder-search"`, outputs=`default`+`error` | 作为对齐基准 |
| 前端运行时源 | `web/src/stores/useNodeTypesStore.ts` | 唯一消费 `/node-types/`；`NodeType` 接口缺 `ui_schema`/`default_config`/`execution_mode` | 扩接口 + 字段 |
| 硬编码源 1（主删目标） | `web/src/types/workflow/registry.ts` L80-277 `NODE_REGISTRY` | legacy 区块 L86-276 含幽灵 `fetch_project_info` L182-192 | 删 legacy；helper 改读 store；保留 `configComponent` 独立映射 |
| 硬编码源 2 | `web/src/components/workflow/editor/utils/portConfig.ts` | `getDefaultPortsForNodeType` 全硬编码端口分支 + `TRIGGER/APPROVAL/ERROR_OUTPUT_NODE_TYPES` | Handle 改读 store；`migratePortId` 保留（见 Pitfall 4） |
| 硬编码源 3 | `web/src/types/workflow/schemas.ts` L377-394 `NODE_CONFIG_SCHEMAS` | 第二套 type→zod 映射，含幽灵 L386 | 幽灵改名；视收敛程度精简 |
| 视觉源（保留） | `web/src/components/workflow/editor/nodes/nodeVisuals.ts` | icon 组件 + color 唯一源，含幽灵 L50 | 幽灵改名；**保留**作前端视觉源 |
| Handle 渲染 | `web/src/components/workflow/editor/nodes/BaseWorkflowNode.vue` L18,44-46 | `ports = getDefaultPortsForNodeType(nodeType)` | 改读 `store.getNodeType(type).inputs/outputs`，空时最小回退 |
| Vue Flow 类型注册 | `web/src/components/workflow/editor/nodes/index.ts` L10,27-33 | 从 `NODE_REGISTRY` keys 生成；已有 Proxy fallback→baseNode | 改从 `allNodeTypeKeys`(nodeVisuals) + specialNodes 生成，去 `NODE_REGISTRY` 依赖 |

### Pattern 1: 后端 `default_config` 派生（零回归扩字段）
**What:** 从 `config_schema.properties.*.default` 收集顶层默认值，省去前端 `schema.parse({})` 反推。
**When to use:** `BaseNode.get_schema()` 内一次性派生，`/node-types/` 与 `/nodes/schemas/` 同时受益。
**Example:**
```python
# server/workflows/nodes/base.py — get_schema() 内新增（示意）
@classmethod
def _get_default_config(cls) -> dict:
    props = (cls.config_schema or {}).get("properties", {}) or {}
    return {k: v["default"] for k, v in props.items() if isinstance(v, dict) and "default" in v}
# get_schema() 返回 dict 增: "default_config": cls._get_default_config()
```
```python
# server/workflows/api/serializers.py — NodeTypeSerializer 增 2 字段
ui_schema = serializers.JSONField(required=False, allow_null=True)
default_config = serializers.JSONField(required=False)
```
**零回归依据：** `get_schema()` 是新增 key、不删改既有 key；DRF `Serializer` 多余 key 不报错；唯一消费方 `useNodeTypesStore` 用 `data.results || data` 整体接收，新增字段不破坏旧消费。

### Pattern 2: store 适配器替换 `NODE_REGISTRY` helper（前端收敛核心）
**What:** `registry.ts` 的 `getNodeDefinition/getDefaultConfig/getNodesByCategory/validateNodeConfig` 改为从 `useNodeTypesStore` 读，但字段命名从 snake_case（`node_type`/`display_name`/`config_schema`/`default_config`）适配为前端既有 camelCase 消费形态。
**When to use:** 所有 8 个消费方经由这层适配，避免逐个改 snake/camel。
**Example:**
```ts
// 适配器（示意）：store NodeType → 前端 NodeDefinition 形态
function toDefinition(nt: NodeType): NodeTypeDefinition {
  return {
    nodeType: nt.node_type,
    displayName: nt.display_name,
    description: nt.description,
    icon: nt.icon,                              // 后端 lucide 名；视觉仍以 nodeVisuals 为准
    color: getNodeVisual(nt.node_type).color,   // 颜色后端不产出 → nodeVisuals
    category: nt.category,
    defaultConfig: nt.default_config ?? {},      // ★ 后端新字段，免 zod.parse({})
    uiSchema: nt.ui_schema ?? undefined,
    configComponent: CONFIG_COMPONENTS[nt.node_type],  // ★ 前端专属映射
  }
}
```

### Pattern 3: Handle 由 store 端口渲染 + 最小回退（D-04）
**What:** `BaseWorkflowNode.vue` 的 `ports` computed 改为读 store。
**Example:**
```ts
const store = useNodeTypesStore()
const ports = computed(() => {
  const nt = store.getNodeType(props.data.nodeType)
  if (!nt) return [{ id: 'default', group: 'input' }, { id: 'default', group: 'output' }] // 首帧/未就绪回退
  return [
    ...nt.inputs.map(p => ({ id: p.name, group: 'input' as const })),
    ...nt.outputs.map(p => ({ id: p.name, group: 'output' as const })),
  ]
})
```
**关键：** computed 依赖 store ref → store 异步就绪后自动重渲染 Handle，解决"首帧空 Handle"。触发器（后端 `inputs=[]`）天然渲染 0 输入，无需 `TRIGGER_NODE_TYPES`；审批节点后端 outputs 直接含 `approved`/`rejected`。

### Pattern 4: 派生节点类型集合（替换硬编码 NODE_TYPES 列表）
- `pages/workflows/[id].vue` L53-55 `hasTriggers` 用 `TRIGGER_NODE_TYPES.includes()` → 改 `store.getNodeType(type)?.category === 'trigger'`。
- `APPROVAL_NODE_TYPES`/`ERROR_OUTPUT_NODE_TYPES`：Handle 既已直接读后端端口集，这两个常量在渲染路径上**不再需要**；仅 `migratePortId` 仍需端口顺序回退（见 Pitfall 4）。

### Anti-Patterns to Avoid
- **删 `configComponent` / `nodeVisuals`：** API 不可能下发 Vue 组件与 Tailwind 渐变；删了画布无图标、配置面板打不开。只删 (a) 类纯数据。
- **同步读 store 假设已就绪：** store 异步加载，任何"挂载即读 nodeTypes"的非响应式逻辑会拿到空数组。必须 computed/响应式 + 回退。
- **用 `validate-node-definitions.ts` 在线请求做 CI 守护：** CI 无后端、需鉴权、不稳定；只作本地工具。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 节点默认配置 | 前端 `zod.parse({})` 反推每个节点默认值 | 后端 `default_config` 字段（D-01） | 反推依赖前端 zod 与后端 schema 同步——正是漂移根因 |
| 端口推断 | `getDefaultPortsForNodeType` 按 type 猜端口 | 后端 NodePort `inputs/outputs` | 后端已是引擎路由权威（Phase 18 target_handle 语义） |
| 触发器/审批/错误端口节点判定 | 维护 `TRIGGER_/APPROVAL_/ERROR_OUTPUT_NODE_TYPES` 列表 | 后端 `category` + 端口集派生 | 列表必与后端漂移 |
| 一致性快照 dump | 手写 EXPECTED_NODES 数组（现状 node-sync.test.ts） | 脚本从 `NodeRegistry` dump fixture | 手维列表必过时（现含幽灵 `fetch_project_info`、缺 `delivery_knowledge_search`） |

**Key insight:** 本阶段所有"漂移"都源于**前端复刻了一份本应只读后端的定义**。凡能由后端字段派生的，一律不要在前端再维护一张表。

## Runtime State Inventory

> 本阶段含"幽灵节点全量改名 `fetch_project_info`→`fetch_space_info`"，属 rename 性质，逐项核查运行时状态。

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | **可能存在** `WorkflowNode.node_type == 'fetch_project_info'` 的存量行：前端 `NODE_REGISTRY` 曾以 `fetch_project_info` 为 key，用户拖此节点保存即落库该 type；但后端 `NodeRegistry` 从无此 type，执行时即为未知节点（早已断裂）。grep 全仓：仅前端代码与 `.planning` 文档命中，**无后端模板/fixture 引用**（内置模板不含它）。 | code 改名为必做；**数据态需 planner 决策**：(a) 加一条数据迁移把存量 `fetch_project_info` 行重写为 `fetch_space_info`（推荐，含 edge handle 不变），或 (b) 仅靠 `index.ts` Proxy fallback→baseNode 容错显示。建议在 plan 加一个"查 DB 是否存在该 type 节点"的核查任务（MEDIUM：无法在静态分析确证存量数据量）。 |
| Live service config | 无。节点定义不写入任何外部服务配置（无 n8n/Datadog/Tailscale 等）。 | None — verified by grep（`fetch_project_info` 仅命中前端+planning） |
| OS-registered state | 无。节点类型不参与任何 OS 级注册（无 Task Scheduler/launchd/pm2）。 | None |
| Secrets/env vars | 无。无 env/secret 以节点 type 命名。 | None |
| Build artifacts | `web/src/types/workflow/node-definitions/node-definitions.json`（构建产物，被后端 `_load_node_definitions_json` 读作 ui_schema 源）；`web/src/components.d.ts`（unplugin 自动生成，含 `FetchProjectInfoConfig` 组件声明 L182）。 | `node-definitions.json` 若节点定义变更需 `pnpm generate:node-defs` 重生成；`components.d.ts` 由 unplugin 自动更新（若物理改名配置组件文件）。 |

**The canonical question:** 全仓文件改名后，仍以 `fetch_project_info` 缓存/存储/注册的运行时系统 = **仅 DB 存量 `WorkflowNode` 行（若有）**。其余皆无。

## Common Pitfalls

### Pitfall 1: store 异步未就绪导致画布空 Handle / palette 闪烁
**What goes wrong:** `useNodeTypesStore.nodeTypes` 在 `fetchNodeTypes()` resolve 前为 `[]`；若 Handle/palette 用非响应式快照读取，首帧渲染空端口、连线错位。
**Why it happens:** `pages/workflows/[id].vue` L57-62 `onMounted` 内 `Promise.all([fetchNodeTypes, fetchWorkflow])` 是**并行**，组件挂载时数据未到。
**How to avoid:** 全部经 `computed`/响应式读 store（store 就绪后自动重渲染）+ `BaseWorkflowNode` 最小回退端口（D-04）。验证步骤：组件测试 mock 空 store 断言回退端口、再 setNodeTypes 断言真实端口出现。
**Warning signs:** 刷新工作流页瞬间节点无 Handle、连线消失后恢复。

### Pitfall 2: `fetch_space_info` 分类从 integration 漂移到 action（palette 分组变化）
**What goes wrong:** 前端旧 `fetch_project_info` 归 `integration`/"数据获取"组、橙色；后端 `fetch_space_info` `category=ACTION`。API 驱动后该节点会落到 action 分组。
**Why it happens:** 真实后端 category 与前端旧硬编码不一致。
**How to avoid:** 接受以后端为准（CONTEXT 终态验收只要求"出现真实 fetch_space_info"，未锁定分组）；如需保留"数据获取"组观感，由 `NodePalette.vue` 的前端分组展示层处理（palette 分组本就是前端维护的展示分组，与 `category` 字段解耦）。planner 注意：`NodePalette.vue` L42-50"数据获取"组是硬编码 group，可继续把 `fetch_space_info` 放此组展示。
**Warning signs:** 节点在 palette 里"消失"（实际是换组了）。

### Pitfall 3: 删 `NODE_REGISTRY` 导致隐性消费方编译/运行时遗漏
**What goes wrong:** `NODE_REGISTRY`/`NodeTypeKey`/`NodeTypeDefinition` 被多处 import；`web/src/types/workflow/index.ts` L17-25 barrel 再导出。漏改一处即 type-check 失败或运行时 `undefined`。
**Why it happens:** 类型与值双重导出 + barrel 扩散。
**How to avoid:** 以本文 Component Responsibilities 表 + 下列 grep 清单逐一核销：消费 `NODE_REGISTRY` 值的 8 文件（`useNodeMeta.ts`/`useDragAndDrop.ts`/`nodes/index.ts`/`WorkflowDataTable.vue`/`WorkflowMiniMap.vue`/`GradientEdge.vue`/`CreateWorkflowModal.vue`/`useWorkflowsStore.ts` 经 `getRegistryDefaultConfig`）；`NodeTypeKey` 类型消费（`nodes/index.ts`、`useNodeMeta.ts`）。`pnpm type-check`（CI L202）作硬门禁。
**Warning signs:** `vue-tsc` 报 `NodeTypeKey` 未找到；运行时 `Cannot read properties of undefined`。

### Pitfall 4: `migratePortId` 在 store 未就绪时退化为 'default'，破坏存量 edge
**What goes wrong:** `useWorkflowsStore.toStoreEdges`（L148-160）在 `fetchWorkflow` 时调 `migratePortId` 把 legacy `output-N/input-N` 句柄换算成语义名；若改为"从 store 取端口顺序"且此刻 store 未就绪，旧句柄会全部回退成 `'default'`，连线错挂。
**Why it happens:** `fetchNodeTypes` 与 `fetchWorkflow` 并行，edge 转换可能先于节点类型加载完成。
**How to avoid:**（D-02 锁定保留 `migratePortId`）二选一：(a) 在 `[id].vue` 改为 `await fetchNodeTypes()` 先于 `fetchWorkflow()`（牺牲少量并行）；或 (b) `migratePortId` 保留一张**最小静态端口回退表**（仅服务于 legacy `input-N/output-N` 索引→名的兜底，不参与正常渲染）。推荐 (a) 顺序化 + 仅对老格式句柄生效（`migratePortId` 已用正则 `^(input|output)-\d+$` 守卫，新句柄直接透传，影响面小）。
**Warning signs:** 打开老工作流后分支连线都连到 default 口、审批 approved/rejected 边丢失。

### Pitfall 5: 前端 `validateNodeConfig` 失去 zod 后校验真空
**What goes wrong:** `validateNodeConfig`（registry.ts L331）当前用各节点 zod schema 做客户端校验；改读 store 后 store 只有 JSON-Schema（`config_schema`），无 zod。若直接删 zod 又不补 JSON-Schema 校验，保存前的前端校验消失。
**Why it happens:** 后端下发的是 JSON Schema，前端校验栈是 zod。
**How to avoid:** 本阶段**不引入 ajv**。两条务实路径，planner 定夺：(a) `validateNodeConfig` 降级为轻量必填/类型检查（基于 `config_schema.required` + `properties.*.type`），完整校验交 Phase 20 后端统一 `WorkflowGraphValidator`（VAL-01/02，dry-run 接口 VAL-03）；(b) 暂保留 `NODE_CONFIG_SCHEMAS`（schemas.ts）的 zod 仅供 `validateNodeConfig`，但这与"删硬编码"目标部分相左。推荐 (a)——与里程碑 Phase 20 校验前移方向一致，避免双轨。
**Warning signs:** 非法 config 在前端不再即时报错（属可接受的临时退化，Phase 20 补齐）。

### Pitfall 6: fixture 快照与后端漂移但无人更新
**What goes wrong:** fixture 是离线快照；后端新增/改节点而不更新 fixture，守护测试反而"假绿"或误红。
**How to avoid:** 提供一键再生成脚本（见 §5）并在 README/脚本头注明"改后端节点后须重跑"；fixture 测试失败信息要明确指向"运行 `pnpm gen:node-fixture`"。理想终态：前端无硬编码节点表，测试退化为"palette types ⊆ fixture ∧ 无幽灵节点"，漂移面大幅缩小。

## Code Examples

### 幽灵节点全量改名命中点（grep 核实清单）
```text
# fetch_project_info → fetch_space_info 需处理的前端点：
web/src/types/workflow/registry.ts      L182-192  legacy 区块（随 NODE_REGISTRY 删除而消失）
web/src/types/workflow/registry.ts      L4        type import FetchProjectInfoConfig
web/src/types/workflow/schemas.ts       L341      type FetchProjectInfoConfig（可改名 FetchSpaceInfoConfig）
web/src/types/workflow/schemas.ts       L363,386  联合类型成员 + NODE_CONFIG_SCHEMAS key
web/src/components/workflow/sidebar/NodePalette.vue   L46  { type:'fetch_project_info', ... }
web/src/components/workflow/editor/nodes/nodeVisuals.ts L50  fetch_project_info: {...}
web/src/components/workflow/editor/nodes/IntegrationNode.vue L21  fetch_project_info: FolderSearch
web/src/components/workflow/config/FetchProjectInfoConfig.vue   配置组件（文件可不改名，节点 key 须对齐）
web/src/types/workflow/index.ts         L49  re-export FetchProjectInfoConfig
web/src/components/__tests__/node-sync.test.ts  L20  EXPECTED_NODES（随重写消失）
web/src/components.d.ts                 L182  自动生成（unplugin 重生成）
# 注：IntegrationNode.vue 是否仍被使用需核实——nodes/index.ts 仅将 parallel/join/ai_plan_generation
#     映射到非 baseNode；IntegrationNode.vue 可能已是死代码，planner 核实后决定改名或删除。
```

### 后端字段级断言（pytest，扩展现有 TestNodeTypeAPI）
```python
# server/tests/workflows/test_api.py — 新增断言（示意）
def test_node_types_expose_ui_schema_and_default_config(self, authenticated_admin_client):
    data = authenticated_admin_client.get("/api/node-types/").data
    by_type = {n["node_type"]: n for n in data}
    assert "fetch_space_info" in by_type
    assert "fetch_project_info" not in by_type   # 幽灵节点不存在于后端
    for n in data:
        assert "ui_schema" in n and "default_config" in n
        props = (n["config_schema"] or {}).get("properties", {})
        assert set(n["default_config"]).issubset(set(props))  # 默认值键 ⊆ schema 字段
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| 前端三套硬编码节点表（NODE_REGISTRY/portConfig/NODE_CONFIG_SCHEMAS）与后端并行 | 后端 NodeRegistry 单一源 + 前端只读缓存 store | 本阶段 | 漂移根除；新增节点只改后端 |
| 默认值前端 `zod.parse({})` 反推 | 后端 `default_config` 字段下发 | 本阶段（D-01） | 去除前后端默认值双轨 |
| 端口 `getDefaultPortsForNodeType` 按 type 猜 | 后端 NodePort `inputs/outputs` 渲染 | 本阶段（D-04） | 与 Phase 18 引擎 target_handle 语义一致 |
| 在线 `validate-node-definitions.ts`（URL 写错、不在 CI） | Vitest 离线 fixture 快照（进 CI） | 本阶段（D-05） | 守护真正在 CI 生效 |

**Deprecated/outdated（本阶段清理）：**
- `node-sync.test.ts` 的手维 `EXPECTED_NODES`（含幽灵 `fetch_project_info`、缺 `delivery_knowledge_search`）—— 改 fixture 驱动。
- `validate-node-definitions.ts` L77 `GET /api/workflows/node-types/`（错误路径）—— 正确为 `/api/node-types/`。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | 存量 DB 中可能有 `node_type='fetch_project_info'` 的 `WorkflowNode` 行 | Runtime State Inventory | 若实际为 0，则数据迁移任务多余（低风险，迁移幂等）；若有且不处理，老工作流该节点显示为 fallback baseNode |
| A2 | `IntegrationNode.vue` 可能为死代码（仅 BaseWorkflowNode/DynamicPortNode/AIPlanGenerationNode 被 `nodes/index.ts` 映射） | Code Examples | 若仍被使用，改名/删除判断需调整——planner 须 grep 核实其引用 |
| A3 | CI 守护只能离线（`ci.yaml` 仅 `pnpm test:unit:coverage`，不起后端） | Summary / §5 | 已核实 ci.yaml L191-206，HIGH 而非 ASSUMED |

**说明：** A1/A2 为需在 plan/execute 期用 DB 查询或 grep 确证的数据态/死代码假设；A3 已被 ci.yaml 核实（非假设）。

## Open Questions

1. **存量 `fetch_project_info` 节点数据是否需要迁移？**
   - What we know: 后端从无此 type；内置模板不引用；前端曾以此为 key 可被用户保存。
   - What's unclear: 生产/开发 DB 是否真有此 type 的 `WorkflowNode` 行。
   - Recommendation: plan 加一个核查任务（`WorkflowNode.objects.filter(node_type="fetch_project_info").count()`）；>0 则加幂等数据迁移重写为 `fetch_space_info`，=0 则仅靠 Proxy fallback 容错。

2. **`icon` 映射策略（Claude's Discretion）：后端 lucide 名 vs 前端组件/iconify。**
   - What we know: 后端 `icon` 是 lucide 字符串（如 `folder-search`）；`nodeVisuals.ts` 持 lucide-vue-next 组件 + 渐变色；palette/minimap 用 iconify class（`icon-[lucide--xxx]`）。
   - What's unclear: 是否把 `nodeVisuals` 作唯一视觉源（推荐）还是建后端名→前端值映射。
   - Recommendation: 保留 `nodeVisuals.ts` 为前端视觉权威（icon 组件 + color），API `icon` 仅作新节点缺省映射输入；完整规范化是 Deferred Idea。

3. **`validateNodeConfig` 客户端校验降级范围（见 Pitfall 5）。**
   - Recommendation: 降为基于 `config_schema.required`/`type` 的轻量检查，完整校验交 Phase 20；避免引入 ajv。

## Environment Availability

> 本阶段为纯代码/配置变更（Django/Vue 源码 + 测试），依赖均为仓库既有工具链。

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `uv` + pytest 栈 | 后端 serializer/字段测试 | 既有（`server/pyproject.toml`） | 既有 | — |
| `pnpm` + vitest/tsx | 前端单测 + fixture 生成脚本 | 既有（`web/package.json`） | pnpm@10.34.2 | — |
| 运行中的后端（仅 fixture 生成时，可选） | 从 API dump fixture（若选 API 方式而非 Django 管理命令 dump） | 不强依赖 | — | 用 Django 管理命令/pytest 直接 `NodeRegistry.get_all_schemas()` dump，免起 HTTP 服务 |

**Missing dependencies with no fallback:** 无。
**Missing dependencies with fallback:** fixture 生成可不依赖在线后端——直接在 Python 侧 dump `NodeRegistry`（推荐），或离线读 `node-definitions.json` + 一份后端导出的精简 JSON。

## Validation Architecture

> `nyquist_validation: true`（`.planning/config.json` L20）。前端 vitest + 后端 pytest 双侧。

### Test Framework
| Property | Value |
|----------|-------|
| Framework (前端) | `vitest@^4` + `@vue/test-utils` + `happy-dom`（`web/package.json`） |
| Framework (后端) | `pytest@>=9` + `pytest-django` + `pytest-asyncio`（`server/pyproject.toml`） |
| Config file | `web/vite.config.ts`(test) / `server/pyproject.toml`([tool.pytest]) |
| Quick run (前端) | `pnpm -C web test:unit -- src/components/__tests__/node-sync.test.ts` |
| Quick run (后端) | `cd server && uv run pytest tests/workflows/test_api.py -k NodeType -x` |
| Full suite (前端) | `pnpm -C web test:unit`（CI: `test:unit:coverage`） |
| Full suite (后端) | `cd server && uv run pytest tests/workflows/ -x` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SSOT-01 | `/api/node-types/` 暴露 `ui_schema`+`default_config`；`fetch_space_info` 在、`fetch_project_info` 不在；`default_config` 键⊆`config_schema` | unit (pytest) | `uv run pytest tests/workflows/test_api.py -k NodeType -x` | ✅ 扩展 `TestNodeTypeAPI` |
| SSOT-01 | 前端 palette/默认 config/displayName 经 store 取得（无 NODE_REGISTRY） | unit (vitest) | `pnpm -C web test:unit -- src/composables/__tests__/useNodeMeta*.test.ts` | ❌ Wave 0（新建 store 适配器测试） |
| SSOT-02 | `BaseWorkflowNode` 由 store inputs/outputs 渲染 Handle；空 store 回退单 in/out；审批节点出 approved/rejected | component (vitest) | `pnpm -C web test:unit -- src/components/.../BaseWorkflowNode*.test.ts` | ❌ Wave 0 |
| SSOT-03 | 前端残留硬编码节点 ⊆ 后端 fixture；palette types ⊆ fixture；无幽灵节点 | unit (vitest) | `pnpm -C web test:unit -- src/components/__tests__/node-sync.test.ts` | ⚠️ 重写现有 |
| SSOT-03 | `validate-node-definitions.ts` URL = `/api/node-types/` | unit (vitest) | `pnpm -C web test:unit -- src/components/__tests__/validate-nodes.test.ts` | ⚠️ 现有断言仅查 'node-types' 子串（改 URL 仍绿）；planner 可加严断言不含 `workflows/node-types` |

### Sampling Rate
- **Per task commit:** 相关侧 quick run（前端 node-sync / 后端 NodeType）。
- **Per wave merge:** 双侧 full suite（`pnpm -C web test:unit` + `uv run pytest tests/workflows/`）。
- **Phase gate:** `pnpm -C web lint && pnpm -C web type-check && pnpm -C web test:unit` 全绿 + 后端 `tests/workflows/` 全绿，再进 `/gsd-verify-work`。

### Wave 0 Gaps
- [ ] fixture 生成脚本：`web/scripts/generate-node-fixture.ts`（或 Django 管理命令）从 `NodeRegistry.get_all_schemas()` dump `{node_type, category, inputs[].name, outputs[].name}` 精简集到 `web/src/types/workflow/__fixtures__/node-types.fixture.json`，入库。提供 `pnpm gen:node-fixture` 脚本。
- [ ] 重写 `web/src/components/__tests__/node-sync.test.ts`：删 `EXPECTED_NODES`，改读 fixture 对账（palette types ⊆ fixture、无 `fetch_project_info`/`code_implement`/`technical_plan` 幽灵、parallel/join 端口多 in/out 仍校验）。
- [ ] 新建 store 适配器单测（`getNodeDefinition/getDefaultConfig/getNodesByCategory` 从 mock store 取值）。
- [ ] 新建 `BaseWorkflowNode` Handle 渲染测试（空 store 回退 + 就绪后真实端口）。
- [ ] 后端 `TestNodeTypeAPI` 扩字段级断言。
- [ ] 修正 `validate-node-definitions.ts` L77 URL。

## Security Domain

> `security_enforcement: true`，ASVS L1。本阶段为只读节点元数据 API 扩字段 + 前端渲染收敛，攻击面极小。

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | `NodeTypeViewSet` 已 `IsAuthenticated`，不改 |
| V3 Session Management | no | 不涉及 |
| V4 Access Control | low | `/node-types/` 已要求认证；节点元数据非租户敏感、全局静态 |
| V5 Input Validation | yes | 客户端 config 校验在收敛中可能临时降级（Pitfall 5）；保存期权威校验由 Phase 20 `WorkflowGraphValidator` 承接（VAL-01/02），本阶段不放松后端既有校验 |
| V6 Cryptography | no | 不涉及 |

### Known Threat Patterns for {Django DRF + Vue}
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| 节点元数据中误带敏感字段（如凭证/路径） | Information Disclosure | `default_config` 仅从 `config_schema.properties.*.default` 取静态默认值，不含运行时凭证；review 确保无敏感默认值 |
| 前端校验弱化后非法 config 落库 | Tampering | 保存期后端校验为权威（Phase 20）；本阶段不依赖前端校验作安全边界 |

## Sources

### Primary (HIGH confidence) — 仓库代码核实
- `server/workflows/nodes/base.py` L560-627（`get_schema`/`_get_ui_schema`）、`registry.py`（全文）、`api/serializers.py` L785-809、`api/views.py` L1348-1369、`urls.py`、`friday/urls.py` L28-76、`nodes/data/fetch_space_info.py`
- `web/src/stores/useNodeTypesStore.ts`、`types/workflow/registry.ts`、`schemas.ts` L360-396、`components/workflow/editor/utils/portConfig.ts`、`editor/nodes/BaseWorkflowNode.vue`、`nodeVisuals.ts`、`nodes/index.ts`、`composables/useNodeMeta.ts`、`node-config/composables/useNodeConfig.ts`/`useNodeSchema.ts`、`sidebar/NodePalette.vue`、`stores/useWorkflowsStore.ts` L130-209、`pages/workflows/[id].vue` L40-74
- 测试/脚本：`web/scripts/generate-node-definitions.ts`、`validate-node-definitions.ts`、`components/__tests__/node-sync.test.ts`、`validate-nodes.test.ts`、`server/tests/workflows/test_api.py` L365-393
- CI：`.github/workflows/ci.yaml` L191-206（`lint`/`type-check`/`test:unit:coverage`/`build`）
- 配置：`.planning/config.json`（nyquist/security 开关）

### Secondary / Tertiary
- 无外部 WebSearch 依据——本阶段纯仓内重构，无新库/外部规范。

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 不引入新依赖，全用既有栈，已逐文件核实。
- Architecture / 消费方映射: HIGH — 8 消费方与端口/视觉源均经 grep + 阅读核实。
- 后端扩字段零回归: HIGH — `get_schema` 增 key + serializer 增字段，唯一消费方整体接收。
- Runtime 数据态 (A1) / 死代码 (A2): MEDIUM — 需 plan/execute 期 DB 查询与 grep 确证。
- Pitfalls: HIGH — 均由代码并行加载/双轨结构推得。

**Research date:** 2026-06-13
**Valid until:** 2026-07-13（稳定仓内重构；若 Phase 18/20 改动节点 registry 或校验层需复核）

