# Phase 131 Research: 门禁系统 + 反思环

**Researched:** 2026-08-14  
**Domain:** process_runtime 漏斗收口（统一 gate 契约 + 五门 + 有界反思）  
**Confidence:** HIGH（源码实读；无新外部依赖；消费 128–130 已交付面）

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** 不推倒 RepoRouterV2；无大前端
- **D-02（D4）:** 发布默认 confirmation；auto_selected 仅当 role_map 完整 + 全 unit high + 双证据（charter/history ∪ role_map/shortlist/v2/reuse）
- **D-03:** 反思 N=2；只补丁受影响单元；超限 needs_human_review
- **D-04~D-06:** 统一 GateResult + evaluate_funnel_gates + 观测
- **D-07~D-11:** 五门语义（team / shortlist_coverage / unit_placement / global_consistency / publish）
- **D-12~D-15:** reflection 触发、结构化补丁、ledger
- **D-16~D-17:** Adapter/Association 接线；additive 观测字段

### Claude's Discretion
- reason_code 命名表
- 补丁执行归属（reflection 内 vs Adapter）
- association 明细深度
- needs_human_review 字段形态

### Deferred Ideas (OUT OF SCOPE)
- Phase 132 高三回归；GATE-F01；REFL-F01；大前端；重写 V2
</user_constraints>

<architectural_responsibility_map>
## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Gate 契约与五门求值 | Domain service (`funnel_gates.py`) | 既有 `team_gate.py` | 纯/轻变换；团队门包装不重写 |
| 发布 / auto_selected 纪律 | Domain service（publish 子函数） | Adapter 写出字段 | D4 产品锁在漏斗层落地 |
| 反思环 + 补丁 | Domain service (`reflection.py`) | place_units / shortlist 子集重算 | 有界回跳；禁止全库 |
| Ledger 回放 | interactions ledger | structlog | REFL-03；脱敏 |
| 主路径编排 | Adapter + RepoAssociationService | stage_sandbox | 门禁后阻断静默开工 |
| RepoRouterV2 | Frozen tool | — | 禁止改内核 |
</architectural_responsibility_map>

<research_summary>
## Summary

Phase 130 已产出 `placements[]`（primary/supporting/confidence/evidence/open_questions）并接入 Blueprint/Association，但 **缺少统一 pass|clarify|block 契约**、**全局一致性拦截**与 **发布确认 / auto_selected 纪律（D4）**。现状 `auto_selected` 仍可能跟 V2 置信度走，与「默认 confirmation」冲突。亦无有预算反思：冲突时只能一次 fail/clarify，不能局部回跳修复。

标准做法：在 placements 之后增加纯函数门禁报告；可修复类失败进入最多 2 轮反思，只重算 affected units；每轮写脱敏 ledger；最终 publish 门决定 confirmation vs auto_selected。

**Primary recommendation:** 新增 `funnel_gates.py` + `reflection.py`；Adapter/Association 在 placement 后接线；不改 `repo_router_v2.py`；不新建前端确认页（confirmation 为路由载荷语义，对接既有确认流即可）。
</research_summary>

## Current Codebase Facts

### 已交付（消费面）
- Team：`apply_team_gate` / Adapter `_clarify_result(missing_team|empty_team_core)`
- Shortlist / role_map / placement_defaults（129）
- `build_placement_units` / `place_units` / `_aapply_placement_funnel`（130）
- 守卫：`test_funnel_team_gate.py` / `test_funnel_shortlist.py` / `test_funnel_placement.py`

### 缺口
- 无统一 `reason_codes[]` 聚合；各段自造 status 字符串
- 无 global_consistency（双写状态域、壳散落、复用不改造）
- `auto_selected` 未按 D4 门禁
- 无 reflection loop / ledger 轮次

### Ledger
- `InteractionEvent.EventType.AGENT_DECISION` / `RETRY` 可用
- 写入前 `redact_for_ledger`；best-effort 子事件不反噬
- 无 run 时仅 structlog

### V2 freeze
- 反思重算若调 V2：必须 `repository_ids=hard_scope`（affected 子集 ∩ 原 scope）
- **成功标准：本相位 commits 不修改 `repo_router_v2.py`**

## Recommended Architecture

```text
team → shortlist → role_map → placement → place     # 128–130
        │
        ▼
 evaluate_funnel_gates(...)
   ├─ team
   ├─ shortlist_coverage
   ├─ unit_placement
   ├─ global_consistency   # GATE-03
   └─ publish              # D4
        │
        ├─ triggers repairable? ──► run_reflection_loop (≤2)
        │                              ├─ patch affected only
        │                              ├─ re-place / re-signal subset
        │                              └─ ledger + structlog per round
        │
        ▼
 FunnelGateReport + auto_selected + optional needs_human_review
 → Adapter / Association / MCP 出口
```

### Module layout
| Module | Responsibility |
|--------|----------------|
| `funnel_gates.py` | GateResult、五门、`evaluate_funnel_gates`、reason_codes |
| `reflection.py` | 触发检测、补丁、N 轮循环、ledger hook |
| `blueprint_route.py` | placements 后接线；auto_selected 收口 |
| `repo_association_service.py` | feature-list 同等门禁纪律 |
| `stage_sandbox.py` | block / needs_human_review 不得全库 primary |
| tests | `test_funnel_gates.py`、`test_reflection.py`、`test_funnel_gates_wiring.py` |

### GateResult（最小契约）
```text
{
  "gate_id": "team|shortlist_coverage|unit_placement|global_consistency|publish",
  "status": "pass|clarify|block",
  "reason_codes": ["..."],
  "evidence": [{"kind": "...", "unit_id": "...", "repo_id": "..."}],
  "affected_unit_ids": ["..."]
}
```

### ReflectionPatch（最小契约）
```text
{
  "round": 1,
  "contradictions": ["..."],
  "root_cause_hypotheses": ["..."],
  "jump_back_to": "shortlist|role_map|place_units",
  "repair_actions": [{"action": "re_place_units", "affected_unit_ids": ["u1"]}],
  "outcome": "resolved|partial|unresolved"
}
```

## Constraints & Pitfalls

| Pitfall | Mitigation |
|---------|------------|
| 重写 V2 做一致性 | 禁止；只用 placements/role_map 数据 |
| 反思全库重跑 | 补丁强制 affected_unit_ids；测断言 V2 mock 收到的 ids ⊆ hard_scope |
| auto_selected 仍跟 V2 | D-16：发布门独占 |
| 与 BlueprintConfirmGate 缠死 | 漏斗 publish 只改路由载荷；不改线程 UI |
| 日志/ledger 泄漏需求 | redact；只记 codes/ids/counts |
| 第三套状态词 | 映射既有 clarify；needs_human_review 可测锁定 |

## Out of Scope
- 高三回归、策略后台、对抗反思、大前端、重写 V2

## Package Legitimacy
无新 pip/npm 包。复用 Django、structlog、既有 funnel 模块、interactions ledger。

## Validation Architecture (Nyquist)

| Behavior | Test file | Command |
|----------|-----------|---------|
| 统一 status + reason_codes + evidence | `test_funnel_gates.py` | `uv run pytest .../test_funnel_gates.py -q` |
| 五门语义（含 GATE-03 四类） | 同上 | 同上 |
| D4 publish / auto_selected | 同上 | 同上 |
| 反思 N=2、只补丁 affected、超限 review | `test_reflection.py` | `uv run pytest .../test_reflection.py -q` |
| ledger/事件脱敏可回放 | 同上 | 同上 |
| Adapter/Association 接线；无全库 | `test_funnel_gates_wiring.py` | `uv run pytest .../test_funnel_gates_wiring.py -q` |
| 128–130 守卫不回归 | funnel_team/shortlist/placement | 子集套件 |

## Sources
- Primary: `team_gate.py`、`place_units.py`、`role_map.py`、`blueprint_route.py`、`repo_association_service.py`、`interactions/ledger.py`（2026-08-14）
- Locked: `v0.23.0-DECISIONS.md` D4；`131-CONTEXT.md`
- Prior: Phase 128–130 VERIFICATION/CONTEXT
