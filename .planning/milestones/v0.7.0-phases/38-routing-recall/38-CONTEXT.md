# Phase 38: 路由 + 召回接入 - Context

**Gathered:** 2026-06-16
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous — grey areas resolved at Claude's discretion per DOMAIN §14/§15 + 现有底座)

<domain>
## Phase Boundary

把 Phase 36 引擎里 `routing` / `recalling` 两段的骨架（`SkeletonRouter`/`SkeletonRecall` 抛 NotImplementedError）替换为真实实现，接既有底座：

1. **ROUTE-01**：`routing` 阶段调 `RepoRouterV2.route(query, top_k, repository_ids, use_llm=True)` → 候选仓 + confidence 写入 `PlanSession`，按 §14 `routed`（routing → recalling）转移。
2. **RECALL-01**：`recalling` 阶段调 `DeliveryKnowledgeSearchService.search_similar` 召回相似需求/缺陷/复盘/技术方案 → 召回上下文写入 `PlanSession`，注入后续并行调研（Phase 39 消费），按 §14 `recalled`（recalling → clarifying）转移。
3. **EVENT（部分）**：两段产出 §15 信封 trace 事件 `repo.routing` / `knowledge.recalling`（经 Phase 36 `_emit_event` 钩子，真实 sink/taxonomy 基础设施在 Phase 41 收口；本 phase 按 §15 信封 shape 产出）。

**不在本 phase**：真实并行调研 fan-out（39 消费 routing+recall）、Clarification 回路（41）、融合（40）、事件 sink 基础设施完整化（41）。

</domain>

<decisions>
## Implementation Decisions

### 路由 adapter（ROUTE-01）
- 新建 `RepoRouterV2Adapter(RouterProtocol)` 落 `server/services/plan_orchestration/`（与 engine/protocols 同 package）。`route(session)` 取 `session.decomposition["requirement_text"]` 作 query；候选范围 `repository_ids` 取 `session.decomposition["include_repos"]`（空则 None=全库，但优先用 work_item 所属 project 的仓库范围——见下）；`use_llm=True`、`top_k` 默认 3（可配）。
- 候选范围优先级：① `include_repos` 显式指定 → 用之；② 否则若 `session.work_item.project` 存在 → 该 project 下仓库 id 列表；③ 否则 None（全库）。
- 产出写入：候选 `[{repo_id, confidence, repository_name?}]` + `router_version` + `auto_selected` 写入 `PlanSession.routing`（**新增字段**，见下）。RepoRouterV2 已自带 LLM 失败降级 Stage0（不另加容错）。
- **engine `_route` 调整**：当前 `_route` 丢弃 router 返回值。改为 `result = await self.router.route(session); await transition(session, "routed", routing=result)`，由 `PlanSessionService.transition` 持久化 routing payload（INV-6：仍只经 service 写）。

### 召回 adapter（RECALL-01）
- 新建 `DeliveryKnowledgeRecallAdapter(RecallProtocol)` 同 package。`recall(session)` 取 query = `session.decomposition["requirement_text"]`（或叠加路由候选仓名增强）；`entity_kinds` 取相似需求/缺陷/复盘/技术方案对应的 `EntityKind`（work_item / tech_plan / code_change 等——按 knowledge EntityKind 枚举实际值取，缺陷/复盘归 work_item 类）；`repository_ids` 可取路由候选仓收窄召回；`top_k` 默认 10。
- **权限/actor**：`DeliveryKnowledgeSearchService.search_similar` 需 `user`。`PlanSession` 当前无发起人 → **新增 `created_by` nullable FK(user)**（发起编排的用户）。recall adapter 用 `session.created_by` 作 user；为 None（如系统/工作流无交互用户）时 **graceful 降级**：按 `session.work_item.project` 作 project 范围调用（若 search_similar 强制 user 非空，则用 work_item.project 直接走 recall 内部 helper，或 best-effort 跳过返回空召回 + 记 warning，不阻断编排）。倾向：created_by 非空走正常；为空走 project 范围尽力召回，失败/无权限返回空召回不抛。
- 产出写入：召回结果（精简为 `[{entity_id, kind, title, score, ...}]`，避免存大正文）写入 `PlanSession.recall_context`（**新增字段**）。engine `_recall` 改为 `result = await self.recall.recall(session); await transition(session, "recalled", recall_context=result)`。

### PlanSession 字段扩展
- 新增 delivery migration（0011）：`PlanSession.routing JSONField(default=dict, blank)`、`PlanSession.recall_context JSONField(default=dict, blank)`、`PlanSession.created_by FK(settings.AUTH_USER_MODEL, null=True, blank=True, SET_NULL, related_name="+")`。
- `PlanSessionService.create_session` 增 `created_by=None` 可选参数；`transition` 支持把 `routing`/`recall_context` payload 持久化到对应字段（扩展既有 payload→字段映射，保持单一写入入口 INV-6）。

### 事件 taxonomy（部分产出）
- 经 Phase 36 `PlanSessionService._emit_event` 钩子产出 §15 信封：`repo.routing` payload `{candidates:[{repo_id, confidence}]}`；`knowledge.recalling` payload `{query, kinds:[...], hits}`。信封 `{event, session_id, work_item_id?, ts, payload}`。本 phase 只保证「产出」（钩子调用 + 结构正确 + 可被测试断言），真实 sink/订阅基础设施 Phase 41 收口。
- 在 adapter 或 engine `_route`/`_recall` 完成后调用 `_emit_event`（倾向 engine 侧统一发，adapter 专注取数）。

### Claude's Discretion
- routing/recall 结果的精确精简 schema（够 Phase 39 消费即可）。
- created_by 为空时 recall 的具体降级路径（project 范围尽力召回 vs 跳过空召回）——倾向尽力召回、失败返回空不抛。
- entity_kinds 的精确取值映射到 knowledge EntityKind 枚举（planner 按实际枚举定）。
- top_k 默认值与是否暴露为 engine/adapter 配置。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/codegraph/services/repo_router_v2.py:RepoRouterV2.route(query, *, top_k=3, repository_ids=None, use_llm=True) -> RepoRouteResultV2`（候选 + confidence + router_version + auto_selected；自带 LLM 失败降级 Stage0）。
- `server/knowledge/retrieval.py:DeliveryKnowledgeSearchService.search_similar(query, *, user, top_k=10, entity_kinds=None, project_ids=None, repository_ids=None, as_of=None, include_superseded=False) -> list[SearchResultDTO]`（向量召回 + 图扩散 + 时间衰减 + fail-closed 权限过滤）。
- `server/services/plan_orchestration/protocols.py` — RouterProtocol/RecallProtocol（待真实实现替换 Skeleton*）。
- `server/services/plan_orchestration/engine.py` — `_route`/`_recall` handler（调注入依赖 + transition；本 phase 调整为捕获返回值入 transition payload）。
- `server/delivery/services` PlanSessionService.transition / create_session（payload→字段持久化，单一写入入口）。
- knowledge `EntityKind` 枚举（确定 entity_kinds 取值）。

### Established Patterns
- async ORM 经 sync_to_async；RepoRouterV2/search_similar 均 async。
- 编排状态/产物只经 PlanSessionService 写（INV-6）；engine 不旁路 status。
- LLM/检索失败降级范式（RepoRouterV2 自带；recall best-effort 不阻断）。

### Integration Points
- adapter 注入 engine（替换 Skeleton*）：工作流入口（41）/ chat 入口（42）建 engine 时注入真实 RepoRouterV2Adapter + DeliveryKnowledgeRecallAdapter。
- routing/recall_context 字段被 Phase 39 并行调研消费（筛选需深入仓 + 注入召回上下文）。
- 事件经 _emit_event 钩子，Phase 41 接真实 sink。

</code_context>

<specifics>
## Specific Ideas

- 严格按 §14 转移（routed: routing→recalling 写候选仓+confidence；recalled: recalling→clarifying 注入召回上下文）、§15 事件 payload（repo.routing / knowledge.recalling 字段）。
- 复用既有 RepoRouterV2 与 DeliveryKnowledgeSearchService，**不重写检索/路由逻辑**，只做编排接线 + 结果持久化 + 事件产出。
- 召回权限 fail-closed：search_similar 自带权限过滤，created_by 为空走尽力降级不泄漏越权数据。

</specifics>

<deferred>
## Deferred Ideas

- 并行调研 fan-out 消费 routing+recall（Phase 39）。
- Clarification 回路真实实现（Phase 41，本 phase _clarify 仍 pass-through）。
- 事件 sink / 订阅 / 对外 adapter 基础设施（Phase 41 收口，本 phase 仅经钩子产出信封）。
- 路由/召回结果的前端可视化（若需，归 41 工作流入口 UI）。

</deferred>
