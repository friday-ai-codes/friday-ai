---
phase: 43-env-resume
verified: 2026-06-16T19:20:00Z
status: human_needed
score: 23/23 must-haves verified
overrides_applied: 0
human_verification:

  - test: "真实 runner + Docker + 任务容器端到端 resume：私有仓 clone 成功 + 落正确目标分支（非 friday/task-{id}）"
    expected: "派发编码容器后，容器用注入的 git token 成功 clone 私有仓，并在 env_FRIDAY_TASK_BRANCH_STRATEGY 指定的工作分支上提交（target_branch 为 base_branch）"
    why_human: "需真实 runner + Docker + 任务容器 + 真实编码 agent，本地无法闭环（VALIDATION.md Manual-Only + STATE.md Deferred Items）"

  - test: "真实 deep-research 容器在途完成 → chat/workflow 会话自动续驱到 done"
    expected: "调研容器完成回调后，chat 入口 PlanSession 经 callback 续驱 merging→architecting→done，barrier 回灌使对话自动 resume 呈现 canonical 主方案"
    why_human: "需真实 runner + Docker + 调研容器 + 真实编排 LLM，本地无法闭环（VALIDATION.md Manual-Only + STATE.md Deferred Items）"
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  status: human_needed
---

# Phase 43: 编码 env 对齐 + 通用 resume 回流地基 Verification Report

**Phase Goal:** 修 PF-06（workflow `AICodingNode._run_repo_coding` 缺失 branch strategy / git token env 注入，对齐 chat `coding_session_service.build_dispatch_metadata`）+ 建立通用 coding/plan_session → workflow/session resume 回流通路（消化 v0.7 audit D-2）。
**Verified:** 2026-06-16T19:20:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

#### Plan 01 — PF-06 编码 env 对齐 (`coding.py`)

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1 | token 非空 → 顶层 `env_FRIDAY_TASK_GIT_ACCESS_TOKEN`/`GIT_AUTH_TYPE`/`GIT_SSL_VERIFY` | ✓ VERIFIED | `coding.py:941-945`（`git_env` 在 `if token:` 块内填三键，并入 metadata `coding.py:1015`） |
| 2 | `BRANCH_STRATEGY`=branch_name、`TARGET_BRANCH`=base_branch | ✓ VERIFIED | `coding.py:954-957` 无条件注入 `branch_env`，取本次调用参数（多仓 per-repo） |
| 3 | token 非空 + `git@` SSH URL → 改写为 `https://host/path.git` | ✓ VERIFIED | `coding.py:947-950` 正则锚定 `git@([^:]+):(.+?)(?:\.git)?$`，`DispatchTask(repo_url=repo_url)` `:1003` 用改写后变量 |
| 4 | token 为空 → 不注入 access_token 键且不改写 repo_url（降级不回退） | ✓ VERIFIED | `git_env` / SSH 改写均在 `if token:` 块内；空 token 时 metadata 不含 access_token 键、`repo_url` 原样 |
| 5 | git token 绝不入日志，仅记 `has_git_token` 布尔 | ✓ VERIFIED | `coding.py:1065-1071` `task_dispatched_to_runner` 仅记 `has_git_token=bool(token)` 等布尔；测试 `test_no_token_leak_in_dispatch_logs` 守护 |
| 6 | nested `metadata['git_credentials']` dict 原样保留（零回归） | ✓ VERIFIED | `coding.py:927-933` 保留 nested dict，`:1014` 并入 metadata |

#### Plan 02 — RESUME-01 共享续驱 helper (`resume.py`)

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 7 | 入口无关共享 helper `adrive_plan_session_to_pause_or_terminal(engine, session)` | ✓ VERIFIED | `resume.py:24-79`，engine 由调用方传入，无第二个 engine 工厂 |
| 8 | session 到终态 `{DONE, FAILED}` 返回该 session | ✓ VERIFIED | `resume.py:46,48,79` while 条件 + 终态返回 |
| 9 | researching 且 `aall_research_tasks_terminal` False → 立即短路返回 | ✓ VERIFIED | `resume.py:71-74` |
| 10 | clarifying 且有未答 Clarification（`answered_at` 为空）→ 立即短路返回（保护 HITL） | ✓ VERIFIED | `resume.py:63-68` 照搬 `_maybe_suspend` 的 `answered_at__isnull=True` query |
| 11 | advance 步数超 max_steps → `transition(session, "fail")` 标记失败并返回 | ✓ VERIFIED | `resume.py:50-57` reason=`advance_step_limit` |
| 12 | helper 不直接写 `session.status`，状态只经 `engine.session_service.transition` | ✓ VERIFIED | `resume.py` 全文无 `session.status =` 赋值；唯一状态写为 `:52` transition |

#### Plan 03 — RESUME-01 chat 入口续驱 + barrier 回灌 (`callbacks.py`)

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 13 | chat 入口 plan_research 全终态后 callback 续驱 engine 到 done | ✓ VERIFIED | `callbacks.py:348-351` `build_orchestration_engine()` + `adrive_...`；接线于 `_handle_completed:777,793` |
| 14 | 续驱到终态后 `BarrierManager.task_completed(str(plan_session.id), result)` 回灌 | ✓ VERIFIED | `callbacks.py:378`，task_id 用 `str(plan_session.id)` |
| 15 | 工作流入口（有 node_execution）不走 chat 续驱，仍走 `_schedule_workflow_resume` | ✓ VERIFIED | `callbacks.py:111-113` 早返；`workflow_entry_session_skips_chat_resume` 测试守护 |
| 16 | 重复回调 / 部分调研未终态 → 不重复续驱、不重复 notify（幂等） | ✓ VERIFIED | `callbacks.py:344` `aall_research_tasks_terminal` 短路 + barrier 自带去重 |
| 17 | 续驱内部抛异常 → 回调仍返 200（fail-soft swallow） | ✓ VERIFIED | `callbacks.py:385-386` 独立 try/except + warning；fire-and-forget `:388-393` |
| 18 | plan_research 容器 failed → barrier `success=False` 回灌不卡死 | ✓ VERIFIED | `_handle_failed:833,849` 接线；`callbacks.py:365` `success=(status==DONE)` |
| 19 | chat 续驱仅在 `PlanSession.entrypoint==chat` 守门下触发 | ✓ VERIFIED | `callbacks.py:330-332` 服务端权威字段守门 |

#### Plan 04 — RESUME-01「不造两套」收尾 (`plan_research.py` / `plan_research_tools.py`)

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 20 | 工作流节点 advance 循环复用共享 helper | ✓ VERIFIED | `plan_research.py:123,146` 调用 helper；无内联 `while session.status not in` 残留 |
| 21 | chat 工具 start_plan_research 复用同一 helper | ✓ VERIFIED | `plan_research_tools.py:92,127` 调用 helper；`_maybe_suspend` marker 映射保留 |
| 22 | clarifying-未答 / researching-在途 挂起行为零回归（needs-clarification 不被错误 FAILED） | ✓ VERIFIED | `test_plan_research_node.py::test_clarifying_suspends_waiting_event` 通过（5 passed） |
| 23 | start_plan_research 占位文案/description 改为「调研完成后自动融合回流」，不再声称未接入 | ✓ VERIFIED | `plan_research_tools.py:41,256-257` 肯定表述；全仓搜索无「尚未接入」残留 |

**Score:** 23/23 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `server/workflows/nodes/ai/coding.py` | `_run_repo_coding` 注入对称 git/branch env + SSH→HTTPS | ✓ VERIFIED | 含 `env_FRIDAY_TASK_BRANCH_STRATEGY` `:955`；WR-01 已修（不访问不存在的 `credential.ssl_verify`，硬编码 `"false"` `:932,945`） |
| `server/tests/test_coding_node.py` | PF-06 dispatch metadata env 键断言 | ✓ VERIFIED | `TestRunRepoCodingPF06` 6 测全绿 |
| `server/services/plan_orchestration/resume.py` | 共享续驱 helper | ✓ VERIFIED | barrel re-export 经 `services.plan_orchestration` 可导入 |
| `server/tests/services/test_plan_resume_driver.py` | helper 单测 | ✓ VERIFIED | 5 passed（终态/researching/clarifying/step 上限） |
| `server/subagent/api/callbacks.py` | `_schedule_chat_plan_resume` + 分支接线 | ✓ VERIFIED | `:290` 定义；`:138` 委派；CR-01/WR-02/WR-03 已修 |
| `server/tests/services/test_research_completion_callback.py` | 闭环/回归/幂等/fail-soft/失败路径 | ✓ VERIFIED | 17 passed |
| `server/workflows/nodes/ai/plan_research.py` | 节点复用 helper（行为零变更） | ✓ VERIFIED | `:146` 复用 helper |
| `server/agents/tools/plan_research_tools.py` | 工具复用 helper + 文案更新 | ✓ VERIFIED | `:127` 复用 + `:256` 文案更新 |

### Key Link Verification

| From | To | Via | Status |
| ---- | -- | --- | ------ |
| `_run_repo_coding` | `DispatchTask.metadata` | 顶层 `env_FRIDAY_TASK_*` 并入 | ✓ WIRED (`coding.py:1015-1016`) |
| `_run_repo_coding` | `aresolve_git_token` | token 解析复用 | ✓ WIRED (`coding.py:928`) |
| `resume.py` | `aall_research_tasks_terminal` | researching 在途短路 | ✓ WIRED (`resume.py:71`) |
| `plan_orchestration/__init__.py` | `resume.adrive_...` | barrel re-export | ✓ WIRED |
| `_schedule_agent_session_resume` (plan_research 分支) | `_schedule_chat_plan_resume` | entrypoint==chat 守门后委派 | ✓ WIRED (`callbacks.py:138`) |
| `_schedule_chat_plan_resume` | `adrive_plan_session_to_pause_or_terminal` | engine 续驱 | ✓ WIRED (`callbacks.py:351`) |
| `_schedule_chat_plan_resume` | `barrier.task_completed` | `task_id=str(plan_session.id)` 回灌 | ✓ WIRED (`callbacks.py:378`) |
| 节点/工具 execute | `adrive_plan_session_to_pause_or_terminal` | 复用共享续驱循环 | ✓ WIRED (`plan_research.py:146` / `plan_research_tools.py:127`) |

### Probe Execution / Behavioral Spot-Checks

| Suite | Command | Result | Status |
| ----- | ------- | ------ | ------ |
| 5 套 phase 测试 | `uv run pytest tests/test_coding_node.py tests/services/test_plan_resume_driver.py tests/services/test_research_completion_callback.py tests/workflows/test_plan_research_node.py tests/agents/test_start_plan_research_tool.py -q` | 45 passed, 1 xfailed (11.28s) | ✓ PASS |

1 xfailed = `test_build_output_structure`（`@pytest.mark.xfail` 标注 `_build_output` 结构已变更，预期失败，非回归）。

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| PF-06 | 43-01 | workflow 编码 branch strategy / git token env 注入对齐 chat | ✓ SATISFIED (code) | `coding.py:941-957` + 6 守护测试。**注：** `REQUIREMENTS.md` 仍标 `[ ]` / 表格 `Pending`（文档同步滞后，非代码缺口） |
| RESUME-01 | 43-02/03/04 | 通用 coding/plan_session → workflow/session resume 回流 | ✓ SATISFIED | `resume.py` + `callbacks.py` 接线 + 节点/工具复用；`REQUIREMENTS.md` 已标 `[x]` Complete |

无 orphaned requirements（REQUIREMENTS.md Phase 43 仅映射 PF-06 / RESUME-01，两者均在 plan frontmatter 声明且已实现）。

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| `coding.py` | 1045 | `metadata={"placeholder": True}` | ℹ️ Info | 合法——找不到 main_session 时创建占位 AgentSession 的元数据标志，非未实现桩 |
| `plan_research_tools.py` | 255 | `"placeholder": (...)` | ℹ️ Info | 合法——挂起 marker dict 的键名（UI 展示文案），文案为肯定表述「调研完成后自动融合」，非桩 |

无 `TODO`/`FIXME`/`XXX`/`TBD`/`HACK`/「尚未接入」debt marker。无 stub/空实现。

### Code Review 修复核对（来自 43-REVIEW.md）

| 编号 | 问题 | 修复状态 | 代码证据 |
| ---- | ---- | -------- | -------- |
| CR-01 | chat 续驱调度早于 research 完成处理 → 竞态卡死 | ✓ 已修 | `callbacks.py:777→793`（completed）/ `833→849`（failed）：续驱调度移至 research handler 之后 |
| WR-01 | `_run_repo_coding` 访问不存在的 `credential.ssl_verify` 致生产异常 | ✓ 已修 | `coding.py:927-933,945` 不再访问反向 OneToOne，硬编码 `"false"` 对齐 chat 基线 |
| WR-02 | 续驱后无条件 notify barrier，未守门终态 | ✓ 已修 | `callbacks.py:353-362` 非终态短路 `return`，仅 `{DONE,FAILED}` 才回灌 |
| WR-03 | 守门只校验 entrypoint，缺研究任务归属校验 | ✓ 已修 | `callbacks.py:334-341` 交叉校验 `task.session_id == plan_session.id` |

IN-01 / IN-02 为 RESEARCH 已文档化 by-design 取舍，地基 phase 接受（不在修复范围）。

### Human Verification Required

以下为 `43-VALIDATION.md` Manual-Only + STATE.md Deferred Items 明确记录的「本地无法闭环」项——按任务指示作为 **human_needed**（非 gap）：

1. **真实 runner + Docker 私有仓 clone + 正确分支** — 派发编码容器，观察用注入 git token 成功 clone 私有仓 + 落 `env_FRIDAY_TASK_BRANCH_STRATEGY` 指定分支（不再落默认 `friday/task-{id}`）。需真实 runner + Docker + 任务容器 + 真实编码 agent。
2. **真实调研容器在途完成 → 会话自动续驱到 done** — 调研容器完成回调后，chat/workflow 会话经 callback 续驱 merging→architecting→done + barrier 回灌自动 resume。需真实 runner + Docker + 调研容器 + 真实编排 LLM。

### Gaps Summary

无阻断目标达成的 gap。全部 23 条 must-have truth 在实际代码中验证通过，5 套自动化测试全绿（45 passed, 1 documented xfail），8 个产物 + 8 条 key link 全部 WIRED，REVIEW.md 的 1 个 critical + 3 个 warning 修复均已落地并经代码核对。

唯一开放项为 2 个真实容器端到端 resume 验收——这些是 VALIDATION.md / STATE.md 明确记录的 Manual-Only Deferred 项（本地无 runner+Docker 无法闭环），按任务指示归为 human_needed 而非 gap。

**观察（非 gap）：** `REQUIREMENTS.md` 中 PF-06 仍标 `[ ]` 且映射表为 `Pending`（RESUME-01 已正确标 Complete）。代码层 PF-06 已完成，属文档勾选同步滞后，建议下游更新但不影响目标达成。

---

_Verified: 2026-06-16T19:20:00Z_
_Verifier: Claude (gsd-verifier)_
