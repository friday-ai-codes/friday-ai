---
phase: 44-repocodingtask-execution-plan-dag-wave
plan: 05
subsystem: workflows
tags: [wave, dag, dispatch, resume, callback-driven, partial-success, zero-regression, inv-6, liveness]

# Dependency graph
requires:
  - phase: 44-02 wave_layering 拓扑分层纯函数
    provides: build_repo_waves（{repo_id: wave} + 环检测 fail-fast）/ build_repo_dep_edges（仓级 DAG 边）
  - phase: 44-03 RepoCodingTaskService 单一写入入口
    provides: create_tasks_for_plan / mark_running / mark_failed（INV-6 单一写入建行 + 状态推进）
  - phase: 44-04 wave_progression 入口无关推进 helper
    provides: aadvance_coding_waves（回填→传递闭包阻断→决策出口，返回 waiting/dispatch/all_terminal）
  - phase: 43-01 PF-06 编码 env 注入
    provides: _run_repo_coding 容器 dispatch（git token + anthropic 凭证 + branch env，本 plan 复用不改）
  - phase: 43-03 RESUME-01 callback 驱动 resume
    provides: _schedule_workflow_resume（容器全终态触发节点重入，本 plan 复用不改契约）
provides:
  - AICodingNode 按拓扑 wave 分批 dispatch（首发仅最小 wave）+ callback 驱动多 wave 推进
  - 部分成功收尾（done 仓出 MR / failed/blocked 仓如实标注 / 不自动回滚）
  - 空依赖 + 无 plan_version 的 legacy 全并行零回归路径
  - 多仓 wave 集成测试（零回归 / 多 wave 推进 / 部分成功阻断 / 环 fail-fast）
affects: [45 上游产物注入下游 wave（消费 wave 调度 + RepoCodingTask.produced_artifacts）]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "首发与 wave 推进共用 _dispatch_wave / _resolve_anthropic_credentials / _finalize_and_notify（不造两套）"
    - "wave 状态走 DB（RepoCodingTask），waiting_event output 仅传无状态 plan_version_id 锚（resume 从 DB 重算）"
    - "resume 段 plan_version_id 分流 wave/legacy；wave 推进全段 fail-soft 不回灌容器回调 5xx"
    - "wave N→N+1 由 _schedule_workflow_resume 容器回调触发节点重入自驱（不另造调度：无 while True/sleep/timer）"
    - "dispatch 失败仓 mark_failed 保 liveness（无容器回调可驱动则 aadvance 阻断下游收尾）"

key-files:
  created:
    - server/tests/test_coding_wave.py
  modified:
    - server/workflows/nodes/ai/coding.py

key-decisions:
  - "wave 模式激活双 guard：plan_version 可解析 AND repo_waves 完整覆盖全部待编码仓——否则回退 legacy 全并行（保护非 canonical/legacy plan_data 零回归，防 repo_waves 不覆盖时误激活）"
  - "首发恒 dispatch 最小 wave（min(repo_waves.values())）；空依赖 → 全仓 wave=0 → 一次性 dispatch 全部 = 现行为等价"
  - "不双 backfill：aadvance_coding_waves 独占 running→终态回填（Step 1），_finalize_wave 仅从 DB 读最终状态构建 succeeded/failed（不再回填）"
  - "waiting != finalize：aadvance 返回 waiting（仍有 RUNNING）→ _resuspend_wave 重挂起等下次回调，绝不当收尾触发"
  - "收尾从 DB（RepoCodingTask 全行）重算 done/failed 而非 pending_sessions——捕获跨全部 wave 的结果（pending_sessions 仅末 wave）"
  - "有限收敛 for 循环（上界=task 总数）替代 while True 处理「整 wave dispatch 全失败」收敛，满足无新调度循环/轮询约束"

patterns-established:
  - "节点 wave 接线：首发 _execute_with_branch 建行+dispatch 最小 wave；resume _resume_wave 经 aadvance 判 gate 推进/收尾"
  - "wave 集成测试范式：真实 ORM(PlanVersion/RepoCodingTask/SubAgentSession) + 真实 NodeExecution 链 + mock IO 边界(dispatcher/git token/MR/通知/子步骤)"

requirements-completed: [WAVE-01, WAVE-02]

# Metrics
duration: 22min
completed: 2026-06-16
---

# Phase 44 Plan 05: AICodingNode wave 调度接线 Summary

**把 `AICodingNode` 从「一把梭全并行 dispatch + 一次性 resume」改成「按拓扑 wave 分批 dispatch、wave N 全终态才推 N+1」——首发段 `_execute_with_branch` 经 `build_repo_waves` 分层 + 环 fail-fast + `RepoCodingTaskService.create_tasks_for_plan` 建行（INV-6）后仅 dispatch 最小 wave 并 `mark_running`；resume 段 `_resume_after_containers` 按 `plan_version_id` 分流 wave/legacy，wave 路径经 `aadvance_coding_waves` 判 gate → dispatch 下一 wave 再 `waiting_event`（不双 backfill、waiting != finalize）或 `_finalize_wave` 从 DB 重算 done/failed 走部分成功收尾（done 出 MR、failed/blocked 如实标注、不自动回滚）；空依赖 + 无 plan_version 退化为既有全并行字节级等价（零回归）；wave N→N+1 由 Phase 43 `_schedule_workflow_resume` 容器回调触发节点重入自驱，不另造调度（无 while True/sleep/timer）**

## Performance

- **Duration:** ~22 min
- **Tasks:** 3（+ STATE/ROADMAP 收尾）
- **Files modified:** 2（1 created + 1 modified）

## Accomplishments
- `_execute_with_branch` 首发段 wave 接线：`build_repo_waves` 分层 + `build_repo_dep_edges` 仓级边；依赖环 fail-fast（`status=failed`/`error.reason` 不进 dispatch）；`plan_version` 可解析 AND `repo_waves` 完整覆盖待编码仓时进 wave 模式（`create_tasks_for_plan` 建行 + 仅 dispatch 最小 wave + `mark_running` 回填），否则 legacy 全并行零回归（`warning("repo_coding_task_skipped_no_plan_version")`）
- 抽 `_resolve_anthropic_credentials` / `_dispatch_wave` / `_build_waiting_output` helper，首发与 wave 推进共用（不造两套）；`_dispatch_wave` 保留 `asyncio.gather(return_exceptions=True)` 单仓隔离，wave 模式下成功仓 `mark_running`、dispatch 失败仓 `mark_failed`（liveness）
- `_resume_after_containers` 按 `plan_version_id` 分流：legacy → `_resume_legacy`（既有一次性收尾，零回归）；wave → `_resume_wave`（经 `aadvance_coding_waves` 判 gate）
- `_resume_wave` 三态处理：`waiting`→`_resuspend_wave` 重挂起（waiting != finalize）；`dispatch`→`_dispatch_next_wave`（复用 `_dispatch_wave`）+ 再 `waiting_event`；`all_terminal`→`_finalize_wave`；整段 fail-soft（`aadvance` 异常 swallow + warning 降级 → 收尾，绝不回灌容器回调 5xx）
- `_finalize_wave` 从 DB（`RepoCodingTask` 全行）重算 done/failed 收尾，复用 `_finalize_and_notify`（done 仓出 MR、failed/blocked 仓如实标注含 `upstream_failed` 文案、不自动回滚）
- 4 个 wave 集成测试全绿：零回归（全并行不建行单 resume）/ 多 wave 推进（首发仅 wave0 → resume dispatch wave1 → 收尾两仓 MR）/ 部分成功（repoB failed → repoC blocked 不 dispatch、仅 repoA 出 MR、无回滚）/ 依赖环 fail-fast

## Task Commits

Each task was committed atomically:

1. **Task 1+2: AICodingNode wave dispatch + resume 接线（首发分批 + callback 推进 + 收尾）** - `d38637ea` (feat)
2. **Task 3: 多仓 wave 调度集成测试** - `bcf2c3b1` (test)

（Task 1 与 Task 2 均为对 `coding.py` 单文件的紧耦合改造——首发段与 resume 段共用同批 helper，故合并为一次 feat 提交；提交内 amend 一次以将 `_resume_wave` 的 `while True` 重构为有限收敛 `for` 循环，满足「无新调度循环」验收。）

## Files Created/Modified
- `server/workflows/nodes/ai/coding.py` - `_execute_with_branch` 首发 wave 接线；新增 `_resolve_anthropic_credentials` / `_dispatch_wave` / `_build_waiting_output`；`_resume_after_containers` 分流 + 新增 `_resume_legacy` / `_resume_wave` / `_dispatch_next_wave` / `_resuspend_wave` / `_build_resume_waiting_output` / `_finalize_wave` / `_finalize_and_notify`（收尾共用）
- `server/tests/test_coding_wave.py` - 4 场景 wave 集成测试（真实 ORM + 真实 NodeExecution 链 + mock IO 边界）

## Decisions Made
- wave 模式激活双 guard（plan_version 可解析 AND repo_waves 完整覆盖全部待编码仓），否则回退 legacy 全并行——防 legacy/非 canonical plan_data（task 无 id → repo_waves 不覆盖）误激活
- 不双 backfill：`aadvance_coding_waves` 独占 running→终态回填，`_finalize_wave` 仅读 DB 最终状态（不回填）
- waiting != finalize：`aadvance` 返回 `waiting` → 重挂起等下次回调，不收尾
- 收尾从 DB `RepoCodingTask` 全行重算（捕获全部 wave 结果），非 `pending_sessions`（仅末 wave）
- `while True` → 有限收敛 `for`（上界=task 总数）以满足「无新调度循环/轮询」验收

## Deviations from Plan

None - plan executed exactly as written.

（Task 1 与 Task 2 合并为一次原子 feat 提交：二者均改 `coding.py` 单文件且共用同批 helper，事后无法干净拆分；功能与验收逐条覆盖。Task 3 额外补 `test_dependency_cycle_fails_fast`（环 fail-fast 守护，对齐 must_have「依赖环 → 节点 failed」），超出 plan 列举的 3 场景。）

## Issues Encountered
- 集成测试初版用 `_FakeNodeExecution`（id=""）→ 并行 dispatch 各建占位 `AgentSession` 撞 `session_id` unique 约束（占位创建未填 `session_id` 字段）。改为建真实 `NodeExecution` 链（Project→Workflow→WorkflowExecution→NodeExecution + 同 metadata 的 main `AgentSession`），使 `_create_session` 命中同一 main_session，消除占位冲突——更贴近生产路径。

## Threat Model Compliance
- **T-44-TAMPER-NODE**（resume 推进越权他人 plan_version）：wave 推进限本 `plan_version_id`（从节点 output_data 锚，服务端写入）；终态判定经 `aadvance_coding_waves` 读服务端权威 `SubAgentSession.status`（44-04 已守）。
- **T-44-DAG-DOS-NODE**（半可信 execution_plan 含环）：`build_repo_waves` 复用 `plan_validator` 三色 DFS；环 fail-fast 节点直接 failed 不进 dispatch（`test_dependency_cycle_fails_fast` 守护）。
- **T-44-CRED**（凭证注入）：复用既有 `_run_repo_coding` 凭证路径（Phase 43 PF-06），`_resolve_anthropic_credentials` 仅记 `has_api_key`/`source` 布尔，凭证绝不入日志——本 plan 不改凭证解析。
- **T-44-IDEM-NODE**（重复回调重复 dispatch）：推进经 `aadvance_coding_waves` + service 条件更新幂等（已 running/done 不重 dispatch）；`_schedule_workflow_resume` 二次 guard「全 SubAgentSession 终态才续跑」。

## Next Phase Readiness
- wave 调度端到端就绪（首发分批 dispatch + callback 驱动多 wave 推进 + 部分成功收尾），Phase 45 可在 wave 之间提取/注入 `produced_artifacts`
- 全部 RepoCodingTask 状态写入收口 RepoCodingTaskService（INV-6）；wave N→N+1 复用 Phase 43 callback 自驱（不另造调度）
- 验收：`tests/test_coding_node.py`（12 passed + 1 xfailed 零回归）+ `tests/test_coding_wave.py`（4 passed）+ `tests/delivery` + `tests/services/plan_orchestration` 合计 340 passed + 1 xfailed；ruff 通过；grep 确认无 `while True`/`asyncio.sleep`/timer/apscheduler

## Self-Check: PASSED

- `server/tests/test_coding_wave.py` + `server/workflows/nodes/ai/coding.py` 均存在
- 2 task 提交均在 git history（d38637ea / bcf2c3b1）
- 全量验收 340 passed + 1 xfailed；ruff 通过；无新调度原语

---
*Phase: 44-repocodingtask-execution-plan-dag-wave*
*Completed: 2026-06-16*
