---
phase: 71-observability-foundation
plan: "71-04"
subsystem: system / observability
tags: [logging, observability, retention, apscheduler, LOG-01, LOG-03, LOG-08]
requires:
  - server/system/models.py (SystemLogEntry, InboundWebhookEvent, SettingKeys.LOG_*)
  - server/system/log_sink.py (snapshot_counters)
  - server/system/settings_service.py (aget_int_setting)
  - server/permissions/api_permissions.py (IsSuperUser)
  - server/audit/services (AuditService.aemit)
provides:
  - SystemLogQueryView (GET /api/system/logs/)
  - SystemLogClearView (POST /api/system/logs/clear/)
  - log_retention.purge_system_logs / purge_webhook_events
  - apscheduler job purge_observability_logs (daily 04:30)
affects:
  - server/system/urls_system.py (logs/ 路由替换内存缓冲版)
  - server/tests/test_system_logs.py (旧端点契约更新)
tech-stack:
  added: []
  patterns: [adrf-async-apiview, sync_to_async-orm-bridge, isSuperUser-fail-closed, apscheduler-cron-job, best-effort-observability]
key-files:
  created:
    - server/system/log_views.py
    - server/system/log_retention.py
    - server/tests/test_system_log_api.py
  modified:
    - server/system/serializers.py
    - server/system/urls_system.py
    - server/agents/management/commands/runapscheduler.py
    - server/tests/test_system_logs.py
decisions:
  - "查询/清理同款筛选语义抽到 _extract_filters/_apply_filters 复用，避免重复"
  - "level 输入归一（WARNING→warn）以命中落库归一值"
  - "clear 无条件必须 confirm_all=true 才允许清空全表（防误清，T-71-04-02）"
  - "保留 daily 04:30 错开既有 03:00/03:30/04:00 清理任务，避免争 SQLite 写锁"
  - "保留清理 async 测试用 django_db(transaction=True)，让 sync_to_async 跨线程连接可见 + 用例间真正清表"
metrics:
  duration: ~25m
  completed: 2026-06-24
---

# Phase 71 Plan 04: 日志查询 / 清理 / 保留治理 Summary

把日志中心从"内存环形缓冲"升级为基于 `SystemLogEntry` 的可搜索 / 可清理 / 可保留后端：时间倒序 + 组件/级别/用户/来源/关键词(icontains)/时间段筛选与全文搜索 + 顶部队列四计数；按条件批量清理（防误清）+ apscheduler 保留策略到期自动清理（SystemLogEntry + InboundWebhookEvent，按天数/行数）。

## Tasks

### Task 1: 日志查询/筛选/全文 + 四计数 API — PASS
- 新建 `server/system/log_views.py`：`SystemLogQueryView`（adrf async APIView，`IsSuperUser`），`GET /api/system/logs/` 基于 `SystemLogEntry` `order_by("-ts")`，组合 AND 筛选 `component/level/user_id/source/start/end/keyword`，`limit`(默认100/最大500)+`offset` 分页；返回 `{"items", "total", "counters"}`，counters 即 `log_sink.snapshot_counters()`（queued/max/enqueued/written/dropped/write_failed/sampled_out）。async ORM 经 `sync_to_async` 桥接。查询事件记 `category="sampling"`（高频轮询不污染 caller 统计）。
- `serializers.py` 增 `SystemLogEntrySerializer`（全 read_only，payload/correlation 直出已脱敏内容）。
- `urls_system.py`：`logs/` 改指向 `SystemLogQueryView`（替换内存缓冲版 `SystemLogsView`），向后兼容 `limit`/`level`。
- 测试：倒序+counters、component/level(WARNING归一)/user_id/source/keyword(icontains)/start-end 各筛、limit/offset、非超管 403、匿名 401/403。

### Task 2: 按条件批量清理 API + 保留策略定时自动清理 — PASS
- `log_views.py` 增 `SystemLogClearView`（`IsSuperUser`），`POST /api/system/logs/clear/`：body 同款筛选，无条件且无 `confirm_all=true` → 400 中文报错；否则 `qs.delete()` 返回 `{"deleted": n}`。best-effort 经 `AuditService.aemit` 记 caller 类删除审计（失败不反噬）。
- 新建 `server/system/log_retention.py`：`purge_system_logs()`（先按 `LOG_RETENTION_DAYS`(默认30) 删旧，再按 `LOG_RETENTION_SIZE`(默认1_000_000) 行数上限删最旧超出部分，返回 `{"by_age", "by_size"}`）+ `purge_webhook_events()`（`InboundWebhookEvent` 同款按 `received_at`）。全 best-effort（异常 warning 不抛）。
- `runapscheduler.py`：新增 `purge_observability_logs_job()`（`run_async_task` 跑 `purge_system_logs`+`purge_webhook_events`）+ `add_job(CronTrigger(hour=4, minute=30), id="purge_observability_logs", ...)` + `job_registered` 日志。
- `urls_system.py`：`logs/clear/` 排在 `logs/` 之前（显式顺序惯例）。
- 测试：clear by level / 无条件 400 / confirm_all 全删 / 非超管 403；保留按天数删旧、按行数删最旧到 size、webhook 同款按天数。

## Verification

- `uv run pytest tests/test_system_log_api.py -q` → **17 passed**。
- `uv run pytest tests/test_system_logs.py tests/test_credential_leak_protection.py tests/test_scheduler_registration.py tests/test_system_log_api.py tests/test_observability_view.py tests/test_system_log_sink.py -q` → **62 passed**（含 credential_leak_protection 守护未破、scheduler 注册断言未破）。
- `uv run ruff check <changed files>` → All checks passed。
- `uv run python manage.py makemigrations --check --dry-run system` → No changes detected（无模型字段变更，零新迁移）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] 旧 `test_system_logs.py` 视图契约更新（路由替换直接导致）**
- **Found during:** Task 1 回归运行。
- **Issue:** plan 明确把 `/api/system/logs/` 从内存缓冲版 `SystemLogsView`（返回 `{"logs": [...]}`）替换为 `SystemLogQueryView`（返回 `{"items", "total", "counters"}`），导致 `tests/test_system_logs.py::TestSystemLogsView` 两个用例（断言 `body["logs"]`）失败。
- **Fix:** 把 `TestSystemLogsView` 两个用例改为新契约（造 `SystemLogEntry`、断言 `items`/`counters`、`level` 向后兼容筛选）；`TestLogBuffer`（测 `common.log_buffer` 本身）保持不变。
- **Files modified:** `server/tests/test_system_logs.py`（不在 `files_modified` 清单内，但由本 plan 路由替换直接导致，按执行规则记录）。
- **Commit:** 未提交（用户要求 Do NOT git commit）。

**2. [Rule 1 - Bug] `log_retention.py` 误用 `timezone.timedelta`**
- **Found during:** Task 2 自检。
- **Issue:** `django.utils.timezone` 不导出 `timedelta`。
- **Fix:** 改 `from datetime import timedelta`。

### 测试隔离调整（非偏离，记录）
- `TestRetentionPurge` 用 `@pytest.mark.django_db(transaction=True)`：保留清理走 `sync_to_async` 异步 ORM，普通事务回滚对跨线程连接不生效会导致 `SystemSetting`/`SystemLogEntry` 行在异步用例间泄漏（首次 `UNIQUE constraint failed: system_settings.key`）。`transaction=True` 让落库数据跨线程可见且用例间真正清表。

## Threat Model Coverage
- T-71-04-01（越权）：`SystemLogQueryView`/`SystemLogClearView` 均 `IsSuperUser` fail-closed，测试覆盖非超管 403。
- T-71-04-02（误删全表）：clear 无条件需 `confirm_all=true`，否则 400，测试覆盖。
- T-71-04-03（敏感回放）：只读/删 71-02 已脱敏的 `SystemLogEntry`，serializer read_only 直出，未引入新落库内容。
- 审计经既有 `AuditService.aemit`（入口强制脱敏）。

## Known Stubs
None — 查询/清理/保留均接真实 `SystemLogEntry`/`InboundWebhookEvent` 数据源，无占位。

## Self-Check: PASSED
- FOUND: server/system/log_views.py
- FOUND: server/system/log_retention.py
- FOUND: server/tests/test_system_log_api.py
- FOUND: server/system/serializers.py (SystemLogEntrySerializer)
- FOUND: server/system/urls_system.py (logs/clear/ + logs/ 指向新视图)
- FOUND: server/agents/management/commands/runapscheduler.py (purge_observability_logs)
- 62 passed；ruff clean；makemigrations 无变更。
- 注：按用户指令未执行 git commit，无 commit hash。
