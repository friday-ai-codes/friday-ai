---
phase: 01-auditevent-emit
plan: 01-02
subsystem: audit
tags: [emit, middleware, contextvars, actor, best-effort, test]
requires: [AUDIT-02, AUDIT-03]
provides: [emit_audit_event, aemit_audit_event, AuditContextMiddleware, AuditActor]
affects: [friday/settings.py, audit/__init__.py]
tech_stack:
  added: [audit.context, audit.middleware, audit.emitter]
  patterns: [contextvars, ASGI middleware, sync/async dual entry, best-effort degradation]
key_files:
  created:
    - server/audit/context.py
    - server/audit/middleware.py
    - server/audit/emitter.py
    - server/tests/audit/test_audit_emit.py
  modified:
    - server/friday/settings.py
    - server/audit/__init__.py
decisions:
  - "AuditActor as frozen dataclass with contextvars for request-scoped actor propagation"
  - "ASGI middleware follows (app)->async __call__ pattern consistent with runners/middleware.py and core/middleware.py"
  - "emit uses best-effort pattern from interactions/ledger.py: DB failure -> structlog warning -> return None"
  - "source auto-inferred: API if request_id present, SYSTEM otherwise"
  - "middleware placed after AuthenticationMiddleware in MIDDLEWARE list to ensure scope['user'] is populated"
metrics:
  duration: 322s
  completed: "2026-06-15T11:38:13Z"
  tasks_completed: 2
  tasks_total: 2
  files_created: 4
  files_modified: 2
  tests_added: 17
---

# Phase 01 Plan 01-02: Audit Event Emit + Actor Context Summary

emit_audit_event() sync/async dual entry with contextvars-based actor extraction middleware and best-effort DB write degradation.

## What Was Built

- **`audit/context.py`** — `AuditActor` frozen dataclass + `contextvars.ContextVar` for request-scoped actor propagation (`set_current_actor`, `get_current_actor`, `reset_current_actor`). Thread/coroutine-safe.
- **`audit/middleware.py`** — `AuditContextMiddleware` ASGI middleware extracts actor from HTTP scope: JWT (scope["user"] authenticated) -> user, PAT (scope["auth"] has token_hash) -> pat, unauthenticated -> system/anonymous. Extracts IP from scope["client"] and request_id from x-request-id header. Cleans up contextvar in finally block.
- **`audit/emitter.py`** — `emit_audit_event()` synchronous entry and `aemit_audit_event()` async wrapper (sync_to_async bridge, following interactions/ledger.py pattern). Best-effort: DB write failure degrades to structlog warning, returns None. Actor priority: explicit params > contextvars > system default.
- **`settings.py`** — Registered `audit.middleware.AuditContextMiddleware` after `AuthenticationMiddleware` in MIDDLEWARE list.
- **17 tests** covering: contextvars get/set/reset, frozen dataclass, middleware JWT/PAT/anonymous extraction, middleware cleanup on exception, non-HTTP scope skip, x-request-id extraction, emit sync success, emit async success, contextvars auto-injection, explicit actor override, DB error degradation, before/after defaults, source inference.

## Decisions Made

1. **AuditActor as frozen dataclass** — immutable value object prevents accidental mutation of actor context between middleware set and emit read
2. **contextvars over threading.local** — correct for async (coroutine isolation), works for threads too; standard library with no dependencies
3. **Middleware only processes HTTP scope** — WebSocket and lifespan events skip actor extraction; aligns with REST audit focus
4. **PAT detection via hasattr(auth, "token_hash")** — duck-typing avoids import coupling to access_tokens app; middleware stays loosely coupled
5. **source auto-inference from request_id** — API requests carry x-request-id header; absence implies system/scheduler origin

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test assertion for PAT actor auto-read**
- **Found during:** Task 2 test run
- **Issue:** Test used `event.actor_id_field` which doesn't exist on AuditEvent model (model has no actor_id field, only actor_type and actor_display)
- **Fix:** Changed assertion to `event.actor_display == "cli-token"` to match actual model fields
- **Files modified:** server/tests/audit/test_audit_emit.py
- **Commit:** cb637f41

## Known Stubs

None — all modules are fully functional.

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| threat_flag: actor_extraction | audit/middleware.py | Middleware extracts actor from scope populated by AuthenticationMiddleware; trust boundary: only safe if middleware order is maintained (T-01-05 mitigated by placing after AuthenticationMiddleware) |
| threat_flag: actor_override | audit/emitter.py | Explicit actor_type/actor_id params allow caller to set arbitrary actor; accepted risk (T-01-06) — used only for system operations like management commands |

## Self-Check: PASSED

- [x] server/audit/context.py exists and exports AuditActor, set_current_actor, get_current_actor, reset_current_actor
- [x] server/audit/middleware.py exists and implements AuditContextMiddleware
- [x] server/audit/emitter.py exists and exports emit_audit_event, aemit_audit_event
- [x] server/tests/audit/test_audit_emit.py exists with 17 tests
- [x] Commit 98a20571 exists (Task 1: contextvars + middleware + settings)
- [x] Commit cb637f41 exists (Task 2: emitter + tests)
- [x] All 23 audit tests pass (17 new + 6 existing)
- [x] `python manage.py check` reports no issues
