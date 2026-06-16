---
phase: 41-hitl-taxonomy
plan: 02
subsystem: orchestration
tags: [clarification, hitl, clarify-adapter, stale-rerun, delivery, plan-orchestration]

requires:
  - phase: 41-01
    provides: EVENT_CLARIFICATION_ASKED/ANSWERED 常量 + _emit_event 持久化
  - phase: 39
    provides: RepoResearchTask/PartialPlan + ResearchService stale 机制
  - phase: 36
    provides: PlanSession 状态机 + engine 可注入 stage 协议
provides:
  - Clarification 模型 + migration 0016（§6 + affected_partials M2M）
  - ClarificationService（INV-6 单一写入入口 + 仅 affected 重跑 + 幂等答）
  - ResearchService.mark_stale（按指定 task 置 stale，reason=clarification）
  - ClarifyProtocol/SkeletonClarify + ClarifyAdapter + default_needs_clarification
  - engine._clarify 真实接线（needs→挂起 / else→researching）
affects: [41-03, 42]

tech-stack:
  added: []
  patterns:
    - "needs-clarification policy 可注入（默认 routing 无 high/medium 或 ambiguous）"
    - "澄清回答仅 affected_partials 经 mark_stale 重跑，其余 partial 复用（§14）"
    - "engine 经 transition 推进（needs_clarification 自挂起 / clarified→researching），纯度守护"

key-files:
  created:
    - server/delivery/models/clarification.py
    - server/delivery/migrations/0016_clarification.py
    - server/delivery/services/clarification_service.py
    - server/services/plan_orchestration/clarify_adapter.py
    - server/tests/delivery/test_clarification_service.py
    - server/tests/services/test_engine_clarify.py
  modified:
    - server/delivery/models/__init__.py
    - server/delivery/services/__init__.py
    - server/delivery/services/research_service.py
    - server/services/plan_orchestration/protocols.py
    - server/services/plan_orchestration/engine.py
    - server/services/plan_orchestration/__init__.py
    - server/tests/services/test_plan_orchestration_engine.py

key-decisions:
  - "answer_clarification 幂等条件更新（answered_at IS NULL）：重复答 no-op，不二次覆盖/不重复 stale/不重复 emit"
  - "ResearchService.mark_stale 新增窄方法（reason=clarification），区别 invalidate_for_repo（repo_reindexed）"
  - "clarification.answered 在 ClarificationService.answer 流程 emit（payload {clarification_id, answer, affected_partials}）"

patterns-established:
  - "Pattern: Clarification 落库/状态变更唯一经 ClarificationService（INV-6 grep 守护）"
  - "Pattern: engine stage 协议注入 + Skeleton NotImplementedError；_clarify 接真实 ClarifyAdapter"

requirements-completed: [CLARIFY-01]

duration: ~30min
completed: 2026-06-16
---

# Phase 41 Plan 02: HITL 澄清回路 Summary

**Clarification 模型 + ClarificationService（INV-6）补齐 HITL 澄清回路：不清晰时建 pending 挂起 + emit clarification.asked，回答后仅 affected_partials 经 mark_stale 重跑、其余复用；engine._clarify 接真实可注入 ClarifyAdapter（needs-clarification policy）。**

## Performance
- **Tasks:** 3
- **Files modified:** 13（6 created + 7 modified）
- **Completed:** 2026-06-16

## Accomplishments
- `Clarification`（delivery）模型 + migration 0016（question/answer/answered_at + affected_partials M2M）
- `ClarificationService` 单一写入入口：create_clarification(pending+M2M) / answer_clarification（幂等 + 仅 affected stale 重跑 + emit answered）
- `ResearchService.mark_stale(task_ids)` 窄方法（按指定 task 置 stale，reason=clarification，只触指定 task）
- `ClarifyProtocol`/`SkeletonClarify` + `ClarifyAdapter` + `default_needs_clarification`（routing 无 high/medium 或 ambiguous → 需澄清）
- `engine._clarify` 接真实：needs→needs_clarification 挂起（clarifying 自留）/ else→clarified→researching

## Task Commits
1. **Task 1: Clarification 模型 + migration 0016 + re-export** - `(feat 41-02 T1)`
2. **Task 2: ClarificationService + mark_stale + INV-6 守护测试** - `(feat 41-02 T2)`
3. **Task 3: ClarifyProtocol/ClarifyAdapter + engine._clarify 接真实** - `(feat 41-02 T3)`

## Decisions Made
- `answer_clarification` 幂等条件更新（`answered_at IS NULL`）：重复答 no-op，保留首答、不重复 stale/emit。
- 新增 `ResearchService.mark_stale`（澄清 affected 重跑窄入口，`invalidated_reason="clarification"`），与既有 `invalidate_for_repo`（`repo_reindexed`）语义区分；仅触指定 task。
- `clarification.answered` 在 ClarificationService.answer 流程 emit（而非节点侧），payload `{clarification_id, answer, affected_partials}`——使 41-01 alignment 覆盖性反查对 clarification.answered 自动强制（producer=clarification_service.py）。
- ClarifyAdapter 已有 pending（未答）时短路返回挂起，不重复建（resume 幂等）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] 更新既有 test_clarify_pass_through**
- **Found during:** Task 3
- **Issue:** SkeletonClarify 从 pass-through 改为 NotImplementedError 后，既有 `test_clarify_pass_through`（默认 engine 期望 clarifying→researching）必然失败。
- **Fix:** 改为注入 no-clarification mock 的 `test_clarify_no_clarification_advances_to_researching`（保留 pass-through 等价语义验证）。
- **Files modified:** server/tests/services/test_plan_orchestration_engine.py
- **Verification:** test_plan_orchestration_engine.py 10 项全绿。

**2. [Rule 1 - Bug] INV-6 grep 守护排除 .venv/site-packages**
- **Found during:** Task 2
- **Issue:** Python `rglob` 扫描 server/ 含 `.venv` 误报。
- **Fix:** 守护扫描排除 `.venv`/`node_modules`/`.git`/`__pycache__`/`site-packages`。
- **Files modified:** server/tests/delivery/test_clarification_service.py
- **Verification:** INV-6 守护绿（仅 clarification_service.py 含 Clarification.objects.create）。

**Total deviations:** 2 auto-fixed (1 missing-critical test 更新, 1 bug)
**Impact on plan:** 无 scope 蔓延；均为接真实回路必需的连带修正。

## Issues Encountered
- 无（import 顺序经 lazy PlanSessionService 构造规避潜在环）。

## Verification Results
- `makemigrations --check --dry-run` 干净（0015+0016 均已落）。
- `test_clarification_service.py`（5）+ `test_engine_clarify.py`（6）+ `test_plan_orchestration_engine.py`（10）+ alignment（3）+ plan_session_event（4）全绿（28 passed）。
- INV-6 grep 守护绿；engine 纯度守护绿；`ruff check` 通过。

## Next Phase Readiness
- 41-03 可注入真实 ClarifyAdapter 驱动 engine 端到端；clarifying（pending）处工作流节点挂 waiting_event。

---
*Phase: 41-hitl-taxonomy*
*Completed: 2026-06-16*
