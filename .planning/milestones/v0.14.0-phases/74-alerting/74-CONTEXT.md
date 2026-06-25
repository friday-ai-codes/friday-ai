# Phase 74: 告警引擎与通知（阈值 + 告警事件 + 邮件） - Context

**Gathered:** 2026-06-24
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous——grey area 按 MILESTONE-PROPOSAL §A.3/§B Phase 74 + STATE.md 关键约束自动采纳最优解）

<domain>
## Phase Boundary

数据可查后评估阈值告警——新建**系统级**告警（**不套** workflow `AlertRule`），沉淀告警事件并按级别通知，共享飞书/webhook/邮件三通道分发。

**交付（ALERT-01/02/03）：**
- `SystemAlertRule` 模型（系统级阈值规则，运行时可改）+ 周期评估器（查 Phase 73 时序/快照）
- `AlertEvent` 模型（P0/P1/P2 + 中文标题 + 机器可读规则信息 + 开始/结束/持续时长 + firing/resolved + email_sent + 去重）
- SMTP 邮件通道（新增 `EMAIL_*` 配置 + `SystemSetting` 收件人/开关，按级别发邮件回写 email_sent）
- 复用飞书/webhook 通知分发（三通道并存）

依赖 Phase 73（告警评估依赖时序查询与快照）。

</domain>

<decisions>
## Implementation Decisions

### 系统告警模型（ALERT-01，另起不复用 workflow AlertRule）
- **`SystemAlertRule`**（落 `system` app）：`metric`(qps/error_rate/ttft/cpu/memory/db/redis/qdrant/queue_depth 等枚举)、`op`(gt/gte/lt/lte)、`value`(float 阈值)、`window`(评估窗口秒)、`dimension`(jsonb 受控，如 provider/source/queue 名)、`severity`(P0/P1/P2)、`enabled`、`channels`(jsonb: email/feishu/webhook 子集)、`cooldown`(秒)、`title_template`(中文标题模板)。运行时可改（REST CRUD + IsSuperUser）。
- **不复用** `workflows.AlertRule`（强绑 workflow：`project` 非空、`AlertRuleExecution.workflow_execution` 非空、条件全是 execution_*）。系统告警语义不同（CPU>85%、错误率、队列深），独立模型避免拧巴（§A.3）。
- **趋势类（RATE-03）默认不参与**告警（GaugeSample 只记不告警），除非显式建规则。

### 周期评估器（ALERT-01）
- apscheduler 周期任务（评估间隔默认 60s）`evaluate_system_alerts`：对每条 enabled `SystemAlertRule`，调 Phase 73 `metrics_query`（时序聚合）或 `snapshot_service`（当前快照）取当前值，与阈值比较。
- 超阈触发 → firing（去重：同规则同对象一条 firing）；恢复 → resolved（收尾，写 ended_at/duration）。cooldown 防抖。
- best-effort：评估失败不反噬，单规则隔离。

### 告警事件（ALERT-02）
- **`AlertEvent`**（落 `system` app）：`severity`(P0/P1/P2)、`title_zh`(中文标题)、`rule_info`(jsonb 机器可读：规则·当前值·窗口·维度，参考格式 `cpu_usage_percent > 85.00 (current 95.40) over last 5m (overall)`)、`rule`(FK SystemAlertRule)、`target`(对象标识 jsonb，如 provider/queue 名)、`started_at`、`ended_at`(nullable)、`duration_s`(nullable)、`status`(firing/resolved)、`email_sent`(bool/枚举 sent/skipped/—)、`notified_channels`(jsonb)。
- **去重**：同规则同对象（rule + target）只保持一条 firing；重复评估超阈不新建（更新 last_seen/current_value），恢复时该条转 resolved 写 ended_at + duration_s。
- 列对齐 REFERENCE-UI §1.4（时间/级别/状态/维度/规则ID/标题+规则信息/持续时长/邮件状态）——Phase 75 告警事件页消费。

### 通知分发（ALERT-03，三通道并存）
- **邮件（新增）**：Django SMTP——新增 `EMAIL_*` settings（EMAIL_BACKEND/HOST/PORT/HOST_USER/HOST_PASSWORD/USE_TLS/FROM，从 env，全仓当前无）+ `SystemSetting` 收件人列表/开关（`SettingKeys.ALERT_EMAIL_*`）。按 severity 发邮件（中文标题 + rule_info），回写 `email_sent`。SMTP 未配置/发送失败 → email_sent=skipped/failed，不反噬评估。
- **飞书/webhook（复用）**：复用现有通知分发（飞书 IM 卡片 / webhook），系统告警共享同一分发出口（抽 `notify_channels(event, channels)` helper，按 rule.channels 子集分发）。三通道并存，各通道独立 best-effort。
- 凭证脱敏：邮件/webhook 正文经 `redact_secrets_in_text`，不泄漏。

### Claude's Discretion
- migration 编号自动生成；评估间隔、cooldown 默认、metric 枚举集合、title 模板格式在 plan 定。
- 邮件用 Django `send_mail`/`EmailMessage`（async 经 sync_to_async）；HTML vs 纯文本由 plan 定（倾向简洁纯文本/轻 HTML）。
- 飞书复用 `feishu_im_notify`/卡片 builder 还是直发由 plan 按现有 idiom 定。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- Phase 73：`metrics_query.py`（时序聚合，评估取当前值）、`snapshot_service.py`（快照取 CPU/内存/队列等当前值）、`GaugeSample`。
- Phase 71：`settings_service`/`SettingKeys`/`signals`（运行时配置 ALERT_*/EMAIL_*）、apscheduler job 范式（`runapscheduler.py`）、`log_retention`（AlertEvent 保留清理可复用）。
- `server/workflows/hooks/builtin.py` `AlertRuleHook`（去重/cooldown/动作分发范式参考，**不复用模型**）；`server/workflows/models/execution.py` `AlertRule`/`AlertRuleExecution`（反面教材：强绑 workflow，不复用）。
- 飞书通知：`server/workflows/nodes/integrations/feishu_im_notify.py`、`server/feishu/cards/failure_notification_card.py`、`feishu_im` 服务（卡片/IM 分发复用）。
- `server/common/logging.py` `redact_secrets_in_text`（邮件/webhook 正文脱敏）。

### Established Patterns
- best-effort 观测 `except: pass`；async ORM sync_to_async；IsSuperUser 运维端点；apscheduler 周期任务；运行时配置走 SystemSetting+settings_service+signals。
- 第一性原理：静态阈值 + 去重（自适应/降噪列 v2 OBSX-04）。

### Integration Points
- 评估器调 Phase 73 metrics_query/snapshot_service。
- apscheduler 注册 `evaluate_system_alerts`（~60s）。
- 邮件：Django SMTP（settings EMAIL_* + SettingKeys.ALERT_EMAIL_*）。
- 飞书/webhook：复用现有分发出口。
- REST CRUD（SystemAlertRule）+ AlertEvent 查询 API 落 `server/system/`（IsSuperUser）；Phase 75 前端消费。

</code_context>

<specifics>
## Specific Ideas

- 严守 `.cursor/rules/observability-logging.mdc`：评估器/通知是后台任务，携带 `initiated_by_user_id=system`（Phase 71 bind_task_context，source=scheduler）；评估告警事件结构化日志 started/completed/failed + duration_ms。
- rule_info 机器可读格式对齐 REFERENCE-UI §1.4 与 ROADMAP 示例。
- 去重硬约束：一条 firing，恢复收尾（不刷屏）。
- EMAIL_* 全仓首次引入，需在 settings.py + .env.example 补齐文档。

</specifics>

<deferred>
## Deferred Ideas

- 告警自适应/降噪/值班排班 → v2 OBSX-04。
- 大盘告警事件页前端 + 阈值规则配置 UI → Phase 75（本 Phase 仅后端模型 + 评估 + CRUD/查询 API）。
- Sentry 接入 → v2 OBSX-05。

</deferred>
