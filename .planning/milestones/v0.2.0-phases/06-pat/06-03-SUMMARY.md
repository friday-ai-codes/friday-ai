---
phase: 06-pat
plan: 03
subsystem: ui
tags: [pat, vue3, vee-validate, zod, tailwind, access-tokens, frontend]

# Dependency graph
requires:
  - phase: 06-01
    provides: "RED frontend specs (never-warning 风险, note-in-payload, prefix…suffix fingerprint, note column)"
  - phase: 06-02
    provides: "backend note + token_suffix serializer output + optional note create input"
provides:
  - "AccessTokenDto carries note + token_suffix (may be empty for historical tokens)"
  - "AccessTokenCreatePayload optional note"
  - "Create form: optional note input (zod max 500) + name max 200 + non-blocking never-expire amber warning"
  - "Token list: 备注 column + prefix…suffix fingerprint with prefix-only fallback"
affects: [07-auth, future PAT UI work]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Synchronous zod safeParse on submit (instead of vee-validate async handleSubmit) for predictable, test-deterministic emit"
    - "User-controlled text rendered via Vue interpolation only (auto-escape; never v-html) at the API→render trust boundary"

key-files:
  created: []
  modified:
    - web/src/types/accessToken.ts
    - web/src/components/accessTokens/AccessTokenForm.vue
    - web/src/components/accessTokens/AccessTokenListTable.vue
    - web/src/stores/__tests__/accessTokens.spec.ts

key-decisions:
  - "Submit emits via synchronous accessTokenSchema.safeParse(values) rather than vee-validate's async handleSubmit; field-level validation/FormMessage still driven by the same schema"
  - "备注 column placed after 指纹, hidden on small screens (md:table-cell) with truncation, matching existing column responsiveness"

patterns-established:
  - "Sync-on-submit zod gate: keep vee-validate for live field UX, but parse form values synchronously at submit so emit lands in the current tick"
  - "Fingerprint render: token_suffix ? `${prefix}…${suffix}` : prefix (U+2026, no dangling separator for historical tokens)"

requirements-completed: [PAT-01, PAT-03, PAT-04, PAT-05]

# Metrics
duration: ~35min
completed: 2026-06-09
---

# Phase 6 Plan 03: PAT Frontend增量 (note + token_suffix + never-warning) Summary

**Extended the accessTokens Vue UI to surface note + token_suffix and a non-blocking never-expire amber warning, turning all four Wave-0 (06-01) frontend specs GREEN with a synchronous zod submit gate.**

## Performance

- **Duration:** ~35 min
- **Completed:** 2026-06-09
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments

- `AccessTokenDto` now carries `note` + `token_suffix`; `AccessTokenCreatePayload` carries optional `note`.
- Create form gained an optional 备注 input (zod `max(500)`), aligned `name.max(200)`, and a non-blocking amber `风险` warning shown only when expiry strategy is `never` (submit still fires).
- Token list renders a 备注 column (text-interpolated, auto-escaped) and a `prefix…suffix` fingerprint that degrades to prefix-only for historical (empty-suffix) tokens.
- No renewal/续期 control added — revoke remains the only mutating action (PAT-04 preserved).
- All 11 `src/components/accessTokens` vitest specs GREEN; project typecheck passes.

## Task Commits

1. **Task 1: Extend DTO + create payload (note / token_suffix)** - `9bf8ac1b` (feat)
2. **Task 2: Form note input + zod alignment + never-expire amber warning** - `04e698db` (feat)
3. **Task 3: List table note column + prefix…suffix fingerprint** - `c135fb05` (feat)

## Files Created/Modified

- `web/src/types/accessToken.ts` - Added `note` + `token_suffix` to `AccessTokenDto`, optional `note` to `AccessTokenCreatePayload`.
- `web/src/components/accessTokens/AccessTokenForm.vue` - note FormField, zod `name.max(200)` + optional `note.max(500)`, non-blocking amber never-expire warning, synchronous safeParse submit.
- `web/src/components/accessTokens/AccessTokenListTable.vue` - 备注 column + `prefix…suffix` fingerprint (prefix-only fallback), empty-state colspan 7→8.
- `web/src/stores/__tests__/accessTokens.spec.ts` - Fixture aligned to new required DTO fields (Rule 3 blocking fix; see Deviations).

## Decisions Made

- **Synchronous submit gate:** The locked 06-01 specs (`never_expiry_shows_nonblocking_warning_and_still_creates`, `note_value_flows_into_createToken_payload`) assert `createToken` is called after only `await flushPromises()`. Empirically, vee-validate's async `handleSubmit` validation resolves on wall-clock time (a single 30ms real delay fired it; microtask flushing did not), so a bare `flushPromises()` never captured the emit. Resolution: keep vee-validate + the same zod schema for live field-level validation/FormMessage, but perform a **synchronous** `accessTokenSchema.safeParse(values)` in `onSubmit` and `emit` in the current tick. Field errors are mapped back via `setErrors` for display. This makes submit deterministic and satisfies the locked specs without modifying them.
- **备注 column placement/responsiveness:** Placed after 指纹, `hidden md:table-cell` with truncation to match sibling columns.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Aligned store spec fixture with new required DTO fields**
- **Found during:** Task 1 (DTO extension)
- **Issue:** `AccessTokenDto` gained required `note`/`token_suffix`. `web/src/stores/__tests__/accessTokens.spec.ts` `makeToken()` constructs a bare `AccessTokenDto` literal, which fails `vue-tsc` (missing required properties) since tsconfig typechecks all non-excluded files. This is a blocking type error directly caused by the Task 1 change.
- **Fix:** Added `note: ''` and `token_suffix: ''` to the store spec's `makeToken()` fixture (mirrors the pattern 06-01 used in the accessTokens component specs).
- **Files modified:** `web/src/stores/__tests__/accessTokens.spec.ts`
- **Verification:** `pnpm vue-tsc --noEmit` exits 0; store spec still 5/5 GREEN.
- **Committed in:** `9bf8ac1b` (Task 1 commit)

**2. [Rule 3 - Blocking] Submit emit made synchronous (vee-validate async handleSubmit → sync safeParse)**
- **Found during:** Task 2 (form never-warning + note-payload specs)
- **Issue:** Locked specs assert `createToken` is called after `trigger('submit')` + a single `await flushPromises()`. vee-validate's `handleSubmit` validation resolves only after real elapsed time, so `createToken` was never called within the spec's awaits (the call leaked into the next test). The locked specs cannot be modified.
- **Fix:** Replaced `handleSubmit(cb)` with a plain `onSubmit()` that synchronously `safeParse`s the reactive `values` against the same zod schema, maps any errors via `setErrors`, and emits in the current tick. Live per-field validation/FormMessage still flows from `validationSchema`.
- **Files modified:** `web/src/components/accessTokens/AccessTokenForm.vue`
- **Verification:** `pnpm vitest run src/components/accessTokens` 11/11 GREEN; `vue-tsc` exits 0.
- **Committed in:** `04e698db` (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 3 - Blocking)
**Impact on plan:** No scope creep. Both fixes were required to make the change typecheck and to satisfy the locked Wave-0 contract. UI behavior matches the plan (optional note, non-blocking never-warning, escaped note column, prefix…suffix fingerprint, revoke-only).

## Issues Encountered

- Diagnosed the submit timing via a throwaway debug spec (created, used to confirm vee-validate value commit was correct but async validation needed wall-clock time, then deleted). No debug artifacts remain.

## Security Contract Held

- **T-06-07 (stored XSS via note):** `note` rendered via Vue text interpolation (`{{ t.note }}`) in the list — auto HTML-escaped, never `v-html`.
- **T-06-09 (oversized input):** zod `name.max(200)` + `note.max(500)` mirror backend authoritative limits.
- **T-06-08 (plaintext leakage):** No store/api/persistence changes; new fields are read-only metadata; existing AccessTokenSettings plaintext-clearing specs remain GREEN.
- **PAT-04:** No renewal/续期 control added; revoke remains the only mutating action.

## Validation Results

| Check | Command | Outcome |
|-------|---------|---------|
| Frontend specs | `pnpm vitest run src/components/accessTokens` | 11 passed (3 files; all 06-01 RED → GREEN) |
| Store regression | `pnpm vitest run src/stores/__tests__/accessTokens.spec.ts` | 5 passed |
| Typecheck | `pnpm vue-tsc --noEmit -p tsconfig.json` | Exit 0 |
| Lint | diagnostics on changed files | No linter errors |

## Known Stubs

None — all new fields/UI are fully wired to the DTO/store data path.

## Threat Flags

None — no new network endpoints, auth paths, or trust-boundary surface introduced beyond the planned `note` render (escaped) and `token_suffix` display.

## Next Phase Readiness

- PAT UI half of Phase 6 complete (PAT-01/03/04/05 frontend). Backend (06-02) + frontend (06-03) both GREEN.
- Manual verification (per 06-VALIDATION Manual-Only) deferred to end-of-phase human verify: browser create → never-expire amber warning + submit success; list shows note + prefix…suffix.

## Self-Check: PASSED

- FOUND: web/src/types/accessToken.ts (note + token_suffix on DTO; optional note on payload)
- FOUND: web/src/components/accessTokens/AccessTokenForm.vue (note input + zod + never-expire 风险 warning + sync submit)
- FOUND: web/src/components/accessTokens/AccessTokenListTable.vue (备注 column + token_suffix fingerprint, colspan 8)
- FOUND commit 9bf8ac1b (Task 1)
- FOUND commit 04e698db (Task 2)
- FOUND commit c135fb05 (Task 3)

---
*Phase: 06-pat*
*Completed: 2026-06-09*
