---
phase: 43-env-resume
reviewed: 2026-06-16T11:00:00Z
depth: standard
files_reviewed: 6
files_reviewed_list:
  - server/workflows/nodes/ai/coding.py
  - server/services/plan_orchestration/resume.py
  - server/services/plan_orchestration/__init__.py
  - server/subagent/api/callbacks.py
  - server/workflows/nodes/ai/plan_research.py
  - server/agents/tools/plan_research_tools.py
findings:
  critical: 1
  warning: 3
  info: 2
  total: 6
status: clean
fix_status: all_critical_warning_fixed
fix_note: >-
  CR-01 / WR-01 / WR-02 / WR-03 已修复并通过相关测试套件（45 passed, 1 pre-existing xfail）。
  IN-01（多容器并发重复驱动 engine）与 IN-02（回灌 output 为 plan_version id）为
  RESEARCH 已文档化的 by-design 取舍，本地基 phase 接受，不在本次修复范围。
---

# Phase 43: Code Review Report

**Reviewed:** 2026-06-16
**Depth:** standard
**Files Reviewed:** 6
**Status:** findings

## Summary

审查范围为 Phase 43 的两块后端地基：PF-06（`_run_repo_coding` 的 git token/分支 env 注入对齐 + SSH→HTTPS 改写）与 RESUME-01（共享续驱 helper + chat 入口 plan_research 容器回调续驱 + barrier 回灌）。

安全脱敏方面表现良好：T-43-INFO（git token 绝不入日志，仅记 `has_git_token` 布尔）已正确落实并有针对性测试；T-43-TAMPER 的 `entrypoint == CHAT` 服务端权威字段守门已实现并有回归测试；fail-soft（独立 try/except swallow，回调不 5xx）与 step-limit 防死循环均到位。

但发现一个**并发时序 BLOCKER**：chat 入口的 fire-and-forget 续驱被调度在 `_handle_research_completion`（把 RepoResearchTask 翻终态 + session `researching→merging`）**之前**，二者在事件循环 await 点交错，存在让 chat 方案会话卡在 `merging`/`researching`、barrier 永不被通知（对话永不 resume）的窗口——这恰好是 RESUME-01 想消除的缺口。此外，PF-06 新测试用 `select_related` + monkeypatch **掩盖了一个生产侧会触发的 `repository.credential` 异步访问 / 缺字段缺陷**，给出"端到端可用"的假阳性信心。

## Critical Issues

### CR-01: chat 续驱被调度在 research 完成处理之前，存在让会话永久卡死的竞态

**File:** `server/subagent/api/callbacks.py:744`（及 `:805` 失败路径）

**Issue:**
在 `_handle_completed` 中，调用顺序为：

```
744  _schedule_agent_session_resume(session, log)   # → _schedule_chat_plan_resume → loop.create_task(_resume())
...
762  await _handle_research_completion(session, p, log)  # record_partial(task→DONE) + amaybe_complete_research(researching→merging)
```

`_schedule_chat_plan_resume` 内的 `_resume()` 是 `loop.create_task` 的 fire-and-forget 协程。它在第 744 行被排入事件循环后，主协程继续执行到第 762 行 `await _handle_research_completion(...)`；该 await 的第一个内部挂起点（`_aload_research_task` 的 `afirst()` DB 调用）会把控制权交还事件循环，使 `_resume()` 与 `_handle_research_completion` 在各自的 await 点**交错执行**。

`_resume()` 的幂等短路（`callbacks.py:334`）：

```python
if not await aall_research_tasks_terminal(plan_session.id):
    return
```

若 `_resume()` 的 `aall_research_tasks_terminal`（内部 `acount` + `aexists`，见 `research_aggregation.py:57-70`）在 `record_partial` 把该 task 翻为 `DONE` **之前**执行，则读到 task 仍为 `RUNNING` → 返回 `False` → `_resume()` 直接 no-op 返回（既不续驱也不通知 barrier）。随后 `_handle_research_completion` 才把 task 翻终态并 `researching→merging`。chat 入口此后**没有任何其它消费者**驱动 `engine.advance`（这正是 D-2 缺口 b），session 永久停在 `merging`，barrier（注册键 `str(plan_session.id)`）永不被 `task_completed` 通知，chat 会话永不 resume。

`_handle_failed`（`:805` 在 `:814` `_handle_research_failure` 之前）有完全相同的结构性问题。

注意：`test_research_completion_callback.py` 里 `_passing_engine` 的 docstring 只覆盖了"task 已终态但 session 仍 researching"这一**窗口**（靠 engine 再跑一次 `amaybe_complete_research`）；它**没有**覆盖"`_resume` 在 task 翻终态之前就读到非终态"这条无防御的分支。测试当前通过只是因为线程池/DB 时序碰巧让 `record_partial` 先赢——属时序依赖，生产环境（真实 DB 延迟、不同调度）可复现卡死。

**Fix:** 让续驱在 research 完成处理**之后**才被调度，确保 `_resume()` 被创建时 DB 状态已一致（task 终态 + session 已 `merging`），届时 `_resume()` 必然走到 `adrive` 把 `merging→done` 并通知 barrier。即把两处 fire-and-forget 调度移到对应 research handler 之后：

```python
# _handle_completed: 先处理 research 完成（翻终态 + researching→merging），再调度续驱
try:
    await _handle_research_completion(session, p, log)
except Exception as exc:  # noqa: BLE001
    logger.warning("research_completion_callback_failed", session_id=session.session_id, error=str(exc))

# research 状态已落库后再调度 resume（消除竞态）
_schedule_workflow_resume(session, log)
_schedule_agent_session_resume(session, log)
```

`_handle_failed` 同理：把 `_schedule_agent_session_resume`（及 `_schedule_workflow_resume`）移到 `await _handle_research_failure(...)` 之后。（注：`_schedule_workflow_resume` 自身有"所有 SubAgentSession 终态才续跑"的二次 guard，工作流路径不受影响；移动顺序对其安全。）

## Warnings

### WR-01: `_run_repo_coding` 的 `repository.credential.ssl_verify` 在生产异步路径会抛异常，且被新测试掩盖

**File:** `server/workflows/nodes/ai/coding.py:927-931`

**Issue:**
PF-06 核心场景（私有仓 + token 非空）必经此 nested `git_credentials` 分支：

```python
if token:
    ssl_verify = (
        str(repository.credential.ssl_verify).lower()
        if repository.credential
        else "true"
    )
```

存在两个生产侧缺陷：

1. **异步反向 OneToOne**：`repository.credential` 是 `GitCredential` 的反向 `OneToOneField`（`repositories/models.py:603-607`，`related_name="credential"`）。生产路径 `_fetch_repositories`（`coding.py:731-740`）**未** `select_related("credential")`，故在 async 上下文里 `if repository.credential` 触发同步 DB 访问 → `SynchronousOnlyOperation`。
2. **字段不存在**：`GitCredential` 模型（`repositories/models.py:599-627`）**没有 `ssl_verify` 字段**，即便 OneToOne 访问成功也会 `AttributeError`。

由于 `_run_repo_coding` 经 `asyncio.gather(..., return_exceptions=True)`（`coding.py:430-432`）收集，异常会被转成该 repo 的 `failed`，于是 token 非空（PF-06 想修的私有仓）反而**不会成功 dispatch**——PF-06 的主目标在生产可能并未真正达成。

关键风险：新测试**主动掩盖**了这两点——`_make_real_repo` 用 `select_related("credential")` 重载（注释自承"避免 async 上下文反向 OneToOne 触发 SynchronousOnlyOperation"，`test_coding_node.py:386,400`），`_ssl_verify_attr` fixture 用 `monkeypatch.setattr(GitCredential, "ssl_verify", True, raising=False)`（注释自承"GitCredential 模型未定义该字段"，`test_coding_node.py:417-420`）。测试全绿但生产路径未被真实覆盖，给出端到端可用的假阳性。

> 该 nested 块为 Phase 43 之前既有代码（`git show 43e92bae` 显示 PF-06 仅新增 `git_env`/`branch_env`），严格意义属 pre-existing，但 PF-06 的价值依赖此路径成功，且新测试刻意绕过，故纳入本次评审。

**Fix:** 二选一并使测试如实覆盖生产路径：
- 推荐：`_fetch_repositories` 加 `.select_related("credential")`，并把 `ssl_verify` 取值改为不依赖不存在的字段（既然新增的顶层 `env_FRIDAY_TASK_GIT_SSL_VERIFY` 已硬编码 `"false"` 对齐 chat 基线，nested dict 的 `ssl_verify` 可直接取常量或 `getattr(repository.credential, "ssl_verify", False)`）。
- 或：在模型补 `ssl_verify` 字段并迁移；同时确保异步预取。
- 测试侧移除 `select_related` 重载与 `monkeypatch ssl_verify`，让 `_run_repo_coding` 跑真实生产取数路径。

### WR-02: `_schedule_chat_plan_resume` 续驱后无条件通知 barrier，未守门终态

**File:** `server/subagent/api/callbacks.py:341-357`

**Issue:**
`adrive_plan_session_to_pause_or_terminal` 可能在**非终态**短路返回（`resume.py:63-74` 的 clarifying-pending / researching-在途短路）。但 `_resume()` 在 adrive 返回后**无条件**构建 `BlockingTaskResult` 并 `barrier.task_completed(...)`：

```python
plan_session = await adrive_plan_session_to_pause_or_terminal(engine, plan_session)
success = plan_session.status == PlanSessionStatus.DONE
...
satisfied = await get_barrier_manager().task_completed(str(plan_session.id), result)
```

若续驱过程中 engine 把 session 推进到一个新的 `clarifying`（pending）或回到 `researching` 而短路，session 此刻并非 `{DONE, FAILED}`，却仍会以 `success=False`、`error="{}"`（`str(plan_session.error or {})`）通知 barrier，**提前把 chat 阻塞任务解析为失败**，与 RESEARCH 步骤 2 伪代码"仅当 session 到 DONE/FAILED 才回灌"的设计相悖。当前 merge 段一般不回退到 clarifying/researching，故概率低，但缺少守门是健壮性缺陷。

**Fix:** 仅在终态回灌；非终态短路（仍需再次挂起/等待）时不通知 barrier：

```python
if plan_session.status not in (PlanSessionStatus.DONE, PlanSessionStatus.FAILED):
    log.info("chat_plan_resume_resuspended", plan_session_id=str(plan_session.id), status=plan_session.status)
    return
```

### WR-03: T-43-TAMPER 守门只校验 entrypoint，缺研究任务归属校验

**File:** `server/subagent/api/callbacks.py:329-334`

**Issue:**
RESEARCH 的 T-43-TAMPER 缓解明确要求"`PlanSession.entrypoint==chat` 守门 **+** `RepoResearchTask` 归属该 session 校验"。实现只做了前者：`plan_session_id` 取自 runner 可经 progress 篡改的 `session.last_output`，随后仅 `entrypoint == CHAT` 守门 + `aall_research_tasks_terminal(plan_session.id)`，**未校验本 `SubAgentSession` 的 `research_task_id` 确属该 `plan_session`**。半可信 runner 可把 `plan_session_id` 指向另一个 chat 入口的受害 `PlanSession`，从而触发对其的续驱 + barrier 回灌。

实际影响有限：`plan_session_id` 是难以猜测的 UUID，且 `aall_research_tasks_terminal` + `entrypoint==chat` 双重 guard 意味着只能"推进一个本就全终态、确实该完成的会话"，回灌的 `output` 取自服务端 `current_plan_version`（非 runner 输入）。但这是文档化威胁缓解未完全落地。

**Fix:** 续驱前用已加载的 `task`（`_aload_research_task` 已读出）交叉校验 `str(task.session_id) == str(plan_session.id)`，或直接以 `task.session_id` 派生 `plan_session`，不信任 `last_output.plan_session_id` 单独取值。

## Info

### IN-01: 多仓"最后一个"容器并发完成可能重复驱动 engine

**File:** `server/subagent/api/callbacks.py:333-341`

**Issue:** 两个调研容器近乎同时完成时，各自回调的 `_resume()` 都可能读到"全部终态"并各调一次 `build_orchestration_engine()` + `adrive`，造成重复的 merge/architect LLM 调用（成本）。状态一致性由 `PlanSessionService.transition` 的 `ConcurrentTransitionError` + `BarrierManager.task_completed` 去重兜底，不致数据损坏。属 RESEARCH 已文档化的已知 race。

**Fix:**（可选）若成本敏感，可在续驱前加一次 `transition` 抢占/状态 guard；本 phase 作为地基可接受。

### IN-02: 回灌 `output` 为 plan_version id 而非主方案摘要

**File:** `server/subagent/api/callbacks.py:345`

**Issue:** `output_text = str(plan_session.current_plan_version or "")` 回灌的是版本标识而非方案摘要文本，chat 端拿到的是 id 字符串。符合 RESEARCH Assumption A2（"id/摘要均可，闭环不阻塞"），如需更丰富呈现可后续格式化。

**Fix:**（可选）后续如需，按 deep_analysis 的结构化追加范式拼接主方案摘要。

---

_Reviewed: 2026-06-16_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
