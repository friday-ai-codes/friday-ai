---
phase: 75-dashboard-ui
verified: 2026-06-24T18:30:00Z
status: gaps_found
score: 3/5 must-haves verified
overrides_applied: 0
gaps:
  - truth: "UI-01 信息卡『上游错误』含 429·529 单列"
    status: partial
    reason: "后端 error 时序查询（metrics_query._query_request_metric）仅按 error_class 维度拆分 system/upstream/business，RequestMetric 查询无 429/529 上游状态码维度（上游码落在 ModelUsageRecord.upstream_status_code，未经查询 API 暴露为可聚合维度）。前端如实显示 '—' + footnote「细分 429/529 待后端维度支持」，未臆造拆分。属后端查询维度缺口，非前端实现缺陷。"
    artifacts:
      - path: "web/src/pages/admin/observability/index.vue"
        issue: "上游错误卡 429·529 子项硬编码 EMPTY（line ~355），无数据源可填"
      - path: "server/system/metrics_query.py"
        issue: "_DIMENSIONS 无 upstream_status_code；error metric 仅 system/upstream/business 三口径"
    missing:
      - "后端 metrics_query 增加上游状态码（429/529）可聚合维度，或新增上游码统计端点，前端再补单列数据"
  - truth: "UI-01 请求时长 / TTFT 头部为 P99"
    status: partial
    reason: "后端 metrics_query._AGGS 受控枚举为 {p95,p90,p50,avg,max}，无 p99。前端头部大字取 P95（最高受控分位）+ footnote「后端分位上限，暂无 P99」。属后端聚合能力缺口。"
    artifacts:
      - path: "server/system/metrics_query.py"
        issue: "_AGGS = {p95,p90,p50,avg,max}；_PERCENTILE 无 0.99"
      - path: "web/src/pages/admin/observability/index.vue"
        issue: "durationStats/ttftStats 头部用 p95，未取 p99"
    missing:
      - "后端 _AGGS/_PERCENTILE 增加 p99（percentile_cont 0.99），前端头部改取 P99"
  - truth: "UI-04 系统日志多维筛选支持 call_source/provider/credential/model/关联键（服务端全量过滤）"
    status: partial
    reason: "后端 log_views._apply_filters 仅支持 component/level/user_id/source/start/end/keyword 服务端精确/全文筛选；call_source/provider/credential/model/关联键落在 payload/correlation JSON 内，后端不做顶层列筛选。前端对这 5 个维度提供「高级维度」客户端 narrowing（仅作用当前页），已注释并在 UI 明示「仅过滤当前页（后端不支持 payload 顶层筛选）」。属后端查询缺口；前端做了透明降级，未发臆造参数。"
    artifacts:
      - path: "server/system/log_views.py"
        issue: "_extract_filters/_apply_filters 不含 call_source/provider/credential/model/correlation"
      - path: "web/src/components/observability/SystemLogTable.vue"
        issue: "高级维度（call_source/provider/credential/model/关联键）仅当前页客户端过滤，非服务端全量筛选"
    missing:
      - "后端 SystemLogEntry 查询支持 payload/correlation 内 call_source/provider/credential/model/关联键 服务端筛选（JSON 字段过滤或抽列索引），前端再切为后端参数"
human_verification:
  - test: "超管登录访问 /admin/observability（总览/告警/日志三视图）核对亮/暗双主题"
    expected: "两套主题对比度 ≥4.5:1、状态色语义正确、无样式破裂；颜色非唯一信号（配图标/文字）"
    why_human: "视觉对比度与双主题观感需真机肉眼判定，grep/typecheck 无法验证"
  - test: "375/768/1024/1440 四档断点逐页查看响应式"
    expected: "移动端卡片单列、表格横向滚动不溢出；无横向溢出/重叠"
    why_human: "响应式布局需实际渲染于不同视口验证"
  - test: "接通真实后端，核对快照行内联阈值超阈变色 + 5 类源不可用降级 n/a 灰态"
    expected: "CPU/内存/协程/DB·Redis 连接占比超阈时绿→琥珀→红切换；source available=false 显 n/a 不报错"
    why_human: "需真实运行期数据触发阈值与源不可用分支，静态无法验证渲染正确性"
  - test: "实时速率卡窗口 tab（1m/5m/30m/1h）切换 + 自动刷新（5s）+ 时间范围选择器联动"
    expected: "切窗口/时间范围后 QPS·TPS 当前/峰值/平均 + sparkline 随之更新；自动刷新生效且 document.hidden 暂停"
    why_human: "实时刷新与时序联动行为需运行期观察"
  - test: "告警规则 CRUD 与告警事件页端到端（新建/编辑/启停/删除规则 → 事件表筛选联动）"
    expected: "规则增改删后事件表规则筛选项联动；后端 400 中文 detail 经 toast 不崩"
    why_human: "需真实后端往返与交互流程，单测仅覆盖调用契约不覆盖端到端 UX"
  - test: "系统日志调用下钻三类（会话原始/调用明细含召回/webhook 原始）打开核对脱敏"
    expected: "三抽屉按 correlation 可用性渲染；只显 username/fingerprint 不显 token；原始内容 <pre> 文本无 v-html 注入"
    why_human: "需真实下钻数据验证脱敏字段与内容渲染正确性"
---

# Phase 75: 运维大盘前端 + 规范固化 Verification Report

**Phase Goal:** 后端 API 就绪后做统一运维大盘（借鉴 REFERENCE-UI.md 卡片范式但按 Agent 维度重构），并把日志/埋点规范固化为长期约束。
**Verified:** 2026-06-24T18:30:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #   | Truth (ROADMAP SC / UI-01~04, SPEC-01)                                                                                          | Status      | Evidence                                                                                                                                                                                                                  |
| --- | ------------------------------------------------------------------------------------------------------------------------------ | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | UI-01 大盘上半区：健康分 + 实时速率卡 + 6 信息卡 + 时间范围；含上游错误 429·529 单列 + 请求时长/TTFT **P99**                       | ⚠️ PARTIAL  | `index.vue` 装配 HealthScoreGauge / RealtimeRateCard（1m/5m/30m/1h tab + 当前·峰值·平均 + sparkline）/ 6×MetricInfoCard / ObservabilityTimeRange，消费 `queryMetrics`/`querySla`/`getMetricsSnapshot`。**429/529 单列显 '—'、分位头取 P95**（后端维度/聚合缺口，见 gaps 1·2）。 |
| 2   | UI-02 快照行（CPU/内存/DB/Redis/Qdrant/协程/后台）内联阈值变色 + 吞吐/错误/时长/并发·排队趋势                                       | ✓ VERIFIED  | `SnapshotRow.vue` 7 卡经 `healthBandClass` 超阈变色 + available=false → n/a 降级；`TrendCharts.vue` 吞吐(provider↔call_source 可切)/错误(系统·上游·业务三线)/时长(P95·P50)/并发·排队(GaugeSample) 四图。                                  |
| 3   | UI-03 告警事件页 8 列 + 多维筛选 + 阈值规则配置入口                                                                              | ✓ VERIFIED  | `AlertEventsTable.vue` 8 列（时间/级别/状态/维度/规则ID/标题+rule_info/持续/邮件）+ 级别·状态·规则·时间段筛选 + 分页；`AlertRulesPanel.vue`+`AlertRuleFormDialog.vue` 规则 CRUD（启停/编辑/删除二次确认）；`AlertEventDetailSheet.vue` 详情抽屉。 |
| 4   | UI-04 系统日志页：4 计数 + 倒序 + 多维筛选（含 call_source/provider/credential/model/关联键）+ 下钻三类 + 按筛选清理 + 运行时配置 | ⚠️ PARTIAL  | `QueueCountersBar.vue` 队列/写入/丢弃/失败 4 计数；`SystemLogTable.vue` 倒序+服务端筛选(级别/组件/user_id/source/keyword)+分页；`LogDrilldownSheet.vue` 会话/调用(含召回)/webhook 三 tab；clear-by-filter+confirm_all；`RuntimeLogConfigForm.vue`。**call_source/provider/credential/model/关联键仅客户端当前页 narrowing**（后端缺口，见 gap 3）。 |
| 5   | SPEC-01 规范固化：LOGGING-SPEC 事件目录全量 + cursor 规则 + AGENTS/CLAUDE 复核 + PR/Review checklist 落地                          | ✓ VERIFIED  | `LOGGING-SPEC.md` §9 检查清单（12 项）+ §10.1~10.9 覆盖 Phase 71–74 事件目录 + §4.1 call_source(22 值) + §5 component 清单；`.cursor/rules/observability-logging.mdc` 收敛；AGENTS.md/CLAUDE.md 可观测性章节引用 §9/mdc。            |

**Score:** 3/5 truths fully verified（UI-01、UI-04 部分达成——均因后端查询 API 维度/聚合缺口，非前端实现缺陷）

### Required Artifacts

| Artifact                                                          | Expected                          | Status     | Details                                                              |
| ----------------------------------------------------------------- | --------------------------------- | ---------- | ------------------------------------------------------------------- |
| `web/src/api/system.ts`                                           | 71–74 端点 typed 函数 + interface | ✓ VERIFIED | 13 函数（getMetricsSnapshot/queryMetrics/querySla/告警 CRUD/listAlertEvents/querySystemLogs/clearSystemLogs/webhook/drilldown）；typecheck 绿 |
| `web/src/components/observability/*`（17 件）                     | 全部组件 + format/status 工具      | ✓ VERIFIED | HealthScoreGauge/RealtimeRateCard/MetricInfoCard/SnapshotRow/TrendCharts/AlertEventsTable/AlertEventDetailSheet/AlertRuleFormDialog/AlertRulesPanel/QueueCountersBar/SystemLogTable/LogDrilldownSheet/RuntimeLogConfigForm/ObservabilityTabs/ObservabilityTimeRange/format.ts/status.ts 均存在且实质实现 |
| `web/src/pages/admin/observability/{index,alerts,logs}.vue`       | 三视图页面 + requiresAdmin         | ✓ VERIFIED | 三页 definePage requiresAdmin；装配各自组件 + 共享 tab/时间范围        |
| `web/src/components/layout/AppSidebar.vue`                        | 运维监控入口                       | ✓ VERIFIED | `{ to: '/admin/observability', label: '运维监控', icon: 'lucide--activity' }`（line 105）；三视图由页内 ObservabilityTabs 切换 |
| `.planning/observability/LOGGING-SPEC.md`                         | 事件目录 + checklist 全量          | ✓ VERIFIED | §9 检查清单 + §10.1~10.9 + §4.1/§5 枚举完整                          |
| `.cursor/rules/observability-logging.mdc` + AGENTS.md/CLAUDE.md   | 规则收敛 + 复核                    | ✓ VERIFIED | always-applied 规则在仓内；AGENTS/CLAUDE 可观测性章节引用 §9/mdc 单一来源 |

### Key Link Verification

| From                          | To                                | Via                          | Status   | Details                                                       |
| ----------------------------- | --------------------------------- | ---------------------------- | -------- | ------------------------------------------------------------- |
| index.vue                     | getMetricsSnapshot/queryMetrics   | useQuery 调用真实 API         | ✓ WIRED  | snapshot + qps/tps/error/sla/duration/ttft 全部 useQuery 接入  |
| AlertEventsTable.vue          | listAlertEvents                   | useQuery + queryParams 映射   | ✓ WIRED  | 筛选参数（severity/status/rule_id/start/end）映射后端入参      |
| logs.vue → SystemLogTable     | querySystemLogs                   | counters/rowClick/filters emit | ✓ WIRED | QueueCountersBar 消费 emit counters；rowClick→correlation 下钻 |
| LogDrilldownSheet.vue         | getConversationDrilldown/getCallDrilldown/getWebhookEvent | 三 tab 懒加载 useQuery | ✓ WIRED | enabled 受控，按 context 可用性渲染                            |
| AlertRulesPanel.vue           | createAlertRule/updateAlertRule/deleteAlertRule | vue-query mutation + invalidate | ✓ WIRED | 启停/编辑/删除联动 ['obs-alert-rules']                         |

### Data-Flow Trace (Level 4)

| Artifact          | Data Variable                      | Source                                   | Produces Real Data | Status      |
| ----------------- | ---------------------------------- | ---------------------------------------- | ------------------ | ----------- |
| index.vue 信息卡  | totalRequests/durationStats/...    | queryMetrics（后端 metrics_query SQL 聚合） | ✓（除 429/529 无源） | ⚠️ HOLLOW_PROP（仅 429·529 子项无数据源；其余流通） |
| SnapshotRow.vue   | cards                              | getMetricsSnapshot（collect_snapshot 五源）| ✓                  | ✓ FLOWING   |
| AlertEventsTable  | events                             | listAlertEvents（AlertEvent 查询）         | ✓                  | ✓ FLOWING   |
| SystemLogTable    | items + counters                   | querySystemLogs（SystemLogEntry + log_sink）| ✓                | ✓ FLOWING   |
| LogDrilldownSheet | conversation/call/webhook          | 三 drilldown 端点（真实 ORM 查询）          | ✓                  | ✓ FLOWING   |

> 唯一 HOLLOW 数据点：UI-01 上游错误卡「429·529」子项（后端无该聚合维度，前端如实显 '—'）。其余卡片/表格/图表/抽屉数据均流通自真实后端查询。

### Behavioral Spot-Checks

| Behavior              | Command                                                                          | Result          | Status |
| --------------------- | -------------------------------------------------------------------------------- | --------------- | ------ |
| 前端类型契约编译       | `pnpm vue-tsc --noEmit`                                                           | exit 0（全仓无错）| ✓ PASS |
| 观测组件 + API 单测    | `pnpm exec vitest run src/components/observability src/api/__tests__/observability.spec.ts` | 4 files / 22 tests passed | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan        | Description                  | Status      | Evidence                                                       |
| ----------- | ------------------ | ---------------------------- | ----------- | -------------------------------------------------------------- |
| UI-01       | 75-01/75-02        | 大盘上半区                    | ⚠️ PARTIAL  | 健康分/速率/6 卡/时间范围齐备；429·529 单列无后端维度 + 分位取 P95（非 P99） |
| UI-02       | 75-01/75-02        | 快照行 + 趋势                 | ✓ SATISFIED | SnapshotRow 内联阈值 + TrendCharts 四图                         |
| UI-03       | 75-01/75-03        | 告警事件页 + 规则配置          | ✓ SATISFIED | 8 列表 + 多维筛选 + 规则 CRUD + 详情抽屉                        |
| UI-04       | 75-01/75-04        | 系统日志页                    | ⚠️ PARTIAL  | 4 计数/倒序/下钻/清理/运行时配置齐备；5 个高级维度仅客户端当前页 narrowing |
| SPEC-01     | 75-05              | 规范固化                      | ✓ SATISFIED | LOGGING-SPEC §9/§10 + mdc + AGENTS/CLAUDE 收敛                  |

无 ORPHANED 需求（REQUIREMENTS.md Phase 75 仅映射 UI-01~04 + SPEC-01，均被 plan 认领）。

### Anti-Patterns Found

| File                              | Line | Pattern                  | Severity | Impact                                                       |
| --------------------------------- | ---- | ------------------------ | -------- | ----------------------------------------------------------- |
| index.vue                         | ~355 | 上游错误 429·529 子项 EMPTY | ⚠️ Warning | 非 stub——后端无该维度，前端如实 '—' + footnote 标注，已透明降级 |
| SystemLogTable.vue                | 83+  | 高级维度客户端 narrowing   | ⚠️ Warning | 非 stub——后端不支持 payload 顶层筛选，UI 明示「仅过滤当前页」  |

未发现 🛑 Blocker 级反模式：无未引用的 `TBD/FIXME/XXX` 调试标记；无 `v-html`（下钻/原始内容均 `<pre>`/文本插值）；无明文 token/凭证字段（下钻仅展示 username/fingerprint）；无 mock/占位数据流向 UI（除上述两处已透明降级的后端缺口）。

### Human Verification Required

见 frontmatter `human_verification`（6 项）：亮/暗双主题、375/768/1024/1440 响应式、真机快照阈值变色与源降级、实时速率/自动刷新/时间范围联动、告警规则 CRUD 端到端、日志下钻三类脱敏。均为需运行浏览器 + 真实后端数据的纯视觉/交互 UAT，静态验证无法覆盖。

### Gaps Summary

代码层 5 个交付项中 **UI-02、UI-03、SPEC-01 完全达成**；**UI-01、UI-04 部分达成**。三处缺口（429/529 单列无聚合维度、请求时长/TTFT 无 P99、系统日志 5 个高级维度无服务端筛选）**全部源于后端查询 API 能力边界**（`server/system/metrics_query.py` 的 `_AGGS`/`_DIMENSIONS` 与 `log_views.py` 的 `_apply_filters`），**非前端实现缺陷**——75-02/75-04 summary 已主动声明，前端对三处均做了诚实降级（'—' + footnote / 客户端当前页 narrowing + UI 明示），未臆造数据或参数。

由于 Phase 75 是 v0.14.0 里程碑末阶段（无后续 Phase 可承接），这三项不可作为「deferred」处理。它们要么作为后端后续工作（新增 p99 聚合 / 上游码维度 / SystemLogEntry JSON 字段服务端筛选），要么由人类对「UI-01/UI-04 字面措辞 vs 后端当前能力」做接受性裁决（override）。前端代码本身已就绪、可在后端补齐维度后零成本切换。typecheck + 22 单测全绿，无 blocker 反模式。

---

_Verified: 2026-06-24T18:30:00Z_
_Verifier: Claude (gsd-verifier)_
