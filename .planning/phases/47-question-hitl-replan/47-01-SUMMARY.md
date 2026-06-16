---
phase: 47-question-hitl-replan
plan: 01
subsystem: task
tags: [hitl, question, ask-user, coding-blocked, mcp-tool, reuse-first]

# Dependency graph
requires:
  - phase: 43-env-resume
    provides: "容器统一回调端点 + callback 驱动 resume 通路（answer 回灌后续跑承接点）"
  - phase: 44-repocodingtask
    provides: "wave 编码 task（aadvance_coding_waves 把 RUNNING 视为在途）"
provides:
  - "CallbackClient.report_question —— POST type=question（payload 对齐 QuestionPayloadSerializer）"
  - "core/question_loop.py：ask_user_and_wait + build_ask_user_mcp_server + ask_user_allowed_tools + QuestionTimeout"
  - "executor coding 模式挂载 ask_user 工具（白名单含编码内建工具，standalone 零回归）"
affects: [47-02, coding-hitl]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "复用既有 question 协议契约（type=question + answer.json 共享卷）补 task 侧发起，不另造机制"
    - "进程内 SDK MCP 工具镜像 remote_tools.py（向后兼容 None / handler 永不 raise / 脱敏）"
    - "遇阻等待期心跳保活使 SubAgentSession 保持 RUNNING，server wave 调度天然视为在途（waiting）"

key-files:
  created:
    - task/core/question_loop.py
    - task/tests/test_question_loop.py
  modified:
    - task/integrations/callback.py
    - task/core/executor.py
    - task/core/runner.py

key-decisions:
  - "ask_user 用进程内本地工具（非 RemoteTool 远端通道）——遇阻提问是容器自包含 HITL，无需 server RBAC 往返"
  - "超时无回答：有 default_option 用之续跑，否则抛 QuestionTimeout 由 handler 转结构化工具错误；绝不无限挂起、绝不触发 replan"
  - "extra_allowed_tools 含 _BUILTIN_CODING_TOOLS（白名单排他陷阱）——挂 ask_user 不连带禁掉 Bash/Edit/Write（WR-02 同因），_execute_claude 去重保与 RemoteTool 共存"

patterns-established:
  - "编码遇阻 → ask_user 发问 + 阻塞等回答 → 据回答续跑（HITL，非全自动 replan）"

requirements-completed: [HITL-01]

# Metrics
duration: 12min
completed: 2026-06-17
---

# Phase 47 Plan 01: task 侧编码遇阻 question 抛人 Summary

**编码容器遇阻时不再走 `report_failed` 死路——给编码 agent 一个 `ask_user` 工具，复用既有 question 协议契约（`type=question` + `answer.json` 共享卷回灌）向人发问并阻塞等待回答，等待期心跳保活使容器保持 RUNNING，回答后据此续跑；超时则 default 续跑或优雅失败，绝不挂起/replan。**

## Performance
- **Duration:** ~12 min
- **Completed:** 2026-06-17
- **Tasks:** 4
- **Files:** 2 created, 3 modified

## Accomplishments
- `CallbackClient.report_question`（`task/integrations/callback.py`）：镜像 `report_failed`，POST `type=question`，内层 payload 严格对齐 server `QuestionPayloadSerializer`（question/options/context/code_snippet/default_option/timeout_minutes），standalone 短路 + httpx fail-soft + 脱敏。
- `task/core/question_loop.py`（新）：`ask_user_and_wait`（发问 → 轮询 `answer.json` → 心跳保活 → 取答返回 / 超时 default / 超时 `QuestionTimeout`，注入 `_now`/`_sleep` 可测）+ `build_ask_user_mcp_server`（无 callback_url → None 向后兼容）+ `_make_ask_user_handler`（永不 raise，超时/异常转结构化 `is_error`）+ `ask_user_allowed_tools`。
- `executor.py`：coding/execute 模式经既有 `_build_options` 扩展点（`extra_mcp_servers`/`extra_allowed_tools`）挂载 ask_user，白名单并入 `_BUILTIN_CODING_TOOLS` 防排他陷阱；`ClaudeRunner.__init__` 增可选 `callback`。
- `runner.py`：构造 `ClaudeRunner` 时传入 `self.callback`。
- 测试 `test_question_loop.py` 8/8 全绿；task 全套 179 passed/3 skipped 零回归；ruff line 100 通过。

## Task Commits
1. **Plan 01（task 侧 HITL 全部 4 任务）** - `5b202f20` (feat) — report_question + question_loop 模块 + executor/runner 接线 + 测试

_本 plan 一次原子提交（task 侧改动紧耦合）。_

## Files Created/Modified
- `task/core/question_loop.py` - ask_user 工具 + 等待回答循环（新）
- `task/tests/test_question_loop.py` - 守护测试（新）
- `task/integrations/callback.py` - report_question
- `task/core/executor.py` - coding 模式挂载 ask_user + ClaudeRunner callback 参数
- `task/core/runner.py` - 传入 callback

## Decisions Made
- 进程内本地工具（非远端 RemoteTool），遇阻提问容器自包含。
- 超时不挂起、不 replan：default 或优雅失败（QuestionTimeout → 结构化错误）。
- 白名单含编码内建工具，避免挂 ask_user 连带禁用 Bash/Edit/Write。

## Deviations from Plan
None - 按计划执行。

## Issues Encountered
None.

## User Setup Required
None.

## Next Phase Readiness
- task 侧发起能力就绪；Plan 02（server 侧 question 卡片路由 + e2e resume + no-replan 守护）可推进。
- 真实 runner + Docker 容器端到端 HITL 验收仍 deferred（本地无法闭环）。

## Self-Check: PASSED
- FOUND: task/core/question_loop.py（`async def ask_user_and_wait`）
- FOUND: task/integrations/callback.py（`def report_question`）
- FOUND: task/core/executor.py（`build_ask_user_mcp_server` 接线）
- FOUND commit: 5b202f20 (feat)
- TESTS: tests/test_question_loop.py 8/8 green；task 全套零回归

---
*Phase: 47-question-hitl-replan*
*Completed: 2026-06-17*
