---
phase: 132
slug: integration-gaosan-regression
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-08-14
---

# Phase 132 — Validation Strategy

> Per-phase validation contract. Derived from `132-RESEARCH.md` Validation Architecture + D2 / INT-02 / INT-03.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (pytest-django / pytest-asyncio) |
| **Config file** | `server/pyproject.toml` |
| **Quick run command** | `cd server && uv run pytest tests/services/process_runtime/test_gaosan_eval.py tests/services/process_runtime/test_gaosan_funnel_regression.py tests/services/process_runtime/test_int03_contracts.py -q --tb=short` |
| **Full suite command** | `cd server && uv run pytest tests/services/process_runtime/test_gaosan_eval.py tests/services/process_runtime/test_gaosan_funnel_regression.py tests/services/process_runtime/test_int03_contracts.py tests/services/process_runtime/test_funnel_gates.py tests/services/process_runtime/test_reflection.py tests/services/process_runtime/test_funnel_gates_wiring.py tests/services/process_runtime/test_funnel_placement.py tests/services/process_runtime/test_funnel_shortlist.py tests/services/process_runtime/test_funnel_team_gate.py tests/mcp_tools/test_mcp_read_flow.py -q --tb=short --reuse-db` |
| **Estimated runtime** | ~60–180 seconds |

---

## Sampling Rate

- **After every task commit:** Run that task's `<automated>` command
- **After every plan wave:** Run Full suite command above（Wave 1 可先跑 gaosan_eval）
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 180 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------------|-----------------|-----------|-------------------|-------------|--------|
| 132-01-T1 | 01 | 1 | INT-02 | T-132-01 | 无需求全文入 bar 日志 | unit | `pytest .../test_gaosan_eval.py` | after T1 | ⬜ pending |
| 132-01-T2 | 01 | 1 | INT-02 | T-132-01 | 同上 | unit | same | yes | ⬜ pending |
| 132-02-T1 | 02 | 2 | INT-02 | T-132-03/04 | out_of_team primary=0；V2 受限 scope | integration | `pytest .../test_gaosan_funnel_regression.py` | after T1 | ⬜ pending |
| 132-02-T2 | 02 | 2 | INT-02 | T-132-03/04 | 同上 | integration | gaosan_eval + funnel_regression | yes | ⬜ pending |
| 132-03-T1 | 03 | 2 | INT-03 | T-132-06/08 | 脱敏 + 非全库 primary | unit/wiring | `pytest .../test_int03_contracts.py .../test_funnel_gates_wiring.py` | after T1 | ⬜ pending |
| 132-03-T2 | 03 | 2 | INT-03 | T-132-06/07/08 | N=2 预算保留；脱敏 | contract pack | Full suite command | yes | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Existing pytest infrastructure covers phase requirements. RED tasks create `test_gaosan_*.py` / `test_int03_contracts.py`. No framework install.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 活 Learning-tools Space 漏斗评测 | INT-02 | 需生产/预发 Space 与索引 | 可选 `@pytest.mark.live_space` 或脚本；引用 `.planning/quick/260809-repo-route-eval/SUMMARY.md` Space id；**非 CI 门禁** |

All CI-required behaviors have automated verification via synthetic fixtures.

---

## Success Criteria ↔ Test Map

| ROADMAP Success Criterion | Primary tests |
|---------------------------|---------------|
| 1. 四基线 placement-unit primary 覆盖达 D2 门槛 | `test_gaosan_eval.py` + `test_gaosan_funnel_regression.py` |
| 2. out_of_team 不得 primary | same（`out_of_team_primary_count==0`） |
| 3. 契约不回归 + 门禁/反思自动化（含角色坍塌→反思） | `test_int03_contracts.py` + funnel/gates/reflection 包 + wiring collapse 用例 |

---

## V2 Freeze Guard

```bash
# 本相位执行 commits 的 files 列表不得包含 repo_router_v2.py 业务改动
git log --oneline -- server/codegraph/services/repo_router_v2.py | head -5
```

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references（无 MISSING）
- [x] No watch-mode flags
- [x] Feedback latency < 180s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending execution
