# Phase 75: 运维大盘前端 + 规范固化 - Context

**Gathered:** 2026-06-24
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous——grey area 按 REFERENCE-UI + MILESTONE-PROPOSAL §B Phase 75 + ui-ux-pro-max 设计建议自动采纳最优解）

<domain>
## Phase Boundary

后端 API（71–74）全部就绪后做统一运维大盘前端，并把日志/埋点规范固化为长期约束。

**交付（UI-01~04, SPEC-01）：**
- 大盘上半区（UI-01）：复合健康分圆环 + 实时速率卡（窗口 tab + 当前/峰值/平均 QPS·TPS + sparkline）+ 信息卡排（请求/SLA排除业务限制/请求错误系统·业务限制分列/请求时长 P99+分位/TTFT P99+分位/上游错误 429·529 单列）+ 时间范围选择器
- 快照行 + 趋势（UI-02）：CPU/内存/DB/Redis/Qdrant/协程/后台卡内内联阈值超阈变色 + 吞吐(各 provider QPS+TPS 可切 call_source)/错误(三口径)/请求时长分布/并发·排队趋势
- 告警事件页（UI-03）：表列对齐 REFERENCE-UI §1.4 + 多维筛选 + 阈值规则配置入口
- 系统日志页（UI-04）：顶部四计数 + 倒序 + 多维筛选 + 调用下钻（会话原始/召回内容/webhook 原始）+ 按筛选清理 + 运行时日志配置表单
- 规范固化（SPEC-01）：LOGGING-SPEC + cursor 规则 + AGENTS/CLAUDE 复核 + 事件目录补全 + PR/Review checklist

依赖 71–74（消费全部后端 API）。

</domain>

<decisions>
## Implementation Decisions

### 设计系统（ui-ux-pro-max 建议 + 沿用 Friday 既有栈）
- **沿用既有设计系统**（Tailwind 4 + reka-ui `web/src/components/ui/` + `analytics/`），**不引入新调色板/字体**，保持全站一致（ui-ux-pro-max 推荐的 Fira Code/Dark-OLED 仅作参考，落地用现有 token 以保证一致性 + 暗色模式适配）。
- 应用 ui-ux-pro-max 数据密集大盘最佳实践：状态色（绿/琥珀/红）表健康/警告/严重；卡片 + 明细下钻范式；tabular 数字（分位/计数对齐）；sparkline 迷你趋势；空态/加载骨架；hover 150–300ms 过渡；focus 可见；prefers-reduced-motion 尊重；响应式 375/768/1024/1440；图标用 lucide（不用 emoji）。
- 复用既有组件：`ChartCard`/`TrendChart`/`KpiCards`/`DurationDistribution`/`TimeRangeSelector`/`AnalyticsGroupingSelector` + `ui/` 的 card/badge/table/tabs/select/dialog/sheet/skeleton/tooltip 等 + echarts(`VChart`/chart-theme)。

### 路由与信息架构
- 重构 `web/src/pages/admin/observability/` 为多视图：大盘总览（index）+ 告警事件页 + 系统日志页 + （运行时配置面板内嵌日志页或独立 tab）。用 tabs 或子路由组织（倾向子路由 `observability/index`、`observability/alerts`、`observability/logs`，admin 导航加入口）。
- 入口请求 / LLM 子调用 / 工具 / 召回 / 容器 多层维度经 `call_source`/`source`/关联键下钻（REFERENCE-UI §4）。

### 大盘上半区（UI-01）
- 复合健康分 0–100 圆环（CPU/内存/错误率/上游错误/队列积压加权）+ 健康/警告/严重色。
- 实时速率卡：1min/5min/30min/1h tab + 当前/峰值/平均 QPS·TPS + sparkline（消费 `/api/system/metrics/query`）。
- 信息卡排：请求汇总 / SLA(排除业务限制) / 请求错误(系统·业务限制分列) / 请求时长(P99 大字 + P95/P90/P50/Avg/Max) / TTFT(同) / 上游错误(429·529 单列)。
- 时间范围选择器（5m/1h/24h/自定义）复用 `TimeRangeSelector`。

### 快照行 + 趋势（UI-02）
- 快照行：CPU/内存/DB(连接·活跃·空闲)/Redis(连接 x/maxclients)/Qdrant/协程/后台任务，**卡内内联阈值**超阈变色（阈值取 SystemAlertRule 或内置默认）。消费 `/api/system/metrics/snapshot`。
- 趋势：吞吐(各 provider QPS+TPS 千，可切 call_source)/错误(系统·上游·业务限制三线)/请求时长分布/并发·排队(provider+索引/AI描述/异步)。消费 `/api/system/metrics/query`。

### 告警事件页（UI-03）
- 表列：时间/级别 P0-P2/状态 firing·resolved/维度/规则ID/标题+规则信息/持续时长/邮件状态（对齐 REFERENCE-UI §1.4）。多维筛选（级别/状态/维度/规则/时间段）。
- 阈值规则配置入口：SystemAlertRule CRUD（dialog/sheet 表单，metric/op/value/window/severity/channels/cooldown）。消费 74 的 `/api/system/alerts/rules/`、`/api/system/alerts/events/`。

### 系统日志页（UI-04）
- 顶部四计数（队列 x/5000 · 写入 · 丢弃 · 失败）。倒序列表 + 多维筛选（级别/组件/user_id/source/call_source/provider/credential/model/关联键/关键词/时间段）。
- 调用下钻：点日志/会话 → 抽屉(sheet)展示会话全部请求·原始数据 / 召回内容 / webhook 原始（消费 71 drilldown + webhook + retrieval trace API）。
- 按当前筛选清理（confirm dialog 二次确认）+ 运行时日志配置表单（级别/堆栈阈值/采样初始·后续/保留天数·大小 + caller·sampling + 保存并生效/回滚默认）。消费 71 的 `/api/system/logs/`、`/clear/`、运行时配置 API。

### API 客户端（web/src/api/system.ts 扩展）
- 新增 typed 函数：`getMetricsSnapshot`、`queryMetrics`、告警规则/事件 CRUD、系统日志查询/清理、运行时日志配置 get/set、下钻（call/conversation/webhook/retrieval）。沿用既有 `client.ts` 范式（ApiError + cookie-JWT）。

### 规范固化（SPEC-01）
- 复核 `LOGGING-SPEC.md`（事件目录全量补全 71–74 已埋点事件）+ `.cursor/rules/observability-logging.mdc` + AGENTS.md/CLAUDE.md 挂接；落地 PR/Code Review checklist（已有雏形，确认覆盖 LLM call_source/请求入口/召回/队列/webhook/告警）。

### Claude's Discretion
- 子路由 vs tabs 组织、健康分加权公式、阈值默认值、各卡片精确栅格、i18n key 命名在 plan/实现定（默认中文 vue-i18n）。
- 是否保留旧 index.vue 实时采样作为大盘的一部分或整体替换为后端时序驱动（倾向后端时序驱动 + 保留实时刷新）。
- 组件拆分粒度（每张卡/页一个组件）。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `web/src/components/analytics/`：`ChartCard`/`TrendChart`/`KpiCards`/`DurationDistribution`/`TimeRangeSelector`/`AnalyticsGroupingSelector`/`TokenCostChart`/`NodePerformanceTable` + `chart-theme.ts` + `echarts-setup.ts`(VChart)。
- `web/src/components/ui/`：card/badge/table/tabs/select/dialog/sheet/skeleton/tooltip/switch/input/form/pagination/scroll-area/separator/sonner 等（reka-ui）。
- `web/src/pages/admin/observability/index.vue`（现有实时采样大盘，重构基底）。
- `web/src/api/system.ts`（getObservability/getSystemHealth/getSystemLogs/getActiveTasks，待扩展新 API）+ `web/src/api/client.ts`（ApiError + cookie-JWT）。
- 既有 admin 页范式（audit/users/git-credentials）+ `requiresAdmin` 路由 meta。
- echarts/vue-echarts 已在依赖（出图）。

### Established Patterns
- Vue 3 `<script setup>` + TS；unplugin auto-import；`~/` alias=web/src；vue-i18n 默认中文；@tanstack/vue-query server 缓存。
- ESLint @antfu；`definePage({ meta: { requiresAdmin: true } })`；PascalCase 组件。
- 后端 IsSuperUser 端点；前端 admin 路由守卫。

### Integration Points
- 消费 71–74 后端 API：`/api/system/logs/`(+clear)、运行时日志配置、drilldown、webhooks、`/api/system/metrics/snapshot`、`/api/system/metrics/query`、`/api/system/alerts/rules/`、`/api/system/alerts/events/`。
- admin 导航加观测大盘/告警/日志入口。
- system.ts 扩展 typed API + 类型。

</code_context>

<specifics>
## Specific Ideas

- REFERENCE-UI 布局借鉴但按 Agent 维度重构（call_source/会话/工作流/召回/容器），不照抄请求中心架构。
- ui-ux-pro-max 数据密集大盘最佳实践（状态色/tabular 数字/sparkline/空态骨架/响应式/a11y/reduced-motion/lucide 图标）。
- 沿用 Friday 既有设计系统保持全站一致 + 暗色适配。
- 严守 `.cursor/rules/observability-logging.mdc`：前端轮询端点已被后端打 synthetic 标隔离（不污染 SLA）。

</specifics>

<deferred>
## Deferred Ideas

- Prometheus/Grafana 导出、外部栈 → v2 OBSX-01。
- 告警自适应/降噪 → v2 OBSX-04。
- 累计/本月成本估算卡（REFERENCE-UI §5 可选）→ 可作锦上添花，非首屏硬需求。

</deferred>
