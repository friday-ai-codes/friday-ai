---
phase: 123-detect-changes
plan: 04
subsystem: code-intelligence
tags: [detect_changes, conversational, DetectChangesToolInput, chat_runner, DIFF-01, DIFF-02]

requires:
  - phase: 123-02
    provides: run_detect_changes unique orchestrator
  - phase: 123-03
    provides: DetectChangesRequestSerializer MCP field table (compare/base_ref)
provides:
  - DetectChangesToolInput (strict pydantic; no branch overlay)
  - detect_changes @tool thin shell → run_detect_changes
  - agents.tools export + chat_runner._INDEXED_TOOL_NAMES whitelist
  - Registration + fail-closed tests in test_graph_tools.py
affects: [123-05]

tech-stack:
  added: []
  patterns:
    - "Conversational shell mirrors impact_analysis; output[data] passthrough (D-13)"
    - "compare required / base_ref declarative-only; no resolve_tool_graph_branch"
    - "Registration ≠ exposure: __init__ import + _INDEXED_TOOL_NAMES both required"

key-files:
  created: []
  modified:
    - server/agents/tools/schemas/graph_tools.py
    - server/agents/tools/graph_tools.py
    - server/agents/tools/__init__.py
    - server/agents/chat_runner.py
    - server/tests/agents/tools/test_graph_tools.py

key-decisions:
  - "Pydantic compare/base_ref validation mirrors MCP _SAFE_COMPARE_RE / _FULL_SHA_RE"
  - "Shell events use detect_changes_tool_* naming (impact shell pattern); component=agents.tools"
  - "DIFF-01/DIFF-02 left Pending until 123-05 dual-surface closure"

patterns-established:
  - "detect_changes chat shell: owner fail-closed → validate → _resolve_tool_repo → run_detect_changes → RetrievalTrace EDGE"
  - "Agents-side registration tests live in test_graph_tools.py; mcp test stub left for 123-05"

requirements-completed: []

duration: 2min
completed: 2026-08-09
---

# Phase 123 Plan 04: Conversational Tool Surface Summary

**Indexed-chat `detect_changes` thin shell shares `run_detect_changes` with MCP, with pydantic fields locked to the serializer table and whitelist exposure gated by `_INDEXED_TOOL_NAMES` (D-13).**

## Performance

- **Duration:** 2 min
- **Started:** 2026-08-09T18:52:20Z
- **Completed:** 2026-08-09T18:54:02Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- Added `DetectChangesToolInput` (`compare` required, optional `base_ref`, impact-aligned DoS bounds; no `branch`)
- Landed `@tool detect_changes` / `_detect_changes_impl` delegating 100% to `run_detect_changes` with fail-closed conversation owner gate
- Exported tool from `agents.tools` and whitelisted in `chat_runner._INDEXED_TOOL_NAMES`
- Greened agents-side registration + fail-closed tests (`-k detect_changes`)

## Task Commits

Each task was committed atomically:

1. **Task 1: DetectChangesToolInput + @tool 薄壳** - `d474edb8` (feat)
2. **Task 2: 导出、白名单与注册测** - `cc8c2366` (feat)

**Plan metadata:** (docs commit via gsd-tools)

## Files Created/Modified

- `server/agents/tools/schemas/graph_tools.py` — `DetectChangesToolInput` + ref validation
- `server/agents/tools/graph_tools.py` — `detect_changes` / `_detect_changes_impl` thin shell
- `server/agents/tools/__init__.py` — export + `__all__`
- `server/agents/chat_runner.py` — `_INDEXED_TOOL_NAMES` entry
- `server/tests/agents/tools/test_graph_tools.py` — registration + fail-closed tests

## Decisions Made

- Mirror MCP serializer regex validation in pydantic so chat/MCP reject the same bad refs
- Keep shell caller events as `detect_changes_tool_failed` / `detect_changes_tool_done` (same file pattern as impact); orchestrator retains `code_graph_detect_changes_*`
- Do not mark DIFF-01/DIFF-02 Complete here — left for 123-05 dual-surface plan

## Deviations from Plan

None - plan executed exactly as written.

## Threat Flags

None — no new trust-boundary surface beyond the planned conversational tool shell (ACL via conversation owner + orchestrator readable check; counts-only RetrievalTrace).

## Known Stubs

None — tool is fully wired to `run_detect_changes`; mcp skip stub in `test_detect_changes_tools.py` intentionally untouched (123-05).

## Verification Results

```text
GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False \
  uv run pytest tests/agents/tools/test_graph_tools.py -k detect_changes -q --reuse-db
→ 2 passed, 2 deselected
```

Import smoke: `DetectChangesToolInput` has `compare`, no `branch`; `_detect_changes_impl` calls `run_detect_changes`.

## Next Plan

123-05 — dual-surface sentinel + requirement closure for DIFF-01/DIFF-02.

## Self-Check: PASSED

- Files present; commits d474edb8 / cc8c2366 on branch.
