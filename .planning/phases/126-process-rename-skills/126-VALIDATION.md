---
phase: 126
slug: process-rename-skills
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-08-10
---

# Phase 126 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest ≥9 + pytest-django ≥4.8 + pytest-asyncio（server）；task pytest for skills |
| **Config file** | `server/pyproject.toml` `[tool.pytest.ini_options]`；`task/pyproject.toml` |
| **Quick run command** | `cd server && uv run pytest tests/services/code_graph/test_process_trace.py tests/services/code_graph/test_process_query.py tests/services/code_graph/test_rename_preview.py tests/services/code_graph/test_affected_processes.py -q` |
| **Full suite command** | `cd server && uv run pytest tests/services/code_graph/ tests/codegraph/test_process_trace_model.py tests/mcp_tools/test_schema_snapshot.py -q` + `cd task && uv run pytest tests/test_skills_injection.py tests/core/test_knowledge_tools.py -q`（若后者路径存在） |
| **Estimated runtime** | ~60–120 seconds |

---

## Sampling Rate

- **After every task commit:** Run the task-scoped pytest file(s) listed in the Per-Task Verification Map（quick）
- **After every plan wave:** Full suite command above
- **Before `/gsd-verify-work`:** Full suite must be green; `applied is False` assertions present; impact_report Recommendations 无「待 Phase 126」占位
- **Max feedback latency:** 120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 126-01-01 | 01 | 0 | EXEC-01..SKILL-01 | T-126-04/06 | Wave 0 七桩 collect-only | unit | `cd server && uv run pytest tests/codegraph/test_process_trace_model.py tests/services/code_graph/test_process_trace.py tests/services/code_graph/test_process_enqueue.py tests/services/code_graph/test_affected_processes.py tests/services/code_graph/test_process_query.py tests/services/code_graph/test_rename_preview.py tests/services/code_graph/test_frozen_surface_126.py --collect-only -q` | ❌ W0 | ⬜ pending |
| 126-02-01 | 02 | 1 | EXEC-01 | T-126-04 | ProcessTrace schema / unique | unit | `cd server && uv run pytest tests/codegraph/test_process_trace_model.py -q` | ❌ W0 | ⬜ pending |
| 126-02-02 | 02 | 1 | EXEC-01 + EXEC-02(内核) | T-126-04 | BFS 闸门 + intra/cross/unknown | unit | `cd server && uv run pytest tests/services/code_graph/test_process_trace.py -q` | ❌ W0 | ⬜ pending |
| 126-02-03 | 02 | 1 | EXEC-01 | — | QUEUE_GRAPH + queueing_lock | unit | `cd server && uv run pytest tests/services/code_graph/test_process_enqueue.py -q` | ❌ W0 | ⬜ pending |
| 126-03-01 | 03 | 2 | EXEC-03 | — | assemble affected_processes | unit | `cd server && uv run pytest tests/services/code_graph/test_affected_processes.py -q` | ❌ W0 | ⬜ pending |
| 126-03-02 | 03 | 2 | EXEC-03 | — | impact_report 执行流段 | unit | `cd server && uv run pytest tests/services/code_graph/test_impact_report.py -q` | ✅ 扩展 | ⬜ pending |
| 126-03-03 | 03 | 2 | EXEC-02 | T-126-01 | list/get 共享编排 + MCP/@tool call-through + schema | unit/api | `cd server && uv run pytest tests/services/code_graph/test_process_query.py tests/mcp_tools/test_schema_snapshot.py -q` | ❌ W0 | ⬜ pending |
| 126-04-01 | 04 | 3 | RENAME-01 | T-126-02/T-126-05 | exclusion + applied=false | unit | `cd server && uv run pytest tests/services/code_graph/test_rename_preview.py -q` | ❌ W0 | ⬜ pending |
| 126-04-02 | 04 | 3 | RENAME-01 | T-126-03 | knowledge 白名单 + dual-face RetrievalTrace | unit | `cd task && uv run pytest tests/ -k rename_preview -q` | ✅ 扩展 | ⬜ pending |
| 126-05-01 | 05 | 4 | SKILL-01 | — | SKILL_NAMES + sha256 | unit | `cd task && uv run pytest tests/test_skills_injection.py -q` | ✅ 扩展 | ⬜ pending |
| 126-XX-F | * | * | D-16 | T-126-06 | frozen surfaces | unit | `cd server && uv run pytest tests/services/code_graph/test_frozen_surface_126.py -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `server/tests/codegraph/test_process_trace_model.py` — stubs for EXEC-01 schema
- [ ] `server/tests/services/code_graph/test_process_trace.py` — stubs for BFS hard gates
- [ ] `server/tests/services/code_graph/test_process_enqueue.py` — stubs for QUEUE_GRAPH lock
- [ ] `server/tests/services/code_graph/test_affected_processes.py` — stubs for EXEC-03
- [ ] `server/tests/services/code_graph/test_process_query.py` — stubs for EXEC-02 list/get + MCP/agents call-through
- [ ] `server/tests/services/code_graph/test_rename_preview.py` — stubs for RENAME-01
- [ ] `server/tests/services/code_graph/test_frozen_surface_126.py` — stubs for D-16
- [ ] Extend existing: `test_impact_report.py` / `test_skills_injection.py` / knowledge whitelist / schema snapshot

*Framework install: none — existing pytest covers all phase requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| npm `@friday-ai-codes/skills` publish | SKILL-01 (deferred) | 运维 follow-up，不阻断相位验收 | Deferred per D-15 |

*All phase acceptance behaviors have automated verification except deferred npm publish.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references（含 `test_process_query.py`）
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
