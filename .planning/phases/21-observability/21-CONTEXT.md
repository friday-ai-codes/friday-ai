# Phase 21: 触发模型与执行可观测 - Context

**Gathered:** 2026-06-13
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous——orchestrator 基于代码勘察提出 grey-area 决策并采纳）

<domain>
## Phase Boundary

触发链路真实可用、失败可查；执行状态与节点错误在前端如实呈现——用户不再把"失败"误感知为"卡住"、把"没触发"误感知为"没反应"。本里程碑收官阶段。

**In scope（TRIG-01/02/03、OBS-01/02/03）：**
- 修复 feishu_event_trigger 字段断裂（event_type/event_types 统一），保存后 WorkflowTrigger 表正确生成、飞书事件能匹配
- schedule 假功能处置（移除可配置入口，详见 D-02）
- dispatch 失败不再静默吞掉——记录到可查询位置（TriggerLog 或等价），用户可见原因
- 执行详情页节点失败清晰展示 error_message / 失败变量引用 / 重试 / error_code
- 详情页 WebSocket 断线自动降级 REST 轮询，进度以服务端权威值为准，长时执行 UI 不冻结
- 前端执行状态枚举与后端 ExecutionStatus 对齐（补 suspended，清除误用的 execution 级 waiting_approval）

**Out of scope：**
- 不改引擎执行/挂起/死锁语义（Phase 18 已收口），本阶段只让其对前端可见
- 不改变量解析语义（Phase 17 已定稿），只在前端解析展示其结构化错误
- 不重写执行详情页整体视觉，仅补失败展示 + WS 降级 + 状态对齐
</domain>

<decisions>
## Implementation Decisions

### D-01 [feishu 字段统一] 单数 event_type 为准，同步侧兼容兜底
- 统一以 **单数 `event_type`** 为事实源（模型 WorkflowTrigger.event_type、节点 schema、前端 schema/UI、序列化已是单数）。
- 修复 `async_sync_workflow_triggers`（views.py L96-166）：改读 `config.get("event_type")`，对历史 `event_types` 数组做兜底（取首项或展开多 trigger），消除"读复数→恒空→trigger 被 deactivate"的根因。
- 补齐同步遗漏：`project_ids` / 排除规则 / `filter_status` 数组形态（schemas.ts L138 为数组）正确写入 filter_config。
- 加 `async_sync_workflow_triggers` 专项测试 + 字段对齐回归（保存 feishu_event_trigger → WorkflowTrigger 生成 → FeishuHandler.find_workflows 命中）。

### D-02 [schedule 处置] 移除假功能（非实现）
移除 `schedule` 可配置入口而非实现原生定时调度。理由：① schedule 当前**无配置 UI、无画布节点**（仅 Workflow.TriggerType 枚举 + 列表标签的残留）；② daily_summary 模板已确立"外部 cron → 调 webhook"的既定模式（templates/daily_summary.json 注释）；③ 移除是 fail-safe——用户无法再配置出不生效的触发器（满足 TRIG-02 第二选项）。
- 后端：从 `Workflow.TriggerType` choices 移除 `schedule`（migration 安全处理存量：若有 schedule 行，迁移为 manual 或保留只读不报错——由 executor 依存量核查定）。
- 前端：移除 schedule 类型/标签/创建选项（useWorkflowsStore 类型、executions/index.vue 标签、CreateWorkflowModal）。
- 文档化：定时触发 = 外部 cron 调 webhook（沿用 daily_summary 注释口径）。

### D-03 [dispatch 失败可查] 失败落到可查询记录
dispatch 失败（未知类型 / 校验失败 / 无匹配工作流 / start_execution 异常）不再仅 structlog——记录到可查询位置，前端可见"触发了但没跑起来"的原因。
- 优先扩展现有 `TriggerLog`（feishu/models.py，已有 status/error_message/workflow_execution）：飞书路径在 dispatch 校验失败/无匹配/启动异常时更新 status 为失败态 + error_message（不再恒 ACCEPTED）。
- manual/webhook 路径：在 dispatch 返回空或抛异常时，记录到可查询位置（扩展 TriggerLog 适用范围或新建轻量 dispatch 失败记录——由 planner 定最小方案）。
- 加 dispatch 失败持久化断言测试（test_trigger_dispatcher 扩展）。

### D-04 [节点失败实时可见] WS 广播 error + 前端结构化展示
- 后端 `WebSocketBroadcastHook`（hooks/builtin.py L55-65）的 node 状态广播 payload 增加 `error_message`（失败时），使前端无需 full fetch 即见失败原因。
- 前端：`useExecutionsStore` 的 `node_failed` WS 处理更新对应 NodeExecution 的 error_message（不只 failed_nodes++）；NodeOverviewTab/ExecutionNode 展示 error_message、error_code、重试次数；对 Phase 17 结构化变量错误（error_message 末行 JSON）做 `JSON.parse` 友好展示（解析失败回退纯文本）；DAG 失败节点加 error tooltip。

### D-05 [WS 断线降级轮询] 详情页对齐列表页
执行详情页 WS 断线时自动降级 REST 轮询（复用列表页 `refetchInterval` / `useExecutionsStore` usePolling 5s 模式），断线横幅期间持续拉取 execution + node 状态；重连后恢复 WS。进度/状态以服务端权威值为准（不被前端本地推断覆盖）。长时执行 UI 不冻结。

### D-06 [状态枚举对齐] 前端对齐后端 ExecutionStatus，区分 execution/node 等待态
- 前端执行状态配置（config/status.ts）补齐后端 `ExecutionStatus` 全集：增 `suspended`（Phase 18 等待态落点）、`timeout`；确保都有 badge 配置（消除 raw 字符串 fallback）。
- 清除前端把 **execution 级**误用 `waiting_approval`（实为 NodeExecutionStatus）：useExecutionsStore stats 统计、ExecutionCard/useExecutionState 的 active 判断按"execution 用 suspended、node 用 waiting_*"区分。
- 列表筛选、DAG 节点色映射补 suspended/timeout/waiting_event。

### Claude's Discretion
- schedule 存量行迁移的精确策略、dispatch 失败记录的最小持久化形态（扩 TriggerLog vs 新表）、WS 广播 payload 的精确字段、结构化变量错误的前端展示样式、wave 划分——交 planner/executor 依代码现状定夺。
</decisions>

<code_context>
## Existing Code Insights（勘察结论，RESEARCH 将深化）

**TRIG-01 根因**：`async_sync_workflow_triggers`（views.py L96-166，仅 bulk_update L722-744 调用）读 `config["event_types"]`（复数），但 UI/节点 schema/模型/序列化均用单数 `event_type` → configured_triggers 恒空 → 旧 trigger 被 deactivate（L155-159）→ WorkflowTrigger 表 effectively 空 → FeishuHandler.find_workflows（feishu.py L67-108）返回 []。同步还遗漏 project_ids/排除规则，filter_status 数组处理不当。

**TRIG-02**：`schedule` 在 Workflow.TriggerType（workflow.py L30-34）+ executions/index.vue L258 标签 + useWorkflowsStore L52 类型存在；**无 ScheduleHandler、无 apscheduler 注册、无 dispatch**（handlers/__init__.py 仅 manual/webhook/feishu；dispatcher 未知类型返回 []）。apscheduler（runapscheduler.py）用于 repo polling 等系统任务，与工作流 trigger 无关。

**TRIG-03**：dispatcher.py 失败路径（L74-132）+ feishu/views.py（L726-731）+ workflows/api/views.py webhook（L1565-1574）mostly structlog only。`TriggerLog`（feishu/models.py L32-87）有 status/error_message/workflow_execution，但 dispatch 校验失败/无匹配/启动异常仍记 ACCEPTED；manual/webhook 无等价。

**OBS-01**：NodeExecution 有 error_message/error_traceback/error_code/attempt/logs（execution.py L437-515）。前端 NodeOverviewTab 展示 error_message+traceback（L133-147）、重试（L115-120）；**未展示 error_code**、**未解析 Phase 17 结构化变量错误**；WS node_failed 只 failed_nodes++（useExecutionsStore L374-376），广播 payload 不含 error（hooks/builtin.py L55-65）→ 运行中失败需 full fetch 才可见。

**OBS-02**：详情页 WS（useExecutionState L120-143）断线仅横幅+重连按钮（ExecutionStatusBanners L32-44），**无 REST 轮询降级**。列表页有 refetchInterval 5s（executions/index.vue L98-105）+ useExecutionsStore usePolling（L161-170）可复用。

**OBS-03**：后端 ExecutionStatus（execution.py L17-27）含 suspended/timeout；前端 config/status.ts（L9-21）有 waiting_approval/waiting_input 但**缺 suspended**；useExecutionsStore stats（L148-150）误把 waiting_approval 当 execution.status；DAG 节点色（ExecutionNode.vue L38-48）无 suspended/timeout 映射。Phase 18 等待 → ExecutionStatus.SUSPENDED（scheduler.py L942-962），前端多处仍假设 execution 级 waiting_approval（实为 node 级）。

**测试缺口**：async_sync_workflow_triggers 专项、dispatch 失败持久化断言、[id].vue/NodeOverviewTab/WS 降级/suspended 组件测试均缺。
</code_context>

<specifics>
## Specific Ideas

- 保存 feishu_event_trigger → WorkflowTrigger 生成 → 飞书事件匹配触发（端到端）。
- schedule 用户无法再配置出不生效的触发器。
- dispatch 失败有可查询原因记录。
- 详情页节点失败展示 error_message / 失败变量引用 / 重试 / error_code；WS 断线降级 REST 轮询；状态枚举前后端对齐（含 suspended）。
</specifics>

<deferred>
## Deferred Ideas

- 原生 schedule/cron 触发的完整实现（apscheduler per-workflow job 生命周期）——本里程碑用"外部 cron→webhook"模式替代，移除假入口。
- 执行详情页全面可观测增强（节点级实时日志流等）——本阶段只补失败展示 + WS 降级 + 状态对齐。
- DAG 失败节点的富交互（点击跳转/根因高亮）——可最小实现或留 TODO。
</deferred>

---

*Phase: 21-observability*
*Context gathered: 2026-06-13 via smart discuss (autonomous)*
