# Phase 21: 触发模型与执行可观测 - Research

**Researched:** 2026-06-13
**Domain:** Django 触发器同步/分发可观测 + Vue 3 执行详情可观测（WS 降级、状态对齐、失败展示）
**Confidence:** HIGH（纯内部代码勘察，无外部依赖；所有断言均有行号锚点 [VERIFIED: codebase grep/read]）

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01 [feishu 字段统一]** 单数 `event_type` 为事实源。修复 `async_sync_workflow_triggers`（views.py L96-166）：改读 `config.get("event_type")`，对历史 `event_types` 数组做兜底（取首项或展开多 trigger）。补齐同步遗漏：`project_ids` / 排除规则 / `filter_status` 数组形态正确写入 filter_config。加专项测试 + 字段对齐回归（保存 → WorkflowTrigger 生成 → FeishuHandler.find_workflows 命中）。
- **D-02 [schedule 处置]** 移除假功能（非实现原生定时）。后端从 `Workflow.TriggerType` choices 移除 `schedule`（migration 安全处理存量）；前端移除 schedule 类型/标签/创建选项；文档化"外部 cron → 调 webhook"。
- **D-03 [dispatch 失败可查]** dispatch 失败（未知类型/校验失败/无匹配/start 异常）记录到可查询位置。优先扩展现有 `TriggerLog`（飞书路径在失败时更新 status + error_message，不再恒 ACCEPTED）；manual/webhook 路径最小持久化（扩 TriggerLog 适用范围或新建轻量记录——planner 定）。加 dispatch 失败持久化断言测试。
- **D-04 [节点失败实时可见]** `WebSocketBroadcastHook`（hooks/builtin.py L55-65）node 广播 payload 增加 `error_message`；前端 `useExecutionsStore` 的 `node_failed` 更新对应 NodeExecution 的 error_message（不只 failed_nodes++）；展示 error_message/error_code/重试；Phase 17 结构化变量错误末行 JSON 做 `JSON.parse` 友好展示（失败回退纯文本）；DAG 失败节点加 error tooltip。
- **D-05 [WS 断线降级轮询]** 详情页 WS 断线自动降级 REST 轮询（复用列表页 refetchInterval/usePolling 5s 模式），断线横幅期间持续拉取 execution + node 状态，重连后恢复 WS。进度/状态以服务端权威值为准（不被前端本地推断覆盖）。
- **D-06 [状态枚举对齐]** 前端 config/status.ts 补齐后端 `ExecutionStatus` 全集：增 `suspended`、确保 `timeout` 有 badge。清除前端把 execution 级误用 `waiting_approval`（实为 NodeExecutionStatus）；区分 execution 用 suspended、node 用 waiting_*。列表筛选、DAG 节点色补 suspended/timeout/waiting_event。

### Claude's Discretion
- schedule 存量行迁移的精确策略、dispatch 失败记录的最小持久化形态（扩 TriggerLog vs 新表）、WS 广播 payload 的精确字段、结构化变量错误的前端展示样式、wave 划分——交 planner/executor 依代码现状定夺。

### Deferred Ideas (OUT OF SCOPE)
- 原生 schedule/cron 触发的完整实现（apscheduler per-workflow job 生命周期）——用"外部 cron→webhook"替代。
- 执行详情页全面可观测增强（节点级实时日志流等）——本阶段只补失败展示 + WS 降级 + 状态对齐。
- DAG 失败节点的富交互（点击跳转/根因高亮）——可最小实现或留 TODO。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| TRIG-01 | 飞书触发同步字段断裂修复（`WorkflowTrigger` 正确生成、事件能匹配） | §架构 Pattern 1 + Don't Hand-Roll + Pitfall 1/2；`async_sync_workflow_triggers` 改读单数 + filter_config 映射；matches_event 语义已确认 |
| TRIG-02 | `schedule` 不再是假功能：移除选项 | §Runtime State Inventory + Pattern 2；migration AlterField 模式（参 0022/0003）；前端 6 处移除点清单 |
| TRIG-03 | dispatch 失败不再静默吞掉，可查询原因 | §Pattern 3；`_dispatch_to_workflows`（feishu/views.py L693-731）失败更新 TriggerLog；webhook/manual 最小持久化方案 |
| OBS-01 | 节点失败清晰展示（error_message/失败变量引用/重试/error_code） | §Pattern 4；WebSocketBroadcastHook 加 error_message；前端 node_failed 处理 + NodeOverviewTab 结构化展示 |
| OBS-02 | WS 断线自动降级 REST 轮询，进度以服务端权威值为准 | §Pattern 5；useExecutionState + usePolling 状态机；列表页 refetchInterval 复用 |
| OBS-03 | 执行状态前后端枚举对齐（清除不存在状态值） | §Pattern 6；ExecutionStatus vs NodeExecutionStatus 区分；config/status.ts 补 suspended |
</phase_requirements>

## Summary

本阶段是**纯内部契约修复**——不引入任何新依赖，不改引擎/变量/挂起语义，只让既有后端状态对前端如实可见，并修复触发链路的字段断裂与失败静默。研究确认所有六个需求的根因与改点都已在 CONTEXT 行号锚点中定位，且与代码现状逐一吻合。

三条主线：(1) **触发器同步**——`async_sync_workflow_triggers` 读复数 `event_types` 而 schema/模型/序列化全用单数 `event_type`，导致 `configured_triggers` 恒空、旧 trigger 被 deactivate、`WorkflowTrigger` 表空、飞书事件无法匹配（TRIG-01）；`schedule` 是无 handler/无 UI 的僵尸枚举，移除即 fail-safe（TRIG-02）；dispatch 失败仅 `structlog`，`TriggerLog` 恒记 ACCEPTED（TRIG-03）。(2) **节点失败可见**——`WebSocketBroadcastHook` 广播 payload 不含 error，前端 `node_failed` 只 `failed_nodes++`，运行中失败需 full fetch 才可见（OBS-01）。(3) **执行可观测**——详情页 WS 断线只有横幅无轮询降级（OBS-02）；前端 `config/status.ts` 缺 `suspended`、把 node 级 `waiting_approval` 误当 execution 级（OBS-03）。

**Primary recommendation:** 复用既有原语（`matches_event` 的 list/dotted-path 过滤、`TriggerLog.status`+`error_message`、`usePolling`/`useIntervalFn`、`getStatusConfig` fallback、Phase 18 死锁结构化 JSON 约定、`StatusBadge`），**绝不新建并行机制**；migration 走 AlterField（参照 `0022_remove_cancelled_status.py`、`0003_suspended_status.py`），WS 广播只**新增可选字段**保持向后兼容，轮询与 WS 用单一"权威值"写入路径避免双写竞态。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| feishu_event_trigger → WorkflowTrigger 同步 | API/Backend（`async_sync_workflow_triggers`，views.py L96-166） | — | 触发器表是服务端权威配置，保存时（bulk_update L744）服务端重建 |
| 飞书事件匹配工作流 | API/Backend（`FeishuEventHandler.find_workflows` + `WorkflowTrigger.matches_event`） | — | 匹配语义在 trigger model，前端不参与 |
| schedule 枚举移除 | API/Backend（`Workflow.TriggerType` + migration） | Browser/Client（前端 6 处展示移除） | 枚举是后端 SSOT，前端只是消费 |
| dispatch 失败持久化 | API/Backend（`TriggerLog` + 三条 dispatch 路径） | Browser/Client（logs 页已有展示） | 失败原因是服务端事实，前端只读 |
| 节点失败实时广播 | API/Backend（`WebSocketBroadcastHook`） | Browser/Client（store WS 消费 + 组件展示） | error_message 服务端写入，WS 推送，前端展示 |
| 结构化变量错误解析展示 | Browser/Client（NodeOverviewTab `JSON.parse`） | API/Backend（Phase 17/18 已写入末行 JSON） | 后端只产出约定格式，解析展示是前端职责 |
| WS 断线降级轮询 | Browser/Client（useExecutionState 状态机） | API/Backend（REST `/workflow-executions/{id}/` 提供权威值） | 降级是前端连接管理，服务端只需提供 REST |
| 执行状态枚举对齐 | Browser/Client（config/status.ts） | API/Backend（`ExecutionStatus` 为 SSOT） | 前端枚举必须镜像后端，区分 execution/node 级 |

**关键边界纠偏**：前端当前在 **Browser 层**把 `waiting_approval`（属 `NodeExecutionStatus`，node 级）误当 execution 级状态判断（useExecutionsStore L148-150、executions/index.vue L129）——这是 tier 语义错位，须按"execution 用 `suspended`、node 用 `waiting_*`"重新归位（OBS-03）。

## Standard Stack

### Core

**本阶段不引入任何新依赖。** 全部复用 v0.4.0 既有栈，对照各需求改点：

| 既有原语 | 位置 | 用途 | 为何复用 |
|---------|------|------|---------|
| `WorkflowTrigger.matches_event` / `_matches_filter` | server/workflows/models/trigger.py L104-166 | 事件类型 + filter_config 过滤（支持 list 成员匹配、dotted-path 嵌套） | 已实现 list/嵌套语义，TRIG-01 只需正确填充 filter_config |
| `TriggerLog.status` + `error_message` | server/feishu/models.py L71-76 | dispatch 失败落库（已有 ACCEPTED/IGNORED/ERROR/DUPLICATE） | TRIG-03 直接复用，无需新表 |
| `WebSocketBroadcastHook` | server/workflows/hooks/builtin.py L38-78 | 执行/节点状态 WS 广播 | OBS-01 仅在 message dict 追加可选 `error_message` |
| `usePolling` / `@vueuse/core useIntervalFn` | web/src/composables/usePolling.ts | REST 轮询降级 | OBS-02 复用，已有 start/stop/卸载自动清理 |
| `@tanstack/vue-query refetchInterval` | web/src/pages/executions/index.vue L98-105 | 列表页条件轮询范式 | OBS-02 详情页可同构复用 |
| `getStatusConfig` + `StatusBadge` | web/src/config/status.ts L84-99 | 状态徽章 + unknown fallback | OBS-03 只需补 map 条目 |
| Django `AlterField` migration | server/workflows/migrations/0022/0003 | TextChoices 增删（无 DB 约束） | TRIG-02 安全移除 schedule 的成熟模式 |

### Supporting

| 既有测试栈 | 位置 | 用途 |
|-----------|------|------|
| pytest + pytest-asyncio + pytest-django | server/tests/ | 后端触发同步/dispatch 失败断言 |
| `test_trigger_dispatcher.py` 范式（AsyncMock engine + registry fixture） | server/tests/test_trigger_dispatcher.py L29-55 | TRIG-03 dispatch 失败测试扩展点 |
| vitest + @vue/test-utils + happy-dom | web/src/**/__tests__/ | 前端状态/WS 降级/失败展示组件测试 |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| 扩展 `TriggerLog`（TRIG-03） | 新建轻量 `DispatchFailure` 表 | TriggerLog 已有 status/error_message/workflow_execution + logs 页展示；新表需新 model/migration/序列化/前端页——D-03 指明"优先扩展现有"，新表仅在 manual/webhook 无 TriggerLog 归属时考虑（见 Open Questions OQ-2） |
| AlterField 移除 schedule（TRIG-02） | 保留枚举只隐藏前端入口 | 保留则用户仍可能通过 API/导入配出 schedule；移除枚举是 D-02 要求的 fail-safe |
| WS 广播加 `error_message`（OBS-01） | 前端 full fetch on node_failed | full fetch 每次失败一次额外请求 + 抖动；WS 直推零额外请求且即时 |

**Installation:** 无（零新依赖）。验证：`server/pyproject.toml` / `web/package.json` 不新增条目。

## Package Legitimacy Audit

**N/A — 本阶段不安装任何外部包。** 全部为既有代码内部重构 + Vue/Django 既有 API。无 npm/PyPI 新增，故无 slopcheck/registry 验证需求。

## Architecture Patterns

### System Architecture Diagram（触发与可观测数据流）

```text
保存工作流 (bulk_update PUT)                  飞书 Webhook / 外部 cron→webhook / 手动
        │                                              │
        ▼                                              ▼
_bulk_update_nodes_and_edges                  feishu/views.py 接收 → TriggerLog(ACCEPTED)
        │                                              │
        ▼                                              ▼
async_sync_workflow_triggers ──────┐          TriggerDispatcher.dispatch(context)
  读 node.config.event_type(单数)   │            ├─ unknown type → return []   ┐
  组 filter_config(status/proj/排除)│            ├─ validate() errors → []      │ 失败均仅 structlog
  upsert/deactivate WorkflowTrigger │            ├─ find_workflows() → []        │ → TRIG-03 须落 TriggerLog
        │                           │            └─ start_execution() 异常       ┘
        ▼                           │                     │ 成功
  WorkflowTrigger 表 ◄──────────────┘                     ▼
        │                                        WorkflowEngine 调度节点
        ▼ (飞书事件到达)                                   │
  matches_event(event_type, payload)                      ▼
  _matches_filter: list成员/dotted-path           Hook 链: WebSocketBroadcastHook
        │ 命中                                     广播 {event,status,node_id,node_status
        ▼                                                  (+error_message ← OBS-01)}
  find_workflows → 工作流执行                              │
                                              ┌────────────┴───────────┐
                                              ▼                        ▼
                                   ws/workflow-executions/{id}/   REST /workflow-executions/{id}/
                                              │                        │ (权威值, OBS-02 降级源)
                                              ▼                        ▼
                                   useExecutionsStore.handleWebSocketMessage
                                   ├─ node_failed → error_message 写入 NE (OBS-01)
                                   ├─ status → execution.status (区分 suspended/node waiting_*, OBS-03)
                                   └─ WS CLOSED → usePolling REST 降级 (OBS-02)
                                              │
                                              ▼
                       NodeOverviewTab / ExecutionNode(DAG色) / ExecutionCard / StatusBadge
                       (error_code + 重试 + 结构化变量错误 JSON.parse 展示)
```

### Recommended File Touch Map

```text
server/workflows/api/views.py        # async_sync_workflow_triggers (L96-166) TRIG-01
server/workflows/models/workflow.py  # TriggerType 移除 schedule (L30-34) TRIG-02
server/workflows/migrations/00XX_*   # AlterField trigger_type choices TRIG-02
server/feishu/views.py               # _dispatch_to_workflows (L693-731) TRIG-03
server/workflows/api/views.py        # webhook dispatch (L1565-1574) TRIG-03 (最小)
server/workflows/hooks/builtin.py    # WebSocketBroadcastHook (L55-65) OBS-01
web/src/stores/useExecutionsStore.ts # node_failed 处理(L374-376) + stats(L148-150) OBS-01/03
web/src/config/status.ts             # 补 suspended badge (L9-21) OBS-03
web/src/pages/executions/composables/useExecutionState.ts # WS 降级状态机 OBS-02
web/src/components/execution/NodeOverviewTab.vue          # error_code/变量错误展示 OBS-01
web/src/components/execution/dag/ExecutionNode.vue        # DAG色补 suspended/timeout OBS-03
web/src/pages/executions/index.vue   # 移除 schedule 标签(L258) + statusOptions(L61) TRIG-02/OBS-03
web/src/stores/useWorkflowsStore.ts  # trigger_type 类型移除 schedule(L52) TRIG-02
web/src/components/execution/ExecutionCard.vue / ExecutionHistoryCard.vue # schedule 标签 TRIG-02
```

### Pattern 1: 触发器同步字段统一（TRIG-01）

**What:** `async_sync_workflow_triggers`（views.py L96-166）改读单数 `event_type`，对历史 `event_types` 数组兜底，并把 `filter_status`(数组)/`filter_project_key`/`filter_work_item_type` 正确写入 `filter_config`。
**When to use:** bulk_update（L744，唯一调用方）保存含 `feishu_event_trigger` 节点的工作流时。
**根因证据:** L106 `event_types = config.get("event_types", [])` 读复数 → schema（schemas.ts L132）定义单数 `event_type` → `event_types` 恒空 → L117 `for event_type in event_types` 零次 → `configured_triggers` 空 → L156-159 旧 trigger 全部 deactivate → 表空。
**Example:**
```python
# server/workflows/api/views.py  async_sync_workflow_triggers  (改造示意)
async for node in workflow.nodes.filter(node_type="feishu_event_trigger"):
    config = node.config or {}
    # 单数为准 + 历史复数兜底（取所有，去重，保留非空）
    event_type = config.get("event_type")
    legacy = config.get("event_types") or []
    event_type_list = [et for et in ([event_type] if event_type else legacy) if et]

    filter_config: dict = {}
    if config.get("filter_project_key"):
        filter_config["project_key"] = config["filter_project_key"]
    if config.get("filter_work_item_type"):
        filter_config["work_item_type_key"] = config["filter_work_item_type"]
    # filter_status 已是数组 → matches_event._matches_filter 支持 list 成员匹配
    statuses = config.get("filter_status") or []
    if config.get("filter_status_custom"):
        statuses = [*statuses, config["filter_status_custom"]]
    if statuses:
        filter_config["cur_work_item_status.state_key"] = statuses
    # project_ids / exclude_* → 见 Open Questions OQ-1（matches_event 仅支持正向 include）

    for et in event_type_list:
        configured_triggers.append({"event_type": et, "filter_config": filter_config,
                                    "node_id": str(node.id), "node_name": node.name})
```
匹配侧无需改：`_matches_filter`（trigger.py L137-147）对 list 值走"actual ∈ expected"、对 dotted key 走 `_get_nested_value`（L149-166），与上面 filter_config 结构契合 [VERIFIED: trigger.py read]。

### Pattern 2: 僵尸枚举移除（TRIG-02）

**What:** 从 `Workflow.TriggerType`（workflow.py L30-34）移除 `SCHEDULE`，生成 `AlterField` migration；前端删除所有 schedule 展示点。
**Why safe:** `schedule` **无 handler**（triggers/handlers/__init__.py 仅 manual/webhook/feishu）、**无画布节点**、**无 dispatch**——纯枚举 + 列表标签残留。Django `TextChoices` **不施加 DB CHECK 约束**，存量 `trigger_type='schedule'` 行在移除 choice 后仍是合法字符串、不会报错（与 0022/0003 同模式 [VERIFIED: migration read]）。
**Example (migration):**
```python
# 参照 0022_remove_cancelled_status.py 的 AlterField 模式
operations = [
    migrations.AlterField(
        model_name="workflow",
        name="trigger_type",
        field=models.CharField(
            choices=[("manual","手动触发"),("webhook","Webhook 触发"),("event","事件触发")],
            default="manual", max_length=20, verbose_name="触发类型",
        ),
    ),
    # 可选数据迁移（Claude's Discretion）：存量 schedule → manual
    # migrations.RunPython(lambda apps,_: apps.get_model("workflows","Workflow")
    #   .objects.filter(trigger_type="schedule").update(trigger_type="manual"),
    #   migrations.RunPython.noop),
]
```
**前端移除点清单 [VERIFIED: grep]:** `useWorkflowsStore.ts:52`（联合类型）、`executions/index.vue:258,265`（标签+图标）、`ExecutionCard.vue:29`、`ExecutionHistoryCard.vue:54`、测试夹具 `executions-datatable.test.ts:34,92` / `logs-datatable.test.ts:37`。注意 `repositories.ts:106` 的 `'scheduled'` 是**仓库索引**触发类型，与工作流无关，**勿动**。

### Pattern 3: dispatch 失败持久化（TRIG-03）

**What:** 飞书路径 `_dispatch_to_workflows`（feishu/views.py L693-731）在 dispatch 异常或返回空时更新 `trigger_log.status`+`error_message`（不再恒 ACCEPTED）。
**证据:** 当前 L726-731 `except Exception` 仅 `logger.error`；成功仅 L722-724 写 workflow_execution；**返回空（无匹配）/异常 → status 永远停在 ACCEPTED（L661）**。
**Example:**
```python
# feishu/views.py _dispatch_to_workflows  (改造示意)
try:
    executions = await dispatcher.dispatch(context)
    if executions:
        if len(executions) == 1:
            trigger_log.workflow_execution = executions[0]
        await trigger_log.asave(update_fields=["workflow_execution"])
    else:
        # 无匹配工作流：用 IGNORED + 原因（区别于"已接受并执行"）
        trigger_log.status = TriggerLogStatus.IGNORED
        trigger_log.error_message = f"无匹配工作流（event_type={event_type}）"
        await trigger_log.asave(update_fields=["status", "error_message"])
except Exception as e:
    logger.error("workflow_dispatch_failed", event_type=event_type, error=str(e))
    trigger_log.status = TriggerLogStatus.ERROR
    trigger_log.error_message = str(e)[:2000]  # 截断防膨胀
    await trigger_log.asave(update_fields=["status", "error_message"])
```
**webhook/manual 最小方案:** webhook（views.py L1565-1574）已对空结果返回 `no_workflows`（200），但**无持久化**。最小做法：webhook 路径在 dispatch 前后写一条 `TriggerLog`（event_type 用 webhook path，status 按结果）——见 OQ-2，planner 定是否值得（manual 触发通常用户在前端即时看到结果，持久化优先级最低）。
**前端可查位置:** logs 页已消费 `triggerLogStatusConfig`（status.ts L54-59），失败态 `error`/`ignored` 已有 badge，无需前端改动即可查 [VERIFIED]。

### Pattern 4: 节点失败实时展示（OBS-01）

**What:** (a) 后端 `WebSocketBroadcastHook` 在 node 广播 message 追加可选 `error_message`；(b) 前端 `node_failed` 写入对应 NE 的 error_message；(c) `NodeOverviewTab` 展示 `error_code` + 结构化变量错误 `JSON.parse`。
**后端改点（hooks/builtin.py L62-65 之后）:**
```python
node_execution = kwargs.get("node_execution")
if node_execution:
    message["node_id"] = str(node_execution.node_id)
    message["node_status"] = node_execution.status
    # OBS-01：失败时附 error_message + error_code（仅新增可选键，向后兼容）
    if node_execution.status in ("failed", "timeout"):
        message["error_message"] = node_execution.error_message or ""
        message["error_code"] = node_execution.error_code or ""
```
**前端改点（useExecutionsStore.ts L357-376）:** 现 L357-364 已按 `ne.node === node_id` 找 NE 并更新 status；在 `node_failed` 分支补：
```ts
else if (event === 'node_failed') {
  currentExecution.value.failed_nodes++
  const ne = currentExecution.value.node_executions.find(n => n.node === node_id)
  if (ne) {
    if (data.error_message != null) ne.error_message = data.error_message
    if (data.error_code != null) ne.error_code = data.error_code
  }
}
```
**结构化变量错误展示（NodeOverviewTab.vue L133-148）:** Phase 17/18 约定 error_message = 中文一句话 + `\n` + 末行 `json.dumps(...)`（VAR-02 变量解析失败 / ENG-04 死锁诊断 [VERIFIED: 18-03-SUMMARY L70]）。前端按末行尝试 parse：
```ts
function parseStructuredError(msg: string): { summary: string, detail: any | null } {
  const lines = msg.trimEnd().split('\n')
  const last = lines[lines.length - 1]
  try {
    const detail = JSON.parse(last)            // 成功 → 友好展示拓扑/引用
    return { summary: lines.slice(0, -1).join('\n'), detail }
  }
  catch { return { summary: msg, detail: null } }  // 失败回退纯文本
}
```
`error_code` 当前 NodeOverviewTab **未展示**（L90-121 信息行无 error_code），须新增一行（`NodeExecution.error_code` 已在 store 类型 L29）。DAG 失败节点 tooltip：`ExecutionNode.vue` 已有 `Tooltip*` 组件 import（L13-18）+ `failed: 'border-red-400/70'`（L41），可在失败时把 error_message 注入 TooltipContent（最小实现）。

### Pattern 5: WS 断线降级 REST 轮询（OBS-02）

**What:** 详情页（useExecutionState.ts）在 `wsStatus === 'CLOSED'` 且执行仍活跃时，启动 `usePolling` 拉 `store.fetchExecution(id)`（含 node 状态）；WS 重连成功后停轮询。
**现状:** `wsDisconnected`（L74-81）已计算断线（active + CLOSED）；`ExecutionStatusBanners.vue` 已渲染横幅 + "重新连接"按钮——**但断线期间无任何 REST 拉取**，长时执行 UI 冻结在断线快照。
**推荐接法（vue-query vs useIntervalFn）:** 详情页用的是 store 手动 fetch（非 vue-query），故复用 `usePolling`（已有 start/stop + onUnmounted 自动清理）最贴合，避免再引 vue-query 到详情页造成双状态源。状态机：
```ts
// useExecutionState.ts （新增）
const { start: startPoll, stop: stopPoll } = usePolling(
  () => store.fetchExecution(executionId.value),  // REST = 服务端权威值
  { interval: 5000, immediate: true },            // 与列表页 5s 对齐
)
watch(wsDisconnected, (disconnected) => {
  if (disconnected) startPoll()   // 断线 → 降级轮询
  else stopPoll()                 // 重连/终态 → 停轮询
})
// onUnmounted 已由 usePolling 内部处理
```
**权威值约束（D-05）:** `fetchExecution` 整体覆盖 `currentExecution`（store L207），天然以服务端为准；轮询期间**不要**让 WS 的 `handleWebSocketMessage` 本地推断（`completed_nodes++` 等 L368-382）与轮询结果并存——断线时 WS 已无消息，重连后首个 REST/WS 全量刷新对齐即可（见 Pitfall 6 双写竞态）。

### Pattern 6: 执行状态枚举对齐（OBS-03）

**What:** `config/status.ts` 的 `executionStatusConfig`（L9-21）补 `suspended`；纠正前端把 node 级 `waiting_approval` 当 execution 级。
**证据:** 后端 `ExecutionStatus`（execution.py L17-27）= pending/running/paused/**suspended**/completed/failed/cancelled/timeout——**无 waiting_approval/waiting_input**（那些是 `NodeExecutionStatus` L30-43，node 级）。前端 `executionStatusConfig` 却含 `waiting_approval`/`waiting_input`（status.ts L18-19）**却缺 `suspended`**——正好相反。
**改点:**
1. `config/status.ts` `executionStatusConfig` 增 `suspended: { label: '挂起中', icon: 'lucide--pause-circle', variant: 'warning' }`；`timeout` 已有（L17）。`waiting_approval`/`waiting_input` 可保留供 `StatusBadge type="execution"` 渲染 **node** 状态（NodeOverviewTab L95 即用 execution 类型渲染 node 状态）——但**不应**用于 execution 级筛选/统计。
2. `useExecutionsStore.ts` stats（L148-150）+ `executions/index.vue` stats（L129）：execution 级"等待"应判 `e.status === 'suspended'`，node 级 `waiting_approval` 仍可经 `node_executions.some(...)` 旁路保留（已有），但语义命名应区分。
3. `executions/index.vue` `statusOptions`（L61-69）补 `suspended`（"挂起中"）、`timeout`（"超时"）筛选项。
4. `ExecutionNode.vue` `statusBorderClass` map（L38-49）补 `suspended`/`timeout`（DAG 节点是 NodeExecution，理论无 suspended，但防御性补色 + 已有 waiting_event L45）。
**已就绪:** `useExecutionState.isActiveStatus`（L11）已含 `suspended`/`waiting_event`——状态判断侧无需改，仅展示配置缺失。

### Anti-Patterns to Avoid
- **读复数 `event_types`**：schema 单数，任何复数读取都恒空（TRIG-01 根因），新代码统一单数 + 兜底。
- **WS 广播新增必填键**：现有消费方（debug 工作流、其他订阅）只读已知键；新字段必须**可选**（`if status in (...)`）。
- **轮询 + WS 双写本地推断**：两路同时 `++` 计数会双计；以"服务端权威全量覆盖"为单一真相。
- **schedule 用数据库约束删除**：TextChoices 无 DB 约束，强行加 CHECK 反而破坏存量行——只 AlterField。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 事件 payload 过滤（状态/类型多选、嵌套字段） | 自写匹配逻辑 | `WorkflowTrigger.matches_event` / `_matches_filter` / `_get_nested_value`（trigger.py L104-166） | 已支持 list 成员匹配 + dotted-path，TRIG-01 只需填对 filter_config |
| dispatch 失败记录 | 新建 DispatchFailure 表 | 扩展 `TriggerLog.status`+`error_message`（feishu/models.py） | 已有状态枚举 + logs 页展示 + workflow_execution FK |
| REST 轮询 | 自写 setInterval | `usePolling`（已含卸载清理）/ vue-query refetchInterval | 已封装 start/stop/immediate/onUnmounted |
| 状态徽章 + unknown 兜底 | 各组件 switch-case | `getStatusConfig` + `StatusBadge`（status.ts L84-99） | 已有 fallback `{label:status, icon:help-circle}` |
| 死锁/变量错误结构化 | 前端重构 error 结构 | Phase 17/18 末行 JSON 约定（18-03-SUMMARY L70） | 后端已产出 `中文一句话\n{json}`，前端只 parse 末行 |
| 移除枚举值 migration | 手写 SQL | `migrations.AlterField`（参 0022/0003） | TextChoices 无 DB 约束，AlterField 即足够 |

**Key insight:** 本阶段几乎不需要"建造"，只需要"连通"——所有原语都已存在，缺的是字段对齐、可选字段透传、和断线降级的状态机接线。

## Runtime State Inventory

> TRIG-02（移除 schedule 枚举）属枚举/契约移除，需核查运行态残留。

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `Workflow.trigger_type='schedule'` 存量行（DB workflows 表） | 数据迁移可选：转 `manual`，或保留（TextChoices 无约束，移除 choice 后字符串仍合法、列表标签 fallback 显示原值）——Claude's Discretion，executor 依存量核查定 |
| Live service config | **无** — schedule 无 apscheduler 注册（`runapscheduler.py` 仅 repo polling 等系统任务，与工作流 trigger 无关 [VERIFIED: CONTEXT L68]）、无 webhook 端点、无外部服务持有 | 无 |
| OS-registered state | **无** — 无 cron/Task Scheduler/launchd 注册（schedule 从未实现 dispatch） | 无 |
| Secrets/env vars | **无** — schedule 无 secret/env 引用 | 无 |
| Build artifacts | **无** — 纯枚举移除，无编译产物；前端类型移除经 vite/vue-tsc 重编译生效 | 重新构建前端（CI 常规） |

**核查结论:** schedule 是纯"声明态僵尸"——除 DB 枚举字符串与前端展示标签外无任何运行态副作用。最安全策略：AlterField 移除 choice + 前端清理；存量行**可不迁移**（fallback 标签兜底）或迁 manual（更干净）。`executions` 列表筛选/统计**不受影响**：筛选按 `execution.status`（运行态枚举），与 `workflow.trigger_type`（触发类型）正交；列表 trigger_type 标签查表 fallback 即可。

## Common Pitfalls

### Pitfall 1: event_types 兜底破坏存量
**What goes wrong:** 完全删除 `event_types` 读取，导致历史用复数键保存的节点同步后 trigger 丢失。
**How to avoid:** 单数优先 + 复数兜底**并存**（Pattern 1 的 `event_type_list`）；加回归测试：构造仅含 `event_types` 的历史 config 断言仍生成 trigger。
**Warning signs:** 升级后历史飞书工作流突然不触发。

### Pitfall 2: project_ids / 排除规则无法用 matches_event 表达
**What goes wrong:** `_matches_filter`（trigger.py L137-147）**只支持正向 include**（actual == expected 或 actual ∈ list）；`exclude_project_ids`/`exclude_work_item_pattern`/`exclude_work_item_regex`（schemas.ts L141-143）是**排除**语义，写进 filter_config 会被当正向匹配，行为完全错误。`project_ids` 是 friday Space UUID（schemas.ts L134），而 payload 携带飞书 `project_key`，两者非同一标识。
**How to avoid:** 见 OQ-1。最小正确做法：TRIG-01 先只同步可正确表达的 `filter_status`/`filter_project_key`/`filter_work_item_type`；exclude_* 与 project_ids 要么扩展 `matches_event` 支持排除/Space→project_key 映射，要么明确标注为"暂不生效"留 v2，**绝不**塞进正向 filter_config 制造静默误匹配。
**Warning signs:** 配了排除却仍触发，或选了项目反而不触发。

### Pitfall 3: schedule 移除影响存量工作流报错
**What goes wrong:** 误加 DB CHECK 约束或 `RunPython` 误删行。
**How to avoid:** 仅 AlterField（参 0022）；若迁移存量只 `update(trigger_type='manual')` 不删行。
**Warning signs:** migration 报 IntegrityError 或工作流消失。

### Pitfall 4: TriggerLog 语义膨胀
**What goes wrong:** 为 manual/webhook 强塞 TriggerLog（该表强飞书语义：event_uuid/work_item_* 字段），污染 logs 页飞书事件视图。
**How to avoid:** TRIG-03 飞书路径直接复用（天然契合）；manual/webhook 若持久化需评估字段语义（见 OQ-2），优先最小——manual 用户即时可见结果，可不持久化。
**Warning signs:** logs 页混入非飞书的空 work_item 记录。

### Pitfall 5: WS 广播加字段破坏现有消费
**What goes wrong:** message 结构变动使现有订阅方（debug 流、列表）解析异常。
**How to avoid:** 只追加可选键（`error_message`/`error_code`），仅失败态写入；前端读取用 `data.error_message != null` 防御。
**Warning signs:** 非失败节点出现空 error_message，或旧消费方报错。

### Pitfall 6: 轮询与 WS 双写竞态
**What goes wrong:** 断线降级轮询全量覆盖 `currentExecution`，同时 WS 残留消息做 `completed_nodes++` 本地推断 → 计数双计/进度跳变。
**How to avoid:** 断线时 WS 本无消息流；以 `fetchExecution` 全量覆盖为单一真相；重连后首个全量刷新对齐，不混合本地推断与 REST。进度/状态严格服务端权威（D-05）。
**Warning signs:** 进度条回跳、failed_nodes 超过 total_nodes。

### Pitfall 7: suspended 对齐遗漏导致 raw 字符串
**What goes wrong:** 后端转 SUSPENDED（scheduler.py，Phase 18），前端 `executionStatusConfig` 无该键 → `getStatusConfig` fallback 显示原始 "suspended" + help-circle 图标。
**How to avoid:** config/status.ts 补全 ExecutionStatus 全集（pending/running/paused/suspended/completed/failed/cancelled/timeout）；加 vitest 断言每个后端枚举值都有非 fallback 配置。
**Warning signs:** 详情/列表出现英文 "suspended" 文本徽章。

## Code Examples

### 飞书事件匹配端到端（验证锚点）
```python
# 保存 → 同步 → 匹配 的契约链（TRIG-01 回归测试目标）
# 1. node.config = {"event_type": "WorkitemStatusEvent", "filter_status": ["s1"]}
# 2. async_sync_workflow_triggers(workflow) → WorkflowTrigger(event_type=..., filter_config=...)
# 3. FeishuEventHandler.find_workflows(ctx) → trigger.matches_event(event_type, payload)
#    matches_event: event_type 相等 + is_active + _matches_filter
#    _matches_filter: filter_config["cur_work_item_status.state_key"]=["s1"]
#                     _get_nested_value(payload, "cur_work_item_status.state_key") ∈ ["s1"]
```

### dispatch 失败状态（TRIG-03 断言形态）
```python
# server/feishu/models.py TriggerLogStatus: accepted/ignored/error/duplicate (L14-20)
# 断言：dispatch 抛异常 → trigger_log.status == "error" && error_message 非空
# 断言：无匹配工作流 → trigger_log.status == "ignored" && error_message 含 event_type
```

### 后端枚举 SSOT（OBS-03 对齐源）
```python
# server/workflows/models/execution.py
class ExecutionStatus:   # L17-27  execution 级
    pending running paused suspended completed failed cancelled timeout
class NodeExecutionStatus:  # L30-43  node 级（含 waiting_approval/waiting_input/waiting_event）
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| waiting → 永久 running 僵尸线程 + 5s 轮询 | waiting 即 `amark_suspended()` + execution_suspended hook，线程退出 | Phase 18-03 | OBS-03 须前端识别 suspended（之前几乎不出现，现在是等待态正常落点） |
| 死锁仅列节点名 | `diagnose_deadlock` 结构化 JSON（末行 json.loads） | Phase 18-01/03 | OBS-01 前端可 parse 死锁拓扑友好展示 |
| 变量解析失败静默替空串 | VAR-02 显式失败 + 可读引用错误（末行 JSON） | Phase 17 | OBS-01 结构化变量错误展示复用同一 parse |

**Deprecated/outdated:**
- `schedule` 触发类型：从未实现 dispatch，本阶段移除（TRIG-02）。
- 前端 `executionStatusConfig` 的 `waiting_approval`/`waiting_input` 作为 execution 级状态：实为 node 级，OBS-03 纠正。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | 存量 `trigger_type='schedule'` 行可不迁移（TextChoices 无 DB 约束，fallback 标签兜底） | Runtime State Inventory | 低——若某处对 trigger_type 做穷举 match 可能漏 case；executor 应 grep `trigger_type ==`/`schedule` 后端用法确认 |
| A2 | manual 触发持久化优先级最低（用户前端即时可见结果） | Pattern 3 / OQ-2 | 中——若产品要求 manual 失败也可审计，则需扩 TriggerLog 适用范围或新表 |
| A3 | WS 新增可选 `error_message` 键不破坏现有消费方 | Pattern 4 / Pitfall 5 | 低——前端消费方均按已知键解析；建议 grep WS 消费方确认无严格 schema 校验 |

**注:** 本表 3 项均为低/中风险实现策略选择，非事实性未验证断言；核心代码事实（行号/字段/枚举）全部 [VERIFIED: read]。

## Open Questions

1. **project_ids / exclude_* 规则如何落地（TRIG-01）**
   - What we know: schema 有 `project_ids`(Space UUID 数组)、`exclude_project_ids`、`exclude_work_item_pattern/regex`（schemas.ts L134,141-143）；`_matches_filter` 仅支持正向 include（trigger.py L137-147）。
   - What's unclear: project_ids（friday Space）→ payload（飞书 project_key）的映射；排除语义在 matches_event 无表达能力。
   - Recommendation: TRIG-01 先正确同步可表达的 filter_status/filter_project_key/filter_work_item_type（满足"保存→生成→匹配"核心契约）；project_ids/exclude_* 二选一——(a) 扩展 `matches_event` 增排除分支 + Space→project_key 映射，(b) 标注"暂不生效"留 v2。**禁止**塞进正向 filter_config。由 planner 据产品优先级裁定。

2. **manual/webhook dispatch 失败的最小持久化形态（TRIG-03）**
   - What we know: `TriggerLog` 强飞书语义（event_uuid/work_item_*）；webhook 路径（views.py L1565-1574）对空结果返回 no_workflows 但不落库；manual 无等价。
   - What's unclear: 是否复用 TriggerLog（语义膨胀风险，Pitfall 4）还是新建轻量表。
   - Recommendation: 飞书路径必做（D-03，天然契合）；webhook 可选——若做，复用 TriggerLog 用 webhook path 充 event_type；manual 默认不持久化（A2）。planner 定最小方案。

3. **suspended 在 DAG 节点（ExecutionNode）是否需要色映射**
   - What we know: suspended 是 execution 级，DAG 渲染的是 NodeExecution（node 级 waiting_*）。
   - Recommendation: 防御性补 suspended/timeout 色（ExecutionNode.vue L38-49）避免 fallback，但主要对齐点在 config/status.ts execution 徽章。

## Environment Availability

> 本阶段为纯代码/配置内部修改，无新增外部工具/服务/运行时依赖。

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Django + pytest-django | 后端触发/dispatch 测试 | ✓（既有） | 项目已装 | — |
| vitest + @vue/test-utils + happy-dom | 前端组件测试 | ✓（既有） | 项目已装 | — |
| channels（WS 广播） | OBS-01 | ✓（既有，hooks 已用） | — | — |

**Missing dependencies:** 无。Step 2.6 外部依赖审计：仅依赖项目内既有栈。

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework (backend) | pytest + pytest-asyncio + pytest-django（server/） |
| Framework (frontend) | vitest@^4 + @vue/test-utils + happy-dom（web/） |
| Config file | server/pyproject.toml（pytest）; web/vitest 配置（既有） |
| Quick run (backend) | `cd server && uv run pytest tests/test_trigger_dispatcher.py tests/test_trigger_views.py -x` |
| Quick run (frontend) | `cd web && pnpm vitest run src/config src/stores/__tests__` |
| Full suite (backend) | `cd server && uv run pytest tests/ -q` |
| Full suite (frontend) | `cd web && pnpm vitest run` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TRIG-01 | 单数 event_type 同步生成 WorkflowTrigger + 复数兜底 | unit/integration | `uv run pytest tests/workflows/test_trigger_sync.py -x` | ❌ Wave 0 |
| TRIG-01 | 保存→生成→find_workflows 命中端到端 | integration | `uv run pytest tests/workflows/test_trigger_sync.py::test_e2e_match -x` | ❌ Wave 0 |
| TRIG-01 | filter_status 数组写入 filter_config 正确 | unit | 同上文件 | ❌ Wave 0 |
| TRIG-02 | trigger_type choices 不含 schedule | unit | `uv run pytest tests/workflows/test_trigger_type_choices.py -x` | ❌ Wave 0 |
| TRIG-02 | 存量 schedule 行不报错（migration） | migration | `uv run pytest tests/workflows/test_migrations.py -x`（或 `migrate` 冒烟） | ❌ Wave 0 |
| TRIG-02 | 前端无 schedule 选项 | unit(vitest) | `pnpm vitest run src/pages/executions` | ⚠️ 扩展既有 |
| TRIG-03 | dispatch 异常 → TriggerLog.status=error | integration | `uv run pytest tests/test_trigger_dispatcher.py -k fail -x` | ⚠️ 扩展 L1-339 |
| TRIG-03 | 无匹配 → TriggerLog.status=ignored | integration | 同上 | ⚠️ 扩展 |
| OBS-01 | WS 广播 node_failed 含 error_message | unit | `uv run pytest tests/workflows/test_hooks.py -k broadcast -x` | ❌ Wave 0 |
| OBS-01 | 前端 node_failed 写入 NE.error_message | unit(vitest) | `pnpm vitest run src/stores/__tests__` | ❌ Wave 0 |
| OBS-01 | 结构化变量错误 JSON.parse 展示/回退 | unit(vitest) | `pnpm vitest run src/components/execution` | ❌ Wave 0 |
| OBS-02 | WS CLOSED → 启动轮询；重连停止 | unit(vitest) | `pnpm vitest run src/pages/executions/composables` | ❌ Wave 0 |
| OBS-03 | 每个 ExecutionStatus 值有非 fallback badge | unit(vitest) | `pnpm vitest run src/config` | ❌ Wave 0 |
| OBS-03 | stats 区分 execution(suspended) vs node(waiting_*) | unit(vitest) | `pnpm vitest run src/stores/__tests__` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** 受影响的单文件快速命令（上表 Quick run 子集）
- **Per wave merge:** `cd server && uv run pytest tests/workflows tests/test_trigger_dispatcher.py tests/test_trigger_views.py -q` + `cd web && pnpm vitest run`
- **Phase gate:** 后端 `uv run pytest tests/ -q` 全绿 + 前端 `pnpm vitest run` 全绿 + `pnpm lint`/`vue-tsc` 通过，再进 `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `server/tests/workflows/test_trigger_sync.py` — TRIG-01 同步/兜底/filter_config/端到端匹配（含 conftest workflow + feishu_event_trigger node 夹具）
- [ ] `server/tests/workflows/test_trigger_type_choices.py` — TRIG-02 choices 断言（轻量）
- [ ] `server/tests/workflows/test_hooks.py` — OBS-01 WebSocketBroadcastHook error_message 广播（mock channel_layer.group_send 断言 message dict）
- [ ] `web/src/stores/__tests__/useExecutionsStore.spec.ts` — OBS-01/03 node_failed 写 error_message + stats 语义
- [ ] `web/src/config/__tests__/status.spec.ts` — OBS-03 ExecutionStatus 全覆盖断言
- [ ] `web/src/pages/executions/composables/__tests__/useExecutionState.spec.ts` — OBS-02 WS 降级状态机
- [ ] 扩展 `server/tests/test_trigger_dispatcher.py`（已存在 L1-339）— TRIG-03 失败持久化断言

## Security Domain

> security_enforcement=true, ASVS Level 1。

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | 既有 JWT，本阶段不改鉴权 |
| V3 Session Management | no | — |
| V4 Access Control | yes | TriggerLog/execution 详情须沿用既有 ProjectScoped 权限（勿在新 WS 字段/REST 降级中绕过项目隔离） |
| V5 Input Validation | yes | filter_config 来自 node.config（已过 WorkflowGraphValidator/schema）；migration 数据迁移用 ORM 非裸 SQL |
| V6 Cryptography | no | — |
| V7 Error Handling/Logging | yes | TriggerLog error_message / WS error_message 须截断（防超大）且**不得泄露** node 输出值/凭证（沿用 Phase 18 死锁诊断"仅拓扑元数据"原则） |

### Known Threat Patterns for Django/Vue 可观测
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| error_message/广播泄露敏感输出或凭证 | Information Disclosure | 失败信息只含人类可读摘要 + 结构化拓扑（Phase 18 已确立零输出值泄露 [VERIFIED: 18-03 T-18-03]）；error_message 截断（如 [:2000]） |
| 轮询降级绕过项目权限取他人 execution | Elevation/IDOR | REST `/workflow-executions/{id}/` 复用既有对象级权限，不新增旁路 |
| error_message 超大文本 DoS（TextField 无限增长） | DoS | dispatch 失败 error_message 写入前截断 |
| WS 新字段被未授权订阅方读取 | Information Disclosure | WS 已按 `execution_{id}` group 隔离；新字段不扩大订阅面 |

## Sources

### Primary (HIGH confidence) — 代码勘察 [VERIFIED: read]
- `server/workflows/api/views.py` L80-166（async_sync_workflow_triggers）、L722-748（bulk_update）、L1545-1588（webhook dispatch）
- `server/workflows/models/workflow.py` L30-34（TriggerType）
- `server/workflows/models/trigger.py` L42-191（WorkflowTrigger / matches_event / _matches_filter / _get_nested_value）
- `server/workflows/models/execution.py` L17-43（ExecutionStatus/NodeExecutionStatus）、L437-515（NodeExecution 字段）
- `server/workflows/triggers/dispatcher.py` 全（dispatch 失败路径 L74-134）
- `server/workflows/triggers/handlers/feishu.py` 全（find_workflows L67-108）
- `server/feishu/models.py` L14-87（TriggerLogStatus / TriggerLog）
- `server/feishu/views.py` L485-731（TriggerLog 创建 + _dispatch_to_workflows）
- `server/workflows/hooks/builtin.py` L38-78（WebSocketBroadcastHook）
- `server/workflows/migrations/0022_remove_cancelled_status.py`、`0003_suspended_status.py`（AlterField 模式）
- `web/src/config/status.ts`、`web/src/stores/useExecutionsStore.ts`、`web/src/pages/executions/composables/useExecutionState.ts`、`web/src/composables/usePolling.ts`、`web/src/pages/executions/index.vue`、`web/src/components/execution/NodeOverviewTab.vue`、`web/src/components/execution/dag/ExecutionNode.vue`、`web/src/pages/executions/components/ExecutionStatusBanners.vue`、`web/src/types/workflow/schemas.ts`
- `.planning/phases/18-engine/18-01-SUMMARY.md`、`18-03-SUMMARY.md`（结构化错误/挂起语义/diagnose_deadlock 约定）
- `server/workflows/templates/daily_summary.json` L4（外部 cron→webhook 既定口径）

### Secondary (MEDIUM)
- 无外部检索（纯内部修复，无需）。

### Tertiary (LOW)
- 无。

## Metadata

**Confidence breakdown:**
- Standard Stack: HIGH — 零新依赖，全部既有原语经 read 确认
- Architecture: HIGH — 所有改点行号与 CONTEXT 锚点逐一吻合
- Pitfalls: HIGH — 根因（复数读取/排除语义/枚举错位/双写）均代码佐证
- Open Questions: 2 项需 planner 产品裁定（project_ids/exclude 落地、manual 持久化范围）

**Research date:** 2026-06-13
**Valid until:** 2026-07-13（内部代码事实稳定；除非引擎/触发器结构再变）




