# Phase 91: 澄清出口面 + 回流 resume (clarification-outlets-resume) - Research

**Researched:** 2026-06-27
**Domain:** 既有代码接线（Django adrf + channels / Vue3 / 飞书交互卡 / 自研 PlanSession 编排引擎）—— 无新外部栈
**Confidence:** HIGH（全部落点都在仓内有强 analog，0 个新库；签名/行号已对真实源码核对）

## Summary

本 phase 是**纯接线 + 模型复用**，几乎不引入新概念：Phase 90 已落地结构化澄清数据脊柱（`Clarification` 轮次容器 + `ClarificationQuestion` 子题 + `create_round`/`answer_round`/`ahas_pending`/`recommendation_adopted` + 入口无关 `ask_clarification` helper）。Phase 91 把这套模型「发出来 + 收回去 + 续推 + 多轮」：①会话内联卡（`ClarificationCard.vue`）从单选升级为多题多选并对接 `answer_round` 形态；②飞书群卡复用已建的 `build_clarification_card`，但**当前其 form_submit 的 `action="chat_question_answer"` 路由到的是工作流 GroupChatQuestion 回调（写 `approval_data` → `approve_node`），不是 plan_orchestration 路径**——必须新建一个澄清专用回调动作；③统一回流闭环——工作流入口节点 `ai_plan_research` 目前 CLARIFYING 只挂 `waiting_event`、**既不发卡也不建 `WorkflowEventSubscription`**，需照 `plan_deepen.py` 范式补齐；会话端 `ClarificationAnswerView` 目前只写 `chat.ConversationIntentTrace`（LangGraph 路径），需在检测到 plan 澄清时同步写 `delivery.Clarification` 并续推 `PlanSession`；④放开多轮——移除 `clarify_adapter.py:110` 的 CR-01 单轮硬限，改为带答案重判 + 轮次上界（默认 5–6）兜底。

**最大的认知陷阱**：仓内存在**两套并行的「澄清」系统**，名字几乎一样但完全不同源：(A) chat LangGraph 路径 `agents/tools/clarification.py::ask_clarification`（marker + `chat.ConversationIntentTrace` + `resume_clarification_run` 重跑 chat_graph）；(B) plan_orchestration 路径 `delivery.Clarification` + `adrive_plan_session_to_pause_or_terminal` 续推 `PlanSession`（Phase 90 模型）。**本 phase 的出口面/回流全部围绕 (B)**；现有的 `ClarificationCard.vue` + `/api/chat/clarifications/{id}/answer/` endpoint 服务的是 (A)。CLARIFY-04/06 的核心难点正是让这套前端卡 + endpoint 能**额外**渲染/回写 (B) 的结构化轮（CONTEXT 明确：扩展现有组件、endpoint 检测到 plan 澄清时同步写 delivery + 续推，**不**彻底收敛双来源——那是 Phase 94 UNIFY-05）。

**Primary recommendation:** 抽一个入口无关的共享回流 helper `services/plan_orchestration/answer_resume.py::aanswer_round_and_resume(session_or_id, answers, *, engine=None)`（薄封装 `ClarificationService.answer_round` + `build_orchestration_engine` + `adrive_plan_session_to_pause_or_terminal`，**入口私有的重调度/barrier 回灌留各调用方**），让飞书回调与会话 endpoint **同源**调用（对齐 Phase 43 `adrive_...` 抽取范式，落 CONTEXT「工作流 + 会话同源，不造两套」）。飞书侧补一个新回调动作 + 工作流节点发卡 + `WorkflowEventSubscription`；前端扩多题多选卡；adapter 放开多轮 + 轮次上界。

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**A. 与 Phase 90 数据模型打通（前置基座）**
- 出口面与回流**完全围绕 Phase 90 的结构化模型**（轮次容器 + 问题行 + 按题答案 + 推荐采纳信号 + 绑定技术方案）建设；渲染/回写都读写同一模型，不另立数据。

**B. 双出口面渲染**
- **AI 会话（CLARIFY-04）**：扩展现有 `ClarificationCard.vue` 支持**多选（checkbox）+ 多题**（现仅单选），渲染推荐项（⭐/默认选中）、可选自由输入；按 Phase 90 模型的题/选项/推荐结构渲染。
- **工作流/群（CLARIFY-05）**：复用已建 `server/feishu/cards/chat_question_card.py::build_clarification_card`（多题表单卡：单/多选 + ⭐推荐 + 「其他」input + form_submit）。飞书 App 渲染（网页版升级占位，Out of Scope）。

**C. 统一回流 resume 闭环（CLARIFY-06，当前缺）**
- **统一回流入口**：回调（飞书卡 action）/ endpoint（会话）回写结构化答案 → `ClarificationService.answer_clarification`/`answer_round`（按题写 selected/freeform + 算 recommendation_adopted）→ `adrive_plan_session_to_pause_or_terminal` 续推。**工作流 + 会话同源，不造两套**。
- **工作流侧补闭环**：`ai_plan_research` 节点澄清挂起时**发飞书澄清卡** + 建 `WorkflowEventSubscription`（对齐 `plan_deepen.py` 范式）；群卡回调 → 写答案 → 续推 → 重调度节点。
- **会话侧统一**：现 `ClarificationAnswerView` 写 `ConversationIntentTrace` 不写 `delivery.Clarification`；本 phase 让其在检测到 plan 澄清时**同步写 `delivery.Clarification` 并续推**。（彻底收敛「ToolResult marker vs delivery.Clarification」双挂起为单一来源是 UNIFY-05 / Phase 94 收尾；本 phase 先保证回流闭环跑通且写入 Phase 90 模型。）

**D. 多轮 + 防无限挂起（CLARIFY-07）**
- **放开多轮**：移除现有「单轮 CR-01 答过即放行」硬限制，答后由引擎/Agent 重判——信息仍不足再发一轮、足够则继续编排出方案。
- **上界**：设较宽松的轮次上界（**默认 5–6 轮**，实际极少触顶）；超界则带现有信息继续编排（不无限挂起），并 log 记录触顶（best-effort）。轮次由 Phase 90 的 `round_no` 承载。

### Claude's Discretion
- 飞书卡 action 回调路由的具体 endpoint/handler 命名、`WorkflowEventSubscription` 订阅键格式、会话端多选/多题卡的具体交互细节由 plan-phase 定。
- 轮次上界精确值（5 或 6）由 plan-phase 取定，须 ≥5 且有限。

### Deferred Ideas (OUT OF SCOPE)
- 流式方案卡片（STREAM v2）。
- 双挂起单一来源的彻底收敛 → Phase 94（UNIFY-05）。
- 插槽端口/节点（Phase 92）、入口收口/双挂起单一来源彻底收敛（Phase 94 收尾）。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CLARIFY-04 | 出口面·AI 会话——澄清请求在对话前端内联渲染为单/多选提问卡，用户作答经 endpoint 回流 | §Pattern 1（前端多题多选卡扩展）+ §Pattern 4（endpoint 双写 + 结构化 payload）；现状 `ClarificationCard.vue` 单选、`ClarificationAnswerView` 写 ConversationIntentTrace |
| CLARIFY-05 | 出口面·工作流/群——澄清请求经飞书交互卡由机器人发到群（复用 `build_clarification_card`） | §Pattern 2（节点发卡，复用 `build_clarification_card`）；**Pitfall 1**：现卡 `action="chat_question_answer"` 路由错位，需新建澄清回调动作 + 卡片携 `clarification_id` |
| CLARIFY-06 | 答复回流统一——回调/endpoint → answer_round → adrive 续推（工作流+会话同源，不造两套） | §Pattern 3（共享 `aanswer_round_and_resume` helper）+ §Pattern 2（节点发卡 + `WorkflowEventSubscription` + 回调重调度）+ §Pattern 4（会话端双写续推）；analog `plan_deepen.py` / `plan_revision_callback.py` / `_schedule_chat_plan_resume` |
| CLARIFY-07 | 多轮澄清——答后重判、信息不足再发一轮、足够则继续；防无限挂起 | §Pattern 5（移除 `clarify_adapter.py:110` CR-01 硬限 + 轮次上界 + 带答案重判）；**Pitfall 2**（重判必须吃答案否则同题死循环） |
| WR-03（Phase 90 review 延后收账） | 三处 pending 读法收口到 `ahas_pending` 统一谓词 | §Pattern 6；精确清单：`plan_research.py:314`、`plan_research_tools.py:212`、`plan_deepen.py:215`（+ 候选 `conversation_service.py:2318`） |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 多题多选澄清卡渲染（会话） | Frontend (Vue SPA) | API（提供结构化 pending payload） | 渲染/交互是 SPA 职责；后端只供数据 + 收答 |
| 澄清答复回写 + 采纳信号定格 | API/Service（`ClarificationService.answer_round`） | DB（delivery 模型） | 写入收口 INV-6，server 端算 `recommendation_adopted` |
| 飞书群卡发出 / 收答 | Backend（节点 + 回调 handler） | 飞书平台（卡片渲染） | 卡片由飞书 App 渲染；发卡/路由/收答全在后端 |
| 编排续推（answer→resume） | Service（`adrive_plan_session_to_pause_or_terminal`） | 工作流引擎 / chat barrier | 续驱入口无关；重挂起/重调度是入口私有 |
| 工作流挂起/恢复 | Workflow engine（`waiting_event` + `WorkflowEventSubscription`） | 回调 handler（`approve_node`/resume） | 既有挂起-回调-重入范式 |
| 多轮判定 + 轮次上界 | Service（`ClarifyAdapter` + engine `_clarify`） | DB（`Clarification.round_no`） | 编排策略层，状态只经 `transition` |

## Standard Stack

### Core（全部仓内既有，无新增依赖）

| Component | 位置 | Purpose | Why Standard |
|-----------|------|---------|--------------|
| `ClarificationService` | `server/delivery/services/clarification_service.py` | `create_round`/`answer_round`/`ahas_pending`（INV-6 唯一写入） | Phase 90 已落地，本 phase 复用不改写 |
| `adrive_plan_session_to_pause_or_terminal` | `server/services/plan_orchestration/resume.py` | 入口无关续驱到重挂起短路点/终态 | Phase 43 抽取，工作流+chat+回调三处已复用 |
| `build_orchestration_engine` | `server/services/plan_orchestration/`（barrel） | 单一 engine 工厂（chat 无 node_execution_id / 工作流带） | 不造两套 engine |
| `build_clarification_card` | `server/feishu/cards/chat_question_card.py:122` | 多题表单卡（单/多选 + ⭐推荐 + 「其他」+ form_submit） | Phase 90 预研已建，CLARIFY-05 直接复用 |
| `build_clarification_answered_card` | 同上 `:277` | 置灰「已提交」状态卡 | 收答后回卡 |
| `WorkflowEventSubscription` | `server/workflows/models/execution.py` | 挂起节点的事件订阅 + 超时兜底 | `plan_deepen`/`chat_question` 范式 |
| `register_card_callback` | `server/feishu/views.py:179` | 飞书卡片回调前缀路由注册 | 所有交互卡回调统一入口 |
| `_run_in_thread` + `bind_task_context` | `workflows/engine/scheduler.py` / `common/log_context.py` | 飞书回调 3s 内同步返回 + 后台续驱 + re-bind 触发用户 | `plan_revision_callback` 范式 |
| `ClarificationCard.vue` / `chat.ts` store | `web/src/components/chat/` / `web/src/stores/chat.ts` | 会话内联卡渲染 + `pendingClarifications` Map | CLARIFY-04 扩展点 |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| 扩展现有 `ClarificationCard.vue` | 新建 `PlanClarificationCard.vue` 专组件 | CONTEXT 锁定「扩展现有」；但两套澄清数据形态差异大（单题 vs 多题轮），plan-phase 可评估「同组件按 payload 形态分支」vs「新组件 + ChatMessageArea 按 kind 选渲染」。**Discretion** |
| 共享 helper `aanswer_round_and_resume` | 两处各自内联 answer_round + adrive | CONTEXT 锁定「不造两套」→ 必须共享 helper（mirror `adrive_...` 抽取） |
| 新回调动作 `plan_clarify_answer` | 复用 `chat_question_answer` 动作 | 复用会与 GroupChatQuestion 节点回调（写 `approval_data`→`approve_node`）路由冲突（前缀匹配，见 Pitfall 1）→ 必须新前缀 |

**Installation:** 无。本 phase 不新增任何 npm/pip 依赖。

## Package Legitimacy Audit

不适用——本 phase 不安装任何外部包（纯仓内接线 + 模型复用）。

## Architecture Patterns

### System Architecture Diagram

```text
                         ┌─────────────────────── Phase 90 模型（唯一数据源）────────────────────────┐
                         │  delivery.Clarification（轮容器: round_no/container_status/origin_repo）   │
                         │     └─ ClarificationQuestion[]（qtype/options/recommended/selected/        │
                         │                                  freeform_text/recommendation_adopted）      │
                         └──────────────────────────────────────────────────────────────────────────┘
                                   ▲ create_round            ▲ answer_round / ahas_pending
                                   │ (INV-6)                 │ (INV-6, server 算 adopted)
       ┌───────────────────────────┴───────────┐   ┌────────┴──────────────────────────────┐
       │  ClarifyAdapter.clarify (engine _clarify)│   │  ClarificationService (唯一写入入口)   │
       │  · policy 判要不要问 → LLM 判问什么      │   └───────────────────────────────────────┘
       │  · 多轮重判 + round_no 上界(5–6) [P5]    │
       └───────────────┬─────────────────────────┘
                       │ needs_clarification → CLARIFYING 挂起
        ┌──────────────┴───────────────┐
   出口面 A（会话）                出口面 B（工作流/群）
        │                                │
  ┌─────▼───────────────┐        ┌───────▼─────────────────────────────┐
  │ AIPlanResearchNode   │        │ AIPlanResearchNode（工作流入口）     │
  │ via chat 入口        │        │ CLARIFYING → 发 build_clarification_ │
  │ (start_plan_research)│        │ card + WorkflowEventSubscription [P2]│
  │ → 前端 pending_      │        │ → waiting_event                      │
  │   clarification 渲染  │        └───────┬─────────────────────────────┘
  │   ClarificationCard  │                │ 飞书群卡（飞书 App 渲染）
  │   (多题多选) [P1]     │                │ form_submit action=plan_clarify_answer [P2]
  └─────┬───────────────┘                │
        │ POST /api/chat/clarifications/   │
        │ {id}/answer/ [P4]                ▼
        │  · 检测 plan 澄清          ┌──────────────────────────┐
        │  · answer_round + 续推      │ 新回调 handler [P2]      │
        ▼                            │ form_value q{i}/qt{i}    │
  ┌──────────────────────────────────┤ → answers[] (按 order)   │
  │  aanswer_round_and_resume [P3]    │ → 后台 _run_in_thread    │
  │  (入口无关共享 helper)            │                          │
  │  answer_round → engine → adrive   ◄──────────────────────────┘
  │  ───────────────────────────────  │ 入口私有重调度:
  │  · chat: barrier/SSE 回灌         │  工作流 → approve_node / engine resume 节点重入
  │  · 工作流: 节点重入续推           │  chat   → _schedule_chat_plan_resume 已有
  └──────────────────────────────────┘
                       │ 信息足够 → clarified → researching → ... → done
                       ▼ 信息不足 & round_no < 上界 → 新一轮（回到 CLARIFYING）
```

### Component Responsibilities（落点 → 文件 + 行号）

| 落点 | 文件:行 | 角色 | 现状 → 目标 |
|------|---------|------|-------------|
| 会话内联卡 | `web/src/components/chat/ClarificationCard.vue` | 渲染 | 单题单选 button radiogroup → 多题 + 多选 checkbox + 每题 ⭐推荐默认选中 + 每题可选 freeform |
| 卡片数据契约 | `web/src/types/clarification.ts` | type | `ClarificationPayload`（单 question + options[]）→ 新增多题轮形态（questions[]，每题 question_id/qtype/options/recommended/selected/freeform） |
| 会话 API | `web/src/api/chat.ts:524` | client | `postClarificationAnswer(id, {selected_option_id, freeform_text})` → 支持 `answers: [{question_id, selected, freeform_text}]` 形态 |
| 会话 store | `web/src/stores/chat.ts:139,2548` | state | `pendingClarifications` Map + `upsertClarification`/`markClarificationAnswered` → 兼容多题轮 |
| 会话 endpoint | `server/chat/views.py:2784` `ClarificationAnswerView` | API | 仅写 `ConversationIntentTrace` → 检测 plan 澄清时**同步** answer_round + 续推 PlanSession（双写） |
| 会话 serializer | `server/chat/serializers.py:729` `ClarificationAnswerSerializer` | schema | 单 `selected_option_id`/`freeform_text` → 支持结构化 answers[] |
| 会话 runtime | `server/chat/conversation_service.py:2318` | 序列化 | `pending_clarification`（单题）→ 暴露 plan 澄清结构化轮供前端渲染（**关键传输点，见 Open Q1**） |
| 工作流入口节点 | `server/workflows/nodes/ai/plan_research.py:307` `_maybe_suspend` | node | CLARIFYING 仅 `waiting_event`（不发卡/不订阅）→ 发 `build_clarification_card` + 建 `WorkflowEventSubscription` |
| 飞书群卡 | `server/feishu/cards/chat_question_card.py:122` `build_clarification_card` | card | 复用；但 form_submit `value.action` 改为新动作 + **补 `clarification_id`/`session_id`** |
| 飞书回调 | `server/feishu/callbacks/`（新文件） | callback | 新 `@register_card_callback("plan_clarify_")`：form_value → answers[] → 共享续推 helper |
| 续推 helper | `server/services/plan_orchestration/answer_resume.py`（新） | service | answer_round + engine + adrive（入口无关，barrel 导出） |
| 多轮判定 | `server/services/plan_orchestration/clarify_adapter.py:104-116` | adapter | 移除 CR-01 单轮硬限 → 带答案重判 + `round_no` 上界 |
| pending 收口 | `plan_research.py:314` / `plan_research_tools.py:212` / `plan_deepen.py:215` | WR-03 | 裸 `filter(answered_at__isnull=True)` → `ahas_pending` 谓词（保留取问题内容用于发卡） |

### Pattern 1: 会话多题多选卡（CLARIFY-04 前端）

**What:** `ClarificationCard.vue` 现是单题 + button 模拟单选（项目无 RadioGroup 组件）+ 单 freeform。升级为多题列表，每题按 `qtype` 渲染 single（button radiogroup，现状）/ multi（checkbox，**新**），推荐项 ⭐ 标记 + 默认选中，每题各带可选 freeform。

**When to use:** 渲染 plan_orchestration 的 `delivery.Clarification` 轮（多子题）。

**关键现状（须保留的零回归点）:**

```112:165:web/src/components/chat/ClarificationCard.vue
<!-- 选项列表（用 button 实现单选；shadcn-vue 项目无 RadioGroup） -->
<div role="radiogroup" :aria-disabled="isAnswered" class="space-y-2">
  <button v-for="opt in payload.options" :key="opt.id" type="button" role="radio" ...
    @click="selectedId = opt.id">
```

**拷贝指引:** multi 用 `role="checkbox"` + `aria-checked` button 或 `Checkbox`（先确认 `web/src/components/ui/` 是否有 Checkbox；若无照单选 button 范式做多选切换 Set）。提交 payload 改为按题聚合：`answers: [{question_id, selected, freeform_text}]`，`selected` single 为 `str`、multi 为 `string[]`（对齐 `answer_round` §Code Examples）。**i18n 默认中文**，措辞接 `web/src/locales/zh-CN.json`（守护测试以真实 json 锁文案，参考 STATE.md Phase 24 范式）。

### Pattern 2: 工作流入口发卡 + 订阅 + 回调重调度（CLARIFY-05/06 工作流侧）

**What:** 照 `plan_deepen.py` 把「CLARIFYING 挂起 → 发飞书澄清卡 + 建 `WorkflowEventSubscription` → waiting_event」补到 `ai_plan_research`，并新建对应回调 handler 完成「收答 → answer_round → 续推 → 重调度节点」。

**Analog（发卡 + 订阅，几乎逐行可拷）** — `plan_deepen.py:186-207`:

```186:207:server/workflows/nodes/integrations/plan_deepen.py
        # CLARIFYING（未答）/ RESEARCHING（在途）→ 挂起等待（多轮校验澄清 HITL）。
        question = await self._apending_clarification_question(session)
        await self._send_clarify_card(
            space, project, context, question, initiated_by_user_id, log=log
        )
        if context.workflow_execution and context.node_execution:
            await WorkflowEventSubscription.objects.acreate(
                workflow_execution=context.workflow_execution,
                node_execution=context.node_execution,
                event_type="PlanDeepenCallback",
                project_key=context.workflow_context.get("project_key", ""),
                timeout_at=timezone.now() + timedelta(minutes=60),
                timeout_action="fail",
            )
        return NodeResult(status="waiting_event", output={...})
```

**Analog（回调收答 → 续推 → 重调度，逐分支可拷）** — `plan_revision_callback.py`（同步即时返回 `_ack_card` + `_run_in_thread` 后台 + `bind_task_context` re-bind + `_aget_waiting_node` 幂等门 + `approve_node` 恢复 + 全程 fail-soft 脱敏）。

**拷贝指引:**
- 节点 `_maybe_suspend`（`plan_research.py:307`）的 CLARIFYING 分支：取 pending 轮 + 其 `ClarificationQuestion` 列表 → `build_clarification_card(questions=[...], execution_id, node_id, clarification_id=<round.id>, round_no=<round.round_no>)` → 发到项目群（`ProjectService().resolve_or_create_group` + `FeishuIMService.send_card`，mirror `plan_deepen._asend_card`）→ 建 `WorkflowEventSubscription(event_type="PlanClarifyCallback")`。
- **build_clarification_card 当前不携 `clarification_id`**（只 execution_id/node_id/question_count，见 `chat_question_card.py:246-252`）。必须扩签名加 `clarification_id`（写进 form_submit `value`），否则回调无法定位 `delivery.Clarification` 轮 + 按 `order` 映射子题。
- 新回调 `@register_card_callback("plan_clarify_")`：从 `form_value` 取 `q{i}`（select 值，multi 为 list）/ `qt{i}`（「其他」freeform）→ 按 `order=i` 映射到 `ClarificationQuestion.id` → 组 `answers[]` → 调共享 helper（Pattern 3）→ 重调度节点（`approve_node` 或 engine resume，mirror `plan_revision_callback` 的 `approve_node`）→ 回 `build_clarification_answered_card`。
- `_resolve_initiator`（`plan_deepen.py:283`）取触发用户，回调 `initiated_by_user_id`/`bind_task_context` 带 `callback.user_open_id`（观测约束：后台/外部触发带 `initiated_by_user_id`）。

### Pattern 3: 入口无关共享回流 helper（CLARIFY-06「不造两套」核心）

**What:** 新建 `services/plan_orchestration/answer_resume.py`，薄封装「answer_round → build engine → adrive」，飞书回调与会话 endpoint 同源调用。

**Analog（入口无关 helper docstring + lazy import 规避环）** — `resume.py:1-17,42-45`（已是「engine 由调用方传入 / 入口私有留各方」的范本）。

**建议签名:**

```python
# server/services/plan_orchestration/answer_resume.py
async def aanswer_round_and_resume(
    clarification_or_id: Any,
    answers: list[dict[str, Any]],
    *,
    engine: Any = None,
    clarification_service: Any = None,
) -> Any:
    """按题回写答案（answer_round）后用同源 engine 续驱 PlanSession 到重挂起/终态。

    入口无关：engine 缺省经 build_orchestration_engine() 构造（chat 入口）；工作流入口
    可传带 node_execution_id 的 engine。**入口私有的重调度（工作流节点重入 / chat barrier
    回灌）留各调用方**，对齐 adrive_... 抽取精神。返回续驱后的 PlanSession。
    """
    # lazy import 规避环；answer_round → 取 session_id → build engine → adrive
```

**拷贝指引:** barrel `__init__.py` 加 import + `__all__`。helper **不**驱动重调度、**不**写 marker（入口私有）。续驱后由飞书回调走 `approve_node`、会话端走既有 `_schedule_chat_plan_resume`/SSE。`answer_round` 已幂等（按题 `answered_at IS NULL` 条件更新）→ 回调重复提交安全。

### Pattern 4: 会话 endpoint 双写 + 续推（CLARIFY-06 会话侧）

**What:** `ClarificationAnswerView`（`chat/views.py:2784`）现仅服务 chat LangGraph 路径（写 `ConversationIntentTrace` + `resume_clarification_run`）。需在检测到该 `clarification_id` 对应一个 `delivery.Clarification`（plan 澄清）时，**同步**走 answer_round + 续推 PlanSession。

**关键现状:**

```2894:2899:server/chat/views.py
        await ConversationIntentTrace.objects.filter(pk=trace.pk).aupdate(
            selected_option_id=selected_id,
            freeform_answer=freeform,
            inferred_state=implies,
            answered_at=now,
        )
```

**拷贝指引:**
- `delivery.Clarification` 与会话经 `PlanSession.conversation_id`（`plan_session.py:74`，nullable UUID 软引用）关联。检测路径：`clarification_id` → `Clarification.objects.filter(id=...).afirst()` 命中即 plan 澄清 → 取 `session_id` → 调 Pattern 3 helper + 触发 chat 续推。
- **入口判别 Discretion**：endpoint URL `clarifications/{id}/` 当前 id 语义是 `ConversationIntentTrace.clarification_id`（chat 路径）。plan 澄清的 id 是 `delivery.Clarification.id`/`ClarificationQuestion.id`。plan-phase 需定：(a) 同一 endpoint 按 id 命中哪张表分流；(b) 还是新增 `/api/chat/conversations/{id}/plan-clarification/answer/` 专路由收结构化 answers[]。倾向 (b)——payload 形态差异大（单 vs 多题轮），分流更干净，且不污染既有 chat 澄清回归测试。
- 续推后台 task 必须 `context=contextvars.Context()` 干净启动（`chat/views.py:2942-2947` 已踩过坑：复制请求 contextvars 会带 `CurrentThreadExecutor`，请求结束后 `sync_to_async` 抛 "already quit"，run 永卡——quick task `260612-crc` 修过同类）。

### Pattern 5: 放开多轮 + 轮次上界（CLARIFY-07）

**What:** 移除 `clarify_adapter.py` 的 CR-01 单轮硬限，改为「带答案重判 + `round_no` 上界兜底」。

**现状（CR-01 单轮硬限，须移除/替换）** — `clarify_adapter.py:104-116`:

```104:116:server/services/plan_orchestration/clarify_adapter.py
        # 2. §14「全部已答 → researching」单轮 HITL 语义（CR-01 无限挂起修复）：
        #    ... 已答即视为澄清满足，放行下游。
        if await Clarification.objects.filter(session_id=session.id).aexists():
            return {"needs_clarification": False}

        # 3. 首轮（本 session 尚无任何 Clarification）→ 静态 policy 判「要不要问」
        needs, question, affected_task_ids = self.policy(session)
        if not needs:
            return {"needs_clarification": False}
```

**拷贝指引:**
- 用 `ClarificationService.ahas_pending` 判 pending（步骤 1 已是，零回归）；**步骤 2 的 `aexists()` 短路**改为：统计已答轮数 `round_count = Clarification.objects.filter(session_id=...).acount()`（或 max `round_no`）→ 若 `round_count >= MAX_ROUNDS`（常量 5 或 6，CONTEXT D）→ 返回 `{"needs_clarification": False}` 并 best-effort log `clarification_round_cap_reached`（category=sampling/component=plan_orchestration）→ 带现有信息继续。
- 未达上界 → **带答案重判**：重新跑 `agenerate_clarification_questions(...)`，**把已答轮的问答喂进 prompt**（否则同信号产同题 → 死循环，见 Pitfall 2）。生成器现签名 `requirement/routing/recall_hits/max_questions`（`clarification_questions.py:132`）——可能需扩 `prior_answers`/`history` 入参或把已答内容拼进 requirement。新问题非空 → `create_round(round_no=round_count+1)`；空 → 视为信息足够，放行 researching。
- engine `_clarify`（`engine.py:170-195`）逻辑不变（只看 `needs_clarification` 转移）——多轮判定全在 adapter。
- 上界精确值（5/6）写常量 `_MAX_CLARIFY_ROUNDS`（CONTEXT Discretion，须 ≥5）。

### Pattern 6: 三处 pending 读法收口 ahas_pending（WR-03）

**What:** Phase 90 已把 adapter/resume/e2e 的 pending 判定收口到 `ahas_pending`，但仍有读站点用裸 `filter(answered_at__isnull=True)`，对新结构化子题轮**会误判**（容器 answered_at 仍空但子题已答 / 反之）。

**精确清单（grep `Clarification.objects.filter` + `answered_at__isnull=True`，已排除 service 自身与 tests）:**

| 文件:行 | 用途 | 收口方式 |
|---------|------|----------|
| `server/workflows/nodes/ai/plan_research.py:314` | `_maybe_suspend` 取 pending 决定挂起 + 取 question 发卡 | gate 用 `ahas_pending`；仍需单独取 pending 轮 + 子题列表用于 Pattern 2 发卡 |
| `server/agents/tools/plan_research_tools.py:212` | chat 工具挂起判定 | 同上 gate 收口 |
| `server/workflows/nodes/integrations/plan_deepen.py:215` | `_apending_clarification_question` 取最新未答问题 | gate/取问题分离；用 `ahas_pending` 判存在性 |
| `server/chat/conversation_service.py:2318`（候选） | runtime `pending_clarification` 序列化 | 核对是否 delivery.Clarification；是则收口 |

**拷贝指引:** `ahas_pending(session_id)` 只回 bool；发卡仍需 `ClarificationQuestion.objects.filter(clarification__session_id=..., answered_at__isnull=True).order_by("clarification__round_no","order")`。两者分工：判存在用谓词、取内容用查询。`chat/views.py:3047` 是 `ConversationIntentTrace`（chat 路径）**不在** WR-03 范围。

### Anti-Patterns to Avoid

- **复用 `chat_question_answer` 动作做 plan 澄清回调**：`CardCallbackView` 用前缀匹配（`feishu/views.py:282 action_name.startswith(prefix)`），`chat_question_answer` 已被 GroupChatQuestion 节点占用（写 `approval_data`→`approve_node`，非 plan_orchestration）。新前缀 `plan_clarify_` 隔离（mirror `plan_revision_` 刻意区别于 `plan_revise`）。
- **新建第二个 engine 工厂**：必须 `build_orchestration_engine`（CONTEXT/STATE 反复强调「不造两套」）。
- **绕过 `ClarificationService` 写 `delivery.Clarification`/`ClarificationQuestion`**：INV-6 grep 守护会红（`test_clarification_service.py` 已断言）。回调/endpoint 一律经 service。
- **adapter 让 LLM 异常上抛**：`engine.advance` 通用 except 落 `failed`（`engine.py`）→ 回归无限挂起的反面（直接失败）。`agenerate_clarification_questions` 已 best-effort 返回 `[]`，重判分支只处理 `[] → 放行`。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 续驱 PlanSession 到终态 | 新 advance 循环 | `adrive_plan_session_to_pause_or_terminal` | 已处理 clarifying/researching 短路 + max_steps fail-soft + transition 纯度 |
| 飞书卡 3s 内响应 + 后台续推 | 在 handler 内同步 await 续推 | `_run_in_thread` + `_ack_card` 即时返回 | 飞书回调超 3s 判失败；`plan_revision_callback` 范式 |
| 多题表单卡 JSON | 手拼 2.0 表单 | `build_clarification_card`（扩 `clarification_id`） | Phase 90 已建（⭐推荐/「其他」/multi_select_static/form_submit）|
| 按题写答案 + 采纳信号 | endpoint/回调里直接 update | `ClarificationService.answer_round` | INV-6 + server 端算 `recommendation_adopted`（T-90-02-02 绝不接受调用方传） |
| pending 判定 | 裸 `filter(answered_at__isnull=True)` | `ClarificationService.ahas_pending` | 兼容旧单题行 + 新子题两形态（Pitfall 2 防误放行） |
| 工作流挂起/超时 | 自建定时器 | `WorkflowEventSubscription`（timeout_at/timeout_action） | 既有订阅 + 超时兜底 |

**Key insight:** 本 phase 的「难」不在写新逻辑，而在**接对既有的两套澄清系统**——分清 A(chat LangGraph) / B(plan_orchestration) 的数据源与续推通道，所有新代码只接 B 并复用已抽好的 helper。

## Common Pitfalls

### Pitfall 1: 飞书卡 form_submit 动作路由错位 + 缺 clarification_id 锚
**What goes wrong:** 直接复用 `build_clarification_card`（其 `value.action="chat_question_answer"`）发 plan 澄清卡 → 回调被 `handle_chat_question_answer`（工作流 GroupChatQuestion 节点回调）接走，写 `approval_data`→`approve_node`，**完全不触 answer_round / PlanSession**；且卡片 value 无 `clarification_id`，即便接对 handler 也无法定位 `delivery.Clarification` 轮、无法按 `order` 映射 `q{i}`→子题。
**Why it happens:** 前缀路由 + Phase 90 卡是按工作流 chat_question 既有动作建的（当时无 plan 续推闭环）。
**How to avoid:** 扩 `build_clarification_card` 加 `clarification_id` 入参写进 form_submit value，改 `value.action` 为新前缀（如 `plan_clarify_answer`），新建 `@register_card_callback("plan_clarify_")`。
**Warning signs:** 群里提交澄清后工作流报 `approve_node` 相关错误 / PlanSession 不续推。

### Pitfall 2: 多轮重判不吃答案 → 同题死循环（或上界过严回归无限挂起反面）
**What goes wrong:** 移除 CR-01 硬限后，若 `clarify` 重判仍只看 `routing/decomposition` 静态信号（答复不改变这些信号）→ 每轮产相同问题 → 永远 CLARIFYING；反之若把上界设太小或答后无脑放行，又回到「单轮」。
**Why it happens:** CR-01 短路当初正是为防此死循环加的；放开多轮必须用**答案**改变重判输入。
**How to avoid:** 重判必须把已答轮问答喂进 `agenerate_clarification_questions`（或据已答推进 routing/decomposition）；并以 `round_no` 上界（5–6）做硬兜底——超界带现有信息继续 + log 触顶。
**Warning signs:** e2e 测试中 session 反复在 CLARIFYING / advance 触 max_steps 被 FAILED。

### Pitfall 3: 续推后台任务复制请求 contextvars 致 CurrentThreadExecutor 崩
**What goes wrong:** endpoint/回调后台续推 task 默认复制当前请求 contextvars（含 asgiref `CurrentThreadExecutor`），请求结束后 executor 退出，后台 `sync_to_async`（async ORM）抛 "CurrentThreadExecutor already quit or is broken"，run 永卡。
**Why it happens:** `asyncio.create_task` 默认复制上下文。
**How to avoid:** `asyncio.create_task(coro, context=contextvars.Context())`（`chat/views.py:2942-2947` 已有范例）+ 后台 worker 入口 `bind_task_context` re-bind 触发用户（`plan_revision_callback` 范式）。
**Warning signs:** quick task `260612-crc` 即此 bug 的历史修复记录。

### Pitfall 4: INV-6 grep 守护 / async 裸 lazy-FK
**What goes wrong:** 回调/endpoint 直接 `Clarification.objects.create/.update` → INV-6 守护测试红；async 上下文裸访问 `clarification.session` → Phase 38 CR-01 类同步 lazy-FK 崩。
**How to avoid:** 写入只经 `ClarificationService`；async 用 `*_id` 标量 / `.afirst()` / `sync_to_async` 块（`clarification_service.py` 通篇范式）。

## Code Examples

### answer_round 入参/出参形态（回流 payload 契约）

```221:252:server/delivery/services/clarification_service.py
    async def answer_round(self, round_or_id: Any, answers: list[dict[str, Any]]) -> Clarification:
        """按题作答 + 作答时一次性定格 ``recommendation_adopted``（采纳信号）。

        ``answers`` 为 ``[{question_id, selected, freeform_text}]``。每题幂等条件更新
        （仅 ``answered_at IS NULL`` 可答，重复作答 no-op 不二次覆盖首答）。采纳信号
        **只在 server 端作答时计算、绝不接受调用方传入**（T-90-02-02）：
        - single：``selected == recommended[0]``
        - multi：``set(selected) == set(recommended)`` 全等
        - 无 recommended 或纯 freeform（selected 为空）→ ``None``
```
→ 前端/飞书回调回流体统一为 `answers: [{question_id, selected, freeform_text}]`，`selected`：single=str、multi=str[]。

### ahas_pending 统一谓词（pending 判定唯一真相）

```330:352:server/delivery/services/clarification_service.py
    async def ahas_pending(self, session_id: Any) -> bool:
        """统一 pending 谓词：会话内是否仍有未答澄清（兼容旧单题行 + 新结构化子题）。"""
        return await self._ahas_pending_sync(session_id)

    @sync_to_async
    def _ahas_pending_sync(self, session_id: Any) -> bool:
        child_pending = ClarificationQuestion.objects.filter(
            clarification__session_id=session_id, answered_at__isnull=True
        ).exists()
        if child_pending:
            return True
        legacy_pending = Clarification.objects.filter(
            session_id=session_id, answered_at__isnull=True, questions__isnull=True
        ).exists()
        return legacy_pending
```

### 飞书卡 form_value 合并（回调取 q{i}/qt{i} 的来源）

```251:254:server/feishu/views.py
        # Merge form_value into action_value (for form submissions, e.g. custom_answer)
        form_value = action.get("form_value", {})
        if isinstance(form_value, dict) and isinstance(action_value_dict, dict):
            action_value_dict = {**action_value_dict, **form_value}
```
→ `build_clarification_card` 表单字段命名 `q{i}`（select 值，multi 为 list）/ `qt{i}`（「其他」），回调据 `value.clarification_id` 取轮、据 `order=i` 映射子题 id。

### 入口无关续驱 helper（Pattern 3 直接复用）

```24:48:server/services/plan_orchestration/resume.py
async def adrive_plan_session_to_pause_or_terminal(
    engine: Any, session: Any, *, max_steps: int = 20
) -> Any:
    """续驱 PlanSession 到「重挂起短路点」或终态 ``{DONE, FAILED}`` 后返回该 session。"""
    from delivery.models import PlanSession, PlanSessionStatus
    from delivery.services import ClarificationService
    from services.plan_orchestration import aall_research_tasks_terminal
    terminal = {PlanSessionStatus.DONE, PlanSessionStatus.FAILED}
```

## Runtime State Inventory

不适用——本 phase 非 rename/refactor/migration，无存量数据 key/服务配置改名。新增字段（Phase 90 已建）无新 migration（除非 `build_clarification_card` 不需改库；本 phase 预计**无新 migration**，全是接线 + 前端 + 服务方法）。**verify**：plan-phase 跑 `makemigrations --check` 应干净（除非引入新模型字段）。

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| 后端 Framework | `pytest>=9.0.2` + `pytest-django>=4.8` + `pytest-asyncio` + `respx`（httpx mock）+ `pytest-socket`（网络隔离）|
| 后端 Config | `server/pyproject.toml`（`[tool.pytest.ini_options]`），conftest 在 `server/tests/conftest.py`（adrf monkeypatch）|
| 后端 Quick run | `cd server && uv run pytest tests/delivery/test_clarification_service.py -x` |
| 后端 Full（相关） | `cd server && uv run pytest tests/delivery tests/services tests/workflows tests/test_clarification_*.py -q` |
| 前端 Framework | `vitest@^4` + `@vue/test-utils` + `happy-dom` |
| 前端 Quick run | `cd web && pnpm vitest run src/components/chat/__tests__/ClarificationCard.spec.ts` |
| 前端 typecheck | `cd web && pnpm vue-tsc --noEmit` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CLARIFY-04 | 多题多选卡渲染 + 提交聚合 answers[] | unit(vitest) | `pnpm vitest run src/components/chat/__tests__/ClarificationCard.spec.ts` | ❌ Wave 0（现 ClarificationCard 无 spec） |
| CLARIFY-04 | endpoint 收结构化 answers + 双写 delivery | integration | `uv run pytest tests/test_clarification_answer_endpoint.py -x` | ✅ 扩展（现仅 ConversationIntentTrace 路径） |
| CLARIFY-05 | 节点发 build_clarification_card（携 clarification_id） | unit | `uv run pytest tests/workflows/test_plan_research_node.py -k clarif -x` | ✅ 扩展 |
| CLARIFY-05 | 飞书回调 form_value→answers[]→answer_round | unit | `uv run pytest tests/feishu/test_plan_clarify_callback.py -x` | ❌ Wave 0 |
| CLARIFY-06 | 共享 helper answer_round + adrive 续推（工作流+会话同源） | integration | `uv run pytest tests/services/test_answer_resume.py -x` | ❌ Wave 0 |
| CLARIFY-06 | 工作流节点 CLARIFYING 建 WorkflowEventSubscription | unit | `uv run pytest tests/workflows/test_plan_research_node.py -k subscription -x` | ✅ 扩展 |
| CLARIFY-07 | 多轮：答后信息不足再发一轮 | unit | `uv run pytest tests/services/test_engine_clarify.py -k multi_round -x` | ✅ 扩展 |
| CLARIFY-07 | 轮次上界触顶带现有信息继续（不无限挂起） | unit | `uv run pytest tests/services/test_engine_clarify.py -k round_cap -x` | ✅ 扩展 |
| CLARIFY-07 | e2e 多轮 resume 续推到 done | integration | `uv run pytest tests/services/test_plan_research_e2e.py -x` | ✅ 扩展 |
| WR-03 | 三处 pending 读法经 ahas_pending（结构化轮不误判） | unit | `uv run pytest tests/workflows/test_plan_research_node.py tests/services -k pending -x` | ✅ 扩展 |
| INV-6 | 无旁路写 Clarification/ClarificationQuestion | unit(grep guard) | `uv run pytest tests/delivery/test_clarification_service.py -k inv6 -x` | ✅（Phase 90 已建，回调/endpoint 不得触红） |

### Sampling Rate
- **Per task commit:** 对应 `-k` quick run（单文件 < 30s）
- **Per wave merge:** `cd server && uv run pytest tests/delivery tests/services tests/workflows tests/feishu -q` + `cd web && pnpm vitest run`
- **Phase gate:** 后端相关全绿 + `pnpm vue-tsc --noEmit` + `ruff`/`mypy` 干净 + INV-6 守护无回归 → `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `web/src/components/chat/__tests__/ClarificationCard.spec.ts` — 覆盖 CLARIFY-04（现组件无 spec）
- [ ] `server/tests/feishu/test_plan_clarify_callback.py` — 覆盖 CLARIFY-05 回调（form_value→answers→answer_round→续推，respx/mock 飞书）
- [ ] `server/tests/services/test_answer_resume.py` — 覆盖 CLARIFY-06 共享 helper
- [ ] 既有 `test_engine_clarify.py` / `test_plan_research_e2e.py` / `test_plan_research_node.py` / `test_clarification_answer_endpoint.py` 扩多轮/上界/订阅/双写用例

## Security Domain

### Applicable ASVS Categories（security_enforcement=true, ASVS L1）

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V4 Access Control | yes | 会话 endpoint owner gate（`ClarificationAnswerView` 已有：跨用户 404 隐藏存在性 + `has_project_access`）；plan 澄清回写须同等 owner 校验，绝不让他人答他人会话的澄清 |
| V5 Input Validation | yes | answers[] 经 serializer 校验；`question_id` 必须属于该轮（`answer_round` 已按 id+`answered_at IS NULL` 过滤，越界 id no-op）；飞书 form_value 不可信，按 `order` 映射前校验 `clarification_id` 归属 session |
| V6 Cryptography | no | 不新增凭证/加密 |
| V9/V10 (Logging/Comms) | yes | 飞书 payload/上游响应/异常文本脱敏（`redact_secrets_in_text`）；后台/外部触发带 `initiated_by_user_id`（observability rule 强制） |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| 半可信 runner/飞书回调篡改 session/clarification 锚 | Tampering/Elevation | 用服务端权威字段交叉校验（mirror `_schedule_chat_plan_resume` 的 `entrypoint==CHAT` 守门 + research_task 归属校验，`subagent/api/callbacks.py:346-357`）；回调按 `clarification_id` 查 `delivery.Clarification` 再取 `session_id`，绝不信回调直传的 session_id |
| 跨会话答澄清 | Elevation | endpoint owner gate（已有，落库/续推前 404）；plan 路径同等校验 `PlanSession.conversation_id` 归属 |
| 澄清文本回灌日志泄密 | Info Disclosure | 发卡/回调正文经 `redact_secrets_in_text`（`plan_deepen._send_clarify_card` 已范式）|
| 无限挂起（DoS 自伤） | DoS | `round_no` 上界（CLARIFY-07）+ adrive `max_steps` fail-soft + `WorkflowEventSubscription.timeout_at` |

## Project Constraints (from .cursor/rules/ + AGENTS.md)

- **观测/日志（强制，`.cursor/rules/observability-logging.mdc`）**：`structlog.get_logger(__name__)`，事件 snake_case（started/completed/failed）+ `duration_ms`；每事件设 `category`（caller/sampling）与 `component`；新增飞书 webhook/回调原始 payload 脱敏后落库（`record_inbound_webhook` 已在 `CardCallbackView`）；后台任务（飞书回调/续推）显式带 `initiated_by_user_id`，worker 入口 `bind_task_context` re-bind；观测 best-effort 绝不反噬业务（`_safe_log` 范式）。
- **新增 LLM 调用**：多轮重判仍走 `agenerate_clarification_questions`（已赋 `call_source=plan_clarification`）——本 phase 不新增 LLM 调用点，复用即可；若新增需登记 LOGGING-SPEC §4.1。
- **INV-6 单一写入**：`Clarification`/`ClarificationQuestion` 写入只经 `ClarificationService`（grep 守护已建）。
- **async ORM 走 `sync_to_async`**，禁裸 lazy-FK（用 `*_id`/`.afirst`/`.aexists`）。
- **i18n 默认中文**：前端文案接 `web/src/locales/zh-CN.json`，守护测试以真实 json 锁措辞。
- **脱敏不可绕过**：飞书 payload/上游响应/异常文本 `redact_credentials`/`redact_secrets_in_text`。
- **代码风格**：Python `ruff format`（line 100, py314）+ `mypy`；TS/Vue `@antfu/eslint-config` + `vue-tsc`；注释解释意图（why）非机制，后端注释惯用中文。
- **GSD 工作流**：经 GSD 命令推进，不在工作流外直接改仓。

## Environment Availability

不适用（SKIPPED）——纯代码/接线变更，无新外部工具/服务依赖。运行测试需既有 `uv`（server）/`pnpm`（web），仓内已具备。飞书真实 App 交互卡渲染/抓包属 live-platform 人工验收（里程碑级 deferred，见 STATE.md v0.16.0 遗留）。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | 本 phase 无新 DB migration（Phase 90 字段已够，`build_clarification_card` 扩 `clarification_id` 仅卡片参数非库字段） | Runtime State Inventory | 若需新字段则多一个 migration 任务（低风险，makemigrations --check 可早发现） |
| A2 | 会话端结构化 plan 澄清宜走**新专路由**而非复用 `/clarifications/{id}/answer/`（payload 形态差异大） | Pattern 4 / Open Q1 | 若强行复用既有 endpoint，需 id 分流逻辑 + 不破 chat 澄清回归测试；plan-phase 定夺 |
| A3 | 飞书回调新前缀 `plan_clarify_`（具体名 Discretion） | Pattern 2 | 命名撞 `chat_question`/`plan_*` 前缀会路由错位（前缀 startswith 匹配） |
| A4 | 多轮重判把已答问答喂进 `agenerate_clarification_questions`（可能需扩生成器入参） | Pattern 5 | 不喂答案 → 同题死循环（Pitfall 2）；生成器签名是否够用需 plan-phase 核 `clarification_questions.py` 全文 |
| A5 | `web/src/components/ui/` 可能无 Checkbox 组件（单选现用 button 模拟，多选或同样手搓） | Pattern 1 | 若有 Checkbox 直接用；无则按 button radiogroup 范式做多选 |

## Open Questions

1. **会话端结构化澄清的「数据如何到前端」与「endpoint 如何收」**
   - What we know：plan 澄清在 chat 经 `start_plan_research`，PlanSession 关 `conversation_id`；前端现靠 `pending_clarification`（runtime，单题形态）+ SSE `phase_transition` 拿澄清。
   - What's unclear：plan 多题轮经哪条通道暴露给前端渲染（扩 `conversation_service` runtime serializer 输出结构化轮？还是 SSE 新事件？），以及收答走新路由 vs 复用 endpoint（A2）。
   - Recommendation：plan-phase 读 `conversation_service.py` runtime 序列化全段 + `ChatMessageArea.vue` 澄清渲染分支后定；倾向「runtime 暴露结构化轮 + 新专路由收 answers[]」，与既有 chat 澄清物理隔离（不污染回归、对齐 Phase 94 才彻底收敛的边界）。

2. **工作流澄清卡发到哪个群 / 项目解析**
   - What we know：`plan_deepen._asend_card` 经 `ProjectService().resolve_or_create_group` + `FeishuIMService.create(space)`；`ai_plan_research` 工作流入口有 `workflow_execution`→space。
   - What's unclear：`ai_plan_research` 节点当前不解析 space/project（不发卡）；需补 `_resolve_space`/`_aresolve_project`（`board_split_review` 提供可复用 helper，`plan_deepen` 已 import）。
   - Recommendation：复用 `workflows/nodes/integrations/board_split_review._resolve_space/_aresolve_project`，mirror `plan_deepen`。

3. **回调重调度工作流节点的具体动作**：`approve_node`（plan_revision/chat_question 范式，走 approval_data）vs 直接 engine resume + `_schedule_workflow_resume`。Recommendation：续推（answer_round + adrive）后用 `approve_node` 恢复挂起节点（与 `plan_revision_callback` 一致，最低风险），节点重入时 `_resolve_session` 据 `output_data.session_id` 续推。

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| 单题 `Clarification.question/answer` | 轮容器 + `ClarificationQuestion` 多子题 + 采纳信号 | Phase 90 (v0.16.1) | 本 phase 出口面/回流全读写新模型 |
| CR-01 单轮答过即放行 | 多轮重判 + `round_no` 上界 | 本 phase (CLARIFY-07) | 移除 `clarify_adapter.py:110` 硬限 |
| 工作流 plan 澄清仅 `waiting_event`（无卡/无订阅） | 发飞书卡 + `WorkflowEventSubscription` + 回调续推 | 本 phase (CLARIFY-05/06) | 补 `plan_deepen` 同款闭环 |
| 会话澄清仅 chat LangGraph(`ConversationIntentTrace`) | plan 澄清同步写 `delivery.Clarification` + 续推 | 本 phase (CLARIFY-06) | 双来源仍并存，彻底收敛留 Phase 94 |

**Deprecated/outdated:** 无——既有 chat 澄清路径(A) 本 phase 不动（Phase 94 收敛）。

## Sources

### Primary (HIGH confidence) — 仓内真实源码（已逐文件核对签名/行号）
- `server/delivery/services/clarification_service.py`（create_round/answer_round/ahas_pending/recommendation_adopted）
- `server/services/plan_orchestration/resume.py`（adrive_...）、`clarify_adapter.py`（CR-01 硬限）、`engine.py:170-195`（_clarify）
- `server/workflows/nodes/ai/plan_research.py`（_maybe_suspend）、`workflows/nodes/integrations/plan_deepen.py`、`chat_question.py`
- `server/feishu/cards/chat_question_card.py`（build_clarification_card）、`feishu/views.py`（CardCallbackView/register_card_callback）、`feishu/callbacks/chat_question_callback.py`、`plan_revision_callback.py`
- `server/chat/views.py:2784`（ClarificationAnswerView）、`subagent/api/callbacks.py`（_schedule_chat_plan_resume）、`delivery/models/plan_session.py:74`（conversation_id）
- `web/src/components/chat/ClarificationCard.vue`、`types/clarification.ts`、`types/chat.ts`、`api/chat.ts`、`stores/chat.ts`
- `.planning/phases/90-clarification-capability/90-PATTERNS.md` + STATE.md Phase 90 decisions
- `.planning/phases/91-clarification-outlets-resume/91-CONTEXT.md`、`.planning/REQUIREMENTS.md`、`.planning/config.json`

### Secondary / Tertiary
- 无外部 WebSearch（纯仓内接线，无新栈）。

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 全部仓内既有、签名行号核对，无新库
- Architecture（接线落点）: HIGH — 每个落点有强 analog（plan_deepen/plan_revision_callback/resume/Phase 90 service）
- Pitfalls: HIGH — 双系统错位/contextvars 崩/INV-6 均有历史先例（STATE.md / quick task）
- Open questions: MEDIUM — 会话端结构化数据传输通道 + endpoint 复用 vs 新路由需 plan-phase 读 conversation_service/ChatMessageArea 后定

**Research date:** 2026-06-27
**Valid until:** 2026-07-27（仓内代码为主，稳定；若 Phase 90 后有人改 clarification_service/plan_research 需复核行号）
