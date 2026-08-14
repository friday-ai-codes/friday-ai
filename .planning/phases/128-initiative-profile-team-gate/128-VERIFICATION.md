# Phase 128 Verification

**Phase:** 128-initiative-profile-team-gate  
**Verified:** 2026-08-14  
**Status:** passed

## Success criteria

| # | Criterion | Evidence | Result |
|---|-----------|----------|--------|
| 1 | 机读专项画像 | `test_initiative_profile.py`（ok 字段齐全） | pass |
| 2 | 语料排除 acceptance；不足 → clarify | `test_initiative_profile.py`（corpus/clarify） | pass |
| 3 | 画像 fail-soft + 观测字段 | `test_initiative_profile.py`（degraded）；CallSource.INITIATIVE_PROFILE | pass |
| 4 | team_core；out_of_team 非 primary | `test_team_gate.py` + `test_funnel_team_gate.py` | pass |
| 5 | 无团队/空 core/全无索引 → clarify，非全库 primary | funnel + sandbox + repo_association 测 | pass |

## Automated tests

```text
cd server && uv run pytest \
  tests/services/process_runtime/test_initiative_profile.py \
  tests/services/process_runtime/test_team_gate.py \
  tests/services/process_runtime/test_funnel_team_gate.py \
  tests/services/process_runtime/test_stage_sandbox.py \
  tests/initiatives/test_repo_association_service.py \
  -q --tb=line --reuse-db
# → 41 passed
```

## Constraints checked

- [x] 未重写 `RepoRouterV2` 内核 / grouping 仍 annotate-only（文档守卫测）
- [x] D1/D3：MCP/Blueprint/RepoAssociation 漏斗门禁
- [x] 观测：structlog kv，无需求原文全文

## Gaps

None blocking. Phase 129+ 承接 shortlist/角色/放置/反思/回归。

## Human needed

None.
