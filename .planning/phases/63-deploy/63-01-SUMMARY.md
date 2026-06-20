---
plan: 63-01
phase: 63-deploy
status: complete
completed: 2026-06-20
requirements: [DEPLOY-01, DEPLOY-02]
---

# Plan 63-01 Summary — 优雅终止 + web/worker/scheduler workload 拆分

## What was built

- **DEPLOY-01 优雅终止**：`server/durable/management/commands/run_worker.py` 新增 `--graceful-timeout`（默认透传 `shutdown_graceful_timeout` 给 `run_worker_async`）。优雅 drain 由 Procrastinate 内置 SIGTERM 处理承载，**无自写信号循环**；`listen_notify=False` 保持。
- **DEPLOY-02 workload 拆分（helm）**：新增 `deploy/helm/friday/templates/worker-deployment.yaml`（role=worker，`replicaCount` 可配，`terminationGracePeriodSeconds` 默认 120 > gracefulTimeout 110 > heartbeat 10s/stalled 30s）+ `scheduler-deployment.yaml`（role=scheduler，**replicas 硬编码 1 + strategy Recreate**，首次拉起 `runapscheduler` apscheduler cron）。复用 `_helpers.tpl`/configmap/secret；`values.yaml` 新增 `worker{}`/`scheduler{}` 段。
- **DEPLOY-02 workload 拆分（compose）**：`docker-compose.yaml` + `docker-compose.build.yaml` 新增 `worker`（`run_worker --graceful-timeout 110` + `FRIDAY_PROCESS_ROLE=worker`）与 `scheduler`（`runapscheduler` + `FRIDAY_PROCESS_ROLE=scheduler`）service，同 server 镜像不同 command。
- durable 周期 rescue 保持在 **worker**（periodic deferrer + DB 去重），未移到 scheduler（对齐 RESEARCH 校正）。

## Commits

- `1bfb60aae` / `fff5a1226`: feat(63-01) run_worker --graceful-timeout（注：执行期自监控误报"并发执行"，产生一对同义 Task-1 提交；二者均前向、最终态以 fff5a1226 的测试为准，无功能分叉，已由 orchestrator 核验）
- `ddd1f5821`: feat(63-01) helm 拆出独立 worker/scheduler Deployment + values 段
- `c5184dbe5`: feat(63-01) compose 拆出 worker/scheduler service + build override

## Verification

- `helm lint deploy/helm/friday` → 0 failed；`helm template deploy/helm/friday` → 渲染通过
- `docker compose -f docker-compose.yaml config -q` → 通过
- `manage.py check` → 0 issues；`run_worker --help` 含 `--graceful-timeout`
- `pytest tests/durable/test_run_worker_args.py` → 2 passed

## Deviations / Threat Flags

- **执行器并发误报**：gsd-executor 自监控将自身提交误判为"并发进程"并在 Task 3 后 CHECKPOINT 退出未写 SUMMARY；orchestrator 核验全部 3 任务实际已落地且校验全绿，补写本 SUMMARY。重复的 Task-1 提交无害（同义、最终态一致），保留不做 history rewrite。
- **compose 首启迁移顺序**（plan-check Warning 2）：worker/scheduler `depends_on` 已尽量约束；全新 `docker compose up -d` 首次启动若 worker 早于 server 迁移建表，可能短暂 `relation "procrastinate_jobs" does not exist` crash-loop，经 `restart` 自愈（存量升级无此问题）。属预期自愈，记录备查。

## Human-needed (runtime)

- 真实 k8s rolling update 下 worker SIGTERM drain 实测（在途 job 跑完/接管不丢）。
- 真实 compose `up -d` 升级既有部署不破坏。
