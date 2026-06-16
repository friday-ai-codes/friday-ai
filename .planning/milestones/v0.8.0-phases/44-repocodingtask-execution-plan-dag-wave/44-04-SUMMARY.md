---
phase: 44-repocodingtask-execution-plan-dag-wave
plan: 04
subsystem: api
tags: [wave, dag, transitive-closure, bfs, liveness, idempotent, resume, plan-orchestration, inv-6]

# Dependency graph
requires:
  - phase: 44-01 RepoCodingTask 操作态模型
    provides: RepoCodingTask 表 + RepoCodingTaskStatus 枚举 + wave/depends_on M2M self DAG + dependents 反向边
  - phase: 44-03 RepoCodingTaskService 单一写入入口
    provides: mark_done/mark_failed/mark_blocked 条件更新幂等 + create_tasks_for_plan（本 helper 经其回填终态/阻断下游）
  - phase: 43-02 入口无关续驱 helper
    provides: adrive_plan_session_to_pause_or_terminal 范式（入口无关、状态只经 service、不造两套）
provides:
  - acurrent_wave_all_terminal(plan_version_id, wave)：指定 wave 全终态(done|failed)判定，仅对 RUNNING 在途 wave 求值
  - aadvance_coding_waves(plan_version_id, *, service=None)：入口无关 wave 推进续驱（回填→传递闭包阻断→决策出口）
  - 传递闭包 BFS/worklist 下游阻断（多跳，含 seen 去重），liveness 守护防死锁
  - wave gate/失败隔离/下游阻断(含 2 跳)/幂等/全终态收尾 6 场景单测
affects: [44-05 AICodingNode（resume 段消费 aadvance_coding_waves：判 gate→推下一 wave 或收尾）]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "入口无关推进 helper 镜像 resume.py「不造两套」+ research_aggregation barrier 全终态判定"
    - "严格执行序（回填→传递闭包阻断→决策出口）：阻断在任何 early-return 之前完成（liveness 关键）"
    - "传递闭包 BFS/worklist 沿 dependents 反向边多跳阻断（seen 去重防环重入）"
    - "等待判定 keys off RUNNING 在途（aexists），不靠最小 pending wave（防抢先 return waiting 死锁）"
    - "状态只经 RepoCodingTaskService.mark_*（INV-6），async ORM *_id 标量/afirst/aexists/async for 安全"

key-files:
  created:
    - server/services/plan_orchestration/wave_progression.py
    - server/tests/services/plan_orchestration/test_wave_progression.py
  modified:
    - server/services/plan_orchestration/__init__.py

key-decisions:
  - "执行序固定「回填→传递闭包阻断→决策出口」——阻断必须在任何 early-return 前完成，否则未派发 pending 下游永不阻断→all_terminal 永不触发→死锁（T-44-DEADLOCK）"
  - "等待判定以 status=RUNNING 的 aexists() 为准，不对最小 pending wave 调 acurrent_wave_all_terminal（后者仅供 RUNNING 在途 wave 求值/barrel/测试复用）"
  - "下游阻断为传递闭包 BFS：worklist 初始全 failed task，弹出后沿 dependents 标 pending 下游 blocked 并入队继续传播，seen 去重；链 A→B→C 单次 aadvance 内 B、C 同时 blocked"
  - "回填终态按服务端权威 SubAgentSession.status（completed→done；error/timeout/cancelled→failed；pending/running→跳过等下次回调），经 subagent_session_id 标量取（T-44-TAMPER）"
  - "dispatchable = pending 且 depends_on.exclude(status=done).aexists() 为 False；阻断后残留 pending 上游只可能 done/pending/running（failed 已阻断），DAG 必有 source→无死锁"

patterns-established:
  - "wave 推进 helper 入口无关、DB 重算（不读内存）、由 callback 触发节点重入自驱（对齐 Phase 43 闭环，不新建调度循环/轮询）"
  - "传递闭包阻断 + 等待 keys off RUNNING 的 liveness 范式可复用于后续 barrier 类收尾逻辑"

requirements-completed: [WAVE-02]

# Metrics
duration: 8min
completed: 2026-06-16
---

# Phase 44 Plan 04: 入口无关 wave 推进 helper Summary

**立 `wave_progression.py` 入口无关 wave 推进续驱——`aadvance_coding_waves` 严格按「① 回填 running→终态（按服务端权威 `SubAgentSession.status`）→ ② 传递闭包 BFS/worklist 沿 `dependents` 多跳阻断全部 failed 上游的下游 → ③ 决策出口（RUNNING 在途→waiting / 有 depends_on 全 done 的 pending→dispatch 最小 wave / 无 pending 无 running→all_terminal）」执行；阻断在任何 early-return 之前完成是 liveness 关键（链 A→B→C 单次内 B、C 全 blocked → 收尾可达不死锁，T-44-DEADLOCK）；状态只经 `RepoCodingTaskService` 条件更新幂等（INV-6），复用 Phase 43 callback 驱动 resume 不造两套**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-06-16T12:37:00Z
- **Completed:** 2026-06-16T12:45:00Z
- **Tasks:** 2
- **Files modified:** 3（2 created + 1 modified）

## Accomplishments
- `acurrent_wave_all_terminal(plan_version_id, wave)`：镜像 `aall_research_tasks_terminal`，存在 pending/running 即非终态、取反返回（终态含 failed，避免失败仓永挂 T-44-GATE）；仅供 RUNNING 在途 wave 求值
- `aadvance_coding_waves(plan_version_id, *, service=None)`：入口无关续驱，严格序「回填→传递闭包阻断→决策出口」，返回 `{"waiting": True}` / `{"dispatch": [...], "wave": n}` / `{"all_terminal": True}` 互斥三态
- 回填段按服务端权威 `SubAgentSession.status`（经 `subagent_session_id` 标量取，绝不裸访问 lazy-FK）经 `service.mark_done`/`mark_failed` 回填，非终态跳过等下次回调
- 下游阻断为**传递闭包** BFS/worklist：沿 `dependents` 反向边多跳传播，`seen` 去重防重入；2 跳链 A→B→C 中 A failed 时 B、C 在单次 aadvance 内均被标 blocked（C 不残留 pending → 收尾可达）
- 决策出口：等待判定 keys off `status=RUNNING` 的 `aexists()`（不靠最小 pending wave 防抢先 return waiting 死锁）；dispatch 取 `depends_on` 全 done 的最小 wave pending 批；无 pending 无 running → all_terminal
- barrel 导出两 helper；6 场景单测全绿（gate/失败隔离/单跳下游阻断/2 跳传递闭包 liveness/幂等/全终态收尾）

## Task Commits

Each task was committed atomically:

1. **Task 1: acurrent_wave_all_terminal + aadvance_coding_waves 入口无关 helper + barrel 导出** - `bb2b1375` (feat)
2. **Task 2: wave 推进单测（gate/失败隔离/下游阻断/2 跳传递闭包/幂等/全终态）** - `46c7ea8f` (test)

## Files Created/Modified
- `server/services/plan_orchestration/wave_progression.py` - 两 helper + 3 私有子步骤（`_backfill_running_terminal` / `_block_downstream_transitive` / `_collect_dispatchable_pending`），中文 docstring，lazy import 规避环，ruff line 100
- `server/services/plan_orchestration/__init__.py` - barrel 新增 `acurrent_wave_all_terminal` / `aadvance_coding_waves` 导出（import 块 + `__all__`）
- `server/tests/services/plan_orchestration/test_wave_progression.py` - 6 场景行为单测（async + django_db transaction=True）

## Decisions Made
- 执行序固定「回填→传递闭包阻断→决策出口」：阻断必须在任何 early-return 前完成（liveness 关键防死锁）
- 等待判定以 `status=RUNNING` 的 `aexists()` 为准，不对最小 pending wave 调 `acurrent_wave_all_terminal`（后者仅供 RUNNING 在途 wave / barrel / 测试 / plan 05 复用）
- 下游阻断为传递闭包 BFS（worklist + seen 去重），非单跳：链 A→B→C 单次内全阻断
- 回填按服务端权威 `SubAgentSession.status`（completed→done；error/timeout/cancelled→failed；其余在途跳过），经 `subagent_session_id` 标量取（T-44-TAMPER）
- 幂等单测以 `updated_at` 不变断言 `mark_done` 条件更新只生效一次（重复 aadvance no-op）

## Deviations from Plan

None - plan executed exactly as written.

（Task 2 标 `tdd="true"`，但实现是 Task 1 前置产物，故 Task 2 为写后即绿的行为守护测试——非新增行为的 RED/GREEN 循环，对齐 44-01/44-02/44-03 范式。本 plan 仅立入口无关 helper，**不**接入 callback——callback 接线（AICodingNode resume 段消费 `aadvance_coding_waves`）归 plan 05，与 plan objective「为 plan 05 提供入口无关逻辑」一致。）

## Issues Encountered
None - 烟测（import + ruff）+ 6 单测一次通过。

## Threat Model Compliance
- **T-44-DEADLOCK**（间接下游残留 pending → all_terminal 永不触发死锁）：下游阻断为传递闭包 BFS/worklist 多跳，阻断在任何 early-return 前完成；`test_downstream_blocked_transitive_2hop` 守护 liveness（A→B→C 单次全 blocked + all_terminal）。
- **T-44-GATE**（gate 用「全 done」因 failed 永挂）：`acurrent_wave_all_terminal` 终态含 failed；`aadvance_coding_waves` 等待 keys off RUNNING 在途、收尾在无 pending 无 running 时触发。
- **T-44-IDEM**（重复回调重复推进）：状态只经 service 条件更新（重复 no-op）+ wave 从 DB 重算非内存态；`test_idempotent` 以 `updated_at` 不变守护。
- **T-44-TAMPER**（wave 归属/终态判定）：回填按服务端权威 `SubAgentSession.status`（`subagent_session_id` 标量取），推进范围限本 `plan_version_id`。

## Next Phase Readiness
- `aadvance_coding_waves` 入口无关推进 helper 就绪，可供 44-05 AICodingNode resume 段消费（判 gate → 推下一 wave dispatch 或收尾 all_terminal），由 Phase 43 callback `_schedule_workflow_resume` 触发节点重入自驱（不造两套）
- wave gate / 失败隔离 / 传递闭包下游阻断 / 幂等 / 全终态收尾均经单测守护；状态写入收口于 RepoCodingTaskService（INV-6）

## Self-Check: PASSED

- 2 created + 1 modified 文件均存在
- 2 task 提交均在 git history（bb2b1375 / 46c7ea8f）
- 6 单测全绿（pytest tests/services/plan_orchestration/test_wave_progression.py）；ruff 通过；barrel 可导入两 helper

---
*Phase: 44-repocodingtask-execution-plan-dag-wave*
*Completed: 2026-06-16*
