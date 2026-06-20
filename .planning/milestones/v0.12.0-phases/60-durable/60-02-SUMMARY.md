---
phase: 60-durable
plan: 02
subsystem: infra
tags: [process-role, appconfig-ready, startup-side-effects, durable-roles, zero-regression]

# Dependency graph
requires:
  - phase: 60-01
    provides: durable.roles.current_role / should_run_startup_side_effects（角色判定 helper）
provides:
  - 三处 AppConfig.ready() 的 web-only 启动副作用经 FRIDAY_PROCESS_ROLE 门禁
  - repositories._reset_stuck_indexing role 门禁（worker/migrate/test 短路）
  - codegraph galaxy warm + orphan graph reconcile role 门禁（backend 注册保留）
  - resumable._schedule_recovery role 门禁（handler 注册保留，叠加既有 argv 嗅探）
  - test_process_role.py：真值表 + 三处短路 + web 零回归 + 短路日志守护
affects: [60-03 Procrastinate 后端/periodic rescue, 60-04 Postgres CI, 61 index/graph 迁移]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "role 门禁前置于既有 argv 嗅探：role 是显式入口，argv 是兜底；两者任一拦截即短路"
    - "纯内存注册（handler/backend）与 DB 副作用解耦：注册无条件执行（所有角色需要），仅 DB 副作用受 role 门禁"
    - "ready() 短路测试用 mock.patch('threading.Thread') 拦截线程构造，无需真跑副作用"

key-files:
  created:
    - server/tests/durable/test_process_role.py
  modified:
    - server/repositories/apps.py
    - server/codegraph/apps.py
    - server/resumable/apps.py

key-decisions:
  - "repositories 门禁置于 ready() 入口（无 argv 嗅探）；resumable/codegraph 门禁置于各 _schedule_* 入口、前于既有 argv 嗅探"
  - "register_default_handlers / volar+gopls backend 注册保持无条件执行（纯内存、所有角色都需要 handler/backend 可用）"
  - "reconcile_orphaned_graph_builds 函数本体不改，仅其启动调度被门禁"

patterns-established:
  - "新增 web-only 启动副作用一律经 durable.roles.should_run_startup_side_effects(job=...) 门禁"

requirements-completed: [DURABLE-02]

# Metrics
duration: 11min
completed: 2026-06-20
---

# Phase 60 Plan 02: 进程角色门禁 Summary

**三处 `AppConfig.ready()` 的 web-only 启动副作用（repositories `_reset_stuck_indexing`、codegraph galaxy warm + orphan graph reconcile、resumable `_schedule_recovery`）接入 60-01 的 `durable.roles.should_run_startup_side_effects` 门禁：worker/migrate/test 进程短路并记 info 日志，handler/backend 注册无条件保留，web 默认零回归。**

## Performance

- **Duration:** ~11 min
- **Started:** 2026-06-20T01:59Z (approx)
- **Completed:** 2026-06-20T02:10Z (approx)
- **Tasks:** 3
- **Files modified:** 4 (1 created, 3 modified)

## Accomplishments
- `RepositoriesConfig.ready()` 在起 `_reset_stuck_indexing` daemon 线程前先判 `should_run_startup_side_effects(job="reset_stuck_indexing")`，False 直接 return（不起线程、不 join），避免 worker/migrate 进程误把 INDEXING/RUNNING 行标 FAILED。
- `ResumableConfig._schedule_recovery` 顶部加 `should_run_startup_side_effects(job="resumable_recovery")` 门禁，前置于既有 pytest/runserver/管理命令 argv 嗅探；`register_default_handlers()` 维持无条件执行。
- `CodegraphConfig` 的 `_schedule_galaxy_cache_warm`（job=`galaxy_cache_warm`）与 `_schedule_orphan_graph_build_reconcile`（job=`orphan_graph_reconcile`）各加 role 门禁，前置于各自 argv 嗅探；volar/gopls backend 注册与 `reconcile_orphaned_graph_builds` 本体不动。
- 新增 `server/tests/durable/test_process_role.py`（16 用例）：roles helper 真值表（web/缺省→True，worker/scheduler/migrate/test→False）、归一化、短路 info 日志（`startup_side_effect_skipped_by_role` 含 role+job）、三处 ready() 在 worker/migrate 短路（mock `threading.Thread` 断言未构造）、web 执行（绕过 argv 兜底后断言构造），及 handler/backend 注册与 role 无关。

## Task Commits

1. **Task 1: repositories/resumable 启动副作用接入进程角色门禁** - `973e35988` (feat)
2. **Task 2: codegraph galaxy warm 与 orphan reconcile 接入进程角色门禁** - `418a0f590` (feat)
3. **Task 3: 进程角色门禁守护测试** - `81fd690b0` (test)

_注：本 plan 不写 STATE.md / ROADMAP.md（由 orchestrator 负责）。_

## Files Created/Modified
- `server/repositories/apps.py` — `ready()` 经 `should_run_startup_side_effects` 门禁 `_reset_stuck_indexing` 线程。
- `server/codegraph/apps.py` — 两处 `_schedule_*` 加 role 门禁（前于 argv 嗅探）；顺带修复 `_register_gopls_backend` 既有 ruff I001 导入排序。
- `server/resumable/apps.py` — `_schedule_recovery` 顶部加 role 门禁（前于 argv 嗅探）；handler 注册保留。
- `server/tests/durable/test_process_role.py` — 进程角色门禁守护测试（新建）。

## Decisions Made
- **门禁位置**：repositories 因无 argv 嗅探，门禁置于 `ready()` 入口；resumable/codegraph 门禁置于各 `_schedule_*` 入口、前于既有 argv 嗅探（role 显式入口优先、argv 兜底）。
- **注册与副作用解耦**：`register_default_handlers()`、volar/gopls backend 注册均为纯内存操作且所有角色都需要，故保持无条件执行，只对 DB 副作用（reconcile/sweep/recovery）加门禁。
- **测试不真跑副作用**：用 `mock.patch("threading.Thread")` 拦截线程构造来判定"是否调度"，web 分支用 `monkeypatch.setattr(sys, "argv", ["uvicorn"])` 绕过 pytest argv 兜底以验证执行路径；纯单元、不触达 Postgres。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] 修复 codegraph `_register_gopls_backend` 既有 ruff I001 导入排序**
- **Found during:** Task 2 commit（pre-commit 钩子对暂存文件跑 ruff）。
- **Issue:** `server/codegraph/apps.py` 的 `_register_gopls_backend` 存在既有 ruff `I001`（import block un-sorted，third-party `import structlog as _structlog` 与 first-party import 之间缺空行）。经 `git stash` 验证为本 plan 编辑前即存在的问题，且位于未被 60-02 改动的方法体内。
- **影响：** 仓库启用 pre-commit 钩子且禁用 `--no-verify`，该 I001 阻塞 `codegraph/apps.py` 的提交（验证命令 `ruff check codegraph/apps.py` 同样要求清零）。
- **Fix:** `ruff check --fix codegraph/apps.py` 仅在两条 import 间补一空行（单行变更，无逻辑改动）。
- **Files modified:** `server/codegraph/apps.py`
- **Commit:** `418a0f590`（随 Task 2）

## Issues Encountered

### pre-commit 钩子 stash 残留导致工作区未提交改动暂时丢失（已完整恢复）
- **现象：** Task 2 首次提交因 ruff I001 失败，仓库的 pre-commit 钩子（lefthook/lint-staged 范式）在校验前 `git stash` 了全部未暂存改动，校验失败后未自动恢复，留下一个 `stash@{0}`（含本 plan 的 codegraph 编辑 + 用户既有的 ~50 个未提交文件）。
- **处置：** 确认 `stash@{0}` 为权威 pre-commit 工作态后，将被钩子半途重生成、与 stash 冲突的 `web/src/auto-imports.d.ts` / `web/src/components.d.ts` 两个 typegen 产物 `git checkout HEAD --` 复位，再 `git stash pop` 完整恢复全部 56 项 tracked 改动（含 `RAGEnhancementSettings.vue` 删除、`useToolDisplay.ts` 的 `rerankInfo` 等用户改动）与 codegraph 门禁编辑。恢复后用户既有工作零丢失。
- **根因规避：** 修复阻塞性 I001 后，后续 Task 2/Task 3 提交钩子均正常 stash→校验→pop，无残留。

## Verification Results
- `uv run python manage.py check` → System check identified no issues（web 默认零回归）。
- `uv run ruff check repositories/apps.py codegraph/apps.py resumable/apps.py` → All checks passed。
- `uv run ruff check tests/durable/test_process_role.py` → All checks passed。
- `uv run pytest tests/durable/test_process_role.py -q` → **16 passed**。
- `uv run pytest tests/durable -q` → **31 passed**（15 旧 + 16 新），无 SocketBlockedError、不带 postgres_queue marker。

## Threat Model Compliance
- **T-60-03（worker/migrate 跑 web-only reconcile 误杀在途任务）→ mitigated：** 三处 DB 副作用经 `should_run_startup_side_effects` 门禁，`test_process_role.py` 守护 worker/migrate 短路（mock `threading.Thread` 断言未构造对应线程）。
- **T-60-04（role 误判致 web 也短路 → 僵尸 RUNNING 累积）→ mitigated：** 默认 role=web、allowed 默认 `{"web"}`，测试断言 web 执行 + handler/backend 注册与 role 无关。

## Known Stubs
None — 三处门禁均接真实 helper 与真实启动副作用，无占位/硬编码空值。

## Self-Check: PASSED
- `server/tests/durable/test_process_role.py`、`server/repositories/apps.py`、`server/codegraph/apps.py`、`server/resumable/apps.py` 均存在且含 `should_run_startup_side_effects`。
- 三个 task 提交（973e35988 / 418a0f590 / 81fd690b0）经 git log 确认存在。
- 未修改 STATE.md / ROADMAP.md。

---
*Phase: 60-durable*
*Completed: 2026-06-20*
