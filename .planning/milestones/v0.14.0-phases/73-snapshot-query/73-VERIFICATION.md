---
phase: 73-snapshot-query
verified: 2026-06-25T00:40:00Z
status: passed
score: 6/6 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: null
recommended_live_checks:  # 非阻塞——代码层 must-have 已满足，仅需真机 PG/Redis/Qdrant 终态确认
  - test: "Postgres 实例下 GET /api/system/metrics/query?metric=duration&agg=p95 返回精确分位（degraded=false）"
    expected: "vendor=postgresql、degraded=false、value 为 percentile_cont 精确分位（非 MAX 兜底）"
    why_live: "percentile_cont 仅 Postgres 可执行；本地 SQLite 走 degraded 兜底（代码分支已确认存在，见 metrics_query.py:247-254）"
  - test: "真实 Redis 下 snapshot 返回 connected_clients/maxclients/命中率"
    expected: "redis.clients.{cache,channels,llm} available=true，hit_rate 为 hits/(hits+misses)"
    why_live: "测试环境未配 Redis（not_configured 降级路径已测）；真实 INFO 字段需运行期确认"
  - test: "真实 Qdrant 下 snapshot 返回 liveness + collection_count，二次请求 cached=true"
    expected: "首次 cached=false 枚举、60s 内二次 cached=true（不重复枚举）"
    why_live: "缓存命中/ping-不健康-不枚举逻辑已单测 mock 验证；真机枚举耗时与缓存命中需运行期确认"
  - test: "Postgres 下 DB 快照返回 pg_stat_activity 连接分布 + max_connections + 池"
    expected: "db.available=true、connections{total/active/idle/idle_in_transaction/waiting} + max_connections + pool"
    why_live: "SQLite dev 优雅降级 available=false（已测）；PG 真实查询需运行期确认"
---

# Phase 73: 快照·趋势·查询 API Verification Report

**Phase Goal:** 把 Phase 72 采集的数据变成"可按任意时间段查询 + 出趋势"，并补齐"只看当前"的快照与查询 API。
**Verified:** 2026-06-25T00:40:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths（ROADMAP Phase 73 六条成功标准，逐条对照代码而非任务完成度）

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | server/主机快照：CPU、内存(psutil)、协程数、线程数、后台任务数当前值可查 | ✓ VERIFIED | `snapshot_service.collect_host_snapshot`（snapshot_service.py:64-114）返回 `cpu_percent`/`mem_total_mb`/`mem_used_mb`/`mem_percent` + `asyncio.all_tasks()` 协程数（事件循环线程内取，RuntimeError 降级 None）+ `threading.active_count()` 线程数 + `background_tasks`（复用 `observability_views._background_task_summary` 口径）。psutil 异常→available=false 不冒泡。 |
| 2 | DB(连接/活跃/空闲/max_connections)、Redis(连接/maxclients/内存/命中率)、Qdrant(可用性/collection 数/占用，缓存+长超时)当前值可查 | ✓ VERIFIED | DB：`collect_db_snapshot`+`_collect_db_sync`（:122-237）查 pg_stat_activity（total/active/idle/idle_in_transaction/waiting）+ `SHOW max_connections` + psycopg 池 `get_stats()` + PgBouncer(opt-in)；SQLite 优雅降级 `n/a (sqlite dev)`。Redis：`collect_redis_snapshot`+`_probe_redis`（:245-331）三路 cache/channels/llm 去重 INFO，取 connected_clients/maxclients/used_memory/keyspace_hits·misses→hit_rate。Qdrant：`collect_qdrant_snapshot`（:382-453）ping_liveness(fast) 不健康不枚举 + 枚举段缓存 `_QDRANT_CACHE_TTL=60` + `SOURCE_TIMEOUT_SLOW=8.0` 长超时，返 collection_count + approx_size。 |
| 3 | 并发/排队当前值：provider 凭证槽位、durable todo/doing、runner 待派发/本地、RAG 并发 | ✓ VERIFIED | `collect_concurrency_snapshot`（:551-594）四块独立 try/except：provider 槽位 `_collect_provider_slots`（Redis ZCARD 清过期租约 / 进程内信号量内省）；durable 复用 `_durable_queue_stats`；runner `_collect_runner_stats`（assignments_by_status + current_tasks/concurrent 汇总）；RAG 无显式信号量记 `{available:false, error:"n/a"}`（计划授权不臆造）。 |
| 4 | 趋势(只记不告警)：GaugeSample 周期采样并发/排队/积压；吞吐(各 provider QPS/TPS)/错误趋势可按时间段查询 | ✓ VERIFIED | 采样侧：`metric_sampling.sample_gauges`（:52-168）调 73-01 并发/主机采集器拍平受控 name 行 `abulk_create`；`runapscheduler.sample_gauges_job` + `IntervalTrigger(~45s)` 注册（runapscheduler.py:485-495）。查询侧：`metrics_query.query_timeseries` 支持 `gauge:<name>`（`_query_gauge` 受控前缀校验）+ qps(`_query_count`)/tps(`_query_sum` ModelUsageRecord.created_at SUM token)/error(error_class 三口径)。 |
| 5 | 每时刻可用率/业务故障率可查（口径"排除业务限制"） | ✓ VERIFIED | `metrics_query._query_sla`（:316-364）：分母 `eligible=error_class != 'business'`（业务限制不计入）、故障 `failures=error_class IN ('system','upstream')`、`availability=(eligible-failures)/eligible`（eligible=0→None）、`business_rejected` 单列；synthetic 行排除分母。 |
| 6 | 时序查询 API 任意时间段/step/维度 + P95/P90/P50/Avg/Max（percentile_cont；SQLite 降级）；快照 API 聚合当前值 | ✓ VERIFIED | `query_timeseries`（:372-461）：metric×start/end/step×dimension×agg 全白名单校验 + epoch-floor 任意 step 分桶。**Postgres percentile_cont 精确路径确认存在**（`_query_percentile` :247-254，`vendor=="postgresql"` 分支 `percentile_cont({frac}) WITHIN GROUP`）；SQLite 降级 p95/p90→MAX、p50→AVG + `degraded=true`（:255-259）。快照 API `MetricsSnapshotView`（metrics_views.py:29-65）调 `collect_snapshot` 聚合五源 + 队列计数。 |

**Score:** 6/6 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `server/system/snapshot_service.py` | 五源采集器 + collect_snapshot 聚合 | ✓ VERIFIED | 625 行，五源 + `collect_snapshot`（gather return_exceptions=True 双保险局部降级）。 |
| `server/system/models.py::GaugeSample` | ts/name/value/labels + 复合索引 | ✓ VERIFIED | models.py:402-441，BigAutoField + Index(ts,name)/(name,-ts)，db_table=gauge_samples。 |
| `server/system/migrations/0011_gaugesample.py` | 建表迁移 | ✓ VERIFIED | 文件存在；`makemigrations --check` 干净（summary 确认 No changes）。 |
| `server/system/metrics_views.py` | MetricsSnapshotView + MetricsQueryView | ✓ VERIFIED | 两视图 IsSuperUser async；snapshot 调 collect_snapshot，query 经 sync_to_async 调 query_timeseries。 |
| `server/system/metrics_query.py` | query_timeseries 双后端分位 | ✓ VERIFIED | 462 行；percentile_cont/SQLite 降级、白名单防注入、SLA、gauge。 |
| `server/system/metric_sampling.py` | sample_gauges 拍平 GaugeSample | ✓ VERIFIED | best-effort，受控 name/labels，available=false 源跳过。 |
| `server/system/metric_retention.py` | 三表保留清理 | ✓ VERIFIED | GaugeSample/RequestMetric=ts、ModelUsageRecord=created_at（白名单 time_field 不删错列）。 |
| `SettingKeys.METRIC_*` | 三运行时配置常量 | ✓ VERIFIED | models.py:127-130（SAMPLE_INTERVAL_SECONDS/RETENTION_DAYS/RETENTION_SIZE）。 |
| `runapscheduler.py` 两 job | sample_gauges(~45s) + purge_metrics(daily) | ✓ VERIFIED | :485-508 注册 IntervalTrigger + CronTrigger(05:00)，max_instances=1。 |

### Key Link Verification

| From | To | Via | Status |
| --- | --- | --- | --- |
| urls_system.py | MetricsSnapshotView/MetricsQueryView | metrics/snapshot/ + metrics/query/ 路由 | ✓ WIRED (urls_system.py:9,28,30) |
| metrics_views.py | snapshot_service.collect_snapshot / metrics_query.query_timeseries | 视图调聚合器 | ✓ WIRED |
| metric_sampling.py | snapshot_service.collect_concurrency_snapshot | sample_gauges 调采集器 | ✓ WIRED |
| runapscheduler.py | metric_sampling.sample_gauges / metric_retention.purge_* | 两 job 周期调用 | ✓ WIRED (:486,501) |
| common/middleware.py | _SYNTHETIC_ROUTE_MARKERS | /api/system/metrics 前缀 synthetic 隔离 | ✓ WIRED (middleware.py:41) |
| metrics_query.py | connection.vendor | percentile_cont(PG) / avg·max 降级(SQLite) 分支 | ✓ WIRED (:247-259,392) |

### Behavioral / Test Verification

Ran: `uv run pytest tests/test_metrics_snapshot.py tests/test_metrics_query.py tests/test_metric_sampling.py tests/test_metric_retention.py tests/test_credential_leak_protection.py tests/test_scheduler_registration.py -p no:randomly -q`

| Result | Detail |
| --- | --- |
| **69 passed, 0 failed** (8.96s) | 快照五源 + 缓存命中 + 局部降级 + 权限 + synthetic；查询解析/校验/分桶/synthetic 排除/三口径/分位降级/null 排除/TPS/gauge/SLA/权限；采样拍平/跳空源/失败降级/job 接线；清理三表按龄·按量/created_at 口径/失败降级；凭证脱敏守护；scheduler 注册守护。 |

> percentile_cont 精确路径在 SQLite 本机无法直跑——测试按 `connection.vendor` 分支断言 SQLite 走 degraded 兜底（计划与本次任务均明确：SQLite degrade 可接受，**非 gap**）。Postgres 精确分支代码确认存在（metrics_query.py:247-254），故 percentile 精确性不标 human_needed。

### Anti-Patterns Found

| File | Pattern | Severity |
| --- | --- | --- |
| （新建/修改五文件）| 无 TODO/FIXME/XXX/TBD/PLACEHOLDER/not implemented | — 无 |

RAG 并发记 `{available:false, error:"n/a"}` 为有意降级（无显式信号量，计划明确"不臆造"），非 stub。

### Gaps Summary

无阻塞性 gap。Phase 73 六条 ROADMAP 成功标准均在代码层落地并由 69 个测试守护通过：五源快照聚合器 best-effort 局部降级、Qdrant 缓存+长超时硬约束、GaugeSample 趋势采样 + ~45s apscheduler、SLA 可用率排除业务限制、时序查询 API（Postgres percentile_cont 精确路径确认存在 + SQLite degrade 兜底）、快照 API 聚合当前值。注入面全白名单 + 参数化、IsSuperUser fail-closed、凭证脱敏守护绿。

`recommended_live_checks`（frontmatter）为**非阻塞**的真机终态确认（PG percentile 精确值 / 真实 Redis INFO / 真实 Qdrant 枚举与缓存 / PG pg_stat_activity）——这些 best-effort 源在测试环境走已验证的优雅降级路径，对应代码分支均已确认存在，仅需运行期最终确认，不影响 passed 判定。

---

_Verified: 2026-06-25T00:40:00Z_
_Verifier: Claude (gsd-verifier)_
