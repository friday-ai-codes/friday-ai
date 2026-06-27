---
phase: 91-clarification-outlets-resume
plan: 03
subsystem: api
tags: [clarification, feishu_callback, plan_clarify, resume, approve_node, async, sync_to_async, inv6, observability, anti-tamper]

# Dependency graph
requires:
  - phase: 91-01
    provides: aanswer_round_and_resume（入口无关「作答 + 续推」共享回流 helper）
  - phase: 91-02
    provides: build_clarification_card 携 clarification_id + 新 action plan_clarify_answer + PlanClarifyCallback 订阅 + 发卡按 order 枚举 q{i}
  - phase: 89-02
    provides: plan_revision_callback 范式（_extract_callback_data/_ack_card/_run_in_thread/_aget_waiting_node/approve_node/_FeishuResponder）
provides:
  - "新回调 action plan_clarify_answer（前缀 plan_clarify_）：handler feishu.callbacks.plan_clarify_callback.handle_plan_clarify_action"
  - "工作流侧 CLARIFY-05/06 端到端闭环：群卡发出（91-02）→ 收答续推（本 plan）→ approve_node 重调度 ai_plan_research"
  - "_build_answers：按 order 枚举 q{i}/qt{i} → answers[]（索引↔question_id 固化，WARNING #3）"
affects: [91-04 会话端续推 endpoint, 92 插槽系统]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "飞书澄清回调 = 同步即时 ack 卡（3s 内）+ _run_in_thread 后台续推（bind_task_context re-bind 归因）；据卡片权威 clarification_id 取轮、绝不信回调直传 session_id（防伪造）"
    - "回调按 order_by('order') 整轮取子题映射 answers[]（不依赖部分已答 filter，索引↔question_id 不随重放/部分已答漂移）——与 91-02 发卡侧枚举逐字一致"
    - "写入只经 aanswer_round_and_resume → answer_round（INV-6），回调无 .objects.create/.update/.save 旁路写 delivery 表"

key-files:
  created:
    - server/feishu/callbacks/plan_clarify_callback.py
    - server/tests/feishu/test_plan_clarify_callback.py
  modified:
    - server/feishu/urls.py

key-decisions:
  - "回调按 order_by('order') 取整轮子题（不加 answered_at__isnull=True filter）——索引↔question_id 不随部分已答/重放漂移（WARNING #3），与 91-02 发卡侧（发卡时整轮均未答）枚举一致；answer_round 自身按题幂等过滤已答，重放 no-op"
  - "据卡片权威 clarification_id 取轮（绝不信回调直传 session_id），缺 clarification_id/execution_id/node_id 即拒（T-91-03-01 防伪造），不退化到信任客户端锚"
  - "置灰卡发到 callback.chat_id（点击卡所在群=项目群），space 经 _resolve_space(node_execution) 取，create_feishu_im_client_for_project 发卡 best-effort（mirror plan_revision _send_card_best_effort），避免再解析项目群一跳"
  - "engine 经 build_orchestration_engine(node_execution_id=str(node_execution.id)) 构造（工作流入口形态，CR-02 调研容器回调 resume 钥匙）显式传入 helper，不走 helper 缺省 chat 入口构造"
  - "_build_answers 抽为纯函数，便于单测固化「索引↔question_id」映射断言（WARNING #3 防错位）"

patterns-established:
  - "Pattern: 飞书澄清回调收答闭环 = ack 即时返回 + 后台（幂等门 _aget_waiting_node → 据卡片 clarification_id 取整轮 order 子题 → _build_answers → aanswer_round_and_resume 同源续推 → approve_node 重调度 → 置灰卡）+ 全程 fail-soft 脱敏 INV-6"

requirements-completed: [CLARIFY-05, CLARIFY-06]

# Metrics
duration: ~20min
completed: 2026-06-27
---

# Phase 91 Plan 03: plan_clarify 飞书澄清回调收答 + 续推 + 重调度 Summary

**新建飞书澄清专用回调 `@register_card_callback("plan_clarify_")`——群卡 form_submit（`q{i}`/`qt{i}`）经 `CardCallbackView` 合并进 action_value → 据卡片权威 `clarification_id` 取该轮整轮子题（按 `order`，绝不信回调直传 session_id 防伪造）→ 按 order 枚举映射 `answers[]`（索引↔question_id 与 91-02 发卡侧逐字一致，WARNING #3）→ 同源 helper `aanswer_round_and_resume`（91-01）写答案 + 续推 PlanSession（工作流入口 engine 带 node_execution_id）→ `approve_node` 重调度挂起的 `ai_plan_research` 节点 → 置灰卡 best-effort，完成工作流侧 CLARIFY-05/06 收答端到端闭环。**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-06-27T08:33:00Z
- **Completed:** 2026-06-27T08:40:00Z
- **Tasks:** 1
- **Files modified:** 3（2 新建 + 1 改）

## Accomplishments
- **同步入口 `handle_plan_clarify_action`（CLARIFY-05）**：`_extract_callback_data` 取 action/execution_id/node_id/clarification_id/question_count（`form_value` 的 `q{i}`/`qt{i}` 已被 `CardCallbackView` 合并进 action_value 同在 data 里）；`action != "plan_clarify_answer"` → None；缺 clarification_id/execution_id/node_id → warning + None（T-91-03-01 防伪造，绝不退化信任 session_id）；`_run_in_thread(_do_clarify_answer_async(...))` 后台续推 + 即时返回 `_ack_card`（3s 内同步，Don't Hand-Roll，T-91-03-05）。
- **后台 `_do_clarify_answer_async`（CLARIFY-06）**：`bind_task_context(user_id=callback.user_open_id, source="feishu", component="plan_orchestration")` re-bind 触发用户（T-91-03-04）。① 幂等门 `_aget_waiting_node`（非 waiting → ignored + return，T-91-03-02 防重放）；② **据卡片权威 clarification_id 取整轮子题** `ClarificationQuestion.objects.filter(clarification_id=...).order_by("order")`（`_acollect_round_questions`，**不信回调直传 session_id**）；③ `_build_answers` 按 order 枚举 `q{i}`（select 值，single=str/multi=list）/ `qt{i}`（freeform）组 `answers[{question_id, selected, freeform_text}]`；④ 同源续推 `engine = build_orchestration_engine(node_execution_id=str(node_execution.id))` → `aanswer_round_and_resume(clarification_id, answers, engine=engine)`（91-01）；⑤ 重调度 `node_execution.approval_data = {clarification_answered, clarification_id}` + SUSPENDED→RUNNING + `WorkflowEngine().approve_node(node_execution, _FeishuResponder, "plan_clarify_answer")`（节点重入据 output_data.session_id 续推）；⑥ 置灰卡 best-effort（`build_clarification_answered_card` → `create_feishu_im_client_for_project` 发到 callback.chat_id）。
- **WARNING #3 索引↔question_id 固化**：回调按 `order_by("order")` 整轮取子题（**不依赖部分已答 filter**），与 91-02 发卡侧（发卡时整轮均未答、按 order 枚举 q{i}）枚举顺序逐字一致；`_build_answers` 抽为纯函数 + 单测显式断言「`q0`→子题0.id、`q1`→子题1.id」映射不错位（防重放下索引偏移）。
- **威胁缓解落实**：T-91-03-01 用卡片权威 clarification_id 查轮再经 helper 解析 session（绝不信直传 session_id）+ 越界 id 经 answer_round `answered_at IS NULL` 过滤 no-op；T-91-03-02 `_aget_waiting_node` 幂等门 + answer_round 按题幂等；T-91-03-03 异常 `redact_secrets_in_text` + 日志仅记 execution_id/node_id/clarification_id 标量；T-91-03-04 bind_task_context re-bind；T-91-03-05 `_ack_card` 即时返回 + `_run_in_thread` 后台；T-91-03-06 写入只经 answer_round（INV-6），回调无任何 `.objects.create/.update/.save` 旁路写 delivery 表。
- 全程 fail-soft：`except Exception` → `logger.error("plan_clarify_answer", status="failed", ...)` 绝不反噬飞书主响应 5xx；发卡 best-effort try/except 不阻断恢复。

## Task Commits

Each task was committed atomically:

1. **Task 1: plan_clarify 回调收答 + 同源 helper 续推 + approve_node 重调度** - `dc91f7f62` (feat)

**Plan metadata:** (final docs commit)

## Files Created/Modified
- `server/feishu/callbacks/plan_clarify_callback.py` - 新建澄清回调状态机（`@register_card_callback("plan_clarify_")` handler + `_extract_callback_data`/`_ack_card`/`_resolve_space`/`_aget_waiting_node`/`_acollect_round_questions`/`_build_answers`/`_do_clarify_answer_async`/`_send_answered_card_best_effort`/`_FeishuResponder`）
- `server/feishu/urls.py` - 加 `import feishu.callbacks.plan_clarify_callback`（import 触发 @register_card_callback 注册）
- `server/tests/feishu/test_plan_clarify_callback.py` - 新建 11 用例（前缀注册唯一 / 同步入口 ack·缺 id no-op·非目标动作 / `_build_answers` 映射固化 single·multi·freeform / 后台续推+approve_node / 非 waiting 幂等 / helper 抛错 fail-soft / 无子题短路）

## Decisions Made
- **回调取整轮 order 子题（不加 answered_at filter）**：索引↔question_id 不随部分已答/重放漂移（WARNING #3），与 91-02 发卡侧一致（每轮 clarification_id 是 91-01 多轮新建的全新轮、发卡时整轮均未答，故「整轮」== 发卡时枚举集）；answer_round 自身按题幂等过滤已答，重放天然 no-op。
- **据卡片权威 clarification_id（绝不信直传 session_id）**：缺 clarification_id 即拒，不退化信任客户端锚（T-91-03-01）；session 由 helper 经 `clar.session_id` 标量解析（91-01）。
- **置灰卡发到 callback.chat_id**：点击卡所在群即项目群，space 经 `_resolve_space(node_execution)` 取，`create_feishu_im_client_for_project` best-effort 发（mirror plan_revision `_send_card_best_effort`），避免再经 `ProjectService.resolve_or_create_group` 解析项目群一跳。
- **engine 显式传工作流入口形态**：`build_orchestration_engine(node_execution_id=str(node_execution.id))`（CR-02 resume 钥匙）传入 helper，不走 helper 缺省 chat 入口构造。
- **`_build_answers` 抽纯函数**：便于单测固化「索引↔question_id」映射断言（WARNING #3 防错位）。

## Deviations from Plan

None - plan executed exactly as written.（plan Task 1 action 逐项落地：同步 ack + 后台幂等门 + 据卡片 clarification_id 取整轮 order 子题 + answers 映射 + 同源 helper 续推 + approve_node 重调度 + 置灰卡，均 fail-soft 脱敏 INV-6。置灰卡发送目标取 callback.chat_id（点击卡所在群）而非 output_data.chat_id——ai_plan_research waiting output 不含 chat_id，属 plan「取 space 经 _resolve_space」语义内的实现选择，非偏离。）

## Issues Encountered
- **2 个既有 INV-6 守护失败（与本 plan 无关，war-room 未提交在制品）**：`tests/delivery -k inv6` → 2 failed / 26 passed，为 91-02 SUMMARY/STATE 已记的同两项：
  - `test_inv6_no_bypass_feishu_chat_id_write`：命中 `initiatives/services/project_service.py:365/404`（`project.feishu_chat_id = ...`）——`git status` 标 `M server/initiatives/...` 的 war-room 未提交改动。
  - `test_inv6_no_bypass_canonical_plan_write`：命中 `initiatives/services/plan_deepen_service.py:267`（docstring）/ `feishu/callbacks/plan_revision_callback.py:11`（89-02 既有 docstring 字面误判）。
  - **确认与 91-03 无关**：命中文件均非本 plan 新增的 `plan_clarify_callback.py`（该文件无 `.feishu_chat_id =` / 无 TechnicalPlan/PlanVersion 旁路写，守护未 flag）；本 plan 写入只经 `aanswer_round_and_resume → answer_round`（INV-6）。记 deferred-items.md，不在 91-03 范围内修复。

## Threat Surface Scan
threat_model 六项 mitigate 全落实（见 Accomplishments 威胁缓解段）。无新增网络端点（复用既有 `card/callback/` 单一回调入口，按 action 前缀路由）/ 认证路径 / schema 变化（无 migration）。卡片 value 仅携服务端权威 `clarification_id`，回调据其取轮、绝不信回调直传 session_id；写入只经 answer_round（INV-6）。无新威胁面。

## Known Stubs
None - 本 plan 落地飞书回调收答闭环（解析 form_value → answers → 同源 helper 续推 → approve_node 重调度），无 UI 渲染、无 mock 数据。会话端续推 endpoint（91-04）与前端 ClarificationCard（91-05）按 ROADMAP 规划接续，非 stub。

## User Setup Required
None - 飞书回调走既有 `card/callback/` 端点 + `create_feishu_im_client_for_project` 凭证链，无新增配置。

## Next Phase Readiness
- 工作流侧 CLARIFY-05/06 端到端闭环就绪：CLARIFYING 挂起发卡（91-02）→ 群卡提交回调收答（本 plan）→ 同源 helper 续推 + approve_node 重调度 `ai_plan_research`。
- 同源续推单一来源：飞书回调（本 plan）与会话 endpoint（91-04）均调 `aanswer_round_and_resume`，入口私有重调度（approve_node / chat barrier）各自实现，不造两套。
- 索引↔question_id 映射固化（WARNING #3），91-04 会话端按相同 order 约定收 answers[]。
- 验收：`tests/feishu/test_plan_clarify_callback.py` 11 测绿；`tests/feishu` + `tests/delivery/test_clarification_service.py` 116 测绿（含 INV-6 子模型守护）；`test_plan_research_node.py` 12 测绿；ruff format/check + mypy 干净。

---
*Phase: 91-clarification-outlets-resume*
*Completed: 2026-06-27*

## Self-Check: PASSED
- FOUND: server/feishu/callbacks/plan_clarify_callback.py
- FOUND: server/tests/feishu/test_plan_clarify_callback.py
- FOUND: server/feishu/urls.py（plan_clarify_callback 注册）
- FOUND: .planning/phases/91-clarification-outlets-resume/91-03-SUMMARY.md
- FOUND commit dc91f7f62 (Task 1 feat)
