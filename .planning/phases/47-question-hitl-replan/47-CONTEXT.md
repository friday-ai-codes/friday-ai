# Phase 47: 编码遇阻 → question 抛人（HITL，非全自动 replan） - Context

**Gathered:** 2026-06-17
**Status:** Ready for planning

<domain>
## Phase Boundary

本 phase 补齐 v0.8.0 多仓 wave 编码的**最后一环 HITL 回路**——编码容器遇阻时不再走「Server 端不再重试」死路，而是 **task 侧发起 question 抛人**，回答后经 Phase 43 resume 通路驱动对应 wave/task 续跑。纯后端基础设施（无新 Vue 组件；UI hint=yes，但**复用既有 `ask_user_question` 澄清卡片 / 容器提问卡片**，reuse-first，零新前端组件）：

1. **HITL-01a — task 侧发起 question（复用既有 question 协议契约）**：编码容器（`task/`）遇阻时，复用既有 `CallbackType.QUESTION` 协议（`QuestionPayloadSerializer` + `_handle_question` + `InteractionLog` + 容器提问飞书卡片），由 task 侧主动发起提问并**阻塞等待回答**（复用既有 `answer.json` 共享卷协议 + 容器 HTTP 直达回答端点），而非走 `report_failed` 死路。等待期持续心跳保活 → `SubAgentSession` 保持 `RUNNING`。

2. **HITL-01b — 回答后经 Phase 43 resume 通路续跑**：用户/orchestrator 回答 → 既有 `handle_container_answer_enhanced` 把回答回灌容器（HTTP/volume）→ 容器提问循环解除阻塞 → agent 继续编码 → 最终 `report_completed`/`report_failed` → 既有 `_handle_completed`/`_handle_failed` → **Phase 43 `_schedule_workflow_resume` → Phase 44 `aadvance_coding_waves`** 驱动对应 wave/task 续跑。**不另造第二条 resume 通路**。因等待期容器保持 `RUNNING`，wave gate 天然视其为「在途」（`waiting`），不阻断下游、不死锁。

3. **HITL-01c — 显式非目标守护（no auto replan）**：编码遇阻**只抛人**，绝不触发全自动回溯重规划 / 重调研改方案。question/answer/resume 全链路不得调用任何编排 replan / research 重派发；全自动回溯留 backlog（REPLAN-01）。以测试 + grep 守护断言该路径不触发 replan。

**复用既有机制（硬约束，不另造）**：
- question 发起**只走**既有 `CallbackType.QUESTION` 协议 + `QuestionPayloadSerializer`（必要时仅扩展可选字段，不改既有键语义）。
- 提问卡片**只复用** `feishu/cards/container_question_card.py` + `subagent/question_handler.py`（`send_question_card_enhanced` / `handle_container_answer_enhanced` / `write_answer_to_volume`）。
- 回答回灌**只走**既有 `_send_answer_to_container`（HTTP）+ `write_answer_to_volume`（`ANSWER_FILE` 共享卷）双通道。
- 续跑**只走** Phase 43 `_schedule_workflow_resume` + Phase 44 `aadvance_coding_waves`（容器回调驱动节点重入），绝不新建轮询/定时器/第二套 resume/调度循环。

**显式不做**（留 backlog / 后续）：编码中全自动回溯重规划 / 重调研改方案（REPLAN-01，里程碑显式非目标）、新的 question 机制 / 新的 resume 通路（硬禁）、新 Vue 提问组件（复用既有卡片）、chat 编码入口的遇阻 HITL 接线（本 phase 优先 workflow wave 入口；task 侧 question helper 入口无关以便复用）、真实 runner + Docker 容器端到端 HITL 验收（沿用既有 deferred，本 phase 以 mock IO 边界测试覆盖）。

</domain>

<decisions>
## Implementation Decisions

> 基础设施 + 接口决策 phase——以下为「推荐 / 最安全默认」技术决策，autonomous 模式已全部 AUTO-ACCEPT 推荐项，均在 the agent's Discretion 范围内。Planner 可在 PLAN.md 细化，但应保持「复用既有 question 协议 + Phase 43/44 resume 通路、不造两套、守 no-auto-replan 非目标、对既有 chat 提问循环零回归」的方向。

### Area 1：task 侧 question 发起（HITL-01a）

- **D-01 发起协议**：复用既有 `CallbackType.QUESTION`，task 侧新增 `CallbackClient.report_question(question, options, context, code_snippet, default_option, timeout_minutes)` → POST `type=question` 到统一回调端点。payload 严格对齐既有 `QuestionPayloadSerializer` 字段（`question`/`options`/`context`/`code_snippet`/`default_option`/`timeout_minutes`），**不新增协议键**。
- **D-02 发起触面（agent 如何抛问）**：编码 agent 遇阻时经一个 `ask_user` 风格的进程内 SDK MCP 工具发起提问（mirror 既有 `ask_user_question` 澄清语义；落在 `task/core/` 内，reuse-first）。工具 handler 调 `report_question` 发卡 → 阻塞等待回答 → 把回答作为工具结果返回给 agent 继续编码。是否同时支持「executor 检测到确定性遇阻信号自动抛问」由 planner 定，倾向：先打通 agent 主动 `ask_user` 工具路径（最小、可单测）。
- **D-03 等待回答（复用既有回灌通道）**：发起后 task 侧**阻塞轮询**既有 `answer.json` 共享卷（`/workspace/.friday/answer.json`，`ANSWER_FILE`）；同时可暴露容器内 HTTP 回答端点供 `_send_answer_to_container` 直达（既有双通道）。轮询期间持续 `report_status(heartbeat/progress)` 保活，确保 `SubAgentSession` 不被判超时、保持 `RUNNING`。
- **D-04 超时行为（最安全默认，非目标对齐）**：等待超过 `timeout_minutes`（默认沿用 serializer 的 10 分钟）无人回答 → task 侧**优雅失败**：若给了 `default_option` 则用之续跑；否则 `report_failed(error="blocked_awaiting_human_answer_timeout")` 落既有失败终态。**绝不**触发 replan、绝不无限挂起。超时落 failed → 既有 wave gating 标 failed + 阻断下游（既有语义，零新行为）。
- **D-05 脱敏**：question/context/code_snippet 文本不得含 token/凭证；task 侧日志只记 `has_question`/`question_id`/`status`，绝不记回答正文敏感片段（对齐既有 RTOOL-03 / redact 范式）。

### Area 2：server 侧 question 接收 + 回答 + 续跑（HITL-01b）

- **D-06 question 接收复用既有**：`_handle_question` 已能处理任意 `SubAgentSession`（含带 `node_execution_id` 的 wave 编码任务）的 question 回调——创建 `InteractionLog` + 写 `last_output.pending_question` + 发容器提问卡片。本 phase **不改** `_handle_question` 主干，仅在必要时确保 wave/node 编码任务的提问卡片能正确路由 chat（`_resolve_notification_chat_id` 已支持 `node_execution.node.config.chat_id` 与 `main_session.metadata.chat_id` 双路径，缺失则 fail-soft 不发卡、不阻塞）。
- **D-07 回答回灌复用既有**：用户/orchestrator 回答 → `handle_container_answer_enhanced`（既有）→ `_send_answer_to_container`（HTTP）优先、`write_answer_to_volume`（共享卷）兜底 → 清 `pending_question`。本 phase 不改回灌主干。
- **D-08 续跑只走 Phase 43/44（硬约束）**：容器收到回答 → 继续编码 → 最终 `report_completed`/`report_failed` → 既有 `_handle_completed`/`_handle_failed` → `_schedule_workflow_resume`（Phase 43）→ 节点重入 → `aadvance_coding_waves`（Phase 44）回填/推进 wave。**绝不**为 HITL 新增 resume 通路。等待期容器 `RUNNING` → `aadvance_coding_waves` 的 `_backfill_running_terminal` 跳过在途（既有），决策出口 `waiting`，下游不被提前阻断。
- **D-09 幂等 + fail-soft**：question 回调 / 回答处理 / 续跑全部幂等（重复回调 no-op，对齐既有 status guard）；发卡 / 回灌 / 续跑副作用失败仅 `logger.warning` 降级，绝不让回调主流程 5xx（对齐既有 callback 钩子独立 try/except swallow 范式）。

### Area 3：非目标守护 + 测试 + 零回归（HITL-01c，验收硬项）

- **D-10 no-auto-replan 守护**：编码遇阻 question/answer/resume 全链路**不得**调用任何 replan / 重调研 / `start_*_research` / 重新派发 research 容器的入口。以单测断言：构造「编码容器遇阻 → 发 question → 回答 → resume」流程，断言不触发任何 research/replan 编排调用（mock 守护 + 必要时 grep 守护断言该路径无 replan 调用）。
- **D-11 task 侧单测**：`report_question` 发送正确 `type=question` payload（字段对齐 serializer）；`ask_user` 工具 handler 发起→等待→返回回答；超时 → 用 `default_option` 续跑或 `report_failed` 落 timeout 终态（不挂起、不 replan）。轮询解析 `answer.json` 正确取回答 + 幂等。
- **D-12 server 侧单测**：带 `node_execution_id` 的 wave 编码 `SubAgentSession` question 回调 → 创建 `InteractionLog` + 卡片路由（node_execution chat_id）；`handle_container_answer_enhanced` 回灌 + 清 `pending_question`；缺 chat_id → fail-soft 不抛。
- **D-13 端到端集成测试（SC 硬项）**：mock IO 边界（dispatcher / SubAgentSession / answer 通道），构造 wave 编码任务遇阻 → 发 question（容器保持 RUNNING）→ `aadvance_coding_waves` 返回 `waiting`（不阻断下游、不死锁）→ 回答 → 容器 `report_completed` → `_schedule_workflow_resume` → `aadvance_coding_waves` 推进/收尾。断言「遇阻不再 dead-end，回答后 wave 续跑」。
- **D-14 零回归命门**：既有 chat 编码提问循环（`coding`/`coding_commit` 单容器路径）行为逐字不变；未遇阻的 happy-path wave 编码行为与 Phase 46 逐字等价（无 question 时不触发任何新分支）。
- **D-15 幂等 / fail-soft 测试**：重复 question 回调 / 重复回答 → no-op；发卡失败 / 缺飞书配置 → warning 降级、容器仍可经共享卷取回答；resume 副作用失败不回灌容器回调 5xx。

### the agent's Discretion

- `ask_user` SDK MCP 工具的具体落点（`task/core/` 下新模块 vs 扩展 `remote_tools.py`）、工具名 / input_schema 细节、是否经 RemoteTool 远端工具通道 vs 进程内本地工具由 planner 按最小 diff / 复用最大化定，倾向进程内本地工具（无需 server 端 RBAC 往返，遇阻提问是容器自包含 HITL）。
- 等待回答的轮询间隔 / 心跳频率 / `timeout_minutes` 默认值细节、是否复用既有 heartbeat 上报由 planner 定。
- 是否给 wave 编码任务的提问卡片增加「方案/工作项」追溯段（对齐 Phase 46 cross-ref 可追溯精神）由 planner 决定，倾向低成本接通但非硬验收项。
- 是否顺带发 `coding.blocked` / `coding.question.raised` / `coding.resumed` trace 事件（DOMAIN §15 若已定义词表）由 planner 决定，倾向低成本接通。
- question 卡片是否需要区分「wave 编码遇阻」与既有「chat 编码提问」视觉/文案由 planner 定，倾向复用既有卡片不分叉（reuse-first）。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `subagent/api/serializers.py:QuestionPayloadSerializer`——既有 question 协议契约（`question`/`options`/`context`/`code_snippet`/`default_option`/`timeout_minutes`），task 侧发起须严格对齐，不新增键。
- `subagent/api/callbacks.py:_handle_question`——既有 question 回调处理（创建 `InteractionLog` + 写 `last_output.pending_question` + 异步发卡），对任意 SubAgentSession（含 node_execution）通用，本 phase 不改主干。
- `subagent/api/callbacks.py:_handle_completed` / `_handle_failed` / `_schedule_workflow_resume`——容器回调统一收口 + Phase 43 workflow resume 闭环（回答后续跑的唯一通路，不改契约）。
- `subagent/question_handler.py`——`send_question_card_enhanced`（发卡）/ `handle_container_answer_enhanced`（回答回灌 + 清 pending + 更新卡片）/ `_send_answer_to_container`（HTTP 直达）/ `write_answer_to_volume`（`answer.json` 共享卷兜底）。task 侧等待回答须对接此双通道。
- `services/protocols.py`——`QUESTION_FILE` / `ANSWER_FILE` / `CONTAINER_PROTOCOL_DIR`（`/workspace/.friday`）协议常量，task 侧轮询 `answer.json` 须复用。
- `feishu/cards/container_question_card.py`——`build_container_question_card` / `build_container_answered_card`，复用不新造。
- `services/plan_orchestration/wave_progression.py:aadvance_coding_waves` / `_backfill_running_terminal`——Phase 44 wave 推进核心；RUNNING 在途跳过回填、决策出口 `waiting`，等待期容器保活天然不阻断下游（HITL 续跑的承接点，不改）。
- `task/integrations/callback.py:CallbackClient`——task 侧回调客户端（`report_status`/`report_completed`/`report_failed`/`report_*`）；新增 `report_question` 对齐既有 `_callback_endpoint` + token 注入范式。
- `task/core/runner.py:TaskRunner` / `task/core/executor.py:ClaudeRunner`——编码执行入口；遇阻 question 发起 + 等待回答的接线点。
- `task/core/remote_tools.py`——进程内 SDK MCP 工具构建范式（`SdkMcpTool` / `create_sdk_mcp_server` / RTOOL-03/04 脱敏与 graceful），`ask_user` 工具可镜像此范式（倾向进程内本地工具）。
- `agents/tools/user_interaction.py` / `agents/tools/clarification.py`——既有 `ask_user_question` 澄清语义蓝本（卡片复用方向）。
- `subagent/models.py:InteractionLog` / `SubAgentSession`(`last_output.pending_question`)——提问态承载（不改）。

### Established Patterns
- 容器回调统一端点 `POST /api/containers/callback/`，`type` 路由到 `_HANDLERS`；token 校验 + 终态拒重复回调（数据补充类除外）。
- callback 钩子 fire-and-forget（`loop.create_task` / `asyncio.run` 兜底）+ 独立 try/except swallow + `logger.warning` 降级，绝不让回调主流程 5xx。
- resume 续跑统一收口：不手工翻转状态，经 `_schedule_workflow_resume` → `engine._continue_after_node` 标记重入；wave 全从 DB 重算（不读内存）。
- async ORM 经 `*_id` 标量 / `afirst` / `aexists` / `async for`，绝不裸访问同步 lazy-FK（规避 `SynchronousOnlyOperation`）。
- 凭证 / 敏感值绝不入日志 / 卡片 / 回答正文，仅记 `has_*` / id / status。
- task 侧脱敏（RTOOL-03）+ handler 永不 raise（RTOOL-04，结构化工具错误 return 而非冒泡崩容器）。
- ruff line 100、Python 3.14、async adrf；注释/docstring 中文（zh-CN）。

### Integration Points
- task 侧发起：`task/integrations/callback.py:CallbackClient.report_question` + `task/core/`（`ask_user` 工具 + 等待回答轮询，对接 `ANSWER_FILE` 共享卷 / HTTP 回答端点）。
- server 侧接收：`_handle_question`（既有，不改主干）+ `_resolve_notification_chat_id`（node_execution / main_session 双路由）。
- 回答回灌：`handle_container_answer_enhanced` → `_send_answer_to_container` / `write_answer_to_volume`（既有）。
- 续跑：`_schedule_workflow_resume`（Phase 43）→ `aadvance_coding_waves`（Phase 44）——不改契约，仅靠等待期 RUNNING 保活天然承接。
- 无新模型 / 无新迁移（复用既有 `InteractionLog` + `SubAgentSession.last_output`）。

</code_context>

<specifics>
## Specific Ideas

- 病根明确：`_handle_failed` 的「Server 端不再重试」对编码遇阻是死路；HITL-01 让遇阻走 question 抛人而非直接 failed，回答后经既有 resume 续跑。
- 「复用既有 question 协议 + Phase 43/44 resume，不造两套」是硬约束：task 侧仅补「发起 + 等待回答」，server 侧几乎零改（question 接收 / 回答回灌 / resume 全是既有），新增面集中在 `task/`。
- 等待期容器保持 `RUNNING` 是关键——`aadvance_coding_waves` 天然把 RUNNING 当在途（`waiting`），不阻断下游、不死锁，回答后正常完成回调即触发 Phase 43 resume。
- 超时最安全默认：有 `default_option` 用之，否则优雅 `report_failed`（落既有 failed 终态），**绝不** replan、绝不无限挂起。
- no-auto-replan 是里程碑显式非目标——question/answer/resume 链路不得触发任何 replan/重调研，全自动回溯留 backlog（REPLAN-01）。
- UI reuse-first：复用既有容器提问卡片 / `ask_user_question` 澄清卡片，零新 Vue 组件。
- 真实 runner + Docker 端到端 HITL 验收沿用既有 deferred；本 phase 以 mock IO 边界（answer 通道 / SubAgentSession / dispatcher）覆盖发起→等待→回答→续跑全链路。

</specifics>

<deferred>
## Deferred Ideas

- 编码中全自动回溯重规划 / 重调研改方案 → backlog（REPLAN-01，里程碑显式非目标）。
- chat 编码入口（`coding_session_service`）的遇阻 HITL 接线 → follow-up（本 phase 优先 workflow wave 入口；task 侧 question helper 入口无关以便复用）。
- executor 自动检测确定性遇阻信号主动抛问（vs agent 主动 `ask_user`）→ 倾向 follow-up（本 phase 先打通 agent 主动工具路径）。
- 真实 runner + Docker 容器端到端 HITL 验收 → 既有 deferred（本地无法闭环，本 phase 以 mock IO 边界覆盖）。
- 提问卡片的「wave 编码遇阻」专属视觉/文案分叉 → 非本 phase（reuse-first，复用既有卡片）。

</deferred>
