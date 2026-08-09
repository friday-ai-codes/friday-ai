---
phase: 125-community-summary
plan: 04
subsystem: services
tags: [adapter, blueprint-route, module-summary-signal, frozen-surface, research-prompt]

requires:
  - phase: 125-01
    provides: CallSource.MODULE_SUMMARY + Wave 0 signal/prompt/frozen stubs
  - phase: 125-02
    provides: SymbolCommunity + Louvain community rebuild
  - phase: 125-03
    provides: module_summary LLM + render_module_summary + Jaccard skip
provides:
  - "module_summary_signal aapply/aload fail-soft evidence (no score change)"
  - "blueprint_route evidence.module_summaries default [] (D-14 identity intact)"
  - "conversation + MCP RouteRepositories module summary evidence wiring"
  - "research prompt ## 模块摘要 with relevance sort + 2000/top-5 budget truncate"
  - "frozen-surface guard green (repo_router_v2 / mcp/ zero edits)"
affects:
  - Phase 126 Process (may consume module community context)

tech-stack:
  added: []
  patterns:
    - "D-13/D-15: adapter-only injection mirroring charter_route_signal; never touch repo_router_v2"
    - "D-14: evidence key extension only — no fourth scoring component"
    - "D-16: empty-section guard + relevance sort + char/item budget + truncated marker"

key-files:
  created:
    - server/services/module_summary_signal.py
  modified:
    - server/services/process_runtime/blueprint_route.py
    - server/agents/tools/repository_relevance.py
    - server/mcp_tools/views.py
    - server/services/process_runtime/artifact_injection.py
    - server/services/process_runtime/blueprint_research_adapter.py
    - server/tests/services/test_module_summary_signal.py
    - server/tests/services/process_runtime/test_blueprint_route_breakdown.py
    - server/tests/services/process_runtime/test_module_summary_prompt.py
    - server/tests/services/code_graph/test_frozen_surface_125.py

key-decisions:
  - "v1 module summary signal appends evidence/reason only; blended_score == router_score (no new weight key)"
  - "No candidate supplement in v1 (discretion skipped — not a gap)"
  - "Research prompt reads module_summaries from candidate evidence (filled by blueprint_route); fail-soft empty"
  - "Prompt budget: 2000 chars or top 5 communities (whichever first); mark truncated"
  - "Frozen surface commits never stage repo_router_v2.py or mcp/"

patterns-established:
  - "Three injection points: blueprint evidence / post-router signal / research prompt section"
  - "render_module_summaries_section in artifact_injection mirrors upstream-artifacts empty guard"
  - "test_frozen_surface_125 AST + git log --grep=125-04 path guard"

requirements-completed: [MOD-04]

duration: 4min
completed: 2026-08-09
---

# Phase 125 Plan 04: Adapter Injection + Frozen Surface Summary

**Three-point module-summary injection (blueprint evidence / conversation·MCP signal / research prompt) with relevance budget truncation, while keeping `repo_router_v2.py` and `mcp/` untouched**

## Performance

- **Duration:** 4 min
- **Started:** 2026-08-09T20:30:10Z
- **Completed:** 2026-08-09T20:34:26Z
- **Tasks:** 2 (TDD RED/GREEN ×2 → 4 commits)
- **Files modified:** 10

## Accomplishments

- Landed `module_summary_signal.py`: fail-soft load + relevance-ranked evidence append; scores unchanged
- Extended blueprint `_EVIDENCE_KEYS` with `module_summaries` (default `[]`); three-component identity still holds
- Wired post-charter signal into `repository_relevance` and `mcp_tools.views.RouteRepositoriesView`
- Added `render_module_summaries_section` + research prompt `## 模块摘要` with empty guard / sort / budget / truncated
- Frozen-surface guard green: AST bans router imports in new kernels; 125-04 commits exclude `repo_router_v2.py` and `mcp/`

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: module_summary_signal + evidence tests** - `37bbf045` (test)
2. **Task 1 GREEN: signal + blueprint evidence + conversation/MCP wiring** - `f1a2cd8f` (feat)
3. **Task 2 RED: prompt + frozen surface tests** - `008507b2` (test)
4. **Task 2 GREEN: research prompt budget truncate** - `5a0aa471` (feat)

**Plan metadata:** `ff8239ff` (docs: complete plan)

## Files Created/Modified

- `server/services/module_summary_signal.py` — aload + aapply; evidence-only; sampling logs
- `server/services/process_runtime/blueprint_route.py` — `module_summaries` evidence key + fail-soft fill
- `server/agents/tools/repository_relevance.py` — `_apply_module_summary_signal` after charter
- `server/mcp_tools/views.py` — RouteRepositories reason append (server-side only)
- `server/services/process_runtime/artifact_injection.py` — `render_module_summaries_section`
- `server/services/process_runtime/blueprint_research_adapter.py` — `_summarize_module_summaries` in research prompt
- Tests: signal / breakdown / prompt / frozen_surface_125 unskipped and green

## Decisions Made

- Keep v1 signal score-neutral (D-15); no fourth blueprint weight (D-14)
- Skip candidate supplement (discretion; not a gap)
- Prompt section consumes evidence already attached by blueprint_route; no second DB hop required at prompt time
- Concurrent dirty `repo_router_v2.py` / `mcp` left unstaged throughout

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- MOD-01…04 complete for Phase 125; ready for phase verification / milestone progress
- Frozen surfaces remain locked for Phase 126+ unless explicitly reopened

## Self-Check: PASSED

- `server/services/module_summary_signal.py` FOUND
- `server/tests/services/code_graph/test_frozen_surface_125.py` FOUND
- Commits `37bbf045` `f1a2cd8f` `008507b2` `5a0aa471` FOUND in git log
- `git log --grep=125-04 --name-only` contains neither `repo_router_v2.py` nor `mcp/` paths

---
*Phase: 125-community-summary*
*Completed: 2026-08-09*
