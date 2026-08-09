---
phase: 123-detect-changes
verified: 2026-08-09T19:15:00Z
status: passed
score: 8/8 must-haves verified
overrides_applied: 0
re_verification: false
---

# Phase 123: detect_changes 工具本体 Verification Report

**Phase Goal:** 用户/agent 对分支 diff 一键得到「这次改动碰了哪些符号、波及多大」——受影响符号清单 + 批量 impact，行号与 Symbol 同源对齐、rename 不误报

**Verified:** 2026-08-09T19:15:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | 对分支 diff 执行 detect_changes 得到受影响符号清单（changeType / 行数 / file:line）与批量 impact；diff base 强制锚定 `last_indexed_commit_sha` | ✓ VERIFIED | `run_detect_changes` pins base via `ensure_mirror_sha(indexed_sha)` + hard-reject if sha ≠ waterline (`code_graph_tools.py:1155-1177`); kernel emits `changeType`/`lines_changed`/`file_line` (`detect_changes.py:232-240`); sequential `run_impact(symbol_id=…)` (`code_graph_tools.py:1370-1384`); orchestrator tests assert pin + impact batch |
| 2 | compare + base_ref（MR diff）可用；`git diff -M` / `--find-renames` 识别 rename；纯 rename 不双报 deleted+added | ✓ VERIFIED | `base_ref` only declared on envelope, never used as diff left (`code_graph_tools.py:1074,1431-1432`; `test_base_ref_declarative_only`); `diff_mirror` argv `diff --unified=0 --find-renames` (`repo_mirror.py:418-425`); kernel pure-rename → single `renamed` (`test_rename_single_entry_not_delete_add`) |
| 3 | 输出带索引 staleness 声明（`as_of`）；索引落后仍可算并声明可信度 | ✓ VERIFIED | Success envelope includes `staleness` from `staleness_payload` + behind≥20 declaration boost (`code_graph_tools.py:1400-1407`); `test_staleness_behind_still_ok` asserts `ok=True` + `as_of` + `behind_commits=42` |
| 4 | MCP / 对话双面薄壳共用 `run_detect_changes`，data 零加工（D-13） | ✓ VERIFIED | `DetectChangesView` → `run_detect_changes` passthrough + `run_id` (`views.py:1430-1450`); `_detect_changes_impl` → `run_detect_changes` (`graph_tools.py:807-819`); `test_two_surfaces_same_payload_detect_changes` green |
| 5 | CR-01：diff base 硬 pin 索引水位，禁止 tip/cache 回退冒充 base | ✓ VERIFIED | Production uses `ensure_mirror_sha` not branch `ensure_mirror_commit` for base; mismatch → `mirror_fetch_failed`; `ensure_mirror_commit` skips tip TTL cache when `pin_sha` set but ≠ cached tip (`repo_mirror.py:277-285`); orchestrator asserts `ensure_calls[0]` is sha-pin |
| 6 | WR-01：大小写 40 位 SHA 走 `ensure_mirror_sha` | ✓ VERIFIED | `_FULL_SHA_RE` is `re.IGNORECASE`; head path lowercases before pin (`code_graph_tools.py:111,1179-1181`) |
| 7 | WR-02：rename 有 hunk 但未命中符号 → 文件级 renamed，不整文件灌种子 | ✓ VERIFIED | Kernel branch `if not hit_uids: symbols=[]` (`detect_changes.py:347-358`); `test_rename_with_hunks_no_symbol_hit_is_file_level_only` |
| 8 | WR-03：超阈值时 `files[].symbols` 清空 + `file_level_only` | ✓ VERIFIED | Truncation collapses symbols to `[]` and sets `summary.file_level_only=True` (`code_graph_tools.py:1352-1416`); orchestrator asserts empty symbol lists |

**Score:** 8/8 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `server/services/repo_mirror.py` | `DiffMirrorResult` / `diff_mirror` / `ensure_mirror_sha` | ✓ VERIFIED | ~755 lines; two-dot + `--find-renames`; sha pin without `refs/heads/{sha}` |
| `server/services/code_graph/detect_changes.py` | Pure overlap kernel (zero ORM) | ✓ VERIFIED | ~495 lines; `ranges_overlap` / `parse_unified_diff` / `detect_affected_symbols` / `is_formatting_only` |
| `server/services/code_graph_tools.py` | `run_detect_changes` + `tool_trace_payload(detect_changes)` | ✓ VERIFIED | Orchestration + counts-only trace branch |
| `server/mcp_tools/views.py` | `DetectChangesView` | ✓ VERIFIED | Thin shell; wired to `run_detect_changes` |
| `server/mcp_tools/serializers.py` | `DetectChangesRequestSerializer` + schema snapshot | ✓ VERIFIED | `compare` required; `base_ref` optional; snapshot key present |
| `server/mcp_tools/urls.py` | `tools/detect_changes/` | ✓ VERIFIED | Route registered |
| `server/agents/tools/schemas/graph_tools.py` | `DetectChangesToolInput` | ✓ VERIFIED | Field table matches MCP |
| `server/agents/tools/graph_tools.py` | `@tool detect_changes` | ✓ VERIFIED | Delegates via `_detect_changes_impl` |
| `server/agents/chat_runner.py` | `_INDEXED_TOOL_NAMES` includes `detect_changes` | ✓ VERIFIED | Whitelist entry present |
| `server/tests/services/code_graph/test_detect_changes.py` | Kernel green tests | ✓ VERIFIED | Rename / formatting / WR-02 coverage |
| `server/tests/services/test_diff_mirror.py` | Mirror argv + rename | ✓ VERIFIED | `--find-renames` + bare-repo paths |
| `server/tests/services/code_graph/test_detect_changes_orchestrator.py` | Orchestrator contracts | ✓ VERIFIED | D-01/D-02/D-04/D-08/staleness |
| `server/tests/mcp_tools/test_detect_changes_tools.py` | MCP + dual-surface | ✓ VERIFIED | PAT fail-closed + sentinel |
| `server/tests/agents/tools/test_graph_tools.py` | Chat registration / fail-closed | ✓ VERIFIED | `detect_changes` in registry + whitelist |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | --- | --- | ------ | ------- |
| `diff_mirror` | `_run_git` | `['diff','--unified=0','--find-renames', base, head]` | ✓ WIRED | `repo_mirror.py:418-425`; unit asserts argv |
| `detect_affected_symbols` | Symbol records (in-memory) | old-side hunk × `start_line/end_line` | ✓ WIRED | `ranges_overlap` on base-side lines |
| `run_detect_changes` | `diff_mirror` / kernel / `run_impact` | ACL → pin → head → overlap → threshold → sequential impact | ✓ WIRED | Full path in `code_graph_tools.py:1140-1441` |
| `run_detect_changes` | `staleness_payload` / degradation (`graph`) | Success envelope | ✓ WIRED | Key `graph` holds `degradation_payload` (122 envelope shape) |
| `DetectChangesView` | `run_detect_changes` | Thin shell | ✓ WIRED | No algorithm in view |
| `detect_changes @tool` | `run_detect_changes` | `_detect_changes_impl` | ✓ WIRED | Chat thin shell |
| `chat_runner._INDEXED_TOOL_NAMES` | `detect_changes` | Whitelist | ✓ WIRED | Indexed mode exposure |
| `urls.py` | `TOOL_SCHEMA_SNAPSHOT` | Same-batch `detect_changes` | ✓ WIRED | Snapshot + route; schema tests pass |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| `run_detect_changes` | `files` / `impacts` | `diff_mirror` → parse → ORM Symbol → kernel → `run_impact` | Yes (ORM + git; mocked in unit, real git in `test_diff_mirror`) | ✓ FLOWING |
| `DetectChangesView` | response body | `run_detect_changes` result + `run_id` | Yes (passthrough) | ✓ FLOWING |
| Chat `detect_changes` | `output.data` | same orchestrator | Yes (dual-surface sentinel) | ✓ FLOWING |
| `tool_trace_payload(detect_changes)` | counts only | summary / list lengths | Counts-only; no paths/names/diff body | ✓ FLOWING (intentional scrub) |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Scoped detect_changes suites | `GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False uv run pytest` on kernel / orchestrator / diff_mirror / MCP / agents / schema_snapshot `--reuse-db` | **38 passed** in ~55s | ✓ PASS |

### Probe Execution

| Probe | Command | Result | Status |
| ----- | ------- | ------ | ------ |
| — | — | No phase-declared `scripts/*/tests/probe-*.sh` | SKIPPED |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ---------- | ----------- | ------ | -------- |
| DIFF-01 | 123-01..05 | 分支 diff → 受影响符号 + 批量 impact；base 锚定索引水位 | ✓ SATISFIED | Kernel fields + orchestrator pin + `run_impact` batch + tests |
| DIFF-02 | 123-01..05 | compare + base_ref；rename 识别不误报 | ✓ SATISFIED | Declarative `base_ref`; `--find-renames`; pure-rename + WR-02 tests |

No orphaned REQUIREMENTS.md IDs for Phase 123 beyond DIFF-01/DIFF-02.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| — | — | No `TBD`/`FIXME`/`XXX` in phase deliverables | — | — |
| `test_detect_changes_orchestrator.py` | (IN-01) | Mirror pin helpers still mocked in orchestrator D-01 tests | ℹ️ Info | LOW skipped in review; production path uses real `ensure_mirror_sha` + hard-reject — not a goal blocker |
| ROADMAP D-27 | — | `test_mcp_package_tools_match_server_snapshot` allowed red (drift 7→8) | ℹ️ Info | Explicitly accepted; not a Phase 123 goal failure |

### Review Fix Presence

| Finding | Status | Evidence |
| ------- | ------ | -------- |
| CR-01 | ✓ present | `ensure_mirror_sha` base pin + sha equality hard-reject; tip-cache guard when `pin_sha` set |
| WR-01 | ✓ present | case-insensitive `_FULL_SHA_RE` + `.lower()` before sha pin |
| WR-02 | ✓ present | rename+hunks+no-hit → `symbols=[]` |
| WR-03 | ✓ present | truncated → empty `symbols` + `file_level_only` |

### Human Verification Required

None required for goal closure. Automated suite covers kernel rename/formatting, orchestrator pin/`base_ref`/staleness/threshold, MCP PAT fail-closed, dual-surface byte equality, and counts-only traces. Live end-to-end against a production MR tip is deferred to Phase 124 encoding-chain integration (DIFF-03/04), not a Phase 123 must-have gap.

### Gaps Summary

No blocking gaps. Phase 123 roadmap success criteria, DIFF-01/DIFF-02, D-01..D-16 core contracts exercised by code+tests, and review fixes CR-01/WR-01/WR-02/WR-03 are present and wired.

---

_Verified: 2026-08-09T19:15:00Z_
_Verifier: Claude (gsd-verifier)_
