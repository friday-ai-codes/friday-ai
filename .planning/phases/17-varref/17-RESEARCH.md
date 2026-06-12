# Phase 17: 变量引用链路修复 - Research

**Researched:** 2026-06-12
**Domain:** Django 工作流引擎模板变量解析 + Vue3 编辑器引用生成（纯内部代码改造，无新依赖）
**Confidence:** HIGH（全部关键结论来自本仓库代码逐行核实）

## Summary

本阶段是"引用生成 → 保存落库 → 执行解析"三段链路的契约修复。研究确认了完整的故障链：前端用 nanoid 自行生成 shortId 并用它构造 `{{nodes.<shortId>.*}}` 引用写进 config，但 bulk-update 的 `toBackendNodes` 根本不发送 short_id，且后端两个 serializer 一个将 short_id 设为 read-only、另一个不含该字段——新建节点落库时拿到的是服务端随机生成的另一个 short_id，配置里的引用从落库那一刻就注定漂移 `[VERIFIED: codebase]`。

解析端的问题同样核实清楚：`render_template` 对节点 ID 不存在已抛 ValueError（含大小写提示），但字段缺失静默回退空串（且 `get_previous_output` 只做**扁平 key 查找**，`data.name` 这种嵌套路径永远取不到）、未知前缀原样保留字面量；`get_template_value`/`_resolve_simple_path` 则连节点 ID 校验都没有，未知节点/未知前缀一律返回空串——两个 API 错误语义不一致。异常传播链路是通的：节点 execute() 内抛出的 ValueError 会被 scheduler 的 `except Exception` 捕获并 `amark_failed` 写入 `NodeExecution.error_message`，所以本阶段不需要动引擎主干，核心工作是重写解析核心 + 打通保存路径 + 统一前端三入口。

**Primary recommendation:** 解析核心抽取为 `server/workflows/engine/template_resolver.py`（纯函数 + 类型化异常 `TemplateResolutionError`，`ExecutionContext` 两个 API 委托同一核心）；VAR-01 复用 `templates/loader.py` 已有的 `_rewrite_template_refs` 改写引擎；前端新建单一 util `web/src/utils/variableRef.ts` 收口三入口。

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### 解析失败语义（VAR-02 — 全里程碑语义地基，一次定对）
- 失败时机：节点执行前的模板渲染/输入收集阶段即失败（fail-fast），返回 `NodeResult(status="failed", error=...)`，不进入节点业务逻辑、不静默替换为空串
- 错误信息必须包含：完整模板片段、失败的引用路径、失败原因分类（节点 ID 不存在 / 字段不存在 / 未知前缀）、可用候选（可用节点 ID 列表或该节点输出的顶层字段 keys）
- 未知前缀（如 `{{foo.bar}}` 不属于 input/context/config/nodes/global/trigger/$）：显式报错，不再原样保留 `{{...}}` 字面量输出
- 字段路径缺失（节点存在但字段不存在）：报错指明"节点 X 输出中不存在字段 path Y"，废除 render 路径上默认空串回退
- 错误信息语言：中文（与项目后端约定一致），并以结构化字段（reference / reason / available）落入 NodeExecution.error_message，供 Phase 21 错误展示直接复用

#### short_id 同步策略（VAR-01）
- bulk-update 保存时：客户端提供的 short_id 直接落库为权威值；服务端校验工作流内唯一性
- short_id 缺失或冲突时：服务端生成新 short_id，并同步重写该工作流所有节点 config 中引用旧 short_id 的 `{{nodes.<old>.*}}` 为新值——保证"保存成功 ⇒ 引用可解析"不变式
- 解析端兼容：`previous_outputs` 查找同时支持 short_id 与节点 UUID（归一化查找），存量工作流不回退
- 不做全局迁移脚本强制重写历史数据；靠保存路径收敛（下次保存即修复）

#### 引用格式统一（VAR-03）
- 统一规范格式：`{{nodes.<short_id>.<field.path>}}`；VariablePicker、端口复制、SmartInput 三个入口全部生成该格式，禁止再生成 UUID 形式引用
- JSONPath 高级语法（`{{$...[...]}}`）保留现状不动，属于高级用法不在入口生成范围内
- `{{trigger.*}}`/`{{global.*}}` 等非节点前缀格式保持现有语法，三入口生成时也走统一的引用构造函数（前端单一 util，杜绝三处各写一遍）

#### 嵌套路径与测试（VAR-04）
- `{{nodes.x.data.name}}` 点路径逐层下钻 dict；list 数字索引（`items.0.name`）顺带支持；中途非 dict/list 或键缺失 → 解析失败报错
- `render_template` 与 `get_template_value` 两个 API 行为一致（同一套解析核心），错误语义相同
- 专项单元测试覆盖：错误节点 ID（含大小写近似提示）、字段不存在、未知前缀、UUID vs short_id 双键、嵌套 dict/list 路径、单变量保类型（get_template_value）、多变量字符串渲染（render_template）

### Claude's Discretion
- 解析核心是否抽取独立模块（如 `workflows/engine/template_resolver.py`）还是留在 base.py 内重构——按改动面最小且可测性最好选择
- 错误信息具体文案措辞
- 前端引用构造 util 的文件位置与命名

### Deferred Ideas (OUT OF SCOPE)
- 历史工作流数据的一次性 short_id 引用迁移脚本（按需，保存路径已能收敛）
- JSONPath 语法的入口级支持（高级用法维持手写）
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| VAR-01 | bulk-update 保存后 short_id 引用保证可解析（客户端 short_id 落库或服务端重写） | 漂移根因链已完整定位（见"现状链路"§1）；可复用 `loader.py:_rewrite_template_refs` 作为服务端重写引擎；serializer/视图改动点明确 |
| VAR-02 | 解析失败显式报错（指明引用、节点/字段、原因），不再静默空串/保留字面量 | 现有两个 API 的静默点逐行定位（见"现状链路"§2）；异常→`NodeExecution.error_message` 传播链路已验证畅通（scheduler.py:1013-1029） |
| VAR-03 | 三入口生成统一 short_id 格式引用 | 三入口现状全部核实：picker/SmartInput 用 shortId（但有 UUID 前 8 位兜底 bug）、端口复制用 UUID（见"现状链路"§3） |
| VAR-04 | 嵌套路径支持 + 解析器专项单测 | 嵌套路径失败根因 = `get_previous_output` 扁平 key 查找（base.py:130-135）；现有测试覆盖确认为零（仅 mock，无解析器专项测试） |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 模板解析核心（语法、嵌套下钻、错误分类） | API / Backend（engine） | — | 执行时唯一事实源，前端不解析只生成 |
| short_id 落库与唯一性校验 | API / Backend（serializer + bulk-update 视图） | — | 持久化契约归属服务端 |
| config 引用重写（short_id 冲突时） | API / Backend（bulk-update 事务内） | — | 必须与节点保存同事务，保证不变式 |
| 引用字符串生成（三入口） | Frontend（单一 util） | — | 纯展示/编辑期行为 |
| previous_outputs 双键写入（UUID + short_id） | API / Backend（scheduler 两处写入点） | — | 执行期运行时状态 |
| 结构化错误展示 | Frontend（Phase 21，本阶段只定数据契约） | Backend 产出结构化 error_message | 本阶段产出格式，Phase 21 消费 |

## 现状链路（核心调查结论，全部 [VERIFIED: codebase]）

### §1 VAR-01：short_id 漂移的完整根因链

1. **前端生成**：`web/src/utils/shortId.ts` 用 nanoid 生成 3 位 shortId（1 字母 + 2 字母数字）；`useDragAndDrop.ts:130,178` 新建节点时赋值 `shortId: generateShortId()`。用户随即在 config 中写入 `{{nodes.<该shortId>.*}}`。
2. **保存不发送**：`useWorkflowsStore.ts:185-208 toBackendNodes` 构造 bulk-update payload 时**不包含 short_id 字段**。
3. **后端忽略**：`server/workflows/api/serializers.py` — `WorkflowNodeSerializer` 将 `short_id` 列入 `read_only_fields`（:208）；`WorkflowNodeCreateSerializer`（:241-260）的 fields 根本不含 short_id。新建节点走 `WorkflowNode.objects.create(...)`，short_id 取模型默认 `generate_short_id`（`models/node.py:30-35`，服务端随机 3 位）。
4. **保存后前端被覆盖**：`useWorkflowsStore.ts:379-384` 保存成功后用服务端返回的 nodes 覆盖 store（`toStoreNodes`），shortId 变成服务端值，**但 config 里已写入的旧 shortId 引用原样保存进了数据库**。
5. **执行时爆炸**：scheduler 把输出按 `node_outputs[uuid]` 和 `node_outputs[short_id]`（服务端值）双键写入（scheduler.py:713-715, 798-801），引用里的前端 shortId 两个键都匹配不上 → `render_template` 抛 `ValueError: 节点 ID 'xxx' 不存在`。
6. **唯一性现状**：`short_id` 模型字段无 unique 约束，仅有 `Index(fields=["workflow", "short_id"])`（node.py:121-123）——服务端唯一性校验必须在应用层做（与锁定决策一致）。
7. **公共 util 已存在**：`server/common/short_id.py` 提供 `generate_unique_short_id(existing_ids)`（冲突时自动加长，3→12 位），冲突重生成可直接复用。
8. **重写引擎已存在**：`server/workflows/templates/loader.py:63-95 _rewrite_template_refs(config, id_map)` —— 正则 `\{\{(\s*(?:\$\.?)?nodes\.)(<ids>)(\.)` 递归遍历 dict/list/str，把 `{{nodes.<旧>.}}` 改写为新 ID，**同时覆盖 `$nodes.` JSONPath 形式**。这就是 VAR-01"服务端重写"所需的全部机制，建议提为公共函数复用，勿重写。

**bulk-update 入口**：`server/workflows/api/views.py:491-517 bulk_update` → `sync_to_async(_bulk_update_nodes_and_edges)`（:153-201，`transaction.atomic()` 内逐节点 update-or-create + 全量重建 edges）。short_id 落库 + 唯一性校验 + 冲突重写都应进这个事务。

### §2 VAR-02/VAR-04：解析端现状（`server/workflows/nodes/base.py`）

| 场景 | `render_template`（:341-429） | `get_template_value` → `_resolve_simple_path`（:431-608） |
|------|------------------------------|------------------------------------------------|
| 节点 ID 不存在 | ✅ 抛 ValueError（:399-414，含大小写近似提示 + 可用 ID 列表） | ❌ 静默：`previous_outputs.get(node_id, {})` → 空 dict → 返回 `""` |
| 字段不存在（节点存在） | ❌ 静默空串：`get_previous_output(node_id, key, "")`（:415） | ❌ 静默 `""`（:604-606 None→""） |
| 嵌套路径 `data.name` | ❌ 取不到：`get_previous_output` 用 `output.get("data.name")` **扁平 key 查找**（:130-135），永远 miss → 空串 | ❌ 同左 |
| 未知前缀 `{{foo.bar}}` | ❌ 原样保留字面量 `match.group(0)`（:427） | ❌ 返回 `""`（:593-595） |
| JSONPath `{{$...[...]}}` | `_resolve_jsonpath`（:464-542）已校验节点 ID（:490-515）；零匹配返回 `""`；结果为 "" 时 render 保留字面量（:373） | 同核心（锁定决策：保留现状不动） |

关键不对称：`get_input`/`get_trigger_data` 支持点分嵌套路径（:101-120, :137-156），唯独 `get_previous_output` 是扁平 key——这就是 VAR-04 嵌套路径 bug 的唯一根因。

**错误传播链（已验证畅通，不需要动引擎）**：节点在 `execute()` 内调用 `context.render_template(...)`（典型如 `nodes/ai/prompt.py:332-333`，位于业务逻辑之前）→ ValueError 逸出 execute → scheduler `_execute_node` 的 `except Exception`（scheduler.py:1013-1029）→ `last_error = str(exc)` → `node_execution.amark_failed(last_error, error_code=...)` → `NodeExecution.error_message`（execution.py:647-655）。即：解析器抛类型化异常天然满足"渲染阶段 fail-fast、不进业务逻辑、落 error_message"。

**调用面**：`render_template`/`get_template_value` 的调用方共 ~20 个节点文件（prompt、plan_generation、context_retrieval、http、feishu 系列、loop、pr、branch、approval、chat_question 等）+ `prompts/services.py`。这些调用点本身不用改——语义变化由解析核心统一生效；但计划需含一个"广撒网回归"任务，确认没有节点用裸 `except Exception` 把解析错误吞成别的语义（抽样 prompt.py 无此问题）。

### §3 VAR-03：前端三入口现状

| 入口 | 文件 | 生成格式 | 问题 |
|------|------|---------|------|
| 变量选择器（设计态） | `VariablePicker.vue` ← `useDesignTimeVariables.ts:171,186,214` | `nodes.<shortId>.<field>` | 兜底 `extNode.shortId \|\| node.id.slice(0, 8)`——UUID 前 8 位**永远无法解析**（双键里没有这个键） |
| 变量选择器（运行时分支） | `VariablePicker.vue:162-173` | `nodes.<nodeId>.<key>`，nodeId 来自 `context.node_outputs` 的键 | 该字典 UUID 与 short_id 双键并存 → 同一字段出现两条、可能选中 UUID 形式 |
| SmartInput | `smart-input/SmartInput.vue:43,62` ← 同一 `useDesignTimeVariables` | 同 picker | 同 picker（含 slice(0,8) 兜底）；chip 序列化 `{{path}}`（SmartInput.vue:121-145）格式本身没问题 |
| 端口复制 | `NodePortsDisplay.vue:40-42` | `{{nodes.<props.nodeId>.<port>}}` | `nodeId` = `currentNodeId` = `selectedNodeId` = **UUID**（NodeConfigPanel.vue:200 传入）→ 直接产 UUID 引用 |
| （第四处，顺带）Schema 展示路径 | `useNodeSchema.ts:106-108 getOutputPath` | `shortId \|\| selectedNodeId`（UUID 兜底） | 被 `NodeSchemaDisplay.vue:144,171` 展示；统一 util 时一并收口 |

UUID 形式引用在运行时**其实能解析**（previous_outputs 双键），所以 VAR-03 是"格式统一"而非"修复不可用"；但 `slice(0,8)` 兜底产生的引用是**真坏的**，必须消灭。

`NodePortsDisplay` 的使用方：`config/` 下多个节点配置组件（ContextRetrievalConfig、DeliveryKnowledgeSearchConfig 等）以 `:node-id="currentNodeId"` 传 UUID——改造方案要么改传 shortId、要么组件内部经 store 由 UUID 查 shortId（后者改动面最小，单点收口）。

**已有可复用前端资产**：`useDownstreamVarCheck.ts` 的 `extractNodeVarRefs`（正则 `\{\{nodes\.<id>\.([\w.]+)\}\}`，同时查 UUID 和 short_id 两种引用）；测试范式见 `composables/__tests__/use-downstream-var-check.test.ts`（vitest 纯函数测试）。

## Standard Stack

### Core（全部为既有依赖，无新增安装）

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Django ORM + DRF serializer | 既有（django>=5.1, drf>=3.15） | short_id 落库、唯一性校验、bulk-update 事务 | 项目既定栈 [VERIFIED: codebase] |
| Python `re` + 纯函数 | stdlib | 模板解析核心 | 现有解析器即 re 实现；无需引入模板引擎 |
| `jsonpath-ng` | 已安装（探测通过） | `{{$...}}` 高级语法（保持现状） | 现有 `_resolve_jsonpath` 依赖 [VERIFIED: 本机 import 通过] |
| `nanoid`（前端） | 已安装 | shortId 生成（保持现状） | `web/src/utils/shortId.ts` 既有实现 |
| pytest + pytest-django + factory fixtures | 既有 | 解析器专项单测 | `server/tests/workflows/conftest.py` 已有 Workflow/Node 工厂 fixture |
| vitest | ^4 既有 | 前端 util 单测 | `pnpm test:unit`，范式见 `use-downstream-var-check.test.ts` |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| re 手写解析核心重构 | Jinja2（task/ 已有依赖） | Jinja2 语法与现有 `{{nodes.x.y}}` 兼容但语义不同（StrictUndefined 行为、过滤器），迁移面大且破坏 JSONPath 共存——**不采用** |
| 在 error_message 存 JSON | 新增 `error_details` JSONField | 锁定决策明确"落入 NodeExecution.error_message"，不开新字段 |

## Package Legitimacy Audit

本阶段**不安装任何外部包**（纯内部代码改造，前后端依赖全部既有）。无需 slopcheck。

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```text
编辑期（前端）                          保存期（后端）                       执行期（后端）
┌──────────────────┐    bulk-update   ┌─────────────────────────┐       ┌──────────────────────────┐
│ variableRef.ts   │  nodes 含        │ _bulk_update_nodes_     │       │ scheduler                │
│ (新·单一构造util) │  short_id ──────▶│  and_edges (事务内)      │       │  node_outputs[uuid]=out  │
│   ▲   ▲   ▲      │                  │  1. 校验 short_id 格式/  │       │  node_outputs[short]=out │
│   │   │   │      │                  │     工作流内唯一          │       └──────────┬───────────────┘
│ Picker SmartInput│                  │  2. 缺失/冲突→生成新ID    │                  │ previous_outputs
│ 端口复制(改传short)│                  │  3. _rewrite_template_  │                  ▼
└──────────────────┘                  │     refs 重写全部 config │       ┌──────────────────────────┐
        引用格式统一:                  │  4. 落库（同事务）        │       │ template_resolver (新核心)│
        {{nodes.<short_id>.<path>}}   └─────────────────────────┘       │  render_template ┐       │
                                       不变式:保存成功⇒引用可解析         │  get_template_value┴→同核心│
                                                                        │  嵌套下钻 dict/list        │
                                                                        │  失败→TemplateResolution-  │
                                                                        │  Error{reference,reason,   │
                                                                        │  available}                │
                                                                        └──────────┬───────────────┘
                                                                                   │ 异常逸出 execute()
                                                                                   ▼
                                                                        scheduler except → amark_failed
                                                                        → NodeExecution.error_message
                                                                          (中文 + 结构化字段, Phase 21 消费)
```

### Pattern 1: 解析核心抽取（推荐方案，属 Claude's Discretion）

**What:** 新建 `server/workflows/engine/template_resolver.py`，包含：类型化异常 `TemplateResolutionError(reference, reason, available, template)`、嵌套路径下钻函数（dict 键 + list 数字索引）、统一的前缀分发与节点 ID 归一化查找（short_id 与 UUID 双支持）。`ExecutionContext.render_template` / `get_template_value` 改为薄委托。
**When to use:** 满足"两个 API 同一套核心、错误语义相同"的锁定决策；独立模块可用纯 dict 构造测试，**不需要 Django DB**，可测性最优。
**Why not 留在 base.py:** base.py 已 863 行且混合 NodeResult/BaseNode/normalize_repositories 多职责；两 API 共核心意味着大段新代码，独立模块改动面反而更小（base.py 只删旧逻辑 + 加委托）。

### Pattern 2: 类型化异常承载结构化错误

**What:**

```python
# 新 server/workflows/engine/template_resolver.py（示意）
class TemplateResolutionError(ValueError):
    """模板解析失败。继承 ValueError 保持对既有 except ValueError 调用方的兼容。"""
    def __init__(self, *, template: str, reference: str, reason: str,
                 available: list[str], message: str):
        super().__init__(message)
        self.template = template      # 完整模板片段
        self.reference = reference    # 失败的引用路径，如 nodes.aB1.data.name
        self.reason = reason          # node_not_found | field_not_found | unknown_prefix
        self.available = available    # 可用节点 ID 或该节点输出顶层字段 keys
```

scheduler `_execute_node` 的 `except Exception` 分支（scheduler.py:1013）增加对该异常的识别：error_message 写入"中文人类可读文案 + 结构化 JSON"（具体编码格式属文案 discretion，但必须落 error_message——锁定决策）。
**When to use:** 这是满足"fail-fast 在渲染阶段 + NodeResult(failed) + error_message 结构化"三个锁定决策的最小改动路径：节点 execute() 顶部的 render 调用抛异常 → 不进业务逻辑 → scheduler 捕获 → amark_failed。不需要引擎中心化预渲染（那会破坏 code 节点脚本等"故意不渲染"的字段，改动面巨大）。

### Pattern 3: 保存路径 short_id 收敛（VAR-01）

**What:** 在 `_bulk_update_nodes_and_edges` 事务内：
1. serializer 接受 short_id（`WorkflowNodeSerializer` 从 read_only_fields 移除；`WorkflowNodeCreateSerializer` fields 增加）+ 格式校验（字母开头、字母数字、≤12 位——与 `common/short_id.py` 约束一致；必须拒绝含 `.`/`{`/`}` 等会破坏模板语法的字符）
2. 收集本次 payload 全部 short_id，应用层校验工作流内唯一
3. 缺失/冲突的节点用 `generate_unique_short_id(existing_ids)` 重生成，并记录 `old_short_id → new_short_id` 映射
4. 用提为公共函数的 `_rewrite_template_refs` 对**该工作流全部节点**（含本次未改动的）config 执行重写后落库
**Warning:** 前端 `toBackendNodes` 必须同步加上 `short_id: node.shortId`，否则服务端拿不到客户端权威值，一切白搭。

### Anti-Patterns to Avoid

- **引擎中心化预渲染 config**：code 节点脚本、JSONPath 字段、提示词里的字面 `{{` 示例都会被误伤；保持"节点自己决定渲染哪些字段"，只让解析核心变严格。
- **在三个前端组件里各写一遍引用拼接**：锁定决策要求单一 util；`NodePortsDisplay`、`useDesignTimeVariables`、`useNodeSchema` 全部 import 同一构造函数。
- **给 short_id 加 DB unique 约束来做唯一性**：存量数据可能已有重复（无约束历史），迁移会炸；按锁定决策走应用层校验。
- **删除 previous_outputs 的 UUID 键**：锁定决策要求双键兼容，存量工作流的 UUID 引用不回退。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| config 引用批量重写 | 新写正则遍历器 | `templates/loader.py:_rewrite_template_refs`（提为公共函数） | 已处理 `$nodes.` JSONPath 变体、递归 dict/list、正则转义；新写必漏 |
| 唯一 short_id 生成 | 自写重试循环 | `common/short_id.py:generate_unique_short_id` | 已实现冲突自动加长（3→12位） |
| 前端引用提取（测试用） | 新写正则 | `useDownstreamVarCheck.ts:extractNodeVarRefs` | 已支持 UUID/short_id 双形式 + 点路径 |
| JSONPath 解析 | 任何改动 | 现状 `_resolve_jsonpath` 原样保留 | 锁定决策：JSONPath 保留现状不动 |

## Common Pitfalls

### Pitfall 1: "可用节点 ID 列表"会把 UUID 和 short_id 混着报
**What goes wrong:** `previous_outputs` 双键（UUID + short_id），现有错误提示 `available_ids = list(nodes_data.keys())` 会列出 `['550e8400-...', 'aB1', ...]`，候选列表噪音大。
**How to avoid:** 错误信息的 available 候选应过滤为 short_id 形态（或去重为"每节点一个最优标识"）。注意 scheduler 有**两处**双键写入点（运行中 :713-715/:798-810 与 resume 路径 `_collect_all_outputs` :1527-1532），错误候选的口径要与两处一致。

### Pitfall 2: 严格化字段缺失误伤其他前缀
**What goes wrong:** 把"字段不存在→报错"扩大到 `input./trigger./global.` 所有前缀，会把大量依赖"可选字段缺省为空串"的存量工作流（如 prompt 节点渲染含 `{{trigger.payload.xxx}}` 的提示词）瞬间打挂；Phase 18 还要重做 trigger 注入。
**How to avoid:** 严格语义按 VAR-02 的三分类落地：`nodes.*` 的节点不存在/字段不存在 + 所有未知前缀。`input./trigger./global./context./config.` 的字段缺失行为本阶段保持现状（见 Open Questions #1，需在计划中显式定界）。
**Warning signs:** 改完后跑全量工作流测试，若大批与变量无关的节点测试失败，多半是这里扩大化了。

### Pitfall 3: `{{nodes.x}}`（只有两段）落入未知前缀分支
**What goes wrong:** 现 render 的 nodes 分支要求 `len(parts) >= 3`（base.py:394），`{{nodes.aB1}}` 不满足会掉到"无法解析保留字面量"；严格化后会报"未知前缀 nodes"——误导。
**How to avoid:** 解析核心对 `nodes` 前缀单独处理段数不足的情形，报"引用缺少字段路径"而非未知前缀。

### Pitfall 4: 重写发生在服务端，但前端 store 里仍是旧引用
**What goes wrong:** 服务端冲突重写后，若前端不用响应数据刷新 config，用户下一次保存又会把旧引用写回去（兜底重写能再救，但体验是"引用反复变"）。
**How to avoid:** `saveWorkflow` 已用响应覆盖 nodes（useWorkflowsStore.ts:379-384），确认 bulk-update 响应的 `WorkflowSerializer` 返回重写后的 config 即可（它返回 DB 状态，天然满足）；计划中加一条前端断言测试。

### Pitfall 5: `WorkflowNodeSerializer` 不只服务 bulk-update
**What goes wrong:** 该 serializer 同时被单节点 `node_detail` PUT/PATCH（views.py:409-427）使用；放开 short_id 可写后，单节点更新路径也能改 short_id，但那条路径**没有**唯一性校验和引用重写。
**How to avoid:** 要么唯一性/格式校验下沉到 serializer 的 `validate_short_id`（重写仍只在 bulk-update 做），要么单独为 bulk-update 开 serializer 变体。计划需明确选择。

### Pitfall 6: render_template 对 JSONPath 空结果保留字面量
**What goes wrong:** base.py:373 `return str(result) if result != "" else match.group(0)`——JSONPath 解析成功但结果为空时保留 `{{...}}` 字面量，是另一处"静默字面量"。锁定决策说 JSONPath 现状不动，但"未知前缀不再保留字面量"与"JSONPath 空结果保留字面量"并存时要在测试里明确预期，避免实现时顺手"修"掉。
**How to avoid:** 给 JSONPath 现状行为补"现状锁定"测试（characterization test），与新严格语义的边界写清楚。

### Pitfall 7: 模板/导入路径的 short_id 是另一个入口
**What goes wrong:** `Workflow.from_json` 导入（export 含 short_id 但导入不设置）与模板实例化（loader.py 已有重写）是 bulk-update 之外的节点创建路径。导入路径会产生与 bulk-update 相同的漂移。
**How to avoid:** 本阶段范围按 ROADMAP 只锁 bulk-update；导入路径列为已知缺口（Open Questions #2），TPL 归 Phase 20。

### Pitfall 8: pytest 网络隔离与异步 ORM
**What goes wrong:** server 测试套件启用 pytest-socket 网络隔离；解析器若设计为依赖 DB 的方法，单测会被迫挂 `@pytest.mark.django_db` 拖慢。
**How to avoid:** 解析核心做成纯函数（输入 previous_outputs/input_data 等 dict），单测零 DB；bulk-update 的落库/重写测试用既有 conftest 工厂 + `django_db`。

## Code Examples

### 现状：嵌套路径取不到的根因

```130:135:server/workflows/nodes/base.py
    def get_previous_output(self, node_id: str, key: str | None = None, default: Any = None) -> Any:
        """获取上游节点输出"""
        output = self.previous_outputs.get(node_id, {})
        if key:
            return output.get(key, default)
        return output
```

`output.get("data.name")` 是扁平查找——嵌套下钻应仿照 `get_input`（base.py:101-120）的逐段遍历，并按锁定决策补 list 数字索引与"中途断路即报错"。

### 现状：未知前缀保留字面量（VAR-02 要废除的行为）

```427:429:server/workflows/nodes/base.py
            return match.group(0)  # 无法解析则保持原样

        return re.sub(r"\{\{(.+?)\}\}", replace, template)
```

### 可复用：服务端引用重写引擎

```79:95:server/workflows/templates/loader.py
    pattern = re.compile(
        r"\{\{(\s*(?:\$\.?)?nodes\.)(" + "|".join(re.escape(k) for k in id_map) + r")(\.)"
    )

    def _rewrite_value(value: Any) -> Any:
        if isinstance(value, str):
            return pattern.sub(
                lambda m: "{{" + m.group(1) + id_map[m.group(2)] + m.group(3),
                value,
            )
        if isinstance(value, dict):
            return {k: _rewrite_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_rewrite_value(item) for item in value]
        return value

    return _rewrite_value(config)
```

### 前端统一构造 util（新建，命名属 discretion，建议）

```typescript
// web/src/utils/variableRef.ts（新建）
/** 统一的节点输出引用构造：{{nodes.<shortId>.<fieldPath>}} */
export function buildNodeRef(shortId: string, fieldPath: string): string {
  return `{{nodes.${shortId}.${fieldPath}}}`
}
/** 非节点前缀（input/trigger/global 等）保持现有语法 */
export function buildPrefixRef(prefix: 'input' | 'trigger' | 'global' | 'context' | 'config', path: string): string {
  return `{{${prefix}.${path}}}`
}
```

三入口改造点：`useDesignTimeVariables.ts:171`（删除 `node.id.slice(0, 8)` 兜底——store 节点必有 shortId，新建即生成）、`NodePortsDisplay.vue:40-42`（UUID→shortId）、`useNodeSchema.ts:106-108`（删 UUID 兜底）、`VariablePicker.vue` 运行时分支（过滤/归一化 node_outputs 的双键）。

## State of the Art

| Old Approach（现状） | Current Approach（本阶段目标） | When Changed | Impact |
|--------------|------------------|--------------|--------|
| 字段缺失/未知前缀静默空串或保留字面量 | 三分类显式报错 + 结构化 error_message | Phase 17 | Phase 18/20/21 全部消费此语义 |
| short_id 服务端随机、客户端值丢弃 | 客户端权威值落库 + 冲突服务端重写 | Phase 17 | "保存成功 ⇒ 引用可解析"不变式 |
| 三入口三种格式（shortId / UUID / UUID 前 8 位） | 单一 util、统一 `{{nodes.<short_id>.<path>}}` | Phase 17 | 与解析器语法完全一致 |

**Deprecated/outdated（本阶段后不应再出现）：**
- `node.id.slice(0, 8)` 兜底引用：产物永远不可解析，直接删除
- `{{nodes.<UUID>.*}}` 新生成：解析端保留兼容，生成端禁止

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | 所有调用 render_template 的节点都在业务副作用之前渲染（fail-fast 时机依赖此事实，抽样 prompt.py 证实，未逐一核查全部 ~20 个文件） | Pattern 2 | 个别节点先做副作用再渲染会导致"失败但已产生副作用"；计划应含逐节点核查任务 |
| A2 | 存量数据中同一工作流内 short_id 无重复（模型无 unique 约束，理论可重复） | Pattern 3 | 唯一性校验需对存量重复容错（视为冲突走重生成+重写路径即可自愈） |

## Open Questions

1. **`input./trigger./global.` 等非 nodes 前缀的字段缺失是否也报错？**
   - What we know: 锁定决策的三分类是"节点 ID 不存在 / 字段不存在 / 未知前缀"，"废除 render 路径上默认空串回退"出现在"字段路径缺失（节点存在但字段不存在）"条目下，语境是 nodes 引用。
   - What's unclear: 是否扩大到全部前缀。
   - Recommendation: 本阶段严格化限定 `nodes.*` + 未知前缀；其余前缀维持现状并补现状锁定测试，留给 Phase 18（trigger 注入）/20（保存校验）再收紧。计划中必须显式写出此定界。
2. **工作流导入（`Workflow.from_json`）不设置 short_id，导入即漂移。**
   - Recommendation: 超出 ROADMAP 对本阶段的定义（bulk-update），列为已知缺口移交 Phase 20 或 backlog；若计划者认为顺手（导入处按 export 的 short_id 落库 + 同样唯一性处理），可作可选任务。
3. **结构化字段在 error_message 中的具体编码**（纯文案/格式 discretion）：建议"中文一句话 + `\n` + JSON 对象（reference/reason/available/template）"，Phase 21 可 `JSON.parse` 最后一行。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| uv（pytest 运行） | 后端单测 | ✓ | 0.10.2 | — |
| pnpm（vitest 运行） | 前端单测 | ✓ | 10.30.3 | — |
| jsonpath-ng | JSONPath 现状回归 | ✓ | server venv 内可 import | — |

**Missing dependencies with no fallback:** 无（纯内部代码改造）。

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | 后端 pytest>=9.0.2 + pytest-django；前端 vitest ^4 |
| Config file | `server/pyproject.toml`（[tool.pytest]）；`web/`（vitest 默认 + package.json scripts） |
| Quick run command | `cd server && uv run pytest tests/workflows/test_template_resolver.py -x` |
| Full suite command | `cd server && uv run pytest` ；前端 `cd web && pnpm test:unit run` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| VAR-01 | bulk-update 落库客户端 short_id；冲突重生成且 config 同事务重写；保存成功⇒引用可解析（不变式） | integration（django_db） | `cd server && uv run pytest tests/workflows/test_bulk_update_short_id.py -x` | ❌ Wave 0 |
| VAR-02 | 节点不存在/字段不存在/未知前缀 → TemplateResolutionError；scheduler 落 error_message（中文+结构化） | unit + integration | `cd server && uv run pytest tests/workflows/test_template_resolver.py tests/workflows/test_error_handling.py -x` | ❌ Wave 0（test_error_handling.py 已存在可扩展） |
| VAR-03 | 三入口生成 `{{nodes.<short_id>.<path>}}`；slice(0,8) 兜底删除 | unit（vitest） | `cd web && pnpm test:unit run src/utils/__tests__/variableRef.test.ts` | ❌ Wave 0 |
| VAR-04 | 嵌套 dict/list 路径、UUID vs short_id 双键、单变量保类型、多变量渲染 | unit（纯函数零 DB） | `cd server && uv run pytest tests/workflows/test_template_resolver.py -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `cd server && uv run pytest tests/workflows/test_template_resolver.py -x`（<30s，纯函数）
- **Per wave merge:** `cd server && uv run pytest tests/workflows/ -x` + `cd web && pnpm test:unit run`
- **Phase gate:** 后端全量 `uv run pytest` + 前端 `pnpm test:unit run` 全绿后进入 `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `server/tests/workflows/test_template_resolver.py` — 覆盖 VAR-02/VAR-04 全场景 + JSONPath/非 nodes 前缀现状锁定测试
- [ ] `server/tests/workflows/test_bulk_update_short_id.py` — 覆盖 VAR-01（复用 conftest 既有工厂 fixture）
- [ ] `web/src/utils/__tests__/variableRef.test.ts` — 覆盖 VAR-03 构造函数（范式照抄 `use-downstream-var-check.test.ts`）
- [ ] 框架安装：无需（pytest/vitest 均就绪）

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | 不涉及（bulk-update 已有 IsAuthenticated + WorkflowPermission） |
| V3 Session Management | no | — |
| V4 Access Control | yes | bulk-update 既有 `WorkflowPermission` + ProjectScopedQueryset 不得绕过；重写只作用于**同一 workflow** 的节点 config |
| V5 Input Validation | yes | short_id 服务端格式白名单（`^[A-Za-z][A-Za-z0-9]{0,11}$`）——防注入模板语法字符（`.`、`{`、`}`、空白）破坏解析器或重写正则 |
| V6 Cryptography | no | — |

### Known Threat Patterns for Django + 模板解析

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| 恶意 short_id 注入正则（重写引擎拼接 alternation） | Tampering | `_rewrite_template_refs` 已 `re.escape`；落库前白名单校验双保险 |
| 错误信息泄露其他节点输出内容 | Information Disclosure | available 候选只列**键名**（节点 ID/字段 key），绝不包含输出值 |
| 跨工作流引用重写越权 | Elevation of Privilege | 重写范围严格限定 `workflow.nodes`（既有事务函数作用域天然满足，测试锁定） |

## Sources

### Primary (HIGH confidence — 全部为本仓库代码逐行核实)
- `server/workflows/nodes/base.py`（解析器全量 :101-608）
- `server/workflows/engine/scheduler.py`（双键写入 :713-715/:798-810/:1527-1532；异常→error_message :999-1035；_collect_inputs :1073-1087）
- `server/workflows/api/views.py`（bulk-update :153-201/:491-517）+ `serializers.py`（short_id read-only :208/:241-260）
- `server/workflows/models/node.py`（short_id 字段 :30-35，索引 :121-123）+ `models/execution.py`（amark_failed :647-655）
- `server/common/short_id.py`、`server/workflows/templates/loader.py`（:63-95 重写引擎）
- `web/src/stores/useWorkflowsStore.ts`（:185-208/:367-398）、`web/src/utils/shortId.ts`、`web/src/composables/useDesignTimeVariables.ts`（:171/:186/:214）
- `web/src/components/workflow/NodePortsDisplay.vue`（:40-42）、`VariablePicker.vue`（:162-173/:246-253）、`smart-input/SmartInput.vue`（:43/:62/:121-145）、`node-config/NodeConfigPanel.vue`（:200）、`composables/useNodeSchema.ts`（:106-113）
- 本机环境探测：uv 0.10.2 / pnpm 10.30.3 / jsonpath_ng import 通过

### Secondary / Tertiary
- 无（本阶段无外部技术选型，不依赖网络资料）

## Metadata

**Confidence breakdown:**
- 现状链路与根因: HIGH — 每条结论附文件行号，逐行验证
- 推荐架构（resolver 抽取 + 类型化异常）: HIGH — 基于已验证的异常传播链与锁定决策推导，无外部不确定性
- Pitfalls: HIGH — 全部来自代码事实；唯二 MEDIUM 项已列入 Assumptions Log（A1 节点渲染时机抽样、A2 存量 short_id 重复）

**Research date:** 2026-06-12
**Valid until:** 2026-07-12（内部代码契约，随 Phase 18-21 演进需复核）
