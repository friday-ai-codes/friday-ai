---
phase: 123-detect-changes
reviewed: 2026-08-09T19:10:00Z
depth: standard
files_reviewed: 16
files_reviewed_list:
  - server/services/code_graph/detect_changes.py
  - server/services/repo_mirror.py
  - server/services/code_graph_tools.py
  - server/mcp_tools/serializers.py
  - server/mcp_tools/views.py
  - server/mcp_tools/urls.py
  - server/agents/tools/schemas/graph_tools.py
  - server/agents/tools/graph_tools.py
  - server/agents/tools/__init__.py
  - server/agents/chat_runner.py
  - server/tests/services/code_graph/test_detect_changes.py
  - server/tests/services/test_diff_mirror.py
  - server/tests/services/code_graph/test_detect_changes_orchestrator.py
  - server/tests/mcp_tools/test_detect_changes_tools.py
  - server/tests/mcp_tools/test_schema_snapshot.py
  - server/tests/agents/tools/test_graph_tools.py
findings:
  critical: 1
  warning: 3
  info: 3
  total: 7
  blocker: 1
  high: 2
  medium: 1
  low: 1
  info_items: 2
status: issues_fixed
fix_report: .planning/phases/123-detect-changes/123-REVIEW-FIX.md
fixed_at: 2026-08-09T19:11:44.841Z
fixed_in_scope: [CR-01, WR-01, WR-02, WR-03]
skipped_out_of_scope: [IN-01, IN-02, IN-03]
---

# Phase 123: Code Review Report

**Reviewed:** 2026-08-09T19:10:00Z
**Depth:** standard
**Files Reviewed:** 16
**Status:** issues_fixed (see `123-REVIEW-FIX.md` — CR-01 / WR-01 / WR-02 / WR-03 committed; INFO/LOW skipped)

## Summary

Phase 123 delivers a coherent detect_changes stack: pure overlap kernel, `diff_mirror`/`ensure_mirror_sha`, shared `run_detect_changes`, and thin MCP/chat shells with counts-only traces and dual-surface sentinel coverage. Adversarial review found one **BLOCKER** on D-01 base anchoring (`ensure_mirror_commit` can return default-branch tip / cached HEAD instead of `last_indexed_commit_sha`), plus **HIGH** gaps on uppercase SHA routing and rename-with-missed-hunk over-seeding. ACL fail-closed, credential scrubbing, and dual-surface passthrough look sound where exercised.

Severity legend used below: **BLOCKER** / **HIGH** / **MEDIUM** / **LOW** / **INFO** (frontmatter `critical` ≡ BLOCKER).

## Narrative Findings (AI reviewer)

### BLOCKER Issues

### CR-01: Diff base not hard-pinned to `last_indexed_commit_sha` (D-01 / D-03)

**Severity:** BLOCKER
**File:** `server/services/code_graph_tools.py:1155-1167`
**Also:** `server/services/repo_mirror.py:273-325`

**Issue:** `run_detect_changes` pins base via `ensure_mirror_commit(repository_id)` (no branch). That helper is **branch-HEAD oriented** and may return a non-index sha:

1. TTL `_fetch_cache[(repo_id, default_branch)]` can short-circuit **before** sha pin fetch and return a previously cached branch tip even when `pin_sha` (indexed sha) is set but not yet local (`repo_mirror.py:277-283`).
2. If indexed-sha fetch fails, step 4 **falls back to** `refs/heads/{default_branch}` tip (`repo_mirror.py:306-325`) and still returns success with `matches_index=False`.
3. Orchestrator never asserts `base.commit_sha == indexed_sha` / `base.matches_index`, so a drifted base silently drives `diff_mirror` and old-side line overlap against Symbol rows from the index waterline — exactly the Pitfall 5 / D-01 failure mode. D-03 requires hard-reject when base object is unavailable, not silent tip substitution.

Orchestrator tests mock `ensure_mirror_commit` to always return `BASE_SHA`, so they never catch this real helper semantics gap.

**Fix:**
```python
# run_detect_changes — pin base by sha, fail closed
try:
    base = await ensure_mirror_sha(repository_id, indexed_sha.lower())
except MirrorError as exc:
    _log_failed(exc.code, exc.detail)
    return {
        "ok": False,
        "error_code": exc.code,
        "error": exc.detail,
        "tool": "detect_changes",
        "repository_id": repository_id,
    }
if base.commit_sha.lower() != indexed_sha.lower():
    err = "无法将 diff base 锚定到索引水位 commit"
    _log_failed("mirror_fetch_failed", err)
    return {
        "ok": False,
        "error_code": "mirror_fetch_failed",
        "error": err,
        "tool": "detect_changes",
        "repository_id": repository_id,
    }
```

Also fix `ensure_mirror_commit` cache ordering (do not return branch-tip cache when `pin_sha` is set) so other callers do not inherit the same pitfall — but detect_changes must not depend on that fallback path at all.

---

### HIGH Issues

### WR-01: Uppercase full SHA accepted by shells, rejected as sha by orchestrator

**Severity:** HIGH
**File:** `server/services/code_graph_tools.py:111`, `1169-1173`
**Also:** `server/mcp_tools/serializers.py:13,246-247`; `server/agents/tools/schemas/graph_tools.py:17,209`

**Issue:** MCP / pydantic allow `[0-9a-fA-F]{40}` for `compare`. Orchestrator routes sha only with lowercase-only `_FULL_SHA_RE = r"^[0-9a-f]{40}$"`. An uppercase (or mixed-case) 40-char sha therefore takes the **branch** path `ensure_mirror_commit(..., branch=compare_s)`, which tries `refs/heads/<sha>` and typically hard-fails (`mirror_fetch_failed`) even though `ensure_mirror_sha` would succeed after `.lower()`. Dual-surface still matches each other (both wrong), but DIFF-01 head resolution is broken for common GitHub-copied SHAs.

**Fix:**
```python
_FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
# ...
compare_s = (compare or "").strip()
if _FULL_SHA_RE.match(compare_s):
    head = await ensure_mirror_sha(repository_id, compare_s.lower())
else:
    head = await ensure_mirror_commit(repository_id, branch=compare_s)
```

---

### WR-02: Rename with content hunks that miss all symbols seeds entire file

**Severity:** HIGH
**File:** `server/services/code_graph/detect_changes.py:347-353`

**Issue:** For rename + hunks, if `hit_uids` is empty the kernel maps **all** old-path symbols as `renamed` with `impact_seed=True`:

```python
targets = (
    [s for s in symbols if s.uid in hit_uids]
    if hit_uids
    else list(symbols)
)
```

A rename that only touches non-symbol lines (comments, blank lines outside Symbol spans, or parser gaps) therefore floods impact seeds / can trip the 100-seed threshold. Pure-rename-without-hunks intentionally maps all symbols (single-entry, D-06); the `else list(symbols)` branch for **hunk-present-but-no-hit** over-includes and conflicts with “no flood” intent for content-bearing renames.

**Fix:** When `fc.hunks` is non-empty and `hit_uids` is empty, emit file-level `renamed` summary with `symbols=[]` (or only formatting_only if applicable) — do **not** promote every symbol to an impact seed.

```python
if fc.hunks and not hit_uids:
    files_out.append({
        "path": new_key or old_key,
        "change_type": ChangeType.RENAMED.value,
        "old_path": old_key,
        "new_path": new_key,
        "symbols": [],
        "file_summary": {"changeType": ChangeType.RENAMED.value},
    })
    continue
```

---

### MEDIUM Issues

### WR-03: D-08 “file-level summary” on threshold not applied to `files[]`

**Severity:** MEDIUM
**File:** `server/services/code_graph_tools.py:1290-1354`

**Issue:** When `impact_seed_count > 100`, batch `run_impact` is correctly skipped (`impacts=[]`, `truncated`/`not_expanded`), but the response still returns the full per-symbol `files[].symbols` list. CONTEXT D-08 asks to switch to **文件级摘要** under threshold. Agents still receive a large symbol dump (token / noise), undermining the DOS/noise control even though impact fan-out is gated.

**Fix:** On `truncated`, collapse each file group to `symbols=[]` (retain `file_summary` / counts in `summary`), or cap symbols and set an explicit `summary.file_level_only=True` declaration.

---

### LOW Issues

### IN-01: Orchestrator D-01 tests only mock pin helper (reliability gap)

**Severity:** LOW
**File:** `server/tests/services/code_graph/test_detect_changes_orchestrator.py:137-179`

**Issue:** `test_diff_base_pinned_to_last_indexed` asserts `ensure_mirror_commit(..., branch=None)` and that the mock returns indexed sha. It does not exercise real `ensure_mirror_sha` / `matches_index` / pin-failure hard-reject, which allowed CR-01 to land green.

**Fix:** After production fix, add an unmocked (or thin-mocked `_fetch_repo_params` only) test that index-behind + cached branch tip cannot become `diff_base_sha`, and that pin failure yields `ok=False` rather than tip fallback.

---

### INFO

### IN-02: Kernel vs orchestrator `truncated` criteria diverge

**Severity:** INFO
**File:** `server/services/code_graph/detect_changes.py:478`; `server/services/code_graph_tools.py:1290`

**Issue:** Kernel sets `truncated` from total affected symbol count; orchestrator rebuilds summary from `impact_seed_count`. Harmless today because orchestrator discards kernel summary, but confusing if someone later surfaces kernel summary directly.

**Fix:** Document single source of truth (seeds) or align kernel helper with seed counting.

### IN-03: Observability / ACL / dual-surface (positive notes)

**Severity:** INFO

- ACL: `ensure_repository_readable` before mirror/ORM; `GraphAccessDenied` propagates; shells map via `GraphError` — fail-closed OK.
- Credentials: mirror stderr scrubbed (`_scrub`); failed events use `redact_secrets_in_text`; `tool_trace_payload(detect_changes)` counts-only — OK.
- Staleness: success path attaches `staleness_payload` + behind≥20 declaration strengthen — OK for D-04.
- D-09: sequential `run_impact(..., graph_branch=None)` — OK.
- D-13: MCP/chat thin passthrough + dual-surface sentinel (success + `repository_not_indexed`) — OK within tested matrix.
- D-05/D-06 happy paths (old-side overlap, `--find-renames`, single rename entry) covered by kernel/mirror tests — OK aside from WR-02.

---

_Reviewed: 2026-08-09T19:10:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
