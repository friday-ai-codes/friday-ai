---
phase: 10-mcpb
reviewed: 2026-06-10T01:15:00Z
depth: deep
files_reviewed: 13
files_reviewed_list:
  - server/tools/models.py
  - server/tools/migrations/0003_tooltokenbinding.py
  - server/tools/serializers.py
  - server/tools/views.py
  - server/tools/urls.py
  - server/friday/urls.py
  - web/src/api/toolBindings.ts
  - web/src/stores/toolBindings.ts
  - web/src/types/toolBinding.ts
  - web/src/components/toolBindings/ToolBindDialog.vue
  - web/src/components/toolBindings/ToolBindingTable.vue
  - web/src/components/toolBindings/ToolBindingSettings.vue
  - web/src/pages/profile.vue
findings:
  critical: 0
  warning: 4
  info: 2
  total: 6
status: clean
resolution:
  resolved_at: 2026-06-10T01:30:00Z
  fixed: [WR-02, WR-03, WR-04]
  acknowledged: [WR-01, IN-01, IN-02]
  actionable_remaining: 0
---

# Phase 10: Code Review Report

**Reviewed:** 2026-06-10T01:15:00Z
**Depth:** deep (cross-file: auth → executor → ledger traced)
**Files Reviewed:** 13
**Status:** clean — all actionable findings resolved (WR-02/03/04 fixed; WR-01 + INFO acknowledged)

## Resolution Log (2026-06-10)

- **WR-04 — FIXED** (`d9356a93`): `validate_access_token` now enforces
  `value.is_valid` alongside ownership; binding a revoked/expired token returns
  400 server-side. Test: `test_bind_revoked_token_rejected`.
- **WR-03 — FIXED** (`1d7bf133`): `acreate` upsert now catches `IntegrityError`
  on the `unique_together` race and converges to updating the existing binding's
  token instead of 500. Test: `test_upsert_integrity_error_resolves_to_update`.
- **WR-02 — FIXED** (`cbef7019`): `RemoteToolExecuteView.post` now records a
  (redacted) tool-call and transitions the run to a terminal status (COMPLETED on
  ok, ERROR otherwise) with `completed_at`, mirroring `McpToolView`. Tests:
  `test_execute_finalizes_run`, `test_execute_error_finalizes_run_error`.
- **WR-01 — ACKNOWLEDGED (intentional Phase 11 deferral):** No per-tool
  authorization at execute time; bindings are advisory metadata in the shipped
  state. This is the CONTEXT-locked decision — "端点按 PAT 认证可执行任意 active
  工具；绑定强校验/令牌注入在 Phase 11"。Enforcement (consult binding table, deny
  `builtin`/unbound) is deferred to Phase 11, not a Phase 10 defect.
- **IN-01 — ACKNOWLEDGED:** Upsert returns 201 on rebind (vs 200). Cosmetic
  REST-correctness only; frontend handles both idempotently. Left as-is.
- **IN-02 — ACKNOWLEDGED:** Binding CRUD inherits global PAT+CookieJWT auth.
  Intentional (PAT == owner identity; `get_queryset` scopes to `request.user`, no
  IDOR). Left as-is.

## Summary

Phase 10 (MCP 绑定用户令牌 + RemoteTool 执行端点) was reviewed adversarially with
focus on the three high-risk axes called out in scope: **secret handling**,
**binding ownership / IDOR**, and **execute-endpoint authentication**.

**All three critical security axes PASS — no BLOCKER findings.**

- **No token leak.** Every output serializer is a strict field whitelist.
  `BoundTokenSerializer` exposes only `id / name / token_prefix / token_suffix /
  is_valid`; `token_hash` and plaintext are never referenced in any serializer,
  view, or log. The execute endpoint never echoes the PAT (the PAT lives in the
  `Authorization` header, not the serialized body; the audit run stores
  `token_hash` as fingerprint only, and `acreate_interaction_run` redacts
  `raw_request`).
- **No binding IDOR.** `validate_access_token` rejects cross-user token refs
  (`created_by_id != request.user.id` → 400). `get_queryset` scopes list/delete to
  `request.user` (cross-user delete → 404, no existence leak). `aupdate_or_create`
  is keyed on `user=request.user`, so a caller cannot upsert another user's binding.
- **No execute auth bypass.** `RemoteToolExecuteView` overrides
  `authentication_classes = [AccessTokenAuthentication]` (PAT-only) + `IsAuthenticated`,
  and `handle_exception` maps `NotAuthenticated/AuthenticationFailed → 401`
  (fail-closed, not 403). A browser CookieJWT caller cannot reach it (JWT cookie is
  not a `friday_pat_` Bearer, so the authenticator returns `None` → 401). Revoked /
  expired / inactive-owner PATs are rejected at the authentication layer → 401.

The remaining findings are quality / robustness / observability concerns. The most
notable (WR-01, WR-02) are **documented, intentional Phase 11 deferrals** but are
reported here because they exist in shipped code and have real access-control /
audit implications.

## Warnings

### WR-01: Execute endpoint performs NO per-tool authorization — any valid PAT can execute ANY active tool by name

**Status: ACKNOWLEDGED — intentional Phase 11 deferral (CONTEXT-locked).** See Resolution Log.

**File:** `server/tools/views.py:112-122`
**Issue:** `RemoteToolExecuteView.post` calls `execute_tool(name, arguments)` with
no check that (a) the authenticated owner actually has a `ToolTokenBinding` for that
tool, or (b) the tool source is restricted to `mcp/skill`. Any holder of *any* valid
PAT can therefore invoke *any* `is_active` `RemoteTool` by name — including `builtin`
tools, which `BindableToolsView` deliberately excludes from the bindable set. The
binding table (the entire point of this phase) is **not consulted** at execution
time, so binding/unbinding has no effect on what a PAT can run today. This widens the
reachable surface to the `mcp` command dispatch (`execute_mcp` → `CommandNotAllowedError`
implies a command-execution path) and `skill` orchestration for every token holder.

This is documented as a Phase 11 gap (view comment: "不传 user（Phase 11 gap，per
RESEARCH Open Q1）") and the SSRF/command-injection surface in `_dispatch` is
pre-existing. It is reported as a WARNING (not BLOCKER) because it is an intentional,
documented deferral — but reviewers/operators must understand that **in the shipped
state, bindings are advisory metadata, not an authorization boundary.**

**Fix:** Before Phase 11 ships, enforce authorization at execute time, e.g.:
```python
binding = await ToolTokenBinding.objects.filter(
    user=request.user,
    remote_tool__name=serializer.validated_data["name"],
    remote_tool__source__in=[RemoteTool.Source.MCP, RemoteTool.Source.SKILL],
    remote_tool__is_active=True,
).select_related("remote_tool").afirst()
if binding is None:
    return Response(
        {"ok": False, "error": {"code": "forbidden", "message": "无绑定或工具不可执行"}},
        status=status.HTTP_403_FORBIDDEN,
    )
```
If deferral is truly intended, gate the endpoint (feature flag / deny `builtin`) so a
PAT cannot reach unbound or `builtin` tools in the interim.

### WR-02: Audit InteractionRun created by execute endpoint is never finalized (dangling RUNNING, no tool-call/result events)

**Status: FIXED** (`cbef7019`). See Resolution Log.

**File:** `server/tools/views.py:116`
**Issue:** `begin_interaction_run(request, source="tool")` creates a top-level
`InteractionRun` with `status = RUNNING` (`acreate_interaction_run` default,
`interactions/ledger.py:215`). The view then discards the returned run, calls
`execute_tool`, and returns — it never records a tool-call, never attaches the
result/error, and never transitions the run out of `RUNNING`. Unlike the mirror
`McpToolView`, which records the tool call via `arecord_tool_call` and finalizes the
run, this endpoint leaves **one perpetually-RUNNING run per execution with no
result/error event**. The audit trail (the stated purpose of `begin_interaction_run`)
is therefore incomplete, and the `X-Friday-Run-ID` reuse lookup (which filters on
`status=RUNNING`) will match stale never-closed runs.

**Fix:** Record the tool call and finalize the run, mirroring `McpToolView._record`,
e.g. capture `started_at = time.perf_counter()`, then after `execute_tool` call
`arecord_tool_call(run, tool_name=name, input_data=arguments, output_data=result,
call_status="ok" if result.get("ok") else "error", ...)` and mark the run
complete/failed accordingly.

### WR-03: `aupdate_or_create` can raise IntegrityError (→ 500) under concurrent upsert

**Status: FIXED** (`1d7bf133`). See Resolution Log.

**File:** `server/tools/views.py:60-64`
**Issue:** `aupdate_or_create` does a `get` then `create`; it does not retry on
`IntegrityError`. Two concurrent POSTs for the same `(user, remote_tool)` (e.g. a
double-click / retried request) can both miss the `get` and race the `create`,
violating `unique_together` and surfacing as an unhandled 500 rather than a clean
upsert. Low probability for this UI flow, but the docstring explicitly claims upsert
"不撞 unique_together 抛 500", which is not guaranteed.

**Fix:** Wrap the upsert and translate the collision into a retry or a 409/200, e.g.:
```python
try:
    binding, _ = await ToolTokenBinding.objects.aupdate_or_create(...)
except IntegrityError:
    binding = await ToolTokenBinding.objects.aget(user=request.user,
                                                  remote_tool=serializer.validated_data["remote_tool"])
    binding.access_token = serializer.validated_data["access_token"]
    await binding.asave(update_fields=["access_token", "updated_at"])
```

### WR-04: Binding accepts a revoked/expired access_token (validity not enforced server-side)

**Status: FIXED** (`d9356a93`). See Resolution Log.

**File:** `server/tools/serializers.py:61-72`
**Issue:** `validate_access_token` checks ownership only; it does not check
`value.is_valid`. `validate_remote_tool` checks tool `is_active` but nothing checks
token validity. A direct API caller (bypassing the UI) can therefore create a binding
to an already-revoked/expired token. The binding is silently useless (execution later
401s at auth time), and validity is enforced **only** in the frontend
(`ToolBindDialog` filters `is_valid`), making this a client-side-only guard. The
RESEARCH note ("Pitfall 5: 绝不让用户绑到已吊销/过期令牌") is only honored in the UI.

**Fix:** Enforce in the serializer to match the documented intent:
```python
def validate_access_token(self, value: AccessToken) -> AccessToken:
    request = self.context["request"]
    if value.created_by_id != request.user.id:
        raise serializers.ValidationError("无法引用他人的 Access Token。")
    if not value.is_valid:
        raise serializers.ValidationError("令牌已吊销或已过期，无法绑定。")
    return value
```

## Info

### IN-01: Upsert returns `201 Created` even when it performs an update (换绑)

**Status: ACKNOWLEDGED — cosmetic, left as-is.** See Resolution Log.

**File:** `server/tools/views.py:71-73`
**Issue:** `acreate` always returns `HTTP_201_CREATED`, but `aupdate_or_create` also
covers the rebind/update path (`_created` is discarded). Re-binding an existing tool
to a new token returns 201 rather than the semantically correct 200. Cosmetic /
REST-correctness only; the frontend store handles both cases idempotently.
**Fix:** Use the `_created` flag: `status.HTTP_201_CREATED if _created else status.HTTP_200_OK`.

### IN-02: Binding CRUD views inherit global auth (PAT + CookieJWT), unlike the PAT-only execute endpoint

**Status: ACKNOWLEDGED — intentional, left as-is.** See Resolution Log.

**File:** `server/tools/views.py:36-50, 76-89`
**Issue:** `ToolTokenBindingViewSet` and `BindableToolsView` do not override
`authentication_classes`, so they inherit the global default
(`AccessTokenAuthentication` + `CookieJWTAuthentication`,
`server/friday/settings.py:277-280`). This means a container/PAT can list/create/delete
its own bindings, not just the browser. This appears intentional (PAT == owner
identity, and `get_queryset` still scopes to `request.user`), so there is no IDOR — but
it is worth recording that "binding CRUD is browser-only" is not actually enforced.
**Fix:** None required if intentional; otherwise restrict to `[CookieJWTAuthentication]`
to match the "browser does binding, container does execute" split implied by the docs.

---

_Reviewed: 2026-06-10T01:15:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
