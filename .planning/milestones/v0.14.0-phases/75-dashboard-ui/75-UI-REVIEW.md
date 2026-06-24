# Phase 75 — 运维大盘前端 UI Review（6 维度代码级审计）

**Audited:** 2026-06-25
**Baseline:** `75-UI-SPEC.md`（§0 设计原则 + §7 验收清单）
**Screenshots:** 未捕获（localhost:3000/5173/8080 均无 dev server，纯代码级审计）
**Scope:** `pages/admin/observability/{index,alerts,logs}.vue` + `components/observability/*.vue`（15 组件）+ `format.ts` / `status.ts`
**性质：** 顾问性 / 非阻塞（advisory）。纯视觉渲染项（真实对比度、断点表现、亮/暗主题切换）需浏览器 UAT，已单列为「建议人工 UAT」，不计阻塞。

---

## 维度评分总览

| # | 维度 | 判定 | 分 | 关键发现 |
|---|------|------|----|---------|
| 1 | 视觉层级与一致性 | PASS | 4/4 | 全量复用 ui/* + ChartCard/VChart + 集中式 `status.ts` 语义色；信息分层贴合 §0.2 |
| 2 | 可访问性 a11y | FLAG | 2/4 | 可聚焦表格行缺可见 focus ring（high）；图表无 aria/文字替代；微小低透明文字对比待验 |
| 3 | 响应式 | PASS | 4/4 | 响应式 grid + 表格 `overflow-x-auto min-w-[…]` 横向滚动；无固定宽溢出（待断点 UAT） |
| 4 | 交互与反馈 | PASS | 4/4 | hover 150–300ms、骨架、空态、异步禁用+spinner、destructive 二次确认、cursor-pointer 齐备 |
| 5 | 数据可视化质量 | PASS | 3/4 | tabular-nums + 图例/tooltip + 空态/降级齐全；但 `chart-theme` 为浅色单主题（暗色 tooltip 风险） |
| 6 | i18n 与打磨 | PASS | 3/4 | 中文一致、无英文文案泄漏、全程禁 v-html；但文案为硬编码中文，未接 vue-i18n（偏离 §7） |

**总分：20 / 24** — 实现完成度高、契约基本达成。无阻塞项；1 项 high a11y（表格行 focus ring）建议 GA 前修复。

---

## Top 优先修复

1. **可聚焦表格行无可见焦点环（high / a11y）** — 键盘用户无法看清当前聚焦行。
   `AlertEventsTable.vue:294-301`、`SystemLogTable.vue:378-382` 行有 `tabindex="0"` + `@keydown.enter` 但仅 `cursor-pointer transition-colors`，无 `focus-visible:ring`。
   *修复：* 行 class 加 `focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 focus-visible:ring-inset`，并补 `@keydown.space.prevent`。

2. **图表缺 aria/文字替代 + 主题为浅色单主题（medium / a11y + data-viz）** — 偏离 §0.5「图表提供文字/表格替代或 aria-label」；且 `chart-theme.ts:14-21` tooltip 硬编码白底深字（`rgba(255,255,255,0.98)` / `#0f172a`），暗色主题下 tooltip 反差突兀。
   *修复：* `<VChart>` 容器加 `role="img"` + `aria-label`（趋势摘要）；tooltip 背景/文字改用随主题变量或注册暗色 echarts 主题（需联动 analytics，跨 plan 评估）。

3. **文案硬编码中文未接 vue-i18n（medium / i18n）** — §7 验收要求「i18n 中文（vue-i18n）」，当前所有用户文案为模板内硬编码 zh-CN 字面量（如 `运维大盘`/`告警事件`/`暂无系统日志`），未走 `$t()`。技术名词（QPS/TTFT/run_id/payload 等）保留英文符合规范。
   *修复：* 若多语言为目标里程碑则抽取 i18n key；若 zh-first 可接受，建议在 SPEC 中显式降级该验收项。

---

## 分维度详细发现

### 维度 1：视觉层级与一致性 — PASS（4/4）

**符合：**
- 全量复用既有设计系统组件：`Card/Badge/Button/Select/Table/Sheet/Dialog/AlertDialog/Switch/Checkbox/Progress/Skeleton/Collapsible/Tabs`；图表复用 `ChartCard` + `VChart` + `chart-theme`（`TrendCharts.vue:22-31`、`RealtimeRateCard.vue:17-18`）。
- 语义状态色集中在 `status.ts`（`logLevelClass`/`alertSeverityClass`/`alertStatusClass`/`healthBandClass`/`healthScoreBand`），健康=emerald、警告=amber、严重=rose、信息=blue、采样=teal/muted，三页一致复用。
- 信息分层严格贴合 §0.2：健康分 → 速率 → 6 信息卡 → 快照 → 趋势（`index.vue:277-400`）；三页标题栏结构统一（图标芯片 + 标题 + 副标）。
- `MetricInfoCard` / `SnapshotRow` / `QueueCountersBar` 卡片圆角/边框/留白风格统一（`rounded-xl border-border/60-70`）。

**轻微（low）：**
- 严重态色用 Tailwind `rose-500`（`status.ts:15,30,38,53`），而错误/按钮处用 token `text-destructive`（`AlertEventsTable.vue:279`、`AlertRulesPanel.vue:222`）。两套「红」内部各自一致，但 token 与调色板混用，略偏离 §0.1「以主题变量为准」。建议统一到 `destructive`/`--destructive`。
- 图标芯片底色用 `bg-blue-500/10`、`bg-violet-500/10`、`bg-orange-500/10`（`index.vue:294-372`）等调色板色而非语义 token——属 analytics 既有范式，可接受，非新调色板。

### 维度 2：可访问性 a11y — FLAG（2/4）

**符合：**
- 图标按钮普遍带 `aria-label`：清理/刷新/分页/规则编辑删除/展开收起/移除组件级别（`logs.vue:159`、`ObservabilityTimeRange.vue:129`、`AlertEventsTable.vue:357-361`、`AlertRulesPanel.vue:218-221`、`SystemLogTable.vue:419`）。
- SVG 健康环 `role="img"` + 动态 `aria-label`（含分数与档位，`HealthScoreGauge.vue:167`）。
- 速率窗口 tab `role="tablist"/role="tab"/:aria-selected`（`RealtimeRateCard.vue:153-161`）；导航 `aria-current="page"`（`ObservabilityTabs.vue:41`）。
- **颜色非唯一信号**：firing/resolved 徽标配 flame/check 图标 + 文字（`AlertEventsTable.vue:317-321`）；健康档配圆点 + 文字（`HealthScoreGauge.vue:204-208`）；日志级别/类别/告警级别均为文字徽标。达成 §0.3。
- `prefers-reduced-motion` 降级（`HealthScoreGauge.vue:230-234`，环过渡禁用）。
- 自定义按钮/输入有 `focus-visible:ring`（rate tab、nav、collapsible trigger、datetime-local）。

**问题：**
- **(high)** 表格数据行可键盘聚焦但无可见焦点样式——`AlertEventsTable.vue:294-301`、`SystemLogTable.vue:378-382`。键盘可达却不可见，违反 §0.5「focus ring 可见」。
- **(medium)** 图表（sparkline + 4 趋势图）无 `aria-label`/`role`/文字替代（`RealtimeRateCard.vue:196,226`、`TrendCharts.vue:311,326,350,365`）；仅 `prefers-reduced-motion` 仅覆盖健康环，未覆盖图表/loader。偏离 §0.5「图表提供文字/表格替代或 aria-label」。
- **(medium / 需 UAT)** 大量极小号 + 低透明灰字可能 < 4.5:1：`SnapshotRow.vue:250-254`（`text-[10px] text-muted-foreground/60`、`/50`）、`MetricInfoCard.vue:105`（footnote `/70`）、`HealthScoreGauge.vue:194`（`text-[11px]`）。需浏览器实测对比度。

### 维度 3：响应式 — PASS（4/4，真实断点需 UAT）

**符合：**
- 三页容器 `mx-auto max-w-7xl … p-4 sm:p-6`；信息卡 `sm:grid-cols-2 lg:grid-cols-3`（`index.vue:289`）；快照行 `grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7`（`SnapshotRow.vue:216`）；健康/速率 `lg:grid-cols-[minmax(280px,1fr)_2fr]`；趋势 `lg:grid-cols-2`；四计数 `grid-cols-2 lg:grid-cols-4`。
- 表格 `overflow-x-auto` + `min-w-[860px]/[920px]` → 移动端横向滚动不溢出（§0.6 允许，`AlertEventsTable.vue:239-240`、`SystemLogTable.vue:322-323`）。
- 顶部 tab 导航 `overflow-x-auto`（`ObservabilityTabs.vue:34`）；筛选条 `flex flex-wrap`；Dialog `max-h-[90vh] overflow-y-auto`；Sheet `w-full sm:max-w-md/2xl`。

**轻微（low）：**
- 筛选区多为固定宽 Select/Input（`w-[120px]`～`w-[200px]`），靠 `flex-wrap` 换行避免溢出；375px 下会多行堆叠（可接受），建议 UAT 确认拥挤度。

### 维度 4：交互与反馈 — PASS（4/4）

**符合：**
- hover 过渡 150–300ms：`MetricInfoCard.vue:59`、`ChartCard.vue:23`、`SnapshotRow.vue:231`、`ObservabilityTabs.vue:42`、`RealtimeRateCard.vue:162` 均 `duration-200`；表格行 `transition-colors`（默认 150ms）。
- 加载骨架：全组件覆盖（卡/表/图/抽屉，`Skeleton`）。
- 空态：告警事件、系统日志、趋势图（4 张各有空态 + 图标）、规则面板（含「创建第一条」CTA）、下钻无关联键（`LogDrilldownSheet.vue:138-141`）。
- 异步禁用 + spinner：清理（`logs.vue:212-216`）、删除规则（`AlertRulesPanel.vue:242-246`）、保存/创建（`AlertRuleFormDialog.vue:390-392`、`RuntimeLogConfigForm.vue:341-343`）、规则启停 `:disabled="togglingId===rule.id"`。
- destructive 二次确认：清理日志 AlertDialog（区分有/无筛选 + `confirm_all` 文案，`logs.vue:196-221`）、删除规则 AlertDialog（`AlertRulesPanel.vue:233-251`）。
- cursor-pointer：表格行、tab、nav、rate tab、datetime-local、checkbox/switch label、collapsible trigger。

### 维度 5：数据可视化质量 — PASS（3/4）

**符合：**
- `tabular-nums` 覆盖所有分位/计数/QPS·TPS/时间戳（达成 §0.4）。
- 图例 + tooltip：`baseLineOption` 统一 legend（icon circle）+ `tooltip trigger:'axis'` + `tooltipStyle`（`TrendCharts.vue:117-138`）；sparkline 自定义 `/s` 格式 tooltip（`RealtimeRateCard.vue:106-114`）。
- 空态/降级：每趋势图独立空态；SQLite 近似分位「近似分位」徽标 + 描述切换（`TrendCharts.vue:208,332,336-344`）。
- echarts 主题复用 analytics `chart-theme`（axis/legend/grid/tooltip），双轴 TPS(千) 标注清晰。

**问题：**
- **(medium / 需 UAT)** `chart-theme.ts` 自注释为「浅色主题片段」，tooltip 硬编码白底深字（`:14-21`）、轴 `#64748b`。暗色主题下 tooltip 仍为白底，风格割裂、对比可能失衡。§0.1 要求亮/暗双主题落地。建议注册暗色 echarts 主题或令 tooltip 背景随 CSS 变量。
- **(low)** 系列色为 canvas 内硬编码 hex（`PALETTE`、`#3b82f6`/`#8b5cf6` 等）——canvas 内无法用 Tailwind class，属合理；仅记录。

### 维度 6：i18n 与打磨 — PASS（3/4）

**符合：**
- 全程中文用户文案，无英文文案泄漏；技术名词（QPS/TPS/TTFT/P99/run_id/payload/correlation/webhook/fingerprint/call_source）保留英文，符合 doc-writing 规范。
- **禁 v-html**：所有原始/JSON 数据走 `<pre>{{ }}` 文本插值（`AlertEventDetailSheet.vue:175`、`SystemLogTable.vue:439-459`、`LogDrilldownSheet.vue:234,247,307-328,389-396`），多处注释显式声明禁 v-html。达成安全打磨项。
- 打磨细节到位：口径 footnote、SQLite 降级提示、`confirm_all` 风险文案、规则表单占位符示例。

**问题：**
- **(medium)** 文案为模板内硬编码 zh-CN 字面量，未接 `vue-i18n`（`$t()`）——偏离 §7「i18n 中文（vue-i18n）」。zh-first 场景功能无碍，但与验收项字面不符；建议抽 key 或在 SPEC 显式降级。

---

## §7 验收清单核对（代码级可判定项）

| 验收项 | 结论 |
|--------|------|
| 三视图路由 + admin 入口可达 | ✅ `AppSidebar.vue:105` 加「运维监控」入口；三页 `definePage requiresAdmin` |
| 时间范围 + 自动刷新生效 | ✅ `ObservabilityTimeRange` + 各页定时器 + visibilitychange 暂停 |
| UI-01 健康分/速率/6 信息卡（分位 tabular） | ✅ tabular-nums 齐全；P99 头部 + P95/P90/P50/Avg/Max 副行 |
| UI-02 快照内联阈值变色 + n/a 降级；4 趋势图 + 空态 | ✅ `SnapshotRow` 阈值 + `available` 灰态；4 图各空态 |
| UI-03 事件表 8 列 + 多维筛选 + 规则 CRUD | ✅ 8 列对齐；级别/状态/规则筛选；规则增删改 + 启停 + 二次确认 |
| UI-04 四计数 + 倒序 + 多维筛选 + 下钻三类 + 清理(二次确认) + 运行时配置 | ✅ 全覆盖；下钻 conversation/call/webhook 三 tab |
| a11y：focus/aria-label/reduced-motion；响应式无溢出；亮暗双主题 | ⚠️ aria-label/reduced-motion 部分达成；**表格行 focus ring 缺失**；暗色图表主题待补；对比/断点/主题需 UAT |
| 无 emoji 图标（lucide）；hover 150–300ms；骨架 + 空态；clickable cursor-pointer | ✅ 全为 `icon-[lucide--*]`，无 emoji；其余齐备 |
| i18n 中文（vue-i18n），无硬编码英文 | ⚠️ 中文/无英文泄漏达成；**未接 vue-i18n（硬编码 zh-CN）** |

---

## 建议人工 UAT（浏览器内验证，非阻塞）

- 亮/暗双主题逐页核对：尤其 echarts tooltip 暗色表现、微小灰字（`text-muted-foreground/50-70` @ 10–11px）实际对比度 ≥ 4.5:1。
- 375 / 768 / 1024 / 1440 四断点：信息卡/快照行换列、表格横向滚动、筛选条换行拥挤度、Sheet/Dialog 移动端高度溢出。
- 键盘操作：Tab 进入表格行的焦点可见性（修复后复验）、Sheet/Dialog 焦点陷阱与 Esc 关闭、Select/Tabs 键盘导航。
- 实时刷新与 `placeholderData` 切换时数字抖动（tabular-nums 应已缓解）。

---

## Files Audited

- `web/src/pages/admin/observability/index.vue`、`alerts.vue`、`logs.vue`
- `web/src/components/observability/`：`HealthScoreGauge` `RealtimeRateCard` `MetricInfoCard` `SnapshotRow` `TrendCharts` `AlertEventsTable` `AlertEventDetailSheet` `AlertRuleFormDialog` `AlertRulesPanel` `QueueCountersBar` `SystemLogTable` `LogDrilldownSheet` `RuntimeLogConfigForm` `ObservabilityTabs` `ObservabilityTimeRange`
- `web/src/components/observability/format.ts`、`status.ts`
- 旁证：`web/src/components/analytics/chart-theme.ts`、`ChartCard.vue`、`web/src/components/layout/AppSidebar.vue`

## Registry Safety

不适用——本期未引入 shadcn 第三方 registry block（全部复用既有 `ui/*` 与 analytics 组件）。

---

## Polish applied（2026-06-25）

两处 UI 打磨已落地（未提交 git）：

- **Fix 1（a11y，高）：可聚焦表格行的键盘焦点环。** `AlertEventsTable.vue`、`SystemLogTable.vue` 的数据行此前有 `tabindex=0` + `@keydown.enter` 但无可见焦点指示。补充 `focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:ring-inset`，沿用项目既有 `ring-ring` 设计令牌；`ring-inset` 避免行边缘裁切，明暗主题均生效，hover 样式保留。
- **Fix 2（data-viz 暗色，中）：图表 tooltip 主题感知。** `analytics/chart-theme.ts` 的 `tooltipStyle` 原硬编码白底深字（white-on-light），暗色下对比度不足。改为引用 Tailwind 4 `@theme` 暴露的 CSS 变量（`var(--color-popover)` / `var(--color-border)` / `var(--color-popover-foreground)`）。ECharts 默认 tooltip 以 HTML DOM 渲染，内联样式中的 CSS 变量在浏览器侧按当前主题解析，故无需在各图表内做主题分支，且当前 light 主题取值与旧值一致（popover=白、foreground=slate-800、border=slate-200），对既有 analytics 图表（TrendChart / TokenCostChart / DurationDistribution）零回归；阴影不透明度从 0.1 微调至 0.18 以增强暗色可辨识度。

**Verify：** `pnpm vue-tsc --noEmit` 通过；`pnpm exec eslint <changed files>` 通过；`pnpm exec vitest run src/components/observability src/components/analytics` → 4 文件 22 用例全过。
