---
phase: 49-produce-spec
plan: 04
subsystem: api
tags: [plan_orchestration, architect_merge, fail_soft, spec_generation]

# Dependency graph
requires:
  - phase: 49-produce-spec
    provides: agenerate_specs_for_plan（Plan 03）+ SddSpecService.create_draft
provides:
  - ArchitectMergeAdapter._handle_pass best-effort 挂接 spec 生成（fail-soft）
  - 可注入 spec_generation_hook（默认真实实现，可注入 stub）
  - 全链路 merge hook 守护测试（SDD 产 / 零回归 / fail-soft / 幂等）
affects: [50-spec-lifecycle]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "merge.completed emit 后 best-effort 挂接 + 外层 try/except 双保险（绝不阻断融合返回）"
    - "构造注入可选 hook（延迟默认绑定避免 import 环）"

key-files:
  created:
    - server/tests/services/test_spec_generation_merge_hook.py
  modified:
    - server/services/plan_orchestration/architect_merge_adapter.py

key-decisions:
  - "spec 生成挂接仅追加在 merge.completed emit 之后，不改 record_merge/set_current_plan_version/返回顺序"
  - "外层 try/except 与 hook 内逐仓 try/except 构成双保险"

patterns-established:
  - "融合通过路径 fail-soft 挂接副产物生成（spec），既有融合语义零回归"

requirements-completed: [SPEC-01, SPEC-02]

# Metrics
duration: ~10min
completed: 2026-06-17
---

# Phase 49 Plan 04: 融合挂接 spec 生成 + 全链路守护 Summary

**ArchitectMergeAdapter._handle_pass 在 merge.completed 之后 best-effort 调 spec 生成 hook（默认 agenerate_specs_for_plan，可注入 stub），整段 try/except 吞 warning 绝不阻断融合返回；全链路守护封板 Phase 49**

## Performance

- **Duration:** ~10 min
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- `ArchitectMergeAdapter.__init__` 新增可注入 `spec_generation_hook`（延迟默认绑定 `agenerate_specs_for_plan` 避免 import 环）
- `_handle_pass` 在 `EVENT_PLAN_MERGE_COMPLETED` emit 之后、return 之前 best-effort 调 hook，外层 try/except 吞为 warning `sdd_spec_generation_failed`（双保险）
- 全链路守护测试：SDD 仓产 spec / 非 SDD 零回归 / 无匹配仓 / spec 合成异常 fail-soft / hook 整体抛错 fail-soft / stub 收到 canonical pv id / 幂等不翻倍
- 既有 test_architect_merge_adapter + engine merge 全量回归通过

## Task Commits

1. **Task 1: _handle_pass best-effort 挂接 + 构造注入** - `36730de61` (feat)
2. **Task 2: 全链路 merge hook 守护测试** - `9123f13d6` (test)

**Related fix:** `d7bc55382` (fix) — reword sdd_spec_service docstring to satisfy Document INV-6 guard（Plan 02 自引入，Rule 1 自修）

## Files Created/Modified
- `server/services/plan_orchestration/architect_merge_adapter.py` - 构造注入 hook + _handle_pass best-effort 挂接
- `server/tests/services/test_spec_generation_merge_hook.py` - 7 个全链路守护测试

## Decisions Made
None - followed plan as specified.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Document INV-6 守护因 sdd_spec_service.py docstring 字面量误报**
- **Found during:** Task 2（跑全 phase 收口测试时）
- **Issue:** Plan 02 的 `sdd_spec_service.py` 模块 docstring 含字面量 ``Document(sdd_spec)``，命中 test_document_inv6_guard 的 `\bDocument\s*\(` 旁路写表正则，守护误报违反。
- **Fix:** 改写 docstring 为「文档（sdd_spec 类型）」，避开写表模式；行为不变。
- **Files modified:** server/delivery/services/sdd_spec_service.py
- **Verification:** 三个 INV-6 守护（document/sdd_spec/architect_merge）全绿
- **Committed in:** `d7bc55382`

---

**Total deviations:** 1 auto-fixed (1 Rule 1 bug)
**Impact on plan:** 仅 docstring 措辞调整，无行为/逻辑改动，无 scope creep。

## Issues Encountered
- 见上「Deviations」：docstring 字面量触发 INV-6 grep 误报，已修。

## Next Phase Readiness
- SPEC-01/SPEC-02 全链路闭合：SDD 仓融合通过 → SddSpec(draft) + Document(sdd_spec) + emit spec.drafted，关联 work_item/plan_version/repository
- 非 SDD / 无 SDD / spec 异常 → merge 返回 passed 零回归；幂等不翻倍
- Phase 50（spec 状态机 + 评审 + 前端）可在 SddSpec 脊柱上挂载

---
*Phase: 49-produce-spec*
*Completed: 2026-06-17*
