---
phase: 07-ident
plan: 02
subsystem: backend-auth-core
tags: [auth, pat, jwt, identity, prefix-gate, authenticate-header, settings-ordering]
requires:
  - "access_tokens.models (PAT_PREFIX, AccessToken.created_by, is_valid)"
  - "common.authentication.CookieJWTAuthentication"
  - "07-01 RED tests (test_pat_identity.py, test_access_tokens.py owner assertion)"
provides:
  - "PAT auth returns owner identity: (token.created_by, token); request.user is owner User, request.auth is AccessToken"
  - "friday_pat_ prefix gate: non-PAT Bearer returns None (passthrough to CookieJWT, never raises)"
  - "authenticate_header 'Bearer realm=\"api\"' keeps site-wide unauthenticated responses at 401 (no 403 downgrade)"
  - "DEFAULT_AUTHENTICATION_CLASSES PAT-first ordering"
affects:
  - "07-03 (MCP IsAuthenticated tightening) — owner identity + ordering now real; MCP fail-closed test still RED until 07-03"
tech-stack:
  added: []
  patterns:
    - "DRF BaseAuthentication: prefix gate (return None) for credential-type routing across stacked auth classes"
    - "authenticate_header on first global auth class to preserve 401 challenge semantics"
    - "select_related on FK in synchronous auth stage to avoid N+1"
key-files:
  created: []
  modified:
    - server/access_tokens/authentication.py
    - server/friday/settings.py
decisions:
  - "PAT class first in DEFAULT_AUTHENTICATION_CLASSES; prefix gate (not raising) is what makes PAT/JWT coexistence safe"
  - "authenticate_header returns 'Bearer realm=\"api\"' — mandatory to ship with reordering or 401 silently downgrades to 403"
  - "TYPE_CHECKING import of accounts.models.User for the return type hint; no runtime import added"
metrics:
  duration: 8
  completed: 2026-06-09
---

# Phase 7 Plan 2: PAT 认证地基核心改造 Summary

Made "令牌即用户身份" the authenticated reality: a valid `friday_pat_` token now authenticates as its owner (`request.user == token.created_by`, owner RBAC), the `friday_pat_` prefix gate lets non-PAT Bearer pass through to JWT untouched, `authenticate_header` preserves site-wide 401, and `DEFAULT_AUTHENTICATION_CLASSES` is reordered PAT-first — all in a single atomic plan so the global auth change never lands without its 401-preserving counterpart.

## What Was Built

Two production files changed, shipped together (no migration, zero new dependencies):

1. **`server/access_tokens/authentication.py`** — four surgical edits to `AccessTokenAuthentication`:
   - **Import**: `from .models import PAT_PREFIX, AccessToken` (constant reused, not hard-coded); `TYPE_CHECKING` import of `accounts.models.User` for the return hint.
   - **Prefix gate** (after the empty-string `return None`): `if not plaintext.startswith(PAT_PREFIX): return None` — non-PAT Bearer (e.g. JWT) falls through to `CookieJWTAuthentication`, never raises (Pitfall 1).
   - **Owner pre-fetch**: lookup changed to `AccessToken.objects.select_related("created_by").get(token_hash=fingerprint)` (Pitfall 4 — avoids N+1 in the synchronous auth stage).
   - **Success branch**: `return (None, token)` → `return (token.created_by, token)` (IDENT-01); `_touch_last_used` still runs before the return.
   - **New method** `authenticate_header(self, request) -> str: return 'Bearer realm="api"'` (Pitfall 2 — first global auth class must give a non-None challenge to keep 401).
   - Docstrings (module + class) and the `authenticate` return hint updated to describe the `(owner, token)` contract. `_record_denial`, `_touch_last_used`, the `DoesNotExist` branch, and the `is_valid` denial branch are **untouched** (IDENT-04/05 unchanged).

2. **`server/friday/settings.py`** — `REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"]` set to `["access_tokens.authentication.AccessTokenAuthentication", "common.authentication.CookieJWTAuthentication"]` (PAT first), with a Chinese comment explaining why CookieJWT cannot be first (Pitfall 1). Permissions, schema, exception handler, throttle rates unchanged.

## Verification Results

| Suite | Result |
|-------|--------|
| `tests/test_access_tokens.py` + `tests/test_pat_identity.py` (Task 1) | 13 passed; integration `test_pat_authenticates_protected_endpoint_as_owner` RED until Task 2 (expected — needs settings ordering) |
| `tests/test_auth.py` + `tests/test_auth_e2e.py` + `tests/test_pat_identity.py` (Task 2) | 34 passed — 401 preserved (no 403 downgrade), integration PAT test now GREEN |
| Full regression: `test_pat_identity test_access_tokens test_auth test_auth_e2e test_interactions_ledger` | **49 passed** |
| `manage.py makemigrations --check --dry-run` | No changes detected |

07-01's `test_valid_token_passes` (owner) and all `test_pat_identity.py` owner/passthrough/coexistence/revoked assertions are GREEN. `test_access_tokens::test_revoked_expired_denied_and_logged` (IDENT-05) stays GREEN. The MCP fail-closed test (`test_mcp_auth_errors`) remains RED by design until 07-03.

## Deviations from Plan

None — plan executed exactly as written.

## Threat Surface

No new security surface. Threat register dispositions hold:
- **T-07-04** (ordering swallows credential) — mitigated: PAT-first + prefix gate returns None; coexistence tests GREEN.
- **T-07-05** (401→403 downgrade) — mitigated: `authenticate_header` returns the Bearer challenge; `test_auth`/`test_auth_e2e` 401 assertions GREEN.
- **T-07-06** (revoked token reused) — mitigated: `is_valid` + DENIED run + `AuthenticationFailed` retained unchanged.
- **T-07-07** (audit chain break) — mitigated: `request.auth` stays the `AccessToken`; `token_hash` fingerprint path untouched.
- **T-07-08** (owner over-privilege) — accepted: owner gets only own RBAC; cross-resource isolation is Phase 8.

## Self-Check: PASSED
- FOUND: server/access_tokens/authentication.py (modified — `authenticate_header`, `PAT_PREFIX` gate, owner return)
- FOUND: server/friday/settings.py (modified — PAT-first ordering)
- FOUND commit f37106cc (Task 1)
- FOUND commit bfd5e5e5 (Task 2)
