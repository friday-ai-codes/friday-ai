# Phase 39: 并行调研子 agent - Context

**Gathered:** 2026-06-16
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous — grey areas resolved at Claude's discretion per DOMAIN §6/§7/§14/§15 + 既有 fan-out 底座)

<domain>
## Phase Boundary

实现编排的 **map 段**：替换 Phase 36 引擎 `_research` 的 `SkeletonResearch`，实现 filter_then_container 并行调研 + 结构化 `PartialPlan` 产出 + 子任务级可靠恢复（重试 / stale 重跑）。

1. **RESEARCH-01**：先 server 端快筛（复用 Phase 38 routing 候选 + confidence），只对「需深入」的仓 fan-out 独立 claude code 容器并行调研（上下文隔离），每仓产出结构化 `PartialPlan`（§7：research_summary / proposed_changes / candidate_files / api_contracts_exposed / dependencies_on_other_repos）。
2. **RESEARCH-02**：单仓 `RepoResearchTask` 失败可单独重试，不重跑整个 `PlanSession`（子任务级状态 pending→running→done/failed）。
3. **RESEARCH-03**：仓库被重新索引（commit 变化）使关联 `PartialPlan.valid=False` 置 `stale`，融合前需重跑。
4. **EVENT（部分）**：产出 `repo.research.started` / `repo.research.completed` / `repo.research.failed` §15 trace 事件。

**不在本 phase**：架构师融合消费 partial（Phase 40）、Clarification（41）、事件 sink 基础设施完整化（41）。**真实容器 E2E 验收**沿用既有里程碑惯例 deferred（本地无 runner+docker；逻辑/dispatch/解析以 mock 单测覆盖，对齐 `test_callbacks_cross_repo_relevance` 范式）。

</domain>

<decisions>
## Implementation Decisions

### 模型（delivery app，DOMAIN §6/§12 邻域）
- `RepoResearchTask`：`id UUIDField(pk, uuid4)`、`session FK(delivery.PlanSession, CASCADE, related_name="research_tasks")`、`repository FK(repositories.Repository, CASCADE)`（跨 app 真实 FK 可接受——repositories 是稳定基础 app）、`subagent_session FK(subagent.SubAgentSession, null=True, SET_NULL)`（dispatch 后回填）、`status CharField(choices: pending|running|done|failed|stale, default=pending)`、`routed_confidence CharField(blank)`（来自 Phase 38 routing）、`attempt IntegerField(default=0)`（重试计数）、`error JSONField(default=dict, blank)`、`created_at/updated_at`。
- `PartialPlan`：`id UUIDField(pk)`、`research_task FK(RepoResearchTask, CASCADE, related_name="partial_plans")`、`content JSONField(default=dict)`（§7 PartialPlan schema）、`valid BooleanField(default=True)`、`invalidated_reason CharField(blank)`、`content_hash CharField(blank)`、`created_at`。
- migration：delivery 0013（在 0012 之后）。curated re-export。
- INV-6 精神：RepoResearchTask/PartialPlan 状态/落库只经 `ResearchService`（grep 守护）。

### filter_then_container（RESEARCH-01）
- **filter**：复用 Phase 38 `session.routing.candidates`（已是 server 端 RAG/路由快筛结果）。「需深入」判定：candidates 中 `confidence ∈ {high, medium}` → 起容器深入调研；`confidence == low` → **不起容器**，走轻量 server 端 PartialPlan（从 recall_context/RAG 摘要合成，省资源——这正是 filter_then_container 的「filter」省资源语义）。阈值/集合可配（默认如上）。
- **container fan-out**：对需深入仓，每仓建 `RepoResearchTask(status=pending)` + dispatch 一个独立 `SubAgentSession`（`TaskType.PLAN`，复用 `runners.dispatcher.DispatchTask` + `get_dispatcher`，对齐 `deep_analysis` 范式）容器，**上下文隔离**（每仓独立容器/会话，防串味 + 防超长）。dispatch 后回填 `RepoResearchTask.subagent_session` + status=running。
- **prompt 注入**：容器 prompt 含该仓 routing 上下文 + recall_context（Phase 38 召回）+ 需求 decomposition，要求容器产出结构化 PartialPlan（§7 字段）。
- **聚合**：复用 `orchestration.barrier.BarrierManager` 等所有 RepoResearchTask 终态（done/failed）→ engine `_research` 经 transition `research_complete`（researching→merging）。barrier 完成判定按 §14「所有 RepoResearchTask done/failed」。
- **结果解析**：容器回调 → `SubAgentSession` 结果/`TaskResult` → 解析为结构化 PartialPlan（§7），落 `PartialPlan` + RepoResearchTask.status=done。解析失败 → status=failed + error（不污染其他仓）。
- engine `_research` 调整：`await self.research.dispatch(session)` 负责 filter + fan-out + 建 tasks；barrier/聚合后再 transition（dispatch 触发后若为 fire-and-forget，则 research_complete 由回调/barrier 驱动——见恢复规则）。

### 子任务级可靠恢复（RESEARCH-02 / RESEARCH-03，DOMAIN §6/§14）
- **单仓重试（RESEARCH-02）**：`ResearchService.retry_task(task)` —— 仅对 failed 的单个 RepoResearchTask 重新 dispatch（status→pending→running，attempt+1），不动其他 task、不重跑 session。barrier 重新纳入该 task。
- **stale 重跑（RESEARCH-03）**：`ResearchService.invalidate_for_repo(repository_id)` —— 仓库重索引（commit 变化）时调用：找该 repository 关联且 valid 的 PartialPlan → `valid=False` + `invalidated_reason="repo_reindexed"`，对应 RepoResearchTask.status→stale。融合前（Phase 40）需重跑 stale task。**挂接点**：复用既有索引完成钩子（对齐 Phase 24/25 `run_full_index` FINALIZING best-effort 派发范式），best-effort 调 invalidate_for_repo，失败不阻断索引。
- **恢复**：状态全持久化在 RepoResearchTask/PartialPlan 行 + PlanSession.status；engine 从 researching 可 resume（读未完成 tasks 续等/重派）。

### 事件 taxonomy（部分产出）
- `repo.research.started` {repo_id, task_id, focus}、`repo.research.completed` {repo_id, task_id, summary, candidate_files, api_contracts_exposed}、`repo.research.failed` {repo_id, task_id, error}，经 `_emit_event` 钩子按 §15 信封产出。

### Claude's Discretion
- 「需深入」阈值集合精确值（默认 high+medium 起容器、low 走轻量）+ 是否暴露为配置。
- fire-and-forget dispatch 与 barrier/回调驱动 research_complete 的精确时序（对齐 deep_analysis __blocking_task__ + callback resume 范式 vs 同步 gather）——倾向复用既有 callback/barrier 驱动，engine `_research` 触发 fan-out 后由回调聚合推进（与既有 AICodingNode waiting_event 范式一致）。
- PartialPlan content 解析的容错（容器输出非结构化时的降级：file 级摘要 partial vs failed）。
- 容器 E2E 验收范围（本 phase mock 单测；真实容器 deferred）。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/subagent/models.py:SubAgentSession` —— 容器生命周期/状态/dispatch 追踪，`TaskType.PLAN` 枚举已存在（vNext 标「有枚举无派发代码」，本 phase 接派发）；amark_running/completed/failed 等 async 状态方法 + `TaskResult` 结果模型。
- `server/agents/tools/chat_tools.py:deep_analysis` —— 每仓 dispatch 独立 claude code 容器的成熟范式（`DispatchTask` + `get_dispatcher` + runner 在线检查 + 复用/隔离 + fire-and-forget __blocking_task__）。
- `server/orchestration/barrier.py:BarrierManager` —— 多子 agent 聚合 barrier。
- `server/runners/dispatcher.py:DispatchTask/get_dispatcher` —— 容器派发协议。
- Phase 38 `PlanSession.routing`（候选仓+confidence）/`recall_context`（召回）—— filter + prompt 注入输入。
- `server/services/plan_orchestration/engine.py` `_research` + `ResearchProtocol`（待真实实现替换 SkeletonResearch）。
- Phase 24/25 索引完成钩子 best-effort 派发范式（stale invalidation 挂接参考）。
- delivery service 单一写入入口 + grep 守护范式（INV-6）。

### Established Patterns
- 容器 dispatch fire-and-forget + callback resume + waiting_event/barrier 聚合（chat deep_analysis / AICodingNode）。
- async ORM 经 sync_to_async；dispatch 单测以 mock dispatcher/runner（`test_callbacks_cross_repo_relevance` 范式）。
- 索引完成 best-effort 后台派发（Phase 24/25）。
- 编排状态/产物只经 service 写（INV-6）。

### Integration Points
- ResearchDispatchAdapter(ResearchProtocol) 注入 engine（替换 SkeletonResearch），工作流入口（41）注入。
- PartialPlan 被 Phase 40 架构师融合消费（收齐 valid partial → MergedPlan）。
- invalidate_for_repo 挂接索引完成钩子（重索引置 stale）。
- 事件经 _emit_event，Phase 41 接真实 sink。

</code_context>

<specifics>
## Specific Ideas

- 严格按 DOMAIN §6（RepoResearchTask/PartialPlan 字段 + 子任务级状态 + 可靠恢复规则）、§7（PartialPlan schema）、§14（researching 子状态 + research_complete barrier）、§15（repo.research.* 事件）。
- **复用既有容器 fan-out 底座，不重造**：SubAgentSession + DispatchTask + BarrierManager。
- filter_then_container 已确认决策（vNext）：先 server RAG/路由快筛（Phase 38），只对需深入仓起容器，省资源。
- 上下文隔离：每仓独立容器/会话（防串味 + 防超长上下文）——已确认决策（连接 vs 隔离都要，本 phase 是隔离段）。
- 真实容器 E2E 沿用既有 deferred 惯例；本 phase 逻辑/dispatch/解析以 mock 单测覆盖。

</specifics>

<deferred>
## Deferred Ideas

- 架构师融合消费 valid partial → MergedPlan + PlanValidator（Phase 40）。
- Clarification 回路（41）；事件 sink 基础设施（41）。
- 真实容器端到端验收（需 runner+docker+真实编码 agent，沿用既有里程碑 deferred）。
- 跨仓 partial 的依赖图初步提取可在融合（40）做；本 phase partial 只产 `dependencies_on_other_repos` 字段（§7），不做全局 DAG。

</deferred>
