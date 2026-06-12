# Phase 16 — UI Review

**Audited:** 2026-06-12
**Baseline:** `.planning/phases/16-expo/16-UI-SPEC.md`
**Screenshots:** Captured at `.planning/ui-reviews/16-expo-20260612-114130/` — blank white frames (unauthenticated Playwright session; JWT required). Visual verification deferred to code audit.

---

## Pillar Scores

| Pillar | Score | Key Finding |
|--------|-------|-------------|
| 1. Copywriting | 3/4 | Core `knowledge.entity.*` keys present in `zh-CN.json`; hardcoded strings remain in `index.vue` and relation depth badge |
| 2. Visuals | 2/4 | Missing kind icons, provenance external-link icons, and SubStepTimeline-style vertical connectors |
| 3. Color | 2/4 | Timeline treats all nodes as emerald; latest node and as-of active state lack primary accent |
| 4. Typography | 3/4 | Title/body/mono scale largely matches contract; section heading hierarchy inconsistent |
| 5. Spacing | 3/4 | Card/section rhythm mostly on-scale; relation tree uses arbitrary `marginLeft` |
| 6. Experience Design | 2/4 | Missing error/retry flows, granular skeletons, metadata fields, and proper relation tree |

**Overall: 15/24**

---

## Top 3 Priority Fixes

1. **Add error + retry coverage for non-404 failures** — When entity/timeline/related queries fail (network, 500), the page shows perpetual skeletons or empty sections with no `loadFailed` / `retry` path. Wire per-query `isError` to `CompactEmptyState` + outline retry button per UI-SPEC Interaction & States.
2. **Complete metadata card and relation tree data presentation** — `EntityMetadataCard` omits `source_kind`, `source_id`, `invalid_at`, `project`, `repository` despite i18n keys existing; `EntityRelationTree` uses broken flat `buildTree` logic with hardcoded `跳`, no relation labels (`HAS_PLAN` / `IMPLEMENTED_BY`), and no `Collapsible` for depth > 2.
3. **Implement as-of active feedback and timeline accent states** — `EntityDetailToolbar` never renders `knowledge.entity.asOf.active` or primary status dot after datetime selection; `EntityVersionTimeline` paints every node `bg-emerald-400` instead of `bg-primary` on the newest node per ENH-04 contract.

---

## Detailed Findings

### Pillar 1: Copywriting (3/4)

**WARNING — Hardcoded placeholder copy on index page**

`web/src/pages/knowledge/index.vue:14-16` uses inline Chinese (`从工作流、对话检索结果…`) instead of a `knowledge.*` i18n key. Violates Copywriting Contract ("全部用户可见文案经 vue-i18n").

**WARNING — Hardcoded depth badge text**

`EntityRelationTree.vue:60-62` renders `{{ node.entity.depth }} 跳` without i18n. UI-SPEC defines relation/depth copy under `knowledge.entity.relation.*` and depth badge pattern.

**WARNING — Missing locale keys for relation/related/CTA**

`zh-CN.json` defines fields through `loading` but omits keys declared in UI-SPEC:
- `knowledge.entity.relation.hasPlan` / `implementedBy` / `relatesTo`
- `knowledge.entity.related.expand` / `viewEntity`
- `knowledge.entity.cta.openSource`

Components do not reference these keys yet, but contract keys are incomplete.

**PASS (partial)** — Primary entity detail strings (`sections`, `fields`, `empty`, `error`, `asOf`, `provenance`) are wired through `t()` and match `zh-CN.json` values.

---

### Pillar 2: Visuals (2/4)

**WARNING — Kind badges lack spec icons**

UI-SPEC Design System table requires per-kind lucide icons (`clipboard-list`, `file-text`, `git-pull-request`). `EntityKindBadge.vue` renders text-only `Badge` with no `icon-[lucide--*]` elements.

**WARNING — Provenance buttons missing external-link icon**

Wireframe and Interaction spec: `Button variant="outline" size="sm"` + `icon-[lucide--external-link]`. `ProvenanceLinkButton.vue:28-40` shows label text only.

**WARNING — Timeline visual pattern diverges from SubStepTimeline**

`EntityVersionTimeline.vue:20-22` uses inline `w-px` connector per node instead of `left-[7px]` absolute vertical line pattern documented in UI-SPEC Spacing Exceptions and implemented in `SubStepTimeline.vue:43-46`.

**WARNING — Inconsistent section hierarchy**

`[id].vue` renders `h2` section titles for timeline and related (`:108`, `:118`) but metadata section has no equivalent card/section title — anchor nav label only. Creates uneven visual rhythm.

**WARNING — Toolbar wireframe icon absent**

UI-SPEC wireframe shows `[icon history]` beside as-of label. `EntityDetailToolbar.vue` has label + input only.

**needs_human_review: true** — Screenshots captured but blank (auth gate); live visual hierarchy unverified.

---

### Pillar 3: Color (2/4)

**WARNING — Timeline accent not reserved for latest node**

UI-SPEC Color: "最新节点 accent 高亮（圆点 `bg-primary`）"; completed nodes use `bg-emerald-400`. `EntityVersionTimeline.vue:21` applies `bg-emerald-400` to **all** nodes unconditionally.

**WARNING — As-of active state missing primary indicator**

UI-SPEC: "as-of 已生效指示" via `bg-primary` dot + `text-xs text-primary` for `asOf.active`. `EntityDetailToolbar.vue` has no conditional active banner/dot when `asOfLocal` is non-empty.

**PASS (partial)** — Kind semantic colors in `EntityKindBadge.vue:12-16` match spec table (`slate`, `primary/10`, `emerald`). Current-version badge uses `variant="default"` (primary). Relation link hover uses `hover:text-primary`.

**PASS** — Superseded hint uses amber palette per spec (`EntityMetadataCard.vue:26-28`).

---

### Pillar 4: Typography (3/4)

**PASS** — Entity title `text-xl font-semibold` (`EntityMetadataCard.vue:18-19`) matches Metadata role.

**PASS** — Field labels `text-sm font-medium text-muted-foreground` and mono ID `font-mono text-xs` (`EntityMetadataCard.vue:29-36`) match contract.

**PASS** — Timeline node title `text-sm font-medium`, summary `text-xs text-muted-foreground line-clamp-3` (`EntityVersionTimeline.vue:26-30`).

**WARNING — Section titles outside card**

Timeline/related `h2.text-sm.font-semibold` sit above `.card` containers while metadata title lives inside card — breaks declared "卡片标题 14px" pattern for all three blocks.

---

### Pillar 5: Spacing (3/4)

**PASS** — Toolbar `px-5 py-3`, `flex-wrap`, `gap-4` (`EntityDetailToolbar.vue:28`) aligns with card toolbar spec (minor `gap-4` vs wireframe `gap-3`).

**PASS** — Section vertical rhythm `space-y-4`, `mt-6` (`[id].vue:103-117`); timeline list `space-y-6` (`EntityVersionTimeline.vue:13`).

**PASS** — Empty states use `CompactEmptyState` (implicit `py-12` via shared component).

**WARNING — Arbitrary depth indentation**

`EntityRelationTree.vue:50` uses `:style="{ marginLeft: \`${node.entity.depth * 12}px\` }"` — 12px per depth is off the 4px spacing scale and not documented as an exception.

**WARNING — Metadata card padding**

Uses uniform `p-5` (`EntityMetadataCard.vue:16`) rather than documented card header `px-5 py-3.5` + body split seen in reference components.

---

### Pillar 6: Experience Design (2/4)

**BLOCKER — No non-404 error handling or retry**

UI-SPEC requires `knowledge.entity.error.loadFailed` + `retry` button. `[id].vue` only handles `is404` (`:79-95`). Timeline/related/entity `isError` states are unhandled — failed fetches fall through to empty states or stale UI.

**WARNING — No per-section partial failure UX**

Spec: "失败区块内 CompactEmptyState + 重试 Button；其他已成功区块正常展示." Not implemented for independent query failures.

**WARNING — Coarse loading skeletons**

Spec: Metadata 6-cell grid skeleton, Timeline 4 rows, Related 3 rows, toolbar disabled. Implementation uses single `Skeleton` blocks (`h-40`, `h-48`, `h-32`) with no `aria-busy="true"` and toolbar remains interactive during load.

**WARNING — Metadata card incomplete field grid**

API type (`knowledge.ts:9-24`) and i18n include `source_kind`, `source_id`, `invalid_at`, `project_id`, `repository_id` but `EntityMetadataCard.vue` only renders version, entity_id, valid_at, event_time.

**WARNING — Entity ID lacks tooltip and copy**

Spec: "单行 mono + Tooltip 展示完整 UUID；可选 copy（useClipboard + toast）". Current implementation is plain `dd` text only (`EntityMetadataCard.vue:35-36`).

**WARNING — EntityRelationTree does not build hierarchical tree**

`buildTree()` (`EntityRelationTree.vue:18-39`) skips depth-0 items, fails to attach children to parents, and falls back to flat list. No `Collapsible` for layers beyond 2, no `RouterLink` preservation of `as_of` query param.

**WARNING — As-of invalid input not surfaced**

`localToIso` silently returns `null` on bad input (`[id].vue:28-34`); no `text-destructive text-xs` inline message per spec.

**WARNING — Current version badge logic incomplete**

Badge shown when `!entity.invalid_at` only (`EntityMetadataCard.vue:22`). Spec also references `is_latest` flag when `invalid_at` may be set on non-latest snapshots.

**PASS** — 404 fail-closed with `CompactEmptyState` + `router.back()` (`[id].vue:89-95`).

**PASS** — Read-only surface: no edit/delete controls.

**PASS** — Provenance links use `target="_blank" rel="noopener noreferrer"` and `aria-label` (`ProvenanceLinkButton.vue:35-37`).

**PASS** — As-of / include_superseded invalidate queries correctly (`[id].vue:37-44`).

**PASS** — Sidebar nav entry added (`AppSidebar.vue:85`) with `lucide--book-open`.

---

## Registry Safety

Registry audit: skipped — UI-SPEC `shadcn_initialized: false`; only project-local `~/components/ui/*` and reka-ui. No third-party shadcn registry blocks to scan.

---

## Files Audited

- `.planning/phases/16-expo/16-UI-SPEC.md`
- `web/src/pages/knowledge/entities/[id].vue`
- `web/src/pages/knowledge/index.vue`
- `web/src/components/knowledge/EntityDetailToolbar.vue`
- `web/src/components/knowledge/EntityMetadataCard.vue`
- `web/src/components/knowledge/EntityVersionTimeline.vue`
- `web/src/components/knowledge/EntityRelationTree.vue`
- `web/src/components/knowledge/EntityKindBadge.vue`
- `web/src/components/knowledge/ProvenanceLinkButton.vue`
- `web/src/locales/zh-CN.json` (knowledge.entity section)
- `web/src/api/knowledge.ts`
- `web/src/components/layout/AnchorNavLayout.vue` (reference)
- `web/src/components/execution/dag/SubStepTimeline.vue` (reference)
- `web/src/components/layout/AppSidebar.vue`
- `web/src/pages/knowledge/__tests__/entity-detail.spec.ts`
- `web/src/components/knowledge/__tests__/entity-components.spec.ts`
- Screenshots: `.planning/ui-reviews/16-expo-20260612-114130/desktop.png`, `mobile.png`
