---
phase: 126-process-rename-skills
fixed_at: 2026-08-09T21:42:58Z
review_path: .planning/phases/126-process-rename-skills/126-REVIEW.md
iteration: 1
findings_in_scope: 6
fixed: 6
skipped: 0
status: all_fixed
---

# Phase 126: Code Review Fix Report

**Fixed at:** 2026-08-09T21:42:58Z
**Source review:** `.planning/phases/126-process-rename-skills/126-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 6 (all Warnings; Info skipped per scope)
- Fixed: 6
- Skipped: 0

## Fixed Issues

### WR-01: Global `seen_global` drops alternate terminals / longer spines

**Files modified:** `server/services/code_graph/process_trace.py`
**Commit:** `60bb9498`
**Status:** fixed: requires human verification
**Applied fix:** Removed process-wide `seen_global`; cycles stay on `path_ids` only. Added `MAX_PATHS_PER_ENTRY=64` / `MAX_FRONTIER_SIZE=256` budgets so diamond alternate spines are explored without unbounded fan-out.

### WR-02: Community rebuild failure never enqueues Process rebuild

**Files modified:** `server/durable/tasks_impl.py`, `server/tests/services/code_graph/test_process_enqueue.py`
**Commit:** `f70ebdfe`
**Applied fix:** Best-effort `enqueue_process_rebuild` now runs on both community success and hard failure (before re-raise). Updated D-03 test to assert failure still chains. (Integrated via targeted merge because concurrent WIP dirtied `tasks_impl.py` during worktree FF.)

### WR-03: `tool_trace_payload` never counts `rename_preview` edits

**Files modified:** `server/services/code_graph_tools.py`
**Commit:** `855a5f79`
**Applied fix:** Added `rename_preview` count-only branch: `result_count=total_edits`, `total_found=files_affected`, `truncated` from `text_search_truncated` — no files/edits body in RetrievalTrace.

### WR-04: Async boundary markers use bare substring match

**Files modified:** `server/services/code_graph/process_trace.py`
**Commits:** `d0a20512`, `812b1abd`
**Applied fix:** Replaced substring `ASYNC_NAME_MARKERS` with token/suffix regex (`_ASYNC_BOUNDARY_RE`) so `delay_response` / `group_sender` etc. no longer truncate BFS; removed stale `__all__` export.

### WR-05: GraphError / shell failure paths omit `applied: false`

**Files modified:** `server/services/code_graph_tools.py`, `server/mcp_tools/views.py`, `server/agents/tools/graph_tools.py`
**Commit:** `2f058fa2`
**Applied fix:** `run_rename_preview` catches `GraphError` and returns soft envelope with `applied: false`. MCP / agent rename shells convert residual `GraphError` to the same shape (HTTP 200 / `ToolResult(success=True)` path) instead of hard error responses.

### WR-06: `max_processes` truncates by raw Endpoint iteration order

**Files modified:** `server/services/code_graph/process_trace.py`
**Commit:** `09528015`
**Status:** fixed: requires human verification
**Applied fix:** Collect all resolvable endpoint candidates first, sort (`cross_community` first, then `step_count` desc), then slice to `max_processes` and set `truncated_by_max_processes` when needed.

## Skipped Issues

None — all in-scope Warning findings were fixed.

## Out of scope (Info)

- **IN-01** / **IN-02** / **IN-03** — skipped per `fix_scope=critical_warning` (Info only if trivial; none applied).

## Verification

Scoped pytest in isolated worktree (20 passed):

```text
tests/services/code_graph/test_process_trace.py
tests/services/code_graph/test_process_enqueue.py
tests/services/code_graph/test_rename_preview.py
tests/services/code_graph/test_process_query.py
```

Frozen surfaces (`repo_router_v2.py`, `mcp/`) were not modified by fix commits.

## Integration note

Worktree FF onto `main` initially failed due to concurrent dirty `tasks_impl.py`. Fix commits were recovered from `gsd-reviewfix/126-93366` and cherry-picked / merged onto `main` (tip `f70ebdfe`). Optional leftover refs: `gsd-reviewfix/126-93366`, `phase126-review-fixes`.

---

_Fixed: 2026-08-09T21:42:58Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
