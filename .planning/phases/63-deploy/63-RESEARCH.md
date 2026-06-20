# Phase 63: 部署硬化 + 外部副作用 fencing - Research

**Researched:** 2026-06-21
**Domain:** k8s/compose 多副本部署编排（Procrastinate worker 优雅终止 + workload 拆分 + KEDA/PDB/Redis 强约束）+ at-least-once 外部副作用 fencing
**Confidence:** HIGH（Procrastinate shutdown/periodic 语义、KEDA postgres scaler、既有代码坐标均已核实）

## Summary

Phase 63 把 v0.12.0 的 durable 底座（Phase 60–62 已交付：`DurableTaskService` 适配层、`run_worker` 命令、`@app.periodic` rescue、`FRIDAY_PROCESS_ROLE` 角色门禁）落到**生产多副本部署**。四条交付互相独立：

1. **DEPLOY-01 优雅终止**——核实结论：**无需写任何信号处理代码**。Procrastinate `run_worker_async` 默认 `install_signal_handlers=True`，收到 SIGTERM/SIGINT 即触发内置 graceful shutdown（停止领取新 job、等在途跑完）。本阶段只需：① 给 `run_worker` 暴露并传入 `shutdown_graceful_timeout`；② helm/compose 配 `terminationGracePeriodSeconds` > graceful timeout > heartbeat(10s)。崩溃/SIGKILL 的"快速接管"由既有 heartbeat-stalled 检测（30s）+ 周期 rescue 兜底，不靠"释放租约"原语（Procrastinate 无此原语）。

2. **DEPLOY-02 workload 拆分**——同镜像 + 不同 command + `FRIDAY_PROCESS_ROLE` 拆 web/worker/scheduler。**关键澄清**：`runapscheduler`（10 个 apscheduler cron + 1 个 one-shot）**当前完全没有在任何 compose/helm/entrypoint 中被拉起**（仅测试引用），是 Phase 61 deferred 的真实迁移项——需新建 scheduler workload（replicas=1）跑它。durable 周期 rescue（`retry_stalled_durable_jobs`）则由 **worker 进程的 periodic deferrer 自动 defer + DB 去重**（`defer_periodic_job` 保证多副本只 defer 一份），**不依赖 scheduler workload**——这是与 CONTEXT 措辞的重要校正。

3. **DEPLOY-03 KEDA/PDB/Redis**——KEDA postgresql scaler 按 `procrastinate_jobs` 表 `COUNT(*) WHERE status='todo'` 伸缩 worker（可按 `queue_name` 维度）；PDB 给 web/worker；多副本无 Redis channel layer → 双层 fail-closed（helm `fail` 模板期 + settings `ImproperlyConfigured` 运行期，复用既有 `IS_PRODUCTION` 校验范式）。KEDA/PDB 全部 values-gated 默认 off。

4. **IDEMP-02 fencing**——核实结论：CONTEXT 点名的"飞书通知/建群、MR/PR 创建"**目前都不在 durable 队列里**（在 workflow 引擎 / callback 重驱路径）；唯一在 durable 任务内的外部副作用是 `run_crawl_ingest`→`ingest_from_urls`，其 MR diff 已有 `aarchive_exists` fencing、文档/WorkItem 已 upsert 幂等。fencing 缺口在 **callback 重驱的 MR/PR 创建**（`coding.py:_create_mr_for_repo` 无 existing-MR 检查）与 **CreateGroupChatNode 建群**（未先查 `WorkItem.feishu_chat_id`）。reuse-first：建群复用 Phase 59 writeback 字段作 fence；MR 复用"查在途 MR / branch 已有 PR"检查；最小新建。

**Primary recommendation:** 优雅终止纯配置（零信号代码）+ 复用 `_helpers.tpl`/configmap/secret 镜像出 worker/scheduler-deployment（scheduler 强制 replicas=1，跑 `runapscheduler`）+ KEDA/PDB values-gated 默认 off + 多副本无 Redis 双层 fail-closed + fencing 复用既有写回字段（建群查 `feishu_chat_id`、MR 查 existing）。

## User Constraints (from CONTEXT.md)

### Locked Decisions

**worker 优雅终止（DEPLOY-01）**
- worker 进程（Phase 60 `run_worker` 命令）捕获 SIGTERM：停止领取新 job（Procrastinate worker 自带 graceful stop）、跑完在途或释放/缩短租约（让其他副本快速接管，非干等过期）。
- helm worker Deployment 配 `terminationGracePeriodSeconds` > 心跳/lease 间隔（具体值由 research 给默认）。
- 复用 Procrastinate worker 既有 graceful shutdown 信号处理；不重造信号循环。

**compose/helm 拆 workload（DEPLOY-02）**
- 同镜像 + 不同 command + `FRIDAY_PROCESS_ROLE`（Phase 60 已建角色门禁）拆三类 workload：`web`（role=web，ASGI/daphne，现有 server-deployment）、`worker`（role=worker，`manage.py run_worker`，可多副本）、`scheduler`（role=scheduler，单例 leader，承载 cron + 周期 `retry_stalled_durable_jobs`）。
- scheduler 单例：承载 Phase 61 deferred 的 runapscheduler 9 cron job 迁移 + Phase 60 周期 rescue（leader 经 queueing_lock，replicas=1）。
- compose（root `docker-compose.yaml` + `docker-compose.build.yaml`）同构拆 worker/scheduler service；`up -d` 拉新镜像重建迁移顺序不破坏既有部署（migrate job 先行、role 门禁防误跑）。
- helm（`deploy/helm/friday/`）：现有 server-deployment 保留为 web；新增 worker-deployment + scheduler-deployment（复用 _helpers.tpl + configmap/secret）。

**KEDA/PDB/Redis 强约束（DEPLOY-03）**
- KEDA `ScaledObject`（postgresql scaler）按队列深度 `COUNT(status='todo')` 伸缩 worker：cooldownPeriod 防抖、可按 queue 维度（trigger query 参数化）；minReplicaCount/maxReplicaCount 由 values 配置。
- PodDisruptionBudget 给 worker/web（minAvailable 或 maxUnavailable）。
- 多副本强制 Redis channel layer：replicas>1 时未配 Redis channel layer → fail-closed 提示（对齐 `values.yaml` 既有约束 + settings 校验）。
- KEDA/PDB 经 values flag 可选启用（默认行为不破坏单副本部署）。

**外部副作用 fencing/outbox（IDEMP-02）**
- 给有外部副作用的 durable 任务（飞书通知/自动建群、MR/PR 创建）上 fencing token 或 outbox，保证 at-least-once 重复执行不重复外部动作。
- 倾向 **fencing/dedup 记录**（轻量）：在执行外部动作前检查/写入幂等标记（deterministic key），已执行则跳过；对建群/PR 复用既有写回字段（如 `WorkItem.feishu_chat_id` Phase 59 writeback、MR/PR archive `aarchive_exists` Phase 62 同款）作 fencing。
- outbox 仅在 fencing 不足以覆盖时引入（research 评估）。

### Claude's Discretion
- `terminationGracePeriodSeconds`、KEDA cooldown/min/max、PDB 阈值的默认值。
- fencing 实现形态（既有写回字段复用 vs 新建 dedup 表/列 vs outbox 表）——倾向 reuse-first，最小新建。
- compose scheduler service 是否默认启用（vs profile 可选）。
- helm KEDA/PDB 模板是否 values-gated（默认 off 保兼容）。

### Deferred Ideas (OUT OF SCOPE)
- runner k8s Job executor → Phase 64。
- `listen_notify=True` 低延迟唤醒 → v2 DURABLEX-01。
- exactly-once → 非目标。

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DEPLOY-01 | worker 优雅终止（SIGTERM 停领取/跑完在途/快速接管 + terminationGracePeriodSeconds） | Procrastinate 内置 graceful shutdown（`install_signal_handlers=True` 默认）+ `shutdown_graceful_timeout` 参数；heartbeat(10s)/stalled(30s) 兜底接管 — 见 Architecture Patterns §优雅终止 |
| DEPLOY-02 | compose/helm 拆 web/worker/scheduler workload；scheduler 单例承载 cron + 周期 rescue；升级不破坏既有部署 | 既有 `FRIDAY_PROCESS_ROLE` 门禁（`roles.py`）+ `run_worker` 命令 + 未接线的 `runapscheduler`；helm `_helpers.tpl`/configmap/secret 可复用 — 见 §workload 拆分 + §runapscheduler 迁移 |
| DEPLOY-03 | KEDA postgres scaler（queue depth）+ PDB + 多副本强制 Redis channel layer fail-closed | KEDA postgresql scaler 已验证语法；`procrastinate_jobs.status='todo'` 队列深度；settings `IS_PRODUCTION` fail-closed 范式可扩展 — 见 §KEDA/PDB/Redis |
| IDEMP-02 | 飞书通知/建群、MR/PR 创建 fencing，at-least-once 不重复外部动作 | 外部副作用触点清单 + 既有 fence（`aarchive_exists`/`feishu_chat_id` writeback）vs 缺口（MR 无 existing 检查、建群未查 chat_id）— 见 §Fencing 触点映射 |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| worker 优雅终止 | Worker 进程（Procrastinate） | k8s/compose 编排 | 信号处理是 Procrastinate 内置；编排层只配 grace period |
| cron 调度（apscheduler 10+1 jobs） | Scheduler workload（单例） | DB（DjangoJobStore） | 必须单实例，跨 Pod flock 失效 → 改 replicas=1 workload |
| durable 周期 rescue | Worker 进程（periodic deferrer） | DB（`procrastinate_periodic_defers` 去重） | Procrastinate periodic 由 worker defer，DB 去重天然单例，**不在 scheduler** |
| 队列深度弹性伸缩 | KEDA（k8s 控制面） | Postgres（`procrastinate_jobs`） | KEDA 查 DB 队列深度驱动 HPA |
| WS 跨副本广播 | Redis channel layer | settings/helm fail-closed | 多副本必须共享 channel layer，否则 WS 丢消息 |
| 外部副作用 fencing | 任务/节点 handler | DB（写回字段/dedup） | at-least-once 正确性靠 handler 幂等，DB 作 fence 真相源 |

## Standard Stack

### Core（已在仓库，本阶段消费）
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| procrastinate[django] | 3.8.1 (`<3.9`) | durable 队列 + worker + periodic + graceful shutdown | [VERIFIED: `server/pyproject.toml` + 60-01-SUMMARY] PoC PASS，已锁定 |
| django-apscheduler | >=0.7.0 | apscheduler cron jobs（DjangoJobStore） | [CITED: CLAUDE.md STACK] 既有 cron 载体，本阶段迁到 scheduler workload |
| channels[daphne] / channels_redis | >=4.3.2 | WS channel layer（多副本 → Redis） | [VERIFIED: `settings.py:178-192`] 已有 Redis/InMemory 分支 |

### Supporting（部署侧，非 Python 依赖）
| Tool | Version | Purpose | When to Use |
|------|---------|---------|-------------|
| KEDA | 2.x（CRD `keda.sh/v1alpha1`） | postgresql scaler ScaledObject 伸缩 worker | values-gated，仅 KEDA 已装的集群启用 |
| PodDisruptionBudget | `policy/v1` | 滚动/驱逐时保最小可用副本 | values-gated，多副本时启用 |
| Helm | v3 | 模板渲染（`helm template`/`helm lint` 验证） | 已用（`deploy/helm/friday/`） |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| 新建 worker/scheduler Deployment | 把 worker 塞进 server Deployment 多容器 | 违背"可独立伸缩"——worker 要 KEDA 伸缩、web 不要；拆 Deployment 才能各自 replicas/HPA |
| scheduler 跑 `runapscheduler`（apscheduler） | 把 cron 全迁成 procrastinate `@app.periodic` | 大改 + 偏离最小 diff；apscheduler cron 已稳定，本阶段只"挪进单例 workload" |
| 轻量 fencing（写回字段/dedup） | outbox 表（DURABLEX-02） | outbox 是 v2 显式范围；当前触点用既有写回字段即可 fence，不引入新表 |
| KEDA postgres scaler | Prometheus scaler（导出队列深度 metric） | 需额外 metrics exporter；postgres scaler 直查 DB 零额外组件，对齐"开箱即用" |

**Installation（部署侧，非代码）:**
```bash
# KEDA（仅当集群启用 keda values flag；用户集群侧自备，chart 不内置 KEDA operator）
helm repo add kedacore https://kedacore.github.io/charts && helm install keda kedacore/keda -n keda --create-namespace
```

**Version verification:**
```bash
# 已核实：server/pyproject.toml 锁 procrastinate[django]>=3.8.1,<3.9（60-01-SUMMARY 实测 import 3.8.1）
# KEDA CRD apiVersion keda.sh/v1alpha1（kind: ScaledObject / TriggerAuthentication）— keda.sh 2.x 文档核实
```

## Package Legitimacy Audit

> 本阶段**不新增任何 Python/JS 包**——纯部署编排（helm/compose YAML）+ 既有 procrastinate/apscheduler/channels 消费 + 少量 Python fencing 逻辑（复用既有 model 字段/service）。KEDA 为集群侧 operator（用户自备，chart 不打包）。

| Package | Registry | Disposition |
|---------|----------|-------------|
| （无新增） | — | N/A — 复用既有锁定依赖（procrastinate 3.8.1 / django-apscheduler / channels_redis） |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
                          ┌──────────────────────────────────────────┐
                          │           Postgres (durable 真相源)         │
                          │  procrastinate_jobs(status,queue_name)     │
                          │  django_apscheduler_djangojob              │
                          │  WorkItem.feishu_chat_id / CodeChangeArchive│
                          └────▲────────▲───────────▲────────▲─────────┘
                               │ defer  │ consume    │ periodic│ fence
       ┌───────────────┐       │        │            │ defer   │ check
HTTP → │ web workload  │───────┘        │            │(DB dedup)│
 / WS  │ role=web      │                │            │          │
       │ gunicorn ASGI │◄──Redis────┐   │            │          │
       └───────────────┘ channel    │   │            │          │
                          layer      │   │            │          │
       ┌───────────────┐ (多副本必需) │   │            │          │
       │ worker workload│────consume─┘───┘────────────┘          │
       │ role=worker    │ run_worker (graceful SIGTERM)          │
       │ N replicas     │ periodic deferrer → retry_stalled      │
       └──────▲────────┘                                          │
              │ scale by COUNT(status='todo')                     │
       ┌──────┴────────┐                                          │
       │ KEDA ScaledObj │ (values-gated, default off)             │
       └───────────────┘                                          │
       ┌───────────────┐                                          │
       │scheduler workld│ role=scheduler, replicas=1 (单例 leader)│
       │ runapscheduler │ apscheduler cron (10 recurring + 1 1shot)│
       └───────────────┘                                          │
       ┌───────────────┐                                          │
       │ runner / task  │ MR/PR 创建 + 建群 (callback 重驱) ───────┘ fencing
       │ (workflow 引擎) │ 需补 existing-MR / chat_id 检查
       └───────────────┘
       migrate Job (helm hook pre-upgrade / compose entrypoint) — 先于所有 workload
```

### Pattern 1: 优雅终止（DEPLOY-01）— 零信号代码，纯配置

**What:** Procrastinate `run_worker_async` 默认 `install_signal_handlers=True`，收到 SIGTERM/SIGINT 即停止领取新 job、等在途 job 跑完；`shutdown_graceful_timeout` 控制最大等待秒数（None=无限等到完成，超时则 abort）。
**When to use:** worker workload（k8s 滚动更新 / 缩容 / 驱逐时 Pod 收 SIGTERM）。
**核实来源:** [CITED: procrastinate.readthedocs.io/en/stable/howto/advanced/shutdown.html + reference.html `run_worker_async` 签名]

关键参数（已核实默认值）：
- `install_signal_handlers: bool = True` — 自带 SIGTERM/SIGINT graceful 处理（**当前 `run_worker.py:73` 未显式传 → 已是 True，已优雅**）。
- `shutdown_graceful_timeout: float | None = None` — 等在途完成的上限；超时 abort 未完成 job。
- `update_heartbeat_interval: float = 10` — worker 心跳间隔。
- `stalled_worker_timeout: float = 30` — 多久无心跳判 worker stalled（启动时 prune）。

**现状（`server/durable/management/commands/run_worker.py:58-73`）:** 已 `run_worker_async(queues=queues, listen_notify=False)`，`install_signal_handlers` 默认 True → **SIGTERM 已优雅**。需 build：暴露 `--graceful-timeout` arg 传入 `shutdown_graceful_timeout`（让运维可控）。

```python
# server/durable/management/commands/run_worker.py — 建：加 arg + 传参（其余零改）
parser.add_argument("--graceful-timeout", type=float, default=None,
                    help="收到 SIGTERM 后等在途 job 完成的最大秒数；超时 abort（默认无限等到完成）")
# ...
await worker_app.run_worker_async(
    queues=queues, listen_notify=False,
    shutdown_graceful_timeout=options.get("graceful_timeout"),
)
```

**helm worker Deployment（build）:** `terminationGracePeriodSeconds` 必须 > `shutdown_graceful_timeout` > heartbeat(10s)/stalled(30s)。推荐默认：
- `terminationGracePeriodSeconds: 120`（values 可调；长任务可加大）。
- `shutdown_graceful_timeout` 默认 None（让短 job 跑完）或一个略小于 grace period 的值（如 110）。
- 不需要 `preStop` hook（Procrastinate 自处理 SIGTERM）。

**"快速接管"语义校正（重要）:** Procrastinate **没有"主动释放/缩短租约"原语**。"快速接管"靠：① graceful 关停时在途 job 正常跑完（无孤儿）；② 若 SIGKILL（超 grace period）→ worker 停止心跳，`get_stalled_jobs(seconds_since_heartbeat=30)` 30s 后判 stalled，由周期 rescue 重投。当前 rescue cron 是 `*/10 * * * *`（10 分钟，`tasks.py:107`）——**若要更快接管可调成 `*/2` 或更短**（Claude's Discretion）；但这违反不了 at-least-once 语义，仅影响接管延迟。CONTEXT 的"释放/缩短租约"应理解为"靠 heartbeat-stalled 检测快速判定 + rescue 重投"，不是新原语。

### Pattern 2: workload 拆分（DEPLOY-02）— 同镜像 + command + role

**What:** 同一 server 镜像，三类 workload 用不同 command + `FRIDAY_PROCESS_ROLE`：
| Role | Command | Replicas | 职责 |
|------|---------|----------|------|
| `web` | `gunicorn friday.asgi:application ...`（现 `server-deployment.yaml:43-58`） | N（KEDA/HPA 可选） | ASGI/WS，跑 web-only 启动副作用 |
| `worker` | `python manage.py run_worker` | N（KEDA 伸缩） | 消费 durable 队列 + periodic deferrer |
| `scheduler` | `python manage.py runapscheduler` | **1（强制）** | apscheduler cron（10+1 jobs） |

**关键：role 门禁已就位。** `server/durable/roles.py` 的 `current_role()` 读 `FRIDAY_PROCESS_ROLE`（默认 web）；`should_run_startup_side_effects(allowed={"web"})` 让 worker/scheduler/migrate 进程**不跑 web-only 的 reconcile/sweep**（Phase 60 DURABLE-02 已收口 `repositories.apps`/`codegraph.apps`/`resumable.apps`）。`durable/apps.py:38` 已允许 web/worker/scheduler 注册 durable 任务对象。

**helm（build）:** 新增 `worker-deployment.yaml` + `scheduler-deployment.yaml`，镜像 `server-deployment.yaml` 结构，复用 `_helpers.tpl`（labels/selectorLabels/fullname）+ `envFrom configmap/secret`，仅改：
- `command`（worker: `["python","manage.py","run_worker"]`；scheduler: `["python","manage.py","runapscheduler"]`）。
- env 加 `FRIDAY_PROCESS_ROLE`（worker/scheduler）。
- worker：`replicas: {{ .Values.worker.replicaCount }}` + `terminationGracePeriodSeconds`。
- scheduler：`replicas: 1` **硬编码或 `strategy: Recreate`**（防滚动期两份并存重复跑 cron），不暴露 replicaCount 给用户调。
- worker/scheduler 无 HTTP 端口、无 liveness httpGet（用 exec/无探针；或 worker 用 `pgrep` exec 探针）。
- initContainer wait-for-db 复用 server-deployment 范式（`server-deployment.yaml:20-36`）。

**compose（build）:** root `docker-compose.yaml` 加 `worker` + `scheduler` service：
```yaml
worker:
  image: ${...}/server:${...}          # 同 server 镜像
  command: ["python", "manage.py", "run_worker"]
  environment:
    - FRIDAY_PROCESS_ROLE=worker
    - DATABASE_URL=${DATABASE_URL:-postgres://...}   # 与 server 同
    - DURABLE_TASK_BACKEND=${DURABLE_TASK_BACKEND:-auto}
    # ... 复用 server 的 DB/Redis/Qdrant/加密 env
  depends_on: { postgres: {condition: service_healthy}, redis: {condition: service_healthy} }
  restart: unless-stopped
  stop_grace_period: 120s             # compose 等价 terminationGracePeriodSeconds
scheduler:
  image: ${...}/server:${...}
  command: ["python", "manage.py", "runapscheduler"]
  environment: [ FRIDAY_PROCESS_ROLE=scheduler, ... ]
  deploy: { replicas: 1 }             # 单例
  depends_on: { postgres: {condition: service_healthy} }
  restart: unless-stopped
```
- `docker-compose.build.yaml` 同步加 worker/scheduler 的 `build`/`image: friday-server:local`（镜像同 server，无需新 build context；可只 override image）。

### Pattern 3: runapscheduler 迁移（DEPLOY-02 子项 — Phase 61 deferred）

**核实结论（重要）:** `runapscheduler` **当前没有被任何 entrypoint/compose/helm 拉起**。`server/entrypoint.sh` 只起 gunicorn；helm 只有 server/web/runner/migrate；compose 无 scheduler。grep `runapscheduler` 在部署侧零命中（仅测试引用）。所以这些 cron **当前在生产里根本没跑**——本阶段新建 scheduler workload 是首次让它们运行。

`server/agents/management/commands/runapscheduler.py` 注册的 jobs（10 recurring + 1 one-shot）：
1. `check_timeout_reminders`（每小时）
2. `cleanup_expired_sessions`（每日 03:00）
3. `cleanup_orchestration_checkpoints`（每日 03:30）
4. `cleanup_coding_sessions`（每日 04:00）
5. `delete_old_job_executions`（每周一 00:00）
6. `refresh_repo_caches`（每日 02:00）
7. `prune_cache_volumes`（每日 05:00）
8. `poll_repository_updates`（间隔 `SYNC_INTERVAL_SECONDS`）
9. `calculate_behind_commits`（间隔 `SYNC_INTERVAL_SECONDS`）
10. `cleanup_stale_branch_indexes`（每小时）
11. `backfill_chunk_edges`（启动一次性 DateTrigger）

**单例机制:** `runapscheduler.py:260-287` 已用 `fcntl.flock`（`/tmp/friday-scheduler.lock`）做单实例门禁——但 **flock 仅单机/单容器有效，跨 Pod 失效**（STATE.md 约束已明确）。迁到 scheduler workload 后真正的单例保证 = **k8s replicas=1 + `strategy: Recreate`**（或 compose `replicas: 1`）。flock 保留作"同一节点误启两份"的兜底无害。

**不需要把 cron 改成 procrastinate periodic**——最小 diff 是"把现有 `runapscheduler` 命令挪进单例 workload"。`DjangoJobStore` 跨进程共享 job 状态本就为此设计；replicas=1 即满足契约（`runapscheduler.py:241` docstring "scheduler 必须单实例运行"）。

**durable 周期 rescue 不归 scheduler。** `retry_stalled_durable_jobs`（`tasks.py:107` `@app.periodic`）由 **worker 进程的 periodic deferrer 自动 defer**（`JobManager.defer_periodic_job` "ensuring no other worker will defer a job for the same timestamp" — DB 去重，[VERIFIED: procrastinate reference.html])。只要 ≥1 worker 在跑，rescue 就持续发生并被某个 worker 执行。**scheduler workload 不跑 worker，故不承载 durable rescue**。CONTEXT 把 rescue 归 scheduler 是措辞偏差——research 校正：rescue 在 worker，cron 在 scheduler。

### Pattern 4: KEDA / PDB / Redis 强约束（DEPLOY-03）

**KEDA postgresql scaler（build，values-gated）:** [VERIFIED: keda.sh/docs scalers/postgresql]
```yaml
# deploy/helm/friday/templates/worker-scaledobject.yaml — {{ if .Values.worker.keda.enabled }}
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: {{ include "friday.fullname" . }}-worker
spec:
  scaleTargetRef:
    name: {{ include "friday.fullname" . }}-worker
  pollingInterval: {{ .Values.worker.keda.pollingInterval | default 30 }}   # 默认 30s
  cooldownPeriod: {{ .Values.worker.keda.cooldownPeriod | default 300 }}    # 默认 300s 防抖
  minReplicaCount: {{ .Values.worker.keda.minReplicaCount | default 1 }}    # 不 scale-to-zero（in-flight/leader）
  maxReplicaCount: {{ .Values.worker.keda.maxReplicaCount | default 5 }}
  triggers:
    - type: postgresql
      metadata:
        # 队列深度：todo 数 / 每副本可消化量；COALESCE 防 null
        query: >-
          SELECT COALESCE(ceil(COUNT(*)::decimal / {{ .Values.worker.keda.jobsPerReplica | default 10 }}), 0)
          FROM procrastinate_jobs WHERE status = 'todo'
        targetQueryValue: "1"
      authenticationRef:
        name: {{ include "friday.fullname" . }}-keda-pg-auth     # TriggerAuthentication 引 secret，绝不硬编码
```
- **表/列已核实:** Procrastinate schema 表 `procrastinate_jobs`，列 `status`（enum: `todo`/`doing`/`succeeded`/`failed`/`cancelled`/`aborting`/`aborted`）、`queue_name`。队列深度 = `status='todo'`。
- **按 queue 维度（可选）:** trigger query 加 `AND queue_name = 'index'` 等，或多 trigger 各 queue；values 参数化。CONTEXT 已锁"可按 queue 维度"——给 values 留 `query` override 或 per-queue 列表。
- **凭证:** 用 `TriggerAuthentication` + secretTargetRef（复用 chart secret 的 `DATABASE_URL` 或单独 PG 连接串），**绝不在 ScaledObject metadata 硬编码密码**（[CITED: keda discussion #3612]）。
- **minReplicaCount≥1**：worker 不 scale-to-zero（要持续跑 periodic deferrer 驱动 rescue；scale-to-zero 会让 rescue 停摆）。

**PodDisruptionBudget（build，values-gated）:**
```yaml
# deploy/helm/friday/templates/worker-pdb.yaml — {{ if .Values.worker.pdb.enabled }}
apiVersion: policy/v1
kind: PodDisruptionBudget
spec:
  {{- if .Values.worker.pdb.minAvailable }}
  minAvailable: {{ .Values.worker.pdb.minAvailable }}
  {{- else }}
  maxUnavailable: {{ .Values.worker.pdb.maxUnavailable | default 1 }}
  {{- end }}
  selector:
    matchLabels: { ...selectorLabels, component: worker }
```
- web 同款 PDB（values-gated）。scheduler **不配 PDB**（单例，PDB 与 replicas=1 冲突会阻塞驱逐）。
- 默认值：worker `maxUnavailable: 1`；web `minAvailable: 1`（多副本时）。

**多副本无 Redis → 双层 fail-closed（build）:**
- **settings 运行期（复用 `IS_PRODUCTION` 范式 `settings.py:75-83`）:** 新增校验——当"声明多副本"且 `USE_REDIS_CHANNEL_LAYER=False` → `raise ImproperlyConfigured`。多副本信号需一个 env（settings 不知道 k8s replicas）：建议新增 `FRIDAY_EXPECT_MULTI_REPLICA`（bool），helm 在 `server.replicaCount>1` 或 `worker.enabled` 时注入 true；亦可顺带校验 `GUNICORN_WORKERS>1` 时也要 Redis（单进程多 worker 同样需共享 channel layer）。
```python
# settings.py（建，紧跟 CHANNEL_LAYERS 定义后或 IS_PRODUCTION 块内）
_expect_multi = env.bool("FRIDAY_EXPECT_MULTI_REPLICA", default=False) or env.int("GUNICORN_WORKERS", default=1) > 1
if _expect_multi and not USE_REDIS_CHANNEL_LAYER:
    raise ImproperlyConfigured(
        "多副本 / 多 worker 部署必须启用 Redis channel layer（USE_REDIS_CHANNEL_LAYER=true + REDIS_URL）；"
        "否则 WebSocket 推送跨副本丢失。单副本单 worker 才可用内存 channel layer。"
    )
```
- **helm 模板期（`fail`）:** 在 `_helpers.tpl` 加校验 helper 或 NOTES 前置 `fail`：
```
{{- if and (gt (int .Values.server.replicaCount) 1) (not .Values.redis.enabled) (not .Values.externalRedis.url) }}
{{- fail "server.replicaCount>1 需启用 redis.enabled 或配置 externalRedis.url（多副本 channel layer 强约束）" }}
{{- end }}
```
- 对齐 `values.yaml:116-138` 既有注释约束（"redis.enabled=false 且 externalRedis.url 为空时退回内存 channel layer，此时 server 必须保持单 worker 单副本"）——本阶段把"注释约束"升级为"强制 fail-closed"。

### Pattern 5: Fencing 触点映射（IDEMP-02）

**核实结论:** durable 队列里**唯一**的外部副作用任务是 `run_crawl_ingest`（`tasks_impl.py:63`）→ `ingest_from_urls`，其 MR diff 已有 `aarchive_exists` fence（`ingest_orchestrator.py:332`），WorkItem/Document 已 upsert/content_hash 幂等（IDEMP-01 已交付）。CONTEXT 点名的"飞书通知/建群、MR/PR 创建"**不在 durable 队列**，而在 **workflow 引擎 + callback 重驱**路径。

| 触点 | 位置 | 运行上下文 | 既有 fence | 缺口 → 建议（reuse-first） |
|------|------|-----------|-----------|----------------------------|
| MR diff 归档 | `ingest_orchestrator.py:332` `aarchive_exists` | **durable** `run_crawl_ingest` | ✅ `aarchive_exists(source_kind, source_id)` | 无缺口（已 fence） |
| WorkItem/Document upsert | `ingest_from_urls` 内核 | **durable** `run_crawl_ingest` | ✅ 三元组 upsert / content_hash（IDEMP-01） | 无缺口 |
| **MR/PR 创建** | `coding.py:1805 _create_mr_for_repo` → `client.create_merge_request` | workflow 引擎 / callback 重驱（**非 durable job**） | ❌ 无 existing-MR 检查 | **建**：创建前查"该 source_branch→target_branch 是否已有 open MR/PR"，有则复用其 URL；GitLab/GitHub client 加 `find_existing_mr`。最小 fence，不新建表 |
| **飞书建群** | `feishu_chat.py CreateGroupChatNode.execute` → `FeishuIMService.create_chat` | workflow 节点（**非 durable job**） | ⚠️ 有 writeback 但**未先查** | **建**：建群前查 `WorkItem.feishu_chat_id`（Phase 59 字段），已有则跳过创建、直接复用。复用既有写回字段作 fence |
| **飞书通知/卡片** | `feishu_im.py send_card/send_message` / bot service | 请求级（chat/bot）+ 节点 | — 大多请求级（断开重试，REQUIREMENTS 已豁免） | 若进入 durable 重投路径才需 dedup key；当前请求级无需 fence（与"聊天/RAG 不进队列"一致） |

**关键判断（"哪些外部动作在 durable 任务内"）:**
- **在 durable 内**：仅 `run_crawl_ingest` 的入库副作用（MR 归档/文档/WorkItem）——**已全部 fenced**。
- **不在 durable 内**：MR/PR 创建、建群、飞书通知——它们由 workflow 引擎 / server↔runner callback 驱动。这些路径的"重复"风险来自 **callback 重投 / 节点重入**（Phase 43/44 callback resume），不是 durable at-least-once。

**最小 robust 方案（per 触点）:**
1. **建群** → 复用 `WorkItem.feishu_chat_id`（Phase 59 `awriteback_feishu_chat_id`）：`CreateGroupChatNode` 执行前先查 WorkItem 是否已有 `feishu_chat_id`，有则返回既有 chat_id 跳过 `create_chat`。**零新表/列**。
2. **MR/PR** → 复用平台天然幂等 + 显式 existing 检查：`_create_mr_for_repo` 前调平台 `list_merge_requests(source_branch, target_branch, state=opened)`/GitHub `pulls?head=...`，命中则复用。GitLab 重复创建本会报"Another open merge request already exists"——把它转成"复用既有"而非报错。**零新表**。
3. **outbox 不引入**——三触点都能用既有写回字段/平台查询 fence；outbox 是 v2 DURABLEX-02 显式范围（REQUIREMENTS Out of Scope）。

**provenance 说明:** 上述 fencing 是 reuse-first 推荐，需 plan/discuss 确认 `WorkItem.feishu_chat_id` 在建群节点入口可定位（Phase 59 writeback 仅在节点出口写）——若节点入口无 WorkItem 锚（project_key/work_item_id 为空），建群本就 fail-soft，fence 退化为 no-op（不阻断）。

### Anti-Patterns to Avoid
- **scheduler 多副本**：两份 `runapscheduler` 并存 → cron 重复跑（backfill OOM、重复通知）。必须 replicas=1 + `strategy: Recreate`（不是 RollingUpdate，避免新旧 Pod 重叠）。
- **worker scale-to-zero**：minReplicaCount=0 会让 periodic deferrer 停摆 → durable rescue 不再触发 → stalled job 永挂。worker 至少 1 副本。
- **KEDA 硬编码 DB 密码**：必须 TriggerAuthentication（[CITED: keda discussion #3612]）。
- **compose 升级先起 worker 再 migrate**：worker import durable 任务对象需 procrastinate 表已建；migrate 必须先行（compose `depends_on` + entrypoint migrate / helm pre-upgrade hook）。
- **把 durable rescue 塞进 scheduler**：scheduler 不跑 worker，塞了也没 worker 执行 defer 出来的 rescue job。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| worker SIGTERM 优雅停 | 自写 signal handler + asyncio 取消循环 | Procrastinate `install_signal_handlers=True`（默认）+ `shutdown_graceful_timeout` | 官方内置，自写易漏 abort/drain 边界（CONTEXT 已锁"不重造信号循环"） |
| 周期 rescue 单例选主 | 自写 leader election / flock 跨 Pod | `@app.periodic` + `defer_periodic_job` DB 去重（已交付 Phase 60） | DB 去重天然多副本单例 |
| cron 单例 | 自写分布式锁 | k8s replicas=1 + Recreate（apscheduler DjangoJobStore） | 编排层保证比应用层锁简单可靠 |
| 队列深度伸缩 | 自写 metrics exporter + HPA | KEDA postgresql scaler 直查 `procrastinate_jobs` | 零额外组件，对齐开箱即用 |
| MR 重复检测 | 自建 dedup 表 | 平台 list MR/PR by branch + 既有 `aarchive_exists` 范式 | 平台是真相源；新表是 v2 outbox 范围 |

**Key insight:** 本阶段几乎全是"配置/编排 + 复用既有原语"，真正的新代码只有：①`run_worker` 加 graceful-timeout arg；②settings fail-closed 校验；③两处 fencing 检查（建群查 chat_id、MR 查 existing）。其余是 helm/compose YAML。

## Common Pitfalls

### Pitfall 1: scheduler 滚动更新期双实例重复跑 cron
**What goes wrong:** RollingUpdate 默认新 Pod 起、旧 Pod 未停时两份 `runapscheduler` 并存 → `backfill_chunk_edges` 等并发跑、6 builder×N repo 双倍 RAM（`runapscheduler.py:241-255` 明确警告）。
**Why:** flock 跨 Pod 失效；DjangoJobStore 不阻止两 scheduler 各自 add_job + 拉同一 job 执行。
**How to avoid:** scheduler Deployment 设 `strategy: { type: Recreate }` + `replicas: 1`（硬编码，不暴露 values）。
**Warning signs:** 同一 cron job 日志在两个 Pod 名下出现。

### Pitfall 2: compose `up -d` 升级时 worker 先于 migrate 起，procrastinate 表不存在
**What goes wrong:** worker `apps.py:47` import `durable.tasks`（`@app.task` 注册）+ 消费需 `procrastinate_jobs` 表；新表（如 Phase 新 migration）未迁时 worker 崩/空跑。
**Why:** compose 无显式迁移顺序保证；server entrypoint 跑 migrate，但 worker 是独立 service。
**How to avoid:** worker/scheduler `depends_on: postgres(healthy)` + **不自己 migrate**（role 门禁 + 让 server entrypoint 或专门 migrate 步骤先行）；或给 worker 加 initContainer/entrypoint 等 migrate 完成（检测某 marker）。helm 已有 pre-upgrade migration Job hook（`migration-job.yaml:10` `helm.sh/hook: pre-install,pre-upgrade` weight 0）——worker/scheduler Deployment 在 hook 后才 apply，天然有序。
**Warning signs:** worker 日志 `relation "procrastinate_jobs" does not exist`。

### Pitfall 3: 多副本误用内存 channel layer，WS 静默丢消息
**What goes wrong:** replicas>1 + `USE_REDIS_CHANNEL_LAYER=false` → 每副本独立 InMemoryChannelLayer，跨副本 WS group_send 丢失（workflow/runner 实时状态推不到连在别的副本的客户端）。
**Why:** `settings.py:187-192` 静默退回 InMemory，无报错。
**How to avoid:** 双层 fail-closed（Pattern 4）。
**Warning signs:** 多副本下部分客户端收不到实时状态更新。

### Pitfall 4: KEDA worker scale-to-zero 致 rescue 停摆
**What goes wrong:** minReplicaCount=0，队列空时 worker 缩到 0 → periodic deferrer 不跑 → stalled job 不再被 rescue → 新 job 入队后冷启动延迟。
**How to avoid:** minReplicaCount≥1。
**Warning signs:** stalled job 长时间不重投；新任务入队后久不开始。

### Pitfall 5: 非 KEDA / 非 k8s 安装被新模板破坏
**What goes wrong:** KEDA CRD 未装的集群 apply `ScaledObject` → `no matches for kind ScaledObject`，整个 helm install 失败；compose 用户被 scheduler service 强制启用搅乱。
**How to avoid:** KEDA/PDB 全 `{{ if .Values.worker.keda.enabled }}` 默认 false；ScaledObject/PDB 默认不渲染。compose scheduler 是否默认启用是 Claude's Discretion——建议默认启用（cron 当前根本没跑，启用才修复功能缺失），但用 compose profile 让极简单机可关。

## Code Examples

### 既有优雅终止入口（无需改信号逻辑）
```58:73:server/durable/management/commands/run_worker.py
    async def _run_worker(self, queues: list[str]) -> None:
        # 本地 import procrastinate：保持适配层隔离边界（仅 backends/tasks/management
        # 允许直接 import），且 SQLite 路径在上面已 CommandError 退出、不会到此。
        from procrastinate.contrib.django import app

        # get_worker_connector()：检测到 psycopg3 → 返回 PsycopgConnector（独立 async
        # 连接，专为长跑 worker）；绝不复用 DjangoConnector 跑 worker。
        connector = app.connector.get_worker_connector()
        with app.replace_connector(connector) as worker_app:
            # listen_notify=False 必须显式传入（锁定决策）：v1 走 polling，低延迟
            # NOTIFY 唤醒 deferred 到 v2（DURABLEX-01）。
            await worker_app.run_worker_async(queues=queues, listen_notify=False)
```

### 既有 fail-closed 校验范式（扩展给多副本 Redis）
```75:83:server/friday/settings.py
if IS_PRODUCTION:
    if DEBUG:
        raise ImproperlyConfigured("Production mode requires DEBUG=False")
    if not SECRET_KEY or SECRET_KEY == INSECURE_SECRET_KEY:
        raise ImproperlyConfigured("Production mode requires a non-default SECRET_KEY")
    if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:
        raise ImproperlyConfigured(
            "Production mode requires explicit ALLOWED_HOSTS (wildcard not allowed)"
        )
```

### 既有 role 门禁（worker/scheduler 复用）
```30:49:server/durable/roles.py
def current_role() -> str:
    """返回归一化后的当前进程角色（小写、去空白），缺省 ``"web"``。"""
    return os.environ.get("FRIDAY_PROCESS_ROLE", DEFAULT_ROLE).strip().lower() or DEFAULT_ROLE


def should_run_startup_side_effects(
    *,
    job: str,
    allowed: frozenset[str] = frozenset({"web"}),
) -> bool:
    role = current_role()
    if role in allowed:
        return True
    logger.info("startup_side_effect_skipped_by_role", role=role, job=job)
    return False
```

### 既有 fence 范式（aarchive_exists — MR/PR 创建可镜像）
```533:536:server/knowledge/diff_archive.py
async def aarchive_exists(source_kind: str, source_id: str) -> bool:
    """是否已存在归档行（按 source_kind+source_id；编排层区分重复幂等 vs 失败用）。
```

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| 单 server 容器跑 gunicorn（worker/cron 不独立） | web/worker/scheduler 三 workload 拆分 | worker 可 KEDA 独立伸缩；cron 单例 leader |
| `flock` 单机 scheduler 单例 | k8s replicas=1 + Recreate（跨 Pod 正确） | 跨节点单例保证 |
| 手动 HPA / 无伸缩 | KEDA postgres 队列深度伸缩 | 按 todo 深度弹性，cooldown 防抖 |
| 内存 channel layer 容忍多副本（静默丢） | 多副本强制 Redis fail-closed | 配置错误启动即报，不静默丢 WS |

**Deprecated/outdated:**
- `runapscheduler` 的 `fcntl.flock` 单例：保留作同节点兜底，但**不再是跨 Pod 单例真相**（改靠 replicas=1）。
- `get_stalled_jobs(nb_seconds=...)`：已弃用，用 `seconds_since_heartbeat`（Phase 60 已遵循）。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `procrastinate_jobs` 状态枚举含 `todo`，列名 `status`/`queue_name`（KEDA query 依赖） | KEDA | 中——若列/枚举名不同，KEDA query 报错（伸缩失效，不影响正确性）。plan 应 `\d procrastinate_jobs` 实测确认 |
| A2 | `WorkItem.feishu_chat_id` 在建群节点入口可读到（作 fence） | Fencing | 低——Phase 59 字段确存在；若节点入口无 WorkItem 锚则 fence 退化 no-op，建群本就 fail-soft |
| A3 | helm pre-upgrade migration hook 保证 worker/scheduler Deployment 在迁移后才 apply | Pitfall 2 | 低——helm hook weight/顺序标准行为；compose 侧需显式 depends_on + 不自 migrate |
| A4 | KEDA operator 由用户集群自备（chart 不打包 KEDA） | Stack | 低——KEDA 模板 values-gated 默认 off，非 KEDA 集群零影响 |
| A5 | `terminationGracePeriodSeconds=120` / KEDA cooldown 300 / max 5 为合理默认 | Patterns | 低——均 values 可调，Claude's Discretion；plan 可微调 |

## Open Questions

1. **scheduler workload 的 worker 探针/健康检查形态**
   - 已知：worker/scheduler 无 HTTP 端口，server liveness 用 httpGet `/health`（`values.yaml:23-36`）不适用。
   - 不清楚：worker 用 `exec pgrep -f run_worker` 还是无探针；scheduler 同理。
   - 建议：worker/scheduler 用简单 exec 探针（`pgrep`）或省略 liveness（靠 restart policy），plan 定。

2. **compose scheduler 默认启用 vs profile（Claude's Discretion）**
   - 已知：cron 当前根本没跑（功能缺失）。
   - 建议：默认启用（修复缺失），单机极简可用 compose profile 关。

3. **KEDA 按 queue 维度的具体形态（单 query 全队列 vs per-queue 多 trigger / 多 ScaledObject）**
   - 建议：v1 单 query 全 todo 深度伸 worker（worker 默认消费全队列）；per-queue 伸缩留 values override，不在 v1 强求（worker 默认 `--queues` 全部）。

4. **MR/PR existing 检查的平台 client 能力**
   - 不清楚：`services/git_platform/{gitlab,github}_client.py` 是否已有 list MR by branch 方法。
   - 建议：plan 先 grep client 现有方法；若无则薄封装一个 `find_open_mr(source, target)`。

## Environment Availability

| Dependency | Required By | Available | Fallback |
|------------|------------|-----------|----------|
| Postgres | durable worker / KEDA query / scheduler | ✓（compose `postgres:17-alpine` / helm postgresql.enabled） | 无（durable 必需 Postgres，SQLite 仅 dev fallback 不跑 worker） |
| Redis | 多副本 channel layer | ✓（compose redis / helm redis.enabled） | 单副本可 InMemory；多副本 fail-closed 无 fallback |
| KEDA operator | worker 队列深度伸缩 | ✗（集群侧自备，可选） | values-gated 默认 off；无 KEDA 用固定 replicas |
| k8s `policy/v1` PDB | 驱逐保护 | ✓（标准 API） | values-gated 默认 off |
| helm v3 | 模板渲染/lint 验证 | ✓（既有 chart） | — |

**Missing dependencies with fallback:**
- KEDA：默认 off，用户用固定 `worker.replicaCount` 手动伸缩。
- Redis（仅单副本时）：InMemory channel layer。

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest（server）+ helm CLI（template/lint）+ docker compose config |
| Config file | `server/pyproject.toml`（pytest + `postgres_queue` marker，默认排除） |
| Quick run command | `cd server && uv run pytest tests/durable -q` |
| Full suite command | `cd server && uv run pytest -q` |

### Phase Requirements → Test Map
| Req | Behavior | Test Type | Automated Command | Exists? |
|-----|----------|-----------|-------------------|---------|
| DEPLOY-01 | `run_worker` 接受 `--graceful-timeout` 并传入 `shutdown_graceful_timeout` | unit | `pytest tests/durable/test_run_worker_args.py -x`（mock `run_worker_async`，断言 kwarg） | ❌ Wave 0 |
| DEPLOY-01 | SIGTERM graceful（真实 drain）| manual | 人工/容器 E2E（kill -TERM worker，观察在途完成）| ❌ human_needed（需真实 worker+Postgres）|
| DEPLOY-02 | helm 渲染出 worker/scheduler Deployment（role/command/replicas=1）| smoke | `helm template deploy/helm/friday --set worker.enabled=true \| grep -A... worker` | ❌ Wave 0（可加 bats/shell test 或 pytest 调 helm）|
| DEPLOY-02 | helm lint 通过 | smoke | `helm lint deploy/helm/friday` | ❌ Wave 0 |
| DEPLOY-02 | compose 配置合法（worker/scheduler service）| smoke | `docker compose -f docker-compose.yaml config -q` | ❌ Wave 0 |
| DEPLOY-02 | scheduler 模板强制 replicas=1 + Recreate | smoke | `helm template ... \| yq 'select(.metadata.name\|test("scheduler")).spec.replicas'` == 1 | ❌ Wave 0 |
| DEPLOY-03 | 多副本无 Redis → settings `ImproperlyConfigured` | unit | `pytest tests/test_settings_fail_closed.py`（override env `FRIDAY_EXPECT_MULTI_REPLICA=true` + `USE_REDIS_CHANNEL_LAYER=false` → raises）| ❌ Wave 0 |
| DEPLOY-03 | helm 多副本无 redis → `fail` | smoke | `helm template ... --set server.replicaCount=2 --set redis.enabled=false` 期望非零退出 | ❌ Wave 0 |
| DEPLOY-03 | KEDA ScaledObject 仅 keda.enabled 时渲染 + query 含 `status='todo'` | smoke | `helm template ... --set worker.keda.enabled=true \| grep procrastinate_jobs` | ❌ Wave 0 |
| IDEMP-02 | 建群 fence：已有 `feishu_chat_id` → 跳过 create_chat | unit | `pytest tests/workflows/test_chat_nodes.py::test_create_group_fenced`（mock service，断言 create_chat 未被调）| ❌ Wave 0（既有 test_chat_nodes.py 可扩）|
| IDEMP-02 | MR fence：已有 open MR → 复用不重复创建 | unit | `pytest tests/test_coding_*.py::test_mr_dedup`（mock client list+create）| ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `cd server && uv run pytest tests/durable -q` + 改到的 helm/compose 时 `helm lint` / `docker compose config -q`
- **Per wave merge:** `cd server && uv run pytest -q`（SQLite 默认）+ `helm template`/`lint` 全渲染
- **Phase gate:** 全量 pytest 绿 + helm template/lint 绿 + compose config 绿，真实多副本 drain/接管 E2E 标 human_needed

### Wave 0 Gaps
- [ ] `server/tests/durable/test_run_worker_args.py` — 覆盖 DEPLOY-01 graceful-timeout arg 透传
- [ ] `server/tests/test_settings_fail_closed.py` — 覆盖 DEPLOY-03 多副本无 Redis raise
- [ ] helm 渲染断言（`helm template`/`lint` 包进 CI 或 shell/pytest 调用）— 覆盖 DEPLOY-02/03（CI 当前**无 helm lint**，grep 零命中）
- [ ] compose `config -q` 校验步骤
- [ ] 扩 `tests/workflows/test_chat_nodes.py` + coding MR 测试覆盖 IDEMP-02 fence
- 真实 SIGTERM drain / 多副本接管 / KEDA 实际伸缩 → human_needed（需真实 k8s+Postgres+KEDA）

## Security Domain

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | 本阶段无新认证面 |
| V4 Access Control | no | — |
| V5 Input Validation | partial | KEDA query 模板化（参数化 jobsPerReplica，无用户输入拼 SQL） |
| V6 Cryptography | no | 复用既有 Fernet/secret，无新加密 |
| V7 Secrets Management | **yes** | KEDA `TriggerAuthentication` 引 secret，**绝不在 ScaledObject/values 明文 DB 密码**；helm secret 复用既有 `secret.yaml` |
| V10 Config / Hardening | **yes** | 多副本无 Redis fail-closed；scheduler 单例防重复副作用；KEDA/PDB 默认 off 不破坏既有 |

### Known Threat Patterns
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| KEDA 明文 DB 密码进 ScaledObject/values | Information Disclosure | `TriggerAuthentication` + secretTargetRef（[CITED: keda #3612]）|
| scheduler 多实例重复外部副作用（重复通知/PR）| Tampering（重复动作）| replicas=1 + Recreate + IDEMP-02 fencing |
| 多副本静默丢 WS（可用性退化）| Denial of Service（功能丢失）| fail-closed 强制 Redis |
| at-least-once 重复建群/开 PR | Tampering | 复用 `feishu_chat_id`/existing-MR fence |

## Sources

### Primary (HIGH confidence)
- procrastinate.readthedocs.io/en/stable/howto/advanced/shutdown.html — graceful shutdown（`install_signal_handlers`/`shutdown_graceful_timeout`/`wait`）
- procrastinate.readthedocs.io reference.html（已下载全文核实）— `run_worker_async` 签名（heartbeat 10s / stalled 30s）、`periodic`、`defer_periodic_job`（DB 去重）、`get_stalled_jobs(seconds_since_heartbeat=30)`
- keda.sh/docs/2.20/scalers/postgresql + keda-docs GitHub — postgresql scaler（query/targetQueryValue/cooldownPeriod/min-max/TriggerAuthentication）
- 仓库代码（file:line 引用）：`run_worker.py`、`roles.py`、`tasks.py`、`tasks_impl.py`、`apps.py`、`service.py`、`settings.py`、`runapscheduler.py`、`server-deployment.yaml`、`migration-job.yaml`、`values.yaml`、`configmap.yaml`、`docker-compose.yaml`、`diff_archive.py`、`ingest_orchestrator.py`、`coding.py`、`feishu_chat.py`
- Phase 60/61 SUMMARY（durable/role/rescue/migration 已交付范畴）

### Secondary (MEDIUM confidence)
- KEDA 社区博客（oneuptime / srekubecraft）— ScaledObject 实例参数佐证 cooldown/polling/fallback

### Tertiary (LOW confidence)
- 无关键结论依赖未验证来源

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — procrastinate/apscheduler/channels 均已在仓库 + 官方文档核实
- Architecture（workload 拆分 / graceful / KEDA / fail-closed）: HIGH — 既有代码坐标 + 官方语义核实
- Pitfalls: HIGH — runapscheduler 单例契约/未接线、多副本 channel layer 均代码佐证
- Fencing: HIGH（触点定位）/ MEDIUM（具体 client existing-MR 能力待 grep，见 OQ4）

**Research date:** 2026-06-21
**Valid until:** 2026-07-21（procrastinate <3.9 锁定、KEDA CRD 稳定，30 天有效）

## RESEARCH COMPLETE
