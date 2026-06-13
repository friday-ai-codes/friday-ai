---
phase: 18-engine
plan: 04
subsystem: api
tags: [workflow-engine, scheduler, callback-resume, reentry, mutex, deadlock, container-callback, pytest]

# Dependency graph
requires:
  - phase: 18-engine
    plan: 01
    provides: routing 五纯函数 + RoutingState + engine barrel 导出
  - phase: 18-engine
    plan: 02
    provides: 主循环 node_statuses/node_handles 状态映射 + conftest 引擎测试基建（waiting_*/branch workflow + 可控节点）
  - phase: 18-engine
    plan: 03
    provides: _finalize_run_state 单一收口（挂起>死锁>失败>完成）+ waiting 即挂起语义
provides:
  - "_continue_after_node 重入式薄入口：执行级原子抢锁 + 标记重跑 + 重建状态重入主循环——回调续跑与主循环字面同源（同一 while 调度循环 + 同一 _finalize_run_state 收口）"
  - "_rebuild_state_from_db：从 DB 真实 NE 状态重建调度集合（回调续跑 + paused-resume + _check_execution_complete 共用的唯一状态源）"
  - "_run_execution 增 rebuilt_state 形参：首跑/重入共用调度循环，首跑零行为变化"
  - "容器回调断裂链路（A1）修复：带 _resume_from_callback 标记且仍 WAITING_* 的节点经 _execute_node 重跑"
  - "coding_callback 第三套手工迷你调度器删除，三套回调收敛为一套统一入口"
  - "tolerated fallback 持久化到 NE.output_data（_tolerated 标记），重入可恢复 tolerated 语义"
affects: [18-05, 21-engine]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "重入续跑复用主循环：_run_execution(rebuilt_state=...) 覆盖首跑空集初始化，回调续跑/恢复与首跑共用同一 while 调度循环与收口（消除两套路由实现漂移的最终落点）"
    - "执行级原子抢锁互斥：仅 SUSPENDED 时 filter(status=SUSPENDED).aupdate(status=RUNNING)，rows==0 即 resume_lock_lost 放弃，防并发双循环"
    - "DB 状态→routing 集合的单一重建函数：COMPLETED/SKIPPED/FAILED(±tolerated)/WAITING_*/CANCELLED 各态映射 node_statuses，pending=无终态记录节点"

key-files:
  created: []
  modified:
    - server/workflows/engine/scheduler.py
    - server/subagent/api/callbacks.py
    - server/feishu/callbacks/coding_callback.py
    - server/tests/workflows/conftest.py
    - server/tests/workflows/test_engine_waiting.py
    - server/tests/workflows/test_engine_deadlock.py

key-decisions:
  - "不抽取独立 _run_scheduling_loop，改为 _run_execution 增 rebuilt_state 形参——避免 dedent ~290 行循环体、首跑零行为变化（同等满足'两路径字面同源'）"
  - "抢锁条件定稿：仅 entry==SUSPENDED 时原子抢锁；RUNNING/PENDING/PAUSED 放行（保留 approval_callback / feishu views / chat_question 等域外预翻转入口，不回退）"
  - "tolerated fallback 持久化键 _tolerated：写入 NE.output_data，重建时剥离该标记后入 node_outputs 与首跑内存值一致"
  - "_check_execution_complete 保留为兼容入口委托重建 + _finalize_run_state（test_hooks 外部消费）；_check_dependencies_ready 删除（无外部调用点）"

requirements-completed: [ENG-01, ENG-02, ENG-04]

# Metrics
duration: ~75min
completed: 2026-06-13
---

# Phase 18 Plan 04: 回调续跑重入主循环 + 执行级互斥 + 双路径同源 Summary

**`_continue_after_node` 退化为薄入口——执行级原子抢锁 → 带标记节点经 `_execute_node` 重跑（修复容器回调断裂 A1）→ `_rebuild_state_from_db` 重建真实 NE 状态重入 `_run_execution` 同一 while 调度循环与 `_finalize_run_state` 收口；coding_callback 第三套手工迷你调度器根除，三套回调收敛为一套统一入口。审计定性"两套路由实现漂移"最终消除。tests/workflows/ 419 例全绿、workflows+feishu+回调 519 例零回归。**

## Performance

- **Duration:** ~75 min
- **Completed:** 2026-06-13
- **Tasks:** 2
- **Files modified:** 6（0 新建 + 6 修改）

## Accomplishments

- `_continue_after_node` 重入式薄入口（签名不变，七条恢复入口零改动）：
  1. **执行级互斥**——先于任何节点重跑，仅 SUSPENDED 时原子抢锁 `filter(status=SUSPENDED).aupdate(status=RUNNING)`，抢锁失败即 `resume_lock_lost` 放弃，杜绝同一挂起执行被两回调起双循环（T-18-05）。
  2. **标记重跑（A1 修复）**——节点仍 WAITING_* 且带 `_resume_from_callback`/`_confirmed_branch_name` 恢复标记时，重置 RUNNING 经 `_execute_node` 重跑（复用重试/超时/on_error 全套）；无标记仍 WAITING → 还原挂起不空转。
  3. **重建重入**——`_rebuild_state_from_db` 重建真实状态集合 → `_run_execution(rebuilt_state=...)` 重入同一 while 调度循环 + `_finalize_run_state` 收口（恢复后残留纯死锁在此暴露转 FAILED）。
- `_run_execution` 增 `rebuilt_state` 形参：非 None 时覆盖首跑空集初始化与 `initial_outputs` 预填充——回调续跑/恢复与首跑共用同一调度循环，首跑分支零行为变化。
- `_rebuild_state_from_db`：DB NE 状态 → routing 调度集合的单一映射函数（COMPLETED/SKIPPED/FAILED±tolerated/WAITING_*/CANCELLED·TIMEOUT 各态，pending=无终态记录节点）。
- `resume_execution` 废弃 COMPLETED→SKIPPED 改写，改为按真实状态重建重入（与回调续跑同源）。
- `_execute_node` tolerated fallback 持久化（`_tolerated` 标记 + fallback 写入 NE.output_data）——重入重建据此恢复 tolerated 语义与下游可见 fallback 值。
- `coding_callback._schedule_branch_confirmation` 删除整段手工迷你调度器（手动重置 NE / 手工 `ExecutionContext` / 手工 execute / 手工复刻 `_next_handle` / SUSPENDED→RUNNING 翻转），改为写入 `_confirmed_branch_name` + `_resume_from_callback` 标记后调统一入口。
- `subagent callbacks._schedule_workflow_resume` 文档化：统一入口消费标记重跑节点（A1），不做手工状态翻转。

## Task Commits

每个任务原子提交（顺序执行，正常 git hooks，无 --no-verify）：

1. **Task 1: _continue_after_node 重入式重构 + 执行级互斥 + 旧判定退役** — `9b9a1054e` (feat)
2. **Task 2: 回调收敛统一续跑入口，删除 coding_callback 手工调度器** — `8a2cc297c` (feat)

## 统一续跑入口最终形态（_run_scheduling_loop 抽取与否）

**未抽取独立 `_run_scheduling_loop`。** 改为给 `_run_execution` 增 `*, rebuilt_state: dict | None` 形参：首跑（`rebuilt_state=None`）走空集初始化 + `initial_outputs` 预填充；回调续跑/恢复（`rebuilt_state` 非 None）用 `_rebuild_state_from_db` 重建集合覆盖。二者共用同一 `while pending_nodes:` 循环与 `_finalize_run_state` 收口。

**理由（结构性决策）：** 抽取独立循环方法需把约 290 行循环体整体 dedent 4 空格（高改动面、易引入缩进 bug、首跑可能行为漂移）。`rebuilt_state` 注入方案以最小 diff 同等满足"两路径字面同源"目标，且首跑分支逐字符不变（已由 tests/workflows/ 417 基线零回归坐实）。入口胶水 `_rebuild_and_run(execution, dag)` 供 `_continue_after_node`（await 同步续跑）与 `resume_execution`（`_run_in_thread`）共用。

## 抢锁条件最终定稿

```python
entry_status = execution.status  # 重载后
if entry_status in (COMPLETED, FAILED, CANCELLED, TIMEOUT):
    return                                   # 终态不续跑
if entry_status == SUSPENDED:
    rows = await WorkflowExecution.objects.filter(
        pk=..., status=SUSPENDED
    ).aupdate(status=RUNNING)
    if not rows:                             # 竞态：他人已抢到 SUSPENDED→RUNNING
        logger.info("resume_lock_lost", ...) # → 放弃（互斥）
        return
# else RUNNING/PENDING/PAUSED → 放行
```

**与计划字面表述的偏差（保兼容必要调整）：** 计划描述"总是尝试抢锁，rows==0 且 RUNNING → 放弃"。但代码库存在多处**域外入口**在调用 `_continue_after_node`/`approve_node` 前**已外部预翻转 SUSPENDED→RUNNING**：`feishu/callbacks/approval_callback.py:252`、`feishu/views.py:1013`、`feishu/callbacks/chat_question_callback.py:273`（均不在本计划 files_modified）。若对 entry==RUNNING 一律放弃，这些审批/问答续跑路径将全部回退。故定稿为：**仅 entry==SUSPENDED 时原子抢锁**（这是真实双回调竞态的形态——容器回调 / views skip_wait·trigger_resume 均不预翻转、留 SUSPENDED），entry==RUNNING/PENDING/PAUSED 放行（保留既有预翻转/inline 入口）。互斥保证对"同一挂起执行两回调到达"成立（一个抢到、另一个 `resume_lock_lost`），不回退任何域外入口。互斥**先于**标记重跑执行，确保节点重跑受锁保护。

## tolerated fallback 持久化键名

键名 **`_tolerated`（值 `True`）**，与 fallback 输出同写入 `NodeExecution.output_data`：

```python
fallback = node.fallback_values or {"status": "skipped", "output": {}}
tolerated_output = {**fallback, "_tolerated": True}
node_execution.output_data = tolerated_output  # amark_failed 后补 asave
```

重建时 `_rebuild_state_from_db` 对 FAILED 节点检测 `output_data.get("_tolerated")` → 归 `tolerated_failures` + `completed_nodes` + `STATUS_TOLERATED`，并**剥离 `_tolerated` 键**后入 `node_outputs`，与首跑内存 fallback 值字面一致（避免下游 collect_inputs 混入标记）。

## A1 红测验证过程（容器回调断裂修复）

按计划 TDD 红测先行：
1. **RED**：先写 `tests/workflows/test_engine_waiting.py::TestCallbackResume`（4 例）+ `test_engine_deadlock.py` 重建死锁兜底（1 例），对**未改造** scheduler 运行 → `test_dual_path_consistency` / `test_marked_node_rerun_fixes_broken_chain`（A1）/ `test_concurrent_resume_mutex_no_double_exec` / `test_reentry_pure_deadlock_after_cancelled_dep_fails` **4 失败**，`test_callback_resume_completes_downstream` 1 通过（旧 `_continue_after_node` 对"已完成节点放行下游"恰好可工作）。Test 3 坐实 A1：标记节点未重跑（`_exec_count==1`）、下游 PENDING 不执行。
2. **GREEN**：实现重入式 `_continue_after_node` 后全 18 例（waiting 9 + deadlock 9）绿。新增 `ResumableWaitEventNode`（首次 waiting_event，带 `_resume_from_callback` 标记时 completed）模拟 ai_coding 消费标记重跑范式。

因顺序执行 + 每任务原子提交，红→绿在本机验证后单提交（test+impl 同提交 `9b9a1054e`），未拆分独立 test/feat 红绿提交对。

## _check_execution_complete 外部调用点处理方式（18-05 / Phase 21 消费）

- `_check_dependencies_ready`（COMPLETED-only 判定，Pitfall 4 根因）**删除**——重入式续跑后无任何调用点（`rg` 全仓确认仅旧 `_continue_after_node` 递归骨架引用，已随骨架移除）。
- `_check_execution_complete` **保留为兼容入口**，重写为委托 `_rebuild_state_from_db` + `_finalize_run_state`（仅当无 pending/waiting 活跃节点时收口，保留原 all-done 语义）。外部调用点 `tests/workflows/test_hooks.py`（直接调本方法的两例：FAILED→execution_failed、COMPLETED→execution_completed）零改动通过。`workflows/api/views.py` 等回调入口已统一走 `_continue_after_node`，不再直调本方法。18-05/Phase 21 若需完成判定可继续复用此委托入口或直接调 `_finalize_run_state`。

## Decisions Made

- **rebuilt_state 注入而非 _run_scheduling_loop 抽取**：见上"统一续跑入口最终形态"。
- **抢锁仅在 SUSPENDED 时尝试**：见上"抢锁条件最终定稿"——保兼容域外预翻转入口的必要调整。
- **Test 4 互斥用终态守卫断言**：单线程顺序执行无法复现"entry==SUSPENDED 但 aupdate rows==0"的真实竞态丢锁（重载后 DB 即真值），故 Test 4 以"两次续跑节点恰重跑一次（第二次 entry 终态放弃）"断言可观测的反双执行属性（T-18-05 安全语义）；`resume_lock_lost` 给弃分支由代码 + 该断言覆盖。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - 阻塞] 抢锁条件适配域外预翻转入口，避免审批/问答续跑回退**
- **Found during:** Task 1（设计执行级互斥时核查 `_continue_after_node` 七条调用点状态）
- **Issue:** 计划字面"rows==0 且 RUNNING → 放弃"会令 `approval_callback`/`feishu/views`/`chat_question_callback`（均在 `_continue_after_node`/`approve_node` 前预翻转 SUSPENDED→RUNNING，且均不在本计划 files_modified）续跑全部放弃回退
- **Fix:** 抢锁仅在 entry==SUSPENDED 时原子尝试；RUNNING/PENDING/PAUSED 放行。互斥对真实双回调竞态（均留 SUSPENDED）仍成立，零回退域外入口
- **Files modified:** server/workflows/engine/scheduler.py
- **Commit:** `9b9a1054e`

**2. [Rule 3 - 阻塞] callbacks.py 预存 ruff format 长行重排（满足验证 format 门禁）**
- **Found during:** Task 2 验证（`ruff format --check subagent/api/callbacks.py` 是计划 `<verification>` 门禁项）
- **Issue:** `subagent/api/callbacks.py` 含多处预存超长 `if` 单行，`ruff format --check` 报需重排
- **Fix:** 对本计划已修改的 `callbacks.py` 执行 `ruff format`（机械换行，无逻辑变更），使验证门禁绿
- **Files modified:** server/subagent/api/callbacks.py
- **Commit:** `8a2cc297c`

**Total deviations:** 2 阻塞修复（Rule 3），0 功能偏差、0 架构变更。

## Deferred Issues

- **预存 ruff check lint（范围外，未触碰）**：`uv run ruff check workflows/ subagent/ feishu/` 报 12 处错误，全部位于本计划未修改文件（`feishu/bot/service.py`、`workflows/api/analytics.py`、`workflows/api/permissions.py`、`workflows/hooks/builtin.py`、`workflows/migrations/0025_alert_rules.py`、`workflows/nodes/ai/delivery_knowledge_search.py`、`workflows/nodes/control/loop.py`）。按 SCOPE BOUNDARY 不予修复。本计划修改的 6 个文件 `ruff check` 与 `ruff format --check` 全绿。

## Issues Encountered

- 计划 verify 命令引用 `tests/subagent/` 目录不存在——subagent 回调测试实际散落在 `tests/` 根（`test_callbacks_cross_repo_relevance.py`、`test_repo_summary_callback.py`），已纳入验证。
- `uv run` 偶发重排 `server/uv.lock`：本计划零新依赖，每次提交前 `git checkout -- uv.lock` 还原，最终 uv.lock 无 diff。

## Threat Surface

- **T-18-05（并发续跑双循环 / 重复执行节点·发卡·dispatch）已缓解**：执行级原子抢锁 `filter(status=SUSPENDED).aupdate(status=RUNNING)`，互斥先于标记重跑；Test 4 断言两次续跑节点恰重跑一次，`resume_lock_lost` 可审计。
- **T-18-06（伪造回调推进他人执行）accept**：既有回调鉴权（CONTAINER_CALLBACK_TOKEN / 飞书验签 / IsAuthenticated）不动，本计划所有 `_continue_after_node` 调用方均在鉴权后，不新增任何 API 面。
- **T-18-SC（包安装）accept**：零新依赖。
- 死锁诊断信息泄露防线沿用 18-01/03：重建路径死锁经 `routing.diagnose_deadlock`（签名不接收 node_outputs）→ `_finalize_run_state` 写结构化 error_message，零输出值泄露。

## Next Phase Readiness

- 18-05（trigger_data 注入）可在统一 `_continue_after_node`/`_run_execution` 路径上直接消费，重入续跑天然继承 `execution.trigger_data`。
- 容器回调（ai_coding）断裂链路已修复——A1 在运行环境可经"标记 → 统一入口重跑节点"自动续跑（静态分析断裂结论已由 Test 3 红→绿坐实）。
- 三套回调（agent_tasks / 容器 callbacks / coding_callback 分支确认）收敛为一套 `_continue_after_node` 入口，后续新增恢复入口零再设计。

## Self-Check: PASSED

- 6 个修改文件 + SUMMARY.md 均存在于磁盘
- 两个任务提交 `9b9a1054e` / `8a2cc297c` 均可达
- `tests/workflows/` 419 例全绿（含本计划新增 5：CallbackResume 4 + 重建死锁兜底 1）；workflows + feishu + 回调 519 例零回归；resume/approve 调用点 66 例绿
- 修改的 6 个文件 ruff format --check + ruff check 全绿；`rg "ExecutionContext\(" coding_callback.py` 零命中、scheduler 抢锁 `aupdate(status=` 命中、`_check_dependencies_ready` 零命中、scheduler 导入函数体内延迟；`server/uv.lock` 无 diff

---
*Phase: 18-engine*
*Completed: 2026-06-13*
