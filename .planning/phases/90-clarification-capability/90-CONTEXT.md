# Phase 90: 澄清能力层 - Context

**Gathered:** 2026-06-27
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous，用户逐 phase 定夺）

<domain>
## Phase Boundary

把「澄清」做成 `plan_orchestration` 的一等能力：用一套**结构化、可统计**的数据模型承载澄清，
LLM 基于需求 + 路由候选 + 召回上下文产出多问题（单/多选 + 选项 + 推荐项），并提供入口无关的
统一 `ask_clarification` 能力。**重点是把数据模型设计好**，使后续能围绕它建设出口面（91）、
插槽（92/93）、入口统一（94），并能统计「推荐采纳率」。

覆盖：CLARIFY-01（结构化数据模型）、CLARIFY-02（LLM 多问题生成接线）、CLARIFY-03（统一提问能力）。
不含：出口面/回流 resume（91）、插槽端口（92）、入口收口（94）。

</domain>

<decisions>
## Implementation Decisions

### A. Clarification 数据模型（核心——必须好好设计）

- **目标新增维度「推荐采纳率」**：每个问题都带推荐答案，用户作答后必须能统计「用户最终选择是否=推荐」，
  以便后续聚合「推荐采纳率」指标。该信号要持久化到模型里（不靠日志事后拼）。
- **建结构化父子模型，绑定技术方案**：澄清不再是单 `question`/`answer` 文本行。设计为：
  - **轮次容器**（沿用/扩展 `Clarification`，1 个 PlanSession 可有多轮 → 支撑 91 多轮）：`session` FK、
    `round_no`、`status`（pending/answered/skipped）、`origin_repo`（nullable，CLARIFY-03 可携带）、时间戳。
  - **问题行**（新增 `ClarificationQuestion`，FK 轮次容器）：`order`、`question`(text)、`type`(single/multi)、
    `options`(JSON)、`recommended`(JSON：single=str / multi=list)、`origin_repo`(nullable)。
  - **答案**（落在问题行，便于按题统计）：`selected`(JSON：single=str / multi=list[str])、`freeform_text`、
    `answered_at`、并**持久化 `recommendation_adopted`(bool/nullable)**——作答时一次性算清「选择是否命中推荐」，
    供采纳率聚合（避免事后重算/歧义）。
  - **绑定技术方案**：澄清经 `PlanSession` 关联到 `TechnicalPlan`/`PlanVersion`（session.current_plan_version）。
    为采纳率分析便利，可在轮次容器上**冗余一个 nullable plan 关联**（canonical 绑定仍是 session）。
- **单一写入入口（INV-6）**：所有澄清/问题/答案写入只经 `ClarificationService`（扩展现有），
  不旁路写表；status 流转仍只经 `PlanSessionService.transition`。
- **向后兼容**：保留现有 `Clarification.question`/`answer`/`answered_at`/`affected_partials(M2M)` 字段不删；
  新增字段 nullable、新增子表；旧单题数据读时兼容映射为「单题轮次」。迁移**不强制回填历史**，
  但提供读取兼容层（旧行 → 1 问 1 答视图）。`resume` 短路的 pending 判定从「answered_at IS NULL」
  升级为「轮次内存在未答问题」。

### B. LLM 澄清问题生成接线（clarification_questions.py 收编）

- **接入点**：在 `ClarifyAdapter.clarify` 内——先用**静态 policy**（routing 置信度无 high/medium、
  `decomposition.ambiguous`）判定「是否需要澄清」，需要时再调 `agenerate_clarification_questions`
  产结构化多题，经 `ClarificationService` 写入新模型。
- **职责切分**：静态 policy 决定「要不要问」，LLM 只决定「问什么」（省 token、确定性可控）。
- **fail-soft**：LLM 返回 `[]` 或异常时，回退到现状粗问题（`default_needs_clarification` 的 hint），
  绝不阻断编排主流程。
- **观测**：LLM 调用赋 `call_source=plan_clarification`（已存在枚举），上报请求/token/TTFT/上游错误码；
  事件 `clarification_questions_generated`（category=sampling, component=plan_orchestration）。

### C. 统一 ask_clarification 能力

- **能力落点**：在 `plan_orchestration` 内提供入口无关的 `ask_clarification` helper，
  写 `delivery.Clarification`（INV-6），编排任意点（架构师融合 / 调研容器卡住）可调用产出结构化澄清请求。
- **origin_repo**：经轮次容器/问题行的 `origin_repo` 字段携带（标记某澄清源自哪个仓的调研）。
- **入口无关**：工作流与对话复用同一 helper + 同一模型，不造两套。

### Claude's Discretion
- 子表命名、字段精确类型、迁移编号、采纳率聚合查询的具体 SQL/serializer 形态由 plan-phase 定。
- 是否把「轮次容器」直接复用 `Clarification` 还是新建 `ClarificationRound` 由 plan-phase 按最小迁移成本定，
  但必须满足：多轮、多问题、按题答案 + 推荐采纳信号、绑定技术方案、INV-6。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/services/plan_orchestration/clarification_questions.py`（**已写好待接线**）：
  `agenerate_clarification_questions(*, requirement, routing, recall_hits, max_questions=5)` +
  `normalize_clarification_questions`，产 `{question,type,options,recommended}`，已用 `call_source=plan_clarification`。
- `server/services/plan_orchestration/clarify_adapter.py`：`ClarifyAdapter.clarify` / `default_needs_clarification`
  （静态 policy）。CR-01 单轮短路（已答且无 pending → 不重跑）。
- `server/delivery/models/clarification.py`：现 `Clarification`（单 question/answer + M2M affected_partials）。
- `server/delivery/services/clarification_service.py`：`create_clarification` / `answer_clarification`（INV-6 唯一写入）。
- `server/delivery/models/plan_session.py`：`PlanSession`（status 8 态机）、`current_plan_version` 软引用。
- `server/delivery/models/technical_plan.py`：`TechnicalPlan` / `PlanVersion`。
- `server/agents/call_source.py`：`CallSource.PLAN_CLARIFICATION` 已存在；`use_call_source` 上下文。
- `server/agents/llm_factory.build_chat_model` + `services/provider_config.ProviderConfigService.aresolve`。

### Established Patterns
- 状态只经 `PlanSessionService.transition`（白名单 + 并发守卫 `ConcurrentTransitionError`）。
- 写入收口 INV-6；async ORM 走 `sync_to_async`；观测 best-effort 不反噬业务。

### Integration Points
- `PlanOrchestrationEngine._clarify` → `ClarifyAdapter.clarify` → transition `needs_clarification`/`clarified`。
- `resume.adrive_plan_session_to_pause_or_terminal` 的 clarifying 短路（pending 判定要升级）。

</code_context>

<specifics>
## Specific Ideas

- 用户强诉求：**为「推荐采纳率」指标建模**——每题持久化「推荐 vs 实选」是否一致。
- 多问题与一个技术方案绑定，数据模型要经得起后续出口面/插槽/统一入口复用。

</specifics>

<deferred>
## Deferred Ideas

- 采纳率运维大盘可视化（属观测大盘范畴，本里程碑只保证数据可统计，不做新前端图表）。
- 出口面渲染/回流/多轮续推 → Phase 91。

</deferred>
