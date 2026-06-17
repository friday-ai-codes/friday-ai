---
phase: 49-produce-spec
plan: 01
subsystem: database
tags: [django, sdd_spec, document, migration, inv6]

# Dependency graph
requires:
  - phase: 30-document
    provides: Document/DocumentVersion 模型 + DocumentService 写入收口范式
  - phase: 44-repo-coding-task
    provides: 跨 app 字符串前向 FK 脊柱模型范式 + curated re-export
provides:
  - SddSpec 脊柱模型（delivery app）+ SddSpecStatus(5)/SddSpecChangeKind(2) 枚举
  - unique_together(plan_version, repository) 幂等键
  - 0018_sddspec 建表迁移（跨 app FK 依赖 repositories.0036）
  - DocumentService.create_internal_spec —— 内部生成文档单一写入入口
affects: [49-02, 49-03, 49-04, 50-spec-lifecycle, 51-coding-gate, 52-spec-pr]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "脊柱模型零业务方法（INV-6），写入只经 service"
    - "internal_generated 文档 external_ref='' 豁免飞书唯一约束"
    - "create_internal_spec 复用 hash 不翻版本铁律 + 可选 document 形参支撑版本复用"

key-files:
  created:
    - server/delivery/models/sdd_spec.py
    - server/delivery/migrations/0018_sddspec.py
    - server/tests/delivery/test_create_internal_spec.py
  modified:
    - server/delivery/models/__init__.py
    - server/delivery/services/document_service.py

key-decisions:
  - "SddSpecStatus 全 5 态现在定义，本 phase 仅落 draft 初值；流转归 Phase 50"
  - "document FK SET_NULL 保脊柱不随文档删除被抹"
  - "repository_label 仅入日志上下文，不持久化为 external_ref（守豁免语义）"

patterns-established:
  - "内部生成文档写入入口 create_internal_spec 与 upsert_from_feishu 并列收口 DocumentService"

requirements-completed: [SPEC-01, SPEC-02]

# Metrics
duration: ~10min
completed: 2026-06-17
---

# Phase 49 Plan 01: SddSpec 数据底座 + 内部文档写入入口 Summary

**新建 SddSpec 脊柱模型（5 态枚举 + unique_together 幂等键 + 0018 迁移）与 DocumentService.create_internal_spec 内部生成文档单一写入入口（INV-6）**

## Performance

- **Duration:** ~10 min
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments
- `SddSpec` 模型：document/repository/work_item/plan_version 四 FK，零业务方法（INV-6），跨 app 字符串前向 FK
- `SddSpecStatus`（draft/in_review/approved/implemented/archived）+ `SddSpecChangeKind`（proposal/delta）全枚举
- `unique_together(plan_version, repository)` 幂等键 + `0018_sddspec` 自动生成迁移（deps: delivery.0017 + repositories.0036）
- `DocumentService.create_internal_spec`：落 Document(sdd_spec, internal_generated, snapshot, external_ref="") + DocumentVersion，hash 不翻版本，可选 document 形参支撑幂等/版本复用

## Task Commits

1. **Task 1: SddSpec 模型 + 枚举 + re-export** - `28493f950` (feat)
2. **Task 2: 0018_sddspec 建表迁移** - `ffa36804c` (feat)
3. **Task 3: DocumentService.create_internal_spec (TDD)** - `766583fe5` (feat)

## Files Created/Modified
- `server/delivery/models/sdd_spec.py` - SddSpec 脊柱模型 + 两枚举
- `server/delivery/models/__init__.py` - curated re-export SddSpec/SddSpecStatus/SddSpecChangeKind
- `server/delivery/migrations/0018_sddspec.py` - 建表迁移
- `server/delivery/services/document_service.py` - 新增 create_internal_spec + _create_internal_spec_locked
- `server/tests/delivery/test_create_internal_spec.py` - 6 个 TDD 测试

## Decisions Made
None - followed plan as specified.

## Deviations from Plan
None - plan executed exactly as written.

## Issues Encountered
None.

## Next Phase Readiness
- SddSpec 模型 + create_internal_spec 就绪，Plan 02 可在其上建 SddSpecService.create_draft
- makemigrations --check 干净；ruff 通过；test_document_inv6_guard 仍绿

---
*Phase: 49-produce-spec*
*Completed: 2026-06-17*
