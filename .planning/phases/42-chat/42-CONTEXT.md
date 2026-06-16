# Phase 42: Chat 入口薄封装 - Context

**Gathered:** 2026-06-16
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous — grey areas resolved at Claude's discretion per DOMAIN §6/§14 + Phase 41 工作流入口范式)

<domain>
## Phase Boundary

给 Chat 加一层**薄封装**入口，复用 Phase 36-41 已建的同一底层 `PlanOrchestrationEngine` + 真实 adapters 发起方案编排——**不并行造两套编排**（验证 engine 入口无关性）。

1. **ENTRY-02**：Chat 入口薄封装复用同一 engine，从对话即可发起方案编排；产出与工作流入口一致的 `MergedPlan` 与 §15 trace 事件（同一 engine、同一状态机）。
2. **INV-2**：Chat 自然语言需求允许 `PlanSession.work_item` / `TechnicalPlan.work_item` 为 null 但显式标记（origin=chat）。

**不在本 phase**：新编排逻辑（复用 41 的 engine/adapters）、对外 API adapter（v0.11）、新前端组件（chat 已有对话/澄清 UI）。这是 v0.7.0 末 phase——薄封装收口。

</domain>

<decisions>
## Implementation Decisions

### Chat 入口形态（ENTRY-02）
- 新增 chat agent 工具 `start_plan_research`（`@tool`，落 `server/agents/tools/`，对齐既有 `deep_analysis`/`create_coding_plan` 工具范式），LLM 在对话中识别"做多仓技术方案"意图时调用。工具职责（**薄**）：① 建 `PlanSession(entrypoint=chat, work_item=可空, created_by=对话用户, decomposition={requirement_text: 需求文本, include_repos: 可选})`（经 PlanSessionService.create_session，INV-6）；② 用与 Phase 41 **完全相同**的真实 adapters（RepoRouterV2Adapter / DeliveryKnowledgeRecallAdapter / ResearchDispatchAdapter / ArchitectMergeAdapter / ClarifyAdapter）构建 `PlanOrchestrationEngine`；③ 驱动 `engine.advance` 推进流水线；④ 终态 done → 返回/流式 canonical `TechnicalPlan`/`MergedPlan` 引用。
- **复用提取**：若 Phase 41 工作流节点的「建 session + 构建 engine + 驱动」逻辑可抽公共 helper（如 `plan_orchestration` 内 `start_orchestration(entrypoint, requirement, work_item, created_by, ...)`），则 chat 与 workflow 入口都调它——这正是「底层 engine 复用、不造两套」的落地。倾向抽一个薄 helper，两入口共用（Claude's Discretion：若抽取成本高则 chat 工具直接复用 adapters 构建，保持逻辑等价）。

### 澄清 / 调研挂起（chat 范式）
- Chat 已有 clarification interrupt 机制（chat graph clarification，`test_chat_graph_clarification_interrupt`）+ deep_analysis 容器 fire-and-forget + resume 范式。澄清/调研挂起复用 **chat 既有** interrupt/resume（而非工作流 waiting_event）——因 chat 与 workflow 是不同入口运行时，但驱动的是同一 engine 状态机。
- **Claude's Discretion**：chat 入口的挂起/恢复精确接法（chat graph interrupt vs fire-and-forget + 后续轮次再 advance）。倾向：chat 工具发起后，clarifying（pending clarification）经 chat clarification interrupt 问用户；researching 容器 fan-out 经既有 chat deep_analysis resume 范式；engine 状态持久化保证跨轮次/回调可 resume（engine 本就入口无关 + 状态全持久化）。

### INV-2（自然语言需求 null work_item）
- Chat 发起允许无 work_item：`PlanSession.work_item=None` + canonical `TechnicalPlan.origin="chat"` 显式标记（Phase 37 origin 字段已支持）。融合落 canonical 时 `create_from(origin="chat"...)`（注意：编排经 orchestration engine，融合 adapter 已用 `origin="orchestration"` —— 本 phase 需确认 chat 自然语言需求的 canonical origin 标记：倾向保持融合产物 origin="orchestration"，而 work_item=None 即标记"自然语言需求"；或在 PlanSession 记 entrypoint=chat 供追溯。Claude's Discretion，保证 INV-2 可追溯/显式即可）。

### 一致性验证（SC-2）
- Chat 与工作流入口经同一 engine/状态机 → 产出一致的 MergedPlan 结构 + §15 事件。测试断言：相同需求经 chat 入口与 workflow 入口驱动 engine 得到结构等价的 MergedPlan + 相同 taxonomy 事件序列（IO 边界 mock）。

### Claude's Discretion
- 是否抽 `start_orchestration` 公共 helper（倾向是，两入口共用）。
- chat 工具的精确名/参数 schema + 流式返回形态。
- chat 挂起/恢复接法（chat interrupt vs 多轮 advance）。
- chat 自然语言需求 canonical origin 标记细节（保证 INV-2 即可）。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- Phase 41 `AIPlanResearchNode`（建 session + 构建 engine + 驱动 + 挂起恢复）—— chat 入口对称参考/可抽公共 helper。
- Phase 36-40 全部真实 adapters + `PlanOrchestrationEngine`（入口无关）+ PlanSessionService/ClarificationService/ResearchService/TechnicalPlanService。
- `server/agents/tools/chat_tools.py`（`@tool` 范式 + `deep_analysis` 容器 fire-and-forget + resume + `create_coding_plan`）。
- chat clarification interrupt 机制（`test_chat_graph_clarification_interrupt`）。
- Phase 37 `TechnicalPlan.origin`（chat 标记 + work_item null 支持，INV-2）。

### Established Patterns
- chat agent 工具 `@tool` 注册（与工作流节点共用工具/adapter）。
- engine 入口无关 + 状态全持久化（跨入口/跨轮次 resume）。
- INV-6 单一写入；engine 纯度（transition only）；real LLM/容器 E2E deferred（mock）。

### Integration Points
- chat 工具 → 同一 engine/adapters（验证入口无关性，不造两套）。
- 产物 canonical TechnicalPlan + §15 事件与工作流入口一致。
- 澄清/调研挂起复用 chat 既有 interrupt/resume。

</code_context>

<specifics>
## Specific Ideas

- **薄封装**是核心约束：本 phase 不写新编排逻辑，只加 chat 入口适配 + 复用 41 的 engine/adapters（vNext 已确认「工作流先行、Chat 薄封装后置，不要两入口并行造」）。
- 验证 engine 入口无关性：chat 与 workflow 两入口产出一致（同 engine 同状态机）。
- INV-2：chat 自然语言需求 work_item=null 显式标记可追溯。
- 收口 v0.7.0 末 phase。

</specifics>

<deferred>
## Deferred Ideas

- 对外 OpenAI/Anthropic API adapter 透出编排事件（v0.11，复用 §15 taxonomy）。
- chat 编排的富前端可视化（chat 已有对话/澄清 UI；trace 可视化非 SC 必需）。
- 真实 LLM/容器端到端验收（沿用既有 deferred）。

</deferred>
