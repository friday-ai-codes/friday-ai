---
phase: 07-ident
plan: 03
subsystem: backend-mcp-auth
tags: [auth, mcp, fail-closed, isauthenticated, pat, jwt, ident-03, ident-04]
requires:
  - "access_tokens.authentication.AccessTokenAuthentication (PAT auth returning owner, from 07-02)"
  - "common.authentication.CookieJWTAuthentication"
  - "interactions.entry.begin_interaction_run (token_hash fingerprint path)"
  - "07-01 RED test: tests/mcp_tools/test_mcp_auth_errors.py::test_missing_token_returns_error_code"
provides:
  - "Fail-closed McpToolView base: permission_classes = [IsAuthenticated], inherited by all 17 subclasses"
  - "Explicit authentication_classes = [AccessTokenAuthentication, CookieJWTAuthentication] (PAT first, Web JWT fallback)"
  - "Anonymous/invalid-token MCP request → 401 authentication_failed (no internal leak, no 403 downgrade)"
affects:
  - "MCP/tool HTTP entry is now an authenticated trust boundary (IDENT-03 complete)"
tech-stack:
  added: []
  patterns:
    - "Base-class permission/authentication declaration propagates to all subclasses (single point of control)"
    - "handle_exception hard-codes 401 for AuthenticationFailed/NotAuthenticated (immune to global 401→403 downgrade)"
key-files:
  created: []
  modified:
    - server/mcp_tools/views.py
decisions:
  - "Open Question 2 resolved: include CookieJWTAuthentication so Web-triggered MCP calls authenticate via cookie/Bearer JWT"
  - "_begin's request.auth-None guard kept as defense-in-depth; Web JWT path degrades token_hash to empty string (no error), PAT path preserves fingerprint (IDENT-04)"
  - "Scope discipline: only mcp_tools/views.py changed; runner/feishu/webhook/compat/subagent AllowAny entries untouched (independent trust boundaries)"
metrics:
  duration: 6
  completed: 2026-06-09
---

# Phase 7 Plan 3: MCP 入口 fail-closed Summary

Tightened the MCP/tool HTTP entry from fail-open to fail-closed in a single base-class edit: `McpToolView` now declares `permission_classes = [IsAuthenticated]` and `authentication_classes = [AccessTokenAuthentication, CookieJWTAuthentication]`, so all 17 subclasses (including `CreateMergeRequestView` via `SummarizeBranchView`) reject anonymous/invalid-token calls at the permission layer with `401 authentication_failed` — while valid PAT (owner identity from 07-02) reaches the business path and keeps the `token_hash` audit fingerprint (IDENT-04).

## What Was Built

One production file changed (no migration, zero new dependencies):

**`server/mcp_tools/views.py`** — three surgical edits:
- **Import swap**: `from rest_framework.permissions import AllowAny` → `IsAuthenticated`; added `from common.authentication import CookieJWTAuthentication` (placed in ruff import order between `codegraph.models` and `interactions.entry`). No leftover `AllowAny` reference remains in the file.
- **`McpToolView` base body**: `authentication_classes = [AccessTokenAuthentication, CookieJWTAuthentication]` (PAT first so `friday_pat_` Bearer hits the PAT class, Web JWT/cookie hits CookieJWT) and `permission_classes = [IsAuthenticated]` (IDENT-03 fail-closed).
- **Kept unchanged**: `handle_exception` (already maps `AuthenticationFailed`/`NotAuthenticated` → `error_response("authentication_failed", ..., 401)`, hard-coded 401 immune to the global 401→403 downgrade) and `_begin`'s `if request.auth is None:` defense-in-depth guard.

## Verification Results

| Suite | Result |
|-------|--------|
| `tests/mcp_tools -q` (Task 1) | **37 passed** — RED test `test_missing_token_returns_error_code` now GREEN (401 + authentication_failed); valid-PAT tests (`test_repository_not_found_error_code`, `test_repository_not_indexed_error_code`) stay GREEN |
| Full-phase gate: `test_pat_identity test_access_tokens test_auth test_auth_e2e test_interactions_ledger mcp_tools` | **86 passed** |

07-01's MCP fail-closed assertion converged to GREEN exactly as predicted; valid-PAT business paths and the interactions ledger audit chain are intact.

## Acceptance Criteria

- [x] `McpToolView.permission_classes == [IsAuthenticated]` and `authentication_classes == [AccessTokenAuthentication, CookieJWTAuthentication]`
- [x] No remaining `AllowAny` reference in `server/mcp_tools/views.py`
- [x] Anonymous MCP request → 401 `authentication_failed`
- [x] Valid-PAT MCP request reaches business path (owner satisfies IsAuthenticated)
- [x] No other view module modified

## Deviations from Plan

None — plan executed exactly as written.

## Threat Surface

No new security surface. Threat register dispositions hold:
- **T-07-09** (MCP fail-open → anonymous tool call) — mitigated: base `permission_classes = [IsAuthenticated]`; regression test asserts anonymous → 401.
- **T-07-10** (error response leaks internals) — mitigated: `handle_exception` returns generic `authentication_failed`/401, no internals.
- **T-07-11** (audit fingerprint lost) — mitigated: PAT path keeps `request.auth = AccessToken`; `begin_interaction_run` token_hash path unchanged (IDENT-04).
- **T-07-SC** (npm/pip installs) — N/A: pure code edit, zero new dependencies.

## Self-Check: PASSED
- FOUND: server/mcp_tools/views.py (modified — IsAuthenticated + CookieJWTAuthentication)
- FOUND commit 40498032 (Task 1)
