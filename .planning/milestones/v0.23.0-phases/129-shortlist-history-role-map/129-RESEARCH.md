# Phase 129 Research: 短名单 + 历史先验 + 章程角色图

**Researched:** 2026-08-14  
**Domain:** process_runtime 漏斗中段（shortlist + history prior + role map）  
**Confidence:** HIGH（源码实读；无新外部依赖）

## Summary

Phase 129 在 Phase 128 的 `team_core` 硬门禁之后增加两层可单测能力：`build_shortlist`（活跃度 + 能力粗相关 + 章程域 + 历史 force-include）与 `build_role_map`（固定四角色主/辅/禁 + boundaries 降级 + `placement_defaults`）。**禁止改写** `RepoRouterV2` 内核；在已收窄的 `repository_ids` 上把它当黑盒信号源。演进面：`blueprint_charter_match.acollect_charter_candidates`、`blueprint_route_history.ascore_history_match`（拆 demand/launch）、`BlueprintRouteAdapter` 在 team_gate 后接线。

## Current Codebase Facts

### Team gate（128 已交付）
- `team_gate.resolve_team_core` / `apply_team_gate`：空/缺团队 → clarify；primary 仅 `team_core`
- `team_adjacent` 仅预留枚举；**证据校验（章程复用/历史）在本相位落实**（128 RESEARCH Out of Scope）
- 漏斗三入口已 hard gate：Blueprint / RepoAssociation / MCP sandbox

### InitiativeProfile
- 字段：`product_form`、`domains`、`change_kind`、`capability_clusters`、`non_goals`、`reuse_summary`
- 可作 shortlist 粗相关 query 的结构化输入（勿回灌 acceptance）

### Charter match（可演进）
- `score_charter_match`：`owned_implemented=1.0`、`owned_planned=0.7`、`boundary_hit=-1.0`
- `acollect_charter_candidates`：planned/implemented domain 命中补入（能力树 0 分仍可进候选）——**LIST-02 的机制雏形**，shortlist 应正式消费并写入 `force_include_reasons=charter_planned`
- 纯函数 vs ORM 分离；fail-soft

### History match（可演进）
- `HISTORY_ENTITY_KINDS = ["code_change", "tech_plan", "document"]` 单次检索
- document 走 artifact 边归因；无 actor → `unavailable_reason=no_acting_user`
- **缺口（LIST-03）**：结果未拆「需求史 vs 上线史」标签；shortlist force-include 需按 entity kind 分桶后与 `team_core` 求交

### BlueprintRouteAdapter
- 顺序现状：pin → profile → team_gate → V2(`repository_ids=team_core`) → charter/history 融合 → boundary override
- 本相位插入点：team_gate 通过后 → **shortlist** → **role_map** → 后续融合候选硬限制在 shortlist（V2 细排不得再扩到全 team 外，更不得全库）
- `resolve_boundary_override`：boundary 命中需显式理由——ROLE-02 直接复用

### RepoRouterV2（只调不改）
- Stage0：`repo_index_nodes` hybrid；活跃度 last_commit 聚合 + facets 回退
- `grouping_repository_ids` 仍 annotate-only
- shortlist 的 `capability_coarse` / `activity`：调用方传入 `repository_ids=team_core∪adjacent`，读取候选分数进 breakdown；**零改 V2 文件为成功标准**（可用测试/守卫断言）

### Observability
- 既有：`blueprint_route_*`、`blueprint_route_history_*`、`initiative_profile_*`、`team_gate_*`
- 新增事件须：`category`、`component=process_runtime`、`duration_ms`、计数字段；历史召回续写 RetrievalTrace 指标，不写正文

## Recommended Architecture

```text
team_gate pass (team_core, optional adjacent stubs)
        │
        ▼
 build_shortlist(...)
   ├─ universe = team_core ∪ evidence_adjacent
   ├─ activity(repo) + capability_coarse(V2|stage0 within universe, query←profile)
   ├─ charter_domain hits + acollect planned → force_include(charter_planned)
   ├─ history_priors ∩ team_core → force_include(history_demand|history_launch)
   └─ ranked ShortlistResult{repos[], breakdown[], force_includes[], meta}
        │
        ▼
 build_role_map(shortlist, charters, profile)
   ├─ map domains → {app_shell, practice_reuse_host, course_config, learning_state}
   ├─ assignment primary|supporting|forbidden
   ├─ boundary_hit → forbidden/demote unless override reason
   ├─ unmapped owned domain → clarify(unmapped_role)
   └─ placement_defaults for Phase 130
        │
        ▼
 BlueprintRouteAdapter：融合/细排候选 ⊆ shortlist；stage 观测携带 shortlist+role_map
```

### Module layout
| Module | Responsibility |
|--------|----------------|
| `shortlist.py` | `build_shortlist`、信号合成、breakdown、观测 |
| `history_prior.py`（或扩展 `blueprint_route_history.py`） | `asplit_history_priors` → demand/launch ids + force_include |
| `role_map.py` | 枚举、映射、boundary 处理、`placement_defaults` |
| tests | `test_shortlist.py`、`test_history_prior.py`、`test_role_map.py`、`test_funnel_shortlist.py` |

### ShortlistResult（最小契约）
```text
{
  "status": "ok" | "clarify",
  "clarify_reason": "" | "unmapped_role" | ...,
  "repositories": [{"repository_id", "rank", "score", "team_membership", "signals": {...}, "force_include_reasons": []}],
  "shortlist_count": N,
  "duration_ms": ...,
  "degrade_reasons": []
}
```

### RoleMapResult（最小契约）
```text
{
  "status": "ok" | "clarify",
  "clarify_reason": "" | "unmapped_role",
  "roles": {
     "app_shell": {"primary": id|null, "supporting": [], "forbidden": []},
     ...
  },
  "per_repo": [{"repository_id", "role", "assignment", "evidence": [...], "violated_boundaries": []}],
  "placement_defaults": {"learning_state_writer_not_app_shell": true, ...}
}
```

### History prior split
- `demand` ← entity.kind == `tech_plan`
- `launch` ← `document` | `code_change`
- Force-include：桶内 top_score 过阈值（discretion，须可测）且 `repository_id ∈ team_core`；adjacent 仅当 charter/reuse 证据同时成立

## Constraints & Pitfalls

| Pitfall | Mitigation |
|---------|-----------|
| 改 V2 内核做 shortlist | **禁止**；只调 `route(..., repository_ids=...)` 取分 |
| force-include 拉入 out_of_team | 与 team_core 求交；adjacent 要证据 |
| 历史单桶无法区分需求/上线 | `asplit_history_priors` 按 kind 打标 |
| 角色枚举膨胀 | 锁四枚举；不可映射 → clarify |
| boundary 只降权仍当 primary | ROLE-02：无 override → 不得 primary |
| 日志泄漏需求原文 | 只记 count/reason/ids 长度；redact |
| shortlist 后再对全 team 外扩 V2 | Adapter 硬限制候选 ⊆ shortlist |

## Out of Scope
- Placement units / RepoRouterV2 细 primary 编排 → 130
- GATE/REFL → 131
- 高三四基线回归 → 132
- 近 90d commit 混合活跃度 → 不做

## Package Legitimacy
无新 pip/npm 包。复用 Django ORM、structlog、既有 knowledge retrieval、RepoRouterV2。

## Architectural Responsibility Map

| Concern | Tier | Owner |
|---------|------|-------|
| Shortlist 纯逻辑 | Domain service | `shortlist.py` |
| History 分桶 | Domain service | `blueprint_route_history` / `history_prior` |
| Role map | Domain service | `role_map.py` |
| Funnel 接线 | Adapter | `blueprint_route.py`（+ 轻量 association/MCP 收窄） |
| V2 能力树 | Frozen tool | `repo_router_v2.py`（只读调用） |

## Validation Architecture (Nyquist)

| Behavior | Test file | Command |
|----------|-----------|---------|
| team 内 shortlist + breakdown | `test_shortlist.py` | `uv run pytest .../test_shortlist.py -q` |
| planned charter force-include | 同上 | 同上 |
| history demand/launch force-include ∩ team_core | `test_history_prior.py` | `uv run pytest .../test_history_prior.py -q` |
| 四角色映射 + unmapped clarify | `test_role_map.py` | `uv run pytest .../test_role_map.py -q` |
| boundary 无 override 非 primary | 同上 | 同上 |
| placement_defaults 导出 | 同上 | 同上 |
| Adapter 候选 ⊆ shortlist；无需求原文日志 | `test_funnel_shortlist.py` | `uv run pytest .../test_funnel_shortlist.py -q` |
| V2 内核未改（守卫） | 既有 `test_repo_router_v2*` 或 grep 守卫 | 选择性 |

## Sources
- Primary: `team_gate.py`、`initiative_profile.py`、`blueprint_charter_match.py`、`blueprint_route_history.py`、`blueprint_route.py`、`repo_router_v2.py`、`charter_route_signal.py`（2026-08-14）
- Locked: `v0.23.0-DECISIONS.md` D1/D5；`129-CONTEXT.md`
- Prior: Phase 128 RESEARCH/VERIFICATION
