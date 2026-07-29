# Phase 107: 分层呈现与链路韧性 - Research

**Researched:** 2026-07-30
**Domain:** 检索结果分组呈现（aggregated search / block ranking）、级联重排边界化、HITL 澄清回路韧性（超时出口 + 送达可观测）、定时任务幂等
**Confidence:** HIGH（代码现状全部实读 + 关键数值离线实测）/ MEDIUM（delta 与 α/K 的具体取值仍靠判断，见 Assumptions Log）

---

<user_constraints>
## User Constraints（来自 107-CONTEXT.md）

### Locked Decisions

**分组与跨组呈现（ROUTE-01/02）**
- **一套分数、组内全序、组间不全序**：组别只进独立字段 `group ∈ {in_project, global}`、`trust ∈ {trusted, needs_confirmation}`、`cross_group_note`，**绝不进分数**——严禁任何 in-domain boost 或 group-conditional 偏移（research §5.1；两组可比性是 Phase 106 定版打分函数的直接收益，加了偏移即自我实现预言）。
- 组内各展示 Top-3，按同一套 `S_ranked` 降序；in-project 首位 `confidence=high` 且迟滞未触发时，全局组默认折叠（降认知负担，research §5.2 代价 3）。
- **置顶决策（block ranking + 迟滞）**：`S_global(1) - S_in_project(1) >= delta` 时把全局组置顶并显式提示「更匹配的仓不在本项目关联范围内」；`delta` 默认 0.15（迟滞阈值，绝不用 0——0 会让 0.001 级波动反复翻转置顶，破坏幂等与体验），外置可调（沿用 106 权重外置载体或 settings，planner 定）。
- 跨组候选带标注「未关联当前平台，可能涉及跨组协作」。
- 归属判定复用既有项目↔仓关联设施（`initiatives` 关联服务 / ProjectBranch 反查，researcher 确认具体入口）；无关联即 `global`。无项目上下文（如全局检索入口）时全部记 `global` 并跳过分组呈现，不得报错。

**降级可见（RELY-03）**
- 触发条件消费 Phase 105 已有的 `degraded` 标志与 `router_version`（`v2_stage0_only` / `v1_fallback`），前端不自行推断。
- 提示形态：面板级醒目提示「本次未经 LLM 推理，置信度仅供参考」+ 候选 confidence 徽标降级样式；复用既有告警/提示组件与色板，零新色板（UI-SPEC 定稿）。
- 透出**粗粒度**降级原因（超时 / 网关错误 / 未配模型 / 解析失败），原始异常文本经 `redact_secrets_in_text` 脱敏后才可入库/展示；细节不泄漏凭证。

**澄清必达与超时出口（RELY-02）**
- **必达保证**：澄清创建后必须有送达确认——会话内 pending 状态对用户可见，且 IM/飞书送达失败可观测（失败即标记 `delivery_failed` 并走出口，绝不静默挂起）。
- **超时出口**：可配超时（默认 24h，外置）；到期默认**带「未澄清假设」标注继续推进**（as-if 默认答案，并在产出中显式标注哪些点未澄清），备选路径为如实失败并说明原因。核心红线：会话不得再永久停在 `waiting_clarification`。
- 到期执行者复用既有 apscheduler 定时任务扫描过期 pending，任务必须携带 `initiated_by_user_id`（无触发用户记 `system`），best-effort 不反噬。
- **幂等**：出口动作幂等——重复扫描不重复推进、不重复通知；状态机单向推进（`waiting_clarification → resumed_with_assumptions | failed_no_answer`），并发扫描用行级锁或状态条件更新保护。

**Stage 1 有界与延迟（RELY-05）**
- 单次调用 **1 次重试**（指数退避，重试与首调共享总延迟上界），总延迟硬上界外置（沿用/扩展 `REPO_ROUTER_STAGE1_TIMEOUT_SECONDS` 语义），超出即降级继续（`degraded=True` 对用户可见）。
- **有界重排（rank-swap budget）**：`|rank_llm(r) - rank_stage0(r)| <= K`，K=3；LLM 不得引入 Stage 0 Top-12 之外的仓库；最终分数为凸组合 `S_ranked = (1-α)·S_final + α·S_llm`，`S_llm = 1 - (rank_llm-1)/(N-1)`，α=0.35 外置；**Stage 1 降级时 α=0**。约束违反即裁剪回预算内并记录（可写成单元测试，research §1.3b/c）。
- O-6：Stage 1 延迟分布实测（p50/p90/p99）落 `107-MEASUREMENTS.md`，沿用数据环境标注纪律；若压不到可接受范围，明确记录「输入哈希缓存 + 快照回放为主要收益来源」这一设计取舍。

### Claude's Discretion
- 阈值/参数的具体载体（SystemSetting vs settings）、澄清超时扫描任务的注册位置与频率、分组字段在既有 pydantic/serializer 链的具体命名由 planner/executor 按代码库惯例定。
- 观测埋点按 LOGGING-SPEC 补齐（新增定时任务/出口动作/降级原因均需 category/component + 触发用户绑定）。
- 事件源设计需为 Phase 110（阶段流式/时间线）留出复用面，不重复建设。

### Deferred Ideas（OUT OF SCOPE）
- 阶段流式输出、容器日志可见、阶段时间线 → Phase 110（复用本 phase 事件源）。
- 编排产出直连执行流、移除徒手创作路径 → Phase 109。
- 方案结构深度（DEPTH-01~05）→ 已移交 v0.20.0 技术方案蓝图；`process_runtime` 的 prompt/schema 冻结。
- Permutation self-consistency（20× 成本）→ 仅作离线质量上界参考，不实现。
- 生产延迟压降的深度优化（cross-encoder 替代 LLM 重排等）→ 视 O-6 实测结论另议。
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ROUTE-01 | 路由结果分两组呈现——本项目关联仓一组、全局候选一组，各自排序 | §「项目↔仓关联判定」给出 3 条可用归属数据源与 8 个调用方的项目上下文可用性矩阵；§「路由结果透传链」逐跳列出加 `group` 字段的改动点；**§Open Question OQ-1 是 planner 必须先裁决的前提**（现状 `repository_ids` 硬过滤会让 global 组恒空） |
| ROUTE-02 | 跨组候选带明确标注「未关联当前平台，可能涉及跨组协作」 | 同上字段链；前端 `RoutingDecisionPanel.vue` 现有 `Badge` variant 池（8 个 variant，零新色板可满足）与 `Collapsible` 折叠组件已就位 |
| RELY-02 | 编排不会无人应答地永久停在澄清阶段——澄清必达、可作答、超时/失败有明确出口 | §「澄清回路现状」定位状态机（`ConvergenceSessionStatus` 6 值 + `clarify` StageDef）、三条收答路径、发卡 best-effort 无留痕的确切代码行；§「定时任务基建」给出 `check_timeouts` 命令作为逐字可镜像的先例（`select_for_update(skip_locked=True)` + 事务内收集/事务外重驱 + 有界重试） |
| RELY-03 | 路由降级时用户能看见「本次未经 LLM 推理，置信度仅供参考」 | `degraded`/`router_version` 已在 router→adapter→事件 payload 链上就位，但**未进 `RepositoryRoutingTrace` 与前端类型**——§「降级原因分类」给出 6 个降级分支到粗粒度枚举的完整映射 |
| RELY-05 | 路由在上游 LLM 抖动或缓慢时仍可用——单次调用有重试与延迟上界 | §「Stage 1 现状与有界重排落点」给出现状 `max_retries=0` + 单层 `asyncio.wait_for` 的确切位置，重试/预算改造方案，以及 **S_ranked 必须走新字段而不能覆盖 `score`** 的硬证据（两条既有断言 + 前端容差校验） |

</phase_requirements>

---

## Summary

本 phase 是「用户看到的东西不再骗人」的收口相位，五条需求分布在三个几乎不重叠的改造面上：**路由结果的呈现层**（ROUTE-01/02 + RELY-03，改 router 输出字段 + 4 跳透传链 + 1 个 Vue 组件）、**Stage 1 调用的有界化**（RELY-05，改 `_stage1_llm_reasoning` 单函数 + 1 个新纯函数模块）、**澄清回路的韧性**（RELY-02，新增 1 个 management command + 1 个 apscheduler job + 送达留痕字段）。三面可并行成三个 wave，彼此只在观测事件命名上有约定耦合。

**代码现状对本 phase 极其有利的三点**：(1) Phase 105/106 已把 `degraded` / `router_version` / `breakdown` / 快照 / 确定性 confidence 全部落地，RELY-03 是纯呈现接线而非机制新建；(2) `ConvergenceSessionService.transition` 用「DB 行 `current_stage == from_stage`」做 CAS 原子更新，澄清超时出口的幂等**不需要新建保护机制**，直接复用这个 CAS 即天然单次生效；(3) golden fixture 已含 2 条带 `project_scope` 字段的 cross_group 样本，delta 校准可完全离线零网络完成——**本次已实测：gk-008 delta=0.1771、gk-009 delta=0.2614，均落在 0.15 阈值之上**，CONTEXT 锁定的 `delta=0.15` 被现有 golden 数据验证为可用（且上界受 gk-008 的 0.177 约束）。

**三个必须在 planning 阶段解决的硬问题**：其一，`RepoRouterV2.route(repository_ids=...)` 的候选范围过滤与「分组呈现」在语义上冲突——编排入口当前把 `work_item.space.repositories` 作为**硬过滤**传入，global 组永远为空，ROUTE-01 会退化成一个恒空的分区（详见 OQ-1）。其二，凸组合 `S_ranked` **不能覆盖 `RepoRouteCandidateV2.score`**——两条既有集成测试断言 `Σbreakdown == score`、前端也有同款容差校验，覆盖即同时打断可拆解不变量（ROUTE-07）与前端渲染约定；必须走新字段。其三，Stage 1 现有默认 `REPO_ROUTER_STAGE1_TIMEOUT_SECONDS=90` 已经等于「可接受总上界」量级，若把它直接当总预算，1 次重试就没有余量——per-call 超时与总预算必须拆成两个参数。

**Primary recommendation:** 分三个独立 wave（呈现层 / Stage 1 有界 / 澄清韧性），呈现层第一个 task 先裁决 OQ-1 的候选范围语义；`S_ranked` 与 `group/trust` 一律走**新增旁路字段 + 默认值**（additive-safe，8 个消费方零改动）；Stage 1 重试用「总预算 deadline + 剩余预算派生 per-attempt 超时」而非独立两个超时；澄清超时出口逐字镜像 `workflows/management/commands/check_timeouts.py`（同一份 `select_for_update(skip_locked=True)` + 事务外重驱范式），出口状态转移直接调 `transition(session, "clarified")` 复用既有 CAS 幂等。

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 分组归属判定（in_project / global） | API / Backend（`RepoRouterV2` 外层或 adapter 层） | — | 归属取决于「调用方是否有项目上下文」，只有服务端知道；绝不能让前端按仓名猜 |
| block ranking 置顶决策（delta 迟滞） | API / Backend（纯函数，router 层） | Browser（仅渲染顺序） | 决策必须可回放、可写单元测试；放前端等于每个消费方各写一份 |
| 组内排序（按 `S_ranked` 降序） | API / Backend（排序权威） | Browser（**当前前端会自行 re-sort，必须同步改**） | `RoutingDecisionPanel.vue:53` 现在按 `b.score - a.score` 重排，会覆盖后端顺序 |
| 凸组合 `S_ranked` + rank-swap 裁剪 | API / Backend（纯函数模块，`repo_router_scoring` 之外的新模块） | — | 打分口径冻结（Phase 106 定版），凸组合是其**外层包装**；纯函数才能进 golden/单测 |
| 降级横幅与徽标降级样式 | Browser（`RoutingDecisionPanel.vue`） | API（提供 `degraded` / `degrade_reason` 事实） | 前端只渲染事实、不推断（CONTEXT 锁定） |
| 降级原因分类（超时/网关/未配/解析失败） | API / Backend（`_stage1_llm_reasoning` 与 `route()` 异常分支） | — | 只有异常发生点知道类型；脱敏必须在服务端完成 |
| 澄清 pending 的用户可见性 | API / Backend（会话详情 payload） + Browser（`ClarificationCard`） | — | 状态权威在 `delivery.Clarification` |
| 澄清送达失败留痕（`delivery_failed`） | API / Backend（发卡点 `plan_research._send_clarify_card`） | — | 发卡失败只有发卡处能捕获 |
| 澄清超时扫描与出口推进 | Scheduler（apscheduler job → management command） | API（`ConvergenceSessionService.transition` 唯一状态入口） | 到期是时间驱动，无请求上下文；状态写必须走既有单一入口 |
| Stage 1 延迟分位实测 | Scheduler / 离线（management command 或查询脚本） | — | 数据源是 `SystemLogEntry.payload`（见 §O-6 延迟实测） |

---

## Standard Stack

### Core（全部已在仓内，本 phase **零新依赖**）

| 库 / 模块 | 版本 | 用途 | 为何是标准 |
|-----------|------|------|------------|
| `apscheduler` + `django-apscheduler` | `>=0.7.0`（`django_apscheduler`） | 澄清超时周期扫描 | 仓内既有 21 个 job 全走 `server/agents/management/commands/runapscheduler.py`；单实例由 `fcntl.flock` 保证 [VERIFIED: 实读 runapscheduler.py:486-511] |
| `django.db.transaction` + `select_for_update(skip_locked=True)` | Django 5.1+ | 并发扫描行级锁 | `check_timeouts.py:43` 的既有范式；**SQLite 下退化为 no-op**（多处代码显式记录该事实） [VERIFIED: 实读] |
| `structlog` | 仓内既有 | 结构化事件 | LOGGING-SPEC 强制 |
| `asyncio.wait_for` | stdlib | Stage 1 硬超时 | `repo_router_v2.py:1168` 既有用法 |
| `reka-ui` + Tailwind 4 + `class-variance-authority` | 见 `web/package.json` | 分组分区 / 折叠 / 徽标 | `Badge`（8 variant）+ `Collapsible` 均已在 `RoutingDecisionPanel.vue` 使用 |

### Supporting

| 模块 | 用途 | 何时用 |
|------|------|--------|
| `common.logging.redact_secrets_in_text` | 上游异常文本脱敏（纯函数，替换 `sk-*` / `sk-ant-*` / `AIza*` / `Bearer *` / PEM） | 降级原因入库/展示前；澄清正文进卡片前（发卡侧已在用） |
| `interactions.redaction.redact_for_ledger` | 入库留痕整体脱敏 | 事件 payload 落 `ConvergenceSessionEvent`（`_routing_snapshot_payload` 已在用） |
| `common.log_context.bind_task_context` | 后台任务重新 bind 触发用户 | apscheduler job（`_with_scheduler_log_context` 已封装为装饰器，固定 `user_id="system"`） |
| `system.settings_service.get_json_setting` | SystemSetting JSON 读取（60s 进程内缓存 + post_save 失效） | 若把 delta/α/K/超时放 SystemSetting |
| `django-environ` `env.float/env.int`（`friday/settings.py`） | 技术参数外置 | 若把 delta/α/K/超时放 settings+env（**推荐**，见 Pitfall 5） |

### Alternatives Considered

| 不用 | 可以用 | 取舍 |
|------|--------|------|
| settings+env 放 delta/α/K | 扩 `SettingKeys.REPO_ROUTER_WEIGHT_CONFIG` 的 `constants` 段 | SystemSetting 可不发版热改（运维友好），但 `constants` 白名单派生自 `DEFAULT_WEIGHT_CONFIG["constants"]`，新增键会进快照 `weight_config` 节 → 影响 106-07 回放比对与 golden fixture 的 `constants` 形状；且 `weight_set_version` 语义是「打分口径版本」，α/K/delta 不改打分口径，混进去会污染版本语义。**推荐 settings+env**（与既有 `REPO_ROUTER_STAGE1_*` / `REPO_ROUTER_CONF_THETA_*` 同轨），只有 delta 若确认需运维频繁调再考虑 SystemSetting |
| 新增 `ConvergenceSessionStatus` 枚举值 | 复用现有 6 值 + `stage_state` 标注 | CONTEXT 写的 `resumed_with_assumptions` / `failed_no_answer` 是**语义名而非 DB 值**；新增枚举值要迁移且会撞 `lifecycle_projection` / `chat` / `orchestration` 多处 status 分支（30 个文件引用 `waiting_clarification`）。推荐：出口 = `transition(session, "clarified")`（→ `running` + `current_stage=research`）或 `transition(session, "fail")`，"未澄清假设" 标注写 `stage_state` |
| 新建 `clarification.timed_out` 事件名 | 扩 `EVENT_CLARIFICATION_ANSWERED` payload | 事件 taxonomy 有守护测试（`ALL_EVENTS` 覆盖性反查）。新增常量 + 加入 `ALL_EVENTS` 是**既有扩展路径**（v0.9 `EVENT_SPEC_DRAFTED` 就是这么加的），推荐新增 `clarification.timed_out` 而非污染 answered 语义——Phase 110 时间线需要区分「答了」和「超时放行」 |

**Installation:** 无需安装任何包。

**Version verification:** 本 phase 不引入外部包，跳过 `pip index versions` / `npm view` 核验。

## Package Legitimacy Audit

**不适用** —— 本 phase 零新增外部依赖（全部复用仓内既有模块与已锁定的 `server/uv.lock` / `web/pnpm-lock.yaml` 依赖）。无包可审，无需运行 slopcheck。

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

---

## 关键调查结论（planner 需要的事实）

### 1. 项目↔仓关联判定：三条数据源 + 8 个调用方的项目上下文可用性

**可用的归属数据源**（三条，语义各不相同，planner 必须选一条并在 PLAN 里写明理由）：

| 数据源 | 入口 | 语义 | 可用性 |
|--------|------|------|--------|
| **`Space.repositories`（M2M）** | `wi.space.repositories.values_list("id", flat=True)`（`repo_router_adapter.py:88`）、`Repository.objects.filter(spaces=project, ...)`（`repository_relevance.py:196`） | 「空间下的仓」——**当前唯一在路由链路里实际用到的关联** | 编排入口（经 `work_item.space`）与 chat 入口（经 `space_id`）都有 [VERIFIED: 实读] |
| **`initiatives.RepoAssociation`** | `RepoAssociationService.get_verified_associations(project=..., work_item=...)` → `[{repository_id, repo_name, verdict, score, ...}]`，只取 `status=verified` | 「项目已确认关联仓」（Phase 88/89 语义，含容器深验 verdict） | 需要 `initiatives.Project` 实例；路由调用方**都没有直接持有 Project**，需先 `_aresolve_project(space)`（`workflows/nodes/integrations/board_split_review.py` 有该 helper，`plan_research._send_clarify_card` 已在用） |
| **`initiatives.ProjectBranch`** | `ProjectBranch(project, repository, branch_name)` 反查 | 「项目已配分支的仓」——比 verified 关联更强的信号（真的开工了） | 表存在但路由链路无现成 helper |

**8 个 `RepoRouterV2.route()` 调用方的项目上下文矩阵** [VERIFIED: `rg RepoRouterV2.route` 全量实读]：

| # | 调用方 | 有项目上下文？ | 现状是否传 `repository_ids` | 分组可行性 |
|---|--------|---------------|---------------------------|-----------|
| 1 | `services/process_runtime/repo_router_adapter.py:46` | ✅ `session.work_item_id → WorkItem.space` | ✅ `include_repos` → `space.repositories` → `None` 三级优先 | **主战场**；但见 OQ-1（硬过滤冲突） |
| 2 | `agents/tools/repository_relevance.py:216` | ✅ `space_id`（chat 工具，`Space` 实例已取） | ✅ 空间内 `index_status=indexed` 仓 | 同 OQ-1；此路径产出 `RepositoryRoutingTrace` → 前端面板 |
| 3 | `agents/tools/space_tools.py:56` | ✅ 空间仓列表 | ✅ `repo_ids` | `use_llm=False` 的 L1 收敛，**不面向用户呈现**，只需字段带默认值不炸 |
| 4 | `initiatives/services/repo_association_service.py:165` | ✅ 有 `project` | 视 `_space_repository_ids` 而定 | 关联提案本身就在建关联，分组语义退化；带默认值即可 |
| 5 | `knowledge/sources/artifact.py:146` | ❓ 需实读确认 | — | 带默认值即可 |
| 6 | `tools/handlers/skill_steps.py:76` | ❌ 参数直传 `repository_ids or None` | 调用方给 | 全 `global`，跳过分组 |
| 7 | `mcp_tools/views.py:434`（`RouteRepositoriesView`） | ❌ **无任何项目上下文**（`RepoRouterV2.route(query, top_k=top_k)`） | ❌ 全库 | 全 `global`，跳过分组（CONTEXT 明确允许） |
| 8 | `repositories/route_views.py:39`（`POST /api/repositories/route/`） | ❌ **无任何项目上下文** | ❌ 全库 | 全 `global`，跳过分组 |

**结论**：只有 #1、#2 两个入口既有项目上下文又面向用户呈现，是 ROUTE-01/02 的真实落点。#7/#8 必须验证「无项目上下文不报错、全部 `global`」这条降级路径（写测试）。

### 2. 路由结果透传链：加 `group` / `trust` / `cross_group_note` / 降级原因要改哪几处

完整字段链（逐跳实读，105-06 已铺 `breakdown` 的同一条路）：

```
RepoRouteCandidateV2 (dataclass, repo_router_v2.py:139)  ← 加 group/trust/cross_group_note/score_ranked
  ├─ .to_dict() (repo_router_v2.py:156)                   ← 加对应键（进快照 candidates 节）
  └─ RepoRouteResultV2 (repo_router_v2.py:172)            ← 加 block_order / degrade_reason
       │
       ├─[编排链]→ repo_router_adapter.route() 精简 dict (repo_router_adapter.py:49-63)
       │              ← 现只映 {repo_id, confidence, repository_name} + router_version/auto_selected/degraded/snapshot
       │              ← 需补 group/trust（下游 clarify/research/feature_confirm 读 confidence，加字段 additive-safe）
       │       → _h_route (builtin_processes.py:147) → session.routing（snapshot 被 pop 剔除，不落库）
       │       → _routing_snapshot_payload (builtin_processes.py:120) → EVENT_REPO_ROUTING → ConvergenceSessionEvent
       │
       └─[chat 链]→ repository_relevance._analyze_relevance_core (repository_relevance.py:239)
                      → RepositoryRelevanceCandidate (pydantic, schemas/repository_relevance.py:29)  ← 加字段
                      → RepositoryRoutingTrace.candidates JSON (chat/models.py:666) + .router_version 列(:683)
                         ⚠️ 该表**无 degraded 列**——RELY-03 需要它，两选一：加列 / 塞进 candidates 外层？（见下）
                      → chat/views.py:537 routing_trace_payload（detail hydrate，**当前只出 5 个键**）
                      → web/src/types/routing.ts RoutingCandidate / RoutingDecisionData
                      → web/src/stores/chat.ts:515（detail hydrate）/ :1283（chat_tool）/ :1309（deep_analysis）
                      → web/src/stores/routing.ts upsertTrace / applyManualOverride
                      → web/src/components/chat/RoutingDecisionPanel.vue
```

**必改点清单（chat 链，RELY-03 + ROUTE-01/02 都走这条）**：

1. `RepositoryRelevanceCandidate`（pydantic）加 `group` / `trust` / `cross_group_note`，全部带默认值。**注意**：schema snapshot fixture `server/tests/agents/fixtures/repository_relevance_input_schema.json` 只冻结 **Input** schema（`RepositoryRelevanceInput`），Output 加字段不触发该守护 [VERIFIED: 实读 schemas/repository_relevance.py:3-6 docstring + fixture 名]。
2. `RepositoryRoutingTrace` 缺 `degraded`：`router_version` 已是列（默认 `legacy_hybrid`），`v2_stage0_only` / `v1_fallback` 已能表达「Stage 1 未参与」。**推荐不加列**——前端按 `router_version ∈ {v2_stage0_only, v1_fallback}` 判定降级即可，但 CONTEXT 明确「前端不自行推断」→ 折中方案：后端在 `routing_trace_payload` 里**计算出** `degraded: bool` + `degrade_reason: str` 再下发（推断在后端，前端只渲染）。降级原因需要新列或 JSON 承载（`candidates` 是 list，不能塞外层）→ **planner 决策点**：加 `degrade_reason CharField(max_length=32, blank=True, default="")` 一列（迁移开销小、可 SQL 聚合）优于塞 JSON。
3. `chat/views.py:537` 的 `routing_trace_payload` 只出 `{trace_id, query, candidates, threshold, triggered_by}` —— 必须补 `router_version` / `degraded` / `degrade_reason`，否则**刷新页面后降级提示消失**。
4. `web/src/stores/routing.ts:74-80` 的 `applyManualOverride` **重建 trace 时只保留 4 个字段**（`trace_id/query/candidates/threshold/triggered_by`）：用户改一次勾选后 `degraded` / `router_version` 会丢失 → 降级横幅消失。⚠️ 这是一个必修的既有陷阱（同类问题在 105-06 加 `breakdown` 时靠 `response.candidates` 携带侥幸躲过）。
5. `RoutingDecisionPanel.vue:50-54` `sortedCandidates` 按 `b.score - a.score` 重排 —— **会覆盖后端的分组内排序与 block 置顶**。必须改成：先按 `group` 分区（区顺序由后端 `block_order` 决定），区内按 `score_ranked ?? score` 降序。

**兼容性约束（8 个消费方）**：全部按具名字段读取（`c.score` / `c.confidence` / `c.reasoning` / `c.breakdown`），无一处做 `**kwargs` 展开或字段数断言 [VERIFIED: 105-RESEARCH §4 消费方矩阵 + 本次抽读 #1/#2/#3/#7/#8]。因此**新增带默认值的 dataclass / pydantic 字段是 additive-safe**。唯一例外：`RepoRouteCandidateV2` 是 `@dataclass`，新字段必须有 `default` 或 `default_factory`（否则位置参数构造的测试替身会炸）。

### 3. 澄清回路现状（RELY-02 的确切缺口）

**状态机**：`ConvergenceSessionStatus`（`delivery/models/convergence_session.py:30`）只有 6 值：`created / running / waiting_clarification / waiting_event / done / failed`。`waiting_clarification` 由 stage graph 派生而非直接赋值——`_TECHNICAL_PLAN_STAGES["clarify"]`（`builtin_processes.py:291`）：

```python
"clarify": StageDef(
    key="clarify",
    handler=_h_clarify,
    transitions={"clarified": "research", "needs_clarification": "clarify"},
    pausable=True,
    wait_status="waiting_clarification",
),
```

self-loop event `needs_clarification` + `pausable=True` → status 取 `wait_status`。所以**超时出口 = `transition(session, "clarified")`**（→ `current_stage="research"`, `status="running"`）或 `transition(session, "fail")`。

**三条收答路径**（+1 条逃生路径）：

| # | 入口 | 代码位置 | 收答后动作 | 有超时？ |
|---|------|---------|-----------|---------|
| A | 飞书群卡回调（工作流入口） | `feishu/callbacks/plan_clarify_callback.py`（前缀 `plan_clarify_`） | `_aget_waiting_node` 幂等门 → `_acollect_round_questions` → `aanswer_round_and_resume(engine=带 node_execution_id)` → `approve_node` 重调度 | ✅ **但只覆盖 workflow 节点**：`plan_research.py:400` 建 `WorkflowEventSubscription(timeout_at=now+60min, timeout_action="fail")`；到期由 `check_timeouts` 把 **NodeExecution/WorkflowExecution 标 TIMEOUT**，**`ConvergenceSession` 仍停在 `waiting_clarification`** ⚠️ |
| B | chat 会话 endpoint（结构化多子题轮） | `chat/views.py:2941` `PlanClarificationAnswerView`（`POST /conversations/<id>/plan-clarification/answer/`） | `ahas_pending` 门 → question_id 越界 400 → `aanswer_round_and_resume(round_id, answers)` | ❌ 无任何超时 |
| C | chat 单题澄清（**不同模型**） | `chat/views.py:2752` `ClarificationAnswerView` | 写 `chat.ConversationIntentTrace` → `ConversationService.resume_clarification_run`（LangGraph interrupt 恢复），**不碰 `delivery.Clarification`** | ❌ 无超时 |
| D | 逃生路径 | `chat/views.py:3123` `ClarificationSkipView` | 按 conversation 维度找最近未答 trace 并注入跳过指令 | 手动触发，非自动出口。已有 `chat/management/commands/cleanup_waiting_clarification_errors.py`（清脏数据，非出口） |

> 命名撞车提示：`services/process_runtime/ask_clarification.py`（写 `delivery.Clarification`）与 `agents/tools/clarification.py:ask_clarification`（`@tool`，写 `chat.ConversationIntentTrace` + LangGraph interrupt）**同名不同物**，靠模块路径区分。RELY-02 的「必达 + 超时出口」目标是 `delivery.Clarification` 这条（路径 A/B），路径 C 属 chat agent 协商卡，是否纳入需 planner 裁决（推荐纳入统计但出口只做 A/B——C 有 LangGraph checkpoint 语义，改动面完全不同）。

**送达失败当前如何处理（关键缺口）** [VERIFIED: 实读 `plan_research.py:432-491`]：

```python
async def _send_clarify_card(self, session, context, clarification_id) -> None:
    try:
        ...  # resolve space → project → chat_id → build_clarification_card → send_card
    except Exception:  # noqa: BLE001 — 发卡 best-effort，绝不反噬挂起
        log.warning("plan_research_clarify_card_failed", session_id=str(session.id))
```

同时函数内有 **4 个静默 `return`**（`not questions` / `space is None` / `project is None` / `not chat_id`）——这四条路径连 warning 都不记，卡片没发出去、会话照样挂起 `waiting_clarification`。这正是 CONTEXT「绝不静默挂起」要修的确切点。

**`delivery_failed` 标记的落点选择**：`Clarification` 模型有 `container_status CharField(max_length=16, null=True)`（当前取值 `pending/answered/skipped`，docstring 明确「严禁命名 status」）。可加取值 `delivery_failed`，或加新字段。**推荐**：`container_status="delivery_failed"` 复用既有列（零迁移列变更，只是新取值）+ 新增 `delivery_attempted_at` / `delivery_error` 若需诊断。注意 `ahas_pending` 谓词（`ClarificationService:281`）当前按 `answered_at__isnull` 判定，需确认 `delivery_failed` 轮是否仍算 pending——**推荐算 pending 但让扫描 job 对它用更短超时（立即出口）**。

**`clarify_adapter` 的 policy 判定点**（`clarify_adapter.py:64`）：

```python
def default_needs_clarification(session) -> tuple[bool, str, list]:
    候选无任一 confidence ∈ {high, medium} → 需澄清
    decomposition["ambiguous"] 真 → 需澄清（取 ambiguous_hint）
    否则不需澄清
```

`_MAX_CLARIFY_ROUNDS = 6`（模块常量，未外置）已提供「轮数上界」兜底，但**它只在下一次 `clarify()` 被调用时生效**——没人来答就永远不会再进 `clarify()`，所以轮数上界救不了「无人应答」。这是 RELY-02 与既有 CLARIFY-07 兜底的关键区别，必须在 PLAN 里说清。

> **DEPTH 冻结遵守**：以上改动全部落在 `plan_research.py` 发卡侧、新 command、`Clarification` 模型列取值、以及 `clarify_adapter` 的**判定之外**。不碰 `clarification_questions.py`（prompt）、不碰 `agenerate_clarification_questions` 的 schema、不碰 `spec_generation`/`merged_plan`/`architect_merge_adapter` 的产出结构。

### 4. 定时任务基建（逐字可镜像的先例）

**注册位置**：`server/agents/management/commands/runapscheduler.py`（唯一 scheduler 进程，`fcntl.flock` 单实例强制，`APSCHEDULER_LOCK_PATH` 可配）。仓库同步轮询在 `:696`（`poll_repository_updates_job`，`IntervalTrigger(seconds=settings.SYNC_INTERVAL_SECONDS)`）。

**两种 job 范式**：
- `run_async_task(coro_func)` 包装异步 `tasks.*` 函数（如 `poll_repository_updates_job`）
- `call_command("...")` 调 management command（命令内部自管事务/`asyncio.run`）——**推荐本 phase 用这条**，与最贴近的先例 `check_workflow_event_timeouts_job`（`:758`，`IntervalTrigger(60s)` → `call_command("check_timeouts")`）一致，且 command 可手动执行便于验收。

**`initiated_by_user_id` 怎么带**：`@_with_scheduler_log_context` 装饰器（`:30`）在 job 执行体外层 `bind_task_context(user_id="system", source="scheduler", component="scheduler")`。**周期任务本身无触发用户 → 记 `system`（符合 CONTEXT）**；但被推进的会话有 `ConvergenceSession.initiated_by_user_id` 字段（`convergence_session_service.py:122` 建会话时写入）——出口动作的日志/事件应把它作为 kv 带上（`initiated_by_user_id=session.initiated_by_user_id or "system"`），这样"谁的会话被超时放行"可归因。

**幂等/并发保护先例**（两层，都要用）：
1. 扫描层：`check_timeouts.py:41-47`
   ```python
   with transaction.atomic():
       expired = list(
           WorkflowEventSubscription.objects.select_for_update(skip_locked=True)
           .filter(is_active=True, timeout_at__lte=now, timeout_at__isnull=False)
           .select_related(...).exclude(workflow_execution__is_debug=True)
       )
   ```
   注意 **SQLite 下 `select_for_update` 是 no-op**（`graph_builder.py:94` / `indexer.py:3407` 都显式记录）——本地开发/测试环境的并发保护实际来自单进程 + `max_instances=1`。
2. 状态转移层：`ConvergenceSessionService._apply_transition_sync`（`:219`）
   ```python
   updated = ConvergenceSession.objects.filter(id=session.id, current_stage=from_stage).update(**values)
   if updated != 1: raise ConcurrentTransitionError(...)
   ```
   这就是 CONTEXT 要的「状态条件更新」——**天然保证出口只生效一次**（第二个并发扫描的 CAS 命中 0 行 → 抛 `ConcurrentTransitionError`，捕获后当幂等 no-op 处理）。

**事务边界纪律**（`check_timeouts` 已踩过的坑，逐字照抄）：`select_for_update` 的 `atomic` 块内**只收集**目标，异步引擎重驱（`aanswer_round_and_resume` / `adrive_convergence_session_to_pause_or_terminal`）必须在事务外 `asyncio.run`（`:60-68`）。

### 5. Stage 1 现状与有界重排落点

**现状（`_stage1_llm_reasoning`，`repo_router_v2.py:991-1271`）**：

| 项 | 现状 | 位置 |
|----|------|------|
| 重试 | `max_retries=0`（显式关掉 langchain 默认 2 次，注释说明「路由是启发式，超时无需 3× 重试空等」） | `:1061` |
| 超时 | 单层 `asyncio.wait_for(model.ainvoke([system, human]), timeout=timeout_seconds)`，`timeout_seconds = REPO_ROUTER_STAGE1_TIMEOUT_SECONDS`（默认 **90.0**，`settings.py:328`，env 可覆盖） | `:1048` / `:1168` |
| decode | `temperature=0, top_p=1, seed=42` 固定，参与缓存 key | `:97` |
| 缓存 | `sha256(model_id ‖ PROMPT_TEMPLATE_VERSION ‖ canonical_json(stage0_input) ‖ decode_params ‖ index_version)`，TTL 86400 | `:964-988` |
| 候选窗口 | `stage0_candidates[:REPO_ROUTER_STAGE1_MAX_CANDIDATES]`，默认 **8**（不是 12） | `:1069` |
| 输出消费 | LLM 只给排列；`score=float(base["score"])`（**Stage 0 分原样**）；`confidence = apply_llm_adjustment(deterministic, llm_conf)`（只降不升） | `:1224-1254` |

**RELY-05 改造落点**：

(a) **1 次重试 + 总延迟上界**。推荐结构（放在 `:1160-1174` 的 `if not cache_hit:` 块内）：
```python
budget_deadline = time.monotonic() + total_budget_seconds      # 新 settings：总预算
for attempt in range(2):                                        # 首调 + 1 次重试
    remaining = budget_deadline - time.monotonic()
    if remaining <= 0: raise TimeoutError("stage1_budget_exhausted")
    try:
        with use_call_source(CallSource.AUX_REPO_ROUTER):
            response = await asyncio.wait_for(model.ainvoke([system, human]),
                                              timeout=min(per_call_timeout, remaining))
        break
    except (asyncio.TimeoutError, <网关/连接异常>):
        if attempt == 1: raise
        await asyncio.sleep(min(backoff_base, max(0.0, budget_deadline - time.monotonic())))
```
⚠️ **参数拆分是硬约束**：现默认 `TIMEOUT_SECONDS=90` 若直接当总预算，首调就能吃满 90s、重试无余量。推荐 `REPO_ROUTER_STAGE1_TIMEOUT_SECONDS` 保持 per-call 语义并**下调默认**（O-6 实测后定，观测到的 34–71s 说明 40–45s 会切掉长尾）+ 新增 `REPO_ROUTER_STAGE1_TOTAL_BUDGET_SECONDS`（默认 90，与今日行为上界一致 → 零回归）。若 planner 不愿改现有默认，则总预算设 120 并保持 per-call 90（重试只在快速失败场景生效）。

(b) **rank-swap budget + 凸组合的落层**：应是**新纯函数**，`repo_router_scoring.py` 的六信号打分口径一行不改。推荐新建 `server/codegraph/services/repo_router_ranking.py`（零 Django import，便于进 golden/单测），导出：
```python
def clamp_llm_permutation(llm_order: list[str], stage0_order: list[str], k: int) -> list[str]
def blend_ranked_scores(stage0_scores: dict[str, float], llm_rank: dict[str, int],
                        *, alpha: float, n: int) -> dict[str, float]
```
调用点：`_stage1_llm_reasoning` 内 `parsed` 消费循环之后（此时已有 `by_id` / `rank_by_id` / `seen` 去重结果），或 `route()` 内 Stage 1 返回后。**推荐前者**——白名单过滤/去重/`apply_llm_adjustment` 都在那儿，K 裁剪与它们同层最自然。

(c) 🔴 **`S_ranked` 绝不能覆盖 `RepoRouteCandidateV2.score`**（本 phase 最容易踩死的一条）。硬证据：
- `server/tests/codegraph/test_repo_router_v2_meta.py:248` 与 `:462`：`assert abs(math.fsum(top.breakdown.values()) - top.score) < 1e-9`
- `RoutingDecisionPanel.vue:129-145`：`Math.abs(sum - c.score) > 1e-6` → `console.warn`；`:283` 合计行渲染 `c.score.toFixed(3)`
- ROUTE-07 的可拆解不变量 INV-R3（`Σ w_j·M_j == S_final`）是 Phase 105/106 的交付承诺

`S_ranked = (1-α)·S_final + α·S_llm` 里的 `α·S_llm` 项**不是任何信号的贡献**，塞进 breakdown 会让「分数分解」变成假的。**推荐**：新增旁路字段 `score_ranked: float | None = None`（默认 `None` = 未重排，消费方回退 `score`），排序用它、展示 breakdown 仍用 `score`；前端合计行文案保持 `score`，另在排序处用 `score_ranked ?? score`。

(d) **confidence 不能改由 `S_ranked` 推导**。现状 `_deterministic_confidence(sorted_scores, rank)` 吃的是 Stage 0 分数列表（`:1210` `sorted_scores = [float(c["score"]) for c in stage0_candidates]`）。若改吃 `S_ranked`，LLM 就重新变成了置信度的决策者，直接违背 RELY-04（Phase 105 刚修完的死锁根因）。**保持现状**，只让 `apply_llm_adjustment` 继续做「只降不升」。

(e) **N=1 除零**：`S_llm = 1 - (rank_llm-1)/(N-1)`，`N` 取参与重排的候选数（= `len(stage0_candidates)` 截断后，≤8）。N==1 时分母为 0 → 必须短路（单候选无重排空间，直接 `S_ranked = S_final`）。写成单元测试。

(f) **golden 门禁不受影响**：离线 harness `score_case`（`repo_router_eval.py`）走的是纯 Stage 0 六信号路径，Stage 1 从不参与 → α=0 恒成立 → `phase106-v2` baseline 无需重建。⚠️ 但如果 planner 让 `S_ranked` 影响 `ranked_repo_ids` 的生成口径，baseline 就会动——**不要**把凸组合塞进 `evaluate_cases`。

### 6. 降级原因分类：6 个分支 → 粗粒度枚举映射

现有降级出口（全部实读）：

| 触发点 | 代码位置 | 现有 `skipped_reason` | 建议粗粒度枚举 | 用户可见文案 |
|--------|---------|---------------------|---------------|-------------|
| provider 未解析 | `:1023` | `provider_missing` | `provider_missing` | 未配置模型 |
| 无 model 名 | `:1046` | `no_model_configured` | `provider_missing`（合并） | 未配置模型 |
| LLM 输出不可解析 | `:1206` | `unparsable_llm_output` | `unparsable` | 解析失败 |
| LLM 输出无合法候选 | `:1257` | `no_valid_candidates_in_llm_output` | `unparsable`（合并） | 解析失败 |
| `route()` 捕获任意 Stage 1 异常 | `:322-332` | `stage1_failed:{ExceptionName}` | 按异常类型细分 → `timeout` / `upstream_error` / `unknown` | 超时 / 网关错误 / 未知 |
| Stage 0 零候选 / `use_llm=False` | `:300` / `:313` | `no_stage0_candidates` / `use_llm_false` | **不算降级提示**（前者是数据缺失、后者是主动纯检索） | 不提示 |
| v1 回落 | `:1298` | `router_version="v1_fallback"` | `no_node_index` | 无能力树索引 |

**异常类型 → 枚举的映射建议**（`route()` 的 `except Exception as exc` 分支，已有 `type(exc).__name__`）：
- `asyncio.TimeoutError` / `TimeoutError` → `timeout`
- httpx / openai / anthropic 的连接与 HTTP 状态异常（`ConnectError` / `APIConnectionError` / `APIStatusError` / `BadRequestError` …）→ `upstream_error`（**不要**把上游 400 的 body 原文透给用户）
- 其它 → `unknown`

**枚举值必须是受控闭集**（否则前端 i18n map 与指标维度基数失控），推荐 6 值：`timeout / upstream_error / provider_missing / unparsable / no_node_index / unknown`。

**脱敏纪律**：现状 `logger.warning(..., error=str(exc)[:200])`（`:326`）——**截断不是脱敏**。凡是要入库（`RepositoryRoutingTrace.degrade_reason` / 事件 payload）或回前端的原始文本，必须先 `redact_secrets_in_text(str(exc))`。粗粒度枚举本身不含敏感信息，**推荐前端只拿枚举 + 后端把脱敏后的原文留在事件 payload 里供排障**（最小泄漏面）。

### 7. 事件源与 Phase 110 复用面

**唯一写入入口**：`ConvergenceSessionService._emit_event(event_name, session, payload)`（`:304`）→ `ConvergenceSessionEvent(session, event, work_item, payload, ts)`。best-effort（持久化失败只 warning），**绝不抛**。同时打一条 `convergence_session_event` structlog（`category="sampling"`, `component="convergence_session_service"`）。

**现有 taxonomy**（`delivery/services/event_taxonomy.py`，`ALL_EVENTS` 13 值 + `RESERVED_EVENTS` 3 值）：`knowledge.recalling` / `repo.routing` / `repo.research.{started,completed,failed}` / `clarification.{asked,answered}` / `technical_plan.feature.classified` / `technical_plan.merge.{started,completed}` / `technical_plan.validation.failed` / `process.session.failed` / `spec.drafted`。有守护测试断言「所有 emit 点引用值 ∈ ALL_EVENTS」且「每个 `ALL_EVENTS` 成员至少被一个 emit 点产出」（覆盖性反查）——**新增常量必须同时加进 `ALL_EVENTS` 并真的 emit**，否则守护测试红。

**本 phase 推荐的事件设计**：
- 澄清超时出口 → **新增** `EVENT_CLARIFICATION_TIMED_OUT = "clarification.timed_out"`，payload `{clarification_id, round_no, exit_action: "resumed_with_assumptions"|"failed_no_answer", waited_seconds, unclarified_points: [...]}`。理由：Phase 110 时间线必须能区分「用户答了」与「超时放行」，塞进 `clarification.answered` 会让时间线撒谎（正是本 phase 要消灭的行为）。
- 澄清送达失败 → **新增** `EVENT_CLARIFICATION_DELIVERY_FAILED = "clarification.delivery_failed"`，payload `{clarification_id, channel: "feishu", reason}`（reason 为受控枚举：`no_space` / `no_project` / `no_chat_id` / `send_failed` / `no_questions`，对应 `_send_clarify_card` 的 4 个静默 return + except）。
- 降级原因 → **扩 `repo.routing` 的 payload**（不新增事件）：`_routing_snapshot_payload` 已出 `degraded`，加 `degrade_reason` 一键即可。理由：降级是路由这一次事件的属性，不是独立生命周期事件。

**Phase 110 的形状前瞻**：`ConvergenceSessionEvent` 有 `Index(fields=["session","ts"])`，按 session 时序拉取即时间线。为 110 留面只需保证：(1) 每个新事件都带**同一批关联键**（`session_id` 由信封自带，payload 里补 `clarification_id` / `run_id` 等）；(2) payload 有 `duration_ms` 或 `waited_seconds` 之类可算耗时的量；(3) 事件名用点分层级（`clarification.*`）便于前端按前缀分组。**不要**在本 phase 建 WebSocket 推送/流式通道——那是 110 的活。

### 8. 前端现状（`RoutingDecisionPanel.vue`，105-06/106-05 改动后）

结构（303 行，实读）：`Card` → 折叠按钮（`collapsed` ref，标题带 `高 N · 中 N · 低 N` 计数）→ query + threshold 行 → `TooltipProvider > ul > li`（每候选：`Checkbox` + 仓名 + score/level `Badge`(Tooltip) + evidence(Tooltip) + `Collapsible` 分数分解）→ 两个按钮。

**可复用资产**：
- `Badge` variant 池（`web/src/components/ui/badge/index.ts`）：`default / secondary / destructive / outline / success / warning / info / muted` —— **零新色板可满足**：跨组 badge 用 `info` 或 `muted`；降级态 confidence 徽标从 `success/warning` 降为 `muted`；面板级降级提示用 Tailwind `amber-500/30` + `icon-[lucide--triangle-alert]`（仓内既有告警条范式：`CommitConfirmCard.vue:102-105`、`ContextExceededCard.vue:81`、`ConversationBadges.vue:44` 三处同款）。
- `Collapsible / CollapsibleTrigger / CollapsibleContent` 已 import —— 全局组默认折叠直接用它。
- **无 `ui/alert` 组件**（`web/src/components/ui/` 33 个目录里没有 alert，只有 `alert-dialog`）→ 降级横幅按上述 Tailwind 内联类写，与既有三处告警条一致。
- `SIGNAL_LABELS`（`:84`）是硬编码中文 map 而非 i18n（106-05 既定），新增分组/trust 文案沿用同一风格（硬编码中文常量）以保持一致。

**必改点**：`sortedCandidates`（见 §2 第 5 条）；新增分区渲染；新增 `props`/store 字段读取 `degraded` / `degrade_reason` / `block_order`。测试文件 `web/src/components/chat/__tests__/RoutingDecisionPanel.test.ts` 现 12 passed，需扩用例（分区渲染 / 降级横幅 / 折叠默认态 / 缺字段静默降级）。

### 9. O-6 延迟实测：数据来源

⚠️ **重要发现：Stage 1 不落 `ModelUsageRecord`。** `_stage1_llm_reasoning` 用 `build_chat_model(...).ainvoke(...)` **直调**，`use_call_source(CallSource.AUX_REPO_ROUTER)` 只是设 contextvar；而 `ModelUsageRecord` 的写入点是 `interactions/ledger.py:record_model_usage` / `arecord_model_usage`，调用方只有 `mcp_tools/views.py` 三处 + 两个 Runner（`agents/langchain_runner.py:551` 带 `ttft_ms`、`agents/chat_runner.py`）与 `subagent/api/callbacks.py:1376` [VERIFIED: `rg record_model_usage` 全量]。Stage 1 不经这些 chokepoint → **`ModelUsageRecord` 里查不到 `aux_repo_router` 的行**。

**可用数据源（两条，推荐第一条）**：
1. **`SystemLogEntry`**（`system/models.py:342`）：字段 `ts`(db_index) / `level` / `component` / `category` / `event` / `payload`(JSONField) / `user_id` / `source` / `trace_id` / `request_id`；`Index(component, -ts)`。Stage 1 已有 `logger.info("repo_router_v2_stage1_completed", model=..., candidate_count=..., parsed_count=..., duration_ms=int(...), category="sampling", component="repo_router_v2")`（`:1184-1192`）—— `duration_ms` 就在 `payload` 里。查询：
   ```sql
   -- Postgres（生产）：LOGGING-SPEC §4.3 明确用 percentile_cont，不自研直方图
   SELECT percentile_cont(0.5)  WITHIN GROUP (ORDER BY (payload->>'duration_ms')::int) AS p50,
          percentile_cont(0.9)  WITHIN GROUP (ORDER BY (payload->>'duration_ms')::int) AS p90,
          percentile_cont(0.99) WITHIN GROUP (ORDER BY (payload->>'duration_ms')::int) AS p99,
          count(*) AS n
   FROM system_log_entry   -- 实际表名见 Meta.db_table，需核对
   WHERE event = 'repo_router_v2_stage1_completed' AND ts >= now() - interval '7 days';
   ```
   ⚠️ 两个前置条件：(a) `category="sampling"` 的事件受运行时采样配置（`SettingKeys.LOG_*`）影响，可能不是全量落库——测量前需确认采样率并在 `107-MEASUREMENTS.md` 里标注；(b) 该事件是 `logger.info`，若 `repo_router_v2` 组件级日志级别被调到 WARNING 就没有行。**SQLite 本地无 `percentile_cont`** → 本地只能近似或用 Python 算分位。
2. **补埋 `ModelUsageRecord`**（顺手补齐 LOGGING-SPEC §9 检查项「新增 LLM 调用点：赋 call_source，上报 TTFT/上游错误码」）：在 Stage 1 调用点加 `arecord_model_usage(..., call_source=CallSource.AUX_REPO_ROUTER, duration_ms=..., upstream_status_code=..., failure_type=...)`。这条其实是 Phase 105 遗留的埋点缺口，RELY-05 改造时一并补最经济，且让 `system/metrics_query.py` 的既有分位聚合直接可用（无需新写查询）。**推荐两条都做**：先用 (1) 出 O-6 数字（零改动即可测），同时用 (2) 让后续可持续观测。

**落文档形态**：`107-MEASUREMENTS.md`，沿用 105/106 的数据环境标注纪律（哪个环境、什么时间窗、样本量 n、采样率、是否含缓存命中）。⚠️ 缓存命中路径**不发 LLM 调用也不打 `stage1_completed`**（`if not cache_hit:` 块内才打）→ 实测的是「未命中时的真实上游延迟」，这正是要的口径，但必须在文档里写明，否则会被误读成「用户感知延迟」。

**交付形态推荐**：management command（如 `measure_stage1_latency`），镜像 105 的 `measure_repo_index_stats`（有测试 `tests/codegraph/test_measure_repo_index_stats.py`），输出只含分位数/计数/时间窗，无敏感串。

### 10. golden fixture 的 cross_group 样本 + delta 离线验证（已实测）

**fixture 结构**（`server/tests/codegraph/fixtures/repo_router_golden/golden_main.json`，14 条 main case）：每 case 键为 `{id, _notice, query, label_source, cross_group, project_scope?, expected_repos, node_hits, repo_meta, scored_at, constants}`。⭐ **已有 `project_scope` 字段**（仅 cross_group 样本带），正是分组归属的离线表达。

2 条 cross_group 样本：

| case | `project_scope` | `expected_repos` | node_hits 覆盖仓 |
|------|----------------|------------------|-----------------|
| `gk-008-cross-group-auth` | `["edu-content-hub"]` | `["auth-service"]` | `auth-service`, `edu-content-hub` |
| `gk-009-cross-group-payment` | `["finance-dashboard"]` | `["payment-gateway"]` | `payment-gateway`, `finance-dashboard` |

**本次离线实测（零网络，纯函数 `score_case`，`phase106-v2` 生效权重）** [VERIFIED: 实跑 `uv run python -c "from codegraph.services.repo_router_eval import score_case ..."`]：

| case | S_in_project(1) | S_global(1) | delta = 差值 | delta=0.15 是否触发置顶 | 余量 |
|------|----------------|-------------|-------------|----------------------|------|
| `gk-008-cross-group-auth` | `edu-content-hub` 0.7565 | `auth-service` 0.9336 | **0.1771** | ✅ 触发 | +0.0271 |
| `gk-009-cross-group-payment` | `finance-dashboard` 0.6238 | `payment-gateway` 0.8852 | **0.2614** | ✅ 触发 | +0.1114 |

**校准结论（O-4 收口）**：CONTEXT 锁定的 `delta = 0.15` 被现有 golden 数据验证可用——两条样本都触发置顶，正确答案（在跨组）会被置顶到用户眼前。**delta 的可用上界由 gk-008 约束为 < 0.1771**；若 planner 想调高 delta，超过 0.177 就会让 gk-008 回到「本项目组置顶而正确仓被压在下面」，等于重演本里程碑要修的故障。建议在 PLAN 里把这两条写成**机制级断言**（ROUTING-RANKING §7.4 纪律）：

```python
# ✅ 机制断言：锁「跨组正确仓能被置顶」这个因果性质
assert block_order_for(gk008) == ["global", "in_project"]
assert delta_of(gk008) >= DELTA_DEFAULT      # 现值 0.1771 >= 0.15
# ❌ 不要写 assert delta_of(gk008) == 0.1771（权重微调即假红）
```

**迟滞行为的验证方式**：单元测试注入两组人造分数（差值 = delta ± ε）证明「差值恰好在阈值下不翻转、在阈值上翻转」，再证明「同一输入重复调用 block_order 恒等」（幂等，ROUTING-RANKING §6 清单）。这不需要 fixture，纯函数即可。

---

## Architecture Patterns

### System Architecture Diagram

```
                        ┌─── 有项目上下文 ───────────────────────────────┐
用户需求文本 ──┬─ 编排入口 (repo_router_adapter, 经 work_item.space)   │
              ├─ chat 工具 (repository_relevance, 经 space_id)         │──┐
              ├─ MCP route_repositories ──── 无项目上下文 ────────────┐ │  │
              └─ REST /repositories/route/ ─ 无项目上下文 ────────────┤ │  │
                                                                      │ │  │
                                        ┌─────────────────────────────▼─▼──▼─┐
                                        │ RepoRouterV2.route()               │
                                        │  Stage 0: hybrid 检索 → 六信号打分  │
                                        │    (repo_router_scoring 纯函数,    │
                                        │     口径冻结, S_final + breakdown) │
                                        └───────────┬────────────────────────┘
                                                    │ stage0_candidates (≤12→截8)
                                     ┌──────────────▼───────────────┐
                                     │ Stage 1 (可跳过/可失败)       │
                                     │  ① 输入哈希缓存命中? → 直接用 │
                                     │  ② 首调 + 1 次退避重试        │  ← RELY-05 (a)
                                     │     共享总预算 deadline       │
                                     │  ③ 只输出排列, 不输出分数     │
                                     └──────┬──────────────┬────────┘
                                    成功    │              │ 失败/超时/未配/不可解析
                                            │              │
                        ┌───────────────────▼──┐      ┌────▼──────────────────────┐
                        │ repo_router_ranking  │      │ 降级出口                   │
                        │  (新纯函数模块)      │      │  degraded=True             │
                        │  · K=3 rank 裁剪     │      │  router_version=           │  ← RELY-03
                        │  · S_ranked 凸组合   │      │   v2_stage0_only/v1_fallback│
                        │    → score_ranked    │      │  degrade_reason=<6值枚举>   │
                        │  (score/breakdown    │      │  (α=0, score_ranked=None)  │
                        │   一律不动!)         │      └────┬───────────────────────┘
                        └───────────┬──────────┘           │
                                    └──────────┬───────────┘
                                    ┌──────────▼─────────────────────┐
                                    │ 分组标注 (新纯函数)             │
                                    │  · group = repo ∈ 项目关联仓?   │  ← ROUTE-01
                                    │  · trust / cross_group_note     │  ← ROUTE-02
                                    │  · block_order: delta 迟滞比较   │
                                    │  · 无项目上下文 → 全 global      │
                                    └──────────┬─────────────────────┘
                                               │
              ┌────────────────────────────────┼───────────────────────────────┐
              │ 编排链                          │ chat 链                       │
              ▼                                 ▼                              │
   session.routing (精简)          RepositoryRelevanceCandidate (pydantic)      │
   + EVENT_REPO_ROUTING             → RepositoryRoutingTrace(candidates JSON,   │
     (payload 含 degrade_reason)       router_version, +degrade_reason 列?)      │
              │                       → chat/views detail payload               │
              ▼                       → routing store (⚠️ override 会丢字段)     │
   clarify / research / merge         → RoutingDecisionPanel.vue                 │
   (读 confidence, 加字段无感)          · 【本项目关联仓】Top-3                   │
              │                          · 【全局候选】Top-3 (可折叠 + badge)     │
              │                          · 降级横幅 + 徽标降级样式               │
              ▼                                                                 │
   ┌──────────────────────────────────────────────┐                            │
   │ clarify stage (pausable, waiting_clarification)│                           │
   │  发卡 (feishu) ─失败→ delivery_failed 留痕     │  ← RELY-02                 │
   │  收答 3 路: 飞书回调 / chat endpoint / (chat 单题)│                          │
   └──────────────┬───────────────────────────────┘                            │
                  │ 无人应答                                                    │
   ┌──────────────▼──────────────────────────────────────┐                     │
   │ apscheduler job (system 归因)                        │                     │
   │  → management command: 扫过期 pending                │                     │
   │     select_for_update(skip_locked=True) 事务内收集   │                     │
   │     事务外: transition("clarified") ← CAS 天然幂等   │                     │
   │            或 transition("fail")                     │                     │
   │     emit clarification.timed_out                     │──→ Phase 110 时间线 │
   └──────────────────────────────────────────────────────┘   复用同一事件源 ───┘
```

### Recommended Project Structure（增量）

```
server/
├── codegraph/services/
│   ├── repo_router_ranking.py        # 新建：K 裁剪 + 凸组合 + 分组/block_order（零 Django import，纯函数）
│   ├── repo_router_v2.py             # 改：candidate 新字段、Stage 1 重试与预算、降级原因、调用 ranking
│   └── repo_router_config.py         # 可能改：若参数走 SystemSetting（推荐不改，走 settings）
├── codegraph/management/commands/
│   └── measure_stage1_latency.py     # 新建：O-6 分位查询（镜像 measure_repo_index_stats）
├── delivery/
│   ├── models/clarification.py       # 改：container_status 新取值 delivery_failed（+ 诊断字段）
│   └── services/event_taxonomy.py    # 改：新增 2 个事件常量并加入 ALL_EVENTS
├── delivery/management/commands/
│   └── expire_pending_clarifications.py  # 新建：超时扫描 + 出口（镜像 check_timeouts.py）
├── agents/management/commands/runapscheduler.py  # 改：注册 1 个 job（call_command 范式）
├── services/process_runtime/repo_router_adapter.py  # 改：透传分组字段
├── workflows/nodes/ai/plan_research.py  # 改：_send_clarify_card 4 个静默 return → 留痕 + emit
├── agents/tools/schemas/repository_relevance.py  # 改：Output candidate 新字段
├── chat/models.py + migrations/       # 改：RepositoryRoutingTrace 加 degrade_reason 列
└── chat/views.py                      # 改：routing_trace_payload 补 router_version/degraded/degrade_reason

web/src/
├── types/routing.ts                   # 改：RoutingCandidate/RoutingDecisionData 新字段（全 optional）
├── stores/routing.ts                  # 改：applyManualOverride 保留 degraded/router_version/degrade_reason
├── stores/chat.ts                     # 改：三处 upsertTrace 透传新字段
└── components/chat/RoutingDecisionPanel.vue  # 改：分区渲染 + 降级横幅 + 排序改为 score_ranked ?? score
```

### Pattern 1: 纯函数 + 参数注入（106-RESEARCH Pattern 2 的延续）

**What:** 打分/排序/分组决策写成零 I/O 纯函数，配置由 router 层读取后以参数注入。
**When to use:** 任何需要进 golden set / 离线回放 / 单元测试的逻辑。
**Example:**
```python
# server/codegraph/services/repo_router_config.py 的既有范式（照抄）
aload_weight_config = sync_to_async(load_weight_config, thread_sensitive=False)

# 新模块保持同样纪律：零 Django import、零 settings 读取
def decide_block_order(in_project_top: float | None, global_top: float | None,
                       *, delta: float) -> list[str]:
    """delta 迟滞比较（纯函数，可幂等断言）。"""
    if in_project_top is None:
        return ["global"]
    if global_top is None:
        return ["in_project"]
    return ["global", "in_project"] if (global_top - in_project_top) >= delta else ["in_project", "global"]
```
> 守护测试可直接 `rg -c 'import django|from django' server/codegraph/services/repo_router_ranking.py == 0`（106-08 用过同款自检）。

### Pattern 2: 定时扫描 = 事务内收集 + 事务外重驱

**What:** `select_for_update(skip_locked=True)` 在 `transaction.atomic()` 内**只列出并标记**目标，异步重驱在事务外。
**When to use:** 任何「扫到期行 → 调异步引擎」的 job。
**Example (逐字来自 `server/workflows/management/commands/check_timeouts.py:38-68`):**
```python
retry_targets: list[tuple[str, str]] = []
with transaction.atomic():
    expired = list(
        WorkflowEventSubscription.objects.select_for_update(skip_locked=True)
        .filter(is_active=True, timeout_at__lte=now, timeout_at__isnull=False)
        .select_related("workflow_execution", "node_execution")
    )
    for sub in expired:
        try:
            target = self._handle_timeout(sub)
            if target is not None:
                retry_targets.append(target)
        except Exception:
            logger.exception("timeout_handle_error", subscription_id=str(sub.id))
# 事务外重跑（异步引擎入口不能在 atomic + select_for_update 内调用）
for wf_exec_id, node_exec_id in retry_targets:
    try:
        asyncio.run(self._redrive_retry(wf_exec_id, node_exec_id))
    except Exception:
        logger.exception("timeout_retry_redrive_error", ...)
```

### Pattern 3: 状态转移 CAS 即幂等（无需另建锁）

**Example (`server/delivery/services/convergence_session_service.py:219-227`):**
```python
updated = ConvergenceSession.objects.filter(
    id=session.id, current_stage=from_stage
).update(**update_values)
if updated != 1:
    raise ConcurrentTransitionError(...)
```
出口调用方只需捕获 `ConcurrentTransitionError` 当 no-op：
```python
try:
    await ConvergenceSessionService().transition(session, "clarified", stage_state=new_state)
except ConcurrentTransitionError:
    logger.info("clarification_timeout_exit_noop_concurrent", category="sampling",
                component="delivery", session_id=str(session.id))
    return  # 已被并发/前一次扫描推进，幂等返回
```

### Anti-Patterns to Avoid

- **给 in-project 加分数偏移**（`score += 0.1`）：CONTEXT 明令禁止；会让两组分数不可比，"跨组分更低" 变成自我实现预言。
- **把 `S_ranked` 写进 `score` 或 `breakdown`**：打断 `Σbreakdown == score`（两条既有断言 + 前端容差校验），且 `α·S_llm` 不是任何信号的贡献。
- **让 `S_ranked` 参与 confidence 推导**：LLM 重新变成决策者，回退 RELY-04。
- **前端按仓名/路径猜分组**：归属只有服务端知道（关联表在 DB）。
- **新增 `ConvergenceSessionStatus` 枚举值**：30 个文件引用 `waiting_clarification`，`lifecycle_projection` / `chat` / `orchestration` 都有 status 分支；用 stage graph + `stage_state` 表达出口更安全。
- **在扫描 job 里直接写 `ConvergenceSession.status`**：绕过 `transition` 唯一入口（INV-6），丢掉 CAS 幂等与事件 emit。
- **把 `str(exc)[:200]` 当脱敏**：截断不是脱敏，必须 `redact_secrets_in_text`。
- **delta = 0**：0.001 级波动反复翻转置顶，破坏幂等（ROUTING-RANKING §5.2 明确）。
- **`_send_clarify_card` 继续静默 return**：4 条静默路径就是「无声卡死」的直接成因。

---

## Don't Hand-Roll

| 问题 | 别自己写 | 用现成的 | 为什么 |
|------|---------|---------|--------|
| 周期任务调度 | 自建线程 + `while True: sleep` | `runapscheduler.py` 加一个 `add_job`（`CronTrigger` / `IntervalTrigger`, `max_instances=1`, `replace_existing=True`） | 单实例 flock、DjangoJobStore 崩溃恢复、`DjangoJobExecution` 审计、`delete_old_job_executions` 清理全都现成 |
| 后台任务的用户归因 | 手工 `bind_contextvars` | `@_with_scheduler_log_context` 装饰器 | 已固定 `user_id="system"/source="scheduler"/component="scheduler"`，且 best-effort 不打断 job |
| 并发扫描互斥 | 自建 advisory lock / Redis 锁 | `select_for_update(skip_locked=True)`（Postgres）+ `max_instances=1` + transition CAS | 三层已足够；且仓内已明确记录 SQLite no-op 的事实，避免踩「本地测不出」的坑 |
| 会话状态单次推进 | 先 `if status == X` 再 `save()` | `ConvergenceSessionService.transition`（CAS on `current_stage`） | TOCTOU 已被 WR-01 处理过一轮；自己写必然重演 |
| 澄清作答 + 续推 | 各入口各写一份 | `aanswer_round_and_resume(clar_or_id, answers, engine=...)`（`process_runtime/answer_resume.py`） | 飞书回调与 chat endpoint 已同源复用；INV-6 写入只经 `answer_round` |
| 澄清落库 | 直接 `Clarification.objects.create` | `ClarificationService.create_round` / `answer_round`（`ask_clarification` helper 是其薄封装） | INV-6 有 grep 守护断言覆盖子模型 |
| pending 判定 | `answered_at__isnull=True` 自己查 | `ClarificationService.ahas_pending(session_id)` | 统一谓词兼容旧单题行 + 新结构化子题（T-90-03-04），自己写会误判 |
| 事件持久化 | 直接建 `ConvergenceSessionEvent` | `ConvergenceSessionService._emit_event` | 唯一入口 + best-effort + 统一信封 + Phase 110 复用面 |
| 分位统计 | 自研直方图/聚合器 | Postgres `percentile_cont`（LOGGING-SPEC §4.3 明确）或既有 `system/metrics_query.py` | 量级低不值得自研；口径要与运维大盘一致 |
| 凭证脱敏 | 自己写正则 | `redact_secrets_in_text`（日志/展示）/ `redact_for_ledger`（入库） | 已覆盖 `sk-*` / `sk-ant-*` / `AIza*` / `Bearer *` / PEM；脱敏不可绕过是强制规范 |
| 告警条组件 | 新建 `ui/alert` + 新色板 | 仓内三处既有范式（`CommitConfirmCard.vue:102` / `ContextExceededCard.vue:81` / `ConversationBadges.vue:44`）+ `Badge` 8 variant | CONTEXT 锁定「零新色板」 |
| LLM 重试 | 打开 langchain `max_retries=2` | 显式重试循环 + 共享 deadline | langchain 内部重试**不受我们的总预算约束**，且 105 已刻意关掉它（注释记录了 30s×3≈90s 的旧病） |

**Key insight:** 本 phase 几乎不需要发明任何机制——`check_timeouts.py`（扫描+出口）、`transition` CAS（幂等）、`answer_resume`（收答续推）、`_emit_event`（事件）、`runapscheduler`（调度）、`Badge`/`Collapsible`（前端）六件套已经把所有"难做对"的部分做对了。新代码的价值全在**接线正确**与**边界正确**（字段不覆盖、事务不嵌套、脱敏不遗漏）。

---

## Runtime State Inventory

> 本 phase 主体是新增功能而非重命名，但 RELY-02 涉及**生产中已存在的卡死会话**——不清点会导致「新出口只对未来会话生效，历史卡死会话仍永久挂起」。

| 类别 | 发现项 | 需要的动作 |
|------|--------|-----------|
| **存量数据** | 生产库中已存在停在 `status=waiting_clarification` 的 `ConvergenceSession`（CONTEXT 记录：会话 `ccd817d9` 有 2 条）。新扫描 job 的 `WHERE status='waiting_clarification' AND <pending 轮 created_at + timeout <= now>` 会**立刻命中这些历史行**并批量推进 | ⚠️ **planner 必须决策**：首次上线是否需要 dry-run / 分批 / 只处理 N 天内的行。推荐 command 支持 `--dry-run` 与 `--limit`，首次人工跑 dry-run 看清影响面（这也是 UAT 的天然验收手段） |
| **存量数据（澄清轮）** | `Clarification.container_status` 现有行可能为 `NULL`（字段 `null=True`，旧行不强制回填，见模型 docstring）。若新逻辑按 `container_status == "pending"` 过滤会漏掉全部旧行 | 判定统一走 `ClarificationService.ahas_pending`（按 `answered_at__isnull`），**不要**按 `container_status` 过滤 |
| **活跃服务配置** | `WorkflowEventSubscription(timeout_at=now+60min, timeout_action="fail")` 是 `plan_research.py:400` **代码写死**的 60 分钟——不是数据库配置。生产中已有的活跃订阅行携带旧 `timeout_at` | 若改这个 60min（与新的 24h 澄清超时不一致，见 OQ-2），旧订阅行的 `timeout_at` 不会自动更新，只影响新建订阅——可接受，但要在 PLAN 里说明 |
| **OS 注册状态** | apscheduler job 存在 `django_apscheduler_djangojob` 表（DjangoJobStore）。新 job 首次启动由 `add_job(replace_existing=True)` 自动建；**若后续改 trigger 间隔**，`runapscheduler.py:704-706` 记录的坑会重演（旧 `job_state` 残留旧 trigger） | 新增 job 无历史行，首次上线无需清理。若上线后改间隔，按 `:705` 注释在生产执行 `DELETE FROM django_apscheduler_djangojob WHERE id='<new_job_id>';` |
| **Secrets / env vars** | 新增 `REPO_ROUTER_STAGE1_TOTAL_BUDGET_SECONDS` / `REPO_ROUTER_GROUP_DELTA` / `REPO_ROUTER_STAGE1_ALPHA` / `REPO_ROUTER_STAGE1_RANK_BUDGET_K` / `CLARIFICATION_TIMEOUT_HOURS` 等 env 键；均为**非敏感数值**，有代码内默认值 | 需同步更新根目录 `.env.example`（该文件"documents all vars"，见 STACK.md Configuration）。无密钥变更 |
| **构建产物 / 已装包** | 无（零新依赖，无 egg-info / 无镜像 tag 变更） | 无动作。前端新增字段不需要重新生成 `auto-imports.d.ts`（不新增组件文件的前提下） |
| **缓存** | Stage 1 输入哈希缓存 key 含 `PROMPT_TEMPLATE_VERSION`。本 phase **不改 prompt 文案**（DEPTH 冻结 + 无需改）→ key 不变 → 历史缓存继续命中，无需清理。⚠️ 但若 planner 决定改 system prompt（例如告知 LLM K 约束），**必须递增 `PROMPT_TEMPLATE_VERSION`**（`repo_router_v2.py:92` 的注释是硬约束） | 推荐不改 prompt：K 裁剪在**消费侧**做，比让 LLM 自觉遵守更可靠 |

---

## Common Pitfalls

### Pitfall 1: `S_ranked` 覆盖 `score` → 打断可拆解不变量与前端渲染

**What goes wrong:** `Σbreakdown != score`，两条既有集成测试红（`test_repo_router_v2_meta.py:248`/`:462`），前端 `console.warn` 刷屏且合计行显示的数不等于徽标百分比。
**Why it happens:** 直觉上「最终分数」就该放在 `score` 里。
**How to avoid:** 新增 `score_ranked` 旁路字段（默认 `None`）；`score`/`breakdown` 严格保持 Stage 0 六信号口径。前端排序用 `score_ranked ?? score`，合计行仍用 `score`。
**Warning signs:** 运行 `cd server && uv run pytest tests/codegraph/test_repo_router_v2_meta.py -q` 出现 fsum 断言失败。

### Pitfall 2: 分组做完了但 global 组恒空（OQ-1 的具体后果）

**What goes wrong:** 编排/chat 入口把 `repository_ids` 当**硬过滤**传给 `route()`，候选集从一开始就只有项目内仓 → 分组后 `global` 组永远 0 条 → ROUTE-01/02 上线即无效，且看不出来（UI 只是少一个分区）。
**Why it happens:** `_resolve_repository_ids`（`repo_router_adapter.py:65`）与 `repository_relevance.py:196` 的空间过滤是既有行为，语义上是"候选范围"而非"分组依据"。
**How to avoid:** 先裁决 OQ-1。若选「放开过滤」：把项目关联仓从 `repository_ids` 移到「分组依据」参数，`repository_ids=None`（全库召回）；同时给 Stage 0 的 `STAGE0_NODE_K` / `STAGE0_REPO_K` 留意（全库召回会改变候选构成 → 影响 8 个消费方的实际结果，需回归测试）。
**Warning signs:** 集成测试里构造「正确仓在项目外」的场景，断言 global 组非空——若恒空即命中本坑。

### Pitfall 3: `applyManualOverride` 丢字段 → 用户改一次勾选，降级提示消失

**What goes wrong:** `web/src/stores/routing.ts:74-80` 重建 `RoutingDecisionData` 时只保留 5 个键；`degraded` / `degrade_reason` / `router_version` / `block_order` 全丢。
**Why it happens:** 后端 override 接口（`chat/views.py:2717`）只返回 `{trace_id, original_trace_id, candidates, triggered_by}`，store 从 `original` 里补 `query`/`threshold` 时漏了新字段。
**How to avoid:** 同时改两处——后端 override 响应回传 `router_version`/`degraded`/`degrade_reason`（新 trace 行本身应继承这些值），前端从 `original` 兜底继承。写组件测试：override 后降级横幅仍在。
**Warning signs:** 手动勾选一次后横幅消失（UAT 必查项）。

### Pitfall 4: 前端 re-sort 覆盖后端排序

**What goes wrong:** `RoutingDecisionPanel.vue:53` `[...candidates].sort((a,b) => b.score - a.score)` 会把后端的分组内 `S_ranked` 排序与 block 置顶全部还原成「按 Stage 0 分数全序」——分组分区看起来做了，实际顺序不是设计的顺序。
**Why it happens:** 这个 re-sort 是 105-06 之前就有的防御性代码（当时 LLM 排列顺序也被它覆盖，无人察觉）。
**How to avoid:** 改为「按 `block_order` 分区 → 区内按 `score_ranked ?? score` 降序」；写组件测试断言渲染顺序等于后端给的顺序。
**Warning signs:** 后端 block_order 是 `["global","in_project"]` 但面板仍先渲染本项目组。

### Pitfall 5: 参数塞进 `weight_config.constants` → 污染 golden / 回放 / 版本语义

**What goes wrong:** `_validate_constants`（`repo_router_config.py:194`）的白名单 = `set(DEFAULT_WEIGHT_CONFIG["constants"])`；加 `alpha`/`k`/`delta` 后它们会进 `snapshot["weight_config"]["constants"]`，而 106-07 回放与 golden fixture 的 `constants` 形状有比对；`weight_set_version` 的语义（"打分口径版本"）也被稀释。
**Why it happens:** "都是路由参数"的直觉归并。
**How to avoid:** 走 `friday/settings.py` + env（与 `REPO_ROUTER_STAGE1_*` / `REPO_ROUTER_CONF_THETA_*` 完全同轨，读取时机为调用时——见 `_stage1_conf` / `_conf_thresholds` 两个既成范式）。若确认 delta 需运维热改，单开一个 `SettingKeys.REPO_ROUTER_PRESENTATION`（独立键，不动 weight_config）。
**Warning signs:** `uv run pytest tests/codegraph/test_repo_router_golden.py` 或 `test_repo_router_replay.py` 出现 constants 形状不匹配。

### Pitfall 6: 澄清超时出口用 `transition("clarified")` 但 `clarify` stage 会立刻再判"需澄清"

**What goes wrong:** 出口把 stage 推到 `research`；但如果之后有任何回到 `clarify` 的路径（`merge` 的 `validation_failed_reclarify` → `clarify`，`builtin_processes.py:310`），`_h_clarify` 会重跑 `default_needs_clarification`——若 routing 仍无 high/medium 候选，又会建一轮新澄清并再次挂起。
**Why it happens:** 出口只改了状态，没在 `stage_state` 里留「已按未澄清假设放行」的标记。
**How to avoid:** 出口时在 `stage_state` 写标记（如 `stage_state["clarification_exit"] = {"reason": ..., "at": ..., "assumptions": [...]}`），并让 policy 或 `_h_clarify` 读取该标记短路（**注意**：改 policy 属 `clarify_adapter` 的判定层，DEPTH 冻结只冻 prompt/schema，policy 可改）。同时 `_MAX_CLARIFY_ROUNDS=6` 已提供第二道兜底。
**Warning signs:** 集成测试「超时放行 → merge 校验失败回退 clarify → 再次 waiting_clarification」复现无限循环。

### Pitfall 7: 澄清超时的"起算时间"取错

**What goes wrong:** 用 `ConvergenceSession.updated_at` 起算 → 任何无关的 `transition` 都会刷新它（`_apply_transition_sync` 每次都写 `updated_at=timezone.now()`），超时永不到达。
**Why it happens:** `updated_at` 看起来是最自然的"最后活动时间"。
**How to avoid:** 用 **pending 轮的 `Clarification.created_at`**（`auto_now_add`，不会被刷新）起算。多轮场景取「最早未答轮」的 `created_at`（`plan_research.py:387` 已有 `order_by("round_no","created_at")` 取 pending 轮的范式）。
**Warning signs:** 手工把某会话的时间戳回拨后扫描仍不命中。

### Pitfall 8: 事件常量加了但守护测试红

**What goes wrong:** 新增 `EVENT_CLARIFICATION_TIMED_OUT` 常量却没加进 `ALL_EVENTS`（或加了但没有任何 emit 点真的产出它）→ taxonomy 守护测试的双向断言失败。
**Why it happens:** `ALL_EVENTS` 是「本 phase 编排实际产出的事件全集」，有**覆盖性反查**（每个成员至少被一个 emit 点产出）。
**How to avoid:** 常量 + `ALL_EVENTS` + emit 点 + 测试四者同提交。
**Warning signs:** `cd server && uv run pytest tests/delivery -q` 出现 event taxonomy 断言失败。

### Pitfall 9: 在 `atomic() + select_for_update` 块内调异步引擎

**What goes wrong:** `asyncio.run` / `sync_to_async` 在持锁事务内执行 → 长事务持锁、Postgres 连接被跨线程复用、`SynchronousOnlyOperation`。
**Why it happens:** 顺手在 for 循环里就 await 了。
**How to avoid:** 逐字照抄 `check_timeouts.py` 的两段式（事务内收集 → 事务外 `asyncio.run`）。
**Warning signs:** 本地跑 command 报 `SynchronousOnlyOperation` 或事务超时。

### Pitfall 10: 降级原因把上游 400 body 原文透给用户

**What goes wrong:** 上游网关 400 的 body 常含请求回显（可能带 prompt 片段甚至 header 残留）；直接展示 = 信息泄漏。
**Why it happens:** "把 error 展示出来才好排障"。
**How to avoid:** 前端只拿 6 值受控枚举；脱敏后的原文只进事件 payload / 系统日志（`redact_secrets_in_text`），排障时从下钻页看。
**Warning signs:** 前端出现 `sk-` 或 `Bearer ` 字样、或 degrade_reason 字段出现变长文本。

### Pitfall 11: `_send_clarify_card` 的 4 个静默 return 只补了 except 分支

**What goes wrong:** 只在 `except` 里加 `delivery_failed` 留痕，但生产里最常见的失败是 `space is None` / `project is None` / `not chat_id`（配置缺失，不抛异常）→ 依旧静默挂起。
**Why it happens:** 直觉认为「失败 = 抛异常」。
**How to avoid:** 逐条 return 都记 reason（`no_questions` / `no_space` / `no_project` / `no_chat_id` / `send_failed`）并 emit `clarification.delivery_failed`。
**Warning signs:** 测试只覆盖 `send_card` 抛异常一条路径。

---

## Code Examples

### 分组标注 + block ranking（纯函数，新模块）

```python
# server/codegraph/services/repo_router_ranking.py（新建，零 Django import）
from __future__ import annotations

GROUP_IN_PROJECT = "in_project"
GROUP_GLOBAL = "global"
TRUST_TRUSTED = "trusted"
TRUST_NEEDS_CONFIRMATION = "needs_confirmation"


def annotate_groups(
    repo_ids: list[str],
    *,
    project_repo_ids: frozenset[str] | None,
) -> dict[str, tuple[str, str]]:
    """归属标注。``project_repo_ids is None`` = 调用方无项目上下文 → 全部 global。

    绝不返回任何分数偏移——组别只进独立字段（CONTEXT / ROUTING-RANKING §5.1）。
    """
    if project_repo_ids is None:
        return {rid: (GROUP_GLOBAL, TRUST_NEEDS_CONFIRMATION) for rid in repo_ids}
    return {
        rid: (
            (GROUP_IN_PROJECT, TRUST_TRUSTED)
            if rid in project_repo_ids
            else (GROUP_GLOBAL, TRUST_NEEDS_CONFIRMATION)
        )
        for rid in repo_ids
    }
```

### rank-swap budget 裁剪（ROUTING-RANKING §1.3b）

```python
def clamp_llm_permutation(
    llm_order: list[str], stage0_order: list[str], *, k: int
) -> tuple[list[str], int]:
    """把 LLM 排列裁剪回 |rank_llm - rank_stage0| <= k，返回 (裁剪后排列, 违规数)。

    白名单已由调用方保证（``by_id`` 过滤 + 去重）——本函数只管位移预算。
    违规项被移回其 stage0 位置附近；返回违规数供观测记录（约束违反必须留痕）。
    """
    stage0_rank = {rid: i for i, rid in enumerate(stage0_order)}
    violations = 0
    clamped: list[str] = []
    for target_rank, rid in enumerate(llm_order):
        base = stage0_rank.get(rid)
        if base is None:
            continue  # 不在 Stage 0 窗口内（防御；调用方已过滤）
        if abs(target_rank - base) <= k:
            clamped.append(rid)
        else:
            violations += 1
            clamped.append(rid)  # 先收集，下面统一按裁剪后的允许区间重排
    if violations:
        clamped.sort(key=lambda r: (min(max(llm_order.index(r), stage0_rank[r] - k),
                                        stage0_rank[r] + k), stage0_rank[r]))
    return clamped, violations
```
> 上面的 `sort` 只是一种实现；planner 可选更简单的语义（"越界项直接放回 stage0 位置"）。**关键是把违规数记进 trace 并写单元测试**，而不是具体裁剪算法——ROUTING-RANKING §1.3b 要的是"损害有硬上界且可测"。

### 凸组合（`S_llm` 与 N=1 短路）

```python
def blend_ranked_scores(
    stage0_scores: dict[str, float], llm_order: list[str], *, alpha: float
) -> dict[str, float]:
    """S_ranked = (1-α)·S_final + α·S_llm，S_llm = 1 - (rank_llm-1)/(N-1)。

    N == 1 → 无重排空间，直接返回 S_final（防除零）。
    alpha == 0（Stage 1 降级）→ 恒等返回 S_final。
    """
    n = len(llm_order)
    if n <= 1 or alpha <= 0.0:
        return dict(stage0_scores)
    out: dict[str, float] = dict(stage0_scores)
    for idx, rid in enumerate(llm_order):
        if rid not in stage0_scores:
            continue
        s_llm = 1.0 - idx / (n - 1)
        out[rid] = (1.0 - alpha) * stage0_scores[rid] + alpha * s_llm
    return out
```

### 澄清超时出口（幂等 + 归因 + 事件）

```python
# server/delivery/management/commands/expire_pending_clarifications.py（新建，骨架）
async def _exit_one(session, pending_round, *, action: str, waited_seconds: float) -> None:
    from delivery.services import ConvergenceSessionService
    from delivery.services.convergence_session_service import ConcurrentTransitionError
    from delivery.services.event_taxonomy import EVENT_CLARIFICATION_TIMED_OUT

    svc = ConvergenceSessionService()
    initiated_by = getattr(session, "initiated_by_user_id", "") or "system"
    stage_state = dict(session.stage_state or {})
    stage_state["clarification_exit"] = {
        "clarification_id": str(pending_round["id"]),
        "action": action,                     # resumed_with_assumptions | failed_no_answer
        "waited_seconds": round(waited_seconds, 1),
        "unclarified_points": [...],          # 供产出显式标注「哪些点未澄清」
    }
    try:
        if action == "resumed_with_assumptions":
            await svc.transition(session, "clarified", stage_state=stage_state)
        else:
            await svc.transition(session, "fail", error={
                "stage": "clarify", "reason": "clarification_timeout_no_answer",
            })
    except ConcurrentTransitionError:
        logger.info("clarification_timeout_exit_noop_concurrent",
                    category="sampling", component="delivery",
                    session_id=str(session.id), initiated_by_user_id=initiated_by)
        return                                 # 幂等：已被并发扫描/真实作答推进
    await svc._emit_event(EVENT_CLARIFICATION_TIMED_OUT, session, {
        "clarification_id": str(pending_round["id"]),
        "exit_action": action,
        "waited_seconds": round(waited_seconds, 1),
    })
    logger.info("clarification_timeout_exit", category="caller", component="delivery",
                session_id=str(session.id), initiated_by_user_id=initiated_by,
                exit_action=action, waited_seconds=round(waited_seconds, 1))
```

### apscheduler job 注册（照抄 `check_workflow_event_timeouts_job` 范式）

```python
# server/agents/management/commands/runapscheduler.py 增量
@_with_scheduler_log_context
def expire_pending_clarifications_job():
    """Job wrapper：扫描过期 pending 澄清并走出口（RELY-02）。

    与 ``check_workflow_event_timeouts_job`` 同 ``call_command`` 模式（命令内部
    自管事务 + 事务外 asyncio.run 重驱）。归因 system（scheduler 上下文），
    被推进会话的 ``initiated_by_user_id`` 由命令内逐条携带。命令异常被本
    wrapper 吞掉记日志，绝不打断 scheduler 主循环。
    """
    from django.core.management import call_command

    log = logger.bind(job="expire_pending_clarifications")
    log.info("job_start")
    try:
        call_command("expire_pending_clarifications")
        log.info("job_complete")
    except Exception as e:
        log.exception("job_error", error=str(e))

# ... 在 handle() 内：
scheduler.add_job(
    expire_pending_clarifications_job,
    trigger=IntervalTrigger(
        seconds=getattr(settings, "CLARIFICATION_EXPIRY_CHECK_INTERVAL_SECONDS", 600)
    ),
    id="expire_pending_clarifications",
    name="Expire pending clarifications past timeout (resume with assumptions / fail)",
    max_instances=1,
    replace_existing=True,
)
logger.info("job_registered", job="expire_pending_clarifications", schedule="every ~10min")
```
> 频率建议 10 分钟（超时默认 24h，分钟级精度足够；避免与 `sample_gauges`(45s) / `evaluate_system_alerts`(60s) 争 SQLite 写锁）。

### 降级原因分类

```python
_DEGRADE_REASONS = frozenset({
    "timeout", "upstream_error", "provider_missing", "unparsable", "no_node_index", "unknown",
})

def classify_degrade_reason(skipped_reason: str, exc: BaseException | None = None) -> str:
    """把内部 skipped_reason / 异常映射为 6 值受控枚举（基数可控，可做指标维度）。"""
    if skipped_reason in ("provider_missing", "no_model_configured"):
        return "provider_missing"
    if skipped_reason in ("unparsable_llm_output", "no_valid_candidates_in_llm_output"):
        return "unparsable"
    if exc is not None:
        name = type(exc).__name__
        if "Timeout" in name:
            return "timeout"
        if any(t in name for t in ("Connect", "APIStatus", "APIError", "HTTPStatus", "BadRequest")):
            return "upstream_error"
    return "unknown"
```

---

## State of the Art

| 旧做法（本仓 v0.18 及之前） | 现做法 | 何时变的 | 影响 |
|---------------------------|--------|---------|------|
| `confidence` 由 LLM 断言 | 确定性 margin 规则（`derive_confidence` + `apply_llm_adjustment` 只降不升） | Phase 105（v0.19.0） | 本 phase **不得**让 `S_ranked` 反向影响 confidence |
| `score = min(c["score"], 1.0)` 截断 | 归一化分按构造 ∈[0,1]，无截断 | Phase 105 | 分数可直接做 delta 比较（跨组可比性的前提） |
| 三信号乘性加成 | 六信号加性 + pivoted size normalization，`Σbreakdown == score` | Phase 106（`weight_set_version = phase106-v2`） | 分组呈现的"一套分数"前提已成立；口径**本 phase 冻结** |
| `WEIGHT_SET_VERSION` 写死字面量 | 取自 `DEFAULT_WEIGHT_CONFIG["weight_set_version"]` 单一来源 + golden 门禁字面绑定断言 | Phase 106-08 | 本 phase 若不改打分口径就**不要** bump 版本（bump 必须与 baseline 重建同提交） |
| Stage 1 用 langchain 默认 `max_retries=2` | `max_retries=0` + 显式 `asyncio.wait_for` | Phase 105-05 | RELY-05 的"1 次重试"要在**我们的**循环里做，不是重新打开 langchain 重试 |
| Stage 1 输出含浮点分数 | 只输出排列（消费侧过滤 `score` 键） | Phase 105-05（`PROMPT_TEMPLATE_VERSION = "stage1-permutation-v1"`） | 凸组合的 `S_llm` 必须由**排名**导出，不能读 LLM 分数 |
| golden baseline 为 `phase105-v1`（Top-1 13/14） | `phase106-v2`，Top-1 14/14、Recall@5 0.9642857、误自动选中率 0.0 | Phase 106-08 → 106-04(BL-01) | 本 phase 的回归比较锚是 `phase106-v2`；离线 harness 全量 0.18s |
| 澄清单轮硬限（`aexists` 短路） | 多轮 HITL + `_MAX_CLARIFY_ROUNDS=6` 兜底 | Phase 91（v0.16.1） | 轮数上界救不了"无人应答"——本 phase 补的是时间维度出口 |

**Deprecated / 已废弃**：
- `create_clarification` / `answer_clarification`（legacy 单题 API）已删除；一律走 `create_round` / `answer_round`（`clarify_adapter.py` docstring 明确记录）。
- `_stage0_candidates(repo_meta=None)` 的 legacy 三信号路径仍在（兼容直调方与 replay），但生产 `route()` 已恒走六信号；本 phase 不要在这条兼容路径上加分组逻辑（会漏）。

---

## Assumptions Log

| # | 假设 | 出现章节 | 若错的风险 |
|---|------|---------|-----------|
| A1 | 「本项目关联仓」应取 `Space.repositories` 而非 `initiatives.RepoAssociation(status=verified)` | §1 项目↔仓关联 | 两者语义不同：Space 是"空间下的仓"（宽），verified 关联是"项目已确认要改的仓"（窄）。选错会让 in_project 组要么过宽（几乎所有候选都在组内，分组无信息量）要么过窄（大量真相关仓被标 needs_confirmation，用户被无谓打扰）。**建议 planner 在 discuss/plan 时向用户确认，或按入口分别取**（编排入口有 work_item → 优先 verified 关联，回退 Space；chat 入口只有 space_id → 取 Space） |
| A2 | `delta` / `α` / `K` 走 `settings + env` 而非 SystemSetting | §Standard Stack Alternatives、Pitfall 5 | 若运维需要不发版调 delta（跨组协作频率随组织变化），settings 就不够；届时需补一个独立 SettingKeys 键 |
| A3 | 澄清超时出口用现有 6 值 status（`transition("clarified")` / `"fail"`）而非新增枚举值 | §Alternatives、§3 | 若产品要求「超时放行」在列表/看板上与「正常运行」视觉区分，`running` 就不够表达，需要新状态或额外标记字段供投影层读取（`workflows/lifecycle_projection.py` 有 status 投影） |
| A4 | 新增 `clarification.timed_out` / `clarification.delivery_failed` 两个事件名 | §7 | 若 Phase 110 已在别处规划了不同事件命名，会造成 taxonomy 二次改名。命名前建议 grep v0.20 蓝图 DESIGN.md 是否已占用 `clarification.*` 命名空间 |
| A5 | Stage 1 per-call 超时默认应从 90s 下调（以给重试留余量） | §5(a) | 下调会让原本 70–89s 能成功的调用变成降级（`degraded=True` 用户可见）。**必须先做 O-6 实测再定这个数**，顺序不能颠倒 |
| A6 | 降级原因用 6 值枚举，前端不展示原始异常文本 | §6 | 若排障方（开发者）强烈需要在面板上直接看到原文，需要一个仅 superuser 可见的展开区——那是额外权限面 |
| A7 | `RepositoryRoutingTrace` 加 `degrade_reason` 列优于塞 JSON | §2 第 2 条 | 加列需迁移；若团队偏好零迁移，可把它塞进 `candidates` 的每个元素（冗余但无迁移）——代价是无法 SQL 聚合"降级原因分布" |
| A8 | `check_timeouts` 的 `select_for_update(skip_locked=True)` 范式在 `ConvergenceSession` 上同样适用 | §Pattern 2 | `ConvergenceSession` 无 `is_active` 类字段，锁定条件是 `status='waiting_clarification'`；Postgres 下正常，SQLite 下 no-op（与既有 job 同等风险，可接受） |
| A9 | 生产已存在的卡死会话可以被首次上线的 job 直接推进 | §Runtime State Inventory | 若那些会话已被人工绕道处理过（CONTEXT 记录 agent 绕道 `create_coding_plan` 徒手编方案），批量推进可能产生重复产出。**推荐 `--dry-run` 先看** |

---

## Open Questions

### OQ-1（🔴 阻塞级，planner 必须先裁决）：候选范围过滤 vs 分组呈现

- **我们知道的**：`RepoRouterV2.route(repository_ids=[...])` 把 `repository_ids` 作为 Qdrant `filters`（`_stage0_node_search:387-389`）——是**硬过滤**。编排入口（`repo_router_adapter._resolve_repository_ids`）与 chat 入口（`repository_relevance.py:196`）都会传项目/空间内仓。ROUTING-RANKING §8 第 7 步把「分层召回与分组呈现」的收益明确写成「修复 Space 硬过滤漏召回」，且 §7.1 记录 `study-user-status` 曾被 Space 硬过滤完全挡在门外。
- **不清楚的**：CONTEXT 只锁了「归属判定 + 分组呈现 + delta 置顶」，**没有明确授权放开候选范围过滤**。而不放开的话，global 组恒空、ROUTE-01/02 上线即无效果（Pitfall 2）。
- **推荐**：把项目关联仓从「过滤条件」改为「分组依据」，`route()` 新增独立参数（如 `project_repo_ids: list[str] | None`）与 `repository_ids` 正交；编排/chat 两个入口改为传 `project_repo_ids=项目仓` + `repository_ids=None`。**这是本 phase 唯一有实际回归风险的改动**（候选构成变化会影响 8 个消费方的实际返回内容），必须：(a) 在 PLAN 里作为独立 task 并写明；(b) 只改 #1/#2 两个入口，#3–#8 行为逐字不变；(c) 用既有 `tests/services/test_repo_router_adapter.py` / `tests/agents/test_repository_relevance_tool.py` 做回归基线。若用户/planner 判断风险过高，退路是「保留过滤 + 分组仅标注 trust」，但需在 VERIFICATION 里如实记录 ROUTE-01 的 global 组在当前范围语义下为空。

### OQ-2：工作流 60min 订阅超时 vs 澄清 24h 超时的不一致

- **我们知道的**：`plan_research.py:400` 建 `WorkflowEventSubscription(timeout_at=now+60min, timeout_action="fail")`；`check_timeouts` 到期把 NodeExecution/WorkflowExecution 标 `TIMEOUT`，但 `ConvergenceSession` 不动。CONTEXT 的澄清超时默认 24h。
- **不清楚的**：工作流入口的会话在第 60 分钟就已经"工作流侧失败"了，再等到 24h 才走会话出口，中间 23 小时是个矛盾态（工作流 TIMEOUT + 会话 waiting_clarification）。
- **推荐**：两条之一——(a) 把订阅 `timeout_at` 对齐澄清超时（改成 `now + CLARIFICATION_TIMEOUT_HOURS`），让工作流与会话同时到期，出口动作由澄清 job 统一驱动；(b) 保留 60min 但把 `timeout_action` 从 `fail` 改为让节点走"带假设继续"的路径。(a) 改动更小且语义一致，**推荐 (a)**，但要注意 60min→24h 会让飞书群卡的有效期变长（用户体验上是好事）。

### OQ-3：chat 单题澄清（路径 C）是否纳入超时出口

- **我们知道的**：`ClarificationAnswerView` 走 `chat.ConversationIntentTrace` + LangGraph interrupt 恢复，**完全不碰 `delivery.Clarification`**；已有 `cleanup_waiting_clarification_errors` 命令处理脏数据。
- **不清楚的**：RELY-02 的表述是「技术方案编排不会无人应答地永久停在澄清阶段」——路径 C 属 chat agent 的协商卡，不是方案编排的 clarify stage。
- **推荐**：本 phase 出口只做 `delivery.Clarification`（路径 A/B）；路径 C 只在观测上纳入（记一个 gauge/日志"未答协商卡数"），出口留给后续。理由：LangGraph checkpoint 的恢复语义与 stage graph 完全不同，混做会让 PLAN 膨胀且风险不可控。**需在 VERIFICATION 里如实标注该边界**。

### OQ-4：「未澄清假设」的产出标注落在哪一层

- **我们知道的**：CONTEXT 要求「在产出中显式标注哪些点未澄清」。产出正文由 `architect_merge_adapter` / `merged_plan` / `render_merged_plan_markdown` 生成，而 DEPTH 向改动（`process_runtime` 的 prompt/schema）被冻结（v0.20.0 并行改同批文件）。
- **不清楚的**：在不改 prompt/schema 的前提下，标注放在哪——`stage_state.clarification_exit`（数据层，前端/文档渲染时读）？还是 `ArtifactVersion.content` 的某个既有可选键？
- **推荐**：只写 `stage_state.clarification_exit.unclarified_points`（数据层，零 schema 变更），并在 `EVENT_CLARIFICATION_TIMED_OUT` payload 里携带同一份。渲染侧展示留给 Phase 109/110 或 v0.20.0（它们本来就要动产出渲染）。这样既满足"标注可查"，又不碰冻结文件。**planner 需与用户确认这个降级解释是否可接受**。

### OQ-5：α=0.35 的取值是否要在本 phase 校准

- **我们知道的**：ROUTING-RANKING §1.3c 建议在 golden 上扫 α ∈ {0, 0.2, 0.35, 0.5}；但离线 harness (`score_case`) **不跑 Stage 1**，α 在离线口径下恒为 0 → **golden set 无法校准 α**。
- **不清楚的**：α 的取值只能靠生产 A/B 或人工抽检。
- **推荐**：本 phase 取 CONTEXT 锁定的 0.35 并外置；在 `107-MEASUREMENTS.md` 里如实记录「α 未经数据校准，因离线 harness 结构上不含 Stage 1」，作为已知局限。**不要**为了校准 α 把凸组合塞进离线 harness（会污染 baseline，Pitfall 5 同源）。

---

## Environment Availability

| 依赖 | 被谁需要 | 可用 | 版本 | 回退 |
|------|---------|------|------|------|
| Python 3.14 + `uv` | 后端全部改动与测试 | ✓ | 见 `server/.python-version` | — |
| Node + `pnpm` | 前端面板改动与 vitest | ✓ | 见 `web/.nvmrc` / `pnpm@10.28.0` | — |
| `apscheduler` / `django-apscheduler` | 澄清超时 job | ✓（已装，21 个 job 在跑） | `django-apscheduler>=0.7.0` | — |
| PostgreSQL | `select_for_update(skip_locked=True)` 真实行锁；`percentile_cont` 分位查询 | ⚠️ 生产有，本地 dev 常用 SQLite | 生产 `postgres:17-alpine` | SQLite：`select_for_update` 退化 no-op（`max_instances=1` + transition CAS 兜底）；分位在 Python 侧算或跳过（LOGGING-SPEC §4.3 已允许 dev 降级） |
| Qdrant | Stage 0 检索（回归测试用替身） | 生产有；测试用内存/替身 | `qdrant/qdrant` | 单测全部用替身，无需真实 Qdrant |
| LLM provider | Stage 1 真实调用与 O-6 实测 | ⚠️ 单测不需要（`respx`/替身）；**O-6 实测需要生产环境数据** | — | O-6 无生产数据时：按 105/106 的"数据环境标注纪律"如实记 deferred，并在文档里写明用何命令在有数据环境复测 |
| 飞书 IM 凭证 | 澄清发卡失败路径的真实验证 | ⚠️ 单测用替身 | — | 送达失败路径全部可用 mock 覆盖（4 个静默 return + except），无需真实凭证 |

**Missing dependencies with no fallback:** 无。
**Missing dependencies with fallback:** 生产 Postgres（分位查询与行锁）、LLM provider 与飞书凭证（真实链路验证）——三者都有测试替身/文档 deferred 的既有先例。

---

## Validation Architecture

### Test Framework

| 属性 | 值 |
|------|-----|
| Framework | pytest 9.x（`server/`，`uv` 管理，含 `pytest-asyncio` / `pytest-django` / `pytest-socket` / `respx` / `factory-boy`）+ vitest 4（`web/`，`happy-dom`） |
| Config file | `server/pyproject.toml`（`[tool.pytest.ini_options]`）；前端 vitest 由 `web/vite.config.ts` 配置 |
| Quick run command | `cd server && uv run pytest tests/codegraph tests/delivery -x -q -k "router or clarif"` |
| Full suite command | `cd server && uv run pytest -q`；前端改动另跑 `cd web && pnpm vitest run src/components/chat/__tests__/RoutingDecisionPanel.test.ts src/stores/__tests__/routing.test.ts` |
| 现有基线 | `cd server && uv run pytest tests/codegraph tests/delivery tests/services/test_repo_router_adapter.py -q` → **839 passed / 20 skipped**（106-08 收官值）；`RoutingDecisionPanel.test.ts` → 12 passed |

### Phase Requirements → Test Map

| Req ID | 行为 | Test Type | Automated Command | File Exists? |
|--------|------|-----------|-------------------|-------------|
| ROUTE-01 | 分组标注纯函数：有项目上下文分两组、无项目上下文全 global 且不抛 | unit | `cd server && uv run pytest tests/codegraph/test_repo_router_ranking.py -x -q` | ❌ Wave 0（新建） |
| ROUTE-01 | block_order delta 迟滞：差值恰在阈值下不翻转 / 上翻转 / 重复调用恒等（幂等） | unit | 同上（`-k block_order`） | ❌ Wave 0 |
| ROUTE-01 | golden cross_group 机制断言：gk-008/gk-009 的 delta >= 默认 delta 且 global 组被置顶 | unit（离线零网络） | `cd server && uv run pytest tests/codegraph/test_repo_router_golden.py -x -q -k cross_group` | ✅ 既有文件，补 2 用例 |
| ROUTE-01/02 | route() 输出携带 group/trust/cross_group_note 且 8 消费方零改动仍绿 | integration（回归） | `cd server && uv run pytest tests/codegraph tests/services/test_repo_router_adapter.py tests/agents/test_repository_relevance_tool.py tests/initiatives/test_repo_association_service.py -q` | ✅ 既有测试 |
| ROUTE-02 | 无项目上下文入口（MCP / REST）返回全 global 且不报错 | integration | `cd server && uv run pytest tests/codegraph/test_repo_router_v2_meta.py -x -q -k no_project_context` | ✅ 既有文件，补用例 |
| ROUTE-01/02 | 前端分区渲染：区顺序等于后端 block_order、区内按 score_ranked 排序、全局组默认折叠、跨组 badge 存在 | component unit | `cd web && pnpm vitest run src/components/chat/__tests__/RoutingDecisionPanel.test.ts` | ✅ 既有文件（12 passed），补 4+ 用例 |
| RELY-03 | 降级原因分类函数：6 个分支全覆盖 + 未知回退 unknown | unit | `cd server && uv run pytest tests/codegraph/test_repo_router_v2_degraded.py -x -q -k degrade_reason` | ✅ 既有文件，补用例 |
| RELY-03 | 降级原因经 `redact_secrets_in_text`：注入含 `sk-ant-` 的异常，断言入库/输出无明文 | unit（安全） | 同上（`-k redact`） | ✅ 既有文件，补用例 |
| RELY-03 | 前端降级横幅：`degraded=true` 渲染醒目提示 + confidence 徽标降级 variant；`degraded=false` 不渲染 | component unit | `cd web && pnpm vitest run src/components/chat/__tests__/RoutingDecisionPanel.test.ts` | ✅ 既有文件，补用例 |
| RELY-03 | override 后不丢降级字段（Pitfall 3） | store unit | `cd web && pnpm vitest run src/stores/__tests__/routing.test.ts` | ✅ 既有文件，补用例 |
| RELY-05 | Stage 1 首调超时后重试 1 次并成功；两次都失败即降级（`degraded=True`, reason=timeout） | unit（替身计数） | `cd server && uv run pytest tests/codegraph/test_repo_router_v2_degraded.py -x -q -k retry` | ✅ 既有文件，补用例 |
| RELY-05 | 总预算耗尽即刻降级：不发第二次调用（断言调用次数 == 1） | unit | 同上（`-k budget`） | ✅ 既有文件，补用例 |
| RELY-05 | K=3 rank-swap 裁剪：越界排列被裁回预算内 + 违规数被记录；LLM 编造 repo_id 被丢弃 | unit | `cd server && uv run pytest tests/codegraph/test_repo_router_ranking.py -x -q -k clamp` | ❌ Wave 0 |
| RELY-05 | 凸组合：α=0 恒等返回 S_final；N==1 不除零；`Σbreakdown == score` 仍成立（`score_ranked` 不覆盖 `score`） | unit + integration | `cd server && uv run pytest tests/codegraph/test_repo_router_ranking.py tests/codegraph/test_repo_router_v2_meta.py -x -q` | ❌/✅ 混合 |
| RELY-05 | golden baseline 不因本 phase 改动而变（`phase106-v2` 门禁三规则继续绿） | golden gate | `cd server && uv run pytest tests/codegraph/test_repo_router_golden.py -x -q` | ✅ 既有（9 passed, 0.18s） |
| RELY-02 | 超时扫描命中过期 pending 并按默认动作推进（`clarified` → `current_stage=research`），`stage_state.clarification_exit` 写入 | integration | `cd server && uv run pytest tests/delivery/test_expire_pending_clarifications.py -x -q` | ❌ Wave 0（新建） |
| RELY-02 | 幂等：连续跑两次扫描只推进一次、只 emit 一次；并发 CAS 冲突被当 no-op | integration | 同上（`-k idempotent`） | ❌ Wave 0 |
| RELY-02 | 未到期不动、已答不动、终态不动 | integration | 同上（`-k not_expired or answered or terminal`） | ❌ Wave 0 |
| RELY-02 | 起算时间用 pending 轮 `created_at`（Pitfall 7）：刷新 `session.updated_at` 后仍命中 | integration | 同上（`-k started_at`） | ❌ Wave 0 |
| RELY-02 | 送达失败 5 条路径（`no_questions`/`no_space`/`no_project`/`no_chat_id`/`send_failed`）全部留痕 + emit `clarification.delivery_failed` | unit | `cd server && uv run pytest tests/workflows/test_plan_research_node.py -x -q -k delivery` | ✅ 既有文件，补用例 |
| RELY-02 | 事件 taxonomy 守护：新常量 ∈ `ALL_EVENTS` 且有 emit 点产出 | unit | `cd server && uv run pytest tests/delivery -q -k taxonomy` | ✅ 既有守护测试 |
| O-6 | 延迟查询命令产出分位且输出无敏感串 | unit + doc check | `cd server && uv run pytest tests/codegraph/test_measure_stage1_latency.py -x -q` + `test -f .planning/phases/107-layered-presentation/107-MEASUREMENTS.md` | ❌ Wave 0（新建） |

### Sampling Rate

- **Per task commit:** `cd server && uv run pytest tests/codegraph tests/delivery -x -q -k "router or clarif"`（前端 task 用 `cd web && pnpm vitest run <spec>`）
- **Per wave merge:** `cd server && uv run pytest tests/codegraph tests/delivery tests/services/test_repo_router_adapter.py tests/agents/test_repository_relevance_tool.py tests/workflows/test_plan_research_node.py -q`（比对 839 passed 基线）+ `cd web && pnpm vitest run src/components/chat src/stores`
- **Phase gate:** `cd server && uv run pytest -q` 全绿 + `cd web && pnpm vitest run` 全绿 + `ruff check` / `ruff format --check`（改动文件）+ `cd web && pnpm exec vue-tsc --noEmit`，然后才 `/gsd-verify-work`
- **Max feedback latency:** < 60s（quick run 实测量级 ~30s；golden 门禁 0.18s）

### Wave 0 Gaps

- [ ] `server/tests/codegraph/test_repo_router_ranking.py` — 覆盖 ROUTE-01（分组/block_order/迟滞/幂等）与 RELY-05（K 裁剪/凸组合/N==1）
- [ ] `server/tests/delivery/test_expire_pending_clarifications.py` — 覆盖 RELY-02（出口/幂等/起算时间/边界）
- [ ] `server/tests/codegraph/test_measure_stage1_latency.py` — 覆盖 O-6 命令
- [ ] 无框架安装需求：pytest / vitest / respx / factory-boy / pytest-socket 全部就位，新测试为纯增量

---

## Security Domain

（`security_enforcement: true`, `security_asvs_level: 1`, `security_block_on: high`）

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | 不新增认证面；新 endpoint 无（只有 management command + 既有 view 字段扩展） |
| V3 Session Management | no | 不碰 JWT/cookie 逻辑 |
| V4 Access Control | **yes** | `RepositoryRoutingTrace` 的跨用户/跨项目校验已在 `chat/views.py:2688`/`:2702` 实现（`routing_trace_manual_override_denied_cross_user` / `_cross_project`）——**新增 `degrade_reason` 字段不得绕过这两道校验**；分组信息暴露"项目外有哪些仓更匹配"，属既有 `Repository` 可见性范围内（候选本来就来自用户可见的索引），但若 OQ-1 放开候选范围，需确认「全库召回」不会把用户无权见的仓名暴露给他（⚠️ 见下方威胁 T-107-01） |
| V5 Input Validation | **yes** | 飞书回调 `form_value` 已由 `plan_clarify_callback` 按 `clarification_id` 权威取轮映射（防伪造，T-91-03）；新增 env 数值参数需 clamp（delta ∈ [0,1]、α ∈ [0,1]、K >= 0、超时 > 0），非法值回退默认（照 `repo_router_config` 的 fail-safe 范式） |
| V6 Cryptography | no | 不新增加解密；脱敏走既有 `redact_secrets_in_text` / `redact_for_ledger`，不自研正则 |
| V7 Error Handling & Logging | **yes** | 降级原因/异常文本入库前必须脱敏；高频循环禁 INFO（`route()` 已用 debug + `category="sampling"`）；观测 best-effort 不反噬 |
| V8 Data Protection | **yes** | 澄清正文进卡片/日志前已 `redact_secrets_in_text`（发卡侧既有）；"未澄清假设"标注写 `stage_state` 时同样要脱敏（需求原文可能含凭证） |

### Known Threat Patterns for Django/DRF + Vue

| Pattern | STRIDE | Standard Mitigation | 本 phase 具体落点 |
|---------|--------|---------------------|------------------|
| **T-107-01** 全库召回把用户无权访问的仓名/路径暴露到分组结果 | Information Disclosure | 候选集必须先过可见性过滤，再做分组 | 若 OQ-1 采纳"放开过滤"，必须确认 `repo_index_nodes` 的可见范围与用户权限一致（现状 `route()` 全库调用已存在于 MCP/REST 两个入口且已上线，说明团队既有判断是"仓名不敏感"——**planner 需显式确认这一前提并记入 PLAN**，不要默认它成立） |
| **T-107-02** 上游异常 body 原文透给前端 | Information Disclosure | 只透受控枚举；原文脱敏后仅入事件/系统日志 | §6 的 6 值枚举；`redact_secrets_in_text(str(exc))` 后才入 `degrade_reason` 相关 payload |
| **T-107-03** 超时扫描 job 被用于批量推进他人会话 | Elevation of Privilege | job 无外部触发面（只由 scheduler 调用）；management command 需要 shell 权限 | 不给 job 加 HTTP 触发端点。command 加 `--dry-run` / `--limit` 降低误操作面 |
| **T-107-04** 澄清超时出口被用于绕过 HITL（攻击者刻意不答以拿到"带假设"的方案） | Tampering / Repudiation | 出口必须留痕且产出显式标注 | `EVENT_CLARIFICATION_TIMED_OUT` + `stage_state.clarification_exit`（含 `unclarified_points`）；日志带 `initiated_by_user_id` |
| **T-107-05** `delta`/`α`/`K` 被设成极端值使排序退化 | Tampering | 参数 clamp + 非法回退默认 | 照 `repo_router_config._CONSTANT_RULES` 范式；若走 settings 则在 `_conf` 读取处 clamp（`_stage1_conf` 现无 clamp，**本 phase 新参数应加**） |
| **T-107-06** XSS via 降级原因 / cross_group_note 文案 | Tampering | Vue 模板插值自动转义，禁 `v-html` | `RoutingDecisionPanel.vue` 现无 `v-html`（实读确认）；新增文案继续用 `{{ }}` 插值；跨组 note 与降级文案**用前端常量而非后端自由文本**（受控枚举 → 前端 map，双重保险） |
| **T-107-07** 无界重试放大上游压力（DoS 自伤） | Denial of Service | 重试次数硬上界 1 + 共享总预算 deadline + 指数退避 | §5(a) 的 `for attempt in range(2)` + `budget_deadline`；`max_instances=1` 防 job 重叠 |
| **T-107-08** 扫描 job 单次处理无上界导致长事务/内存膨胀 | Denial of Service | 批量上限 + `skip_locked` | command 支持 `--limit`（默认如 200）；`select_for_update(skip_locked=True)` 让并发扫描互不阻塞 |

---

## Sources

### Primary（HIGH confidence — 本仓代码实读，全部核对行号）
- `server/codegraph/services/repo_router_v2.py`（1359 行）— Stage 0/1 全链、`RepoRouteCandidateV2`/`RepoRouteResultV2`、`_finalize_stage0`/`_stage0_only_result`/`_build_snapshot`/`_stage1_llm_reasoning`/`_stage1_cache_key`/`_fallback_v1`、`_STAGE1_DEFAULTS`/`_CONF_THETA_DEFAULTS`/`PROMPT_TEMPLATE_VERSION`
- `server/codegraph/services/repo_router_scoring.py`（717 行）— `DEFAULT_WEIGHT_CONFIG`（`weight_set_version = "phase106-v2"`）、`WEIGHT_SET_VERSION` 单一来源
- `server/codegraph/services/repo_router_config.py`（405 行）— `validate_weight_config` / `_CONSTANT_RULES` / `WEIGHT_GRID` / loader 三兄弟
- `server/codegraph/services/repo_router_eval.py` + `tests/codegraph/fixtures/repo_router_golden/*.json` — `score_case`、14 条 main case、`project_scope` 字段、`phase106-v2` baseline
- `server/services/process_runtime/repo_router_adapter.py` / `builtin_processes.py`（`_h_route` / `_routing_snapshot_payload` / `_TECHNICAL_PLAN_STAGES`）/ `clarify_adapter.py` / `answer_resume.py` / `ask_clarification.py`
- `server/delivery/services/convergence_session_service.py`（336 行）— `transition` CAS、`_fail`、`_emit_event`、`ConcurrentTransitionError`
- `server/delivery/services/event_taxonomy.py`（119 行）— `ALL_EVENTS` / `RESERVED_EVENTS` / `build_envelope`
- `server/delivery/models/convergence_session.py` / `convergence_session_event.py` / `clarification.py`
- `server/delivery/services/clarification_service.py` — `create_round` / `answer_round` / `ahas_pending`
- `server/agents/management/commands/runapscheduler.py`（815 行）— 21 个 job、`_with_scheduler_log_context`、flock 单实例
- `server/workflows/management/commands/check_timeouts.py`（177 行）— `select_for_update(skip_locked=True)` + 事务外重驱 + 有界重试范式
- `server/workflows/nodes/ai/plan_research.py:380-530` — `_send_clarify_card`（4 静默 return + except）、`WorkflowEventSubscription(60min, fail)`、`_resolve_initiator`
- `server/feishu/callbacks/plan_clarify_callback.py`（345 行）— 收答路径 A 全貌
- `server/chat/views.py:518-545`（detail payload）/`:2646-2750`（override）/`:2752-2939`（单题 answer）/`:2941-3120`（结构化 answer）/`:3123+`（skip）
- `server/chat/models.py:616-700` — `RepositoryRoutingTrace`（含 `router_version` 列、无 `degraded` 列）
- `server/agents/tools/repository_relevance.py`（435 行）+ `schemas/repository_relevance.py`
- `server/agents/call_source.py` — `CallSource.AUX_REPO_ROUTER`、contextvar 传播（chokepoint 说明）
- `server/interactions/models.py:240-300` — `ModelUsageRecord`（`call_source`/`duration_ms`/`ttft_ms`/`upstream_status_code`/`failure_type`）
- `server/interactions/ledger.py` — `record_model_usage` / `arecord_model_usage`（调用方枚举证明 Stage 1 未落库）
- `server/system/models.py:342-395` — `SystemLogEntry`（`payload` JSONField + `Index(component,-ts)`）；`SettingKeys.REPO_ROUTER_*`
- `server/common/logging.py:362-370` — `redact_secrets_in_text`
- `server/friday/settings.py:328-350` — `REPO_ROUTER_STAGE1_*` / `REPO_ROUTER_CONF_THETA_*`
- `server/initiatives/services/repo_association_service.py`（`get_verified_associations` 契约）/ `context_link_service.py` / `models/repo_association.py` / `models/project_branch.py`
- `web/src/components/chat/RoutingDecisionPanel.vue`（303 行）、`web/src/stores/routing.ts`（101 行）、`web/src/types/routing.ts`（50 行）、`web/src/stores/chat.ts:515/1283/1309`、`web/src/components/ui/badge/index.ts`
- **离线实测**：`cd server && uv run python -c "from codegraph.services.repo_router_eval import score_case ..."` → gk-008 delta=0.1771 / gk-009 delta=0.2614（本次实跑，零网络）

### Primary（HIGH confidence — 设计权威文档）
- `.planning/research/ROUTING-RANKING.md` §0 结论速览 / §1.3(a)(b)(c) 级联重排三条修正 / §4 权重与 INV-R1~R4 / §5.1 两组可比性 / §5.2 block ranking + delta 迟滞 + 三条代价 / §6 幂等清单 9 条 / §7.4 机制级断言 / §8 落地顺序第 7–8 步 / §9 O-4 与 O-6
- `.planning/observability/LOGGING-SPEC.md` §2 事件分类 / §4.1 call_source / §4.3 `percentile_cont` 分位纪律 / §5 component 清单 / §6 用户上下文贯穿 / §7 Ledger / §8 SystemLogEntry / §9 自检清单
- `.planning/phases/107-layered-presentation/107-CONTEXT.md`（锁定决策）
- `.planning/phases/106-multi-signal-scoring/106-06-SUMMARY.md` / `106-08-SUMMARY.md`（路由接线现状、golden 版本纪律、839 passed 基线）
- `.planning/phases/105-golden-set/105-RESEARCH.md` §4 消费方矩阵（8 个调用方）、§Pitfall「只测 router 单元不足」
- `.planning/phases/105-golden-set/105-VALIDATION.md`（VALIDATION 格式与命令口径参照）
- `./CLAUDE.md` + `.cursor/rules/observability-logging.mdc`（强制观测规范）

### Secondary（MEDIUM confidence）
- 文献引用全部转引自 `ROUTING-RANKING.md` 的一手来源清单（Arguello vertical selection SIGIR 2009 / CIKM 2011 支撑 block ranking；Tang et al. NAACL 2024 支撑固定输入顺序 + rank budget；Thinking Machines batch invariance 支撑"系统层保幂等"）。本次**未重新访问外部文献**——设计结论已在 ROUTING-RANKING 中定版且被 CONTEXT 锁定，重新检索无法改变可执行结论。

### Tertiary（LOW confidence）
- 无。本 phase 未依赖任何未经代码或文档验证的判断；所有取值不确定项已列入 Assumptions Log 与 Open Questions。

---

## Metadata

**Confidence breakdown:**
- 代码现状与改动落点：**HIGH** — 8 个消费方、4 跳透传链、3 条收答路径、澄清状态机、apscheduler 范式全部实读并核对行号
- delta=0.15 的可用性：**HIGH** — 本次离线实测两条 cross_group 样本（0.1771 / 0.2614）均触发置顶，且给出了 < 0.1771 的可用上界
- `S_ranked` 不得覆盖 `score`：**HIGH** — 两条既有 pytest 断言 + 前端容差校验 + ROUTE-07 承诺三重证据
- α=0.35 / K=3 的具体取值：**MEDIUM** — 形式有据（ROUTING-RANKING §1.3b/c），数值是判断；α 结构上无法用离线 golden 校准（OQ-5）
- Stage 1 per-call 超时新默认值：**LOW** — 必须先做 O-6 实测（A5）
- 候选范围语义（OQ-1）：**MEDIUM** — 现状机制 HIGH 置信（实读硬过滤），但"该不该放开"是产品/风险裁决，非研究可定
- 「本项目关联仓」数据源选择（A1）：**MEDIUM** — 三条数据源都存在且可达，选哪条取决于产品语义

**Research date:** 2026-07-30
**Valid until:** 2026-08-29（30 天；本仓代码变动是唯一失效来源，无外部依赖版本风险。⚠️ 若 v0.20.0 蓝图分支合入 `process_runtime`，§3 的澄清链现状需重新核对）
