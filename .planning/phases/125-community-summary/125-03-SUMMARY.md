---
phase: 125-community-summary
plan: 03
subsystem: code_graph
tags: [module-summary, jaccard, llm, call-source, fingerprint]

requires:
  - phase: 125-01
    provides: CallSource.MODULE_SUMMARY dual-registration
  - phase: 125-02
    provides: SymbolCommunity + Louvain community.py + summary_fn hook
provides:
  - "module_summary.py agenerate/render with CallSource.MODULE_SUMMARY"
  - "Fingerprint short-circuit + greedy Jaccard≥0.8 summary reuse"
  - "test_rebuild_twice_zero_llm green (unchanged rebuild×2 → LLM=0)"
  - "durable run_community_rebuild wires agenerate_module_summary"
affects:
  - 125-04 (adapter injection consuming SymbolCommunity.summary)

tech-stack:
  added: []
  patterns:
    - "D-09/D-10: use_call_source(MODULE_SUMMARY); metadata-only prompt; JSON summary + render_module_summary"
    - "D-06/D-07/D-08: fingerprint short-circuit → Jaccard greedy; empty summary retries; serial LLM"
    - "Surgical staging of dirty durable/tasks_impl.py around concurrent charter WIP"

key-files:
  created:
    - server/services/code_graph/module_summary.py
  modified:
    - server/services/code_graph/community.py
    - server/durable/tasks_impl.py
    - server/tests/services/code_graph/test_module_summary.py
    - server/tests/services/code_graph/test_community.py

key-decisions:
  - "summary stored as JSON text (key_files/entry_points/responsibility); render_module_summary is sole consumer render"
  - "JACCARD_THRESHOLD stays module constant 0.8 (calibration deferred)"
  - "rebuild_communities summary_fn=None means no LLM; durable always passes agenerate_module_summary"
  - "summary_fn may be sync or async; reconcile awaits awaitables"

patterns-established:
  - "Reconcile before LLM: fingerprint hit with non-empty summary skips Jaccard entirely"
  - "TDD RED/GREEN for Wave 0 stub unskip; async tests use acreate/aget"

requirements-completed: [MOD-02, MOD-03]

duration: 8min
completed: 2026-08-09
---

# Phase 125 Plan 03: Module Summary + Jaccard Skip Summary

**Metadata-only MODULE_SUMMARY LLM helper plus fingerprint/Jaccard reconcile so unchanged rebuild×2 yields zero LLM calls**

## Performance

- **Duration:** 8 min
- **Started:** 2026-08-09T20:21:27Z
- **Completed:** 2026-08-09T20:29:00Z
- **Tasks:** 2 (TDD RED/GREEN ×2 → 4 commits)
- **Files modified:** 5

## Accomplishments

- Landed `module_summary.py`: `agenerate_module_summary` under `use_call_source(CallSource.MODULE_SUMMARY)`, metadata-only prompt, fail-soft `None`, `render_module_summary`
- Extended `rebuild_communities` with fingerprint short-circuit, greedy Jaccard≥0.8 reuse, empty-summary retry, serial summary_fn; unclustered/size&lt;5 never call LLM
- Wired `run_community_rebuild` → `summary_fn=agenerate_module_summary` (surgical commit avoiding charter WIP)
- Unskipped and greened MOD-02/MOD-03 acceptance including `test_rebuild_twice_zero_llm`

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: module_summary acceptance tests** - `4ea2932f` (test)
2. **Task 1 GREEN: module_summary LLM helper** - `550815c2` (feat)
3. **Task 2 RED: Jaccard / rebuild×2 LLM=0 tests** - `63520014` (test)
4. **Task 2 GREEN: reconcile + durable summary_fn** - `88106a99` (feat)

**Plan metadata:** (see final docs commit after this SUMMARY)

## Files Created/Modified

- `server/services/code_graph/module_summary.py` — LLM helper + render (not in barrel)
- `server/services/code_graph/community.py` — `_apply_summary_reconcile` + async summary_fn
- `server/durable/tasks_impl.py` — community rebuild passes `agenerate_module_summary` only
- `server/tests/services/code_graph/test_module_summary.py` — 4 MOD-03 cases green
- `server/tests/services/code_graph/test_community.py` — Jaccard / rebuild×2 / retry / unclustered green

## Decisions Made

- Store structured summary as JSON text; `render_module_summary` is the single markdown renderer
- Keep `JACCARD_THRESHOLD = 0.8` as module constant; no SystemSetting in this plan
- Durable always injects real `agenerate_module_summary`; unit tests inject counting fakes
- Concurrent charter WIP in `tasks_impl.py` left unstaged via HEAD-patch surgical commit

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] FakeChatModel ainvoke assignment invalid under pydantic**
- **Found during:** Task 1 GREEN
- **Issue:** Test assigned `fake.ainvoke = AsyncMock(...)` → pydantic `ValueError`
- **Fix:** Use plain `_BrokenModel` with `ainvoke`/`bind` methods
- **Files modified:** `server/tests/services/code_graph/test_module_summary.py`
- **Commit:** `550815c2`

**2. [Rule 1 - Bug] Sync ORM create in async tests**
- **Found during:** Task 2 GREEN
- **Issue:** `SymbolCommunity.objects.create` in `@pytest.mark.asyncio` → `SynchronousOnlyOperation`
- **Fix:** Switch seed rows to `acreate` / `adelete`
- **Files modified:** `server/tests/services/code_graph/test_community.py`
- **Commit:** `88106a99` (test fix landed with GREEN)

## Issues Encountered

- Working tree had concurrent uncommitted charter durable changes; community hunks committed without staging charter or frozen `repo_router_v2.py` / `mcp/`
- `gsd-tools` not on PATH; use `node .cursor/gsd-core/bin/gsd-tools.cjs`

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- 125-04 can inject `SymbolCommunity.summary` via adapters (blueprint evidence / signal / research prompt)
- Frozen surfaces untouched in all 125-03 commits
- Acceptance iron rule proven: rebuild×2 unchanged → LLM call count flat (`test_rebuild_twice_zero_llm`)

## Self-Check: PASSED

- [x] `server/services/code_graph/module_summary.py` contains `use_call_source(CallSource.MODULE_SUMMARY)`
- [x] `server/services/code_graph/community.py` contains `JACCARD_THRESHOLD = 0.8` and `match_communities_greedy` / `summaries_skipped`
- [x] `test_rebuild_twice_zero_llm` present and not skipped
- [x] Commits `4ea2932f`, `550815c2`, `63520014`, `88106a99` present
- [x] No commit includes `repo_router_v2.py` or `mcp/`
- [x] Scoped pytest: 12 passed (`test_module_summary.py` + `test_community.py`)

---
*Phase: 125-community-summary*
*Completed: 2026-08-09*
