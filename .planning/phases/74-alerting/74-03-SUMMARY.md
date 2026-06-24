---
phase: 74-alerting
plan: "74-03"
subsystem: system / alerting
tags: [alerting, notification, email, feishu, webhook, ssrf, redaction]
requires:
  - "74-01: AlertEvent (email_sent/notified_channels/rule_info/title_zh/severity/target)、SettingKeys.ALERT_EMAIL_*/ALERT_FEISHU_CHAT_ID/ALERT_WEBHOOK_URL"
  - "71: settings_service(aget_setting/aget_bool_setting)、common.logging.redact_secrets_in_text、common.log_context (system/scheduler 归因)"
  - "feishu: services.feishu_im.FeishuIMService.create(None).send_card"
provides:
  - "system.alert_notifier.notify_channels(event, channels) 单一三通道分发出口"
  - "EMAIL_* Django SMTP 配置（全仓首次引入，从 env）"
affects:
  - "74-02 评估器：产生 firing/resolved 事件后调一次 notify_channels 完成多通道通知"
tech-stack:
  added: ["Django core.mail SMTP（EMAIL_* settings，全仓首次）"]
  patterns: ["逐通道 + 最外层 try/except best-effort", "redact_secrets_in_text 正文/异常脱敏", "_is_internal_host SSRF 防护（复用 AlertRuleHook 范式）", "sync_to_async 包 send_mail"]
key-files:
  created:
    - server/system/alert_notifier.py
    - server/tests/test_alert_notifier.py
  modified:
    - server/friday/settings.py
    - .env.example
decisions:
  - "EMAIL_HOST 空 → backend=dummy 且 notify 据 EMAIL_HOST 空判定回写 skipped（不依赖 backend 行为）"
  - "EMAIL_TIMEOUT=10 + httpx timeout=10 防 SMTP/webhook 挂起拖垮评估线程"
  - "notify_channels 未选 email 通道时保留 AlertEvent.email_sent 默认 pending（仅选了才回写）"
  - "webhook/feishu 仅实际成功（True / email==sent）才计入 notified_channels"
metrics:
  duration: ~20m
  completed: 2026-06-25
---

# Phase 74 Plan 03: 系统告警三通道通知分发 (ALERT-03) Summary

单一分发出口 `notify_channels(event, channels)` 按 `rule.channels` 子集分发 EMAIL（Django SMTP，全仓首次引入）/ 飞书（复用 FeishuIMService）/ webhook（httpx POST + SSRF 防护）三通道，各通道独立 best-effort，正文经 `redact_secrets_in_text` 脱敏，回写 `email_sent` + `notified_channels`，绝不反噬评估。

## Tasks

### Task 1: EMAIL_* Django SMTP 配置 + .env.example 文档 — PASS
- `server/friday/settings.py` 新增「邮件（系统告警通知，ALERT-03）」节：`EMAIL_HOST/PORT/HOST_USER/HOST_PASSWORD/USE_TLS/USE_SSL/DEFAULT_FROM_EMAIL/EMAIL_TIMEOUT`（均从 env，沿用 `env.str/int/bool`）；`EMAIL_BACKEND` 据 `EMAIL_HOST` 非空选 smtp / 否则 dummy。
- `.env.example` 新增 SMTP 文档段（中文说明 + 英文键名，`# Optional`）。
- 验证：Django setup 可读到 `EMAIL_BACKEND`/`DEFAULT_FROM_EMAIL`/`EMAIL_TIMEOUT`（EMAIL_HOST 空时 backend=dummy）。✅

### Task 2: alert_notifier.notify_channels 单一出口 + 三通道 helper — PASS
- `notify_channels`：逐通道独立 try/except + 最外层兜底返回空 dict；回写 `email_sent`（仅选 email 才回写）+ `notified_channels`（实际成功通道）；结构化日志 `alert_notified`（category=caller / component=alerting / source=scheduler / duration_ms）。
- `_send_email`：未开启/`EMAIL_HOST` 空/无收件人 → `skipped`；`send_mail` 经 `sync_to_async` 发送成功 → `sent`，异常 → `failed`（脱敏异常文本，只记收件人数量不记明文地址）。收件人兼容逗号分隔与 JSON 列表。
- `_send_feishu`：未配置 chat_id → False（不调 create）；复用 `FeishuIMService.create(None).send_card`，按 severity 取 header template（P0=red/P1=orange/P2=blue），正文脱敏。
- `_send_webhook`：scheme 白名单 + `_is_internal_host`（private/loopback/link-local/localhost/.local）SSRF 拦截；payload 脱敏后 httpx POST（timeout=10）；>=400/异常 → False。
- 测试 `tests/test_alert_notifier.py`（13 用例，`@pytest.mark.django_db(transaction=True)`）：email skipped/sent(脱敏)/failed、webhook SSRF 拦截/合法 200(脱敏)/4xx/未配置、feishu 成功/未配置不调 create、notify_channels 汇总回写/helper 抛错不冒泡/未选 email 保留 pending。
- 验证：`pytest tests/test_alert_notifier.py` 13 passed；`ruff check` 干净。✅

## Test Results
- `tests/test_alert_notifier.py`：13 passed。
- `tests/test_credential_leak_protection.py`（回归守护）：24 passed。
- `ruff check system/alert_notifier.py friday/settings.py tests/test_alert_notifier.py`：All checks passed。
- `python manage.py makemigrations --check --dry-run`：No changes detected（本 plan 不动模型）。

## Files Changed
- 新建 `server/system/alert_notifier.py`
- 新建 `server/tests/test_alert_notifier.py`
- 修改 `server/friday/settings.py`（新增 EMAIL_* 节）
- 修改 `.env.example`（新增 SMTP 文档段）

## Deviations from Plan
None - plan executed exactly as written.

## Threat Surface
计划 `<threat_model>` 全部缓解项已落实：
- T-74-03-01：邮件/webhook/飞书正文与所有异常 str 经 `redact_secrets_in_text`；邮件 warning 只记收件人数量。
- T-74-03-02：webhook scheme 白名单 + `_is_internal_host` 拦截内网（测试覆盖 127.0.0.1 不发请求）。
- T-74-03-03：EMAIL_TIMEOUT=10 + httpx timeout=10 + send_mail 经 sync_to_async。
- T-74-03-04：逐通道 + 最外层 try/except，单通道失败不连累其它，绝不反噬评估（测试覆盖 helper 抛错不冒泡）。
- T-74-03-05：日志 category=caller + source=scheduler + event_id/severity/notified/duration_ms。
未引入计划外安全面（不新增依赖，复用 django.core.mail / httpx / FeishuIMService）。

## Self-Check: PASSED
- FOUND: server/system/alert_notifier.py
- FOUND: server/tests/test_alert_notifier.py
- 13/13 tests pass；ruff clean；no pending migrations。
