# Phase 129 Verification

**Phase:** 129-shortlist-history-role-map  
**Verified:** 2026-08-14  
**Status:** passed

## Success criteria

| # | Criterion | Evidence | Result |
|---|-----------|----------|--------|
| 1 | team 内 shortlist + 可解释 breakdown | `test_shortlist.py`（排序/signals） | pass |
| 2 | planned charter force-include（能力分 0） | `test_shortlist.py`（charter_planned） | pass |
| 3 | out_of_team 永不进 shortlist | `test_shortlist.py`（D-01） | pass |
| 4 | 历史 demand/launch 分桶 ∩ team_core | `test_history_prior.py` | pass |
| 5 | 历史 fail-soft（no_acting_user / retrieval_error） | `test_history_prior.py` | pass |
| 6 | 四角色 primary + placement_defaults | `test_role_map.py` | pass |
| 7 | boundary 无 override 非 primary；unmapped → clarify | `test_role_map.py` | pass |
| 8 | Adapter 载荷 shortlist/role_map；候选 ⊆ shortlist | `test_funnel_shortlist.py` | pass |
| 9 | role_map clarify 不塞全库；128 funnel 不回归 | funnel_shortlist + funnel_team_gate | pass |
| 10 | 未改写 RepoRouterV2 | Phase 129 commits 文件列表无 `repo_router_v2.py` | pass |

## Automated tests

```text
cd server && uv run pytest \
  tests/services/process_runtime/test_funnel_shortlist.py \
  tests/services/process_runtime/test_funnel_team_gate.py \
  tests/services/process_runtime/test_shortlist.py \
  tests/services/process_runtime/test_history_prior.py \
  tests/services/process_runtime/test_role_map.py \
  -q --tb=short --reuse-db
# → 23 passed
```

## Key files

| Path | Role |
|------|------|
| `server/services/process_runtime/shortlist.py` | build_shortlist |
| `server/services/process_runtime/history_prior.py` | asplit_history_priors |
| `server/services/process_runtime/role_map.py` | RepoRole + build_role_map |
| `server/services/process_runtime/blueprint_route.py` | 漏斗中段接线 |
| `server/initiatives/services/repo_association_service.py` | shortlist 收窄 |

## Constraints checked

- [x] 未重写 `RepoRouterV2`（本相位 commits 未触及该文件）
- [x] Shortlist 宇宙 ⊆ team_core ∪ adjacent；out_of_team 剔除
- [x] D5 固定四角色；unmapped → clarify(unmapped_role)
- [x] 观测：structlog `category=sampling` / `component=process_runtime`；无需求原文；异常 redact

## Gaps

None blocking. Phase 130 承接放置单元与细 primary。

## Human needed

None.

## Self-Check: PASSED

- SUMMARY ×4 存在；VERIFICATION 存在
- Commits：`b53e78be` `a588eb30` `6793aa3e` `14766002` `064fa05b` `84d6e21b` `d4a0c30d` `ef9445d2`
- 自动化 23 passed
