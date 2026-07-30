---
phase: 113-2
plan: 03
requirements: [FLOW-05, SCHEMA-03]
provides:
  - "validate_repo_plan(content) -> tuple[bool, str | None]（`services/process_runtime/blueprint_repo_plan_schema.py`，纯函数、**绝不外抛**）：jsonschema Draft 2020-12 预编译 validator + 两条后置检查 —— (a) `impl_items[].depends_on` 只能引用本仓 `item_id`（跨仓走 apis_consumed）；(b) `apis_consumed[].data_source.availability == \"needs_support\"` 必须有非空 `data_source.support_repository_id`。报错经复制的 12 行 `_format_error` 脱敏 + 截断 500"
  - "十一字段 `BLUEPRINT_REPO_PLAN_SCHEMA`：repository_id / role / responsibility(Block[]) / fitness{verdict,reasons,citations} / current_state[{summary,findings[]}] / impl_items[] / apis_provided[] / apis_consumed[] / local_impact{} / risks(Block[]) / open_question_thread_ids[]；`required = [\"repository_id\", \"role\", \"impl_items\"]`"
  - "**`REPO_PLAN_CHANGE_TYPES = (\"create\", \"modify\", \"remove\", \"indirect_refine\")`** —— 与 111 `blueprint_schema` 的 `implementation_overview.items[].change_type` 逐字同源（**不是** PLAN 草案里的 new/modify/delete/indirect，见 Deviation 1；有一条测试断言两者列表相等）"
  - "**`REPO_PLAN_AVAILABILITY = (\"existing\", \"needs_support\")`**；`REPO_PLAN_ROLES = (\"direct\", \"indirect\")`；`REPO_PLAN_VERDICTS = (\"suitable\", \"partial\", \"unsuitable\")`"
  - "`apis_consumed[]` 形状：`{name, method, path, request_schema, response_schema, description, from_repository_id, data_source: {from_service, from_api, fields_needed[], availability ∈ existing|needs_support, support_repository_id, notes}, citations[]}` —— **可用性与协作仓一律在 `data_source` 下，无顶层 availability 字段**（有一条测试证明只写顶层键时后置检查 (b) 不触发）；`from_repository_id` 是中间产物专属键，融合投影时映射到 `data_source.from_service` / `support_repository_id`"
  - "**派发时已写入 `AgentSession.user = dispatch_user`**（`blueprint_research_adapter._dispatch_deep_task` 的 `AgentSession.objects.acreate(..., user=dispatch_user)`）：两个 mode 都写，`session.created_by` 为 None 时留空不伪造。这是 113-02 会话归属校验（`sub.main_session.user_id == request.user.id`）的唯一真实数据来源"
  - "`dispatch(session, *, force_deep_repository_ids=None, mode=\"research\", repository_ids=None) -> {dispatched, synthesized, degraded, tasks}`：`mode=\"plan\"` 换 `bp-plan-` 前缀 / `last_output.source=\"blueprint_repo_plan\"` / `CallSource.BLUEPRINT_REPO_PLAN` / `env_FRIDAY_TASK_KNOWLEDGE_QUOTA=\"400\"`，并**跳过轻量合成**；`repository_ids` 非 None 时跳过路由候选面。`mode=\"research\"` 缺省路径逐字等价 112（有实测断言）"
  - "`_build_prompt(..., mode=\"research\")` / `_build_dispatch_metadata(..., mode=\"research\")` / `_dispatch_deep_task(..., mode=\"research\")` 三处同样是带默认值 keyword-only；`env_FRIDAY_TASK_MODE` / `env_FRIDAY_TASK_TASK_MODE` 恒 `explore` 未动"
  - "`BLUEPRINT_REPO_PLAN_SOURCE = \"blueprint_repo_plan\"`（派发侧常量，`blueprint_research_adapter.__all__` 已导出；回调侧同值独立常量 `_BLUEPRINT_REPO_PLAN_SOURCE`）"
  - "`BlueprintRepoPlanAdapter(*, research_service=None, research_adapter=None, synthesizer=None, lifecycle_service=None, node_execution_id=\"\")` 八个公开成员：`acollect_locked_repos(session) -> list[{repository_id, repository_name, role, responsibility, fitness}]` / `dispatch_plans(session) -> {dispatched:int, synthesized:int, pending:int, completed:list, repositories:list}`（形状恒定）/ `acollect_repo_plans(session) -> dict[str, dict]` / `aall_repo_plans_ready(session) -> bool` / `arequest_targeted_research(session, repository_id) -> bool` / `arecord_repo_plan(task, section)` / `aopen_clarification(session, repository_id, detail) -> thread_id str` / `build_stage_state(*, plans, dispatched, pending, attempts=None) -> dict`"
  - "`stage_state[\"repo_plan\"]` 形状（`STAGE_STATE_KEY = \"repo_plan\"`）：`{\"ready_repository_ids\": [...], \"pending_repository_ids\": [...], \"attempts\": {rid: n}}` —— 只存 id 与计数，序列化后 < 2KB"
  - "`aall_repo_plans_ready` 的完成判据口径：锁定仓集里每仓**有非空 `repo_plan` 段** 或 **task 已 failed**（失败仓不阻塞 barrier）。只看产物存在性 + 失败终态，**不看 done/stale**（两 stage 共用同一 task），**不复用 `aall_research_tasks_terminal`**"
  - "`MAX_REPO_PLAN_ATTEMPTS = 2`（首轮 + 2 轮重试 = 3 次机会）；direct 仓的重试计数源是 **`SubAgentSession.session_id` 以 `bp-plan-{task.id.hex[:12]}` 为前缀的行数**（服务端生成、runner 不可篡改、跨阶段不串），indirect 仓由 adapter 内循环计数"
  - "callbacks 第四链函数名（113-04/06 可直接消费）：`_is_blueprint_repo_plan` / `_parse_blueprint_repo_plan(output) -> (section|None, err)` / `_aload_blueprint_plan_task` / `_acount_blueprint_plan_containers` / `_handle_blueprint_repo_plan_completion` / `_handle_blueprint_repo_plan_failure` / `_trigger_blueprint_repo_plan_barrier`；`mark_failed` 的 reason 枚举：`repo_plan_invalid_retrying`（重试中）/ `repo_plan_invalid`（超界）/ `container_failed`"
affects:
  - "113-04（等待原语与重派）：`dispatch(mode=\"plan\", repository_ids={rid})` 即单仓重派入口；`waiting_context` 分支挂在 `_handle_blueprint_repo_plan_completion` 的解析前探测位；配额已是 400"
  - "113-05（融合投影）：`repo_plan` 段的 `current_state` / `impl_items` / `apis_provided` / `apis_consumed` 字段名即投影源，`change_type` 与 `data_source.availability` 已与 111 schema 逐字对齐可直接搬；`from_repository_id` 需映射掉不落蓝图顶层"
  - "113-06（stage 注册）：`_h_bp_repo_plan` 调 `dispatch_plans` + `aall_repo_plans_ready` + `build_stage_state`；本 plan **完全没碰** `builtin_processes.py` / `entrypoint.py` / `blueprint_resume.py`"
  - "113-02（总线 MCP view）：会话归属校验的数据来源已就位（`AgentSession.user`）"
key-files:
  created:
    - server/services/process_runtime/blueprint_repo_plan_schema.py
    - server/services/process_runtime/blueprint_repo_plan.py
    - server/tests/services/process_runtime/test_blueprint_repo_plan_schema.py
    - server/tests/services/process_runtime/test_blueprint_repo_plan_stage.py
    - server/tests/subagent/test_blueprint_repo_plan_callback.py
  modified:
    - server/services/process_runtime/blueprint_research_adapter.py
    - server/subagent/api/callbacks.py
completed: 2026-07-30
---

# Phase 113-2 Plan 03: 阶段 2 分仓方案（RepoPlan） Summary

**一行结论**：RepoPlan 落地为两个新模块（独立 `blueprint_repo_plan_schema.py` 的十一字段 jsonschema + 两条后置检查绝不外抛；`blueprint_repo_plan.py` 的仓集/direct 派发/indirect LLM 合成/有界重试/自写完成判据），对 112 派发面只做 **11 行删改的加性扩展**（四处带默认值 keyword-only + `mode="research"` 缺省逐字等价，实测 `bp-research-` 前缀与 `blueprint_research` source 零回归），`callbacks.py` **纯追加**第四条 PLAN 链（`git diff | rg "^-"` 为空）；B1 的 `AgentSession.objects.acreate(..., user=dispatch_user)` 已落地并被**两个 mode 各一条**断言守住；41 例新测试全绿，`tests/{services/process_runtime,subagent,delivery}` 981 例零回归。

## Accomplishments

- **SCHEMA-03 schema 面**：`blueprint_repo_plan_schema.py` 三件套（模块级 schema dict → 预编译 `Draft202012Validator` → `validate_repo_plan`），报错出口是从 `blueprint_schema.py` **复制**的 12 行（零 import 受限模块的私有函数），整函数体外层包 `except Exception` 故 `rg "raise "` 零命中。两条后置检查：`depends_on` 仓内引用完整性、`needs_support` 必带 `support_repository_id`。**枚举与 111 逐字同源并有测试锁死**（`change_type` 与 `data_source.availability` 各一条断言直接读 `BLUEPRINT_JSON_SCHEMA` 比对），另有一条断言 111 的 `api_contracts.items.properties` **没有**顶层可用性键。
- **B4 定夺落地**：`apis_consumed[].data_source` 承载 `availability`（只有 `existing|needs_support`）与 `support_repository_id`；`rg '"available"|"unknown"'` 零命中。⭐ 一条**可证伪断言**：只写顶层同名键（无 `data_source`）时后置检查 (b) **不触发**，证明判定绝不取自幻觉字段。
- **FLOW-05 派发面加性扩展（改动可枚举，11 行 `-`）**：`dispatch` / `_build_prompt` / `_build_dispatch_metadata` / `_dispatch_deep_task` 各加带默认值 keyword；`mode="plan"` 只影响 prompt / `bp-plan-` 前缀 / `last_output.source` / `call_source` / 配额键五处；`env_FRIDAY_TASK_MODE` 与 `_bucket` / `_collect_candidates` 一行未改；`CallSource` 复用 111 已注册值（`git diff --stat server/agents/call_source.py` 为空）。新增 `_build_plan_prompt` + `_summarize_locked_role` + `_summarize_stage1` + `_plan_candidates` 四个纯追加成员。
- **⭐ B1 会话归属数据来源**：`AgentSession.objects.acreate(..., user=dispatch_user)`，`dispatch_user` 由既有 `_resolve_dispatch_user`（签名未改）解析，为 None 时留空不伪造 system 用户。三条断言：`mode="plan"` 与缺省 `mode="research"` 各断言 `sub.main_session.user_id == session.created_by_id`；`created_by=None` 时断言 `user_id is None` 且不抛、且不铸 token。
- **RepoPlan adapter 五面**：仓集取**最新** `ArtifactVersion`（`order_by("-version_no")`，测试构造「session 钉住空的 v1 + 最新 v2 有两仓」证明未读会话钉住的版本），缺失回落确认门快照；direct 派发前 `mark_stale` 置回可派发态再 `dispatch(mode="plan", repository_ids={rid})`；indirect 走服务端 LLM 合成（`ProviderConfigService.aresolve` → `build_chat_model` → `use_call_source` → `_content_to_text` / `_parse_json` 复制不 import），产物过 schema、`repository_id`/`role`/`responsibility` 由服务端权威覆写；有界重试耗尽后开 blocking 澄清线程并落 **degraded 但过 schema** 的最小 repo_plan（`impl_items=[]` + risks 写明原因 + `open_question_thread_ids` 带线程 id），绝不静默丢弃。
- **⭐ P-1 唯一防线**：落库唯一入口 `arecord_repo_plan` 强制 `{**prev, "repo_plan": section}`。回调测试预置含 `fitness.verdict="suitable"` + `findings` + §7 五键的 PartialPlan，写入 repo_plan 后断言 `acollect_fitness(session)[rid]["verdict"]` 仍是 `suitable`、`findings` 逐字相等、八个键仍在、历史行仍是 2 行未被覆盖。
- **⭐ P-4 四链两两互斥**：一条断言矩阵覆盖 `_is_blueprint_repo_plan` × `_is_blueprint_research` / `_is_plan_research` / `_is_repo_verify` 四向；另一条断言 `source="blueprint_research"` 的 session 跑第四链完成钩子后 task 状态与 PartialPlan 行数都不变（既有链零扰动）。
- **callbacks 第四链纯追加**：`git diff server/subagent/api/callbacks.py | rg "^-"` 输出为空（只跑 `ruff check`，**未跑 `ruff format`**）。落库前过 `validate_repo_plan`；不合格走有界重试（先 `mark_failed` 落终态再 `mark_stale`，见 Deviation 3）且**不落非法 content**；超界 `mark_failed({"reason": "repo_plan_invalid"})` + 开 blocking 澄清线程（测试断言 `thread.return_stage == "repo_plan"`）；barrier 用自写判据。
- **观测**：三个生命周期事件 `blueprint_repo_plan_dispatch_started/completed/failed`（`category="sampling"`、`component="process_runtime"`、completed 带 `duration_ms`），容器动作与澄清线程另记 `category="caller"` + `initiated_by_user_id`（无触发用户记 `system`）。异常文本一律 `redact_secrets_in_text` + 截断 500；方案正文零进日志与 `stage_state`。

## Task Commits

| Task | Commit | 内容 |
| ---- | ------ | ---- |
| 1 | `f4a33b9f` | `blueprint_repo_plan_schema.py`（十一字段 + 预编译 validator + 两条后置检查 + 脱敏截断）+ 12 例纯函数测试 |
| 2 | `a6f70d39` | 派发面 plan 模式四扩展点 + B1 `user=dispatch_user` + `blueprint_repo_plan.py`（仓集/派发/合成/落库/判据） |
| 3 | `dcad9ca4` | callbacks 第四条 PLAN 链（纯追加）+ 两个方法转公开 + 29 例回调面与编排面测试 |

## Files

- `server/services/process_runtime/blueprint_repo_plan_schema.py`（新建 ~330 行：四段模块 docstring、四个枚举常量、`BLUEPRINT_REPO_PLAN_SCHEMA`、`_REPO_PLAN_VALIDATOR`、复制的 `_format_error`、两个后置检查纯函数、`validate_repo_plan`）
- `server/services/process_runtime/blueprint_repo_plan.py`（新建 ~660 行：五段模块 docstring、`RepoPlanSynthesizer` Protocol + `LLMRepoPlanSynthesizer`、`BlueprintRepoPlanAdapter` 八个公开成员 + 六个 `@sync_to_async` / `afirst` 只读边界、八个模块级纯函数）
- `server/services/process_runtime/blueprint_research_adapter.py`（修改：11 行 `-`；新增 `BLUEPRINT_REPO_PLAN_SOURCE` 常量、`_plan_candidates` / `_build_plan_prompt` / `_summarize_locked_role` / `_summarize_stage1` 四个成员、`user=dispatch_user` 一行、plan 模式跳过轻量合成一段）
- `server/subagent/api/callbacks.py`（修改：**纯追加** ~190 行，第四链七个函数 + 两个挂载点 + 一条 `CallSource` 映射 elif）
- `server/tests/services/process_runtime/test_blueprint_repo_plan_schema.py`（新建 12 例，零 DB）
- `server/tests/services/process_runtime/test_blueprint_repo_plan_stage.py`（新建 16 例，`django_db(transaction=True)` + `asyncio`，`_FakeDispatcher` / `_FakeSynthesizer` 替身）
- `server/tests/subagent/test_blueprint_repo_plan_callback.py`（新建 13 例）

## Decisions

- **`change_type` 取既有枚举而非 PLAN 草案值**：PLAN 明确要求「先 rg 核对，若既有枚举用别的字面量则以既有为准（融合投影要直接搬）」，实测 111 的枚举是 `create|modify|remove|indirect_refine`，故照它落并加断言锁死（见 Deviation 1）。
- **`fitness.reasons` 允许 `string | object` 两种元素类型**：阶段 1 的 `PartialPlan.content.fitness.reasons` 是字符串列表（`callbacks._blueprint_str_list`），而确认门 `build_locked_associations` 投影后是 block 列表。两种来源都会被快照进 repo_plan，锁死单一类型会让合法产物判非法。
- **有界重试计数源用 `bp-plan-` 前缀的 `SubAgentSession` 行数**，不用 `RepoResearchTask.attempt`（跨阶段共用，阶段 1 已占一次）、不用 `stage_state`（并行容器 lost-update，回调路径按纪律永不写它）。前缀由派发侧服务端生成、runner 不可篡改，计数天然单调。
- **`arecord_repo_plan` / `aopen_clarification` 取公开名**：`callbacks.py` 需要跨模块调用它们，PLAN 伪码写的是私有名 `_arecord_repo_plan`；跨模块调私有方法是明确的代码异味，故在 Task 3 内改成公开名（该文件是本 plan 新建，无外部引用）。
- **不新增 `ConvergenceSessionEvent` 类型**：`event_taxonomy.py` 是 §13.2 绝对冻结面且不在本 plan 的 `files_modified` 内，而 taxonomy 里没有 `blueprint.repo_plan.*` 常量。故阶段 2 的观测**只走 structlog**（三事件齐全），`ConvergenceSessionEvent` 留给 113-06 连同 stage 注册一起补。
- **degraded 兜底产物自身再过一次 `validate_repo_plan`**：兜底若非法就宁可不落库（记 warning 留待下轮），杜绝「为了不丢弃而落进非法 content」。

## Deviations from Plan

共 6 处：2 处为 PLAN 前提与本仓事实不符的修正，3 处为被既有机制逼出的必要调整，1 处为改动预算内的等价搬移。

**1. [Rule 1 - 前提不成立] `REPO_PLAN_CHANGE_TYPES` 取 `create|modify|remove|indirect_refine`，不是 PLAN 写的 `new|modify|delete|indirect`**

- **Found during:** Task 1
- **Issue:** PLAN Task 1 给的字面量是 `("new", "modify", "delete", "indirect")`，同时要求「取值须与 `blueprint_schema.py` 的 `implementation_overview.items[].change_type` 枚举逐字一致，实现时先 rg 核对，若既有枚举用别的字面量则以既有为准」。实测 `blueprint_schema.py:441-445` 的枚举是 `["create", "modify", "remove", "indirect_refine"]` —— 照 PLAN 字面量会让 113-05 的融合投影必须做一层映射，或更糟：映射漏了就在 `validate_blueprint` 处判非法。
- **Fix:** 按 PLAN 自带的优先级规则以既有为准，并加一条测试 `test_change_type_enum_matches_blueprint_schema` 直接读 `BLUEPRINT_JSON_SCHEMA` 比对列表相等（将来任一侧漂移，这条先挂）。
- **Files modified:** `blueprint_repo_plan_schema.py`、`test_blueprint_repo_plan_schema.py`
- **Commit:** `f4a33b9f`

**2. [Rule 2 - 缺失关键功能] plan 模式必须跳过「无 runner 降级轻量合成」**

- **Found during:** Task 2
- **Issue:** 112 的 `dispatch` 在 deep 桶非空且零在线 runner 时整体降级为 `_synthesize_light_partial` + `record_partial`。该产物是**调研形状**（有 fitness、无 repo_plan），落库会把该仓最新 content 换成没有 `repo_plan` 段的一行 —— 阶段 2 的完成判据永远不满足，handler 每轮重进都再合成一次（无界重合成 + 反复覆盖最新行）。
- **Fix:** 在轻量分支前加一段**纯追加**的 `if mode == "plan": light_index = {}`（放在降级块之后，故降级搬过来的 deep 仓也被清掉）。无 runner 时该仓保持待办，`dispatch_plans` 见 `degraded=True` 记 `blueprint_repo_plan_dispatch_no_runner` warning。选纯追加写法而不是改 `if online == 0:` 条件行，是为了守住「派发面 `-` 行 ≤ 12」的验收（实测 11）。
- **Files modified:** `blueprint_research_adapter.py`
- **Commit:** `a6f70d39`

**3. [Rule 1 - 既有机制冲突] 有界重试必须「先 `mark_failed` 再 `mark_stale`」，且 plan 模式豁免 `_MAX_ATTEMPTS`**

- **Found during:** Task 3（写重试路径时实测）
- **Issue:** 两处冲突。① `ResearchService.mark_stale` 按 WR-01 **只动已终态**（done/failed）task，而 plan 容器回调时 task 是 `running` —— PLAN 写的「`mark_stale` 触发重跑」会静默 no-op，task 永久 running、barrier 永不满足。② `dispatch` 的 `_MAX_ATTEMPTS = 2` 判的是**跨阶段共用**的 `RepoResearchTask.attempt`，阶段 1 已把它涨到 1，故阶段 2 的**第一次重试**就会撞 `max_attempts_exhausted` 被判 failed —— 有界重试形同不存在，且失败仓不阻塞 barrier ⇒ 静默降级（正是 PLAN 明令禁止的）。
- **Fix:** ① 回调重试路径先 `mark_failed({"reason": "repo_plan_invalid_retrying", "detail": ...})` 落终态，再 `mark_stale([task.id])` 置回可派发白名单（两步都经 service，INV-6 未破）；测试断言第 1 轮后 task 是 `STALE` 且 reason 为 `repo_plan_invalid_retrying`。② 派发面的上界判定加 `mode != "plan"` 前缀（占 1 行 `-`），阶段 2 的上界改由回调侧按 `bp-plan-` 容器计数判（`MAX_REPO_PLAN_ATTEMPTS`），互不干扰。
- **Files modified:** `blueprint_research_adapter.py`、`callbacks.py`
- **Commit:** `a6f70d39` / `dcad9ca4`

**4. [Rule 1 - P-1 残留口] `_aload_latest_valid_content` 在全部行失效时回落最新的失效行**

- **Found during:** Task 2
- **Issue:** PLAN 写的是「`valid=True` + `-created_at` 取最新」。但 direct 仓派发前会 `mark_stale`，它会把阶段 1 的 PartialPlan 一并置 `valid=False` —— 等 plan 容器回调时「最新有效行」为空，合并基线是 `{}`，`repo_plan` 落库时把 112 的 fitness / findings / §7 五键一起吃掉。这正是 P-1 要防的失血，只是走的另一条路径。
- **Fix:** 先取 `valid=True` 的最新一行，取不到再回落**最新的失效行**（内容仍是阶段 1 的权威结论，只是被标失效待重跑），并在 docstring 写明理由。
- **Files modified:** `blueprint_repo_plan.py`
- **Commit:** `a6f70d39`

**5. [Rule 3 - PLAN 签名不足] `build_stage_state` 增 `attempts: dict | None = None` 可选 kwarg**

- **Found during:** Task 2
- **Issue:** PLAN 要求 `build_stage_state(*, plans, dispatched, pending)` 产出含 `attempts: {rid: n}` 的摘要，但三个入参里没有任何能给出「已重试次数」的信息源。
- **Fix:** 增一个可选 kwarg（缺省 `{}`），未给时对 `dispatched` 里的仓兜底记 1。调用方（113-06 handler）知道轮次就传，不知道就留空——绝不编造计数。
- **Files modified:** `blueprint_repo_plan.py`
- **Commit:** `a6f70d39`

**6. [Rule 3 - 范围外，未修] `tests/delivery/test_blueprint_context_seq.py::test_threaded_concurrent_appends_have_no_duplicate_or_gap` 在满套件下偶发失败**

- **Found during:** verification
- **Issue:** PLAN verification 全套跑第二遍时该例失败（第一遍 981 全绿）。它是 113-01 的 8 路真线程并发用例，在 SQLite 上靠吸收 `OperationalError` 重投跑通（113-01 SUMMARY 已记录该竞争是"并发确实发生"的证据）；满套件负载下写锁竞争加剧会超出其重投次数。
- **Fix:** 按范围纪律**不修**（该文件与本 plan 零交集）。单独重跑 `tests/delivery/test_blueprint_context_seq.py` 6 例全绿、单跑该例亦绿，确认是负载相关的既有 flake 而非本 plan 引入的回归。已在此登记供 113-01 归属方按需加固。
- **Files modified:** 无
- **Commit:** —

## 测试与验证

- `tests/services/process_runtime/test_blueprint_repo_plan_schema.py`：**12 passed**（合法 direct/indirect / 三必填缺失 / 三处枚举越界 + 旧变体 / 两条枚举同源断言 / depends_on / needs_support / ⭐顶层键不被识别 / 绝不外抛 / 脱敏截断）
- `tests/services/process_runtime/test_blueprint_repo_plan_stage.py`：**16 passed**（仓集取最新版本 + 快照回落 / direct 派发四断言 / ⭐B1 三条 / ⭐mode 缺省等价性 / 已有产物不重派 / 空仓集恒定形状 / indirect 合成不起容器 / degraded + 澄清线程 / 合成器异常隔离 / 完成判据三档 / 判据只看产物 / 一仓多条取最新 / 定向补调研委托 / stage_state < 2KB）
- `tests/subagent/test_blueprint_repo_plan_callback.py`：**13 passed**（⭐四链互斥矩阵 / 既有链零扰动 / 结构化与围栏两条成功路径 / ⭐P-1 fitness 不被吃掉 / 有界重试第 1 轮 stale / 超界 failed + blocking 线程带 `return_stage` / 自由文本判不合格 / 解析器残缺形状 / 失败回调 / 钩子异常 swallow 返 200 / call_source 映射 / 终态幂等）
- **PLAN verification 全套**：`uv run pytest tests/services/process_runtime/ tests/subagent/ tests/delivery/ -q` → **981 passed**（既有 940 例零扰动；第二遍有 1 例 113-01 并发 flake，见 Deviation 6）
- `uv run python manage.py makemigrations --check --dry-run`：退出码 **0**（零模型改动）
- `uv run ruff check services/process_runtime/ subagent/`：All checks passed；`ruff format --check` 两个新模块已格式化。**`subagent/api/callbacks.py` 全程未跑 `ruff format`**（P-10）
- **冻结面自检**：本 plan 三个 commit 共触及 **7 个文件**，全在 `server/services/process_runtime/{blueprint_repo_plan,blueprint_repo_plan_schema,blueprint_research_adapter}.py`、`server/subagent/api/callbacks.py` 与三个测试文件。`repo_router_v2 / decompose_segments / research_adapter / architect_merge_adapter / merged_plan / clarify_adapter / render / resume / builtin_processes / entrypoint / blueprint_schema / blueprint_route / blueprint_spec_gate / blueprint_confirm_gate / blueprint_resume / blueprint_lifecycle_service / charter_service / system/{models,settings_service} / event_taxonomy / call_source` **零命中**
- **受限面自检**：`git diff f4a33b9f~1 dcad9ca4 -- server/subagent/api/callbacks.py | rg "^-" | rg -v "^---" | wc -l` → **0**（纯追加）
- **派发面改动可枚举**：同口径对 `blueprint_research_adapter.py` → **11**（≤ 12），11 行逐条为被扩展的 4 个签名行、`candidates` 赋值行、`_MAX_ATTEMPTS` 判定行、`session_id` 行、两处 `source` 行、`_build_prompt` 与 `_build_dispatch_metadata` 两处调用行、`use_call_source` 行
- **并行自检**：本 plan 三个 commit 与 113-02 **零文件交集**（不含 `server/mcp_tools/`、`task/`、`server/tests/mcp_tools/`）
- 运行时验收：`rg -c 'mode: str = "research"'` = 4；`bp-plan-` / `BLUEPRINT_REPO_PLAN_SOURCE` / `CallSource.BLUEPRINT_REPO_PLAN` / `env_FRIDAY_TASK_KNOWLEDGE_QUOTA = "400"` 全命中；`env_FRIDAY_TASK_MODE` 邻行 `explore` 命中 3 处；`user=dispatch_user` 在 `AgentSession.objects.acreate` 后 8 行内；新模块内 `_collect_candidates` / `_bucket` / `aall_research_tasks_terminal` / `retry_task` / `session.current_artifact_version` **全部零命中**

## Self-Check: PASSED

- 文件存在：7 个 key-files 全部命中（5 新建 + 2 修改）
- commit 存在：`f4a33b9f` / `a6f70d39` / `dcad9ca4` 均在 `git log`
- artifacts contains 断言：`def validate_repo_plan` ∈ schema 模块 ✓；`BLUEPRINT_REPO_PLAN_SOURCE` ∈ `blueprint_repo_plan.py`（`__all__` 再导出）✓；`_is_blueprint_repo_plan` ∈ `callbacks.py`（5 处）✓；`acollect_fitness` ∈ 回调测试（P-1 断言）✓
- key_links 断言：`mode="plan"` ∈ `blueprint_repo_plan.py`（组合复用派发面）✓；`record_partial` ∈ `blueprint_repo_plan.py`（读-合并-写后调用，未再调 `mark_done`）✓；`validate_repo_plan` ∈ `callbacks.py`（落库前过 schema）✓
- must_haves truths 逐条：direct 起 plan 容器三特征 ✓／`mode="research"` 缺省等价 ✓／plan session 跑 `_is_blueprint_research` 为 False ✓／写入后 `acollect_fitness` verdict 不变 ✓／不合格有界重试后开 blocking 线程 ✓／indirect 服务端合成同形落库且不起容器 ✓／一仓多条取最新且历史行保留 ✓／`impl_items` 逐项带 `change_type` + `files_touched` + `depends_on` ✓

## Next Phase Readiness

- **113-04（等待原语与重派）**：单仓重派直接用 `research_adapter.dispatch(session, mode="plan", repository_ids={rid})`；`waiting_context` 分支请挂在 `_handle_blueprint_repo_plan_completion` 内**解析之前**的探测位（`_parse_blueprint_repo_plan` 之前先看 `output["waiting_context"]`），走「登记 waiter + 不判完成」并**跳过** `mark_failed`/`mark_stale` 分支；容器配额已是 400。
- **113-05（融合投影）**：`repo_plan.current_state` 直接投影 `current_state_analysis`（字段名已对齐）；`impl_items` 直接投影 `implementation_overview.items`（`change_type` 已同源，需补 `feature_point_id` 与 `repository_id`）；`apis_consumed[].from_repository_id` **不落蓝图顶层**，映射到 `data_source.from_service` / `support_repository_id`；⚠️ citations 仍是裸文件路径，投影前必须建引用池或按 112 白名单过滤（P-5 未在本 plan 处理）。
- **113-06（stage 注册）**：`_h_bp_repo_plan` 三步 —— `dispatch_plans(session)` → `aall_repo_plans_ready(session)` 判 `plan_complete` / `plan_dispatched` → `build_stage_state(plans=..., dispatched=..., pending=...)` 写 `stage_state["repo_plan"]`；deps 属性名请用 `repo_plan`（`entrypoint` 的 `SimpleNamespace(repo_plan=BlueprintRepoPlanAdapter(node_execution_id=...))`）。`blueprint_resume` 的 stage→status 映射需把 `repo_plan` 映到 `drafting`（本 plan 零触碰该文件）。
- **给后续 writer 的硬约束**：写 `repo_plan` 段**只能**经 `BlueprintRepoPlanAdapter.arecord_repo_plan`（读-合并-写）；新增 `open_thread` 调用**必须**带 `return_stage="repo_plan"`；`callbacks.py` 只跑 `ruff check`，绝不跑 `ruff format`。
