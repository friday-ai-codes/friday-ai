---
phase: 73-snapshot-query
plan: "73-01"
subsystem: observability
tags: [snapshot, metrics, psutil, qdrant, redis, concurrency, IsSuperUser]
requires:
  - "Phase 71: SystemLogEntry / log_sink / log_retention"
  - "Phase 72: RequestMetric / metric_sink / middleware synthetic 隔离"
  - "llm_concurrency 槽位 / durable.service / qdrant_service.ping_liveness / observability_views 聚合范式"
provides:
  - "snapshot_service.collect_snapshot 五源聚合器（host/db/redis/qdrant/concurrency）"
  - "GaugeSample 周期采样模型（供 73-03 写入 / 73-02 趋势查询）"
  - "GET /api/system/metrics/snapshot/（IsSuperUser）"
  - "/api/system/metrics 前缀 synthetic 隔离"
affects:
  - "73-02 趋势查询（消费 GaugeSample）"
  - "73-03 周期采样（写入 GaugeSample，调 snapshot_service 并发/队列部分）"
tech-stack:
  added: []
  patterns:
    - "各源 best-effort：整函数 try/except 兜底 + asyncio.wait_for 超时 + gather(return_exceptions=True) 双保险"
    - "Qdrant 缓存(TTL 60s)+长超时+ping 不健康不枚举（硬约束）"
    - "async 事件循环内取 asyncio.all_tasks()；DB 聚合 sync_to_async 桥接"
key-files:
  created:
    - server/system/snapshot_service.py
    - server/system/metrics_views.py
    - server/system/migrations/0011_gaugesample.py
    - server/tests/test_metrics_snapshot.py
  modified:
    - server/system/models.py
    - server/system/urls_system.py
    - server/common/middleware.py
decisions:
  - "Runner 容量字段用既有 concurrent（计划文本写 max_concurrent，实际模型字段为 concurrent，与 observability_views._runner_load 对齐）"
  - "RunnerTaskAssignment 按实际 Status(assigned/running/completed/failed) 计数（计划文本提及 pending/dispatched，实际模型无此枚举）"
  - "Qdrant 占用空间仅采样前 20 个 collection 的 points_count，避免遍历全部拖垮"
  - "RAG 并发无显式信号量 → 记 {available:false, error:'n/a'}（不臆造）"
metrics:
  duration: ~25min
  completed: 2026-06-24
---

# Phase 73 Plan 01: 快照地基（SNAP-01~05 + QUERY-02） Summary

新增单一聚合采集器 `snapshot_service`（host/DB/Redis/Qdrant/并发排队五源，各源独立 best-effort）+ 快照 API `GET /api/system/metrics/snapshot/`（IsSuperUser）+ `GaugeSample` 周期采样模型，兑现"现在健康吗"一次取齐，并为 73-02/73-03 的趋势查询/周期采样打地基。

## Tasks

| Task | 状态 | 说明 |
|------|------|------|
| Task 1: GaugeSample 模型 + 0011 迁移 + host/DB 源 | PASS | 模型/迁移就位；host 返 CPU/内存/协程/线程/后台任务；DB Postgres 返 pg_stat_activity+max_connections+pool(+PgBouncer opt-in)，SQLite 优雅降级 |
| Task 2: Redis/Qdrant/并发排队三源 + 聚合器 | PASS | Redis 多路去重+命中率；Qdrant 缓存+长超时+ping 不健康不枚举；并发槽位/durable/runner/RAG；collect_snapshot 局部降级 |
| Task 3: 快照 API + urls + 中间件 synthetic | PASS | MetricsSnapshotView(IsSuperUser) 聚合+队列计数；/api/system/metrics 纳入 synthetic 隔离 |

## Verification Results

- `uv run pytest tests/test_metrics_snapshot.py` → **13 passed**（host/db/redis/qdrant/concurrency/aggregate/API 权限/synthetic）。
- `uv run pytest tests/test_credential_leak_protection.py` → **24 passed**（脱敏守护保持绿；合计 37 passed）。
- `uv run python manage.py makemigrations --check --dry-run` → **No changes detected**（0011 已生成）。
- `uv run ruff check`（snapshot_service/metrics_views/models/middleware/urls_system/test）→ **All checks passed**（line-length 100）。

## Files Changed

- **新建** `server/system/snapshot_service.py` — 五源采集器 + `collect_snapshot` 聚合器。
- **新建** `server/system/metrics_views.py` — `MetricsSnapshotView`（async，IsSuperUser）。
- **新建** `server/system/migrations/0011_gaugesample.py` — GaugeSample 建表（base 0010_requestmetric）。
- **新建** `server/tests/test_metrics_snapshot.py` — 13 用例覆盖五源 + 缓存命中 + 局部降级 + 权限 + synthetic。
- **改** `server/system/models.py` — 新增 `GaugeSample`（ts/name/value/labels + 复合索引 (ts,name)/(name,-ts)）。
- **改** `server/system/urls_system.py` — 接入 `metrics/snapshot/` 路由。
- **改** `server/common/middleware.py` — `_SYNTHETIC_ROUTE_MARKERS` 增加 `/api/system/metrics` 前缀。

## Deviations from Plan

### 与实际模型对齐的修正（Rule 1）

**1. [Rule 1 - 对齐实际字段] Runner 容量字段 `concurrent`（非 `max_concurrent`）**
- **Found during:** Task 2（runner 统计）。
- **Issue:** 计划文本写 `Runner.max_concurrent`，实际模型字段为 `concurrent`（见 `runners/models.py:85`，与 `observability_views._runner_load` 用法一致）。
- **Fix:** `_collect_runner_stats` 用 `Sum("concurrent")` 作为容量。
- **Files:** `server/system/snapshot_service.py`。

**2. [Rule 1 - 对齐实际枚举] RunnerTaskAssignment 按实际 Status 计数**
- **Found during:** Task 2。
- **Issue:** 计划文本提及 pending/dispatched，实际 `RunnerTaskAssignment.Status` 为 assigned/running/completed/failed。
- **Fix:** 按实际 status `values().annotate(Count)` 输出 `assignments_by_status`（如实反映，不臆造枚举）。
- **Files:** `server/system/snapshot_service.py`。

### Claude's Discretion（计划授权范围内）

- Qdrant 占用空间仅采样前 `_QDRANT_SIZE_SAMPLE_LIMIT=20` 个 collection 的 `points_count`，带 `truncated` 标记（避免遍历数百 collection 拖垮，计划授权"采样前 N 个"）。
- RAG 并发无显式信号量/槽位 → 记 `{available:false, error:"n/a"}`（计划明确"无显式信号量不臆造"）。

## 可观测性 / 安全自检

- 结构化事件：`metrics_snapshot_served`（category=caller, component=metrics, duration_ms）；各源失败 `snapshot_*_failed`（category=sampling, component=metrics）。
- best-effort：所有源 + counters 采集失败吞掉，绝不反噬主流程。
- IsSuperUser fail-closed（非超管 403，匿名 401/403 — 测试覆盖）。
- 脱敏：快照仅返回状态元数据（CPU%/连接数/collection 数/槽位占用），provider 槽位仅暴露 `credential_id`(UUID) 不含密钥；GaugeSample name/labels 受控枚举；`test_credential_leak_protection.py` 保持绿。
- synthetic 隔离：`/api/system/metrics` 前缀打 `labels.synthetic=true`，快照/查询自身 QPS 不污染业务 SLA（中间件 `_is_synthetic` 测试覆盖）。

## Known Stubs

无功能性 stub。RAG 并发为有意 `n/a`（无显式信号量），非阻塞性占位。

## Self-Check: PASSED

- 文件存在：`snapshot_service.py` / `metrics_views.py` / `0011_gaugesample.py` / `test_metrics_snapshot.py` 均 FOUND。
- 模型/迁移：`GaugeSample` 落 `gauge_samples` 表，`makemigrations --check` 干净。
- 测试：37 passed（13 快照 + 24 凭证脱敏守护）。
- 未做 git commit（per 执行约束）。
