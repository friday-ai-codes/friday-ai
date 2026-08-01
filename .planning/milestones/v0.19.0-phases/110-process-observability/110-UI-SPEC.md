---
phase: 110
slug: 110-process-observability
status: draft
shadcn_initialized: true
preset: none（既有 web/components.json，本 phase 不跑 init、不拉 registry 块）
created: 2026-07-31
---

# Phase 110 — UI Design Contract（在途阶段时间线 + 失败停在哪一步 + 调研容器日志按仓可见）

> 本 phase 的 UI 面是**编排在途期间**的那块空白——Phase 109 的裁决 D-4 把它整块留给了本相位
> （`OrchestratedPlanCard.vue:5-7` 的注释逐字写着「不做进度 / 阶段 UI，阶段可见性整块留给 Phase 110」）。
> 三块增量：
> ① **在途阶段时间线（OBS-01 / OBS-03）**：编排工具气泡内竖向六步（+ 可选第七步）时间线，
>    每步一句结构化摘要，完成后收敛为一行、把版面交给 `OrchestratedPlanCard`；
> ② **失败呈现（OBS-03）**：失败阶段标红 + 粗粒度原因闭集，原始异常文本不进渲染路径；
> ③ **调研容器日志（OBS-02）**：plan_research 容器日志**按仓一张卡**，复用 `DeepAnalysisCard` 渲染。
>
> **与 Phase 107 的边界（裁决 D-3）**：降级提示与 confidence 徽标灰化**仍归 `RoutingDecisionPanel`**，
> 时间线只在「路由」这一步标一个 `Badge variant="warning"`「降级」角标，不重复渲染横幅与原因句。
> 见 §交互契约 D（内含一条必须上报的事实：该面板今天在 SPA 里**没有任何挂载点**）。
>
> AUTONOMOUS MODE：所有未决问题按既有设计系统（`web/DESIGN.md`）与代码惯例自行裁定，逐条标注 `[默认决策]`。

---

## 落点与数据链路（侦察结论）

### 落点一览

| # | 文件 | 性质 | 本 phase 增量 |
|---|------|------|--------------|
| 1 | `web/src/components/chat/OrchestrationStageTimeline.vue` | **新建** | 在途阶段时间线卡（内嵌复用 `SubStepTimeline`）+ 终态收敛为一行 + 单一 sr-only live region |
| 2 | `web/src/components/execution/dag/SubStepTimeline.vue`（71 行，实读） | 改（**纯加性**） | item 类型与 `SubStep` 解耦；新增 `skipped` 态、可选 `summary` 行、可选 `badge`、`interactive` 开关、状态文本 |
| 3 | `web/src/components/chat/PlanResearchLogGroup.vue` | **新建** | 按仓分组的调研容器日志（`v-for` 内嵌复用 `DeepAnalysisCard`）+ 组标题 |
| 4 | `web/src/components/chat/ChatMessageBubble.vue`（`:1223-1266` 单例 tool 分支，实读） | 改 | 在途分支挂时间线与日志组；`orchestratedPlanData` 的 `.find` 加固为「末位终态匹配」 |
| 5 | `web/src/stores/chat.ts` | 改 | `switch (event.type)` 加 `process_event` case；`orchestration` / `planResearchSessions` 状态；`applyRuntimeSnapshot` 补齐 |
| 6 | `web/src/types/chat.ts` | 改 | `ProcessEventEnvelope` / `OrchestrationRuntime` / `PlanResearchSession` + `ConversationRuntime` 扩两字段 |
| 7 | `server/chat/conversation_service.py::get_conversation_runtime` | 改（后端） | `orchestration` 快照 + `plan_research_sessions` 独立分支（`:2458-2468` 谓词放宽点的**旁路**，不混入 `deep_sessions`） |
| 8 | `server/delivery/services/convergence_session_service.py::_emit_event` | 改（后端） | `_persist_event` 之后 best-effort fan-out 到 chat SSE（单一推送出口，INV-6） |

### 关键现状事实（实读，planner 直接采信）

**A. 编排工具在途期间已经是一个独立的单例 tool 气泡——挂载点现成，无需改分组算法。**
`UNGROUPABLE_TOOLS`（`ChatMessageBubble.vue:506-512`，109-04 已加入 `start_plan_research` /
`start_feature_solution`）保证编排工具走 `item.kind === 'tool'` 单例分支（`:1223-1266`），
不被归入「分析过程」折叠面板。⇒ 时间线与日志组直接作为 `tool-pill` 的兄弟节点插在
`OrchestratedPlanCard`（`:1252-1255`）**之前**即可，**不动 `groupedDisplayItems` 算法**。

**B. 🔴 编排的 7 个内部 stage 里，只有 6 个有事件；「拆分」一步在事件流里是哑的。**
实读 `builtin_processes.py:270-315` 的 `_TECHNICAL_PLAN_STAGES`：

| stage key | handler emit 的领域事件 | payload（实读，逐字） |
|-----------|------------------------|----------------------|
| `decompose` | **无** | — （`_h_decompose` 只打 `logger.info`，`:69-74` / `:91-96`） |
| `route` | `repo.routing` | `{candidates:[{repo_id,confidence,score,breakdown}], router_version, degraded, auto_selected, stage0, stage1, versions, weight_config?, repo_meta?}`（`:109-180`） |
| `recall` | `knowledge.recalling` | `{query, kinds, hits}`（`hits` 是**条数**，`:183-193`） |
| `classify` | `technical_plan.feature.classified`（**仅 feature_list**） | `{summary:{new,modify,unclear}, evidence_hits}`（`:214-221` + `classify_adapter.py:68/107`） |
| `clarify` | `clarification.asked` / `.answered` / `.timed_out` / `.delivery_failed` | asked = `{clarification_id, question}`（`clarify_adapter.py:260-263`）；timed_out = `{clarification_id, round_no, exit_action, waited_seconds, unclarified_points}` |
| `research` | `repo.research.started` / `.completed` / `.failed` | started = `{repo_id, task_id, focus}`（`research_adapter.py:224-232`）；completed = `{repo_id, task_id, summary, candidate_files, api_contracts_exposed}`（`callbacks.py:1788-1796`）；failed = `{repo_id, task_id, error}` |
| `merge` | `technical_plan.merge.started` / `.completed` / `technical_plan.validation.failed` | started = `{partials, extra_evidence_count}`（`architect_merge_adapter.py:204-208`）；completed = `{artifact_version_id}`（`:275-277`）；validation.failed = `{reasons:[check名]}`（`:349-350`） |

**B2. 但每次 `transition()` 都会额外 emit 一条「转移事件名」**（`convergence_session_service.py:188`：
`await self._emit_event(event, session, {})`，**payload 恒为空**）。即事件流里还有
`decomposed` / `routed` / `recalled` / `classified` / `clarified` / `needs_clarification` /
`research_dispatched` / `research_complete` / `merged` / `validation_failed_*` / `exhausted` / `fail`。
⇒ **阶段推进的骨架靠转移事件，阶段摘要的内容靠领域事件**，两类都从同一条 `process_event` 通道来。
「拆分」因此**能拿到状态**（`decomposed` 一到就是完成），但**拿不到摘要**（需求点条数只在
`stage_state.decomposition.segments` 里）⇒ 摘要走运行时快照补，见 §前端数据契约。

**C. 🔴 `process.session.failed` 与 `fail` 两条失败事件的 payload 都是空 dict。**
`convergence_session_service.py:272`（`_fail` 路径）与 `:188`（`transition("fail")` 路径）
都传 `{}`。⇒ **失败原因不在事件里**，必须按 CONTEXT 的裁决从
`ConvergenceSession.current_stage` + `session.error` 取——即走**运行时快照**，不是 SSE 事件。
SSE 的失败事件只负责「立刻把状态翻红」，原因文案在同一次快照/下一次轮询里补齐（§交互契约 B.3）。

**D. `session.error` 的实际形状是「半闭集」，不能直接上屏。** 全部 `transition(session,"fail",error=…)` 落点实读：

| 落点 | error 形状 | 含自由文本？ |
|------|-----------|------------|
| `engine.py:94-101`（stage 内未捕获异常，**最常见**） | `{stage, exception:<异常类名>, message:<str(exc)>}` | 🔴 是（`message` 是原始异常文本，**无 `reason` 键**） |
| `builtin_processes.py:253-261`（融合限次耗尽） | `{stage:"merge", reason:"merge_validation_exhausted", report:{…}}` | 🔴 是（`report.errors[].message`） |
| `expire_pending_clarifications.py:399-405`（澄清超时无人答） | `{stage:"clarify", reason:"clarification_timeout_no_answer", clarification_id}` | 否 |
| `resume.py:47-49`（advance 步数超限） | `{reason:"advance_step_limit", steps}` | 否 |
| `engine.py:74-77` / `:84-87`（注册缺失） | `{reason:"unknown_process_type"|"unknown_stage", …}` | 否 |
| `_fail` 收到非 dict | `{message:str(error)}` | 🔴 是 |

⇒ **后端必须把它压成闭集 `reason_code` 再出网**（§前端数据契约 后端契约要求 #4）。前端拿到的
永远是枚举值，不是异常文本——这不是前端"选择不渲染"，而是**渲染路径上根本没有这个字符串**。

**E. 容器日志被挡在快照外的根因是读取谓词，日志本身早就在库里。**
`conversation_service.py:2462-2468` 的谓词是 `task_type == EXPLORE` **且**
`last_output.source == "chat_deep_analysis"`；plan_research 走的是 `TaskType.PLAN` +
`source == "plan_research"`（`research_adapter.py:182-196`，`last_output` 同时带
`plan_session_id` / `research_task_id` / `repository_id` 三个绑定键）。日志经
`runners/consumers.py:925-946` 的 `_append_runtime_log` 写进 `last_output.logs`（**source-agnostic**，
最多保留 80 条 `_MAX_RUNTIME_LOGS`），形状是 `{type, content, ts}`——与 `DeepAnalysisLog` 逐字同形。
⇒ 前端 `decorateDeepLog`（`useDeepAnalysisLog.ts:85-158`）可**零改动**解码 plan_research 的日志。

**F. 🔴 `orchestratedPlanData` 用 `.find` 取首个编排工具，异步路径下卡片不会出现。**
`ChatMessageBubble.vue:791-816` 是 `toolCalls.value.find(tc => isOrchestrationTool(tc.name))`，
命中**第一个**。而编排在 chat 里的真实时序是：`start_plan_research` 同步跑完
`decompose→route→recall→classify→clarify`，到 `research` 才挂起并返回
`{__blocking_task__:true, …}`（`plan_research_tools.py:245-272`，**无 `artifact_version_id`**）；
容器回调后经 `callbacks.py:389-495` 续驱 + barrier 回灌，二次运行的 prompt 明确写着
「不要再调用任何工具」（`graph.py:812-819`），且 `all_tool_calls = state.tool_calls + 新增`
（`graph.py:851`）⇒ 同一条消息里那条 `__blocking_task__` 的 tool call **永远在最前**。
两种情形都指向同一个结果：**异步路径上 `OrchestratedPlanCard` 不渲染**。
本相位**不承担补 109 的入口缺口**（超出边界），但因此有两条硬性约束：
1. **时间线自身的终态就是完成信号**，不得依赖卡片出现（§交互契约 A.6）；
2. 顺手做**一行加固**：`.find` → 「从后往前找第一个解析得终态的编排工具」。成本极低，
   否则 110 落地后卡片仍不出现，会被误判成 110 的回归。[默认决策]

**G. 编排在途期间前端拿不到 `session_id`。** 工具直到挂起才返回带 `session_id` 的 result，
而 `decompose→clarify` 五个阶段都发生在 result 之前（tool pill 一直是 `running`）。
⇒ 时间线**不能靠解析 tool result 来绑定会话**，必须靠 `process_event` 自带的 `session_id`
+ store 里「本次 run 的活跃编排会话」来绑（§前端数据契约 `activeOrchestrationSessionId`）。

### 已就位可复用资产（零新依赖、零新色板、零新组件原语）

| 资产 | 位置 | 本 phase 用法 |
|------|------|--------------|
| `SubStepTimeline`（竖向连线 + 状态点 + 失败摘要行） | `web/src/components/execution/dag/SubStepTimeline.vue:29-71` | 时间线本体。**加性泛化**后同时服务 `ExecutionNode`（`:340`）与本 phase，见 §交互契约 A.2 |
| `DeepAnalysisCard`（头部状态点 + `{n} 步` + 逐行日志 + 结构化展开） | `web/src/components/chat/DeepAnalysisCard.vue`（353 行，实读） | 每仓一张调研日志卡，**零改动**（`taskLabel` / `status` / `defaultExpanded` 三个 prop 够用） |
| `decorateDeepLog` / `isLongText` / `previewText` / `TOOL_LABELS_CN` | `web/src/composables/useDeepAnalysisLog.ts` | 容器日志解码，**零改动**（日志形状同源） |
| `Badge` 8 variant | `web/src/components/ui/badge/index.ts` | 路由行降级角标 `warning`；时间线折叠头计数不用 Badge（见 §Typography） |
| `.card` / `animate-fade-in` / `shadow-card` | `web/src/styles/main.css:181` / `:95` | 时间线卡与 `OrchestratedPlanCard`（`:108`）**同一张卡底**，收敛时视觉连续 |
| `OrchestratedPlanCard` 卡片骨架 | `web/src/components/chat/OrchestratedPlanCard.vue:108-121` | 头部 `px-4 py-3 border-b border-border/50 flex items-center gap-2` + `icon-[lucide--workflow] text-primary` **逐字沿用**，让"在途 → 完成"看起来是同一张卡在变 |
| 硬编码中文常量惯例 | `TOOL_LABELS`（`useToolDisplay.ts:23`）、`SIGNAL_LABELS`（106-05）、`COPY`（`OrchestratedPlanCard.vue:35-45`） | 新增文案沿用 `COPY` 常量对象，**不接 vue-i18n**（见 §Copywriting 首段） |
| `repoNames` 映射（`repository_id → name`） | `ChatMessageBubble.vue:407-410`（源自 `repositoriesStore.repositories`） | 调研卡与「并行调研」摘要的仓库名兜底解析 |

**图标可用性已核验**（worktree 内 `rg` 计数）：`workflow`、`loader-2`、`chevron-right`、
`triangle-alert`、`check-circle-2`、`terminal`、`layers`(17)、`folder-git-2`(17)、
`search-code`(3)、`list-checks`(5) 均已在仓内使用。**`folder-search` / `route` / `merge` /
`microscope` 仓内零使用，本契约不采用。**

---

## 前端数据契约变更（供 planner 提升为任务）

```ts
// web/src/types/chat.ts

/** 编排内部 stage key（与 builtin_processes._TECHNICAL_PLAN_STAGES 字面对齐，7 值）。 */
export type OrchestrationStageKey
  = 'decompose' | 'route' | 'recall' | 'classify' | 'clarify' | 'research' | 'merge'

/**
 * 时间线单步状态（5 值）。
 * `skipped` 与 `unknown` 共用同一视觉（空心灰点），靠摘要文案区分——见 §交互契约 A.3。
 */
export type OrchestrationStageStatus
  = 'pending' | 'active' | 'complete' | 'failed' | 'skipped' | 'unknown'

/**
 * 失败原因闭集（6 值 + 兜底）。**由后端从 session.error 压制而来**，
 * 前端永远拿不到 `error.message` / `error.exception` / `error.report`。
 * 故意保留 `| string`：后端新增取值时前端不该编译失败，而应走「未知原因」保守分支。
 */
export type OrchestrationFailReason
  = 'stage_exception'
    | 'merge_validation_exhausted'
    | 'clarification_timeout_no_answer'
    | 'advance_step_limit'
    | 'unknown_process_type'
    | 'unknown_stage'
    | 'unknown'

/** chat SSE 新增事件类型：`event_taxonomy.build_envelope()` 的原样信封 + format_sse 的两个附加键。 */
export interface ProcessEventEnvelope {
  type: 'process_event'
  /** taxonomy 事件名或 stage 转移事件名（开放集，见 §落点 B/B2）。 */
  event: string
  session_id: string
  work_item_id?: string | null
  /** ISO8601 串。 */
  ts: string
  payload: Record<string, unknown>
  message_id?: string
  run_id?: string
}

/** 运行时快照里的编排进度（刷新/重连补齐的权威态）。 */
export interface OrchestrationRuntime {
  session_id: string
  /** ConvergenceSessionStatus 字面值。 */
  status: 'created' | 'running' | 'waiting_clarification' | 'waiting_event' | 'done' | 'failed' | string
  /** 权威阶段指针——**折叠事件流得到的指针与它冲突时以它为准**。 */
  current_stage: OrchestrationStageKey | string
  /** 是否走 feature_list 流程（决定「功能点分类」步是否出现）。 */
  has_classify: boolean
  /** 拆分出的需求点条数（事件流里拿不到，只能走快照，见 §落点 B）。 */
  segment_count?: number | null
  /** 失败事实；仅 status === 'failed' 时非空。 */
  failure?: { stage: OrchestrationStageKey | string, reason_code: OrchestrationFailReason | string } | null
  /** 历史事件（按 (ts, created_at) 升序）。截断时保留**最新** N 条并置 events_truncated。 */
  events: Array<{ event: string, ts: string, payload: Record<string, unknown> }>
  events_truncated?: boolean
}

/** plan_research 容器会话（**独立字段，绝不混进 deep_sessions**）。 */
export interface PlanResearchSession {
  /** SubAgentSession.session_id */
  session_id: string
  /** 归属的 ConvergenceSession id（绑定键，实读确认为 last_output.plan_session_id）。 */
  plan_session_id: string
  repository_id: string
  /** 后端解析的仓库名；缺失时前端回退 repoNames[repository_id]，再兜底常量。 */
  repository_name?: string
  /** SubAgentSession.status（PENDING/RUNNING/COMPLETED/ERROR/…）。 */
  status?: string
  /** 与 DeepAnalysisLog 逐字同形，直接喂 decorateDeepLog。 */
  logs: DeepAnalysisLog[]
}

export interface ConversationRuntime {
  // ...既有字段不变
  /** ---- [新增 110] ---- 本对话最近一次编排会话的进度快照；无编排时为 null。 */
  orchestration?: OrchestrationRuntime | null
  /** ---- [新增 110] ---- 该编排会话下的调研容器会话（按 repository 一条）。 */
  plan_research_sessions?: PlanResearchSession[]
}
```

**后端侧硬性契约要求（planner 必须落进后端 task，否则前端无法正确渲染）**：

1. **新增 SSE 事件类型 `process_event`**，body 为 `build_envelope()` 原样信封。
   `format_sse`（`chat/streaming.py:14-30`）是 `{"type": event.type, **event.data, message_id, run_id}`
   的平铺结构 ⇒ 信封的 5 个键平铺在顶层，前端按上表消费。**不复用 `phase_transition`**（裁决既定）。
2. **fan-out 挂 `_emit_event` 的 `_persist_event` 之后**（`convergence_session_service.py:304-324`），
   **best-effort 且 `session.conversation_id` 为空时静默跳过**（workflow / MCP 入口无推送目标，
   照常落库、不报错、不阻塞）。埋点 `category="sampling"` + `debug`，绝不在每个事件上打 INFO。
3. **运行时快照的 `events` 有上界**（建议 200 条；多仓调研 + 融合重试可轻松破百）。
   🔴 **截断必须保留最新 N 条并置 `events_truncated=true`**——前端靠折叠事件算摘要，
   但**阶段指针取 `current_stage`**，所以截断只会丢摘要精度、不会让时间线走错阶段。
   反过来（保留最旧 N 条）会让时间线永远停在早期阶段，是错的。
4. 🔴 **`failure.reason_code` 必须在服务端压成闭集**：`error.reason` 存在则直取；
   不存在但有 `exception` 键（`engine.py:94-101` 那条最常见路径）→ `stage_exception`；
   其余 → `unknown`。**`error.message` / `error.exception` / `error.report` 一律不出网**
   （不进 `orchestration` 快照、不进 `process_event` payload）。原始文本的去处是
   `SystemLogEntry` / 事件表本身，供 superuser 排障——与 107-UI-SPEC Unresolved #4 同一条纪律。
5. **`plan_research_sessions` 走独立分支、独立字段**：谓词
   `task_type == PLAN AND last_output.source == "plan_research" AND last_output.plan_session_id == <本对话编排会话>`，
   归属校验沿用 deep analysis 那套（`main_session__metadata__conversation_id`
   + 服务端权威字段交叉验证，参照 `callbacks.py:433-440` 的 WR-03 范式）。
   **绝不并进 `deep_sessions`**——混进去前端要二次判别两种语义，是给自己挖坑。
6. **日志出网前过 `redact_secrets_in_text`**（`_append_runtime_log` 写入时不脱敏，读取面必须补）。
7. **`repository_name` 由后端解析**（前端 `repoNames` 只覆盖当前用户可见仓，跨组仓会解析不出名字）。

**透传链（逐跳都要补）**：
`ConvergenceSessionEvent`（已有 `(session, ts)` 索引，正是时间线查询面）
→ `_emit_event` fan-out → `chat/views.py::_stream_events`（`:1440-1549`）→ SSE
→ `stores/chat.ts` 的 `switch (event.type)`（`:1530`）→ `OrchestrationStageTimeline`。
补齐链：`get_conversation_runtime`（`:2458` 旁路新增两个分支）→ `applyRuntimeSnapshot`（`:849-890`）
→ 同一个 store 状态 → 同一个组件。**两条链写同一份 store 状态，组件不区分来源**（§交互契约 E）。

---

## Design System

| Property | Value |
|----------|-------|
| Tool | **shadcn-vue（已初始化）**——`web/components.json` 存在（`style: new-york` / `baseColor: slate` / `cssVariables: true`）。本 phase **不跑 `shadcn init`、不从任何 registry 拉块**，仅复用 `web/src/components/ui/` 下已手工维护的组件 |
| Preset | not applicable（无 preset 串；样式走 `src/styles/main.css` 的 CSS variables） |
| Component library | reka-ui（经本仓 `ui/` 封装：本 phase 只用到 `Badge`，**零新增依赖**） |
| Icon library | Iconify `icon-[lucide--*]`（既有惯例）；只用仓内已出现的图标名 |
| Font | 继承全局；仓库名沿用 `font-mono`？→ **否**，`DeepAnalysisCard` 头部标题是普通字体（`:154-163`），调研卡按仓命名沿用其既有样式，不额外加 mono |

---

## Spacing Scale

沿用 `SubStepTimeline` / `OrchestratedPlanCard` / `DeepAnalysisCard` 既有间距，增量**不引入任何新值**：

| Token | Value | Usage |
|-------|-------|-------|
| xs | 4px（`gap-1` / `pt-1` / `mt-1`） | 状态点与标签的基线微调（既有 `SubStepTimeline:49`）、卡片操作区上内边距 |
| sm | 8px（`gap-2` / `mt-2` / `space-y-2`） | 步骤行内图标与文字间距（既有 `:39`）、时间线卡与上方 tool pill 的间距、调研卡之间的纵向间距 |
| md | 12px（`px-3` / `py-3` / `pb-3`） | 时间线卡头部纵向内边距（沿用 `OrchestratedPlanCard:109`）、日志组标题内边距 |
| lg | 16px（`px-4`） | 时间线卡横向内边距（沿用 `OrchestratedPlanCard:109/117`） |

**Exceptions（既有半步/微值，本 phase 沿用不新增）**：`px-1 py-0.5`（步骤行内边距，`SubStepTimeline:39`）、
`pl-1`（时间线左内边距，`:30`）、`w-2.5 h-2.5`（状态点尺寸，`:49`）、`left-[7px] top-4`（连线定位，`:45`）、
`mt-0.5`（2px 图标基线微调）。五者均已存在于被复用的组件中，复用比引入新的 4 倍数值更一致。[默认决策，沿用 107/109-UI-SPEC 同款裁定]

---

## Typography

沿用既有层次，**不新增字号字重**：

| Role | Size | Weight | 用途 |
|------|------|--------|------|
| Card title | 14px（`text-sm`） | 600（`font-semibold`） | 时间线卡头部标题（沿用 `OrchestratedPlanCard:111`） |
| Step label | 11px（`text-[11px]` + `leading-tight`） | 400 | 六个阶段标签（既有 `SubStepTimeline:55`） |
| Step summary | 10px（`text-[10px]`） | 400 | 每阶段一句摘要 / 失败原因行（既有 `:63`，本 phase 把它从"仅失败时"扩为"每步可选"） |
| Group label | 11px（`text-[11px]`） | 600（`font-semibold`） | 调研日志组标题（沿用 `DeepAnalysisGroup.vue:165-172` 的 `dag-bar-title` 层级） |
| Caption | 12px（`text-xs`） | 400 | 时间线折叠态说明行（沿用 `OrchestratedPlanCard:118`） |

**Exceptions（既有微字号，沿用不新增）**：`text-[11px]` / `text-[10px]` / `text-[9px]` 三档均已在
`ChatMessageBubble` 与 `SubStepTimeline` 中使用。**折叠头的步数计数不用 `Badge`**——Badge 的
垂直尺寸在 11px 行里过重，沿用 `DeepAnalysisCard:56` 的 `{n} 步` 纯文本计数惯例。[默认决策]

---

## Color

**零新色板**——全部走既有语义 token 与 `SubStepTimeline` 已有的状态点色：

| Role | Value | Usage |
|------|-------|-------|
| Dominant (60%) | `.card`（白底 `rounded-2xl` `shadow-card` `border-border/50`） | 时间线卡与 `OrchestratedPlanCard` 共享同一张卡底，**不给在途态另设底色** |
| Secondary (30%) | `text-muted-foreground` / `border-border/50` | 阶段标签、摘要行、卡片分隔线（既有） |
| Accent (10%) | `text-primary` | 卡头 `icon-[lucide--workflow]`（DESIGN.md：所有卡片图标统一 primary）、**active 状态点** `bg-primary animate-pulse`（既有 `SubStepTimeline:22`） |
| 状态点 · pending | `bg-muted-foreground/50`（既有 `:20`） | 未开始 |
| 状态点 · active | `bg-primary animate-pulse`（既有 `:21`） | 进行中 |
| 状态点 · complete | `bg-emerald-400`（既有 `:22`） | 已完成 |
| 状态点 · failed | `bg-red-400`（既有 `:23`） | 失败 |
| 状态点 · skipped / unknown | `bg-transparent border border-muted-foreground/50`（**同色 token，改用边框**） | 跳过 / 进度未知。**空心 vs 实心是形状差异**，同时满足「不靠颜色单独传达状态」[默认决策] |
| 失败文字 | `text-red-400` / 摘要 `text-red-400/70`（既有 `:56` / `:63`） | 失败阶段标签与原因行 |
| 降级角标 | `Badge variant="warning"` | **仅「路由」这一步**，纯 variant、无 `:class` 追加颜色 |
| 调研卡运行态 | `da-card--running`（`DeepAnalysisCard:115-118` 既有 teal 边框） | 容器运行中，**零改动** |

**Accent reserved for**：卡头图标、active 状态点、`Badge variant="warning"` 降级角标。

**禁止（DESIGN.md 显式禁令，本 phase 必守）**：
- ❌ **不给时间线卡换配色**（彩虹卡片禁令）——它与 `OrchestratedPlanCard` 同族同色。
- ❌ **不在 Badge 上用 `:class` 追加颜色**。
- ❌ 不用 shadcn `<Card>` 包裹（用 `.card` CSS 类）。
- ⚠️ `SubStepTimeline` 的 `stepStatusColor` 是一个组件内局部状态色 map，形式上违反
  DESIGN.md「禁止在组件内部定义 `statusColors` / `statusMap`」。**本 phase 不把它迁去
  `~/config/status.ts`**（那份配置服务于 `StatusBadge` 的 5 个 `type`，塞一个时间线专用的
  点色 map 进去反而是更差的耦合），但**新增的 `skipped`/`unknown` 分支必须并入既有那个 map，
  不得在 chat 侧再起第二份**。记入 Unresolved。[默认决策]

---

## 交互契约

### A. 在途阶段时间线（OBS-01 / OBS-03）

#### A.1 六个用户面标签 + 一个可选步

阶段粒度取 ROADMAP SC-1 的原文措辞，**不另造词**（CONTEXT 既定）：

| # | stage key | 用户面标签 | 是否恒显示 |
|---|-----------|-----------|-----------|
| 1 | `decompose` | `拆分` | 是 |
| 2 | `route` | `路由` | 是 |
| 3 | `recall` | `召回` | 是 |
| — | `classify` | `功能点分类` | **可选步**，见下 |
| 4 | `clarify` | `澄清` | 是 |
| 5 | `research` | `并行调研` | 是 |
| 6 | `merge` | `融合` | 是 |

🔴 **`classify` 的可选规则（非 feature_list 时整步不渲染，而不是渲染一个永远跳过的灰步）**：

```
showClassify =
     runtime.orchestration?.has_classify === true          // 权威：后端从 stage_state.decomposition.mode 派生
  || seenEvent('technical_plan.feature.classified')        // 兜底：领域事件只在 feature_list 流程产出
```

两条**或**关系，缺 runtime 时靠事件兜底。`has_classify === true` 时该步从**一开始**就出现在列表里
（用户一眼看到本次流程共几步，而不是跑到一半突然多出一行）；两条都不成立 ⇒ 列表恒为 6 行。
`classify` 步的标签**不在 ROADMAP 的六词之内，是本契约新增的第七个词**——因为它是
feature_list 专属扩展点，六词表本就没覆盖它。[默认决策]

> 边缘情形：feature_list 流程但 `deps.classify` 未注入（`builtin_processes.py:208-210` 的
> pass-through）⇒ 有 `has_classify` 但无领域事件 ⇒ 该步走 `complete` + 摘要留空。
> **不标 `skipped`**——它确实穿过了，只是没产出内容。

#### A.2 时间线本体：`SubStepTimeline` 的加性泛化

**先说结论：`SubStepTimeline` 原样不能用，但它是正确的复用对象——需要 5 处纯加性改动。**
实读 `:10-12` 与 `types/execution.ts:110-120`，缺口是：
① 类型硬绑 `SubStep`（要求 `step_type` / `step_order` / `input_data` / `started_at` 等编排侧
根本没有的字段）；② `status` 只有 4 值，无 `skipped`；③ 摘要行只在 `failed` 时渲染，
且取值写死 `step.output_data.error` 并 `.slice(0,50)`；④ 每行 `cursor-pointer` + `hover` +
`@click` emit `stepClick`（编排阶段不可点）；⑤ 状态只由圆点颜色传达，无任何文本。

**改法（对既有唯一调用方 `ExecutionNode.vue:340` 零影响，因为全部新增项都是可选的）**：

```ts
// SubStepTimeline.vue —— item 类型与 execution 域解耦；SubStep 结构上天然满足它
export interface TimelineStepItem {
  id: string
  name: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped' | 'unknown'
  /** [新增] 该步的一句话摘要；缺省不渲染摘要行。 */
  summary?: string
  /** [新增] 行尾角标；缺省不渲染。纯 variant，禁止 :class 追加颜色。 */
  badge?: { text: string, variant: 'warning' | 'info' | 'muted' }
  /** 既有：failed 时的错误摘要来源，保留以兼容 ExecutionNode。 */
  output_data?: Record<string, any>
}

defineProps<{
  steps: TimelineStepItem[]
  /** [新增] 是否可点击。默认 true = 今日行为逐字不变；chat 侧传 false。 */
  interactive?: boolean
  /** [新增] 每个状态的中文文本（供 sr-only 与 title），缺省用内置默认。 */
  statusText?: Partial<Record<TimelineStepItem['status'], string>>
}>()
```

- **状态映射**：chat 侧把 `active → 'running'`、`complete → 'completed'` 传下去，
  复用既有 4 个色值；`skipped` / `unknown` 走新增的空心点分支（§Color）。
- **摘要行**：`step.summary` 存在即渲染（`text-[10px] text-muted-foreground`）；
  `failed` 时优先渲染 `summary`，`summary` 缺失才回退既有 `output_data.error.slice(0,50)`
  路径 ⇒ `ExecutionNode` 行为逐字不变。
- **`interactive === false`**：去掉 `cursor-pointer` / `hover:bg-muted/30` / `@click`，
  不 emit `stepClick`，**行不进 tab 序**（本来就是 `div`，不加 `tabindex`）。

> 若 checker/planner 判定「改共享组件太侵入」，替代方案是在 `chat/` 下新建一个逐字复制
> 同一套 DOM 与类名的本地时间线组件，代价是标记重复。**两种做法都满足 CONTEXT 的
> 「不新增组件原语、复用同一视觉语言」**；本契约选前者，理由是上面 5 项全是通用时间线
> 关注点（摘要、跳过、只读、角标、可读状态），不是 chat 专属逻辑。记入 Unresolved。[默认决策]

#### A.3 单步状态机（六态）

| 状态 | 触发条件（折叠事件流 + `current_stage` 指针） | 视觉 |
|------|--------------------------------------------|------|
| `pending` | 该步序号 > 当前阶段序号 | 灰实心点 + `text-muted-foreground` |
| `active` | 该步 === 当前阶段，且 session 未终态 | 主色脉冲点 |
| `complete` | 该步序号 < 当前阶段序号，或 session 已 `done` | 绿点 |
| `failed` | `failure.stage` 命中该步（或 session `failed` 且 `current_stage` 命中） | 红点 + `text-red-400` 标签 + 红色摘要行 |
| `skipped` | 该步被穿过且**明确无内容产出**（当前仅「澄清」一种，见下） | 空心灰点 + 摘要 `本次无需澄清` |
| `unknown` | 中断态（§交互契约 E.3） | 空心灰点 + 摘要 `进度未知，可能已中断` |

🔴 **阶段指针的权威顺序**：`runtime.orchestration.current_stage` **优先于**折叠事件流得到的指针。
理由见 §前端数据契约 后端要求 #3——事件截断只丢摘要，不能让指针退回去。两者冲突时以快照为准，
且**不打 warn、不报错**（正常的截断/时序场景，不是异常）。

「澄清」判 `skipped` 的精确规则：session 已推进过 `clarify`（当前阶段序号 > 澄清）**且**
本会话从未出现任何 `clarification.*` 事件 ⇒ `skipped`。出现过 `clarification.asked` ⇒ 走
`active`（等待中）/ `complete`（已答/已超时放行）。[默认决策]

#### A.4 每阶段一句摘要（结构化字段直出，不展示思维链）

**全部取 payload 里已有的结构化字段，不为此新增任何 LLM 调用。** 摘要恒为可选——
缺数据时该行整行不渲染（不是渲染一句「暂无」）。

| 阶段 | 摘要来源 | 文案模板 |
|------|---------|---------|
| 拆分 | `orchestration.segment_count`（快照；事件流拿不到） | `已拆出 {n} 个需求点` |
| 路由 | `repo.routing` payload `candidates.length` + `degraded` | `命中 {n} 个候选仓`；`degraded === true` 时**同一行尾追加 `Badge variant="warning"`「降级」角标**（不追加解释句，见 §D） |
| 召回 | `knowledge.recalling` payload `hits`（已是条数） | `召回 {n} 条相关知识` |
| 功能点分类 | `technical_plan.feature.classified` payload `summary:{new,modify,unclear}` | `新增 {new} · 改造 {modify}`；`unclear > 0` 时追加 ` · 待确认 {unclear}` |
| 澄清 | `clarification.*` 事件计数与类型 | 见下表 |
| 并行调研 | `repo.research.started/completed/failed` 按 `repo_id` 去重计数 | `{done}/{total} 个仓库完成`；有失败时追加 ` · {k} 个失败` |
| 融合 | `technical_plan.merge.started` 出现次数 = 轮次 | 第 1 轮进行中：`正在融合各仓方案`；第 n(≥2) 轮：`第 {n} 轮融合`；`merge.completed` 后：`方案已产出` |

澄清子表：

| 事件 | 摘要 |
|------|------|
| `clarification.asked`（第 n 次出现） | `等待你回答第 {n} 轮澄清` |
| `clarification.answered` | `第 {n} 轮澄清已回答` |
| `clarification.timed_out`（payload 有 `round_no`） | `第 {round_no} 轮澄清超时，已按假设继续` |
| `clarification.delivery_failed` | `澄清卡送达失败` |
| 无任何澄清事件而已推进 | `本次无需澄清`（状态 `skipped`） |

🔴 **绝不渲染的 payload 字段**（T-107-06 / T-107-02 同一条纪律，本 phase 逐字沿用）：
- `clarification.asked` 的 **`question`**（LLM 自由文本）；
- `repo.research.completed` 的 **`summary`**（容器产出的自由文本）与 `candidate_files` /
  `api_contracts_exposed`（结构化但属方案内容，不是进度）；
- `repo.research.failed` 的 **`error`**（上游异常文本）；
- `technical_plan.validation.failed` 的 **`reasons`**（校验 check 名，非受控）——**只计数不回显**；
- `repo.routing` 的 `stage0` / `stage1` / `weight_config` / `repo_meta`（排查材料）。

「并行调研」的仓库名解析顺序：`plan_research_sessions[].repository_name` →
`repoNames[repo_id]` → 常量 `未知仓库`。**任何情况下不回显裸 UUID**。[默认决策]

#### A.5 挂载位置与渲染条件

在 `ChatMessageBubble.vue` 的单例 tool 分支内，插在 `OrchestratedPlanCard` **之前**：

```
div.tool-inline
├─ div.tool-pill                              （既有，不动）
├─ <OrchestrationStageTimeline>               ← 新增（本 phase）
├─ <PlanResearchLogGroup>                     ← 新增（本 phase，见 §C）
└─ <OrchestratedPlanCard v-if="…">            （109-04，不动）
```

时间线的渲染条件（三条同时成立）：

| # | 条件 | 不成立时 |
|---|------|---------|
| 1 | `isOrchestrationTool(item.name)`（既有判定，`:776-779`，两个编排工具都覆盖） | 不渲染 |
| 2 | 能为该 tool item 绑到一个编排会话（§A.7） | 不渲染（回到今日现状：只有 tool pill） |
| 3 | 该会话至少有一条已知事实（事件 ≥ 1 或 runtime 快照存在） | 不渲染 |

⇒ **历史消息、无编排会话、老后端**：三条任一不成立即完全不渲染，**与今日逐像素一致，不抛错、不打 warn**。

#### A.6 卡片结构与终态收敛

```
.card mt-2 animate-fade-in                                   data-test="orchestration-stage-timeline"
├─ 头部 px-4 py-3 border-b border-border/50 flex items-center gap-2   ← 逐字沿用 OrchestratedPlanCard:109
│   ├─ span.icon-[lucide--workflow].text-primary
│   ├─ span.text-sm.font-semibold      标题（三态，见 §Copywriting）
│   ├─ span.text-[10px].text-muted-foreground.ml-auto   「{done}/{total} 步」
│   └─ button（折叠切换，原生 button）
│        └─ span.icon-[lucide--chevron-right]  展开时 rotate-90
├─ p.sr-only[role="status" aria-live="polite"]            ← 唯一 live region（§F）
└─ div v-if="!collapsed" 正文 px-4 pb-3 pt-1
    └─ <SubStepTimeline :steps="…" :interactive="false" />
```

**终态收敛规则（"收敛为一行"而不是"消失"）**：

| session 状态 | 时间线 | `OrchestratedPlanCard` |
|-------------|--------|----------------------|
| 进行中 / 等待澄清 / 等待事件 | 展开，active 步脉冲 | 不渲染（109 A.1 三条件不成立） |
| `done` | **自动折叠**为头部一行（标题 + `6/6 步`），全部绿点收进折叠区 | 渲染（若 109 的入口条件成立，见 §落点 F） |
| `failed` | **保持展开**，红步与原因行可见 | 不渲染 |

- 自动折叠只在 `done` **首次到达时触发一次**（`watch` + 一次性 flag）；用户手动展开后
  **不再被自动折叠回去**。[默认决策：进度是过程信息，完成后默认让位给结果，但用户想回看时不能被抢走]
- 🔴 **时间线自身的终态就是完成信号**：标题变为 `方案编排已完成`。这条不可省——
  §落点 F 已实测确认异步路径上 `OrchestratedPlanCard` 大概率不出现，若时间线在
  `done` 时直接消失，用户会看到「跑完了，然后什么都没有」。
- **不渲染任何后端自由文本**：标题、说明句全部取 `COPY` 常量，`placeholder` / `message` 不上屏
  （沿用 `OrchestratedPlanCard.vue:8-10` 的纪律）。

#### A.7 会话绑定（§落点 G 的落法）

前端不解析 tool result 拿 `session_id`（在途五个阶段里根本没有 result）。绑定顺序：

1. **store 的 `activeOrchestrationSessionId`**：`process_event` 到达时按 `session_id` 记为活跃；
   同一 run 内只可能有一个编排会话在跑。
2. **runtime 快照的 `orchestration.session_id`**：刷新/重连时的权威来源。
3. **tool result 里的 `session_id`**（挂起 marker 与终态 result 都带）：作为交叉校验；
   与 1/2 不一致时**以 tool result 为准**（它明确属于这个气泡）。

同一条消息里有多个编排 tool call（在途 + 终态）时，**它们绑定同一个 `session_id`，
时间线只渲染一次**——挂在**最后一个**编排 tool item 上，避免同一进度出现两遍。[默认决策]

---

### B. 失败呈现（OBS-03）

#### B.1 用户看到什么

失败阶段那一行：

```
● (红实心点)  融合                        ← text-red-400
              融合校验多次未通过           ← text-[10px] text-red-400/70，role="alert"
```

- **红点 + 红字 + 明确的中文原因**，位置就在它停下的那一步上——「停在哪一步」由时间线位置
  回答，「原因是什么」由这句闭集文案回答。
- 其后的步骤保持 `pending`（灰实心），**不标红、不标跳过**——它们确实没跑，不是失败。
- 时间线卡头部标题变为 `方案编排失败`，**不折叠**。

#### B.2 原因闭集（前端常量 map，7 值）

| `reason_code` | 中文文案 |
|---------------|---------|
| `stage_exception` | `该阶段执行出错` |
| `merge_validation_exhausted` | `融合校验多次未通过` |
| `clarification_timeout_no_answer` | `澄清超时且无人应答` |
| `advance_step_limit` | `流程推进步数超限` |
| `unknown_process_type` | `流程类型未注册` |
| `unknown_stage` | `阶段未注册` |
| 其余 / 缺失 | `未知原因` |

🔴 **未命中一律回退「未知原因」，绝不回显原始值**——与 107-UI-SPEC 的
`DEGRADE_REASON_LABELS` 同款裁定，且理由更强：这里的上游是异常分类，一旦后端出现
非受控值（异常类名、截断的上游 body），回显即泄漏面。[默认决策]

#### B.3 永远不显示的东西

| 字段 | 为什么不显示 |
|------|------------|
| `session.error.message`（`str(exc)` 原文） | 原始异常文本。CONTEXT 写的是「经脱敏后**才可**展示」——那是**上限，不是要求**。本契约**不花这笔额度**：不新增前端展开区，与 107-UI-SPEC Unresolved #4 同一条裁定（原始文本只入事件表 / `SystemLogEntry`，要看是 superuser 权限面，需要单独设计）。 |
| `session.error.exception`（异常类名） | 同上，且对用户零信息量 |
| `session.error.report`（融合校验报告） | 含 `errors[].message` 自由文本 |
| `technical_plan.validation.failed` 的 `reasons` | 校验 check 名，非受控；**只用于数轮次** |
| `repo.research.failed` 的 `error` | 上游/容器异常文本 |

**这不是"前端选择不渲染"，而是后端契约要求 #4 保证这些字段根本不出网**——渲染路径上不存在这个字符串。
双保险：Vue 插值天然转义，且本 phase 新增组件**零 `v-html`**。

#### B.4 单仓调研失败 ≠ 编排失败

`repo.research.failed` 只影响「并行调研」的摘要计数（` · {k} 个失败`），
**不把该步标红**——单仓失败被 `research_adapter.py:114-131` 显式隔离，其余仓继续，
编排照常推进到融合。只有 session 整体 `failed` 才有红步。[默认决策：把可恢复的单仓失败
标成红色会让用户以为整件事完了，这正是"时间线撒谎"]

---

### C. 调研容器日志（OBS-02）

#### C.1 形态：按仓一张卡，纵向堆叠

```
div.mt-2                                          data-test="plan-research-log-group"
├─ div.flex.items-center.gap-2.px-1.pb-2          组标题行
│   ├─ span.icon-[lucide--search-code].text-[11px].text-primary
│   └─ span.text-[11px].font-semibold             「方案调研 · {n} 个仓库」
└─ div.space-y-2
    └─ <DeepAnalysisCard v-for="repo in sessions"
          :session="…" :task-label="仓库名" :status="…" :default-expanded="…" />
```

- **每仓一张卡**（调研本就是 per-repo 容器），与用户对「并行调研」的心智一致。
- **不用 `DeepAnalysisGroup`**。理由是实读结论，不是偏好：
  ① 它的多项形态是**横向 swiper**（`:130-138`），一次只看得见一个仓——恰好把"并行"藏起来；
  ② 它的 bar 标题 `深度分析 · {n} 个子任务` 是**写死的**（`:87`），没有任何 prop 能改
  ⇒ CONTEXT 说的「仅换标签文案」在这个组件上**做不到**。
  若后续确实想要 swiper，正确做法是给 `DeepAnalysisGroup` 加一个 `title` prop（加性，
  默认值保持今日文案），而不是在 chat 侧接受一个说"深度分析"的容器。记入 Unresolved。[默认决策]
- **`DeepAnalysisCard` 零改动**：`taskLabel` 覆盖头部标题（`:40` 的
  `props.taskLabel || session.task_description || '执行记录'`）⇒ 传仓库名即可。

#### C.2 展开策略

| 场景 | `defaultExpanded` |
|------|------------------|
| 单仓 | `true`（与深度分析体验一致） |
| 多仓 | 仅**第一张**（按 `repo.research.started` 顺序）`true`，其余 `false` |

理由：`DeepAnalysisCard` 的日志区 `max-height: 22rem`（`:187`），5 个仓全展开会把整条对话顶飞。
`defaultExpanded` 是 mount 时读一次的 `ref`（`:19`），**不会**随状态变化重置——这正好是我们要的
（用户展开谁就是谁）。[默认决策]

#### C.3 与深度分析的区分（不让用户混淆两者）

| 维度 | 深度分析 | 方案调研（本 phase） |
|------|---------|---------------------|
| 组标题 | `深度分析 · {n} 个子任务`（`DeepAnalysisGroup:87`） | `方案调研 · {n} 个仓库` |
| 组图标 | `icon-[lucide--layers]` | `icon-[lucide--search-code]` |
| 卡片标题 | 子任务描述（自然语言） | **仓库名** |
| 排布 | 横向 swiper | 纵向堆叠 |
| 挂载位置 | `deep-analysis-group` 独立节点 | 编排 tool 气泡内，紧贴时间线之下 |

四条差异里有三条不靠文字（图标、标题语义、排布），**即使不读字也能看出这是两种东西**。

#### C.4 生命周期

- **出现时机**：第一条 `plan_research_sessions` 到达（即第一个调研容器被建起来）。
  ⇒ 与时间线的「并行调研」步进入 `active` 大致同时。
- **消失时机**：**不消失**。编排完成后日志组仍在（OBS-02 要的是"可查"，不只是"可见"），
  但整组默认收起（组标题行可点击折叠整组）。[默认决策]
- **空态**：`plan_research_sessions` 为空 ⇒ 整组不渲染（不占位、不写"暂无日志"）。
  单个仓有会话但 `logs` 为空 ⇒ 交给 `DeepAnalysisCard` 既有空态（`:64-66`
  的 `正在执行…` / `暂无执行记录`），**不另写文案**。

---

### D. 与 Phase 107 的边界（裁决 D-3：同一事实只有一个渲染者）

#### D.1 本 phase **不渲染**的东西

| 事实 | 归属 | 本 phase 的行为 |
|------|------|---------------|
| 降级横幅「本次未经 LLM 推理，置信度仅供参考」 | `RoutingDecisionPanel`（107-UI-SPEC §C） | **不渲染** |
| 降级原因中文句（`DEGRADE_REASON_LABELS` 6 值） | 同上 | **不渲染** |
| confidence 徽标灰化（`variant="muted"`） | 同上 | **不渲染**（时间线上根本没有候选列表） |
| 折叠态降级徽标 | 同上 | **不渲染** |
| 候选仓列表 / 分数 / 分数分解 / 跨组标注 / 置顶提示 | 同上（107 §A/§B） | **不渲染** |
| 澄清卡本身（问题与选项） | 既有 plan 澄清卡（`pending_plan_clarification` 驱动） | **不渲染**，时间线只说"等待你回答第 n 轮澄清" |
| 方案正文 / 影响文件 / 进入编码按钮 | `OrchestratedPlanCard` + `TechPlanCard`（109） | **不渲染** |

#### D.2 本 phase **只**渲染的那一个降级信号

「路由」这一步的行尾一个 `Badge variant="warning"`，文案 **`降级`**，取值来源
`repo.routing` payload 的 `degraded` 布尔（后端算好的事实，**前端绝不按 `router_version`
或候选内容自行推断**；字段缺失 ⇒ 视为 `false`，零角标）。

角标**不带解释句、不带 Tooltip、不带原因**——它只回答「这一步走了降级路径」，
「降级意味着什么」由 107 的面板回答。这就是 D-3「同一事实只有一个渲染者」的落法：
**事实的完整解释在一处，另一处只做一个不可误读的位置标记。**

#### D.3 🔴 必须上报的事实：`RoutingDecisionPanel` 今天在 SPA 里没有挂载点

实读核验（worktree，107 的 9 个 plan 全部 `[x]`）：

```
rg -i "RoutingDecisionPanel|routing-decision-panel" web/src --glob '*.vue'
  → 只命中组件自身的注释与 RelevanceBadge 的注释，**零个 <RoutingDecisionPanel /> 使用点**
rg -l "useRoutingStore" web/src --glob '*.vue'
  → RoutingDecisionPanel.vue、RelevanceBadge.vue（两者互为孤岛）
```

`stores/chat.ts:1301/1330` 确实在 `upsertTrace` 写 trace，但**没有任何页面/组件把面板挂出来**。

**后果与本 phase 的处置**：
- 对 SC-4（「同一状态不存在两处各自实现」）：**成立**——本 phase 的角标不是第二个实现。
- 对用户可见性：编排链路上，用户今天看不到降级横幅（107-UI-SPEC Unresolved #3 已记录
  「编排链路由结果的前端呈现在 web 端仍零引用」，本次核验发现**chat 链也一样没挂**）。
  ⇒ 落地后「降级」角标事实上会是编排链**唯一**的降级信号。
- **本 phase 不去挂 107 的面板**（超出边界，且挂载位置/数据源是 107 的设计决策）。
  记入 Unresolved，交 planner 判定是补 107 的收尾还是开后续项。**这条不解决不影响
  Phase 110 的四条 SC，但影响 RELY-03 在用户侧是否真的成立——必须在 VERIFICATION 里如实记录。**

---

### E. 刷新 / 重连 / 中断

#### E.1 补齐机制

刷新后 SSE 内存态全丢（与 `streaming_snapshot` 同源问题）。补齐走**既有的 runtime 轮询**
（`chat.ts:1043-1077`，2s 间隔，深度分析日志走的就是这条），`applyRuntimeSnapshot`
（`:849-890`）把 `runtime.orchestration` 与 `runtime.plan_research_sessions`
写进**与 SSE 完全相同的那份 store 状态**。

🔴 **组件不知道数据从哪条链来，也不该知道**——两条链写同一个 store 形状是本设计的核心不变量。
任何「if 来自 SSE 则…」的分支都是这条不变量被破坏的信号。

#### E.2 直播态 vs 补齐态的视觉差异：**没有**

**刷新后的时间线与刷新前逐像素一致**，不加「已恢复」徽标、不加时间戳、不加任何提示。

理由：这类标记讲的是我们的传输机制，不是用户的任务状态；用户刷新页面时想确认的是
「我的编排还在跑吗」，而不是「你是怎么知道的」。加一个恢复徽标只会让刷新看起来像降级。[默认决策]

**唯一由状态（而非传输）驱动的差异**：active 步的脉冲动画只在
`orchestration.status ∈ {running, waiting_clarification, waiting_event}` 时开启。
会话已终态时不脉冲——因为它确实不在动。

#### E.3 中断 / 未知态

| 判定 | 表现 |
|------|------|
| `runtime.active === false` **且** `orchestration.status ∈ {running, waiting_event}` | 当前步转 `unknown`：空心灰点 + 摘要 `进度未知，可能已中断`；后续步保持 `pending`；卡头标题保持在途文案但**停止脉冲**；不自动折叠 |
| `orchestration.status === 'waiting_clarification'` 且 `runtime.active === false` | **不算中断**——这是合法的等待用户，澄清步保持 `active`（不脉冲），摘要照常 `等待你回答第 {n} 轮澄清` |
| 有在途编排 tool item 但 `runtime.orchestration` 缺失（老会话 / 服务重启前的历史消息） | **整个时间线不渲染**（§A.5 条件 2 不成立），回到今日现状。**不渲染一个全 `unknown` 的空壳**——那是在告诉用户"我们丢了东西"，而实际上这条消息本来就从没有过进度信息 |

`unknown` 与 `skipped` 共用空心灰点（§Color），靠摘要文案区分。两者都不是错误态，
**都不用红色**——把"不知道"画成"失败"是撒谎。[默认决策]

#### E.4 事件重复与乱序

- **重复**：SSE 补发 + 快照补齐必然产生重复事件。折叠算法必须**幂等**：
  按 `(event, ts, payload.repo_id ?? payload.task_id ?? '')` 去重；计数类摘要
  （调研完成数、融合轮次、澄清轮次）**按去重后的集合算**，不是按到达次数累加。
- **乱序**：快照 `events` 已按 `(ts, created_at)` 升序；SSE 到达顺序即产生顺序。
  混合时按 `ts` 归并。阶段指针不依赖顺序（取 `current_stage`），所以乱序最多影响摘要瞬时值。

---

### F. 可访问性

| 项 | 契约 |
|----|------|
| **不靠颜色单独传达状态** | ① 空心 vs 实心是形状差异；② 每个步骤行带 `title` 与 `sr-only` 状态文本（`未开始` / `进行中` / `已完成` / `失败` / `已跳过` / `进度未知`）；③ 失败额外有红色**文字**摘要，不是只有红点 |
| **单一 live region** | 卡内**唯一**一处 `<p class="sr-only" role="status" aria-live="polite">`，内容为 `当前阶段：{标签}` / 终态时 `方案编排已完成` / 失败时 `编排失败：{标签} — {原因}`。🔴 **只在「活跃阶段 key 或 session 状态」变化时更新**——**绝不**把调研的 `{done}/{total}` 计数写进去，否则五个仓完成会连播五次 |
| **失败行用 `role="alert"`，不加 `aria-live`** | 沿用 109-UI-SPEC §B.2 的裁定：补齐场景下失败行随卡片首次渲染出现（非动态插入），`aria-live` 不产生播报价值反而可能重复朗读；直播场景下该失败已由上面那个 polite live region 播报过一次。**一个事实播一次** |
| **步骤行不是交互元素** | `interactive={false}` ⇒ 无 `@click`、无 `cursor-pointer`、不进 tab 序。时间线里**唯一**的 tab stop 是折叠切换 `button` |
| **焦点行为** | ① 终态自动折叠时**不移动焦点**、不 autofocus；若用户焦点正在折叠按钮上，折叠后焦点**留在原按钮**（按钮不被卸载，只换 `aria-expanded`）；② 折叠按钮带 `aria-expanded` 与 `aria-controls`；③ 新出现的调研日志卡**不抢焦点** |
| **容器语义** | 时间线卡 `role="group"` + `aria-label="方案编排进度"`；`SubStepTimeline` 的外层加 `role="list"`、每行 `role="listitem"`（加性，`ExecutionNode` 侧同样受益） |
| **动效** | active 脉冲用既有 `animate-pulse`；`DeepAnalysisGroup` 已有 `prefers-reduced-motion` 先例（`:309-313`），新增卡片**不引入新的自定义动画**，只用 `animate-fade-in` 与 `animate-pulse` |
| **无 `v-html`** | 所有新文案走 `{{ }}` 插值。本 phase 新增组件**零 `v-html`** |

---

## Copywriting Contract

沿用本组件家族硬编码中文常量惯例（`OrchestratedPlanCard.vue:35-45` 的 `COPY` 对象、
`TOOL_LABELS`、`SIGNAL_LABELS` 先例），**不引入 vue-i18n key**。

> 📌 与「项目级 i18n 约定（vue-i18n / 默认 zh-CN）」的偏差是**有意且有据**的：实读
> `web/src/components/chat/*.vue` 只有 `ClarificationCard.vue` 一个文件用了 i18n，
> 家族其余全部硬编码中文；107 与 109 两份 UI-SPEC 均已就同一问题作出同样裁定。
> 与既有组件一致优先于全局约定；家族整体迁移属技术债，记入 Unresolved。[默认决策]

### 时间线（`OrchestrationStageTimeline` 的 `COPY` 常量）

| Element | Copy |
|---------|------|
| 卡头标题 · 在途 | `正在生成技术方案` |
| 卡头标题 · 完成 | `方案编排已完成` |
| 卡头标题 · 失败 | `方案编排失败` |
| 卡头步数计数 | `{done}/{total} 步` |
| 折叠按钮 `aria-label` · 收起态 | `展开编排进度` |
| 折叠按钮 `aria-label` · 展开态 | `收起编排进度` |
| 容器 `aria-label` | `方案编排进度` |
| 阶段标签 | `拆分` / `路由` / `召回` / `功能点分类` / `澄清` / `并行调研` / `融合` |
| 状态文本（`sr-only` + `title`） | `未开始` / `进行中` / `已完成` / `失败` / `已跳过` / `进度未知` |
| Live region · 在途 | `当前阶段：{标签}` |
| Live region · 完成 | `方案编排已完成` |
| Live region · 失败 | `编排失败：{标签} — {原因}` |
| 摘要 · 拆分 | `已拆出 {n} 个需求点` |
| 摘要 · 路由 | `命中 {n} 个候选仓` |
| 摘要 · 召回 | `召回 {n} 条相关知识` |
| 摘要 · 功能点分类 | `新增 {new} · 改造 {modify}`（`unclear > 0` 时追加 ` · 待确认 {unclear}`） |
| 摘要 · 澄清（等待） | `等待你回答第 {n} 轮澄清` |
| 摘要 · 澄清（已答） | `第 {n} 轮澄清已回答` |
| 摘要 · 澄清（超时放行） | `第 {n} 轮澄清超时，已按假设继续` |
| 摘要 · 澄清（送达失败） | `澄清卡送达失败` |
| 摘要 · 澄清（未触发） | `本次无需澄清` |
| 摘要 · 并行调研 | `{done}/{total} 个仓库完成`（有失败时追加 ` · {k} 个失败`） |
| 摘要 · 融合（第 1 轮） | `正在融合各仓方案` |
| 摘要 · 融合（第 n≥2 轮） | `第 {n} 轮融合` |
| 摘要 · 融合（完成） | `方案已产出` |
| 摘要 · 中断 | `进度未知，可能已中断` |
| 降级角标 | `降级` |
| 失败原因 · `stage_exception` | `该阶段执行出错` |
| 失败原因 · `merge_validation_exhausted` | `融合校验多次未通过` |
| 失败原因 · `clarification_timeout_no_answer` | `澄清超时且无人应答` |
| 失败原因 · `advance_step_limit` | `流程推进步数超限` |
| 失败原因 · `unknown_process_type` | `流程类型未注册` |
| 失败原因 · `unknown_stage` | `阶段未注册` |
| 失败原因 · 未命中 / 缺失 | `未知原因` |
| 仓库名兜底 | `未知仓库` |
| **Primary CTA** | **不适用**——时间线是纯展示面，唯一可点的是折叠切换。进入编码的 CTA 归 `OrchestratedPlanCard`（109 §Copywriting 的 `进入编码`），本 phase 不新增任何提交类操作 |
| **Empty state** | 三条渲染条件任一不成立 ⇒ **整块不渲染**，无空态占位文案（沿用 107「面板已足够密集，空态文案是噪音」的裁定）。单步无摘要 ⇒ 摘要行不渲染，不写"暂无" |
| **Error state** | 编排失败 = 红步 + 闭集原因行（上表），**不弹 toast**（失败信息属于这条消息的上下文，不该飘走）。前端自身的解析失败（payload 形状意外）⇒ 该步摘要不渲染，**不抛错、不打 warn** |
| **Destructive** | **本 phase 无破坏性操作**，无确认弹层、无 destructive 配色 |

### 调研日志组（`PlanResearchLogGroup` 的 `COPY` 常量）

| Element | Copy |
|---------|------|
| 组标题 | `方案调研 · {n} 个仓库` |
| 组折叠 `aria-label` · 收起态 | `展开方案调研日志` |
| 组折叠 `aria-label` · 展开态 | `收起方案调研日志` |
| 每卡标题 | 仓库名（`repository_name` → `repoNames[id]` → `未知仓库`） |
| 卡内空态 / 步数 | **沿用 `DeepAnalysisCard` 既有文案**（`{n} 步` / `正在执行…` / `暂无执行记录`），不改、不覆写 |

---

## Registry Safety

| Registry | Blocks Used | Safety Gate |
|----------|-------------|-------------|
| 无（不从 shadcn 官方 registry 或任何第三方 registry 拉块） | 仅复用本仓既有手工维护组件：`ui/badge`；以及既有业务组件 `SubStepTimeline` / `DeepAnalysisCard` | not applicable — 零第三方引入、零新依赖、不执行 `shadcn add` / `shadcn init`（2026-07-31 确认；`web/pnpm-lock.yaml` 不变） |

> `web/components.json` 存在（109-UI-SPEC 已更正 107 的记述），但本 phase **不触发任何
> registry 拉取动作**，故无需 `shadcn view` 审源门。

---

## UI Considerations

### Covered（本契约已覆盖，可直接提升为 must_haves）

1. **在途阶段时间线（OBS-01/03）**：编排 tool 气泡内 `.card`，头部逐字沿用 `OrchestratedPlanCard:109`
   的骨架与 `icon-[lucide--workflow]`，正文为竖向六步（+ 可选「功能点分类」第七步）时间线。
2. **六个用户面标签取 ROADMAP SC-1 原文**（`拆分/路由/召回/澄清/并行调研/融合`），不另造词；
   `classify` 为**可选步**，`has_classify` 或 `technical_plan.feature.classified` 事件成立才出现，
   否则**整步不渲染**（不是灰步）。第七个标签 `功能点分类` 是本契约新增（六词表未覆盖它）。
3. **单步六态** `pending/active/complete/failed/skipped/unknown`，复用 `SubStepTimeline` 既有四色，
   `skipped`/`unknown` 用**空心灰点**（同色 token、形状差异，同时满足 a11y 不靠颜色）。
4. 🔴 **阶段指针以 `runtime.orchestration.current_stage` 为权威**，折叠事件流只用于算摘要；
   两者冲突以快照为准，不打 warn（事件截断是正常场景）。
5. **每阶段一句结构化摘要**（拆分/路由/召回/分类/澄清/调研/融合七套模板，见 §A.4），
   全部取 payload 已有结构化字段，**不新增 LLM 调用**；缺数据时摘要行整行不渲染。
6. 🔴 **payload 自由文本一律不上屏**：`clarification.asked.question`、
   `repo.research.completed.summary` / `candidate_files`、`repo.research.failed.error`、
   `technical_plan.validation.failed.reasons`（只计数）、`repo.routing` 的 stage0/stage1/weight_config。
7. **失败呈现（OBS-03）**：失败步红点 + 红标签 + `role="alert"` 的闭集原因行；后续步保持
   `pending` 不标红；卡头标题变 `方案编排失败` 且不折叠。
8. 🔴 **失败原因闭集 7 值 + 未命中回退「未知原因」，绝不回显原始值**；
   `error.message` / `error.exception` / `error.report` **由后端保证不出网**（契约要求 #4）。
9. **单仓调研失败 ≠ 编排失败**：只进「并行调研」摘要的失败计数，不把该步标红。
10. **调研容器日志（OBS-02）**：`plan_research_sessions` 按仓一张 `DeepAnalysisCard`（零改动），
    纵向堆叠；单仓默认展开、多仓仅首张展开；组标题 `方案调研 · {n} 个仓库` + `icon-[lucide--search-code]`。
11. **不使用 `DeepAnalysisGroup`**：其 swiper 会把"并行"藏起来，且 bar 标题
    `深度分析 · {n} 个子任务` 写死无 prop ⇒ CONTEXT 的「仅换标签文案」在该组件上做不到。
12. **与 107 的边界（D-3）**：本 phase **不渲染**降级横幅 / 降级原因句 / confidence 灰化 /
    折叠态降级徽标 / 候选列表 / 澄清卡 / 方案正文；**只**在「路由」步渲染一个
    `Badge variant="warning"`「降级」角标（无解释句、无 Tooltip），取值来自 `degraded` 布尔，
    **前端绝不自行推断降级**，字段缺失视为 `false`。
13. **刷新补齐（SC-1 的隐含要求）**：走既有 runtime 轮询写**同一份 store 状态**；
    直播态与补齐态**视觉零差异**（不加"已恢复"标记）；唯一状态驱动差异是终态不脉冲。
14. **中断态**：`runtime.active === false` 且 `status ∈ {running, waiting_event}` ⇒ 当前步转
    `unknown` + `进度未知，可能已中断`；`waiting_clarification` **不算中断**；
    `orchestration` 完全缺失 ⇒ 整块不渲染（不渲染全 `unknown` 空壳）。
15. **事件折叠幂等**：按 `(event, ts, repo_id/task_id)` 去重；计数类摘要按去重集合算，
    不按到达次数累加（SSE + 快照必然重复）。
16. **终态收敛**：`done` 时时间线**自动折叠为一行**（一次性，用户手动展开后不再自动折叠），
    卡头标题变 `方案编排已完成`；`failed` 时保持展开。🔴 **时间线自身的终态就是完成信号，
    不依赖 `OrchestratedPlanCard` 出现**。
17. 🔴 **`orchestratedPlanData` 的 `.find` 加固为「末位终态匹配」**（`ChatMessageBubble.vue:792`）：
    异步路径下 `__blocking_task__` 那条 tool call 恒在最前，`.find` 命中它即 `return null`
    ⇒ 卡片永不渲染。一行改动，避免 110 落地后被误判为回归。
18. **`SubStepTimeline` 纯加性泛化**（5 项：item 类型解耦 / `skipped`+`unknown` / 可选 `summary` /
    可选 `badge` / `interactive` 开关 + `role=list` 语义）。全部可选 ⇒
    `ExecutionNode.vue:340` 行为逐字不变；`failed` 时 `summary` 缺失仍回退既有
    `output_data.error.slice(0,50)` 路径。
19. **可访问性**：唯一一处 `sr-only role="status" aria-live="polite"`，只在活跃阶段/状态变化时更新
    （**绝不写入调研计数**）；失败行 `role="alert"` **不加** `aria-live`（一个事实播一次）；
    步骤行非交互不进 tab 序；自动折叠不移动焦点；折叠按钮带 `aria-expanded` / `aria-controls`。
20. **前端数据契约**：新增 `ProcessEventEnvelope` / `OrchestrationRuntime` / `PlanResearchSession`
    三个类型，`ConversationRuntime` 扩 `orchestration?` / `plan_research_sessions?` 两个可选字段；
    `OrchestrationFailReason` 故意含 `| string` 让未知取值走保守分支而非编译失败。
21. **后端契约要求（planner 必须落进后端 task）**：① 新增 SSE type `process_event` 承载
    `build_envelope()` 原样信封；② fan-out 挂 `_emit_event` 的 `_persist_event` 之后、
    `conversation_id` 为空静默跳过、best-effort；③ 快照 `events` 有上界且**保留最新** N 条
    + `events_truncated`；④ `failure.reason_code` 服务端压闭集、原始文本不出网；
    ⑤ `plan_research_sessions` 独立分支独立字段、不混进 `deep_sessions`、归属校验沿用既有范式；
    ⑥ 日志出网前 `redact_secrets_in_text`；⑦ `repository_name` 后端解析。
22. **视觉零漂移**：不新增颜色 / 字号 / 字重 / 间距值 / `ui/` 组件 / npm 依赖；
    遵守 DESIGN.md 彩虹卡片禁令、Badge `:class` 禁令、`<Card>` 禁令；
    时间线卡与 `OrchestratedPlanCard` 同族同色，让"在途 → 完成"看起来是同一张卡在变。

### Backstop（兜底行为，executor 必须实现但无需显式设计）

1. **历史消息零报错**：无 `orchestration` / `plan_research_sessions` 的 runtime 与老消息 ⇒
   时间线与日志组均不渲染，其余渲染与今日**逐像素一致**，不抛错、不打 warn。
2. **payload 形状意外**：任何字段缺失 / 类型不符（`candidates` 不是数组、`hits` 不是数字等）⇒
   该条摘要不渲染，其余步骤照常。**纯字面读取，不对 `undefined` 做属性访问**。
3. **未知事件名**：`event` 出现在 taxonomy 之外（后端加了新事件而前端未同步）⇒
   **静默忽略**，不影响阶段指针（指针取 `current_stage`），不打 warn、不显示"未知事件"。
4. **`current_stage` 为未知 key**：不匹配 7 个 stage key 之一 ⇒ 全部步骤保持折叠事件流推出的
   状态，不崩、不清空时间线。
5. **`events_truncated === true`**：不给用户任何提示（截断是我们的实现细节，不是他的问题）；
   摘要以能算出的为准，算不出就不渲染那一行。
6. **多个编排会话**：一条消息只绑一个 `session_id`（§A.7），时间线只渲染一次；
   同一对话内先后两次编排 ⇒ runtime 只带**最近一次**，历史那条的时间线随消息保留其
   已折叠的终态（store 按 `session_id` 分桶，不互相覆盖）。
7. **`repo_id` 解析不出仓库名**：回退 `未知仓库`，**绝不回显裸 UUID**。
8. **调研会话数与路由候选数不一致**：`{done}/{total}` 的 `total` 取
   `repo.research.started` 的去重 `repo_id` 数（实际派了几个容器），**不取路由候选数**
   （light path 的仓不起容器，用候选数当分母会让进度永远到不了满）。
9. **零 `v-html`**：新增组件全部走 `{{ }}` 插值。
10. **状态不持久化**：折叠态 / 展开态均为组件本地 `ref`；`session_id` 变化后重算默认态
    （与 `expandedBreakdowns` / `expandedTools` 的既有惯例一致），不写 store、不入 localStorage。
11. **观测代码不反噬**：前端侧任何进度解析异常都吞掉（`try/catch` 或纯防御性读取），
    **绝不影响对话正文与工具气泡的渲染**——编排跑通比进度可见重要得多（CONTEXT 既定）。
12. **测试扩充**：
    - `web/src/components/chat/__tests__/OrchestrationStageTimeline.spec.ts`（**新**）：
      六步默认渲染；`has_classify=true` → 七步且第四行是「功能点分类」；`has_classify=false`
      且无分类事件 → **DOM 里不存在**该行（而非存在且置灰）；七套摘要模板各一条；
      `degraded=true` → 路由行有 `warning` Badge 且**全文不含**「未经 LLM 推理」；
      `failed` → 红步 + 7 个 `reason_code` 文案 + 未知 code 回退「未知原因」且不含原始值；
      单仓 `repo.research.failed` → 调研步**不**标红、摘要含「1 个失败」；
      `done` → 自动折叠一次且用户展开后不再自动折叠；
      中断态 → `unknown` 步 + 文案；`waiting_clarification` + `active=false` → **不**判中断；
      事件重复投递两次 → 计数不翻倍；`events_truncated` → 指针仍取 `current_stage`；
      live region 只有一处且不含 `{done}/{total}`；步骤行无 `@click`、失败行
      `role="alert"` 且 `aria-live` 为 `undefined`。
    - `web/src/components/chat/__tests__/PlanResearchLogGroup.spec.ts`（**新**）：
      每仓一张卡且标题为仓库名；`repository_name` 缺失 → 走 `repoNames` → 再兜底「未知仓库」
      且**不含 UUID**；单仓展开 / 多仓仅首张展开；空数组 → 整组不渲染；
      组标题含「方案调研」且**不含**「深度分析」。
    - `web/src/components/execution/dag/__tests__/SubStepTimeline.spec.ts`（**新或加用例**）：
      `ExecutionNode` 既有用法零回归（4 状态 + `output_data.error` 摘要 + `stepClick` 仍 emit）；
      `interactive=false` → 无 `cursor-pointer`、不 emit；`skipped`/`unknown` → 空心点；
      `summary` 存在时优先于 `output_data.error`。
    - `web/src/stores/__tests__/chat.*.spec.ts`（**加用例**）：`process_event` 分发进
      `orchestration` 分桶；`applyRuntimeSnapshot` 与 SSE 写同一份状态且互不覆盖丢字段；
      未知 `event` 名静默忽略。
    - `web/src/components/chat/__tests__/chatMessageBubble.parts.spec.ts`（**加用例**）：
      在途编排 tool item 下渲染时间线且**不**渲染 `OrchestratedPlanCard`；
      同一消息含「`__blocking_task__` 在前 + 终态在后」两条编排 tool call →
      `orchestratedPlanData` 命中**终态那条**（`.find` 加固的回归锁）。
    - 后端：fan-out 在 `conversation_id` 为空时不抛、不推；`failure.reason_code`
      六个 error 形状各映射一条 + 兜底 `unknown`；断言 `orchestration` 快照的 JSON
      **不含** `message` / `exception` / `report` 键；`plan_research_sessions` 不出现在
      `deep_sessions` 里；日志经脱敏。

### Unresolved（本 phase 明确不做 / 依赖后端裁决 / 需 planner 判定）

1. 🔴 **`RoutingDecisionPanel` 无挂载点**（§D.3，本次实读发现）：107 的 9 个 plan 全部完成，
   但该组件在 `web/src/**/*.vue` 里**零使用点**。⇒ 落地后「降级」角标事实上是编排链唯一的
   降级信号，RELY-03 在用户侧是否成立存疑。**本 phase 不挂它**（超出边界）；
   planner 需判定这是 107 的收尾遗漏还是需要开后续项，并在 VERIFICATION 中如实记录。
2. 🔴 **`OrchestratedPlanCard` 在异步路径上大概率不渲染**（§落点 F）：这是 109 的入口缺口，
   本 phase 只做 `.find` 加固（Covered #17）+ 让时间线终态自给自足（Covered #16），
   **不补 109 的缺口**。planner 应用一次真实编排跑通来确认卡片到底出不出现。
3. **`SubStepTimeline` 泛化 vs chat 本地新组件**：本契约选「加性泛化共享组件」，
   替代方案是 chat 侧新建一个逐字复制同款 DOM 的本地组件。两者都满足 CONTEXT 的
   「不新增组件原语」，差别是「共享组件承载两个域的关注点」vs「标记重复」。
   planner 应把这个二选一写进任务，而不是留给 executor 现场发挥。
4. **`DeepAnalysisGroup` 的 `title` prop**：本 phase 不改它（改动会牵动既有 swiper 测试）。
   若后续确实要给方案调研做 swiper 形态，正确做法是加一个默认值为今日文案的 `title` prop。
5. **`SubStepTimeline` 的局部状态色 map**：形式上违反 DESIGN.md「禁止组件内定义 statusColors」，
   本 phase 只在既有 map 内增分支、不迁 `~/config/status.ts`（那份配置服务于 `StatusBadge`
   的 5 个 `type`）。记为技术债。
6. **组件家族 i18n 迁移**：chat 家族整体硬编码中文（实读：仅 `ClarificationCard.vue` 用 i18n），
   本 phase 跟随现状。统一迁移 vue-i18n 属技术债（107/109 已两次记录同一条）。
7. **`decompose` 无领域事件**：本 phase 靠快照的 `segment_count` 补摘要。若后续希望
   「拆分」也能边跑边出（现在它的摘要要等一次 2s 轮询），正确做法是给 `_h_decompose`
   补一条 `technical_plan.decomposed` 领域事件进 taxonomy，**而不是**在 `transition()` 的
   通用 emit 里塞 payload（那会污染全部转移事件）。**本 phase 不做**。
8. **workflow / MCP 入口的过程可视化**：无 chat 会话即无推送目标（CONTEXT 既定 Deferred）。
   事件照常落库，读取面已具备（`(session, ts)` 索引）。
9. **原始异常文本的排障下钻**：脱敏后的原文只入事件表 / `SystemLogEntry`，**不做前端展开区**
   （与 107-UI-SPEC Unresolved #4 同一裁定：开发者要看原文是额外权限面，需 superuser 可见性设计）。
10. **调研日志的历史留存**：`_append_runtime_log` 只保留最后 80 条
    （`runners/consumers.py:_MAX_RUNTIME_LOGS`）。长调研的早期日志会被截断，
    前端**不提示截断**（与 `events_truncated` 同一裁定）。若 UAT 判为不可接受，
    处置是调 `_MAX_RUNTIME_LOGS` 或落独立日志表，**不在前端做假**。
11. **`deep_analysis_progress` 死路径**：定义了但从无生产发射方，本 phase **不救活、不参照**
    （CONTEXT 既定范围外）。

---

## Checker Sign-Off

- [ ] Dimension 1 Copywriting: PASS
- [ ] Dimension 2 Visuals: PASS
- [ ] Dimension 3 Color: PASS
- [ ] Dimension 4 Typography: PASS
- [ ] Dimension 5 Spacing: PASS
- [ ] Dimension 6 Registry Safety: PASS

**Approval:** pending
