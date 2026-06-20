---
phase: 63-deploy
plan: 02
subsystem: infra
tags: [keda, autoscaling, pdb, helm, kubernetes, channels-redis, fail-closed, procrastinate, DEPLOY-03]

# Dependency graph
requires:
  - phase: 63-01
    provides: helm worker-deployment.yaml（scaleTargetRef 目标 {fullname}-worker）+ values worker{} 段
  - phase: 60-durable-foundation
    provides: procrastinate worker（periodic deferrer 驱动 rescue，禁 scale-to-zero 的理由）
provides:
  - settings _require_redis_for_multi_replica 纯函数 + 运行期 fail-closed（FRIDAY_EXPECT_MULTI_REPLICA / GUNICORN_WORKERS>1）
  - helm worker-scaledobject.yaml（KEDA postgresql scaler，按 procrastinate_jobs todo 深度伸缩，values-gated 默认 off）
  - helm keda-triggerauth.yaml（TriggerAuthentication，DB 凭证经 secret 不明文）
  - helm worker-pdb.yaml / web-pdb.yaml（PodDisruptionBudget，values-gated 默认 off）
  - helm configmap 模板期 fail（多进程 web + 无 Redis）+ FRIDAY_EXPECT_MULTI_REPLICA 注入
  - values worker.keda / worker.pdb / web.pdb 段
affects: [63-deploy 后续, runner k8s Job executor]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "KEDA/PDB values-gated 默认 off：{{ if .Values.*.enabled }} 包裹，非 KEDA/默认安装零渲染（不破坏既有 install）"
    - "双层 fail-closed 同源 trigger：settings 运行期（FRIDAY_EXPECT_MULTI_REPLICA 或 GUNICORN_WORKERS>1）与 helm 模板期 fail（server.replicaCount>1 或 gunicornWorkers>1）均锚 web/server 层，避免模板通过运行期崩"
    - "KEDA 凭证经 TriggerAuthentication + secretTargetRef→DATABASE_URL，绝不在 ScaledObject metadata 明文连接串（keda #3612）"
    - "禁 worker scale-to-zero：minReplicaCount 默认 1，保 periodic deferrer 持续驱动 durable rescue"

key-files:
  created:
    - server/tests/test_settings_fail_closed.py
    - deploy/helm/friday/templates/worker-scaledobject.yaml
    - deploy/helm/friday/templates/keda-triggerauth.yaml
    - deploy/helm/friday/templates/worker-pdb.yaml
    - deploy/helm/friday/templates/web-pdb.yaml
  modified:
    - server/friday/settings.py
    - deploy/helm/friday/templates/configmap.yaml
    - deploy/helm/friday/values.yaml

key-decisions:
  - "多副本信号锚 web/server 层（server.replicaCount>1 或 gunicornWorkers>1），不含 worker.enabled —— configmap 为全 workload 共享，按 worker.enabled 声明会让单 server+关 Redis+默认开 worker 部署的 web pod 启动即崩（落实 plan-check Warning 1）"
  - "helm 模板期 fail 与 settings 运行期 trigger 同源：均含 gunicornWorkers>1，消除模板通过运行期崩的不对称（plan 原文 fail 仅查 replicaCount，本实现对齐扩到 gunicornWorkers）"
  - "KEDA query 默认 SELECT COALESCE(ceil(COUNT(*)::decimal / jobsPerReplica),0) FROM procrastinate_jobs WHERE status='todo'，按 queue 维度经 worker.keda.query override（追加 queue_name 过滤）"
  - "scheduler 不配 PDB：单例 replicas=1，PDB 与单例冲突会阻塞驱逐"

requirements-completed: [DEPLOY-03]

# Metrics
duration: ~15min
completed: 2026-06-21
---

# Phase 63 Plan 02: KEDA + PDB + 多副本 Redis 双层 fail-closed Summary

**给 worker 加 KEDA postgresql scaler（按 `procrastinate_jobs status='todo'` 队列深度伸缩、minReplicaCount>=1 禁 scale-to-zero、凭证经 TriggerAuthentication）+ web/worker PodDisruptionBudget + 把"多副本误用内存 channel layer 静默丢 WS"从注释约束升级为 settings 运行期 + helm 模板期双层 fail-closed；KEDA/PDB 全 values-gated 默认 off，默认安装/单副本零回归。**

## Performance

- **Duration:** ~15 min
- **Tasks:** 3
- **Files:** 8 (5 created, 3 modified)

## Accomplishments

- **DEPLOY-03 settings 运行期 fail-closed**：`settings.py` 新增纯函数 `_require_redis_for_multi_replica(*, expect_multi, use_redis)`——`expect_multi and not use_redis` 时 `raise ImproperlyConfigured`（中文提示）；模块级 `_EXPECT_MULTI_REPLICA = FRIDAY_EXPECT_MULTI_REPLICA 或 GUNICORN_WORKERS>1` 驱动校验，复用既有 `IS_PRODUCTION` 范式。`test_settings_fail_closed.py` 4 条纯函数单测覆盖真值表（多副本无 Redis raise / 其余放行）。
- **DEPLOY-03 KEDA**：`worker-scaledobject.yaml` postgresql scaler 按 `procrastinate_jobs WHERE status='todo'` 深度伸缩（`COUNT/jobsPerReplica` + COALESCE 防 null），`minReplicaCount` 默认 1 禁 scale-to-zero（保 periodic deferrer 驱动 rescue）、`cooldownPeriod` 300s 防抖、`maxReplicaCount` 5；`scaleTargetRef` 指向 63-01 的 `{fullname}-worker`；`keda-triggerauth.yaml` 经 `secretTargetRef→DATABASE_URL` 注入 DB 连接串，metadata 零明文密码。`worker.keda.query` 可 override 支持按 queue 维度。
- **DEPLOY-03 PDB**：`worker-pdb.yaml`（默认 `maxUnavailable: 1`）/ `web-pdb.yaml`（默认 `minAvailable: 1`）`policy/v1` PodDisruptionBudget，selector 锚各自 component label；scheduler 不配 PDB。
- **DEPLOY-03 helm 模板期 fail-closed**：`configmap.yaml` 顶部加 `{{ fail }}`——`server.replicaCount>1 或 gunicornWorkers>1` 且无 `redis.enabled`/`externalRedis.url` 时硬失败；并注入 `FRIDAY_EXPECT_MULTI_REPLICA`（web/server 层多进程时 true）供 settings 运行期消费。
- **全 values-gated 默认 off**：`worker.keda` / `worker.pdb` / `web.pdb` 段默认 `enabled: false`，默认 `helm template` 不渲染 ScaledObject/PDB，非 KEDA 集群零影响。

## Schema 核实（OQ1/A1）

`server/.venv/.../procrastinate/sql/schema.sql:23-24,73` 实测：`CREATE TYPE procrastinate_job_status AS ENUM ('todo', ...)`，`procrastinate_jobs.status` 列默认 `'todo'`，含 `queue_name` 列。KEDA query 用 `status = 'todo'` 与实际枚举一致，按 queue 维度可加 `queue_name` 过滤。

## Verification

| 检查 | 结果 |
|------|------|
| `pytest tests/test_settings_fail_closed.py -q` | 4 passed |
| `pytest tests/durable -q`（回归） | 60 passed, 13 deselected |
| `manage.py check`（默认 env） | no issues |
| `helm lint deploy/helm/friday` | 0 failed |
| `helm template`（默认）ScaledObject/PDB 计数 | 0 / 0（默认 off）|
| `--set worker.keda.enabled=true` ScaledObject/TriggerAuth | 1 / 1，query 含 `status = 'todo'`，`minReplicaCount: 0` 计数 0 |
| `--set worker.pdb.enabled=true --set web.pdb.enabled=true` PDB | 2（web minAvailable=1 / worker maxUnavailable=1，无 scheduler PDB）|
| `--set server.replicaCount=2 --set redis.enabled=false --set externalRedis.url=""` | 模板期 fail（非零退出，中文 fail 信息）|
| `--set server.gunicornWorkers=2 --set redis.enabled=false` | 模板期 fail（同源 trigger 一致性）|
| `--set server.replicaCount=2`（默认 redis 开） | 渲染 OK，`FRIDAY_EXPECT_MULTI_REPLICA: "true"` |
| `helm template`（默认）`FRIDAY_EXPECT_MULTI_REPLICA` | "false" |
| `docker compose config -q` | 合法（未改 compose，无回归）|

## Deviations from Plan

### 落实 plan-check Warning 1（非新增范围，user key_constraints 明确要求）

**1. [Rule 2 - 正确性] FRIDAY_EXPECT_MULTI_REPLICA 仅锚 web/server 层，剔除 worker.enabled**
- **Found during:** Task 3
- **Issue:** plan task 3 action 原文 configmap 条件含 `.Values.worker.enabled`（`if or (replicaCount>1) (gunicornWorkers>1) worker.enabled`）。但 configmap 为全部 workload 共享，`worker.enabled` 默认 true，会让"单 server + 关 Redis + 默认开 worker"部署的每个 web pod 启动即 `ImproperlyConfigured` 崩溃。
- **Fix:** 条件改为仅 `or (server.replicaCount>1) (server.gunicornWorkers>1)`，与 user key_constraints / plan must_haves 一致。
- **Files:** `deploy/helm/friday/templates/configmap.yaml`
- **Commit:** 6200973f7

**2. [Rule 2 - 正确性] helm 模板期 fail 扩到 gunicornWorkers>1，与 settings 运行期 trigger 同源**
- **Found during:** Task 3
- **Issue:** plan 原文 fail 条件仅 `gt (int server.replicaCount) 1`，但 settings 运行期 trigger 还含 `GUNICORN_WORKERS>1`。若仅扩 gunicornWorkers（replicaCount=1）关 Redis，模板会通过但运行期 settings 崩——正是 user key_constraints 警示的"模板通过、运行期崩"不对称。
- **Fix:** fail 条件改为 `and (or (replicaCount>1) (gunicornWorkers>1)) (not redis.enabled) (not externalRedis.url)`，与 settings 同源。
- **Files:** `deploy/helm/friday/templates/configmap.yaml`
- **Commit:** 6200973f7

### 说明（非偏差）

- **Task 1 实现已存在于工作区**：执行起始时 `settings.py` 的 `_require_redis_for_multi_replica` 改动与 `test_settings_fail_closed.py` 已在工作区未提交（疑似本 plan 前次运行残留），内容与 plan 完全一致；本次验证单测 4 passed 后原样提交，未改写。

## Task Commits

1. **Task 1: settings 多副本无 Redis 运行期 fail-closed + 单测** - `0307cbf3c` (feat)
2. **Task 2: KEDA ScaledObject + TriggerAuthentication + values** - `86958e593` (feat)
3. **Task 3: PDB（worker/web）+ 模板期 fail + configmap 信号** - `6200973f7` (feat)

## Known Stubs

None — 全部为可运行配置/编排（helm 模板 + settings 纯函数校验）+ 单测守护，无占位 stub。

## Threat Flags

无新增超出 plan `<threat_model>` 的安全面。T-63-04（KEDA 凭证经 secret）、T-63-05（双层 fail-closed）、T-63-06（禁 scale-to-zero）、T-63-07（默认 off 不破坏既有）均已落地。

## Next Phase Readiness

- worker 队列深度弹性伸缩（KEDA）+ 驱逐保护（PDB）配置就位，values-gated 默认 off 安全。
- 多副本误用内存 channel layer 已双层 fail-closed（settings 运行期 + helm 模板期）。
- 真实 KEDA 集群伸缩 / 多副本运行期 raise 的 E2E 仍 human_needed（需真实 k8s+Postgres+KEDA，见 63-VALIDATION）。
- 63-deploy 剩余：IDEMP-02 外部副作用 fencing（建群查 feishu_chat_id、MR 查 existing）。

## Self-Check: PASSED

- 创建文件全部存在：test_settings_fail_closed.py、worker-scaledobject.yaml、keda-triggerauth.yaml、worker-pdb.yaml、web-pdb.yaml、63-02-SUMMARY.md。
- 提交全部可从 HEAD 追溯：`0307cbf3c`（Task 1）、`86958e593`（Task 2）、`6200973f7`（Task 3）。
- 未改动 STATE.md / ROADMAP.md（按编排指令本 plan 不更新）。

---
*Phase: 63-deploy*
*Completed: 2026-06-21*
