---
phase: 124-coding-chain
fixed_at: 2026-08-09T19:54:12.908Z
review_path: .planning/phases/124-coding-chain/124-REVIEW.md
iteration: 1
findings_in_scope: 5
fixed: 5
skipped: 1
status: partial
---

# Phase 124: Code Review Fix Report

**Fixed at:** 2026-08-09T19:54:12.908Z
**Source review:** `.planning/phases/124-coding-chain/124-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 5 (HI-01, ME-01..03, plus clearly-safe LO-02)
- Fixed: 5
- Skipped: 1 (LO-01 product decision; INFO skipped by scope)

Scope note: HIGH + MEDIUM required; INFO skipped; LO-02 applied as clearly safe assertion tighten; LO-01 skipped (requires product decision on MR reuse description updates).

## Fixed Issues

### HI-01: DIFF-03 guidance assumes repository UUID the container never receives

**Files modified:** `task/core/config.py`, `task/core/executor.py`, `task/tests/test_detect_changes_prompt.py`, `server/workflows/nodes/ai/coding.py`, `server/chat/coding_session_service.py`
**Commit:** `5a9de968`
**Applied fix:** Added `TaskConfig.repository_id` (`FRIDAY_TASK_REPOSITORY_ID`); inject `env_FRIDAY_TASK_REPOSITORY_ID` from AICodingNode + chat `build_dispatch_metadata`; bake UUID into `_build_coding_prompt` branch section; `_detect_changes_guidance` inlines UUID-validated id via string concat (unsafe values fall back to env hint).

### ME-01: D-14 dual-path parity sentinel is vacuous under mocks

**Files modified:** `server/tests/mcp_tools/test_mr_impact_report.py`
**Commit:** `7735b696`
**Applied fix:** Spy records await kwargs from workflow + MCP shells and asserts `(repo, compare, base_ref, user)` equality; stub parity calls unpatched `build_impact_report_section` with mocked `run_detect_changes` (`ok=False`) and `user=None` for byte-stable stubs.

### ME-02: Outer MR shell `except Exception: pass` swallows total omission without observability

**Files modified:** `server/workflows/nodes/ai/coding.py`, `server/workflows/services/mr_service.py`, `server/mcp_tools/merge_request_service.py`
**Commit:** `d783abff`
**Applied fix:** Outer except now best-effort logs `impact_report_shell_failed` (`component`/`category`/`repository_id`/`error[:200]`) then continues; nested log failure still swallowed.

### ME-03: Missing `user` always yields `unavailable` stub (silent product degradation)

**Files modified:** `server/services/code_graph/impact_report.py`, `server/workflows/services/mr_service.py`, `server/tests/services/code_graph/test_impact_report.py`, `server/tests/mcp_tools/test_mr_impact_report.py`
**Commit:** `2fb3a0b5`
**Status:** `fixed: requires human verification`
**Applied fix:** Kept ACL short-circuit (no `run_detect_changes` without user) but stub/log `error_code=user_missing`; `mr_service` resolves user via `_resolve_impact_user` (fields_cache → async id lookup for Django models; fixture attribute otherwise). Plan intentionally does not invent a system user for graph ACL.

### LO-02: MCP fail-soft test assertion is too loose

**Files modified:** `server/tests/mcp_tools/test_mr_impact_report.py`
**Commit:** `83521b38`
**Applied fix:** When helper raises, assert description equals `"base body"` only (D-09 regression signal).

## Skipped Issues

### LO-01: Impact computed before MR dedup; reused MR description not updated

**File:** `server/workflows/nodes/ai/coding.py:2218-2268`
**Reason:** Product decision required — whether to skip impact on reuse path vs update remote MR description. Not a clearly safe mechanical fix.
**Original issue:** Impact built before `find_open_merge_request`; on dedup hit the existing remote MR keeps old description.

### IN-01 / IN-02 / IN-03

**Reason:** Out of fix_scope (INFO skipped).

---

_Fixed: 2026-08-09T19:54:12.908Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
