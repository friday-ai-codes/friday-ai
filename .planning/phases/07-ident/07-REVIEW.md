---
phase: 07-ident
reviewed: 2026-06-09T13:25:00Z
depth: deep
files_reviewed: 6
files_reviewed_list:
  - server/access_tokens/authentication.py
  - server/friday/settings.py
  - server/mcp_tools/views.py
  - server/tests/test_pat_identity.py
  - server/tests/test_access_tokens.py
  - server/tests/mcp_tools/test_mcp_auth_errors.py
findings:
  critical: 1
  warning: 2
  info: 1
  total: 4
status: clean
resolved_at: 2026-06-09T21:30:00Z
resolution:
  CR-01: resolved
  WR-01: resolved
  WR-02: resolved
  IN-01: acknowledged
---

# Phase 07 (令牌即用户身份/认证地基): Code Review Report

**Reviewed:** 2026-06-09T13:25:00Z
**Depth:** deep (cross-file: auth chain + DRF settings + MCP views + ledger entry + simplejwt)
**Files Reviewed:** 6
**Status:** clean (all findings resolved/acknowledged 2026-06-09)

> **Resolution (2026-06-09):** CR-01, WR-01, WR-02 fixed with atomic commits; IN-01
> acknowledged (no code change). Suite green:
> `tests/test_pat_identity.py tests/test_access_tokens.py tests/test_auth.py
> tests/test_auth_e2e.py tests/test_interactions_ledger.py tests/mcp_tools` → 88 passed.

## Summary

Phase 07 turns the Friday Access Token (PAT) into a real user identity: success now
returns `(token.created_by, token)`, a `friday_pat_` prefix gate routes JWT Bearer
through to `CookieJWTAuthentication`, `authenticate_header` preserves site-wide 401, and
`McpToolView` is fail-closed (`IsAuthenticated`). I traced the full DRF auth chain across
`access_tokens.authentication`, `friday/settings.py`, `mcp_tools/views.py`,
`interactions/entry.py`, `common/authentication.py`, and the installed `simplejwt`.

The core security contract holds well, with one important exception:

- **PAT/JWT coexistence is correct.** Non-`friday_pat_` Bearer → `return None` (falls
  through to JWT, never raises). A `friday_pat_`-prefixed but unknown/revoked/expired token
  → `raise AuthenticationFailed` (rejected, never silently passed to JWT). PAT-first
  ordering in `DEFAULT_AUTHENTICATION_CLASSES` is right.
- **Fail-closed is correct.** `McpToolView` base is `IsAuthenticated`; no subclass overrides
  `permission_classes` back to `AllowAny` (only one `permission_classes` declaration exists in
  `mcp_tools/`). `handle_exception` hard-codes 401, immune to 403 downgrade.
- **`authenticate_header`** returns `'Bearer realm="api"'` (non-None challenge), preventing the
  global 401→403 downgrade; it leaks no info.
- **Audit/scope.** `request.auth` remains the `AccessToken`; only `token_hash` fingerprints are
  logged, never plaintext. The `runner/feishu/webhook/compat/subagent` `AllowAny` entries were
  not modified.

The one real gap (BLOCKER below): the PAT path **does not check `created_by.is_active`**, so a
deactivated user's still-valid PAT keeps authenticating — asymmetric with the JWT path in the
same default auth chain, which *does* reject inactive users.

## Critical Issues

### CR-01: PAT authenticates a deactivated user — `created_by.is_active` is never checked

**Status:** ✅ RESOLVED — added an `is_active` gate in
`AccessTokenAuthentication.authenticate` right after the `is_valid` check and before
returning `(token.created_by, token)`. An inactive owner now triggers a best-effort
`reason="owner_inactive"` DENIED `InteractionRun` and `raise AuthenticationFailed`,
symmetric with the JWT path (simplejwt `CHECK_USER_IS_ACTIVE`). `created_by` is already
loaded via `select_related`, so no extra query/async issue. Regression tests added in
`server/tests/test_pat_identity.py` (`test_inactive_owner_pat_is_rejected` unit +
`test_inactive_owner_pat_rejected_through_chain` integration → 401).

**File:** `server/access_tokens/authentication.py:83-93`
**Issue:**
The success branch returns the owner unconditionally:

```83:93:server/access_tokens/authentication.py
        if not token.is_valid:
            # 存在但吊销/过期：可审计的「废 token 调用」，写 DENIED run（contract）。
            self._record_denial(
                request, fingerprint=token.token_hash, reason="revoked_or_expired"
            )
            raise AuthenticationFailed("Token 已吊销或已过期")

        # contract：有效即放行，不做任何 scope/项目/allowlist 校验（contract）。
        # request.user = 令牌所有者，享其本人 RBAC（IDENT-01）。
        self._touch_last_used(token)
        return (token.created_by, token)
```

`is_valid` only covers the token's own `revoked_at`/`expires_at` — it says nothing about the
*owner*. Because this is now the first global authenticator and `IsAuthenticated` only checks
`user.is_authenticated` (True for any `User`, regardless of `is_active`), a PAT whose owner has
been deactivated (`is_active=False`) continues to authenticate with that user's full RBAC.

This is a concrete bypass of the account-disable control (e.g. offboarding a departed/compromised
employee): disabling the account does **not** cut off their API access unless every PAT is also
individually revoked. It is also asymmetric within the same default auth chain — the JWT path
(`CookieJWTAuthentication` → simplejwt) *does* reject inactive users:

```138:139:server/.venv/lib/python3.14/site-packages/rest_framework_simplejwt/authentication.py
        if api_settings.CHECK_USER_IS_ACTIVE and not user.is_active:
            raise AuthenticationFailed(_("User is inactive"), code="user_inactive")
```

Given this is the auth foundation with high blast radius, the fail-closed behavior is to deny
inactive owners. (Note: the token owner being `staff`/`superuser` is by-design — token = owner
identity — so no escalation *beyond* the owner; the issue is purely the missing `is_active` gate.)

**Fix:** reject before returning the owner, mirroring the JWT path. Treat it as an auditable
denial for parity with `revoked_or_expired`:

```python
        if not token.created_by.is_active:
            # 所有者被停用：与 JWT 路径（simplejwt CHECK_USER_IS_ACTIVE）对齐，fail-closed。
            self._record_denial(
                request, fingerprint=token.token_hash, reason="owner_inactive"
            )
            raise AuthenticationFailed("令牌所有者已被停用")

        self._touch_last_used(token)
        return (token.created_by, token)
```

Add a regression test (none currently exists) asserting an inactive owner's valid PAT yields 401
through the full chain.

## Warnings

### WR-01: JWT-authenticated MCP requests record an empty audit `token_fingerprint`

**Status:** ✅ RESOLVED — `begin_interaction_run` now falls back to a stable, non-sensitive
`f"user:{request.user.id}"` fingerprint when `request.auth` has no `token_hash` (JWT path),
keeping the existing AccessToken `token_hash` behavior unchanged. No plaintext/raw JWT is
logged. Existing ledger tests stay green.

**File:** `server/interactions/entry.py:69` (triggered by `server/mcp_tools/views.py:145`,`159`)
**Issue:**
07-03 added `CookieJWTAuthentication` to `McpToolView.authentication_classes`, so MCP tools can
now be reached with a web JWT. `_begin` only guards `request.auth is None`, and for a
JWT-authenticated request `request.auth` is a simplejwt token, not an `AccessToken`:

```69:69:server/interactions/entry.py
    token_fingerprint = getattr(request.auth, "token_hash", "")
```

A simplejwt token has no `token_hash`, so every JWT-driven MCP `InteractionRun` is created with
`token_fingerprint=""`. This silently breaks audit continuity (the whole point of `request.auth`
fingerprinting) for the JWT path, and `X-Friday-Run-ID` reuse keys off an empty fingerprint. No
crash, no plaintext leak — but the audit trail is degraded exactly for interactive/web callers.

**Fix:** derive a stable, non-PAT fingerprint for JWT runs (e.g. `auth:user:<id>` or a hashed
`jti`) instead of `""`, or explicitly tag the run `source`/principal type so JWT-originated runs
are distinguishable rather than blank. Example:

```python
    token_fingerprint = getattr(request.auth, "token_hash", "") or (
        f"user:{request.user.id}" if getattr(request, "user", None)
        and request.user.is_authenticated else ""
    )
```

### WR-02: `_begin`'s `request.auth is None` 401 branch is now partly dead / inconsistent

**Status:** ✅ RESOLVED — kept the `request.auth is None` guard as defense-in-depth but
aligned its error code from `authentication_required` to `authentication_failed` (matching
`handle_exception`), so the "no usable token" contract is single-valued. Added a comment
documenting why the branch is retained. `test_missing_token_returns_error_code` stays green.

**File:** `server/mcp_tools/views.py:158-165`
**Issue:**
With the base now `IsAuthenticated`, an unauthenticated request is rejected at the permission
layer (returns 401 `authentication_failed` via `handle_exception`) before any `post()` runs, so
`_begin`'s `request.auth is None` → `authentication_required` branch is unreachable for the
anonymous case it was written for. It can still fire for an *authenticated-but-auth-is-None*
edge (not currently produced by either configured authenticator), yielding a second, divergent
error code (`authentication_required` vs. the canonical `authentication_failed`) for what is
conceptually the same "no usable token" condition. This is dead-ish code that can drift.

**Fix:** either drop the `request.auth is None` guard (rely on `IsAuthenticated`) or, if kept as
defense-in-depth, return the same `authentication_failed` code/shape used by `handle_exception`
so the contract stays single-valued.

## Info

### IN-01: Global PAT authenticator now runs on inherited-default `AllowAny` endpoints (benign, verify)

**Status:** ☑️ ACKNOWLEDGED (no code change) — verified `server/feishu/views.py` callbacks
authenticate via signature verification + decryption and a `webhook_token` param
(`verify_webhook_token`), **not** an `Authorization: Bearer` header. They never send a
`friday_pat_`-prefixed Bearer, so the new global PAT authenticator returns `None` for them
(no Bearer → `AnonymousUser` → `AllowAny` passes). The documented assumption holds; behavior
is unchanged for Feishu/webhook traffic.

**File:** `server/friday/settings.py:275-282`
**Issue:**
Adding `AccessTokenAuthentication` as the first `DEFAULT_AUTHENTICATION_CLASSES` entry means the
`AllowAny` endpoints that do **not** set their own `authentication_classes`
(`feishu/views.py:184,409,538`, `subagent/api/callbacks.py:363`, `workflows/api/views.py:1159`)
now execute the PAT authenticator on every request. Behavior is unchanged for normal traffic
(no `Authorization` header → `return None` → `AnonymousUser` → `AllowAny` passes), and a bad
Bearer already produced 401 via the previously-default `CookieJWTAuthentication`. The fully
isolated endpoints (`authentication_classes = []`: `accounts`, `compat`, runner register,
`repositories/index_views`) are unaffected. No action required, but worth confirming no Feishu/
webhook caller sends a `friday_pat_`-prefixed Bearer (it would now 401 instead of being treated
as anonymous).

---

_Reviewed: 2026-06-09T13:25:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
