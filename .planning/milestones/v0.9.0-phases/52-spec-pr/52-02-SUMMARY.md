---
phase: 52-spec-pr
plan: 02
subsystem: api
tags: [sdd-spec, serializer, drf, traceability, fail-soft, link-02]

requires:
  - phase: 52-01
    provides: SddSpec.implementation_prs JSON 字段
  - phase: 50-spec-governance
    provides: SddSpecDetailSerializer（body/reviews/relations）
provides:
  - SddSpecDetailSerializer 扩 implementation_prs + work_item url + plan_version 追溯摘要
affects: [52-03]

tech-stack:
  added: []
  patterns:
    - "detail-only 追溯字段：implementation_prs 仅 DetailSerializer 暴露，List 不变"
    - "work_item.url 取 prd_url（不臆造 URL），缺失降级空串/省键"

key-files:
  created:
    - server/tests/delivery/test_sdd_spec_detail_serializer.py
  modified:
    - server/delivery/api/serializers.py

key-decisions:
  - "implementation_prs 用 serializers.JSONField(read_only=True) 直映模型 JSON 列，default=list 天然空列表 fail-soft"
  - "work_item.url 取 prd_url or ''（对齐 pr_cross_reference 不构造臆造 URL 范式）"

patterns-established:
  - "序列化器只读暴露追溯数据，写入仍只经 SddSpecService（INV-6，序列化器不写表）"

requirements-completed: [LINK-01, LINK-02]

duration: 6min
completed: 2026-06-17
---

# Phase 52 Plan 02: SddSpecDetailSerializer 交付验收追溯摘要 Summary

**SddSpecDetailSerializer 暴露 implementation_prs（实现 PR 列表）+ work_item url(取 prd_url)/title + plan_version 摘要，形成 spec → 需求 → PR 完整追溯 JSON；缺数据降级（[]/省键）不报错**

## Performance

- **Duration:** ~6 min
- **Completed:** 2026-06-17
- **Tasks:** 1
- **Files modified:** 2（1 created + 1 modified）

## Accomplishments
- `SddSpecDetailSerializer.Meta.fields` 追加 `implementation_prs`，以 `serializers.JSONField(read_only=True)` 直映模型 JSON 列（无回填 → 空列表，天然 fail-soft）。
- `get_relations` 的 work_item 分支补 `"url": obj.work_item.prd_url or ""`（取 prd_url，不臆造），保留 title；无 work_item 维持省键降级。
- plan_version 摘要保持原样；列表序列化器（SddSpecListSerializer）不暴露 implementation_prs（仅 detail）。

## Task Commits

1. **Task 1: SddSpecDetailSerializer 扩追溯摘要** - `27dde7de` (feat, TDD RED→GREEN 单提交)

## Files Created/Modified
- `server/delivery/api/serializers.py` - SddSpecDetailSerializer 扩 implementation_prs + work_item url
- `server/tests/delivery/test_sdd_spec_detail_serializer.py` - 追溯摘要 + 降级守护（7 用例）

## Decisions Made
- 直映 JSONField 而非 SerializerMethodField（default=list 已天然空列表降级）。

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None - 既有 spec list/detail/transition API 测试零回归（17 用例 + 7 新用例全绿）；无新增 migration（仅序列化器变更，makemigrations --check 干净）。

## Next Phase Readiness
- detail 契约就绪：Plan 03 前端按 `delivery_contract`（implementation_prs / work_item.url / plan_version / status）渲染交付验收面板。

## Self-Check: PASSED
- FOUND: server/tests/delivery/test_sdd_spec_detail_serializer.py
- FOUND commit: 27dde7de

---
*Phase: 52-spec-pr*
*Completed: 2026-06-17*
