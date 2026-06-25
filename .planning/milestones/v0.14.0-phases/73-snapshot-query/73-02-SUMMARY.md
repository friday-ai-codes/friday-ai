---
phase: 73-snapshot-query
plan: "73-02"
subsystem: system / observability
tags: [metrics, timeseries, percentile, sla, query-api]
requires: ["72-01 RequestMetric", "72-02 ModelUsageRecord", "73-01 GaugeSample / metrics_views"]
provides: ["GET /api/system/metrics/query", "system.metrics_query.query_timeseries"]
affects: ["server/system/metrics_views.py", "server/system/urls_system.py"]
tech-stack:
  added: []  # 零新增依赖（Django ORM + raw SQL + 标准库 datetime/math/decimal）
  patterns: ["connection.vendor 双后端分支", "raw cursor 参数化聚合", "白名单列名 + int 收口防注入", "sync_to_async 桥接 async 视图"]
key-files:
  created:
    - server/system/metrics_query.py
    - server/tests/test_metrics_query.py
  modified:
    - server/system/metrics_views.py
    - server/system/urls_system.py
decisions:
  - "分位精确走 Postgres percentile_cont(WITHIN GROUP)；SQLite dev 降级 p95/p90→MAX、p50→AVG，打 degraded=true + note，功能不阻塞（§A.4）"
  - "任意 step 用 epoch-floor 分桶（to_timestamp/floor 与 strftime/整除）替代 date_trunc，支持任意秒级 step"
  - "SQLite 下 strftime('%s') 的 %s 与 Django cursor 占位符冲突，转义为 %%s"
  - "dimension 落到各表实际列才分组（_REQUEST_DIMS/_USAGE_DIMS），否则退化 '__all__' 全量桶，避免 SQL 列错"
  - "SLA 口径 error_class!='business' 进分母、IN('system','upstream') 计故障、business 单列 business_rejected"
metrics:
  duration: "~1 工作单元"
  completed: 2026-06-24
  tasks: 3
  files: 4
---

# Phase 73 Plan 02: 时序查询 API（QUERY-01 + SLA-01 + RATE-03 查询侧）Summary

One-liner: 新增单一只读时序聚合服务 `system/metrics_query.py`（任意 step epoch-floor 分桶 + Postgres `percentile_cont` 精确分位 / SQLite 降级兜底 + qps/tps/error/duration/ttft/sla/gauge 各 metric）与 `GET /api/system/metrics/query`（IsSuperUser），把 Phase 72 事件行变成"可按任意时间段查询 + 出趋势"，零自研聚合器、全参数化无注入面。

## Tasks（PASS/FAIL）

- **Task 1 — 查询服务地基（参数校验 + 任意 step 分桶 + QPS/错误计数）**：PASS
  - `_METRICS/_AGGS/_DIMENSIONS/_PERCENTILE` 受控枚举 + gauge: 前缀；`_parse_step`（30s/1m/5m/1h/1d，默认 60、收口 [10,86400]）、`_parse_range`（缺省 end=now/start=end-1h）、`_cap_step`（桶数超 2000 按比例抬 step）、`_validate`（白名单，非法中文 ValueError）。
  - `_bucket_expr` 双后端 epoch-floor；`_query_count` qps（synthetic 排除）/ error（按 error_class 三口径）。
  - 验证：`pytest -k "parse or validate or qps or error or bucket"` → 9 passed。
- **Task 2 — 分位时长/TTFT + TPS + gauge 趋势**：PASS
  - `_query_percentile`（Postgres `percentile_cont` 精确；SQLite p95/p90→MAX、p50→AVG，`degraded=true`+`note="sqlite_percentile_approx"`，null value 排除）；`_query_sum`（`ModelUsageRecord.created_at` 桶 SUM(total_tokens) 分 provider/call_source/model）；`_query_gauge`（受控名校验 + AVG/MAX）；`query_timeseries` 统一分派出口。
  - 验证：`pytest -k "percentile or duration or ttft or tps or gauge or degraded"` → 5 passed。
- **Task 3 — SLA-01 可用率 + MetricsQueryView + urls**：PASS
  - `_query_sla`（口径排除业务限制：eligible=非 business、failures=system/upstream、business_rejected 单列、availability=(eligible-failures)/eligible，eligible=0→None，synthetic 排除）。
  - `MetricsQueryView(APIView)`（IsSuperUser，async，`sync_to_async(query_timeseries)`，ValueError→400 中文 detail，结构化 `metrics_query_served` 日志 category=caller/component=metrics）。
  - `urls_system.py` 挂 `metrics/query/`（紧邻 metrics/snapshot/）。
  - 验证：`pytest tests/test_metrics_query.py` → 17 passed；`ruff check` 干净。

## Verification Results

- `uv run pytest tests/test_metrics_query.py -q` → **17 passed**。
- `uv run ruff check system/metrics_query.py system/metrics_views.py tests/test_metrics_query.py system/urls_system.py` → **All checks passed**（自动修了一处 import 排序 I001）。
- `uv run python manage.py makemigrations --check --dry-run` → **No changes detected**（本 plan 零模型/迁移变更）。
- 回归守护：`uv run pytest -k "credential_leak or redact"` → **60 passed**（脱敏链路零回归）。

## Files Changed

- `server/system/metrics_query.py`（新建，~360 行）：时序聚合单一服务。
- `server/system/metrics_views.py`（修改）：新增 `MetricsQueryView` + import `metrics_query`/`sync_to_async`。
- `server/system/urls_system.py`（修改）：新增 `metrics/query/` 路由 + import `MetricsQueryView`。
- `server/tests/test_metrics_query.py`（新建）：17 用例覆盖解析/校验/分桶/synthetic 排除/三口径/分位降级/null 排除/TPS/gauge/SLA/权限。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] SQLite `strftime('%s', ...)` 与 Django cursor 占位符冲突**
- **Found during:** Task 1（首次跑测，所有行误落入 1970-01-01 单桶）。
- **Issue:** Django SQLite cursor 把 SQL 文本里的 `%s` 当作绑定占位符消费，导致 `strftime('%s', ts)` 的 `%s` 被错误替换，分桶表达式失效。
- **Fix:** `_bucket_expr` SQLite 分支把 `%s` 转义为 `%%s`（Django `convert_query` 还原为字面 `%`），并加注释说明。
- **Files modified:** `server/system/metrics_query.py`
- **Commit:** 未提交（按执行约定不 git commit）。

> 其余按计划原样实现。Postgres `percentile_cont` 精确路径在本机 SQLite 无法直跑，测试按 `connection.vendor` 分支断言（SQLite 走 degraded 兜底），不强求真 PG，符合 plan「tests run on SQLite by default」约定。

## Decisions Made

- `dimension` 按表可分组列收口（`_REQUEST_DIMS`={source,route,error_class} / `_USAGE_DIMS`={provider,call_source,model}）：维度落不到该表实际列时退化 `'__all__'` 全量桶，既满足白名单防注入又避免跨表列名错（注：provider/call_source/model 在 RequestMetric 是 labels JSON、非列，故 qps/error/duration/ttft/sla 仅 source/route/error_class 可分组）。
- 各 metric 默认 dimension：qps/tps/sla/duration/ttft 默认 `'__all__'`（不分组总量），error 默认按 `error_class` 分组（口径需要）。
- 时间参数经 `connection.ops.adapt_datetimefield_value` 适配双后端可比较值（Postgres datetime / SQLite ISO 串），统一参数化 `%s` 占位。

## Threat Model Compliance

- T-73-02-01（注入）：metric/agg/dimension 全经 `frozenset` 白名单，列名仅取白名单常量，step 经 `int()`，start/end/gauge-name 经 `%s` 参数化——无用户原文进 SQL 文本。✓
- T-73-02-02（DoS）：`_cap_step` 桶数超 2000 抬 step。✓
- T-73-02-03（信息泄漏）：聚合仅返回计数/分位/比率元数据，不回显 raw payload。✓
- T-73-02-04（越权）：`MetricsQueryView` `IsSuperUser` fail-closed。✓
- T-73-02-05（降级误判）：SQLite 分位返回 `degraded=true`+`note`。✓
- T-73-02-SC：零新增依赖。✓

## Observability 合规

- 查询入口结构化日志 `metrics_query_served`（snake_case + `category="caller"` + `component="metrics"` + `duration_ms` + metric/step_seconds/series_len/degraded），不记用户查询原文外的敏感内容；`/api/system/metrics` 前缀已在 72-01 中间件打 synthetic 隔离（本 plan 未改中间件）。

## Self-Check: PASSED

- `server/system/metrics_query.py`：FOUND
- `server/tests/test_metrics_query.py`：FOUND
- `server/system/metrics_views.py` 含 `class MetricsQueryView`：FOUND
- `server/system/urls_system.py` 含 `metrics/query/`：FOUND
- pytest 17 passed / ruff clean / makemigrations no-change：CONFIRMED
