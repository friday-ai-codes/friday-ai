---
phase: 44-repocodingtask-execution-plan-dag-wave
reviewed: 2026-06-16T21:40:00Z
depth: standard
iteration: 2
files_reviewed: 4
files_reviewed_list:
  - server/services/plan_orchestration/wave_layering.py
  - server/services/plan_orchestration/wave_progression.py
  - server/delivery/services/repo_coding_task_service.py
  - server/workflows/nodes/ai/coding.py
findings:
  critical: 0
  warning: 0
  info: 2
  total: 2
status: clean
---

# Phase 44: Code Review Report (Iteration 2)

**Reviewed:** 2026-06-16T21:40:00Z
**Depth:** standard
**Files Reviewed:** 4
**Status:** clean

## Summary

第 2 轮复审聚焦：(1) 确认 iteration 1 的两个 WARNING 是否真正修复，(2) 排查修复引入的 NEW 回归。结论：**两个 WARNING 均已修复，未发现新的 critical/warning 回归**，故 `status: clean`。

**WR-01（已修复，commit `6b82c7f7`）** — `build_repo_dep_edges` 现已在成边循环前置 `if not t.get("id"): continue`（`wave_layering.py:107-108`），与 `build_repo_waves` 的 `for t in execution_plan if t.get("id")` 口径完全一致。半可信 plan 中「无 id 但有 repository_id + dependencies」的任务不再贡献仓级 `depends_on` 边，消除了「同 wave 跨仓依赖绕过首发 wave 保证」的窗口。逐字段比对两函数的 `task_repo` 构造与过滤条件，现已对齐，无新增逻辑分叉。

**WR-02（已修复，commit `55655572`）** — `_mark_running_sync` 从「无条件 `task.status=RUNNING; save()`」改为条件更新 `RepoCodingTask.objects.filter(id=task.id, status=PENDING).update(status=RUNNING, subagent_session=..., updated_at=timezone.now())` 并返回影响行数（`repo_coding_task_service.py:95-104`），与 `mark_done` / `mark_blocked` 同范式。状态写现已幂等：并发/重复 dispatch 下仅首个 claim 影响 1 行，其余天然 no-op。

**回归排查（无新增缺陷）：**
- **返回类型变更（`-> None` → `-> int`）**：唯一生产调用方 `coding.py:605` `await service.mark_running(task, sess)` 忽略返回值，不依赖旧返回语义；测试调用方亦只 await，无回归。
- **in-memory 实例不再被更新**：旧版 `save()` 会同步更新内存 `task` 的 `.status`，新版 `.update()` 只改 DB 行。排查所有调用点——`_dispatch_wave` / `_dispatch_next_wave` 在 `mark_running` 后不再复用该 `task` 实例；resume 段（`_backfill_running_terminal` / `_collect_dispatchable_pending` / `_finalize_wave`）一律从 DB 重查（`status=RUNNING` / `status=PENDING` 过滤），**不读内存态**。无悬挂脏对象依赖。
- **`updated_at` 手工置位**：`.update()` 不触发 `auto_now`，新版已显式 `updated_at=timezone.now()`，与 `mark_done` / `mark_blocked` 一致，无字段漂移。
- **liveness 不受影响**：串行回调路径下（项目不变式「reuse Phase 43 callback resume / no parallel scheduler」），首发 `create_tasks_for_plan` 后的 task 恒 PENDING、下一 wave dispatch 集合来自 `_collect_dispatchable_pending`（PENDING 过滤），`mark_running` 条件更新恒影响 1 行，正常派发不会被新条件误吞。

其余不变式仍守得到位：`aadvance_coding_waves`「① 回填 → ② 传递闭包阻断 → ③ 决策出口」顺序未变，阻断仍在任何 early-return 前完成（T-44-DEADLOCK）；INV-6 单一写入入口未被旁路；async ORM 标量/`afirst`/`aexists`/`async for` 安全；空依赖零回归命门保留。

下列 2 条 INFO 为透明记录（非本轮新增缺陷、不阻塞），其中 IN-02 为 iteration 1 IN-03 的延续（相关代码本轮未改动）。

## Info

### IN-01: WR-02 修复仅覆盖「状态写幂等」，派发副作用幂等仍隐式依赖串行续驱不变式

**File:** `server/workflows/nodes/ai/coding.py:546-611`（`_dispatch_wave`）、`server/services/plan_orchestration/wave_progression.py:116-120`

**Issue:** iteration 1 WR-02 的修复建议含两半——(1) 条件更新使状态写幂等（**已做**），(2) 调用方据 `mark_running` 影响行数决定是否真正建容器（**未做**）。当前 `_dispatch_wave` 先在 `asyncio.gather` 内**无条件 dispatch 容器 / 建 SubAgentSession**，之后才对 `waiting_sessions` 逐个 `await service.mark_running(...)`（忽略返回值）。即「建容器」发生在「claim」之前。若假设性地出现同一 node 的并发回调重入，两次 `_collect_dispatchable_pending` 可能读到同一批 PENDING → 各 dispatch 一次容器（虽然只有一个 `mark_running` 影响 1 行，另一个容器变为孤儿，仍可能推分支/产 MR）。

实际安全性由项目不变式「reuse Phase 43 callback resume（no parallel scheduler）」即回调串行续驱兜底——串行下不存在并发重入，故无重复派发。本条仅记录：源码层未自证该串行性（`wave_progression.py:9-11` 与 `coding.py:798-799` 说明「不另造调度」，但未断言「同一 node 回调不会并发」）。

**Fix（可选加固）:** 若未来放宽串行假设，把 claim 提前——在 dispatch 前以 `mark_running`（pending→running）原子占位，仅对影响 1 行的 task 真正建容器；或在 `_resume_wave` 入口对 `plan_version` 加节点级串行锁，并在注释中显式记录 Phase 43 续驱对同一 node 的串行性保证。

### IN-02: `_dispatch_wave` 在 SubAgentSession 查不到时静默跳过 `mark_running`（延续 iteration 1 IN-03）

**File:** `server/workflows/nodes/ai/coding.py:599-605`

**Issue:**
```python
sess = await SubAgentSession.objects.filter(session_id=s["session_id"]).afirst()
if sess is not None:
    await service.mark_running(task, sess)
```
若 `afirst()` 返回 `None`，该仓虽已计入 `waiting_sessions`（容器视为已派发），但其 task 仍停留 PENDING 且无 `subagent_session_id`。后续 resume 的回填只遍历 `status=RUNNING` → 该 task 不被回填；`_collect_dispatchable_pending` 在其 `depends_on` 满足时可能再次将其当作可派发 → 重复建容器。WR-02 的条件 `mark_running` 不改变此路径（sess 为 None 时根本不调用 mark_running）。

正常路径下 `_run_repo_coding._create_session()` 在 dispatch 前已 `aupdate_or_create(session_id=...)` 且被 await，`session_id` 唯一，故 `sess` 不会为 `None`，可达性极低；列为 INFO 记录该隐含前提。

**Fix:** 当 `sess is None` 但该仓已计入 `waiting_sessions` 时，记 warning 并经 `service.mark_failed(task, {"reason": "session_missing"})` 标终态（避免悬挂 PENDING 致重复派发），而非静默跳过。

---

_Reviewed: 2026-06-16T21:40:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
_Iteration: 2_
