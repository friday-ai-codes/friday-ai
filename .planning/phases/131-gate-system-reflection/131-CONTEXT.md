# Phase 131: 门禁系统 + 反思环 - Context

**Gathered:** 2026-08-14
**Status:** Ready for planning
**Mode:** Smart discuss auto-accepted（v0.23.0-DECISIONS D4 + Defaults 反思 N=2；灰区由 smart discuss 定夺）

<domain>
## Phase Boundary

本相位在 Phase 130 的 placement units + 主路径接线之后，交付漏斗收口两块：

1. **统一门禁（GATE）**：全阶段统一输出 `pass | clarify | block` + `reason_codes[]` + evidence；至少落地团队门、短名单覆盖门、单元落点门、全局一致性门、发布门。
2. **有界反思环（REFL）**：证据冲突 / 角色坍塌 / 复用矛盾 / 覆盖空洞等触发反思；最多 N=2 轮；补丁只重算受影响短名单/单元；超限 → `needs_human_review`；每轮写 ledger/事件（脱敏）可回放。

**不实现**：高三提分四基线回归门槛与 INT-03 全量契约套件（132）、门禁策略运营后台（GATE-F01）、多 Agent 对抗式反思（REFL-F01）、路由控制台大前端、章程自动生效。**禁止重写** `RepoRouterV2`。

</domain>

<decisions>
## Implementation Decisions

### Locked product（v0.23.0-DECISIONS + Defaults）
- **D-01（← Defaults）:** 不推倒 `RepoRouterV2`；演进 `BlueprintRouteAdapter` / `RepoAssociationService`；无大前端。
- **D-02（← D4 / GATE-02）:** Feature-list 漏斗发布门默认 **confirmation**；`auto_selected=True` **仅当**同时满足：(a) role_map 完整（status=ok 且所需角色有 primary 指派）；(b) 全部 placement units `confidence=high`；(c) **双证据**：每个 unit 至少一条 evidence.kind ∈ `{charter, history}`，且至少一条 ∈ `{role_map, shortlist, v2, reuse}`。任一不满足 → 不得 auto_selected，须确认门（P0 未确认不可下游开工）。
- **D-03（← Defaults）:** 反思最多 **N=2**；补丁只重算受影响短名单/单元；超限 → `needs_human_review`。

### 统一门禁契约（GATE-01）
- **D-04:** 新模块 `server/services/process_runtime/funnel_gates.py`（可拆 `gate_types.py`），导出统一结果类型：`status ∈ {pass, clarify, block}`、`reason_codes: list[str]`、`evidence: list[dict]`、`gate_id`、可选 `open_questions` / `affected_unit_ids`。
- **D-05:** 编排入口 `evaluate_funnel_gates(...)`：按固定顺序跑五门，聚合为 `FunnelGateReport`（per-gate 结果 + 最严重 status：block > clarify > pass）+ 顶层 `reason_codes` 去重合并。既有 team_gate clarify 载荷 **映射进**统一契约，不另造第三套状态词。
- **D-06:** structlog：`funnel_gates_started/completed/failed` 及分门 `funnel_gate_<id>_evaluated`（sampling）；`component=process_runtime`；只记 gate_id / status / reason_codes / counts / duration_ms；禁止需求全文与召回正文。

### 五门语义（GATE-02 / GATE-03）
- **D-07 团队门 `team`:** 包装既有 `apply_team_gate` / Adapter clarify：缺团队/空 team_core → `clarify`（reason `missing_team` / `empty_team_core`）；`out_of_team` 作 primary → `block`（`out_of_team_primary`）。不重写团队解析。
- **D-08 短名单覆盖门 `shortlist_coverage`:** shortlist 空且存在 feature/unit → `clarify`（`empty_shortlist`）；任一 unit 的 hard_scope 空或与 shortlist∪reuse 无交 → `clarify`（`coverage_hole`）；force-include 所需仓缺失且无 degrade 说明 → `clarify`（`force_include_uncovered`）。
- **D-09 单元落点门 `unit_placement`:** unit 无 primary 且无合法 open_question 路径 → `clarify`（`missing_primary`）；primary ∉ hard_scope → `block`（`primary_out_of_scope`）；P0/高优先级 unit 仍有 blocking open_questions → `clarify`（`unit_open_questions`）。
- **D-10 全局一致性门 `global_consistency`（GATE-03）:** 至少拦截并产出对应 reason_codes：
  1. `out_of_team_primary` / `primary_outside_universe` — primary 出 team/shortlist 宇宙；
  2. `dual_state_domain_writer` — ≥2 个不同 primary 声称 `learning_state` 写方（或 placement_defaults 等价冲突）；
  3. `app_shell_scattered` — 页面壳/壳类 unit 的 primary 散落多个 `app_shell` 仓（同需求多壳 primary）；
  4. `reuse_modify_forbidden` — 标记「复用」的 unit 却把 reuse host 当作可改造 primary 且违反 role/boundary「复用不改造」。
  命中默认 `block`（可附 evidence 指向 unit_id / repo_id / role）。
- **D-11 发布门 `publish`:** 默认 `publish_mode=confirmation` → 门结果 `clarify`（`needs_confirmation`）且 `auto_selected=False`，直到调用方显式 `confirmation_acked=True` 或满足 D-02 自动条件。满足 D-02 → `pass` 且允许 `auto_selected=True`。未确认时下游编码/开工路径必须看到非 pass（P0）。

### 反思环（REFL-01/02/03）
- **D-12:** 新模块 `server/services/process_runtime/reflection.py`，入口 `run_reflection_loop(...)`。触发条件（任一）：证据冲突（同 unit charter vs history 矛盾）、角色坍塌（role_map clarify / forbidden 被选 primary）、复用矛盾（reuse_modify / host 缺失）、覆盖空洞（coverage_hole / empty_shortlist 可修复类）、全局一致性可局部修复类 reason。
- **D-13:** 每轮产出结构化补丁：`contradictions[]`、`root_cause_hypotheses[]`、`jump_back_to`（`shortlist` | `role_map` | `place_units`）、`repair_actions[]`（含 `affected_unit_ids` / `affected_repo_ids`）、`round`。执行时 **只** 对 affected 子集重跑 shortlist 增量信号或 `place_units` 子集；**禁止**无 `repository_ids` 的全库 V2、禁止重跑无关 unit。
- **D-14:** `max_rounds=2`（可注入）；仍触发且未 resolve → 顶层 status `needs_human_review`（映射对外：`clarify` + reason `needs_human_review`，或显式字段 `review_status=needs_human_review`，载荷二者择一但必须可观测且单测锁定）。
- **D-15:** 每轮：structlog `reflection_round_started/completed/failed`（sampling）+ best-effort Interaction Ledger：`arecord_event` / `record_event`，`event_type=agent_decision`（或 `retry`），payload 经 `redact_for_ledger`，含 round / trigger_codes / jump_back_to / affected_unit_ids / outcome；无需求全文。无 run 上下文时仅 structlog，不造假 run。

### 主路径接线
- **D-16:** `BlueprintRouteAdapter`：在 Phase 130 placements 之后调用 `evaluate_funnel_gates`；若报告含可反思 trigger 且未超预算，调用 `run_reflection_loop` 再评估；最终 `auto_selected` **只**由发布门/D-02 决定（覆盖旧 V2 置信度路径）。`RepoAssociationService` feature-list 主路径同等消费门禁报告（至少 block/clarify 阻断静默开工；publish confirmation 语义一致）。MCP/stage_sandbox：不得在 gate=block 或 needs_human_review 时返回全库 primary。
- **D-17:** 观测字段 additive：`funnel_gates`、`publish_mode`、`reflection`（rounds / final_status）；入口 `caller` 事件可附 gate 摘要计数，内部 sampling。

### Claude's Discretion
- reason_code 字符串表精确命名（须稳定、可测、snake_case）
- 反思补丁内「重算」是同步调用 place_units 子集还是返回 patch 由 Adapter 执行（须单测证明未全库重跑）
- association 是否写满 reflection 明细或只写 gate 摘要（优先：Blueprint 写满；association 至少 gate status + auto_selected 纪律）
- `needs_human_review` 是顶层 status 字段还是 reason_code（须与既有 clarify 载荷兼容、可测）

</decisions>

<specifics>
## Specific Ideas

- Phase 128–130 已有 team_gate / shortlist / role_map / placements 与 funnel 守卫测；本相位是 **统一契约 + 聚合门 + 反思**，不是重做团队解析。
- 既有 `BlueprintConfirmGateAdapter`（蓝图阶段确认门）与本相位 **漏斗发布门** 互补：本相位管「路由结果能否 auto / 须确认」；不替换蓝图 repo_confirmation 线程模型，不扩大前端。
- 高三四基线回归属 Phase 132；本相位用合成 placements/role_map 证明五门与反思预算即可。
- INT-03「角色坍塌→反思修复」合成用例可在本相位落最小一条，132 再扩回归套件。

</specifics>

<canonical_refs>
## Canonical References

### Product / requirements
- `.planning/milestones/v0.23.0-DECISIONS.md` — **D4 publish gate**；Defaults 反思 N=2
- `.planning/REQUIREMENTS.md` — GATE-01~03、REFL-01~03
- `.planning/ROADMAP.md` — Phase 131 success criteria
- `.planning/PROJECT.md` — 漏斗收口：一致性门禁与反思

### Prior phases
- `.planning/phases/130-placement-units-wiring/130-CONTEXT.md` / `130-VERIFICATION.md`
- `.planning/phases/129-shortlist-history-role-map/129-CONTEXT.md`
- `.planning/phases/128-initiative-profile-team-gate/128-CONTEXT.md`

### Observability
- `.planning/observability/LOGGING-SPEC.md`
- `server/interactions/ledger.py` — `redact_for_ledger` / `arecord_event`

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `team_gate.py` — resolve/annotate/apply
- `shortlist.py` / `role_map.py` / `place_units.py` / `placement_units.py`
- `blueprint_route.py` — `_aapply_placement_funnel` 之后挂门禁
- `repo_association_service.py` — feature-list 主路径
- `blueprint_confirm_gate.py` — 确认门模式参考（不直接复用 UI/线程）
- `interactions/ledger.py` — 事件写入

### Established Patterns
- fail-soft + 显式 clarify；additive payload
- structlog kv + category + component；无需求原文
- TDD：Wave1 纯模块 → Wave2 反思 → Wave3 接线
- V2 freeze：commits 不含 `repo_router_v2.py` 业务改动

### Integration Points
- Adapter：placements → **gates → reflection → publish/auto_selected**
- Association / MCP：消费统一 status，禁止静默开工
- Phase 132：消费门禁/反思可回放轨迹做回归

</code_context>

<deferred>
## Deferred Ideas

- 高三四基线 hit@primary / out_of_team=0 门槛 → Phase 132 / D2
- GATE-F01 可配置策略包运营后台
- REFL-F01 多 Agent 对抗式反思
- 路由控制台大前端 / 章程自动生效
- 推倒重写 RepoRouterV2 → 禁止

</deferred>
