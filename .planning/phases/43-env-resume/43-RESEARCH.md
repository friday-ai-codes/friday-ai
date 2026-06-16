# Phase 43: 编码 env 对齐 + 通用 resume 回流地基 - Research

**Researched:** 2026-06-16
**Domain:** Django 后端编排（容器 dispatch env 注入对齐 + callback 驱动的 PlanSession/会话 resume 回流）
**Confidence:** HIGH（全部基于代码库内既有实现与契约 grep/读取核对，无外部依赖，无新包）

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**PF-06：env 注入对齐**
- 对齐目标：以 chat 路径 `build_dispatch_metadata` 的 env 注入键集合为权威基线。workflow 路径 `_run_repo_coding` 注入对称 git token env（`env_FRIDAY_TASK_GIT_ACCESS_TOKEN` / `env_FRIDAY_TASK_GIT_AUTH_TYPE` / `env_FRIDAY_TASK_GIT_SSL_VERIFY`）+ 分支 env（`env_FRIDAY_TASK_BRANCH_STRATEGY` = 工作分支、`env_FRIDAY_TASK_TARGET_BRANCH` = 目标/base 分支）。
- token 解析：复用既有 `aresolve_git_token(repository)`（Phase 26 单一入口），不内联 decrypt；token 仅进 dispatch payload，绝不入日志（仅记 `has_token` 布尔）。
- SSH→HTTPS 改写：对齐 chat 路径——token 认证时把 `git@host:path` 改写为 `https://host/path.git`。
- 保留既有 nested `git_credentials` dict 兼容（零回归）；以容器实际读取的 env 键为准（runner `env_` 前缀 TrimPrefix）。
- 凭证缺失行为不回退：无 token 时保持既有降级（不注入 access_token env）。

**RESUME-01：通用 resume 回流通路**
- 复用既有范式，不另造调度：以 `subagent/api/callbacks.py` 既有 `_schedule_workflow_resume`（node_execution 路径，已闭环工作流）为蓝本，补齐 chat / 纯会话入口的对称 resume 路径，统一收口在容器统一回调端点（`_handle_completed` / `_handle_failed`）。
- 消化 D-2 的两处缺口（chat `plan_research` 路径）：(1) barrier 未通知；(2) engine 未续驱（`amaybe_complete_research` 只 researching→merging，chat 入口此后无消费者驱动 `engine.advance`）。
- 入口一致：优先抽一个入口无关的 resume 驱动 helper（mirror `plan_orchestration/entrypoint.py` 的「同一 engine 复用」精神），工作流走既有 node resume、chat 走会话 resume，但**底层续驱 engine 的逻辑同源**，不重复两套。
- 幂等 + fail-soft：resume 触发必须幂等（对齐 `amaybe_complete_research` status guard）；resume 失败仅 `logger.warning` 降级，绝不让回调主流程 5xx（对齐既有钩子独立 try/except swallow 范式）。
- 作用域克制：本 phase 立「通用回流通路」地基；多 wave 调度（wave N done → wave N+1）留 Phase 44。
- 真实容器 E2E 沿用既有 deferred；本 phase 以 IO 边界 mock 的单测/集成测试覆盖 happy-path 与 deep-research 路径闭环。

### Claude's Discretion
- 是否新增「通用 resume helper」模块（如 `services/plan_orchestration/resume.py` 或在 `callbacks.py` 内抽函数）由 planner 按最小 diff / 复用最大化决定。
- chat 会话最终回流呈现由 planner 对照既有 `barrier` / `BlockingTaskResult` / `schedule_resume_agent_session` 决定，倾向复用 deep_analysis 既有回灌通道，不新造前端组件。
- 是否顺带更新 `start_plan_research` 工具的「自动回流尚未接入」措辞（接通后改为已接入）由 planner 决定，倾向同步更新。

### Deferred Ideas (OUT OF SCOPE)
- `RepoCodingTask` 模型 + `execution_plan` DAG 拓扑分层 + wave 调度 → Phase 44。
- 上游 `produced_artifacts` 提取 + 注入下游 wave → Phase 45。
- 多仓融合 PR + 跨仓 PR 关联 → Phase 46。
- 编码遇阻 question 抛人 → Phase 47。
- 编码中全自动回溯重规划 → backlog（v0.8 显式非目标）。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PF-06 | 修 workflow 编码路径 `AICodingNode._run_repo_coding` 未注入 branch strategy / git token env，对齐 chat 路径，使私有仓 clone 成功且用正确目标分支（不再落默认 `friday/task-{id}`） | §「PF-06 env 键差异表」逐键列出缺失键 + 容器/runner 侧消费契约核对 + SSH→HTTPS + 多仓 per-repo branch_name 取值 |
| RESUME-01 | 立通用 `coding`/`plan_session` → 工作流/会话 resume 回流通路，消化 v0.7 audit D-2 | §「RESUME-01 D-2 两处缺口精确定位」+ §「推荐方案：同源续驱 + barrier 回灌」+ 调用链时序图 |
</phase_requirements>

## Summary

本 phase 是纯后端基础设施，**无新模型、无 migration、无新外部依赖、无新包**，只补两块既有路径的接线缺口。

**PF-06** 的根因已坐实：workflow 编码路径 `AICodingNode._run_repo_coding`（`server/workflows/nodes/ai/coding.py:976-997`）的 `DispatchTask.metadata` 只放了一个 **nested `git_credentials` dict**，而 runner 的 Docker executor（`runner/internal/docker/executor.go:154-162`）**只对 `env_` 前缀的顶层 metadata 键做 TrimPrefix 下传容器环境变量**——nested `git_credentials` dict 永远不会被容器读取（dead payload）。同时 workflow 路径**完全没有**注入 `env_FRIDAY_TASK_BRANCH_STRATEGY` / `env_FRIDAY_TASK_TARGET_BRANCH`，导致容器侧 `TaskConfig.branch_strategy` 为 `None`、`setup_task_branch` 回退到 `friday/task-{task_id}` 默认分支（`task/git_ops/operations.py:459-462`）。修复 = 逐键对齐 chat 路径 `build_dispatch_metadata`（`server/chat/coding_session_service.py:170-187`）的 `env_FRIDAY_TASK_GIT_*` + `env_FRIDAY_TASK_BRANCH_STRATEGY/TARGET_BRANCH` 注入 + SSH→HTTPS 改写 `repo_url`。注意 workflow 是 fan-out 多仓（每仓不同 `branch_name`），`env_FRIDAY_TASK_BRANCH_STRATEGY` 须取**每仓的工作分支**（`_run_repo_coding` 的 `branch_name` 参数），`env_FRIDAY_TASK_TARGET_BRANCH` 取 `base_branch`。

**RESUME-01** 的 D-2 两处缺口也已精确定位：chat 入口 `start_plan_research` fire-and-forget 进 `researching` 后，(a) `_schedule_agent_session_resume`（`callbacks.py:124-134`）对 `source == plan_research` **提前 return**，从不通知 chat 阻塞任务 barrier；(b) `amaybe_complete_research`（`research_aggregation.py:73-88`）只把 `researching → merging`，chat 入口此后**无消费者驱动 `engine.advance`** 把 session 推到 `done`。工作流入口已闭环（`AIPlanResearchNode` 设 `node_execution_id` → `_schedule_workflow_resume` 重跑节点 → 节点内 advance 循环续驱 merging→done）。推荐方案：抽一个**入口无关的 engine 续驱 helper**（mirror `entrypoint.py`「同一 engine 复用」精神），新增 `_schedule_chat_plan_resume`（与 `_schedule_workflow_resume` 对称、fire-and-forget）：仅对 chat 入口 plan_research 容器、在调研全终态后续驱 engine 到终态，再用 `BarrierManager.task_completed(plan_session_id, result)` 回灌 chat 会话（chat barrier 注册时 `task_id = str(plan_session.id)`）。

**Primary recommendation:** PF-06——在 `_run_repo_coding` 内 mirror `build_dispatch_metadata` 注入对称 `env_FRIDAY_TASK_GIT_*` + `env_FRIDAY_TASK_BRANCH_STRATEGY`(=branch_name)/`TARGET_BRANCH`(=base_branch) + SSH→HTTPS 改写，保留 nested dict 零回归。RESUME-01——抽共享 `async def adrive_plan_session_to_pause_or_terminal(engine, session)` 续驱循环（chat 工具 / 工作流节点 / 回调消费者三处复用），并新增 `_schedule_chat_plan_resume` 回调消费者打通 chat 入口的 engine 续驱 + barrier 回灌。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 编码容器 git 凭证/分支 env 注入（PF-06） | API/Backend (`workflows/nodes/ai/coding.py`) | — | dispatch metadata 构造在服务端节点执行；token 经服务端凭证解析器取，绝不下放前端/容器自取 |
| 容器侧 env 消费（clone 凭证 + 目标分支） | Task executor (`task/core/config.py`, `task/git_ops/operations.py`) | Runner (`runner/internal/docker/executor.go`) | runner 仅做 `env_` TrimPrefix 透传，task 用 pydantic `env_prefix="FRIDAY_TASK_"` 映射消费——本 phase **不改 task/runner**，只确保 server 注入的键名对齐既有消费契约 |
| 容器完成回调收口（RESUME-01） | API/Backend (`subagent/api/callbacks.py`) | — | 容器统一回调端点 `_handle_completed`/`_handle_failed` 是唯一收口点；resume 调度在此 fire-and-forget |
| PlanSession engine 续驱（merging→done） | Service (`services/plan_orchestration/engine.py` + 新 helper) | — | engine 入口无关、只接收 `PlanSession` + 注入依赖；续驱逻辑须工作流/chat 同源 |
| chat 会话 resume 回灌 | API/Backend (`orchestration/barrier.py` → `conversation_service._on_barrier_complete`) | — | chat 用 LangGraph `interrupt` 挂起 + BarrierManager `on_complete` 回灌；plan_research 复用此通道 |
| 工作流节点 resume | API/Backend (`workflows/engine/scheduler._continue_after_node`) | — | 已闭环，本 phase 不改 |

## Standard Stack

无新增依赖。本 phase 全部复用既有栈与既有模块：

| 模块/函数 | 路径 | 用途 | 为何是权威基线 |
|-----------|------|------|----------------|
| `aresolve_git_token(repository)` | `server/services/git_credentials.py` | 统一 token 解析（per-repo → host 实例池 fallback） | Phase 26 单一入口，两条编码派发路径已在用 |
| `build_dispatch_metadata()` | `server/chat/coding_session_service.py:125-203` | chat env 注入权威基线 | CONTEXT 锁定的 PF-06 对齐目标 |
| `_run_repo_coding()` | `server/workflows/nodes/ai/coding.py:895-1062` | PF-06 注入点（待修） | workflow 编码 dispatch 唯一构造点 |
| `_schedule_workflow_resume()` | `server/subagent/api/callbacks.py:193-282` | 工作流 resume 已闭环范式（蓝本） | CONTEXT 锁定的 RESUME-01 蓝本 |
| `_notify_barrier_manager()` | `server/subagent/api/callbacks.py:54-97` | chat deep_analysis barrier 通知机制（可复用范式） | 现成 chat 会话 resume 触发器 |
| `BarrierManager` | `server/orchestration/barrier.py` | all_of 汇聚 + on_complete 回灌 | chat 阻塞任务满足驱动会话 resume 的现成机制 |
| `amaybe_complete_research()` | `server/services/plan_orchestration/research_aggregation.py:73-88` | researching→merging（含 status guard 幂等） | 已是幂等 + service transition 范式 |
| `build_orchestration_engine()` | `server/services/plan_orchestration/entrypoint.py:55-84` | 两入口共用同一 engine 构造 | 「不造两套」现成范式 |
| `PlanOrchestrationEngine.advance()` | `server/services/plan_orchestration/engine.py:70-104` | 状态驱动续推一步 | 入口无关、可 resume |

**版本核对：** 无新包安装，跳过 registry 校验。

## Package Legitimacy Audit

**N/A** — 本 phase 不安装任何外部包（纯内部代码接线）。无 `[SLOP]`/`[SUS]` 项需处理。

## Architecture Patterns

### System Architecture Diagram — RESUME-01 回流通路（修复后）

```text
                    容器完成 (plan_research / coding)
                              │
                              ▼
          POST /api/containers/callback/ (ContainerCallbackView)
                              │
                      _handle_completed / _handle_failed
                              │
        ┌─────────────────────┼──────────────────────────────┐
        ▼                     ▼                                ▼
 _schedule_workflow_resume  _handle_research_completion   _schedule_chat_plan_resume  ← 新增
 (有 node_execution_id)      / _handle_research_failure     (chat 入口 + 无 node_execution)
        │                     │                                │
        │             amaybe_complete_research                 │
        │             (researching→merging, 幂等)              │
        ▼                     │                                ▼
 重跑挂起节点              [工作流: 节点重跑续驱]      adrive_plan_session_to_pause_or_terminal()
 AIPlanResearchNode.execute                              (共享 helper, mirror 节点/chat 工具 advance 循环)
        │                     │                                │
        │                     │                          engine.advance 循环: merging→done
        ▼                     │                                │  (或 validation_fail→重挂起)
 engine.advance 循环          │                                ▼
 merging→done                 │                    BarrierManager.task_completed(
        │                     │                       str(plan_session.id), BlockingTaskResult)
        ▼                     │                                │
 NodeResult completed         │                          barrier 满足 → on_complete
 → _continue_after_node       │                                │
   续跑工作流下游              │              conversation_service._on_barrier_complete:
                              │              LangGraph Command(resume=results) → finalize 落库
                              │                          (chat 会话回流主方案)
```

**关键：** 工作流入口（左）与 chat 入口（右）共享同一 `engine.advance` 续驱循环（中间的 `adrive_*` helper），区别只在「谁触发续驱」与「续驱后如何回灌」（工作流走 NodeResult/`_continue_after_node`，chat 走 barrier/LangGraph resume）。这正是 CONTEXT「底层续驱同源、不造两套」的落地。

### Pattern 1: env_ 前缀 metadata 注入（runner TrimPrefix 契约）

**What:** 服务端把容器环境变量以 `env_<KEY>` 形态放进 `DispatchTask.metadata` 顶层；runner Docker executor 对 `env_` 前缀键 TrimPrefix 后注入容器环境变量。

**When to use:** 任何需要下传容器环境变量的 dispatch（git 凭证、分支、Claude 凭证、排除规则）。

**Critical pitfall:** nested dict（如当前 `metadata["git_credentials"]`）**不会**被 runner 消费——只有顶层 `env_` 键生效。

```go
// Source: runner/internal/docker/executor.go:154-162
if meta, ok := task.Payload["metadata"].(map[string]any); ok {
    for k, v := range meta {
        if strings.HasPrefix(k, "env_") {
            envKey := strings.TrimPrefix(k, "env_")  // env_FRIDAY_TASK_X -> FRIDAY_TASK_X
            if s, ok := v.(string); ok && s != "" {  // 注意：仅 string 且非空才注入
                env = append(env, envKey+"="+s)
            }
        }
    }
}
```

### Pattern 2: 容器侧 env 消费契约（task pydantic env_prefix）

**What:** task 容器用 pydantic-settings `env_prefix="FRIDAY_TASK_"` 把环境变量映射到 `TaskConfig` 字段。

```python
# Source: task/core/config.py:22-50, 125-133
model_config = SettingsConfigDict(env_prefix="FRIDAY_TASK_", ...)
git_auth_type: str = Field(default="ssh")        # ← FRIDAY_TASK_GIT_AUTH_TYPE
git_access_token: str = Field(default="")         # ← FRIDAY_TASK_GIT_ACCESS_TOKEN
git_ssl_verify: bool = Field(default=False)       # ← FRIDAY_TASK_GIT_SSL_VERIFY
branch_strategy: str | None = Field(default=None) # ← FRIDAY_TASK_BRANCH_STRATEGY
target_branch: str | None = Field(default=None)   # ← FRIDAY_TASK_TARGET_BRANCH
```

容器侧 `setup_task_branch(branch_strategy, task_id)`（`task/git_ops/operations.py:432-474`）：`branch_strategy` 非空时严格用其字面值建分支；为 `None` 时**回退 `friday/task-{task_id}`**（PF-06 落默认分支的根因）。clone 凭证：`operations.py:81-87` 当 `git_access_token` 非空即走 token auth（HTTPS）。

### Pattern 3: callback 钩子独立 try/except swallow（fail-soft）

**What:** 所有 callback 副作用钩子用独立 `try/except` + `logger.warning`，绝不让回调主流程返回 5xx。

```python
# Source: server/subagent/api/callbacks.py:670-678（_handle_research_completion 调用范式）
try:
    await _handle_research_completion(session, p, log)
except Exception as exc:  # noqa: BLE001 — 永不阻塞 _handle_completed 主流程
    logger.warning("research_completion_callback_failed", session_id=session.session_id, error=str(exc))
```

### Pattern 4: fire-and-forget 异步调度（不阻塞回调响应）

**What:** resume 续驱可能慢（merge 段调 architect LLM），用 `loop.create_task` 后台执行；无 loop 时 `asyncio.run`。

```python
# Source: server/subagent/api/callbacks.py:277-282（_schedule_workflow_resume 尾部范式）
try:
    loop = asyncio.get_running_loop()
    loop.create_task(_resume())
except RuntimeError:
    asyncio.run(_resume())
```

### Recommended Project Structure（改动落点，最小 diff）

```
server/
├── workflows/nodes/ai/coding.py          # PF-06：_run_repo_coding 注入对称 env + SSH→HTTPS
├── services/plan_orchestration/
│   ├── entrypoint.py                      # （可选）新增共享 adrive_* 续驱 helper，或新建 resume.py
│   └── resume.py                          # （Discretion）入口无关 engine 续驱 helper 新模块（推荐）
├── subagent/api/callbacks.py             # RESUME-01：新增 _schedule_chat_plan_resume + 接线
├── agents/tools/plan_research_tools.py    # （可选）接通后更新「自动回流尚未接入」措辞 + 复用 helper
└── workflows/nodes/ai/plan_research.py    # （可选）advance 循环复用共享 helper（不改行为）
```

### Anti-Patterns to Avoid

- **把凭证放进 nested metadata dict** —— runner 不读，等于没注入（PF-06 现状 bug）。必须用顶层 `env_` 键。
- **token / endpoint 明文进日志** —— 只记 `has_token` 布尔（`redact_credentials` structlog processor 兜底，但代码侧也须自律）。
- **engine/callback 直接写 `session.status`** —— 必须经 `PlanSessionService.transition`（INV-6 / engine 纯度，§14 转移表）。
- **手工翻转 SUSPENDED→RUNNING** —— 工作流 resume 经 `engine._continue_after_node` 统一入口（18-04）。
- **chat 与工作流各造一套续驱循环** —— 违反 CONTEXT「不造两套」；必须共享底层 `engine.advance` 驱动逻辑。
- **resume 失败让回调 5xx** —— 必须独立 try/except swallow + warning。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| git token 解析 | 内联 `decrypt_value(credential.encrypted_token)` | `aresolve_git_token(repository)` | Phase 26 单一入口；per-repo→host 池 fallback；缺凭证降级语义已定 |
| SSH→HTTPS 改写 | 新写 URL 解析 | 照搬 `build_dispatch_metadata` 的 `re.match(r"git@([^:]+):(.+?)(?:\.git)?$", ...)`（`coding_session_service.py:177-180`） | 已验证的改写规则，零漂移 |
| researching→merging 推进 | 在 callback 里直接改 status | `amaybe_complete_research(session)` | 已含 status guard 幂等 + service transition |
| chat 会话 resume 回灌 | 新造前端通道 | `BarrierManager.task_completed` → 既有 `_on_barrier_complete` → LangGraph `Command(resume=)` | deep_analysis 已用此通道；plan_research 注册的 blocking task 即用此机制 |
| engine 构造 | 新建第二个 engine 工厂 | `build_orchestration_engine()` | 「不造两套」现成范式 |
| 终态判定集 | 自定义 set | `{PlanSessionStatus.DONE, PlanSessionStatus.FAILED}`（节点/工具已用） | 与既有 advance 循环一致 |

**Key insight:** 本 phase 的全部「新逻辑」实质是**接线**——把已存在但未连通的两端（容器回调 ↔ chat engine 续驱 ↔ chat barrier 回灌）用既有范式串起来。任何「新写」都应先确认现有模块不可复用。

---

## PF-06：env 键差异表（权威核对）

chat `build_dispatch_metadata` 注入键集合（`coding_session_service.py:155-201`） vs workflow `_run_repo_coding` 当前注入（`coding.py:924-997`）：

| env 键 | chat 路径（基线） | workflow 当前 | 容器侧消费（`task/core/config.py`） | PF-06 动作 |
|--------|------------------|---------------|--------------------------------------|------------|
| `env_FRIDAY_TASK_GIT_ACCESS_TOKEN` | ✅ token 非空时注入 | ❌（只在 nested `git_credentials.access_token`，runner 不读） | `git_access_token` → token auth clone | **新增** |
| `env_FRIDAY_TASK_GIT_AUTH_TYPE` | ✅ `"token"` | ❌ | `git_auth_type`（默认 ssh） | **新增**（`"token"`，token 非空时） |
| `env_FRIDAY_TASK_GIT_SSL_VERIFY` | ✅ `"false"` | ❌（nested `git_credentials.ssl_verify`，runner 不读） | `git_ssl_verify`（默认 False） | **新增**（对齐基线 `"false"`；或 per-repo credential 值，见 Open Q1） |
| `env_FRIDAY_TASK_BRANCH_STRATEGY` | ✅ `execution_spec.work_branch`（单仓） | ❌ **完全缺失** | `branch_strategy` → `setup_task_branch` 工作分支 | **新增**（= 本仓 `branch_name`，多仓 per-repo） |
| `env_FRIDAY_TASK_TARGET_BRANCH` | ✅ `execution_spec.target_branch` | ❌ **完全缺失** | `target_branch` → MR target | **新增**（= `base_branch`） |
| `repo_url`（SSH→HTTPS 改写） | ✅ token 认证时改写 | ❌ 直传 `repository.git_url`（SSH 仓 token clone 失败） | `git_repo_url` | **新增**改写：token 非空 + `git@` 开头 → `https://host/path.git` |
| `env_FRIDAY_TASK_CLAUDE_API_KEY` | ✅ | ✅（`coding.py:944`） | `claude_api_key` | 已对齐 |
| `env_FRIDAY_TASK_CLAUDE_BASE_URL` | ✅ | ✅（`coding.py:946`） | `claude_base_url` | 已对齐 |
| `env_FRIDAY_TASK_EXCLUDE_PATTERNS` | ✅ | ✅（`coding.py:969-974`） | `exclude_patterns` | 已对齐 |
| `metadata["git_credentials"]`（nested） | ❌ chat 无 | ✅ 现存（runner 不读，dead） | — | **保留**零回归（CONTEXT 决策） |

**多仓差异（关键）：** chat 是单仓（`execution_spec.work_branch` 来自单个 `coding_session.branch_name`）；workflow `_run_repo_coding` 是 fan-out 多仓（每仓一次调用，签名已带 `branch_name`/`base_branch` 参数，见 `coding.py:895-907`）。因此：
- `env_FRIDAY_TASK_BRANCH_STRATEGY` = **本次调用的 `branch_name`**（每仓工作分支；注意当前 workflow 多仓共用同一 `branch_name`，是既有行为，本 phase 不改分支命名策略，只把已解析的 `branch_name` 正确下传）。
- `env_FRIDAY_TASK_TARGET_BRANCH` = **本次调用的 `base_branch`**。
- `DispatchTask` 已正确设 `branch=base_branch` / `target_branch=branch_name`（`coding.py:982-983`），但 runner **不会**把 `DispatchTask.target_branch` 映射成容器 env（runner 只下传 `FRIDAY_TASK_GIT_BRANCH=task.Branch`，见 executor.go:142）——所以**必须**额外注入 `env_FRIDAY_TASK_BRANCH_STRATEGY`/`TARGET_BRANCH` 键，`DispatchTask.target_branch` 字段本身不足以驱动容器分支。

**容器/runner 侧消费确认（无需改动）：**
- runner `executor.go:154-162`：仅 TrimPrefix `env_` 顶层键 → 确认对齐键名即生效。
- task `config.py:22-26`：`env_prefix="FRIDAY_TASK_"` → `FRIDAY_TASK_GIT_ACCESS_TOKEN` 映射 `git_access_token` 等。
- task `operations.py:81-87`：`git_access_token` 非空即 token auth（HTTPS clone）。
- task `operations.py:459-462`：`branch_strategy` 非空用字面值，否则落 `friday/task-{task_id}`。
- runner `executor_test.go:33,49` 已有 `env_FRIDAY_TASK_BRANCH_STRATEGY` 透传断言——确认这是 runner 既测契约，server 注入即生效。

**结论：** 对齐这些键即可修复「私有仓 clone 失败 + 落默认 `friday/task-{id}` 分支」，无需改 task/runner。

---

## RESUME-01：D-2 两处缺口精确定位

**缺口 (a) — barrier 未通知（`callbacks.py:124-134`）：**
```python
# _schedule_agent_session_resume 内：
if src == "plan_research":
    log.debug("plan_research_skip_agent_resume", ...)
    return   # ← chat 入口（无 node_execution）的 plan_research 容器完成后，从不通知 chat barrier
```
chat 入口 `start_plan_research._maybe_suspend`（`plan_research_tools.py:243-271`）在 `researching` 处 `register_blocking_task(conversation_id, {"task_id": str(session.id), "task_type": "plan_research", ...})` 并返回 `__blocking_task__` marker。orchestration graph 据 marker 注册 BarrierManager barrier（`conversation_service._handle_waiting_state:596-604`，**`task_id = str(plan_session.id)`**），LangGraph `interrupt` 挂起会话。但容器完成后无人调 `barrier.task_completed(str(plan_session.id), ...)` → barrier 永不满足 → 会话永不 resume。

**缺口 (b) — engine 未续驱（`research_aggregation.py:73-88`）：**
`_handle_research_completion`（`callbacks.py:1269-1325`）→ `_trigger_research_barrier` → `amaybe_complete_research` 只把 `researching → merging`。工作流入口此后由挂起节点重跑续驱（`_schedule_workflow_resume` → 节点 `execute` 内 advance 循环 merging→done）；**chat 入口无 node_execution、无消费者驱动 `engine.advance`** → session 卡在 `merging` 永不到 `done`。

**为何工作流入口已闭环（对照）：**
- `AIPlanResearchNode._build_engine`（`plan_research.py:242-254`）透传 `node_execution_id` → 调研 SubAgentSession 关联 node_execution。
- 容器完成 → `_schedule_workflow_resume`（`callbacks.py:193-282`）检查节点所有 SubAgentSession 终态 → 写 `_resume_from_callback` → `engine._continue_after_node` → 重跑节点 → 节点 `execute` 的 advance 循环把 session 推到 done → `NodeResult completed` → 续跑工作流下游。
- chat 入口的调研 SubAgentSession **无 `node_execution_id`**（`build_orchestration_engine()` 不传），故 `_schedule_workflow_resume` 在 `callbacks.py:199` 提前 return——这是正确的（chat 不该走 workflow resume），但留下了 chat 侧的空洞。

## RESUME-01：推荐方案（同源续驱 + barrier 回灌，复用既有范式不造两套）

### 步骤 1 — 抽入口无关的 engine 续驱 helper（消化「不造两套」）

新增（Discretion：放 `services/plan_orchestration/resume.py` 或 `entrypoint.py`）：
```python
async def adrive_plan_session_to_pause_or_terminal(engine, session, *, max_steps=20):
    """复用 AIPlanResearchNode.execute / start_plan_research 的同一 advance 循环：
    advance + 重读 status，遇终态({DONE,FAILED})或重挂起条件(researching 仍有在途 /
    clarifying 有 pending)即返回。入口无关——不含任何 workflow/chat IO。"""
    from delivery.models import PlanSession, PlanSessionStatus
    from services.plan_orchestration import aall_research_tasks_terminal
    terminal = {PlanSessionStatus.DONE, PlanSessionStatus.FAILED}
    steps = 0
    while session.status not in terminal:
        steps += 1
        if steps > max_steps:
            await engine.session_service.transition(session, "fail",
                error={"reason": "advance_step_limit", "steps": steps})
            return await PlanSession.objects.aget(id=session.id)
        # 重挂起短路：researching 仍有在途调研 → 不再 advance（等下一次容器回调）
        if session.status == PlanSessionStatus.RESEARCHING \
           and not await aall_research_tasks_terminal(session.id):
            return session
        # （clarifying pending 也可在此短路；本 phase 调研回流主路径聚焦 researching）
        await engine.advance(session)
        session = await PlanSession.objects.aget(id=session.id)
    return session
```
该 helper 抽自 `plan_research.py:142-167` 与 `plan_research_tools.py:125-153` 的**重复 advance 循环**——三处（工作流节点 / chat 工具 / 回调消费者）复用同一份，落「底层续驱同源」。工作流节点与 chat 工具的入口私有挂起映射（`NodeResult` / `ToolResult` marker）仍各自保留（驱动是入口私有，对齐 `entrypoint.py` docstring 精神）。

### 步骤 2 — 新增 chat 回调消费者 `_schedule_chat_plan_resume`（mirror `_schedule_workflow_resume`）

在 `callbacks.py` 新增（与 `_schedule_workflow_resume` 对称、fire-and-forget、幂等、fail-soft）：
```python
def _schedule_chat_plan_resume(session: SubAgentSession, log) -> None:
    """chat 入口 plan_research 容器完成 → 续驱 engine 到终态 + 回灌 chat barrier。
    仅当：plan_research source + 无 node_execution(=chat 入口) + 关联 PlanSession.entrypoint==chat。"""
    async def _resume():
        try:
            # 1. 取 plan_session（从 last_output.plan_session_id；entrypoint==chat 守门）
            # 2. 调研全终态才续驱（aall_research_tasks_terminal）→ 幂等
            # 3. engine = build_orchestration_engine()（无 node_execution_id）
            #    session = await adrive_plan_session_to_pause_or_terminal(engine, session)
            # 4. 仅当 session 到 DONE/FAILED → 构建 BlockingTaskResult(task_id=str(plan_session.id),
            #    task_type="plan_research", success=(status==DONE), output=<主方案摘要/plan_version_id>,
            #    error=<failed 时 session.error>)
            # 5. get_barrier_manager().task_completed(str(plan_session.id), result)
            #    （barrier 已去重：task_id 已在 results → 返回 False no-op，幂等安全）
            ...
        except Exception:  # noqa: BLE001 — 永不阻塞回调主流程
            log.warning("chat_plan_resume_error", session_id=session.session_id)
    try:
        loop = asyncio.get_running_loop(); loop.create_task(_resume())
    except RuntimeError:
        asyncio.run(_resume())
```

### 步骤 3 — 接线（`_handle_completed` / `_handle_failed`）

两个落点二选一（planner 按最小 diff 定）：
- **选项 A（推荐，最小耦合）**：在 `_schedule_agent_session_resume` 的 `plan_research` 分支，把当前的 `return` 替换为「若关联 PlanSession 为 chat 入口 → `_schedule_chat_plan_resume(session, log)`」。该分支已在 `_handle_completed:654` / `_handle_failed:715` 被调用，天然覆盖 completed + failed 两路。
- **选项 B**：在 `_handle_research_completion` / `_handle_research_failure` 末尾（`_trigger_research_barrier` 之后）追加 chat 续驱（已持有 plan_session + 已知 entrypoint）。

> 注意时序：续驱（engine.advance → merge → architect LLM）须在 `barrier.task_completed` **之前**完成，使 `BlockingTaskResult.output` 能携带最终主方案/`plan_version_id`。故续驱与 notify 在同一 `_resume()` 协程内顺序执行。

### 幂等 + fail-soft 保证（对齐 CONTEXT）
- `amaybe_complete_research` status guard：仅 `researching` 且全终态才转 merging（重复回调 no-op）。
- `adrive_*` 在 `researching` 仍有在途时短路：多仓调研逐个完成时，只有最后一个（使全终态）真正续驱。
- `BarrierManager.task_completed`：`task_id in barrier.results` → 返回 False（重复回调不重放 resume）。
- `PlanSessionService.transition` 条件更新（`updated != 1` → `ConcurrentTransitionError`）：并发推进良性 no-op（engine handler 已 catch，见 `engine.py:224-231,282-285`）。
- 全程独立 try/except swallow + warning。

### 已知 race（文档化，沿用既有 deferred）
容器在 barrier 注册前完成（dispatch→graph 注册 barrier 的窗口）→ `task_completed` 返回 False。此 race 对 deep_analysis 已存在且被接受；真实容器 E2E 沿用既有「需真实 runner + Docker」deferred（STATE.md Deferred Items）。本 phase 以 mock IO 边界测试覆盖闭环，不解决 race（留 Phase 44+ 若需）。

### 文案更新（Discretion）
接通后 `start_plan_research` 的 `_maybe_suspend` placeholder 文案（`plan_research_tools.py:262-270`）+ 工具 description（`:41`）的「自动回流尚未接入」应如实改为「调研完成后自动融合回流」，避免误导。

## Common Pitfalls

### Pitfall 1: nested metadata dict 不被 runner 消费
**What goes wrong:** 把 git 凭证放进 `metadata["git_credentials"]` dict，容器永远拿不到。
**Why:** runner 只 TrimPrefix 顶层 `env_` string 键（`executor.go:158-161`）。
**How to avoid:** 一律用顶层 `env_FRIDAY_TASK_*` string 键。
**Warning signs:** 私有仓 clone 401/403；容器日志无 token auth。

### Pitfall 2: runner 只下传 string 且非空的 env 值
**What goes wrong:** 注入了非 string（如 bool）或空串值的 `env_` 键，被静默丢弃。
**Why:** `executor.go:160` `if s, ok := v.(string); ok && s != ""`。
**How to avoid:** ssl_verify 等用字符串 `"false"`/`"true"`（chat 基线即如此）；空 token 不注入键（缺凭证降级）。

### Pitfall 3: chat barrier 的 task_id 是 PlanSession.id 而非 SubAgentSession.session_id
**What goes wrong:** 误用调研容器的 `session.session_id` 去 notify barrier，barrier 找不到任务静默 False。
**Why:** chat 入口 `register_blocking_task` 用 `task_id=str(plan_session.id)`（`plan_research_tools.py:249`）；deep_analysis 才用 SubAgentSession id。
**How to avoid:** `_schedule_chat_plan_resume` 必须用 `barrier.task_completed(str(plan_session.id), ...)`。

### Pitfall 4: 续驱与 barrier notify 时序颠倒
**What goes wrong:** 先 notify barrier 再续驱，会灌出 status=merging 的半成品/空 plan_version。
**How to avoid:** 同一协程内先 `adrive_*` 到终态，再 notify。

### Pitfall 5: 凭证/明文进日志
**How to avoid:** 仅记 `has_token` 布尔（`coding_session_service` / `coding.py` 既有范式）；`redact_credentials` structlog processor 兜底但代码须自律。

### Pitfall 6: 直接写 session.status 绕过 transition
**How to avoid:** 一律经 `PlanSessionService.transition`（§14 转移表 + 条件更新幂等）。

## Code Examples

### PF-06 注入对齐（mirror chat build_dispatch_metadata，落在 `_run_repo_coding`）
```python
# Source 基线: server/chat/coding_session_service.py:170-187
# 目标: server/workflows/nodes/ai/coding.py _run_repo_coding 内（branch_name=本仓工作分支, base_branch=目标分支）
repo_url = repository.git_url
token = await aresolve_git_token(repository)
git_env: dict[str, str] = {}
if token:
    git_env["env_FRIDAY_TASK_GIT_ACCESS_TOKEN"] = token
    git_env["env_FRIDAY_TASK_GIT_AUTH_TYPE"] = "token"
    git_env["env_FRIDAY_TASK_GIT_SSL_VERIFY"] = "false"  # 或 per-repo credential.ssl_verify，见 Open Q1
    if repo_url.startswith("git@"):  # SSH→HTTPS（token 认证需 HTTPS）
        m = re.match(r"git@([^:]+):(.+?)(?:\.git)?$", repo_url)
        if m:
            repo_url = f"https://{m.group(1)}/{m.group(2)}.git"
branch_env = {
    "env_FRIDAY_TASK_BRANCH_STRATEGY": branch_name,   # 本仓工作分支（多仓 per-repo）
    "env_FRIDAY_TASK_TARGET_BRANCH": base_branch,      # 目标/base 分支
}
# DispatchTask(repo_url=repo_url, ..., metadata={..., **git_env, **branch_env, "git_credentials": git_credentials(保留)})
```
只记布尔：`log.info("task_dispatched_to_runner", has_git_token=bool(token), ...)`。

### RESUME-01 barrier 回灌（BlockingTaskResult 形态，对齐 `_notify_barrier_manager`）
```python
# Source 范式: server/subagent/api/callbacks.py:74-83
from orchestration.barrier import get_barrier_manager
from orchestration.contracts import BlockingTaskResult
result: BlockingTaskResult = {
    "task_id": str(plan_session.id),          # chat barrier 注册键
    "task_type": "plan_research",
    "success": plan_session.status == PlanSessionStatus.DONE,
    "output": <主方案摘要 / plan_version_id 文本>,  # 复用 deep_analysis 回灌通道
    "error": "" if success else str(plan_session.error or {}),
}
await get_barrier_manager().task_completed(str(plan_session.id), result)  # 已去重，幂等
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| 容器分支默认 `friday/task-{id}` | server 经 `FRIDAY_TASK_BRANCH_STRATEGY` 传模板分支 | task `operations.py` Bug 修复（见 docstring:444-453） | workflow 路径未注入该键 → 仍落默认（PF-06 待修） |
| chat plan_research fire-and-forget「自动回流尚未接入」 | callback 驱动 chat 续驱 + barrier 回灌 | 本 phase（RESUME-01） | 接通后更新工具文案 |

**Deprecated/outdated:**
- workflow 路径 `metadata["git_credentials"]` nested dict：runner 从不消费（dead payload）；PF-06 保留它仅为零回归，真正生效的是新增 `env_` 键。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `git_ssl_verify` 对齐 chat 基线用字符串 `"false"`（而非 per-repo `credential.ssl_verify`） | PF-06 差异表 / Open Q1 | 自签名证书内部 Git 服务器若需 per-repo 值会被覆盖；但 chat 基线即 `"false"`，task 默认也 False，风险低。planner 可选保留 per-repo 值。 |
| A2 | chat 入口续驱后用 `BlockingTaskResult.output` 回灌主方案摘要即满足 chat 呈现 | RESUME-01 步骤 2 | 若需更丰富的 RoutingDecisionPanel 式结构化回灌，需额外格式化（参考 cross_repo_relevance 的 TaskResult 追加范式 `callbacks.py:1197-1206`）。不阻塞闭环。 |
| A3 | 多仓 `_run_repo_coding` 各仓 `branch_name` 即应作为该仓 `BRANCH_STRATEGY`（当前多仓共用同名 branch 是既有行为，本 phase 不改命名策略） | PF-06 多仓差异 | 若 Phase 44 引入 per-repo 独立分支命名需再调；本 phase 仅正确下传已解析值，不引入新策略。 |

## Open Questions

1. **`env_FRIDAY_TASK_GIT_SSL_VERIFY` 取值：chat 基线硬编码 `"false"` vs workflow 现有 nested dict 的 per-repo `credential.ssl_verify`？**
   - What we know：chat `build_dispatch_metadata:175` 硬编码 `"false"`；workflow nested dict（`coding.py:927-931`）取 per-repo `credential.ssl_verify`（fallback `"true"`）；task 默认 `git_ssl_verify=False`。
   - What's unclear：是否有依赖 per-repo `ssl_verify=true` 的内部仓。
   - Recommendation：对齐 chat 基线 `"false"`（CONTEXT「以 chat 为权威基线」）；如 planner 认为 per-repo 更稳，可传 `str(credential.ssl_verify).lower()`——两者都满足「token 认证 + 自签名证书」主场景。低风险，倾向 `"false"`。

2. **`_schedule_chat_plan_resume` 接线落点（选项 A vs B）。**
   - Recommendation：选项 A（`_schedule_agent_session_resume` plan_research 分支）——已覆盖 completed+failed 两路、改动最小、与 `_schedule_workflow_resume`/`_notify_barrier_manager` 并列语义最清晰。

3. **chat 入口最终主方案如何呈现回对话（输出格式）。**
   - Recommendation：复用 deep_analysis 既有回灌通道（`BlockingTaskResult.output` 文本 + 可选 plan_version_id），不新造前端组件（CONTEXT Discretion）。

## Environment Availability

**SKIPPED（无外部依赖）** —— 本 phase 是纯 server 代码接线，不新增 CLI/服务/运行时依赖。容器/runner 侧契约只读核对、不改。真实容器 E2E 沿用既有 deferred（需真实 runner + Docker）。

## Validation Architecture

> `.planning/config.json` `workflow.nyquist_validation = true` → 本段适用。

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.x + pytest-asyncio（`asyncio_mode=auto`） + pytest-django（`DJANGO_SETTINGS_MODULE=friday.settings`） |
| Config file | `server/pyproject.toml` `[tool.pytest.ini_options]`（`testpaths=["tests"]`, `--disable-socket --allow-unix-socket`，默认排除 `perf/integration/slow`） |
| Quick run command | `cd server && uv run pytest tests/test_coding_node.py tests/services/test_research_completion_callback.py -x` |
| Full suite command | `cd server && uv run pytest` |
| DB marker | `@pytest.mark.django_db(transaction=True)`（异步 + 多协程回调需 transaction=True） |
| Network isolation | `pytest-socket` 强制；容器/runner/LLM 全 mock（IO 边界） |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PF-06 | `_run_repo_coding` dispatch metadata 含 `env_FRIDAY_TASK_GIT_ACCESS_TOKEN/AUTH_TYPE/SSL_VERIFY`（token 非空时） | unit | `uv run pytest tests/test_coding_node.py -k git_env -x` | ❌ Wave 0（扩展既有 `tests/test_coding_node.py`） |
| PF-06 | `env_FRIDAY_TASK_BRANCH_STRATEGY` == 本仓 `branch_name`，`TARGET_BRANCH` == `base_branch` | unit | `uv run pytest tests/test_coding_node.py -k branch_strategy -x` | ❌ Wave 0 |
| PF-06 | SSH `git@` repo_url → `https://...` 改写（token 非空）；token 空时不注入 access_token 键且不改写（降级不回退） | unit | `uv run pytest tests/test_coding_node.py -k ssh_https -x` | ❌ Wave 0 |
| PF-06 | token 绝不入日志（断言 log 仅 `has_*` 布尔） | unit | `uv run pytest tests/test_coding_node.py -k no_token_leak -x` | ❌ Wave 0 |
| PF-06 | nested `git_credentials` dict 保留（零回归） | unit | 同上文件 | ❌ Wave 0 |
| RESUME-01 | chat 入口 plan_research 容器全终态 → engine 续驱 PlanSession 到 `done`（mock merge adapter） | integration | `uv run pytest tests/services/test_research_completion_callback.py -k chat_resume_done -x` | ❌ Wave 0（扩展既有文件，已有 `_setup` chat-entry fixture） |
| RESUME-01 | 续驱到终态后 `BarrierManager.task_completed(plan_session_id)` 被调用（mock/真 barrier 注册后断言 satisfied） | integration | `uv run pytest tests/services/test_research_completion_callback.py -k barrier_notified -x` | ❌ Wave 0 |
| RESUME-01 | 工作流入口 plan_research（有 node_execution）**不**走 chat 续驱（仍走 `_schedule_workflow_resume`，回归守护） | integration | `uv run pytest tests/services/test_research_completion_callback.py -k workflow_not_chat -x` | ❌ Wave 0 |
| RESUME-01 | 幂等：重复 completed 回调 / 部分调研未终态 → 不重复续驱、不重复 notify（no-op） | integration | `uv run pytest tests/services/test_research_completion_callback.py -k idempotent -x` | ❌ Wave 0 |
| RESUME-01 | fail-soft：续驱内部抛异常 → 回调仍返 200（swallow） | integration | `uv run pytest tests/services/test_research_completion_callback.py -k swallow -x` | ✅ 既有「回调异常 swallow 返 200」可扩展 |
| RESUME-01 | 失败路径：plan_research 容器 failed → 续驱/或直接 barrier success=False 回灌（不卡死） | integration | `uv run pytest tests/services/test_research_completion_callback.py -k failed_path -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `cd server && uv run pytest tests/test_coding_node.py tests/services/test_research_completion_callback.py -x`
- **Per wave merge:** `cd server && uv run pytest tests/test_coding_node.py tests/services/ tests/workflows/test_plan_research_node.py tests/agents/test_start_plan_research_tool.py tests/services/test_orchestration_entry_consistency.py`
- **Phase gate:** `cd server && uv run pytest` 全绿 before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_coding_node.py` — 新增 PF-06 dispatch metadata env 键集合断言（git token env + branch strategy + target branch + SSH→HTTPS + no-token 降级 + 不泄漏）。既有文件，已有 dispatch mock 范式（参考 `tests/chat/test_coding_exclusion_env.py` 的 env 键断言风格 + `test_coding_anthropic_base_url_passthrough.py`）。
- [ ] `tests/services/test_research_completion_callback.py` — 新增 chat 入口续驱 + barrier 回灌闭环测试（已有 `_setup` chat-entry fixture + `_PATCHES` mock 范式，需放开 `_schedule_agent_session_resume` mock 或新增针对 `_schedule_chat_plan_resume` 的断言；mock merge adapter 把 merging→done）。
- [ ] 共享续驱 helper 若新建 `services/plan_orchestration/resume.py` → 新增 `tests/services/test_plan_resume_driver.py` 单测（advance 循环：终态返回 / researching 在途短路 / step 上限 fail）。
- [ ] 框架已就绪，无需安装。

## Security Domain

> `security_enforcement = true` → 本段适用。

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | 不涉登录/会话认证（容器回调用 `CONTAINER_CALLBACK_TOKEN`，既有，不改） |
| V3 Session Management | no | — |
| V4 Access Control | partial | 容器回调端点 `AllowAny` + token 校验（`callbacks.py:404-411`，既有）；resume 不放大权限面 |
| V5 Input Validation | yes | callback payload 经 `CompletedPayloadSerializer`/`FailedPayloadSerializer` 校验（既有）；`last_output` 半可信（runner 可经 progress 篡改），见下 |
| V6 Cryptography | yes | git token 经 `aresolve_git_token` 取（Fernet 解密在解析器内），**绝不**内联 decrypt、绝不入日志；`redact_credentials` structlog processor 兜底 |

### Known Threat Patterns for Django async callback + dispatch env
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| git token 泄漏进日志/trace | Information Disclosure | 只记 `has_token` 布尔；token 仅进 dispatch payload；structlog `redact_credentials` 兜底 |
| runner 经 `last_output` 篡改 `plan_session_id`/`research_task_id` 越权驱动他人 session | Tampering / Elevation | 既有 `_aload_research_task` 按 id 读取（Phase 39 范式）。**新增** chat 续驱须以 `PlanSession.entrypoint==chat` 守门 + `RepoResearchTask` 归属该 session 校验（沿用 cross_repo_relevance 用「服务端权威字段」而非 runner 可改字段的范式，`callbacks.py:1121-1126`）。本 phase 不放大既有信任面，但 planner 须显式守门 entrypoint。 |
| SSH→HTTPS 改写注入（恶意 repo_url） | Tampering | `repository.git_url` 来自服务端 DB（非 runner 输入），改写正则锚定 `git@host:path`，无注入面 |
| resume 副作用让回调 5xx / DoS | Denial of Service | fire-and-forget + 独立 try/except swallow；barrier/transition 幂等去重防重放 |

## Sources

### Primary (HIGH confidence) — 代码库内核对
- `server/workflows/nodes/ai/coding.py`（`_run_repo_coding` PF-06 注入点 + waiting_event/resume）
- `server/chat/coding_session_service.py`（`build_dispatch_metadata` PF-06 权威基线）
- `server/subagent/api/callbacks.py`（`_handle_completed/_handle_failed`、`_schedule_workflow_resume`、`_schedule_agent_session_resume`、`_handle_research_completion/_failure`、`_notify_barrier_manager`）
- `server/agents/tools/plan_research_tools.py`（chat 入口 + `__blocking_task__` + register_blocking_task + 占位文案）
- `server/workflows/nodes/ai/plan_research.py`（工作流入口节点 advance 循环 + node_execution_id 透传）
- `server/services/plan_orchestration/{engine.py,entrypoint.py,research_aggregation.py}`（engine.advance / 共用 engine 构造 / amaybe_complete_research）
- `server/orchestration/barrier.py`（BarrierManager.register/task_completed/on_complete）
- `server/chat/conversation_service.py`（`_handle_waiting_state` barrier 注册 + `_on_barrier_complete` LangGraph resume 回灌）
- `server/orchestration/graph.py`（`_extract_blocking_tasks` / waiting_node interrupt）
- `server/agents/tools/blocking_task_registry.py`、`server/tasks/agent_tasks.py`（register/drain + schedule_resume_agent_session）
- `server/delivery/services/plan_session_service.py`、`server/delivery/models/plan_session.py`（transition 条件更新幂等 + entrypoint 字段）
- `task/core/config.py`、`task/git_ops/operations.py`、`task/cli/commands.py`（容器侧 env 消费契约）
- `runner/internal/docker/executor.go`、`runner/internal/docker/executor_test.go`（`env_` TrimPrefix 契约 + branch strategy 透传既测）
- `server/tests/services/test_research_completion_callback.py`、`server/tests/workflows/test_engine_waiting.py`、`server/pyproject.toml`（测试范式 + pytest 配置）

### Secondary (MEDIUM confidence)
- 无（无外部检索；全部一手代码核对）

### Tertiary (LOW confidence)
- 无

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 无新包，全部既有模块路径/行号核对。
- Architecture（PF-06 env 差异 + RESUME-01 缺口/方案）: HIGH — server/task/runner 三侧消费契约逐一 grep 核对，缺口在源码中精确定位（行号引用）。
- Pitfalls: HIGH — 均来自代码内既有注释/契约（runner string-only TrimPrefix、barrier task_id=plan_session.id、transition 条件更新）。
- Security: MEDIUM-HIGH — 复用既有信任面与脱敏范式；新增 entrypoint 守门为推荐项，需 planner 落实。

**Research date:** 2026-06-16
**Valid until:** 2026-07-16（稳定内部代码；若 Phase 44 引入 RepoCodingTask/wave 调度会改动 dispatch 形态，届时复核）
