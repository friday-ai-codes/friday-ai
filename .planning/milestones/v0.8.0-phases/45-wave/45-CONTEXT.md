# Phase 45: 上游产物提取 + 注入下游 wave - Context

**Gathered:** 2026-06-16
**Status:** Ready for planning

<domain>
## Phase Boundary

本 phase 在 Phase 44 立的「多仓 wave 编码操作态脊柱 + 拓扑调度」之上，补上**跨仓上下文传递**的最后一环，纯后端基础设施（无新 UI 触面）：

1. **ARTIFACT-01 — 上游产物提取落库**：上游 wave 的某仓 `RepoCodingTask` 进入 `done`（终态回填时刻）后，从其 `SubAgentSession.task_result`（`TaskResult`：`branch_name` / `commit_sha` / `pr_url` / `modified_files` / `raw_output`）**提取结构化产物**（API 契约 / OpenAPI / diff 摘要），经**单一写入入口** service（INV-6）落 `RepoCodingTask.produced_artifacts`（Phase 44 仅立字段，本 phase 才真正写入内容）。

2. **ARTIFACT-02 — 注入下游 wave**：下游 wave dispatch 时，沿 `depends_on` 收集其上游仓的 `produced_artifacts`，注入下游容器编码 prompt（新增「上游产物 / 上游契约」段）与 `global_context`，使下游仓编码能消费上游契约（如 wave1 后端产出 API 契约 → wave2 前端 prompt/上下文含该契约）。

**复用 Phase 44 既有机制（硬约束，不另造）**：提取**只挂在** `wave_progression._backfill_running_terminal` 的 `mark_done` 终态回填点（唯一 done 收口）；注入**只走** `coding._dispatch_next_wave` → `_dispatch_wave` → `_run_repo_coding` → `_build_coding_prompt` 既有 dispatch 链；写库**只经** `RepoCodingTaskService`。绝不新建调度循环 / 轮询 / 第二套 dispatch / 旁路写表。

**显式不做**（留后续 phase / backlog）：多仓融合 PR + 跨仓 PR 关联（Phase 46）、编码遇阻 HITL question（Phase 47）、`follow_openspec=True` 的 openspec system prompt 注入（v0.9）、对 raw_output 做重度语义解析 / LLM 二次提炼产物（v0.8 仅做轻量启发式结构化提取，不引入额外 LLM 调用）、真实 runner + Docker 容器端到端验收（沿用既有 deferred，本 phase 以 mock IO 边界测试覆盖）。

</domain>

<decisions>
## Implementation Decisions

> 基础设施 phase——以下为「推荐 / 最安全默认」技术决策，均在 the agent's Discretion 范围内（无用户面交互，autonomous 模式已全部 AUTO-ACCEPT 推荐项）。Planner 可在 PLAN.md 细化，但应保持「挂既有 done 回填点 / 既有 dispatch 链、守 INV-6 单一写入、对空产物零回归、不造两套」的方向。

### Area 1：产物提取（ARTIFACT-01）

- **D-01 提取触发点**：唯一触发点 = `services/plan_orchestration/wave_progression.py:_backfill_running_terminal` 中 `service.mark_done(task)` 成功之后（task 由 running→done 的唯一收口）。`done` 后立即提取并落库，绝不另设轮询/定时器/第二处 done 收口。
- **D-02 提取来源**：按 `task.subagent_session_id` 标量取 `SubAgentSession`，再取其 `TaskResult`（OneToOne `task_result`，coding 任务 `result_type="git"`）。来源字段权威：`branch_name` / `commit_sha` / `pr_url` / `modified_files`(list) / `raw_output`(dict)。无 TaskResult（时序/异常）→ 落最小占位产物（`{"available": false}`），不抛错、不阻塞 wave 推进（fail-soft）。
- **D-03 产物结构（produced_artifacts JSON shape）**：结构化 dict，推荐键：`{"repository_id", "repository_name", "branch", "commit_sha", "mr_url", "modified_files": [...], "api_contracts": [...], "openapi": [...], "diff_summary": {...}, "extracted_at"}`。`api_contracts` / `openapi` 由对 `modified_files` 路径的**轻量启发式**归类（路径含 `openapi`/`swagger`/`.proto`/`schema`/`api/` 等模式 → 归入对应桶）；`diff_summary` 为 `{"files_changed": n}` 之类计数摘要。绝不存 token/凭证；产物仅含路径/URL/计数/契约文本片段，不入敏感值。
- **D-04 提取实现落点**：新增 `services/plan_orchestration/artifact_extraction.py`（纯函数 `build_produced_artifacts(task, session, task_result) -> dict` + 启发式归类 helper），与 `wave_layering.py` / `wave_progression.py` 同包（入口无关、可单测、可复用）。提取逻辑与归类启发式必须可被纯函数单测覆盖（无需 DB）。
- **D-05 单一写入入口（INV-6）**：`produced_artifacts` 写库新增 `RepoCodingTaskService.record_produced_artifacts(task, artifacts)`（`sync_to_async` 桥接，`update_fields=["produced_artifacts","updated_at"]`，幂等覆盖式写入）。`mark_done` 保持纯状态转移不变；提取→写库在 `_backfill_running_terminal` 内 `mark_done` 之后调用本方法。模型层零业务方法不破。提取/写库失败仅 `logger.warning` 降级，绝不让 wave 推进 / 回调主流程失败（对齐 Phase 44 fail-soft 范式）。

### Area 2：下游注入（ARTIFACT-02）

- **D-06 注入对象（哪些上游）**：下游 `RepoCodingTask` 的**直接** `depends_on` 上游仓的 `produced_artifacts`（DAG 边即直接依赖；wave gating 已保证 dispatch 时直接上游必为 done，故 `produced_artifacts` 必已落库）。直接依赖足以覆盖跨仓契约消费场景，不做传递闭包收集（避免上下文膨胀；间接上游的契约应由中间仓在自身产物中透传，非本 phase 目标）。
- **D-07 注入点**：唯一注入点 = `_dispatch_next_wave`（wave 推进 dispatch 下游时）收集每个待派发下游 task 的上游产物 → 传入 `_dispatch_wave` → `_run_repo_coding` → `_build_coding_prompt`。首发 wave（wave 0）无上游，注入为空（与现行为逐字等价，零回归）。
- **D-08 注入形态（prompt + global_context）**：`_build_coding_prompt` 新增 `upstream_artifacts` 参数，非空时渲染独立「# 上游产物 / 上游契约」段（列出每个上游仓的仓名、分支、MR、契约/OpenAPI 文件、变更文件清单），插在「项目背景(global_context)」之后、编码任务之前。同时把该段并入 prompt 即等价注入容器上下文（容器 prompt 即编码 agent 的 global context）；不新增第二条上下文通道。空产物 → 不渲染该段（无空标题、无回归）。
- **D-09 收集 helper 落点**：新增 `services/plan_orchestration/artifact_injection.py`（`acollect_upstream_artifacts(task) -> list[dict]`：沿 `task.depends_on` 反查上游 task 的 `produced_artifacts`，async ORM 安全经 `async for`；纯文本渲染 `render_upstream_artifacts_section(artifacts) -> str` 可纯函数单测）。`coding.py` 仅调用，不内联收集/渲染逻辑（保持节点薄、逻辑入口无关可复用）。
- **D-10 async ORM 安全**：收集上游沿 `depends_on`（M2M）只经 `async for task.depends_on.all()` / `*_id` 标量 / `afirst`，绝不在 async 上下文裸访问 lazy-FK（规避 `SynchronousOnlyOperation`，对齐 Phase 44 范式）。

### Area 3：测试与零回归（验收硬项）

- **D-11 提取单测**：纯函数 `build_produced_artifacts` —— 含 git TaskResult（modified_files 含 openapi/proto/schema 路径 → 正确归类 api_contracts/openapi）、无 TaskResult（落 `{"available": false}` 占位）、空 modified_files（产物结构合法、各桶为空）。
- **D-12 注入单测**：`render_upstream_artifacts_section` 纯函数（多上游 → 段含各仓契约；空 → 返回空串）；`_build_coding_prompt` 带 upstream_artifacts → prompt 含「上游产物」段且含上游契约文件名；不带 → prompt 与现行为逐字一致（零回归断言）。
- **D-13 端到端集成测试（SC-3 硬项）**：构造 wave1 后端仓 + wave2 前端仓（`depends_on` 跨仓边）；mock wave1 容器完成（SubAgentSession completed + TaskResult 含 openapi 文件）→ 经 `aadvance_coding_waves` 回填 done 触发提取落 `produced_artifacts` → 推进 wave2 dispatch → **断言 wave2 容器 dispatch 的 prompt / DispatchTask.metadata 含 wave1 产出的契约**（产物传递正确）。
- **D-14 INV-6 守护**：`produced_artifacts` 写入只经 `RepoCodingTaskService.record_produced_artifacts`，纳入既有 INV-6 grep 守护断言（旁路写 `produced_artifacts` 字段断言失败），对齐 Phase 44 grep 守护范式。
- **D-15 幂等 / fail-soft**：重复回调重复触发 done 回填 → `mark_done` 已幂等（仅 running→done），提取写库覆盖式幂等（重复写同产物 no-op 语义）；提取/收集/渲染任一环异常仅 warning 降级，wave 推进与容器回调主流程绝不因产物逻辑失败。

### the agent's Discretion

- 启发式归类的具体路径模式集合（`openapi`/`swagger`/`.proto`/`.graphql`/`schema`/`openapi.json|yaml` 等）、`diff_summary` 的具体字段、`produced_artifacts` 各桶命名细节由 planner 按最小实现/可读性定。
- `record_produced_artifacts` 是覆盖写还是 merge（倾向覆盖，单仓单 done 只提取一次）、是否在 `mark_done` 同事务内写由 planner 按最小 diff 决定（倾向 done 后独立调用，解耦状态转移与产物落库）。
- 上游产物注入段的中文文案/Markdown 结构细节、是否截断超长契约文本（倾向对 raw_output 摘要/截断防 prompt 膨胀）由 planner 定。
- 是否顺带发 `coding.artifact.extracted` / `coding.artifact.injected` trace 事件（DOMAIN §15 词表若已定义）由 planner 决定，倾向低成本接通。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `services/plan_orchestration/wave_progression.py:_backfill_running_terminal`——running→done 唯一回填收口（`service.mark_done(task)` 调用点）；**ARTIFACT-01 提取的唯一挂载点**。`aadvance_coding_waves` 的「回填→阻断→决策」三步顺序须保持不变，提取只在回填 done 后追加。
- `services/plan_orchestration/wave_layering.py`（`build_repo_waves` / `build_repo_dep_edges`）——同包纯函数范式蓝本，artifact_extraction/injection 新模块对齐其纯函数 + 可单测风格。
- `delivery/services/repo_coding_task_service.py:RepoCodingTaskService`——`produced_artifacts` 写库唯一入口（新增 `record_produced_artifacts`）；`mark_done`/`mark_running`/`mark_failed`/`mark_blocked` 单一写入范式蓝本（`sync_to_async` + `update_fields` + 条件更新幂等）。
- `delivery/models/repo_coding_task.py:RepoCodingTask`——`produced_artifacts JSONField(default=dict)` 已立（Phase 44），本 phase 写内容；`depends_on`(self-M2M) 正查上游、`dependents` 反查下游。
- `subagent/models.py:TaskResult`——coding 产物权威源（`result_type="git"`：`branch_name`/`commit_sha`/`pr_url`/`modified_files`(list)/`raw_output`(dict)）。OneToOne `session.task_result`。
- `workflows/nodes/ai/coding.py`：`_dispatch_next_wave`（wave 推进 dispatch 下游——ARTIFACT-02 收集+注入挂载点）、`_dispatch_wave`（批量 dispatch，传 prompt 上下文）、`_run_repo_coding`（构造 DispatchTask + prompt）、`_build_coding_prompt`（prompt 组装——上游产物段注入点；现 parts 顺序：global_context→分支→任务→文件→要求）。
- `subagent/api/callbacks.py`——容器回调收口（done 回填经此触发 `aadvance_coding_waves`），不改契约。

### Established Patterns
- 单一写入入口（INV-6）：状态/字段写库只经 service，模型层零业务方法，旁路写由 grep 守护断言。
- async ORM 经 `*_id` 标量 / `afirst` / `aexists` / `async for`，绝不裸访问同步 lazy-FK（规避 `SynchronousOnlyOperation`）。
- wave 推进 / 回调钩子 fail-soft：副作用失败仅 `logger.warning` 降级，绝不让回调主流程 5xx；幂等经条件更新/覆盖写。
- 入口无关 helper 抽到 `services/plan_orchestration/` 纯函数（mirror `wave_layering` / `resume`），coding.py 节点只调用不内联。
- ruff line 100、Python 3.14、async adrf；注释/docstring 中文（zh-CN）。
- 凭证/敏感值绝不入产物、不入日志（仅记 `has_*` 布尔 / 计数）。

### Integration Points
- 提取：`wave_progression._backfill_running_terminal`（done 回填后）→ `artifact_extraction.build_produced_artifacts` → `RepoCodingTaskService.record_produced_artifacts`。
- 注入：`coding._dispatch_next_wave`（收集上游）→ `artifact_injection.acollect_upstream_artifacts` → `_dispatch_wave` → `_run_repo_coding` → `_build_coding_prompt`（`render_upstream_artifacts_section`）。
- 新模块导出：`services/plan_orchestration/__init__.py` barrel（新增 artifact_extraction / artifact_injection 公共函数导出，对齐既有 `build_repo_waves` / `aadvance_coding_waves` 导出范式）。
- 无新模型 / 无新迁移（`produced_artifacts` 字段 Phase 44 已建表）。

</code_context>

<specifics>
## Specific Ideas

- ARTIFACT-01 提取**只挂** Phase 44 的 `mark_done` 终态回填点（唯一 done 收口），不另设第二处提取。
- ARTIFACT-02 注入**只走** Phase 44 既有 dispatch 链（`_dispatch_next_wave` → `_build_coding_prompt`），prompt 即容器编码上下文，不新增第二条 global_context 通道。
- 「空产物零回归」是命门：wave 0 / 无上游 / 提取失败 → 注入段为空 → prompt 与 Phase 44 现行为逐字一致。
- v0.8 仅做轻量启发式结构化提取（路径模式归类 + 计数摘要），不引入额外 LLM 调用做语义提炼（留 v0.9+）。
- 端到端验收（SC-3）以 mock IO 边界（SubAgentSession/TaskResult/dispatcher）覆盖「wave1 done → 提取 → wave2 prompt 含契约」全链路；真实 runner+Docker 沿用既有 deferred。

</specifics>

<deferred>
## Deferred Ideas

- 多仓融合 PR + 跨仓 PR 关联 → Phase 46（PR-01/02）。
- 编码遇阻 question 抛人（HITL）→ Phase 47（HITL-01）。
- `follow_openspec=True` 的 openspec system prompt 注入 → v0.9（仅留字段）。
- 对 raw_output 的重度语义解析 / LLM 二次提炼产物（结构化 API schema diff、契约语义比对）→ v0.9+（本 phase 仅轻量启发式）。
- 传递闭包（间接上游）产物收集 → 非本 phase 目标（直接 depends_on 足够；间接契约由中间仓透传）。
- chat 编码入口（`coding_session_service`）的上游产物注入接线 → follow-up（本 phase 优先 workflow 入口；artifact_extraction/injection helper 入口无关以便复用）。
- 真实 runner + Docker 容器端到端产物传递验收 → 既有 deferred（本地无法闭环）。

</deferred>
