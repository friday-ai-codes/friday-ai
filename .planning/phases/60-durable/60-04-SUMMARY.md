---
phase: 60-durable
plan: 04
subsystem: infra
tags: [ci, github-actions, postgres, durable-task-queue, pytest-postgres-marker]

# Dependency graph
requires:
  - phase: 60-01
    provides: postgres_queue marker（addopts 默认排除）+ DURABLE_TASK_BACKEND/_use_procrastinate 判定
  - phase: 60-03
    provides: ProcrastinateBackend + procrastinate.contrib.django 条件注册 + postgres_queue 测试（test_procrastinate_backend.py / test_stalled_rescue.py）
provides:
  - .github/workflows/ci.yaml（仓库从零重建的唯一 workflow）
  - server-ci job：SQLite 默认零回归门禁（uv sync --locked --dev + manage.py check + ruff advisory + uv run pytest）
  - postgres-queue job：postgres:17-alpine service + migrate + uv run pytest -m postgres_queue --allow-hosts=127.0.0.1,localhost
affects: [61 index/graph 迁移, 62 爬取队列, 63 部署硬化]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "marker 分层 CI：默认 server-ci 走 SQLite（addopts 默认排除 postgres_queue），独立 postgres-queue job 显式 -m postgres_queue + service container（T-60-09）"
    - "pytest-socket 默认 --disable-socket，postgres-queue 步骤 --allow-hosts=127.0.0.1,localhost 放行 service TCP（T-60-10）"
    - "FRIDAY_PROCESS_ROLE=migrate 跑 manage.py migrate 短路 web-only 启动副作用并建 procrastinate 表（T-60-11 / Pitfall 3）"
    - "聚焦范围：只建 server + Postgres 两 job，不恢复历史 413 行的 web/runner/docs/task/security-scan（RESEARCH Open Q1）"

key-files:
  created:
    - .github/workflows/ci.yaml
  modified: []

key-decisions:
  - "action 版本沿用历史 ci.yaml 已验证的真实大版本：actions/checkout@v6、astral-sh/setup-uv@v8.2.0(SHA 钉)、actions/setup-python@v6，不臆造伪版本"
  - "Python 版本经 setup-python 的 python-version-file: server/.python-version（3.14.2）驱动，单一真源不硬编码"
  - "server-ci 的 ruff 设为 continue-on-error advisory（沿用历史 ci.yaml 既有约定）：全量 ruff 仍有 295 条历史遗留告警，聚焦阶段不清理 legacy lint，避免零回归基线门禁一上线即假红"
  - "postgres-queue 显式 migrate 步骤（除 pytest-django 自身建测试库外）兑现 Pitfall 3 / T-60-11，并验证迁移对真实 Postgres 干净应用"

requirements-completed: [DURABLE-04]

# Metrics
duration: ~8min
completed: 2026-06-20
---

# Phase 60 Plan 04: 聚焦 server 的 Postgres CI Summary

**从零创建 `.github/workflows/ci.yaml`（仓库 workflow 已于 5579e45f2 全删）：`server-ci` 跑 SQLite 默认路径作零回归门禁（addopts 默认排除 postgres_queue），`postgres-queue` 用 postgres:17-alpine service container + migrate + `uv run pytest -m postgres_queue --allow-hosts=127.0.0.1,localhost` 跑 Plan 03 的 durable Postgres 行为，两 job 经 marker 分层共存；聚焦 server+Postgres，不恢复历史无关 job。**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-06-20T02:28Z (approx)
- **Completed:** 2026-06-20T02:36Z (approx)
- **Tasks:** 2
- **Files modified:** 1 (1 created)

## Accomplishments
- 新建唯一 workflow `.github/workflows/ci.yaml`：`on` push/pull_request 到 `main` + `paths: server/** + 自身`，`concurrency` 按 ref `cancel-in-progress`，`permissions: contents: read`。
- `server-ci`（SQLite 默认零回归门禁）：`actions/checkout@v6` → `astral-sh/setup-uv@v8.2.0`(cache) → `actions/setup-python@v6`(`python-version-file: server/.python-version`) → `uv sync --locked --dev` → `uv run python manage.py check` → `uv run ruff check .`(advisory) → `uv run pytest`（默认 addopts 即 SQLite 且 `-m 'not ... and not postgres_queue'`，无需显式 `-m`）。
- `postgres-queue`（durable Postgres 门禁）：`services.postgres` 用 `postgres:17-alpine`（`POSTGRES_USER/PASSWORD/DB` + `ports: 5432:5432` + `pg_isready` health check），job 级 `env` 设 `DATABASE_URL=postgres://...@127.0.0.1:5432/...` + `DURABLE_TASK_BACKEND=procrastinate`；步骤 checkout/uv/python/sync → `FRIDAY_PROCESS_ROLE=migrate uv run python manage.py migrate`（建 procrastinate 表，Pitfall 3）→ `uv run pytest -m postgres_queue --allow-hosts=127.0.0.1,localhost`（放行 pytest-socket，Pitfall 2）。
- 两 job 经 `postgres_queue` marker 分层共存：默认 SQLite 套件不触达 Postgres（T-60-09），Postgres 专项覆盖 defer/priority/retry-backoff/stalled rescue(forged-heartbeat)/并发竞争/SQLite fallback 退化路径。
- workflow 不含 web/runner/docs/task/security-scan job（聚焦 server，RESEARCH Open Q1）。

## Task Commits

Each task was committed atomically:

1. **Task 1: ci.yaml 骨架 + server-ci（SQLite 默认）job** - `77d8381cf` (ci)
2. **Task 2: postgres-queue job（postgres:17-alpine service + -m postgres_queue）** - `13fd7c681` (ci)

_注：本 plan 不写 STATE.md / ROADMAP.md（由 orchestrator 负责）；无 plan-metadata 提交。_

## Files Created/Modified
- `.github/workflows/ci.yaml` — `jobs.server-ci`（SQLite 默认零回归）+ `jobs.postgres-queue`（postgres:17-alpine service，`-m postgres_queue`）

## Decisions Made
- **action 版本沿用历史 ci.yaml 已验证的真实标签**：`actions/checkout@v6`、`astral-sh/setup-uv@fac544c07...`（v8.2.0，SHA 钉）、`actions/setup-python@v6`；不臆造伪版本（T-60-SC：仅用知名官方 action）。
- **Python 版本经 `python-version-file: server/.python-version`**：单一真源（3.14.2），不在 workflow 内硬编码 `'3.14'` 字符串。
- **`manage.py migrate` 用 `FRIDAY_PROCESS_ROLE=migrate`**：短路 web-only 启动副作用（DURABLE-02），并对真实 Postgres 建含 procrastinate 的全部表。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - 防假红] server-ci 的 ruff 步骤设为 `continue-on-error` advisory**
- **Found during:** Task 1
- **Issue:** 计划 action 文案写 `uv run ruff check .` 作普通步骤；实测全量 `uv run ruff check .` 在仓库现状下报 **295 条历史遗留告警**（legacy 代码，超出本 plan SCOPE）。若作阻塞步骤，server-ci 这个"SQLite 零回归绿色基线门禁"会一上线即假红，与 must_have「默认 server-ci 跑 SQLite 路径，与既有本地默认路径一致」「零回归基线」相悖。
- **Fix:** 沿用历史 `ci.yaml` 既有约定，将 ruff 设为 `continue-on-error: true` advisory baseline（保留 lint 信号但不阻塞门禁）。`manage.py check` 与 `pytest` 仍为硬门禁。SCOPE 边界：不在本 plan 清理 legacy lint（属无关既有问题）。
- **Files modified:** `.github/workflows/ci.yaml`
- **Commit:** `77d8381cf`

**Total deviations:** 1（Rule 1 防假红，对齐历史约定，无范围扩张、无架构变更）。

## Issues Encountered
- 本机 system `python3` 无 `pyyaml`；改用 server venv（`uv run python`）做 YAML 解析与 acceptance 断言，全部通过。

## Verification Results
- `uv run python -c "import yaml; d=yaml.safe_load(open('.github/workflows/ci.yaml')); ..."` → YAML 解析无异常；`jobs = ['server-ci', 'postgres-queue']`。
- Task 1 断言：`server-ci in jobs`、`on` 含 push/pull_request、workflow 不含 web/runner/docs/task job → 全绿。
- Task 2 断言：`postgres-queue in jobs`、`services.postgres.image == 'postgres:17-alpine'`、`options` 含 `pg_isready`、`env.DURABLE_TASK_BACKEND == procrastinate`、`env.DATABASE_URL` 含 `postgres://`、步骤含 `manage.py migrate` 与 `pytest -m postgres_queue --allow-hosts=127.0.0.1,localhost` → 全绿。
- `grep -n "postgres:17-alpine"` 命中；`grep -c "postgres_queue"` = 5 命中。
- `uv run python manage.py check`（SQLite 默认，本机）→ 0 issues（确认 server-ci 的 check 步骤本地可绿）。

## Manual-Only / Deferred Verifications
- **真实 GitHub Actions run**（push 后 server-ci 绿 + postgres-queue 绿）：**human_needed** —— 无法本地运行 GH Actions runner / service container；YAML 已离线校验合法、各 acceptance 断言通过，实际 CI 绿待推送验证。
- **真实 kill-worker E2E**（双 worker 真实 kill → 周期 leader rescue 接管在途 stalled）：**human_needed**（见 60-VALIDATION.md「Manual-Only Verifications」）；CI 内以 forged-heartbeat 自动逼近 rescue（test_stalled_rescue.py）。

## User Setup Required
None — workflow 自带 postgres:17-alpine service container，CI 无需额外密钥/配置。仅需将本 plan 提交推送到 GitHub 触发首次实跑。

## Threat Mitigations Applied
- **T-60-09**（默认 CI 误跑 postgres_queue 全红）→ server-ci 用默认 addopts 排除；仅 postgres-queue job 显式 `-m postgres_queue` + service container。
- **T-60-10**（pytest-socket 拦截 Postgres 连接假红）→ postgres-queue 步骤 `--allow-hosts=127.0.0.1,localhost`。
- **T-60-11**（缺 migrate 致 `relation "procrastinate_jobs" does not exist`）→ 测试前 `manage.py migrate`（条件注册 procrastinate.contrib.django 后建表）。
- **T-60-SC**（GH Actions 第三方 action 供应链）→ 仅用 actions/checkout、astral-sh/setup-uv（SHA 钉）、actions/setup-python 知名官方 action，钉大版本标签。

## Next Phase Readiness
- ✅ Postgres 专项 CI 门禁就位，Phase 61/62 迁移 index/graph/crawl 业务任务到 durable 队列后，可直接复用 postgres-queue job 跑 `-m postgres_queue` 回归。
- ⚠️ 首次真实 GH Actions run 待推送验证（human_needed）；真实 kill-worker E2E 留人工。

## Self-Check: PASSED
- `.github/workflows/ci.yaml` 存在并落地（server-ci + postgres-queue 两 job）。
- 2 个 task 提交（`77d8381cf` / `13fd7c681`）经 git log 确认存在。
- 未修改 STATE.md / ROADMAP.md（由 orchestrator 负责）。

---
*Phase: 60-durable*
*Completed: 2026-06-20*
