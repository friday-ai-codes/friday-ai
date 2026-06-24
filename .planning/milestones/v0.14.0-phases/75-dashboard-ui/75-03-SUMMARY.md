---
phase: 75-dashboard-ui
plan: "75-03"
subsystem: web/observability
tags: [ui, observability, alerts, vue, frontend]
requires:
  - "web/src/api/system.ts (75-01：listAlertEvents / 告警规则 CRUD + 类型)"
  - "web/src/components/observability/{ObservabilityTabs,ObservabilityTimeRange,format.ts,status.ts} (75-01/02)"
provides:
  - "告警事件页 UI-03：/admin/observability/alerts（事件表 + 多维筛选 + 详情抽屉 + 阈值规则 CRUD）"
affects:
  - "运维大盘三视图之「告警事件」视图（75-05 负责接入导航/路由编排）"
tech-stack:
  added: []
  patterns:
    - "组件自取数 @tanstack/vue-query（keepPreviousData，queryKey 含筛选参数失效重拉）"
    - "受控枚举表单 reka-ui Select/Checkbox/Switch + zod safeParse 前校验 + 后端 400 ApiError 兜底"
    - "删除走 alert-dialog 二次确认；规则 CRUD invalidate ['obs-alert-rules']/['obs-alert-events'] 联动"
key-files:
  created:
    - web/src/pages/admin/observability/alerts.vue
    - web/src/components/observability/AlertEventsTable.vue
    - web/src/components/observability/AlertEventDetailSheet.vue
    - web/src/components/observability/AlertRuleFormDialog.vue
    - web/src/components/observability/AlertRulesPanel.vue
    - web/src/components/observability/__tests__/alerts.spec.ts
  modified: []
decisions:
  - "表单前校验用 reactive + zod safeParse 手动校验（zod 仍为前置校验层），不引 vee-validate Field 包装——结构更直观、单测更易钉死提交体，与 client.ts ApiError.detail 错误链对齐"
  - "规则筛选选项由父页 props.rules 传入（与 AlertRulesPanel 共享 ['obs-alert-rules'] vue-query 缓存），避免重复请求 listAlertRules"
  - "事件表时间段由父页 ObservabilityTimeRange 受控传入（统一时间轴），表内只保留 级别/状态/规则 三个本地筛选"
  - "维度键 Select 用 'overall' 哨兵代表全局（reka-ui SelectItem 不允许空字符串值）"
metrics:
  duration: ~35m
  completed: 2026-06-25
---

# Phase 75 Plan 03: 告警事件页（UI-03）Summary

实现运维大盘「告警事件页」`/admin/observability/alerts`：8 列告警事件表（对齐 REFERENCE-UI §1.4）+ 级别/状态/规则/时间段多维筛选 + 行详情抽屉（完整 rule_info / target / notified_channels），以及阈值规则配置入口（列表 + 启停 switch + 新建/编辑 dialog + 删除二次确认），全链路消费 75-01 封装的 `listAlertEvents` 与告警规则 CRUD，受控枚举与后端 `alert_serializers` 白名单双层对齐。

## Tasks

- **Task 1 — 事件表 + 详情抽屉：PASS**
  - `AlertEventsTable.vue`：vue-query 自取数（keepPreviousData、queryKey 含筛选参数）；8 列（时间 / 级别 P0-P2 徽标 / 状态 firing红·resolved绿 / 维度 overall兜底 / 规则ID #N·已删 / 标题+rule_info.expr 等宽截断 / 持续时长 firing「进行中」 / 邮件状态 已发送·已忽略·失败·—）；级别/状态/规则筛选映射 `listAlertEvents` 参数、筛选变化重置 offset；limit/offset 上一页/下一页 + total（倒序由后端保证）；骨架/空态(bell-off)/错误态；行 `cursor-pointer` + Enter 键 emit `rowClick`；移动端横向滚动不溢出。
  - `AlertEventDetailSheet.vue`：`ui/sheet` 抽屉，展示标题+级别/状态徽标、起止/持续/当前值/last_seen 概览、rule_info 键值表、target（`<pre>` 文本，**无 v-html**）、notified_channels 通道徽标；event=null 不渲染主体；aria-label 完备。
- **Task 2 — 规则 CRUD + 页面组装 + 单测：PASS**
  - `AlertRuleFormDialog.vue`：受控枚举字段（metric 9 项 / op gt·gte·lt·lte 符号显示 / severity P0-P2 / channels 多选 checkbox / dimension 受控键 Select+值 / window·cooldown number / title_template / enabled switch）；zod 前校验 + 提交 `createAlertRule`/`updateAlertRule`；后端 400 中文 detail 经 ApiError → handleError toast，不崩；异步提交禁用按钮 + spinner。
  - `AlertRulesPanel.vue`：vue-query 自取数；规则列表（人读 expr + 级别徽标 + 窗口/冷却 + 通道徽标 + 启用 switch 即时 `updateAlertRule` + 编辑 + 删除）；删除走 `alert-dialog` 二次确认 → `deleteAlertRule`；空态/骨架/错误；变更后 invalidate `['obs-alert-rules']` 联动事件表规则筛选。
  - `alerts.vue`：`definePage({ meta: { requiresAdmin: true } })`；ObservabilityTabs（高亮告警）+ ObservabilityTimeRange；上 AlertRulesPanel、下 AlertEventsTable（传 rules + 监听 rowClick 打开详情）；规则列表与事件表筛选共享 `['obs-alert-rules']` 缓存。
  - `__tests__/alerts.spec.ts`：5 用例全绿——(a) 8 列表头 + 含 rule_info.expr 行；(b) 选级别 P0 → severity=P0 调 listAlertEvents；(c) 提交合法 body → createAlertRule；(d) 后端 ApiError(400) 展示错误不崩；(e) 删除二次确认 → deleteAlertRule。

## Verification

- `pnpm vue-tsc --noEmit`：**全绿**（无新增类型错误）。
- `pnpm exec vitest run src/components/observability/__tests__/alerts.spec.ts`：**5 passed (5)**。
- `pnpm exec eslint src/pages/admin/observability/alerts.vue src/components/observability`：**干净**（exit 0，无 error/warning）。
- 安全：无 `v-html`（rule_info/target 用 `<pre>`/键值表文本）；表单受控枚举 + zod 前校验 + 后端 400 白名单双层兜底（T-75-03-02）；删除二次确认（T-75-03-04）；页面 requiresAdmin + 后端 IsSuperUser（T-75-03-01）；无新依赖（T-75-03-SC）。

## Deviations from Plan

### 设计抉择（非缺陷）

1. **[Rule 设计抉择] 表单前校验用 reactive + zod safeParse 手动校验**，未用 `ui/form`（vee-validate Field）包装。理由：zod 仍是前置校验层（满足"zod schema 前校验"），手动校验结构更直观、组件单测更易钉死提交体与错误兜底；与既有 `client.ts` `ApiError.detail` 错误链一致。`ui/form` 仍在依赖中、未引入新包。
2. **[Rule 设计抉择] 规则筛选选项由父页 `props.rules` 传入**（事件表不单独再请求 `listAlertRules`），与 AlertRulesPanel 共享 `['obs-alert-rules']` vue-query 缓存——即计划注释中"建议 props.rules 传入避免重复请求"的选项。
3. **[Rule 设计抉择] 事件表时间段由父页 ObservabilityTimeRange 受控传入**（统一时间轴），表内仅保留 级别/状态/规则 三个本地筛选，符合 §4.1"复用页面 ObservabilityTimeRange"。

### 执行说明

- 单测覆盖 reka-ui dialog/alert-dialog 经 teleport 渲染的内容，统一用 `findAllComponents` / `findComponent` 在 Vue 组件树定位（而非 `wrapper.find` DOM 查询，后者取不到 teleport 到 body 的节点）。

## Known Stubs

无。所有数据源均已接 75-01 的真实 API（`listAlertEvents` / `listAlertRules` / `createAlertRule` / `updateAlertRule` / `deleteAlertRule`），无 mock/占位数据流向 UI。

## Self-Check: PASSED

- 文件存在：alerts.vue / AlertEventsTable.vue / AlertEventDetailSheet.vue / AlertRuleFormDialog.vue / AlertRulesPanel.vue / __tests__/alerts.spec.ts 均已落盘。
- typecheck + 单测(5/5) + eslint 全绿。
- 未提交 git（按执行约束，不 commit）。
