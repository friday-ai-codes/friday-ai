---
phase: 126-process-rename-skills
reviewed: 2026-08-09T21:35:00Z
depth: standard
files_reviewed: 22
files_reviewed_list:
  - server/codegraph/models.py
  - server/codegraph/migrations/0013_processtrace.py
  - server/services/code_graph/process_trace.py
  - server/services/process_enqueue.py
  - server/services/code_graph/affected_processes.py
  - server/services/code_graph/rename_preview.py
  - server/services/code_graph/impact_report.py
  - server/services/code_graph_tools.py
  - server/durable/tasks.py
  - server/durable/tasks_impl.py
  - server/durable/handlers.py
  - server/friday/settings.py
  - server/mcp_tools/views.py
  - server/mcp_tools/urls.py
  - server/mcp_tools/serializers.py
  - server/agents/tools/graph_tools.py
  - server/agents/tools/schemas/graph_tools.py
  - server/agents/chat_runner.py
  - task/core/knowledge_tools.py
  - task/scripts/sync_skills.py
  - skills/skills/friday-impact/SKILL.md
  - skills/skills/friday-refactoring/SKILL.md
findings:
  critical: 0
  warning: 6
  info: 3
  total: 9
status: issues_found
---

# Phase 126: Code Review Report

**Reviewed:** 2026-08-09T21:35:00Z
**Depth:** standard
**Files Reviewed:** 22
**Status:** issues_found

## Summary

Adversarial review of Phase 126 (ProcessTrace/BFS, process query, `affected_processes`, `rename_preview`, skills packaging) across SUMMARYs 126-01..05. Frozen surfaces (`repo_router_v2.py`, `mcp/`) were not touched by `126-*` commits. BFS hard gates, `applied=false` success/fail envelopes, dual-face shells, and skill hash mirrors are largely intact. Main risks: global BFS visit can drop alternate spines; community failure never chains Process rebuild; rename RetrievalTrace counts stay zero; async-name substring markers over-fire.

## Warnings

### WR-01: Global `seen_global` drops alternate terminals / longer spines

**File:** `server/services/code_graph/process_trace.py:163-235`
**Issue:** `collect_process_paths` marks every expanded node in a process-wide `seen_global` and refuses re-entry from other branches. On a diamond (`entry→A→C→D` vs `entry→B→C→E`), the second path through `C` is skipped entirely, so terminal `E` (or a longer spine via `B`) never appears. This conflicts with D-02’s “同 entry→terminal 留最长” (longest among explored paths is meaningless if exploration is truncated) and can under-report ProcessTrace / `affected_processes` for real multi-caller graphs. Path-local cycle detection already exists via `path_ids`; global first-visit is an extra fan-out heuristic that changes semantics.
**Fix:** Keep cycle detection on `path_ids` only; replace `seen_global` with a bounded path budget (e.g. cap frontier size / paths-per-entry) or allow re-visit when the new path is longer/deeper than the prior visit before applying entry→terminal longest keep:

```python
# Prefer path-local only for cycles; optional depth memo:
# skip re-expansion of succ only when prior depth_at[succ] <= depth+1
if succ in path_ids:
    # cycle handle (existing)
    ...
prior = depth_at.get(succ)
if prior is not None and prior <= depth + 1:
    continue
depth_at[succ] = depth + 1
```

### WR-02: Community rebuild failure never enqueues Process rebuild (D-03 gap)

**File:** `server/durable/tasks_impl.py:811-821`
**Issue:** `enqueue_process_rebuild` runs only after `rebuild_communities` returns successfully. If the community job raises, the chain is skipped. D-03 / CONTEXT state that when community fails/empty, Process may still be built with `community_class` degradation — empty success is covered, hard failure is not. Result: ProcessTrace stays stale/missing whenever community rebuild fails, and `affected_processes` / impact_report stay empty without a retry path.
**Fix:** Best-effort enqueue Process rebuild in a `finally` after community attempt, or in the `except` before re-raise (still swallow enqueue errors):

```python
try:
    result = await rebuild_communities(...)
except Exception:
    try:
        await enqueue_process_rebuild(
            str(repository_id),
            branch_name=branch,
            initiated_by_user_id=initiated_by_user_id,
        )
    except Exception:
        pass
    raise
else:
    await enqueue_process_rebuild(...)
    return result
```

### WR-03: `tool_trace_payload` never counts `rename_preview` edits

**File:** `server/services/code_graph_tools.py:2302-2358`
**Issue:** `list_processes` / `get_process` get an explicit count-only branch, but `rename_preview` falls through the default `hops` path. Successful previews therefore write RetrievalTrace with `result_count=0` / `total_found=0` even when `summary.total_edits > 0`. Breaks T-126-03 count-only observability for the rename dual-face.
**Fix:** Add a branch before `return payload`:

```python
elif tool == "rename_preview":
    payload["result_count"] = int(summary.get("total_edits") or 0) if summary else 0
    payload["total_found"] = int(summary.get("files_affected") or 0) if summary else 0
    payload["truncated"] = 1 if bool((result.get("graph") or {}).get("text_search_truncated")) else 0
    # do not copy files/edits/context into trace
```

### WR-04: Async boundary markers use bare substring match (false truncations)

**File:** `server/services/code_graph/process_trace.py:38-46,82-84,208-221`
**Issue:** `ASYNC_NAME_MARKERS` includes short tokens `"delay"` and `"defer"`. `is_async_boundary_name` uses `marker in lowered`, so ordinary symbols like `delay_response`, `deferred_validation`, or `group_sender` can be treated as `async_dispatch` terminals and stop BFS. That silently shortens ProcessTrace spines unrelated to Celery/Channels dispatch.
**Fix:** Match token boundaries or exact/suffix call patterns (e.g. name equals marker, or endswith `".delay"` / `"apply_async"` / `"group_send"`), and keep short tokens out of naive substring checks:

```python
import re
_ASYNC_RE = re.compile(
    r"(?:^|_)(?:sync_to_async|apply_async|create_task|background_runner|group_send)(?:$|_)"
    r"|(?:^|\.)(?:delay|defer)$",
    re.I,
)
def is_async_boundary_name(name: str) -> bool:
    return bool(_ASYNC_RE.search(name or ""))
```

### WR-05: GraphError / shell failure paths omit `applied: false` contract

**File:** `server/mcp_tools/views.py:1734-1737` · `server/agents/tools/graph_tools.py:1402-1404` · `server/services/code_graph_tools.py:1987-1995`
**Issue:** Orchestrator success and soft-fail envelopes force `applied: False`. When `fetch_graph_for_tool` raises `GraphError`, MCP returns `_graph_error_response` (typically 4xx) and agents return `ToolResult(success=False)` with **no** `applied` field. RenamePreviewView docstring claims `ok=False` always HTTP 200 + envelope with applied false — GraphError path violates that. Clients/skills that gate on `applied` may mis-handle “not indexed / graph error” differently from `symbol_not_found`.
**Fix:** Catch `GraphError` inside `run_rename_preview` (or in both shells) and return the same soft envelope shape:

```python
except GraphError as exc:
    code, message = graph_error_to_tool_error(exc)
    return {
        "ok": False,
        "error_code": code,
        "error": message,
        "tool": "rename_preview",
        "applied": False,
        "coverage_limitations": COVERAGE_LIMITATIONS,
        "query": query,
    }
```

### WR-06: `max_processes` truncates by raw Endpoint iteration order

**File:** `server/services/code_graph/process_trace.py:447-511`
**Issue:** `_build_process_rows` breaks when `len(rows) >= max_processes` while iterating Endpoint queryset order (undefined/insertion order). Cross-community or longer flows discovered later are dropped arbitrarily; degradation only sets `truncated_by_max_processes`. Query default sort prefers `cross_community`, but those rows may never be persisted.
**Fix:** Collect candidates for all resolvable endpoints (or a higher working set), score/sort (`cross_community` first, then `step_count`), then slice to `max_processes` before persist.

## Info

### IN-01: `enqueue_process_rebuild` lacks `*_started` lifecycle event

**File:** `server/services/process_enqueue.py:44-57`
**Issue:** Observability checklist expects started/completed/failed. Helper logs completed/failed only (aligned with community enqueue, but incomplete lifecycle).
**Fix:** Emit `enqueue_process_rebuild_started` before `DurableTaskService.defer` (best-effort, same category/component).

### IN-02: Frozen-surface git guard depends on commit-message grep `126-`

**File:** `server/tests/services/code_graph/test_frozen_surface_126.py:76-101`
**Issue:** Guard runs `git log --grep=126-`. Commits that touch frozen paths without `126-` in the message are invisible to the test. Phase commits currently match; reliability is fragile.
**Fix:** Scope the guard to merge-base..HEAD file lists for known 126 SHAs, or `git log -- server/codegraph/services/repo_router_v2.py mcp` over the phase window.

### IN-03: Skill source ↔ `task/assets` hash currently consistent

**File:** `task/scripts/sync_skills.py:26` · `skills/skills/friday-impact/SKILL.md` · `skills/skills/friday-refactoring/SKILL.md`
**Issue:** No defect found — `SKILL_NAMES` includes both coding-period skills; sha256 of submodule sources matches `task/assets/skills/` mirrors; skills text correctly locks rename to read-only preview. npm publish remains Deferred (D-15) by design.
**Fix:** None required for Phase 126 acceptance; keep sync+hash tests green on future skill edits.

---

_Reviewed: 2026-08-09T21:35:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
