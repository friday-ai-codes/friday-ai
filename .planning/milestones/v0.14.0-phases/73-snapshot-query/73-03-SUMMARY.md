---
phase: 73-snapshot-query
plan: "73-03"
subsystem: observability / metrics
tags: [RATE-03, sampling, retention, apscheduler, gauge-sample]
requires:
  - system.snapshot_service.collect_concurrency_snapshot (73-01)
  - system.snapshot_service.collect_host_snapshot (73-01)
  - system.models.GaugeSample / RequestMetric (73-01 / 72)
  - interactions.models.ModelUsageRecord (72)
  - system.log_retention (Phase 71 范式)
  - agents.management.commands.runapscheduler (_with_scheduler_log_context + run_async_task)
provides:
  - system.metric_sampling.sample_gauges
  - system.metric_retention.purge_gauge_samples / purge_request_metrics / purge_model_usage_records
  - runapscheduler: sample_gauges_job (IntervalTrigger ~45s) + purge_metrics_job (daily Cron 05:00)
  - SettingKeys.METRIC_SAMPLE_INTERVAL_SECONDS / METRIC_RETENTION_DAYS / METRIC_RETENTION_SIZE
affects:
  - 73-02 gauge:<name> 时序查询（消费 GaugeSample 趋势）
tech-stack:
  added: []
  patterns: [best-effort 观测不反噬, 受控 name/labels 枚举, async ORM abulk_create/adelete/async for, apscheduler IntervalTrigger/CronTrigger]
key-files:
  created:
    - server/system/metric_sampling.py
    - server/system/metric_retention.py
    - server/tests/test_metric_sampling.py
    - server/tests/test_metric_retention.py
  modified:
    - server/system/models.py
    - server/agents/management/commands/runapscheduler.py
decisions:
  - "采样间隔 apscheduler 以 settings 启动值为准（getattr 默认 45），热改间隔需重启 scheduler——量级低可接受"
  - "purge_metrics 选 daily 05:00（与 prune_cache_volumes 同时段，量级低不争 SQLite 写锁）"
  - "_purge_table 抽公共逻辑 + 白名单 time_field 字面量（ts / created_at），ModelUsageRecord 按 created_at 绝不删错列"
  - "MetricDailyRollup 仅留占位（模块 docstring 注明 v2 可选），不建模型/迁移"
metrics:
  duration: ~20m
  completed: 2026-06-25
---

# Phase 73 Plan 03: 趋势采样侧 + 指标表保留清理 Summary

apscheduler 周期把 73-01 并发/队列/积压快照拍平成受控 name 的 `GaugeSample` 行（~45s，best-effort），并镜像 Phase 71 `log_retention` 对 `GaugeSample`/`RequestMetric`（按 `ts`）+ `ModelUsageRecord`（按 `created_at`）做按天数+行数上限的 daily 保留清理（RATE-03 采样侧 + 保留治理）。

## Task 结果

| Task | 内容 | 状态 |
|------|------|------|
| 1 | SettingKeys.METRIC_* 三常量 + `metric_sampling.py`（sample_gauges 拍平 + bulk_create）+ 测试 | PASS |
| 2 | `metric_retention.py`（三表按天数+行数清理，_purge_table 公共逻辑）+ 测试 | PASS |
| 3 | runapscheduler 注册 sample_gauges(~45s) + purge_metrics(daily 05:00) + job wrapper 测试 | PASS |

## 实现要点

- **sample_gauges**（best-effort，整函数 try/except 返回 `{"written": n}`）：
  - provider 槽位 → `concurrency.provider_slots`（labels 仅 `credential` UUID / `provider` 枚举，`in_use=None` 凭证跳过不臆造）；
  - durable → `queue.durable_todo` / `queue.durable_doing`（按 procrastinate 队列名分行，仅 todo/doing）；
  - runner → `queue.runner_pending`（assigned）/ `queue.runner_local`（current_tasks）；
  - RAG（源 n/a）跳过不落 0 噪声；
  - 后台积压 → `backlog.subagent_active` / `backlog.background_tasks`（取 `collect_host_snapshot().background_tasks` 聚合值）；
  - 所有行共用同一 `ts`；`name` 全在模块级 `_GAUGE_NAMES` 受控枚举内（与 73-02 `_validate_gauge_name` 前缀对齐）；事件 `gauge_sampled` 用 `category=sampling`。
- **metric_retention**：`_purge_table(model, time_field, label)` 抽公共「按龄 + 按量」清理（白名单 `time_field` 字面量，`_SIZE_DELETE_BATCH=50_000` 分批）；三 wrapper 分清口径（GaugeSample/RequestMetric=`ts`，ModelUsageRecord=`created_at`），各记 `<table>_purged`（category=caller）；模块 docstring 注明 MetricDailyRollup 为 v2 占位不建表。
- **runapscheduler**：`sample_gauges_job`（IntervalTrigger，秒数 `getattr(settings, "METRIC_SAMPLE_INTERVAL_SECONDS", 45)`）+ `purge_metrics_job`（CronTrigger 05:00，内层 `_run` 顺序 await 三表），均 `@_with_scheduler_log_context` + `run_async_task`，异常 `log.exception` 吞掉不打断 scheduler；不动既有 job / 单实例 flock 契约。

## Deviations from Plan

None - plan executed exactly as written.

## 测试

- `tests/test_metric_sampling.py`（7）：拍平受控行/labels 无密钥、跳空源、采集器抛错降级 written=0、`sample_gauges_job`/`purge_metrics_job` 接线 + 失败不冒泡。
- `tests/test_metric_retention.py`（4）：GaugeSample 按龄、RequestMetric 按量、ModelUsageRecord 按 `created_at`（不抛 FieldError）、adelete 抛错降级。
- async 写测试均 `@pytest.mark.django_db(transaction=True)`。

## 验证结果

- `uv run pytest tests/test_metric_sampling.py tests/test_metric_retention.py -q` → **11 passed**。
- `uv run python manage.py makemigrations --check --dry-run` → **No changes detected**（仅加 SettingKeys 常量 + 新模块，零迁移）。
- `uv run ruff check`（6 个改动文件）→ **All checks passed**。
- 守护回归 `tests/test_scheduler_registration.py` + `tests/test_credential_leak_protection.py` → **28 passed**。

## Known Stubs

None.

## Self-Check: PASSED

- 文件存在：`server/system/metric_sampling.py`、`server/system/metric_retention.py`、`server/tests/test_metric_sampling.py`、`server/tests/test_metric_retention.py`（均 FOUND）。
- 修改：`server/system/models.py`（SettingKeys.METRIC_*）、`server/agents/management/commands/runapscheduler.py`（两 job + 注册块）（均 FOUND）。
- 未 git commit（per 执行规则）。
