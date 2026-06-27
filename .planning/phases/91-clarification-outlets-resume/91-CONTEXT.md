# Phase 91: 澄清出口面 + 回流 resume - Context

**Gathered:** 2026-06-27
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous，用户逐 phase 定夺）

<domain>
## Phase Boundary

围绕 Phase 90 的结构化澄清数据模型，建设「双出口面 + 统一回流 resume + 多轮」能力：
澄清请求能在「AI 会话」与「工作流/群」两个出口面发出，用户作答统一回流并续推编排，支持多轮且不无限挂起。

覆盖：CLARIFY-04（会话内联卡）、CLARIFY-05（飞书群交互卡）、CLARIFY-06（统一回流续推）、CLARIFY-07（多轮 + 防无限挂起）。
不含：插槽端口/节点（92）、入口收口/双挂起单一来源彻底收敛（94 收尾）。

</domain>

<decisions>
## Implementation Decisions

### A. 与 Phase 90 数据模型打通（前置基座）
- 出口面与回流**完全围绕 Phase 90 的结构化模型**（轮次容器 + 问题行 + 按题答案 + 推荐采纳信号 + 绑定技术方案）建设；
  渲染/回写都读写同一模型，不另立数据。

### B. 双出口面渲染
- **AI 会话（CLARIFY-04）**：扩展现有 `ClarificationCard.vue` 支持**多选（checkbox）+ 多题**（现仅单选），
  渲染推荐项（⭐/默认选中）、可选自由输入；按 Phase 90 模型的题/选项/推荐结构渲染。
- **工作流/群（CLARIFY-05）**：复用已建 `server/feishu/cards/chat_question_card.py::build_clarification_card`
  （多题表单卡：单/多选 + ⭐推荐 + 「其他」input + form_submit）。飞书 App 渲染（网页版升级占位，Out of Scope）。

### C. 统一回流 resume 闭环（CLARIFY-06，当前缺）
- **统一回流入口**：回调（飞书卡 action）/ endpoint（会话）回写结构化答案 →
  `ClarificationService.answer_clarification`（按题写 selected/freeform + 算 recommendation_adopted）→
  `adrive_plan_session_to_pause_or_terminal` 续推。**工作流 + 会话同源，不造两套**。
- **工作流侧补闭环**：`ai_plan_research` 节点澄清挂起时**发飞书澄清卡** + 建 `WorkflowEventSubscription`
  （对齐 `plan_deepen.py` 范式）；群卡回调 → 写答案 → 续推 → 重调度节点。
- **会话侧统一**：现 `ClarificationAnswerView` 写 `ConversationIntentTrace` 不写 `delivery.Clarification`；
  本 phase 让其在检测到 plan 澄清时**同步写 `delivery.Clarification` 并续推**。
  （彻底收敛「ToolResult marker vs delivery.Clarification」双挂起为单一来源是 UNIFY-05 / Phase 94 收尾；
  本 phase 先保证回流闭环跑通且写入 Phase 90 模型。）

### D. 多轮 + 防无限挂起（CLARIFY-07）
- **放开多轮**：移除现有「单轮 CR-01 答过即放行」硬限制，答后由引擎/Agent 重判——信息仍不足再发一轮、
  足够则继续编排出方案。
- **上界**：设较宽松的轮次上界（**默认 5–6 轮**，实际极少触顶）；超界则带现有信息继续编排（不无限挂起），
  并 log 记录触顶（best-effort）。轮次由 Phase 90 的 `round_no` 承载。

### Claude's Discretion
- 飞书卡 action 回调路由的具体 endpoint/handler 命名、`WorkflowEventSubscription` 订阅键格式、
  会话端多选/多题卡的具体交互细节由 plan-phase 定。
- 轮次上界精确值（5 或 6）由 plan-phase 取定，须 ≥5 且有限。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- 前端：`web/src/components/chat/ClarificationCard.vue`（现单选 + 自由输入 + skip）、
  `web/src/types/clarification.ts`、`web/src/api/chat.ts::postClarificationAnswer/skipClarification`、
  `web/src/stores/chat.ts`（pendingClarifications Map、SSE phase_transition/ask_clarification 接入）、
  `ChatMessageArea.vue`（澄清卡独立于消息循环渲染）。
- 飞书卡：`server/feishu/cards/chat_question_card.py::build_clarification_card`（多题表单）。
- 工作流：`server/workflows/nodes/ai/plan_research.py`（挂起 waiting_event + session_id；**缺发卡/订阅**）；
  对照 `server/workflows/nodes/integrations/plan_deepen.py`（发卡 + `PlanDeepenCallback` 订阅范式）、
  `server/workflows/nodes/integrations/chat_question.py`（group_chat_question 发卡 + 回调）。
- 回流/续推：`server/delivery/services/clarification_service.py::answer_clarification`、
  `server/services/plan_orchestration/resume.py::adrive_plan_session_to_pause_or_terminal`。
- 会话端 endpoint：`server/chat/views.py::ClarificationAnswerView`（现写 ConversationIntentTrace）。

### Established Patterns
- 工作流挂起：`NodeResult(status="waiting_event")` + 调度器 `amark_waiting_event` + 容器/回调重调度。
- 续推钥匙：节点 `NodeExecution.output_data["session_id"]`；resume 后节点重入 `_resolve_session`。
- 飞书 payload/上游响应脱敏；后台/外部触发带 `initiated_by_user_id`。

### Integration Points
- 飞书卡 form_submit → 回调 handler → `answer_clarification` → `adrive_...` → 重调度节点/会话续流。
- 会话 SSE phase `waiting_clarification` → 前端 `ClarificationCard`；作答 → `postClarificationAnswer`。

</code_context>

<specifics>
## Specific Ideas

- 用户：「与 phase 90 打通，围绕数据模型建设能力，放开多轮即可，顶多五六轮次就够。」

</specifics>

<deferred>
## Deferred Ideas

- 流式方案卡片（STREAM v2）。
- 双挂起单一来源的彻底收敛 → Phase 94（UNIFY-05）。

</deferred>
