---
phase: 123-detect-changes
fixed_at: 2026-08-09T19:11:44.841Z
review_path: .planning/phases/123-detect-changes/123-REVIEW.md
iteration: 1
findings_in_scope: 4
fixed: 4
skipped: 0
status: all_fixed
---

# Phase 123: Code Review Fix Report

**Fixed at:** 2026-08-09T19:11:44.841Z
**Source review:** `.planning/phases/123-detect-changes/123-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 4 (BLOCKER + HIGH + MEDIUM; INFO/LOW skipped per scope)
- Fixed: 4
- Skipped: 0

## Fixed Issues

### CR-01: Diff base not hard-pinned to `last_indexed_commit_sha` (D-01 / D-03)

**Files modified:** `server/services/code_graph_tools.py`, `server/services/repo_mirror.py`, `server/tests/services/code_graph/test_detect_changes_orchestrator.py`
**Commit:** `0f0ed4c6`
**Applied fix:** `run_detect_changes` now pins base via `ensure_mirror_sha(indexed_sha)` and hard-rejects when returned sha ≠ index waterline. `ensure_mirror_commit` no longer returns TTL branch-tip cache when `pin_sha` is set but not yet the cached object. Orchestrator D-01 assertions updated to expect sha-pin call shape.
**Status:** fixed: requires human verification (logic/pinning semantics)

### WR-01: Uppercase full SHA accepted by shells, rejected as sha by orchestrator

**Files modified:** `server/services/code_graph_tools.py`
**Commit:** `46f4d230`
**Applied fix:** `_FULL_SHA_RE` is now case-insensitive; compare head resolution lowercases before `ensure_mirror_sha`.

### WR-02: Rename with content hunks that miss all symbols seeds entire file

**Files modified:** `server/services/code_graph/detect_changes.py`, `server/tests/services/code_graph/test_detect_changes.py`
**Commit:** `2c542b5a`
**Applied fix:** When rename has hunks but `hit_uids` is empty, emit file-level `renamed` with `symbols=[]` instead of seeding all old-path symbols. Added unit coverage.
**Status:** fixed: requires human verification (logic branch)

### WR-03: D-08 “file-level summary” on threshold not applied to `files[]`

**Files modified:** `server/services/code_graph_tools.py`, `server/tests/services/code_graph/test_detect_changes_orchestrator.py`
**Commit:** `d971a24d`
**Applied fix:** On `truncated`, collapse each file group's `symbols` to `[]` while retaining counts in `summary`; set `summary.file_level_only=True`. DOS orchestrator test asserts empty symbol lists + preserved counts.

## Skipped Issues

None in scope — INFO (`IN-02`, `IN-03`) and LOW (`IN-01`) intentionally skipped per fix scope (`BLOCKER + HIGH + MEDIUM`).

### Out of scope (not attempted)

### IN-01: Orchestrator D-01 tests only mock pin helper

**File:** `server/tests/services/code_graph/test_detect_changes_orchestrator.py:137-179`
**Reason:** LOW — skipped unless clearly safe; production pin path fixed in CR-01; deeper unmocked tip-vs-pin test left for follow-up.
**Original issue:** Mocked `ensure_mirror_commit` never exercised real tip-fallback / pin-failure hard-reject.

### IN-02: Kernel vs orchestrator `truncated` criteria diverge

**Reason:** INFO — skipped per scope.

### IN-03: Observability / ACL / dual-surface (positive notes)

**Reason:** INFO — skipped per scope (no defect).

## Test Results

Scoped suite (mandatory prefix env + `--reuse-db`):

```
tests/services/code_graph/test_detect_changes.py
tests/services/code_graph/test_detect_changes_orchestrator.py
tests/services/test_diff_mirror.py
tests/mcp_tools/test_detect_changes_tools.py
tests/agents/tools/test_graph_tools.py
```

**Result:** 36 passed

---

_Fixed: 2026-08-09T19:11:44.841Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
