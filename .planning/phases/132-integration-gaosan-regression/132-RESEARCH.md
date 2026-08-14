# Phase 132: 集成验收与高三提分回归 - Research

**Researched:** 2026-08-14  
**Domain:** 漏斗集成回归 / placement-unit 验收 harness / 契约套件  
**Confidence:** HIGH（128–131 VERIFICATION + 源码 + quick 评测对照；无新外部依赖）

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** placement-unit 级评测（非 43 点 top1）
- **D-02:** 四基线各至少一次 unit primary（含 alias 归一）
- **D-03:** out_of_team primary count == 0
- **D-04:** Learning-tools Space + 漏斗（charter/history），禁止裸 V2 作验收主路径
- **D-05:** 不推倒 RepoRouterV2；无大前端
- **D-06~D-08:** 合成 fixture 优先；quick 仅参考；门槛文档化 = 每基线≥1 + out_of_team=0
- **D-09~D-10:** `gaosan_eval` 纯函数 bar + 漏斗回归测
- **D-11~D-13:** INT-03 契约包 + 接线级 role_collapse→reflection + V2 freeze

### Claude's Discretion
- fixture 单元数量；live_space 放置；契约包组织方式；角色覆盖硬/软断言（默认硬：四角色有 primary 或等价）

### Deferred Ideas (OUT OF SCOPE)
- GATE-F01 / REFL-F01 / 大前端 / 43 点 top1 CI / 可配置 hit% 后台
</user_constraints>

<architectural_responsibility_map>
## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| D2 bar 计算与归一 | Domain service（`gaosan_eval.py`） | pytest | 纯函数可测；不进 API |
| 合成 Learning-tools 宇宙 | Test fixtures | — | CI 无活 Space |
| 漏斗路径驱动到 placements | process_runtime Adapter / place_units | stubs | D-04 强制漏斗 |
| 活 Space 可选评测 | scripts / marked tests | quick 语料 | 默认 skip |
| INT-03 契约聚合 | pytest suite | MCP 契约子集 | 不回归 |
| 角色坍塌→反思接线 | reflection + BlueprintRouteAdapter | gates | 扩 131 钩子 |
| RepoRouterV2 | Frozen | stub only | 禁止改内核 |
</architectural_responsibility_map>

<research_summary>
## Summary

Phases 128–131 已交付完整漏斗（画像→团队→短名单→角色→放置→门禁→反思）并各自 VERIFICATION passed。Phase 132 **不再造新漏斗阶段**，而是：(1) 把 D2 验收门槛落成可自动化的 placement-unit bar；(2) 用合成 Learning-tools 宇宙在 CI 证明四基线 primary 覆盖与 out_of_team=0；(3) 收口 INT-03 契约包与接线级反思修复用例。

历史 quick 评测（260809 / 260811）证明 **裸 V2** 在高三语料上不稳定（study-course 召回天花板、onion-learning 被剔、out_of_team 漂移）。D2 明确要求漏斗路径验收，因此回归不得把旧 JSON 的 top1 分布当 pass 标准；旧结果只作「失败模式 / alias / Space id」参考。

**Primary recommendation:** 新增 `gaosan_eval` 纯函数 + 合成 fixture 漏斗回归测断言 D2；另建 INT-03 契约聚合与 Adapter 级 role_collapse→reflection 用例；可选 `@pytest.mark.live_space` 跳过。无新 pip 依赖。
</research_summary>

## Current Codebase Facts

### 集成面（128–131 VERIFICATION）

| Phase | Surface | Pytest 锚点 |
|-------|---------|-------------|
| 128 | profile + team_gate | `test_initiative_profile` / `test_team_gate` / `test_funnel_team_gate` |
| 129 | shortlist + history + role_map | `test_shortlist` / `test_history_prior` / `test_role_map` / `test_funnel_shortlist` |
| 130 | placement units + place + INT-01 wiring | `test_placement_units` / `test_place_units` / `test_funnel_placement` |
| 131 | gates + reflection + wiring | `test_funnel_gates` / `test_reflection` / `test_funnel_gates_wiring`（49 passed） |

主路径文件：`blueprint_route.py`（`_aapply_placement_funnel`）、`repo_association_service.py`、`stage_sandbox.py`、`funnel_gates.py`、`reflection.py`。

### D2 与旧评测差距
- 旧：feature-point / V2 top_k 召回率（常 <4/4）。
- 新：placement-unit 级「每基线至少一次 primary」+ out_of_team=0。
- Alias：payload/`repo_name` 可能缺 `frontend/`/`backend/` 前缀（260809 SUMMARY 已记）——bar 必须归一。

### INT-03 钩子现状
- `test_reflection.py::test_role_collapse_repair_path_for_int03_hook` 已证明纯函数路径。
- 缺口：Adapter/wiring 层尚未强制「坍塌 → reflection → 修复后无 role_collapse」。

### Package Legitimacy
- **无新包安装。** 沿用 pytest / structlog。

## Recommended Architecture

```text
[合成 Learning-tools fixture]
  team_core = 4 baselines (+ optional adjacent)
  out_of_team = decoys (study-app, study-practice, …)
  modules/features (compact 高三)
  charter / history / role signals
        │
        ▼
 funnel stubs → shortlist → role_map → place_units → gates[/reflection]
        │
        ▼
 gaosan_eval.score_placement_bar(placements, membership)
        │
        ├─ missing_baselines == []
        ├─ out_of_team_primary_count == 0
        └─ (discretion) four RepoRole primaries covered
```

### Module layout

| Path | Responsibility |
|------|----------------|
| `server/services/process_runtime/gaosan_eval.py` | D2 bar 纯函数 + alias 归一 + 常量 |
| `server/tests/fixtures/gaosan_learning_tools/`（或 `tests/services/process_runtime/fixtures/gaosan_*`） | 合成 Space / modules / membership |
| `server/tests/services/process_runtime/test_gaosan_eval.py` | bar 单元测 |
| `server/tests/services/process_runtime/test_gaosan_funnel_regression.py` | INT-02 漏斗回归 |
| `server/tests/services/process_runtime/test_int03_contracts.py`（或 marker 文档 + wiring 扩测） | INT-03 |
| 可选 `scripts/gaosan_live_space_eval.py` | live_space skip 路径 |

### Pitfalls
1. 误用 43 点 top1 或复用 260811 JSON 当 pass 标准 → 违反 D-01/D-04。
2. 合成 fixture 把四基线硬编码进 `place_units` 绕过漏斗 → 假绿；须走 shortlist/role/place（可 stub 分数但仍经入口）。
3. alias 漏归一导致 `onion-practice` vs `frontend/onion-practice` 双计/漏计。
4. live Space 测进默认 CI → 不稳定；必须 mark + skip。
5. 修改 `repo_router_v2.py`「顺便修」→ 违反 freeze。
6. 日志写入 feature list 全文 → 观测违规。

### Validation Architecture
- Framework: pytest（server `uv run pytest`）
- Wave 0: 无新框架；RED 任务创建 `test_gaosan_*.py`
- Quick: gaosan_eval + gaosan_funnel + reflection collapse
- Full: 上述 + 128–131 funnel 契约列表 + 选定 mcp_tools
- Manual: 可选 live_space 一次（非门禁）

## Source Audit Seeds（for planner）

| SOURCE | ID | Item |
|--------|-----|------|
| GOAL | — | 高三锚点四基线 primary + out_of_team=0；契约不回归；合成反思用例 |
| REQ | INT-02 | D2 bar + 漏斗路径 |
| REQ | INT-03 | 契约包 + role_collapse→reflection |
| CONTEXT | D-01..D-13 | 见上 |
| RESEARCH | harness + fixtures + pitfalls | 本文件 |

## Out of Scope
- 新前端、新策略后台、重写 V2、把裸 V2 5 轮复跑纳入 CI 必过
