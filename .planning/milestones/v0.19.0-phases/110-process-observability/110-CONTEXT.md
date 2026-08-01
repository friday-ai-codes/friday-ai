# Phase 110: 过程可观测（阶段流式 + 容器日志 + 阶段时间线） - Context

**Gathered:** 2026-07-31
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous 变体，4 个灰区 16 问全部按推荐答案采纳）

<domain>
## Phase Boundary

把技术方案编排的**过程**对用户暴露出来：阶段进展与阶段性内容边跑边出、调研容器日志可查、失败停在哪一步一目了然。

**在范围内：** `ConvergenceSessionEvent` → chat SSE 的桥接、编排阶段时间线的前端呈现、plan_research 容器日志进入 runtime 快照并渲染、失败阶段与粗粒度原因的展示。

**不在范围内：** 改动编排本身的阶段划分与状态机；重做 Phase 107 已落地的降级提示；把 `deep_analysis_progress` 这条死路径救活；给 workflow / MCP 入口做同等的过程可视化（它们无 chat 会话，事件照常落库但没有推送目标）。
</domain>

<decisions>
## Implementation Decisions

### 事件桥接形态（OBS-01）

- **新增 SSE 事件类型 `process_event`**，承载 `event_taxonomy.build_envelope()` 的原样信封（`{event, session_id, work_item_id?, ts, payload}`）。不复用 `phase_transition` —— 那是 LangGraph 的 chat 级阶段（`executing` / `waiting` / `finalizing`），与编排的 stage key 是两套概念，混用会让两边都难改。
- **fan-out 落在 `ConvergenceSessionService._emit_event` 持久化之后**，作为单一推送出口（INV-6）。不在 7 个 stage handler 里各推一份 —— 那样每加一个阶段就要记得补推，是必然漂移的形态。
- **关联键取 `ConvergenceSession.conversation_id`**（chat 入口在 `plan_research_tools.py` 经 `start_orchestration` 写入），与 SSE 信封已有的 `run_id` 并行使用，不新建映射表。
- **断线与刷新兜底：** 事件本来就落库，前端在建立/重建流时用 runtime 快照补齐历史事件，保证「刷新页面不丢时间线」。非 chat 入口（workflow / MCP）没有推送目标，事件照常落库、不报错、不阻塞 —— fan-out 必须 best-effort。

**裁决 D-1（阻塞项，勘察实测）：`ConvergenceSessionEvent` 今天是只写不读的。** 没有 REST 读取面、没有 SSE 桥接、前端零消费；`workflows/reactions/signal.py:67` 定义了 `SOURCE_PROCESS_EVENT` 但没有对应的投影实现。ROADMAP SC-4 的「复用同一事件源」是**方向正确但尚未接线** —— Phase 110 的第一件事是把桥搭出来，而不是接到一个现成的通道上。planner 必须按「新建桥接」而非「接既有通道」来排 task。

**裁决 D-2（SC-4 的正确读法）：「不新建平行推送通道」指的是不为进度另起一套事实来源，而不是禁止新增 SSE 事件类型。** 事实来源唯一（`ConvergenceSessionEvent`），传输复用既有 chat SSE 连接，只是在既有信封协议里多一个 `type`。这满足 SC-4；若为了避免新增 type 而去挤 `phase_transition`，反而制造了「同一通道两种语义」的新债。

### 阶段时间线呈现（OBS-03）

- **复用 `web/src/components/execution/dag/SubStepTimeline.vue`** —— 竖向步骤 + 状态点 + 失败摘要行，形状正好。项目硬约束：不新增组件原语、不新增色板与字号。
- **挂在编排工具气泡内**（in-flight 期间），编排完成后收敛为 Phase 109 已落地的 `OrchestratedPlanCard`。`OrchestratedPlanCard.vue:6-7` 的注释已显式把进度 UI 留给本相位。
- **阶段粒度取 ROADMAP 的六个用户面标签**（拆分 / 路由 / 召回 / 澄清 / 并行调研 / 融合），不直接暴露 7 个内部 stage key。`classify` 只在 feature_list 流程出现，映射为**可选步**：非该流程时不显示该步，而不是显示一个永远跳过的灰步。
- **阶段性内容每阶段一句话摘要**（路由：命中仓数与是否降级；召回：条数；调研：各仓完成进度；融合：重试轮次），不展示思维链。payload 里已有的结构化字段够用，不为此新增 LLM 调用。

### 容器日志可见（OBS-02）

- **根因是读取时过滤，不是写入时。** `conversation_service.get_conversation_runtime:2458-2468` 的谓词是 `task_type == EXPLORE AND last_output.source == "chat_deep_analysis"`，而 plan_research 走的是 `TaskType.PLAN` + `source == "plan_research"`（`research_adapter.py:182-196`）—— 双重不匹配。日志本身经 `runners/consumers.py:_append_runtime_log` 已经写进 `last_output.logs` 了，只是快照不吐。
- **放宽方式：加独立分支与独立返回字段**，不把 plan_research 会话混进 `deep_analysis_sessions` —— 混进去会让前端拿到两种语义不同的东西还得二次判别，是给自己挖坑。
- **前端复用 `DeepAnalysisCard` / `DeepAnalysisGroup` 渲染**，仅换标签文案。
- **多仓并行按仓分组**，每仓一张卡（调研本就是 per-repo 容器），与用户对「并行调研」的心智一致。
- **脱敏与归属校验沿用既有设施**（`redact_secrets_in_text` + deep analysis 那套会话归属判定），不另起一套。

### 失败呈现与观测埋点

- **失败事实取 `ConvergenceSession.current_stage` + `session.error`** —— `engine.py:94-101` 已经在异常路径写了结构化 `{stage, exception, message}`，不需要解析日志反推。
- **时间线上失败阶段标红 + 粗粒度原因**；原始异常文本经脱敏后才可展示。
- **裁决 D-3（SC-4 的「同一状态不存在两处各自实现」）：时间线不重复渲染降级提示。** 降级仍归 Phase 107 的 `RoutingDecisionPanel` 负责，时间线只在「路由」这一步标一个角标。勘察发现 107 的降级 UI 实际读的是 tool-result 里的路由 trace 而非事件表 —— 本相位**不回改** 107 的实现（返工面大、收益低），而是靠「谁渲染什么」的分工来满足 SC-4：同一事实只有一个渲染者。
- **埋点按 LOGGING-SPEC：** fan-out 是高频路径，用 `category="sampling"` + debug，绝不在每个事件上打 INFO。`component` 沿用 `convergence_session_service` / `process_runtime`。新增的 runtime 读取分支纳入既有请求指标。**不新增 LLM 调用，故不需要新 `call_source`。**
- **观测代码 best-effort：** 桥接失败必须吞掉，绝不反噬编排主流程 —— 编排跑通比进度可见重要得多。

### Claude's Discretion

- `process_event` 在前端 store 的具体落点与状态结构、runtime 快照补齐历史事件的字段命名、时间线组件的 props 适配层，由 planner / executor 按代码库惯例定。
- plan_research 会话与 `ConvergenceSession` 的绑定键（勘察建议 `last_output.plan_session_id`）需 planner 实读确认后定版。
- 阶段摘要的具体文案由 executor 按既有 i18n 惯例定（默认中文）。
</decisions>

<code_context>
## Existing Code Insights

### 可复用资产

- `ConvergenceSessionEvent`（`server/delivery/models/convergence_session_event.py`）：已有 `(session, ts)` 索引，正是时间线查询面；`build_envelope()` 在 `event_taxonomy.py:121-135`。
- `ConvergenceSessionService._emit_event`（`convergence_session_service.py:304-335`）：已是 best-effort、永不抛出的单一事件出口 —— fan-out 挂这里天然继承这个性质。
- `SubStepTimeline.vue`（`web/src/components/execution/dag/`）：竖向步骤 + 状态点 + 失败摘要（`:61-66`）。
- `DeepAnalysisCard` / `DeepAnalysisGroup` + `useDeepAnalysisLog`：容器日志渲染的现成一套。
- `_append_runtime_log`（`runners/consumers.py:925-946`）：写日志是 source-agnostic 的，plan_research 的日志**已经在库里**。

### 既有模式

- SSE 信封格式：`chat/streaming.py:14-30` —— `data: {"type": <event>, ...event.data, "message_id", "run_id"}`。
- 事件类型枚举：`agents/core/events.py:12-79`。
- runtime 轮询：`chat.ts:1043-1077`（`pollConversationRuntime`，2s 间隔）—— 深度分析日志走的就是这条，不是 SSE 推送。
- CAS 状态推进：`transition()` 的 `UPDATE ... WHERE current_stage=from_stage`，第二方命中 0 行抛 `ConcurrentTransitionError`。

### 集成点

- fan-out 注入点：`convergence_session_service.py:304`（`_emit_event` 内，`_persist_event` 之后）。
- SSE 生成器：`chat/views.py:1440-1549`（`_stream_events`，Phase 109 刚在此补过用户绑定）。
- runtime 快照放宽点：`chat/conversation_service.py:2458-2468`。
- 前端事件分发：`web/src/stores/chat.ts` 的 `switch (event.type)`。
- 渲染挂载点：`ChatMessageBubble.vue:1251-1255`（编排工具完成后渲染 `OrchestratedPlanCard` 的分支）。
</code_context>

<specifics>
## Specific Ideas

- 六个用户面阶段标签直接取 ROADMAP SC-1 的原文措辞（拆分 / 路由 / 召回 / 澄清 / 并行调研 / 融合），不另造词。
- 「体验与深度分析一致」是 OBS-02 的原文要求 —— 复用 `DeepAnalysisCard` 不只是省事，本身就是需求的字面含义。
- 勘察发现 `deep_analysis_progress` 这个 SSE 事件类型已定义但**从无生产发射方**（`deep_analysis_registry.register()` 从未被调用）。不要把它当成可参照的先例，也不要顺手去救活它 —— 那是范围外的死代码清理。
</specifics>

<deferred>
## Deferred Ideas

- **workflow / MCP 入口的过程可视化**：这两条链无 chat 会话，没有推送目标。事件照常落库，将来若要做，读取面已经具备（`(session, ts)` 索引）。
- **`SOURCE_PROCESS_EVENT` 的信号投影实现**（`workflows/reactions/signal.py:67` 定义了常量但无 `project_from_process_event()`）：属工作流反应体系，与本相位的用户可见性目标不同源。
- **清理 `deep_analysis_progress` 死路径**：范围外。
- **把 Phase 107 的降级提示改为读事件表**：返工面大、用户可见收益为零，按 D-3 明确不做。
</deferred>
