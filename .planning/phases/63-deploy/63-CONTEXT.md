# Phase 63: 部署硬化 + 外部副作用 fencing - Context

**Gathered:** 2026-06-20
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous — 灰区默认值按里程碑锁定约束自动采纳)

<domain>
## Phase Boundary

完成多副本/弹性伸缩部署硬化 + 给外部副作用任务上 fencing/outbox。交付：

1. **worker 优雅终止（DEPLOY-01）**：捕获 SIGTERM → 停止领取新任务、跑完在途或释放/缩短租约让其他副本快速接管（非干等租约过期）；helm worker 配 `terminationGracePeriodSeconds`（> 心跳间隔）。
2. **compose/helm 拆 workload（DEPLOY-02）**：同构拆 web/worker/scheduler 三类 workload（同镜像不同 command + `FRIDAY_PROCESS_ROLE`）；scheduler 单例 leader 承载 cron + 周期 rescue（含 Phase 61 deferred 的 runapscheduler cron 迁移到 scheduler workload）；compose `up -d` 升级不破坏既有部署。
3. **KEDA/PDB/Redis 强约束（DEPLOY-03）**：KEDA Postgres scaler 按队列深度（`COUNT(status='todo')`）伸缩 worker（cooldown 防抖、可按 queue 维度）+ PodDisruptionBudget + 多副本强制 Redis channel layer（未开启 fail-closed 提示，对齐 values.yaml 既有约束）。
4. **外部副作用 fencing/outbox（IDEMP-02）**：飞书通知/自动建群、MR/PR 创建上 fencing token 或 outbox，at-least-once 重复执行不产生重复外部动作（不重复发通知/不重复建群/不重复开 PR）。

**不在范围内**：runner k8s Job executor（Phase 64）；`listen_notify=True`、exactly-once（v2/非目标）。

</domain>

<decisions>
## Implementation Decisions

### worker 优雅终止（DEPLOY-01）
- worker 进程（Phase 60 `run_worker` 命令）捕获 SIGTERM：停止领取新 job（Procrastinate worker 自带 graceful stop）、跑完在途或释放/缩短租约（让其他副本快速接管，非干等过期）。
- helm worker Deployment 配 `terminationGracePeriodSeconds` > 心跳/lease 间隔（具体值由 research 给默认）。
- 复用 Procrastinate worker 既有 graceful shutdown 信号处理；不重造信号循环。

### compose/helm 拆 workload（DEPLOY-02）
- 同镜像 + 不同 command + `FRIDAY_PROCESS_ROLE`（Phase 60 已建角色门禁）拆三类 workload：
  - `web`（role=web，ASGI/daphne，现有 server-deployment）
  - `worker`（role=worker，`manage.py run_worker`，可多副本）
  - `scheduler`（role=scheduler，单例 leader，承载 cron + 周期 `retry_stalled_durable_jobs`）
- scheduler 单例：承载 Phase 61 deferred 的 runapscheduler 9 cron job 迁移 + Phase 60 周期 rescue（leader 经 queueing_lock，replicas=1）。
- compose（root `docker-compose.yaml` + `docker-compose.build.yaml`）同构拆 worker/scheduler service；`up -d` 拉新镜像重建迁移顺序不破坏既有部署（migrate job 先行、role 门禁防误跑）。
- helm（`deploy/helm/friday/`）：现有 server-deployment 保留为 web；新增 worker-deployment + scheduler-deployment（复用 _helpers.tpl + configmap/secret）。

### KEDA/PDB/Redis 强约束（DEPLOY-03）
- KEDA `ScaledObject`（postgresql scaler）按队列深度 `COUNT(status='todo')` 伸缩 worker：cooldownPeriod 防抖、可按 queue 维度（trigger query 参数化）；minReplicaCount/maxReplicaCount 由 values 配置。
- PodDisruptionBudget 给 worker/web（minAvailable 或 maxUnavailable）。
- 多副本强制 Redis channel layer：replicas>1 时未配 Redis channel layer → fail-closed 提示（对齐 `values.yaml` 既有约束 + settings 校验）。
- KEDA/PDB 经 values flag 可选启用（默认行为不破坏单副本部署）。

### 外部副作用 fencing/outbox（IDEMP-02）
- 给有外部副作用的 durable 任务（飞书通知/自动建群、MR/PR 创建）上 fencing token 或 outbox，保证 at-least-once 重复执行不重复外部动作。
- 倾向 **fencing/dedup 记录**（轻量）：在执行外部动作前检查/写入幂等标记（deterministic key），已执行则跳过；对建群/PR 复用既有写回字段（如 `WorkItem.feishu_chat_id` Phase 59 writeback、MR/PR archive `aarchive_exists` Phase 62 同款）作 fencing。
- outbox 仅在 fencing 不足以覆盖时引入（research 评估）。

### Claude's Discretion
- `terminationGracePeriodSeconds`、KEDA cooldown/min/max、PDB 阈值的默认值。
- fencing 实现形态（既有写回字段复用 vs 新建 dedup 表/列 vs outbox 表）——倾向 reuse-first，最小新建。
- compose scheduler service 是否默认启用（vs profile 可选）。
- helm KEDA/PDB 模板是否 values-gated（默认 off 保兼容）。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- Phase 60 `server/durable/`（roles.py FRIDAY_PROCESS_ROLE、run_worker 命令、queueing_lock leader rescue、tasks.py periodic）。
- `deploy/helm/friday/templates/`（server-deployment / runner-deployment / configmap / secret / _helpers.tpl / redis-statefulset / migration-job）— 拆 workload 复用。
- `deploy/helm/friday/values.yaml`（Redis channel layer 约束、镜像/副本配置）。
- 根 `docker-compose.yaml` + `docker-compose.build.yaml`（web/runner/postgres/redis/qdrant）— 拆 worker/scheduler。
- `server/friday/settings.py`（channel layer / Redis 配置 + 多副本 fail-closed 校验点）。
- `runapscheduler`（Phase 61 deferred 的 9 cron job — 迁移到 scheduler workload）。
- 外部副作用点：飞书通知/建群（Phase 59 `WorkItemService.awriteback_feishu_chat_id` / `create_chat`）、MR/PR 创建（coding 路径 `aarchive_exists` 范式）。

### Established Patterns
- FRIDAY_PROCESS_ROLE 角色门禁（Phase 60）；同镜像不同 command。
- queueing_lock 单 leader（Phase 60）。
- deterministic key 幂等 / 写回字段 fencing（Phase 59/61/62）。
- values-gated 可选特性（helm 兼容性）。

### Integration Points
- helm: 新增 worker-deployment / scheduler-deployment / keda-scaledobject / pdb 模板 + values。
- compose: worker/scheduler service + command/role。
- settings.py: 多副本 Redis fail-closed 校验。
- durable worker: SIGTERM graceful（复用 Procrastinate）。
- 外部副作用 handler: fencing 检查。
- scheduler: runapscheduler cron 迁移。

</code_context>

<specifics>
## Specific Ideas

- 多副本生产就绪：worker 可水平伸缩（KEDA 按 todo 深度）、优雅终止快速接管、scheduler 单 leader 不重复跑 cron。
- compose 升级（`up -d`）不破坏既有单/多副本部署。
- at-least-once 下外部动作不重复：不重复发飞书通知、不重复建群、不重复开 MR/PR。

</specifics>

<deferred>
## Deferred Ideas

- runner k8s Job executor → Phase 64。
- `listen_notify=True` 低延迟唤醒 → v2 DURABLEX-01。
- exactly-once → 非目标。

</deferred>

---

*Phase: 63-deploy*
*Context gathered: 2026-06-20 via smart discuss (autonomous)*
