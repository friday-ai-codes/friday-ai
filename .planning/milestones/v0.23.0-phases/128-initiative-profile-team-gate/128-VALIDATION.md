---
phase: 128
slug: initiative-profile-team-gate
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-08-14
---

# Phase 128 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `128-RESEARCH.md` ## Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (pytest-django / pytest-asyncio) |
| **Config file** | `server/pyproject.toml` |
| **Quick run command** | `cd server && uv run pytest tests/services/process_runtime/test_initiative_profile.py tests/services/process_runtime/test_team_gate.py -q --tb=short` |
| **Full suite command** | `cd server && uv run pytest tests/services/process_runtime/test_initiative_profile.py tests/services/process_runtime/test_team_gate.py tests/services/process_runtime/test_funnel_team_gate.py tests/services/process_runtime/test_stage_sandbox.py tests/initiatives/test_repo_association_service.py -q --tb=short` |
| **Estimated runtime** | ~30–90 seconds |

---

## Sampling Rate

- **After every task commit:** Run that task's `<automated>` command
- **After every plan wave:** Run Full suite command above
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 90 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 128-01-01 | 01 | 1 | PROF-01, PROF-02 | T-128-01 | 日志无需求原文；语料剔除 acceptance | unit | `cd server && uv run pytest tests/services/process_runtime/test_initiative_profile.py -q --tb=short -k "corpus or clarify or shape"` | ❌ W0→create | ⬜ pending |
| 128-01-02 | 01 | 1 | PROF-01, PROF-03 | T-128-01, T-128-02 | fail-soft + redact；schema 校验 | unit | `cd server && uv run pytest tests/services/process_runtime/test_initiative_profile.py -q --tb=short` | ❌ W0→create | ⬜ pending |
| 128-02-01 | 02 | 1 | TEAM-01, TEAM-03 | T-128-03 | 无团队不回全库；全无索引→empty | unit | `cd server && uv run pytest tests/services/process_runtime/test_team_gate.py -q --tb=short -k "resolve or empty or missing or unindex"` | ❌ W0→create | ⬜ pending |
| 128-02-02 | 02 | 1 | TEAM-02, TEAM-03 | T-128-03 | out_of_team 非 primary；clarify 载荷 | unit | `cd server && uv run pytest tests/services/process_runtime/test_team_gate.py -q --tb=short` | ❌ W0→create | ⬜ pending |
| 128-03-01 | 03 | 2 | PROF-02, TEAM-01~03 | T-128-05 | Blueprint/RepoAssociation hard gate | integration | `cd server && uv run pytest tests/services/process_runtime/test_funnel_team_gate.py tests/initiatives/test_repo_association_service.py -q --tb=short` | ❌ W0→create | ⬜ pending |
| 128-03-02 | 03 | 2 | TEAM-01~03, D1/D3 | T-128-05 | MCP 无静默全库 primary | integration | `cd server && uv run pytest tests/services/process_runtime/test_funnel_team_gate.py tests/services/process_runtime/test_stage_sandbox.py -q --tb=short` | ❌ W0→create | ⬜ pending |
| 128-03-03 | 03 | 2 | TEAM-03 + V2 compat | T-128-01 | 漏斗门禁 + 裸 V2 兼容注释 | regression | `cd server && uv run pytest tests/services/process_runtime/test_funnel_team_gate.py tests/services/process_runtime/test_initiative_profile.py tests/services/process_runtime/test_team_gate.py -q --tb=short` | ❌ W0→create | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*File Exists: test files are created in-plan (TDD tasks); Wave 0 stubs not required — existing pytest infra covers framework.*

---

## Wave 0 Requirements

Existing infrastructure covers all phase requirements.

- pytest + Django test settings already available under `server/`
- New test modules are created by Wave 1 plans 01/02 (TDD) before Wave 2 wiring
- No framework install / conftest Wave 0 needed

---

## Manual-Only Verifications

All phase behaviors have automated verification.

---

## Success Criteria ↔ Test Map

| ROADMAP Success Criterion | Primary tests |
|---------------------------|---------------|
| 1. 可机读专项画像字段齐全 | `test_initiative_profile.py` (shape / ok) |
| 2. 排除验收语料；不足→clarify | `test_initiative_profile.py` (corpus / clarify) |
| 3. stage 可观测 + fail-soft degrade | `test_initiative_profile.py` + `test_funnel_team_gate.py` |
| 4. team_core + out_of_team 非 primary | `test_team_gate.py` + funnel |
| 5. 无团队/空 core/全无索引 → clarify | `test_team_gate.py` (empty/missing/unindexed) + funnel/MCP |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (none — TDD creates tests in-wave)
- [x] No watch-mode flags
- [x] Feedback latency < 90s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending execute
