---
phase: 03-audit-ui
plan: 03
subsystem: audit
tags: [audit, ui, frontend, vue, export]
depends_on:
  requires: [audit-api, audit-model]
  provides: [audit-ui]
  affects: [admin-pages]
tech_stack:
  added: [audit-api-module]
  patterns: [server-side-pagination, json-diff-dialog, dropdown-export]
key_files:
  created:
    - web/src/api/audit.ts
    - web/src/pages/admin/audit.vue
    - web/src/pages/admin/__tests__/audit.spec.ts
  modified:
    - web/src/api/index.ts
decisions:
  - "Use sentinel value __all__ for reka-ui SelectItem (no empty string allowed)"
  - "Server-side pagination via DRF PageNumberPagination + frontend page controls"
  - "Export via window.open (direct download, not fetch wrapper)"
  - "Detail dialog uses pre/code for JSON diff display (no external diff library)"
metrics:
  duration: ~10min
  completed: "2026-06-15T12:40:00Z"
  tasks: 4
  files: 4
---

# Phase 03 Plan 03: Audit Query UI Summary

## One-liner

Vue 3 audit query page with DataTable, filters (action/source/target_type/date range), detail dialog (before/after JSON diff), and CSV/JSON export.

## What Was Built

- **`web/src/api/audit.ts`**: Typed API client module with `listAuditEvents()` (paginated list with filters) and `exportAuditEvents()` (CSV/JSON download trigger)
- **`web/src/pages/admin/audit.vue`**: Admin-only audit page at `/admin/audit` with:
  - DataTable (server-side pagination) showing audit events
  - Filter bar: action dropdown (preset values), source dropdown (web/api/system), target_type input, date range picker, reset button
  - Detail dialog on row click: shows actor, IP, action, source, target info + before/after JSON diff in pre/code blocks + extra context
  - Export dropdown: CSV and JSON export buttons (trigger browser download with current filters)
- **`web/src/api/index.ts`**: Registered audit API in barrel exports
- **`web/src/pages/admin/__tests__/audit.spec.ts`**: Vitest tests covering requiresAdmin meta, table rendering, detail dialog opening, and export trigger

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] reka-ui SelectItem rejects empty string value**
- **Found during:** Task 4 (tests)
- **Issue:** reka-ui's SelectItem component throws error when value="" is used for "all" options
- **Fix:** Changed to sentinel value `__all__` and added `applyFilterFromSelect()` helper to convert sentinel back to filter clearing
- **Files modified:** web/src/pages/admin/audit.vue
- **Commit:** 95c94fc4

**2. [Rule 1 - Bug] Dialog content not in wrapper.text() in tests**
- **Found during:** Task 4 (tests)
- **Issue:** Dialog renders via teleport to document.body, so wrapper.text() doesn't include dialog content
- **Fix:** Changed test assertion to check `document.body.textContent` instead
- **Files modified:** web/src/pages/admin/__tests__/audit.spec.ts
- **Commit:** 95c94fc4

## Decisions Made

- **Sentinel value for Select "all" option**: reka-ui doesn't allow empty string as SelectItem value; used `__all__` sentinel with conversion helper
- **Server-side pagination**: DataTable uses `server-side` mode; page controls rendered separately below table
- **Export via window.open**: Direct browser download (not fetch wrapper) to avoid CORS/cookie issues with file downloads
- **JSON diff with pre/code**: Simple formatted JSON display instead of external diff library (keeps bundle small)

## Known Stubs

None - all data flows through real API endpoints.

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| - | - | No new security surface (audit is read-only, protected by IsSuperUser) |

## Auth Gates

None - page uses `requiresAdmin` meta (UX guard) backed by `IsSuperUser` backend permission.
