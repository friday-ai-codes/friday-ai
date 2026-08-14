# Phase 129: 短名单 + 历史先验 + 章程角色图 - Context

**Gathered:** 2026-08-14
**Status:** Ready for planning
**Mode:** Smart discuss auto-accepted（v0.23.0-DECISIONS D1/D5 + Phase 128 地基；灰区由 smart discuss 定夺）

<domain>
## Phase Boundary

本相位在 Phase 128 的 `team_core` 硬门禁之后，交付漏斗中段：

1. **可解释 shortlist**：仅在 `team_core ∪ 证据合法的 team_adjacent` 内，用活跃度 + 能力树粗相关（吃专项画像）+ 章程 domain 命中生成短名单；规划中章程域与历史先验可强制拉入。
2. **历史先验拆分**：需求史（`tech_plan`）与上线史（`document` / `code_change`）与 `team_core` 求交后可 force-include。
3. **章程角色图**：对 shortlist 逐仓映射固定小枚举角色（主/辅/禁），触碰 `boundaries` 则降级/剔除（除非显式 override）；角色图作为后续放置默认约束导出。

**不实现**：放置单元细落点与主路径全量接线（130）、门禁/反思（131）、高三提分回归门槛（132）。**禁止重写** `RepoRouterV2`——仅可作 shortlist 范围内的粗排/信号工具。

</domain>

<decisions>
## Implementation Decisions

### Locked product（v0.23.0-DECISIONS + Defaults）
- **D-01（← D1）:** shortlist 候选宇宙 = `team_core ∪ 合法 adjacent`；`out_of_team` 不得进入 shortlist，更不得作 primary。Adjacent 仅当具备复用/章程/历史上线证据时合法。
- **D-02（← D5）:** 角色固定小枚举：`app_shell` | `practice_reuse_host` | `course_config` | `learning_state`。章程 `owned_domains` **映射进**该枚举；无法映射 → `clarify(unmapped_role)`，不静默捏造角色。
- **D-03:** 不推倒 `RepoRouterV2`；演进 `BlueprintRouteAdapter` / 既有 `blueprint_charter_match` / `blueprint_route_history`；三分量融合降为漏斗内信号，不再单独决定 shortlist 全集。
- **D-04:** 章程规划中域（`owned_domains.status=planned` 或等价 evolution/planned 语义）能力树分低/为 0 时仍可 force-include 进 shortlist（LIST-02）。
- **D-05:** 历史先验拆「需求史」=`tech_plan` 与「上线史」=`document`+`code_change`；与 `team_core` 求交后可强制拉入（LIST-03）。无 actor / 检索失败 → fail-soft（显式 `unavailable_reason`），不阻断 shortlist 其他信号。

### Shortlist 生成（LIST-01/02/04）
- **D-06:** 新模块 `server/services/process_runtime/shortlist.py`（或等价），入口形如 `build_shortlist(...)`，输入至少：`team_core`、可选 `adjacent_ids`、`InitiativeProfile`（或 domains/capability_clusters）、query terms、章程表、历史 force-include ids。
- **D-07:** 信号至少三路可拆解进逐仓 breakdown：`activity`、`capability_coarse`、`charter_domain`；另记 `force_include_reasons[]`（`charter_planned` | `history_demand` | `history_launch`）。
- **D-08:** `capability_coarse`：在 **已限定** 的 repository_ids 上调用既有 `RepoRouterV2`（或只取其 stage0/router_base 分数）作为黑盒信号；**禁止**改 V2 grouping/内核。画像 `capability_clusters`/`domains` 拼进粗相关 query，不把验收语料塞回。
- **D-09:** `activity`：复用既有 last_commit / facets「活跃度」口径（ROUTING-RANKING 连续衰减或 V2 枚举回退），在 shortlist 模块内可读聚合，不改 V2。
- **D-10:** shortlist 大小默认可配置常数（建议 top **N=10**，force-include 可突破上界但不引入 `out_of_team`）；排序可解释；观测上报 `shortlist_count` / `duration_ms` / 各信号计数，**不回显需求原文**。

### 角色图与边界（ROLE-01/02/03）
- **D-11:** 新模块 `server/services/process_runtime/role_map.py`：对 shortlist 逐仓产出 `{role, assignment: primary|supporting|forbidden, evidence}`；至少覆盖四枚举角色在团队内的主仓偏好。
- **D-12:** 触碰章程 `boundaries` → 该落点候选 `forbidden` 或降为非 primary（复用/演进 `resolve_boundary_override`）；无 override 理由不得保留为 primary。
- **D-13:** 导出 `placement_defaults`（例如 `learning_state` 写方默认 ≠ `app_shell` primary），供 Phase 130 放置单元消费；本相位只产约束结构 + 单测，不实现放置算法。
- **D-14:** 角色映射以章程 domain/note + 画像 domains 启发式对照表为主；未覆盖且章程声明拥有 → clarify，不猜。

### 接线与观测
- **D-15:** 接线点：`BlueprintRouteAdapter.route` 在 team_gate 通过之后、细排/融合之前插入 shortlist → role_map；结果写入 stage 观测 payload（`shortlist`、`role_map`、`placement_defaults`）。RepoAssociation / MCP 漏斗路径至少消费 shortlist 范围（primary 不得出 shortlist）；细落点全量留给 130。
- **D-16:** structlog：`shortlist_started/completed/failed`、`role_map_started/completed/failed`；`category=sampling`（内部）或入口 `caller`；`component=process_runtime`；异常 `redact_secrets_in_text`；禁止需求全文/召回正文入日志。

### Claude's Discretion
- shortlist 默认 N、各信号加权系数（须可测、可进 breakdown）
- 角色启发式对照表的具体关键词（须覆盖四基线角色语义，不硬编码仓名 UUID）
- 是否在本相位把 RepoAssociation/MCP 接到 role_map 只读字段，或仅 Blueprint 写满、其余入口只收窄候选（优先：Blueprint 写满；association/MCP 至少 shortlist 收窄）

</decisions>

<specifics>
## Specific Ideas

- 验收锚点「高三提分」四基线仓属 Phase 132；本相位用合成 team_core + mock 章程/历史证明 force-include 与角色图即可。
- 演进而非旁路：`acollect_charter_candidates`（planned 补入）、`ascore_history_match`（kinds 已含 tech_plan/document/code_change）、`resolve_boundary_override` 是直接演进面。
- Phase 128 已提供 `InitiativeProfile`、`resolve_team_core` / `apply_team_gate`、漏斗 clarify 载荷形状——本相位不得回退为静默全库。

</specifics>

<canonical_refs>
## Canonical References

### Product / requirements
- `.planning/milestones/v0.23.0-DECISIONS.md` — D1 team gate、D5 role taxonomy、Defaults（shortlist/planned/history）
- `.planning/REQUIREMENTS.md` — LIST-01~04、ROLE-01~03
- `.planning/ROADMAP.md` — Phase 129 success criteria
- `.planning/research/ROUTING-RANKING.md` — 活跃度衰减与能力树粗相关信号口径

### Prior phase
- `.planning/phases/128-initiative-profile-team-gate/128-CONTEXT.md`
- `.planning/phases/128-initiative-profile-team-gate/128-RESEARCH.md`
- `.planning/phases/128-initiative-profile-team-gate/128-VERIFICATION.md`

### Observability
- `.planning/observability/LOGGING-SPEC.md` — category / component / 脱敏 / RetrievalTrace

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/services/process_runtime/team_gate.py` — `team_core` / adjacent 枚举与 hard gate
- `server/services/process_runtime/initiative_profile.py` — 画像 domains / capability_clusters
- `server/services/process_runtime/blueprint_charter_match.py` — `score_charter_match`、`acollect_charter_candidates`（planned 补入）
- `server/services/process_runtime/blueprint_route_history.py` — `ascore_history_match`（tech_plan/document/code_change）
- `server/services/process_runtime/blueprint_route.py` — `BlueprintRouteAdapter`、`resolve_boundary_override`、三分量 breakdown
- `server/codegraph/services/repo_router_v2.py` — 限定 `repository_ids` 时的能力树/活跃度信号（只调不改）

### Established Patterns
- fail-soft + 显式 unavailable/degrade reason；clarify 载荷 additive
- structlog kv + `category` + `component`；召回只记指标
- 纯函数打分与 ORM 读分离（charter_match 模式）

### Integration Points
- Blueprint 漏斗：profile → team_gate → **[本相位 shortlist → role_map]** →（既有融合/V2 细排收窄到 shortlist）
- 后续 Phase 130 消费 `role_map` + `placement_defaults`

</code_context>

<deferred>
## Deferred Ideas

- 放置单元聚合与 shortlist 内细 primary → Phase 130
- 统一门禁 pass|clarify|block 与反思环 → Phase 131
- 高三提分四基线回归门槛 → Phase 132 / D2
- 路由控制台大前端 / 章程自动生效 → 本里程碑不做
- 活跃度 v2「近 90 天 commit 数」混合项 → ROUTING-RANKING 标明本次不做

</deferred>
