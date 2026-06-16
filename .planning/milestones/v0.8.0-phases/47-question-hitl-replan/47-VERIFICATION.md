---
phase: 47-question-hitl-replan
verified: 2026-06-17T00:30:00Z
status: passed
score: 8/8 must-haves verified
overrides_applied: 0
deferred:
  - truth: "真实 runner + Docker 容器编码遇阻 → 飞书提问卡片 → 用户回答 → 容器续跑 → wave 推进端到端"
    addressed_in: "既有 deferred（里程碑级，本地无法闭环）"
    evidence: "47-CONTEXT.md / 47-VALIDATION.md Manual-Only §：需真实 runner + Docker + 飞书配置；本 phase 以 mock IO 边界覆盖发起→等待→回答→续跑（accepted verification level）"
  - truth: "chat 编码入口（coding_session_service）遇阻 HITL 接线"
    addressed_in: "follow-up（task 侧 question helper 入口无关已就绪以便复用）"
    evidence: "47-CONTEXT.md deferred §：本 phase 优先 workflow wave 入口"
  - truth: "test_batch_pr.py 既有失败（Phase 26 stale patch target）"
    addressed_in: "Phase 26 遗留 backlog（非 Phase 47 范围，已显式 deferred）"
    evidence: "Phase 47 未触 pr.py / test_batch_pr.py"
---

# Phase 47: 编码遇阻 → question 抛人（HITL，非全自动 replan）Verification Report

**Phase Goal:** 补编码遇阻的 HITL 回路——task 侧发起 question（复用已有 question 协议契约 + orchestrator resume），抛给用户/orchestrator 等回答后续跑；显式非目标：不做编码中全自动回溯重规划。
**Verified:** 2026-06-17T00:30:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Success Criteria (ROADMAP)

| SC | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | 编码容器遇阻时 task 侧能发起 question（复用已有 question 协议契约），不再走「Server 端不再重试」死路 | ✓ VERIFIED | `CallbackClient.report_question`（callback.py:293，POST type=question，payload 对齐 QuestionPayloadSerializer）+ `ask_user` 进程内 MCP 工具（question_loop.py:184）+ executor coding 挂载；`test_question_loop.py` 8/8 PASS |
| 2 | question 抛给用户/orchestrator，回答后经 Phase 43 resume 通路驱动对应 wave/task 续跑 | ✓ VERIFIED | `send_question_card_enhanced` 经 `_resolve_notification_chat_id` 路由（node_execution fallback）；e2e：遇阻 RUNNING → `aadvance_coding_waves` waiting（不 dead-end）→ 回答 completed → dispatch 下游；`test_blocked_wave_task_stays_waiting` + `test_answer_then_complete_resumes_wave` PASS |
| 3 | 显式非目标守护：编码遇阻只抛人、不触发全自动 replan/重调研 | ✓ VERIFIED | `test_hitl_path_does_not_trigger_replan`：spy `amaybe_complete_research` 零调用；超时 default/优雅失败不挂起、不 replan（`ask_user_and_wait` QuestionTimeout）PASS |

### Observable Truths (must_haves)

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | task 侧经既有 question 协议（type=question）发起，payload 对齐 serializer，不新增协议键 | ✓ VERIFIED | `report_question` payload 键集 == {question,options,context,code_snippet,default_option,timeout_minutes}；`test_report_question_posts_question_frame` PASS |
| 2 | ask_user 经 answer.json 取回答，等待期心跳保活使容器保持 RUNNING（不走 report_failed 死路） | ✓ VERIFIED | `ask_user_and_wait` 轮询 answer.json + `report_status` 心跳；`test_returns_answer_from_volume` PASS；遇阻路径不调 report_failed |
| 3 | 超时：有 default_option 用之续跑，否则优雅失败；绝不挂起/replan | ✓ VERIFIED | `test_ask_user_timeout_with_default_returns_default` + `test_ask_user_timeout_without_default_raises`（QuestionTimeout）PASS；有界轮询 |
| 4 | 向后兼容：无 callback 配置不挂 ask_user，编码零回归 | ✓ VERIFIED | `build_ask_user_mcp_server` 无 callback_url 返回 None；`test_build_ask_user_mcp_server_none_when_standalone` + task 全套 179 passed |
| 5 | 脱敏：问题/回答不入日志 | ✓ VERIFIED | report_question/ask_user/handler 仅记 has_*/id/status；源审查通过 |
| 6 | wave 编码（node_execution）question 卡片经 node_execution chat_id 路由 | ✓ VERIFIED | `send_question_card_enhanced` 委派 `_resolve_notification_chat_id`；`test_send_card_routes_via_node_execution` PASS |
| 7 | 缺 chat_id fail-soft（不发卡、不抛、InteractionLog 仍创建） | ✓ VERIFIED | `test_send_card_failsoft_no_chat_id` PASS；`_handle_question` 仍创建 InteractionLog（不受发卡影响） |
| 8 | 续跑只走 Phase 43/44，无新 resume 通路；既有 chat 提问循环零回归 | ✓ VERIFIED | 无新 resume 代码；`test_answer_then_complete_resumes_wave` 经 aadvance_coding_waves 推进；`test_question_loop_integration` 3/3 + `test_coding_wave` 7/7 PASS |

## Test Evidence
- task：`tests/test_question_loop.py` 8/8 PASS；task 全套 179 passed / 3 skipped（零回归）。
- server：`tests/test_coding_question_hitl.py` 6/6 + `test_question_loop_integration` 3/3 + `test_coding_wave` 7/7 + 飞书 question 卡片/回调 20/20 PASS。
- ruff line 100 全部通过（task + server 改动文件）。

## Non-Goal Guard (HITL-01c)
编码遇阻 question/answer/resume 全链路零触发 research/replan 编排（spy 断言）；全自动回溯重规划（REPLAN-01）按里程碑显式非目标留 backlog。

## Verdict
**PASSED** — 3/3 Success Criteria + 8/8 Observable Truths verified（mock IO 边界）。真实 runner + Docker 端到端 HITL 验收沿用既有 deferred。
