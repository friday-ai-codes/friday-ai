---
phase: 06-pat
reviewed: 2026-06-09T19:53:00Z
depth: deep
files_reviewed: 11
files_reviewed_list:
  - server/access_tokens/models.py
  - server/access_tokens/migrations/0002_accesstoken_note_accesstoken_token_suffix.py
  - server/access_tokens/serializers.py
  - server/access_tokens/views.py
  - web/src/types/accessToken.ts
  - web/src/components/accessTokens/AccessTokenForm.vue
  - web/src/components/accessTokens/AccessTokenListTable.vue
  - server/tests/test_access_tokens.py
  - server/tests/conftest.py
  - web/src/components/accessTokens/__tests__/AccessTokenListTable.spec.ts
  - web/src/components/accessTokens/__tests__/AccessTokenSettings.spec.ts
findings:
  critical: 0
  warning: 2
  info: 2
  total: 4
status: clean
resolved:
  - WR-01
  - WR-02
acknowledged:
  - IN-01
  - IN-02
---

# Phase 06 (PAT 模型增强与一次性明文): Code Review Report

**Reviewed:** 2026-06-09T19:53:00Z
**Depth:** deep
**Files Reviewed:** 11
**Status:** clean (both warnings resolved; 2 info acknowledged, no action)

## Summary

Phase 06 adds `note` + `token_suffix` to `AccessToken` and surfaces a `prefix…suffix`
fingerprint plus a note column/input in the web UI. The security contract is upheld
across every checked surface:

- **Plaintext never persisted / leaked.** `acreate` derives `token_hash=hash_token(plaintext)`,
  `token_prefix=plaintext[:12]`, `token_suffix=plaintext[-4:]`, and returns the plaintext only
  once in the create response (`response_data["token"]`). The suffix exposes exactly 4 chars
  (`models.py:47`, asserted `len <= 4` in `test_access_tokens.py:40`); combined with the 1
  random char in the 12-char prefix, only ~5 of the ~43-char high-entropy body is ever shown —
  no meaningful entropy loss, no path to reconstruct the token.
- **`read_only_fields = fields` not weakened.** Both new fields are output-only on
  `AccessTokenSerializer`; the write path (`AccessTokenCreateSerializer`) accepts only
  `name`/`note`/`expires_at` and explicitly refuses `token_suffix` (server-derived). Verified the
  serializer instantiates cleanly despite `is_valid` being a declared field listed in
  `read_only_fields` — all 7 backend tests pass.
- **Unsalted sha256 + unique index intact.** `runners.models.hash_token` (plain
  `hashlib.sha256(...).hexdigest()`) is reused unchanged; `token_hash` keeps `unique=True,
  db_index=True`. No Argon2/salt drift.
- **Owner isolation + soft-revoke intact.** `get_queryset` filters `created_by=request.user`;
  `revoke` resolves via `aget_object()` (scoped by `get_queryset`), so cross-user revoke is
  structurally impossible; revoke is a soft `revoked_at` write. Cross-user isolation test passes.
- **Stored-XSS safe.** `note` and `name` render exclusively via Vue text interpolation
  (`{{ t.note }}`, `{{ t.name }}`) — no `v-html`. The fingerprint string is also interpolated.
- **adrf / async correct.** `acreate`/`revoke` serialize in-memory instances only (no lazy FK or
  async ORM access during serialization); `is_valid` uses local fields. ruff line-length ≤ 100;
  Chinese-comment convention followed.

All 7 backend tests (`tests/test_access_tokens.py`) and all 11 frontend tests
(`components/accessTokens/__tests__/*`) pass. Findings below are non-blocking robustness/UX issues.

## Warnings

### WR-01: `revoke` overwrites the original `revoked_at` on re-revoke (audit integrity) — medium

**Status:** ✅ Resolved (commit `5030c87f`) — `revoke` now guards on `token.revoked_at is None`,
so a re-revoke preserves the first revocation timestamp and still returns 200. Covered by
`test_revoke_is_idempotent_preserves_original_timestamp` in `server/tests/test_access_tokens.py`
(8/8 backend tests pass).

**File:** `server/access_tokens/views.py:76-82`
**Issue:** The `revoke` action unconditionally sets `revoked_at = timezone.now()`. Posting
`revoke` against an already-revoked token silently overwrites the original revocation timestamp,
losing the audit record of when the token was first revoked. There is no guard and no idempotency.
**Fix:**
```python
@action(detail=True, methods=["post"])
async def revoke(self, request: Request, pk: str | None = None) -> Response:
    token = await self.aget_object()
    if token.revoked_at is None:  # 已吊销则保留首次吊销时间戳，吊销操作幂等
        token.revoked_at = timezone.now()
        await token.asave(update_fields=["revoked_at"])
    return Response(AccessTokenSerializer(token).data)
```

### WR-02: Custom expiry date parsed as UTC midnight → expires early in local time — medium

**Status:** ✅ Resolved (commit `b865cd3b`) — the custom-date strategy now builds the expiry at
local end-of-day (`new Date(`${customDate.value}T23:59:59.999`).toISOString()`), so the token
stays valid through the user's chosen calendar date in positive-offset timezones. Covered by
`custom_expiry_uses_end_of_local_day` in `AccessTokenSettings.spec.ts` (12/12 frontend tests pass;
`vue-tsc --noEmit` clean).

**File:** `web/src/components/accessTokens/AccessTokenForm.vue:88`
**Issue:** `<input type="date">` yields a bare `"YYYY-MM-DD"` string. `new Date("2026-12-31").toISOString()`
interprets it as **UTC** midnight, so for a UTC+8 user a token chosen to expire on Dec 31 actually
expires at 08:00 local on Dec 31 — up to a full day earlier than the user's intent at date
boundaries. The displayed expiry in the list (`toLocaleString('zh-CN')`) will also not match the
picked day.
**Fix:** Construct the date in local time (or pin to end-of-day) before converting, e.g.
```ts
// 选中本地日期当天结束（23:59:59 本地）再转 ISO，避免 UTC 解析提前过期
payload.expires_at = new Date(`${customDate.value}T23:59:59`).toISOString()
```

## Info

### IN-01: Submit validation bypasses vee-validate `handleSubmit` (schema-coupling) — low

**Status:** ⏸️ Acknowledged — accepted, no action. No behavioral bug today (single
`accessTokenSchema` source of truth already in place); residual concern is maintainability only.

**File:** `web/src/components/accessTokens/AccessTokenForm.vue:64-71`
**Issue:** The deviation to synchronous `accessTokenSchema.safeParse(values)` works correctly and
is well-justified for test determinism. Field-level error display remains correct: the same
`accessTokenSchema` drives both vee-validate's `validationSchema` (live `FormMessage`) and the
manual `setErrors` on submit, and both `name` (max 200) and `note` (max 500) limits are enforced
client-side (zod) and server-side (`AccessTokenCreateSerializer` `CharField(max_length=...)`).
The only residual risk is maintainability: validation now lives in two code paths bound to one
schema — if a future edit changes `formSchema` without updating the manual `safeParse` (or vice
versa) the gates desync. No behavioral bug today.
**Fix:** Keep the single `accessTokenSchema` source of truth (already done); add a brief comment
warning future editors that both `formSchema` and `onSubmit` consume it, or add a test asserting a
too-long `note` blocks submit to lock the coupling.

### IN-02: `token_hash` unique collision not handled in `acreate` — low

**Status:** ⏸️ Acknowledged — accepted, no action. Collision probability is effectively zero
(256-bit `secrets.token_urlsafe(32)` body); informational only.

**File:** `server/access_tokens/views.py:60-69`
**Issue:** A sha256 collision on `token_hash` (or an astronomically improbable duplicate
`generate_pat()` output) would surface as an unhandled `IntegrityError` → HTTP 500 rather than a
graceful retry/4xx. Probability is effectively zero (256-bit `secrets.token_urlsafe(32)` body), so
this is informational only.
**Fix:** Optional — none required given the entropy. If desired, wrap `acreate` in a single
regenerate-and-retry on `IntegrityError`.

---

_Reviewed: 2026-06-09T19:53:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
