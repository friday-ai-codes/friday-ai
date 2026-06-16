# Phase 44: RepoCodingTask + execution_plan DAG 拓扑分层 + wave 调度 - Context

**Gathered:** 2026-06-16
**Status:** Ready for planning

<domain>
## Phase Boundary

本 phase 立 v0.8.0 多仓 wave 编码的**操作态脊柱 + 拓扑调度引擎**，纯后端基础设施（无新 UI 触面）：

1. **WAVE-01 — `RepoCodingTask` 操作态模型 + 拓扑分层**：在 `delivery` app 立 `RepoCodingTask`（`plan_version` FK / `repository` FK / `wave` int / `depends_on` M2M self DAG / `status` / `produced_artifacts` JSON / `follow_openspec` 预留 SDD 扩展点 / `attempt` / `error`），经**单一写入入口** service（INV-6 精神，禁旁路写表）。把 `MergedPlan.execution_plan[].dependencies` 真正消费——按跨仓依赖拓扑分层成 wave（消化 PF-07：`dependencies` 不再仅 schema 声明、`AICodingNode` 真正读 dependencies、下游不再无条件全并行）。

2. **WAVE-02 — wave 式执行推进 + 失败/回滚语义**：wave N 全部终态（done）才触发 wave N+1（按 `depends_on` 拓扑顺序推进），依赖未满足的仓不提前 dispatch。复用 Phase 43 callback 驱动 resume 通路（`_schedule_workflow_resume` → `_resume_from_callback` → 节点重入）扩成多 wave，**不另造调度**。明确单 wave 内单仓失败的隔离边界与整体回滚语义（有定义、有测试）。

**显式不做**（留后续 phase / backlog）：上游 `produced_artifacts` 的**提取 + 注入下游** wave（Phase 45 ARTIFACT-01/02——本 phase 仅立 `produced_artifacts` 字段并预留写入扩展点，不做内容提取/注入）、多仓融合 PR + 跨仓 PR 关联（Phase 46）、编码遇阻 HITL question 抛人（Phase 47）、编码中全自动回溯重规划（backlog，v0.8 显式非目标——遇阻不自动 replan）、`follow_openspec=True` 时的 openspec system prompt 注入（v0.9，仅留字段）、真实 runner + Docker 容器端到端验收（沿用既有 deferred，本 phase 以 mock IO 边界测试覆盖）。

</domain>

<decisions>
## Implementation Decisions

> 基础设施 phase——以下为「推荐 / 最安全默认」技术决策，均在 the agent's Discretion 范围内（无用户面交互，autonomous 模式已全部 AUTO-ACCEPT 推荐项）。Planner 可在 PLAN.md 细化，但应保持「对齐既有 `delivery` 模型范式、复用既有 callback resume 通路、守 INV-6 单一写入入口、不造两套」的方向。

### Area 1：`RepoCodingTask` 模型形状（WAVE-01）

- **`plan_version` 引用**：真实 FK 指向 `delivery.PlanVersion`（v0.7 已建表，同 app 无迁移耦合风险）。`on_delete=models.CASCADE` 或 `PROTECT` 由 planner 定，倾向 `CASCADE`（删方案版本删其编码任务，对齐 RepoResearchTask 删 session 级联范式）。注意区别于 `PlanSession.current_plan_version` 的软 UUID 引用——那是为规避 36↔37 迁移耦合，本 phase 无此约束，用真实 FK（DOMAIN §6/§12 写明 "plan_version FK"）。
- **`repository`**：跨 app 真实 FK 指向 `repositories.Repository`，`on_delete=CASCADE`，`related_name="+"`（不污染 Repository 反查，对齐 RepoResearchTask 范式）。
- **`wave`**：`IntegerField`（拓扑层级，0-based），由 service 在建任务时按拓扑分层算法计算写入。
- **`depends_on`**：`ManyToManyField("self", symmetrical=False, blank=True)`（有向 DAG，承载跨仓依赖边）。`related_name` 显式命名（如 `dependents`）以便正反查。
- **`status`**：`TextChoices` 4 态 `pending → running → done | failed`（逐字对齐 DOMAIN §14 `RepoCodingTask` 子任务级状态；**不含** `stale`——stale 是调研期重索引语义，编码期无）。
- **`produced_artifacts`**：`JSONField(default=dict, blank=True)`——**本 phase 仅立字段 + 预留写入扩展点**（service 在任务 done 时可写空/占位），内容提取与下游注入留 Phase 45。
- **`follow_openspec`**：`BooleanField(default=False)`——SDD 扩展点预留位，本 phase **不消费**（v0.9 才注入 openspec system prompt）。
- **`subagent_session`**：FK 指向 `subagent.SubAgentSession`，`on_delete=SET_NULL, null=True, blank=True, related_name="+"`（dispatch 容器后回填，删容器会话不删 task；对齐 RepoResearchTask）。
- **可靠恢复字段**：`attempt IntegerField(default=0)`（单仓重试承载，对齐 DOMAIN §6「失败→单仓重试不重跑整 session」）+ `error JSONField(default=dict, blank=True)`（结构化失败诊断）。
- **元数据**：`id UUIDField(primary_key, default=uuid4)`、`created_at auto_now_add`、`updated_at auto_now`。
- **Meta**：`db_table="delivery_repo_coding_task"`、中文 verbose_name、`indexes=[Index(plan_version, wave, status), Index(repository)]`。
- **模型层零业务方法**：不写任何 create/save/状态变更/校验业务方法（守 INV-6 精神，旁路写表由 grep 守护），全部经 service。

### Area 2：拓扑分层算法（消化 PF-07，WAVE-01）

- **依赖引用语义**：先**核对** `MergedPlan.execution_plan[]` 项中 `dependencies` 字段的真实引用对象（执行项 `id` vs `repository_id`）——以 `workflows/schemas/technical_plan.py` 的 schema 定义为权威。Planner 须 grep 确认后再实现，倾向：`dependencies` 引用其他 execution_plan 项的 `id`，由 service 解析为仓级 `depends_on` 边。
- **算法**：Kahn 拓扑排序分层（入度为 0 集合为 wave 0，移除后再取入度 0 为 wave 1，依此类推）。同层任务（依赖已全满足）落同一 wave，可并行 dispatch。
- **环检测**：检测到依赖环 → fail-fast，落结构化 error（`{reason: "dependency_cycle", cycle: [...]}`），节点返回 `failed` / 不进入 dispatch。复用 / 对齐既有 `plan_validator.validate_plan` 的 DAG 无环校验（grep `CHECK_NAMES` 确认是否已有 `dag` 校验项，能复用则复用，不重复造）。
- **向后兼容（关键）**：`execution_plan` 中**全部** `dependencies` 为空/缺失 → 退化为单 wave（wave 0）全并行——**完整保留**当前 `AICodingNode` 全并行行为，零回归。消化 PF-07 的语义是「**有** dependencies 声明时按拓扑分层、不再无条件全并行」，而非强制串行。
- **多任务同仓**：`execution_plan` 可能多项同 `repository_id`（现有 `_group_by_repository` 已按仓分组）。wave 调度粒度 = **仓级**（一个 `RepoCodingTask` = 一仓在本次方案中的全部编码任务），与既有 `_group_by_repository` 分发粒度一致；仓的 wave = 该仓所有 execution_plan 项依赖层级的最大值（保证依赖满足）。

### Area 3：wave 调度推进 + resume 复用（WAVE-02）

- **复用 callback 驱动 resume，不另造调度**（硬约束）：以 Phase 43 已闭环的 workflow resume 通路为蓝本——`AICodingNode` 首次 dispatch wave 0 → `waiting_event`；容器回调 `subagent/api/callbacks.py:_schedule_workflow_resume` 检查节点 SubAgentSession 终态 → 写 `_resume_from_callback` → engine `_continue_after_node` 重入节点。
- **wave 状态全持久化**：当前 wave 进度由 `RepoCodingTask` 行（status/wave）承载，**不依赖内存态**（engine 可从任意点 resume）。节点 resume 时：查本 plan_version 的 RepoCodingTask，按 SubAgentSession status 回填 done/failed → 判定当前 wave 是否全终态 → 若是且有下游 wave，dispatch 下一 wave 并再次 `waiting_event`；若全部 wave 终态，进入 MR 创建 + 通知（复用既有 `_resume_after_containers` 收尾逻辑）。
- **单一写入入口**：RepoCodingTask 的建表/状态回填/wave 推进只经 `RepoCodingTaskService`（INV-6 精神）；engine/callback/节点不直接写 `task.status`。
- **幂等 + fail-soft**：resume / wave 推进必须幂等——重复回调 / 并发已推进 → no-op（status guard，对齐 `amaybe_complete_research` 幂等范式）；wave 调度副作用失败仅 `logger.warning` 降级，绝不让回调主流程 5xx（对齐既有 callback 钩子独立 try/except swallow 范式）。
- **入口范围**：本 phase 优先打通 **workflow 入口**（`AICodingNode`）的多 wave 调度（PF-07 直接触面）。chat 编码入口（`coding_session_service`）若派发粒度对称可顺带对齐，否则留作 follow-up（倾向：底层 wave 推进逻辑入口无关、可被两入口复用，mirror RESUME-01「不造两套」精神，但 chat 编码入口的多 wave 接线非本 phase 硬性验收项）。
- **dispatch 抑制**：依赖未满足的仓（wave > 当前 wave，或上游 depends_on 未全 done）**不提前 dispatch**——只 dispatch「当前 wave 且 depends_on 全 done」的 pending 任务。

### Area 4：wave 失败 / 部分回滚语义（WAVE-02）

- **单仓失败隔离**：单 wave 内某仓任务 `failed` **不影响**同 wave 其余仓任务（它们各自独立完成；现有 `asyncio.gather(..., return_exceptions=True)` 已隔离单仓异常）。失败仓标 `RepoCodingTask.status=failed` + 结构化 `error`。
- **wave gate（推进门）**：wave N+1 仅在 wave N **全部任务终态**（`done` 或 `failed`）后触发——不是「全部 done」。这样失败也是终态、不会无限挂起。
- **下游阻断（最安全默认）**：若 wave N 内有任务 `failed`，其**直接/间接下游** depends_on 链上的任务标记为 blocked（落 `failed` + `error={reason: "upstream_failed", upstream: [...]}`），**不 dispatch**（依赖产物不可用，提前编码无意义）。无失败上游的独立分支仍正常推进。
- **回滚语义（明确，v0.8 非目标对齐）**：**不做自动回滚**——已 dispatch / 已成功仓的分支/容器产物**不自动回退/不自动删分支**（v0.8 显式非目标：不做编码中全自动回溯重规划）。`MergedPlan.rollback_plan` 作为**人工回滚指引**保留呈现，编排层不自动执行。「部分回滚语义」= 部分成功收尾：为已 done 仓正常创建 MR（Phase 46 才融合），失败/阻断仓在结果中如实标注，整体不因单仓失败而丢弃已成功产物。
- **测试覆盖（验收硬项）**：
  1. 拓扑分层单测——含空依赖退化单 wave、线性链多 wave、菱形依赖、环检测 fail-fast。
  2. wave gating——wave N 全终态才 dispatch wave N+1；当前 wave 在途时不提前 dispatch 下游。
  3. 失败隔离——单 wave 内单仓失败，同 wave 兄弟不受影响；下游 depends_on 被阻断（不 dispatch）。
  4. 幂等——重复 callback / 并发 resume → no-op，不重复 dispatch。
  5. 单一写入入口（INV-6）——grep 守护断言旁路写 RepoCodingTask 表（对齐既有 INV-6 grep 测试范式）。

### the agent's Discretion

- `RepoCodingTaskService` 模块落点（`services/` 下新模块 vs 复用 `plan_orchestration/` 包）、wave 推进 helper 是否抽成入口无关函数（mirror `resume.adrive_plan_session_to_pause_or_terminal` 范式）由 planner 按最小 diff / 复用最大化决定。
- `plan_version` FK 的 `on_delete`（CASCADE vs PROTECT）、`depends_on` 的 `related_name`、索引字段组合细节由 planner 定。
- 是否在本 phase 顺带发 `coding.wave.started` / `coding.wave.completed` trace 事件（DOMAIN §15 已定义词表）由 planner 决定，倾向接通（事件 taxonomy 早产出，低成本）。
- `RepoCodingTask` 与现有 `AICodingNode` 既有「全并行 + 一次性 resume」逻辑的衔接方式（重构 `_execute_with_branch` / `_resume_after_containers` vs 新增 wave 编排层）由 planner 按回归风险最小化决定。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `delivery/models/research_task.py`（`RepoResearchTask` / `PartialPlan`）——**最强范式蓝本**：跨 app FK 字符串前向引用、`subagent_session SET_NULL`、`attempt` 重试计数、`status TextChoices`、模型层零业务方法、`db_table`/中文 verbose_name/`indexes` 约定。`RepoCodingTask` 应逐项对齐其形状。
- `delivery/models/plan_session.py`（`PlanSession` / `PlanSessionStatus`）——状态枚举 + 软引用 vs 真实 FK 取舍的参考。
- `delivery/models/technical_plan.py`（`PlanVersion`）——`RepoCodingTask.plan_version` FK 目标（v0.7 已建表）。
- `services/plan_orchestration/resume.py:adrive_plan_session_to_pause_or_terminal`——Phase 43 入口无关续驱 helper，wave 推进 helper 的范式参考（「逻辑同源、不造两套」）。
- `services/plan_orchestration/research_aggregation.py`（`amaybe_complete_research` / `aall_research_tasks_terminal`）——barrier 式「全终态 → 推进」+ status guard 幂等的现成范式，wave gate 判定可对齐。
- `services/plan_orchestration/merged_plan.py:validate_merged_plan` + `workflows/schemas/technical_plan.py:validate_technical_plan`——`execution_plan[]` schema 权威源（`dependencies` 字段引用语义需在此核对）。
- `services/plan_orchestration/plan_validator.py:validate_plan` + `CHECK_NAMES`——已有跨仓 DAG/契约校验，环检测可复用/对齐（grep 确认是否已有 acyclic 校验项）。
- `workflows/nodes/ai/coding.py:AICodingNode`——PF-07 直接触面：`_extract_plan_data` / `_group_by_repository`（仓级分组现成）/ `_run_repo_coding`（dispatch + waiting_event）/ `_resume_after_containers`（callback resume 收尾 + MR 创建）。当前**全并行无 wave**，需改成按 wave 分批 dispatch。
- `subagent/api/callbacks.py:_schedule_workflow_resume` / `_handle_completed` / `_handle_failed`——容器回调统一收口 + workflow resume 闭环（wave N→N+1 的回调驱动点）。

### Established Patterns
- `delivery` 模型：跨 app FK 用字符串前向引用避 import 环；`related_name="+"` 不污染目标反查；状态变更只经 service（INV-6）；模型层零业务方法 + grep 守护旁路写表。
- async ORM 经 `*_id` 标量 / `afirst` / `aget` / `aexists` / `async for`，绝不裸访问同步 lazy-FK（规避 `SynchronousOnlyOperation`）。
- 状态机推进经 service `transition`，engine/callback 不直接写 status；幂等 status guard（重复触发 no-op）。
- callback 钩子独立 try/except swallow + `logger.warning` 降级，绝不让回调主流程失败。
- resume 续跑统一收口：不手工翻转 SUSPENDED→RUNNING，经 `engine._continue_after_node` / `_resume_from_callback` 标记重入。
- 节点 `waiting_event` + `output_data` 持久化承载跨容器回调的恢复状态（`_resume_after_containers` 从 `output_data` 重读 pending_sessions）。
- ruff line 100、Python 3.14、async adrf；注释/docstring 中文（zh-CN）。

### Integration Points
- workflow 编码 dispatch + resume：`AICodingNode._execute_with_branch`（wave 0 首发）/ `_resume_after_containers`（wave N→N+1 推进 + 终态收尾）。
- 容器统一回调端点：`POST /api/containers/callback/` → `_handle_completed` / `_handle_failed` → `_schedule_workflow_resume`（wave 推进触发点，复用不改契约）。
- 新模型迁移：`delivery/migrations/`（下一个序号 `0017_*`，对齐既有 `makemigrations` 流程）。
- 模型 barrel：`delivery/models/__init__.py`（新增 `RepoCodingTask` / `RepoCodingTaskStatus` 导出）。
- execution_plan schema：`workflows/schemas/technical_plan.py`（`dependencies` 引用语义核对点）。

</code_context>

<specifics>
## Specific Ideas

- `RepoCodingTask` 逐项对齐 `RepoResearchTask` 模型形状（同 app 姊妹模型），降低认知与维护成本。
- 拓扑分层「向后兼容退化单 wave」是零回归关键——空 dependencies 时行为必须与当前 `AICodingNode` 全并行逐字一致。
- 「不另造调度」：wave N→N+1 的推进必须复用 Phase 43 callback resume 通路（`_schedule_workflow_resume` → `_resume_from_callback` → 节点重入），不新建轮询/定时器/独立调度循环。
- 「不做自动回滚」对齐 v0.8 显式非目标——`rollback_plan` 仅作人工指引呈现，编排层部分成功收尾、不自动回退已成功产物。
- 真实 runner + Docker 端到端 wave 验收沿用既有 deferred；本 phase 以 mock IO 边界（dispatcher / SubAgentSession 状态）的单测/集成测试覆盖拓扑分层、wave gating、失败隔离、幂等。

</specifics>

<deferred>
## Deferred Ideas

- 上游 `produced_artifacts` 提取 + 注入下游 wave prompt/global_context → Phase 45（ARTIFACT-01/02）。本 phase 仅立字段 + 预留写入扩展点。
- 多仓融合 PR + 跨仓 PR 关联 → Phase 46（PR-01/02）。本 phase 仍每仓独立 MR。
- 编码遇阻 question 抛人（HITL）→ Phase 47（HITL-01）。
- `follow_openspec=True` 的 openspec system prompt 注入 → v0.9（本 phase 仅留字段）。
- chat 编码入口（`coding_session_service`）的多 wave 调度接线 → follow-up（本 phase 优先 workflow 入口；底层 wave 逻辑应入口无关以便后续复用）。
- 编码中全自动回溯重规划 → backlog（REPLAN-01，v0.8 显式非目标）。
- 真实 runner + Docker 容器端到端 wave resume 验收 → 既有 deferred（本地无法闭环）。

</deferred>
