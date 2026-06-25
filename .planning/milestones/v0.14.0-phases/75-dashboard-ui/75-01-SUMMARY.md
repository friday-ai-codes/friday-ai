---
phase: 75-dashboard-ui
plan: "75-01"
subsystem: web/observability
tags: [api-client, typed-contract, scaffolding, observability]
requires: []
provides:
  - "web/src/api/system.ts 运维端点 typed 函数 + interface（71–74 全覆盖）"
  - "web/src/components/observability/ 共享脚手架（tabs/时间范围/format/status）"
affects:
  - "75-02 总览页（消费 getMetricsSnapshot/queryMetrics/querySla + 脚手架）"
  - "75-03 告警页（消费 alert 规则 CRUD + listAlertEvents + 脚手架）"
  - "75-04 日志/下钻页（消费 querySystemLogs/clearSystemLogs/webhook/drilldown + 脚手架）"
tech-stack:
  added: []
  patterns: ["复用 ./client get/post/patch/del + cookie-JWT", "reka-ui Select/Switch/Button", "icon-[lucide--*] iconify class", "vitest mock ~/api/client"]
key-files:
  created:
    - web/src/api/__tests__/observability.spec.ts
    - web/src/components/observability/format.ts
    - web/src/components/observability/status.ts
    - web/src/components/observability/ObservabilityTimeRange.vue
    - web/src/components/observability/ObservabilityTabs.vue
  modified:
    - web/src/api/system.ts
decisions:
  - "告警 metric 单独建 AlertMetric 联合类型（qps/error_rate/ttft/cpu/memory/db_connections/redis_clients/qdrant/queue_depth），区别于时序查询 MetricName——后端 alert_serializers 与 metrics_query 是两套受控枚举"
  - "新日志行用 SystemLogRow、新告警事件用 AlertEventRow，避免与既有 SystemLogEntry / AlertEvent(OBS-01) interface 撞名"
  - "AlertEventQuery/SystemLogQuery 为 interface（无隐式 index signature），get 调用处用 params ? { ...params } : undefined 展开以满足 QueryParams（沿用 queryMetrics 既有 spread 范式）"
  - "ObservabilityTimeRange 自动刷新用受控 v-model:autoRefresh，组件不自持定时器，定时逻辑留各页"
metrics:
  duration: ~15min
  completed: 2026-06-25
---

# Phase 75 Plan 01: 运维大盘数据层 + 共享脚手架 Summary

把 Phase 71–74 后端运维端点封装成类型安全 API 客户端（扩展 `web/src/api/system.ts`，新增 13 个 typed 函数 + 全套 interface，路由/参数/响应逐一对齐后端视图），并产出 75-02/03/04 三页共享脚手架（顶部三视图 tab 导航、5m/1h/24h+自定义时间范围+自动刷新选择器、format/status 纯函数）。零业务页面、零新依赖、零跨页文件冲突。

## What Was Built

### Task 1 — `system.ts` 运维端点 typed 客户端（PASS）

在 `web/src/api/system.ts` 末尾追加（既有导出零改动；import 由 `get` 扩为 `del, get, patch, post`）：

**导出函数（downstream 可直接 import）：**
- `getMetricsSnapshot(): Promise<MetricsSnapshot>` — `GET /system/metrics/snapshot/`
- `queryMetrics(params: MetricsQueryParams): Promise<MetricsQueryResult<MetricPoint>>` — `GET /system/metrics/query/`
- `querySla(params): Promise<MetricsQueryResult<SlaPoint>>` — 固定 metric='sla'
- `listAlertRules / createAlertRule / getAlertRule / updateAlertRule / deleteAlertRule` — `/system/alerts/rules/(+<id>/)`
- `listAlertEvents(params?): Promise<{ items: AlertEventRow[], total }>` — `GET /system/alerts/events/`
- `querySystemLogs(params?): Promise<SystemLogResult>` — `GET /system/logs/`
- `clearSystemLogs(body): Promise<{ deleted: number }>` — `POST /system/logs/clear/`
- `listWebhookEvents / getWebhookEvent` — `/system/webhooks/(+<id>/)`
- `getCallDrilldown(params) / getConversationDrilldown(conversationId)` — `/system/calls/drilldown/`、`/system/conversations/<uuid>/drilldown/`

**导出类型：** `SnapshotEnvelope, HostSnapshot, DbSnapshot, RedisClientSnapshot, RedisSnapshot, QdrantSnapshot, ConcurrencySnapshot, QueueCounters, MetricsSnapshot, MetricName, MetricAgg, MetricDimension, MetricPoint, SlaPoint, MetricsQueryResult<T>, MetricsQueryParams, AlertOp, AlertSeverity, AlertChannel, AlertMetric, AlertRule, AlertRuleWrite, AlertEventRow, AlertEventQuery, SystemLogRow, SystemLogQuery, SystemLogResult, WebhookEventRow, CallDrilldown, ConversationDrilldown`。

`MetricsSnapshot` 按 collect_snapshot 五源 envelope（host/db/redis/qdrant/concurrency 各 available/error + 数据字段）+ `counters{request_metric,system_log}` + `generated_at` 建模。`queryMetrics` 返回 `MetricPoint[]`、`querySla` 返回 `SlaPoint[]`（含 availability/eligible/failures/business_rejected）。

测试 `web/src/api/__tests__/observability.spec.ts`（5 用例，全绿）：queryMetrics URL+参数、querySla 强制 metric=sla、clearSystemLogs POST body、getConversationDrilldown uuid 路径、`expectTypeOf` 编译期断言 MetricPoint/SlaPoint。

### Task 2 — `components/observability/` 共享脚手架（PASS）

- `format.ts` — `formatNumber / formatRatio(0..1→%) / formatPercent(已是%) / formatDurationMs / formatThousands / formatRelativeTime / formatClock / formatDateTime`，全部 null/NaN → `'—'` 不抛。
- `status.ts` — `logLevelClass / alertSeverityClass / alertStatusClass / healthBandClass(value,warn,crit,invert) / healthScoreBand(score)`，class 风格复用既有 `text-<color>-500 bg-<color>-500/10`。
- `ObservabilityTimeRange.vue` — Select 预设 5m/1h/24h/custom（custom 显双 datetime-local），自动刷新 `v-model:autoRefresh` + 立即刷新按钮 emit refresh，`#right` 插槽；不自持定时器。
- `ObservabilityTabs.vue` — 三 RouterLink（`/admin/observability`、`/alerts`、`/logs`）+ lucide 图标 + `useRoute().path` 高亮，移动端横向滚动，focus-visible ring。

## Verification Results

| 检查 | 命令 | 结果 |
|------|------|------|
| Typecheck | `pnpm vue-tsc --noEmit` | PASS（exit 0，全仓无错） |
| Lint | `pnpm exec eslint src/api/system.ts src/components/observability src/api/__tests__/observability.spec.ts` | PASS（@antfu，0 error） |
| Unit | `pnpm exec vitest run src/api/__tests__/observability.spec.ts` | PASS（5/5） |

## Deviations from Plan

**1. [Rule 1 - Bug] AlertEventQuery / SystemLogQuery interface 不满足 QueryParams index signature**
- **Found during:** Task 1 typecheck
- **Issue:** `get(url, params)` 的 `params: Record<string, ...>` 要求隐式 index signature，`interface` 声明（与 plan 规定一致）不具备 → TS2345。
- **Fix:** 调用处改为 `params ? { ...params } : undefined` 展开（沿用文件内 `queryMetrics` 既有 spread 范式），保留 interface 声明不变。
- **Files modified:** web/src/api/system.ts
- **Commit:** （未提交，执行规则要求 do NOT commit）

**2. [增强] 告警 metric 用 AlertMetric 联合类型替代 plan 的 `metric: string`**
- plan 的 `AlertRule.metric` 写作 `string`；实际后端 `alert_serializers._METRIC_CHOICES` 是闭集（qps/error_rate/ttft/cpu/memory/db_connections/redis_clients/qdrant/queue_depth）。新增 `AlertMetric` 联合类型并用于 `AlertRule.metric`，提升 downstream 表单/校验 DX，且与后端 ChoiceField 白名单逐一对齐。非破坏性强化。

**3. [测试断言] getConversationDrilldown mock 断言带 undefined 第二参**
- mock 的 `get` 始终转发 `(url, params)`，无 params 调用时 params=undefined；断言相应写为 `toHaveBeenCalledWith(url, undefined)`。纯测试细节，不影响生产代码。

## Self-Check: PASSED

- web/src/api/system.ts — FOUND（已扩展，含 `getMetricsSnapshot`）
- web/src/api/__tests__/observability.spec.ts — FOUND
- web/src/components/observability/format.ts — FOUND
- web/src/components/observability/status.ts — FOUND
- web/src/components/observability/ObservabilityTimeRange.vue — FOUND
- web/src/components/observability/ObservabilityTabs.vue — FOUND

## Notes for Downstream (75-02/03/04)

- **总览页 (75-02):** `import { getMetricsSnapshot, queryMetrics, querySla } from '~/api/system'`；时序点用 `MetricPoint`，SLA 卡用 `SlaPoint`；快照五源各带 `available/error`，渲染前判 available。
- **告警页 (75-03):** 规则 CRUD 用 `AlertRule / AlertRuleWrite`（write 用 `Partial<AlertRuleWrite>` patch）；事件列表用 `listAlertEvents` → `AlertEventRow`；色用 `alertSeverityClass / alertStatusClass`。
- **日志/下钻页 (75-04):** 日志用 `querySystemLogs` → `SystemLogRow` + `SystemLogResult.counters`（队列四计数）；清理用 `clearSystemLogs`（无筛选须 `confirm_all:true`）；webhook 用 `listWebhookEvents/getWebhookEvent`；下钻用 `getCallDrilldown/getConversationDrilldown`。原始内容禁 `v-html`（plan 在 75-04 强制）。
- **共享件全页通用:** `<ObservabilityTabs />` 顶部导航；`<ObservabilityTimeRange v-model="range" v-model:autoRefresh="auto" @refresh="load" />`；`format.ts` 注意 `formatRatio`(0..1，SLA availability 用此) vs `formatPercent`(已是百分数，cpu_percent 用此)。
