---
phase: 39-parallel-research
reviewed: 2026-06-16T10:25:00Z
depth: standard
files_reviewed: 8
files_reviewed_list:
  - server/delivery/models/research_task.py
  - server/delivery/migrations/0013_reporesearchtask_partialplan.py
  - server/delivery/services/research_service.py
  - server/services/plan_orchestration/research_adapter.py
  - server/services/plan_orchestration/research_aggregation.py
  - server/services/plan_orchestration/engine.py
  - server/subagent/api/callbacks.py
  - server/services/indexer.py
findings:
  critical: 1
  warning: 3
  info: 3
  total: 7
status: fixed
fix_report: 39-REVIEW-FIX.md
fixed_at: 2026-06-16T02:47:00Z
---

# Phase 39: Code Review Report — 并行调研子 agent

**Reviewed:** 2026-06-16T10:25:00Z
**Depth:** standard
**Files Reviewed:** 8
**Status:** fixed（全部 7 项已修复并提交，详见 `39-REVIEW-FIX.md`）

## Summary

对 Phase 39（filter_then_container 并行调研 + 结构化 `PartialPlan` + 子任务级可靠恢复 + §15 事件）的 8 个变更源文件做对抗式审查，重点核对 DOMAIN §6/§7/§14/§15 一致性、INV-5/INV-6、async/ORM 正确性（Phase 38 CR-01 lazy-FK 复发风险）、barrier 竞态、stale 失效作用域与 best-effort 隔离。

总体：模型/migration/service 写入收口/解析健壮性/stale 钩子隔离/barrier 幂等（条件更新去重）实现扎实，且**未复发 Phase 38 CR-01 的 async lazy-load FK bug**（adapter/aggregation/callback 全程只用 `*_id` 标量或 async fetch，未在 async 上下文裸触 `task.repository` / `task.session` 关系对象）。

但发现 **1 个 BLOCKER**：`plan_research` 容器回调复用 `AgentSession`+`SubAgentSession` 底座却未像 `deep_analysis` 那样在 `_schedule_agent_session_resume` 短路，导致**每次调研容器完成/失败都会在 happy path 触发一次虚假 Agent 会话 resume（真实拉起 SDKAgentRunner）**。另有 3 个 WARNING（resume 非幂等重派、deep 派发缺单仓错误隔离、engine 与 barrier 回调竞态下 `_fail` 无条件 save 可覆盖已推进状态）。

## Critical Issues

### CR-01: plan_research 容器回调触发虚假 Agent 会话 resume（happy path 拉起幽灵 agent 执行）

**File:** `server/subagent/api/callbacks.py:641` 与 `server/subagent/api/callbacks.py:702`（根因在 `_schedule_agent_session_resume`，`callbacks.py:100-177`）

**Issue:**
`ResearchDispatchAdapter._dispatch_deep_task`（`research_adapter.py:118-135`）镜像 `deep_analysis` 为每个调研容器建了一个**真实** `AgentSession(status=RUNNING)` 作为 `SubAgentSession.main_session`，`last_output.source="plan_research"`。

容器完成走 `_handle_completed`，在落 PartialPlan 之前先调用了 `_schedule_agent_session_resume(session, log)`（line 641；失败路径 `_handle_failed` line 702 同样）。该函数的短路条件为：

```python
if session.node_execution_id:            # research 无 node_execution → 不返回
    return
if (... session.last_output.get("source") == "chat_deep_analysis"):  # research 是 plan_research → 不返回
    _notify_barrier_manager(session, log)
    return
if not session.main_session_id:          # research 有 main_session → 不返回
    return
# → _prepare_and_resume() → schedule_resume_agent_session(main_session.session_id, ...)
```

`plan_research` 三个条件全部落空 → 进入 `_prepare_and_resume` → `schedule_resume_agent_session` → `resume_agent_session`（`tasks/agent_tasks.py:19`）。后者加载该合成 AgentSession，仅当 status ∈ {COMPLETED, ERROR, MAX_ITERATIONS} 才跳过；而 research 把它建成 `RUNNING`，**不在跳过集**，于是真正以 `result_msg="SubAgent 任务完成…"` 为 prompt 跑一遍 SDKAgentRunner。

后果（发生在每次调研容器完成/失败的正常路径，非边界）：
- 拉起一个无 `project`/`conversation` 上下文的幽灵 agent 执行，消耗 LLM token、改写该 AgentSession 状态、产生混淆日志/可能下游报错；
- 与正确的 `_handle_research_completion`（line 658）并行双重处理同一回调。

虽包在 `loop.create_task(...)` fire-and-forget（不会让回调 500、不污染 research 数据），但属 happy-path 的明确错误行为。

**Fix:** 在 `_schedule_agent_session_resume` 增加 research 短路（与 `deep_analysis` 对称），调研 barrier 由 `_handle_research_completion` 驱动，不需要 agent resume：

```python
def _schedule_agent_session_resume(session, log):
    if session.node_execution_id:
        log.debug("has_node_execution_skip_agent_resume")
        return
    if isinstance(session.last_output, dict):
        src = session.last_output.get("source")
        if src == "chat_deep_analysis":
            log.info("chat_deep_analysis_notify_barrier", session_id=session.session_id)
            _notify_barrier_manager(session, log)
            return
        if src == "plan_research":
            # 调研由 _handle_research_completion/barrier 驱动，无需 agent resume
            log.debug("plan_research_skip_agent_resume", session_id=session.session_id)
            return
    ...
```

（替代方案：research 不建真实 `AgentSession` / 不挂 `main_session`，或把合成 session 建成非可恢复终态；但源码短路最小且与既有范式一致。）

## Warnings

### WR-01: 调研 dispatch 非 resume-幂等（重派已完成 deep 任务、重复落 light partial）

**File:** `server/services/plan_orchestration/research_adapter.py:83-100`

**Issue:**
`create_tasks_for_session` 用 `get_or_create` 做到了**建表幂等**，但 **dispatch/合成本身不幂等**：

```python
deep_tasks = await self.research_service.create_tasks_for_session(session, deep_repos)
for task in deep_tasks:                 # 返回全部 deep task（含已 done/running），无状态过滤
    await self._dispatch_deep_task(session, task)   # 无条件重派 + mark_running(done→running)

light_tasks = await self.research_service.create_tasks_for_session(session, light_repos)
for task in light_tasks:                # 返回全部 light task（含已 done）
    ...
    await self.research_service.record_partial(task, content)  # 再建一条 PartialPlan + 再 mark_done
```

`engine._research` 在 `researching` 可被 re-advance（这是本里程碑反复强调的 resume 路径，CONTEXT 明文「engine 从 researching 可 resume（读未完成 tasks 续等/重派）」）。一旦 re-advance：
- 已 `done` 的 deep 任务被重新派容器并 `mark_running`（done→running），重置进度、浪费容器、扰乱 barrier；
- 已 `done` 的 light 任务每次 resume 再生成一条 `PartialPlan`（重复累积），与「读未完成 tasks」语义矛盾。

**Fix:** 派发/合成前按状态过滤，仅处理非终态（且 deep 仅处理未 running）任务，例如：

```python
deep_tasks = await self.research_service.create_tasks_for_session(session, deep_repos)
for task in deep_tasks:
    if task.status in (RepoResearchTaskStatus.PENDING,):   # 仅未派发的重派
        await self._dispatch_deep_task(session, task)
        dispatched_ids.append(str(task.id))
# light 同理：仅 status==pending 才合成 record_partial
```

### WR-02: deep 派发循环缺单仓错误隔离（一仓 dispatch 异常拖垮整 session，违 RESEARCH-02 隔离）

**File:** `server/services/plan_orchestration/research_adapter.py:83-89`

**Issue:**
deep fan-out 循环对 `_dispatch_deep_task` 直接 `await`，无 per-task try/except：

```python
for task in deep_tasks:
    await self._dispatch_deep_task(session, task)   # 任一仓抛异常 → 整个 dispatch 中断
```

`_dispatch_deep_task` 内 `AgentSession.acreate` / `SubAgentSession.acreate` / `get_dispatcher().dispatch()` 任一抛异常（非 runner offline 的瞬时错误），异常上抛到 `adapter.dispatch` → `engine._research` → `advance` 的通用 `except Exception` → **整个 PlanSession 被 transition fail**。同时已建的 `AgentSession`/`SubAgentSession` 成孤儿、剩余仓任务停在 `pending`、已 dispatch 的仓 `mark_running` 未执行。这与 RESEARCH-02「单仓失败不拖垮整 session」的隔离目标相悖。

**Fix:** 每仓独立 try/except，失败仅标该 task + 发 `repo.research.failed`，继续其他仓：

```python
for task in deep_tasks:
    try:
        await self._dispatch_deep_task(session, task)
        dispatched_ids.append(str(task.id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("research_dispatch_failed", task_id=str(task.id), error=str(exc))
        await self.research_service.mark_failed(task, {"reason": "dispatch_failed", "error": str(exc)})
        await self._emit_failed(session, task, "dispatch_failed")
```

### WR-03: engine 与 barrier 回调竞态下 `ConcurrentTransitionError` 被当作致命错误，`_fail` 无条件 save 可覆盖已推进状态

**File:** `server/services/plan_orchestration/engine.py:184-189`（结合 `delivery/services/plan_session_service.py:201-205` 的 `_fail_sync`）

**Issue:**
`_research` 在 `dispatch` 之后调用 `amaybe_complete_research`，若返回 False 再 `transition(session, "research_dispatched")`。这两步与容器回调侧的 `amaybe_complete_research → transition(research_complete)` 竞用同一 session 行。

竞态序列（窗口极小但语义真实）：`amaybe_complete_research` 读到尚有 running 返回 False → 在 engine 调 `transition("research_dispatched")` 之前，最后一个容器回调把 DB 推进到 `merging` → engine 的 `transition` 以内存 `from_status="researching"` 做条件更新 `filter(id, status="researching")` 命中 0 行 → 抛 `ConcurrentTransitionError`。该异常被 `advance` 的通用 `except Exception` 捕获 → `transition(session, "fail")` → `_fail_sync` 执行**无条件** `session.save(update_fields=["status","error","updated_at"])`，把回调正确推进的 `merging` **覆盖回 `failed`**（`_fail_sync` 不做条件更新，绕过了 `_apply_transition_sync` 的 TOCTOU 防线）。

发生概率低（同协程内 dispatch 返回到 transition 之间几乎无让出点），但一旦命中即把成功完成的编排错误地置失败，属状态损坏。

**Fix:** 在 `_research` 显式区分良性并发：捕获 `ConcurrentTransitionError`（说明 barrier 已推进，视为成功，no-op），不要落到 `advance` 的通用 fail 分支；并建议 `_fail` 改为条件更新（`filter(id, status=from_status).update(...)`）以杜绝无条件 save 覆盖：

```python
from delivery.services.plan_session_service import ConcurrentTransitionError
...
completed = await amaybe_complete_research(session, session_service=self.session_service)
if not completed:
    try:
        await self.session_service.transition(session, "research_dispatched")
    except ConcurrentTransitionError:
        logger.info("research_already_advanced_by_barrier", session_id=str(session.id))
```

## Info

### IN-01: `retry_task` 仅匹配 failed、无 session 状态守护，stale 无恢复路径

**File:** `server/delivery/services/research_service.py:126-149`

**Issue:** `retry_task` 条件更新仅 `status=failed`，对 `stale` 任务调用会抛 `ValueError`——而 stale 任务在本 phase 没有任何重跑入口（deferred 到 Phase 40 融合）。此外 `retry_task` 不校验所属 `PlanSession` 是否仍在 `researching`：barrier 已 fire（session→merging）后重试某 failed 任务会把它复位 `pending`，制造「已 merging 的 session 下挂 pending 任务」的不一致。当前无调用方（仅定义+单测），属潜伏问题。

**Fix:** 接线（Phase 40/41）时在 `retry_task` 增加 session 状态前置校验；并为 stale 任务提供与 retry 对等的「复位 pending 重派」入口。

### IN-02: routing.candidates 含重复 repo_id 时 light 路径会重复落 PartialPlan

**File:** `server/services/plan_orchestration/research_adapter.py:56-67,92-100`

**Issue:** 同一 `repo_id` 在 `candidates` 出现两次会进同一分流列表；`create_tasks_for_session` 经 `get_or_create` 收敛为一行 task，但 light 循环对「同一 task 出现两次」会调 `record_partial` 两次，产生两条 PartialPlan。routing 正常不应产出重复候选，概率低。

**Fix:** 分流前对 candidates 按 `repo_id` 去重（`seen` set），或仅对 `status==pending` 任务 `record_partial`（与 WR-01 同一修法可一并覆盖）。

### IN-03: 缺 git_url 的仓回退到 `https://invalid/{repo_id}.git`

**File:** `server/services/plan_orchestration/research_adapter.py:126`

**Issue:** `repo_url or f"https://invalid/{task.repository_id}.git"` 在仓无 `git_url` 时拼一个必然 clone 失败的占位 URL，容器内会失败 → 经回调 `mark_failed`。功能可收敛，但以「注定失败的容器」表达「仓不可调研」较隐晦，浪费一次容器调度。

**Fix:** 派发前校验 `git_url`，缺失则直接降级为 light 合成（或 `mark_failed` 并发 `repo.research.failed`），不浪费容器。

---

## 正面确认（非 finding）

- **无 async lazy-load FK bug（未复发 Phase 38 CR-01）**：`research_adapter` / `research_aggregation` / `callbacks` 在 async 上下文一律使用 `task.repository_id` / `task.id` 标量或 `await ...afirst()`，未裸触 `task.repository` / `task.session` / `task.subagent_session` 关系对象。
- **INV-6 守住**：adapter/callbacks 对 `RepoResearchTask`/`PartialPlan` 的写入全部经 `ResearchService`，未见旁路写表。
- **barrier 并发去重正确**：两仓并发完成时，`transition` 的条件更新（`filter(status=from_status)`）保证 `research_complete` 仅推进一次，输家抛 `ConcurrentTransitionError` 被回调 `_handle_research_completion` 的 try/except swallow，无 double-advance（Phase 36 WR-01 范式）。
- **stale 失效作用域正确**：`invalidate_for_repo` 按 `repository_id` 过滤 task，仅失效该仓 valid PartialPlan + 置对应 task stale，幂等可重入，不波及其他仓。
- **indexer stale 钩子 best-effort**：`_run_research_stale_invalidation` 整段 try/except，仅 base-only FINALIZING 段调用，失败仅 warning，不阻断索引 success。
- **结果解析健壮**：`parse_partial_plan_content` 结构化/JSON 围栏提取/自由文本降级/空→None 四路覆盖，缺列表字段补 `[]`，始终回填 `repository_id`，不 eval/不执行返回内容。
- **engine 纯度**：`_research` 仅经 `session_service.transition` 推进，未直接写 `session.status`。

---

_Reviewed: 2026-06-16T10:25:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
