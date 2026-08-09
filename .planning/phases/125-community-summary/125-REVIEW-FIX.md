---
phase: 125-community-summary
fixed_at: 2026-08-09T20:45:00Z
review_path: .planning/phases/125-community-summary/125-REVIEW.md
iteration: 1
findings_in_scope: 5
fixed: 5
skipped: 0
status: all_fixed
---

# Phase 125: Code Review Fix Report

**Fixed at:** 2026-08-09T20:45:00Z
**Source review:** `.planning/phases/125-community-summary/125-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 5 (CR-01, WR-01..WR-04; Info skipped per scope)
- Fixed: 5
- Skipped: 0

## Fixed Issues

### CR-01: Full-replace persist is not atomic — wipe-then-fail loses communities

**Files modified:** `server/services/code_graph/community.py`
**Commit:** `f64d203c`
**Applied fix:** Wrapped delete + `bulk_create` in `transaction.atomic()`; added `_unique_community_key` to de-dupe `community_key` collisions before insert.

### WR-01: Hooks hardcode `branch_name=""` — ignores build/edge branch context

**Files modified:** `server/services/graph_builder.py`, `server/code_relations/tasks.py`
**Commit:** `eca014bf`
**Applied fix:** Pass `normalized_branch or ""` from graph builder and `branch_name or ""` from edge-build orchestrator into `enqueue_community_rebuild`.

### WR-02: Member truncation breaks Jaccard member_keys on reload

**Files modified:** `server/services/code_graph/community.py`, `server/codegraph/models.py`, `server/codegraph/migrations/0012_symbolcommunity_member_keys.py`, `server/tests/codegraph/test_symbol_community_model.py`
**Commit:** `35941053`
**Applied fix:** Added `SymbolCommunity.member_keys` JSONField + migration; persist full stable keys (cap 50k) separately from truncated display `members`; load prefers stored keys with fallback for pre-migration rows.
**Status note:** `fixed: requires human verification` — Jaccard correctness for >500-member communities depends on this new column being populated on next rebuild.

### WR-03: New LLM summaries never set `summary_model` / `summary_generated_at`

**Files modified:** `server/services/code_graph/community.py`, `server/services/code_graph/module_summary.py`
**Commit:** `b0bdd1ec`
**Applied fix:** `agenerate_module_summary` mutates the community dict with `summary_model` + `summary_generated_at`; `_apply_summary_reconcile` backfills `summary_generated_at` when missing after a successful summary_fn call.
**Status note:** `fixed: requires human verification` — logic path for metadata attachment should be spot-checked against a live LLM generate.

### WR-04: Adapter failure logs omit credential redaction

**Files modified:** `server/agents/tools/repository_relevance.py`, `server/services/process_runtime/blueprint_route.py`
**Commit:** `deea8871`
**Applied fix:** Wrap exception text with `redact_secrets_in_text`; add `category="sampling"` / `component` on the relevance failure log to match peer paths.

## Skipped Issues

None — all Critical/Warning findings fixed. Info (IN-01, IN-02) out of scope.

## Verification

Scoped tests (18 passed):

```text
GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False \
  uv run pytest \
  tests/services/code_graph/test_community.py \
  tests/services/code_graph/test_module_summary.py \
  tests/services/code_graph/test_community_enqueue.py \
  tests/codegraph/test_symbol_community_model.py \
  --reuse-db
```

Frozen surfaces `repo_router_v2.py` and `mcp/` were not modified.

---

_Fixed: 2026-08-09T20:45:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
