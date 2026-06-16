# Phase 43: 编码 env 对齐 + 通用 resume 回流地基 - Context

**Gathered:** 2026-06-16
**Status:** Ready for planning

<domain>
## Phase Boundary

本 phase 是 v0.8.0 多仓 wave 编码的**两块地基修复**，纯后端基础设施（无 UI 触面）：

1. **PF-06 — 编码 env 对齐**：修 workflow 编码路径 `AICodingNode._run_repo_coding`（`server/workflows/nodes/ai/coding.py`）未注入 branch strategy / git token env 的缺陷——对齐 chat 路径 `coding_session_service.build_dispatch_metadata`（`server/chat/coding_session_service.py`）已有的 `env_FRIDAY_TASK_GIT_*` + `env_FRIDAY_TASK_BRANCH_STRATEGY` / `env_FRIDAY_TASK_TARGET_BRANCH` 注入，使私有仓 clone 成功且用正确目标分支（不再落容器默认 `friday/task-{id}`）。

2. **RESUME-01 — 通用 resume 回流地基**：立通用 `coding`/`plan_session` → 工作流/会话 resume 回流通路，消化 v0.7 audit D-2（chat fire-and-forget 编排进 `researching`、容器在途完成后无消费者驱动 engine 续跑的缺口）。复用既有 `waiting_event` + callback resume 范式（`server/subagent/api/callbacks.py` 的 `_schedule_workflow_resume`），为后续 callback 驱动的多 wave 调度提供统一回流通路。

**显式不做**（留后续 phase / backlog）：`RepoCodingTask` 模型与 wave 拓扑分层（Phase 44）、上游产物注入（Phase 45）、多仓融合 PR（Phase 46）、编码遇阻 HITL（Phase 47）、编码中全自动 replan（backlog）。本 phase 只补 env 注入对齐 + resume 回流通路，不引入新模型、不改编排上游。

</domain>

<decisions>
## Implementation Decisions

> 基础设施 phase——以下为「推荐 / 最安全默认」技术决策，均在 the agent's Discretion 范围内（无用户面交互）。Planner 可在 PLAN.md 细化，但应保持「对齐既有 chat 路径、复用既有 resume 范式、不造两套」的方向。

### PF-06：env 注入对齐

- **对齐目标**：以 chat 路径 `build_dispatch_metadata` 的 env 注入键集合为权威基线。workflow 路径 `_run_repo_coding` 应注入对称的 git token env（`env_FRIDAY_TASK_GIT_ACCESS_TOKEN` / `env_FRIDAY_TASK_GIT_AUTH_TYPE` / `env_FRIDAY_TASK_GIT_SSL_VERIFY`）+ 分支 env（`env_FRIDAY_TASK_BRANCH_STRATEGY` = 工作分支、`env_FRIDAY_TASK_TARGET_BRANCH` = 目标/base 分支）。
- **token 解析**：复用既有 `aresolve_git_token(repository)`（Phase 26 单一入口，per-repo 优先 → host 实例凭证池 fallback），不内联 decrypt；token 仅进 dispatch payload，绝不入日志（仅记 `has_token` 布尔）。
- **SSH→HTTPS 改写**：对齐 chat 路径——token 认证时把 `git@host:path` 改写为 `https://host/path.git`（token 认证需 HTTPS）。
- **保留既有 nested `git_credentials` dict 兼容**：若容器/runner 仍读既有 `metadata["git_credentials"]`，对齐后两种形态并存（不破坏现有 runner 契约）；以容器实际读取的 env 键为准排查（runner `env_` 前缀 TrimPrefix 约定，见 `runner/internal/docker/executor.go`）。决策倾向：新增对称 env 键，既有 nested dict 保留以零回归（最终由 task 容器侧读取契约决定，planner 须核对 `task/` 侧 env 读取）。
- **凭证缺失行为不回退**：无 token 时保持既有降级（不注入 access_token env），与 chat 路径一致。

### RESUME-01：通用 resume 回流通路

- **复用既有范式，不另造调度**：以 `subagent/api/callbacks.py` 既有 `_schedule_workflow_resume`（node_execution 路径，已闭环工作流）为蓝本，补齐 chat / 纯会话入口的对称 resume 路径，统一收口在容器统一回调端点（`_handle_completed` / `_handle_failed`）。
- **消化 D-2 的两处缺口**（chat `plan_research` 路径）：
  1. **barrier 未通知**：`_schedule_agent_session_resume` 当前对 `source == plan_research` 提前 return、从不通知 chat 阻塞任务 barrier → chat 会话永不自动 resume。需在调研全部终态后驱动对应回流（通知阻塞任务 / 续驱 engine）。
  2. **engine 未续驱**：`amaybe_complete_research` 只把 `researching → merging`，chat 入口此后无消费者驱动 `engine.advance`（merging→architecting→done）。需要一个 callback 驱动的消费者把 chat 入口 session 推到终态。
- **入口一致**：resume 通路对「工作流入口」与「chat 入口」一致可用——优先抽一个入口无关的 resume 驱动 helper（mirror `plan_orchestration/entrypoint.py` 的「同一 engine 复用」精神），工作流走既有 node resume、chat 走会话 resume，但**底层续驱 engine 的逻辑同源**，不重复两套。
- **幂等 + fail-soft**：resume 触发必须幂等（重复回调 / 并发已推进 → no-op，对齐 `amaybe_complete_research` 的 status guard）；resume 失败仅 `logger.warning` 降级，绝不让回调主流程 5xx（对齐既有 `_handle_research_completion` 的独立 try/except swallow 范式）。
- **作用域克制**：本 phase 立「通用回流通路」的地基（plan_research + coding 两类容器完成 → 驱动对应 workflow 节点 / chat 会话续跑）；多 wave 调度本身（wave N done → wave N+1）留 Phase 44。
- **真实容器 E2E**：真实 runner + Docker 容器端到端 resume 验收沿用既有 deferred（本地无法闭环），本 phase 以 IO 边界 mock 的单测 / 集成测试覆盖 happy-path 与 deep-research 路径闭环。

### the agent's Discretion

- 是否新增「通用 resume helper」模块（如 `services/plan_orchestration/resume.py` 或在 `callbacks.py` 内抽函数）由 planner 按最小 diff / 复用最大化原则决定。
- chat 会话最终回流呈现（如何把融合后的主方案回灌对话）由 planner 对照既有 `barrier` / `BlockingTaskResult` / `schedule_resume_agent_session` 机制决定，倾向复用 deep_analysis 既有回灌通道，不新造前端组件。
- 是否在本 phase 顺带更新 `start_plan_research` 工具的「自动回流尚未接入」措辞（接通后应如实改为已接入）由 planner 决定，倾向接通后同步更新文案避免误导。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `services/git_credentials.aresolve_git_token(repository)` — Phase 26 统一 token 解析入口（per-repo → host 实例池 fallback），两条编码派发路径已在用。
- `chat/coding_session_service.build_dispatch_metadata()` — chat 路径 env 注入的**权威基线**（git token env + branch strategy + target branch + SSH→HTTPS 改写 + 排除规则）。
- `subagent/api/callbacks.py`：
  - `_schedule_workflow_resume(session, log)` — 容器完成 → 检查节点所有 SubAgentSession 终态 → 写 `_resume_from_callback` 标记 → `WorkflowEngine._continue_after_node` 续跑（**工作流 resume 已闭环范式**）。
  - `_schedule_agent_session_resume(session, log)` — 纯 Agent / chat 会话 resume（**plan_research 分支当前提前 return，是 D-2 缺口所在**）。
  - `_handle_completed` / `_handle_failed` — 统一回调收口点，已挂 `_handle_research_completion`（barrier 触发）。
  - `_notify_barrier_manager` — chat deep_analysis 阻塞任务 barrier 通知（resume chat 的现成机制，可复用于 plan_research）。
- `services/plan_orchestration/research_aggregation.amaybe_complete_research()` — 调研全终态 → `researching→merging`（经 service transition，engine 纯度）；含 status guard 幂等。
- `services/plan_orchestration/entrypoint.py` — `start_orchestration` + `build_orchestration_engine`（工作流/chat 两入口共用同一 engine 构造，「不造两套」的现成范式）。
- `workflows/nodes/ai/plan_research.py` — 工作流入口节点的 advance 驱动循环 + `_maybe_suspend`（researching → waiting_event）+ resume 重入 advance 循环。
- `agents/tools/plan_research_tools.py` — chat 入口工具，researching 处 `register_blocking_task` + 返回 `__blocking_task__` marker（**含「自动回流尚未接入」的诚实占位文案，接通后应更新**）。
- `agents/tools/blocking_task_registry.register_blocking_task` / `orchestration.barrier.get_barrier_manager` — chat 阻塞任务注册 + barrier 满足驱动会话 resume 的现成机制。

### Established Patterns
- async ORM 经 `*_id` 标量 / `afirst` / `aget` / `aexists`，绝不裸访问同步 lazy-FK（规避 SynchronousOnlyOperation）。
- 容器回调 env 注入：`env_FRIDAY_TASK_*` 键经 runner Docker executor `env_` 前缀 TrimPrefix 约定下传容器环境变量。
- 凭证 / 敏感值绝不入日志，仅记 `has_*` 布尔（`redact_credentials` structlog processor 兜底）。
- callback 钩子独立 `try/except` swallow + `logger.warning`，绝不让回调主流程失败（barrier / research_completion / cross_repo_relevance 均如此）。
- resume 续跑统一收口（18-04）：不手工翻转 SUSPENDED→RUNNING，经 `engine._continue_after_node` 统一入口。
- 状态转移只经 `PlanSessionService.transition`（DOMAIN §14 转移表），engine / callback 不直接写 status。

### Integration Points
- workflow 编码 dispatch：`AICodingNode._run_repo_coding` 的 `DispatchTask.metadata`（PF-06 注入点）。
- chat 编码 dispatch：`coding_session_service.build_dispatch_metadata`（PF-06 对齐基线，无需改）。
- 容器统一回调端点：`POST /api/containers/callback/` → `ContainerCallbackView` → `_handle_completed` / `_handle_failed`（RESUME-01 收口点）。
- task 容器侧 env 读取契约：`task/`（planner 须核对 `env_FRIDAY_TASK_BRANCH_STRATEGY` / `env_FRIDAY_TASK_GIT_*` 的容器侧消费，确保对齐键名生效）。

</code_context>

<specifics>
## Specific Ideas

- PF-06 的「对齐」以 chat 路径 `build_dispatch_metadata` 的 env 键集合为权威基线，逐键对齐到 `AICodingNode`，而非反向。
- RESUME-01 强调「不重复造两套」：workflow 与 chat 两入口的 resume 必须复用同一底层续驱逻辑（mirror `entrypoint.py` 同一 engine 复用范式），区别只在入口运行时（workflow node resume vs chat 会话 resume）。
- 真实容器端到端 resume 验收沿用既有「需真实 runner + Docker」deferred，本 phase 以 mock IO 边界的自动化测试覆盖 happy-path + deep-research 闭环。

</specifics>

<deferred>
## Deferred Ideas

- `RepoCodingTask` 模型 + `execution_plan` DAG 拓扑分层 + wave 调度 → Phase 44（WAVE-01/02）。
- 上游 `produced_artifacts` 提取 + 注入下游 wave → Phase 45（ARTIFACT-01/02）。
- 多仓融合 PR + 跨仓 PR 关联 → Phase 46（PR-01/02）。
- 编码遇阻 question 抛人（task 侧发起 + orchestrator resume）→ Phase 47（HITL-01）。
- 编码中全自动回溯重规划 → backlog（REPLAN-01，v0.8 显式非目标）。

</deferred>
