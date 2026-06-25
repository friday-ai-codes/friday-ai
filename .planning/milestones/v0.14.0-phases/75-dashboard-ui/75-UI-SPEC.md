# Phase 75: 运维大盘前端 — UI 设计契约（UI-SPEC）

**Created:** 2026-06-24
**Design intelligence:** ui-ux-pro-max（observability/ops data-dense dashboard）+ Friday 既有设计系统（Tailwind 4 + reka-ui）+ REFERENCE-UI.md
**Scope:** UI-01~04（大盘上半区 / 快照·趋势 / 告警事件页 / 系统日志页）

---

## 0. 设计原则（强约束）

1. **一致性优先**：沿用 Friday 既有设计系统与 token（`web/src/components/ui/` reka-ui + Tailwind 4 主题变量），**不引入新调色板/字体**。ui-ux-pro-max 的 Dark-OLED/Fira 仅作风格参考；落地以现有亮/暗主题变量为准（两套主题都要测）。
2. **数据密集但可扫读**：卡片 + 明细下钻范式；信息分层（健康分 → 速率 → 信息卡 → 快照 → 趋势 → 明细）。
3. **状态色语义**：健康=`text-emerald/green`，警告=`amber`，严重=`destructive/red`；颜色不作唯一信号（配图标/文字，WCAG）。
4. **tabular 数字**：所有分位/计数/QPS·TPS 用等宽数字（`tabular-nums`）避免跳动。
5. **a11y**：对比 ≥4.5:1；focus ring 可见；图标按钮带 aria-label；`prefers-reduced-motion` 降级动画；图表提供文字/表格替代或 aria-label。
6. **响应式**：375/768/1024/1440；移动端卡片单列、表格横向滚动或卡片化；无横向溢出。
7. **图标**：lucide（既有），**禁用 emoji 作图标**。
8. **交互反馈**：hover/active 150–300ms 过渡；加载用 skeleton；异步操作禁用按钮+spinner；空态友好文案。

---

## 1. 信息架构与路由

`web/src/pages/admin/observability/` 重构为三视图（子路由 + 顶部 tabs 导航）：

| 路由 | 视图 | 需求 |
|------|------|------|
| `observability/index` | 大盘总览（健康分 + 速率 + 信息卡 + 快照行 + 趋势） | UI-01, UI-02 |
| `observability/alerts` | 告警事件页 + 阈值规则配置 | UI-03 |
| `observability/logs` | 系统日志页 + 下钻 + 清理 + 运行时配置 | UI-04 |

- admin 导航（`web/src/pages/admin/index.vue` 或侧栏）加"可观测性"入口。
- 顶部统一 `TimeRangeSelector`（5m/1h/24h/自定义）+ 自动刷新开关（沿用既有 4s 实时 + 后端时序）。

---

## 2. UI-01 大盘上半区

### 2.1 复合健康分卡（圆环）
- 0–100 圆环（echarts gauge 或 `ui/progress` 圆环）；加权：CPU/内存/错误率/上游错误/队列积压。
- 大字分数 + 状态徽标（健康≥80 绿 / 警告 60–79 琥珀 / 严重<60 红）。
- 副行：各因子贡献小条（可选）。

### 2.2 实时速率卡
- 窗口 tab：1min/5min/30min/1h（`ui/tabs`）。
- 三联：当前 / 峰值 / 平均，分 QPS 与 TPS 两组。
- sparkline 迷你趋势（echarts line，无轴）。
- 数据源：`queryMetrics({metric:'qps'|'tps', step, window})`。

### 2.3 信息卡排（grid，桌面 3 列 / 平板 2 列 / 移动 1 列）
| 卡 | 内容 |
|----|------|
| 请求汇总 | 请求数 / Token 数 / 平均 QPS / 平均 TPS |
| SLA | 可用率（**排除业务限制**）大字 + 异常数；副注"排除业务限制（含系统繁忙限流）" |
| 请求错误 | 错误率 + 系统错误数 + 业务限制数（分列）|
| 请求时长 | P99 大字 + P95/P90/P50/Avg/Max（tabular）|
| TTFT | P99 大字 + P95/P90/P50/Avg/Max |
| 上游错误 | 错误率 + 错误数(排除429/529) + 429/529 单列 |

- 复用/扩展 `KpiCards`；分位用 `queryMetrics({agg})`。

---

## 3. UI-02 快照行 + 趋势

### 3.1 快照行（一排卡，内联阈值）
- CPU% / 内存% / DB(连接·活跃·空闲/max) / Redis(连接 x/maxclients·命中率) / Qdrant(可用·collection 数) / 协程数 / 后台任务数。
- **卡内内联阈值**（如 `警告 60% 严重 95%`），当前值超阈变色（绿→琥珀→红）。
- 源不可用时卡显示 `n/a` + 灰态（best-effort 降级，不报错）。
- 数据源：`getMetricsSnapshot()`。

### 3.2 趋势区（`ChartCard` + `TrendChart`/echarts）
| 图 | 维度 |
|----|------|
| 吞吐趋势 | 各 provider QPS+TPS(千)，可切 call_source（`AnalyticsGroupingSelector`）|
| 错误趋势 | 系统 / 上游 / 业务限制 三线 |
| 请求时长分布 | `DurationDistribution` |
| 并发·排队趋势 | provider 槽位 + 索引/AI描述/异步队列深（GaugeSample）|

- 空态/加载骨架；图表 tooltip + 图例可点切系列。

---

## 4. UI-03 告警事件页

### 4.1 事件表（`ui/table`）
列：时间 / 级别(P0-P2 徽标) / 状态(firing 红·resolved 绿) / 维度 / 规则ID / 标题+规则信息(`cpu_usage_percent > 85.00 (current 95.40) over last 5m`) / 持续时长 / 邮件状态(已发送/已忽略/—)。
- 多维筛选：级别 / 状态 / 维度 / 规则 / 时间段（`ui/select` + `TimeRangeSelector`）。
- 行点击 → 详情（sheet）展示完整 rule_info + notified_channels。
- 分页（`ui/pagination`）。

### 4.2 阈值规则配置入口
- "新建规则"按钮 → dialog/sheet 表单：metric(select) / op(select) / value(input) / window / severity(P0/P1/P2) / channels(checkbox: email·feishu·webhook) / cooldown / enabled(switch) / title_template。
- 规则列表（启用/禁用 switch、编辑、删除带 confirm）。
- 数据源：`/api/system/alerts/rules/`（CRUD）、`/api/system/alerts/events/`（list/filter）。

---

## 5. UI-04 系统日志页

### 5.1 顶部四计数
- 队列 x/5000（进度条/徽标）· 写入 · 丢弃(>0 琥珀) · 失败(>0 红)。tabular 数字。

### 5.2 日志列表（倒序）+ 多维筛选
- 列：时间 / 级别(色徽标) / 组件 / category(caller·sampling) / user_id / source / 事件 / message(截断+展开)。
- 筛选：时间段 / 级别 / 组件 / user_id / source / call_source / provider / credential / model / 关联键 / 关键词（全文）。
- 虚拟滚动或分页（量大）。

### 5.3 调用下钻（sheet 抽屉）
- 点行/会话 → 抽屉：会话全部请求·原始数据（Conversation/Message）/ 召回内容（RetrievalTrace：query+chunk+score）/ webhook 原始（脱敏后）。tab 切换三类。
- 数据源：71 drilldown（call/conversation）、webhooks、retrieval。

### 5.4 操作
- "按当前筛选清理"（destructive 按钮 + confirm dialog 二次确认，明示删除范围/不可逆）。
- 运行时日志配置表单（折叠区/独立卡）：级别(全局/分组件) / 堆栈阈值 / 采样初始 / 采样后续 / 保留天数·大小 + caller·sampling 勾选 + 「保存并生效 / 回滚默认」（toast 反馈实时生效）。
- 数据源：`/api/system/logs/`、`/clear/`、运行时配置 get/set。

---

## 6. 组件清单（新建 / 复用）

**复用：** `ChartCard`/`TrendChart`/`KpiCards`/`DurationDistribution`/`TimeRangeSelector`/`AnalyticsGroupingSelector`、`ui/*`（card/badge/table/tabs/select/dialog/sheet/skeleton/tooltip/switch/input/form/pagination/scroll-area/separator/sonner/checkbox/progress）、`VChart`/`chart-theme`。

**新建（建议）：** `HealthScoreGauge.vue`、`RealtimeRateCard.vue`、`MetricInfoCard.vue`（信息卡通用）、`SnapshotRow.vue`（内联阈值卡）、`AlertEventsTable.vue` + `AlertRuleFormDialog.vue`、`SystemLogTable.vue` + `LogDrilldownSheet.vue` + `RuntimeLogConfigForm.vue` + `QueueCountersBar.vue`。组件放 `web/src/components/observability/` 或就近 `pages/admin/observability/components/`。

---

## 7. 验收清单（UI review 用）

- [ ] 三视图路由 + admin 入口可达；时间范围 + 自动刷新生效。
- [ ] UI-01 健康分/速率/6 信息卡数据正确（分位 tabular）。
- [ ] UI-02 快照行内联阈值超阈变色 + 5 类源降级 n/a；4 类趋势图出图 + 空态。
- [ ] UI-03 事件表 8 列对齐 REFERENCE-UI §1.4 + 多维筛选 + 规则 CRUD。
- [ ] UI-04 四计数 + 倒序 + 多维筛选 + 下钻三类 + 按筛选清理(二次确认) + 运行时配置实时生效。
- [ ] a11y：对比/focus/aria-label/reduced-motion；响应式 375/768/1024/1440 无溢出；亮暗双主题。
- [ ] 无 emoji 图标（lucide）；hover 过渡 150–300ms；加载骨架 + 空态；clickable 带 cursor-pointer。
- [ ] i18n 中文（vue-i18n），无硬编码英文文案。
