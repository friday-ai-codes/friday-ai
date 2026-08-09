---
phase: 126-process-rename-skills
plan: 04
subsystem: code_graph
tags: [rename-preview, grep-mirror, readonly, mcp, agents, knowledge-tools, D-09, D-10, D-11, D-12]

requires:
  - phase: 126-process-rename-skills
    provides: Wave 0 rename stubs + dual-face process query pattern (126-03)
  - phase: 122-impact-trace-tools
    provides: resolve_symbol_candidates / fetch_graph_for_tool / dual-face shells
provides:
  - dual-source rename_preview kernel (graph + text_search) with applied=false
  - run_rename_preview orchestration + MCP/agents thin shells + RetrievalTrace both faces
  - task knowledge_tools whitelist entry rename_preview (11→12)
affects:
  - 126-05 friday-impact / friday-refactoring skills (consume rename_preview checklist)
  - npm mcp/ client drift (Deferred D-27)

tech-stack:
  added: []
  patterns:
    - "Pure merge kernel in code_graph/rename_preview.py; grep_mirror+exclusion only in orchestrator"
    - "confidence binary graph|text_search; same file:line prefers graph with sources[]"
    - "Dual-face thin shells + knowledge whitelist fail-soft (D-12)"

key-files:
  created:
    - server/services/code_graph/rename_preview.py
    - task/tests/core/test_knowledge_tools.py
  modified:
    - server/services/code_graph_tools.py
    - server/mcp_tools/views.py
    - server/mcp_tools/urls.py
    - server/mcp_tools/serializers.py
    - server/agents/tools/graph_tools.py
    - server/agents/tools/schemas/graph_tools.py
    - server/agents/tools/__init__.py
    - server/agents/chat_runner.py
    - task/core/knowledge_tools.py
    - server/tests/services/code_graph/test_rename_preview.py
    - task/tests/test_knowledge_tools.py
    - task/tests/test_claude_sdk_integration.py
    - task/tests/test_blueprint_context_tools_schema.py
    - task/tests/test_blueprint_context_wait.py

key-decisions:
  - "Graph half = definition + one-hop predecessors (A3); text half via grep_mirror only"
  - "applied forced false on every success/failure envelope path; no apply/rewrite API"
  - "D-27 npm mcp client drift 10→11 (rename_preview); submodule untouched"
  - "chat_runner _INDEXED_TOOL_NAMES includes rename_preview (register ≠ expose)"

patterns-established:
  - "rename_preview_started/completed/failed with component=code_graph category=caller"
  - "MCP View + agents @tool both write RetrievalTrace (Dual-face PATTERNS)"

requirements-completed: [RENAME-01]

duration: 5min
completed: 2026-08-10
---

# Phase 126 Plan 04: Read-only rename_preview Dual-source Summary

**Read-only dual-source `rename_preview` (graph refs + grep_mirror text) with binary confidence, coverage_limitations, MCP/agents thin shells, and coding-container whitelist — closes RENAME-01 without any apply path.**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-08-09T21:24:53Z
- **Completed:** 2026-08-09T21:30:09Z
- **Tasks:** 2/2 (TDD RED→GREEN each)
- **Files modified:** 16

## Accomplishments

- Kernel `merge_dual_source_edits` / `collect_graph_edit_sites` + `run_rename_preview` (ACL → resolve → graph → grep_mirror+exclusion → merge); `applied` always false
- MCP `RenamePreviewView` + agents `@tool(rename_preview)` both call `run_rename_preview` and write RetrievalTrace
- `task/core/knowledge_tools.py` whitelist 11→12 with fail-soft「继续交付」copy (D-12)
- Frozen surfaces untouched: no edits to `repo_router_v2.py` or `mcp/` submodule

## Task Commits

Each task was committed atomically (TDD):

1. **Task 1: rename_preview 内核 + run_rename_preview（D-09/D-10/D-11）** — RED `fc6bc83c` (test) → GREEN `d1229aed` (feat)
2. **Task 2: MCP/对话薄壳 + knowledge 白名单（D-06/D-12）** — RED `6738c750` (test) → GREEN `81f19e83` (feat)

## Files Created/Modified

- `server/services/code_graph/rename_preview.py` — pure dual-source merge; coverage_limitations; no bare grep
- `server/services/code_graph_tools.py` — `run_rename_preview` + lifecycle logs
- `server/mcp_tools/{views,urls,serializers}.py` — RenamePreviewView + `tools/rename_preview/`
- `server/agents/tools/graph_tools.py` (+ schemas / `__init__` / `chat_runner.py`) — dual-face + chat whitelist
- `task/core/knowledge_tools.py` — rename_preview schema entry
- Tests: rename_preview kernel + shell call-through; task whitelist counts

## Decisions Made

- Graph sites = seed definition + one-hop predecessors; text matches filtered with same exclusion matcher as MCP Grep
- Same `file:line` keeps one edit, `confidence=graph`, `sources` may list both
- Ambiguous / not found / mirror errors → `ok=False` + `applied=false` (never fake-empty success)
- Server MCP tool name `rename_preview` drifts npm `mcp/` client (Deferred); submodule not modified

## Deviations from Plan

None - plan executed exactly as written.

**Rule 2 (critical):** Also registered `rename_preview` on `chat_runner._INDEXED_TOOL_NAMES` so chat LLM can see the tool (same pitfall as 126-03 process tools).

## Issues Encountered

None

## npm mcp client drift (D-27)

| Tool | Server path | npm client |
|------|-------------|------------|
| `rename_preview` | `/api/mcp/tools/rename_preview/` | **not yet** (Deferred follow-up) |

Prior plan 03 left drift at **10** server-facing graph tools vs client; this plan adds **+1** (`rename_preview`) → track **11** until npm publish.

## TDD Gate Compliance

- RED commits present: `fc6bc83c`, `6738c750`
- GREEN commits present after RED: `d1229aed`, `81f19e83`

## Known Stubs

None — success paths return real dual-source envelopes; empty `files[]` only when both sources truly miss.

## Threat Flags

None beyond plan register (T-126-01..06 mitigated in tests + applied=false hard lock).

## Verification

```
cd server && GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False \
  uv run pytest tests/services/code_graph/test_rename_preview.py tests/services/code_graph/test_frozen_surface_126.py -q --reuse-db
# 10 passed

cd task && uv run pytest -k rename_preview -q
# 1 passed
```

Frozen confirmation: no commit touches `server/codegraph/services/repo_router_v2.py` or `mcp/`.

## Self-Check: PASSED

- FOUND: `server/services/code_graph/rename_preview.py`
- FOUND: `run_rename_preview` in `code_graph_tools.py`
- FOUND: commits `fc6bc83c` `d1229aed` `6738c750` `81f19e83`
- FOUND: SUMMARY at `.planning/phases/126-process-rename-skills/126-04-SUMMARY.md`
