---
phase: 97-delivery-docs-knowledge-tree
reviewed: 2026-07-01T19:10:00Z
depth: deep
files_reviewed: 5
files_reviewed_list:
  - server/knowledge/api/artifact_tree.py
  - server/knowledge/api/urls.py
  - web/src/components/knowledge/DeliveryDocsTree.vue
  - web/src/pages/knowledge/index.vue
  - web/src/api/knowledge.ts
findings:
  blocker: 0
  high: 0
  medium: 1
  low: 2
  info: 2
  total: 5
status: clean
---

# Phase 97: 交付文档知识树视图 — Code Review Report

**Reviewed:** 2026-07-01T19:10:00Z
**Depth:** deep (cross-file: backend endpoint ↔ TS contract ↔ Vue consumer)
**Files Reviewed:** 5 (+ mirror reference `artifact_overview.py`, `access_scope.py`, `initiatives/models/artifact.py`)
**Status:** clean — no BLOCKER / HIGH findings

## Summary

Phase 97 adds a nested delivery-docs knowledge tree: a new backend endpoint
`GET /api/knowledge/artifacts/tree/` (`ArtifactTreeView`) returning a pre-assembled
`project → type → artifact` tree, a new `DeliveryDocsTree.vue` client (load-once +
pure client-side search/expand/view), a view switcher in `knowledge/index.vue`, TS
contracts in `knowledge.ts`, and zh-CN strings.

The implementation faithfully mirrors the already-shipped Phase 96 `artifact_overview.py`
paradigm, and the security/observability/async fundamentals are sound:

- **Access scope / fail-closed:** `resolve_allowed_project_ids(request.user)` gate runs
  before any DB query; empty scope → `dict(_EMPTY)` with **zero DB hit**. Filter
  `project__space_id__in=allowed` is identical to the overview endpoint. No *new*
  cross-project/space leak introduced (the pre-existing public_org id-mixing = Phase 96
  MED-03, explicitly out of scope).
- **XSS:** search highlight uses `<mark>` segment rendering via text interpolation
  (`highlightTitle` → `HighlightSegment[]`), **no `v-html`**. Safe.
- **external_link:** all outbound anchors carry `rel="noopener noreferrer"` + `target="_blank"`.
- **N+1:** `_build_tree` uses `select_related("type", "project")`; every attribute touched
  (`project.name`, `type.key/name/carrier/ragable`, `carrier`, `url`, `updated_at`) is covered.
- **Authz:** `IsAuthenticated`; no query params → no param-validation surface.
- **Observability:** `artifact_tree_started/completed/failed` with `duration_ms`,
  `category="caller"`, `component="knowledge"`; aggregation wrapped best-effort
  (`except Exception` → warning + empty structure, never 500). No secret leakage in kv.
- **Async:** `_build_tree` (sync ORM) invoked via `sync_to_async`; scope resolver is async. Correct.
- **Hard constraint verified:** `git diff 4ff7ef46^ HEAD -- .../KnowledgeTreePanel.vue` is
  **empty** — code capability tree behavior unchanged.
- **i18n:** all consumed keys resolve (`knowledge.tree.docs.*`, `knowledge.tree.viewSwitch.*`,
  `knowledge.search.loading`, `projects.artifacts.viewFailed/viewDesc/recordCount/unsupported`).
  No missing zh-CN keys.
- **Type safety / states:** TS contracts match backend JSON shape; loading / whole-tree-empty /
  search-no-match states all present; design tokens reuse Phase 96 badge/segmented-control classes.

Remaining findings are minor robustness / UX-consistency notes; none block ship.

## Warnings

### MED-01: Backend error is rendered as the "empty" CTA state, not an error state

**File:** `web/src/components/knowledge/DeliveryDocsTree.vue:189` (and error branch `:46-49`)
**Issue:** On query failure `data` is `undefined`, so the guard
`v-else-if="!data || data.total === 0 || data.projects.length === 0"` renders the
*empty* CompactEmptyState ("暂无交付文档 … 去作战室维护外部依赖"). A transient 5xx/network
error therefore tells the user their data is empty and to go create docs, which is
misleading. A toast does fire (`watch(isError …)`), which mitigates but does not remove
the wrong on-page state. The sibling `index.vue` search flow does not have this issue
because it separates loading/empty explicitly.
**Fix:** add a dedicated error branch before the empty branch, e.g.:
```vue
<div v-else-if="isError" class="flex min-h-[380px] items-center justify-center">
  <CompactEmptyState
    icon="lucide--triangle-alert"
    :title="t('knowledge.tree.docs.loadFailed')"
    :description="t('common.retryHint')"
  />
</div>
```
(guard `!data && isError` so a stale-cache success still renders the tree).

## Info

### LOW-01: `truncated` false-positive at the exact global cap boundary

**File:** `server/knowledge/api/artifact_tree.py:61`
**Issue:** `truncated = len(rows) >= _GLOBAL_FETCH_CAP`. When there are *exactly* 5000
artifacts, the slice `[:_GLOBAL_FETCH_CAP]` returned all of them yet `truncated` is set
`True`, showing the "结果较多已截断" banner despite nothing being dropped. Conservative
(safe) but slightly inaccurate.
**Fix:** fetch one extra sentinel and compare, e.g. `rows = list(qs[:_GLOBAL_FETCH_CAP + 1])`
then `truncated = len(rows) > _GLOBAL_FETCH_CAP` and trim `rows = rows[:_GLOBAL_FETCH_CAP]`.
Low priority.

### LOW-02: `total` excludes projects dropped by the `_MAX_PROJECTS` clamp

**File:** `server/knowledge/api/artifact_tree.py:106-123`
**Issue:** `total` is summed only over projects that survive the `_MAX_PROJECTS`
clamp (`for proj in projects_map.values(): if len(projects) >= _MAX_PROJECTS: break`).
When >200 visible projects exist, the returned `total` under-reports the true visible
artifact count. `truncated=True` is correctly flagged, so this is a cosmetic
inconsistency (unlike overview where `total` is the grand total). Docstring says
`count` records the real bucket count; the *tree* `total` does not for the clamped tail.
**Fix (optional):** accumulate `total` while grouping (before the clamp loop), or document
that `total` is "displayed total" when `truncated`.

### INFO-01: Type node grouped by `type.key` but rows ordered by `type__name`

**File:** `server/knowledge/api/artifact_tree.py:59,78`
**Issue:** Grouping key is `a.type.key` while ordering is `type__name`. If two distinct
type keys share an identical `type_name`, their leaves could interleave in fetch order;
dict grouping still keeps them as separate correct nodes (no data bug), but sibling
display order is first-seen rather than strictly name-sorted. Practically negligible
(type names are effectively unique). No action required.

---

_Reviewed: 2026-07-01T19:10:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
