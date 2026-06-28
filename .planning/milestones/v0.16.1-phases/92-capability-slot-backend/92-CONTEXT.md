# Phase 92: 插槽系统（后端）- Context

**Gathered:** 2026-06-27
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous，用户逐 phase 定夺）

<domain>
## Phase Boundary

让端口具备「**能力/内容契约**」语义并被后端校验：相同能力/上下文输入输出的端口才能拼到一起。
`ai_plan_research` 暴露澄清插槽端口，并新增可编排的「澄清卡」节点。

覆盖：SLOT-01（端口能力契约 + Validator 校验）、SLOT-02（ai_plan_research 插槽端口 + 澄清卡节点）。
不含：前端磁吸/编组（93）。

</domain>

<decisions>
## Implementation Decisions

### A. 端口语义 = 能力/内容契约（不是单纯几何「shape」）
- **核心心智**：匹配的是「**能力 / 上下文 I/O**」——能产出/消费同一类内容/能力的端口才可连。
  例如「澄清能力」可接入带不确定性的节点（AI 技术方案、AI 编码指派），但**不能**接入纯执行器
  （获取工作项、创建工作项群聊——简单执行器，无需澄清）。
- **机制实现**：`NodePort` 新增一个**能力契约标识字段**（与 `port_type` 正交；命名倾向 `shape` 作为内部技术字段，
  但语义=「内容/能力契约」，取值面向能力，如 `clarification_request` / `clarification_answer` /
  `technical_plan` / `coding_assignment` / `feishu_message` / `feishu_document` / `approval_result` 等）。
  字段命名最终由 plan-phase 定，但**语义必须是「能力契约」**而非纯几何形状。
- **兼容规则**：相同契约才可连；**空契约（旧节点/未声明）= 通配宽松可连**（向后兼容，既有工作流不破坏）。
- **校验位置**：`WorkflowGraphValidator` 增「契约兼容」规则——保存即校验，不兼容报 error
  （`incompatible_port_shape` 类 reason），与现有 handle 名校验并存。

### B. ai_plan_research 插槽端口 + 澄清卡节点
- **ai_plan_research 新增插槽端口**：
  - `clarify`（输出，契约 `clarification_request`）——编排需澄清时吐出澄清请求；
  - `resume`（输入，契约 `clarification_answer`）——回流答案续推。
  - 保留既有 `default`/`error`，**既有工作流零回归**（旧边空契约通配）。
- **新增「澄清卡」节点**（`clarification_card`）：入 `clarification_request`、出 `clarification_answer` + `feishu_message`。
  作为可被注册/编排的原子节点：吃澄清请求 → 发卡（飞书群/会话）→ 收答 → 吐结构化答案，并可下接通知。
- **能力门控铺垫**：节点端口的契约声明同时为 Phase 93 的「附着子节点 + IM 能力门控」提供后端依据
  （IM 相关端口在无群聊 chat_id 来源时可降级为空，详见 93）。

### Claude's Discretion
- 能力契约字段最终命名（`shape` / `content_shape` / `capability` 等）、契约取值枚举的初始集合、
  Validator reason 字符串、澄清卡节点与 Phase 91 群卡/回流的接线细节由 plan-phase 定。
- 契约取值应可扩展（Phase 93 会引入更多 feishu_document/notification/approval 契约的连法）。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/workflows/nodes/base.py`：`NodePort`（name/label/port_type/required/default/description/schema，**无契约字段**）、
  `PortType` 枚举、`BaseNode.inputs/outputs(ClassVar)`、`get_schema()`、`@register_node`。
- `server/workflows/validation/graph_validator.py`：`WorkflowGraphValidator.validate(nodes, edges)`
  （现仅校验 handle 名 invalid_source_handle/invalid_target_handle，**不校验端口类型/契约**）。
- `server/workflows/nodes/ai/plan_research.py`：`ai_plan_research`（现仅 default/error 端口）。
- `server/workflows/nodes/ai/coding_dispatcher.py`（`ai_coding_dispatcher`）、`coding.py`（`ai_coding`）——带不确定性可接澄清。
- 澄清卡产卡能力：`server/feishu/cards/chat_question_card.py::build_clarification_card`。
- 节点注册：`server/workflows/nodes/registry.py`（auto-discover，`get_all_schemas()` → `/api/node-types/`）。

### Established Patterns
- 端口经后端 `NodeRegistry.get_all_schemas()` 为权威 SSOT，前端从 `/api/node-types/` 读 inputs/outputs。
- handle 名 = outputs/inputs 的 name；`default`/空为扁平合并路径。
- fixture 漂移守护：`dump_node_fixture` → `node-types.fixture.json`，前端 `node-sync.test.ts`。

### Integration Points
- 校验入口同源：bulk-update / import / template loader / dry-run / 单边 CRUD（`workflows/api/views.py`）。
- 新契约字段须进 `get_schema()` 输出 + fixture，前端方能读到（93 消费）。

</code_context>

<specifics>
## Specific Ideas

- 用户：匹配的是「能力」，AI 技术方案 / AI 编码指派可接澄清；获取工作项、创建工作项群聊等简单执行器不能接
  （它们没有不确定性）。命名上「shape」不够达意，本质是能力契约。

</specifics>

<deferred>
## Deferred Ideas

- 形状插槽推广到更多节点类型（SLOTX-01，v2）。
- 前端磁吸/高亮/附着编组 → Phase 93。

</deferred>
