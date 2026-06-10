---
phase: 06-pat
plan: 01
subsystem: access_tokens
tags: [pat, nyquist-wave-0, tests, contract, red-first]
dependency_graph:
  requires: []
  provides:
    - "token_suffix==plaintext[-4:] + note persistence backend assertions"
    - "AccessTokenSerializer read-only note/token_suffix contract (no plaintext/hash)"
    - "fingerprint prefix…suffix + prefix-only fallback + note column frontend specs"
    - "never-expiry non-blocking warning + note-in-payload frontend specs"
  affects:
    - "06-02 (backend impl) — turns backend assertions GREEN"
    - "06-03 (frontend impl) — turns frontend specs GREEN"
tech_stack:
  added: []
  patterns:
    - "Nyquist Wave 0: RED-first lock-name tests before production code"
    - "pytest.importorskip keeps suite collectable while model fields absent"
    - "Select primitive stub to deterministically drive expiry strategy in happy-dom"
key_files:
  created:
    - web/src/components/accessTokens/__tests__/AccessTokenListTable.spec.ts
  modified:
    - server/tests/conftest.py
    - server/tests/test_access_tokens.py
    - web/src/components/accessTokens/__tests__/AccessTokenSettings.spec.ts
decisions:
  - "Never-warning asserted via distinctive 风险 copy (not 永不过期, which collides with the Select option label)"
  - "Note-in-payload locked at the form→store chain, gated on a name=\"note\" input existence assertion (clean RED, no element-not-found error)"
  - "Empty-suffix prefix-only test is an intentional GREEN regression guard (no dangling … for historical tokens)"
metrics:
  duration: ~9 min
  completed: 2026-06-09
  tasks: 3
  files: 4
---

# Phase 6 Plan 01: PAT Validation Contract (Nyquist Wave 0) Summary

RED-first test contract locking PAT-01/02/03/05 (note persistence, suffix fingerprint, read-only serializer output, never-expire non-blocking warning) as executable assertions before any production code — expected RED until 06-02 (backend) and 06-03 (frontend) land.

## What Was Built

**Task 1 — Backend fixture + suffix/note assertions** (`b27054b2`)
- `conftest.py` `make_access_token._make` now accepts `note: str = ""` and sets `token_suffix=plaintext[-4:]` and `note=note` on `AccessToken.objects.create(...)`, symmetric with the existing `token_prefix=plaintext[:12]`.
- `test_create_returns_plaintext_once` extended with `token.token_suffix == plaintext[-4:]` and `len(token.token_suffix) <= 4` (PAT-02/03).
- New `test_create_persists_note` asserts `token.note == "ci pipeline"` (PAT-01).
- `test_list_never_returns_plaintext` left unchanged — `plaintext not in str(...)` over all concrete fields stays intact (T-06-01 mitigation; the 4-char suffix is a substring, never the full token).

**Task 2 — Serializer read-only contract** (`dd07ab1f`)
- New `test_serializer_exposes_note_and_suffix_readonly`: asserts `note` and `token_suffix` present in serialized output, `data["token_suffix"] == token.token_suffix`, the negative security contract (`token_hash`/`token` absent), and `read_only_fields == fields` (T-06-02 mitigation — no writable field can sneak in).

**Task 3 — Frontend fingerprint/note + never-warning specs** (`2385b255`)
- New `AccessTokenListTable.spec.ts`: asserts `friday_pat_ab…WXYZ` (U+2026) for a suffixed token (RED), prefix-only with no dangling `…` for an empty-suffix historical token (GREEN guard), and the `note` value appears in the row text (RED).
- `AccessTokenSettings.spec.ts`: added a Select passthrough stub + extended `makeToken` with `token_suffix`/`note`; new `never_expiry_shows_nonblocking_warning_and_still_creates` (asserts amber 风险 copy + that submit still invokes `createToken`) and `note_value_flows_into_createToken_payload` (asserts `createToken` receives `{ note }`).

## Validation Results (expected RED — Wave 0)

| Suite | Command | Outcome |
|-------|---------|---------|
| Backend | `uv run pytest tests/test_access_tokens.py -q` | Collects cleanly; RED — `TypeError: AccessToken() got unexpected keyword arguments 'token_suffix', 'note'` |
| Frontend | `pnpm vitest run src/components/accessTokens` | Resolves cleanly; 4 failed / 7 passed — all failures are assertion-level RED |

Frontend RED breakdown: prefix…suffix (RED), note column (RED), never-warning 风险 (RED), note-in-payload (RED). Prefix-only fallback + the 3 existing Settings tests + 3 RevealDialog tests stay GREEN.

## Expected RED Cascade (per Nyquist strategy)

Editing the shared `make_access_token` fixture to pass `token_suffix`/`note` makes **all six** backend tests in `test_access_tokens.py` error with the same `TypeError` until 06-02 adds the model columns. This cascade is the intended Wave 0 state (noted per the execution brief) — collection still succeeds with zero import/collection errors; the failures are purely "field not yet on model".

## Deviations from Plan

**1. [Rule 1 — Bug] Never-warning assertion changed from `永不过期` to `风险`**
- **Found during:** Task 3 first vitest run.
- **Issue:** The plan suggested asserting the warning via `永不过期`, but the `AccessTokenForm` Select renders an option literally labelled `永不过期`. With the Select stub rendering its slot, `wrapper.text()` always contains `永不过期`, so the warning assertion passed falsely (GREEN) regardless of whether a warning exists.
- **Fix:** Assert the distinctive risk copy `风险` instead, which collides with neither the Select option label nor the reveal-dialog/header text — yielding a true RED.
- **Files modified:** `web/src/components/accessTokens/__tests__/AccessTokenSettings.spec.ts`
- **Commit:** `2385b255`

## Known Stubs

None — this plan only writes test contract; the "stubs" present are intentional Vue test-mount stubs (Dialog/Select primitives), not production placeholders.

## Threat Flags

None — no new production surface introduced (test edits only). T-06-01 and T-06-02 mitigations are encoded as assertions; T-06-SC (package installs) not triggered.

## Self-Check: PASSED

- FOUND: server/tests/conftest.py (note kwarg + token_suffix/note)
- FOUND: server/tests/test_access_tokens.py (token_suffix assertion, test_create_persists_note, test_serializer_exposes_note_and_suffix_readonly)
- FOUND: web/src/components/accessTokens/__tests__/AccessTokenListTable.spec.ts
- FOUND: web/src/components/accessTokens/__tests__/AccessTokenSettings.spec.ts (never-warning + note-payload specs)
- FOUND commit b27054b2 (Task 1)
- FOUND commit dd07ab1f (Task 2)
- FOUND commit 2385b255 (Task 3)
