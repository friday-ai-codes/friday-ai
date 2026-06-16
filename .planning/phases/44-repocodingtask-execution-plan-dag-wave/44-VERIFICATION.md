---
phase: 44-repocodingtask-execution-plan-dag-wave
verified: 2026-06-16T13:30:00Z
status: passed
score: 7/7 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: null
  note: initial verification (no prior VERIFICATION.md)
deferred:
  - truth: "真实 runner + Docker 容器端到端 wave resume（wave N done → wave N+1 dispatch）"
    addressed_in: "既有 milestone deferred（本地无法闭环，需真实 runner + Docker daemon）"
    evidence: "44-CONTEXT.md 显式非目标 + 44-VALIDATION.md Manual-Only：本 phase 以 mock IO 边界（dispatcher / SubAgentSession 状态）的单测/集成测试覆盖拓扑分层、wave gating、失败隔离、幂等；STATE.md Deferred Items 已登记"
---

# Phase 44: RepoCodingTask + execution_plan DAG 拓扑分层 + wave 调度 Verification Report

**Phase Goal:** 立 RepoCodingTask 操作态模型（wave / depends_on DAG / produced_artifacts / follow_openspec 预留 SDD 扩展点），把 `MergedPlan.execution_plan` 的 dependencies 真正消费——按跨仓依赖拓扑分层成 wave（消化 PF-07：dependencies 不再仅 schema 声明、下游不再无条件全并行），wave N 全部 done 才触发 wave N+1。复用 Phase 43 callback-driven resume，不另造调度。Requirement: PF-07 / WAVE-01 / WAVE-02。
**Verified:** 2026-06-16T13:30:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `RepoCodingTask` 操作态模型有全部必需字段（plan_version FK / repository FK / wave / depends_on M2M self DAG / status / produced_artifacts / follow_openspec / subagent_session / attempt / error），迁移 0017 完整可应用 | ✓ VERIFIED | `repo_coding_task.py:38-101` 字段逐项齐备；4 态枚举无 stale（`:26-35`）；迁移 `0017_repocodingtask.py` 含表 + M2M through `repocodingtask.depends_on` + 两索引；`makemigrations delivery --check` → "No changes detected"（模型与迁移一致）；`test_repo_coding_task_models.py` 绿 |
| 2 | `execution_plan[].dependencies` 被真正消费成仓级拓扑 wave（非仅声明）；空依赖退化单 wave 全并行（零回归） | ✓ VERIFIED | `wave_layering.py:24-83` 用 graphlib Kahn 分层把 task-id DAG 投影为仓级 wave（同仓取 max）；`coding.py:330-391` 首发段调 `build_repo_waves` 并仅 dispatch 最小 wave；空依赖 → 全仓 wave=0 一次性 dispatch；`test_multi_wave_progression`（repoB deps repoA → 首发仅 dispatch repoA）+ `test_empty_deps_zero_regression`（不建 RepoCodingTask、一次性 dispatch 全部、单 resume 收尾）均绿 |
| 3 | wave N+1 gated on wave N 全终态；上游 failed → 传递闭包阻断全部下游（含间接，无死锁） | ✓ VERIFIED | `wave_progression.py:63-123` 严格序「回填→传递闭包 BFS 阻断（`:157-187`，seen 去重多跳）→决策出口」，阻断在任何 early-return 前完成；等待判定 keys off `status=RUNNING`（`:108-113`）；`test_wave_progression.py` 6 测（gate/失败隔离/单跳+2 跳阻断 liveness/幂等/全终态）+ `test_partial_success_finalize`（repoB failed → repoC blocked 不 dispatch）均绿 |
| 4 | wave 推进复用 Phase 43 callback-driven resume（无并行调度器/轮询/定时器） | ✓ VERIFIED | `coding.py:218-225` resume 入口 keys off `_resume_from_callback`（由 `_schedule_workflow_resume` 写入）；`_resume_wave`（`:787-842`）有限收敛 `for`（上界=task 总数）非调度循环；grep `coding.py` + `wave_progression.py` 无 `while True`/`asyncio.sleep`/`Timer`/`apscheduler`/`add_job`/`create_task` |
| 5 | INV-6：所有 RepoCodingTask 写入只经 service | ✓ VERIFIED | `repo_coding_task_service.py` 五写入方法唯一入口；模型层零业务方法（仅 `__str__`）；`test_repo_coding_task_inv6_guard.py` 源码扫描断言除 service 外无旁路 `.objects.<write>`/实例化/save，且 writer 确实写 `.status`/`.objects.<write>`——绿 |
| 6 | 依赖环 fail-fast（不进 dispatch、不建行） | ✓ VERIFIED | `wave_layering.py:40-46` 复用 `plan_validator.validate_plan` 三色 DFS 取 dependency_cycle 项 fail-fast；`coding.py:332-341` 环 → `status=failed`/`next_handle=error` 不 dispatch；`test_dependency_cycle_fails_fast`（节点 failed + 0 dispatch + 0 RepoCodingTask）绿 |
| 7 | 部分成功收尾：done 仓出 MR，failed/blocked 仓如实标注（含 upstream_failed 文案），不自动回滚 | ✓ VERIFIED | `_finalize_wave`（`coding.py:944-1043`）从 DB 全行重算 done/failed，done 仓出 MR、`upstream_failed` 阻断文案区分；`test_partial_success_finalize` 断言仅 repoA 出 MR、repoB/repoC 在 failed_details、repoC 标 upstream_failed、无回滚——绿 |

**Score:** 7/7 truths verified

### Deferred Items

Items not verified locally but explicitly scoped out of this phase per the locked CONTEXT / VALIDATION contract.

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | 真实 runner + Docker 容器端到端 wave resume | 既有 milestone deferred（本地无法闭环） | 44-CONTEXT.md「显式不做：真实 runner + Docker 容器端到端验收（沿用既有 deferred，本 phase 以 mock IO 边界测试覆盖）」；44-VALIDATION.md Manual-Only 段同源；STATE.md Deferred Items 已登记 |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `server/delivery/models/repo_coding_task.py` | RepoCodingTask 模型 + 4 态枚举 | ✓ VERIFIED | 102 行，全字段 + Meta + 索引，barrel 导出 |
| `server/delivery/migrations/0017_repocodingtask.py` | 表 + M2M through + 索引 | ✓ VERIFIED | `makemigrations --check` 干净 |
| `server/delivery/services/repo_coding_task_service.py` | 单一写入入口（5 方法） | ✓ VERIFIED | create_tasks_for_plan + mark_running/done/failed/blocked，条件更新幂等 |
| `server/services/plan_orchestration/wave_layering.py` | 拓扑分层纯函数 | ✓ VERIFIED | build_repo_waves + build_repo_dep_edges，复用 validate_plan 环检测 |
| `server/services/plan_orchestration/wave_progression.py` | 入口无关 wave 推进 | ✓ VERIFIED | aadvance_coding_waves + acurrent_wave_all_terminal + 传递闭包阻断 |
| `server/workflows/nodes/ai/coding.py` | AICodingNode wave 分批 dispatch | ✓ VERIFIED | 首发分批 + resume 分流 wave/legacy + 部分成功收尾 |
| `server/tests/test_coding_wave.py` | 集成测试 | ✓ VERIFIED | 4 场景（零回归/多 wave/部分成功/环 fail-fast） |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| AICodingNode | wave_layering | `build_repo_waves(execution_plan)` 消费 dependencies | ✓ WIRED | `coding.py:330-332`（PF-07 直接触面） |
| AICodingNode | RepoCodingTaskService | `create_tasks_for_plan` / `mark_running` / `mark_failed` | ✓ WIRED | `coding.py:386-388,605,609`（INV-6 收口） |
| AICodingNode resume | wave_progression | `aadvance_coding_waves(plan_version_id)` | ✓ WIRED | `coding.py:806-814` |
| wave_progression | RepoCodingTaskService | `service.mark_done/mark_failed/mark_blocked` | ✓ WIRED | `wave_progression.py:144-153,182`（状态只经 service） |
| 容器回调 | AICodingNode | `_resume_from_callback` 标记重入（Phase 43 复用） | ✓ WIRED | `coding.py:218-225`；无另造调度 |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Phase 44 scoped 测试套件全绿 | `uv run pytest tests/test_coding_wave.py tests/services/plan_orchestration/ tests/delivery/test_repo_coding_task_models.py tests/delivery/test_repo_coding_task_service.py tests/delivery/test_repo_coding_task_inv6_guard.py -q` | 27 passed, 8 warnings in 13.60s | ✓ PASS |
| ruff lint | `uv run ruff check` | All checks passed! | ✓ PASS |
| 迁移一致性 | `manage.py makemigrations delivery --check --dry-run` | No changes detected in app 'delivery' | ✓ PASS |
| 无并行调度原语 | grep `while True\|asyncio.sleep\|Timer\|apscheduler\|add_job\|create_task` (coding.py + wave_progression.py) | 仅命中方法名 `create_tasks_for_plan`，无调度原语 | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| WAVE-01 | 44-01/02/03 | RepoCodingTask 模型 + execution_plan dependencies 拓扑分层（消化 PF-07） | ✓ SATISFIED | Truth 1/2/5/6 |
| WAVE-02 | 44-03/04/05 | wave N 全终态才触发 N+1 + 失败/部分回滚语义 | ✓ SATISFIED | Truth 3/4/7 |
| PF-07 | 44-02/05 | dependencies 不再仅 schema 声明、下游不再无条件全并行 | ✓ SATISFIED | `build_repo_waves` 消费 + AICodingNode 按 wave 分批 dispatch；空依赖零回归保留 |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | 未发现 debt marker（TBD/FIXME/XXX）/ stub / 空实现 | — | 无 |

注：`produced_artifacts` / `follow_openspec` 为本 phase 显式立而不消费的预留扩展点（Phase 45 / v0.9 才写内容），非 stub——符合 CONTEXT 锁定 scope。

### Human Verification Required

无需阻断本 phase 的人工验证项。唯一手动项（真实 runner + Docker 端到端 wave resume）为 CONTEXT/VALIDATION 显式声明的既有 deferred 非目标（本地无法闭环），不计入本 phase 验收门 —— 本 phase 以 mock IO 边界测试覆盖拓扑分层、wave gating、失败隔离、幂等、部分成功收尾。

### Gaps Summary

无 gap。Phase 44 目标完整达成：

- **WAVE-01** — RepoCodingTask 操作态模型（全字段 + 迁移 0017 一致）落库，`execution_plan[].dependencies` 经 `build_repo_waves` 真正消费成仓级拓扑 wave，AICodingNode 按 wave 分批 dispatch（消化 PF-07）；空依赖严格退化单 wave 全并行（零回归，`test_empty_deps_zero_regression` 守护）。
- **WAVE-02** — `aadvance_coding_waves` 以「回填→传递闭包阻断→决策出口」严格序实现 wave gate（N 全终态才推 N+1）+ 失败隔离 + 间接下游传递闭包阻断（无死锁 liveness）+ 幂等；部分成功收尾 done 出 MR、failed/blocked 如实标注、不自动回滚；复用 Phase 43 callback resume 不另造调度（无 while True/sleep/timer）。
- **INV-6** — 所有写入收口 RepoCodingTaskService，grep 守护断言无旁路。

证据强度：27 个自动化测试全绿（含 4 个端到端节点集成场景 + 拓扑分层 + 推进 + service 幂等 + INV-6 守护），ruff 干净，迁移一致。代码复审 `44-REVIEW.md` 已 clean（2 INFO 为透明记录，非阻塞）。

---

_Verified: 2026-06-16T13:30:00Z_
_Verifier: Claude (gsd-verifier)_
