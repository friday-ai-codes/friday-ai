# Phase 128: 专项画像 + 团队门禁地基 - Context

**Gathered:** 2026-08-14
**Status:** Ready for planning
**Mode:** Smart discuss auto-accepted (user locked D1–D5; remaining grey areas delegated to smart discuss)

<domain>
## Phase Boundary

本相位交付决策漏斗入口：从 feature list 产出可机读专项画像，并划定 `team_core` 硬范围。`out_of_team` 默认不可作 primary；无团队时 `clarify`/`block`，不得静默全库裸路由。覆盖 Blueprint/项目选仓与 MCP（可识别或强制选团队）。不实现 shortlist/角色图/放置单元/反思（129–131）。

</domain>

<decisions>
## Implementation Decisions

### Locked product (v0.23.0-DECISIONS.md)
- D1: Blueprint + 项目关联硬门禁；MCP 也须门禁（自动识别团队/Space 或强制用户选择）；无静默全库 primary
- D3: 期望团队缺失 → `clarify`（MCP 同）
- 不推倒 `RepoRouterV2`；演进 `BlueprintRouteAdapter` / `RepoAssociationService`
- 画像语料：模块总览/简述；测试 case 不进主 query

### 专项画像形状与语料
- 画像为结构化 dataclass/TypedDict（产品形态、域、brownfield|greenfield|fix、主能力簇、显式非目标、复用声明摘要），可 JSON 序列化进 stage 观测
- 主路径输入优先：模块总览、全局流转、模块简述；验收项/测试 case 正文默认剔除
- 仅有操作细节/验收语料时 → `clarify`（reason: insufficient_profile_corpus），不静默噪声画像
- 画像失败 fail-soft：写 degrade 原因，下游可走门禁 `clarify`/`block`，不抛垮路由

### 团队门禁模型
- `team_core` = Project 挂载 Space 的仓库集（优先）；无 Project 时用调用方显式 `space_id`/`team_id`；再无自动识别（上下文绑定 Space）
- 标注三类：`team_core` | `team_adjacent` | `out_of_team`；primary 仅允许 `team_core`（本相位相邻例外只留接口，证据校验在 129）
- `team_core` 空或全无索引 → 路由结果状态 `clarify`（offer bind Space / pick team），禁止退回全库 `RepoRouterV2.route` 作 primary
- MCP：无团队上下文时返回 clarify 载荷（候选 Spaces 列表若可枚举），不返回全库 top-k 当主结果

### 接线与观测
- 新模块建议：`services/process_runtime/initiative_profile.py` + `team_gate.py`（或等价），由 BlueprintRoute / RepoAssociation / MCP route stage 调用
- 观测：structlog `category=sampling`/`caller` 按入口；字段含 `request_id`/`run_id`、画像 degrade、`team_core_count`、gate outcome；不写需求原文全文
- 既有 `grouping_repository_ids` annotate-only 行为本相位在漏斗路径改为 hard gate；裸 V2 直调保持兼容（测试标注）

### Claude's Discretion
- 画像抽取用既有 LLM call_source 枚举扩展或复用合适 source；temperature/idempotency 跟现有 blueprint 路径对齐
- 单元测试用合成 feature list + mock Space 仓库集覆盖 PROF/TEAM 成功与 clarify 路径

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/services/process_runtime/blueprint_route.py` — BlueprintRouteAdapter（三分量融合）
- `server/initiatives/services/repo_association_service.py` — 项目选仓编排
- `server/codegraph/services/repo_router_v2.py` — `grouping_repository_ids` 目前 annotate-only
- `server/mcp_tools/views.py` — `arun_route_stage` MCP 入口
- `server/initiatives/services/feature_list_extractor.py` — feature list 抽取

### Established Patterns
- fail-soft + degrade reason；structlog kv；asgiref `sync_to_async` 桥 ORM
- Space ↔ repositories 已有挂载模型

### Integration Points
- Blueprint 路由 stage、RepoAssociation 选仓、MCP route stage 三入口统一调用画像 + 团队门

</code_context>

<specifics>
## Specific Ideas

- 验收锚点语料「高三提分专项」属 Phase 132；本相位用合成用例即可
- MCP 团队选择：优先自动识别，否则 clarify 让用户选（D1/D3）

</specifics>

<deferred>
## Deferred Ideas

- shortlist / 历史先验 / 章程角色图 → Phase 129
- 放置单元与主路径全量接线 → Phase 130
- 发布门 / 反思环 → Phase 131
- 高三提分回归门槛 → Phase 132 / D2

</deferred>
