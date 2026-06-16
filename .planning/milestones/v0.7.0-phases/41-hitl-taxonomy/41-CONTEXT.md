# Phase 41: HITL 澄清 + 事件 taxonomy + 工作流入口 - Context

**Gathered:** 2026-06-16
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous — grey areas resolved at Claude's discretion per DOMAIN §6/§14/§15)

<domain>
## Phase Boundary

把编排「串起来跑通」并补三件事：

1. **CLARIFY-01**：HITL 澄清回路——不清晰时发 `Clarification` 挂起等用户，回答后仅 `affected_partials` 内的 `RepoResearchTask` 重跑、其余复用（§14 clarifying 挂起/重跑规则）。
2. **ENTRY-01**：工作流入口端到端跑通——一个需求经「拆分→路由→召回→澄清→并行调研→融合」产出带跨仓依赖的 `MergedPlan`（工作流先行）。
3. **EVENT-01**：把 Phase 36-40 经 `_emit_event` 钩子产出的事件**沉淀为稳定 §15 词表**（统一信封 `{event, session_id, work_item_id?, ts, payload}` 持久化），为 v0.11 对外 adapter 留稳定底座（INV-5，progress/trace 非 CoT）。

**不在本 phase**：Chat 入口（42）、对外 API adapter（v0.11）、v0.8 wave 编码。

## UI 触面（reuse-first，无需新建定制组件）
- 工作流节点经既有节点编辑器 SSOT 框架自动渲染（v0.4.0：后端 registry + `node-definitions.json` 唯一事实源 → 前端节点库/配置表单自动生成）。本 phase 提供节点 + node-definitions 条目即获得编辑器 UI，不写新 Vue 组件。
- 澄清交互复用既有工作流 `ask_user_question` 挂起 + 飞书/前端卡片回路（v0.4.0 waiting_event/suspend + clarification resume，260612 已修 resume contextvars）。
- 可选的 plan-session/trace 可视化视图非 SC 必需 → deferred（EVENT-01 只要求产出+持久化事件，不强制 UI）。

</domain>

<decisions>
## Implementation Decisions

### Clarification 模型 + service（CLARIFY-01，DOMAIN §6/§14）
- `Clarification`（delivery）：`id UUIDField(pk)`、`session FK(PlanSession, CASCADE, related_name="clarifications")`、`question TextField`、`answer TextField(blank, default="")`、`answered_at DateTimeField(null)`、`affected_partials M2M(RepoResearchTask, blank)`、`created_at`。migration delivery 0015。curated re-export。
- `ClarificationService`（delivery，INV-6 单一写入入口 + grep 守护）：`create_clarification(session, question, affected_task_ids)`；`answer_clarification(clarification, answer)` → 写 answer/answered_at + 把 `affected_partials` 对应 `RepoResearchTask` 经 `ResearchService` 置 stale（融合前重跑，复用 Phase 39 stale 重跑机制），无 affected 则纯解除挂起。
- 状态：clarification pending = 存在未 answered 的 Clarification。

### engine `_clarify` 实现（替换 pass-through）
- 注入 `ClarifyProtocol`（Phase 36 引擎已有 stage 注入位；当前 _clarify 是 pass-through，本 phase 接真实）。`clarify(session)`：判定是否需澄清——默认策略（Claude's Discretion，可注入 policy）：routing 无 high/medium 候选 或 decomposition 标 ambiguous → 建 Clarification（pending）+ emit `clarification.asked` + **保持 clarifying（挂起）**，不 transition 到 researching；否则（无待澄清/全部已答）→ transition `clarified`（clarifying→researching）。
- **挂起/恢复**：复用工作流 waiting_event/suspend 范式——工作流入口节点在 engine 停于 clarifying（有 pending clarification）时挂起等用户答复（经既有 ask_user_question 卡片回路）；答复经 `ClarificationService.answer_clarification` → resume → engine 重入 _clarify（pending 清空）→ clarified → researching（仅 affected partial stale 重跑）。
- emit `clarification.answered` {clarification_id, answer, affected_partials}。

### 事件 taxonomy 持久化（EVENT-01，DOMAIN §15）
- `PlanSessionEvent`（delivery，append-only）：`id UUIDField(pk)`、`session FK(PlanSession, CASCADE, related_name="events")`、`event CharField`（§15 taxonomy 名）、`work_item` 软引用 `UUIDField(null, blank)`、`payload JSONField(default=dict)`、`ts DateTimeField(default=now)`、`created_at`。migration 0015（与 Clarification 同迁移）。
- **升级 `PlanSessionService._emit_event`**：从 best-effort no-op+log → 持久化 `PlanSessionEvent`（§15 统一信封 shape）。仍 best-effort（DB 写失败只 log warning，绝不抛影响转移）。可选：经 channels 推 WS 实时 trace（倾向预留但本 phase 落 DB 为主，WS 可选）。
- **稳定词表常量**：定义 §15 taxonomy 常量集（work_item.syncing / knowledge.recalling / repo.routing / repo.research.started|completed|failed / clarification.asked|answered / plan.merge.started|completed / plan.validation.failed / plan.session.failed），各 emit 点统一引用常量（消除字符串漂移）。校验现有 38/39/40 的 emit 名对齐该词表。
- §15 信封 helper：`{event, session_id, work_item_id?, ts, payload}` 统一构造，PlanSessionEvent 持久化 + 未来 adapter 复用同一 shape。

### 工作流入口节点（ENTRY-01）
- 新建 `AIPlanResearchNode`（`workflows/nodes/ai/plan_research.py`，BaseNode/AIAgentBaseNode 子类，放入 ai 目录自动经 NodeRegistry 注册）。职责：① 从节点配置/上游输入取需求（requirement_text/include_repos/work_item 锚）建 `PlanSession(entrypoint=workflow, work_item, created_by, decomposition=...)`（经 PlanSessionService.create_session，INV-6）；② 注入真实 adapters（`RepoRouterV2Adapter` / `DeliveryKnowledgeRecallAdapter` / `ResearchDispatchAdapter` / `ArchitectMergeAdapter` / 真实 ClarifyProtocol）建 `PlanOrchestrationEngine`；③ 驱动 `engine.advance` 推进流水线；④ 在 clarifying（pending clarification）/ researching（容器 fan-out 等待）处与工作流 suspend/resume（waiting_event + callback）集成；⑤ 终态 done → 输出 canonical `TechnicalPlan`/`MergedPlan` 引用（PlanSession.current_plan_version）；failed → NodeResult failed + error。
- **node-definitions.json 条目**（SSOT，v0.4.0）：节点 category/ports/config schema（requirement 输入、include_repos、work_item 锚等）→ 前端编辑器自动渲染。复用既有 ai 节点 port/config 范式（参考 plan_generation/coding 节点）。
- **挂起恢复**：复用既有工作流引擎 waiting_event/next_handle/trigger_data + callback resume（v0.4.0 + 260612 clarification resume contextvars 修复），不重造。

### Claude's Discretion
- 澄清是否需要的判定 policy 精确规则（默认 routing 无 high/medium 或 ambiguous；可注入 policy）。
- 工作流节点与 engine 的 suspend/resume 集成精确接法（对齐既有 plan_generation/coding 节点 waiting_event 范式）——倾向复用 AIAgentBaseNode 既有挂起机制。
- WS 实时 trace 推送是否本 phase 落（倾向 DB 持久化为主，WS 预留）。
- node-definitions.json 字段细节。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/delivery/services/plan_session_service.py:_emit_event`（待升级为持久化 PlanSessionEvent + §15 信封）+ transition（payload→字段，含 routing/recall_context）。
- Phase 38-40 各 stage adapter（RepoRouterV2Adapter/DeliveryKnowledgeRecallAdapter/ResearchDispatchAdapter/ArchitectMergeAdapter）+ engine（_clarify 待接真实 ClarifyProtocol）。
- `server/workflows/nodes/ai/`（AIAgentBaseNode/plan_generation/coding 节点范式 + waiting_event 挂起 + ask_user_question）。
- 工作流引擎 waiting_event/next_handle/trigger_data + callback resume（v0.4.0）+ clarification resume contextvars 修复（260612）。
- node-definitions.json SSOT（v0.4.0：后端 registry + 前端自动渲染）。
- Phase 39 ResearchService stale 重跑（澄清 affected_partials 复用）。
- delivery service 单一写入入口 + grep 守护（INV-6）。

### Established Patterns
- 工作流节点 = BaseNode 子类放 nodes/<category>/ 自动注册（registry singleton）。
- ask_user_question 挂起 + waiting_event + callback resume（HITL 范式）。
- append-only 事件 + 读时投影（v0.6 评论/状态事件）。
- 编排状态/产物只经 service 写（INV-6）；engine 不旁路 status（transition only，纯度守护）。
- LLM/容器失败 graceful 降级；真实容器/LLM E2E deferred（mock 单测）。

### Integration Points
- 工作流入口节点注入全部真实 adapter 驱动 engine 端到端（ENTRY-01）。
- Clarification 挂起复用工作流 suspend/resume + ask_user_question 卡片。
- PlanSessionEvent 持久化为 v0.11 对外 adapter 底座（复用同一 §15 信封）。
- Chat 入口（42）复用同一 engine + adapter（本 phase 工作流先行，验证 engine 入口无关性）。

### Established Patterns（async）
- async ORM 经 sync_to_async；事件持久化 best-effort 不抛。

</code_context>

<specifics>
## Specific Ideas

- 严格按 DOMAIN §6（Clarification 字段 + affected_partials 重跑）、§14（clarifying 挂起/全部已答→researching、仅 affected_partials 重跑）、§15（事件 payload 规格 + 统一信封 + 全 taxonomy 覆盖）。
- EVENT-01 是 v0.11 对外开放的稳定底座——taxonomy 词表本 phase 必须落稳，校验 38/39/40 emit 名对齐。
- 工作流先行、Chat 后置（42）——已确认决策；本 phase 验证 engine 入口无关性（工作流节点是第一个真实入口）。
- UI reuse-first：节点编辑器 SSOT 自动渲染 + ask_user_question 卡片复用，不写新定制组件（无新 bespoke UI 满足 SC）。

</specifics>

<deferred>
## Deferred Ideas

- Chat 入口薄封装（Phase 42）。
- 对外 OpenAI/Anthropic adapter 透出事件（v0.11）。
- plan-session/trace 可视化视图（非 SC 必需；EVENT-01 只要求产出+持久化事件）。
- WS 实时 trace 推送（本 phase 倾向 DB 持久化为主，WS 预留）。
- 真实 LLM/容器端到端验收（沿用既有 deferred）。

</deferred>
