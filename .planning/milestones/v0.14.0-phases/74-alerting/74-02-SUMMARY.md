---
phase: 74-alerting
plan: "74-02"
subsystem: 系统告警（评估 + firing/resolved 生命周期）
tags: [alerting, scheduler, observability, ALERT-01, ALERT-02]
requires:
  - "74-01: SystemAlertRule / AlertEvent 模型 + (rule,target_key) status=firing 条件唯一约束 + SettingKeys.ALERT_*"
  - "74-03: alert_notifier.notify_channels(event, channels) 三通道分发出口"
  - "Phase 73: metrics_query.query_timeseries / snapshot_service.collect_snapshot"
  - "Phase 71: bind_task_context（CTX-02）+ runapscheduler _with_scheduler_log_context + run_async_task"
provides:
  - "system.alert_evaluator.evaluate_system_alerts() 周期评估循环"
  - "metric→源分派 _resolve_current_value（时序 metrics_query / 快照 snapshot_service）"
  - "去重/恢复收口 _open_or_update_firing / _resolve_firing"
  - "runapscheduler evaluate_system_alerts_job(~60s) + purge_alert_events_job(daily 05:30)"
affects:
  - server/system/alert_evaluator.py
  - server/agents/management/commands/runapscheduler.py
tech-stack:
  added: []
  patterns:
    - "best-effort 单规则隔离（逐规则 try/except + 最外层兜底，绝不抛回 job wrapper）"
    - "aget_or_create 服务层去重收口 + DB 条件唯一约束 IntegrityError 兜底双保险"
    - "sync_to_async 桥接同步聚合查询；快照异步直接 await"
    - "_with_scheduler_log_context + run_async_task apscheduler job 范式"
key-files:
  created:
    - server/system/alert_evaluator.py
    - server/tests/test_alert_evaluator.py
  modified:
    - server/agents/management/commands/runapscheduler.py
decisions:
  - "qps 口径：单桶 COUNT(*) 折算每秒请求数（count/window）"
  - "error_rate 经 SLA series 派生 failures/eligible（与 SLA-01 口径一致，排除 business）"
  - "qdrant metric 用可用性布尔转 0/1（在线语义；collection_count 深度规则留 v2）"
  - "purge_alert_events 选 daily 05:30 错峰既有 03:00~05:00 清理任务避免争 SQLite 写锁"
  - "ALERT_EVAL_INTERVAL_SECONDS 未在 settings.py 定义 → getattr 默认 60s（与 SettingKeys 注释一致）"
metrics:
  duration: ~25min
  completed: 2026-06-25
---

# Phase 74 Plan 02: 系统告警评估器与 firing/resolved 生命周期 Summary

新增 `alert_evaluator.evaluate_system_alerts`——对每条 enabled `SystemAlertRule` 按 metric 分派到 Phase 73 时序查询（qps/error_rate/ttft 单桶聚合）或快照服务（cpu/memory/db/redis/qdrant/queue_depth 当前值），与阈值比较；超阈触发去重一条 firing（`aget_or_create` + DB 条件唯一约束双保险）并调 74-03 `notify_channels`，恢复时收尾 resolved 写 `ended_at`/`duration_s`；并在 `runapscheduler` 注册 `evaluate_system_alerts`（IntervalTrigger ~60s）+ `purge_alert_events`（daily 05:30）两个周期任务。

## Tasks

### Task 1 — alert_evaluator（评估 + 去重/恢复收口）: PASS
- `_resolve_current_value`：metric→源分派；时序类经 `sync_to_async(query_timeseries)` 单桶聚合，快照类 `await collect_snapshot()` 取字段；趋势类 `gauge:*`/未知 metric → `None` + `alert_metric_unsupported` warning（RATE-03 默认不参与）；整函数 try/except 取值异常返回 `None`（单规则隔离绝不抛）。
- `_breached`：gt/gte/lt/lte 纯函数。
- `_target_for` / `_build_rule_info` / `_render_title`：`target_key=json.dumps(target,sort_keys=True)` 喂去重约束；`rule_info.expr` 采用 REFERENCE-UI §1.4 同款 `metric op X.XX (current Y.YY) over last 5m (overall)`；title 按 `title_template` 渲染（`{metric}/{current}/{value}`），空/异常退化默认中文拼接。
- `_open_or_update_firing`：`aget_or_create(rule,target_key,status=firing)` 幂等；`IntegrityError` 兜底退化取已存在 firing；已存在仅更新 `current_value`/`last_seen_at`/`rule_info`（不刷屏、不新建）。
- `_resolve_firing`：firing → `resolved` + `ended_at` + `duration_s=max(int(ended-started),0)`。
- `_maybe_notify`：空 channels 跳过；否则 `notify_channels` 再 try/except 兜底（cooldown 天然成立——重复超阈不进本函数）。
- `evaluate_system_alerts`：逐规则独立 try/except（`alert_rule_eval_failed` warning 跳过）+ 最外层兜底返回 `{"evaluated":0}`；周期事件 `category=sampling`，firing/resolved `category=caller` + `rule_id`/`duration_ms`/`source=scheduler`。

### Task 2 — runapscheduler 两 job 注册: PASS
- `evaluate_system_alerts_job`（`@_with_scheduler_log_context`，镜像 `sample_gauges_job`）+ `purge_alert_events_job`（镜像 `purge_observability_logs_job`）模块级 wrapper，`run_async_task` 调用，异常 `log.exception` 不抛。
- `handle()` 在 metrics 注册块后加 `evaluate_system_alerts`（`IntervalTrigger(seconds=getattr(settings,"ALERT_EVAL_INTERVAL_SECONDS",60))`）+ `purge_alert_events`（`CronTrigger(hour=5,minute=30)`），`max_instances=1, replace_existing=True`；不动既有 job/flock 单实例契约。

## Verification

```
uv run pytest tests/test_alert_evaluator.py -q        → 11 passed
uv run ruff check <changed files>                     → All checks passed
uv run python manage.py makemigrations --check         → No changes detected（本 plan 不动模型）
uv run pytest tests/test_scheduler_registration.py \
              tests/test_credential_leak_protection.py → 28 passed（零回归）
```

测试覆盖（test_alert_evaluator.py，`@pytest.mark.django_db(transaction=True)`）：
- (a) 快照 cpu=95>80 → 1 条 firing（severity/title 含 95/`rule_info.expr` 含 `current 95.00`）+ notify 调一次。
- (b) 重复超阈 → 不新建第二条（仍 1 条，`current_value` 更新），notify 不再调。
- (c) 恢复 cpu=10 → firing 转 resolved（`ended_at`/`duration_s` 非空），firing 计数归零。
- (d) 时序 ttft 最近桶 2500>1000 → firing；series 空 → `current=None` 跳过不建事件。
- (e) `gauge:queue.durable_doing` → `_resolve_current_value` 返回 None，不建事件。
- (f) 单规则 `collect_snapshot` 抛错 → cpu 规则跳过、ttft 规则正常 fire（不冒泡）。
- Task 2: 两 job 接线 smoke（stub 调一次）+ 失败不冒泡 + 源码注册块断言。

**firing/resolved 去重生命周期端到端确认**：(a)→(b)→(c) 串联验证「首轮开 1 条 firing+通知 → 重复超阈仅更新不刷屏不重复通知 → 恢复收尾 resolved 写时长」完整闭环，去重硬约束（一条 firing）由 `aget_or_create` 服务层 + 74-01 DB 条件唯一约束双保险成立。

## Deviations from Plan

None - 按计划执行。一处测试自我修正：`test_single_rule_failure_isolated` 初版用 `ev.rule.metric` 触发 async 上下文同步 ORM（`SynchronousOnlyOperation`），改为断言 `ev.rule_info["metric"]` 避免懒加载 FK（仅测试断言方式调整，不涉及评估器逻辑）。

## Files Changed

- `server/system/alert_evaluator.py`（新建，评估循环 + metric→源分派 + 去重/恢复收口）
- `server/tests/test_alert_evaluator.py`（新建，11 用例）
- `server/agents/management/commands/runapscheduler.py`（+2 job wrapper +2 add_job 注册块；未动既有 job）

## Self-Check: PASSED

- FOUND: server/system/alert_evaluator.py
- FOUND: server/tests/test_alert_evaluator.py
- FOUND: evaluate_system_alerts_job + purge_alert_events_job + 注册块（runapscheduler.py）
- 测试 11 passed / ruff clean / makemigrations 无变更 / 守护测试 28 passed
- 未 git commit（per 执行约束）
