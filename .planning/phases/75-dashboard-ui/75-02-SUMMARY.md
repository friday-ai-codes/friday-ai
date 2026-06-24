---
phase: 75-dashboard-ui
plan: "75-02"
subsystem: web/observability-dashboard
tags: [vue3, tailwind, echarts, vue-query, observability, ui-01, ui-02]
requires:
  - web/src/api/system.ts (getMetricsSnapshot / queryMetrics / querySla, 75-01)
  - web/src/components/observability/{ObservabilityTabs,ObservabilityTimeRange}.vue (75-01)
  - web/src/components/observability/{format,status}.ts (75-01)
  - web/src/components/analytics/{ChartCard,chart-theme,echarts-setup}.* (既有)
provides:
  - 运维大盘总览页（UI-01 + UI-02）：健康分 + 实时速率 + 6 信息卡 + 快照行 + 4 趋势图
  - 5 个可复用观测组件（HealthScoreGauge/RealtimeRateCard/MetricInfoCard/SnapshotRow/TrendCharts）
affects:
  - web/src/pages/admin/observability/index.vue（整页重构）
tech-stack:
  added: []
  patterns:
    - "后端时序驱动：@tanstack/vue-query 拉 queryMetrics/querySla/snapshot，弃用客户端滚动采样"
    - "自动刷新：invalidate obs-* query + 快照 refetchInterval，document.hidden 暂停"
    - "纯展示组件（MetricInfoCard/SnapshotRow/HealthScoreGauge）prop 驱动，便于单测"
key-files:
  created:
    - web/src/components/observability/HealthScoreGauge.vue
    - web/src/components/observability/RealtimeRateCard.vue
    - web/src/components/observability/MetricInfoCard.vue
    - web/src/components/observability/SnapshotRow.vue
    - web/src/components/observability/TrendCharts.vue
    - web/src/components/observability/__tests__/dashboard.spec.ts
  modified:
    - web/src/pages/admin/observability/index.vue
decisions:
  - "健康分圆环用纯 SVG 环而非 echarts gauge：echarts-setup 仅注册 line/bar，避免跨 plan 改共享注册文件，并天然支持 prefers-reduced-motion"
  - "请求时长 / TTFT 头部取 P95（metrics_query agg 白名单为 p95/p90/p50/avg/max，无 p99），如实标注"
  - "上游错误 429/529 单列显示 n/a + 标注「待后端维度支持」（后端无 429/529 拆分维度，不臆造）"
  - "请求错误率口径与 SLA 一致：排除业务限制（system+upstream）/请求数"
  - "i18n：沿用本观测域既有约定（75-01 组件 + 旧 index.vue 均硬编码中文），保持硬编码中文、零硬编码英文，未拆 i18n key 以与同期组件一致"
metrics:
  duration: ~25m
  completed: 2026-06-25
---

# Phase 75 Plan 02: 运维大盘总览（UI-01 + UI-02）Summary

把 `admin/observability/index.vue` 从纯客户端滚动采样重构为后端时序驱动 + 保留自动刷新的组合页：复合健康分圆环、实时速率卡、6 张关键口径信息卡、内联阈值快照行、4 类时序趋势图，统一接入 75-01 的三视图 tab、时间范围选择器与 `getMetricsSnapshot`/`queryMetrics`/`querySla`。

## Per-task result

| Task | 内容 | 结果 |
|------|------|------|
| Task 1 | HealthScoreGauge / RealtimeRateCard / MetricInfoCard | PASS |
| Task 2 | SnapshotRow / TrendCharts / index.vue 重构 / dashboard.spec.ts | PASS |

### Task 1 — UI-01 上半区组件
- **HealthScoreGauge.vue**：5 因子加权算分（CPU .25 / 内存 .20 / 错误率 .25 / 上游错误 .15 / 队列积压 .15），缺源剔除权重并重新归一化，全缺 → n/a 灰态；SVG 环 + `healthScoreBand` 徽标（健康/警告/严重）；reduced-motion 禁过渡；因子贡献文字列表。
- **RealtimeRateCard.vue**：自管窗口 tab（1min/5min/30min/1h）→ 按窗口反推 start/step + refetchInterval；queryMetrics(qps|tps) 派生当前/峰值/平均（速率=桶值/step）+ echarts sparkline（无轴）；QPS·TPS 两组三联，tabular-nums。
- **MetricInfoCard.vue**：通用纯展示卡（图标芯片 + 大字主值 tone 着色 + subItems 分位/分列网格 + footnote），6 卡复用；loading 骨架；色彩非唯一信号（配文字 label）。

### Task 2 — UI-02 快照 + 趋势 + 总览页
- **SnapshotRow.vue**：CPU/内存/DB/Redis/Qdrant/协程/后台任务 7 卡；卡内内联阈值（CPU 60/95、内存 70/90、协程 8000/15000、DB·Redis 连接占比 70%/90%）经 `healthBandClass` 超阈变色；源 available=false / 字段缺失 → n/a 灰态降级（SQLite dev → `n/a (sqlite dev)`），不抛。
- **TrendCharts.vue**：吞吐（各维 QPS 折线 + 总 TPS 千副轴，provider↔call_source 可切）/ 错误（系统·上游·业务限制三线，缺失补 0）/ 请求时长（P95·P50 折线）/ 并发·排队（受控 gauge：`concurrency.provider_slots`、`concurrency.rag`、`queue.durable_todo`、`queue.durable_doing`、`backlog.subagent_active`，对齐 `metric_sampling._GAUGE_NAMES`）；每图骨架 + 空态 + `degraded` 近似分位提示；按 timeRange 自动推导 step。
- **index.vue**：`definePage requiresAdmin` 保留；顶部 ObservabilityTabs + ObservabilityTimeRange（默认 1h + 自动刷新）；snapshot + 6 卡口径全部 best-effort 拉取；自动刷新每 5s invalidate `obs-*` query（document.hidden 暂停，onUnmounted 清理）；健康分由近窗 error/upstream 率派生喂入。

## Deviations from Plan

### 设计抉择（非 bug，对齐 plan 的 Claude's Discretion / 「不臆造」原则）

**1. [Rule 3 - 类型契约] 健康分圆环用 SVG 而非 echarts gauge**
- `analytics/echarts-setup.ts` 仅 `use([... LineChart, BarChart ...])`，未注册 `GaugeChart`；plan 允许「echarts gauge 或 ui/progress 圆环二选一」。为不修改 files_modified 之外的共享注册文件，改用纯 SVG `stroke-dasharray` 环（更轻、天然 reduced-motion 友好）。

**2. [口径 - 后端能力边界] 请求时长 / TTFT 头部取 P95（非 P99）**
- `MetricAgg` 白名单为 `p95|p90|p50|avg|max`，无 `p99`（传 `agg:'p99'` 会 TS 报错）。头部大字用 P95（最高受控分位）+ subItems P90/P50/Avg/Max，footnote 标注「后端分位上限，暂无 P99」。

**3. [口径 - 后端能力边界] 上游错误 429/529 单列显示 n/a**
- RequestMetric 仅 `error_class='upstream'`，无 429/529 拆分维度。单列显示 `—` + footnote「细分 429/529 待后端维度支持」，不臆造拆分。

**4. [一致性] i18n 沿用硬编码中文**
- 本观测域既有产出（75-01 ObservabilityTabs/TimeRange + 旧 index.vue）均硬编码中文、未拆 i18n key。为遵循 UI-SPEC §0.1「一致性优先」并与同期组件统一，本 plan 同样硬编码中文（零硬编码英文文案，符合 UI-SPEC §7「无硬编码英文」）；未引入新 i18n key 以免与兄弟组件风格割裂。

未涉及架构变更（Rule 4），未触碰共享路由/导航（留给 75-05）。

## Known Stubs
- 上游错误「429·529」单列：当前为 `—` + 待后端维度支持标注（后端 `error_class` 维度尚无 429/529 拆分；非前端可补全，已如实降级标注）。

## Threat Flags
无新增信任边界 surface：页面 `definePage requiresAdmin` + 后端 IsSuperUser 双重兜底；图表仅渲染受控维度（provider/call_source/error_class）数值与中文枚举，无 `v-html`、无凭证/原文渲染。

## Verification
- `pnpm vue-tsc --noEmit`：全绿（含全仓，无新增报错）。
- `pnpm exec vitest run src/components/observability/__tests__/dashboard.spec.ts`：7 passed。
- `pnpm exec eslint src/pages/admin/observability src/components/observability`：exit 0，无问题。
- 人工验收（待执行）：超管访问 `/admin/observability` 核对数据正确性、超阈变色、源降级 n/a、时间范围/自动刷新、亮暗双主题与 375/768/1024/1440 响应式。

## Self-Check: PASSED
- created 文件均存在，index.vue 已重构（含 `requiresAdmin`、`getMetricsSnapshot`、`queryMetrics`）。
- typecheck / 单测 / eslint 三项全绿。
- 未 git commit（按执行约定）。
