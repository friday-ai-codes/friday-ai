---
phase: 125-community-summary
reviewed: 2026-08-09T20:36:00Z
depth: standard
files_reviewed: 18
files_reviewed_list:
  - server/agents/call_source.py
  - server/agents/tools/repository_relevance.py
  - server/code_relations/tasks.py
  - server/codegraph/migrations/0011_symbolcommunity.py
  - server/codegraph/models.py
  - server/durable/handlers.py
  - server/durable/tasks.py
  - server/durable/tasks_impl.py
  - server/mcp_tools/views.py
  - server/services/code_graph/community.py
  - server/services/code_graph/module_summary.py
  - server/services/community_enqueue.py
  - server/services/graph_builder.py
  - server/services/module_summary_signal.py
  - server/services/process_runtime/artifact_injection.py
  - server/services/process_runtime/blueprint_research_adapter.py
  - server/services/process_runtime/blueprint_route.py
  - .planning/observability/LOGGING-SPEC.md
findings:
  critical: 1
  warning: 4
  info: 2
  total: 7
status: issues_found
---

# Phase 125: Code Review Report

**Reviewed:** 2026-08-09T20:36:00Z
**Depth:** standard
**Files Reviewed:** 18
**Status:** issues_found

## Summary

Reviewed Phase 125 (plans 01–04) production sources for SymbolCommunity, Louvain/fingerprint/Jaccard reconcile, `module_summary` LLM + `CallSource.MODULE_SUMMARY`, QUEUE_GRAPH enqueue hooks, and adapter injection. Frozen surfaces `repo_router_v2.py` and `mcp/` were **not** touched by 125-* commits (verified via `git log --grep=125-`). Soft-ref model + ADD-TABLE migration look sound; rebuild×2 fingerprint short-circuit and call_source dual-registration are correctly wired. One **Critical** data-loss window remains in full-replace persist; branch passthrough and large-community Jaccard correctness are the main Warnings.

## Critical Issues

### CR-01: Full-replace persist is not atomic — wipe-then-fail loses communities

**File:** `server/services/code_graph/community.py:405-426`
**Issue:** `_persist_communities` deletes all `(repository, branch_name)` rows, then `bulk_create`s. There is no `transaction.atomic()`. Under Django autocommit, a failure after `delete()` (IntegrityError on duplicate `community_key`, DB blip, process kill) commits an empty community set. Concurrent rebuilds widen the window. This is a real data-loss path for MOD-01’s full-replace design.
**Fix:**
```python
from django.db import transaction

def _persist_communities(...) -> int:
    from codegraph.models import SymbolCommunity
    from repositories.models import Repository

    repo = Repository.objects.get(id=repository_id)
    rows = [SymbolCommunity(...) for c in communities]
    with transaction.atomic():
        SymbolCommunity.objects.filter(repository=repo, branch_name=branch_name).delete()
        if rows:
            SymbolCommunity.objects.bulk_create(rows)
    return len(rows)
```
Also de-dupe `community_key` before insert (e.g. suffix on collision after Jaccard key reuse) so unique violations are less likely inside the transaction.

## Warnings

### WR-01: Hooks hardcode `branch_name=""` — ignores build/edge branch context

**File:** `server/services/graph_builder.py:535-539`
**File:** `server/code_relations/tasks.py:244-248`
**Issue:** RESEARCH/D-03 require enqueue payload to pass the build’s `branch_name` (default `""` only when base). Both hooks always pass `branch_name=""`. Feature-branch graph/edge completion therefore (a) never enqueues community rebuild for that branch, and (b) spuriously schedules a **base** rebuild after feature work. `normalized_branch` / orchestrator `branch_name` are already in scope at both call sites.
**Fix:**
```python
# graph_builder.py — after graph build for normalized_branch
await enqueue_community_rebuild(
    str(repository_id),
    branch_name=normalized_branch or "",
)

# code_relations/tasks.py — inside _run_all_builders_and_sync_payload
await enqueue_community_rebuild(
    str(repository_id),
    branch_name=branch_name or "",
)
```

### WR-02: Member truncation breaks Jaccard member_keys on reload

**File:** `server/services/code_graph/community.py:218-223`
**File:** `server/services/code_graph/community.py:257-265`
**File:** `server/services/code_graph/community.py:414`
**Issue:** Fingerprints are computed on the **full** member set, but persist truncates to `MAX_MEMBERS_STORED=500`. `_load_old_communities` rebuilds `member_keys` from stored (truncated) members. For communities with >500 symbols, fingerprint short-circuit still works, but Jaccard (≥0.8 reuse) compares truncated old keys vs full new keys → score collapse → unnecessary LLM regenerations, defeating D-06/D-07 for large modules.
**Fix:** Persist a dedicated `member_keys` (or hash-stable key list) alongside fingerprint, **or** compute Jaccard from fingerprints + store untruncated key hashes (e.g. sorted key digest list capped separately from display `members`). At minimum, when truncating members for JSON DoS protection, keep full `member_keys` (or their hashes) for reconcile.

### WR-03: New LLM summaries never set `summary_model` / `summary_generated_at`

**File:** `server/services/code_graph/community.py:381-386`
**File:** `server/services/code_graph/module_summary.py:171-304`
**Issue:** D-01/D-06 define `summary_model` / `summary_generated_at` and require reuse of `summary_model` on Jaccard/fingerprint hit. Generation path only sets `community["summary"]`. New rows always leave model/timestamp null; stale/debug consumers cannot tell which model produced the text or when.
**Fix:** Have `agenerate_module_summary` return `(json, model_name)` or set fields in `_apply_summary_reconcile` after a successful call:
```python
from django.utils import timezone

summary = await _call_summary_fn(...)
if summary:
    community["summary"] = summary
    community["summary_model"] = community.get("summary_model") or model_name
    community["summary_generated_at"] = timezone.now()
    summaries_generated += 1
```

### WR-04: Adapter failure logs omit credential redaction

**File:** `server/agents/tools/repository_relevance.py:241-243`
**File:** `server/services/process_runtime/blueprint_route.py:827-834`
**Issue:** LOGGING-SPEC requires `redact_secrets_in_text` on exception text. `_apply_module_summary_signal` logs `error=str(exc)` with no redact and no `category`/`component`. `blueprint_route_module_summary_load_failed` similarly logs raw `str(exc)`. Peer paths in `module_summary_signal.py` / `community_enqueue.py` already redact.
**Fix:**
```python
from common.logging import redact_secrets_in_text

logger.warning(
    "repository_relevance_module_summary_signal_failed",
    error=redact_secrets_in_text(str(exc)),
    category="sampling",
    component="agents",
)
```

## Info

### IN-01: Prompt advertises `degree` but members never attach graph degree

**File:** `server/services/code_graph/community.py:125-145`
**File:** `server/services/code_graph/module_summary.py:106-126`
**Issue:** D-10 lists degree as optional metadata; `build_module_summary_prompt` sorts by `degree`, but `_node_member` never sets it → always `degree=0`, so ranking is path/name only. Not a correctness break for skip/LLM=0, but weakens summary quality.
**Fix:** When building members, set `degree=int(graph.degree(node_id))` (undirected projection degree preferred).

### IN-02: Enqueue lifecycle missing `*_started` event

**File:** `server/services/community_enqueue.py:33-72`
**Issue:** Observability checklist prefers started/completed/failed. Enqueue only emits completed/failed (rebuild job itself has started). Minor gap vs LOGGING-SPEC §9 self-check.
**Fix:** Emit `enqueue_community_rebuild_started` before `DurableTaskService.defer` (best-effort).

---

### Attention checklist (phase-specific)

| Concern | Verdict |
|--------|---------|
| Soft refs (no Symbol FK/M2M) | OK — model + migration + contract tests |
| Jaccard skip + empty-summary retry | OK for ≤500 members; WR-02 for larger |
| rebuild×2 LLM=0 | OK via fingerprint short-circuit + durable `summary_fn` |
| Frozen `repo_router_v2` / `mcp/` | OK — absent from all 125-* commits |
| LOGGING-SPEC `call_source=module_summary` (45) | OK — dual-registered + guardian |
| Migration safety | OK — CreateModel + indexes only; depends `0010` |
| Observability | Mostly OK; WR-04 / IN-02 gaps |

---

_Reviewed: 2026-08-09T20:36:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
