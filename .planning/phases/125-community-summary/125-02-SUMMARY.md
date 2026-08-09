---
phase: 125-community-summary
plan: 02
subsystem: code_graph
tags: [community, louvain, durable, symbol-community, fingerprint]

requires:
  - phase: 125-01
    provides: CallSource.MODULE_SUMMARY dual-registration + Wave 0 skip stubs
  - phase: 121-graph-base
    provides: get_graph_service barrel + frozen MultiDiGraph + QUEUE_GRAPH
provides:
  - "SymbolCommunity model + 0011 ADD TABLE migration (soft-ref members)"
  - "community.py Louvain/fingerprint/Jaccard helpers + full-replace rebuild"
  - "enqueue_community_rebuild + durable_community_rebuild on QUEUE_GRAPH"
  - "graph_builder / code_relations hooks enqueue-only (no inline Louvain)"
affects:
  - 125-03 (module_summary LLM + Jaccard skip + rebuild×2 LLM=0)
  - 125-04 (adapter injection consuming SymbolCommunity.summary)

tech-stack:
  added: []
  patterns:
    - "D-01/D-02: independent SymbolCommunity table; members JSON soft-ref; Symbol untouched"
    - "D-04: LOUVAIN_SEED=42 + sorted undirected projection; WCC<5 → unclustered:{top_dir}"
    - "D-03: hooks only enqueue; worker bind_task_context + get_graph_service"
    - "ORM exception peer of loader: community.py not in barrel __all__ / _INTERNAL_SUBMODULES"

key-files:
  created:
    - server/codegraph/migrations/0011_symbolcommunity.py
    - server/services/code_graph/community.py
    - server/services/community_enqueue.py
  modified:
    - server/codegraph/models.py
    - server/durable/tasks.py
    - server/durable/tasks_impl.py
    - server/durable/handlers.py
    - server/services/graph_builder.py
    - server/code_relations/tasks.py
    - server/tests/codegraph/test_symbol_community_model.py
    - server/tests/services/code_graph/test_community.py
    - server/tests/services/code_graph/test_community_enqueue.py

key-decisions:
  - "community_key = member_fingerprint[:16] (fp-derived; unclustered uses unclustered:{top_dir}:{fp[:8]})"
  - "summary TextField nullable JSON-capable; summary_fn hook left for 125-03 (default None)"
  - "Durable new task name durable_community_rebuild (not a durable_graph payload branch)"
  - "members/top_files truncated (MAX_MEMBERS_STORED=500 / MAX_TOP_FILES_STORED=40) for T-125-04"

patterns-established:
  - "Surgical staging around concurrent dirty durable charter WIP — commit community-only hunks"
  - "Fingerprint/Jaccard pure functions land in 125-02 even if skip logic waits for 125-03"

requirements-completed: [MOD-01]

duration: 4min
completed: 2026-08-09
---

# Phase 125 Plan 02: SymbolCommunity + Louvain Enqueue Summary

**SymbolCommunity ADD-TABLE model with soft-ref members, fixed-seed Louvain rebuild via get_graph_service, and QUEUE_GRAPH durable enqueue from both graph/edge hooks**

## Performance

- **Duration:** 4 min
- **Started:** 2026-08-09T20:16:23Z
- **Completed:** 2026-08-09T20:20:00Z
- **Tasks:** 2 (TDD RED/GREEN ×2 → 4 commits)
- **Files modified:** 12

## Accomplishments

- Landed `SymbolCommunity` (D-01/D-02): pure CreateModel migration; Symbol has no community FK/M2M; members JSON soft-ref `symbol_id`
- Implemented `community.py`: `LOUVAIN_SEED=42`, sorted undirected projection, WCC&lt;5 → `unclustered`, fingerprint/Jaccard helpers, full-delete/full-create persist, observability lifecycle
- Wired `enqueue_community_rebuild` → `durable_community_rebuild` on `QUEUE_GRAPH` with `idempotency_key=community:{repo}:{branch}`; hooks in `graph_builder` / `code_relations` enqueue-only
- Unskipped 125-02 Wave 0 stubs (model + Louvain/fingerprint/enqueue); left 125-03 stubs skipped

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: SymbolCommunity model contract tests** - `e12e39db` (test)
2. **Task 1 GREEN: SymbolCommunity model + migration** - `94d145e0` (feat)
3. **Task 2 RED: Louvain/fingerprint/enqueue acceptance tests** - `6e8474f8` (test)
4. **Task 2 GREEN: community rebuild + QUEUE_GRAPH hooks** - `736b063d` (feat)

**Plan metadata:** see final docs commit after this SUMMARY

## Files Created/Modified

- `server/codegraph/models.py` — `SymbolCommunity` model; `__all__` export
- `server/codegraph/migrations/0011_symbolcommunity.py` — CreateModel + indexes only
- `server/services/code_graph/community.py` — Louvain/fingerprint/rebuild ORM service
- `server/services/community_enqueue.py` — best-effort durable defer helper
- `server/durable/tasks.py` — `durable_community_rebuild` task shell
- `server/durable/tasks_impl.py` — `run_community_rebuild` + `bind_task_context`
- `server/durable/handlers.py` — in-process handler registration
- `server/services/graph_builder.py` — enqueue after `invalidate_repository`
- `server/code_relations/tasks.py` — enqueue after edge-build invalidate
- `server/tests/codegraph/test_symbol_community_model.py` — unskipped contract tests
- `server/tests/services/code_graph/test_community.py` — Louvain/fingerprint/AST tests
- `server/tests/services/code_graph/test_community_enqueue.py` — enqueue + hook source tests

## Decisions Made

- `community_key` derived from fingerprint (`fp[:16]`); unclustered keys include top-dir + short fp for uniqueness
- New durable task name (not branching `durable_graph` / `run_graph`)
- `summary_fn` optional parameter on `rebuild_communities` for 125-03; this plan persists empty summaries
- Truncation caps on members/top_files before ORM write (T-125-04)
- Concurrent dirty charter durable WIP left unstaged via surgical community-only commit

## Deviations from Plan

None - plan executed exactly as written.

(Surgical staging of durable files to avoid committing concurrent charter WIP is operational hygiene, not a plan deviation.)

## Issues Encountered

- `gsd-tools` not on PATH; used `node .cursor/gsd-core/bin/gsd-tools.cjs` for state updates
- Working tree had concurrent uncommitted charter durable changes; community hunks committed without staging charter or frozen `repo_router_v2.py` / `mcp/`

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- 125-03 can wire `module_summary` LLM via `summary_fn` / Jaccard skip on top of existing fingerprint helpers
- Rebuild×2 LLM=0 stubs remain skipped until 125-03
- Frozen surfaces untouched in all 125-02 commits

## Self-Check: PASSED

- [x] `server/codegraph/models.py` contains `class SymbolCommunity`
- [x] `server/codegraph/migrations/0011_symbolcommunity.py` exists with `CreateModel`
- [x] `server/services/code_graph/community.py` contains `LOUVAIN_SEED`
- [x] `server/services/community_enqueue.py` contains `durable_community_rebuild`
- [x] Commits `e12e39db`, `94d145e0`, `6e8474f8`, `736b063d` present
- [x] No commit includes `repo_router_v2.py` or `mcp/`
- [x] Scoped pytest: 10 passed

---
*Phase: 125-community-summary*
*Completed: 2026-08-09*
