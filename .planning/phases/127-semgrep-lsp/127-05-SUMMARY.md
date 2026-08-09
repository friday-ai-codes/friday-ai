---
phase: 127-semgrep-lsp
plan: 05
subsystem: codegraph.lsp
tags: [lsp-orphan, lsp-baseline, impact03-revisit, kill-switch-gate, d16, d17]

requires:
  - phase: 127-semgrep-lsp
    provides: Node/Go/volar/gopls image runtime + go_check/node_check (127-02)
  - phase: 127-semgrep-lsp
    provides: Semgrep MR hang-point complete so Wave 4 can close LSP-01 (127-04)
provides:
  - "reap_orphan_lsp_processes + lsp_process_reaped (sampling)"
  - "measure_lsp_baseline before/after JSON + D-16 gate record (keep False)"
  - "revisit_impact03_samples honest defer when CrossRepoApiCall=0 (D-17)"
  - "impact03-revisit.md + lsp-baseline-report.json artifacts"
affects: [v0.22.0-milestone-close, IMPACT-03-followup]

tech-stack:
  added: []
  patterns:
    - "psutil cmdline orphan reap excluding live supervisor PIDs; best-effort never raises"
    - "baseline measurement must not mutate settings kill-switch defaults"
    - "IMPACT-03: count==0 honest defer OR count>0 four-branch; never claim verified without samples"

key-files:
  created:
    - server/codegraph/lsp/orphan_reap.py
    - server/codegraph/management/commands/measure_lsp_baseline.py
    - server/codegraph/management/commands/revisit_impact03_samples.py
    - .planning/phases/127-semgrep-lsp/lsp-baseline-report.json
    - .planning/phases/127-semgrep-lsp/impact03-revisit.md
    - .planning/phases/127-semgrep-lsp/127-05-SUMMARY.md
  modified:
    - server/codegraph/lsp/supervisor.py
    - server/codegraph/lsp/volar_pool.py
    - server/codegraph/lsp/__init__.py
    - server/codegraph/lsp/tests/test_orphan_reap.py
    - server/tests/codegraph/test_revisit_impact03.py

key-decisions:
  - "D-16: KEEP VOLAR_BACKEND_ENABLED/GOPLS_BACKEND_ENABLED default=False — baseline lacks complete index quality/latency delta; recommend_flip_defaults=false"
  - "D-17: IMPACT-03 honest defer — CrossRepoApiCall/ApiCallSite/ApiWrapper all 0 in this environment; not verified on real samples"
  - "D-12/D-14: orphan reap wired on pool/supervisor shutdown; kill-switch unchanged"

patterns-established:
  - "Lifecycle finally: supervisor.stop then reap_orphan_lsp_processes(live_pids=set())"
  - "Management commands use category=caller component=codegraph.lsp initiated_by_user_id=system"

requirements-completed: [LSP-01]

duration: 6min
completed: 2026-08-10
---

# Phase 127 Plan 05: LSP Orphan Reap + Baseline + IMPACT-03 Summary

**LSP orphan reap + reproducible baseline JSON with D-16 keep-False gate, and IMPACT-03 honest defer (CrossRepoApiCall=0) — kill-switches stay False**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-08-09T22:32:41Z
- **Completed:** 2026-08-09T22:38:08Z
- **Tasks:** 2
- **Files modified:** 11

## Accomplishments

- Landed `orphan_reap.reap_orphan_lsp_processes` (psutil match `gopls` / `vue-language-server` / `typescript-language-server`, live-set exclusion, `lsp_process_reaped` sampling event)
- Wired best-effort reap after `VolarPool.shutdown_all`, `shutdown_all_supervisors`, and atexit cleanup; exposed `LspSupervisor.live_pid`
- Added `measure_lsp_baseline` → `.planning/phases/127-semgrep-lsp/lsp-baseline-report.json` with before/after + `d16_gate.recommend_flip_defaults=false`
- Added `revisit_impact03_samples` → `impact03-revisit.md` **诚实延期** path (real samples = 0)
- Unskipped Wave 0 orphan + IMPACT-03 tests; defaults test still green

## Task Commits

Each task was committed atomically (TDD RED→GREEN):

1. **Task 1: LSP orphan reap + lifecycle finally** - `2724b9d9` (test RED) + `82fd522c` (feat GREEN) + `68321656` (test polish)
2. **Task 2: baseline + IMPACT-03 revisit/defer + D-16 gate** - `58e7edd4` (test RED) + `9e484e0d` (feat GREEN + report artifacts)

**Plan metadata:** `6a8a3fa4` (docs: complete plan; prior `81ed8828` coalesced STATE/ROADMAP)

## Files Created/Modified

- `server/codegraph/lsp/orphan_reap.py` — orphan process reap
- `server/codegraph/lsp/supervisor.py` — `live_pid()`
- `server/codegraph/lsp/volar_pool.py` / `__init__.py` — shutdown + reap
- `server/codegraph/management/commands/measure_lsp_baseline.py` — D-15 baseline command
- `server/codegraph/management/commands/revisit_impact03_samples.py` — D-17 revisit/defer
- `.planning/phases/127-semgrep-lsp/lsp-baseline-report.json` — reproducible baseline
- `.planning/phases/127-semgrep-lsp/impact03-revisit.md` — honest defer record
- Wave 0 tests unskipped under `test_orphan_reap.py` / `test_revisit_impact03.py`

## Decisions Made

### D-16 — 默认翻转门禁（保持 False）

基准报告 `d16_gate.recommend_flip_defaults=false`：缺少完整 before/after 索引质量与延迟差分（或等价可验收证据），**不得**以镜像已装好为唯一理由翻默认。

**结论：建议保持** `VOLAR_BACKEND_ENABLED=False` / `GOPLS_BACKEND_ENABLED=False`。settings 默认字面量未改；`test_lsp_defaults_unchanged` 绿。

### D-17 — IMPACT-03（诚实延期）

本环境真实 `CrossRepoApiCall` / `ApiCallSite` / `ApiWrapper` 均为 **0** → 写入诚实延期，**禁止宣称跨仓 impact 已验证**。Follow-up：env 打开 kill-switch 后在代表性前后端仓重建索引，再跑 `revisit_impact03_samples`。

## Deviations from Plan

### Auto-fixed Issues

None - plan executed as written (orphan reap + baseline + honest defer). Concurrent executor coalesced some GREEN file writes into the same feat commits; outcomes match acceptance criteria.

## Threat Flags

None beyond plan register (T-127-01..05 mitigated: no credentials in baseline JSON; skip-on-missing; honest defer prevents spoofed IMPACT-03 claims; orphan reap mitigates LSP DoS leftovers).

## Known Stubs

- `measure_lsp_baseline` leaves full cold/warm index wall-clock and per-metric LSP deltas as `null` until a full indexer run against `--vue-repo` / `--go-repo` — intentional; command is re-runnable and documents fields.
- IMPACT-03 `peer_permission_denied` runtime path needs a user context on real samples — deferred with honest defer when count=0.

## Verification Results

```text
cd server && GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False \
  uv run pytest codegraph/lsp/tests/test_orphan_reap.py \
  tests/codegraph/test_revisit_impact03.py \
  tests/codegraph/test_lsp_defaults_unchanged.py -q
# → 6 passed
```

Hard locks confirmed:

- VOLAR/GOPLS defaults still `default=False`
- Semgrep not in `server/uv.lock` / `pyproject.toml`
- No edits to `repo_router_v2.py` or `mcp/` for this plan

## Next Phase Readiness

- Phase 127 plans 01–05 complete for Semgrep + LSP-01 delivery surface
- Follow-up (not this plan): data-driven flip only after filled baseline deltas; IMPACT-03 four-branch on real samples after LSP-enabled reindex

## Self-Check: PASSED

- FOUND: `.planning/phases/127-semgrep-lsp/127-05-SUMMARY.md`
- FOUND: `orphan_reap.py`, `lsp-baseline-report.json`, `impact03-revisit.md`
- FOUND commits: `2724b9d9`, `82fd522c`, `68321656`, `58e7edd4`, `9e484e0d`
- Defaults still False; Semgrep not in uv.lock; frozen surfaces untouched by this plan

## Self-Check: PASSED

- Artifacts found: orphan_reap.py, measure_lsp_baseline.py, revisit_impact03_samples.py, lsp-baseline-report.json, impact03-revisit.md, 127-05-SUMMARY.md
- Commits found: `82fd522c`, `9e484e0d` (plus RED/polish `2724b9d9`, `68321656`, `58e7edd4`)
- VOLAR/GOPLS `default=False` confirmed; IMPACT-03 disposition = honest defer
