---
phase: quick-260729-emz-task-category-ask-clarification
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - server/agents/intent_router.py
  - server/agents/feature_solution_dispatch.py
  - server/orchestration/graph.py
  - server/agents/tools/clarification.py
  - server/initiatives/management/__init__.py
  - server/initiatives/management/commands/__init__.py
  - server/initiatives/management/commands/propose_project_repos.py
  - server/tests/test_intent_router.py
  - server/tests/agents/test_feature_solution_dispatch.py
  - server/tests/test_ask_clarification_tool.py
  - server/tests/test_chat_graph_clarification_interrupt.py
  - server/tests/initiatives/test_propose_project_repos_command.py
autonomous: true
requirements: [QUICK-EMZ-ROUTER, QUICK-EMZ-GUARD, QUICK-EMZ-REPOS]
must_haves:
  truths:
    - "项目级对话（bound_project_id 非空）用户说「生成技术方案 / 整体方案 / feature list / 全部模块」等强关键词时，服务端在跑 LLM 前直驱 FeatureSolutionService.start，不经 ask_clarification 单题卡"
    - "ask_clarification 选项 implies.task_category 为 feature_solution|full_tech_plan 且会话有 bound_project 时，resume 后 dispatch 正式编排（plan 多题卡 / blocking / finalizing），不只写 inferred_intent 回 executing 再猜"
    - "同 conversation 已有非终态 ConvergenceSession 时 dispatch 幂等 map 现有 session，不重复 start"
    - "项目级「方案覆盖范围」类 ask_clarification（技术方案覆盖/哪些模块/全部 N 个模块/整体方案/implies 方案类）被工具层拦截并引导立刻调 start_feature_solution；RELEV 选仓澄清（coding_change 或聚焦仓库且无模块/范围）放行"
    - "unknown task_category 被 strip + log task_category_rejected，整次 ask_clarification 仍 success（保 RELEV 选仓）"
    - "`python manage.py propose_project_repos <project_id> --initiated-by-user-id <id>` 经 RepoAssociationService.propose 写出候选（INV-6）；本任务不 SSH 写生产；SUMMARY 写明 10.8.8.153 补「高三提分专项」步骤"
  artifacts:
    - path: "server/agents/intent_router.py"
      provides: "TaskCategory / KNOWN_TASK_CATEGORIES / normalize_task_category / classify_solution_intent"
      exports: ["TaskCategory", "KNOWN_TASK_CATEGORIES", "normalize_task_category", "classify_solution_intent"]
    - path: "server/agents/feature_solution_dispatch.py"
      provides: "graph 可复用 dispatch helper → FeatureSolutionService + WorkflowState patch"
      exports: ["dispatch_feature_solution"]
    - path: "server/orchestration/graph.py"
      provides: "_execute_first_run 预 LLM 直驱 + wait_clarification resume 方案类 dispatch + 条件边"
      contains: "dispatch_feature_solution"
    - path: "server/agents/tools/clarification.py"
      provides: "scope guard + hidden conversation_id + unknown task_category strip"
      contains: "ask_clarification_scope_blocked"
    - path: "server/initiatives/management/commands/propose_project_repos.py"
      provides: "propose_project_repos management command（dry-run / confirm）"
  key_links:
    - from: "orchestration.graph._execute_first_run"
      to: "agents.feature_solution_dispatch.dispatch_feature_solution"
      via: "bound_project_id + classify_solution_intent(user_message) 命中后早返回 WorkflowState patch"
      pattern: "dispatch_feature_solution"
    - from: "orchestration.graph.wait_clarification_node"
      to: "agents.feature_solution_dispatch.dispatch_feature_solution"
      via: "normalize_task_category(implies.task_category) ∈ {feature_solution,full_tech_plan}"
      pattern: "normalize_task_category"
    - from: "agents.feature_solution_dispatch"
      to: "initiatives.FeatureSolutionService.start + feature_solution_tools._map_state"
      via: "复用 _map_state / _resolve_conversation_context；状态映射绝不走 ask_clarification marker"
      pattern: "PLAN_CLARIFICATION_RENDER_MARKER|_map_state"
    - from: "agents.tools.clarification.ask_clarification"
      to: "Conversation.bound_project + scope heuristics"
      via: "hidden conversation_id auto-inject（chat_runner 既有范式）"
      pattern: "conversation_id"
    - from: "propose_project_repos"
      to: "RepoAssociationService.propose"
      via: "ContextLinkService._afeature_corpus 等价语料 → INV-6 唯一写入口"
      pattern: "RepoAssociationService\\(\\)\\.propose"
---

<objective>
项目级对话技术方案第二批（接 260728-ppb）：用受约束 `task_category` + 服务端直驱 `FeatureSolutionService` 兜底路由，挡住「方案覆盖范围」类 `ask_clarification`，并提供可复用 `propose_project_repos` 命令补「高三提分专项」关联仓库（生产步骤只写 SUMMARY，本任务不写库）。

Purpose: 第一批已修 Prompt Center 漂移与引导文案，但 LLM 仍可能用 `ask_clarification` 问「覆盖哪些模块」而不调 `start_feature_solution`；服务端必须在关键词命中 / implies.task_category 命中时直驱正式编排，并在工具层拦截范围澄清。

Output: `intent_router` 枚举与分类器 + `feature_solution_dispatch` + graph 双挂载 + `ask_clarification` 护栏 + `propose_project_repos` command + 测试。

**Locked decisions（D-01 / D-02 / D-03，不可推翻）：**
- D-01：Router — `TaskCategory` / `normalize_task_category` / `classify_solution_intent` + dispatch helper + `_execute_first_run` / `wait_clarification` 双挂载 + 幂等 active session + unknown category strip + 埋点
- D-02：Guard — 项目级范围启发式拦 `ask_clarification` + hidden `conversation_id` + RELEV 白名单 + `ask_clarification_scope_blocked`；graph `_extract_pending_clarification` 二次兜底**不做**（工具层已阻断 pending marker，成本/收益不划算——写清取舍）
- D-03：`propose_project_repos` 代码 + 测试 + SUMMARY 生产步骤；不 SSH 写生产

**明确不做：**
- 不改 Prompt Center / coding_guidance（第一批已做）
- 不改 chat_runner 工具白名单
- 不删除 create_coding_plan
- 不在本任务 SSH / 直连生产 DB 写库
</objective>

<execution_context>
@/Users/zaneliu/Projects/open-source/friday-clean/.cursor/gsd-core/workflows/execute-plan.md
@/Users/zaneliu/Projects/open-source/friday-clean/.cursor/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.cursor/rules/observability-logging.mdc
@.planning/quick/260728-ppb-start-feature-solution/260728-ppb-SUMMARY.md
@server/agents/intent_router.py
@server/agents/tools/clarification.py
@server/agents/tools/feature_solution_tools.py
@server/agents/chat_runner.py
@server/orchestration/graph.py
@server/initiatives/services/feature_solution_service.py
@server/initiatives/services/repo_association_service.py
@server/initiatives/services/context_link_service.py
@server/tests/test_intent_router.py
@server/tests/test_ask_clarification_tool.py
@server/tests/agents/test_feature_solution_tool.py
@server/tests/code_relations/test_rebuild_chunk_edges_command.py
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Router — task_category + feature_solution_dispatch + graph 双挂载</name>
  <files>server/agents/intent_router.py, server/agents/feature_solution_dispatch.py, server/orchestration/graph.py, server/tests/test_intent_router.py, server/tests/agents/test_feature_solution_dispatch.py, server/tests/test_chat_graph_clarification_interrupt.py</files>
  <behavior>
    - `normalize_task_category(None/"")` → None；`"coding_change"` / `"needs_clarification"` 原样；`"feature_solution"` / `"full_tech_plan"` 合法；未知字符串 → None
    - `classify_solution_intent("帮我生成技术方案", bound_project_id="uuid")` → `feature_solution`；无 bound_project → None；弱信号「改一下登录」→ None
    - `classify_solution_intent` 对「整体方案 / 创建方案 / feature list / 全部.*模块」等强关键词命中（有 bound_project）
    - dispatch：mock `FeatureSolutionService.start` 返回 awaiting_confirmation → patch.phase 走 finalizing（或等价收尾），tool/marker 为 `plan_clarification`，**绝不是** `ask_clarification`
    - dispatch：researching → phase waiting + blocking_tasks 含 session_id；completed → finalizing + final_answer 含 markdown；failed → error/finalizing 带错误文案
    - 同 conversation 已有 status∉{done,failed} 的 ConvergenceSession → 不调 start，直接 `_map_state`/`_abuild_state` 现有 session
    - `_execute_first_run`：bound_project + classify 命中 → 不调 `_run_chat_stream`
    - `wait_clarification_node` resume：implies.task_category=feature_solution + config.bound_project_id → dispatch；条件边离开 wait_clarification，不无条件进 executing 再跑 LLM
  </behavior>
  <action>
实现 D-01。

**1) `server/agents/intent_router.py`（纯函数，保持 ≤1ms / 不调 LLM/DB）：**
- 新增 `TaskCategory`（`Literal` 或 `Final` 字符串别名）与 `KNOWN_TASK_CATEGORIES` frozenset，至少含：`coding_change`、`needs_clarification`、`feature_solution`、`full_tech_plan`（兼容既有 implies 用法）。
- `normalize_task_category(raw) -> TaskCategory | None`：strip、小写可选；未知 → None（不抛）。
- `classify_solution_intent(message, *, bound_project_id) -> TaskCategory | None`：`bound_project_id` 空 → None；否则强关键词启发式（技术方案 / 整体方案 / 生成方案 / 创建方案 / feature list / 全部.*模块 等）；命中返回 `feature_solution`（`full_tech_plan` 与 `feature_solution` 在路由层合并——classifier 可统一返回 `feature_solution`，normalize 仍接受两者）。
- 扩展 `test_intent_router.py` 覆盖上述 case；词典变更与测试同步。

**2) 新建 `server/agents/feature_solution_dispatch.py`：**
- 公共入口建议：`async def dispatch_feature_solution(*, conversation_id, bound_project_id, user_message="", initiated_by_user_id="", run_id="", writer=None) -> dict[str, Any]`，返回可直接 merge 进 `WorkflowState` 的 patch。
- 复用 `feature_solution_tools._resolve_conversation_context` / `_map_state`（可从该模块 import 私有 helper，或把二者上提为共享函数——优先 import 既有私有函数，避免大搬家）。
- 幂等（D-01）：dispatch 前查 `ConvergenceSession.objects.filter(conversation_id=...).exclude(status__in=[DONE, FAILED]).order_by("-created_at").afirst()`；有则 `FeatureSolutionService.get` 或 `_abuild_state` 映射现有 session，**不**再 `start`。
- 无 active session：`FeatureSolutionService().start(project_id=bound_project_id, entrypoint="chat", actor=..., initiated_by_user_id=..., conversation_id=conversation_id)`（feature_list 走项目已录入源，对齐工具默认）。
- 将 `_map_state` 的 `ToolResult` 映射为 graph patch（D-01 硬约束：走 plan_clarification / blocking_tasks / finalizing，**绝不**产 `marker=ask_clarification`）：
  - `STATUS_AWAITING_CONFIRMATION`：`phase=finalizing`；`final_answer` 用 `_summarize_questions` 或等价中文摘要；`tool_calls` 可放一条合成记录（name=`start_feature_solution`，result 含 `PLAN_CLARIFICATION_RENDER_MARKER`）便于审计；前端卡由 runtime `pending_plan_clarification`（ConvergenceSession）驱动。
  - `STATUS_RESEARCHING`：确保 `register_blocking_task` 已调用；`phase=waiting` + `blocking_tasks`。
  - `STATUS_COMPLETED`：`phase=finalizing` + `final_answer=markdown`。
  - `STATUS_FAILED`：`phase=error`（或 finalizing + 可读错误）；错误文案经 `redact_secrets_in_text`。
- 埋点（caller，`component="agents"`）：`solution_intent_detected`（分类命中时）、`solution_intent_dispatched`（成功，含 `duration_ms` / `session_id` / `status`）、`solution_intent_dispatch_failed`（异常，best-effort，含 `duration_ms`）；字段带 `conversation_id`、`bound_project_id`、`initiated_by_user_id`（无则 `system`）。观测失败吞掉，不反噬。

**3) `server/orchestration/graph.py` 双挂载：**
- `_execute_first_run`：在 `_build_chat_runner` 成功之后、`_run_chat_stream` **之前**，读 `cfg.bound_project_id` + `state.user_message`；若 `classify_solution_intent(...)` 命中，或 `normalize_task_category((state.result_metadata or {}).get("inferred_intent", {}).get("task_category"))` ∈ `{feature_solution, full_tech_plan}`，则 `await dispatch_feature_solution(...)` 并 early-return patch（写 PHASE_TRANSITION，persist phase）。未命中走原 LLM 路径。
- `wait_clarification_node`：签名增加 `config: RunnableConfig`（对齐 `executing_node`）。resume 后解析 `implies`；若 `normalize_task_category(implies.get("task_category"))` ∈ 方案类 **且** `cfg.get("bound_project_id")` 非空 → 调用 dispatch，返回其 patch（清 `pending_clarification`，可保留 `inferred_intent` 审计字段）；否则保持现有「改写 user_message + inferred_intent → executing」行为。
- 拓扑：将 `builder.add_edge("wait_clarification", "executing")` 改为 conditional（复用或薄包装 `route_after_executing` 逻辑）：若 resume 后 `phase` 已是 `waiting` / `waiting_clarification` / `finalizing` / `error` / `completed` 则路由到对应节点或 END 路径，**避免**方案类 dispatch 后又无条件进 executing 再跑一轮 LLM。非方案类 resume 仍进 `executing`。
- `ask_clarification` 对 unknown `implies.task_category` 的 strip 落在 Task 2 工具层；本任务 router 只提供 `normalize_task_category` 供 Task 2 调用。

测试：`test_feature_solution_dispatch.py`（纯 dispatch + mock service）；扩展 `test_chat_graph_clarification_interrupt.py` 或新建 graph 级测覆盖 wait_clarification 方案类 resume 不回 LLM。ruff line-length 100 / py314。
  </action>
  <verify>
    <automated>cd server &amp;&amp; uv run pytest tests/test_intent_router.py tests/agents/test_feature_solution_dispatch.py tests/test_chat_graph_clarification_interrupt.py --reuse-db -q --tb=short</automated>
  </verify>
  <done>
D-01 落地：合法 task_category 可 normalize；项目级强关键词 / implies 方案类均直驱 FeatureSolutionService 并映射为 plan_clarification/blocking/finalizing；幂等不双开 session；埋点三事件齐全；未知 category API 可供 Task 2 strip。
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Guard — 项目级方案范围 ask_clarification 护栏</name>
  <files>server/agents/tools/clarification.py, server/tests/test_ask_clarification_tool.py</files>
  <behavior>
    - schema properties 含 hidden `conversation_id`（description 含 auto-injected）；required 不含 conversation_id（由 chat_runner 注入，对齐 start_feature_solution）
    - 有 bound_project + question「本次技术方案覆盖哪些模块？」+ options 含「全部 N 个模块」→ ToolResult(success=False)，error 引导立刻调 `start_feature_solution`
    - implies.task_category 为 feature_solution|full_tech_plan（即使 question 弱）+ bound_project → blocked
    - implies.task_category=coding_change 的选仓澄清（question 聚焦仓库、无模块/范围词）→ success=True（RELEV 白名单）
    - 无 bound_project 的范围问法 → 不拦（非项目级）
    - options[].implies.task_category 未知 → strip 该 key + log `task_category_rejected`，整次 call 仍 success（若未命中范围启发式）
    - 命中拦截时 log `ask_clarification_scope_blocked`（sampling）
  </behavior>
  <action>
实现 D-02。

在 `ask_clarification` 参数列表增加 `conversation_id: str = ""`；`_TOOL_PARAMETERS.properties` 增加 `conversation_id`（description 标明 auto-injected，与 `feature_solution_tools` 一致）。**不要**改 `chat_runner` 白名单——既有 hidden-field 注入逻辑会在 properties 含 `conversation_id` 时自动注入（见 `chat_runner` ~677）。

校验顺序：既有 question/options 校验 → `_validate_options` → **新增**（D-02）：
1. 对每个 option 的 `implies`：若含 `task_category`，`normalize_task_category` 为 None → `pop` 该 key + `logger.info("task_category_rejected", category="sampling", component="agents", raw=..., conversation_id=...)`；**不** fail 整个 call（保 RELEV 选仓，D-01/D-02）。
2. 解析 bound_project：`conversation_id` 非空时 async 查 `Conversation.objects.filter(id=...).values_list("bound_project", flat=True).afirst()`（fail-soft：查库失败当无绑定，不抛穿工具）。
3. 若有 bound_project，且命中范围启发式 → `ToolResult(success=False, error="...")`，文案明确引导立刻调用 `start_feature_solution`（中文，说明项目级方案覆盖不走单题澄清）。启发式（question + options labels/hints/implies 拼接文本，大小写不敏感）：`技术方案覆盖` / `哪些模块` / `全部.*模块` / `整体方案` / 任一 implies.task_category ∈ {feature_solution, full_tech_plan}。
4. RELEV 白名单放行：`normalize_task_category(...)=="coding_change"` **或**（问题聚焦「仓库/选仓/哪个仓库」且**不含**模块/范围词）→ 不拦。
5. 拦截时 `logger.info("ask_clarification_scope_blocked", category="sampling", component="agents", conversation_id=..., question_preview=question[:80])`。

**取舍（D-02 写死）：** 不做 `graph._extract_pending_clarification` 二次兜底。理由：工具层 `success=False` 不会产出 `pending=True`+`ask_clarification` marker，graph 提取不到 pending；二次兜底重复且需解析已失败 tool result，成本高。若未来 LLM 绕过工具直接伪造 marker 再议。

扩展 `test_ask_clarification_tool.py`：registry schema 含 conversation_id；blocking / whitelist / strip-unknown / 无项目不拦。DB 用例用 `pytest.mark.django_db` + mock Conversation 或 fixture；无 DB 路径保持纯 asyncio。遵守 observability-logging.mdc；中文注释只写 why。
  </action>
  <verify>
    <automated>cd server &amp;&amp; uv run pytest tests/test_ask_clarification_tool.py --reuse-db -q --tb=short</automated>
  </verify>
  <done>
D-02 落地：项目级范围澄清被拦并引导 start_feature_solution；RELEV 选仓放行；unknown task_category strip 不炸 call；sampling 埋点存在；明确不做 graph 二次兜底。
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: propose_project_repos 命令 + 生产补数说明</name>
  <files>server/initiatives/management/__init__.py, server/initiatives/management/commands/__init__.py, server/initiatives/management/commands/propose_project_repos.py, server/tests/initiatives/test_propose_project_repos_command.py</files>
  <behavior>
    - `call_command("propose_project_repos", project_id, "--initiated-by-user-id", uid, "--dry-run")`：加载 Project+space、构建 feature corpus、调用 propose（可 mock），stdout 打印候选表；dry-run 不写库（mock assert 未调用或 service 短路）
    - 无 `--dry-run`：经 `RepoAssociationService.propose` 写入 proposed（INV-6）；测试 mock route/propose 断言调用参数含 project/space/initiated_by_user_id
    - `--confirm`：propose 后对全部候选 `confirm`（或等价批量确认 API）；缺省不 confirm
    - 缺 `--initiated-by-user-id` 或非法 project_id → CommandError
    - 帮助文案含 project_id / --initiated-by-user-id / --dry-run / --confirm
  </behavior>
  <action>
实现 D-03。

新建 `server/initiatives/management/` 与 `commands/` 包（空 `__init__.py`）。命令 `propose_project_repos.py`：
- 位置参数：`project_id`（UUID 字符串）。
- 选项：`--initiated-by-user-id`（必填）、`--dry-run`、`--confirm`（proposed 后 confirm 全部候选 repo_ids）。
- 实现：`Project.objects.select_related("space").aget(id=...)`；复用 `ContextLinkService._afeature_corpus(project)`（可实例化 service 调私有方法，或抽出共享 helper——优先直接复用，避免复制扁平化逻辑）；`space = project.space`；`RepoAssociationService().propose(space=space, features_flat=flat, project=project, initiated_by_user_id=...)`（D-03 / INV-6：**只**经该 service 写入）。
- `--dry-run`：仍可跑 corpus + mockable propose 预览，但跳过持久化——实现上优先在 command 内 dry-run 时只打印「将 propose 的 query 摘要 / feature 条数」，并 **不** 调用会写库的 propose；若复用 propose 难以只读，则 mock 测试钉住 dry-run 路径零写，生产 dry-run 打印 corpus 统计后退出。推荐：dry-run 打印 flat 条数 + space repo 范围，不调 propose；正式跑才 propose。
- `--confirm`：propose 成功后 `confirm(project=..., repo_ids=[全部候选], ...)`（查 `RepoAssociationService.confirm` 真实签名，按既有 API 传参；勿裸 update 模型）。
- 打印候选表：repo_id / name / score / confidence / reason（stdout，表格或对齐列）。
- 日志：`propose_project_repos_started` / `_completed` / `_failed`（caller，`component="initiatives"`，`duration_ms`，`initiated_by_user_id`，`project_id`，`dry_run`，`candidate_count`）。异常文本脱敏。

测试 `server/tests/initiatives/test_propose_project_repos_command.py`：照 `test_rebuild_chunk_edges_command.py` 用 `call_command` + `django_db` + mock `RepoAssociationService.propose`（及 confirm）；覆盖 dry-run 不写、正式 propose 调用、缺参 CommandError、help 含参数名。

**禁止：** 本任务内 SSH / 连接 10.8.8.153 / 对生产执行 command。

**SUMMARY 必须写明生产步骤（D-03）：**
```
# 在 10.8.8.153 friday-server 容器内
python manage.py propose_project_repos 75248ff9-3a22-4175-b940-6093d71eb4dc --initiated-by-user-id &lt;owner&gt;
# 然后 UI/API repo-decision accept
```
并说明：`feature_solution` 编排本身不依赖 RepoAssociation（走 space 全量仓）；补关联主要修面板空关联 + plan deepen 的 verified 消费链。

verify **不要**把未 migrate 的本地默认库 `manage.py` 裸跑退出码当绿灯——以 pytest `--reuse-db` 为准。
  </action>
  <verify>
    <automated>cd server &amp;&amp; uv run pytest tests/initiatives/test_propose_project_repos_command.py --reuse-db -q --tb=short</automated>
  </verify>
  <done>
D-03 落地：命令经 RepoAssociationService 提案（可选 confirm）；pytest 覆盖 dry-run/写路径/缺参；SUMMARY 含 高三提分专项生产补数步骤且本任务未碰生产库。
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| chat user → ask_clarification / graph resume | 不可信 question/options/implies；须校验并 strip 未知 task_category |
| graph → FeatureSolutionService | 服务端直驱；须验证 bound_project + conversation owner 经既有 service 权限 |
| ops → propose_project_repos | 管理命令持发起用户 id；只经 RepoAssociationService 写库（INV-6） |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-emz-01 | Spoofing | ask_clarification.conversation_id | mitigate | conversation_id 仅 chat_runner 注入；工具不信任模型伪造为授权依据，bound_project 只作启发式开关 |
| T-emz-02 | Tampering | implies.task_category | mitigate | normalize 白名单；unknown strip；方案类走 FeatureSolutionService 而非信任 LLM 自由文案 |
| T-emz-03 | Information Disclosure | dispatch / command logs | mitigate | structlog + redact_secrets_in_text；禁止把凭证写入事件字段 |
| T-emz-04 | Denial of Service | classify_solution_intent 误触发 | mitigate | 强关键词 + 必须 bound_project；幂等 active session 防重复编排风暴 |
| T-emz-05 | Elevation | propose_project_repos --confirm | mitigate | 仅 ops 跑 manage.py；写入收口 RepoAssociationService；本任务不远程执行 |
| T-emz-SC | Tampering | 无新 pip 依赖 | accept | 本计划不新增第三方包 |
</threat_model>

<verification>
全量相关测（reuse-db，勿用裸 manage.py 退出码当完成条件）：

```bash
cd server && uv run pytest \
  tests/test_intent_router.py \
  tests/agents/test_feature_solution_dispatch.py \
  tests/test_chat_graph_clarification_interrupt.py \
  tests/test_ask_clarification_tool.py \
  tests/initiatives/test_propose_project_repos_command.py \
  --reuse-db -q --tb=short
```

并确认：未改 `chat_runner` 工具白名单；未改 Prompt Center / coding_guidance；未删 `create_coding_plan`。
</verification>

<success_criteria>
- 项目级「生成技术方案」类消息在 LLM 前被直驱 FeatureSolutionService，UI 走 plan 确认卡而非 chat 单题范围澄清
- 方案类 implies.task_category resume 后 dispatch，不空跑 LLM
- 范围类 ask_clarification 在有 bound_project 时被拦；选仓澄清仍可用
- `propose_project_repos` 可本地 pytest 验证；SUMMARY 含生产补数说明且执行期未写生产
</success_criteria>

<output>
Create `.planning/quick/260729-emz-task-category-ask-clarification/260729-emz-SUMMARY.md` when done
</output>
