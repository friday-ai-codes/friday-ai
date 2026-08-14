---
phase: 130
slug: placement-units-wiring
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-08-14
---

# Phase 130 — Validation Strategy

> Per-phase validation contract. Derived from `130-RESEARCH.md` ## Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (pytest-django / pytest-asyncio) |
| **Config file** | `server/pyproject.toml` |
| **Quick run command** | `cd server && uv run pytest tests/services/process_runtime/test_placement_units.py tests/services/process_runtime/test_place_units.py -q --tb=short` |
| **Full suite command** | `cd server && uv run pytest tests/services/process_runtime/test_placement_units.py tests/services/process_runtime/test_place_units.py tests/services/process_runtime/test_funnel_placement.py tests/services/process_runtime/test_funnel_shortlist.py tests/services/process_runtime/test_funnel_team_gate.py tests/initiatives/test_repo_association_service.py -q --tb=short --reuse-db` |
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
|---------|------|------|-------------|----------------|-------------------|-------------|
| 130-01-T1 | 01 | 1 | UNIT-01 | T-130-01 | `pytest .../test_placement_units.py` | after T1 |
| 130-01-T2 | 01 | 1 | UNIT-01 | T-130-01 | same | yes |
| 130-02-T1 | 02 | 2 | UNIT-02/03 | T-130-03 | `pytest .../test_place_units.py` | after T1 |
| 130-02-T2 | 02 | 2 | UNIT-02/03 | T-130-03/04 | same + placement_units | yes |
| 130-03-T1 | 03 | 3 | INT-01 | T-130-06 | `pytest .../test_funnel_placement.py` | after T1 |
| 130-03-T2 | 03 | 3 | INT-01 | T-130-06/07/08 | Full suite | yes |

---

## Wave 0

Existing pytest infra sufficient — RED tasks create new test modules. No framework Wave 0.

---

## Manual-Only Verifications

All phase behaviors have automated verification. Phase 132 owns 高三四基线人工/回归门槛。

---

## Success Criteria ↔ Test Map

| ROADMAP Success Criterion | Primary tests |
|---------------------------|---------------|
| 1. feature 点聚合为 Placement Units（模块依赖 + 复用边） | `test_placement_units.py` |
| 2. 每单元 primary + supporting + confidence + evidence + open_questions | `test_place_units.py` |
| 3. V2 候选硬限制 shortlist ∪ 复用宿主 | `test_place_units.py` + `test_funnel_placement.py` |
| 4. 蓝图/项目选仓主路径走漏斗；三分量非唯一决策 | `test_funnel_placement.py` + association 测 |

---

## V2 Freeze Guard

```bash
# 本相位执行后不应有未暂存/提交对 V2 的业务改动（允许无关历史）
git log --oneline -- server/codegraph/services/repo_router_v2.py | head -5
# 执行 commits 的 files 列表不得包含 repo_router_v2.py
```
