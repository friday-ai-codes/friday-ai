---
phase: 41-hitl-taxonomy
plan: 01
subsystem: orchestration
tags: [plan-session-event, event-taxonomy, trace, delivery, django]

requires:
  - phase: 36-plansession
    provides: PlanSession + PlanSessionService._emit_event 钩子
  - phase: 38/39/40
    provides: engine/research_adapter/architect_merge_adapter/callbacks emit 点
provides:
  - PlanSessionEvent append-only 模型 + migration 0015（§15 统一信封持久化）
  - event_taxonomy 稳定常量集（ALL_EVENTS/RESERVED_EVENTS）+ build_envelope 信封 helper
  - _emit_event 升级为 best-effort 持久化 PlanSessionEvent
  - 全 emit 点引用 §15 常量（消除 38/39/40 字符串漂移）+ 漂移对齐守护测试
affects: [41-02, 41-03, v0.11 对外 adapter]

tech-stack:
  added: []
  patterns:
    - "append-only 事件持久化（§15 统一信封：列拆解 event/work_item/payload/ts）"
    - "best-effort 钩子：DB 写失败只 log warning 绝不抛影响转移"
    - "taxonomy 稳定常量集中定义 + 守护测试反查覆盖（producer 文件渐次落地容错）"

key-files:
  created:
    - server/delivery/models/plan_session_event.py
    - server/delivery/services/event_taxonomy.py
    - server/delivery/migrations/0015_plansessionevent.py
    - server/tests/delivery/test_plan_session_event.py
    - server/tests/services/test_event_taxonomy_alignment.py
  modified:
    - server/delivery/models/__init__.py
    - server/delivery/services/__init__.py
    - server/delivery/services/plan_session_service.py
    - server/services/plan_orchestration/engine.py
    - server/services/plan_orchestration/research_adapter.py
    - server/services/plan_orchestration/architect_merge_adapter.py
    - server/subagent/api/callbacks.py

key-decisions:
  - "ALL_EVENTS 仅含本 phase 编排实际产出事件；work_item.syncing / coding.wave.* 列 RESERVED_EVENTS（常量预留不计覆盖集）"
  - "alignment 覆盖性反查按 producer 文件存在性容错——clarify 文件 41-02 落地，缺失时跳过保子计划顺序安全"

patterns-established:
  - "Pattern: §15 事件常量唯一来源 event_taxonomy；emit 点禁裸字面量（漂移守护断言）"
  - "Pattern: _emit_event best-effort 持久化（绝不阻断 transition）"

requirements-completed: [EVENT-01]

duration: ~25min
completed: 2026-06-16
---

# Phase 41 Plan 01: 事件 taxonomy 持久化 Summary

**PlanSessionEvent append-only 模型把编排全程 §15 trace 事件持久化为统一信封行，event_taxonomy 稳定常量收口全 emit 点（消除 38/39/40 字符串漂移），_emit_event 升级为 best-effort 持久化。**

## Performance
- **Tasks:** 3
- **Files modified:** 12（5 created + 7 modified）
- **Completed:** 2026-06-16

## Accomplishments
- `PlanSessionEvent`（delivery）append-only 模型 + migration 0015（§15 信封字段 event/work_item/payload/ts）
- `event_taxonomy` §15 稳定常量集（`ALL_EVENTS` 11 事件 + `RESERVED_EVENTS`）+ `build_envelope` 统一信封 helper
- `_emit_event` 从占位升级为持久化 `PlanSessionEvent`，best-effort（DB 失败只 log，绝不抛影响转移）
- engine/research_adapter/architect_merge_adapter/callbacks/plan_session_service 全 emit 点改引用 `EVENT_*` 常量
- 漂移对齐守护测试（无裸字面量 + 引用值 ∈ ALL_EVENTS + 覆盖性反查）

## Task Commits
1. **Task 1: PlanSessionEvent 模型 + migration 0015 + re-export** - `4e0b6d308` (feat)
2. **Task 2: §15 taxonomy 常量 + 信封 helper + _emit_event 持久化** - `151c0de73` (feat)
3. **Task 3: 各 emit 点引用常量 + 38/39/40 漂移对齐守护** - `bd7569fc4` (feat)

## Decisions Made
- `ALL_EVENTS` 仅含本 phase 编排实际产出的 11 个事件；`work_item.syncing`（WorkItem 同步链路，非编排）与 `coding.wave.*`（v0.8）列 `RESERVED_EVENTS`，常量预留但不计入覆盖集——使 Task 3 覆盖性反查与 41-02 顺序一致。
- 漂移对齐守护的覆盖性反查按 producer 源文件存在性容错：`clarify_adapter.py` / `clarification_service.py`（41-02 落地）缺失时跳过其事件断言，保子计划顺序安全；41-02/41-03 落地后自动转为强制。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] alignment 守护跨子计划顺序安全设计**
- **Found during:** Task 3
- **Issue:** 计划 Task 2 行为列示 `ALL_EVENTS` 含 `clarification.asked/answered`，但其 emit 点（clarify_adapter/clarification_service）在 41-02 才落地；若 Task 3 覆盖性反查强制要求其 producer 存在，则 41-01 检查点会红。
- **Fix:** 覆盖性反查按 `_EVENT_PRODUCERS` 映射的 producer 文件存在性容错跳过；`ALL_EVENTS` 含全 11 事件不变（41-02 落地后 clarify 覆盖自动生效）。
- **Files modified:** server/tests/services/test_event_taxonomy_alignment.py
- **Verification:** 41-01 检查点 3 守护测试全绿；41-02 落地后 clarify 覆盖将自动强制。

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** 无 scope 蔓延；仅守护测试为子计划顺序安全做容错设计。

## Issues Encountered
- 跨行 `self._emit(session,\n EVENT_..., ...)` 调用最初被逐行正则漏匹配 → 改为剔注释后全文匹配（`\s` 跨行）修复。

## Verification Results
- `makemigrations --check --dry-run` 干净（0015 已落）。
- `tests/delivery/test_plan_session_event.py`（4）+ `tests/services/test_event_taxonomy_alignment.py`（3）+ 既有 engine/architect/research/callback 套件（共 45 passed）全绿。
- `ruff check` 全部通过。

## Next Phase Readiness
- 41-02 可直接引用 `EVENT_CLARIFICATION_ASKED/ANSWERED` 常量；落地后 alignment 覆盖自动强制。

---
*Phase: 41-hitl-taxonomy*
*Completed: 2026-06-16*
