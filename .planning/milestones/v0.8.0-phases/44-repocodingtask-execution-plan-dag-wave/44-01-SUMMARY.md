---
phase: 44-repocodingtask-execution-plan-dag-wave
plan: 01
subsystem: database
tags: [django, orm, migration, dag, wave, repo-coding-task, delivery]

# Dependency graph
requires:
  - phase: 43-编码 env 对齐 + 通用 resume 回流地基
    provides: callback 驱动 resume 回流通路 + 编码 env 对齐（多 wave 调度前置地基）
  - phase: 37-canonical TechnicalPlan
    provides: PlanVersion 表（RepoCodingTask.plan_version FK 目标）
provides:
  - RepoCodingTask 操作态模型（plan_version FK / repository FK / wave int / depends_on M2M self DAG / status / produced_artifacts JSON / follow_openspec / attempt / error）
  - RepoCodingTaskStatus 枚举（4 态 pending→running→done|failed，无 stale）
  - delivery_repo_coding_task 表 + M2M through repo_coding_task_depends_on（迁移 0017）
  - barrel 导出 RepoCodingTask / RepoCodingTaskStatus
affects: [44-02 wave_layering, 44-03 RepoCodingTaskService, 44-04 wave_progression, 44-05 AICodingNode]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "操作态模型逐项镜像同 app 姊妹模型（RepoResearchTask → RepoCodingTask）"
    - "depends_on ManyToManyField('self', symmetrical=False) 承载有向 DAG 仓级边"
    - "模型层零业务方法（仅 __str__），守 INV-6 单一写入入口精神"

key-files:
  created:
    - server/delivery/models/repo_coding_task.py
    - server/delivery/migrations/0017_repocodingtask.py
    - server/tests/delivery/test_repo_coding_task_models.py
  modified:
    - server/delivery/models/__init__.py

key-decisions:
  - "plan_version 用真实 FK（on_delete=CASCADE，related_name=coding_tasks），区别于 PlanSession.current_plan_version 软 UUID 引用——本 phase 无 36↔37 迁移耦合约束"
  - "状态枚举去 stale（仅 4 态），编码期无重索引语义"
  - "depends_on related_name=dependents，symmetrical=False 保有向性"
  - "迁移用 makemigrations 自动生成（M2M self through 表须 Django 自动建），不手写 DDL"

patterns-established:
  - "RepoCodingTask 镜像 RepoResearchTask 形状（跨 app FK 字符串前向引用 / subagent_session SET_NULL / attempt+error 可靠恢复字段 / db_table+中文 verbose_name+indexes）"
  - "wave 调度 DAG 字段（wave / depends_on M2M self / produced_artifacts / follow_openspec）为后续 plan 02-05 提供持久化底座"

requirements-completed: [WAVE-01]

# Metrics
duration: 8min
completed: 2026-06-16
---

# Phase 44 Plan 01: RepoCodingTask 操作态模型 + 拓扑调度底座 Summary

**RepoCodingTask 操作态模型落库（plan_version FK + repository FK + wave/depends_on M2M self DAG + produced_artifacts/follow_openspec 预留位 + attempt/error 可靠恢复），4 态枚举无 stale，迁移 0017 自动生成且 makemigrations --check 干净，模型层零业务方法守 INV-6**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-06-16T12:15:00Z
- **Completed:** 2026-06-16T12:20:00Z
- **Tasks:** 3
- **Files modified:** 4（3 created + 1 modified）

## Accomplishments
- `RepoCodingTask` 模型 + `RepoCodingTaskStatus` 枚举逐项镜像 `RepoResearchTask` 形状，新增 wave 调度 DAG 字段（`wave` / `depends_on` M2M self / `produced_artifacts` / `follow_openspec`），drop `stale` 与 `routed_confidence`
- 迁移 `0017_repocodingtask` 由 `makemigrations` 自动生成（含 M2M self through 表 `repo_coding_task_depends_on` + 两条索引），dependencies 含 delivery 0016 + repositories 0036 + subagent 0013，`makemigrations --check` 干净、正向 `migrate` 成功
- 模型单测 4 组全绿：默认值 / db_table+枚举（无 stale）/ depends_on 有向 self-M2M / Meta 索引
- 模型层零业务方法（仅 `__str__`），为 plan 03 的 INV-6 grep 守护铺底

## Task Commits

Each task was committed atomically:

1. **Task 1: 创建 RepoCodingTask 模型 + 枚举 + barrel 导出** - `74eeb7a5` (feat)
2. **Task 2: [BLOCKING] makemigrations delivery → 0017** - `4ad5326a` (feat)
3. **Task 3: RepoCodingTask 模型单测** - `8f04e99d` (test)

## Files Created/Modified
- `server/delivery/models/repo_coding_task.py` - RepoCodingTask 模型 + RepoCodingTaskStatus 枚举（中文 docstring，模型层零业务方法）
- `server/delivery/models/__init__.py` - barrel 新增 RepoCodingTask / RepoCodingTaskStatus 导出（import 块 + `__all__`）
- `server/delivery/migrations/0017_repocodingtask.py` - delivery_repo_coding_task 表 DDL + M2M through + 两条索引（自动生成）
- `server/tests/delivery/test_repo_coding_task_models.py` - 4 组模型守护测试

## Decisions Made
- `plan_version` 用真实 FK（`on_delete=CASCADE`, `related_name="coding_tasks"`）——本 phase 无 36↔37 迁移耦合约束，区别于 `PlanSession.current_plan_version` 的软 UUID 引用
- 状态枚举 4 态（`pending/running/done/failed`），去 `stale`（编码期无重索引语义）
- `depends_on` 用 `ManyToManyField("self", symmetrical=False, related_name="dependents")` 保有向性
- 迁移用 `makemigrations` 自动生成（M2M self through 表须 Django 自动建），不手写 DDL

## Deviations from Plan

None - plan executed exactly as written.

（Task 3 标 `tdd="true"`，但模型实现是 Task 1 的前置产物，故 Task 3 为模型验证测试、写后即绿——非新增行为的 RED/GREEN 循环，符合 model-only 守护测试性质。）

## Issues Encountered
- 计划中 `uv run python -c "from delivery.models import ..."` 验证命令需先 `django.setup()`（Django settings 未配置时直接 import 报 ImproperlyConfigured）；改用 `DJANGO_SETTINGS_MODULE=friday.settings` + `django.setup()` 后通过——不影响产物。

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- RepoCodingTask 持久化底座就绪，可供 44-02（wave_layering 拓扑分层纯函数）、44-03（RepoCodingTaskService 单一写入入口 + INV-6 守护）、44-04（wave_progression 推进 helper）、44-05（AICodingNode wave 分批 dispatch）消费
- `produced_artifacts` / `follow_openspec` 字段已立但本 phase 不消费（Phase 45 / v0.9 才写内容）

## Self-Check: PASSED

- 3 created + 1 modified 文件均存在
- 3 task 提交均在 git history（74eeb7a5 / 4ad5326a / 8f04e99d）

---
*Phase: 44-repocodingtask-execution-plan-dag-wave*
*Completed: 2026-06-16*
