# Phase 73: 快照·趋势·查询 API - Context

**Gathered:** 2026-06-24
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous——grey area 按 MILESTONE-PROPOSAL §B Phase 73 + STATE.md 关键约束自动采纳最优解）

<domain>
## Phase Boundary

把 Phase 72 采集的事件数据变成"可按任意时间段查询 + 出趋势"，并补齐"只看当前"的快照与查询 API。

**交付（SNAP-01~05, RATE-03, SLA-01, QUERY-01, QUERY-02）：**
- 快照采集器：server/主机（CPU/内存/协程/线程/后台任务，psutil）、DB（pg_stat_activity + max_connections + psycopg pool + PgBouncer SHOW POOLS）、Redis（INFO connected_clients/maxclients/内存/命中率，多路客户端）、Qdrant（可用性/collection 数/占用，带缓存+长超时）、并发/排队（provider 槽位/durable todo·doing/runner 待派发·本地队列/RAG 并发）
- `GaugeSample` 周期采样（apscheduler 30–60s）：并发/队列深/积压趋势
- 时序查询 API `GET /api/system/metrics/query`（任意时间段/step/维度 + P95/P90/P50/Avg/Max via `percentile_cont`）+ 保留清理 + 可选每日 rollup
- 快照 API `GET /api/system/metrics/snapshot`（聚合返回 SNAP-01~05 当前值）
- 可用率/业务故障率（SLA-01，口径"排除业务限制"）

依赖 Phase 72（时序查询依赖 RequestMetric/ModelUsageRecord 事件数据）。

</domain>

<decisions>
## Implementation Decisions

### 快照采集（SNAP-01~05，只看当前不长存）
- 单一聚合采集器 `system/snapshot_service.py`，各源独立 best-effort（一源失败不拖垮整体，返回该源 `available=false`+error）。
- **SNAP-01 server/主机**：`psutil`（已依赖）取 CPU%/内存；`asyncio.all_tasks()` 协程数；`threading.active_count()` 线程数；后台任务数（durable active 经 `has_active`/计数、background_runner in-flight、workflow 线程、edge build）。
- **SNAP-02 DB**：PG `pg_stat_activity`（连接/活跃/空闲/等待）+ `max_connections`；psycopg pool `get_stats()`（v0.13 已接池）；PgBouncer 模式 `SHOW POOLS`（opt-in profile）。SQLite dev 降级（返回 n/a）。
- **SNAP-03 Redis**：`INFO`（connected_clients/maxclients/used_memory/keyspace hits·misses→命中率），覆盖 cache/channels/llm 多路客户端（逐客户端或聚合）。
- **SNAP-04 Qdrant**：可用性 + collection 数 + 占用空间；**独立端点 + 缓存（TTL 60s）+ 长超时**，区分现有 `ping_liveness`（快）与 `health_check`（重），避免拖垮。
- **SNAP-05 并发/排队**：provider 凭证当前占用槽位（llm_concurrency 槽位状态）、各 durable 队列 todo/doing、runner 待派发与本地队列、RAG 并发。
- 快照 API `GET /api/system/metrics/snapshot` 聚合返回全部，IsSuperUser，best-effort 局部降级。

### 趋势采样（RATE-03，只记不告警）
- `GaugeSample` 模型（system app）：`ts(index)`, `name`, `value(float)`, `labels(jsonb 受控)`。
- apscheduler 周期任务（30–60s）采样并发/队列深/积压（调 snapshot_service 的并发/队列部分）落 GaugeSample。吞吐(各 provider QPS/TPS)/错误趋势由 Phase 72 事件表 SQL 聚合（不重复采样）。
- 保留清理复用 Phase 71 `log_retention` 同款机制（GaugeSample/RequestMetric/ModelUsageRecord 按保留天数清理）。

### 时序查询 API（QUERY-01 / SLA-04 分位 / SLA-01 可用率）
- `GET /api/system/metrics/query`：参数 `metric`(qps/tps/sla/error/duration/ttft)、`start`/`end`/`step`、`dimension`(source/provider/call_source/error_class 等)、`agg`(p95/p90/p50/avg/max)。
- **分位用 Postgres `percentile_cont`**（精确），`date_trunc(step)` 时间桶。**SQLite dev 降级**：近似/跳过分位（用 avg/max 兜底），功能不阻塞（§A.4）。
- **SLA-01 可用率**：由 RequestMetric 成功/失败比派生，**口径"排除业务限制"**（error_class=business 不计故障）+ 健康探针；按入口/时间段查询。
- QPS/TPS：按时间桶 count；错误率按 error_class 分口径；时长/TTFT 分位 percentile_cont。
- 轮询/health 打标行（72-01 已隔离）在 SLA/QPS 聚合中排除。
- **保留清理 + 可选每日 rollup（MetricDailyRollup）**：长区间趋势可选每日聚合，本 Phase 实现保留清理为主，rollup 标可选（量级低，原始行足够）。

### Claude's Discretion
- migration 编号自动生成；GaugeSample 索引、采样间隔（默认 45s）、查询 API 默认 step/上限、Qdrant 缓存 TTL 在 plan 定。
- snapshot_service 各源拆分粒度、Redis 多客户端聚合 vs 逐路由 plan 定。
- MetricDailyRollup 是否本 Phase 落地：倾向只落保留清理 + 留 rollup 占位（量级低不急）。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `psutil>=5.9.0`（已依赖，SNAP-01）。
- `server/system/health_views.py`（健康探针，可复用 ping 逻辑）；`server/system/dashboard_views.py`/`observability_views.py`（运维视图范式）。
- Phase 71：`system/log_retention.py`（保留清理范式，指标表复用）、apscheduler job 范式（`runapscheduler.py`）、`settings_service`（运行时配置/缓存）。
- Phase 72：`RequestMetric`（QPS/错误/时长/TTFT/SLA 源）、`ModelUsageRecord`（TPS/上游源）、`metric_sink`、`classify_error`（口径）。
- `server/agents/llm_concurrency.py`（provider 槽位状态，SNAP-05）。
- `server/durable/service.py`（`has_active_by_key`/队列状态，SNAP-05）；runner consumers（待派发/本地队列）。
- v0.13 psycopg pool（`get_stats()`，SNAP-02）+ PgBouncer opt-in。
- Qdrant service（`ping_liveness`/`health_check`，SNAP-04）；Redis 多路客户端（cache/channels/llm）。

### Established Patterns
- best-effort 观测 `except: pass`；async ORM sync_to_async；IsSuperUser 运维端点；adrf 异步视图。
- 第一性原理：原始事件行 + `percentile_cont` 精确分位，不自研聚合器（§A.2）；SQLite dev 降级分位（§A.4）。

### Integration Points
- snapshot_service 调 psutil/pg_stat_activity/redis INFO/qdrant/llm 槽位/durable 队列。
- GaugeSample apscheduler 周期采样。
- 查询/快照 API 落 `server/system/`（新 views + urls，IsSuperUser）。
- 保留清理接 Phase 71 log_retention 同款 apscheduler。

</code_context>

<specifics>
## Specific Ideas

- 严守 `.cursor/rules/observability-logging.mdc`：快照/查询入口纳入 QPS（72 已埋点，本 Phase 标 synthetic 隔离避免污染）。
- Qdrant 快照"带缓存+长超时避免拖垮"是硬约束（用户明确）。
- 分位精确走 percentile_cont；SQLite dev 降级不阻塞。
- 本 Phase 只读 + 采样 + 查询，不告警（告警在 74）、不出图（大盘在 75）。

</specifics>

<deferred>
## Deferred Ideas

- 阈值告警评估（SystemAlertRule/AlertEvent）→ Phase 74（消费本 Phase 查询/快照）。
- 大盘前端出图（echarts）→ Phase 75（消费查询/快照 API）。
- MetricDailyRollup 完整 rollup 引擎 → 可选/v2（量级低，原始行足够）。

</deferred>
