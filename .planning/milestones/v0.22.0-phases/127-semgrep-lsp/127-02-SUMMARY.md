---
phase: 127-semgrep-lsp
plan: 02
subsystem: infra
tags: [semgrep, dockerfile, securityfinding, settings, fernet, lsp-runtime]

requires:
  - phase: 127-semgrep-lsp
    provides: Wave 0 acceptance stubs + VALIDATION five-plan map
provides:
  - "/opt/semgrep + SEMGREP_BIN image env (Semgrep==1.172.0)"
  - "Node 22 + @vue/language-server@3.3.9 + typescript tsdk in server image"
  - "Go toolchain + gopls@v0.23.0 in server image"
  - "SEMGREP_* settings + SettingKeys.SEMGREP_APP_TOKEN / CONCURRENCY_SCAN_MAX"
  - "set_semgrep_app_token / get_semgrep_app_token Fernet helpers"
  - "SecurityFinding soft-ref model + migration 0014_securityfinding"
affects: [127-03, 127-04, 127-05]

tech-stack:
  added: [semgrep==1.172.0 (image-only), Node 22 LTS, @vue/language-server@3.3.9, typescript@7.0.2, Go 1.24.5, gopls@v0.23.0]
  patterns:
    - "Semgrep CLI isolated under /opt/semgrep; never in uv.lock / never import semgrep"
    - "Pro token via SystemSetting Fernet (encrypt_value + is_encrypted=True)"
    - "SecurityFinding soft-ref (repository FK only; no Symbol FK); message via prepare_finding_message"

key-files:
  created:
    - server/codegraph/migrations/0014_securityfinding.py
    - server/services/code_graph/semgrep_token.py
    - .planning/phases/127-semgrep-lsp/127-02-SUMMARY.md
  modified:
    - server/codegraph/models.py
    - server/system/models.py
    - server/friday/settings.py
    - server/Dockerfile
    - server/tests/codegraph/test_security_finding_model.py
    - server/tests/services/code_graph/test_semgrep_app_token.py
    - server/tests/codegraph/test_lsp_defaults_unchanged.py
    - server/tests/services/code_graph/test_dockerfile_semgrep_lsp_layers.py

key-decisions:
  - "EXTRACTOR_BACKENDS[go]=gopls as reopen target only; VOLAR/GOPLS kill-switches stay default=False (D-12)"
  - "Empty SEMGREP_APP_TOKEN deletes SystemSetting row → CE path"
  - "Image volume +400–550MB estimated; real docker images size deferred to CI"
  - "TAINT-01/03 and LSP-01 not marked complete — foundation only; scan/MR/LSP probe remain 127-03..05"

patterns-established:
  - "prepare_finding_message wraps redact_secrets_in_text for SecurityFinding.message write path"
  - "Dockerfile install layers must precede USER friday directive; tests ignore comment false-positives"

requirements-completed: []  # Foundation for TAINT-01/03 + LSP-01; full REQ closure in 127-03..05

duration: 7min
completed: 2026-08-10
---

# Phase 127 Plan 02: Semgrep/LSP Runtime Foundation Summary

**Independent Semgrep≥1.172.0 + Node/Go/volar/gopls image layers, Fernet SEMGREP_APP_TOKEN, and SecurityFinding soft-ref model — kill-switches still False**

## Performance

- **Duration:** ~7 min
- **Started:** 2026-08-09T22:11:17Z
- **Completed:** 2026-08-09T22:18:26Z
- **Tasks:** 3
- **Files modified:** 10

## Accomplishments

- Landed `SecurityFinding` (UUID PK, repository CASCADE, mr_key/fingerprint/scan_sha, default status `open`) with migration `0014_securityfinding` and `prepare_finding_message` redaction helper
- Added `SettingKeys.SEMGREP_APP_TOKEN` / `CONCURRENCY_SCAN_MAX` plus `set_semgrep_app_token` / `get_semgrep_app_token` (Fernet encrypt + `is_encrypted=True`; empty → CE)
- Exposed `SEMGREP_BIN` / `TIMEOUT` / `TASK_TIMEOUT` / `CONFIGS` (+ env token escape hatch); kept `VOLAR_BACKEND_ENABLED` / `GOPLS_BACKEND_ENABLED` at `default=False`
- Dockerfile runtime installs `/opt/semgrep`, Node 22, `@vue/language-server`+typescript, Go+gopls before `USER friday`, with build-time version probes
- Un-skipped Wave 0 Dockerfile / model / defaults tests owned by this plan — all green on scoped pytest

## Task Commits

Each task was committed atomically:

1. **Task 1: SecurityFinding + SettingKeys + SEMGREP_APP_TOKEN** - `77e71227` (test RED) + `96cc6215` (feat GREEN)
2. **Task 2: SEMGREP_* settings + kill-switch defaults** - `b6b0bdd7` (feat)
3. **Task 3: Dockerfile Semgrep + Node/Go/volar/gopls** - `b233b23b` (feat)

**Plan metadata:** `a50d8b19` / `533f8422` / `5b9519d3` (docs: complete plan + STATE hygiene)

## Files Created/Modified

- `server/codegraph/models.py` — `SecurityFinding` + `prepare_finding_message`
- `server/codegraph/migrations/0014_securityfinding.py` — ADD TABLE only
- `server/system/models.py` — `SEMGREP_APP_TOKEN` / `CONCURRENCY_SCAN_MAX` keys
- `server/services/code_graph/semgrep_token.py` — Fernet set/get helpers
- `server/friday/settings.py` — `SEMGREP_*`; `EXTRACTOR_BACKENDS["go"]="gopls"` reopen target
- `server/Dockerfile` — Semgrep/Node/Go/LSP layers + probes before `USER friday`
- `server/tests/codegraph/test_security_finding_model.py` — D-05 acceptance (unskipped in RED)
- `server/tests/services/code_graph/test_semgrep_app_token.py` — D-09 round-trip (unskipped in RED)
- `server/tests/codegraph/test_lsp_defaults_unchanged.py` — kill-switch + SEMGREP defaults
- `server/tests/services/code_graph/test_dockerfile_semgrep_lsp_layers.py` — static Dockerfile layers

## Decisions Made

- Declared `EXTRACTOR_BACKENDS["go"]="gopls"` as reopen target with explicit kill-switch comment; did **not** flip `GOPLS_BACKEND_ENABLED` / `VOLAR_BACKEND_ENABLED` defaults (D-12/D-16)
- Empty token deletes the SystemSetting row rather than storing plaintext empty with `is_encrypted=False`
- Image size recorded as **+400–550MB estimate; real `docker images` deferred to CI** (local build not run in this plan)
- Did **not** call `requirements.mark-complete` for TAINT-01/03 / LSP-01 — same lock as 127-01; foundation only

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Dockerfile comment contained `USER friday` and broke line-order assertions**
- **Found during:** Task 3
- **Issue:** Static test matched comment text as the `USER friday` directive, so install lines appeared “after” USER
- **Fix:** Reworded comment; tests resolve the real `USER friday` directive (skip `#` lines) and pin install needles (`semgrep==1.172`, `@vue/language-server@`, `gopls@v0.23`)
- **Files modified:** `server/Dockerfile`, `server/tests/services/code_graph/test_dockerfile_semgrep_lsp_layers.py`
- **Verification:** Dockerfile layer tests green
- **Committed in:** `b233b23b`

**2. [Rule 3 - Blocking] Scoped pytest used isolated SQLite when Postgres test DB was contested**
- **Found during:** Task 1
- **Issue:** Concurrent session held `test_friday` on Postgres (`database already exists` / `being accessed by other users`)
- **Fix:** Ran plan budget tests with `DATABASE_URL=sqlite:////tmp/friday-127-02-test.db` (no production/settings change)
- **Files modified:** none
- **Verification:** 5+7 scoped tests passed under SQLite
- **Committed in:** n/a (test env only)

---

**Total deviations:** 2 auto-fixed (1 bug, 1 blocking)
**Impact on plan:** Necessary for correct Dockerfile acceptance and reliable local verification; no scope creep.

## Issues Encountered

- Concurrent WIP left `server/friday/settings.py` (REPO_ROUTER candidate default) and `repo_router_v2.py` / `mcp` dirty — staged only 127-02 hunks; freeze surfaces untouched in commits

## User Setup Required

None for CE path. Optional Pro: set encrypted `SEMGREP_APP_TOKEN` via `set_semgrep_app_token` (or env escape hatch `SEMGREP_APP_TOKEN` when SystemSetting empty). Rebuild server image to pick up Semgrep/Node/Go layers.

## Next Phase Readiness

- 127-03 can consume `SEMGREP_BIN` / token getter / `SecurityFinding` / `CONCURRENCY_SCAN_MAX` for CLI scan + durable enqueue
- LSP probe/orphan reap (127-05) can assume Node/gopls binaries exist in image once rebuilt
- Kill-switch defaults remain False until benchmark gate (D-16)

## Threat Flags

None beyond plan register — no new public network endpoints; token path matches T-127-01 mitigation.

## Self-Check: PASSED

- FOUND: `server/codegraph/models.py` (`SecurityFinding`)
- FOUND: `server/codegraph/migrations/0014_securityfinding.py`
- FOUND: `server/services/code_graph/semgrep_token.py`
- FOUND: `server/Dockerfile` (`/opt/semgrep`, `vue/language-server`, `gopls`)
- FOUND commits: `77e71227`, `96cc6215`, `b6b0bdd7`, `b233b23b`
- VERIFIED: `VOLAR`/`GOPLS` `default=False`; no `semgrep` in `server/uv.lock` / `pyproject.toml`
- VERIFIED: commits do not touch `repo_router_v2.py` or `mcp/`

---
*Phase: 127-semgrep-lsp*
*Completed: 2026-08-10*
