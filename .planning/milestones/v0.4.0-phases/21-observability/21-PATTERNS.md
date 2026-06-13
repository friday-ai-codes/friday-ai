# Phase 21: 触发模型与执行可观测 - Pattern Map

**Mapped:** 2026-06-13
**Files analyzed:** 13 修改 + 7 新建测试 = 20
**Analogs found:** 18 / 20（含同文件内自我修改型）

> 本阶段是"连通"而非"建造"——绝大多数改点是 **就地修改既有文件**，analog 即文件自身的相邻范式或姊妹模块。下表 Match Quality 中 `self-edit` 表示在该文件内复用同文件已有写法；`sibling` 表示从同类姊妹文件复制范式。

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `server/workflows/api/views.py`（`async_sync_workflow_triggers` L96-166） | service（同步函数） | transform | 同函数现有循环 + `trigger.py _matches_filter` 契约 | self-edit |
| `server/workflows/models/workflow.py`（`TriggerType` L30-34） | model（枚举） | config | `execution.py ExecutionStatus` TextChoices | exact |
| `server/workflows/migrations/00XX_remove_schedule.py`（新建） | migration | batch | `0022_remove_cancelled_status.py` / `0003_suspended_status.py` AlterField | exact |
| `server/feishu/views.py`（`_dispatch_to_workflows` L693-731） | service（dispatch） | event-driven | 同方法成功分支 L712-724 + `TriggerLog` 字段 | self-edit |
| `server/workflows/api/views.py`（webhook dispatch L1540-1588，可选） | controller | request-response | 同视图 L1570-1574 no_workflows 分支 | self-edit |
| `server/workflows/hooks/builtin.py`（`WebSocketBroadcastHook` L55-75） | hook（广播） | pub-sub | 同 Hook `node_debug_paused` 可选键 L67-70 | self-edit |
| `web/src/config/status.ts`（`executionStatusConfig` L9-21） | config（枚举映射） | transform | 同文件其他 `*StatusConfig` 条目 | self-edit |
| `web/src/stores/useExecutionsStore.ts`（`node_failed` L374-376 / stats L144-154） | store | event-driven | 同 store `sub_step.update` 写 NE L420-428 | self-edit |
| `web/src/pages/executions/composables/useExecutionState.ts`（WS 降级状态机） | composable（hook） | streaming→polling | `usePolling.ts` start/stop + 同文件 `wsDisconnected` L74-81 | sibling |
| `web/src/components/execution/NodeOverviewTab.vue`（error_code + 变量错误） | component | request-response | 同组件错误信息块 L133-148 + 重试行 L115-120 | self-edit |
| `web/src/components/execution/dag/ExecutionNode.vue`（DAG 色 L38-49） | component | transform | 同组件 `statusBorderClass` map | self-edit |
| `web/src/pages/executions/index.vue`（标签 L255-267 / statusOptions L61-69 / stats L129） | page | CRUD | 同文件 `triggerTypeLabels` / `statusOptions` 数组 | self-edit |
| `web/src/stores/useWorkflowsStore.ts`（trigger_type 类型 L52） | store（type） | config | 同行联合类型 | self-edit |
| `web/src/components/execution/ExecutionCard.vue` L29 / `ExecutionHistoryCard.vue` L54（schedule 标签） | component | transform | 同文件标签 map | self-edit |
| **新建** `server/tests/workflows/test_trigger_sync.py`（TRIG-01） | test | integration | `test_trigger_dispatcher.py` fixture 范式 | sibling |
| **新建** `server/tests/workflows/test_trigger_type_choices.py`（TRIG-02） | test | unit | `test_trigger_dispatcher.py` | sibling |
| **新建** `server/tests/workflows/test_hooks.py`（OBS-01 广播） | test | unit | `test_trigger_dispatcher.py` AsyncMock/MagicMock | sibling |
| **扩展** `server/tests/test_trigger_dispatcher.py`（TRIG-03 失败持久化） | test | integration | 同文件 `TestDispatchNoMatchingWorkflows` L171-189 | self-edit |
| **新建** `web/src/config/__tests__/status.spec.ts`（OBS-03 全覆盖） | test | unit | 既有 vitest spec 范式 | no-analog-verified |
| **新建** `web/src/stores/__tests__/useExecutionsStore.spec.ts` + `useExecutionState.spec.ts`（OBS-01/02/03） | test | unit | 既有 vitest spec 范式 | no-analog-verified |

---

## Pattern Assignments

### `server/workflows/api/views.py` — `async_sync_workflow_triggers`（service, transform, TRIG-01）

**Analog:** 同函数自身（就地修复读复数 bug）。匹配侧契约见 `trigger.py L137-166`。

**根因（现状 L104-127，必须改）：**
```96:127:server/workflows/api/views.py
async def async_sync_workflow_triggers(workflow: Workflow) -> None:
    ...
    configured_triggers: list[dict] = []
    async for node in workflow.nodes.filter(node_type="feishu_event_trigger"):
        config = node.config or {}
        event_types = config.get("event_types", [])   # ← BUG：schema 是单数 event_type，此处恒空
        filter_config = {}
        if config.get("filter_project_key"):
            filter_config["project_key"] = config["filter_project_key"]
        if config.get("filter_work_item_type"):
            filter_config["work_item_type_key"] = config["filter_work_item_type"]
        if config.get("filter_status"):
            filter_config["cur_work_item_status.state_key"] = config["filter_status"]
        for event_type in event_types:   # ← event_types 恒空 → 循环 0 次 → configured_triggers 空
            ...
```

**deactivate 副作用（现状 L155-159，理解后果，不改逻辑）：**
```155:159:server/workflows/api/views.py
    # Deactivate triggers for removed event types
    for event_type, trigger in existing_triggers.items():
        if event_type not in seen_event_types:
            trigger.is_active = False
            await trigger.asave()
```
→ `configured_triggers` 空 → `seen_event_types` 空 → 所有现存 trigger 被置 `is_active=False`。

**改造方向（单数为准 + 复数兜底；filter_status 已是数组直接走 list 成员匹配）：**
```python
event_type = config.get("event_type")
legacy = config.get("event_types") or []
event_type_list = [et for et in ([event_type] if event_type else legacy) if et]
...
statuses = config.get("filter_status") or []          # schema 已是数组
if statuses:
    filter_config["cur_work_item_status.state_key"] = statuses
for et in event_type_list:
    configured_triggers.append({"event_type": et, "filter_config": filter_config,
                                "node_id": str(node.id), "node_name": node.name})
```

**匹配侧契约（trigger.py L137-166，无需改，仅须填对 filter_config 形态）：**
```137:166:server/workflows/models/trigger.py
        for key, expected_value in self.filter_config.items():
            actual_value = self._get_nested_value(payload, key)
            if isinstance(expected_value, list):
                # 列表匹配：actual_value 在 expected_value 中
                if actual_value not in expected_value:
                    return False
            elif actual_value != expected_value:
                return False
        return True
    def _get_nested_value(self, data: dict, key: str):
        keys = key.split(".")          # 支持 "cur_work_item_status.state_key"
        current = data
        for k in keys:
            if isinstance(current, dict):
                current = current.get(k)
            else:
                return None
        return current
```
**关键约束（Pitfall 2）：** `_matches_filter` **仅正向 include**（`==` 或 `∈ list`），无排除分支；`exclude_*` / `project_ids`（Space UUID≠飞书 project_key）**禁止**塞进正向 filter_config，否则静默误匹配。Open Question OQ-1 留 planner 裁定（先只同步 filter_status/filter_project_key/filter_work_item_type）。

---

### `server/workflows/models/workflow.py` — `TriggerType`（model, config, TRIG-02）

**Analog:** `execution.py L17-27 ExecutionStatus`（同为 `models.TextChoices` 增删范式）。

**现状（L30-34，移除 SCHEDULE 行）：**
```30:34:server/workflows/models/workflow.py
    class TriggerType(models.TextChoices):
        MANUAL = "manual", "手动触发"
        WEBHOOK = "webhook", "Webhook 触发"
        SCHEDULE = "schedule", "定时触发"   # ← 移除（僵尸枚举：无 handler/无节点/无 dispatch）
        EVENT = "event", "事件触发"
```

---

### `server/workflows/migrations/00XX_remove_schedule.py`（migration, batch, TRIG-02）

**Analog:** `0022_remove_cancelled_status.py`（纯 AlterField choices 收窄）+ `0003_suspended_status.py`（status choices 多模型 AlterField 同模式）。

**复制范式（`0022`，TextChoices 无 DB CHECK 约束，存量 `schedule` 行不报错）：**
```1:18:server/workflows/migrations/0022_remove_cancelled_status.py
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('workflows', '0021_workflowexecution_feishu_message_id'),
    ]
    operations = [
        migrations.AlterField(
            model_name='codingtask',
            name='status',
            field=models.CharField(choices=[...], default='pending', max_length=20, verbose_name='状态'),
        ),
    ]
```
**本阶段套用：** `model_name='workflow'`, `name='trigger_type'`, `field=models.CharField(choices=[("manual","手动触发"),("webhook","Webhook 触发"),("event","事件触发")], default="manual", max_length=20, verbose_name="触发类型")`。
**可选数据迁移（Claude's Discretion，参 `0003` 多操作可叠加）：** 追加 `migrations.RunPython` 把存量 `trigger_type="schedule"` → `"manual"`，reverse 用 `migrations.RunPython.noop`；**禁止删行 / 加 CHECK 约束**（Pitfall 3）。dependency 取当前最新 migration 编号。

---

### `server/feishu/views.py` — `_dispatch_to_workflows`（service, event-driven, TRIG-03）

**Analog:** 同方法成功分支（L712-724）+ `TriggerLog.status`/`error_message` 字段（feishu/models.py L71-76）。

**现状（L693-731，失败/无匹配恒停在 ACCEPTED）：**
```709:731:server/feishu/views.py
            dispatcher = TriggerDispatcher()
            executions = await dispatcher.dispatch(context)
            if executions:
                ...
                if len(executions) == 1:
                    trigger_log.workflow_execution = executions[0]
                    await trigger_log.asave(update_fields=["workflow_execution"])
            # ← 缺：executions 为空（无匹配）时不更新 status，恒为 ACCEPTED
        except Exception as e:
            logger.error("workflow_dispatch_failed", event_type=event_type, error=str(e))
            # ← 缺：异常仅 structlog，不落 status=error
```

**可复用的状态枚举（feishu/models.py L14-20）：**
```14:20:server/feishu/models.py
class TriggerLogStatus(models.TextChoices):
    ACCEPTED = "accepted", "已接受"
    IGNORED = "ignored", "已忽略"
    ERROR = "error", "错误"
    DUPLICATE = "duplicate", "重复"
```
**可复用的失败字段（feishu/models.py L71-76）：** `status`（已有 choices）+ `error_message = models.TextField(blank=True, null=True)`——**无需新表/新字段**。

**改造方向：**
```python
if executions:
    ...
else:  # 无匹配工作流
    trigger_log.status = TriggerLogStatus.IGNORED
    trigger_log.error_message = f"无匹配工作流（event_type={event_type}）"
    await trigger_log.asave(update_fields=["status", "error_message"])
except Exception as e:
    logger.error("workflow_dispatch_failed", event_type=event_type, error=str(e))
    trigger_log.status = TriggerLogStatus.ERROR
    trigger_log.error_message = str(e)[:2000]   # 截断防膨胀 + 零输出值泄露（ASVS V7）
    await trigger_log.asave(update_fields=["status", "error_message"])
```

**webhook 路径（views.py L1540-1588，最小/可选）：** 现 `no_workflows` 仅返回 200 无持久化（L1570-1574）。**勿**给 manual/webhook 强塞 `TriggerLog`（该表强飞书语义 event_uuid/work_item_*，Pitfall 4）。OQ-2 留 planner：webhook 若做，复用 TriggerLog 以 webhook path 充 event_type；manual 默认不持久化。

---

### `server/workflows/hooks/builtin.py` — `WebSocketBroadcastHook`（hook, pub-sub, OBS-01）

**Analog:** 同 Hook 的 `node_debug_paused` 可选键追加范式（L67-70）——证明"按事件条件追加可选键"是该文件既定写法。

**现状（L55-75）：**
```55:75:server/workflows/hooks/builtin.py
            message = {
                "type": "workflow.event",
                "event": event,
                "execution_id": str(execution.id),
                "status": execution.status,
            }
            node_execution = kwargs.get("node_execution")
            if node_execution:
                message["node_id"] = str(node_execution.node_id)
                message["node_status"] = node_execution.status
                # 调试暂停事件：附带节点输入输出数据供前端展示
                if event == "node_debug_paused":
                    message["node_input"] = node_execution.input_data or {}
                    message["node_output"] = node_execution.output_data or {}
            await channel_layer.group_send(
                f"execution_{execution.id}",
                message,
            )
```

**改造方向（仅失败态追加可选键，向后兼容——Pitfall 5）：**
```python
if node_execution.status in ("failed", "timeout"):
    message["error_message"] = node_execution.error_message or ""
    message["error_code"] = node_execution.error_code or ""
```
**契约一致性（builtin.py L313-317）：** `error_code` 已是一等字段，`AlertRuleHook` 的 `node_error_code` 告警即按 `node_execution.error_code` 匹配，且其读 DB 对象而非 message dict，故追加可选键**不影响** AlertRuleHook：
```313:317:server/workflows/hooks/builtin.py
        if condition_type == "node_error_code":
            if not node_execution:
                return False
            target_code = config.get("error_code")
            return node_execution.error_code == target_code
```

---

### `web/src/config/status.ts` — `executionStatusConfig`（config, transform, OBS-03）

**Analog:** 同文件 `triggerLogStatusConfig`（L54-59）等条目 + `getStatusConfig` fallback（L98）。

**现状（L9-21，缺 suspended；waiting_* 实为 node 级误入 execution map）：**
```9:21:web/src/config/status.ts
export const executionStatusConfig: Record<string, StatusConfig> = {
  pending: { label: '等待中', icon: 'lucide--clock', variant: 'muted' },
  queued: { label: '排队中', icon: 'lucide--list', variant: 'muted' },
  running: { label: '运行中', icon: 'lucide--loader-2', variant: 'info', animate: true },
  paused: { label: '已暂停', icon: 'lucide--pause', variant: 'warning' },
  completed: { label: '已完成', icon: 'lucide--check-circle', variant: 'success' },
  failed: { label: '失败', icon: 'lucide--x-circle', variant: 'destructive' },
  cancelled: { label: '已取消', icon: 'lucide--square', variant: 'muted' },
  timeout: { label: '超时', icon: 'lucide--alarm-clock-off', variant: 'warning' },
  waiting_approval: { label: '待审批', icon: 'lucide--user-check', variant: 'warning' },
  waiting_input: { label: '待输入', icon: 'lucide--edit', variant: 'info' },
  skipped: { label: '已跳过', icon: 'lucide--skip-forward', variant: 'muted' },
}
```
**对齐源（后端 SSOT，execution.py L17-27）：** execution 全集 = pending/running/paused/**suspended**/completed/failed/cancelled/timeout。
**改造方向：** 增 `suspended: { label: '挂起中', icon: 'lucide--pause-circle', variant: 'warning' }`。`waiting_approval`/`waiting_input` 可保留供 `StatusBadge type="execution"` 渲染 **node** 状态（NodeOverviewTab L95 即如此用），但不得用于 execution 级筛选/统计。fallback 范式（无需改，复制理解）：
```98:98:web/src/config/status.ts
  return configMap[type][status] ?? { label: status, icon: 'lucide--help-circle', variant: 'muted' as const }
```

---

### `web/src/stores/useExecutionsStore.ts` — `node_failed` + `stats`（store, event-driven, OBS-01/03）

**Analog:** 同 store `sub_step.update` 分支写 NE 字段（L420-428）——证明"按 node 找 NE 再写字段"是既定写法。

**现状 node_failed（L374-376，只 ++ 不写 error）：**
```374:376:web/src/stores/useExecutionsStore.ts
    else if (event === 'node_failed') {
      currentExecution.value.failed_nodes++
    }
```
**找 NE 写字段范式（L420-428，复制此结构到 node_failed）：**
```420:428:web/src/stores/useExecutionsStore.ts
      if (stepData.progress && currentExecution.value) {
        const nodeExec = currentExecution.value.node_executions.find(
          ne => ne.id === node_execution_id,
        )
        if (nodeExec) {
          nodeExec.sub_step_progress = stepData.progress
        }
      }
```
**改造方向（防御读 `data.error_message != null`，Pitfall 5）：**
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
**NE 类型已就绪（L17/L29）：** `error_message: string`、`error_code: string | null` 已在 interface，无需扩类型。

**stats 语义纠偏（L144-154，OBS-03）：**
```144:154:web/src/stores/useExecutionsStore.ts
  const stats = computed(() => ({
    total: executions.value.length,
    running: executions.value.filter(e => e.status === 'running').length,
    pending: executions.value.filter(e => e.status === 'pending').length,
    waitingApproval: executions.value.filter(e =>
      e.status === 'waiting_approval'             // ← execution 级永不为此值；应判 'suspended'
      || e.node_executions?.some(n => n.status === 'waiting_approval'),  // ← node 级保留
    ).length,
    completed: executions.value.filter(e => e.status === 'completed').length,
    failed: executions.value.filter(e => e.status === 'failed').length,
  }))
```
**改造方向：** execution 级"等待"判 `e.status === 'suspended'`；node 级 `waiting_approval` 经 `node_executions.some(...)` 旁路保留（命名应区分 execution/node 语义）。

---

### `web/src/pages/executions/composables/useExecutionState.ts` — WS 降级状态机（composable, streaming→polling, OBS-02）

**Analog:** `usePolling.ts`（start/stop/onUnmounted 自动清理）+ 同文件已算好的 `wsDisconnected`（L74-81）+ 列表页 `refetchInterval` 5s 范式（index.vue L98-105）。

**已就绪断线信号（L74-81，无需改，watch 它）：**
```74:81:web/src/pages/executions/composables/useExecutionState.ts
  const wsDisconnected = computed(() => {
    if (!currentExecution.value)
      return false
    if (!isActiveStatus(currentExecution.value.status))
      return false
    return wsStatus.value === 'CLOSED'
  })
```
**usePolling 接口（复用，复制 start/stop 用法）：**
```43:57:web/src/composables/usePolling.ts
  async function start() {
    isPolling.value = true
    if (immediate) {
      await wrappedCallback()
    }
    resume()
  }
  function stop() {
    isPolling.value = false
    pause()
  }
```
**权威值来源（store.fetchExecution 整体覆盖 currentExecution，L201-215）：**
```206:208:web/src/stores/useExecutionsStore.ts
    try {
      currentExecution.value = await api.get<WorkflowExecution>(`/workflow-executions/${id}/`)
    }
```
**改造方向（新增到 useExecutionState）：**
```ts
const { start: startPoll, stop: stopPoll } = usePolling(
  () => store.fetchExecution(executionId.value),   // REST = 服务端权威值
  { interval: 5000, immediate: true },
)
watch(wsDisconnected, (disconnected) => {
  if (disconnected) startPoll()
  else stopPoll()
})
```
**权威值约束（D-05 / Pitfall 6）：** 断线时 WS 无消息流；以 `fetchExecution` 全量覆盖为单一真相，**勿**让 WS `completed_nodes++`（store L368-382）本地推断与轮询并存，避免计数双计/进度回跳。

---

### `web/src/components/execution/NodeOverviewTab.vue`（component, request-response, OBS-01）

**Analog:** 同组件错误信息块（L133-148）+ 重试行（L115-120）+ 信息行 grid（L90-121）。

**现状错误块（L133-148，无 error_code、无结构化变量错误解析）：**
```133:148:web/src/components/execution/NodeOverviewTab.vue
    <div
      v-if="nodeExecution.error_message"
      class="bg-red-50 dark:bg-red-900/20 border border-red-200/50 dark:border-red-800/50 rounded-xl p-4 space-y-2"
    >
      <div class="text-sm font-medium text-red-600 dark:text-red-400">
        错误信息
      </div>
      <pre class="text-xs text-red-700 dark:text-red-300 whitespace-pre-wrap wrap-break-word">{{ nodeExecution.error_message }}</pre>
      <details v-if="nodeExecution.error_traceback" class="mt-2">
        <summary class="text-xs text-red-500 cursor-pointer hover:text-red-600">
          查看堆栈
        </summary>
        <pre class="mt-1 ...">{{ nodeExecution.error_traceback }}</pre>
      </details>
    </div>
```
**重试行范式（L115-120，复制此 grid 行加 error_code 行）：**
```115:120:web/src/components/execution/NodeOverviewTab.vue
        <div v-if="nodeExecution.attempt > 1" class="text-muted-foreground">
          重试次数
        </div>
        <div v-if="nodeExecution.attempt > 1">
          {{ nodeExecution.attempt - 1 }}
        </div>
```
**改造方向：**
1. 信息行 grid（L90-121）新增 `v-if="nodeExecution.error_code"` 的"错误码"行（仿重试行）。
2. 结构化变量错误解析（Phase 17/18 约定 = 中文摘要 `\n` 末行 JSON），在 `<script setup>` 加：
```ts
function parseStructuredError(msg: string): { summary: string, detail: any | null } {
  const lines = msg.trimEnd().split('\n')
  try {
    const detail = JSON.parse(lines[lines.length - 1])
    return { summary: lines.slice(0, -1).join('\n'), detail }
  }
  catch { return { summary: msg, detail: null } }  // 失败回退纯文本
}
```
错误块改为展示 `summary`（纯文本）+ `detail`（若非 null 友好展示拓扑/引用）。

---

### `web/src/components/execution/dag/ExecutionNode.vue`（component, transform, OBS-03）

**Analog:** 同组件 `statusBorderClass` map（L38-49）+ 已 import 的 `Tooltip*`（L13-18）。

**现状（L38-50，缺 suspended/timeout 色）：**
```38:50:web/src/components/execution/dag/ExecutionNode.vue
  const map: Record<string, string> = {
    running: 'border-primary/80 node-running-border',
    completed: 'border-green-400/60',
    failed: 'border-red-400/70',
    pending: 'border-border/50',
    skipped: 'border-border/30 opacity-50',
    waiting_approval: 'border-orange-400/60',
    waiting_event: 'border-indigo-400/60',
    paused: 'border-yellow-400/60',
    cancelled: 'border-border/50',
  }
  return map[props.data.status] ?? 'border-border/50'
```
**改造方向：** 防御性补 `suspended: 'border-purple-400/60'`、`timeout: 'border-rose-400/60'`（OQ-3：DAG 渲染 NodeExecution，理论无 suspended，补色仅防 fallback）。失败节点 error tooltip（D-04 最小实现）：已有 `Tooltip*` import（L13-18），可在 `failed` 时把 `error_message` 注入 `<TooltipContent>`。

---

### `web/src/pages/executions/index.vue`（page, CRUD, TRIG-02/OBS-03）

**Analog:** 同文件 `triggerTypeLabels`/`triggerTypeIcons`（L255-267）、`statusOptions`（L61-69）数组、refetchInterval（L98-105）。

**schedule 标签移除（L255-267，TRIG-02）：**
```255:267:web/src/pages/executions/index.vue
const triggerTypeLabels: Record<string, string> = {
  manual: '手动触发',
  webhook: 'Webhook',
  schedule: '定时触发',                 // ← 移除
  event: '事件触发',
}
const triggerTypeIcons: Record<string, string> = {
  manual: 'icon-[lucide--mouse-pointer-click]',
  webhook: 'icon-[lucide--webhook]',
  schedule: 'icon-[lucide--alarm-clock]',  // ← 移除
  event: 'icon-[lucide--zap]',
}
```
**statusOptions 补 suspended/timeout（L61-69，OBS-03）：**
```61:69:web/src/pages/executions/index.vue
const statusOptions = [
  { value: 'all', label: '全部状态' },
  { value: 'running', label: '运行中' },
  { value: 'pending', label: '等待中' },
  { value: 'paused', label: '已暂停' },
  { value: 'completed', label: '已完成' },
  { value: 'failed', label: '失败' },
  { value: 'cancelled', label: '已取消' },
]
```
→ 增 `{ value: 'suspended', label: '挂起中' }`、`{ value: 'timeout', label: '超时' }`。
**stats waitingApproval 同 store 纠偏（L129）：** execution 级判 suspended，node 级保留 some()。

---

### `web/src/stores/useWorkflowsStore.ts` + `ExecutionCard.vue` + `ExecutionHistoryCard.vue`（TRIG-02）

**Analog:** 各文件同行/同 map 自身。
- `useWorkflowsStore.ts:52` 联合类型移除 `'schedule'`：`trigger_type: 'manual' | 'webhook' | 'event'`。
- `ExecutionCard.vue:29`（`schedule: '定时触发'`）、`ExecutionHistoryCard.vue:54`（`schedule: '定时'`）：移除 schedule 标签条目。
- **勿动** `repositories.ts:106` 的 `'scheduled'`（仓库索引触发类型，与工作流正交）。

---

## Shared Patterns

### TextChoices 增删 → AlterField migration（后端枚举 SSOT）
**Source:** `server/workflows/migrations/0022_remove_cancelled_status.py`、`0003_suspended_status.py`
**Apply to:** TRIG-02（移除 schedule）
**关键：** TextChoices 无 DB CHECK 约束，AlterField 即足够；存量非法字符串行不报错。**禁止** 手写 SQL / 加 CHECK / 删行（Pitfall 3）。

### WS 广播只追加可选键（向后兼容）
**Source:** `server/workflows/hooks/builtin.py` L67-70（`node_debug_paused` 条件键范式）
**Apply to:** OBS-01（error_message/error_code）
**关键：** 仅特定事件/状态条件下写键；前端消费方用 `data.x != null` 防御读（Pitfall 5）。

### error_message 截断 + 零敏感泄露（ASVS V7）
**Source:** Phase 18 死锁诊断"仅拓扑元数据"原则（18-03-SUMMARY）
**Apply to:** TRIG-03 TriggerLog.error_message、OBS-01 WS error_message
**关键：** 写入前 `str(e)[:2000]` 截断；只含人类可读摘要 + 结构化拓扑，**不得**含 node 输出值/凭证。

### 服务端权威值单一真相（避免双写竞态）
**Source:** `useExecutionsStore.fetchExecution` 整体覆盖（L206-208）
**Apply to:** OBS-02 轮询降级
**关键：** REST 全量覆盖 `currentExecution` 为唯一真相；轮询期间不混合 WS 本地 `++` 推断（Pitfall 6）。

### 测试 fixture 范式（AsyncMock engine + registry 清理）
**Source:** `server/tests/test_trigger_dispatcher.py` L29-55（`mock_engine` / `clear_registry` autouse）+ L171-189（无匹配断言范式）
**Apply to:** TRIG-03 失败持久化测试（扩展同文件）、TRIG-01/OBS-01 新建测试
**复制范式（断言 dispatch 结果 + start_execution 未调用）：**
```174:189:server/tests/test_trigger_dispatcher.py
    async def test_dispatch_no_matching_workflows_returns_empty_list(self, mock_engine):
        class NoWorkflowsHandler(MockHandler):
            async def find_workflows(self, context: TriggerContext) -> list:
                return []
        TriggerHandlerRegistry.register(NoWorkflowsHandler)
        dispatcher = TriggerDispatcher(engine=mock_engine)
        context = TriggerContext(trigger_type="test", raw_payload={})
        result = await dispatcher.dispatch(context)
        assert result == []
        mock_engine.start_execution.assert_not_called()
```
TRIG-03 扩展：在飞书路径测试中断言 `trigger_log.status == "error"`/`"ignored"` 且 `error_message` 非空。

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `web/src/config/__tests__/status.spec.ts`（新建） | test | unit | 无现成 config 单测；用通用 vitest describe/it 范式 + 遍历后端 ExecutionStatus 全集断言 `getStatusConfig('execution', s)` 非 fallback |
| `web/src/pages/executions/composables/__tests__/useExecutionState.spec.ts`（新建） | test | unit | 无现成 composable 单测；需 mock store wsStatus + usePolling 断言 WS CLOSED→start/重连→stop。建议先 grep `web/src/**/__tests__/*.spec.ts` 取最接近的 composable/store 测试范式作模板 |

**说明：** WebhookLog（`server/workflows/models/webhook.py L83-124`）作为 manual/webhook dispatch 失败持久化的**潜在第二 analog**（已有 `success`/`error_message`/`execution` FK）——若 planner 决定 webhook 路径持久化失败，WebhookLog 比 TriggerLog 语义更契合（无飞书 event_uuid/work_item_* 包袱）。但 D-03 指明"优先扩展 TriggerLog（飞书路径）"，manual 默认不持久化（A2），故列为参考非主路径。

## Metadata

**Analog search scope:** `server/workflows/{api,models,migrations,hooks,triggers}`、`server/feishu`、`server/tests`、`web/src/{config,stores,composables,pages/executions,components/execution}`
**Files scanned:** 16 源文件 read + 4 grep 定位
**Pattern extraction date:** 2026-06-13
