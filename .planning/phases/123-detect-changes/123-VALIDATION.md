---
phase: 123
slug: detect-changes
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-08-10
---

# Phase 123 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-django + pytest-asyncio |
| **Config file** | `server/pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `cd server && uv run pytest tests/services/code_graph/test_detect_changes.py tests/services/test_diff_mirror.py -q` |
| **Full suite command** | `cd server && uv run pytest tests/services/code_graph/ tests/mcp_tools/test_detect_changes_tools.py tests/mcp_tools/test_impact_trace_tools.py -q` |
| **Estimated runtime** | ~30–90 seconds (quick); ~2–5 minutes (full wave) |

---

## Sampling Rate

- **After every task commit:** Run quick command (overlap + `diff_mirror`)
- **After every plan wave:** Run full suite command + ensure existing `test_impact_trace_tools` has no regressions
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 90 seconds (quick path)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 123-00-* | 00 | 0 | DIFF-01/02 | T-123-ACL / T-123-DOS | stubs exist; ACL/exclusion/DoS fixtures sketched | unit scaffolding | `pytest tests/services/code_graph/test_detect_changes.py --collect-only` | ❌ W0 | ⬜ pending |
| 123-01-* | 01 | 1 | DIFF-01 | T-123-BASE | base pinned to `last_indexed_commit_sha`; hard reject empty index | unit | `pytest ... -k 'overlap or diff_base_pinned or hard_reject' -x` | ❌ W0 | ⬜ pending |
| 123-01-* | 01 | 1 | DIFF-02 | T-123-RENAME | pure rename → `renamed` only; `base_ref` declarative | unit+git | `pytest tests/services/test_diff_mirror.py -k 'rename or base_ref' -x` | ❌ W0 | ⬜ pending |
| 123-01-* | 01 | 1 | DIFF-01 | T-123-EXCL | excluded files absent from affected | unit | `pytest ... -k exclusion -x` | ❌ W0 | ⬜ pending |
| 123-02-* | 02 | 2 | DIFF-01 | T-123-DOS | >100 → file summary + zero `run_impact`; formatting_only skipped | unit | `pytest ... -k 'threshold or formatting_only or batch_impact' -x` | ❌ W0 | ⬜ pending |
| 123-02-* | 02 | 2 | DIFF-01 | T-123-STALE | staleness envelope + behind still ok | unit | `pytest ... -k staleness -x` | ❌ W0 | ⬜ pending |
| 123-02-* | 02 | 2 | DIFF-01 | T-123-ACL | `ensure_repository_readable` → `GraphAccessDenied` 硬拒，无空成功 affected | unit | `pytest tests/services/code_graph/test_detect_changes_orchestrator.py -k hard_reject_acl -x` | ❌ W0 | ⬜ pending |
| 123-03-* | 03 | 3 | DIFF-01/02 | T-123-AUTH | MCP PAT + serializer + ACL error mapping | integration | `pytest tests/mcp_tools/test_detect_changes_tools.py -k mcp -x` | ❌ W0 | ⬜ pending |
| 123-04-* | 04 | 4 | DIFF-01/02 | T-123-AUTH | conversational `@tool` shell | unit | `pytest tests/agents/tools/test_graph_tools.py -k detect_changes -x` | ❌ W0 | ⬜ pending |
| 123-05-* | 05 | 5 | IMPACT-06 延续 | T-123-TRACE | MCP↔对话 data byte-identical (sans `run_id`); RetrievalTrace counts only | integration | `pytest tests/mcp_tools/test_detect_changes_tools.py -k two_surfaces -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `server/tests/services/code_graph/test_detect_changes.py` — overlap / formatting / threshold / rename classification (string fixtures)
- [ ] `server/tests/services/test_diff_mirror.py` — temp bare repo: `git init` + two commits + rename + format
- [ ] `server/tests/services/code_graph/test_detect_changes_orchestrator.py` — `run_detect_changes` mock mirror / spy `run_impact` / `test_hard_reject_acl`
- [ ] `server/tests/mcp_tools/test_detect_changes_tools.py` — MCP 200 + dual-surface sentinel
- [ ] serializers `TOOL_SCHEMAS["detect_changes"]` + snapshot assertion update (accept mcp package drift +1 per D-27)

*Existing infrastructure (pytest, mcp snapshot harness, impact/trace dual-surface patterns) covers runners; new files above are Wave 0 gaps.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real large-repo behind_commits UX wording | DIFF-01 success #3 | Needs live indexed repo with large lag | Call detect_changes on a behind repo; confirm staleness declaration is conspicuous and result still computed |
| Production formatting_only precision across languages | DIFF-01 | Heuristic calibration | Spot-check import-reorder / whitespace-only PRs after ship |

*All core DIFF-01/DIFF-02 behaviors have automated verification planned above.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
