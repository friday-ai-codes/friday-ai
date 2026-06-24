---
phase: 74-alerting
plan: "74-01"
subsystem: system / alerting
tags: [alerting, models, crud-api, retention, observability]
requires:
  - server/system/models.py (SystemLogEntry/RequestMetric/GaugeSample 范式 + SettingKeys)
  - server/system/log_retention.py (按天数+行数清理范式)
  - server/system/log_views.py (adrf APIView + IsSuperUser + 筛选范式)
  - server/system/settings_service.py (aget_int_setting 运行时配置)
  - server/permissions/api_permissions.py (IsSuperUser)
provides:
  - SystemAlertRule 模型（系统级阈值规则，独立于 workflow AlertRule）
  - AlertEvent 模型（P0/P1/P2 + 去重条件唯一约束 + firing/resolved + email_sent）
  - SettingKeys.ALERT_* 7 常量（74-02/03 消费）
  - REST CRUD（/api/system/alerts/rules/）+ 事件查询（/api/system/alerts/events/）
  - alert_retention.purge_alert_events（按 started_at 保留清理）
affects:
  - 74-02（评估器写 AlertEvent + apscheduler 注册评估与清理）
  - 74-03（通知分发读 AlertEvent + ALERT_* 配置，回写 email_sent/notified_channels）
  - Phase 75（告警事件页消费查询 API）
tech-stack:
  added: []  # 零新增第三方依赖（Django ORM/DRF/adrf/标准库）
  patterns:
    - 条件唯一约束去重（镜像 ProviderCredential）
    - adrf async APIView + sync_to_async 桥接 ORM
    - ChoiceField + validate_* 白名单防御
    - best-effort 保留清理（按天数 + 行数上限分批）
key-files:
  created:
    - server/system/migrations/0012_systemalertrule_alertevent.py
    - server/system/alert_serializers.py
    - server/system/alert_views.py
    - server/system/alert_retention.py
    - server/tests/test_system_alert_models.py
    - server/tests/test_system_alert_api.py
  modified:
    - server/system/models.py
    - server/system/urls_system.py
decisions:
  - "SystemAlertRule/AlertEvent 落 system app，独立于 workflow AlertRule（语义不同，避免拧巴）"
  - "去重靠 (rule, target_key) status=firing 条件唯一约束在 DB 层兜底；target_key 由 74-02 写入"
  - "保留清理按 started_at（AlertEvent 事件时间列），不删错列；apscheduler 注册留给 74-02"
  - "事件查询记 category=sampling（高频轮询），规则写操作记 category=caller"
metrics:
  duration: "~5min"
  completed: "2026-06-25"
  tasks: 3
  files: 8
---

# Phase 74 Plan 01: 告警引擎数据载体与运维入口 Summary

系统级告警的模型契约与运维入口落地：`SystemAlertRule`（阈值规则）+ `AlertEvent`（告警事件，含 `(rule,target_key)` status=firing 条件唯一约束去重）两模型 + `0012` 迁移，`SettingKeys.ALERT_*` 7 常量，REST CRUD + 事件查询 API（IsSuperUser fail-closed + metric/op/severity/channels/dimension 白名单防御），及 `alert_retention.purge_alert_events`（镜像 Phase 71 `log_retention`，按 `started_at` 天数 + 行数上限 best-effort 清理）。

## Tasks

### Task 1 — SystemAlertRule + AlertEvent 模型 + SettingKeys.ALERT_* + 0012 迁移 — PASS
- `server/system/models.py` 新增两模型（中文 docstring/verbose_name，沿用 BigAutoField/db_table/JSONField default/复合 Index 惯例）；`SettingKeys` 末尾追加 7 个 `ALERT_*` 点分命名常量（仅常量无新键迁移）。
- 迁移自动生成 `0012_systemalertrule_alertevent.py`（base=`0011_gaugesample`），仅 CreateModel + AddIndex + AddConstraint，无数据迁移。
- `AlertEvent` 去重硬约束 `UniqueConstraint(fields=[rule, target_key], condition=Q(status="firing"))`。
- 测试 `test_system_alert_models.py`（4 用例）：字段持久化/默认值、重复 firing 抛 `IntegrityError`、resolved 后约束释放、7 常量点分命名。
- Verify: `makemigrations --check` → `No changes detected`；`pytest` → 4 passed。

### Task 2 — 规则 CRUD + 事件查询 API + urls 接入 — PASS
- `alert_serializers.py`：`SystemAlertRuleSerializer`（读）/`SystemAlertRuleWriteSerializer`（create+partial_update 共用，metric/op/severity ChoiceField + `validate_channels`⊆{email,feishu,webhook} + `validate_dimension` 键⊆受控集合值为 str）/`AlertEventSerializer`（只读全字段，列对齐 REFERENCE-UI §1.4）。
- `alert_views.py`：3 个 adrf async APIView（`SystemAlertRuleListCreateView` / `SystemAlertRuleDetailView` / `AlertEventListView`），全 `IsSuperUser`，`sync_to_async` 桥接 ORM，结构化打点（caller/sampling + component="alerting"）。
- `urls_system.py`：`alerts/rules/`、`alerts/rules/<int:rule_id>/`、`alerts/events/` 三路由（字面段排通配前，运维端点聚集）。
- 测试覆盖 CRUD + 非超管 403 + 非法 metric/channels/dimension 400 + 事件 severity/status 筛选倒序。
- Verify: `pytest test_system_alert_api.py` → 14 passed；`ruff check` → 干净。

### Task 3 — alert_retention.purge_alert_events 保留清理 — PASS
- `alert_retention.py`：逐源镜像 `log_retention`，时间列换 `started_at`（注释显式标注口径，绝不用 ts/created_at）；`_alert_retention_config` 读 `ALERT_RETENTION_DAYS`(默认 90)/`ALERT_RETENTION_SIZE`(默认 500_000)；`_SIZE_DELETE_BATCH=50_000` 分批；整段 try/except best-effort（`alert_events_purge_failed` warning）。apscheduler 注册留给 74-02。
- 测试（并入 `test_system_alert_api.py`，`transaction=True`）：按龄删旧留新（started_at 口径，不抛 FieldError）、按量删最旧超出、配置读取抛错降级返回部分结果不冒泡。
- Verify: `pytest` → 通过；`ruff check` → 干净。

## Deviations from Plan

None - 三任务按计划逐字实现。迁移文件名与计划预期一致（`0012_systemalertrule_alertevent.py`），无需重命名 `files_modified`。

## Threat Mitigations Applied

- **T-74-01-01（EoP）**：全部 alert_views `IsSuperUser` fail-closed；测试断言非超管规则 CRUD + 事件查询均 403。
- **T-74-01-02（Tampering）**：WriteSerializer ChoiceField（metric/op/severity 闭集）+ `validate_channels`/`validate_dimension` 白名单；非法 400 测试覆盖。
- **T-74-01-03（DoS 告警风暴）**：`(rule,target_key)` status=firing 条件唯一约束 DB 兜底；重复 firing 抛 IntegrityError 测试覆盖。
- **T-74-01-04（Info Disclosure）**：模型字段仅承载元数据（阈值/当前值/受控维度/通道名），无 raw payload/凭证；`test_credential_leak_protection.py` 保持绿（24 passed）。
- **T-74-01-05（DoS 清理）**：`_SIZE_DELETE_BATCH=50_000` 单次上限分批删。

## Verification Results

- `pytest tests/test_system_alert_models.py tests/test_system_alert_api.py tests/test_credential_leak_protection.py -q` → **42 passed**。
- `makemigrations --check --dry-run` → **No changes detected**（0012 已生成，ALERT_* 仅常量无新键迁移）。
- `ruff check`（models/alert_serializers/alert_views/alert_retention/urls_system + 两测试文件）→ **All checks passed**（line-length 100）。

## Notes for Downstream Plans

- **74-02** 须：写 `AlertEvent` 时填 `target_key`（target 规范化 JSON 串）以让去重约束生效；渲染 `title_zh`/`rule_info.expr`（REFERENCE-UI §1.4 同款格式）；在 `runapscheduler.py` 注册 `evaluate_system_alerts`（间隔取 `ALERT_EVAL_INTERVAL_SECONDS`）与 `purge_alert_events`（daily）。
- **74-03** 须：读 `ALERT_EMAIL_*`/`ALERT_FEISHU_CHAT_ID`/`ALERT_WEBHOOK_URL` 配置，按 `rule.channels` 子集分发，正文经 `redact_secrets_in_text`，回写 `email_sent`/`notified_channels`。

## Self-Check: PASSED

- 文件均存在：models.py / 0012 迁移 / alert_serializers.py / alert_views.py / alert_retention.py / urls_system.py / 两测试文件。
- 无 git commit（按用户执行规则）。
