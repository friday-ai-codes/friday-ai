---
phase: 49-produce-spec
plan: 03
subsystem: api
tags: [plan_orchestration, spec_generation, llm, event_taxonomy, openspec]

# Dependency graph
requires:
  - phase: 49-produce-spec
    provides: SddSpecService.create_draft（Plan 02）+ DocumentService.create_internal_spec
provides:
  - EVENT_SPEC_DRAFTED ("spec.drafted") 事件常量 + ALL_EVENTS 纳入
  - SddSpecSynthesizer 协议 + LLMSddSpecSynthesizer（openspec change-proposal prompt）
  - agenerate_specs_for_plan：逐 SDD 仓 synthesize+create_draft+emit，逐仓 try/except 隔离
affects: [49-04]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "可注入 synthesizer 协议 + 默认 LLM 合成器（真 LLM E2E deferred，单测 mock）"
    - "逐仓 try/except 隔离：单仓合成失败不影响其余仓"
    - "facets.methodology==SDD 过滤 = 非 SDD 零回归 / 无 SDD 仓 no-op"

key-files:
  created:
    - server/services/plan_orchestration/spec_generation.py
    - server/tests/services/test_spec_generation.py
  modified:
    - server/delivery/services/event_taxonomy.py
    - server/services/plan_orchestration/__init__.py
    - server/tests/services/test_event_taxonomy_alignment.py

key-decisions:
  - "emit spec.drafted 内联调用 _emit_event(EVENT_SPEC_DRAFTED, ...) 以过对齐守护（无裸字面量）"
  - "真 LLM 路径仅构造 + 单测 mock，真模型 E2E deferred（对齐 LLMMergedPlanSynthesizer）"

patterns-established:
  - "spec 生成逐仓隔离 + best-effort emit；spec.drafted producer = spec_generation.py"

requirements-completed: [SPEC-01, SPEC-02]

# Metrics
duration: ~12min
completed: 2026-06-17
---

# Phase 49 Plan 03: spec 生成逻辑 + spec.drafted 事件 Summary

**agenerate_specs_for_plan 逐 SDD 仓产 openspec spec（可注入 SddSpecSynthesizer + LLMSddSpecSynthesizer），逐仓 try/except 隔离 + emit spec.drafted；event taxonomy 对齐守护同步更新**

## Performance

- **Duration:** ~12 min
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments
- `EVENT_SPEC_DRAFTED = "spec.drafted"`（payload {spec_id, repository_id, plan_version_id}）纳入 ALL_EVENTS
- `SddSpecSynthesizer` 协议 + `LLMSddSpecSynthesizer`（system prompt 教 `## Why` / `## What Changes` / `## Spec Deltas` openspec change-proposal 结构）
- `agenerate_specs_for_plan`：解析 MergedPlan execution_plan repo → facets.methodology==SDD 过滤 → 逐仓 synthesize+create_draft+emit，逐仓 try/except 隔离（warning sdd_spec_generation_failed），无 SDD 仓 no-op
- 对齐守护登记 spec_generation.py 为 spec.drafted producer（无裸字面量、∈ ALL_EVENTS、有 producer）

## Task Commits

1. **Task 1: EVENT_SPEC_DRAFTED** - `f468dfd18` (feat)
2. **Task 2: spec_generation.py synthesizer + agenerate_specs_for_plan** - `e2c9d2726` (feat)
3. **Task 3: spec_generation tests + taxonomy alignment guard** - `951e2cbca` (test)

## Files Created/Modified
- `server/delivery/services/event_taxonomy.py` - EVENT_SPEC_DRAFTED 常量 + ALL_EVENTS
- `server/services/plan_orchestration/spec_generation.py` - synthesizer 协议 + LLM 合成器 + agenerate_specs_for_plan
- `server/services/plan_orchestration/__init__.py` - 三导出 re-export
- `server/tests/services/test_spec_generation.py` - 6 个测试
- `server/tests/services/test_event_taxonomy_alignment.py` - 登记 spec.drafted producer

## Decisions Made
None - followed plan as specified.

## Deviations from Plan
None - plan executed exactly as written.

## Issues Encountered
- Task 1 单独提交后对齐守护 `test_all_events_each_emitted_by_producer` 暂红（spec.drafted 尚无 producer），由 Task 3 在同一 wave 内登记 producer 转绿——符合 plan 任务排序设计。

## Next Phase Readiness
- agenerate_specs_for_plan 就绪，Plan 04 可从 ArchitectMergeAdapter._handle_pass best-effort 挂接
- 对齐守护 + ruff 全绿

---
*Phase: 49-produce-spec*
*Completed: 2026-06-17*
