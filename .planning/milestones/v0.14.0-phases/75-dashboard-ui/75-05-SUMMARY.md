---
phase: 75-dashboard-ui
plan: "75-05"
subsystem: observability / docs / admin-nav
tags: [observability, logging-spec, nav, routing, spec-01, milestone-close]
requires: ["75-02", "75-03", "75-04"]
provides:
  - "admin 导航「运维监控」入口可达 + 三视图子路由（总览/告警/日志，requiresAdmin）"
  - "LOGGING-SPEC.md 事件目录全量补全 71–74 + call_source/component 清单 + PR/Review checklist 终稿"
  - ".cursor/rules/observability-logging.mdc 与 AGENTS.md/CLAUDE.md 可观测性章节收敛无分叉"
affects:
  - "未来任何新增/改动功能的提交前自检（强制 Code Review 清单）"
tech-stack:
  added: []
  patterns: ["docs-as-spec", "unplugin-vue-router auto-routes", "ObservabilityTabs 子路由 + 顶部 tabs"]
key-files:
  created:
    - .planning/phases/75-dashboard-ui/75-05-SUMMARY.md
  modified:
    - .planning/observability/LOGGING-SPEC.md
    - .cursor/rules/observability-logging.mdc
    - AGENTS.md
    - CLAUDE.md
decisions:
  - "AppSidebar 未改动：75-02 已落地 { to:'/admin/observability', label:'运维监控' } 单一总览入口，三视图切换由页内 ObservabilityTabs 承担（对齐 UI-SPEC §1，最小改动）"
  - "RAG 召回与 LLM QPS/TPS/TTFT 数值走 RequestMetric/ModelUsageRecord 指标行而非 structlog 事件，事件目录仅登记可归因/失败生命周期事件（与代码一致，避免臆造）"
  - "三处 checklist 收敛为同一份：LOGGING-SPEC §9 为权威，mdc 补齐高频 INFO 项与之对齐，AGENTS/CLAUDE 引用而非复制"
metrics:
  duration: ~20m
  completed: 2026-06-25
---

# Phase 75 Plan 05: 可观测性导航收口 + 日志规范固化（SPEC-01）Summary

里程碑 v0.14.0 收尾：确认 admin 导航三视图可达，并把日志/埋点规范固化为可执行、可审查的长期工程约束——LOGGING-SPEC 事件目录全量补全 Phase 71–74、call_source（22 值）/component 清单覆盖新增、PR/Code Review checklist 三处收敛。仅文档 + 导航确认，无代码/埋点逻辑变更、无新依赖。

## Tasks

### Task 1: admin 导航入口确认 + 三视图子路由可达性校验 — PASS

- `AppSidebar.vue` 的 `adminNavItems` 已含 `{ to: '/admin/observability', label: '运维监控', icon: 'lucide--activity' }`（75-02 落地），保持单一总览入口；**无需改动**。
- `typed-router.d.ts` 已收录三路由：`/admin/observability/`、`/admin/observability/alerts`、`/admin/observability/logs`。
- 三页 `definePage({ meta: { requiresAdmin: true } })` 均生效（`index.vue:35`、`alerts.vue:24`、`logs.vue:39`）。
- `ObservabilityTabs.vue` 顶部 tabs 链接到三路由（总览 / 告警事件 / 系统日志），子路由切换可达。

### Task 2: LOGGING-SPEC 事件目录/枚举补全 + 规则与 AGENTS/CLAUDE 收敛 + PR checklist 落地 — PASS

- **§4.1 call_source 枚举**：与 `server/agents/call_source.py` 的 `CallSource`（22 值）逐项核对**完全一致**，无需改动。
- **§5 component 清单**：补登 71–74 实际使用值 `interactions` / `metric_sampling` / `metric_retention` / `alerting` / `alert_retention` / `call_drilldown` / `conversation_drilldown` / `webhook_events` / `webhook_recorder` / `system_logs` / `log_retention`（与代码 `component=` 取值核对）。
- **§10 事件目录补全（经 `rg` 核对，事件名与代码一致）**：
  - §10.2 增 `system_logs_purged` / `webhook_events_purged`（+ `*_failed`）。
  - §10.3 增 `inbound_webhook_recorded` / `inbound_webhook_record_failed` / `inbound_webhook_bg_schedule_failed` / `webhook_events_queried`。
  - §10.4 增 `call_drilldown_viewed` / `conversation_drilldown_viewed` / `system_logs_queried` / `system_logs_cleared`。
  - §10.5 增 `job_start` / `job_complete`（scheduler）。
  - **新增 §10.7 调用并发/限流 + 留痕（Phase 72）**：`llm_slot_acquired` / `llm_slot_busy_timeout` / `llm_slot_redis_unavailable_fallback_inprocess` + 5 个 `ledger_*_write_failed`；并说明 RAG/LLM 数值走指标行。
  - **新增 §10.8 快照/趋势/查询/采样/保留（Phase 73）**：`metrics_snapshot_served` / `metrics_query_served` / 5 个 `snapshot_*_failed` / `gauge_sampled` / `gauge_sample_failed` / `*_purged`。
  - **新增 §10.9 告警评估与通知（Phase 74）**：`alert_rules_listed/created/updated/deleted` / `alert_events_queried` / `alert_eval_cycle` / `alert_firing` / `alert_resolved` / 各通知失败事件 / `alert_events_purged`。
- **§9 PR/Code Review checklist 终稿**：覆盖生命周期 + duration_ms、category+component、用户绑定、脱敏、LLM call_source、请求入口 QPS/错误率/时长、召回条数/分层耗时/score + RetrievalTrace、队列积压 + 发起用户、webhook 原始留痕、告警阈值；状态语从"目标态/设施就绪前"更新为"v0.14.0 已落地（现行态）"（header / §4 / §8）。
- **`.cursor/rules/observability-logging.mdc` 收敛**：checklist 补齐"高频循环未用 INFO 刷屏"项与 §9 对齐；footer 过渡语更新为"已落地"并引用 `LOGGING-SPEC §4.1/§5/§10`。
- **AGENTS.md / CLAUDE.md**：两文件镜像同步追加"平台设施已在 v0.14.0（Phase 71–74）落地"收尾说明，引用 §9 + mdc 单一来源，不复制 checklist。

## Verify Results

- `cd web && pnpm vue-tsc --noEmit` → **exit 0**（clean；typed-router 含三 observability 路由）。
- `pnpm exec eslint src/components/layout/AppSidebar.vue` → **exit 0**（clean）。
- `rg` 核对：§10 新增事件名（`alert_firing`/`alert_resolved`/`gauge_sampled`/`llm_slot_acquired`/`ledger_retrieval_trace_write_failed`/`inbound_webhook_recorded` 等）均在 `server/` 命中，无臆造。
- 三视图可达性：`AppSidebar` 运维监控入口 → `/admin/observability`（总览）；页内 `ObservabilityTabs` → `/admin/observability/alerts`（告警）、`/admin/observability/logs`（日志），三路由均 `requiresAdmin`。

## Files Changed

- `.planning/observability/LOGGING-SPEC.md`（§header/§4/§5/§8/§9/§10 补全与状态更新）
- `.cursor/rules/observability-logging.mdc`（checklist 收敛 + footer 状态更新）
- `AGENTS.md`（可观测性章节收尾说明）
- `CLAUDE.md`（同 AGENTS.md，镜像同步）
- `.planning/phases/75-dashboard-ui/75-05-SUMMARY.md`（本文件）

## Deviations from Plan

None — plan executed as written. `AppSidebar.vue` 在 `files_modified` 中列出，但 75-02 已落地正确入口，本 plan 仅确认无需改动（计划 Task 1 明确允许"确认/补全"，最小改动避免改 NavItem 类型）。未触碰 `files_modified` 之外的任何文件。

## Self-Check: PASSED

- FOUND: `.planning/observability/LOGGING-SPEC.md`（§10.7/10.8/10.9 已写入）
- FOUND: `.cursor/rules/observability-logging.mdc`（高频 INFO 项 + footer 更新）
- FOUND: `AGENTS.md` / `CLAUDE.md`（收尾说明已写入）
- FOUND: `.planning/phases/75-dashboard-ui/75-05-SUMMARY.md`
- VERIFIED: `pnpm vue-tsc --noEmit` exit 0；`eslint AppSidebar.vue` exit 0
- VERIFIED: 三 observability 路由 + requiresAdmin；ObservabilityTabs 链接三视图
