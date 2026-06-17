---
phase: 52-spec-pr
plan: 03
subsystem: ui
tags: [vue3, spec-detail, delivery-panel, i18n, fail-soft, vitest, link-02]

requires:
  - phase: 50-spec-governance
    provides: spec 详情页 + SddSpecStatusBadge / SpecReviewTimeline 范式
  - phase: 52-02
    provides: spec detail 交付验收契约（implementation_prs / work_item.url / plan_version）
provides:
  - SpecDeliveryPanel.vue 交付验收追溯面板（WorkItem→spec→PR 链路 + fail-soft 降级）
  - spec 详情页挂接交付验收面板
  - specs.ts SddSpecDetail 类型对齐 + specs.delivery zh-CN 文案
affects: []

tech-stack:
  added: []
  patterns:
    - "追溯面板复用 card / SddSpecStatusBadge 范式 + 真实 i18n 文案"
    - "外链 :href + rel=noopener noreferrer（不用 v-html），全字段可选链 fail-soft"

key-files:
  created:
    - web/src/components/spec/SpecDeliveryPanel.vue
    - web/src/components/spec/__tests__/SpecDeliveryPanel.spec.ts
  modified:
    - web/src/api/specs.ts
    - web/src/locales/zh-CN.json
    - web/src/pages/specs/[id].vue

key-decisions:
  - "interface-first：按 D-52-4 锁定契约编码，wave 1 与后端 Plan 01 并行；vitest 用契约 fixture 不依赖后端运行时"
  - "PR 项展示 pr_url 全文（break-all）+ linkedAt 辅助文案，外链 rel=noopener 规避注入"

patterns-established:
  - "fail-soft 渲染：缺 work_item / 无 PR → 真实中文占位（workItemUnlinked / prsEmpty），绝不崩溃"

requirements-completed: [LINK-02]

duration: 10min
completed: 2026-06-17
---

# Phase 52 Plan 03: spec 详情页交付验收追溯面板 Summary

**SpecDeliveryPanel.vue 沿 WorkItem（需求，可点 prd_url）→ spec（状态徽标）→ 实现 PR 列表（pr_url 可点）渲染交付验收闭环；缺数据 fail-soft 降级真实中文占位；真实 zh-CN.json 文案接通**

## Performance

- **Duration:** ~10 min
- **Completed:** 2026-06-17
- **Tasks:** 3
- **Files modified:** 5（2 created + 3 modified）

## Accomplishments
- `specs.ts`：`SddSpecDetail` 补 `implementation_prs?: ImplementationPr[]` + `relations.work_item.url`，新增导出类型 `ImplementationPr`（对齐 D-52-4 契约）。
- `zh-CN.json`：`specs.delivery.*` 文案（标题/链路三段标签/未关联占位/PR 列表辅助）。
- `SpecDeliveryPanel.vue`：三段链路（需求/规格/实现 PR），全字段可选链 + 默认值 fail-soft；外链 `:href` + `rel="noopener noreferrer"` + `target="_blank"`（规避注入 T-52-06）；复用 `SddSpecStatusBadge` + card 范式 + lucide 图标 + i18n。
- `[id].vue`：评审历史 section 前挂接 `<SpecDeliveryPanel :spec="spec" />`。
- vitest 4 类用例（全链路渲染 / 缺 work_item 降级 / 无 PR 降级 / 无 url 纯文本），真实 zh-CN 文案断言。

## Task Commits

1. **Task 1: specs.ts 类型对齐 + specs.delivery zh-CN 文案** - `b8e7035d` (feat)
2. **Task 2: SpecDeliveryPanel 追溯面板 + 详情页挂接** - `f584a579` (feat)
3. **Task 3: SpecDeliveryPanel vitest 守护** - `5f9f4f44` (test)

## Files Created/Modified
- `web/src/api/specs.ts` - SddSpecDetail 类型对齐 + ImplementationPr
- `web/src/locales/zh-CN.json` - specs.delivery.* 文案
- `web/src/components/spec/SpecDeliveryPanel.vue` - 交付验收追溯面板
- `web/src/pages/specs/[id].vue` - 挂接面板
- `web/src/components/spec/__tests__/SpecDeliveryPanel.spec.ts` - 4 类守护用例

## Decisions Made
- interface-first 契约编码（不依赖后端 Plan 02 运行时，契约 fixture 验证）。
- PR 项展示 pr_url 全文（break-all）便于辨识。

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- `components.d.ts` 未自动重生成：SpecDeliveryPanel 经显式 import（非 auto-import），vue-tsc/eslint 未触发 d.ts 变更，故无需提交 components.d.ts。
- eslint 提示「Detected running in editor, some rules are disabled」（环境探测），与 plan 验证命令一致，无报错。

## Next Phase Readiness
- LINK-02 交付验收视图前端完成；真实容器 E2E（真实 PR 回填 + 验收视图真实数据）→ human_needed deferred。

## Self-Check: PASSED
- FOUND: web/src/components/spec/SpecDeliveryPanel.vue
- FOUND: web/src/components/spec/__tests__/SpecDeliveryPanel.spec.ts
- FOUND commits: b8e7035d, f584a579, 5f9f4f44

---
*Phase: 52-spec-pr*
*Completed: 2026-06-17*
