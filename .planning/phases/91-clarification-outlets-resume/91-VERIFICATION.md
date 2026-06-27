---
phase: 91-clarification-outlets-resume
verified: 2026-06-27T18:00:00Z
status: human_needed
score: 4/4 must-haves verified
overrides_applied: 0
human_verification:
  - test: "启动前端，触发一次 plan 多题澄清（会话入口），确认会话内联卡渲染多题 + 单/多选 + ⭐推荐默认选中 + 自由输入，提交后切「已回复」且方案继续生成"
    expected: "ClarificationCard 渲染 questions[]（single button / multi Checkbox），推荐项默认选中；提交聚合 answers[] 打专路由，卡切「已回复」，PlanSession 续推、方案继续生成"
    why_human: "可视化渲染 + 端到端用户流程（提交→续推→方案生成）非单测可覆盖；91-05 PLAN 显式 defer 的 human-check"
  - test: "触发一次工作流入口（ai_plan_research）CLARIFYING 挂起，确认飞书机器人把澄清交互卡（单/多选 + ⭐推荐 + 其他）发到项目群，群内提交后方案续推"
    expected: "机器人发出 build_clarification_card（携 clarification_id + action=plan_clarify_answer）到项目群；提交触发回调 → answer_round + 续推 → approve_node 重调度 ai_plan_research → 置灰卡"
    why_human: "飞书外部服务集成（真实群发卡 + 回调）端到端非单测/grep 可验证（单测以 mock FeishuIMService.send_card 验证调用）"
---

# Phase 91: 澄清出口面 + 回流 resume Verification Report

**Phase Goal:** 澄清请求能在「AI 会话」与「工作流/群」两出口面发出，用户作答统一回流并续推编排，支持多轮且不无限挂起；围绕 Phase 90 结构化模型建设。
**Verified:** 2026-06-27T18:00:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | AI 会话中澄清请求内联渲染为单/多选提问卡，用户作答经 endpoint 回流（CLARIFY-04） | ✓ VERIFIED | `ClarificationCard.vue` 按 `isPlan = Array.isArray(payload.questions)` 分支渲染多题（single button / multi Checkbox + ⭐推荐默认选中 + Textarea freeform），提交聚合 `answers[]` → `postPlanClarificationAnswer`（api/chat.ts:543 → `POST /chat/conversations/{id}/plan-clarification/answer/`）→ 后端 `PlanClarificationAnswerView`（views.py:2952）。runtime 暴露 `pending_plan_clarification`（conversation_service.py:2374，真实 ClarificationQuestion 序列化）。`ClarificationCard.spec.ts` 6 用例全绿 + 前端 173 测全绿 |
| 2 | 工作流/群场景澄清经飞书交互卡（单/多选 + ⭐推荐 + 其他）由机器人发到群（CLARIFY-05） | ✓ VERIFIED | `plan_research.py:_send_clarify_card`（341 调用）取 pending 轮子题 → `build_clarification_card(..., clarification_id=...)`（card 携 `action=plan_clarify_answer`，chat_question_card.py:273）→ `FeishuIMService.send_card`；建 `WorkflowEventSubscription(event_type="PlanClarifyCallback", timeout=60min, fail)`（342-349）。回调 `@register_card_callback("plan_clarify_")`（plan_clarify_callback.py:55）已在 urls.py:14 注册 |
| 3 | 回写结构化答案后经 answer_round → adrive 续推，工作流 + 会话同源（不造两套）（CLARIFY-06） | ✓ VERIFIED | 共享 helper `aanswer_round_and_resume`（answer_resume.py:42，barrel 导出 __init__.py:7/118）薄封装 answer_round + build_orchestration_engine + adrive_plan_session_to_pause_or_terminal。两入口同源调用：飞书回调（plan_clarify_callback.py:243）+ 会话 endpoint（views.py:3093）。`test_answer_resume.py` + 两入口测试全绿 |
| 4 | 答后引擎重判：信息不足再发一轮、足够则继续，有防无限挂起上界（CLARIFY-07） | ✓ VERIFIED | `clarify_adapter.py` 移除 CR-01 单轮 `aexists()` 硬限，改三段决策：①`ahas_pending` 短路；②`round_count >= _MAX_CLARIFY_ROUNDS`(=6, clarify_adapter.py:57) → 带现有信息继续不再发轮（115-123）；③policy + 带已答重判（`_collect_prior_answers` 喂 prior answers，136-148，防同题死循环）生成非空再发一轮、空则放行。`test_engine_clarify.py` multi_round/round_cap 用例全绿 |

**Score:** 4/4 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `server/services/plan_orchestration/answer_resume.py` | 入口无关 helper aanswer_round_and_resume | ✓ VERIFIED | 115 行实质实现，barrel 导出，两入口调用，TOCTOU getattr 防护（WR-02 已修） |
| `server/services/plan_orchestration/clarify_adapter.py` | 多轮重判 + round_no 上界 | ✓ VERIFIED | `_MAX_CLARIFY_ROUNDS=6`、无 CR-01 aexists、`_collect_prior_answers` 重判 |
| `server/feishu/cards/chat_question_card.py` | build_clarification_card 扩 clarification_id + 新 action | ✓ VERIFIED | clarification_id 入参(137) + action=plan_clarify_answer(273) |
| `server/workflows/nodes/ai/plan_research.py` | _maybe_suspend CLARIFYING 发卡 + 订阅 | ✓ VERIFIED | 发卡(341) + WorkflowEventSubscription(342-349)；WR-01 已修（整轮取子题不按 answered_at 过滤，450） |
| `server/feishu/callbacks/plan_clarify_callback.py` | plan_clarify_ 回调状态机 | ✓ VERIFIED | register_card_callback(55) + 据 clarification_id 取轮 + approve_node(258) |
| `server/chat/views.py` PlanClarificationAnswerView | 专路由收答 + owner gate + 续推 | ✓ VERIFIED | owner gate 双守卫（CR-01 已修，3015-3033）+ 归属校验收窄 pending_round（WR-03 已修，3068）+ 干净 contextvars(3101) |
| `server/chat/conversation_service.py` | runtime 暴露 plan 结构化轮 | ✓ VERIFIED | pending_plan_clarification 序列化真实子题(2374) |
| `web/src/components/chat/ClarificationCard.vue` | 多题多选卡 + answers[] 聚合 | ✓ VERIFIED | isPlan 分支 + postPlanClarificationAnswer(225) |
| `web/src/types/clarification.ts` | plan 多题轮类型 | ✓ VERIFIED | PlanClarificationPayload(91) |

### Key Link Verification

| From | To | Via | Status |
|------|-----|-----|--------|
| answer_resume.py | clarification_service.answer_round | answer_round | ✓ WIRED (76) |
| answer_resume.py | resume.adrive_plan_session_to_pause_or_terminal | adrive | ✓ WIRED (65/103) |
| plan_clarify_callback.py | answer_resume aanswer_round_and_resume | helper 同源 | ✓ WIRED (243) |
| plan_clarify_callback.py | scheduler approve_node | approve_node | ✓ WIRED (258) |
| plan_research.py | chat_question_card build_clarification_card | clarification_id=... | ✓ WIRED (425) |
| plan_research.py | WorkflowEventSubscription | PlanClarifyCallback | ✓ WIRED (342) |
| chat/views.py | answer_resume aanswer_round_and_resume | helper 同源 | ✓ WIRED (3093) |
| ClarificationCard.vue | api/chat postPlanClarificationAnswer | postPlanClarificationAnswer | ✓ WIRED (225) |
| api/chat.ts | 后端专路由 | plan-clarification/answer | ✓ WIRED (548) → urls.py:197 |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| conversation_service runtime | pending_plan_clarification | ClarificationQuestion.objects ORM 查询(2368) | Yes（真实子题 question/qtype/options/recommended/selected） | ✓ FLOWING |
| ClarificationCard.vue | planPayload.questions | store pendingPlanClarifications ← runtime 回灌(stores/chat.ts:1084) | Yes | ✓ FLOWING |
| ChatMessageArea.vue | visiblePlanClarifications | store filter by conversation(111) | Yes | ✓ FLOWING |
| plan_clarify_callback answers | _build_answers(q{i}/qt{i}) | form_value + 整轮子题 order 映射 | Yes | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| 会话端 endpoint + runtime + helper + 多轮 + 回调 + 节点发卡 | `uv run pytest tests/test_plan_clarification_answer_endpoint.py tests/feishu/test_plan_clarify_callback.py tests/services/test_engine_clarify.py tests/services/test_answer_resume.py tests/workflows/test_plan_research_node.py -q` | 56 passed | ✓ PASS |
| 前端多题多选卡渲染 + 聚合提交 + 单题零回归 | `cd web && pnpm vitest run src/components/chat` | 173 passed (24 files) | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| CLARIFY-04 | 91-04, 91-05 | 出口面·AI 会话：内联渲染单/多选卡 + endpoint 回流 | ✓ SATISFIED | 前端组件 + 专路由 + runtime（truth 1） |
| CLARIFY-05 | 91-02, 91-03 | 出口面·工作流/群：飞书交互卡发到群 | ✓ SATISFIED | 发卡 + 订阅 + 回调（truth 2）；e2e 群发卡待人工确认 |
| CLARIFY-06 | 91-01, 91-03, 91-04 | 答复回流统一：同源 helper 续推 | ✓ SATISFIED | aanswer_round_and_resume 两入口共用（truth 3） |
| CLARIFY-07 | 91-01 | 多轮澄清：重判 + 防无限挂起上界 | ✓ SATISFIED | 多轮 + 重判 + _MAX_CLARIFY_ROUNDS=6（truth 4） |
| WR-03 | 91-02 | 三处 pending 收口 ahas_pending | ✓ SATISFIED | plan_research.py:328 / plan_research_tools.py:213 / plan_deepen.py:220 |
| CR-01 | 91-04 (review) | owner gate 二级门误施加于 owner | ✓ SATISFIED | space_id is not None + created_by_id != user.id 双守卫(views.py:3015-3033) |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | 无 TBD/FIXME/XXX/PLACEHOLDER/stub | — | 受改核心文件扫描无债务标记、无占位实现 |

### Code Review Carry-Over (91-REVIEW.md)

| ID | Disposition | 验证 |
|----|-------------|------|
| CR-01 | resolved | owner gate 双守卫已落地（views.py:3015-3033），代码核对一致 |
| WR-01 | resolved | 发卡侧 `_acollect_round_questions` 整轮取子题不过滤 answered_at（plan_research.py:450），与回调侧逐字一致 |
| WR-02 | resolved | helper `getattr(clar, "session_id", None)` 防裸 id AttributeError（answer_resume.py:81） |
| WR-03(review) | resolved | 归属校验收窄到 `clarification_id=pending_round.id`（views.py:3068） |
| IN-01 / IN-02 | deferred | INFO 级（多轮计数含 legacy 行仅影响展示 round_no；runtime 题面脱敏 owner-gated 风险低）— 不阻断目标 |

### Human Verification Required

#### 1. 会话出口面端到端（CLARIFY-04）

**Test:** 启动前端，触发一次 plan 多题澄清（会话入口），确认会话内联卡渲染多题 + 单/多选 + ⭐推荐默认选中 + 自由输入，提交后切「已回复」且方案继续生成。
**Expected:** ClarificationCard 渲染 questions[]（single button / multi Checkbox），推荐项默认选中；提交聚合 answers[] 打专路由，卡切「已回复」，PlanSession 续推、方案继续生成。
**Why human:** 可视化渲染 + 端到端用户流程（提交→续推→方案生成）非单测可覆盖；91-05 PLAN 显式 defer 的 human-check。

#### 2. 工作流/群出口面端到端（CLARIFY-05）

**Test:** 触发一次工作流入口（ai_plan_research）CLARIFYING 挂起，确认飞书机器人把澄清交互卡（单/多选 + ⭐推荐 + 其他）发到项目群，群内提交后方案续推。
**Expected:** 机器人发出 build_clarification_card（携 clarification_id + action=plan_clarify_answer）到项目群；提交触发回调 → answer_round + 续推 → approve_node 重调度 ai_plan_research → 置灰卡。
**Why human:** 飞书外部服务集成（真实群发卡 + 回调）端到端非单测/grep 可验证（单测以 mock FeishuIMService.send_card 验证调用）。

### Gaps Summary

无阻断性 gap。4 个可观测真相均经代码 + 自动化测试验证（后端 56 测 + 前端 173 测全绿）；CR-01 + WR-01/02/03 代码评审项已修并代码核对一致；INV-6 写入只经 ClarificationService、无旁路写；同源 helper 两入口共用、不造两套；多轮上界 6 防无限挂起。

仅余两项端到端人工验证（会话 plan 多题卡可视渲染流程、飞书群真实发卡集成），属可视化 / 外部服务集成范畴，单测以 mock 覆盖了调用契约但无法替代真实运行确认。其中会话流程为 91-05 PLAN 显式 defer 的 end-of-phase human-check。

> 测试范围说明：本报告执行用户限定的 phase 91 测试集（5 个后端文件 + `web/src/components/chat`）。工作树 chat/initiatives/war-room/project-galaxy 无关未提交 WIP 导致的既有失败（execution_concurrency / template_loader / comment-wiring / ProviderCredentialForm 等）经用户确认为已知无关项，不计入本 phase（详见 deferred-items.md）。

---

_Verified: 2026-06-27T18:00:00Z_
_Verifier: Claude (gsd-verifier)_
