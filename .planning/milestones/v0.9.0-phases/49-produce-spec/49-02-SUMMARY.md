---
phase: 49-produce-spec
plan: 02
subsystem: api
tags: [django, sdd_spec, service, idempotency, inv6]

# Dependency graph
requires:
  - phase: 49-produce-spec
    provides: SddSpec 模型 + DocumentService.create_internal_spec（Plan 01）
provides:
  - SddSpecService.create_draft —— SddSpec 单一写入入口（幂等短路 + get_or_create 兜底）
  - SddSpec 旁路写表 INV-6 grep 守护
affects: [49-03, 49-04, 50-spec-lifecycle]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "幂等短路：命中既有 SddSpec 直接返回，不调 create_internal_spec → 不留孤儿 Document/不翻版本"
    - "get_or_create + unique_together DB 约束兜底并发竞态"

key-files:
  created:
    - server/delivery/services/sdd_spec_service.py
    - server/tests/delivery/test_sdd_spec_service.py
    - server/tests/delivery/test_sdd_spec_inv6_guard.py
  modified:
    - server/delivery/services/__init__.py

key-decisions:
  - "幂等短路先探测既有 SddSpec，避免重产留孤儿 Document"
  - "状态流转/评审写入留 Phase 50，本 phase 仅 create_draft"

patterns-established:
  - "SddSpec 写入收口于 SddSpecService（INV-6），grep 守护断言"

requirements-completed: [SPEC-01, SPEC-02]

# Metrics
duration: ~8min
completed: 2026-06-17
---

# Phase 49 Plan 02: SddSpecService.create_draft 单一写入入口 Summary

**SddSpecService.create_draft 幂等单一写入入口（命中既有 SddSpec 短路返回不留孤儿 Document）+ SddSpec INV-6 grep 守护**

## Performance

- **Duration:** ~8 min
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- `SddSpecService.create_draft(plan_version_id, repository, work_item, content, change_kind="proposal")`：经 DocumentService.create_internal_spec 落 Document(sdd_spec) → get_or_create SddSpec(draft)
- 幂等短路：重产同 (plan_version_id, repository) 返回既有 SddSpec，不新增 SddSpec/Document/DocumentVersion
- `test_sdd_spec_inv6_guard`：grep 守护断言仅 SddSpecService 可写 SddSpec + writer 有效性
- curated re-export `SddSpecService`

## Task Commits

1. **Task 1: SddSpecService.create_draft (TDD) + re-export** - `9e6efe154` (feat)
2. **Task 2: SddSpec INV-6 grep guard** - `b1344bc46` (test)

## Files Created/Modified
- `server/delivery/services/sdd_spec_service.py` - create_draft + _create_locked
- `server/delivery/services/__init__.py` - re-export SddSpecService
- `server/tests/delivery/test_sdd_spec_service.py` - 4 个 TDD 测试
- `server/tests/delivery/test_sdd_spec_inv6_guard.py` - 2 个 grep 守护

## Decisions Made
None - followed plan as specified.

## Deviations from Plan
None - plan executed exactly as written.

## Issues Encountered
None.

## Next Phase Readiness
- create_draft 幂等入口就绪，Plan 03 spec 生成可逐 SDD 仓调用
- INV-6 守护全绿；ruff 通过

---
*Phase: 49-produce-spec*
*Completed: 2026-06-17*
