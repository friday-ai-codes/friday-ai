---
phase: 44-repocodingtask-execution-plan-dag-wave
plan: 02
subsystem: api
tags: [dag, topological-sort, graphlib, wave, plan-orchestration, pure-function]

# Dependency graph
requires:
  - phase: 40-架构师融合 + MergedPlan + PlanValidator + 跨仓依赖
    provides: plan_validator.validate_plan（dependency_cycle 三色 DFS 环检测，复用不重写）
  - phase: 44-01 RepoCodingTask 操作态模型
    provides: RepoCodingTask.wave / depends_on M2M self DAG 持久化底座（本 plan 产分层结果待 plan 03 写入）
provides:
  - build_repo_waves(execution_plan) -> ({repo_id: wave}, cycle_report|None) 拓扑分层纯函数
  - build_repo_dep_edges(execution_plan) -> {repo_id: [dep_repo_id]} 仓级跨仓边投影纯函数
  - barrel 导出 services.plan_orchestration.build_repo_waves / build_repo_dep_edges
affects: [44-03 RepoCodingTaskService.create_tasks_for_plan, 44-05 AICodingNode wave 分批 dispatch]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "拓扑分层纯函数：graphlib.TopologicalSorter Kahn 分层（边方向 = task→其依赖 task，依赖先行）"
    - "环检测复用 plan_validator.validate_plan（不重写），仅取 dependency_cycle 项 fail-fast"
    - "半可信 execution_plan 防御逐字对齐 plan_validator（.get(...) or []、.get('repository_id','')、缺 id 跳过、无效引用过滤、绝不抛）"
    - "dependencies 解析为 task id（schema 权威）→ 投影仓级 wave/边；同仓自环去除"

key-files:
  created:
    - server/services/plan_orchestration/wave_layering.py
    - server/tests/services/plan_orchestration/test_wave_layering.py
  modified:
    - server/services/plan_orchestration/__init__.py

key-decisions:
  - "顶部 import plan_validator（叶子模块，无 import 环风险）做权威环检测，不在 wave_layering 内重写 DFS"
  - "TopologicalSorter prepare/get_ready 兜底 try/except CycleError（理论不可达，validate_plan 已前置拦截）保 fail-safe 永不抛"
  - "仓 wave = 该仓所有 task 拓扑层级 max（保证依赖满足）；空依赖退化全 wave 0（零回归命门）"
  - "build_repo_dep_edges 仅跨仓成边（ra and rb and ra != rb），去同仓自环，返回 sorted 稳定有序"

patterns-established:
  - "wave_layering.py 为 plan_orchestration 新增纯函数模块（无 IO/无 ORM/无 LLM），可与模型层并行开发"
  - "task-id DAG → 仓级投影：先建 task_repo 映射、再 Kahn 分层、最后按仓取 max / 跨仓成边"

requirements-completed: [WAVE-01]

# Metrics
duration: 6min
completed: 2026-06-16
---

# Phase 44 Plan 02: wave_layering 拓扑分层纯函数 Summary

**把 `MergedPlan.execution_plan[].dependencies`（task id 引用）真正消费——graphlib Kahn 分层建 task-id DAG → 投影仓级 wave（同仓取 max）+ 跨仓 depends_on 边（去自环），复用 `plan_validator.validate_plan` 做 dependency_cycle fail-fast，空依赖退化单 wave 全并行（零回归）**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-06-16T12:22:43Z
- **Completed:** 2026-06-16T12:28:00Z
- **Tasks:** 2
- **Files modified:** 3（2 created + 1 modified）

## Accomplishments
- `build_repo_waves(execution_plan)` —— 建任务级 DAG（`task → 它依赖的 task`，仅保留指向已知 task 的有效引用），用 `graphlib.TopologicalSorter` Kahn 分层得每 task 层级，仓 wave 取该仓所有 task 层级 **max**；空依赖 → 所有仓 `wave=0`（零回归命门）
- `build_repo_dep_edges(execution_plan)` —— `taskA` 依赖 `taskB` → `repo(A)` 依赖 `repo(B)`，仅跨仓成边（`ra and rb and ra != rb`），去同仓自环，返回 `{repo_id: sorted(dep_repo_ids)}` 稳定有序
- 环检测**复用** `plan_validator.validate_plan`（三色 DFS + 显式栈防递归 DoS），仅取 `dependency_cycle` 项 → 非空则 fail-fast 返回 `({}, {"reason": "dependency_cycle", "detail": [...]})`，不分层
- 半可信 `execution_plan` 防御逐字对齐 `plan_validator`（`.get(...) or []`、`.get("repository_id", "")`、缺 id 跳过、无效引用过滤、绝不 eval/不抛）
- 5 场景单测全绿：空依赖零回归 / 线性链 / 菱形 / 环 fail-fast / 同仓 max

## Task Commits

Each task was committed atomically:

1. **Task 1: build_repo_waves + build_repo_dep_edges 纯函数 + barrel 导出** - `3c2e7b92` (feat)
2. **Task 2: 拓扑分层单测（空/线性/菱形/环/同仓 max）** - `7e5b0847` (test)

**Plan metadata:** _(见 final docs commit)_

## Files Created/Modified
- `server/services/plan_orchestration/wave_layering.py` - `build_repo_waves` + `build_repo_dep_edges` 拓扑分层纯函数（中文 docstring，复用 validate_plan 环检测，ruff line 100）
- `server/services/plan_orchestration/__init__.py` - barrel 新增 `build_repo_waves` / `build_repo_dep_edges` 导出（import 块 + `__all__`）
- `server/tests/services/plan_orchestration/test_wave_layering.py` - 5 组拓扑分层守护测试（纯函数，无 `django_db`）

## Decisions Made
- 顶部 `from services.plan_orchestration.plan_validator import validate_plan`——`plan_validator` 是叶子模块（无反向依赖），顶部 import 无环风险；环检测复用其权威实现，不在 `wave_layering` 内重写 DFS
- `TopologicalSorter.prepare()` 外层兜底 `try/except CycleError` 返回同形 `dependency_cycle` 报告——理论不可达（`validate_plan` 已前置拦截相同边集），belt-and-suspenders 保 fail-safe 永不抛
- 仓 wave = 该仓所有 task 拓扑层级 **max**（保证仓内最深依赖也满足）
- `build_repo_dep_edges` 用 `set` 去重 + `sorted` 稳定输出，仅跨仓成边去同仓自环

## Deviations from Plan

None - plan executed exactly as written.

（Task 2 标 `tdd="true"`，但两纯函数是 Task 1 的前置产物，故 Task 2 为写后即绿的守护测试——非新增行为的 RED/GREEN 循环，符合纯函数守护测试性质，对齐 44-01 model-only 测试范式。）

## Issues Encountered
- 内联导入烟测需先 `DJANGO_SETTINGS_MODULE=friday.settings` + `django.setup()`（barrel `__init__.py` 链式 import 触达 Django 模型相关模块）；纯函数本身不依赖 Django，单测经 pytest（已配 settings）正常运行——不影响产物。

## Next Phase Readiness
- 拓扑分层纯函数就绪，可供 44-03（`RepoCodingTaskService.create_tasks_for_plan` 消费 `{repo_id: wave}` 与 `{repo_id: [dep_repo_id]}` 落 `RepoCodingTask.wave` + `depends_on`）、44-05（AICodingNode 首发 wave 0）消费
- `build_repo_waves` 第二返回值 `cycle_report` 供调用方在建 task 前 fail-fast（环方案不落库）

## Self-Check: PASSED

- 2 created + 1 modified 文件均存在
- 2 task 提交均在 git history（3c2e7b92 / 7e5b0847）
- 5 拓扑分层测试全绿；ruff 通过；barrel 可导入两函数

---
*Phase: 44-repocodingtask-execution-plan-dag-wave*
*Completed: 2026-06-16*
