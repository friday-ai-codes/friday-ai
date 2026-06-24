---
phase: 75-dashboard-ui
plan: "75-03"
subsystem: web-observability
tags: [frontend, vue3, observability, alerts, ui-03]
requires:
  - "web/src/api/system.ts（listAlertEvents / 告警规则 CRUD + 类型，75-01 产出）"
  - "web/src/components/observability/{ObservabilityTabs,ObservabilityTimeRange,format.ts,status.ts}（75-01）"
  - "web/src/components/ui/*（table/badge/select/dialog/sheet/switch/checkbox/input/label/skeleton/alert-dialog/button）"
provides:
  - "告警事件页 /admin/observability/alerts（UI-03）：事件表 + 多维筛选 + 详情抽屉 + 阈值规则 CRUD"
affects:
  - "运维大盘三视图导航的「告警事件」目标页（路由由 75-05 收口）"
tech-stack:
  added: []
  patterns:
    - "组件自取数 + vue-query keepPreviousData（事件表 / 规则面板）"
    - "受控枚举字段 + zod 前校验 + 后端 400（ApiError.detail）兜底双层防御"
    - "规则面板与事件表共享 ['obs-alert-rules'] queryKey 缓存，增删改 invalidate 联动"
key-files:
  created:
    - "web/src/components/observability/AlertEventsTable.vue"
    - "web/src/components/observability/AlertEventDetailSheet.vue"
    - "web/src/components/observability/AlertRuleFormDialog.vue"
    - "web/src/components/observability/AlertRulesPanel.vue"
    - "web/src/components/observability/__tests__/alerts.spec.ts"
  modified:
    - "web/src/pages/admin/observability/alerts.vue（新建页面文件，files_modified 已声明）"
decisions:
  - "事件表自取数并内部维护筛选/分页（plan 建议），规则筛选选项由父页 props.rules 传入避免重复请求"
  - "维度键 Select 用 'overall' 哨兵代表全局（reka-ui SelectItem 禁空字符串值）"
  - "持续时长按 duration_s 秒级本地格式化（format.ts 仅有 ms 版且不在 files_modified，故组件内置纯函数）"
metrics:
  duration: "~30m"
  completed: "2026-06-25"
---

# Phase 75 Plan 03: 告警事件页（UI-03）Summary

实现 `/admin/observability/alerts` 告警事件页：8 列事件表（对齐 REFERENCE-UI §1.4）+ 级别/状态/规则多维筛选 + 行详情抽屉，以及阈值规则配置入口（列表 + 启停 switch + 新建/编辑 dialog 受控枚举表单 + 删除二次确认），消费 75-01 封装的 `listAlertEvents` 与告警规则 CRUD。

## Tasks

- **Task 1 — PASS**：`AlertEventsTable.vue`（8 列：时间/级别/状态/维度/规则ID/标题+rule_info.expr/持续时长/邮件状态 + 级别·状态·规则多维筛选 + limit/offset 分页 + 行点击 emit + 骨架/空态/错误态 + 移动端横向滚动）；`AlertEventDetailSheet.vue`（完整 rule_info 键值表 + target/notified_channels + 起止/持续/当前值/last_seen，`<pre>` 文本渲染无 v-html）。
- **Task 2 — PASS**：`AlertRuleFormDialog.vue`（metric/op/value/window/severity/channels/cooldown/dimension/title_template/enabled 受控枚举 + zod 前校验 + ApiError 400 兜底 + sonner toast + 提交禁用 spinner）；`AlertRulesPanel.vue`（规则列表 + 启停 switch + 编辑 + 删除 alert-dialog 二次确认 + 空态/骨架，CRUD 后 invalidate + emit changed）；`alerts.vue`（definePage requiresAdmin + ObservabilityTabs + 时间段 + 规则面板 + 事件表 + 详情 sheet 联动 + 可选自动刷新）；组件单测 5 例。

## Verification Results

- `pnpm vue-tsc --noEmit`：**PASS**（全项目 0 error；初次发现并修复 `form.value` 类型 `number|null`→`number|undefined` 以匹配 Input modelValue）。
- `pnpm exec vitest run src/components/observability/__tests__/alerts.spec.ts`：**PASS**（5/5）——(a) 8 列表头 + expr；(b) 选 P0 以 severity=P0 调 listAlertEvents；(c) 合法 body 调 createAlertRule；(d) ApiError(400) 不崩 + handleError 被调；(e) 删除二次确认后调 deleteAlertRule。
- `pnpm exec eslint src/pages/admin/observability/alerts.vue src/components/observability`：**PASS**（0 error）。

## Files Changed

- 新建：`AlertEventsTable.vue` / `AlertEventDetailSheet.vue` / `AlertRuleFormDialog.vue` / `AlertRulesPanel.vue` / `__tests__/alerts.spec.ts`
- 新建页面（plan files_modified 已声明）：`web/src/pages/admin/observability/alerts.vue`

未触碰 `files_modified` 之外的文件；未改共享路由/导航（留给 75-05）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] reka-ui SelectItem 禁空字符串值**
- **Found during:** Task 2（单测首次运行报 `<SelectItem /> must have a value prop that is not an empty string`）。
- **Fix:** 维度键「全局」选项由 `value=''` 改为哨兵 `value='overall'`（`DIM_OVERALL`），提交时 `dimensionKey === 'overall'` 视为无维度（`dimension: {}`）。
- **Files modified:** `AlertRuleFormDialog.vue`。

**2. [Rule 3 - Blocking] Input modelValue 不接受 null**
- **Found during:** Task 2 typecheck（`form.value: number|null` 不可赋给 Input `string|number|undefined`）。
- **Fix:** `FormState.value` 改为 `number | undefined`，默认 `undefined`；zod `z.number({message})` 对 undefined 报「请填写有效阈值」。
- **Files modified:** `AlertRuleFormDialog.vue`。

### 实现取舍（非缺陷）

- 持续时长用组件内置秒级格式化纯函数（`format.ts` 仅 `formatDurationMs` 且不在 files_modified，避免越界改共享模块）。
- `AlertRuleFormDialog` 用 reactive form + zod `safeParse` 前校验（而非 vee-validate `Form`），更易测、更贴近 ApiError 字段/toast 兜底；仍满足「zod 前校验 + 受控枚举 + 后端 400 兜底」契约。
- 自动刷新默认**关闭**（历史告警事件页非实时刚需），开启时 10s invalidate `obs-alert-*` query；手动「立即刷新」按钮 invalidate 同前缀 query。

## Threat Model Compliance

- **T-75-03-01（越权）**：`alerts.vue` `definePage({ meta: { requiresAdmin: true } })`；写操作经后端 IsSuperUser CRUD。✓
- **T-75-03-02（注入污染）**：表单 metric/op/severity 用 Select 限受控枚举、channels 用 checkbox 子集、dimension 用受控键 Select；zod 前校验 + 后端 400 白名单兜底（双层）。✓
- **T-75-03-03（信息泄漏）**：rule_info/target 用 `<pre>`/键值表文本渲染，**无 v-html**；只读直出后端已脱敏元数据。✓
- **T-75-03-04（误删）**：删除走 `alert-dialog` 二次确认（明示不可逆）。✓
- **T-75-03-SC**：无新增依赖（复用 reka-ui/zod/vue-query/sonner/lucide）。✓

## Known Stubs

无。所有数据均接 75-01 真实 API；无硬编码占位数据流向渲染。

## Self-Check: PASSED

- 文件存在：`AlertEventsTable.vue` / `AlertEventDetailSheet.vue` / `AlertRuleFormDialog.vue` / `AlertRulesPanel.vue` / `__tests__/alerts.spec.ts` / `pages/admin/observability/alerts.vue` 均 FOUND。
- 未 git commit（按执行约束）。
