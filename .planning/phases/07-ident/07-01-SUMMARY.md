---
phase: 07-ident
plan: 01
subsystem: backend-auth-tests
tags: [auth, pat, jwt, mcp, fail-closed, nyquist-wave-0, red-tests]
requires:
  - "access_tokens.models (PAT_PREFIX, generate_pat, created_by)"
  - "access_tokens.authentication.AccessTokenAuthentication"
  - "tests/conftest.py fixtures (make_access_token, access_user, user, api_client, urls)"
provides:
  - "Executable auth contract for IDENT-01/02/05 (owner identity, prefix gate, PAT/JWT coexistence, revoked denial)"
  - "MCP fail-closed error-code contract (authentication_failed / 401)"
affects:
  - "07-02 (auth refactor + settings ordering) — turns owner/coexistence assertions GREEN"
  - "07-03 (MCP IsAuthenticated tightening) — turns missing-token assertion GREEN"
tech-stack:
  added: []
  patterns:
    - "pytest.importorskip module guard for not-yet-implemented code"
    - "APIRequestFactory drives DRF authenticator directly (unit); APIClient.credentials() exercises full chain (integration)"
key-files:
  created:
    - server/tests/test_pat_identity.py
  modified:
    - server/tests/test_access_tokens.py
    - server/tests/mcp_tools/test_mcp_auth_errors.py
decisions:
  - "Resolved Open Question 1: MCP anonymous request converges to error_code=authentication_failed (not authentication_required), staying 401 fail-closed"
  - "Integration tests target IsAuthenticated-protected /me through the real DRF chain — no mocked authenticators — so 07-02 settings ordering is what gets validated"
metrics:
  duration: 12
  completed: 2026-06-09
---

# Phase 7 Plan 1: PAT 认证地基验证脚手架 (Wave 0 RED) Summary

Encodes the "令牌即用户身份" auth contract as executable tests **before** implementation: owner identity on successful PAT auth, the `friday_pat_` prefix gate (non-PAT Bearer falls through to JWT), PAT/JWT coexistence with PAT class first, revoked-token denial, and MCP fail-closed `authentication_failed`/401 — all expected RED until 07-02/07-03 land.

## What Was Built

Three test files were authored/adjusted, touching **only test code** (no production source modified):

1. **`tests/test_access_tokens.py`** — `test_valid_token_passes` flipped from `assert user is None` to `assert user == token.created_by` (IDENT-01). The `auth_token.token_hash == token.token_hash` and `not hasattr(auth_token, "scope")` assertions are unchanged; `test_revoked_expired_denied_and_logged` (IDENT-05) is untouched.

2. **`tests/test_pat_identity.py`** (new, 6 tests) — locks IDENT-01/02/05:
   - `test_valid_pat_authenticates_as_owner` (unit) — `authenticate()` returns `(owner, token)`.
   - `test_non_pat_bearer_falls_through` (unit) — non-`friday_pat_` Bearer → `authenticate()` returns `None` (passthrough, never raises).
   - `test_unknown_pat_is_rejected_not_passed_through` (unit) — known-prefix-but-absent token → `raise AuthenticationFailed`.
   - `test_pat_authenticates_protected_endpoint_as_owner` (integration) — valid PAT GET `/me` → 200, username == owner.
   - `test_jwt_bearer_still_authenticates_with_pat_class_first` (integration) — minted JWT Bearer GET `/me` → 200 (PAT/JWT 互不吞).
   - `test_revoked_pat_rejected_through_chain` (integration) — revoked PAT GET `/me` → 401.

3. **`tests/mcp_tools/test_mcp_auth_errors.py`** — `test_missing_token_returns_error_code` now asserts `error_code == "authentication_failed"` (kept `status_code == 401`). The two valid-PAT tests are unmodified.

## RED Test Status (Expected)

This is a Nyquist Wave 0 plan — failures below are by design and turn GREEN when 07-02/07-03 ship. Confirmed: no collection/import errors in any file (17 tests collect cleanly).

| Test | State | Turns GREEN in |
|------|-------|----------------|
| `test_access_tokens::test_valid_token_passes` | RED (`None == owner`) | 07-02 (success branch returns owner) |
| `test_pat_identity::test_valid_pat_authenticates_as_owner` | RED (owner not yet returned) | 07-02 |
| `test_pat_identity::test_non_pat_bearer_falls_through` | RED (no prefix gate yet → raises on unknown token) | 07-02 (prefix gate) |
| `test_pat_identity::test_pat_authenticates_protected_endpoint_as_owner` | RED (401 — PAT not in DEFAULT_AUTHENTICATION_CLASSES) | 07-02 (settings ordering) |
| `test_pat_identity::test_unknown_pat_is_rejected_not_passed_through` | GREEN already | — |
| `test_pat_identity::test_jwt_bearer_still_authenticates_with_pat_class_first` | GREEN already | — |
| `test_pat_identity::test_revoked_pat_rejected_through_chain` | GREEN already | — |
| `test_mcp_auth_errors::test_missing_token_returns_error_code` | RED (`authentication_required` vs `authentication_failed`) | 07-03 (IsAuthenticated base) |
| `test_mcp_auth_errors` valid-PAT tests (x2) | GREEN (unchanged) | — |

Per-task verification recorded RED exactly as predicted by RESEARCH §Pitfall 1/2/3.

## Regression Guard (no change, protective)

`tests/test_auth.py` / `tests/test_auth_e2e.py` unauthenticated-401 assertions were intentionally left untouched. They are the BLOCKING guard for Pitfall 2 (401→403 downgrade): 07-02 must add `authenticate_header` so these stay GREEN.

## Deviations from Plan

None — plan executed exactly as written.

## Threat Surface

No new security surface introduced (test edits only). Threat register dispositions T-07-01 (MCP fail-open), T-07-02 (JWT swallow), T-07-03 (revoked usable) are each now backed by an executable assertion as planned.

## Self-Check: PASSED
- FOUND: server/tests/test_pat_identity.py
- FOUND: server/tests/test_access_tokens.py (modified)
- FOUND: server/tests/mcp_tools/test_mcp_auth_errors.py (modified)
- FOUND commit 9e2740d0 (Task 1)
- FOUND commit 10ee9da8 (Task 2)
- FOUND commit e05906a2 (Task 3)
