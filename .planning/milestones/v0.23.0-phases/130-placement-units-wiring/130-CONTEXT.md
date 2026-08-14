# Phase 130: 放置单元 + 主路径接线 - Context

**Gathered:** 2026-08-14
**Status:** Ready for planning
**Mode:** Smart discuss auto-accepted（v0.23.0-DECISIONS D1–D5 + Phase 129 shortlist/role_map/history_prior；灰区由 smart discuss 定夺）

<domain>
## Phase Boundary

本相位在 Phase 129 的 shortlist + role_map + history_prior 之后，交付漏斗后段中的两块：

1. **放置单元（Placement Units）**：将 feature 点按模块依赖与正文「复用 X」边聚合，避免 43/45 点各自独立全库检索。
2. **shortlist 内细落点**：每个放置单元产出 `primary_repo` + `supporting_repos[]` + confidence + evidence + open_questions；细排可调用 `RepoRouterV2`，但候选硬限制在 shortlist（∪ 复用宿主）。
3. **主路径接线（INT-01）**：蓝图路由 / 项目选仓主路径走决策漏斗（或等价编排）；三分量加权作为漏斗内信号，不再作为唯一决策。

**不实现**：统一门禁 pass|clarify|block 与反思环（131）、高三提分四基线回归门槛（132）。**禁止重写** `RepoRouterV2`——仅作 shortlist∪reuse-host 范围内的细排信号工具。

</domain>

<decisions>
## Implementation Decisions

### Locked product（v0.23.0-DECISIONS + Defaults）
- **D-01（← D1）:** primary 仍不得出 team / shortlist 宇宙；`out_of_team` 不得作 primary。复用宿主仅当证据合法时可并入候选宇宙（∪ shortlist），不得借机开放全库。
- **D-02（← Defaults）:** 不推倒 `RepoRouterV2`；演进 `BlueprintRouteAdapter` / `RepoAssociationService`。三分量融合（router_base + charter + history）降为漏斗内信号，**不再单独决定**整篇 feature list 的唯一 primary。
- **D-03（← D5 / Phase 129）:** 消费既有 `role_map` + `placement_defaults`（如 `learning_state_writer_not_app_shell`）；放置不得违反角色禁令（forbidden 仓不得 primary；无 override 的 boundary 命中不得 primary）。

### 放置单元聚合（UNIT-01）
- **D-04:** 新模块 `server/services/process_runtime/placement_units.py`，入口 `build_placement_units(...)`：输入至少 `feature_list`/`features_flat`+`modules`、可选 profile/`reuse_summary`。
- **D-05:** 聚合规则（确定性、可测）：
  1. **同模块优先**：同一 `module` 下的 feature 点默认同属一单元；
  2. **模块依赖边**：消费模块总览中的依赖关系（如 `depends_on` / 「依赖模块」字段 / 相邻模块顺序元数据若已结构化）；有依赖边的模块可合并或建立 unit 间边（实现取「合并为同一放置单元当强依赖且同角色偏好」或「保留 unit 边供 supporting」——见 Claude's Discretion，须可测且避免 43 独立检索）；
  3. **「复用 X」边**：扫描 feature `name`/`description` 中「复用…」模式，解析复用目标（做题组件 / 播放器 / 宿主等），记入 `reuse_edges[]`，并标记 `reuse_host_hints`（映射到 `practice_reuse_host` 等角色或短语，**不硬编码仓 UUID**）。
- **D-06:** 每个 Placement Unit 至少含：`unit_id`、`feature_ids[]`（或 name 键）、`module_names[]`、`query_text`（单元级检索语料，不含 acceptance/测试用例正文）、`reuse_edges[]`、`reuse_host_hints[]`。禁止把验收语料/测试用例塞进 `query_text`。

### shortlist 内细落点（UNIT-02 / UNIT-03）
- **D-07:** 新入口 `place_units(...)`（可同文件或 `place_units.py`）：对每个 unit，在候选宇宙 = `shortlist_ids ∪ reuse_host_repo_ids` 内产出 `primary_repo` + `supporting_repos[]` + `confidence` + `evidence[]` + `open_questions[]`。
- **D-08:** 细排可调用 `RepoRouterV2.route(..., repository_ids=hard_scope, use_llm=...)` **只取分数/候选**；`hard_scope` 必须 ⊆ shortlist∪reuse hosts；**禁止**对全库或未收窄 team 外开放 primary。守卫：任何 `primary_repo ∉ hard_scope` → 丢弃并记 degrade / open_question。
- **D-09:** `reuse_host_repo_ids` 解析：从 shortlist 内 `role_map` 的 `practice_reuse_host` primary/supporting，及 unit 的 `reuse_host_hints` 与仓章程/画像粗匹配得到；仍必须在 team 宇宙内（∩ team_core∪合法 adjacent），不得拉入 out_of_team。
- **D-10:** 置信度与 evidence：至少引用 shortlist signals / role assignment / V2 或三分量信号之一；`open_questions` 在多仓打平、角色冲突、复用宿主缺失时填充（不静默捏造 primary）。
- **D-11:** 应用 `placement_defaults`：例如学习状态写方不得默认 `app_shell` primary；做题复用优先 host 非 shell。

### 主路径接线（INT-01）
- **D-12:** `BlueprintRouteAdapter.route`：在 Phase 129 的 team_gate → shortlist → role_map **之后**，调用 `build_placement_units` → `place_units`；stage 观测写入 `placement_units` / `placements`（计数与摘要，无需求全文）。下游候选 / primary 以放置结果为准；既有三分量 breakdown 可作为 unit 内打分信号保留。
- **D-13:** `RepoAssociationService`（项目选仓）主路径同等走漏斗编排：team → shortlist(±history) → role_map（可只读消费）→ placement units → place；**不得**再「整篇 query 一次 V2 + 三分量唯一决策」作为 feature-list 主路径。三分量可在 place 内作为信号。
- **D-14:** MCP / stage_sandbox：至少保证候选/primary ⊆ shortlist∪reuse hosts（与 129 一致并叠加 placement 收窄）；可不全量写 placement 明细，但禁止静默全库 primary。
- **D-15:** structlog：`placement_units_started/completed/failed`、`place_units_started/completed/failed`（或等价）；`category=sampling`（内部）/ 入口保持既有 `caller`；`component=process_runtime`；`duration_ms`、unit_count、placement_count；异常 `redact_secrets_in_text`；禁止需求全文/召回正文入日志。

### Claude's Discretion
- 模块依赖边是「合并单元」还是「unit 间 supporting 边」的具体阈值（须减少独立全库检索次数，默认倾向同依赖链合并为更少单元）
- 「复用 X」正则/短语表与 host hint → role 映射细节（须覆盖做题组件/播放器等演示语料语义，不硬编码仓名）
- unit 内 LLM 细排是否开启（可对 hard_scope 调用 V2 `use_llm`；单测可 stub）
- association 路径是否完整写 role_map 字段或只消费 placement（优先：Blueprint 写满；association 至少 placements + shortlist 收窄）

</decisions>

<specifics>
## Specific Ideas

- 验收锚点「高三提分」四基线仓属 Phase 132；本相位用合成 modules/features + mock shortlist/role_map 证明聚合与 hard_scope 即可。
- Feature list 语料形态已存在：`modules[]` + `features_flat[]`（`module`/`name`/`description`）；「复用端内做题组件」「复用通用知识点播放器」等出现在高三 demo 正文。
- Phase 129 已导出 `placement_defaults` 与四角色图——本相位是消费者，不重做角色枚举。
- 现状痛点：`RepoAssociationService` / Adapter 仍可能对整篇 requirement 做一次 V2（`corpus_kind=requirement` 切块全探）；本相位用放置单元替代「逐点/整篇唯一 primary」心智。

</specifics>

<canonical_refs>
## Canonical References

### Product / requirements
- `.planning/milestones/v0.23.0-DECISIONS.md` — D1–D5 + Defaults（不重写 V2、三分量降级）
- `.planning/REQUIREMENTS.md` — UNIT-01~03、INT-01
- `.planning/ROADMAP.md` — Phase 130 success criteria
- `.planning/PROJECT.md` — Feature 连贯性 → 放置单元后再 shortlist 内细落点

### Prior phase
- `.planning/phases/129-shortlist-history-role-map/129-CONTEXT.md`
- `.planning/phases/129-shortlist-history-role-map/129-RESEARCH.md`
- `.planning/phases/129-shortlist-history-role-map/129-VERIFICATION.md`

### Observability
- `.planning/observability/LOGGING-SPEC.md` — category / component / 脱敏

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/services/process_runtime/shortlist.py` — `build_shortlist`
- `server/services/process_runtime/history_prior.py` — `asplit_history_priors`
- `server/services/process_runtime/role_map.py` — `RepoRole`、`build_role_map`、`PLACEMENT_DEFAULTS`
- `server/services/process_runtime/blueprint_route.py` — `BlueprintRouteAdapter`（已接 profile→team_gate→shortlist→role_map→V2/融合）
- `server/initiatives/services/repo_association_service.py` — 项目选仓；已有 team + shortlist 收窄 + 三分量融合
- `server/codegraph/services/repo_router_v2.py` — 限定 `repository_ids` 时的细排（只调不改）
- `server/services/process_runtime/initiative_profile.py` — 画像语料选择（剔 acceptance）

### Established Patterns
- fail-soft + 显式 unavailable/degrade/clarify；载荷 additive
- structlog kv + `category` + `component`；召回只记指标
- TDD：Wave1 纯模块单测 → Wave2 漏斗接线测
- 候选 ⊆ shortlist 守卫（`test_funnel_shortlist.py`）

### Integration Points
- Blueprint：role_map 之后插入 **placement units → place**
- RepoAssociation：feature-list 主路径改为同漏斗，三分量不再唯一决策
- 后续 Phase 131 消费 placements 做 GATE/REFL

</code_context>

<deferred>
## Deferred Ideas

- 门禁 pass|clarify|block + 发布确认门（GATE）与反思环（REFL）→ Phase 131
- 高三提分四基线 primary + out_of_team=0 回归门槛 → Phase 132 / D2
- 路由控制台大前端 / 章程自动生效 → 本里程碑不做
- 近 90d commit 混合活跃度 → 不做
- 推倒重写 RepoRouterV2 → 禁止

</deferred>
