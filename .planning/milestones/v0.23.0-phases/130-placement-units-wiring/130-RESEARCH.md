# Phase 130 Research: 放置单元 + 主路径接线

**Researched:** 2026-08-14  
**Domain:** process_runtime 漏斗后段（placement units + shortlist-scoped place + main-path wiring）  
**Confidence:** HIGH（源码实读；无新外部依赖）

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** primary 不得出 shortlist 宇宙；out_of_team 不得 primary；reuse hosts 并入候选时仍 ∩ team，不开放全库
- **D-02:** 不推倒 RepoRouterV2；三分量降为漏斗内信号，不再单独决定整篇唯一 primary
- **D-03:** 消费 role_map + placement_defaults；禁止违反角色禁令
- **D-04~D-06:** `build_placement_units` — 同模块聚合 + 模块依赖边 + 「复用 X」边；单元契约含 unit_id/features/modules/query_text/reuse_*；无 acceptance
- **D-07~D-11:** `place_units` — hard_scope = shortlist ∪ reuse_host_repos；可调 V2；primary∉scope 丢弃；open_questions 显式
- **D-12~D-15:** Blueprint + RepoAssociation 主路径接线；MCP 至少 hard_scope；观测无需求原文

### Claude's Discretion
- 依赖边合并 vs unit 间边阈值
- 「复用 X」短语表与 host hint 映射
- unit 内 V2 use_llm 开关
- association 是否写满 role_map

### Deferred Ideas (OUT OF SCOPE)
- GATE/REFL → 131
- 高三四基线回归 → 132
- 大前端 / 章程自动生效 / 重写 V2
</user_constraints>

<architectural_responsibility_map>
## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Placement unit 聚合 | Domain service (`placement_units.py`) | — | 纯/轻 IO 的 feature→unit 变换 |
| Unit 内细落点 | Domain service (`place_units.py` 或同模块) | RepoRouterV2（只读调用） | hard_scope 内打分；V2 为工具非决策中枢 |
| Funnel 接线 | Adapter (`blueprint_route.py`) + `RepoAssociationService` | stage_sandbox | 主路径编排 INT-01 |
| 角色约束 | Existing `role_map.py` | — | 129 已交付，本相位只消费 |
| V2 能力树/LLM 路由 | Frozen tool (`repo_router_v2.py`) | — | 禁止改内核 |
</architectural_responsibility_map>

<research_summary>
## Summary

Phase 129 已把候选收窄到 shortlist 并导出角色图，但主路径仍接近「一次（或切块）V2 + 三分量融合 → 单一仓排序」：`BlueprintRouteAdapter` 在 shortlist 后仍对整 query 调 V2；`RepoAssociationService` 对 feature list 用 `corpus_kind=requirement` 全切全探后再做 charter/history 融合。这与 UNIT「按连贯单元落点」及 INT-01「三分量不再唯一决策」冲突。

标准做法：先把 feature 点聚成少量 Placement Units（模块 + 依赖 + 复用边），再对每个 unit 在 `shortlist ∪ reuse_hosts` 内细排，产出可解释的 primary/supporting/confidence/evidence/open_questions；Adapter/Association 改为编排该漏斗。

**Primary recommendation:** 新增 `placement_units.py`（聚合 + place），Adapter/Association 在 role_map 后接线；V2 仅 `repository_ids=hard_scope`；不改 `repo_router_v2.py`。
</research_summary>

## Current Codebase Facts

### Phase 129 已交付（消费面）
- `build_shortlist` / `asplit_history_priors` / `build_role_map` + `PLACEMENT_DEFAULTS`
- Adapter：`team_gate → history_prior → shortlist → role_map → V2(repository_ids=shortlist) → charter/history 融合`
- Association：team_core → shortlist 收窄 → V2 requirement 切块 → 三分量融合
- 守卫测：`test_funnel_shortlist.py`（候选 ⊆ shortlist）

### Feature list 形状
- `modules[{name, features[{name, description, acceptance}]}]` + `features_flat[{module, name, description, ...}]`
- Blueprint：`_requirement_spec_to_feature_list` 可从 requirement_spec 派生 flat
- 高三 demo：模块总览含「依赖模块」；正文大量「复用端内做题组件 / 复用通用知识点播放器」——正则/短语可抽 reuse 边

### RepoRouterV2（只调不改）
- `route(query, top_k=, repository_ids=, use_llm=, corpus_kind=)`
- 传入 `repository_ids` 即收窄；本相位 hard_scope 必须显式传入
- **成功标准：本相位 commits 不修改 `repo_router_v2.py`**

### 三分量现状
- `build_score_breakdown(router_base, charter_match, history_match)` 在 Adapter 与 Association 共用
- INT-01：保留为 unit 内信号；整篇唯一决策路径改为 placements 聚合结果（例如按 unit primary 去重为候选集，或显式 `placements[]` 主导）

### Observability
- 既有：`blueprint_route_*`、`shortlist_*`、`role_map_*`、`repo_association_*`
- 新增：`placement_units_*` / `place_units_*`；`component=process_runtime`；无需求原文

## Recommended Architecture

```text
team_gate → shortlist(+history) → role_map          # Phase 129
        │
        ▼
 build_placement_units(feature_list|flat+modules)
   ├─ group by module
   ├─ merge/link via module dependency edges
   ├─ parse 「复用 X」 → reuse_edges + reuse_host_hints
   └─ PlacementUnit{id, features, modules, query_text, reuse_*}
        │
        ▼
 place_units(units, shortlist_ids, role_map, placement_defaults, ...)
   ├─ hard_scope = shortlist ∪ resolve_reuse_hosts(hints, role_map) ∩ team
   ├─ optional RepoRouterV2.route(unit.query_text, repository_ids=hard_scope)
   ├─ optional charter/history scores as signals (not sole decider)
   ├─ apply placement_defaults + forbidden demotion
   └─ Placement{primary_repo, supporting_repos, confidence, evidence, open_questions}
        │
        ▼
 Adapter / RepoAssociation：routing 摘要以 placements 为准；观测写 unit_count/placement_count
```

### Module layout
| Module | Responsibility |
|--------|----------------|
| `placement_units.py` | `build_placement_units`、PlacementUnit 契约、reuse 边解析 |
| `place_units.py`（或同文件下半） | `place_units`、hard_scope、V2 调用边界、defaults 应用 |
| `blueprint_route.py` | role_map 后接线；候选/摘要改 placements |
| `repo_association_service.py` | feature-list 主路径改漏斗；三分量降级为信号 |
| `stage_sandbox.py` | 轻量 hard_scope 守卫（与 129 一致） |
| tests | `test_placement_units.py`、`test_place_units.py`、`test_funnel_placement.py` |

### PlacementUnit（最小契约）
```text
{
  "unit_id": "u1",
  "feature_ids": ["..."],
  "module_names": ["真题检测"],
  "query_text": "模块级/单元级检索语料",
  "reuse_edges": [{"raw": "复用端内做题组件", "hint": "practice_component"}],
  "reuse_host_hints": ["practice_reuse_host"]
}
```

### PlacementResult（最小契约）
```text
{
  "unit_id": "u1",
  "primary_repo": "<uuid>|null",
  "supporting_repos": ["..."],
  "confidence": "high|medium|low",
  "evidence": [{"kind": "role_map|shortlist|v2|charter|history|reuse", "...": "..."}],
  "open_questions": ["..."],
  "hard_scope_count": N,
  "degrade_reasons": []
}
```

## Constraints & Pitfalls

| Pitfall | Mitigation |
|---------|------------|
| 改 V2 内核做放置 | **禁止**；只调 `repository_ids=hard_scope` |
| place 时漏传 repository_ids → 全库 | 硬编码必传；单测断言 mock 收到的 ids ⊆ shortlist∪hosts |
| reuse host 拉入 out_of_team | ∩ team_core∪合法 adjacent |
| 整篇仍用三分量唯一决策 | INT-01：Association/Adapter 主路径以 placements 为准 |
| acceptance/测试用例进 query_text | 复用 `select_profile_corpus` 纪律；单元语料只用 name/description/module |
| 日志泄漏需求原文 | 只记 unit_count、id 长度、reason；redact |
| 43 点各自一次 V2 | 聚合后按 unit 调用，unit 数 ≪ feature 数（测断言） |

## Out of Scope
- GATE/REFL、高三回归、大前端、重写 V2、活跃度 v2 混合项

## Package Legitimacy
无新 pip/npm 包。复用 Django、structlog、既有 shortlist/role_map/V2。

## Validation Architecture (Nyquist)

| Behavior | Test file | Command |
|----------|-----------|---------|
| 同模块聚合 + 复用边 | `test_placement_units.py` | `uv run pytest .../test_placement_units.py -q` |
| 依赖边减少单元数 | 同上 | 同上 |
| query_text 无 acceptance | 同上 | 同上 |
| hard_scope 内 primary；∉scope 丢弃 | `test_place_units.py` | `uv run pytest .../test_place_units.py -q` |
| V2 调用带 repository_ids=hard_scope | 同上 | 同上 |
| placement_defaults 生效 | 同上 | 同上 |
| Adapter/Association placements 主导；无全库 | `test_funnel_placement.py` | `uv run pytest .../test_funnel_placement.py -q` |
| 129 shortlist 守卫不回归 | `test_funnel_shortlist.py` + team_gate | 全量 process_runtime 子集 |

## Sources
- Primary: `shortlist.py`、`role_map.py`、`blueprint_route.py`、`repo_association_service.py`、`repo_router_v2.py`、`initiative_profile.py`（2026-08-14）
- Locked: `v0.23.0-DECISIONS.md`；`130-CONTEXT.md`
- Prior: Phase 129 RESEARCH/VERIFICATION；`.planning/feature-list-demo.md`（复用边语料）
