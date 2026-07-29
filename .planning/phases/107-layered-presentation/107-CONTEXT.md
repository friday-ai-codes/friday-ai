# Phase 107: 分层呈现与链路韧性（分组/跨组标注 + 降级可见 + 澄清必达 + Stage 1 有界） - Context

**Gathered:** 2026-07-29
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous — 推荐项自动采纳）

<domain>
## Phase Boundary

用户看到的路由结果分组可信、降级有明确标注，编排在澄清环节与上游抖动下不再无声卡死。

覆盖需求：ROUTE-01, ROUTE-02, RELY-02, RELY-03, RELY-05。

**边界内**：路由结果分组（in_project/global）与跨组标注、block ranking 迟滞置顶、降级用户可见提示、澄清必达与超时出口、Stage 1 重试/延迟上界/有界重排（rank-swap budget + 凸组合）、O-6 延迟实测落文档。
**边界外**：打分公式本身（Phase 106 已定版，本 phase 绝不改分数口径）；编排产出直连执行流（Phase 109）；阶段流式与容器日志（Phase 110，但事件源须复用本 phase 所落，不重复建设）；方案深度（已移交 v0.20.0，`process_runtime` 的 prompt/schema 冻结不做 DEPTH 向改动）。

**依赖输入（105/106 已产出）**：`degraded` 标志与快照/回放底座、确定性 confidence（margin 规则）、六信号可拆解打分与 `weight_set_version`、`breakdown` 前端展开面（`RoutingDecisionPanel.vue`）、Stage 1 输入哈希缓存与固定 decode。

</domain>

<decisions>
## Implementation Decisions

### 分组与跨组呈现（ROUTE-01/02）
- **一套分数、组内全序、组间不全序**：组别只进独立字段 `group ∈ {in_project, global}`、`trust ∈ {trusted, needs_confirmation}`、`cross_group_note`，**绝不进分数**——严禁任何 in-domain boost 或 group-conditional 偏移（research §5.1；两组可比性是 Phase 106 定版打分函数的直接收益，加了偏移即自我实现预言）。
- 组内各展示 Top-3，按同一套 `S_ranked` 降序；in-project 首位 `confidence=high` 且迟滞未触发时，全局组默认折叠（降认知负担，research §5.2 代价 3）。
- **置顶决策（block ranking + 迟滞）**：`S_global(1) - S_in_project(1) >= delta` 时把全局组置顶并显式提示「更匹配的仓不在本项目关联范围内」；`delta` 默认 0.15（迟滞阈值，绝不用 0——0 会让 0.001 级波动反复翻转置顶，破坏幂等与体验），外置可调（沿用 106 权重外置载体或 settings，planner 定）。
- 跨组候选带标注「未关联当前平台，可能涉及跨组协作」。
- 归属判定复用既有项目↔仓关联设施（`initiatives` 关联服务 / ProjectBranch 反查，researcher 确认具体入口）；无关联即 `global`。无项目上下文（如全局检索入口）时全部记 `global` 并跳过分组呈现，不得报错。

### 降级可见（RELY-03）
- 触发条件消费 Phase 105 已有的 `degraded` 标志与 `router_version`（`v2_stage0_only` / `v1_fallback`），前端不自行推断。
- 提示形态：面板级醒目提示「本次未经 LLM 推理，置信度仅供参考」+ 候选 confidence 徽标降级样式；复用既有告警/提示组件与色板，零新色板（UI-SPEC 定稿）。
- 透出**粗粒度**降级原因（超时 / 网关错误 / 未配模型 / 解析失败），原始异常文本经 `redact_secrets_in_text` 脱敏后才可入库/展示；细节不泄漏凭证。

### 澄清必达与超时出口（RELY-02）
- **必达保证**：澄清创建后必须有送达确认——会话内 pending 状态对用户可见，且 IM/飞书送达失败可观测（失败即标记 `delivery_failed` 并走出口，绝不静默挂起）。
- **超时出口**：可配超时（默认 24h，外置）；到期默认**带「未澄清假设」标注继续推进**（as-if 默认答案，并在产出中显式标注哪些点未澄清），备选路径为如实失败并说明原因。核心红线：会话不得再永久停在 `waiting_clarification`。
- 到期执行者复用既有 apscheduler 定时任务扫描过期 pending，任务必须携带 `initiated_by_user_id`（无触发用户记 `system`），best-effort 不反噬。
- **幂等**：出口动作幂等——重复扫描不重复推进、不重复通知；状态机单向推进（`waiting_clarification → resumed_with_assumptions | failed_no_answer`），并发扫描用行级锁或状态条件更新保护。

### Stage 1 有界与延迟（RELY-05）
- 单次调用 **1 次重试**（指数退避，重试与首调共享总延迟上界），总延迟硬上界外置（沿用/扩展 `REPO_ROUTER_STAGE1_TIMEOUT_SECONDS` 语义），超出即降级继续（`degraded=True` 对用户可见）。
- **有界重排（rank-swap budget）**：`|rank_llm(r) - rank_stage0(r)| <= K`，K=3；LLM 不得引入 Stage 0 Top-12 之外的仓库；最终分数为凸组合 `S_ranked = (1-α)·S_final + α·S_llm`，`S_llm = 1 - (rank_llm-1)/(N-1)`，α=0.35 外置；**Stage 1 降级时 α=0**。约束违反即裁剪回预算内并记录（可写成单元测试，research §1.3b/c）。
- O-6：Stage 1 延迟分布实测（p50/p90/p99）落 `107-MEASUREMENTS.md`，沿用数据环境标注纪律；若压不到可接受范围，明确记录「输入哈希缓存 + 快照回放为主要收益来源」这一设计取舍。

### Claude's Discretion
- 阈值/参数的具体载体（SystemSetting vs settings）、澄清超时扫描任务的注册位置与频率、分组字段在既有 pydantic/serializer 链的具体命名由 planner/executor 按代码库惯例定。
- 观测埋点按 LOGGING-SPEC 补齐（新增定时任务/出口动作/降级原因均需 category/component + 触发用户绑定）。
- 事件源设计需为 Phase 110（阶段流式/时间线）留出复用面，不重复建设。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/codegraph/services/repo_router_v2.py`（105/106 后）— `degraded`/`router_version`/`breakdown`/快照材料/Stage 1 缓存与固定 decode 均已就位；本 phase 在其上加分组字段与有界重排。
- `server/codegraph/services/repo_router_scoring.py` — 六信号纯函数核心（**分数口径本 phase 不改**，只在其外层做凸组合与分组标注）。
- `server/services/process_runtime/*`（clarify_adapter 等）— 澄清回路现状；注意 DEPTH 向改动冻结（v0.20.0 并行），本 phase 只做「必达 + 超时出口」韧性改造。
- `server/delivery/services/convergence_session_service.py` `_emit_event` — 事件唯一入口，澄清出口与降级原因留痕走这里（Phase 110 复用同一事件源）。
- `web/src/components/chat/RoutingDecisionPanel.vue` — 候选列表与 breakdown 展开（105-06/106-05），本 phase 加分组分区、跨组 badge、降级提示。
- django-apscheduler 既有定时任务注册模式（仓库同步轮询）。
- `server/initiatives/services/repo_association_service.py` / `context_link_service.py` — 项目↔仓关联判定候选入口。

### Established Patterns
- 阈值外置双轨：settings+env（技术参数）与 SystemSetting（运维可调）。
- async ORM 走 `sync_to_async`；后台任务显式携带 `initiated_by_user_id` 并在 worker 入口重新 bind。
- 前端 reka-ui + Tailwind 4，i18n 默认中文（`SIGNAL_LABELS` 为硬编码 map 而非 i18n，见 106-05）。

### Integration Points
- 路由结果消费方（105-RESEARCH 列出 8 个）：新增分组/trust 字段必须带默认值，additive-safe。
- `RepositoryRelevanceCandidate` pydantic → `RepositoryRoutingTrace` → store → 面板 的透传链（105-06 已铺）。
- 澄清链：workflow 节点发卡 / chat 专路由 / 飞书回调三条收答路径（v0.16.1 Phase 90–92 已建），超时出口需覆盖全部入口。

</code_context>

<specifics>
## Specific Ideas

- 设计权威：`.planning/research/ROUTING-RANKING.md` §1.3（有界重排三条修正）、§5（分组呈现与 block ranking、delta 迟滞及三条代价）、§6（幂等清单）；冲突以 §0 结论速览裁决。
- 生产事故锚点：会话 `ccd817d9` 两个 `ConvergenceSession` 都停在 `clarify/waiting_clarification`，agent 等不到就绕道 `create_coding_plan` 徒手编方案——RELY-02 的超时出口正是断掉这条绕行的前提（RELY-01/SPINE 在 Phase 109 收口）。
- golden set 需含「正确答案在跨组」样本以校准 delta（O-4）——106 的 fixture 已含 ≥2 条 cross_group 样本，本 phase 用它验证迟滞置顶行为。

</specifics>

<deferred>
## Deferred Ideas

- 阶段流式输出、容器日志可见、阶段时间线 → Phase 110（复用本 phase 事件源）。
- 编排产出直连执行流、移除徒手创作路径 → Phase 109。
- 方案结构深度（DEPTH-01~05）→ 已移交 v0.20.0 技术方案蓝图；`process_runtime` 的 prompt/schema 冻结。
- Permutation self-consistency（20× 成本）→ 仅作离线质量上界参考，不实现。
- 生产延迟压降的深度优化（cross-encoder 替代 LLM 重排等）→ 视 O-6 实测结论另议。

</deferred>
