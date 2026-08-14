---
phase: 128-initiative-profile-team-gate
verified: 2026-08-14T05:40:00Z
status: passed
score: 5/5 must-haves verified
overrides_applied: 0
---

# Phase 128: 专项画像 + 团队门禁地基 Verification Report

**Phase Goal:** 从 feature list 产出机读专项画像，并划定 `team_core` 硬范围；漏斗三入口（Blueprint / RepoAssociation / MCP）禁止无团队静默全库 primary（D1/D3）。

**Verified:** 2026-08-14T05:40:00Z  
**Status:** passed

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | ------- | ---------- | -------------- |
| 1 | 专项画像可序列化；语料剔除 acceptance；不足 clarify | ✓ VERIFIED | `initiative_profile.py` + `test_initiative_profile.py`（7 passed） |
| 2 | 画像 LLM fail-soft → degraded；CallSource 已登记 | ✓ VERIFIED | `CallSource.INITIATIVE_PROFILE`；LOGGING-SPEC §4.1；degrade 单测 |
| 3 | team_core 解析 + out_of_team 非 primary；空/无索引 clarify | ✓ VERIFIED | `team_gate.py` + `test_team_gate.py`（9 passed） |
| 4 | 三入口漏斗 hard gate；MCP 无静默全库 primary | ✓ VERIFIED | `blueprint_route` / `repo_association` / `stage_sandbox` + `test_funnel_team_gate.py` |
| 5 | 裸 RepoRouterV2 不被重写；grouping annotate-only 兼容 | ✓ VERIFIED | `git` 无 V2 内核重写；漏斗测注释守卫 |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Status |
| -------- | ------ |
| `server/services/process_runtime/initiative_profile.py` | ✓ |
| `server/services/process_runtime/team_gate.py` | ✓ |
| `server/tests/services/process_runtime/test_initiative_profile.py` | ✓ |
| `server/tests/services/process_runtime/test_team_gate.py` | ✓ |
| `server/tests/services/process_runtime/test_funnel_team_gate.py` | ✓ |
| `128-01/02/03-SUMMARY.md` | ✓ |

### Automated Verification

```text
uv run pytest tests/services/process_runtime/test_funnel_team_gate.py \
  tests/services/process_runtime/test_initiative_profile.py \
  tests/services/process_runtime/test_team_gate.py -q
# → 21 passed

uv run pytest tests/initiatives/test_repo_association_service.py \
  tests/services/process_runtime/test_stage_sandbox.py \
  -k 'not research and not spec_stage' -q --create-db
# → 16 passed
```

### Requirements Trace

| REQ | Covered by | Status |
| --- | ---------- | ------ |
| PROF-01 | 128-01 build_profile ok 形状 | ✓ |
| PROF-02 | select_profile_corpus 剔除 acceptance | ✓ |
| PROF-03 | degraded + structlog sampling | ✓ |
| TEAM-01 | resolve_team_core 三级解析 | ✓ |
| TEAM-02 | annotate + primary 仅 team_core | ✓ |
| TEAM-03 | empty/unindexed → clarify | ✓ |

### Threat Mitigations

| ID | Disposition | Evidence |
| -- | ----------- | -------- |
| T-128-01 | mitigate | 日志仅长度/reason；redact_secrets_in_text |
| T-128-02 | mitigate | JSON schema 校验；非法 → degraded |
| T-128-03/05 | mitigate | D1/D3 clarify，禁止全库 primary |
| T-128-04 | accept | 入口既有 auth |

### Gaps / Blockers

None.

### Next Phase

Phase 129（短名单 + 历史先验 + 章程角色图）— **未启动**（`--no-transition`）。
