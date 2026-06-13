# Phase 21: 触发模型与执行可观测 - Research

**Researched:** 2026-06-13
**Domain:** Django DRF/channels 触发链路 + Vue 3 执行可观测前端
**Confidence:** HIGH（全部基于代码勘察实证，零新依赖、零外部 API）

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01 [feishu 字段统一]**：统一以单数 `event_type` 为事实源；修复 `async_sync_workflow_triggers`（`server/workflows/api/views.py` L96-166）改读 `config.get("event_type")`，对历史 `event_types` 数组兜底；补齐 `project_ids`/排除规则/`filter_status` 数组写入 filter_config；加同步专项测试 + 字段对齐回归。
- **D-02 [schedule 处置]**：移除假功能（非实现）。后端从 `Workflow.TriggerType` 移除 `schedule`（migration 安全处理存量）；前端移除类型/标签/创建选项；文档化"外部 cron→webhook"。
- **D-03 [dispatch 失败可查]**：dispatch 失败（未知类型/校验失败/无匹配/启动异常）落到可查询记录。优先扩展 `TriggerLog`（飞书路径失败态 + error_message，不再恒 ACCEPTED）；manual/webhook 最小持久化由 planner 定。加失败持久化断言测试。
- **D-04 [节点失败实时可见]**：`WebSocketBroadcastHook`（`server/workflows/hooks/builtin.py` L43-78）node 广播加 `error_message`；前端 `node_failed` 更新 NodeExecution.error_message（不只 failed_nodes++）；展示 error_message/error_code/重试；Phase 17/18 结构化错误（末行 JSON）友好解析（解析失败回退纯文本）；DAG 失败节点 error tooltip。
- **D-05 [WS 断线降级轮询]**：详情页 WS 断线自动降级 REST 轮询（复用列表页 5s 模式）；断线期间持续拉取 execution + node；重连恢复 WS；进度/状态以服务端权威值为准；长时执行 UI 不冻结。
- **D-06 [状态枚举对齐]**：前端 `config/status.ts` 补 `suspended`/`timeout` badge；区分 execution(suspended) vs node(waiting_*)；列表筛选、DAG 节点色补 suspended/timeout/waiting_event；修正 stats 误用 execution 级 waiting_approval。

### Claude's Discretion
- schedule 存量行迁移精确策略、dispatch 失败记录最小持久化形态（扩 TriggerLog vs 新表）、WS 广播 payload 精确字段、结构化错误前端展示样式、wave 划分 —— 交 planner/executor 依代码现状定夺。

### Deferred Ideas (OUT OF SCOPE)
- 原生 schedule/cron 触发完整实现（apscheduler per-workflow job 生命周期）。
- 执行详情页全面可观测增强（节点级实时日志流等）。
- DAG 失败节点富交互（点击跳转/根因高亮）——可最小实现或留 TODO。
- 不改引擎执行/挂起/死锁语义（Phase 18 收口）、不改变量解析语义（Phase 17 定稿）。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| TRIG-01 | 飞书触发同步字段断裂修复，`WorkflowTrigger` 正确生成 | §TRIG-01 根因/改法、filter_config 语义、字段名分歧 |
| TRIG-02 | `schedule` 不再是假功能：移除该选项 | §TRIG-02 migration 安全性 + 前端移除清单 |
| TRIG-03 | dispatch 失败不被静默吞掉，记录到可查询位置 | §TRIG-03 飞书/manual/webhook 三路径方案 |
| OBS-01 | 节点失败清晰展示 error_message/失败变量引用/重试 | §OBS-01 WS payload + 前端解析 |
| OBS-02 | WS 断线降级 REST 轮询，进度以服务端权威值为准 | §OBS-02 状态机 + useIntervalFn 接法 |
| OBS-03 | 执行状态前后端枚举对齐（含 suspended） | §OBS-03 status.ts/stats/DAG 修正点 |
</phase_requirements>

## Summary

本阶段是 v0.4.0 收官，纯后端 Django + 前端 Vue 的契约对齐与可观测修复，**零新依赖、零外部服务、零新网络端点**。核心是六处"读写不对称"缺陷：① 触发同步读复数 `event_types` 实写单数 `event_type` 导致 `WorkflowTrigger` 表恒空；② `schedule` 是无 handler/无 dispatch 的死枚举；③ dispatch 失败路径全部 `return []` + structlog，飞书 `TriggerLog` 恒记 ACCEPTED；④ WS 广播不含错误信息，前端运行中失败需 full fetch；⑤ 详情页 WS 断线无 REST 降级；⑥ 前端 `executionStatusConfig` 缺 `suspended`、stats 在 execution 级误用 node 级 `waiting_approval`。

所有改动落在既有文件既有模式上：触发同步是一个纯函数级修复，schedule 移除是 `AlterField` + 数据迁移（有 0022 先例），dispatch 失败持久化复用既有 `TriggerLog.status/error_message`，WS 广播是给既有 `WebSocketBroadcastHook` message dict 加键（消费侧 `consumers.py` 全量 `json.dumps` 转发，加键安全），轮询降级复用 `useIntervalFn`/`store.fetchExecution`，状态对齐是 `config/status.ts` 补字典项。

**Primary recommendation:** 按"后端先修触发与持久化（pytest 守护）→ 后端 WS 广播加字段 → 前端状态对齐与失败展示 → 前端 WS 降级轮询"分波；TRIG-01 注意 `matches_event` 无排除语义、节点配置键存在 `space_ids`(后端) vs `project_ids`(前端) 分歧两个深坑。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 触发节点→WorkflowTrigger 同步 | API/Backend (`workflows/api/views.py`) | DB | 保存即同步，归属服务端写时一致性 |
| 飞书事件匹配工作流 | API/Backend (`triggers/handlers/feishu.py` + `WorkflowTrigger.matches_event`) | DB | 事件匹配是后端领域逻辑 |
| dispatch 失败可查记录 | API/Backend (`feishu/views.py` + `TriggerLog`) | DB | 失败语义服务端持久化 |
| schedule 枚举移除 | DB migration + Backend model | Frontend (展示移除) | choices 是模型契约，前端仅消费 |
| 节点失败实时推送 | API/Backend (`hooks/builtin.py` WS 广播) | Frontend (消费) | 服务端是状态权威源 |
| 节点失败展示/结构化解析 | Frontend (`NodeOverviewTab.vue`) | — | 纯展示层 |
| WS 断线降级轮询 | Frontend (`useExecutionState.ts` + store) | API (REST 权威值) | 客户端连接管理 + 服务端权威数据 |
| 执行状态枚举展示 | Frontend (`config/status.ts`) | Backend (枚举源) | 前端对齐后端 `ExecutionStatus` |

## Standard Stack

**无新增依赖。** 全部使用既有栈：

### 后端（既有）
| Library | 用途 | 锚点 |
|---------|------|------|
| Django 5.1+ ORM / migrations | TriggerType 移除、TriggerLog 扩展 | `server/workflows/migrations/`（最新 0026，新建 0027） |
| adrf 异步 DRF | `async_sync_workflow_triggers`、dispatch 视图 | `workflows/api/views.py` |
| channels | WS 广播（`group_send`） | `workflows/hooks/builtin.py`、`workflows/consumers.py` |
| structlog | 失败日志（保留 + 补持久化） | 全后端 |
| pytest + pytest-asyncio + pytest-django | 触发/同步/失败持久化测试 | `server/tests/` |

### 前端（既有）
| Library | 用途 | 锚点 |
|---------|------|------|
| Vue 3 `<script setup>` + Pinia | useExecutionsStore、useExecutionState | `web/src/stores/`、`web/src/pages/executions/composables/` |
| `@vueuse/core` `useIntervalFn` / `useWebSocket` | WS + 轮询降级状态机 | store 已用 `useWebSocket`/`useIntervalFn` |
| `@tanstack/vue-query` | 列表页 refetchInterval（详情页**不**强制迁移） | `executions/index.vue` L88-107 |
| vitest + @vue/test-utils + happy-dom | status/stores/组件测试 | `web/src/**/__tests__/` |

**Installation:** 无。`uv.lock` / `pnpm-lock.yaml` 不应产生 diff（执行约定：提交前 `git checkout -- server/uv.lock`）。

## Architecture Patterns

### 触发链路数据流（现状 → 修复后）

```text
[飞书 Webhook POST] → FeishuWebhookView.post (feishu/views.py L540+)
   ├─ 幂等/签名/项目/token 校验 → TriggerLog.acreate(status=ACCEPTED)  ← 恒 ACCEPTED（缺陷）
   ├─ _handle_workitem_* (拉取详情)
   └─ _dispatch_to_workflows(event_type, project, payload, trigger_log)
         └─ TriggerDispatcher.dispatch(context)  ← 失败全 return [] + structlog（静默）
               ├─ 1. 幂等键
               ├─ 2. handler = Registry.get(trigger_type)        → None? return []   (未知类型)
               ├─ 3. handler.validate(context)                   → errors? return [] (校验失败)
               ├─ 4. handler.find_workflows(context)              → []? return []     (无匹配)
               │      └─ WorkflowTrigger.objects.filter(event_type=..., workflow__project=...)
               │            → matches_event(event_type, payload)  ← 依赖 WorkflowTrigger 表非空
               └─ 5. engine.start_execution(...)                 → except? 吞掉      (启动异常)

[保存工作流] → bulk_update (workflows/api/views.py L722-748)
   └─ async_sync_workflow_triggers(workflow) (L96-166)
         读 config["event_types"](复数,恒空) → configured_triggers=[] → 旧 trigger 全 deactivate
         → WorkflowTrigger 表 effectively 空 → find_workflows 恒 []   ← TRIG-01 根因
```

**修复后**：同步读单数 `event_type` → 表正确生成；dispatch 各失败路径回写 `TriggerLog.status + error_message`（飞书路径），manual 已抛 400、webhook 已返回 no_workflows。

### 执行可观测数据流（现状 → 修复后）

```text
[引擎 scheduler] node 失败 → amark_failed(error_message, error_code) → emit "node_failed" hook
   └─ WebSocketBroadcastHook.execute (hooks/builtin.py L43-78)
         message = {type, event, execution_id, status, node_id, node_status}  ← 无 error（缺陷）
         → channel_layer.group_send(f"execution_{id}", message)
               └─ consumers.workflow_event → json.dumps(event) 全量转发  ← 加键安全

[前端详情页] useExecutionState.onMounted
   └─ fetchExecution(id) → connectWebSocket(id) (仅 active 时)
         wsData watch → handleWebSocketMessage (store L345-430)
               node_failed → failed_nodes++  ← 不更新 error_message（缺陷）
         wsStatus===CLOSED && active → wsDisconnected 横幅  ← 无 REST 轮询（缺陷）
```

**修复后**：广播补 `error_message`/`error_code`（失败时）；前端 `node_failed` 更新对应 NodeExecution；`wsDisconnected` 时启 `useIntervalFn` 轮询 `fetchExecution`，重连停。

### Pattern 1: 触发同步纯字段修复（TRIG-01）
**What:** `async_sync_workflow_triggers` 内将 `event_types`（复数数组）改为单数 `event_type`（字符串），保持其余 filter_config 构建不变。
**关键语义对照（`WorkflowTrigger._matches_filter` L125-147）：**
- filter_config 是 dict，键为点分路径，值为标量或**数组**；
- 数组值走 `actual_value in expected_value`（成员匹配）→ **`filter_status` 数组直接存入即可命中**，无需展开；
- 标量值走 `actual_value != expected_value` 全等。
- **filter_config 仅支持"等值/成员"正向匹配，无任何排除（exclude）语义** → `exclude_work_item_pattern`/`exclude_work_item_regex`/`exclude_space_ids` 无法通过现有 `matches_event` 生效（见 Pitfall 7）。

**修复骨架（示意，非最终代码）：**
```python
async for node in workflow.nodes.filter(node_type="feishu_event_trigger"):
    config = node.config or {}
    # 单数为准，历史复数兜底（取首项；多值历史数据可展开为多 trigger）
    event_type = config.get("event_type") or ""
    if not event_type:
        legacy = config.get("event_types") or []
        event_type = legacy[0] if legacy else ""
    if not event_type:
        continue
    filter_config = {}
    if config.get("filter_project_key"):
        filter_config["project_key"] = config["filter_project_key"]
    if config.get("filter_work_item_type"):
        filter_config["work_item_type_key"] = config["filter_work_item_type"]
    if config.get("filter_status"):  # 数组 → matches_event 成员匹配
        filter_config["cur_work_item_status.state_key"] = config["filter_status"]
    configured_triggers.append({"event_type": event_type, "filter_config": filter_config,
                                "node_id": str(node.id), "node_name": node.name})
```

### Pattern 2: choices 移除 = AlterField + 数据迁移（TRIG-02）
**What:** 从 `Workflow.TriggerType` 删 `SCHEDULE`。`choices` 是模型元数据，**DB 列层面不强制枚举**，故删除不会让存量 `trigger_type='schedule'` 行报错；但需 `AlterField` 迁移同步元数据，并建议数据迁移把存量 `schedule` 行转 `manual`（`default=TriggerType.MANUAL`）。
**先例:** `0022_remove_cancelled_status.py` 即纯 `AlterField` 收窄 choices。新建 `0027_remove_schedule_trigger_type.py`（依赖 0026）。
**Example（数据迁移段）：**
```python
def forward(apps, schema_editor):
    Workflow = apps.get_model("workflows", "Workflow")
    Workflow.objects.filter(trigger_type="schedule").update(trigger_type="manual")
operations = [migrations.RunPython(forward, migrations.RunPython.noop),
              migrations.AlterField(model_name="workflow", name="trigger_type", field=models.CharField(...))]
```

### Pattern 3: dispatch 失败回写 TriggerLog（TRIG-03）
**What:** `_dispatch_to_workflows` 已持有 `trigger_log`。在 `dispatch` 返回空（无匹配/校验失败/未知类型）或 `except` 时，回写 `trigger_log.status = TriggerLogStatus.ERROR/IGNORED` + `error_message`。
**取舍：**
- **最小方案（推荐）**：`TriggerDispatcher.dispatch` 当前只返回 `list[WorkflowExecution]`，无法区分"无匹配"vs"启动失败"。在 **caller 侧**（`_dispatch_to_workflows`）判定：`if not executions: trigger_log.status = IGNORED, error_message="无匹配的活跃触发器或校验未通过"`；`except` 块设 `status=ERROR, error_message=str(e)`。避免 dispatcher 反向依赖 feishu 模型（保持分层）。
- **更彻底方案**：dispatcher 返回 `DispatchOutcome(executions, reason)` 结构体，caller 据 reason 精确落库。CONTEXT 允许 planner 定；若选此需改 3 处 caller（manual/webhook/feishu）。
- `TriggerLogStatus` 现有 `ACCEPTED/IGNORED/ERROR/DUPLICATE`（`feishu/models.py` L14-20），**无需新增枚举**。

### Pattern 4: WS 断线 → 轮询状态机（OBS-02）
**What:** 在 `useExecutionState` 内新增 `useIntervalFn`，仅 `wsDisconnected.value === true && isActiveStatus(status)` 时 `resume()` 轮询 `store.fetchExecution(executionId)`；`wsStatus` 回到非 CLOSED 或进入终态时 `pause()`。
**状态机：**
```text
WS OPEN/CONNECTING        → poller.pause()    （WS 推送为主）
WS CLOSED && active       → poller.resume()   （5s 拉 fetchExecution，服务端权威覆盖本地）
WS reconnect→OPEN         → poller.pause()    （autoReconnect retries:3，store L124-127）
status→terminal           → poller.pause() + disconnectWebSocket（已有 watch L137-149）
```
**权威值：** `fetchExecution` 整体替换 `currentExecution`（store L207），覆盖 WS 本地增量（`failed_nodes++` 等可能漂移），天然以服务端为准。轮询与 WS **互斥**（仅断线时轮询）规避双写竞态。

### Anti-Patterns to Avoid
- **把 schedule 移除做成删 DB 列/删数据**：trigger_type 是普通 CharField，仅收窄 choices；删行/删列会破坏存量工作流。
- **dispatcher 直接 import feishu.TriggerLog**：跨层耦合；失败落库应在 caller 侧或经返回结构体。
- **前端 node_failed 仅 failed_nodes++**：丢失 error_message；须更新对应 NodeExecution 对象。
- **WS 与轮询同时活跃**：双写 progress/计数竞态；务必互斥。
- **执行级判 `status==='waiting_approval'`**：execution 永远不会是该值（它是 NodeExecutionStatus）；应判 `suspended` + node 级 `waiting_*`。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 定时轮询 | 自写 setInterval + 清理 | `@vueuse/core` `useIntervalFn`（store 已用） | 自动 onUnmounted 清理、pause/resume API |
| WS 重连 | 自写重连循环 | `useWebSocket({autoReconnect:{retries:3}})`（已配） | 既有配置，勿重复造 |
| 事件过滤匹配 | 新写匹配引擎 | `WorkflowTrigger.matches_event`/`_matches_filter`（已支持数组成员匹配） | 已有点分路径 + 列表语义 |
| choices 移除 | 手改 DB | Django `AlterField` + `RunPython`（0022 先例） | 迁移可回滚、可重放 |
| 状态徽章 | 各组件硬编码 | `config/status.ts` + `getStatusConfig`（含 fallback） | 单一事实源 + raw 兜底 |
| 结构化错误解析 | 正则切割 | `JSON.parse(lastLine)` + try/catch 回退纯文本 | Phase 17/18 约定末行可独立 `json.loads` |

**Key insight:** 本阶段几乎所有"能力"在仓库已存在，问题是**字段对齐与接线**，而非新建机制。新建任何机制都是范围蔓延。

## Runtime State Inventory

> TRIG-02 涉及枚举移除（schedule），按"删除/迁移"要求逐类核查。

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `Workflow.trigger_type='schedule'` 存量行（DB `workflows` 表）。无 `ScheduleHandler`/无 apscheduler per-workflow job/无画布 schedule 节点（仅枚举 + 列表标签残留，CONTEXT 已勘察）。`WorkflowExecution.trigger_type` 实际值来自 `TriggerContext`（manual/webhook/feishu），**从不为 schedule**（无 handler）。 | 数据迁移：`Workflow.objects.filter(trigger_type="schedule").update(trigger_type="manual")` + AlterField |
| Live service config | apscheduler（`runapscheduler.py`）仅用于仓库轮询等系统任务，**与工作流 trigger 无耦合**（CONTEXT 勘察 + Phase 18 SUMMARY 佐证 check_timeouts 独立）。无外部 cron 注册指向 schedule 工作流。 | None — 无外部调度注册需清理 |
| OS-registered state | 无 OS 级注册（无 launchd/systemd/Task Scheduler 引用 schedule 工作流）。 | None |
| Secrets/env vars | 无 env/secret 以 schedule 命名或读取。 | None |
| Build artifacts | 前端编译产物含 schedule 标签字符串（`executions/index.vue` L258/L265、`ExecutionCard.vue` L29、`ExecutionHistoryCard.vue` L54、`useWorkflowsStore.ts` L52 类型）+ 测试夹具（`executions-datatable.test.ts`、`logs-datatable.test.ts`）。 | 源码移除后随构建自动更新；测试夹具按需更新 |

**前端 schedule 移除清单（grep 实证）：**
- `web/src/stores/useWorkflowsStore.ts` L52：`trigger_type: 'manual' | 'webhook' | 'schedule' | 'event'` → 删 `'schedule'`
- `web/src/pages/executions/index.vue` L258（标签）、L265（图标）：删 schedule 项
- `web/src/components/execution/ExecutionCard.vue` L29：删 `schedule: '定时触发'`
- `web/src/components/execution/ExecutionHistoryCard.vue` L54：删 `schedule: '定时'`
- `CreateWorkflowModal`：勘察未在 grep 命中 schedule，planner 执行时再确认是否有创建选项（CONTEXT 假设存在，实测可能已无）
- 测试夹具（`executions-datatable.test.ts` L34/L92、`logs-datatable.test.ts` L37）：含 schedule 测试数据 —— 保留 label fallback 即可，或同步更新
- **保留防御**：`getStatusConfig`/label map 对未知 trigger_type 须有 fallback（避免存量 execution 显示 raw）

## Common Pitfalls

### Pitfall 1: 节点配置键存在前后端命名分歧（TRIG-01 深坑）
**What goes wrong:** 后端节点定义 `feishu_event.py` config_schema 用 `space_ids`/`exclude_space_ids`（L36-42、L69-75）；前端 zod schema `schemas.ts` 用 `project_ids`/`exclude_project_ids`（L134、L141）。CONTEXT D-01 说"补 project_ids"。两套键名不一致，同步函数当前两者都没读。
**Why:** Friday "空间(space)" 与飞书 "project" 概念混用，历史命名漂移。
**How to avoid:** planner 须先确认前端实际写入 config 的键名（以 `schemas.ts` 为准 = `project_ids`），并对齐后端节点 schema 与同步函数读取同一键。**注意：`project_ids`（监听哪些 Friday 空间）语义上不进 filter_config —— `find_workflows` 已按 `workflow__project=context.project` 做空间归属过滤，而一个 Workflow 只属于一个 project**。多空间监听与"单工作流单 project"模型不匹配 → 见 Open Questions Q1。
**Warning signs:** 同步后 trigger 生成但空间过滤行为不符预期。

### Pitfall 2: `matches_event` 无排除语义（TRIG-01 深坑）
**What goes wrong:** `_matches_filter`（trigger.py L125-147）只做"等值/列表成员"正向匹配。`exclude_work_item_pattern`/`exclude_work_item_regex`/`exclude_space_ids` 三个排除字段**无法通过 filter_config 生效**。
**How to avoid:** planner 决策——(a) 扩展 `matches_event`/`_matches_filter` 支持 `exclude_*` 约定键（需正则 ReDoS 防护，见 Security）；或 (b) 本阶段仅同步正向过滤，排除规则记为"已采集未接线"留 TODO（符合 D-04 "可最小实现"精神）。**勿声称排除已生效。**

### Pitfall 3: event_types 兜底破坏存量
**What goes wrong:** 历史节点 config 可能存了 `event_types` 数组（旧 UI）。只读单数会丢失。但当前 UI/schema 已是单数 `event_type`（default `''`）。
**How to avoid:** 兜底逻辑 `event_type or event_types[0]`；若历史数据有多值，展开为多条 trigger（unique_together 已注释掉，允许同 workflow 多 trigger）。加回归测试覆盖"仅复数历史数据"case。

### Pitfall 4: schedule 移除影响存量工作流校验
**What goes wrong:** AlterField 收窄 choices 后，DRF serializer / model `full_clean` 对存量 `schedule` 行校验会失败（choices 校验）。
**How to avoid:** 数据迁移**先于**或同迁移内把 schedule→manual；前端 label map 保留 fallback。

### Pitfall 5: TriggerLog 语义膨胀（TRIG-03）
**What goes wrong:** `TriggerLog` 是飞书 webhook 专用（`event_uuid` unique、work_item_* 字段、db_table `trigger_logs`）。强行复用于 manual/webhook dispatch 失败会污染语义、`event_uuid` 唯一约束冲突。
**How to avoid:** TRIG-03 **聚焦飞书路径**（真正的静默 ACCEPTED 缺陷）。manual 已 `raise TriggerValidationError`（API 400 可见，views.py L487-488）；webhook 已返回 `{status:"no_workflows"}`（L1570-1574）。manual/webhook 失败已对调用方可见，无需强塞 TriggerLog。若坚持统一记录，新建轻量模型而非复用。

### Pitfall 6: WS 广播加字段破坏消费者
**What goes wrong:** 担心给 message dict 加 `error_message`/`error_code` 破坏 WS 消费。
**Reality（已验证）:** `consumers.workflow_event`（consumers.py L205-208）`json.dumps(event)` **全量转发**，无键白名单；前端 `handleWebSocketMessage` 解构已知键、忽略多余键。加键安全。**仅在失败时加**（避免每条消息膨胀）。

### Pitfall 7: 轮询与 WS 双写竞态（OBS-02）
**What goes wrong:** 若轮询 `fetchExecution` 与 WS `handleWebSocketMessage` 同时活跃，progress/计数双写漂移。
**How to avoid:** 轮询仅在 `wsDisconnected` 时启用（与 WS 推送互斥）；`fetchExecution` 整体替换 currentExecution（服务端权威）天然纠偏 WS 本地增量漂移。

### Pitfall 8: suspended 对齐遗漏导致 raw 字符串（OBS-03）
**What goes wrong:** `executionStatusConfig`（status.ts L9-21）缺 `suspended`；Phase 18 末端等待 → `ExecutionStatus.SUSPENDED`，前端徽章走 fallback 显示 raw "suspended"。
**How to avoid:** 补 `suspended`（挂起中）；`timeout` 已存在（L17）勿重复。修正 stats（store L148-150）execution 级判 `suspended` 而非 `waiting_approval`。区分：execution 等待态 = `suspended`；node 等待态 = `waiting_approval`/`waiting_input`/`waiting_event`。

### Pitfall 9: hook 时 error_message 是否已落库
**What goes wrong:** WS 广播读 `node_execution.error_message` 时若该字段未写入则为空。
**Reality（已验证）:** scheduler.py 先 `amark_failed(last_error, error_code)`（L1198/L1221）**再** emit `node_failed` hook（L1205/L1223）。hook 收到的 node_execution 对象已含 error_message/error_code。直接读取即可（无需 refetch）。

## Code Examples

### OBS-01：WS 广播补错误字段（后端，hooks/builtin.py）
```python
# WebSocketBroadcastHook.execute 内，node_execution 分支补充：
node_execution = kwargs.get("node_execution")
if node_execution:
    message["node_id"] = str(node_execution.node_id)
    message["node_status"] = node_execution.status
    # OBS-01：失败时附带错误，前端无需 full fetch
    if node_execution.status == "failed":
        message["error_message"] = node_execution.error_message or ""
        message["error_code"] = node_execution.error_code or ""
    if event == "node_debug_paused":
        message["node_input"] = node_execution.input_data or {}
        message["node_output"] = node_execution.output_data or {}
```

### OBS-01：前端 node_failed 更新 error_message（store handleWebSocketMessage）
```typescript
// 在 node_id && node_status 分支已能定位 nodeExec；node_failed 时补字段：
else if (event === 'node_failed') {
  currentExecution.value.failed_nodes++
  const nodeExec = currentExecution.value.node_executions.find(ne => ne.node === node_id)
  if (nodeExec) {
    if (data.error_message != null) nodeExec.error_message = data.error_message
    if (data.error_code != null) nodeExec.error_code = data.error_code
  }
}
```

### OBS-01：结构化错误末行 JSON 友好解析（NodeOverviewTab.vue）
```typescript
// Phase 17 变量错误 / Phase 18 死锁诊断：error_message = "中文一句话\n{json}"，末行可独立解析
const structuredError = computed(() => {
  const msg = props.nodeExecution.error_message
  if (!msg) return null
  const lastLine = msg.trim().split('\n').at(-1) ?? ''
  try {
    const parsed = JSON.parse(lastLine)
    return (parsed && typeof parsed === 'object') ? parsed : null
  }
  catch { return null }  // 回退纯文本（既有 <pre> 展示）
})
// Phase 18 死锁 JSON 形如：{"reason":"deadlock","pending":[{"node","short_id","waiting_on":[{"node","short_id","status","handle"}]}]}
```

### OBS-02：详情页 WS 断线轮询降级（useExecutionState.ts）
```typescript
import { useIntervalFn } from '@vueuse/core'
const { pause: stopPoll, resume: startPoll } = useIntervalFn(
  () => { store.fetchExecution(executionId.value) },  // 服务端权威值整体覆盖
  5000,
  { immediate: false },
)
watch([wsDisconnected, () => currentExecution.value?.status], ([disconnected, status]) => {
  if (disconnected && isActiveStatus(status)) startPoll()
  else stopPoll()
})
onUnmounted(() => stopPoll())
```

### OBS-03：状态字典补 suspended（config/status.ts）
```typescript
export const executionStatusConfig: Record<string, StatusConfig> = {
  // ...既有...
  suspended: { label: '挂起中', icon: 'lucide--pause-circle', variant: 'warning', animate: false },
  // timeout 已存在；waiting_approval/waiting_input 保留供 node 级展示
}
// stats 修正（useExecutionsStore.ts L148-150）：
// 旧：e.status === 'waiting_approval' || node.some(...)
// 新：e.status === 'suspended' || e.node_executions?.some(n => ['waiting_approval','waiting_input','waiting_event'].includes(n.status))
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| execution 等待态用 `waiting_approval` | execution 用 `SUSPENDED`，node 用 `waiting_*` | Phase 18（0003/scheduler L942-987） | 前端必须区分两层 |
| 死锁只列节点名 | `diagnose_deadlock` 结构化 JSON（末行 `json.loads`） | Phase 18-01 | 前端可解析展示 |
| 变量解析失败静默空串 | 显式失败 + 结构化 error_message | Phase 17 | 前端可解析失败引用 |
| 5s DB 轮询保活线程 | 等待即挂起、线程退出 | Phase 18-03 | execution 真实 SUSPENDED |

**Deprecated/outdated:**
- `schedule` 触发类型：从未实现 handler/dispatch，本阶段移除。
- 前端 execution 级 `waiting_approval` 判断：误用，Phase 18 后应为 `suspended`。

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework (后端) | pytest + pytest-asyncio + pytest-django（`server/pyproject.toml`） |
| Framework (前端) | vitest 4 + @vue/test-utils + happy-dom |
| Config file | `server/pyproject.toml` `[tool.pytest.ini_options]`；`web/vitest.config.*` |
| Quick run (后端) | `cd server && uv run pytest tests/test_trigger_dispatcher.py tests/workflows/ -x -q` |
| Quick run (前端) | `cd web && pnpm vitest run src/config/__tests__/status.test.ts` |
| Full suite (后端) | `cd server && uv run pytest -q` |
| Full suite (前端) | `cd web && pnpm vitest run` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TRIG-01 | 保存 feishu_event_trigger(单数 event_type) → WorkflowTrigger 生成 | integration | `uv run pytest tests/test_sync_workflow_triggers.py -x` | ❌ Wave 0 |
| TRIG-01 | event_types 复数历史数据兜底 | unit | 同上::test_legacy_event_types_fallback | ❌ Wave 0 |
| TRIG-01 | filter_status 数组 → matches_event 成员命中（端到端） | integration | `uv run pytest tests/test_sync_workflow_triggers.py::test_find_workflows_hit -x` | ❌ Wave 0 |
| TRIG-02 | schedule→manual 数据迁移 + choices 收窄 | migration | `uv run pytest tests/test_migrations_trigger_type.py -x` | ❌ Wave 0 |
| TRIG-03 | 飞书无匹配/校验失败/启动异常 → TriggerLog.status≠ACCEPTED + error_message | integration | `uv run pytest tests/test_trigger_dispatcher.py -k failure_persist -x` | ⚠️ 扩展现有 |
| OBS-01 | 失败时 WS message 含 error_message/error_code | unit | `uv run pytest tests/workflows/test_hooks_broadcast.py -x` | ❌ Wave 0 |
| OBS-01 | 前端 node_failed 更新 NodeExecution.error_message | unit | `pnpm vitest run src/stores/__tests__/useExecutionsStore.spec.ts` | ❌ Wave 0 |
| OBS-01 | 结构化错误末行 JSON 解析 + 回退 | unit | `pnpm vitest run src/components/execution/__tests__/NodeOverviewTab.spec.ts` | ❌ Wave 0 |
| OBS-02 | wsDisconnected && active → 启轮询；重连/终态停 | unit | `pnpm vitest run .../useExecutionState.spec.ts` | ❌ Wave 0 |
| OBS-03 | executionStatusConfig.suspended 存在 + 非 raw fallback | unit | `pnpm vitest run src/config/__tests__/status.test.ts` | ⚠️ 扩展现有 |
| OBS-03 | stats execution 级判 suspended（非 waiting_approval） | unit | useExecutionsStore.spec.ts::stats | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** 对应 quick run（后端单测试文件 / 前端单 spec）
- **Per wave merge:** `cd server && uv run pytest tests/workflows/ tests/test_trigger*.py -q` + `cd web && pnpm vitest run`
- **Phase gate:** 后端全量 `uv run pytest -q` 全绿 + 前端 `pnpm vitest run` 全绿，再 `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `server/tests/test_sync_workflow_triggers.py` — TRIG-01 同步 + 兜底 + 端到端命中
- [ ] `server/tests/test_migrations_trigger_type.py` — TRIG-02 数据迁移（或并入既有 migration 测试）
- [ ] `server/tests/workflows/test_hooks_broadcast.py` — OBS-01 WS payload 断言
- [ ] `web/src/stores/__tests__/useExecutionsStore.spec.ts` — node_failed 更新 + stats（**注意：当前无 store 单测**）
- [ ] `web/src/components/execution/__tests__/NodeOverviewTab.spec.ts` — 结构化错误解析
- [ ] `web/src/pages/executions/composables/__tests__/useExecutionState.spec.ts` — 轮询状态机
- [ ] 扩展 `server/tests/test_trigger_dispatcher.py` — 失败持久化断言
- [ ] 扩展 `web/src/config/__tests__/status.test.ts` — suspended 断言

## Security Domain

> `security_enforcement: true`, ASVS Level 1, `security_block_on: high`。本阶段无新增网络端点/鉴权路径，主要风险在输入校验与信息泄露。

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | 复用既有 JWT / 飞书 webhook token（`verify_webhook_token`） |
| V3 Session Management | no | 无变更 |
| V4 Access Control | yes | TriggerLog 查看走既有 `ProjectScopedQuerysetMixin`/权限；WS `execution_{id}` group 复用既有鉴权；失败 error_message 不得跨项目泄露 |
| V5 Input Validation | yes | `exclude_work_item_regex` 用户正则 → ReDoS 风险；filter_config 用户控键值 |
| V6 Cryptography | no | 无加密变更 |
| V7 Error Handling/Logging | yes | error_message 入 WS/TriggerLog 须避免敏感输出值泄露（Phase 18 死锁诊断已仅含拓扑元数据） |

### Known Threat Patterns for Django + channels

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| 用户正则 `exclude_work_item_regex` 导致 ReDoS | DoS | 若本阶段接线排除规则：用 `re` 编译 + 超时/长度上限，或限定为非回溯安全子集；否则不接线（Pitfall 2） |
| WS 广播 error_message 泄露节点输出值/凭证 | Information Disclosure | 仅广播 error_message/error_code（已是脱敏文案）；死锁诊断 Phase 18 已保证零输出值（`diagnose_deadlock` 不接收 node_outputs） |
| TriggerLog error_message 跨项目可见 | Information Disclosure | TriggerLog 查询已 project 作用域；error_message 用领域文案非原始 payload |
| 结构化错误前端 `JSON.parse` 注入 | Tampering | `JSON.parse` 仅解析末行 + try/catch；渲染走 Vue 文本绑定（非 v-html），无 XSS 面 |
| schedule 移除导致存量触发器静默失效误判 | Repudiation | 数据迁移转 manual，行为可追溯（迁移可回滚） |

**关键：前端结构化错误展示务必用文本插值（`{{ }}` / `<pre>`），禁用 `v-html`**，防止 error_message 内容 XSS。

## Sources

### Primary (HIGH confidence) — 代码勘察实证
- `server/workflows/api/views.py` L96-166（async_sync_workflow_triggers）、L455-501（manual execute）、L722-748（bulk_update）、L1540-1588（webhook）
- `server/workflows/models/trigger.py` L8-191（WorkflowTrigger/matches_event/_matches_filter/TriggerEventType）
- `server/workflows/models/workflow.py` L30-34（TriggerType）、L59-62
- `server/workflows/models/execution.py` L17-43（ExecutionStatus/NodeExecutionStatus）
- `server/workflows/triggers/dispatcher.py` L45-157（dispatch 失败路径）
- `server/workflows/triggers/handlers/feishu.py` L67-121（find_workflows）
- `server/workflows/nodes/triggers/feishu_event.py` L26-90（config_schema 键名）
- `server/feishu/views.py` L540-731（webhook + _dispatch_to_workflows + TriggerLog 状态点）
- `server/feishu/models.py` L14-87（TriggerLogStatus/TriggerLog）
- `server/workflows/hooks/builtin.py` L38-78（WebSocketBroadcastHook）
- `server/workflows/consumers.py` L205-208（workflow_event 全量转发）
- `server/workflows/engine/scheduler.py` L1198-1223（amark_failed 先于 node_failed hook）、L942-987（_finalize_run_state 死锁/挂起）
- `server/workflows/migrations/0022_remove_cancelled_status.py`（choices 收窄先例）；最新迁移 0026
- `web/src/config/status.ts` L9-21（executionStatusConfig 缺 suspended）
- `web/src/stores/useExecutionsStore.ts` L122-170（WS/useIntervalFn）、L148-150（stats 误用）、L345-430（handleWebSocketMessage node_failed）
- `web/src/pages/executions/composables/useExecutionState.ts` L9-149（wsDisconnected/生命周期）
- `web/src/pages/executions/index.vue` L88-107（vue-query refetchInterval 5s）、L258/L265（schedule 标签）
- `web/src/types/workflow/schemas.ts` L129-144（feishuEventTriggerConfigSchema 键名分歧）
- `web/src/components/execution/NodeOverviewTab.vue` L133-148（错误展示缺 error_code/结构化）
- `web/src/components/execution/dag/ExecutionNode.vue` L38-50（状态色映射缺 suspended/timeout）
- Phase 18 `18-01-SUMMARY.md`/`18-03-SUMMARY.md`（死锁 JSON 结构、SUSPENDED 语义、check_timeouts 独立）

### Secondary (MEDIUM confidence)
- `web/src/config/__tests__/status.test.ts`、`server/tests/test_trigger_dispatcher.py`（测试范式参考）

### Tertiary (LOW confidence)
- 无外部 WebSearch 依赖（纯内部代码契约对齐，无需第三方文档）

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | 前端实际写入 config 的键为 `project_ids`/`exclude_project_ids`（schemas.ts），与后端节点 `space_ids` 不一致 | Pitfall 1 | 同步读错键 → trigger 仍空 |
| A2 | CreateWorkflowModal 可能已无 schedule 创建选项（grep 未命中） | Runtime Inventory | 漏删一处前端入口 |
| A3 | manual/webhook 失败已通过 API 响应可见，TRIG-03 可仅聚焦飞书 | Pitfall 5 | 若要求统一记录则需新模型 |
| A4 | 排除规则（exclude_*）当前无 matches_event 支持，本阶段可留 TODO | Pitfall 2 | 若 UAT 要求排除生效则需扩展 matches_event |

## Open Questions

1. **`project_ids`/多空间监听语义** — 一个 Workflow 只属于一个 project，`find_workflows` 已按 project 过滤；"监听多个空间"与单工作流模型冲突。
   - 已知：filter_config 是事件 payload 字段匹配，非空间归属。
   - 不清楚：planner 是否将 `project_ids` 落入 filter_config（payload.project_key 成员匹配）还是仅作前端展示。
   - 建议：落 `filter_config["project_key"] = project_ids`（payload 含 project_key/project_simple_name，成员匹配可行），与单 project 归属叠加。
2. **排除规则是否本阶段接线** — `matches_event` 无排除语义。
   - 建议：本阶段同步正向过滤 + filter_status 数组；排除规则记 TODO（D-04 "可最小实现"），或 planner 决策扩展 matches_event（含 ReDoS 防护）。
3. **dispatch 失败粒度** — 是否需区分"无匹配"vs"启动异常"vs"校验失败"。
   - 建议：最小方案 caller 侧二分（空→IGNORED、异常→ERROR）即满足 TRIG-03"用户看到原因"；精确 reason 需 DispatchOutcome 结构体（更大改动）。

## Environment Availability

> 本阶段为纯代码/迁移变更，依赖既有 pytest/vitest/uv/pnpm 工具链，无新增外部服务。Step 2.6 实质 SKIPPED（无新外部依赖）。既有 SQLite/内存 channel layer 足以本地测试 WS 广播。

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 零新依赖，全既有栈
- Architecture: HIGH — 全部基于行号锚点代码勘察 + Phase 18 SUMMARY 佐证
- Pitfalls: HIGH — 字段分歧/排除语义/双写竞态均代码验证
- Open questions: MEDIUM — project_ids 语义与排除规则接线需 planner/UAT 定夺

**Research date:** 2026-06-13
**Valid until:** 2026-07-13（内部代码契约，稳定；除非 Phase 17/18 语义再变）

---
*Phase: 21-observability*



