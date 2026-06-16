---
phase: 44-repocodingtask-execution-plan-dag-wave
plan: 03
subsystem: api
tags: [service, inv-6, single-write-entry, idempotent, wave, depends-on, repo-coding-task, delivery]

# Dependency graph
requires:
  - phase: 44-01 RepoCodingTask 操作态模型
    provides: RepoCodingTask 表 + RepoCodingTaskStatus 枚举 + wave/depends_on M2M self DAG 持久化底座
  - phase: 44-02 wave_layering 拓扑分层纯函数
    provides: build_repo_waves / build_repo_dep_edges（本 service 消费其 {repo_id: wave} 与 {repo_id: [dep_repo_id]}）
provides:
  - RepoCodingTaskService 单一写入入口（INV-6）——RepoCodingTask 建表/状态推进/wave/depends_on 落库唯一收口
  - create_tasks_for_plan(plan_version, repo_waves, repo_dep_edges)：幂等 get_or_create + wave 回填 + depends_on M2M 连边
  - mark_running / mark_done / mark_failed / mark_blocked 子任务级状态推进（mark_done/blocked 条件更新幂等）
  - INV-6 grep 守护测试（断言除 service 外无旁路写 RepoCodingTask）
  - barrel 导出 delivery.services.RepoCodingTaskService
affects: [44-04 wave_progression（经 service 回填终态/阻断下游）, 44-05 AICodingNode（首发 dispatch 后 mark_running）]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "单一写入入口逐项镜像 ResearchService（RepoCodingTask 专用，去调研专属方法）"
    - "M2M depends_on.set(...) 在 @sync_to_async 同步块内执行，避免 async lazy 访问"
    - "幂等优先条件 .filter(status=...).update(...) + 影响行数判定，重复 callback no-op"
    - "INV-6 grep 守护：源码扫描断言无旁路 .objects.<write>/实例化/save"

key-files:
  created:
    - server/delivery/services/repo_coding_task_service.py
    - server/tests/delivery/test_repo_coding_task_inv6_guard.py
    - server/tests/delivery/test_repo_coding_task_service.py
  modified:
    - server/delivery/services/__init__.py

key-decisions:
  - "create_tasks_for_plan 返回 {repository_id: task} dict（按仓可索引，便于 44-04/05 调用方按仓取 task）"
  - "已存在 task 仅 wave 漂移时回填（task.wave != wave 才 save），幂等不无谓写库"
  - "depends_on 仅连同 plan_version 下已建 task（dep_repo_ids 中不在本批的引用过滤），M2M set 在同步块内"
  - "mark_done 仅 running→done 条件更新；mark_blocked 仅 pending→failed 条件更新——已运行/终态不强翻，保在途结果不被覆盖"
  - "mark_blocked error 结构 {reason: upstream_failed, upstream: [...]} 承载 WAVE-02 下游阻断语义"

patterns-established:
  - "RepoCodingTaskService 为 44-04 wave 推进/44-05 节点 dispatch 提供唯一写入口（状态/wave/边只经此）"
  - "INV-6 单模型 grep 守护范式可直接复用于后续操作态模型 service"

requirements-completed: [WAVE-01, WAVE-02]

# Metrics
duration: 7min
completed: 2026-06-16
---

# Phase 44 Plan 03: RepoCodingTaskService 单一写入入口 Summary

**立 `RepoCodingTaskService` 单一写入入口（INV-6）——消费 44-02 拓扑分层结果，`create_tasks_for_plan` 幂等 get_or_create + 写 wave + 同步块内 `depends_on.set(...)` 连仓级 DAG 边；`mark_running/done/failed/blocked` 状态推进，`mark_done`（仅 running→done）/`mark_blocked`（仅 pending→failed）用条件更新 + 影响行数判定保重复 callback no-op；`mark_blocked` 承载 WAVE-02 下游阻断（`error={"reason":"upstream_failed","upstream":[...]}`）；配 INV-6 grep 守护断言除 service 外无旁路写表**

## Performance

- **Duration:** ~7 min
- **Started:** 2026-06-16T12:28:00Z
- **Completed:** 2026-06-16T12:35:00Z
- **Tasks:** 3
- **Files modified:** 4（3 created + 1 modified）

## Accomplishments
- `RepoCodingTaskService` 五写入方法齐备：`create_tasks_for_plan`（幂等 + wave + depends_on M2M）、`mark_running`、`mark_done`、`mark_failed`、`mark_blocked`，所有 ORM 写经 `@sync_to_async _xxx_sync` 桥接
- `create_tasks_for_plan` 消费 44-02 `{repo_id: wave}` / `{repo_id: [dep_repo_id]}`：`get_or_create(plan_version, repository_id)` 幂等，已存在仅 wave 漂移时回填，**同步块内** `depends_on.set(...)` 连仓级 DAG 边（避免 async lazy 访问）
- `mark_done` 条件更新仅 running→done、`mark_blocked` 条件更新仅 pending→failed——影响行数 0 即 no-op，承载重复 callback 幂等与「已运行/终态不强翻」语义
- INV-6 grep 守护测试镜像 `test_research_inv6_guard.py`（单模型 `RepoCodingTask`，`_ALLOWED_WRITER` 指向 service），扫 `server/` 源码断言无旁路写；正则天然排除 `RepoCodingTaskStatus(` 枚举用法
- service 行为单测 6 组全绿：创建幂等（wave + 边）/ mark_done 幂等 / mark_done guard / mark_blocked 结构 / mark_blocked guard（running 不翻）/ mark_failed 包装

## Task Commits

Each task was committed atomically:

1. **Task 1: RepoCodingTaskService 单一写入入口 + barrel 导出** - `b053104d` (feat)
2. **Task 2: INV-6 grep 守护断言无旁路写 RepoCodingTask** - `37f44ebc` (test)
3. **Task 3: service 状态推进 + 幂等单测** - `8503a6ba` (test)

## Files Created/Modified
- `server/delivery/services/repo_coding_task_service.py` - RepoCodingTaskService 五写入方法（中文 docstring，`@sync_to_async` 桥接，条件更新幂等，ruff line 100）
- `server/delivery/services/__init__.py` - barrel 新增 `RepoCodingTaskService` 导出（import 块 + `__all__`）
- `server/tests/delivery/test_repo_coding_task_inv6_guard.py` - INV-6 grep 守护（源码扫描，2 测）
- `server/tests/delivery/test_repo_coding_task_service.py` - service 行为单测（async + django_db，6 测）

## Decisions Made
- `create_tasks_for_plan` 返回 `{repository_id: task}` dict（按仓可索引，便于 44-04/05 按仓取 task）
- 已存在 task 仅 `wave` 漂移时回填（`task.wave != wave` 才 `save`），避免无谓写库
- `depends_on` 仅连同 plan_version 下已建 task（过滤 `dep_repo_ids` 中不在本批的引用），M2M `set` 在同步块内
- `mark_done` 仅 running→done、`mark_blocked` 仅 pending→failed 条件更新——已运行/终态不强翻，保在途结果不被覆盖
- `mark_blocked` error 结构 `{"reason":"upstream_failed","upstream":[...]}` 承载 WAVE-02 下游阻断

## Deviations from Plan

None - plan executed exactly as written.

（Task 3 标 `tdd="true"`，但 service 实现是 Task 1 的前置产物，故 Task 3 为写后即绿的行为守护测试——非新增行为的 RED/GREEN 循环，对齐 44-01/44-02 范式。额外补 `test_mark_blocked_guard_running`（running task mark_blocked no-op）巩固「不强翻在途」语义，属 Rule 2 补全关键守护。）

## Issues Encountered
- service import 烟测需先 `DJANGO_SETTINGS_MODULE=friday.settings` + `django.setup()`（barrel 链式 import 触达 Django 模型）——不影响产物，pytest 经已配 settings 正常运行。

## Threat Model Compliance
- **T-44-INV6**（旁路写 RepoCodingTask）：INV-6 grep 守护测试扫 `server/` 源码断言除 `repo_coding_task_service.py` 外无 `.objects.<write>`/实例化/save，全绿。
- **T-44-IDEM-DUP**（重复 callback 重复推进）：`mark_done`/`mark_blocked` 条件 `.filter(status=...).update(...)` + 影响行数判定，重复调用 no-op，单测 `test_mark_done_idempotent`/`test_mark_done_guard`/`test_mark_blocked_guard_running` 覆盖。

## Next Phase Readiness
- RepoCodingTaskService 单一写入入口就绪，可供 44-04（wave_progression 经 service 回填终态/阻断下游）、44-05（AICodingNode 首发 dispatch 后 mark_running）消费
- 状态/wave/depends_on 落库收口于本 service，后续 plan 不得旁路写表（INV-6 守护断言保障）

## Self-Check: PASSED

- 3 created + 1 modified 文件均存在
- 3 task 提交均在 git history（b053104d / 37f44ebc / 8503a6ba）
- service 6 测 + INV-6 守护 2 测全绿（8 passed）；ruff 通过；barrel 可导入 RepoCodingTaskService

---
*Phase: 44-repocodingtask-execution-plan-dag-wave*
*Completed: 2026-06-16*
