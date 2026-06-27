---
phase: 90-clarification-capability
plan: 03
subsystem: api
tags: [plan_orchestration, clarification, llm, fail-soft, async, sync_to_async, inv6, observability]

# Dependency graph
requires:
  - phase: 90-02
    provides: ClarificationService.create_round / answer_round / ahas_pending（结构化澄清写入入口 + 统一 pending 谓词）
  - phase: P1（澄清生成器）
    provides: agenerate_clarification_questions（LLM 结构化多题生成器，call_source=plan_clarification 已内埋）
provides:
  - ClarifyAdapter.clarify 接 LLM 多题：静态 policy 判「要不要问」→ agenerate_clarification_questions 判「问什么」→ create_round 落结构化多子题轮
  - fail-soft 回退：LLM 返回 [] / 内部异常（生成器已吞）→ 回退现状粗单题（create_clarification legacy 行）+ 记 clarification_fallback_coarse_question，绝不抛、绝不让 engine 落 failed
  - 三处 pending 判定收口 ClarificationService.ahas_pending：clarify_adapter / resume / e2e helper（兼容旧单题行 + 新结构化子题）
affects: [90-04 ask_clarification helper, Phase 91 出口面/回流 resume]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "静态 policy 判要不要问 + LLM 判问什么：policy 静态门控（routing/decomposition 信号）后才调 LLM 产结构化多题，二段分工"
    - "fail-soft 回退配套 legacy 作答路径：回退用 create_clarification（无子题单题行），与 legacy answer_clarification 作答路径配套，保 CR-01 单轮短路零回归（不用 create_round 以免遗留未答子题）"
    - "pending 判定单一谓词收口：clarify_adapter / resume / e2e helper 三处统一调 ahas_pending，避免逻辑漂移（T-90-03-04）"
    - "LLM 接入零新增抛点：依赖 agenerate_clarification_questions 已 best-effort 返回 []，adapter 仅「[]→回退」一处分支（T-90-03-02）"

key-files:
  created: []
  modified:
    - server/services/plan_orchestration/clarify_adapter.py
    - server/services/plan_orchestration/resume.py
    - server/tests/services/test_engine_clarify.py
    - server/tests/services/test_plan_research_e2e.py

key-decisions:
  - "fail-soft 回退用 create_clarification（legacy 单题行）而非 plan 字面的 create_round——后者会建未答子题，与 CR-01 既有用例的 legacy answer_clarification 作答路径不配套导致 ahas_pending 永真，违反零回归硬约束；且与 user query『回退现状粗单题』语义一致"
  - "LLM 多题成功路径用 create_round（结构化子题），fail-soft 路径用 create_clarification（legacy），两条作答路径各自配套"
  - "_emit_asked 仍传 policy 粗 question 作 payload（不改 clarification.asked 事件契约），多题摘要升级留待出口面 plan"

patterns-established:
  - "Pattern: 澄清二段分工——静态 policy 门控 + LLM 内容生成，LLM 失败 fail-soft 回退现状"
  - "Pattern: pending 谓词三处收口 service.ahas_pending（兼容双形态）"

requirements-completed: [CLARIFY-02]

# Metrics
duration: 10min
completed: 2026-06-27
---

# Phase 90 Plan 03: ClarifyAdapter 接 LLM 多题 + fail-soft 回退 + pending 收口 Summary

**把已就绪的 LLM 结构化多题生成器 `agenerate_clarification_questions` 接入 `ClarifyAdapter.clarify`（静态 policy 判要不要问 → LLM 判问什么 → `create_round` 落多子题轮），LLM 返回 `[]`/异常时 fail-soft 回退现状粗单题（`create_clarification`）并记 `clarification_fallback_coarse_question`，同时把 clarify_adapter / resume / e2e helper 三处 pending 判定收口到统一谓词 `ahas_pending`。**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-06-27T06:35:00Z
- **Completed:** 2026-06-27T06:45:00Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments
- `ClarifyAdapter.clarify` 三段判定改造：①pending 短路收口 `ahas_pending`；②CR-01 已答轮短路（`Clarification.objects.filter(session_id=...).aexists()`）；③首轮 policy `needs==True` 后调 `agenerate_clarification_questions(requirement, routing, recall_hits)` → 非空经 `create_round` 落结构化多子题轮。
- fail-soft 回退：LLM 返回 `[]`（含内部异常已吞）→ 记 `clarification_fallback_coarse_question`（category=sampling, component=plan_orchestration）后经 `create_clarification` 建 legacy 单题行，绝不抛、绝不让 engine.advance 通用 except 落 failed。
- `resume.adrive_plan_session_to_pause_or_terminal` 的 CLARIFYING 在途短路从内联 `Clarification.objects.filter(answered_at__isnull=True)` 收口到 `ClarificationService().ahas_pending(session.id)`（函数内 lazy import，最小 diff，不动 researching/max_steps 分支）。
- e2e 驱动 helper `_drive`（`test_plan_research_e2e.py`）的 CLARIFYING pending 查询同步升级为先 `ahas_pending` 门控再取 pending 行作答，旧单题行（`create_clarification`）经兼容分支仍判 pending。
- `test_engine_clarify.py` 扩展 4 个新用例（既有 7 测零回归 → 共 11 测）：LLM 多题接线 / fail-soft 空回退 / fail-soft engine 不落 failed / pending 经 ahas_pending 短路。

## Task Commits

Each task was committed atomically:

1. **Task 1: ClarifyAdapter 接 LLM 多题 + fail-soft 回退 + ahas_pending 收口** - `f6737f744` (feat)
2. **Task 2: resume + e2e helper 的 CLARIFYING pending 判定收口 ahas_pending** - `6d1543528` (refactor)
3. **Task 3: test_engine_clarify 扩展 LLM 多题/fail-soft/pending 升级用例** - `a3e1b28c1` (test)

## Files Created/Modified
- `server/services/plan_orchestration/clarify_adapter.py` - clarify 三段判定接 LLM 多题 + fail-soft 回退；模块顶 import `agenerate_clarification_questions`；docstring 补 CLARIFY-02 二段分工与回退语义
- `server/services/plan_orchestration/resume.py` - CLARIFYING 短路改调 `ahas_pending`（lazy import ClarificationService），移除内联 Clarification 查询
- `server/tests/services/test_engine_clarify.py` - 新增 4 用例 + import ClarificationQuestion + `_LLM_GEN` patch 锚点
- `server/tests/services/test_plan_research_e2e.py` - `_drive` helper CLARIFYING pending 查询升级为 ahas_pending 门控

## Decisions Made
- **fail-soft 回退用 `create_clarification` 而非 plan 字面的 `create_round`**：见 Deviations。
- **多题/回退两条作答路径各自配套**：LLM 多题 → `create_round`（结构化子题，下游经 `answer_round` 作答）；fail-soft → `create_clarification`（legacy 单题行，经 `answer_clarification` 作答）。`ahas_pending` 双形态兼容覆盖两者。
- **`_emit_asked` 仍传 policy 粗 `question`**：不改 `clarification.asked` 事件 payload 契约；多题摘要升级留待出口面 plan（best-effort，非本 plan 范围）。
- **CR-01 已答短路用 `aexists()` 而非区分 answered**：步骤 1 `ahas_pending` 已确认无 pending，故「本 session 存在任意 Clarification 轮」即视为澄清满足放行 researching（语义等价于旧 `has_answered` 分支，兼容多子题轮）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] fail-soft 回退改用 `create_clarification`（legacy 单题行），保 CR-01 零回归**
- **Found during:** Task 1（接线 + fail-soft）
- **Issue:** plan action 字面要求 fail-soft 回退调 `create_round([{...}])`，但 `create_round` 会建 1 容器 + 1 个**未答子题**。既有 CR-01 用例 `test_real_policy_answered_round_advances_no_second_clarification`（7 测之一，硬约束零回归）经 legacy `answer_clarification` 只作答**容器**、不作答子题，导致升级后 `ahas_pending` 因子题未答恒判 pending → 第二轮 advance 仍挂起 clarifying，断言 `RESEARCHING` 失败（无限挂起回归）。
- **Fix:** fail-soft 回退改用 `create_clarification(session, question, affected_task_ids)` 建 legacy 单题行（无子题），与 legacy `answer_clarification` 作答路径配套；`ahas_pending` 旧单题行兼容分支（`questions__isnull=True`）使其作答后正确判非 pending。此选择亦与 user query 关键约束「fail-soft 回退现状粗单题」语义一致。
- **Files modified:** server/services/plan_orchestration/clarify_adapter.py
- **Verification:** `test_engine_clarify.py` 11 测全绿（含 CR-01 `test_real_policy_answered_round_advances_no_second_clarification`）；`test_plan_research_e2e.py` 3 测全绿。
- **Committed in:** `f6737f744`（Task 1 commit）

---

**Total deviations:** 1 auto-fixed（1 bug — 零回归修正）
**Impact on plan:** 仅 fail-soft 落库方法由 create_round 调整为 create_clarification，以满足「CR-01 单轮短路零回归」硬约束并对齐 user query「回退现状粗单题」语义；接线主线（LLM 多题 + create_round）与 pending 收口（ahas_pending）均按 plan 落地，无 scope creep。Task 3 fail-soft 用例据此断言「legacy 单题行、0 子题」（plan 字面写「1 子题」已随此修正调整）。

## Issues Encountered
None — 接线一次通过，CR-01 零回归经设计（fail-soft 用 legacy 路径）保住。

## Deferred Issues（out-of-scope，SCOPE BOUNDARY）
运行 `tests/services/plan_orchestration tests/delivery` 时 6 个失败均与本 plan 无关，源于工作树并发未提交的 project-war-room / initiatives 改动（详见 `deferred-items.md`）：`test_comment_entry_wiring`（3）、`test_entry_wiring`（1）、`test_inv6_guard::feishu_chat_id`（指向 `initiatives/services/project_service.py`）、`test_technical_plan_inv6_guard::canonical_plan_write`。本 plan 仅触及 clarify_adapter/resume + 两个 clarif 测试文件，与上述文件无交集，不在修复范围。澄清相关测试全绿。

## Threat Surface Scan
threat_model 四项 mitigate 均覆盖：T-90-03-01（多题写库前经生成器内 `normalize_clarification_questions` 截断/归一，且只经 `create_round` 落库）；T-90-03-02（fail-soft，adapter 仅「[]→回退」一处分支，零新增抛点）；T-90-03-03（生成器异常只记 `str(exc)`，回退事件只记 session_id/category/component）；T-90-03-04（三处 pending 收口 ahas_pending）；T-90-03-05（async 全程 `session.id` 标量 + service `sync_to_async`，无裸 lazy-FK）。无新增网络端点/认证路径/信任边界 schema 变化，无新威胁面。

## Known Stubs
None — 本 plan 为接线 + 回退逻辑，无 UI 渲染、无 mock 数据占位。LLM 多题路径与 fail-soft 路径均真实落库（create_round / create_clarification）。

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- 工作流/对话两条链经 engine.advance → ClarifyAdapter 即可产结构化多题澄清（每题带 options + recommended），LLM 不可用时 fail-soft 退现状单题不阻断。
- 90-04 `ask_clarification` helper 可继续薄封装 `create_round`（携 origin_repo）；出口面 plan 可把 `clarification.asked` payload 升级为多题摘要。
- pending 判定已全链路收口 `ahas_pending`，Phase 91 回流/resume 无需再处理双形态分叉。

---
*Phase: 90-clarification-capability*
*Completed: 2026-06-27*

## Self-Check: PASSED
- FOUND: server/services/plan_orchestration/clarify_adapter.py
- FOUND: server/services/plan_orchestration/resume.py
- FOUND: server/tests/services/test_engine_clarify.py
- FOUND: server/tests/services/test_plan_research_e2e.py
- FOUND: .planning/phases/90-clarification-capability/90-03-SUMMARY.md
- FOUND commit f6737f744 (Task 1)
- FOUND commit 6d1543528 (Task 2)
- FOUND commit a3e1b28c1 (Task 3)
