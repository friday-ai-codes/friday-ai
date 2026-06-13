# Phase 19: 节点定义单一事实源 (ssot) - Pattern Map

**Mapped:** 2026-06-13
**Files analyzed:** 18（后端 3 + 前端 11 + 测试/脚本/fixture 4，含 3 个新建）
**Analogs found:** 18 / 18（全部命中仓内现有范式；多为"自身扩展"型 analog）

> 本阶段是**契约收敛重构**，几乎不引入新文件类型——绝大多数"analog"就是被改文件自身的现有结构或同目录姊妹文件。新建文件仅 3 个（fixture 生成脚本、fixture JSON、组件/适配器单测），均有明确既有范式可抄。

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `server/workflows/nodes/base.py` (`get_schema`) | model/schema | transform | 自身 `get_schema()` L591-627 | exact（增量扩 key） |
| `server/workflows/api/serializers.py` (`NodeTypeSerializer`) | serializer | request-response | 自身 L796-809 + `NodePortSerializer` L785-793 | exact |
| `server/tests/workflows/test_api.py` (`TestNodeTypeAPI`) | test | request-response | 自身 `test_node_types_have_metadata` L383-392 | exact |
| `web/src/stores/useNodeTypesStore.ts` (`NodeType` 接口) | store | CRUD/read-cache | 自身 L22-33 | exact |
| `web/src/types/workflow/registry.ts` (helper 适配器) | utility | transform | `useNodeTypesStore` + 自身 helper L292-350 | role-match |
| `web/.../editor/utils/portConfig.ts` (`getDefaultPortsForNodeType`) | utility | transform | 自身 L46-94 | exact（降级为回退表） |
| `web/.../editor/nodes/BaseWorkflowNode.vue` (`ports` computed) | component | event-driven (render) | 自身 L41-46 + store 响应式读 | exact |
| `web/.../editor/nodes/index.ts` (Vue Flow 类型注册) | config/registration | transform | 自身 L27-45（已半收敛到 nodeVisuals） | exact |
| `web/src/types/workflow/schemas.ts` (`NODE_CONFIG_SCHEMAS` 幽灵改名) | model | transform | 自身 L341/363/386 | exact（rename） |
| `web/.../editor/nodes/nodeVisuals.ts` (幽灵改名) | config | transform | 自身 L50 | exact（rename） |
| `web/.../sidebar/NodePalette.vue` (幽灵改名 + 分组展示) | component | event-driven | 自身 L46 数据获取组 | exact（rename） |
| `web/.../config/FetchProjectInfoConfig.vue` (节点 key 对齐) | component | request-response | 同目录其它 `*Config.vue` | role-match |
| `web/src/types/workflow/index.ts` (barrel re-export) | config | transform | 自身 L17-25/L49 | exact |
| `web/src/components/__tests__/node-sync.test.ts` (重写) | test | transform | 自身 + `validate-node-definitions.ts` palette 正则 | role-match |
| `web/scripts/validate-node-definitions.ts` (URL 修正) | script | request-response | 自身 L77 | exact |
| **`web/scripts/generate-node-fixture.ts`** (NEW) | script | file-I/O / transform | `web/scripts/generate-node-definitions.ts`（全文范式） | exact-analog |
| **`web/src/types/workflow/__fixtures__/node-types.fixture.json`** (NEW) | build artifact | file-I/O | `node-definitions/node-definitions.json` | role-match |
| **新建 vitest**（store 适配器 + BaseWorkflowNode Handle 渲染） | test | event-driven | `node-sync.test.ts` + `@vue/test-utils` 既有用法 | role-match |

## Pattern Assignments

### `server/workflows/nodes/base.py` — `get_schema()` 增 `default_config`（model/transform）

**Analog:** 自身 `get_schema()`，纯增量加一个 key——不删改既有 key（零回归依据见 RESEARCH Pattern 1）。

**现有结构**（`server/workflows/nodes/base.py` L591-627）：

```591:627:server/workflows/nodes/base.py
    @classmethod
    def get_schema(cls) -> dict:
        """获取完整的节点 Schema（用于前端）"""
        return {
            "node_type": cls.node_type,
            "display_name": cls.display_name,
            "description": cls.description,
            "icon": cls.icon,
            "category": cls.category.value,
            "config_schema": cls.config_schema,
            "ui_schema": cls._get_ui_schema(),
            "inputs": [
                # ...
            ],
            "outputs": [
                # ...
            ],
            "requires_container": cls.requires_container,
            "is_blocking": cls.is_blocking,
            "execution_mode": cls.execution_mode,
        }
```

**派生 helper 范式**（仿照同文件已有的 `_get_ui_schema()` classmethod L581-589）：

```python
@classmethod
def _get_default_config(cls) -> dict:
    """从 config_schema.properties.*.default 收集顶层默认值。"""
    props = (cls.config_schema or {}).get("properties", {}) or {}
    return {
        k: v["default"]
        for k, v in props.items()
        if isinstance(v, dict) and "default" in v
    }
```

**改动点：** `get_schema()` 返回 dict 增 `"default_config": cls._get_default_config()`。中文 docstring 惯例保留。

---

### `server/workflows/api/serializers.py` — `NodeTypeSerializer` 暴露 2 字段（serializer/request-response）

**Analog:** 自身。现有字段全是显式声明的 `serializers.XxxField()`；`config_schema` 用 `JSONField()`，直接照抄。

**现有结构**（`server/workflows/api/serializers.py` L796-809）：

```796:809:server/workflows/api/serializers.py
class NodeTypeSerializer(serializers.Serializer):
    """Serializer for node type definition (for frontend node palette)."""

    node_type = serializers.CharField()
    display_name = serializers.CharField()
    description = serializers.CharField()
    icon = serializers.CharField()
    category = serializers.CharField()
    config_schema = serializers.JSONField()
    inputs = NodePortSerializer(many=True)
    outputs = NodePortSerializer(many=True)
    requires_container = serializers.BooleanField()
    is_blocking = serializers.BooleanField()
    execution_mode = serializers.CharField()
```

**改动点：** 增两行（`ui_schema` 允许 null，因 `_get_ui_schema()` 可能返回 None）：

```python
    ui_schema = serializers.JSONField(required=False, allow_null=True)
    default_config = serializers.JSONField(required=False)
```

---

### `server/tests/workflows/test_api.py` — `TestNodeTypeAPI` 扩字段级断言（test）

**Analog:** 自身 `test_node_types_have_metadata`（同类 fixture/断言风格）。

**现有结构**（`server/tests/workflows/test_api.py` L383-392）：

```383:392:server/tests/workflows/test_api.py
    def test_node_types_have_metadata(self, authenticated_admin_client):
        """Test that node types include metadata."""
        url = "/api/node-types/"
        response = authenticated_admin_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        for node_type in response.data:
            assert "node_type" in node_type
            assert "display_name" in node_type
            assert "category" in node_type
```

**新增断言**（RESEARCH §Code Examples 已给示意）：`fetch_space_info` 在、`fetch_project_info` 不在；每个节点含 `ui_schema`/`default_config`；`default_config` 键 ⊆ `config_schema.properties`。沿用 `authenticated_admin_client` fixture 与 `/api/node-types/` 路径。

---

### `web/src/stores/useNodeTypesStore.ts` — `NodeType` 接口扩字段（store）

**Analog:** 自身。`NodeType` 接口照已有字段补 3 项；`fetchNodeTypes` 的 `data.results || data` 整体接收无需改。

**现有结构**（`web/src/stores/useNodeTypesStore.ts` L22-33）：

```22:33:web/src/stores/useNodeTypesStore.ts
export interface NodeType {
  node_type: string
  display_name: string
  description: string
  icon: string
  category: 'trigger' | 'action' | 'control' | 'integration' | 'ai'
  config_schema: Record<string, any>
  inputs: NodePort[]
  outputs: NodePort[]
  requires_container: boolean
  is_blocking: boolean
}
```

**改动点：** 接口增 `ui_schema?: Record<string, any> | null`、`default_config?: Record<string, any>`、`execution_mode?: string`（execution_mode 后端已返回但接口缺）。`getNodeType(type)` getter（L60-62）作为下游适配器/Handle 渲染的读取入口，保持不变。

---

### `web/src/types/workflow/registry.ts` — helper 改 store 适配器 + 删 legacy（utility/transform）

**Analog:** `useNodeTypesStore`（数据源）+ 自身 helper 签名（对外契约不变）。这是前端收敛核心。

**现有 helper**（`web/src/types/workflow/registry.ts` L291-350，对外签名要保留）：

```291:311:web/src/types/workflow/registry.ts
/** 获取节点定义 */
export function getNodeDefinition<K extends NodeTypeKey>(
  nodeType: K,
): (typeof NODE_REGISTRY)[K]
export function getNodeDefinition(nodeType: string): NodeTypeDefinition | undefined
export function getNodeDefinition(nodeType: string): NodeTypeDefinition | undefined {
  if (hasNodeDefinition(nodeType)) {
    return NODE_REGISTRY[nodeType]
  }
  return undefined
}

/** 获取节点默认配置 */
export function getDefaultConfig<K extends NodeTypeKey>(
  nodeType: K,
): (typeof NODE_REGISTRY)[K]['defaultConfig']
export function getDefaultConfig(nodeType: string): unknown
export function getDefaultConfig(nodeType: string): unknown {
  const def = getNodeDefinition(nodeType)
  return def?.defaultConfig
}
```

**保留项（API 不可提供，禁删）：** `configComponent` 懒加载映射须抽成独立 `Record<string, () => Promise<...>>`（现散落在 legacy 各项的 `configComponent:` 字段，如 L95/107/.../275）。`color` 经 `nodeVisuals.getNodeVisual(type).color` 取。

**store→Definition 适配器范式**（RESEARCH Pattern 2 示意，snake→camel）：

```ts
function toDefinition(nt: NodeType): NodeTypeDefinition {
  return {
    nodeType: nt.node_type,
    displayName: nt.display_name,
    description: nt.description,
    icon: nt.icon,
    color: getNodeVisual(nt.node_type).color, // 颜色后端不产出 → nodeVisuals
    category: nt.category,
    defaultConfig: nt.default_config ?? {},     // ★ 后端新字段，免 zod.parse({})
    uiSchema: nt.ui_schema ?? undefined,
    configComponent: CONFIG_COMPONENTS[nt.node_type], // ★ 前端专属映射
  }
}
```

**删除目标：** `NODE_REGISTRY` legacy 区块 L86-276（含幽灵 `fetch_project_info` L182-192）。⚠️ Pitfall 3：`NodeTypeKey`/`NodeTypeDefinition` 被 8 处消费 + barrel 再导出（见下"Shared Patterns / 消费方核销清单"），逐一核销，`pnpm type-check` 作硬门禁。

---

### `web/.../editor/utils/portConfig.ts` — `getDefaultPortsForNodeType` 降级为回退表（utility）

**Analog:** 自身。正常渲染路径不再调用它（改由 store 端口渲染，见 BaseWorkflowNode）；它仅作 `migratePortId` 的端口顺序回退源。

**现有结构**（`web/.../editor/utils/portConfig.ts` L68-122）：

```100:122:web/src/components/workflow/editor/utils/portConfig.ts
export function migratePortId(
  handle: string,
  nodeType: string | undefined,
  direction: 'input' | 'output',
): string {
  if (!/^(input|output)-\d+$/.test(handle)) {
    return handle
  }

  if (!nodeType) {
    return 'default'
  }

  const ports = getDefaultPortsForNodeType(nodeType)
  const dirPorts = ports.filter(p => p.group === direction)
  const index = Number.parseInt(handle.split('-')[1], 10)

  if (index < dirPorts.length) {
    return dirPorts[index].id
  }

  return 'default'
}
```

**改动点（D-02）：** `migratePortId` **保留**（禁删——兼容存量 edge，正则 `^(input|output)-\d+$` 守卫，新句柄透传）。`TRIGGER/APPROVAL/ERROR_OUTPUT_NODE_TYPES` 三常量在渲染路径上不再需要；Pitfall 4：若 `migratePortId` 仍依赖端口顺序，二选一（推荐 `[id].vue` 改 `await fetchNodeTypes()` 先于 `fetchWorkflow()`，或保留一张最小静态回退表仅服务 legacy 句柄）。

---

### `web/.../editor/nodes/BaseWorkflowNode.vue` — Handle 由 store 渲染（component/event-driven）

**Analog:** 自身。`ports` computed 已是响应式 + `inputPorts`/`outputPorts`/`portLeft` 多端口分布逻辑可全部复用，只换数据源。

**现有结构**（`web/.../editor/nodes/BaseWorkflowNode.vue` L41-46）：

```41:46:web/src/components/workflow/editor/nodes/BaseWorkflowNode.vue
const visual = computed(() => getNodeVisual(props.data.nodeType))
const style = computed(() => useNodeStyle(visual.value.color).value)

const ports = computed(() => getDefaultPortsForNodeType(props.data.nodeType))
const inputPorts = computed(() => ports.value.filter(p => p.group === 'input'))
const outputPorts = computed(() => ports.value.filter(p => p.group === 'output'))
```

**改动点（D-04，RESEARCH Pattern 3）：** 引入 `useNodeTypesStore`，`ports` 改读 store inputs/outputs，store 未就绪时最小回退：

```ts
const nodeTypesStore = useNodeTypesStore()
const ports = computed<PortMetadata[]>(() => {
  const nt = nodeTypesStore.getNodeType(props.data.nodeType)
  if (!nt) {
    return [{ id: 'default', group: 'input' }, { id: 'default', group: 'output' }] // 首帧/离线回退
  }
  return [
    ...nt.inputs.map(p => ({ id: p.name, group: 'input' as const })),
    ...nt.outputs.map(p => ({ id: p.name, group: 'output' as const })),
  ]
})
```

模板 Handle `v-for`（L145-153 input / L176-184 output）+ `:style="{ left: portLeft(...) }"` 全部不变。computed 依赖 store ref → store 异步就绪后自动重渲染（Pitfall 1）。

---

### `web/.../editor/nodes/index.ts` — 去 `NODE_REGISTRY` 依赖（config/registration）

**Analog:** 自身——已半收敛：`registeredTypes` 由 `NODE_REGISTRY` keys + `allNodeTypeKeys`(nodeVisuals) 合并，且有 Proxy fallback→baseNode。

**现有结构**（`web/.../editor/nodes/index.ts` L27-45）：

```27:45:web/src/components/workflow/editor/nodes/index.ts
/** 从 NODE_REGISTRY + nodeVisuals 合并生成节点类型映射 */
const registryTypes = Object.fromEntries(
  (Object.keys(NODE_REGISTRY) as NodeTypeKey[]).map(key => [
    key,
    specialNodes[key] ?? baseNode,
  ]),
)

/** nodeVisuals 中有但 NODE_REGISTRY 中没有的节点类型也注册（如 manual_trigger） */
const visualOnlyTypes = Object.fromEntries(
  allNodeTypeKeys
    .filter(key => !(key in registryTypes))
    .map(key => [key, specialNodes[key] ?? baseNode]),
)
```

**改动点：** 删 `NODE_REGISTRY`/`NodeTypeKey` import，类型映射改纯从 `allNodeTypeKeys`(nodeVisuals) + `specialNodes` 生成；Proxy fallback 保留（兜底未知 type）。

---

### 幽灵节点改名 `fetch_project_info`→`fetch_space_info`（rename，多文件）

**Analog:** 各文件自身。RESEARCH §Code Examples 已给完整 grep 命中清单。逐点对齐：

| 文件 | 行 | 动作 |
|------|----|----|
| `web/src/types/workflow/registry.ts` | L4 import / L182-192 / 此随 NODE_REGISTRY 删除消失 | 删 + import 改名 |
| `web/src/types/workflow/schemas.ts` | L341 type / L363 联合 / L386 `NODE_CONFIG_SCHEMAS` key | `FetchProjectInfoConfig`→`FetchSpaceInfoConfig`、key 改 `fetch_space_info` |
| `web/.../editor/nodes/nodeVisuals.ts` | L50 | key 改名（**保留**为视觉源） |
| `web/.../sidebar/NodePalette.vue` | L46 | `type:'fetch_space_info'`（Pitfall 2：可继续放"数据获取"展示组） |
| `web/.../config/FetchProjectInfoConfig.vue` | — | 节点 key/类型对齐（文件物理改名可选，D-03） |
| `web/src/types/workflow/index.ts` | L49 | re-export 改名 |
| `web/src/components.d.ts` | L182 | unplugin 自动重生成（勿手改） |

⚠️ A2：`IntegrationNode.vue` L21 命中点须先 grep 核实是否死代码（`nodes/index.ts` 未映射它）——存活则改名，死代码则可删。
⚠️ A1：plan 加核查任务 `WorkflowNode.objects.filter(node_type="fetch_project_info").count()`，>0 则加幂等数据迁移。

---

### `web/src/components/__tests__/node-sync.test.ts` — 重写为 fixture 驱动（test）

**Analog:** 自身的 palette 正则提取（L9-12）+ `validate-node-definitions.ts` 同款正则 L58-60。删手维 `EXPECTED_NODES`。

**现有 palette 提取范式（复用）**：

```9:12:web/src/components/__tests__/node-sync.test.ts
const paletteSource = fs.readFileSync(path.join(sidebarDir, 'NodePalette.vue'), 'utf-8')
const paletteSet = new Set(
  [...paletteSource.matchAll(/(?:type:\s*|fromDef\()'([^']+)'/g)].map(m => m[1]),
)
```

**改动点（D-05 终态）：** import fixture JSON（`__fixtures__/node-types.fixture.json`），断言：① palette types ⊆ fixture node_type 全集；② 无幽灵（`fetch_project_info`/`code_implement`/`technical_plan` 均不在 palette）；③ `fetch_space_info` 在；④ parallel/join 端口（多 in/out）改对 fixture 端口集断言而非 `getDefaultPortsForNodeType`。

---

### `web/scripts/validate-node-definitions.ts` — URL 修正（script）

**Analog:** 自身 L77。

```77:77:web/scripts/validate-node-definitions.ts
    const res = await fetch(`${apiBase}/api/workflows/node-types/`)
```

**改动点（D-05）：** `/api/workflows/node-types/` → `/api/node-types/`。此脚本仅作本地工具（CI 不跑、需鉴权），非 CI 守护。

---

### `web/scripts/generate-node-fixture.ts`（NEW，script/file-I/O）

**Analog（直抄范式）：** `web/scripts/generate-node-definitions.ts`（全文）——同款 `tsx` 脚本结构：dynamic import → map → `fs.writeFileSync(JSON.stringify(..., 2))` → console 提示。

**现有范式**（`web/scripts/generate-node-definitions.ts` L16-44）：

```16:44:web/scripts/generate-node-definitions.ts
async function main(): Promise<void> {
  const { ALL_NODE_DEFINITIONS } = await import('../src/types/workflow/node-definitions/index')

  const nodes = Object.values(ALL_NODE_DEFINITIONS).map((def) => {
    const jsonSchema = (def.schema as any).toJSONSchema()
    return {
      node_type: def.nodeType,
      // ...
    }
  })

  const output = { generated_at: ..., node_count: nodes.length, nodes }
  const outputPath = path.resolve(__dirname, '...node-definitions.json')
  fs.writeFileSync(outputPath, JSON.stringify(output, null, 2), 'utf-8')
  console.log(`✓ Generated ${nodes.length} node definitions -> ...`)
}
main().catch((err) => { ...; process.exit(1) })
```

**差异（关键）：** 数据源**不是**前端 `ALL_NODE_DEFINITIONS`，而是后端 `NodeRegistry`（fixture 的目的就是对账后端）。CI 无后端 → 推荐 **Django 管理命令/pytest dump**（`NodeRegistry.get_all_schemas()` 直接产 JSON），或脚本走 HTTP 取在线后端再落盘。dump 精简集 `{node_type, category, inputs[].name, outputs[].name}` → `web/src/types/workflow/__fixtures__/node-types.fixture.json`，纳入版本库。
**package.json scripts 范式**（仿 `web/package.json` L19-20）：加 `"gen:node-fixture": "tsx scripts/generate-node-fixture.ts"`（或 Django 侧 `manage.py` 命令）。Pitfall 6：脚本头注明"改后端节点后须重跑"，失败信息指向该命令。

---

### 新建 vitest（store 适配器 + BaseWorkflowNode Handle 渲染，test/event-driven）

**Analog:** `node-sync.test.ts`（vitest `describe/it/expect` 结构）+ 仓内既有 `@vue/test-utils`/`happy-dom` 组件测试范式（`web/package.json` test 栈）。
- 适配器测试：mock `useNodeTypesStore`（setNodeTypes 注入假数据），断言 `getNodeDefinition/getDefaultConfig/getNodesByCategory` 从 store 取值。
- BaseWorkflowNode 测试：空 store → 断言回退端口（单 in/out）；setNodeTypes 后 → 断言真实端口（如 `ai_coding` 出 `plan` 输入、审批节点出 `approved`/`rejected` 输出）出现（Pitfall 1 验证）。

## Shared Patterns

### 唯一运行时数据源：`useNodeTypesStore`
**Source:** `web/src/stores/useNodeTypesStore.ts`（`getNodeType(type)` L60-62、`nodeTypesByCategory` L41-57、`fetchNodeTypes` L64-77）
**Apply to:** registry.ts 适配器、BaseWorkflowNode.vue、`[id].vue` 派生集合（`hasTriggers` 用 `getNodeType(t)?.category === 'trigger'`）、所有原读 `NODE_REGISTRY` 的消费方。
**关键：** 始终经 `computed`/响应式读（store 异步就绪自动重渲染）；禁"挂载即同步读 nodeTypes"（Pitfall 1）。

### 前端专属、API 不可提供（保留，禁删）
**Source:** `web/.../editor/nodes/nodeVisuals.ts`（icon 组件 + color，`getNodeVisual()` L94-96、`allNodeTypeKeys` L99）；`configComponent` 懒加载映射（从 registry.ts legacy 抽出）。
**Apply to:** registry.ts 适配器（color/configComponent）、index.ts（类型注册）、BaseWorkflowNode（icon）。

### snake→camel 适配
**Source:** RESEARCH Pattern 2 `toDefinition()`。
**Apply to:** registry.ts 内所有 store→前端 `NodeTypeDefinition` 转换；避免逐消费方改命名。

### 消费方核销清单（Pitfall 3 防遗漏）
**消费 `NODE_REGISTRY` 值（8 处）：** `useNodeMeta.ts`、`useDragAndDrop.ts`、`editor/nodes/index.ts`、`WorkflowDataTable.vue`、`WorkflowMiniMap.vue`、`GradientEdge.vue`、`CreateWorkflowModal.vue`、`useWorkflowsStore.ts`（经 `getRegistryDefaultConfig`）。
**消费 `NodeTypeKey` 类型：** `editor/nodes/index.ts`、`useNodeMeta.ts`。
**barrel 再导出：** `web/src/types/workflow/index.ts` L17-25/L49。
**硬门禁：** `pnpm type-check`（CI）。`useNodeMeta.ts` 现完全转发 registry helper（L31-66）——helper 内部换源后，其对外 API 可不变。

### 后端零回归扩字段
**Source:** RESEARCH Pattern 1。`get_schema()` 增 key（不删改）+ serializer 增字段（DRF 多余 key 不报错）+ store `data.results || data` 整体接收 → 三处全向后兼容。

## No Analog Found

无。本阶段所有改/建文件均有仓内现成范式（多为自身扩展或同款脚本/测试）。新建 `generate-node-fixture.ts` 直接套用 `generate-node-definitions.ts`；fixture JSON 套用 `node-definitions.json`；新建 vitest 套用 `node-sync.test.ts` + 既有组件测试栈。

## Metadata

**Analog search scope:** `server/workflows/{nodes,api,urls.py}`、`server/tests/workflows/`、`web/src/{stores,types/workflow,composables}`、`web/src/components/workflow/{editor,sidebar,config}`、`web/scripts/`、`web/package.json`
**Files scanned:** 12 文件精读（base.py / serializers.py / test_api.py / useNodeTypesStore.ts / registry.ts / BaseWorkflowNode.vue / portConfig.ts / nodeVisuals.ts / useNodeMeta.ts / nodes/index.ts / node-sync.test.ts / validate-node-definitions.ts / generate-node-definitions.ts）
**Pattern extraction date:** 2026-06-13
