---
phase: 75-dashboard-ui
plan: "75-04"
subsystem: web-frontend
tags: [observability, system-logs, vue3, ui-04]
requires: ["75-01"]
provides:
  - "系统日志页 /admin/observability/logs（UI-04）"
  - "QueueCountersBar / SystemLogTable / LogDrilldownSheet / RuntimeLogConfigForm 组件"
affects:
  - "web/src/pages/admin/observability/"
  - "web/src/components/observability/"
tech-stack:
  added: []
  patterns:
    - "vue-query 自取数 + keepPreviousData + counters emit 同源刷新"
    - "reka-ui Sheet/Tabs/Collapsible/AlertDialog + pre 文本渲染（禁 v-html）"
    - "settings.ts getSetting/updateSetting 读写 log.* 点分键（SettingKey 字符串形态转入）"
key-files:
  created:
    - web/src/components/observability/QueueCountersBar.vue
    - web/src/components/observability/SystemLogTable.vue
    - web/src/components/observability/LogDrilldownSheet.vue
    - web/src/components/observability/RuntimeLogConfigForm.vue
    - web/src/components/observability/__tests__/logs.spec.ts
  modified:
    - web/src/pages/admin/observability/logs.vue
decisions:
  - "队列计数键以后端 log_sink.snapshot_counters() 实测键名为准（queued/max/written/dropped/write_failed/sampled_out），用宽松取键 + 兜底 0；不臆造 queue_size/failed"
  - "call_source/provider/credential/model/关联键后端不支持顶层筛选 → 提供「高级维度」对当前页 payload/correlation 客户端 narrowing，不发臆造后端参数"
  - "RuntimeLogConfigForm 复用 settings.ts，不新封装端点；SettingKey 受限枚举不含 log.* → asKey() 以 string 形态转入（运行时即点分串）"
  - "回滚默认仅重置表单为内置默认 + info toast 提示需点保存才落库（二选一）"
metrics:
  duration: ~25min
  completed: 2026-06-25
---

# Phase 75 Plan 04: 系统日志页（UI-04）Summary

把 Phase 71 日志中心（队列化落库 + 可搜索 + 可清理 + 运行时可配 + 调用下钻 + webhook 留痕）落成超管可用界面：顶部队列四计数 bar、倒序多维筛选日志列表、会话/调用/webhook 三类下钻抽屉、按当前筛选清理（二次确认 + 无筛选强制 confirm_all）、运行时日志配置表单（保存实时生效）。

## Tasks

- **Task 1 — QueueCountersBar + SystemLogTable**: PASS
  - `QueueCountersBar.vue`：队列 queued/max(5000) 进度条 + 已写入(written) + 已丢弃(dropped >0 琥珀，副注 sampled_out) + 落库失败(write_failed >0 红)，tabular-nums，缺键兜底 0，loading 骨架。
  - `SystemLogTable.vue`：vue-query 调 `querySystemLogs`（keepPreviousData），顶层筛选级别/来源/组件/user_id/keyword(全文) + 时间段（父页 timeRange）+ 分页(100/页)；counters/rowClick/filtersChange emit；message 截断 + 行展开（pre 渲染 payload/correlation）；高级维度（call_source/provider/credential/model/关联键）当前页客户端 narrowing（带注释明示后端不支持顶层 payload 筛选）。
- **Task 2 — 下钻 + 运行时配置 + 清理 + 页面组装 + 测试**: PASS
  - `LogDrilldownSheet.vue`：会话原始(getConversationDrilldown)/调用明细(getCallDrilldown，触发用户只显 username/fingerprint，不显 token)/webhook 原始(getWebhookEvent，脱敏 headers/raw_body)，Tabs 按 context 可用性渲染 + 懒加载(enabled 受控)；全部 `<pre>`/文本插值，**禁 v-html**。
  - `RuntimeLogConfigForm.vue`：复用 settings.ts 读写 LOG_*（全局级别/分组件级别行编辑/堆栈阈值/采样初始·后续/保留天数·行数 + caller·sampling 文案）；保存并生效（逐键 updateSetting + success toast「已实时生效」）/ 回滚默认（重置 + info toast）；Collapsible 折叠卡，异步禁用 + spinner。
  - `logs.vue`：definePage requiresAdmin；ObservabilityTabs + 时间段/自动刷新 + QueueCountersBar(消费 emit counters) + SystemLogTable(rowClick 解析 correlation→下钻) + 清理按钮(AlertDialog 二次确认，无筛选 confirm_all) + RuntimeLogConfigForm。
  - 测试 `logs.spec.ts`：5 用例覆盖 (a)~(e)，全绿。

## Verification

- `pnpm vue-tsc --noEmit` — 全绿（exit 0）。
- `pnpm exec vitest run src/components/observability/__tests__/logs.spec.ts` — 5 passed。
- `pnpm exec eslint <changed files>`（默认 + CI=true 全规则）— 干净。

## Deviations from Plan

None — 按计划执行。两处计划内的抉择已按 plan 注释明示落地：
- 队列计数键名以后端实测为准（plan 已要求「执行时按后端核对实际键名」）。
- `SettingKey` 受限枚举不含 log.* → 以 string 形态 `asKey()` 转入（plan §136 已允许，无需改 settings.ts，未触碰 files_modified 之外文件）。

## Security (Threat Model)

- **T-75-04-01 EoP**：logs.vue definePage requiresAdmin + 后端全端点 IsSuperUser（纵深防御）。
- **T-75-04-02 Info Disclosure**：下钻/webhook/message 全部 `<pre>`/文本插值（**无 v-html**，测试 (d) 断言 HTML 转义）；触发用户只显 username + fingerprint 哈希，绝不显 token；仅渲染后端已脱敏字段。
- **T-75-04-03 DoS**：清理 AlertDialog 二次确认；无筛选时文案升级「清空全部」并强制 `confirm_all: true`（对齐后端防误清）。
- 无新依赖（复用 reka-ui/vue-query/lucide/sonner/settings.ts）。

## Known Stubs

无。所有数据均接真实 75-01 API；高级维度客户端过滤为有意设计（后端不支持 payload 顶层筛选），已注释并在 UI 提示「仅过滤当前页」。

## Self-Check: PASSED

- 文件均存在：QueueCountersBar.vue / SystemLogTable.vue / LogDrilldownSheet.vue / RuntimeLogConfigForm.vue / __tests__/logs.spec.ts / pages/admin/observability/logs.vue。
- typecheck + 单测(5/5) + eslint 全绿。
