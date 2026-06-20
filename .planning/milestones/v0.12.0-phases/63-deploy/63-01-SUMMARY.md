---
phase: 63-deploy
plan: 01
subsystem: infra
tags: [procrastinate, graceful-shutdown, helm, docker-compose, kubernetes, apscheduler, workload-split, FRIDAY_PROCESS_ROLE]

# Dependency graph
requires:
  - phase: 60-durable-foundation
    provides: run_worker 命令、FRIDAY_PROCESS_ROLE 角色门禁（roles.py）、periodic rescue
  - phase: 61
    provides: runapscheduler apscheduler cron（deferred 未接线，本 plan 首次拉起）
provides:
  - run_worker --graceful-timeout 透传 shutdown_graceful_timeout（DEPLOY-01，零信号代码）
  - helm worker-deployment.yaml（role=worker, run_worker, terminationGracePeriodSeconds 不变式）
  - helm scheduler-deployment.yaml（role=scheduler, runapscheduler, replicas=1 + Recreate 单例）
  - helm values worker{}/scheduler{} 段（gating 默认 true）
  - compose worker/scheduler service + build override（同 server 镜像 + command + role）
affects: [63-02, 63-deploy KEDA/PDB, runner k8s Job executor]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "同镜像 + 不同 command + FRIDAY_PROCESS_ROLE 拆 web/worker/scheduler workload"
    - "scheduler 单例 = k8s replicas=1 硬编码 + strategy=Recreate（编排层保证，非应用锁）"
    - "优雅终止纯配置：terminationGracePeriodSeconds > graceful timeout > 心跳/stalled，复用 Procrastinate 内置信号处理"
    - "compose depends_on server(service_healthy) 保证 migrate 先行，worker 不自 migrate"

key-files:
  created:
    - server/tests/durable/test_run_worker_args.py
    - deploy/helm/friday/templates/worker-deployment.yaml
    - deploy/helm/friday/templates/scheduler-deployment.yaml
  modified:
    - server/durable/management/commands/run_worker.py
    - deploy/helm/friday/values.yaml
    - docker-compose.yaml
    - docker-compose.build.yaml

key-decisions:
  - "graceful drain 零信号代码：仅暴露 --graceful-timeout，drain 靠 Procrastinate install_signal_handlers 默认 True"
  - "scheduler replicas=1 模板内硬编码（不暴露 replicaCount）+ strategy=Recreate，防滚动期双实例重复跑 cron"
  - "worker/scheduler compose 服务 depends_on server(service_healthy)，借 server entrypoint 的 migrate 先行避免首启崩循环"
  - "terminationGracePeriodSeconds 默认 worker=120 / scheduler=60；gracefulTimeout=110"

patterns-established:
  - "workload 拆分：同镜像不同 command+role，复用 _helpers.tpl/configmap/secret，无 ports/无探针"
  - "compose 升级零回归：仅新增 service，既有 server/web/runner/postgres/redis/qdrant 逐字不变"

requirements-completed: [DEPLOY-01, DEPLOY-02]

# Metrics
duration: ~12min
completed: 2026-06-21
---

# Phase 63 Plan 01: 优雅终止 + web/worker/scheduler workload 拆分 Summary

**run_worker 暴露 `--graceful-timeout`（透传 Procrastinate `shutdown_graceful_timeout`，零信号代码）+ helm/compose 同构拆出独立 worker/scheduler workload（scheduler 单例 replicas=1+Recreate 首次承载 apscheduler cron），优雅终止不变式 terminationGracePeriodSeconds>graceful>心跳成立。**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-06-20T18:00Z (2026-06-21 02:00 UTC+8)
- **Completed:** 2026-06-20T18:08Z
- **Tasks:** 3
- **Files modified:** 7 (3 created, 4 modified)

## Accomplishments
- DEPLOY-01：`run_worker --graceful-timeout` 把值透传到 `run_worker_async(shutdown_graceful_timeout=...)`，drain 仍由 Procrastinate 内置信号处理提供（绝无自写 signal handler / asyncio 取消循环）；新增 mock 单测守护透传。
- DEPLOY-02（helm）：新增 `worker-deployment.yaml`（role=worker、`run_worker --graceful-timeout`、`terminationGracePeriodSeconds: 120`）与 `scheduler-deployment.yaml`（role=scheduler、`runapscheduler`、`replicas: 1` 硬编码 + `strategy.type: Recreate`），复用 `_helpers.tpl`/configmap/secret/initContainer wait-for-db；values 新增 `worker{}`/`scheduler{}` 段，gating 默认 true、非启用零渲染。
- DEPLOY-02（compose）：`docker-compose.yaml` 新增 `worker`（`stop_grace_period: 120s`）与 `scheduler` service（同 server 镜像 + command + `FRIDAY_PROCESS_ROLE`），均 `depends_on: server(service_healthy)` 保证迁移先行；`docker-compose.build.yaml` 复用 `friday-server:local` 构建产物。
- 验证全绿：helm lint/template、scheduler replicas=1 Recreate、worker role/grace、gating off 零渲染、compose `config -q`（base + build override）、`manage.py check`、`run_worker --help` 显示 `--graceful-timeout`、durable 套件 60 passed。

## Task Commits

1. **Task 1: run_worker --graceful-timeout 透传** - `1bfb60aae` (feat) + `fff5a1226` (hook 自动 ruff format 重排测试文件，同 message)
2. **Task 2: helm worker/scheduler deployment + values** - `ddd1f5821` (feat)
3. **Task 3: compose worker/scheduler service + build override** - `c5184dbe5` (feat)

_Note: Task 1 因 pre-commit 钩子对测试文件二次格式化产生一个同消息的追加 commit（`fff5a1226`），内容等价、均已落 main。_

## Files Created/Modified
- `server/durable/management/commands/run_worker.py` - 新增 `--graceful-timeout` arg + `handle→_run_worker` 透传 `shutdown_graceful_timeout`，`listen_notify=False` 保持显式不变
- `server/tests/durable/test_run_worker_args.py` - 新建，mock app + use_procrastinate_backend，参数化断言透传 110.0 / None 且 listen_notify=False
- `deploy/helm/friday/templates/worker-deployment.yaml` - 新建，worker workload（gating worker.enabled）
- `deploy/helm/friday/templates/scheduler-deployment.yaml` - 新建，scheduler 单例 workload（gating scheduler.enabled）
- `deploy/helm/friday/values.yaml` - 新增 `worker{}`（enabled/replicaCount/gracefulTimeout/terminationGracePeriodSeconds/resources）+ `scheduler{}`（enabled/terminationGracePeriodSeconds/resources）
- `docker-compose.yaml` - 新增 `worker` + `scheduler` service
- `docker-compose.build.yaml` - 新增 worker/scheduler image override（复用 friday-server:local）

## Decisions Made
- **优雅终止零信号代码**：仅暴露 `--graceful-timeout`；drain 靠 Procrastinate `install_signal_handlers`（默认 True）。与 CONTEXT「不重造信号循环」一致。
- **scheduler 单例靠编排层**：`replicas: 1` 模板硬编码 + `strategy: Recreate`（不暴露 replicaCount），防滚动期双实例重复跑 cron（RESEARCH Pitfall 1）。durable 周期 rescue 不放 scheduler（由 worker periodic deferrer + DB 去重承载）。
- **compose 迁移顺序**：worker/scheduler `depends_on: server(service_healthy)`。server entrypoint 先 `migrate` 再变 healthy，故首次 `up -d` 时 `procrastinate_jobs` 等表已建——比仅 depends_on postgres 更强地规避 RESEARCH Pitfall 2 的崩循环（采纳 plan-check 警告建议）。
- **grace 默认值**：worker terminationGracePeriodSeconds=120 > gracefulTimeout=110 > 心跳(10s)/stalled(30s)；scheduler grace=60（无在途 durable job）。

## Deviations from Plan

无功能性偏差——计划按原样执行。两点说明（非偏差）：

1. **compose depends_on 采用 server(service_healthy) 而非仅 postgres(healthy)**：plan task 文本提到 worker `depends_on postgres healthy`，但 plan-check 警告明确要求「depends_on server / 等迁移完成以防首启崩循环」。已核实 `server/entrypoint.sh` 先 `migrate` 再启动 gunicorn、healthcheck 走 `/health`，因此 `depends_on: server(service_healthy)` 是表达迁移先行的最干净方式。这是 plan 内 plan-check 警告的落地，非新增范围。
2. **Task 1 产生两个同消息 commit**：pre-commit 钩子对测试文件二次 ruff format，自动追加 `fff5a1226`；内容等价，run_worker.py 业务改动在 `1bfb60aae`。

## Issues Encountered
- 系统 `python3` 无 `pyyaml`，helm 渲染断言改用 `cd server && uv run python`（仓库 venv 内含 pyyaml）执行，验证通过。

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| human/CI verify | k8s 集群 | 真实 SIGTERM drain / 滚动更新 scheduler 单例接管需真实 k8s+Postgres+在途 job，标 human_needed（见 63-VALIDATION Manual-Only），本地无法自动化 |

_说明：helm/compose 本地 CLI 均可用（helm v4.1.4、docker compose v5.1.2），渲染/lint/config 全部本地验证通过，无 CLI 缺失型 human check。_

## Known Stubs
None — 全部为可运行配置/编排 + 既有 procrastinate/apscheduler 消费，无占位 stub。

## Next Phase Readiness
- worker 可独立伸缩 + 优雅 drain 配置就位；scheduler 单例首次承载 apscheduler cron。
- 63-02 可在此基础上加 worker KEDA ScaledObject / PDB（values-gated 默认 off）+ 多副本无 Redis fail-closed（settings + helm）。
- 真实多副本 drain/接管/KEDA 伸缩 E2E 仍待 human_needed 验证。

## Self-Check: PASSED

- 创建文件全部存在：run_worker.py、test_run_worker_args.py、worker-deployment.yaml、scheduler-deployment.yaml、63-01-SUMMARY.md。
- 提交全部可从 HEAD 追溯：`1bfb60aae`/`fff5a1226`（Task 1）、`ddd1f5821`（Task 2）、`c5184dbe5`（Task 3）。
- 未改动 STATE.md / ROADMAP.md（STATE.md 的工作区变更由编排钩子在执行起始注入，未纳入任何 commit）。

---
*Phase: 63-deploy*
*Completed: 2026-06-21*
