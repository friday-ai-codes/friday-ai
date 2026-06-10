---
phase: 06-pat
plan: 02
subsystem: access_tokens
tags: [pat, backend, model, migration, serializer, green]
dependency_graph:
  requires:
    - "06-01 (RED backend assertions: token_suffix==plaintext[-4:], note persistence, read-only serializer)"
  provides:
    - "AccessToken.note + AccessToken.token_suffix columns (default='')"
    - "acreate persists note + token_suffix=plaintext[-4:]"
    - "AccessTokenSerializer read-only note/token_suffix output (no plaintext/token_hash)"
    - "AccessTokenCreateSerializer optional note input"
  affects:
    - "06-03 (frontend impl) — DTO/列表/表单可消费 note + token_suffix"
tech_stack:
  added: []
  patterns:
    - "Additive AddField migration with default='' (no data migration, historical rows get empty strings)"
    - "Server-side fingerprint derivation (token_suffix=plaintext[-4:]) symmetric with token_prefix=plaintext[:12]"
    - "Output serializer read_only_fields = fields (no writable field can leak)"
key_files:
  created:
    - server/access_tokens/migrations/0002_accesstoken_note_accesstoken_token_suffix.py
  modified:
    - server/access_tokens/models.py
    - server/access_tokens/serializers.py
    - server/access_tokens/views.py
decisions:
  - "Migration file kept generated name 0002_accesstoken_note_accesstoken_token_suffix.py (Django default); contract is one additive 0002_* with two AddField ops, not the exact filename"
  - "note read via data.get('note', '') in acreate for defense-in-depth even though create serializer guarantees default=''"
metrics:
  duration: ~4 min
  completed: 2026-06-09
  tasks: 2
  files: 4
---

# Phase 6 Plan 02: PAT Backend增量 (note + token_suffix) Summary

Surgical additive backend change adding an optional `note` and a non-sensitive `token_suffix` fingerprint to `AccessToken`, turning the Wave-0 (06-01) backend assertions GREEN without touching authentication, hashing, owner isolation, or soft-revoke.

## What Was Built

**Task 1 — Model fields + AddField migration** (`c508f312`)
- `models.py`: added `note = models.CharField(max_length=500, blank=True, default="")` and `token_suffix = models.CharField(max_length=8, default="")`, mirroring the existing `token_prefix` declaration + Chinese comment convention. Both carry `default=""` so historical rows load with empty strings (no interactive default prompt, no data migration).
- Generated `0002_accesstoken_note_accesstoken_token_suffix.py` — exactly two `migrations.AddField` ops (note, token_suffix) with `dependencies = [("access_tokens", "0001_initial")]`.

**Task 2 — Serializer + acreate persistence** (`f5669df5`)
- `serializers.py`: `AccessTokenSerializer.Meta.fields` now includes `note` + `token_suffix`; `read_only_fields = fields` unchanged (output stays fully read-only — the T-06-04 safety contract). `AccessTokenCreateSerializer` gains `note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")`; no `token_suffix` input (derived server-side).
- `views.py` `acreate`: passes `note=data.get("note", "")` and `token_suffix=plaintext[-4:]` to `AccessToken.objects.acreate(...)` alongside the existing `token_prefix=plaintext[:12]`. Suffix derived from in-memory plaintext only; the one-time `response_data["token"] = plaintext` return is unchanged. `get_queryset` owner filter and `revoke` action untouched (PAT-04/06 regression).

## Validation Results

| Check | Command | Outcome |
|-------|---------|---------|
| Backend suite | `uv run pytest tests/test_access_tokens.py tests/test_no_plaintext_token_in_db.py -q` | 8 passed (06-01 RED → GREEN; leak guards stay GREEN) |
| Migration check [BLOCKING] | `uv run python manage.py makemigrations access_tokens --check --dry-run` | EXIT 0 — "No changes detected" (no pending model changes) |
| Migration apply | `uv run python manage.py migrate access_tokens` | Applied 0002 OK on dev DB with existing rows |
| Lint | ruff/mypy diagnostics on changed files | No linter errors |

## Security Contract Held

- Plaintext NEVER persisted: only `token_hash` (unsalted sha256, unique index) + non-sensitive `token_prefix`/`token_suffix`. `token_suffix` = 4 chars, non-recoverable, same class as the 12-char prefix.
- `token_suffix ≤ 4 chars` (stored as `plaintext[-4:]`; `max_length=8` is CONTEXT-locked headroom only).
- Output serializer `read_only_fields = fields` — no writable field can sneak in; `token_hash`/plaintext absent from serialized output.
- `note` writable only on the create (input) serializer, never on the output serializer (T-06-04 mitigation).
- Owner isolation (`get_queryset` created_by filter) and soft-revoke unchanged (T-06-06 accept, regression-covered).

## Deviations from Plan

None — plan executed exactly as written. The generated migration filename is `0002_accesstoken_note_accesstoken_token_suffix.py` (Django's default 2-field name) rather than the plan's illustrative `0002_accesstoken_note_token_suffix.py`; the plan explicitly permits keeping the generated name.

## Known Stubs

None — both fields are fully wired (model column → migration → serializer output → acreate write).

## Threat Flags

None — no new network endpoints, auth paths, or trust-boundary surface beyond the planned `note` input (bounded by `max_length=500` on model + serializer) and server-derived `token_suffix`. All threat-register mitigations (T-06-03/04/05) implemented as planned.

## Self-Check: PASSED

- FOUND: server/access_tokens/models.py (note + token_suffix fields)
- FOUND: server/access_tokens/migrations/0002_accesstoken_note_accesstoken_token_suffix.py (two AddField ops)
- FOUND: server/access_tokens/serializers.py (note + token_suffix in fields; note on create serializer)
- FOUND: server/access_tokens/views.py (token_suffix=plaintext[-4:], note=data.get(...))
- FOUND commit c508f312 (Task 1)
- FOUND commit f5669df5 (Task 2)
