---
phase: 39-parallel-research
fixed_at: 2026-06-16T02:47:00Z
review_path: .planning/phases/39-parallel-research/39-REVIEW.md
iteration: 1
findings_in_scope: 7
fixed: 7
skipped: 0
status: all_fixed
---

# Phase 39: Code Review Fix Report — 并行调研子 agent

**Fixed at:** 2026-06-16T02:47:00Z
**Source review:** `.planning/phases/39-parallel-research/39-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 7（CR×1 + WR×3 + IN×3）
- Fixed: 7
- Skipped: 0

所有修复在隔离 git worktree 内逐条原子提交；每条均带新增/扩展单测，全量受影响
测试套件 92 passed，`makemigrations --check` 干净（无模型变更）。

## Fixed Issues

### CR-01: plan_research 容器回调触发虚假 Agent 会话 resume

**Files modified:** `server/subagent/api/callbacks.py`, `server/tests/services/test_research_completion_callback.py`
**Commit:** b486b9004
**Applied fix:** 在 `_schedule_agent_session_resume` 增加 `source == "plan_research"` 短路（与
`chat_deep_analysis` 对称），调研容器完成/失败不再拉起合成 `AgentSession` 的
SDKAgentRunner resume；结果仅由 `_handle_research_completion` / `_handle_research_failure`
（→ barrier）驱动。新增 2 个测试断言 plan_research 完成/失败回调均不调用
`schedule_resume_agent_session`，且调用对应 research 处理。

### WR-02: deep 派发循环缺单仓错误隔离

**Files modified:** `server/services/plan_orchestration/research_adapter.py`, `server/tests/services/test_research_adapter.py`
**Commit:** 6568d3e6d
**Applied fix:** deep fan-out 循环对每仓 `_dispatch_deep_task` 包 try/except——单仓异常仅
`mark_failed` + emit `repo.research.failed` 后继续其他仓，绝不上抛拖垮整个 PlanSession
（RESEARCH-02 隔离）。新增 `_emit_failed` 辅助。测试：一仓 dispatch 抛异常 → 该 task
failed、其余仓仍正常 running。

### WR-01: 调研 dispatch 非 resume-幂等

**Files modified:** `server/services/plan_orchestration/research_adapter.py`, `server/tests/services/test_research_adapter.py`
**Commit:** 3a049a7f8
**Applied fix:** 引入 `_DISPATCHABLE_STATUSES = (pending, stale)`；deep/light 两循环均跳过
非该集合的任务（running/done/failed 不重派、不重复合成 light partial），stale 仍可重跑。
测试：同 session 二次 dispatch 不重派容器、不重建 task、不重复落 PartialPlan。

### WR-03: engine 与 barrier 回调竞态下 ConcurrentTransitionError 被当致命错误

**Files modified:** `server/services/plan_orchestration/engine.py`, `server/delivery/services/plan_session_service.py`, `server/tests/services/test_plan_orchestration_engine.py`, `server/tests/delivery/test_plan_session_service.py`
**Commit:** 058696668
**Applied fix:** `engine._research` 捕获 `ConcurrentTransitionError`（barrier 已推进视为良性
no-op，不落 advance 通用 fail 分支）；`_fail_sync` 改为以 `status == 内存 from_status`
为前置条件的原子条件更新（镜像 Phase 36 WR-01），命中 0 行返回 False → 放弃 fail +
re-fetch 同步内存态，绝不盲写把已推进的 merging 覆盖回 failed。测试：模拟 dispatch 后
barrier 抢先推进 merging，engine no-op 且状态未损坏；直接单测 `_fail_sync` 并发拒绝。

### IN-01: retry_task 仅匹配 failed、无 session 状态守护，stale 无恢复路径

**Files modified:** `server/delivery/services/research_service.py`, `server/tests/delivery/test_research_service.py`
**Commit:** 4329f850d
**Applied fix:** `retry_task` 增加 session 状态前置校验（仅 `researching` 可重试/复位，
否则 raise，避免已 merging/done 的 session 下挂回 pending），并把 `stale` 纳入可复位集
（与 failed 对等的重跑入口）。测试：stale 复位 pending + attempt+1；session 非
researching 时 retry 被拒且任务不变。

### IN-02: routing.candidates 含重复 repo_id 时 light 路径重复落 PartialPlan

**Files modified:** `server/services/plan_orchestration/research_adapter.py`, `server/tests/services/test_research_adapter.py`
**Commit:** a99bd72a0
**Applied fix:** filter 分流前以 `seen_repo_ids` set 按 repo_id 去重。测试：重复候选 →
单 task + 单 PartialPlan。

### IN-03: 缺 git_url 的仓回退到 `https://invalid/{repo_id}.git` 占位容器

**Files modified:** `server/services/plan_orchestration/research_adapter.py`, `server/tests/services/test_research_adapter.py`
**Commit:** a99bd72a0
**Applied fix:** `_dispatch_deep_task` 改为返回 bool；缺 `git_url` 时直接 `mark_failed`
(`reason=missing_git_url`) + emit `repo.research.failed` 并返回 False（不派注定 clone
失败的占位容器、不计入 dispatched），移除占位 URL 兜底。测试：缺 git_url 仓 →
dispatch 0 次、task failed、emit failed 一次。

---

_Fixed: 2026-06-16T02:47:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
