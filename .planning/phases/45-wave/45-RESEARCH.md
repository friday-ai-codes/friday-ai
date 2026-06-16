# Phase 45: 上游产物提取 + 注入下游 wave - Research

**Researched:** 2026-06-16
**Domain:** 跨仓上下文传递（产物提取落库 + 下游 prompt 注入）——纯后端基础设施，无新模型/迁移/外部依赖
**Confidence:** HIGH（全部基于本仓源码逐文件核对，无外部依赖引入）

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

> 基础设施 phase——CONTEXT 标注为「推荐 / 最安全默认」技术决策，均在 Claude's Discretion 范围内（无用户面交互，autonomous 模式 AUTO-ACCEPT 推荐项）。Planner 可在 PLAN.md 细化，但必须保持以下方向。

**Area 1：产物提取（ARTIFACT-01）**
- **D-01 提取触发点**：唯一触发点 = `services/plan_orchestration/wave_progression.py:_backfill_running_terminal` 中 `service.mark_done(task)` 成功之后（task running→done 唯一收口）。`done` 后立即提取并落库，绝不另设轮询/定时器/第二处 done 收口。
- **D-02 提取来源**：按 `task.subagent_session_id` 标量取 `SubAgentSession`，再取其 `TaskResult`（OneToOne `task_result`，coding 任务 `result_type="git"`）。权威字段：`branch_name`/`commit_sha`/`pr_url`/`modified_files`(list)/`raw_output`(dict)。无 TaskResult → 落最小占位 `{"available": false}`，不抛错、不阻塞 wave 推进（fail-soft）。
- **D-03 产物结构**：结构化 dict，推荐键 `{"repository_id","repository_name","branch","commit_sha","mr_url","modified_files":[...],"api_contracts":[...],"openapi":[...],"diff_summary":{...},"extracted_at"}`。`api_contracts`/`openapi` 由对 `modified_files` 路径的**轻量启发式**归类（路径含 `openapi`/`swagger`/`.proto`/`schema`/`api/` 等模式）；`diff_summary` 为 `{"files_changed": n}` 计数摘要。绝不存 token/凭证；产物仅含路径/URL/计数/契约文本片段。
- **D-04 提取实现落点**：新增 `services/plan_orchestration/artifact_extraction.py`（纯函数 `build_produced_artifacts(...) -> dict` + 启发式归类 helper），与 `wave_layering.py`/`wave_progression.py` 同包。提取逻辑与归类启发式必须可被纯函数单测覆盖（无需 DB）。
- **D-05 单一写入入口（INV-6）**：新增 `RepoCodingTaskService.record_produced_artifacts(task, artifacts)`（`sync_to_async` 桥接，`update_fields=["produced_artifacts","updated_at"]`，幂等覆盖写）。`mark_done` 保持纯状态转移不变；提取→写库在 `_backfill_running_terminal` 内 `mark_done` 之后调用。模型层零业务方法不破。提取/写库失败仅 `logger.warning` 降级，绝不让 wave 推进/回调主流程失败。

**Area 2：下游注入（ARTIFACT-02）**
- **D-06 注入对象**：下游 `RepoCodingTask` 的**直接** `depends_on` 上游仓的 `produced_artifacts`（wave gating 保证 dispatch 时直接上游必为 done，故 `produced_artifacts` 必已落库）。不做传递闭包收集（避免上下文膨胀）。
- **D-07 注入点**：唯一注入点 = `_dispatch_next_wave`（wave 推进 dispatch 下游时）收集每个待派发下游 task 的上游产物 → 传入 `_dispatch_wave` → `_run_repo_coding` → `_build_coding_prompt`。首发 wave（wave 0）无上游，注入为空（与现行为逐字等价，零回归）。
- **D-08 注入形态**：`_build_coding_prompt` 新增 `upstream_artifacts` 参数，非空时渲染独立「# 上游产物 / 上游契约」段（仓名/分支/MR/契约/OpenAPI 文件/变更文件清单），插在「项目背景(global_context)」之后、编码任务之前。prompt 即容器编码上下文，不新增第二条上下文通道。空产物 → 不渲染该段（无空标题、无回归）。
- **D-09 收集 helper 落点**：新增 `services/plan_orchestration/artifact_injection.py`（`acollect_upstream_artifacts(task) -> list[dict]` 沿 `task.depends_on` async ORM 安全反查；纯文本渲染 `render_upstream_artifacts_section(artifacts) -> str` 可纯函数单测）。`coding.py` 仅调用，不内联收集/渲染逻辑。
- **D-10 async ORM 安全**：收集上游沿 `depends_on`（M2M）只经 `async for task.depends_on.all()` / `*_id` 标量 / `afirst`，绝不裸访问 lazy-FK。

**Area 3：测试与零回归（验收硬项）**
- **D-11~D-15**：见 `## Validation Architecture`（提取单测 / 注入单测 / 端到端集成 SC-3 / INV-6 守护 / 幂等 fail-soft 全部为硬验收项）。

### Claude's Discretion
- 启发式归类的具体路径模式集合、`diff_summary` 具体字段、`produced_artifacts` 各桶命名细节由 planner 按最小实现/可读性定。
- `record_produced_artifacts` 覆盖写 vs merge（倾向覆盖，单仓单 done 只提取一次）、是否在 `mark_done` 同事务内写（倾向 done 后独立调用，解耦状态转移与产物落库）。
- 上游产物注入段中文文案/Markdown 结构、是否截断超长契约文本（倾向对 `raw_output` 摘要/截断防 prompt 膨胀）由 planner 定。
- 是否顺带发 `coding.artifact.extracted`/`coding.artifact.injected` trace 事件（DOMAIN §15 词表若已定义）由 planner 决定，倾向低成本接通。 **→ 见 Pitfall 5：§15 词表当前 NOT defined，最安全默认是本 phase 不 emit。**

### Deferred Ideas (OUT OF SCOPE)
- 多仓融合 PR + 跨仓 PR 关联 → Phase 46（PR-01/02）。
- 编码遇阻 question 抛人（HITL）→ Phase 47（HITL-01）。
- `follow_openspec=True` 的 openspec system prompt 注入 → v0.9（仅留字段）。
- 对 `raw_output` 重度语义解析 / LLM 二次提炼产物（结构化 API schema diff、契约语义比对）→ v0.9+（本 phase 仅轻量启发式，**NO 额外 LLM 调用**）。
- 传递闭包（间接上游）产物收集 → 非本 phase 目标（直接 `depends_on` 足够；间接契约由中间仓透传）。
- chat 编码入口（`coding_session_service`）的上游产物注入接线 → follow-up（本 phase 优先 workflow 入口；helper 入口无关以便复用）。
- 真实 runner + Docker 容器端到端产物传递验收 → 既有 deferred（本地无法闭环，以 mock IO 边界测试覆盖）。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ARTIFACT-01 | 上游 wave 完成后提取 `produced_artifacts`（API 契约 / OpenAPI / diff）落 `RepoCodingTask.produced_artifacts` | 提取挂载点已核实唯一：`wave_progression._backfill_running_terminal` 的 `mark_done` 后（line 144）；来源 `SubAgentSession.task_result`（`TaskResult` git 字段）已核实；纯函数 `build_produced_artifacts` + service `record_produced_artifacts` 范式（镜像现有 `mark_done` filter().update() 幂等写）；启发式路径归类示例见 Code Examples |
| ARTIFACT-02 | 把上游 `produced_artifacts` 注入下游 wave 的 prompt / `global_context`，使下游仓编码能消费上游契约 | 注入链路已核实：`_dispatch_next_wave`(844) → `_dispatch_wave`(520) → `_run_repo_coding`(1338) → `_build_coding_prompt`(1534)；`_build_coding_prompt` 为 sync 纯组装方法，新增 `upstream_artifacts` 参数 + `render_upstream_artifacts_section` 纯函数；首发 wave 0 空注入 = 零回归；收集 `acollect_upstream_artifacts` 沿直接 `depends_on` async-safe 反查 |
</phase_requirements>

## Summary

本 phase 在 Phase 44 已闭环的「多仓 wave 编码操作态脊柱 + 拓扑调度 + callback 驱动多 wave 推进」之上，补上**跨仓上下文传递**的最后一环：上游仓编码完成（running→done 回填时刻）从其容器产物提取结构化 `produced_artifacts` 落库，下游 wave dispatch 时沿 `depends_on` 收集直接上游的产物注入下游编码容器 prompt。**纯后端、无新模型/迁移/外部依赖**——`produced_artifacts`（JSONField）字段 Phase 44 已建表，本 phase 只写内容；所有逻辑落在现有 `services/plan_orchestration/` 纯函数包 + `RepoCodingTaskService` 单一写入入口 + `AICodingNode` 既有 dispatch 链的薄接线。

两个唯一挂载点是本 phase 的命门，且**均已被前序 phase 坐实为单一收口**：(1) 提取**只挂** `wave_progression._backfill_running_terminal` 循环内 `await service.mark_done(task)`（line 144）之后——这是 Phase 44 确立的 running→done 唯一 backfill chokepoint，`sess`（SubAgentSession）已在该循环 line 139 取出可直接复用；(2) 注入**只走** `_dispatch_next_wave` → `_build_coding_prompt` 既有 dispatch 链——`_build_coding_prompt`(line 1534) 是一个 sync 纯字符串组装方法，当前 parts 顺序 `global_context → 分支 → 任务 → 文件 → 要求`，新增 `upstream_artifacts` 默认空参即可零回归扩展。

零回归是硬命门：`produced_artifacts` 为空 / wave 0 无上游 / 提取失败 → 注入段不渲染（无空标题）→ prompt 与 Phase 44 现行为**字节级一致**。由于 `_dispatch_wave` 被首发（wave 0）与 wave 推进共用，新增的 `upstream_artifacts_by_repo` 参数必须默认空，使首发路径逐字不变。INV-6 / async ORM 安全 / fail-soft 三条范式逐字沿用 Phase 44，无新模式引入。

**Primary recommendation:** 新建两个入口无关纯函数模块——`artifact_extraction.py`（`build_produced_artifacts` + 路径启发式归类，DB-free 可单测）与 `artifact_injection.py`（`acollect_upstream_artifacts` async 反查 + `render_upstream_artifacts_section` 纯渲染）；`RepoCodingTaskService` 新增 `record_produced_artifacts`（filter().update() 幂等覆盖写，镜像 `mark_done` 范式）；`_backfill_running_terminal` 在 `mark_done` 后追加 fail-soft 提取调用；`_dispatch_next_wave` 收集上游 → `_dispatch_wave`/`_run_repo_coding`/`_build_coding_prompt` 增 defaulted `upstream_artifacts` 参数透传。**本 phase 不 emit `coding.artifact.*` 事件（§15 词表未定义）。无新依赖、无新迁移。**

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 从容器产物（TaskResult git 字段）提取结构化 `produced_artifacts` | 纯函数（`services/plan_orchestration/artifact_extraction.py`） | — | 无 IO、可 DB-free 单测，镜像 `wave_layering.py` 纯函数风格；输入为已物化的标量/JSON 字段 |
| 路径模式 → 契约/OpenAPI 桶启发式归类 | 纯函数（同上 helper） | — | v0.8 仅轻量字符串匹配，无 LLM；纯逻辑 |
| `produced_artifacts` 写库唯一入口（INV-6） | Service（`RepoCodingTaskService.record_produced_artifacts`） | — | 镜像 `mark_done` filter().update()；模型层零业务方法 + grep 守护 |
| 提取触发（done 回填后调用提取+写库） | wave 推进 helper（`wave_progression._backfill_running_terminal`） | Service / 纯函数 | Phase 44 确立的 running→done 唯一收口，`sess` 已就地可复用 |
| 沿直接 `depends_on` 收集上游产物 | 纯函数 helper（`artifact_injection.acollect_upstream_artifacts`，async） | — | async ORM 安全反查，入口无关可被 workflow/chat 复用 |
| 渲染上游产物 prompt 段 | 纯函数（`artifact_injection.render_upstream_artifacts_section`，sync） | — | 纯文本渲染，可纯函数单测（零回归断言基准） |
| 注入接线（收集 → 透传 → 组装 prompt） | Workflow node（`AICodingNode._dispatch_next_wave` / `_dispatch_wave` / `_run_repo_coding` / `_build_coding_prompt`） | 纯函数 helper | dispatch + prompt 组装是 node 既有职责；node 只调用 helper 不内联逻辑 |
| 容器派发 / SubAgentSession / wave gate / MR 收尾 | Phase 44 既有（**不改契约**） | — | 复用既有，不造两套 |

## Standard Stack

**无新增第三方依赖。** 本 phase 全部在现有技术栈内实现（Django 5.1+ / Python 3.14 / adrf 异步）。

### Core（均为现栈既有）
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Django ORM | `django>=5.1`（迁移头注 6.0.1） | `produced_artifacts` JSONField 写（**字段 Phase 44 已建，无新迁移**）+ `depends_on` M2M 反查 | 既有 delivery 模型用之 [VERIFIED: server/delivery/models/repo_coding_task.py:80] |
| adrf + asgiref `sync_to_async` | `adrf>=0.1.12` | service 异步写表桥接 | `RepoCodingTaskService` 全部 `@sync_to_async` 范式 [VERIFIED: repo_coding_task_service.py] |
| structlog | 现栈 | fail-soft `logger.warning` 降级 | 全仓结构化日志范式（仅记 `has_*` 布尔/计数，绝不记 token）[VERIFIED: coding.py:1510] |
| Python stdlib（`str` 方法 / `os.path` / `datetime`） | 3.14 | 路径模式启发式归类 + `extracted_at` 时间戳 | 标准库；无需第三方解析器（v0.8 仅轻量字符串匹配）[ASSUMED] |

### Supporting（复用点）
| Asset | Purpose | When to Use |
|---------|---------|-------------|
| `wave_progression._backfill_running_terminal`（line 126，`mark_done` at 144） | **ARTIFACT-01 唯一提取挂载点**；`sess`(SubAgentSession) 已在 line 139 就地取出 | done 回填后追加提取 [VERIFIED] |
| `subagent.models.TaskResult`（models.py:253，OneToOne `session.task_result`） | 提取来源：`branch_name`/`commit_sha`/`pr_url`/`modified_files`/`raw_output` | `TaskResult.objects.filter(session=sess).afirst()` [VERIFIED] |
| `RepoCodingTaskService`（INV-6 单一写入入口） | 新增 `record_produced_artifacts`；`mark_done`/`mark_failed`/`mark_blocked` 范式蓝本 | `produced_artifacts` 写库 [VERIFIED] |
| `RepoCodingTask.depends_on` / `.dependents`（self-M2M） | 注入：正查 `depends_on` 收集直接上游 | `acollect_upstream_artifacts` [VERIFIED: repo_coding_task.py:60] |
| `coding._dispatch_next_wave`(844)/`_dispatch_wave`(520)/`_run_repo_coding`(1338)/`_build_coding_prompt`(1534) | **ARTIFACT-02 注入链路**（既有 dispatch 链） | 透传 `upstream_artifacts` [VERIFIED] |
| `wave_layering.py` 纯函数风格 | `artifact_extraction`/`artifact_injection` 新模块对齐蓝本 | 模块风格镜像 [VERIFIED] |
| `tests/test_coding_wave.py` mock IO 边界 fixture（`_dispatched` / `_stub_provider_resolution`） | D-13 端到端集成测试复用 | SC-3 集成测试 [VERIFIED] |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| 提取挂 `_backfill_running_terminal`（mark_done 后） | 在 `_finalize_wave` 收尾段统一提取 | **禁止**——CONTEXT D-01 硬约束唯一收口；收尾段提取会漏掉「上游 done 但 wave 未收尾」的中间态，下游 dispatch 时产物缺失 |
| 启发式路径归类（v0.8） | 对 `raw_output` 做 LLM 语义提炼 | **禁止**——CONTEXT 明确 v0.8 NO 额外 LLM 调用；LLM 提炼留 v0.9+ |
| 直接 `depends_on`（D-06） | 传递闭包收集间接上游 | 上下文膨胀；间接契约应由中间仓在自身产物透传，非本 phase 目标 |
| `_build_coding_prompt` 增 defaulted 参数 | 新增第二条 `global_context` 注入通道 | **禁止**——D-08 prompt 即容器编码上下文，不新增第二通道；defaulted 参数保首发零回归 |

**Installation:** 无（无新包）。
**Version verification:** N/A — 本 phase 不安装任何外部包；所有依赖已在 `server/pyproject.toml` 锁定。

## Package Legitimacy Audit

**Not applicable** — 本 phase 不安装任何外部 package（纯内部 Django service + 纯函数 + node 接线，仅用 Python stdlib 与现栈既有依赖）。无 slopcheck / 注册表校验需求。

## Architecture Patterns

### System Architecture Diagram

```text
=== ARTIFACT-01：提取落库（上游 wave done 时刻）===

  容器完成 → POST /api/containers/callback/ → _schedule_workflow_resume（Phase 43，不改）
                          │  AICodingNode 重入 → _resume_wave → aadvance_coding_waves
                          ▼
       wave_progression._backfill_running_terminal  (唯一 running→done 收口)
                          │  async for task in RUNNING tasks:
                          │    sess = SubAgentSession.afirst(id=task.subagent_session_id)  (line 139)
                          │    if sess.status == "completed":
                          │        await service.mark_done(task)            (line 144 — 纯状态转移不变)
                          │   ┌──── 【ARTIFACT-01 提取追加点：mark_done 之后】──────────┐
                          │   │  try:                                                  │
                          │   │    tr = TaskResult.objects.filter(session=sess).afirst()│
                          │   │    repo_name = Repository.afirst(id=task.repository_id) │
                          │   │    artifacts = build_produced_artifacts(               │  ← 纯函数（DB-free）
                          │   │        repository_id, repo_name, tr)                   │     路径启发式归类
                          │   │    await service.record_produced_artifacts(task, ...)  │  ← INV-6 单一写入
                          │   │  except Exception: logger.warning(...)  (fail-soft)    │
                          │   └────────────────────────────────────────────────────────┘
                          ▼
              RepoCodingTask.produced_artifacts = {repository_id, branch, mr_url,
                  modified_files, api_contracts, openapi, diff_summary, extracted_at}

=== ARTIFACT-02：注入下游（下游 wave dispatch 时刻）===

  aadvance_coding_waves 返回 {"dispatch": [下游 task...], "wave": n}
                          ▼
       AICodingNode._dispatch_next_wave
                          │  for 每个待派发下游 task:
                          │    upstream = await acollect_upstream_artifacts(task)   ← async 沿直接 depends_on 反查
                          │  upstream_artifacts_by_repo = {repo_id: [上游产物...]}
                          ▼
       _dispatch_wave(..., upstream_artifacts_by_repo=...)   (首发 wave0 传 {} → 零回归)
                          │  per repo:
                          ▼
       _run_repo_coding(..., upstream_artifacts=by_repo.get(repo_id, []))
                          ▼
       _build_coding_prompt(tasks, global_context, branch, upstream_artifacts=[])
                          │  parts = [global_context,
                          │           render_upstream_artifacts_section(upstream_artifacts),  ← 非空才插，空→不渲染
                          │           分支, 任务, 文件, 要求]
                          ▼
       DispatchTask.prompt（含「# 上游产物 / 上游契约」段）→ 容器编码 agent 消费上游契约
```

### Recommended File Structure
```text
server/services/plan_orchestration/
├── artifact_extraction.py        # 新增：build_produced_artifacts(...) + _classify_modified_files 启发式（纯函数, DB-free）
├── artifact_injection.py         # 新增：acollect_upstream_artifacts(task)(async) + render_upstream_artifacts_section(...)(sync 纯函数)
├── wave_progression.py           # 改造：_backfill_running_terminal 在 mark_done 后追加 fail-soft 提取调用
└── __init__.py                   # 改造：barrel 导出新公共函数（对齐 build_repo_waves / aadvance_coding_waves 范式）

server/delivery/services/repo_coding_task_service.py  # 改造：新增 record_produced_artifacts（filter().update() 幂等覆盖写）

server/workflows/nodes/ai/coding.py  # 改造：_dispatch_next_wave 收集上游；_dispatch_wave/_run_repo_coding/_build_coding_prompt 增 defaulted upstream_artifacts 透传

server/tests/services/plan_orchestration/
├── test_artifact_extraction.py   # 新增：build_produced_artifacts 纯函数（git 产物归类 / 无 TaskResult 占位 / 空 modified_files）
└── test_artifact_injection.py    # 新增：render_upstream_artifacts_section 纯函数（多上游 / 空串）
server/tests/delivery/
├── test_repo_coding_task_service.py        # 扩充：record_produced_artifacts 幂等覆盖写
└── test_repo_coding_task_inv6_guard.py     # 扩充：produced_artifacts 字段旁路写守护（见 Pitfall 6）
server/tests/
├── test_coding_node.py            # 扩充：_build_coding_prompt 带/不带 upstream_artifacts（零回归逐字断言）
└── test_coding_wave.py            # 扩充：D-13 端到端（wave1 done→提取→wave2 prompt 含契约）
```

### Pattern 1: 提取追加于 `_backfill_running_terminal` 的 `mark_done` 之后（唯一收口）
**What:** 在已确立的 running→done backfill 循环内，`mark_done` 成功后就地复用已取出的 `sess`，取 `TaskResult` → 纯函数构产物 → service 写库，整段 fail-soft。
**When to use:** ARTIFACT-01。
**Example:**
```python
# Source: 改造 services/plan_orchestration/wave_progression.py:_backfill_running_terminal（line 126-154）
async def _backfill_running_terminal(plan_version_id, service):
    from delivery.models import RepoCodingTask, RepoCodingTaskStatus
    from subagent.models import SubAgentSession, TaskResult
    from repositories.models import Repository
    from services.plan_orchestration.artifact_extraction import build_produced_artifacts

    async for task in RepoCodingTask.objects.filter(
        plan_version_id=plan_version_id, status=RepoCodingTaskStatus.RUNNING,
    ):
        sid = task.subagent_session_id
        if not sid:
            continue
        sess = await SubAgentSession.objects.filter(id=sid).afirst()
        if sess is None:
            continue
        sess_status = str(sess.status)
        if sess_status in _SUBAGENT_DONE:
            await service.mark_done(task)                    # 纯状态转移不变（line 144）
            # ── ARTIFACT-01：提取落库（fail-soft，绝不阻塞 wave 推进）──
            try:
                tr = await TaskResult.objects.filter(session=sess).afirst()
                repo = await Repository.objects.filter(id=task.repository_id).afirst()
                repo_name = repo.name if repo else str(task.repository_id)
                artifacts = build_produced_artifacts(
                    repository_id=str(task.repository_id),
                    repository_name=repo_name,
                    task_result=tr,          # None → 占位 {"available": false}
                )
                await service.record_produced_artifacts(task, artifacts)
            except Exception as exc:  # noqa: BLE001 — 提取失败降级，不影响 done 推进
                logger.warning("coding_artifact_extract_failed",
                               task_id=str(task.id), error=str(exc))
        elif sess_status in _SUBAGENT_FAILED:
            await service.mark_failed(task, {...})
```
**为什么复用 `sess`：** 循环已在 line 139 取出 `sess`，提取无需二次查 SubAgentSession；只需新增 `TaskResult.afirst` + `Repository.afirst`（repo_name）。`task.repository_id` 标量安全。

### Pattern 2: 纯函数提取 + 路径启发式归类（DB-free 可单测）
**What:** `build_produced_artifacts` 接收已物化的标量/JSON 字段（非 lazy ORM 对象），返回结构化 dict；归类纯字符串匹配。
**When to use:** ARTIFACT-01 / D-11 单测。
**Example:** 见 Code Examples「提取纯函数」。
**关键：** 入参用 `repository_id: str` / `repository_name: str` / `task_result: TaskResult | None`。单测可构造**未保存**的 `TaskResult(result_type="git", modified_files=[...])` 内存实例（不触 DB），满足 D-04/D-11「无需 DB 单测」。

### Pattern 3: service 幂等覆盖写（镜像 `mark_done` filter().update()）
**What:** `record_produced_artifacts` 用 `filter(id=task.id).update(produced_artifacts=..., updated_at=now())`，覆盖式幂等（重复写同产物等价），无 status guard（提取与状态解耦）。
**When to use:** ARTIFACT-01 / D-05。
**Example:**
```python
# Source: 镜像 repo_coding_task_service.py:_mark_done_sync（filter().update() 范式）
async def record_produced_artifacts(self, task, artifacts: dict) -> None:
    """produced_artifacts 写库唯一入口（INV-6，幂等覆盖写）。"""
    await self._record_produced_artifacts_sync(task, artifacts)

@sync_to_async
def _record_produced_artifacts_sync(self, task, artifacts: dict) -> int:
    return RepoCodingTask.objects.filter(id=task.id).update(
        produced_artifacts=artifacts, updated_at=timezone.now(),
    )
```
**注意：** 用 `.update()`（在允许 writer 文件内）而非 `task.produced_artifacts=...; task.save()`，既符合既有 INV-6 grep 守护（`.objects.update` 在允许文件中），又避免依赖 `task` 内存态。

### Pattern 4: 收集 async-safe + 渲染纯函数 + node 薄接线
**What:** `acollect_upstream_artifacts(task)` 沿 `async for task.depends_on.all()` 反查直接上游 `.produced_artifacts`（JSON 标量安全）；`render_upstream_artifacts_section(artifacts)` 纯渲染，空 → `""`。
**When to use:** ARTIFACT-02 / D-09。
**Example:** 见 Code Examples「收集 + 渲染」。

### Anti-Patterns to Avoid
- **在 `_finalize_wave` 或第二处 done 收口提取：** 违反 D-01 唯一收口；中间态下游 dispatch 时产物会缺失。
- **裸访问 lazy-FK：** `task.repository.name` / `task.subagent_session.status` / `task.depends_on.all()`（同步迭代）触发 `SynchronousOnlyOperation`。用 `*_id` 标量 / `afirst` / `async for`。
- **提取/注入异常上抛：** 让容器回调 5xx → runner 重试风暴。全程 fail-soft `logger.warning`。
- **`_build_coding_prompt` 新增非 defaulted 参数：** 破坏首发 wave 0 路径零回归。必须 `upstream_artifacts: list | None = None`，空 → 不渲染段。
- **产物存 token/凭证/敏感值：** 只存路径/URL/计数/契约文本片段；日志仅 `has_*` 布尔/计数。
- **对 `raw_output` 做 LLM 提炼：** v0.8 NO 额外 LLM；仅轻量启发式。
- **emit 未在 §15 定义的 `coding.artifact.*` 事件：** 见 Pitfall 5。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| running→done 提取触发 | 自写轮询/定时器/第二处 done 收口 | `wave_progression._backfill_running_terminal`（Phase 44 唯一收口，`sess` 就地可复用） | CONTEXT D-01 硬约束；新增收口引入竞态与产物缺失 [VERIFIED] |
| 容器产物来源 | 自解析 `last_output` / runner 中转字段 | `SubAgentSession.task_result`（`TaskResult` git 字段，服务端权威） | OneToOne 关系明确，字段权威 [VERIFIED: subagent/models.py:253] |
| `produced_artifacts` 写库 | 模型层 save / 旁路 `.objects.update` | `RepoCodingTaskService.record_produced_artifacts`（INV-6） | 单一写入 + grep 守护 [VERIFIED] |
| 上游收集 | 自写 M2M 遍历 / 传递闭包 | `acollect_upstream_artifacts` 直接 `depends_on` async 反查 | D-06 直接依赖足够；wave gating 保证已 done [VERIFIED] |
| prompt 注入 | 新增第二条 global_context 通道 | `_build_coding_prompt` defaulted 参数 + 纯渲染函数 | D-08 prompt 即容器上下文；defaulted 保零回归 [VERIFIED] |
| 集成测试 IO 边界 | 真实 runner/Docker | `test_coding_wave.py` 既有 mock fixture（dispatcher / provider / token） | 本地无法闭环（既有 deferred）[VERIFIED] |

**Key insight:** 本 phase 真正新增的只有三块纯逻辑：① `build_produced_artifacts` + 路径归类启发式（纯函数），② `acollect_upstream_artifacts` + `render_upstream_artifacts_section`（收集/渲染），③ `record_produced_artifacts`（一个镜像 service 方法）。其余全是把这三块挂到 Phase 44 既有的唯一 done 收口与既有 dispatch 链上的薄接线——所有「难」组件（done 收口、容器产物源、INV-6 写入、M2M 反查、wave gate、MR 收尾、集成测试 fixture）仓内均已就绪。

## Runtime State Inventory

**Not applicable（additive infra，非 rename/refactor/migration）。** 本 phase 不重命名任何现有字符串/键，不迁移既有数据，不新增表/字段（`produced_artifacts` JSONField Phase 44 migration 0017 已建）。逐类核对：

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — `produced_artifacts` 字段已存在（default=dict），本 phase 仅写内容，无既有数据需迁移（Phase 44 后无生产 wave 编码跑过真实产物） | 无 |
| Live service config | None — 无外部服务配置改动（不碰 n8n/Datadog/runner 配置） | 无 |
| OS-registered state | None — 无 OS 级注册（无 Task Scheduler / pm2 / systemd 改动） | 无 |
| Secrets/env vars | None — 不新增 env 键；产物**绝不**含 token（dispatch 既有 `env_FRIDAY_TASK_*` 注入不变） | 无 |
| Build artifacts | None — 无 pyproject/包名改动，无 egg-info 失效 | 无 |

**唯一变更是新增 Python 模块 + service 方法 + node 参数透传**，无 DDL、无数据迁移。

## Common Pitfalls

### Pitfall 1: async 上下文裸访问 lazy-FK / M2M → SynchronousOnlyOperation
**What goes wrong:** 提取时 `task.subagent_session.task_result` / `task.repository.name`，或收集时 `for u in task.depends_on.all()`（同步迭代）抛 `SynchronousOnlyOperation`。
**Why it happens:** wave_progression / coding 均在 async 事件循环内执行。
**How to avoid:** 提取用 `task.subagent_session_id` 标量 + `TaskResult.objects.filter(session=sess).afirst()`（`sess` 已就地取出）+ `Repository.objects.filter(id=task.repository_id).afirst()`；收集用 `async for u in task.depends_on.all()` 读 `u.produced_artifacts`（JSON 列标量安全）。纯函数 `build_produced_artifacts` 只收已物化值，绝不接 lazy ORM 对象。
**Warning signs:** 测试 `pytest.mark.django_db(transaction=True)` 下偶发 `SynchronousOnlyOperation`。
**Source:** [VERIFIED: wave_progression.py:20-21 注释明确此约束 + coding.py:1369 同类规避注释]

### Pitfall 2: 零回归不彻底（空产物注入产生 prompt 漂移）
**What goes wrong:** 改造后 wave 0 / 无上游 / 提取失败场景，prompt 与 Phase 44 现行为不一致（多了空标题 / 分隔符 / 参数顺序变化）。
**Why it happens:** `_build_coding_prompt` 用 `"\n\n---\n\n".join(parts)`——若把空渲染段（`""`）也 append 进 `parts`，会多出一段空白分隔。
**How to avoid:** `render_upstream_artifacts_section` 空时返回 `""`；`_build_coding_prompt` 仅在返回非空时 `parts.append(...)`（与现有 `files_section` 的 `if files_section:` 守卫同范式，line 1566-1568）。新参数 `upstream_artifacts: list[dict] | None = None`，`None`/`[]` → 不 append。首发 `_dispatch_wave` 传 `{}` → 各仓 `[]` → 逐字等价。
**Warning signs:** `test_coding_node` 现有 prompt 断言（12 passed）被打破；空 upstream 的 prompt 字符串与基线不等。
**Source:** [VERIFIED: coding.py:1544-1578 parts 组装 + line 1566 files_section 守卫范式]

### Pitfall 3: 提取/注入异常让回调主流程 5xx
**What goes wrong:** `TaskResult` 缺失 / 归类异常 / 写库失败上抛，使 `_resume_wave` → 容器回调返回 5xx，runner 重试。
**Why it happens:** 提取挂在 `_backfill_running_terminal`（被 `aadvance_coding_waves` 调用，再被 `_resume_wave` 调用）；虽然 `_resume_wave` 整段已 try/except swallow（line 813-817），但产物提取异常不应连带使整个 advance 降级收尾（会误判 all_terminal）。
**How to avoid:** 提取段**独立** try/except `logger.warning`（不向 `_backfill_running_terminal` 外冒泡），与 `mark_done` 成功解耦——提取失败时 task 仍正确 done，只是 `produced_artifacts` 留空 dict（下游注入段为空，零回归）。无 TaskResult → 落 `{"available": false}` 占位（D-02），非异常路径。
**Warning signs:** 单个仓提取失败导致整 wave 误进收尾。
**Source:** [VERIFIED: wave_progression.py:91 注释「本函数不吞异常（由调用方包 try/except swallow）」+ coding.py:815 `_resume_wave` swallow]

### Pitfall 4: `record_produced_artifacts` 误加 status guard 导致写失败
**What goes wrong:** 套用 `mark_done` 的 `filter(status=RUNNING)` 条件 → task 已 done（mark_done 已转 done）时 `filter(id, status=RUNNING).update()` 影响 0 行，产物写不进。
**Why it happens:** 机械镜像 `mark_done` 的条件更新范式，但提取发生在 `mark_done` **之后**（task 已是 done）。
**How to avoid:** `record_produced_artifacts` **不**加 status guard，用 `filter(id=task.id).update(produced_artifacts=...)`（无条件覆盖幂等）。提取与状态解耦（D-05/Discretion）。
**Warning signs:** 集成测试 done 仓 `produced_artifacts` 仍为 `{}`。

### Pitfall 5: emit 未定义的 `coding.artifact.*` 事件触发守护测试 fail
**What goes wrong:** CONTEXT Discretion 提及「`coding.artifact.extracted/injected` 若 §15 已定义则接通」，但 §15 taxonomy **未定义**这两个事件（只定义 `coding.wave.started/completed`，且属 RESERVED OUT OF SCOPE）。若硬接，需新增常量 + 改 `ALL_EVENTS` 覆盖性守护测试。
**Why it happens:** 误读 Discretion 为「应接通」。
**How to avoid:** **最安全默认：本 phase 不 emit `coding.artifact.*` 事件**（§15 词表未定义，且 `coding.wave.*` 本身仍 RESERVED）。Discretion 条件「DOMAIN §15 词表若已定义」未满足。若 planner 仍要接，须：(1) 在 `event_taxonomy.py` 新增 `EVENT_CODING_ARTIFACT_*` 常量，(2) 同步在 DOMAIN §15 表补词，(3) 决定计入 `ALL_EVENTS` 还是 RESERVED，(4) 配套改 `test_event_taxonomy` 覆盖性断言——成本 > 收益，建议 defer。
**Warning signs:** `ALL_EVENTS` 覆盖性守护测试 fail（emit 了未登记 / 登记了未 emit）。
**Source:** [VERIFIED: event_taxonomy.py:60-88 仅 wave.* RESERVED，无 artifact.*；DOMAIN §15:541-556 表无 artifact 行]

### Pitfall 6: INV-6 grep 守护对字段级旁路写有盲区（D-14）
**What goes wrong:** 现有 `test_repo_coding_task_inv6_guard.py` 正则 `_RE_ORM_WRITE`(`.objects.create|update|...`) + `_RE_INSTANTIATE`(`RepoCodingTask(`) + `_RE_INSTANCE_SAVE`(`RepoCodingTask(...).save(`) 能拦 `.objects.update`，但**拦不住** `some_task.produced_artifacts = {...}; some_task.save(update_fields=[...])`（实例字段赋值 + 实例 save，非匹配模式）。本 phase 提取写若误走实例 save 旁路会绕过守护。
**Why it happens:** 守护针对 `RepoCodingTask.objects.*` 与类名实例化，不覆盖实例属性赋值。
**How to avoid:** (1) `record_produced_artifacts` 用 `.objects.filter(id=...).update(...)`（在允许 writer 文件内，被现有守护正向覆盖）；(2) D-14 要求扩充守护：新增正则断言 `\.produced_artifacts\s*=`（字段赋值）只允许出现在 `_ALLOWED_WRITER` + `delivery/models/`（模型字段定义）中，否则 fail——把字段级旁路写纳入守护。
**Warning signs:** 提取逻辑误写在 wave_progression.py 内直接改 `task.produced_artifacts`（应只经 service）。
**Source:** [VERIFIED: test_repo_coding_task_inv6_guard.py:31-41 正则覆盖范围]

### Pitfall 7: 上游产物注入收集时机与 wave gating 的隐含契约
**What goes wrong:** `acollect_upstream_artifacts` 读上游 `produced_artifacts` 时若上游尚未落库（空 dict），下游 prompt 缺契约。
**Why it happens:** 误以为需要额外等待/重试。
**How to avoid:** 无需额外处理——`_dispatch_next_wave` 只在 `aadvance_coding_waves` 返回 `{"dispatch": ...}` 时调用，该时刻**直接上游必为 done**（wave gating：`_collect_dispatchable_pending` 要求 `depends_on` 全 done，wave_progression.py:190-208），而 done 回填时已在同一 `_backfill_running_terminal` 完成提取落库。故收集时上游 `produced_artifacts` 必已写入（除非提取 fail-soft 落空 → 注入段为空，可接受降级）。
**Source:** [VERIFIED: wave_progression.py:190-208 `_collect_dispatchable_pending` 要求 depends_on 全 done]

## Code Examples

### 提取纯函数 + 路径启发式归类（DB-free）
```python
# Source: 新增 services/plan_orchestration/artifact_extraction.py（镜像 wave_layering 纯函数风格）
from __future__ import annotations
from datetime import UTC, datetime

__all__ = ["build_produced_artifacts", "classify_modified_files"]

# 轻量路径启发式（v0.8，无 LLM）；具体集合由 planner 按可读性定（Discretion）。
_OPENAPI_PATTERNS = ("openapi", "swagger")
_OPENAPI_SUFFIXES = ("openapi.json", "openapi.yaml", "openapi.yml", "swagger.json")
_CONTRACT_PATTERNS = ("/api/", "schema", ".proto", ".graphql", ".graphqls", "contract")


def classify_modified_files(modified_files: list[str]) -> tuple[list[str], list[str]]:
    """把 modified_files 路径启发式归类为 (api_contracts, openapi)。纯字符串匹配。"""
    api_contracts: list[str] = []
    openapi: list[str] = []
    for raw in modified_files or []:
        path = str(raw)
        low = path.lower()
        if any(p in low for p in _OPENAPI_PATTERNS) or low.endswith(_OPENAPI_SUFFIXES):
            openapi.append(path)
        elif any(p in low for p in _CONTRACT_PATTERNS):
            api_contracts.append(path)
    return api_contracts, openapi


def build_produced_artifacts(*, repository_id: str, repository_name: str,
                             task_result) -> dict:
    """从 TaskResult（git 产物）构结构化 produced_artifacts；task_result=None → 占位。

    入参为已物化标量 / TaskResult 实例（其字段为已加载列，安全）——绝不接 lazy ORM 对象，
    保 DB-free 可单测（D-04/D-11：单测可构造未保存的 TaskResult 内存实例）。
    """
    base = {
        "repository_id": repository_id,
        "repository_name": repository_name,
        "extracted_at": datetime.now(UTC).isoformat(),
    }
    if task_result is None:
        return {**base, "available": False}

    modified = list(task_result.modified_files or [])
    api_contracts, openapi = classify_modified_files(modified)
    return {
        **base,
        "available": True,
        "branch": task_result.branch_name or "",
        "commit_sha": task_result.commit_sha or "",
        "mr_url": task_result.pr_url or "",
        "modified_files": modified,
        "api_contracts": api_contracts,
        "openapi": openapi,
        "diff_summary": {"files_changed": len(modified)},
    }
```

### 收集（async-safe）+ 渲染（纯函数）
```python
# Source: 新增 services/plan_orchestration/artifact_injection.py
from __future__ import annotations

__all__ = ["acollect_upstream_artifacts", "render_upstream_artifacts_section"]


async def acollect_upstream_artifacts(task) -> list[dict]:
    """沿直接 depends_on 反查上游 produced_artifacts（D-06 仅直接依赖）。

    async ORM 安全：async for + JSON 列标量读取，绝不裸访问 lazy-FK（D-10）。
    """
    out: list[dict] = []
    async for upstream in task.depends_on.all():
        artifacts = upstream.produced_artifacts or {}
        # 空 / 占位（available=False）跳过——下游注入段对其不渲染（零回归）。
        if artifacts and artifacts.get("available", True):
            out.append(artifacts)
    return out


def render_upstream_artifacts_section(artifacts: list[dict]) -> str:
    """渲染「# 上游产物 / 上游契约」段；空 → 返回 ""（零回归命门，不渲染空标题）。"""
    if not artifacts:
        return ""
    lines = ["# 上游产物 / 上游契约", "", "下游仓编码可消费以下上游仓已产出的契约："]
    for a in artifacts:
        name = a.get("repository_name") or a.get("repository_id", "")
        lines.append(f"\n## {name}")
        if a.get("branch"):
            lines.append(f"- 分支: `{a['branch']}`")
        if a.get("mr_url"):
            lines.append(f"- MR: {a['mr_url']}")
        for label, key in (("OpenAPI", "openapi"), ("API 契约", "api_contracts")):
            files = a.get(key) or []
            if files:
                lines.append(f"- {label}:")
                lines.extend(f"  - `{f}`" for f in files)
        changed = (a.get("diff_summary") or {}).get("files_changed")
        if changed is not None:
            lines.append(f"- 变更文件数: {changed}")
    return "\n".join(lines)
```

### `_build_coding_prompt` 零回归注入（defaulted 参数 + 守卫）
```python
# Source: 改造 coding.py:_build_coding_prompt（line 1534-1578）；新增 upstream_artifacts 默认 None
def _build_coding_prompt(self, tasks, global_context, branch_name,
                         upstream_artifacts=None):
    from services.plan_orchestration.artifact_injection import (
        render_upstream_artifacts_section,
    )
    parts: list[str] = []
    if global_context:
        parts.append(f"# 项目背景\n\n{global_context}")
    # ── ARTIFACT-02：上游产物段（D-08：global_context 之后、编码任务之前）──
    upstream_section = render_upstream_artifacts_section(upstream_artifacts or [])
    if upstream_section:                     # 空 → 不 append（零回归，对齐 files_section 守卫）
        parts.append(upstream_section)
    parts.append(f"# 分支信息\n\n目标分支: `{branch_name}`")
    # ... 其余（任务/文件/要求）逐字不变 ...
    return "\n\n---\n\n".join(parts)
```

### 注入透传（`_dispatch_next_wave` 收集 → `_dispatch_wave`/`_run_repo_coding` 默认空）
```python
# Source: 改造 coding.py:_dispatch_next_wave（line 844）收集上游
upstream_by_repo: dict[str, list[dict]] = {}
for repo_id, task in tasks_by_repo.items():
    upstream_by_repo[repo_id] = await acollect_upstream_artifacts(task)
# 透传到 _dispatch_wave(..., upstream_artifacts_by_repo=upstream_by_repo)
# _dispatch_wave 内 per repo: _run_repo_coding(..., upstream_artifacts=by_repo.get(repo_id, []))
# 首发 _execute_with_branch 调 _dispatch_wave 不传该参（默认 {}）→ wave0 各仓 [] → 零回归
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `produced_artifacts` Phase 44 仅立字段（default=dict），从不写内容；下游 prompt 无上游契约 | done 回填时启发式提取落库 + 下游 dispatch 时沿 depends_on 注入 prompt | 本 phase（45） | 兑现 ARTIFACT-01/02 跨仓契约传递 |
| 下游仓编码 prompt 仅含本仓 global_context + 任务 | prompt 新增「上游产物 / 上游契约」段（空产物零回归） | 本 phase（45） | wave1 后端契约 → wave2 前端可消费 |

**Deprecated/outdated:** 无（纯新增能力，无废弃 API；不改 Phase 44 任何契约）。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | v0.8 路径启发式归类模式集合（`openapi`/`swagger`/`.proto`/`.graphql`/`schema`/`/api/`）足够覆盖常见契约文件 | Code Examples | 低——CONTEXT 标为 Discretion；归类不全只是某些契约未进桶，`modified_files` 仍完整保留，下游可见全量变更文件 |
| A2 | 提取仅在 done 分支触发（failed 仓不提取产物） | Pattern 1 | 低——failed 仓无成功产物可注入；CONTEXT「上游 wave 的某仓进入 done 后提取」明确针对 done |
| A3 | 单测可用未保存的 `TaskResult(...)` 内存实例（不触 DB）验证 `build_produced_artifacts` | Pattern 2 / Validation | 低——Django 模型未 save 实例化不查 DB；字段为已设值标量 |
| A4 | 本 phase 不 emit `coding.artifact.*` 事件（§15 未定义） | Pitfall 5 | 低——不 emit 无副作用；接通需配套改 §15 + 守护测试，成本 > 收益 |
| A5 | `record_produced_artifacts` 覆盖写（非 merge）——单仓单 done 只提取一次 | Pattern 3 | 低——CONTEXT Discretion 倾向覆盖；幂等重写同产物等价 |
| A6 | 提取段 fail-soft 失败 → `produced_artifacts` 留空 dict → 下游注入段为空（可接受降级） | Pitfall 3 | 低——零回归路径；契约缺失只是下游少上下文，不阻塞编码 |

## Open Questions

1. **注入段在 prompt 中的精确插入位（global_context 之后 vs 分支信息之后）**
   - What we know: 当前 parts 顺序 `global_context → 分支 → 任务 → 文件 → 要求`（coding.py:1544-1578）；D-08 要求「项目背景之后、编码任务之前」。
   - What's unclear: 「分支信息」段夹在 global_context 与任务之间——上游产物段放 global_context 后（分支前）还是分支后（任务前）。
   - Recommendation: 放 global_context 之后、分支信息之前（最贴合 D-08「项目背景之后」字面），两者均满足「编码任务之前」。planner 按可读性定，零回归不受影响（空段不渲染）。

2. **同一下游仓多上游产物的渲染顺序稳定性**
   - What we know: `acollect_upstream_artifacts` 用 `async for task.depends_on.all()`，顺序由 M2M 默认排序决定。
   - What's unclear: 多上游时渲染顺序是否需确定性（影响集成测试断言稳定）。
   - Recommendation: 收集后按 `repository_id` 排序再渲染（确定性，便于 D-13 断言）；planner 可在 `acollect_upstream_artifacts` 末尾 `sorted(out, key=lambda a: a.get("repository_id",""))`。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Django ORM（JSONField 读写 + M2M 反查） | 提取写库 + 上游收集 | ✓ | django>=5.1 | — |
| `RepoCodingTask.produced_artifacts` 字段 | ARTIFACT-01 落库 | ✓（Phase 44 migration 0017 已建） | — | — |
| `SubAgentSession.task_result`（TaskResult OneToOne） | 提取来源 | ✓ | 本仓 | None → 占位 `{"available": false}` |
| `wave_progression._backfill_running_terminal` 收口 | 提取触发 | ✓（Phase 44 闭环） | 本仓 | — |
| `coding._dispatch_next_wave` → `_build_coding_prompt` dispatch 链 | 注入 | ✓（Phase 44 闭环） | 本仓 | — |
| `test_coding_wave.py` mock IO fixture | D-13 集成测试 | ✓ | 本仓 | — |
| 真实 runner + Docker 容器 | 真实端到端产物传递验收 | ✗ | — | mock IO 边界（SubAgentSession/TaskResult/dispatcher）单测/集成（既有 deferred） |

**Missing dependencies with no fallback:** 无。
**Missing dependencies with fallback:** 真实容器 E2E → mock IO 边界测试（CONTEXT 既有 deferred，本地无法闭环）。

## Validation Architecture

> `workflow.nyquist_validation: true`（config.json）→ 本节必含。

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 + pytest-asyncio + pytest-django 4.8（+ factory-boy / respx / pytest-socket） |
| Config file | `server/pyproject.toml`（`[tool.pytest.ini_options]` / coverage / ruff） |
| Quick run command | `cd server && uv run pytest tests/services/plan_orchestration/test_artifact_*.py tests/delivery/test_repo_coding_task_service.py -x` |
| Full suite command | `cd server && uv run pytest tests/services/plan_orchestration tests/delivery tests/test_coding_wave.py tests/test_coding_node.py -x` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ARTIFACT-01 (D-11) | `build_produced_artifacts`：git TaskResult 含 openapi/proto/schema 路径 → 正确归类 api_contracts/openapi | unit | `pytest tests/services/plan_orchestration/test_artifact_extraction.py::test_classify_git_artifacts -x` | ❌ Wave 0 |
| ARTIFACT-01 (D-11) | 无 TaskResult → 落 `{"available": false}` 占位（不抛） | unit | `pytest tests/services/plan_orchestration/test_artifact_extraction.py::test_no_task_result_placeholder -x` | ❌ Wave 0 |
| ARTIFACT-01 (D-11) | 空 modified_files → 产物结构合法、各桶为空、diff_summary files_changed=0 | unit | `pytest tests/services/plan_orchestration/test_artifact_extraction.py::test_empty_modified_files -x` | ❌ Wave 0 |
| ARTIFACT-01 (D-05) | `record_produced_artifacts` 幂等覆盖写（无 status guard，done task 可写） | unit | `pytest tests/delivery/test_repo_coding_task_service.py::test_record_produced_artifacts -x` | ❌ Wave 0 |
| ARTIFACT-02 (D-12) | `render_upstream_artifacts_section` 多上游 → 段含各仓契约文件名；空 → 返回 "" | unit | `pytest tests/services/plan_orchestration/test_artifact_injection.py -x` | ❌ Wave 0 |
| ARTIFACT-02 (D-12) | `_build_coding_prompt` 带 upstream_artifacts → prompt 含「上游产物」段 + 上游契约文件名 | unit | `pytest tests/test_coding_node.py::test_prompt_with_upstream_artifacts -x` | ❌ Wave 0 |
| ARTIFACT-02 (D-12) | `_build_coding_prompt` 不带 upstream → prompt 与现行为**逐字一致**（零回归断言） | unit | `pytest tests/test_coding_node.py::test_prompt_zero_regression -x` | ❌ Wave 0 |
| ARTIFACT-01/02 (D-13, SC-3) | 端到端：wave1 后端 done（TaskResult 含 openapi）→ aadvance 提取落 produced_artifacts → wave2 dispatch prompt/DispatchTask.metadata 含 wave1 契约 | integration | `pytest tests/test_coding_wave.py::test_upstream_artifacts_injected_downstream -x` | ❌ Wave 0（扩充既有文件） |
| ARTIFACT-01 (D-14) | INV-6：`produced_artifacts` 写入只经 `record_produced_artifacts`；旁路字段写断言 fail | unit | `pytest tests/delivery/test_repo_coding_task_inv6_guard.py -x` | ⚠️ 扩充（新增字段级守护） |
| ARTIFACT-01/02 (D-15) | 幂等/fail-soft：重复回调重复触发提取 → 覆盖写 no-op 语义；提取/收集/渲染异常 → warning 降级，wave 推进不失败 | unit/integration | `pytest tests/services/plan_orchestration/test_artifact_extraction.py::test_failsoft tests/test_coding_wave.py::test_extract_failsoft -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/services/plan_orchestration/test_artifact_*.py tests/delivery/test_repo_coding_task_service.py tests/delivery/test_repo_coding_task_inv6_guard.py -x`
- **Per wave merge:** `uv run pytest tests/services/plan_orchestration tests/delivery tests/test_coding_wave.py tests/test_coding_node.py -x`
- **Phase gate:** 全 server 测试 green（含 INV-6 守护扩充 + `test_coding_node` 12 passed 零回归 + `test_coding_wave` 既有 4 集成不破）

### Wave 0 Gaps
- [ ] `tests/services/plan_orchestration/test_artifact_extraction.py` — D-11 提取纯函数（归类/占位/空/fail-soft）
- [ ] `tests/services/plan_orchestration/test_artifact_injection.py` — D-12 渲染纯函数（多上游/空串）
- [ ] `tests/delivery/test_repo_coding_task_service.py` — 扩充 `record_produced_artifacts` 幂等覆盖写
- [ ] `tests/delivery/test_repo_coding_task_inv6_guard.py` — 扩充字段级 `produced_artifacts` 旁路写守护（D-14）
- [ ] `tests/test_coding_node.py` — 扩充 `_build_coding_prompt` 带/不带 upstream（零回归逐字断言）
- [ ] `tests/test_coding_wave.py` — 扩充 D-13 端到端（wave1 done→提取→wave2 prompt 含契约）；复用既有 `_dispatched`/`_stub_provider_resolution` fixture
- Framework install: 无需（pytest 已配）

## Security Domain

> `security_enforcement: true`, `security_asvs_level: 1`（config.json）。本 phase 纯内部后端基础设施，无新对外触面、无新凭证读取、无用户输入直连执行。

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | 无新认证面（容器回调端点 token 校验已存在，不改） |
| V3 Session Management | no | 无新会话 |
| V4 Access Control | yes（弱） | 提取按服务端权威 `SubAgentSession.task_result` / `RepoCodingTask.plan_version` 关联，绝不信 runner 可经 progress 篡改的字段（对齐 T-44-TAMPER）|
| V5 Input Validation | yes | `modified_files` / `raw_output` 是半可信容器产物 → 归类纯字符串匹配（不 eval、不执行）、长文本截断防 prompt 膨胀（Discretion）；`produced_artifacts` 注入前不解释执行 |
| V6 Cryptography | no | 无加密 |
| V7 Errors & Logging | yes | 产物**绝不**含 token/凭证（仅路径/URL/计数/契约片段）；日志仅 `has_*` 布尔/计数，不记产物正文（避免泄漏契约/路径敏感信息）|

### Known Threat Patterns for 跨仓产物传递
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| 凭证/token 经 `raw_output` 混入 produced_artifacts → 注入下游 prompt 泄漏 | Info Disclosure | 提取只取白名单字段（branch/commit/url/path/计数），不整体落 `raw_output`；对契约文本片段截断 + 不入日志 |
| 半可信 `modified_files` 含恶意超长/超多路径 → prompt 膨胀 DoS | DoS | 归类纯字符串匹配（无递归）；`diff_summary` 仅计数；超长契约文本截断（Discretion）；上游产物段可设条目上限 |
| runner 经回调篡改产物归属（写他人 plan_version 的 produced_artifacts） | Tampering / Elevation | 提取经服务端权威 `task.subagent_session_id` → `SubAgentSession` → `TaskResult` OneToOne 链，按 `RepoCodingTask` 服务端行写库，不信 runner 可改字段 |
| 提取/注入异常 → 回调 5xx 重试风暴 | DoS | 全程 fail-soft `logger.warning`；提取段独立 try/except 不冒泡 |

## Sources

### Primary (HIGH confidence)
- `server/services/plan_orchestration/wave_progression.py` — `_backfill_running_terminal`（line 126，`mark_done` at 144，`sess` at 139）**提取唯一挂载点**；fail-soft / async ORM 安全范式
- `server/services/plan_orchestration/wave_layering.py` — 纯函数模块风格蓝本（artifact_extraction/injection 对齐）
- `server/delivery/services/repo_coding_task_service.py` — `RepoCodingTaskService` 单一写入范式；`mark_done` filter().update() 幂等蓝本（record_produced_artifacts 镜像）
- `server/delivery/models/repo_coding_task.py` — `produced_artifacts` JSONField(line 80) 已建 + `depends_on`/`dependents` self-M2M(line 60)
- `server/subagent/models.py` — `TaskResult`(line 253) git 产物字段（branch_name/commit_sha/pr_url/modified_files/raw_output）+ OneToOne `session.task_result`(line 265-269)
- `server/workflows/nodes/ai/coding.py` — 注入链路：`_dispatch_next_wave`(844) / `_dispatch_wave`(520) / `_run_repo_coding`(1338) / `_build_coding_prompt`(1534, sync, parts 守卫 1566-1568)
- `server/services/plan_orchestration/__init__.py` — barrel 导出范式（新增 artifact 公共函数）
- `server/delivery/services/event_taxonomy.py` — §15 词表（artifact.* 未定义，wave.* RESERVED）
- `server/tests/delivery/test_repo_coding_task_inv6_guard.py` — INV-6 grep 守护范式 + 字段级盲区（Pitfall 6）
- `server/tests/test_coding_wave.py` — D-13 集成测试 mock IO fixture
- `.planning/DOMAIN-MODEL.md` §6(251)/§14(517)/§15(537) — RepoCodingTask produced_artifacts / 状态机 / 事件规格
- `.planning/phases/45-wave/45-CONTEXT.md` — 锁定决策 D-01~D-15
- `.planning/phases/44-.../44-RESEARCH.md` — 前序研究（格式/风格蓝本）
- `.planning/REQUIREMENTS.md` — ARTIFACT-01/02 验收

### Secondary (MEDIUM confidence)
- 无（本 phase 全部基于本仓源码核对，无外部文档依赖）。

### Tertiary (LOW confidence)
- 无。

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 无新依赖，全部现栈既有，源码逐文件核对
- Architecture: HIGH — 提取挂载点（wave_progression mark_done 后）、注入链路（dispatch chain）、产物来源（TaskResult）、写入口（service）均逐行核实
- Pitfalls: HIGH — 均来自源码注释/既有 Phase 经验（SynchronousOnlyOperation / fail-soft / INV-6 守护盲区 / §15 词表 / 零回归守卫）

**Research date:** 2026-06-16
**Valid until:** 2026-07-16（稳定内部基础设施；除非 wave_progression / coding.py dispatch 链 / TaskResult schema 被其他 phase 改动）
