# Phase 92: 插槽系统（后端）capability-slot-backend - Research

**Researched:** 2026-06-27
**Domain:** 工作流端口「能力/内容契约」语义 + 后端图校验 + 节点端口声明（Django/Python，自研工作流引擎）
**Confidence:** HIGH（全部基于仓内真实代码核对，无外部依赖）

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**A. 端口语义 = 能力/内容契约（不是单纯几何「shape」）**
- **核心心智**：匹配的是「能力 / 上下文 I/O」——能产出/消费同一类内容/能力的端口才可连。例如「澄清能力」可接入带不确定性的节点（AI 技术方案、AI 编码指派），但**不能**接入纯执行器（获取工作项、创建工作项群聊——简单执行器，无需澄清）。
- **机制实现**：`NodePort` 新增一个**能力契约标识字段**（与 `port_type` 正交；命名倾向 `shape` 作为内部技术字段，但语义=「内容/能力契约」，取值面向能力，如 `clarification_request` / `clarification_answer` / `technical_plan` / `coding_assignment` / `feishu_message` / `feishu_document` / `approval_result` 等）。字段命名最终由 plan-phase 定，但**语义必须是「能力契约」**而非纯几何形状。
- **兼容规则**：相同契约才可连；**空契约（旧节点/未声明）= 通配宽松可连**（向后兼容，既有工作流不破坏）。
- **校验位置**：`WorkflowGraphValidator` 增「契约兼容」规则——保存即校验，不兼容报 error（`incompatible_port_shape` 类 reason），与现有 handle 名校验并存。

**B. ai_plan_research 插槽端口 + 澄清卡节点**
- **ai_plan_research 新增插槽端口**：`clarify`（输出，契约 `clarification_request`）、`resume`（输入，契约 `clarification_answer`）；保留既有 `default`/`error`，**既有工作流零回归**（旧边空契约通配）。
- **新增「澄清卡」节点**（`clarification_card`）：入 `clarification_request`、出 `clarification_answer` + `feishu_message`。可被注册/编排的原子节点：吃澄清请求 → 发卡（飞书群/会话）→ 收答 → 吐结构化答案，并可下接通知。
- **能力门控铺垫**：节点端口契约声明同时为 Phase 93「附着子节点 + IM 能力门控」提供后端依据（IM 端口在无群聊 chat_id 来源时可降级为空，详见 93）。

### Claude's Discretion
- 能力契约字段最终命名（`shape` / `content_shape` / `capability` 等）、契约取值枚举的初始集合、Validator reason 字符串、澄清卡节点与 Phase 91 群卡/回流的接线细节由 plan-phase 定。
- 契约取值应可扩展（Phase 93 会引入更多 feishu_document/notification/approval 契约的连法）。

### Deferred Ideas (OUT OF SCOPE)
- 形状插槽推广到更多节点类型（SLOTX-01，v2）。
- 前端磁吸/高亮/附着编组 → Phase 93（SLOT-03/04，`isValidConnection` 按 shape 磁吸）。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SLOT-01 | 端口「形状（shape）」语义——节点定义声明端口 shape（`technical_plan` / `clarification_request` / `clarification_answer` / `feishu_message` 等）；后端 `WorkflowGraphValidator` 按 shape 兼容性校验连接合法性（保存即校验） | §Standard Stack（NodePort 加字段 + get_schema 输出）、§Architecture Pattern 1（validator 新规则 `_validate_port_shapes`）、§Code Examples |
| SLOT-02 | `ai_plan_research` 暴露 `clarify`（`clarification_request` 凹槽）/ `resume`（`clarification_answer` 凸点）插槽端口；新增「澄清卡」节点（入 `clarification_request`、出 `clarification_answer` + `feishu_message`） | §Architecture Pattern 2（ai_plan_research 端口扩展）、§Pattern 3（clarification_card 节点，复用 GroupChatQuestionNode + 91 发卡/回调范式）、§Open Questions（standalone 澄清卡回调归属） |
</phase_requirements>

## Summary

本 phase 是纯后端（Python/Django）能力，无任何新外部依赖。核心是给工作流端口模型加一个**正交的「能力契约」标识字段**（内部技术字段名倾向 `shape`，语义=能力/内容契约），让 `WorkflowGraphValidator` 在「保存即校验」链路上新增一条**契约兼容规则**，并把 `ai_plan_research` 与新增 `clarification_card` 节点的端口契约声明出来，经 `get_schema()` → `/api/node-types/` 暴露给前端（Phase 93 消费）。

三件事高度内聚且都落在既有 SSOT 上：(1) `NodePort` 是 `@dataclass`，加一个带默认值 `""` 的字段对全部既有构造**零破坏**（向后兼容 = 空契约通配）；(2) `WorkflowGraphValidator.validate()` 已是「保存/导入/模板/dry-run/单边 CRUD 同源」的唯一校验事实源，新规则只需新增一个 `_validate_port_shapes(nodes, edges, errors)` 私有方法并在 `validate()` 内串接，纯函数零 ORM 可单测；(3) 节点端口契约是 `BaseNode.inputs/outputs` ClassVar 声明，经 `get_schema()` 自动输出。

**最大的真实工程风险不是 SLOT-01（契约字段 + 校验），而是 SLOT-02 的 `clarification_card` 节点如何复用 Phase 91**：91 的发卡（`build_clarification_card`）+ 回调续推（`plan_clarify_callback`）是与 `ai_plan_research` 的 `PlanSession` / `delivery.Clarification` 轮次**强耦合**的，回调直接 `approve_node` 重调度挂起的 `ai_plan_research`。一个**独立可编排**的澄清卡节点需要自己的「发卡 → waiting_event → 回调收答 → resume 本节点」闭环（mirror `GroupChatQuestionNode` + `chat_question_callback`），不能直接搭 91 的 plan_clarify 回调。这是本 phase 必须显式决策的关键点（见 Open Questions Q1）。

**Primary recommendation:** NodePort 加 `shape: str = ""` 正交字段（默认空=通配）→ get_schema() inputs/outputs 各加 `"shape"` 键 → `WorkflowGraphValidator` 新增 `_validate_port_shapes` 规则（双端非空且不等才报 `incompatible_port_shape`，default/空恒通配）→ ai_plan_research 加 `clarify`(out)/`resume`(in) 端口 + 新建 `clarification_card` 节点（mirror `GroupChatQuestionNode` 发卡+订阅范式，自带 `ClarifyCardCallback` 回调）→ 视情况扩 `dump_node_fixture` 把 shape 纳入漂移守护 + 重跑 `pnpm -C web gen:node-fixture`。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 端口能力契约字段声明（NodePort.shape） | Backend / 数据模型层（`workflows/nodes/base.py`） | API（`get_schema()` 输出） | 端口模型是后端 SSOT，前端从 `/api/node-types/` 只读 |
| 契约兼容图校验 | Backend / 校验层（`workflows/validation/graph_validator.py`） | API（views.py 5 个入口同源调用） | 「保存即合法」唯一事实源，纯函数零 DB |
| ai_plan_research 插槽端口声明 | Backend / 节点层（`workflows/nodes/ai/plan_research.py`） | — | ClassVar 端口声明即 SSOT |
| clarification_card 节点（发卡/收答/续推） | Backend / 节点层（`workflows/nodes/integrations/`） | Feishu 集成（卡片+回调）、Engine（waiting_event/approve_node） | 集成类节点 mirror GroupChatQuestionNode |
| 端口契约渲染/磁吸（消费 shape） | Frontend（Phase 93，OUT OF SCOPE） | — | 本 phase 仅产出后端契约 + 经 API 暴露 |

## Standard Stack

### Core（全部为仓内既有，无新增依赖）
| 组件 | 位置 | 用途 | 为什么是标准 |
|------|------|------|--------------|
| `NodePort` `@dataclass` | `server/workflows/nodes/base.py:48-60` | 端口定义（name/label/port_type/required/default/description/schema） | 唯一端口模型；加字段即全栈生效 |
| `PortType` Enum | `base.py:36-46` | 端口**数据类型**（any/string/object/...） | 与「能力契约」正交，不复用、不混淆 |
| `BaseNode.get_schema()` | `base.py:607-644` | 端口 → 前端 schema（含 inputs/outputs dict 列表） | `/api/node-types/` 输出唯一来源 |
| `WorkflowGraphValidator.validate()` | `server/workflows/validation/graph_validator.py:63-116` | 五类静态校验（保存即合法，纯函数零 ORM） | 5 个 API 入口同源；新规则只需加一个私有方法 |
| `NodeRegistry` | `server/workflows/nodes/registry.py:53-179` | auto-discover + `@register_node` + `get_all_schemas()` | 新节点放进 `nodes/<category>/` 即自动注册 |
| `GroupChatQuestionNode` | `server/workflows/nodes/integrations/chat_question.py:54-256` | 发卡 → `WorkflowEventSubscription` → `waiting_event` 范式 | clarification_card 节点的**直接蓝本** |
| `build_clarification_card` | `server/feishu/cards/chat_question_card.py:132-303` | 多问题澄清交互卡（2.0 表单，⭐推荐/多选/自由输入） | 91 已建，可直接复用产卡 |
| `plan_clarify_callback` | `server/feishu/callbacks/plan_clarify_callback.py` | 飞书澄清回调收答 → 续推 → approve_node | 回调范式蓝本（但绑 ai_plan_research，见 OQ Q1） |
| `dump_node_fixture` 命令 | `server/workflows/management/commands/dump_node_fixture.py` | dump 精简节点快照到前端 fixture | 漂移守护基准生成器 |

### Supporting
| 组件 | 位置 | 用途 |
|------|------|------|
| `register_card_callback("<prefix>")` | `feishu/views.py`（`CardCallbackView` startswith 路由） | 注册新澄清卡回调前缀 |
| `WorkflowEventSubscription` | `server/workflows/models/execution.py` | waiting_event 超时兜底订阅（event_type 自定义） |
| `WorkflowEngine.approve_node` | `server/workflows/engine/scheduler.py` | 回调侧重调度挂起节点 |
| `ClarificationService` | `server/delivery/services/clarification_service.py` | `create_round`/`answer_round`/`ahas_pending`（90/91 建） |
| node-sync 漂移测试 | `web/src/components/__tests__/node-sync.test.ts` | palette ⊆ fixture node_type 对账 |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `NodePort.shape: str = ""`（扁平字符串） | `Enum`（`PortShape(str, Enum)`） | Enum 类型安全但取值闭集，CONTEXT 明确「契约取值应可扩展」（93 加更多）→ 用 `str` + 模块级常量集合（`KNOWN_PORT_SHAPES: frozenset`）更灵活；声明处用常量引用保可读 |
| 新增独立 validator 文件 | 在 `graph_validator.py` 加私有方法 | 必须同文件——validator 是唯一事实源，5 入口同源调用 `WorkflowGraphValidator().validate`，新文件会割裂 |
| clarification_card 复用 plan_clarify 回调 | 自建 `ClarifyCardCallback` 回调 | plan_clarify 回调强绑 ai_plan_research 的 PlanSession/approve_node，不能直接复用（见 OQ Q1） |

**Installation:** 无。纯 Python 仓内改动，无新增 pip/npm 包。

## Package Legitimacy Audit

> N/A — 本 phase 不安装任何外部包，全部为仓内既有模块改动（`workflows/`、`feishu/`、`delivery/`）。

## Architecture Patterns

### System Architecture Diagram

```text
┌─────────────────────────────────────────────────────────────────────┐
│ SLOT-01 契约字段 + 校验链路                                            │
└─────────────────────────────────────────────────────────────────────┘

  节点声明 (BaseNode.inputs/outputs: ClassVar[list[NodePort]])
        │  NodePort(name=..., port_type=..., shape="clarification_request")
        ▼
  NodeRegistry.get_all_schemas()  ──►  BaseNode.get_schema()
        │                                   inputs/outputs[].shape  ← 新增键
        ▼
  /api/node-types/  ──────────────────►  前端 (Phase 93 磁吸消费)
        │
        ▼ (前端编辑保存 nodes+edges)
  workflows/api/views.py 5 入口 (bulk-update / 单边 CRUD / import / dry-run / status-validate)
        │  全部调用 ↓ (同源)
        ▼
  WorkflowGraphValidator.validate(nodes, edges)
        ├─ (a) node_type 存在性
        ├─ (b) config jsonschema
        ├─ (c) DAG 结构（环/入口/孤立）
        ├─ (d) edge handle 名合法性 (现状)
        ├─ (e) nodes.*/input.*/trigger.* 变量静态校验
        └─ (f) 端口契约兼容 ★新增 _validate_port_shapes
               for edge: 取 src handle→output port.shape, tgt handle→input port.shape
               双端非空 且 不等 → error(reason="incompatible_port_shape")
               任一端空契约 / default 端口 → 通配放行（向后兼容）

┌─────────────────────────────────────────────────────────────────────┐
│ SLOT-02 ai_plan_research 端口 + clarification_card 节点                │
└─────────────────────────────────────────────────────────────────────┘

  ai_plan_research outputs: [default, error, clarify(shape=clarification_request)] ★
  ai_plan_research inputs:  [default, resume(shape=clarification_answer)]          ★
        │ clarify ──────────────────────────────────┐
        ▼                                            ▼
  ┌──────────────────────────────────────────────────────────┐
  │ clarification_card 节点 ★新增 (INTEGRATION)               │
  │  inputs:  [clarification_request]                         │
  │  outputs: [clarification_answer, feishu_message]          │
  │  execute: 发卡(build_clarification_card) → WorkflowEvent  │
  │           Subscription(ClarifyCardCallback) → waiting_event│
  └──────────────────────────────────────────────────────────┘
        │ feishu_message ──► 下接吃 feishu_message 的通知节点
        │ clarification_answer ──► resume 回 ai_plan_research
        ▲
        │ (用户答卡)
  feishu ClarifyCardCallback 回调 → 收答 → approve_node(本 card 节点) → resume
```

### Recommended Project Structure（改动落点）
```text
server/workflows/nodes/base.py                       # NodePort 加 shape 字段 + get_schema() 输出
server/workflows/nodes/shapes.py                     # ★可选新建：KNOWN_PORT_SHAPES 常量集合 + 注释
server/workflows/validation/graph_validator.py       # 加 _validate_port_shapes 规则 + reason 枚举
server/workflows/nodes/ai/plan_research.py           # 加 clarify(out)/resume(in) 端口
server/workflows/nodes/integrations/clarification_card.py  # ★新建节点
server/feishu/callbacks/clarify_card_callback.py     # ★可能新建：standalone 卡回调（见 OQ Q1）
server/workflows/management/commands/dump_node_fixture.py  # 可选：fixture 纳入 shape
web/src/types/workflow/__fixtures__/node-types.fixture.json # 重跑 gen:node-fixture（node_count 36→37）
```

### Pattern 1: 契约兼容校验规则（纯函数，加进 validator）
**What:** 在 `WorkflowGraphValidator` 加第六类规则 `_validate_port_shapes`，与现有 5 类并存。
**When to use:** 每次保存/导入/dry-run（5 入口同源已覆盖）。
**关键不变量（向后兼容命门）：**
- **双端契约非空 AND 不相等** → `error(reason="incompatible_port_shape")`。
- 任一端契约为空字符串（旧节点/未声明）→ **通配放行**（既有工作流零破坏）。
- `default` / 空 handle 解析到 `default` 端口（其 shape 恒为空）→ 自然通配（扁平合并路径不破坏）。
- 端口按 handle 名解析：source 用 `source_handle or "default"` 查 outputs；target 用 `target_handle or "default"` 查 inputs。handle 不在端口集时**跳过 shape 校验**（已由现有 (d) 规则报 `invalid_*_handle`，不重复报）。
- 节点类型未知 → 跳过（已由 (a) 规则报 `unknown_node_type`）。
**Example:** 见 §Code Examples。

### Pattern 2: ai_plan_research 端口扩展（additive，零回归）
**What:** `outputs` 加 `clarify`（shape=`clarification_request`），`inputs` 加 `resume`（shape=`clarification_answer`）；`default`/`error` 原样保留。
**关键约束：**
- 现节点 `execute` 经 `NodeResult.next_handle` 只走 `default`/`error`（见 `_map_terminal` `plan_research.py:495-515`）。**新增端口是声明（供编辑器磁吸 + 校验），不改 execute 运行时分支**——SLOT-02 是「暴露插槽端口」，不要求重写发卡运行逻辑（91 已在 `_maybe_suspend` 内发卡）。
- `clarify` 加进 outputs 后，validator (d) 规则放行 `source_handle="clarify"` 的边（因 `clarify` ∈ outputs 名集）。
- 测试零回归红线：`test_plan_research_node.py`（12 测）+ `_maybe_suspend`/`_send_clarify_card` 行为不变。

### Pattern 3: clarification_card 节点（mirror GroupChatQuestionNode）
**What:** 新建 `ClarificationCardNode`，`node_type="clarification_card"`，`category=NodeCategory.INTEGRATION`，`execution_mode="server_local"`，`is_blocking=True`。
- `inputs=[NodePort(name="clarification_request", shape="clarification_request", ...)]`
- `outputs=[NodePort(name="clarification_answer", shape="clarification_answer"), NodePort(name="feishu_message", shape="feishu_message")]`
- `execute`: 从输入取 clarification_request payload（问题列表/上下文）→ `build_clarification_card(...)` → 发卡到群（解析 chat_id）→ `WorkflowEventSubscription(event_type="ClarifyCardCallback", timeout_at=..., timeout_action="fail")` → `return NodeResult(status="waiting_event", output={...})`。
- 回调收答后 resume 本节点，终态从 `clarification_answer` 出口吐结构化答案 + 可选 `feishu_message` 出口供下接通知。
**蓝本逐行参考：** `GroupChatQuestionNode.execute`（`chat_question.py:150-256`）——发卡 try/except + `WorkflowEventSubscription.objects.acreate` + `waiting_event`，`is_blocking=True`，多输出端口（answered/timeout/error）。

### Anti-Patterns to Avoid
- **把契约塞进 `PortType`：** PortType 是数据类型（any/string/object），契约是能力语义，**正交两轴**。混用会污染既有 schema 校验 + 前端 type 渲染。
- **复用 plan_clarify 回调驱动 standalone 澄清卡：** plan_clarify 回调 `approve_node` 重调度的是 `ai_plan_research` 且强绑 `PlanSession`/`delivery.Clarification`；独立卡节点无 PlanSession，必须自建回调（见 OQ Q1）。
- **default 端口加非空契约：** 会让既有所有 `default→default` 扁平合并边突然被 shape 校验拦截 → 全量工作流破坏。default 端口 shape 必须恒空。
- **改 validator 时漏 default/空通配短路：** 任一端空契约必须先放行再比较，否则旧节点（全空契约）接新节点（有契约）会误报。

## Don't Hand-Roll

| 问题 | 别自己造 | 用现成 | 为什么 |
|------|----------|--------|--------|
| 校验入口分发 | 不要在每个 API view 各写一遍 shape 校验 | 加进 `WorkflowGraphValidator.validate()` | 5 入口（bulk-update/单边/import/dry-run/status-validate）已同源调用，一处生效 |
| 节点注册 | 不要手动维护节点表 | 文件放进 `nodes/integrations/` + `@register_node` | auto-discover 自动收 |
| 澄清卡产卡 | 不要新写卡片 JSON | `build_clarification_card`（91 已建，支持多问题/⭐推荐/多选/自由输入） | 飞书 2.0 表单细节已踩平 |
| 发卡→等待→回调 resume | 不要自研挂起机制 | `WorkflowEventSubscription` + `waiting_event` + `approve_node`（GroupChatQuestion 范式） | 引擎级超时兜底 + 重调度已具备 |
| 前端端口 schema | 不要前端硬编码端口 | `get_schema()` → `/api/node-types/`（加 shape 键即自动流出） | SSOT 单一来源 |
| 脱敏 | 不要裸写卡片正文 | `redact_secrets_in_text`（发卡正文）/ `redact_credentials`（日志） | 观测规范强制 |

**Key insight:** 本 phase 90% 是「在既有 SSOT 上加字段 + 加一条校验规则 + 加一个 mirror 节点」，几乎不需要新机制；唯一需要新建机制的是 standalone 澄清卡的回调闭环（OQ Q1）。

## Common Pitfalls

### Pitfall 1: shape 校验破坏既有 default 边（零回归命门）
**What goes wrong:** 新 shape 规则把现存 `A.default → B.default` 边判为不兼容 → 所有既有工作流保存 400。
**Why:** default 端口若被赋非空 shape，或规则未对「任一端空契约」短路放行。
**How to avoid:** (1) default 端口 shape 恒为 `""`；(2) `_validate_port_shapes` 第一判定 `if not src_shape or not tgt_shape: continue`（任一空即通配）；(3) 仅 `src_shape and tgt_shape and src_shape != tgt_shape` 才报错。
**Warning signs:** `test_graph_validator.py` 既有合法图用例（`test_code_generation_form_is_clean` 等）变红。

### Pitfall 2: NodePort 加字段破坏既有构造
**What goes wrong:** 全仓数十处 `NodePort(name=..., label=...)` 构造报 TypeError。
**Why:** 新字段无默认值（位置参数）。
**How to avoid:** `shape: str = ""` 带默认值放在 `schema: dict | None = None` **之后**（dataclass 字段顺序：有默认值字段必须在末尾，现有 `schema` 已是末位带默认）。追加在其后即安全。
**Warning signs:** import 期即崩（auto-discover 报 `node_discovery_error`）。

### Pitfall 3: fixture 漂移守护未同步（新节点）
**What goes wrong:** 新增 `clarification_card` 后 `node-types.fixture.json` 仍是 36 节点，CI/对账失配。
**Why:** 忘记重跑 `pnpm -C web gen:node-fixture`（= `dump_node_fixture`）。
**How to avoid:** 新增/改节点后必跑该命令，`node_count` 36→37。
**注意（关键判定）：** `node-sync.test.ts` 断言 **palette ⊆ fixture**（palette 节点须是 fixture 子集，反向不查）。所以「fixture 多一个 palette 没有的节点」**不会**让该测试变红——但意味着 `clarification_card` 在编辑器 palette 中**不可见/不可拖**（palette 收录是 Phase 93 前端工作）。本 phase 只需保证后端注册 + fixture 同步；编辑器可见性留 93。
**仅 shape 字段（不加新节点）：** `dump_node_fixture._to_fixture_node` 当前只 dump `{node_type, category, inputs:[{name}], outputs:[{name}]}`，**不含 shape**。所以单加 NodePort.shape 字段**不改变 fixture 输出**，无需重跑。若要让 fixture 守护 shape 漂移（推荐，给 93 兜底），需扩 `_to_fixture_node` 把 `shape` 纳入 inputs/outputs 项 → 此时必须重跑 fixture。是否扩展属 Claude's Discretion。

### Pitfall 4: standalone 澄清卡误搭 plan_clarify 回调
**What goes wrong:** clarification_card 节点发卡后回调走 `plan_clarify_` 前缀 → 回调里 `aanswer_round_and_resume` 找不到 PlanSession / approve 错节点。
**Why:** `plan_clarify_callback` 强绑 `ai_plan_research` 的 `PlanSession`+`delivery.Clarification`+据 `execution_id/node_id` approve 的是 plan_research 节点。
**How to avoid:** 新建独立回调前缀（如 `clarify_card_`），mirror `chat_question_callback` 而非 `plan_clarify_callback`：据 `execution_id/node_id` 定位本 card 节点的 `NodeExecution`、收答写进本节点 output、`approve_node` 重调度本节点。是否需要 delivery.Clarification 持久化由 plan 定（见 OQ Q1）。

### Pitfall 5: clarify 端口加 outputs 后 next_handle 语义
**What goes wrong:** 误以为加了 `clarify` 输出端口就要改 execute 走 `next_handle="clarify"`。
**Why:** 混淆「端口声明」与「运行时分支」。
**How to avoid:** SLOT-02 要求「暴露插槽端口」（声明），91 的发卡运行逻辑已在 `_maybe_suspend`/`_send_clarify_card` 内，不依赖 `clarify` handle 路由。新端口供前端磁吸 + validator 识别契约即可。若未来要让 clarify 边真正承载数据流，是独立增量（标注，不在本 phase 强制）。

## Code Examples

### NodePort 加契约字段（base.py:48-60 改）
```python
# Source: server/workflows/nodes/base.py（现状 48-60）
@dataclass
class NodePort:
    """节点端口定义"""

    name: str
    label: str
    port_type: PortType = PortType.ANY  # 数据类型（正交轴，不动）
    required: bool = True
    default: Any = None
    description: str = ""
    schema: dict | None = None
    # ★新增：能力/内容契约标识（与 port_type 正交）。空 = 通配宽松（向后兼容）。
    # 取值面向「能力」如 clarification_request / clarification_answer /
    # technical_plan / coding_assignment / feishu_message / approval_result。
    shape: str = ""
```

### get_schema() 输出契约（base.py:619-640 改）
```python
# Source: server/workflows/nodes/base.py:619-640（inputs/outputs dict 各加一键）
"inputs": [
    {
        "name": p.name,
        "label": p.label,
        "type": p.port_type.value,
        "required": p.required,
        "description": p.description,
        "schema": p.schema,
        "shape": p.shape,   # ★新增
    }
    for p in cls.inputs
],
# outputs 同样追加 "shape": p.shape
```

### 契约兼容校验规则（graph_validator.py 加私有方法 + validate() 串接）
```python
# Source: 新增于 server/workflows/validation/graph_validator.py
# 在 validate() 末尾（return 前）串接：self._validate_port_shapes(nodes, edges, errors)

def _validate_port_shapes(
    self,
    nodes: list[dict],
    edges: list[dict],
    errors: list[ValidationIssue],
) -> None:
    """端口能力契约兼容校验（与 (d) handle 名校验并存）。

    向后兼容命门：任一端契约为空 → 通配放行；仅双端非空且不等才报
    incompatible_port_shape。handle 不在端口集 / 节点类型未知 → 跳过
    （已由其它规则报 invalid_*_handle / unknown_node_type，不重复）。
    """
    node_by_id = {str(nd["id"]): nd for nd in nodes if nd.get("id") is not None}
    for idx, edge in enumerate(edges):
        src = node_by_id.get(str(edge.get("source_node_id")))
        tgt = node_by_id.get(str(edge.get("target_node_id")))
        if src is None or tgt is None:
            continue  # 已由 (d) edge_node_missing 报
        src_cls = NodeRegistry.get(src["node_type"])
        tgt_cls = NodeRegistry.get(tgt["node_type"])
        if src_cls is None or tgt_cls is None:
            continue
        sh = edge.get("source_handle") or "default"
        th = edge.get("target_handle") or "default"
        src_port = next((p for p in src_cls.outputs if p.name == sh), None)
        tgt_port = next((p for p in tgt_cls.inputs if p.name == th), None)
        if src_port is None or tgt_port is None:
            continue  # handle 非法已由 (d) 报
        src_shape = getattr(src_port, "shape", "") or ""
        tgt_shape = getattr(tgt_port, "shape", "") or ""
        if not src_shape or not tgt_shape:
            continue  # 任一端空契约 → 通配（向后兼容）
        if src_shape != tgt_shape:
            errors.append(
                ValidationIssue(
                    reason="incompatible_port_shape",
                    severity="error",
                    edge_id=edge.get("id"),
                    field_path=f"edges[{idx}]",
                    message=(
                        f"端口契约不兼容：源 '{sh}'({src_shape}) → "
                        f"目标 '{th}'({tgt_shape})"
                    ),
                )
            )
```
（注：`ValidationIssue.reason` docstring 枚举注释也应补 `incompatible_port_shape`，见 `graph_validator.py:40-50`。）

### ai_plan_research 加插槽端口（plan_research.py:100-137 改）
```python
# Source: server/workflows/nodes/ai/plan_research.py（inputs/outputs 追加）
inputs: ClassVar[list[NodePort]] = [
    NodePort(name="default", label="需求输入", port_type=PortType.OBJECT, required=False, ...),
    NodePort(name="resume", label="澄清答复", port_type=PortType.OBJECT,
             required=False, shape="clarification_answer",
             description="回流澄清答案续推（凸点）"),  # ★新增
]
outputs: ClassVar[list[NodePort]] = [
    NodePort(name="default", label="主方案引用", port_type=PortType.OBJECT, schema={...}),
    NodePort(name="error", label="错误", port_type=PortType.OBJECT, ...),
    NodePort(name="clarify", label="澄清请求", port_type=PortType.OBJECT,
             shape="clarification_request",
             description="需澄清时吐出澄清请求（凹槽）"),  # ★新增
]
```

### clarification_card 节点骨架（mirror GroupChatQuestionNode）
```python
# Source: 新建 server/workflows/nodes/integrations/clarification_card.py
# 蓝本：chat_question.py:54-256（GroupChatQuestionNode）

@register_node
class ClarificationCardNode(BaseNode):
    node_type: ClassVar[str] = "clarification_card"
    display_name: ClassVar[str] = "澄清卡"
    description: ClassVar[str] = "吃澄清请求 → 发飞书交互卡 → 收答 → 吐结构化答案"
    icon: ClassVar[str] = "help-circle"
    category: ClassVar[NodeCategory] = NodeCategory.INTEGRATION
    execution_mode: ClassVar[str] = "server_local"
    is_blocking: ClassVar[bool] = True

    inputs: ClassVar[list[NodePort]] = [
        NodePort(name="clarification_request", label="澄清请求",
                 port_type=PortType.OBJECT, required=True,
                 shape="clarification_request"),
    ]
    outputs: ClassVar[list[NodePort]] = [
        NodePort(name="clarification_answer", label="澄清答复",
                 port_type=PortType.OBJECT, shape="clarification_answer"),
        NodePort(name="feishu_message", label="飞书消息",
                 port_type=PortType.OBJECT, shape="feishu_message"),
    ]

    async def execute(self, context: ExecutionContext) -> NodeResult:
        # 1. 取上游 clarification_request payload（问题/上下文）
        # 2. build_clarification_card(...) → 解析 chat_id → 发卡（try/except best-effort）
        # 3. WorkflowEventSubscription(event_type="ClarifyCardCallback", timeout_action="fail")
        # 4. return NodeResult(status="waiting_event", output={...})
        # 收答 resume 后：终态从 clarification_answer 出口吐答案（+ 可选 feishu_message）
        ...
```

### 重跑 fixture（新增节点后必做）
```bash
pnpm -C web gen:node-fixture
# 等价：cd server && uv run python manage.py dump_node_fixture
# node_count 36 → 37
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| 端口仅有数据类型（PortType） | 端口加正交「能力契约」轴 | 本 phase（92） | 连接合法性从「数据形状」升级为「能力语义」 |
| validator 仅校验 handle 名 | 增契约兼容规则（保存即校验） | 本 phase | 不兼容能力的连接保存即拒 |
| 澄清仅 ai_plan_research 内联发卡（91） | 澄清成可编排原子节点 | 本 phase（SLOT-02） | 澄清能力可拖拽拼接到任意带不确定性节点 |

**无 deprecated/outdated：** 全部为增量叠加，既有路径零回退（空契约通配）。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | 契约字段命名取 `shape`（内部技术名，语义=能力契约） | Standard Stack / Code Examples | 命名是 Claude's Discretion，plan-phase 可改为 `content_shape`/`capability`；不影响机制 |
| A2 | 契约取值用 `str` + 模块级常量集合（非 Enum） | Alternatives | CONTEXT 明确「取值应可扩展」；若 plan 选 Enum 需配套迁移每次加值 |
| A3 | standalone clarification_card 需自建回调（不复用 plan_clarify） | Pitfall 4 / OQ Q1 | 若 plan 决定让 card 节点专为 ai_plan_research 配套（不独立），可复用 91；但 CONTEXT 要求「可注册可编排原子节点」倾向独立 |
| A4 | SLOT-02「暴露插槽端口」= 端口声明，不要求改 execute 运行时分支 | Pattern 2 / Pitfall 5 | 若 plan 要求 clarify 边真正承载数据流，需额外运行时改动 |
| A5 | clarification_request/answer 的 payload schema 由 plan 定 | OQ Q1 | 影响 card 节点 input 解析 + 与 ai_plan_research clarify 输出对齐 |

## Open Questions

1. **standalone `clarification_card` 的回调闭环如何落（最关键设计决策）**
   - What we know: 91 的 `plan_clarify_callback` 收答后 `aanswer_round_and_resume` + `approve_node` 重调度 `ai_plan_research`，强绑 `PlanSession`/`delivery.Clarification`。`GroupChatQuestionNode` + `chat_question_callback` 则是「据 execution_id/node_id 定位本节点 → 收答写本节点 output → approve_node 本节点」的自洽闭环（无 PlanSession）。
   - What's unclear: clarification_card 节点应 mirror 哪个？是否需要把答案落 `delivery.Clarification`（结构化采纳率），还是仅把答案透传到 `clarification_answer` 出口？`clarification_request` 输入 payload 的契约 schema 是什么（问题列表 + chat_id 来源）？
   - Recommendation: **mirror `chat_question_callback`**（自建 `ClarifyCardCallback` 前缀回调，据 execution_id/node_id approve 本 card 节点），复用 `build_clarification_card` 产卡 + `WorkflowEventSubscription` 挂起。答案是否落 delivery.Clarification 作为可选（若 card 节点接的是 ai_plan_research clarify 输出且需采纳率，则落；纯通用澄清可仅透传）。payload schema 建议 `{questions: [{question, type, options, recommended}], chat_id?, title?}`，与 91 `_acollect_round_questions` 输出对齐。**plan-phase 必须拍板。**

2. **契约取值初始枚举集合的确切清单**
   - What we know: CONTEXT 给出候选 `clarification_request / clarification_answer / technical_plan / coding_assignment / feishu_message / feishu_document / approval_result`。
   - What's unclear: 本 phase 实际声明到端口上的有哪几个（clarify/resume/card 用到 clarification_request/answer + feishu_message 是刚需；其余为 93 铺底）。
   - Recommendation: 本 phase 至少声明 `clarification_request`/`clarification_answer`/`feishu_message`；常量集合一次性收全 7 个（含 technical_plan/coding_assignment/feishu_document/approval_result）供 93 扩展，但端口可暂不全部贴。

3. **是否给 ai_plan_research / ai_coding_dispatcher 的现有 default/plan 端口补契约**
   - What we know: `ai_plan_research.default` 输出 §7 MergedPlan；`ai_coding`/`ai_coding_dispatcher.plan` 输入消费 technical_plan。
   - What's unclear: 是否本 phase 就给它们贴 `technical_plan`/`coding_assignment` 契约（会让 plan→coding 边受 shape 校验约束）。
   - Recommendation: **谨慎**——给现有生产边贴契约可能拦截既有工作流（虽空契约通配保护旧边，但新贴双端契约后新建边会受约束）。建议本 phase 仅贴澄清相关 3 个契约 + 常量集合预留，technical_plan/coding_assignment 的端口贴附留 SLOT 推广（SLOTX-01 v2 或 93），避免回归面扩大。

## Environment Availability

> 纯代码改动，无外部工具/服务依赖（飞书发卡走既有 `FeishuIMService` 凭证链，单测以 mock/respx 覆盖，无需真实飞书）。Step 2.6: 无新增外部依赖。

## Validation Architecture

> `workflow.nyquist_validation = true`（config.json）→ 本节适用。

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.x + pytest-django 4.8 + pytest-asyncio（见 server/pyproject.toml） |
| Config file | `server/pyproject.toml`（`[tool.pytest...]`） + `server/tests/conftest.py`（adrf monkeypatch） |
| Quick run command | `cd server && uv run pytest tests/workflows/test_graph_validator.py -x -q` |
| Full suite command | `cd server && uv run pytest tests/workflows tests/feishu -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SLOT-01 | NodePort.shape 进 get_schema() 输出 | unit | `uv run pytest tests/workflows/test_node_schema.py -k shape -x` | ❌ Wave 0（可加进既有 schema/registry 测试或新建） |
| SLOT-01 | 双端契约不等 → incompatible_port_shape error | unit（纯函数零 DB） | `uv run pytest tests/workflows/test_graph_validator.py -k shape -x` | ✅ 扩 `test_graph_validator.py` |
| SLOT-01 | 任一端空契约 → 通配放行（既有图零回归） | unit | `uv run pytest tests/workflows/test_graph_validator.py -x` | ✅ 既有合法图用例兜底 + 新增空契约通配用例 |
| SLOT-02 | ai_plan_research 含 clarify/resume 端口 + default/error 保留 | unit | `uv run pytest tests/workflows/test_plan_research_node.py -k port -x` | ✅ 扩 `test_plan_research_node.py`（12 测零回归） |
| SLOT-02 | clarification_card 注册 + 发卡 waiting_event + 端口契约 | unit/integration | `uv run pytest tests/workflows/test_clarification_card_node.py -x` | ❌ Wave 0 新建 |
| SLOT-02 | clarify_card 回调收答 → approve_node resume | integration | `uv run pytest tests/feishu/test_clarify_card_callback.py -x` | ❌ Wave 0（若自建回调） |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/workflows/test_graph_validator.py tests/workflows/test_plan_research_node.py -x -q`
- **Per wave merge:** `uv run pytest tests/workflows tests/feishu -q`
- **Phase gate:** 全量 green + `ruff format --check` + `ruff check` + `mypy` + `makemigrations --check`（本 phase **无 DB 迁移**，应保持 `--check` 干净）+ `pnpm -C web vitest run node-sync`（若动 fixture）。

### Wave 0 Gaps
- [ ] `tests/workflows/test_clarification_card_node.py` — clarification_card 节点（发卡/waiting_event/端口契约/失败 best-effort），mirror `test_chat_question.py` / `test_plan_research_node.py`
- [ ] `tests/feishu/test_clarify_card_callback.py` — 若自建 standalone 回调（收答→approve_node→resume，幂等门，脱敏）
- [ ] `test_graph_validator.py` 扩 shape 用例（不兼容报错 / 空契约通配 / default 通配 / handle 非法不重复报）
- [ ] `test_plan_research_node.py` 扩 clarify/resume 端口存在性 + default/error 零回归
- [ ] （可选）`test_node_schema.py` 或既有 registry 测试断言 `get_schema()` inputs/outputs 含 `shape` 键

## Security Domain

> `security_enforcement = true`，`security_asvs_level = 1`（config.json）。

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | 不新增认证面（沿用既有 WorkflowPermission / 飞书回调验签） |
| V3 Session Management | no | — |
| V4 Access Control | yes（弱） | 校验入口沿用既有 `WorkflowPermission` + 作用域过滤（views.py 不动权限）；clarify_card 回调据 execution_id/node_id 定位 + 幂等门，绝不信回调直传可伪造字段 |
| V5 Input Validation | yes | 端口契约/边来自前端不可信输入 → validator 已是 fail-closed 结构化校验；新 shape 规则同样只读节点/边 dict 不执行；卡片 payload 经 `redact_secrets_in_text` 脱敏，回调字段服务端权威定位 |
| V6 Cryptography | no | 不碰凭证（发卡走既有 `FeishuIMService` Fernet 凭证链） |

### Known Threat Patterns for 自研工作流 + 飞书回调
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| 回调伪造（伪造 clarification/node id 越权 approve） | Spoofing/Tampering | mirror plan_clarify_callback：据服务端权威 execution_id/node_id 定位 + `waiting_event` 幂等门（非 waiting → no-op）；绝不信客户端直传 session_id（91 范式 T-91-03） |
| 卡片正文/日志泄漏需求/凭证明文 | Information Disclosure | `redact_secrets_in_text`（卡片正文/异常）；日志仅记 id 标量 + `category`/`component` |
| 校验 message 回显 config 取值 | Information Disclosure | `ValidationIssue.message` 只含 node_id/edge_id/handle/shape 名（T-20-01 既有约束），新 incompatible_port_shape message 同样只含 handle/shape 名，不回显 payload |
| 发卡/回调反噬主流程（5xx 崩工作流） | DoS | 发卡 best-effort try/except（不反噬挂起）；回调重活 fail-soft（绝不上抛飞书 5xx）——沿用 91 范式 |
| 观测埋点 | — | 新增节点/回调赋 `category`(caller/sampling)+`component`；后台/外部触发带 `initiated_by_user_id`（缺记 system）；契约校验为高频纯函数不刷 INFO（按 .cursor/rules/observability-logging.mdc） |

## Project Constraints (from .cursor/rules/ + CLAUDE.md)
- **观测/日志强制（`.cursor/rules/observability-logging.mdc`）：** 新增节点（clarification_card）/回调/校验视为「新增功能」，须 structlog snake_case 事件（started/completed/failed）+ `category`+`component`+关键生命周期 `duration_ms`；发卡/回调脱敏不可绕过；后台任务带 `initiated_by_user_id`（缺 `system`）；观测 best-effort 绝不反噬业务；高频循环（validator）禁 INFO 刷屏。
- **async ORM：** 节点/回调走 `sync_to_async` / `afirst`/`aget`/`aexists` 标量，绝不裸 lazy-FK（plan_research.py 已立此范式）。
- **i18n 默认中文：** 卡片/校验文案中文（既有 build_clarification_card 已中文）。
- **凭证复用：** 发卡走 `ProviderCredential`/`SystemSetting`/既有 `FeishuIMService`，不绕加密。
- **INV-6（单一写入入口）：** 若 card 节点落 delivery.Clarification，必经 `ClarificationService`（grep 守护），回调绝不旁路 `.objects.create/.save`。

## Sources

### Primary (HIGH confidence)
- `server/workflows/nodes/base.py:36-60,525-644` — PortType/NodePort/BaseNode.get_schema()（契约字段落点）
- `server/workflows/validation/graph_validator.py:36-204` — ValidationIssue/validate()/_validate_edges（新规则落点 + reason 枚举）
- `server/workflows/api/views.py:80,263-271,376-382,575-581,778-813` — 5 个校验入口同源调用 WorkflowGraphValidator
- `server/workflows/nodes/ai/plan_research.py:100-137,309-462` — ai_plan_research 端口 + _maybe_suspend/_send_clarify_card（91 发卡）
- `server/workflows/nodes/integrations/chat_question.py:54-256` — GroupChatQuestionNode（clarification_card 蓝本）
- `server/feishu/cards/chat_question_card.py:132-303` — build_clarification_card（复用产卡）
- `server/feishu/callbacks/plan_clarify_callback.py` — 回调范式（绑 ai_plan_research，OQ Q1 对比）
- `server/workflows/nodes/registry.py:53-179` — auto-discover/get_all_schemas/get_schema 流
- `server/workflows/management/commands/dump_node_fixture.py` + `web/src/components/__tests__/node-sync.test.ts` + `web/src/types/workflow/__fixtures__/node-types.fixture.json` — 漂移守护链（node_count=36）
- `server/tests/workflows/test_graph_validator.py:1-80` — 纯函数测试范式（零 DB）
- `.planning/config.json` — nyquist_validation/security_enforcement = true
- `.planning/phases/91-*/91-02-SUMMARY.md` + STATE.md Phase 90/91 decisions — 澄清能力/数据/发卡/回调既有资产

### Secondary (MEDIUM confidence)
- CLAUDE.md / AGENTS.md 技术栈 + 约束（Django 5.1/Py3.14、async、INV-6、观测）

### Tertiary (LOW confidence)
- 无（本 phase 全部基于仓内真实代码核对，无 WebSearch 推断）

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 全部为仓内既有模块，真实行号核对
- Architecture（契约字段 + 校验规则 + 端口声明）: HIGH — 落点明确，机制成熟
- clarification_card 回调闭环: MEDIUM — 蓝本清晰（GroupChatQuestion + chat_question_callback），但 standalone vs 复用 91 的接线细节是 plan-phase 必决项（OQ Q1）
- Pitfalls: HIGH — 向后兼容/fixture/回调误搭均有真实代码依据

**Research date:** 2026-06-27
**Valid until:** 2026-07-27（仓内代码为准，稳定；若 90-94 并发改动 plan_orchestration/feishu 资产需复核）
