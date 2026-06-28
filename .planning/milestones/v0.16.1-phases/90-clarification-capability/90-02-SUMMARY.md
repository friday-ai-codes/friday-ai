---
phase: 90-clarification-capability
plan: 02
subsystem: api
tags: [django, orm, async, sync_to_async, clarification, plan_orchestration, inv6, observability]

# Dependency graph
requires:
  - phase: 90-01
    provides: Clarification 轮次容器 nullable 字段 + ClarificationQuestion 子表（recommendation_adopted 等）
provides:
  - ClarificationService.create_round（建容器 + bulk_create N 子题，结构化澄清唯一写入入口）
  - ClarificationService.answer_round（按题幂等作答 + 作答时定格 recommendation_adopted）
  - ClarificationService.ahas_pending（统一 pending 谓词，兼容旧单题行 + 新结构化子题）
  - 采纳率可经 ClarificationQuestion SQL 聚合（recommendation_adopted__isnull=False 为分母）
  - INV-6 grep 守护扩展覆盖 ClarificationQuestion 旁路写
  - clarification_round_created / clarification_round_answered 生命周期事件（category=caller, component=delivery, duration_ms）
affects: [90-03 ClarifyAdapter 接 LLM + 三处 pending 升级, 90-04 ask_clarification helper, Phase 91 出口面/回流 resume]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "结构化澄清写入收口：create_round/answer_round/ahas_pending 三方法收口于 ClarificationService（INV-6），子题经 bulk_create 在 sync_to_async 同步块"
    - "采纳信号作答时定格：recommendation_adopted 在 answer 时一次性算清持久化（single==rec[0] / multi set 全等 / 无推荐或纯 freeform→None），可 SQL 聚合不靠日志事后拼"
    - "统一 pending 谓词兼容双形态：子题未答 OR 旧单题行（无子题且容器未答）"
    - "best-effort 生命周期埋点 _safe_log：观测失败吞掉，绝不反噬业务"

key-files:
  created: []
  modified:
    - server/delivery/services/clarification_service.py
    - server/tests/delivery/test_clarification_service.py

key-decisions:
  - "answer_round 多选采纳语义取 set 全等（CONTEXT 未指定子集采纳，全等最无歧义）"
  - "recommendation_adopted 只 server 端作答时计算，绝不接受调用方传入（T-90-02-02）"
  - "ahas_pending 旧单题行用 questions__isnull=True 表达「无子题」，避免历史挂起被误放行（Pitfall 2）"
  - "采纳率不另写聚合方法，由 ClarificationQuestion.objects.filter(...).aaggregate(...) 直接 SQL 聚合（测试演示形态）"
  - "INV-6 子模型守护单独新增 test_inv6_clarification_question_single_write_entry（正则覆盖 .objects.create/.bulk_create/(...).save）"

patterns-established:
  - "Pattern: answer_round 按题幂等条件更新（filter(answered_at__isnull=True).update(...)）+ 采纳信号同步块内定格"
  - "Pattern: 生命周期事件 _safe_log（best-effort try/except + duration_ms）"

requirements-completed: [CLARIFY-01]

# Metrics
duration: 12min
completed: 2026-06-27
---

# Phase 90 Plan 02: ClarificationService 结构化澄清写入入口 Summary

**把 `ClarificationService` 扩展为结构化澄清的唯一写入入口：新增 `create_round`（建容器 + bulk_create 多子题）、`answer_round`（按题幂等作答 + 作答时一次性定格 `recommendation_adopted` 采纳信号）、`ahas_pending`（统一 pending 谓词，兼容旧单题行），并扩展 INV-6 grep 守护覆盖子模型 + 补结构化生命周期埋点。**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-06-27T06:22:00Z
- **Completed:** 2026-06-27T06:34:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- `create_round(session, questions, *, origin_repo, round_no, plan_version_id)`：建 1 容器（`question=""` 占位保旧 NOT NULL 列、`container_status="pending"`）+ `ClarificationQuestion.bulk_create` N 子题（order 0-based 递增、qtype/options/recommended/origin_repo 落库），全程 `sync_to_async` 同步块。
- `answer_round(round_or_id, answers)`：遍历 `[{question_id, selected, freeform_text}]` 按题幂等条件更新（`answered_at__isnull=True` 前置，重复作答 no-op 不覆盖首答），**作答时一次性定格 `recommendation_adopted`**——single 命中 `selected==rec[0]`、multi `set(selected)==set(rec)` 全等、无推荐/纯 freeform→`None`；采纳信号绝不接受调用方传入。
- `ahas_pending(session_id)`：统一 pending 谓词收口两形态——轮内有未答子题 OR 旧单题行（容器未答且 `questions__isnull=True` 无子题）→ True，防历史挂起误放行。
- 采纳率经 `ClarificationQuestion.objects.filter(recommendation_adopted__isnull=False).aaggregate(total=Count("id"), adopted=Count("id", filter=Q(recommendation_adopted=True)))` SQL 聚合（用例证形态）。
- INV-6 grep 守护扩展：新增 `test_inv6_clarification_question_single_write_entry`（正则覆盖 `ClarificationQuestion.objects.create/.bulk_create` 与 `ClarificationQuestion(...).save` 旁路写仅允许出现在 service）。
- 补 `clarification_round_created` / `clarification_round_answered` 结构化生命周期事件（`category=caller`、`component=delivery`、`duration_ms`），经 `_safe_log` best-effort 包裹绝不反噬业务（AGENTS.md 观测约束 / plan-checker WARNING #2）。

## Task Commits

Each task was committed atomically:

1. **Task 1: 扩展 ClarificationService（create_round/answer_round/recommendation_adopted/ahas_pending + 埋点）** - `852d94c6d` (feat)
2. **Task 2: Wave 0 测试——采纳信号/采纳率聚合/向后兼容/幂等/INV-6 子模型守护** - `e74d22896` (test)

_Note: Task 1 标 tdd="true"，但本 plan 将「service 实现」与「Wave 0 测试」拆为两个独立 task（Task 2 即测试集），按 plan 任务分解顺序执行：先落 service（既有 5 测零回归）再补 9 个新测。_

## Files Created/Modified
- `server/delivery/services/clarification_service.py` - 新增 create_round/_create_round_sync、answer_round/_answer_round_sync/_answer_question、ahas_pending/_ahas_pending_sync、_safe_log；模块 docstring 补结构化澄清入口说明
- `server/tests/delivery/test_clarification_service.py` - 新增 9 个 async 用例（create_round 落库 / 采纳信号 single·multi·None / 采纳率聚合 / ahas_pending 旧单题行·新结构化 / answer_round 幂等）+ 新增 INV-6 子模型守护

## Decisions Made
- **多选采纳语义取 set 全等**：CONTEXT 未指定子集采纳，全等最无歧义（写进 answer_round docstring）。
- **采纳信号 server 端计算**：`recommendation_adopted` 仅在 `_answer_question` 内按 `q.recommended` 算，绝不接受 answers 入参传入（T-90-02-02）。
- **ahas_pending 兼容旧行**：旧单题行用 `Clarification.objects.filter(answered_at__isnull=True, questions__isnull=True)` 表达「容器未答且无子题」，与新子题判定并联（Pitfall 2）。
- **采纳率不另写方法**：由 `aaggregate` SQL 直接聚合，测试演示形态，避免冗余 service 方法。
- **生命周期事件 category=caller/component=delivery**：澄清轮次建/答属用户可归因的编排写操作，归 caller 类。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] 测试 `afirst()` 触发 mypy union-attr，改用 `aget`**
- **Found during:** Task 2（Wave 0 测试）
- **Issue:** 单题轮用 `ClarificationQuestion.objects.filter(clarification=clar).afirst()` 返回 `ClarificationQuestion | None`，后续 `.id` 访问触发 mypy `union-attr`（13 errors），违反 critical_constraints「mypy 通过」。
- **Fix:** 单行场景改用 `.aget(clarification=clar)`（返回非 None），多行场景保留 list comprehension。
- **Files modified:** server/tests/delivery/test_clarification_service.py
- **Verification:** `mypy delivery/services/clarification_service.py tests/delivery/test_clarification_service.py` → Success: no issues found in 2 source files
- **Committed in:** `e74d22896`（Task 2 commit）

---

**Total deviations:** 1 auto-fixed（1 blocking）
**Impact on plan:** 仅测试写法调整以满足 mypy 门禁，不影响断言语义与覆盖范围。无 scope creep。

## Issues Encountered
None - 实现一次通过既有 5 测零回归，新增 9 测全绿。

## Threat Surface Scan
threat_model 四项 mitigate 均已落实：T-90-02-01（INV-6 子模型写入收口 + grep 守护扩展）；T-90-02-02（recommendation_adopted server 端定格，不接受传入）；T-90-02-03（async 全程 `*_id` 标量 + `sync_to_async` 同步块，无裸 lazy-FK，14 用例跑通无 SynchronousOnlyOperation）；T-90-02-04（ahas_pending 旧单题行兼容）。无新增网络端点/认证路径/信任边界 schema 变化，无新威胁面。

## Known Stubs
None - 本 plan 落地 service 写入逻辑 + 采纳信号计算，无 UI 渲染、无 mock 数据。下游 90-03 adapter / 90-04 helper 将消费 create_round/ahas_pending（按 RESEARCH 规划，非 stub）。

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- 写入收口就绪：90-03 ClarifyAdapter 可调 `create_round`（接 `agenerate_clarification_questions` 多题 + fail-soft 回退）+ 三处 pending 判定升级为统一 `ahas_pending`（clarify_adapter / resume / e2e helper）。
- 90-04 入口无关 `ask_clarification` helper 可薄封装 `create_round`（携 origin_repo）。
- 采纳率分析（Phase 91/采纳率大盘）可直接 SQL 聚合 `ClarificationQuestion.recommendation_adopted`。

---
*Phase: 90-clarification-capability*
*Completed: 2026-06-27*

## Self-Check: PASSED
- FOUND: server/delivery/services/clarification_service.py
- FOUND: server/tests/delivery/test_clarification_service.py
- FOUND: .planning/phases/90-clarification-capability/90-02-SUMMARY.md
- FOUND commit 852d94c6d (Task 1)
- FOUND commit e74d22896 (Task 2)
