---
phase: 124-coding-chain
reviewed: 2026-08-09T19:48:00Z
depth: standard
files_reviewed: 17
files_reviewed_list:
  - task/core/knowledge_tools.py
  - task/core/executor.py
  - server/services/code_graph/impact_report.py
  - server/friday/settings.py
  - server/workflows/nodes/ai/coding.py
  - server/workflows/services/mr_service.py
  - server/mcp_tools/merge_request_service.py
  - server/mcp_tools/views.py
  - server/mcp_tools/work_item_execution_service.py
  - server/tests/services/code_graph/test_impact_report.py
  - server/tests/workflows/test_coding_impact_report.py
  - server/tests/mcp_tools/test_mr_impact_report.py
  - task/tests/test_detect_changes_prompt.py
  - task/tests/test_knowledge_tools.py
  - task/tests/test_openspec_prompt.py
  - task/tests/test_claude_sdk_integration.py
  - task/tests/test_blueprint_context_tools_schema.py
findings:
  critical: 0
  blocker: 0
  high: 1
  medium: 3
  low: 2
  warning: 4
  info: 3
  total: 9
status: issues_found
severity_model: BLOCKER/HIGH/MEDIUM/LOW/INFO
---

# Phase 124: Code Review Report

**Reviewed:** 2026-08-09T19:48:00Z
**Depth:** standard
**Files Reviewed:** 17
**Status:** issues_found

## Summary

Phase 124 correctly wires DIFF-03 (knowledge whitelist + non-blocking prompt) and DIFF-04 (shared fail-soft `impact_report` on AICodingNode / MCP `create_merge_request` / `mr_service`). Freeze surfaces (`mcp/` submodule, `repo_router_v2.py`) are clean; runner commit/push is untouched; credential scrubbing for stubs/logs is solid; outer MR shells never raise from impact failures.

No BLOCKER. Main gap: container self-check guidance requires a Friday `repository_id` UUID that coding dispatch does not inject. Secondary: D-14 parity sentinel is mock-weak, and silent shell `except: pass` can hide total impact omission without logs.

## Narrative Findings (AI reviewer)

### BLOCKER

None.

### HIGH

#### HI-01: DIFF-03 guidance assumes repository UUID the container never receives

**File:** `task/core/executor.py:1062-1077`
**Also:** `server/workflows/nodes/ai/coding.py:2069-2127` (`_build_coding_prompt` omits UUID); `task/core/config.py` (no `repository_id` / `FRIDAY_TASK_REPOSITORY_ID`)
**Issue:** `_detect_changes_guidance` tells the agent to call `detect_changes` with ``repository_id=本任务仓 UUID`` and ``compare=当前功能分支``. Branch name is available (`FRIDAY_TASK_BRANCH_STRATEGY` / git). The Friday repository UUID is **not** injected into task env, coding prompt, or `TaskConfig`. Agent must invent/discover the UUID via other MCP tools; many execute-mode turns will fail the tool call, then "继续交付" — so DIFF-03 self-check often never enters the commit decision. DIFF-04 server MR path is unaffected (it has the `Repository` object).
**Fix:** Inject authoritative UUID at dispatch (e.g. `env_FRIDAY_TASK_REPOSITORY_ID`) and/or bake it into `_build_coding_prompt` / guidance text via a templated helper that only interpolates that trusted id (still no external user text).

```python
# executor.py — preferred: config field from FRIDAY_TASK_REPOSITORY_ID
def _detect_changes_guidance(self) -> str:
    repo_id = (self.config.repository_id or "").strip()
    repo_line = (
        f"`repository_id`=`{repo_id}`" if repo_id else "`repository_id`=本任务仓 UUID（见任务环境 FRIDAY_TASK_REPOSITORY_ID）"
    )
    return (
        "影响面自查（编码完成后、结束 turn 前）：\n"
        f"- 若已挂载 friday-knowledge，调用 `detect_changes`：{repo_line}，"
        "`compare`=当前功能分支"
        # ... keep non-blocking language ...
    )
```

### MEDIUM

#### ME-01: D-14 dual-path parity sentinel is vacuous under mocks

**File:** `server/tests/mcp_tools/test_mr_impact_report.py:140-231`
**Issue:** `test_workflow_mcp_impact_section_parity` patches `build_impact_report_section` to return a fixed string for both workflow and MCP, then asserts that same string appears in both descriptions. The trailing stub check patches the helper again and asserts mock equality (`s1 == s2 == _STUB`). This does **not** prove both shells call the real shared formatter with equivalent `(repo, compare, base_ref, user)` or that stub templates stay byte-stable from `impact_report.py`. Implementation happens to call the same helper (good); the sentinel does not lock that contract.
**Fix:** Drive both shells with a spy/`AsyncMock(wraps=real)` or assert await kwargs equality, and for stub parity call the **unpatched** `build_impact_report_section` twice (e.g. `user=None` or mocked `run_detect_changes` → `ok=False`) and compare outputs.

#### ME-02: Outer MR shell `except Exception: pass` swallows total omission without observability

**File:** `server/workflows/nodes/ai/coding.py:2218-2233`
**Also:** `server/workflows/services/mr_service.py:157-174`; `server/mcp_tools/merge_request_service.py:151-166`
**Issue:** Helper is fail-soft and emits `impact_report_*` events. If the import of `services.code_graph.impact_report` fails, or an unexpected `BaseException` subclass slips past the helper contract, the shell drops impact with **no** log. Reviewers get neither section nor stub; operators get no `impact_report_failed`.
**Fix:** Log once in the outer except (best-effort) then continue:

```python
except Exception as exc:  # noqa: BLE001
    try:
        log.warning(
            "impact_report_shell_failed",
            component="workflows",
            category="caller",
            error=str(exc)[:200],
        )
    except Exception:
        pass
```

#### ME-03: Missing `user` always yields `unavailable` stub (silent product degradation)

**File:** `server/services/code_graph/impact_report.py:376-378`
**Also:** `server/workflows/services/mr_service.py:164-165`; `server/workflows/nodes/ai/coding.py:1811-1818`
**Issue:** Intentional ACL short-circuit: `user is None` → stub `unavailable` without calling `run_detect_changes`. System/background workflows with no `triggered_by` (and work_item paths with `initiating_user=None`) will **always** attach the failure stub, never a real four-section report. Fail-soft and ACL-safe, but looks like detect_changes is broken in production MRs.
**Fix:** Keep fail-soft; add distinct `error_code` such as `user_missing` (allowlisted in `_map_error_code`) so stub/logs distinguish ACL-identity gap from graph outage; ensure workflow triggers that create MRs always resolve a real user where product expects full reports.

### LOW

#### LO-01: Impact computed before MR dedup; reused MR description not updated

**File:** `server/workflows/nodes/ai/coding.py:2218-2268`
**Issue:** `_create_mr_for_repo` awaits `build_impact_report_section` before `find_open_merge_request`. On dedup hit, the existing remote MR keeps its old description; the freshly built impact section is only returned in the local result dict. Wasted work; DIFF-04 “MR 描述附影响面” not met for reuse path.
**Fix:** Run impact append only on the create path, or after dedup miss; optionally update description on reuse (product decision).

#### LO-02: MCP fail-soft test assertion is too loose

**File:** `server/tests/mcp_tools/test_mr_impact_report.py:133-137`
**Issue:** `assert description == "base body" or IMPACT_SECTION_MARKER in description` passes for either outcome, weakening D-09 regression signal.
**Fix:** Assert equality to `"base body"` only when the helper raises (current mock side_effect).

### INFO

#### IN-01: Deferred dialect MR paths still lack impact_report

**File:** `server/workflows/nodes/git/pr.py`; `server/orchestration/coding_graph.py:761-768`
**Issue:** CreatePRNode / chat coding_graph create MRs without `build_impact_report_section`. Explicitly deferred in CONTEXT (Claude's Discretion); not a Phase 124 success-criteria miss, but remaining dialect surfaces.
**Fix:** Backlog — wire the same helper when those paths are unified.

#### IN-02: Freeze / non-blocking / credential checks (positive)

- `task/core/runner.py` has zero `detect_changes` references (D-04).
- Phase commits do not touch `mcp/` submodule or `repo_router_v2.py` (D-16).
- Guidance contains non-blocking language (继续交付 / 不要因为 HIGH/CRITICAL).
- Stub + `_sanitize_error_text` strip Traceback / abs paths / secrets from logs; MR stub only embeds mapped `error_code`.
- Settings: timeout 30s / max_chars 10240; no kill-switch (D-13).

#### IN-03: Recommendations always mention Phase 126 placeholder

**File:** `server/services/code_graph/impact_report.py:286`
**Issue:** Every successful report appends the affected_processes deferral line — correct per D-07, mildly noisy for reviewers.
**Fix:** Optional — only when product wants quieter happy-path MRs.

---

## Severity summary

| Severity | Count |
|----------|------:|
| BLOCKER  | 0 |
| HIGH     | 1 |
| MEDIUM   | 3 |
| LOW      | 2 |
| INFO     | 3 |
| **Total**| **9** |

**Review artifact:** `.planning/phases/124-coding-chain/124-REVIEW.md`

---

_Reviewed: 2026-08-09T19:48:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
