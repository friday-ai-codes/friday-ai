---
phase: 126-process-rename-skills
plan: 02
subsystem: code_graph
tags: [process-trace, bfs, durable, queue-graph, community-chain]

requires:
  - phase: 126-process-rename-skills
    provides: Wave 0 Nyquist stubs for ProcessTrace / BFS / enqueue / frozen_surface_126
  - phase: 125-community-module-summary
    provides: SymbolCommunity + QUEUE_GRAPH community enqueue / rebuild patterns
provides:
  - ProcessTrace ORM + 0013_processtrace migration (pure add-table)
  - Forward BFS kernel with depth/branching/minSteps/conf gates + cycle/async markers
  - rebuild_processes full delete-rebuild + community intra/cross/unknown classify
  - enqueue_process_rebuild + durable_process_rebuild + community success chain
affects:
  - 126-03 process query MCP/agents shells + affected_processes backfill
  - impact_report execution-flow narrative (via ProcessTrace rows)

tech-stack:
  added: []
  patterns:
    - "ProcessTrace JSON entry_endpoint snapshot (no Endpoint FK); steps soft-ref symbol_id"
    - "Forward BFS via graph.successors + MultiDiGraph edge attrs; no nx.bfs_layers"
    - "QUEUE_GRAPH idempotency_key=process:{repo}:{branch}; community success best-effort chain"

key-files:
  created:
    - server/codegraph/migrations/0013_processtrace.py
    - server/services/code_graph/process_trace.py
    - server/services/process_enqueue.py
  modified:
    - server/codegraph/models.py
    - server/friday/settings.py
    - server/durable/tasks.py
    - server/durable/tasks_impl.py
    - server/durable/handlers.py
    - server/tests/codegraph/test_process_trace_model.py
    - server/tests/services/code_graph/test_process_trace.py
    - server/tests/services/code_graph/test_process_enqueue.py

key-decisions:
  - "ORM class locked to ProcessTrace; community_class empty string + degradation for unknown"
  - "Injected MultiDiGraph detected via isinstance before getattr(.graph) to avoid NX attr dict pitfall"
  - "Durable commit staged process-only against HEAD; concurrent charter WIP restored to working tree"

patterns-established:
  - "process rebuild mirrors community: enqueue helper + QUEUE_GRAPH task + handlers register + tasks_impl job"
  - "BFS hard gates exported as module Final constants for acceptance rg"

requirements-completed: [EXEC-01, EXEC-02]

duration: 6min
completed: 2026-08-10
---

# Phase 126 Plan 02: ProcessTrace BFS + Durable Rebuild Summary

**ProcessTrace add-table + forward BFS rebuild kernel (depth 10 / branching 4 / minSteps 3 / conf≥0.5) with QUEUE_GRAPH durable task chained after community success.**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-08-09T21:08:36Z
- **Completed:** 2026-08-09T21:14:50Z
- **Tasks:** 3/3
- **Files modified:** 11

## Accomplishments

- `ProcessTrace` model + `0013_processtrace` migration (no `Process` class, no Endpoint FK)
- Forward BFS with cycle / async_dispatch boundary / community intra|cross|unknown classify
- `enqueue_process_rebuild` → `durable_process_rebuild` on `QUEUE_GRAPH`; community success path chains enqueue

## Task Commits

Each task was committed atomically:

1. **Task 1: ProcessTrace 模型 + migration** — RED `1329b30c` (test) → GREEN `a7f8ea33` (feat)
2. **Task 2: 正向 BFS 内核 + rebuild** — RED `4ff937c4` (test) → GREEN `b865144b` (feat)
3. **Task 3: durable enqueue + 社区成功链式** — RED `757345f0` (test) → GREEN `53e4868d` (feat)

## Files Created/Modified

- `server/codegraph/models.py` — `ProcessTrace` + `CommunityClass` TextChoices; `__all__` export
- `server/codegraph/migrations/0013_processtrace.py` — pure add-table migration
- `server/services/code_graph/process_trace.py` — BFS / classify / `rebuild_processes`
- `server/services/process_enqueue.py` — `enqueue_process_rebuild` swallow-on-fail helper
- `server/durable/tasks.py` — `durable_process_rebuild` procrastinate shell
- `server/durable/tasks_impl.py` — `run_process_rebuild` + community success chain
- `server/durable/handlers.py` — in-process handler registration
- `server/friday/settings.py` — `CODE_GRAPH_PROCESS_MIN` / `CODE_GRAPH_PROCESS_MAX_CAP`
- Wave 0 stubs unskipped/rewritten for model, BFS, enqueue

## Decisions Made

- `process_key` = `{METHOD}:{normalize(url_path)}`; `name` = `{METHOD} {url_path}`
- Unknown community → empty `community_class` + `degradation.community_class_unknown` (no fabrication)
- Concurrent charter durable WIP left in working tree; task-3 commit applied process-only on HEAD bases then restored WT

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] NetworkX `.graph` attr swallowed injected MultiDiGraph**
- **Found during:** Task 2 (`test_rebuild_processes_persists_and_filters`)
- **Issue:** `getattr(code_graph, "graph", code_graph)` returns NX graph-level dict when callers inject a raw `MultiDiGraph`
- **Fix:** Detect NX graph types via `isinstance` before getattr
- **Files modified:** `server/services/code_graph/process_trace.py`
- **Committed in:** `b865144b`

**2. [Rule 1 - Bug] Test helper unpacked node attrs positionally**
- **Found during:** Task 2 RED→GREEN
- **Issue:** `g.add_node(*_node(...))` passed attrs dict as positional → NX TypeError
- **Fix:** `_add_node(g, nid, **attrs)` helper
- **Files modified:** `server/tests/services/code_graph/test_process_trace.py`
- **Committed in:** `b865144b`

**Total deviations:** 2 auto-fixed (Rule 1 ×2)
**Impact on plan:** Correctness only; no scope creep.

## Issues Encountered

None beyond the auto-fixed NX getattr / test helper issues. Concurrent dirty durable/settings files required selective staging so charter WIP was not committed into 126-02.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- EXEC-01 / EXEC-02 persistence+classification kernel ready for 126-03 MCP/agents query shells
- Apply migration `0013_processtrace` in deploy environments before querying ProcessTrace
- Frozen surfaces (`repo_router_v2.py`, `mcp/`) untouched

## TDD Gate Compliance

- Task 1: RED `1329b30c` → GREEN `a7f8ea33`
- Task 2: RED `4ff937c4` → GREEN `b865144b`
- Task 3: RED `757345f0` → GREEN `53e4868d`

## Self-Check: PASSED

- [x] `server/codegraph/models.py` has `class ProcessTrace`; no `class Process`
- [x] `server/codegraph/migrations/0013_processtrace.py` exists
- [x] `server/services/code_graph/process_trace.py` exports BFS constants + `rebuild_processes`
- [x] `server/services/process_enqueue.py` exists with `process:{repository_id}:{branch}`
- [x] Commits `1329b30c` `a7f8ea33` `4ff937c4` `b865144b` `757345f0` `53e4868d` present
- [x] Scoped pytest: model + process_trace + process_enqueue + frozen_surface_126 = 14 passed
- [x] No `repo_router_v2.py` / `mcp/` in plan commits

---
*Phase: 126-process-rename-skills*
*Completed: 2026-08-10*
