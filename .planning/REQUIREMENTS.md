# Requirements: Friday AI

**Defined:** 2026-06-20
**Core Value:** 让团队"开箱即用、安全地"把需求自动变成代码。
**Milestone:** v0.12.0 — 弹性任务底座（durable 任务队列与多副本就绪）

> 把现有"可恢复长任务底座"（`server/resumable/`：DB 真相源 + lease/heartbeat + CAS claim + 启动恢复）演进为生产级 **durable 任务队列**——**采用 Procrastinate（3.8.1），但藏在 Friday 自己的 `DurableTaskService` 适配层后**，业务代码不直接依赖 Procrastinate。统一承载索引/图谱/PageIndex/爬取等后台任务，支持多副本竞争消费、租约心跳、周期 rescue、leader 选主、优雅终止与按队列深度弹性伸缩；以「链接爬取+入库」durable 队列为首个用户可见垂直切片；完成 k8s/compose 部署硬化与 runner 改 k8s Job executor，全方位支持 k8s/k0s 多副本/弹性伸缩。
>
> **设计底座：** 本里程碑前置 PoC 调研结论（Procrastinate 3.8.1 / Python 3.14 / Django 6.0 / psycopg 3.3，adrf `defer_async`、worker queue/priority/periodic/retry/stalled rescue 实测 PASS）+ 现有 `server/resumable/` lease/CAS/recovery 范式。
>
> **三条硬前置（PoC 结论）：** ① worker 必须独立进程（用 `get_worker_connector()`/官方 management command，不能直接拿 DjangoConnector 跑 worker）；② SQLite 只能是非 durable dev fallback（真实 compose/helm 默认 Postgres，`docker-compose.yaml:37`/`settings.py:243`）；③ 先收口 `AppConfig.ready()` 启动副作用（否则 worker/migrate 进程会跑业务 reconcile 误杀在途任务）。
>
> **不变量：** 执行语义 **at-least-once**（不承诺 exactly-once）——DB claim 仅保证"同一轮领取只一个成功"，"慢≠死"误判 + 完成未标记即崩仍会重复执行；正确性靠 handler 幂等（checkpoint/deterministic key/upsert）+ 外部副作用 fencing/outbox。一个底座、多条逻辑队列（index/graph/crawl_ingest/page_index/maintenance）。聊天/RAG 流式问答**不进队列**（请求级，断开让用户重试）。i18n 默认中文。

## v1 Requirements

### durable 底座地基（DURABLE）

- [x] **DURABLE-01**: `DurableTaskService` 适配层隔离队列实现——Postgres 走 Procrastinate 3.8.1、SQLite/无 `DATABASE_URL` 退化 in-process 非 durable fallback；统一接口 `defer(task, payload, *, queue, priority, idempotency_key, run_at) / get / cancel / retry_stalled`；worker 用独立进程/worker connector（先 `listen_notify=False` polling）。后端选择点：`DATABASE_URL` 为 Postgres 且 `DURABLE_TASK_BACKEND=procrastinate` 用 Procrastinate，否则 in-process fallback。
- [x] **DURABLE-02**: 引入 `FRIDAY_PROCESS_ROLE=web|worker|scheduler|migrate|test` 进程角色门禁，收口 `repositories.apps` / `codegraph.apps` / `resumable.apps` 的 `AppConfig.ready()` 启动副作用——worker/migrate 进程不跑 web-only 的 reconcile/sweep/startup jobs，消除"只迁队列表时业务表不存在"类 warning 与误杀风险。
- [x] **DURABLE-03**: 内置 `retry_stalled_durable_jobs` 周期任务，经 `queueing_lock` 单例（leader）调 `get_stalled_jobs()` + `retry_job()` 扫 stalled 重投，替代现有"仅启动后补扫 3 次"与 `runapscheduler` 的本地 `flock`；多副本下只有一个 leader 执行周期 rescue 与单例 cron。
- [x] **DURABLE-04**: 新增 Postgres 专项 CI（GitHub Actions service container `postgres:17-alpine` + pytest `postgres_queue` marker），覆盖 defer / priority / retry-backoff / stalled rescue / 并发 worker 竞争 / SQLite fallback；与现有 SQLite 默认测试路径共存（marker 分层，默认 job 仍走 SQLite）。

### 迁移 index/graph + 收口 ResumableTask（MIGRATE）

- [x] **MIGRATE-01**: 代码库索引与知识图谱接入 durable queue——`repositories/views.py`、`tasks/index_trigger_tasks.py`、`resumable/handlers.py` 的 `run_in_background(wrap_resumable(...))` 改 `DurableTaskService.defer`（queue=index/graph，`idempotency_key=index:{repo_id}` / `graph:{repo_id}`）；`IndexHistory`/`GraphBuildHistory` 继续作进度/结果真相源；FileIndex/GraphFileIndex checkpoint 跳过保留。
- [x] **MIGRATE-02**: 一次性 migration command 把存量 PENDING/RUNNING `resumable_tasks`（index/graph）按 deterministic idempotency key 转 durable job（**不双跑**，旧行标 migrated/cancelled 记 legacy id）；`repositories.apps`/`codegraph.apps` 启动 reconcile 改为"仅确认无 durable job 接管时才把 RUNNING 标 FAILED"；`background_runner` 降级为仅 SQLite dev fallback / 少量非持久轻任务，生产 durable 任务不再三套并存。

### 幂等与外部副作用（IDEMP）

- [x] **IDEMP-01**: durable handler 幂等基线——index / graph / page_index 在 at-least-once 重复执行下经 checkpoint / deterministic key / upsert 结果一致；守护测试覆盖"同一任务重复投递/重复执行不产生重复数据或重复副作用"。
- [x] **IDEMP-02**: 有外部副作用的任务（飞书通知 / 自动建群、MR/PR 创建）上 fencing token 或 outbox，确保 at-least-once 重复执行不产生重复外部动作（不重复发通知 / 不重复建群 / 不重复开 PR）。

### 爬取+入库 durable 队列（CRAWL）

- [x] **CRAWL-01**: 链接爬取+入库改 durable 任务——后端支持入队 / 查询 / 开始 / 停止 / 重试 / 断点恢复；状态以 DB 为真相源，刷新页面与 `docker compose up -d`/Pod 重建后任务不丢、自动续跑；入库 at-least-once 幂等（复用现有 upsert/`IngestRun` 范式）。
- [x] **CRAWL-02**: 前端爬取任务队列面板（`BatchIngestPanel`）——贴链接入队、队列列表 + 实时状态、行内开始/停止/重试、刷新后从后端恢复（不再依赖组件内存 `batchId`/`ref`）；`feishu_not_configured` 引导深链保留；i18n 默认中文。
- [x] **PAGEIDX-01**: PageIndex / TOC / summary / tree 生成接入 durable queue（收口 `repositories/tree_views.py` 等裸 `background_runner` 路径），按 target hash 幂等（hash 未变跳过），重复执行安全。

### 部署硬化（DEPLOY）

- [x] **DEPLOY-01**: worker 优雅终止——捕获 SIGTERM 后停止领取新任务、跑完在途或释放/缩短租约让其他副本快速接管（非干等租约过期）；helm 为 worker 配 `terminationGracePeriodSeconds`（> 心跳间隔）。
- [x] **DEPLOY-02**: compose 与 helm 同构拆 web / worker / scheduler 三类 workload（同镜像不同 command + `FRIDAY_PROCESS_ROLE`）；scheduler 单例（leader）承载 cron + 周期 rescue；compose 升级（`up -d` 拉新镜像重建）迁移顺序与服务编排不破坏既有部署。
- [x] **DEPLOY-03**: KEDA Postgres scaler 按队列深度（`COUNT(status='todo')` 等）伸缩 worker（支持 cooldown 防抖、可按 queue 维度）+ PodDisruptionBudget + 多副本强制 Redis channel layer（未开启时 fail-closed 提示，对齐 `values.yaml` 既有约束）。

### runner k8s Job executor（RUNNER）

- [x] **RUNNER-01**: runner 抽象出 executor 接口（docker / k8s 两实现），与现有 server↔runner WebSocket 派发 + HTTP 回调契约解耦，docker executor 行为零回归。
- [x] **RUNNER-02**: k8s Job executor 实现——经 k8s API 起 Job/Pod 跑任务容器（去 `/var/run/docker.sock`），含 ServiceAccount/RBAC、日志流式回传、Pod 清理、失败重试；在 k0s/containerd 环境可用。

## v2 Requirements

### durable 进阶（DURABLEX）

- **DURABLEX-01**: Procrastinate `listen_notify=True` 低延迟唤醒（替代 polling），并处理 PgBouncer transaction pooling 下 NOTIFY 失效的降级。
- **DURABLEX-02**: 外部副作用从 fencing 演进为统一 outbox 模式。
- **DURABLEX-03**: workflow execution / RepoCodingTask 更深度接入 durable 恢复（当前仅做从持久化态重驱的恢复桥接）。

## Out of Scope

| Feature | Reason |
|---------|--------|
| 承诺 exactly-once 执行 | 有超时的分布式系统无法区分"慢"与"死"；统一走 at-least-once + 幂等/fencing（业界一致，River/Oban/Procrastinate 同语义） |
| 把所有任务塞进单一队列 | 长任务（索引）会堵短任务（爬取/页面生成）；按 kind 分多条逻辑队列，各自并发与伸缩 |
| 聊天 / RAG 流式问答进 durable 队列 | 请求级、流式、用户在等；半句回答无续跑意义，Pod 死即中断让用户重试，最多做软可观测/限流 |
| workflow execution / RepoCodingTask 整体塞队列 | 已有自有引擎与状态机（`WorkflowExecution`/`NodeExecution`、wave 调度）；只做"从持久化态重驱"的恢复桥接，不扁平成普通 job |
| 引入 Celery / Temporal / Kafka 等重运维组件 | 违背"开箱即用、自托管"核心价值；已有 Postgres，Procrastinate（Postgres-only）+ 适配层即足够 |
| SQLite 下的 durable 保证 | SQLite 仅本地 dev/pytest，明确为非 durable in-process fallback，不承诺重启恢复；真实部署默认 Postgres |
| Procrastinate `listen_notify=True` 低延迟唤醒 | 本里程碑先用 polling 稳态落地，NOTIFY 优化留 v2（DURABLEX-01） |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| DURABLE-01 | Phase 60 | Complete |
| DURABLE-02 | Phase 60 | Complete |
| DURABLE-03 | Phase 60 | Complete |
| DURABLE-04 | Phase 60 | Complete |
| MIGRATE-01 | Phase 61 | Complete |
| MIGRATE-02 | Phase 61 | Complete |
| IDEMP-01 | Phase 61 | Complete |
| CRAWL-01 | Phase 62 | Complete |
| CRAWL-02 | Phase 62 | Complete |
| PAGEIDX-01 | Phase 62 | Complete |
| DEPLOY-01 | Phase 63 | Complete |
| DEPLOY-02 | Phase 63 | Complete |
| DEPLOY-03 | Phase 63 | Complete |
| IDEMP-02 | Phase 63 | Complete |
| RUNNER-01 | Phase 64 | Complete |
| RUNNER-02 | Phase 64 | Complete |

**Coverage:**

- v1 requirements: 16 total
- Mapped to phases: 16
- Unmapped: 0 ✓

---
*Requirements defined: 2026-06-20 for milestone v0.12.0 — 前置 PoC PASS，详见会话调研结论*
