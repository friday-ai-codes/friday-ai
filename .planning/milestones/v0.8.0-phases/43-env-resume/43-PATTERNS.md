# Phase 43: 编码 env 对齐 + 通用 resume 回流地基 - Pattern Map

**Mapped:** 2026-06-16
**Files analyzed:** 8 (3 source modify/create + 1 new helper + 2 optional touch-ups + 2 test files + 1 optional new test)
**Analogs found:** 8 / 8（全部在库内同文件 / 同 app 找到强分析对象 — 本 phase 是「接线」，无新范式）

> 本 phase 无新模型 / 无 migration / 无新依赖。所有改动都在「逐键对齐 chat 基线」与「mirror 既有 callback resume 范式」两条已知通路上。Planner 应优先**照搬同文件 / 同 app 的既有写法**，而非重新设计。

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `server/workflows/nodes/ai/coding.py` (`_run_repo_coding`) | workflow node / dispatch builder | request-response (fan-out 多仓 dispatch) | `server/chat/coding_session_service.py` `build_dispatch_metadata` | exact（同一 dispatch metadata 构造语义，仅单仓 vs 多仓差异） |
| `server/services/plan_orchestration/resume.py`（新建，Discretion） | service helper | state-driven advance loop / transform | `plan_research.py` execute 循环 + `plan_research_tools.py` `start_plan_research` 循环 | exact（抽两处重复 advance 循环） |
| `server/subagent/api/callbacks.py` (`_schedule_chat_plan_resume` + 接线) | API callback consumer | event-driven (fire-and-forget) | 同文件 `_schedule_workflow_resume` + `_notify_barrier_manager` | exact（对称 mirror，同文件并列语义） |
| `server/agents/tools/plan_research_tools.py`（文案 + 可选 helper 复用） | chat tool | request-response | 同文件 `_maybe_suspend` placeholder（:262-270） | exact（同文件就地改文案） |
| `server/workflows/nodes/ai/plan_research.py`（可选 helper 复用） | workflow node | state-driven advance loop | 自身 execute 循环（:142-167） | exact（行为零变更，仅抽公共循环） |
| `server/tests/test_coding_node.py`（扩展） | test | unit | 同文件 `TestAICodingNode` + `tests/chat/test_coding_exclusion_env.py` env 键断言 | role-match（既有 dispatch mock 范式，需改为断言真实 metadata 键） |
| `server/tests/services/test_research_completion_callback.py`（扩展） | test | integration | 同文件 `_setup` chat-entry fixture + `_PATCHES` mock 范式 | exact（同文件直接扩展） |
| `server/tests/services/test_plan_resume_driver.py`（新建，仅当 helper 落 resume.py） | test | unit | `test_research_completion_callback.py` mock 范式 | role-match |

---

## Pattern Assignments

### `server/workflows/nodes/ai/coding.py` — `_run_repo_coding` (PF-06 env 注入对齐)

**Analog:** `server/chat/coding_session_service.py` `build_dispatch_metadata`（权威基线）
**当前缺陷位置:** `coding.py:924-935`（git_credentials nested dict，runner 不读）+ `coding.py:988-997`（metadata 缺 `env_FRIDAY_TASK_GIT_*` / `BRANCH_STRATEGY` / `TARGET_BRANCH`）

**基线 — git token env + SSH→HTTPS 改写**（照搬 `coding_session_service.py:168-180`）：

```168:180:server/chat/coding_session_service.py
    repo_url = repository.git_url

    # Git 凭据（Phase 26 REPO-01：统一经解析器取 token，无 per-repo token 时按 host 用实例凭证）
    token = await aresolve_git_token(repository)
    if token:
        env_metadata["env_FRIDAY_TASK_GIT_ACCESS_TOKEN"] = token
        env_metadata["env_FRIDAY_TASK_GIT_AUTH_TYPE"] = "token"
        env_metadata["env_FRIDAY_TASK_GIT_SSL_VERIFY"] = "false"
        # SSH URL -> HTTPS（token 认证需要 HTTPS）
        if repo_url.startswith("git@"):
            m = re.match(r"git@([^:]+):(.+?)(?:\.git)?$", repo_url)
            if m:
                repo_url = f"https://{m.group(1)}/{m.group(2)}.git"
```

**基线 — branch strategy / target branch env**（照搬 `coding_session_service.py:186-187`，注意多仓取值差异）：

```186:187:server/chat/coding_session_service.py
    env_metadata["env_FRIDAY_TASK_BRANCH_STRATEGY"] = execution_spec.work_branch
    env_metadata["env_FRIDAY_TASK_TARGET_BRANCH"] = execution_spec.target_branch
```

> **多仓取值映射（关键差异，A3 假设）：** chat 是单仓（`execution_spec.work_branch`）；workflow 是 fan-out 多仓，`_run_repo_coding` 签名已带参数（`coding.py:899-900`）。逐键映射为：
> - `env_FRIDAY_TASK_BRANCH_STRATEGY` = **本次调用的 `branch_name`** 参数（本仓工作分支）
> - `env_FRIDAY_TASK_TARGET_BRANCH` = **本次调用的 `base_branch`** 参数（目标/base 分支）
> - `repo_url` 改写后须传给 `DispatchTask(repo_url=...)`（当前 `coding.py:981` 直传 `repository.git_url`，须改用改写后的局部变量）

**保留既有 nested dict（零回归）+ 注入点**（修改 `coding.py:988-997` 的 metadata dict，把新 git_env/branch_env 并入；`git_credentials` 保留）：

```988:997:server/workflows/nodes/ai/coding.py
            metadata={
                "repository_id": str(repository.id),
                "repository_name": repository.name,
                "work_item_id": config.get("work_item_id", ""),
                "git_credentials": git_credentials,
                **anthropic_env,   # env_FRIDAY_TASK_CLAUDE_API_KEY + env_FRIDAY_TASK_CLAUDE_BASE_URL
                **tools_env,       # RTOOL-03：env_FRIDAY_TASK_TOOLS_ENDPOINT + 机会性 env_FRIDAY_TASK_USER_TOKEN
                **exclude_env,     # Phase 22-04：env_FRIDAY_TASK_EXCLUDE_PATTERNS（容器侧 prune）
            },
```

> Planner 动作：在已有 `token = await aresolve_git_token(repository)`（`coding.py:925`）的基础上**新增** `git_env` dict（顶层 `env_FRIDAY_TASK_GIT_*` 键）+ `branch_env` dict（`BRANCH_STRATEGY`=`branch_name` / `TARGET_BRANCH`=`base_branch`）+ SSH→HTTPS 改写，再 `**git_env, **branch_env` 并入上面的 metadata，`git_credentials` nested dict 原样保留。`DispatchTask(repo_url=<改写后>)`。

**日志范式（仅记布尔，对齐 `coding.py:1040-1046`）：**

```1040:1046:server/workflows/nodes/ai/coding.py
            # 仅记 boolean，绝不记敏感值（PAT 明文/endpoint 明文不入日志，per Pitfall 4）
            log.info(
                "task_dispatched_to_runner",
                session_id=session_id,
                has_tools_endpoint=bool(base),
                has_user_token=bool(user_pat),
            )
```

> Planner 动作：追加 `has_git_token=bool(token)`（绝不记 token 本身）。

**SSL_VERIFY 取值（Open Q1）：** 基线硬编码 `"false"`。当前 workflow nested dict 取 per-repo `str(repository.credential.ssl_verify).lower()`（`coding.py:927-931`）。推荐对齐基线 `"false"`（CONTEXT「以 chat 为权威基线」）；若 planner 保留 per-repo，须确保是字符串（runner 仅透传 string 且非空）。

---

### `server/services/plan_orchestration/resume.py` — `adrive_plan_session_to_pause_or_terminal`（新建共享 helper，RESUME-01 步骤 1）

**Analog 1（工作流节点 advance 循环）:** `server/workflows/nodes/ai/plan_research.py:142-167`

```142:167:server/workflows/nodes/ai/plan_research.py
        terminal = {PlanSessionStatus.DONE, PlanSessionStatus.FAILED}
        steps = 0
        while session.status not in terminal:
            steps += 1
            if steps > _MAX_ADVANCE_STEPS:
                log.warning("plan_research_advance_step_limit", session_id=str(session.id))
                await engine.session_service.transition(
                    session,
                    "fail",
                    error={"reason": "advance_step_limit", "steps": steps},
                )
                session = await PlanSession.objects.aget(id=session.id)
                break

            await engine.advance(session)
            session = await PlanSession.objects.aget(id=session.id)

            suspend = await self._maybe_suspend(session)
            if suspend is not None:
                ...
                return suspend
```

**Analog 2（chat 工具 advance 循环，逐行同构）:** `server/agents/tools/plan_research_tools.py:124-153`（同样的 `terminal`/`steps`/`_MAX_ADVANCE_STEPS`/`transition fail`/`engine.advance`/`_maybe_suspend` 结构）

**重挂起短路判定（研究在途）:** 两处 `_maybe_suspend` 都用 `aall_research_tasks_terminal`（`research_aggregation.py:57-70`）判定 researching 是否仍在途：

```57:70:server/services/plan_orchestration/research_aggregation.py
async def aall_research_tasks_terminal(session_id: Any) -> bool:
    """该 session 至少有一个 RepoResearchTask 且无任何在途态（全部 done/failed）。

    无任何 task → 返回 True（无需调研，直接可推进）。
    """
    from delivery.models import RepoResearchTask

    total = await RepoResearchTask.objects.filter(session_id=session_id).acount()
    if total == 0:
        return True
    pending = await RepoResearchTask.objects.filter(
        session_id=session_id, status__in=_PENDING_STATUSES
    ).aexists()
    return not pending
```

> Planner 动作：抽一个**入口无关**的 `async def adrive_plan_session_to_pause_or_terminal(engine, session, *, max_steps=20)`，内部即 analog 1/2 的 while 循环 + step 上限 fail，但**剔除入口私有的 `_maybe_suspend`/`NodeResult`/`ToolResult` 映射**——改为：`researching` 且 `not await aall_research_tasks_terminal(session.id)` 时 `return session`（重挂起短路），否则 `engine.advance` + 重读，直到终态 `{DONE, FAILED}`。工作流节点 / chat 工具仍各自保留其私有挂起 marker 映射（驱动是入口私有，对齐 `entrypoint.py` docstring：「helper 不驱动 engine.advance……驱动是入口私有」）。
> **engine 构造复用** `build_orchestration_engine()`（`entrypoint.py:55-84`，chat 入口不传 `node_execution_id`），**绝不**新建第二个 engine 工厂。
> **状态转移只经 `engine.session_service.transition`**（见 analog 1 的 fail 分支），绝不直接写 `session.status`。

---

### `server/subagent/api/callbacks.py` — `_schedule_chat_plan_resume` + 接线（RESUME-01 步骤 2/3）

**Analog（结构蓝本，fire-and-forget + 幂等 + fail-soft）:** 同文件 `_schedule_workflow_resume`（`callbacks.py:193-282`）

**fire-and-forget 调度尾部范式**（照搬 `callbacks.py:277-282`）：

```277:282:server/subagent/api/callbacks.py
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_resume())
    except RuntimeError:
        # 没有运行中的事件循环，创建新的
        asyncio.run(_resume())
```

**Analog（barrier 回灌 — BlockingTaskResult 形态）:** 同文件 `_notify_barrier_manager`（`callbacks.py:54-97`）

```74:89:server/subagent/api/callbacks.py
            result: BlockingTaskResult = {
                "task_id": session.session_id,
                "task_type": session.task_type or "deep_analysis",
                "success": is_success,
                "output": output_text,
                "error": error_text,
            }

            barrier = get_barrier_manager()
            satisfied = await barrier.task_completed(session.session_id, result)
            log.info(
                "barrier_task_notified",
                session_id=session.session_id,
                success=is_success,
                barrier_satisfied=satisfied,
            )
```

> **关键差异（Pitfall 3）：** chat 入口 plan_research barrier 注册时 `task_id = str(plan_session.id)`（`plan_research_tools.py:249`），**不是** `session.session_id`。`_schedule_chat_plan_resume` 必须 `barrier.task_completed(str(plan_session.id), result)`，`BlockingTaskResult["task_id"] = str(plan_session.id)`、`task_type="plan_research"`、`success=(status==DONE)`。

**接线落点（选项 A，推荐）：** 把 `_schedule_agent_session_resume` 的 plan_research 分支当前的 `return` 替换为「chat 入口守门 → `_schedule_chat_plan_resume`」：

```121:134:server/subagent/api/callbacks.py
        if src == "plan_research":
            # ... （现状注释保留）
            log.debug("plan_research_skip_agent_resume", session_id=session.session_id)
            return
```

> Planner 动作：该分支已在 `_handle_completed:654` 与 `_handle_failed:715` 两路被调用（天然覆盖 completed + failed）。改为：取 plan_session（从 `session.last_output["plan_session_id"]`）→ 守门 `PlanSession.entrypoint == chat`（V4/Tampering 缓解，绝不信 runner 可改字段）→ 调 `_schedule_chat_plan_resume(session, log)`。**绝不**在此触发 SDKAgentRunner resume（现状注释说明的幽灵 agent 风险）。

**`_schedule_chat_plan_resume` 内部时序（Pitfall 4，同协程内顺序）：**
1. 取 plan_session（`last_output["plan_session_id"]`）；`entrypoint == chat` + 无 node_execution 守门。
2. `if not await aall_research_tasks_terminal(plan_session.id): return`（幂等短路 — 多仓逐个完成时只有最后一个真正续驱）。
3. `engine = build_orchestration_engine()`（无 node_execution_id）。
4. `session = await adrive_plan_session_to_pause_or_terminal(engine, plan_session)`（**先**续驱到终态）。
5. **再** `await get_barrier_manager().task_completed(str(plan_session.id), result)`（barrier 已去重：`task_id in results` → False no-op）。
6. 全程包在 `try/except` swallow + `log.warning("chat_plan_resume_error", ...)`。

**幂等 + fail-soft 守护链（已有，复用）：**
- `amaybe_complete_research` status guard（`research_aggregation.py:82-83`）：仅 `researching` 且全终态才转 merging。
- `adrive_*` researching 在途短路（步骤 2）。
- `BarrierManager.task_completed` 去重（`task_id in results` → False）。
- `PlanSessionService.transition` 条件更新并发良性 no-op。

---

### `server/agents/tools/plan_research_tools.py` — 文案更新（Discretion，接通后如实改）

**就地改文案位置:** `plan_research_tools.py:262-270` 的 placeholder（接通后应去掉「自动回流尚未接入」）+ 工具 description（`:41`）。当前文案：

```262:269:server/agents/tools/plan_research_tools.py
                    # WR-01：如实表述当前能力——chat 入口「调研完成 → 自动续驱 engine /
                    # resume chat graph 融合回流」尚未接线（见 deferred-items.md），故**不**承诺
                    # 自动继续，仅陈述：已发起 + 调研在途 + 自动回流后续接入。
                    "placeholder": (
                        f"已发起跨仓方案编排调研（session={session.id}，状态={session.status}）；"
                        "深入调研容器运行中。注意：本会话「调研完成后自动融合并返回主方案」"
                        "的自动回流能力尚未接入（后续里程碑接线），当前不会自动继续。"
                    ),
```

> Planner 动作（接通后）：改为「调研完成后自动融合并返回主方案」的肯定表述。若选择复用 helper，把 `:124-153` advance 循环替换为 `adrive_plan_session_to_pause_or_terminal`（行为须等价，挂起 marker 映射保留）。

---

### `server/tests/test_coding_node.py` — PF-06 env 键断言（扩展）

**Analog 1（同文件 dispatch mock 范式）:** `test_coding_node.py:118-158`（`TestAICodingNode` + `_make_repo` / `_make_context` / `_make_plan_data` + `patch.object(node, "_run_repo_coding", ...)`）。

> 注意：现有 happy-path 测试 mock 掉了 `_run_repo_coding` 整体。PF-06 测试须**不 mock** `_run_repo_coding`、改为 mock 其内部 IO 边界（`aresolve_git_token` / `get_dispatcher().dispatch` / `SubAgentSession` 创建），断言 `DispatchTask.metadata` 真实键集合。

**Analog 2（env 键断言风格）:** `server/tests/chat/test_coding_exclusion_env.py`（断言 `env_FRIDAY_TASK_*` 键存在/取值的成熟范式）。

**断言清单（来自 RESEARCH §Test Map）：**
- token 非空 → `metadata` 含 `env_FRIDAY_TASK_GIT_ACCESS_TOKEN/AUTH_TYPE/SSL_VERIFY`（`-k git_env`）
- `env_FRIDAY_TASK_BRANCH_STRATEGY == branch_name`、`TARGET_BRANCH == base_branch`（`-k branch_strategy`）
- SSH `git@` repo_url → `https://...` 改写；token 空时不注入 access_token 且不改写（`-k ssh_https`）
- token 绝不入日志，仅 `has_*` 布尔（`-k no_token_leak`）
- nested `git_credentials` dict 保留（零回归）
- `_make_repo` 已提供 `credential.ssl_verify=True`（`:57-60`），可直接复用。

---

### `server/tests/services/test_research_completion_callback.py` — chat 续驱 + barrier 回灌（扩展）

**Analog（同文件，直接扩展）:** `_setup` chat-entry fixture（`:32-63`，已建 `entrypoint=CHAT` 的 PlanSession + RUNNING RepoResearchTask + plan_research SubAgentSession）+ `_PATCHES`（`:73-77`）+ `_log`（`:66-70`）+ `test_structured_partial_recorded_and_completed_event`（`:80-110`）。

```73:77:server/tests/services/test_research_completion_callback.py
_PATCHES = (
    patch("subagent.api.callbacks._update_coding_session_on_complete", new_callable=AsyncMock),
    patch("subagent.api.callbacks._schedule_workflow_resume"),
    patch("subagent.api.callbacks._schedule_agent_session_resume"),
)
```

> Planner 动作：新增测试时须**放开** `_schedule_agent_session_resume` 的 mock（或针对 `_schedule_chat_plan_resume` 直接断言），并 mock merge adapter 把 `merging → done`（IO 边界 mock，pytest-socket 禁网）。

**断言清单（来自 RESEARCH §Test Map）：**
- chat 入口全终态 → engine 续驱到 `done`（`-k chat_resume_done`）
- 续驱到终态后 `BarrierManager.task_completed(str(plan_session.id))` 被调用（`-k barrier_notified`）
- 工作流入口（有 node_execution）**不**走 chat 续驱（回归守护，`-k workflow_not_chat`）
- 幂等：重复回调 / 部分调研未终态 → no-op（`-k idempotent`）
- fail-soft：续驱内部抛异常 → 回调仍返 200（`-k swallow`，复用既有「回调异常 swallow 返 200」）
- 失败路径：plan_research failed → barrier success=False 回灌不卡死（`-k failed_path`）

**DB marker:** `pytestmark = pytest.mark.django_db(transaction=True)`（异步 + 多协程回调，已在文件头 `:29`）。

---

### `server/tests/services/test_plan_resume_driver.py` — 共享 helper 单测（仅当 helper 落 `resume.py`）

**Analog:** `test_research_completion_callback.py` 的 mock 范式（mock engine.advance / PlanSession status 序列）。
**断言:** advance 循环到终态返回 / researching 在途短路返回 / step 上限 → `transition fail`。

---

## Shared Patterns

### Pattern A — `env_` 前缀顶层 metadata 注入（runner TrimPrefix 契约）
**Source:** `runner/internal/docker/executor.go:154-162`（只读核对，不改）
**Apply to:** `_run_repo_coding`（PF-06）
**契约:** runner 仅对**顶层** `env_` 前缀的 **string 且非空** 键 TrimPrefix 下传容器；nested dict 永不被消费（现状 bug 根因）。task 侧 `env_prefix="FRIDAY_TASK_"`（`task/core/config.py`）映射。→ 所有 git 凭证 / 分支须用顶层 `env_FRIDAY_TASK_*` string 键，ssl_verify 用字符串 `"false"`，空 token 不注入键。

### Pattern B — callback 钩子独立 try/except swallow（fail-soft）
**Source:** `server/subagent/api/callbacks.py:671-678`（`_handle_research_completion` 调用范式）
**Apply to:** `_schedule_chat_plan_resume` 内部 + 接线点

```671:678:server/subagent/api/callbacks.py
    try:
        await _handle_research_completion(session, p, log)
    except Exception as exc:  # noqa: BLE001 — 永不阻塞 _handle_completed 主流程
        logger.warning(
            "research_completion_callback_failed",
            session_id=session.session_id,
            error=str(exc),
        )
```

### Pattern C — researching→merging 推进（幂等 + service transition）
**Source:** `server/services/plan_orchestration/research_aggregation.py:73-88` `amaybe_complete_research`
**Apply to:** 续驱前的 status 推进（**不要**在 callback 直接改 status）；`_trigger_research_barrier`（`callbacks.py:1260-1266`）已封装调用。

### Pattern D — engine 构造单一工厂（不造两套）
**Source:** `server/services/plan_orchestration/entrypoint.py:55-84` `build_orchestration_engine`
**Apply to:** `_schedule_chat_plan_resume` 内 engine 构造（chat 入口不传 `node_execution_id`）；`adrive_*` helper 接收已构造的 engine（入口无关）。

### Pattern E — 凭证脱敏日志
**Source:** `coding.py:1040-1046` / `coding_session_service` 既有范式
**Apply to:** PF-06 dispatch 日志 + RESUME-01 续驱日志——仅记 `has_token` / `has_git_token` 布尔，`redact_credentials` structlog processor 兜底但代码须自律。

---

## No Analog Found

无。本 phase 所有改动均在库内同文件 / 同 app 找到强分析对象（PF-06 = chat 基线逐键对齐；RESUME-01 = `_schedule_workflow_resume` / `_notify_barrier_manager` 对称 mirror + 两处 advance 循环抽公共）。这正是 RESEARCH「全部新逻辑实质是接线」的体现。

## Metadata

**Analog search scope:** `server/workflows/nodes/ai/`, `server/chat/`, `server/subagent/api/`, `server/services/plan_orchestration/`, `server/agents/tools/`, `server/tests/`（+ `runner/internal/docker/`, `task/core/`, `task/git_ops/` 只读契约核对）
**Files scanned:** 10（coding.py, coding_session_service.py, callbacks.py, plan_research.py, plan_research_tools.py, research_aggregation.py, entrypoint.py, test_coding_node.py, test_research_completion_callback.py + RESEARCH/CONTEXT 引用核对）
**Pattern extraction date:** 2026-06-16

## PATTERN MAPPING COMPLETE

**Phase:** 43 - 编码 env 对齐 + 通用 resume 回流地基
**Files classified:** 8
**Analogs found:** 8 / 8

### Coverage
- Files with exact analog: 6（coding.py, resume.py, callbacks.py, plan_research_tools.py, plan_research.py, test_research_completion_callback.py）
- Files with role-match analog: 2（test_coding_node.py, test_plan_resume_driver.py）
- Files with no analog: 0

### Key Patterns Identified
- **PF-06 逐键对齐 chat 基线**：`_run_repo_coding` 照搬 `build_dispatch_metadata` 的 git token env + SSH→HTTPS（`re.match(r"git@([^:]+):(.+?)(?:\.git)?$")`）+ `BRANCH_STRATEGY`/`TARGET_BRANCH`，唯一差异是多仓取本次调用的 `branch_name`/`base_branch` 而非单仓 `execution_spec`；nested `git_credentials` dict 保留零回归。
- **RESUME-01 对称 mirror**：`_schedule_chat_plan_resume` 与同文件 `_schedule_workflow_resume` 对称（fire-and-forget `loop.create_task`/`asyncio.run`），barrier 回灌照 `_notify_barrier_manager` 但 `task_id=str(plan_session.id)`（非 session_id，Pitfall 3）。
- **续驱同源**：抽 `adrive_plan_session_to_pause_or_terminal` 自 `plan_research.py:142-167` 与 `plan_research_tools.py:124-153` 两处逐行同构的 advance 循环；engine 经唯一工厂 `build_orchestration_engine` 构造；status 只经 `PlanSessionService.transition`。
- **幂等 + fail-soft 已现成**：`amaybe_complete_research` status guard + `aall_research_tasks_terminal` 在途短路 + `BarrierManager.task_completed` 去重 + 独立 try/except swallow，四重守护复用即可。

### File Created
`/Users/zaneliu/Projects/open-source/friday-clean/.planning/phases/43-env-resume/43-PATTERNS.md`

### Ready for Planning
Pattern mapping complete. Planner 可在 PLAN.md 的 action 段直接引用上述 analog 行号与代码摘录（PF-06 逐键映射表 + RESUME-01 三步接线 + 共享 helper 抽取），无需重新检索。
