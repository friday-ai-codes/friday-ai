---
phase: 01-auditevent-emit
plan: 01-03
subsystem: audit
tags: [rest-api, serializer, pagination, filters, search, wsgi-compat]
requires:
  - phase: 01-auditevent-emit/01-01
    provides: [AuditEvent model]
  - phase: 01-auditevent-emit/01-02
    provides: [emit_audit_event, AuditContextMiddleware]
provides:
  - audit REST API (list/detail) for admin queries
  - WSGI/ASGI dual-mode middleware compatibility
affects: [03-audit-ui]
tech_stack:
  added: [audit.api]
  patterns: [DRF ListAPIView + PageNumberPagination, manual get_queryset filtering, WSGI/ASGI dual-mode middleware]
key_files:
  created:
    - server/audit/api/__init__.py
    - server/audit/api/serializers.py
    - server/audit/api/views.py
    - server/audit/api/urls.py
    - server/tests/audit/test_api.py
  modified:
    - server/friday/urls.py
    - server/audit/middleware.py
decisions:
  - "Use rest_framework.generics (not adrf) for read-only views -- avoids async queryset issues with sync DRF test client"
  - "Manual get_queryset filtering for action/source/target_type/actor instead of django-filter (not installed)"
  - "Explicit SearchFilter + OrderingFilter backends since DEFAULT_FILTER_BACKENDS not configured in project"
  - "Custom _AuditPagination subclass with page_size=20 since PAGE_SIZE not in DRF settings"
  - "WSGI/ASGI dual-mode middleware: sync __call__ dispatches to _asgi_call (3 args) or _wsgi_call (1 arg)"
requirements_completed: [AUDIT-04]
metrics:
  duration: 3min
  completed: "2026-06-15T12:08:29Z"
  tasks_completed: 2
  tasks_total: 2
  files_created: 5
  files_modified: 2
  tests_added: 10
---

# Phase 01 Plan 01-03: 只读 REST API (list/detail) + append-only 守护 Summary

DRF read-only audit event API with list/detail endpoints, manual filtering, search, pagination, and WSGI/ASGI dual-mode middleware fix for test compatibility.

## Performance

- **Duration:** ~3 min
- **Started:** 2026-06-15T11:40:10Z
- **Completed:** 2026-06-15T12:08:29Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments

- Read-only REST API for audit events with superuser-only access (list + detail endpoints)
- Manual filtering by action, source, target_type, actor query params
- SearchFilter on actor_display, action, target_id; OrderingFilter on timestamp, action
- Paginated responses via PageNumberPagination (page_size=20)
- 10 API tests covering auth, permissions, filtering, search, pagination, 405 mutation guard
- Fixed AuditContextMiddleware for WSGI/ASGI dual-mode compatibility with Django test client

## Task Commits

1. **Task 1: REST API views + URL registration** - `d3c1d074` (feat)
2. **Task 2: API tests + middleware WSGI fix** - `12a22729` (test)

## Files Created/Modified

- `server/audit/api/__init__.py` - API package init
- `server/audit/api/serializers.py` - AuditEventSerializer (all fields read-only)
- `server/audit/api/views.py` - AuditEventListView + AuditEventDetailView
- `server/audit/api/urls.py` - URL patterns for audit-events/
- `server/friday/urls.py` - Registered audit API under /api/
- `server/audit/middleware.py` - WSGI/ASGI dual-mode dispatch fix
- `server/tests/audit/test_api.py` - 10 API test cases

## Decisions Made

1. **rest_framework.generics over adrf.generics** -- adrf.ListAPIView causes sync test client to hang on async queryset evaluation; DRF standard generics work correctly for read-only views
2. **Manual get_queryset filtering** -- django-filter is not installed in the project; manual filter loop over query_params is simpler and has no external dependency
3. **Explicit SearchFilter + OrderingFilter backends** -- project has no DEFAULT_FILTER_BACKENDS configured; must be set on view
4. **Custom _AuditPagination with page_size=20** -- DRF PAGE_SIZE not in settings; PageNumberPagination.page_size defaults to api_settings.PAGE_SIZE which is None
5. **WSGI/ASGI dual-mode middleware** -- sync `__call__` dispatches by arg count: 3 args -> ASGI path (async), 1 arg -> WSGI path (sync). Avoids coroutine return in WSGI chain.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] AuditContextMiddleware incompatible with WSGI test client**
- **Found during:** Task 2 (API tests)
- **Issue:** ASGI middleware `__call__(scope, receive, send)` was called by Django's WSGI test client as `__call__(request)`, causing `TypeError: missing 2 required positional arguments`
- **Fix:** Made `__call__` a sync dispatcher: `len(args)==2` -> ASGI path (returns coroutine), else -> WSGI path (returns Response directly)
- **Files modified:** server/audit/middleware.py
- **Verification:** All 33 audit tests pass (23 existing + 10 new)
- **Committed in:** 12a22729 (Task 2)

**2. [Rule 3 - Blocking] Added SearchFilter/OrderingFilter backends and explicit page_size**
- **Found during:** Task 2 (API tests)
- **Issue:** search_fields/ordering_fields had no effect without explicit filter_backends; PageNumberPagination had no page_size (PAGE_SIZE not in DRF settings)
- **Fix:** Added `filter_backends = [SearchFilter, OrderingFilter]` and custom `_AuditPagination(page_size=20)` to view
- **Files modified:** server/audit/api/views.py
- **Verification:** Search, ordering, and pagination tests pass
- **Committed in:** 12a22729 (Task 2)

---

**Total deviations:** 2 auto-fixed (1 bug, 1 blocking)
**Impact on plan:** Both fixes were necessary for the API to function correctly with the existing test infrastructure. No scope creep.

## Known Stubs

None -- all endpoints are fully functional.

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| threat_flag: wsgi_actor_extraction | audit/middleware.py | WSGI mode extracts actor from request.user (populated by AuthenticationMiddleware); trust boundary: relies on middleware ordering (same as ASGI path) |

## Self-Check: PASSED

- [x] server/audit/api/__init__.py exists
- [x] server/audit/api/serializers.py exists
- [x] server/audit/api/views.py exists
- [x] server/audit/api/urls.py exists
- [x] server/tests/audit/test_api.py exists with 10 tests
- [x] server/friday/urls.py modified (audit URLs registered)
- [x] Commit d3c1d074 exists (Task 1: REST API)
- [x] Commit 12a22729 exists (Task 2: tests + middleware fix)
- [x] All 33 audit tests pass (10 new + 23 existing)
- [x] Django check passes
