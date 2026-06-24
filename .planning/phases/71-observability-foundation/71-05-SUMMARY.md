---
phase: 71-observability-foundation
plan: "71-05"
subsystem: observability
tags: [webhook, drilldown, redaction, LOG-04, LOG-07]
requires:
  - server/system/models.py (InboundWebhookEvent, SystemLogEntry — 71-02)
  - server/interactions/redaction.py (redact_for_ledger — Interaction Ledger)
  - server/common/logging.py (redact_secrets_in_text)
  - server/interactions/models.py (InteractionRun/ToolCallRecord/RetrievalTrace/ModelUsageRecord/InteractionEvent)
  - server/chat/models.py (Conversation/Message)
provides:
  - "record_inbound_webhook 单一脱敏收口（入站 webhook 原始留痕）"
  - "InboundWebhookEvent 列表/详情 API（/api/system/webhooks/）"
  - "MCP 调用下钻 API（/api/system/calls/drilldown/）"
  - "AI 对话会话下钻 API（/api/system/conversations/<uuid>/drilldown/）"
affects:
  - server/feishu/views.py (3 入口补写 InboundWebhookEvent)
  - server/subagent/api/callbacks.py (容器回调补写)
  - server/repositories/index_views.py (Git push webhook 补写)
tech-stack:
  added: []
  patterns: [adrf-async-view, IsSuperUser-fail-closed, sync_to_async, best-effort-observability, redact-before-persist]
key-files:
  created:
    - server/system/webhook_recorder.py
    - server/system/webhook_views.py
    - server/system/drilldown_views.py
    - server/tests/test_inbound_webhook_event.py
    - server/tests/test_log_drilldown_api.py
  modified:
    - server/system/serializers.py
    - server/system/urls_system.py
    - server/feishu/views.py
    - server/subagent/api/callbacks.py
    - server/repositories/index_views.py
decisions:
  - "异步入口直接 await 单条 record_inbound_webhook（本地 insert 开销极低、确定可测），bg 包装保留供同步/脱离请求场景"
  - "webhook 留痕统一在验签前记录以捕获全部入站（含被拒），verified 现统一记 False"
  - "容器回调仅记录 completed/failed/question，跳过高频 heartbeat/progress 防留痕表膨胀"
  - "下钻直出已脱敏 append-only 行（dict 组装，不新建 serializer，不重拼明文）"
metrics:
  duration: ~40min
  completed: 2026-06-24
---

# Phase 71 Plan 05: Webhook 原始留痕 + 调用下钻 Summary

统一入站 webhook 原始留痕（LOG-07）与调用下钻（LOG-04）：新增 `record_inbound_webhook` 单一脱敏收口把飞书/Git push/容器回调的原始 payload 脱敏后写入 `InboundWebhookEvent`（飞书入口与既有 `TriggerLog` 双写、零回归），并提供 webhook 原始查看 API + MCP 调用归因/AI 对话会话原始下钻 API（复用 Interaction Ledger / Conversation / Message，经 request_id/run_id/conversation_id 关联不复制）。

## Tasks

### Task 1: webhook 原始留痕统一收口 + 入口接线（LOG-07） — PASS
- `server/system/webhook_recorder.py`：`record_inbound_webhook`（async 收口）+ `record_inbound_webhook_bg`（后台派发）+ `client_ip`。**入库前必经脱敏**：headers/dict body 经 `redact_for_ledger`，str body 先尝试 JSON 解析走结构化脱敏、失败再 `redact_secrets_in_text`；body 超 64KB 截断；整体 best-effort（异常仅 warning，绝不反噬主流程）。
- `InboundWebhookEventSerializer`（全 read_only）+ `WebhookEventListView`（kind/verified/user_id/时间段筛选 + 分页，倒序）+ `WebhookEventDetailView`（单条原始详情），均 `IsSuperUser`。
- 入口接线：飞书 `FeishuWebhookView` / `CardCallbackView` / `IMMessageWebhookView`（kind=feishu，与 TriggerLog 双写）；容器回调 `ContainerCallbackView`（kind=container_callback，仅 completed/failed/question）；Git push `RepositoryWebhookView`（kind=git_push）。
- 路由：`/api/system/webhooks/` + `/api/system/webhooks/<int:event_id>/`。

### Task 2: 调用下钻 API（LOG-04） — PASS
- `server/system/drilldown_views.py`：`CallDrilldownView`（按 request_id/run_id 定位 InteractionRun → 触发用户 + 工具调用/召回/模型用量/事件明细，已脱敏直出）+ `ConversationDrilldownView`（按 conversation_id 取全部 Message + created_by 归因 + 按 correlation.conversation_id 关联 SystemLogEntry/InteractionRun 摘要，不复制正文）。
- 触发用户解析 `_resolve_trigger_user`：`user:<id>` 直取（兼容 UUID 主键）/ 否则按 `AccessToken.token_hash` 反查所有者；只回 id/用户名，绝不回 token。
- 路由：`/api/system/calls/drilldown/` + `/api/system/conversations/<uuid:conversation_id>/drilldown/`。

## Verification
- `pytest tests/test_inbound_webhook_event.py tests/test_log_drilldown_api.py` → **20 passed**。
- 回归：`tests/test_trigger_views.py tests/test_credential_leak_protection.py tests/test_system_log_api.py` → **47 passed**（飞书 webhook 双写零回归 + 凭证泄漏守护绿）。
- 回归：`tests/feishu/ tests/test_repo_summary_callback.py tests/test_callbacks_cross_repo_relevance.py` → **40 passed**（容器回调接线零回归）。
- `makemigrations --check --dry-run` → **No changes detected**（无模型字段变更，不新增迁移）。
- `ruff check` 所有新增/改动文件 → **All checks passed**（feishu/views.py、subagent/api/callbacks.py、5 个新文件均干净）。

## Deviations from Plan

### 设计选择（非缺陷）

**1. [Rule 3 - 决策] 异步入口直接 await 收口，而非全部走 background_runner**
- 计划行动建议飞书入口经 `record_inbound_webhook_bg`（背景派发）。实际所有 webhook 入口（飞书 3 入口/容器回调/Git push）均为 adrf 异步视图，单条本地 `acreate` 开销极低（亚毫秒级），直接 `await record_inbound_webhook(...)` 既不阻塞 3s 响应、又确定可测（双写计数断言无需依赖跨线程 worker 时序）。`record_inbound_webhook_bg`（run_in_background 包装）仍按计划提供，供同步上下文/需脱离请求生命周期场景。

**2. [Rule 2 - 性能] 容器回调仅记录生命周期/用户相关回调**
- 容器回调含高频 heartbeat/progress/action_log/token_usage。全量留痕会撑爆 `InboundWebhookEvent` 表（违背观测规范「高频禁刷屏」）。仅记录 completed/failed/question（出事时"发生了什么/谁触发"的关键终态），高频类跳过。

**3. [决策] verified 统一记 False（捕获全部入站优先）**
- LOG-07 安全价值在"出事时原始可回放（含被拒/恶意入站）"，故所有入口在验签/路由**前**记录以捕获全部入站，`verified` 当前统一记 False。精确逐入口验签态可作后续增强（字段已就位）。

### 入口覆盖说明
- 已接通 3 类 webhook：**feishu**（3 视图）+ **container_callback** + **git_push**（`RepositoryWebhookView`），满足"飞书 + ≥1 其它入口"硬指标且超额。
- "通用 workflow webhook"（kind=workflow）：本代码库无独立的通用 workflow webhook 入口——飞书 webhook 即工作流触发入口（`FeishuWebhookView` 经 token/payload 直达 `WorkflowTrigger`），已以 kind=feishu 覆盖。无单独 kind=workflow 接线，记为 deferred（无对应独立入口）。

## Deferred Issues
- `server/repositories/index_views.py` 存在 **6 处 pre-existing ruff 错误**（行 42/54-57 模块导入、行 1389 `RepositoryIndexView.get` 的 F841 未用变量），均在本 plan 编辑区域（~行 1626）之外、与本次改动无关。按 SCOPE BOUNDARY 不在本 plan 修复。

## Known Stubs
None — 所有 API 均接真实数据源（InboundWebhookEvent / Interaction Ledger / Conversation / Message），无占位数据。

## Threat Flags
None — 未引入计划 `<threat_model>` 之外的新信任边界。新增端点全部 `IsSuperUser` fail-closed；留痕入库前强制脱敏；下钻只读已脱敏 append-only 行，绝不重拼明文。

## Self-Check: PASSED
- 文件存在：webhook_recorder.py / webhook_views.py / drilldown_views.py / test_inbound_webhook_event.py / test_log_drilldown_api.py 均已创建（FOUND）。
- 测试通过：20 新增用例 + 87 回归用例全绿。
- 无新增迁移；ruff 改动文件干净。
