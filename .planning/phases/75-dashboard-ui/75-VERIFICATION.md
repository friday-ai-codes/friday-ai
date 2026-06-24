---
phase: 75-dashboard-ui
verified: 2026-06-25T02:45:00Z
status: passed
score: 5/5 must-haves verified
overrides_applied: 0
gap_closure: 2026-06-25T02:45:00Z
gaps:
  - truth: "UI-01 信息卡『上游错误』含 429·529 单列"
    status: closed
    reason: "后端 metrics_query 新增 'upstream' metric（_query_upstream），聚合 ModelUsageRecord.upstream_status_code 为受控 CASE dim（429/529/other），仅统计 upstream_status_code IS NOT NULL 行，双后端 CASE 通用。前端 index.vue 新增 obs-upstream-breakdown 查询 + upstreamCounts 派生，上游错误卡用 429 限流 / 529 过载 / 其它上游码 / 上游错误数 单列取代旧 '—' 占位。"
    resolution:
      - "server/system/metrics_query.py: _METRICS 增 'upstream'；新增 _query_upstream + 分派"
      - "web/src/pages/admin/observability/index.vue: upstreamBreakdown 查询 + upstreamCounts + 卡片单列"
      - "web/src/api/system.ts: MetricName 增 'upstream'"
    test: "tests/test_metrics_query.py::test_upstream_breakdown_429_529_other（429=2/529=1/other=1，null 排除）"
  - truth: "UI-01 请求时长 / TTFT 头部为 P99"
    status: closed
    reason: "后端 _AGGS 增 p99、_PERCENTILE 增 0.99（Postgres percentile_cont(0.99) 精确，SQLite 降级 MAX 兜底 degraded=true）。前端 DURATION_AGGS 增 p99，请求时长 / TTFT 卡大字头取 P99，P95/P90/P50/Avg/Max 列于副行。"
    resolution:
      - "server/system/metrics_query.py: _AGGS 增 p99；_PERCENTILE['p99']=0.99（SQLite degrade 复用 MAX 分支）"
      - "web/src/pages/admin/observability/index.vue: DURATION_AGGS/percentileSummary 增 p99，头部改 P99"
      - "web/src/api/system.ts: MetricAgg 增 'p99'"
    test: "tests/test_metrics_query.py::test_validate_accepts_p99_and_upstream_metric + test_duration_p99_accepted_and_degrades_on_sqlite"
  - truth: "UI-04 系统日志多维筛选支持 call_source/provider/credential/model/关联键（服务端全量过滤）"
    status: closed
    reason: "后端 log_views._extract_filters/_apply_filters 增 5 维：call_source/provider/credential/model 走 payload jsonb 顶层键精确匹配（payload__<key>=），关联键 correlation 走 Cast(correlation→text)__icontains 子串检索（覆盖任意键/值）。双后端 JSON 字段查找原生支持。前端 SystemLogTable 高级维度由当前页客户端 narrowing 切为真实服务端查询参数（advKey 键名即 SystemLogQuery 键），移除『仅过滤当前页』提示，改为『服务端全量筛选』。clear-by-filter 经共用 _apply_filters 同步支持。"
    resolution:
      - "server/system/log_views.py: _extract_filters/_has_any_filter/_apply_filters 增 5 维（payload 精确 + correlation 文本子串）"
      - "web/src/components/observability/SystemLogTable.vue: 高级维度映射为服务端 query 参数（含 300ms 防抖），删除客户端 narrowing"
      - "web/src/api/system.ts: SystemLogQuery 增 call_source/provider/credential/model/correlation"
    test: "tests/test_system_log_api.py::test_filter_by_{call_source,provider,credential,model}_payload + test_filter_by_correlation_substring + test_clear_by_advanced_dim_call_source"
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
**Verified:** 2026-06-24T18:30:00Z（初验）→ 2026-06-25T02:45:00Z（缺口闭合复核）
**Status:** passed（3 处后端查询缺口已闭合，见文末「Gap Closure」）
**Re-verification:** Yes — 初验 gaps_found（5 truths 中 2 PARTIAL）→ 三处缺口实现 + 测试后转 passed

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

## Gap Closure (2026-06-25)

初验三处缺口**全部源于后端查询 API 能力边界**（已在初验中如实标注，非前端实现缺陷）。本次按"后端补能力 + 前端切真实数据源"闭合，零 model 变更（纯 query-only，`makemigrations --check` 干净）。

### Gap 1 — UI-01 请求时长 / TTFT 头部 P99

- **后端** `server/system/metrics_query.py`：`_AGGS` 增 `p99`、`_PERCENTILE` 增 `"p99": 0.99`。Postgres 走 `percentile_cont(0.99) WITHIN GROUP`；SQLite 无 `percentile_cont` → 复用既有 `MAX` 降级分支（`degraded=true` / `note="sqlite_percentile_approx"`），功能不阻塞。
- **前端** `web/src/pages/admin/observability/index.vue`：`DURATION_AGGS` 与 `percentileSummary` 增 `p99`；请求时长 / TTFT 卡大字头由 P95 改为 **P99**（per UI-SPEC §2.3），P95/P90/P50/Avg/Max 下沉副行。`web/src/api/system.ts` `MetricAgg` 增 `'p99'`。
- **测试**：`test_validate_accepts_p99_and_upstream_metric`（p99 进白名单不回退）、`test_duration_p99_accepted_and_degrades_on_sqlite`（SQLite degrade=true + MAX 兜底 900）。

### Gap 2 — UI-01 上游错误 429 / 529 单列

- **后端** `server/system/metrics_query.py`：`_METRICS` 增 `upstream`；新增 `_query_upstream`，聚合 `ModelUsageRecord.upstream_status_code`，受控 `CASE` 收口 dim 为 `429`/`529`/`other`，仅统计 `upstream_status_code IS NOT NULL` 行（时间列 `created_at`，双后端 CASE 通用，无注入面）。
- **前端** `index.vue`：新增 `obs-upstream-breakdown` 查询 + `upstreamCounts` 派生（按 dim 汇总）；上游错误卡用「429 限流 / 529 过载 / 其它上游码 / 上游错误数」四单列取代旧 `'—'` 占位与 footnote。`system.ts` `MetricName` 增 `'upstream'`。
- **测试**：`test_upstream_breakdown_429_529_other`（429=2 / 529=1 / other=1，null 上游码排除，总数=4）。

### Gap 3 — UI-04 系统日志 5 高级维度服务端筛选

- **后端** `server/system/log_views.py`：`_extract_filters` / `_has_any_filter`（新增 `_FILTER_KEYS`）/ `_apply_filters` 增 5 维。`call_source/provider/credential/model` 走 `payload` jsonb 顶层键**精确**匹配（`payload__<key>=`，PG `->>` / SQLite `json_extract` 语义一致）；`correlation` 走 `Cast(correlation→TextField)__icontains` 子串检索（覆盖任意关联键/值；PG 为 jsonb 文本表示、SQLite 为存储 JSON 文本，行为一致，best-effort）。clear-by-filter 经共用 `_apply_filters` 同步获得能力。
- **前端** `web/src/components/observability/SystemLogTable.vue`：高级维度由「当前页客户端 narrowing」切为**真实服务端查询参数**（`advKey` 取值即 `SystemLogQuery` 键，含 300ms 防抖 + 切换维度清值），删除 `dimValue`/客户端过滤 `items`，并把「仅过滤当前页（后端不支持 payload 顶层筛选）」提示改为「服务端全量筛选」。`system.ts` `SystemLogQuery` 增 5 字段。
- **测试**：`test_filter_by_{call_source,provider,credential,model}_payload`（payload 精确各 1 命中）、`test_filter_by_correlation_substring`（子串命中 run_id/conversation_id 值）、`test_clear_by_advanced_dim_call_source`（高级维度免 confirm_all 清理）。

### 验证结果

- **后端** `cd server && uv run pytest tests/test_metrics_query.py tests/test_system_log_api.py tests/test_credential_leak_protection.py -p no:randomly -q` → **67 passed**。
- **迁移** `makemigrations --check --dry-run` → **No changes detected**（纯 query-only，无 model 变更）。
- **前端** `pnpm vue-tsc --noEmit` → exit 0；`pnpm exec vitest run src/components/observability src/api/__tests__/observability.spec.ts` → **4 files / 22 tests passed**。

5/5 code truths 达成。frontmatter `human_verification`（6 项纯视觉/交互 UAT）仍需真机肉眼判定，与本次代码缺口闭合无关。

---

_Verified: 2026-06-24T18:30:00Z（初验） · 2026-06-25T02:45:00Z（缺口闭合复核）_
_Verifier: Claude (gsd-verifier) · Gap closure: Claude (gsd-executor)_
