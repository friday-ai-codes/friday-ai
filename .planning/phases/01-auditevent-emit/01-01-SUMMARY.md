---
phase: 01-auditevent-emit
plan: 01-01
subsystem: audit
tags: [model, migration, admin, append-only, test]
requires: []
provides: [AuditEvent, audit-app]
affects: [friday/settings.py]
tech_stack:
  added: [audit Django app]
  patterns: [UUID PK, TextChoices, JSONField snapshots, append-only guard, read-only admin]
key_files:
  created:
    - server/audit/__init__.py
    - server/audit/apps.py
    - server/audit/models.py
    - server/audit/admin.py
    - server/audit/migrations/0001_initial.py
    - server/tests/audit/__init__.py
    - server/tests/audit/test_audit_model.py
  modified:
    - server/friday/settings.py
decisions:
  - "append-only enforcement at model layer via save()/delete() overrides (ValueError on update/delete)"
  - "read-only admin with all fields readonly + no add/change/delete permissions"
  - "soft reference for target (target_type + target_id CharField) instead of FK to avoid CASCADE"
  - "actor FK nullable with SET_NULL for system events; actor_display for denormalized username"
metrics:
  duration: 208s
  completed: "2026-06-15T11:31:40Z"
  tasks_completed: 2
  tasks_total: 2
  files_created: 7
  files_modified: 1
  tests_added: 6
---

# Phase 01 Plan 01-01: AuditEvent Model + Migration + Read-Only Admin Summary

AuditEvent append-only model with UUID PK, composite indexes, read-only Django admin, and 6 model-layer guard tests.

## What Was Built

- **`audit` Django app** (`server/audit/`) with `AuditEvent` model following `interactions/models.py` conventions (UUID PK, TextChoices, JSONField, auto_now_add, explicit db_table, Chinese verbose_name)
- **Migration** (`audit/migrations/0001_initial.py`) creating `audit_event` table with composite indexes on `(target_type, target_id)` and `(actor, timestamp)`
- **Append-only enforcement** at model layer: `save()` rejects updates to existing records, `delete()` raises ValueError — no way to modify or remove audit events via ORM
- **Read-only Django admin** (`AuditEventAdmin`) with list_display, list_filter, search_fields, date_hierarchy, and all permissions disabled (no add/change/delete)
- **6 model tests** covering: create with all fields, JSONField defaults, timestamp auto-set, actor nullable for system events, update rejection, delete rejection

## Decisions Made

1. **Append-only at model layer** rather than only at API/admin layer — defense in depth, even raw ORM access cannot mutate audit records
2. **Soft reference for target** (target_type + target_id as CharField) instead of FK — avoids CASCADE complexity and allows auditing any model without schema changes
3. **Actor denormalization** (actor_display field) — preserves actor name even if user is deleted (SET_NULL on FK)
4. **django.contrib.admin not in INSTALLED_APPS** — existing project configuration; admin.py is syntactically valid and will work when admin is enabled

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — all fields have proper defaults and the model is fully functional for audit event creation.

## Self-Check: PASSED

- [x] server/audit/__init__.py exists
- [x] server/audit/apps.py exists
- [x] server/audit/models.py exists
- [x] server/audit/admin.py exists
- [x] server/audit/migrations/0001_initial.py exists
- [x] server/tests/audit/__init__.py exists
- [x] server/tests/audit/test_audit_model.py exists
- [x] Commit d703f468 exists (Task 1: AuditEvent model + migration)
- [x] Commit 57212064 exists (Task 2: append-only + admin + tests)
- [x] All 6 tests pass
