---
phase: 131
slug: gate-system-reflection
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-08-14
---

# Phase 131 — Validation Strategy

> Per-phase validation contract. Derived from `131-RESEARCH.md` ## Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (pytest-django / pytest-asyncio) |
| **Config file** | `server/pyproject.toml` |
| **Quick run command** | `cd server && uv run pytest tests/services/process_runtime/test_funnel_gates.py tests/services/process_runtime/test_reflection.py -q --tb=short` |
| **Full suite command** | `cd server && uv run pytest tests/services/process_runtime/test_funnel_gates.py tests/services/process_runtime/test_reflection.py tests/services/process_runtime/test_funnel_gates_wiring.py tests/services/process_runtime/test_funnel_placement.py tests/services/process_runtime/test_funnel_shortlist.py tests/services/process_runtime/test_funnel_team_gate.py -q --tb=short --reuse-db` |
| **Estimated runtime** | ~30–120 seconds |

---

## Sampling Rate

- **After every task commit:** Run that task's `<automated>` command
- **After every plan wave:** Run Full suite command above
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Automated Command | File Exists |
|---------|------|------|-------------|------------|-------------------|-------------|
| 131-01-T1 | 01 | 1 | GATE-01/02/03 | T-131-01/02/03 | `pytest .../test_funnel_gates.py` | after T1 |
| 131-01-T2 | 01 | 1 | GATE-01/02/03 | T-131-01/02/03 | same | yes |
| 131-02-T1 | 02 | 2 | REFL-01/02/03 | T-131-04/05/06 | `pytest .../test_reflection.py` | after T1 |
| 131-02-T2 | 02 | 2 | REFL-01/02/03 | T-131-04/05/06 | reflection + gates | yes |
| 131-03-T1 | 03 | 3 | GATE/REFL wiring | T-131-07/08/09 | `pytest .../test_funnel_gates_wiring.py` | after T1 |
| 131-03-T2 | 03 | 3 | GATE/REFL wiring | T-131-07/08/09 | Full suite | yes |

---

## Wave 0

Existing pytest infra sufficient — RED tasks create new test modules. No framework Wave 0.

---

## Manual-Only Verifications

All phase behaviors have automated verification. Phase 132 owns 高三四基线人工/回归门槛；本相位不要求真环境 Space。

---

## Success Criteria ↔ Test Map

| ROADMAP Success Criterion | Primary tests |
|---------------------------|---------------|
| 1. 统一 pass\|clarify\|block + reason_codes + evidence | `test_funnel_gates.py` |
| 2. 五门落地（含发布门） | `test_funnel_gates.py` + wiring |
| 3. 全局一致性四类拦截 | `test_funnel_gates.py` |
| 4. 反思 N=2、只补丁受影响、超限 needs_human_review | `test_reflection.py` |
| 5. 每轮 ledger/事件脱敏可回放 | `test_reflection.py` |

---

## V2 Freeze Guard

```bash
# 本相位执行 commits 的 files 列表不得包含 repo_router_v2.py
git log --oneline -- server/codegraph/services/repo_router_v2.py | head -5
```

---

## Source Audit (planning)

| SOURCE | ID | Item | Plan | Status |
|--------|-----|------|------|--------|
| GOAL | — | 统一门禁 + 有界反思 | 01–03 | COVERED |
| REQ | GATE-01 | 统一契约 | 01, 03 | COVERED |
| REQ | GATE-02 | 五门 | 01, 03 | COVERED |
| REQ | GATE-03 | 全局一致性 | 01 | COVERED |
| REQ | REFL-01 | 触发 + N=2 | 02, 03 | COVERED |
| REQ | REFL-02 | 结构化补丁 / 只重算受影响 | 02 | COVERED |
| REQ | REFL-03 | ledger/事件 | 02, 03 | COVERED |
| CONTEXT | D-02/D4 | publish / auto_selected | 01, 03 | COVERED |
| CONTEXT | D-03 | N=2 / needs_human_review | 02 | COVERED |
| RESEARCH | funnel_gates + reflection 模块 | 01–02 | COVERED |
| RESEARCH | Adapter wiring | 03 | COVERED |
