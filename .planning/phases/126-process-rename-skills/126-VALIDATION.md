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
> Plan IDs **exactly** `126-01`..`126-05`（无幽灵第六 plan）；另可有一行 `126-XX-F` frozen 交叉引用。

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest ≥9 + pytest-django ≥4.8 + pytest-asyncio（server）；task pytest for skills |
| **Config file** | `server/pyproject.toml` `[tool.pytest.ini_options]`；`task/pyproject.toml` |
| **Quick run command**（task） | `cd server && GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False uv run pytest <task-scoped> -q --reuse-db` |
| **Full suite command**（wave/phase） | `cd server && uv run pytest tests/services/code_graph/ tests/codegraph/test_process_trace_model.py tests/mcp_tools/test_schema_snapshot.py -q` + `cd task && uv run pytest tests/test_skills_injection.py tests/core/test_knowledge_tools.py -q`（若后者路径存在） |
| **Estimated runtime** | quick ~10–40s；full ~60–120s |

---

## Sampling Rate

- **After every task commit (quick):** Run the task-scoped pytest file(s) listed in the Per-Task Verification Map
- **After every plan wave (full):** Full suite command above
- **Before `/gsd-verify-work` (full):** Full suite must be green; `applied is False` assertions present; impact_report Recommendations 无「待 Phase 126」占位
- **Max feedback latency:** 120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 126-01-01 | 126-01 | 0 | EXEC-01..SKILL-01 | T-126-04/06 | Wave 0 七桩 collect-only（含 `test_process_query`） | unit | `cd server && GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False uv run pytest tests/codegraph/test_process_trace_model.py tests/services/code_graph/test_process_trace.py tests/services/code_graph/test_process_enqueue.py tests/services/code_graph/test_affected_processes.py tests/services/code_graph/test_process_query.py tests/services/code_graph/test_rename_preview.py tests/services/code_graph/test_frozen_surface_126.py --collect-only -q` | ✅ | ⬜ pending |
| 126-02-01 | 126-02 | 1 | EXEC-01 + EXEC-02(内核) | T-126-04 | ProcessTrace schema / unique | unit | `cd server && GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False uv run pytest tests/codegraph/test_process_trace_model.py -q --reuse-db` | ✅ | ⬜ pending |
| 126-02-02 | 126-02 | 1 | EXEC-01 + EXEC-02(内核) | T-126-04 | BFS 闸门 + intra/cross/unknown | unit | `cd server && GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False uv run pytest tests/services/code_graph/test_process_trace.py -q --reuse-db` | ✅ | ⬜ pending |
| 126-02-03 | 126-02 | 1 | EXEC-01 + EXEC-02(内核) | — | QUEUE_GRAPH + process:{repo}:{branch} lock | unit | `cd server && GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False uv run pytest tests/services/code_graph/test_process_enqueue.py -q --reuse-db` | ✅ | ⬜ pending |
| 126-03-01 | 126-03 | 2 | EXEC-02(查询) + EXEC-03 | — | assemble affected_processes | unit | `cd server && GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False uv run pytest tests/services/code_graph/test_affected_processes.py -q --reuse-db` | ✅ | ⬜ pending |
| 126-03-02 | 126-03 | 2 | EXEC-02(查询) + EXEC-03 | — | impact_report 执行流段 | unit | `cd server && GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False uv run pytest tests/services/code_graph/test_impact_report.py -q --reuse-db` | ✅ 扩展 | ⬜ pending |
| 126-03-03 | 126-03 | 2 | EXEC-02(查询) + EXEC-03 | T-126-01 | list/get + MCP/@tool call-through + schema | unit/api | `cd server && GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False uv run pytest tests/services/code_graph/test_process_query.py tests/mcp_tools/test_schema_snapshot.py -q --reuse-db` | ✅ | ⬜ pending |
| 126-04-01 | 126-04 | 3 | RENAME-01 | T-126-02/T-126-05 | exclusion + applied=false | unit | `cd server && GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False uv run pytest tests/services/code_graph/test_rename_preview.py -q --reuse-db` | ✅ | ⬜ pending |
| 126-04-02 | 126-04 | 3 | RENAME-01 | T-126-03 | knowledge 白名单 + dual-face RetrievalTrace | unit | `cd task && uv run pytest tests/ -k rename_preview -q` | ✅ 扩展 | ⬜ pending |
| 126-05-01 | 126-05 | 4 | SKILL-01 | — | SKILL_NAMES + sha256 | unit | `cd task && uv run pytest tests/test_skills_injection.py -q` | ✅ 扩展 | ⬜ pending |
| 126-XX-F | * | * | D-16 | T-126-06 | frozen surfaces（交叉引用，非第六 plan） | unit | `cd server && GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False uv run pytest tests/services/code_graph/test_frozen_surface_126.py -q --reuse-db` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**Plan ID lock:** Map 主 plan 列仅 `126-01` / `126-02` / `126-03` / `126-04` / `126-05`；Wave 列分别为 `0`/`1`/`2`/`3`/`4`。禁止幽灵第六 plan（编号 126 后不可出现 06）。

---

## Wave 0 Requirements

- [x] `server/tests/codegraph/test_process_trace_model.py` — stubs for EXEC-01 schema
- [x] `server/tests/services/code_graph/test_process_trace.py` — stubs for BFS hard gates
- [x] `server/tests/services/code_graph/test_process_enqueue.py` — stubs for QUEUE_GRAPH lock
- [x] `server/tests/services/code_graph/test_affected_processes.py` — stubs for EXEC-03
- [x] `server/tests/services/code_graph/test_process_query.py` — stubs for EXEC-02 list/get + MCP/agents call-through
- [x] `server/tests/services/code_graph/test_rename_preview.py` — stubs for RENAME-01
- [x] `server/tests/services/code_graph/test_frozen_surface_126.py` — stubs for D-16
- [ ] Extend existing: `test_impact_report.py` / `test_skills_injection.py` / knowledge whitelist / schema snapshot

*Framework install: none — existing pytest covers all phase requirements.*
*`wave_0_complete: true` 由 126-01 SUMMARY 后勾选。*

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
