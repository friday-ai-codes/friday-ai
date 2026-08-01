---
phase: 113-2
plan: 04
requirements: [BUS-02]
provides:
  - "`task/core/blueprint_context_wait.py`：`await_blueprint_context(read_handler, key_pattern, *, kind=\"\", since_seq=0, timeout_minutes=3, poll_interval_s=5.0, _now=None, _sleep=None) -> dict`。返回**恒定形状** `{hit: bool, entry?: dict, reason?: str, waited_ms: int, polls: int, max_seq: int}`；`reason ∈ {timeout, tool_unavailable}`；**任何路径都不产 `is_error`**（超时是正常结果，agent 据此降级而非重试）"
  - "模块常量 `DEFAULT_TIMEOUT_MINUTES = 3` / `MAX_TIMEOUT_MINUTES = 5`（硬夹紧 `[0, 5]`，负值立即返回）/ `DEFAULT_POLL_INTERVAL_S = 5.0` / `_READ_LIMIT = 200`；纯函数 `matches_key_pattern(key, pattern)`（精确 / 单 `*` 全匹配 / 尾 `*` 前缀）与 `literal_prefix(pattern)`（首个 `*` 之前，用作服务端 `key_prefix` 收窄）"
  - "`KNOWLEDGE_TOOL_SCHEMAS` **现为 10 项**（7 legacy + read/report + await），`knowledge_allowed_tools()` 同步 10 条；新增导出 `AWAIT_CONTEXT_TOOL_NAME` / `READ_CONTEXT_TOOL_NAME` 与 `_attach_await_handler(sdk_tools)`。⚠️ **await 工具没有也不需要服务端 path**：它的 handler 是容器侧包装，复用工厂造出的 `read_blueprint_context` handler 作数据源"
  - "🔒 `_make_knowledge_handler` 签名 / HTTP 超时常量（`rg -c \"timeout=60.0\" == 1`）/ `quota_counter` 计数 **一行未改**；`rg -n \"callback\" task/core/knowledge_tools.py` 零命中（短等待不发心跳）；`git diff | rg \"^-\"` 为空"
  - "`server/services/process_runtime/blueprint_repo_waves.py`（**纯函数、零 ORM**）：`build_api_waves(repo_plans: dict[str, dict]) -> dict` 返回**恒定四键** `{waves: {int: [rid]}, edges: [{from, to, api}], cycles: [[rid]], unresolved_consumed: [{repository_id, api}]}`；`match_api(consumed, provided) -> bool`（`(method, path)` 全等 → 否则 `name` 全等）。输入只吃 `apis_provided` / `apis_consumed` 两个键，既接真实 repo_plan 段也接确认门条目的预估信息"
  - "波次语义：`provider → consumer` 建边（显式 `from_repository_id` 优先于形状匹配，且必须指向本次仓集内的仓否则记 unresolved）；Kahn 分层 wave 从 **1** 起；**成环的仓放最后一波**并在 `cycles` 如实上报（不丢仓、不静默打平）；零依赖输入 ⇒ 全部 wave 1（全并行，预排前行为零回归）"
  - "`BlueprintRepoPlanAdapter.aplan_waves(session, *, repos=None, plans=None) -> dict`：`build_api_waves` 四键 **再加** `stage_state_summary = {waves: {int: [rid]}, cycle_count: int, unresolved_count: int}`；命中 `cycles` 即开 blocking `ai_clarification`（`return_stage=\"repo_plan\"`，同 artifact 已有 OPEN 阻塞线程时幂等跳过）"
  - "`BlueprintRepoPlanAdapter.build_stage_state(*, plans, dispatched, pending, attempts=None, waves=None)`：`waves` 传 `aplan_waves` 的 `stage_state_summary` 即写入 `stage_state[\"repo_plan\"][\"waves\"] = {waves: {str: [rid]}, cycle_count, unresolved_count}`；不传则不写该键。**adapter 自身不落 stage_state**（本仓约定 handler 单点写，避免并行 lost-update）"
  - "`BlueprintRepoPlanAdapter.aredispatch_waiting_repos(session, repository_ids: list) -> int`：逐仓 `mark_stale`（仅终态 task）后 `dispatch(session, mode=\"plan\", repository_ids={rid}, resume_hints={rid: hint})`，返回真正重派的仓数；单仓失败只 warning 不上抛（调用方是 MCP 端点，上抛会反噬写入响应）"
  - "`BlueprintRepoPlanAdapter.aexpire_stale_waiters(session, *, max_age_seconds=DEFAULT_WAITER_MAX_AGE_SECONDS) -> list[str]`（默认 1800s）：委托 `BlueprintContextService.expire_waiters`，**不新起定时任务**，供 113-06 在 barrier 续驱路径调用一次"
  - "`dispatch_plans(session)` 返回形状**仍是恒定五键**（`dispatched/synthesized/pending/completed/repositories`，113-03 契约未加键）；行为变化只有一条：每次只派发**当前可派发波次**（最早那一波里还有仓没产出 `repo_plan` 的波次），后续波次进 `pending` 由 barrier 续驱推进"
  - "`waiting_context` 段三键约定（output 内与 `fitness` / `repo_plan` **平级**）：`keys: [str]`（必填非空才生效，单次最多登记 `_MAX_WAITING_KEYS = 5` 条）/ `partial_plan_id: str` / `reason: str`。⭐ **未新增 `last_output.source` 值**（仍是 `blueprint_repo_plan`），callbacks 四链互斥判定与两个挂载点零改动"
  - "回调侧新增 `_ahandle_blueprint_waiting_context(session, p, task, blueprint_session, log) -> bool`（挂在 `_handle_blueprint_repo_plan_completion` 内解析 `repo_plan` **之前**）：登记 waiter → 未成环则 `mark_failed(\"waiting_context\")` + `mark_stale` 置回可派发态；成环则**不置 stale 不派发**（澄清线程已由 service 开好）；全程不落 `repo_plan` 段、**不触发 barrier**"
  - "`ReportBlueprintContextView` 响应体新增 `redispatched: int`（键恒在，无 waiter 时为 0）；重派在 `satisfy_waiters` **之后**调用（顺序反了会重复重派），整段 `except Exception` 吞掉 + warning，`200` 与 `applied` 语义不变"
  - "`BlueprintResearchAdapter.dispatch(..., resume_hints: dict[str, dict] | None = None)` 贯穿至 `_build_plan_prompt(resume_hint=…)` 的续作段（`_summarize_resume`）：带 `partial_plan_id` 与已产出段名，**非重派场景恒为空串**，prompt 与首轮逐字一致"
affects:
  - "113-05（融合投影）：`build_api_waves` 的 `unresolved_consumed`（`[{repository_id, api}]`）即 `needs_support` 的前置信号 —— 找不到 provider 的 consumed 项在预排阶段已被点名，投影时按它标 `data_source.availability=needs_support` 并要求 `support_repository_id`；`edges` 可直接投影 `implementation_overview.items[].wave` 与跨仓 `depends_on`"
  - "113-06（stage 注册 / barrier 续驱）：① `_h_bp_repo_plan` 里调 `aplan_waves(session)` 取 `stage_state_summary` 再传 `build_stage_state(waves=…)` 持久化（adapter 不自己写 stage_state）；② barrier 续驱路径**必须**调一次 `aexpire_stale_waiters(session)`，把返回的仓清单喂 `aredispatch_waiting_repos`，否则「等的 key 永不出现」的仓会永久卡住；③ `blueprint_resume` 的 stage→status 映射仍归 113-06（本 plan 零触碰该文件）"
  - "115（时间线）：新增 caller 事件 `blueprint_repo_plan_waiter_redispatched`（structlog，payload `repository_id/dispatched/resumed/initiated_by_user_id`）与 `blueprint_repo_plan_waves_planned`（sampling），可与 `blueprint.context.waiter_*` 事件按 `session_id` 关联成「谁在等谁 + 何时被叫醒」时间线"
  - "容器镜像：新镜像多一个 `await_blueprint_context` 工具；老镜像没有它只是不调（白名单 task 侧硬编码，服务端无对应 path 也不影响）"
key-files:
  created:
    - task/core/blueprint_context_wait.py
    - task/tests/test_blueprint_context_wait.py
    - server/services/process_runtime/blueprint_repo_waves.py
    - server/tests/services/process_runtime/test_blueprint_repo_waves.py
    - server/tests/services/process_runtime/test_blueprint_context_wait_redispatch.py
    - server/tests/mcp_tools/test_blueprint_context_redispatch.py
  modified:
    - task/core/knowledge_tools.py
    - task/tests/test_blueprint_context_tools_schema.py
    - task/tests/test_knowledge_tools.py
    - task/tests/test_claude_sdk_integration.py
    - server/services/process_runtime/blueprint_repo_plan.py
    - server/services/process_runtime/blueprint_research_adapter.py
    - server/subagent/api/callbacks.py
    - server/mcp_tools/views.py
completed: 2026-07-30
---

# Phase 113-2 Plan 04: Context Bus 两档等待原语闭环 Summary

**一行结论**：短等待落在容器侧（`await_blueprint_context` 复用工厂造出的 read handler 做 `deadline` 有界轮询，命中即停、`since_seq` 增量、超时返 `hit=false` 的**正常结果**且经 MCP 包装后仍无 `is_error`，公共 handler 工厂一行未改），长等待落在编排侧（`waiting_context` 段登记 waiter 且**不判完成**、条目就绪时由**真打 `report_blueprint_context` 端点**在 `satisfy_waiters` 之后触发 `aredispatch_waiting_repos` 并带 `partial_plan_id` 续作），第一道防线是零 ORM 纯函数 `build_api_waves`（provider 仓先行、成环如实上报不丢仓、无 provider 记 `unresolved_consumed`），死锁防护在**登记瞬间**判环抛 blocking 澄清（零 sleep 依赖）；43 例新测试全绿（16 容器侧 + 14 纯函数 + 9 编排/回调 + 4 真打端点），`tests/{services/process_runtime,subagent,delivery,mcp_tools}` **1235 passed**（唯一失败是 113-02 已登记的子模块缺失守卫），且**三条路径的断言经变异验证逐一变红**。

## Accomplishments

- **短等待（容器侧有界轮询，工厂零改动）**：`deadline = now() + clamp(timeout_minutes, 0, 5) * 60` 即 while 唯一上界（`rg "while " | rg -v "deadline"` 零命中）；命中即 return 并**不再 sleep**（测试断言 `polls == 2` 且 `sleep` 只发生 1 次）；每轮以上一轮返回的 `max_seq` 作 `since_seq`（配额敏感路径不重复拉全量）；上游带工具错误标记的返回体或 handler 抛异常都只算「本轮未命中」**不中断等待**（服务端瞬时 502 不该让长依赖直接降级）；`read_handler is None` 立即降级返回 `tool_unavailable`。**不发心跳**、**无网络库 import**、命中条目正文零进日志（只记 `hit`/`polls`/`waited_ms`）。
- **🔒 公共工厂三条硬约束逐条守住**：白名单纯追加第 10 项后，`_attach_await_handler` 只把 await 那一个工具的 handler 换成包装（闭包持有同批工具里已造好的 read handler），故配额计数、脱敏、非 200 处理全部原样继承。守护断言：`inspect.signature` 参数名元组恒等、`inspect.getsource` 里 HTTP 超时常量仍在、`rg -c "timeout=60.0" == 1`、`rg "callback"` 零命中、`git diff | rg "^-"` 为空、read 工具的 handler 对象**原样保留**（`is read_handler`）而 await 的**已被替换**。
- **波次预排（BUS-02 第一道防线）**：`build_api_waves` 七类形态全覆盖（provider 先行 / 三层链 / 全并行 / 显式 `from_repository_id` 优先 / 成环 / 无 provider / 半可信输入）。显式 `from_repository_id` 指向仓集外的仓时**不建假边**而记 `unresolved_consumed`；同仓自产自消不建自环、不判成环。`dispatch_plans` 据此只派当前波次，首轮无接口信息时全部 wave 1（有一条专门用例断言两仓同轮派发，锁住零回归）。
- **长等待退出（回调侧纯追加）**：`waiting_context` 探测挂在 `_parse_blueprint_repo_plan` **之前**；`keys` 为空则原样落回正常解析路径（不吞产物，有专门用例）。未成环时按 113-03 Deviation 3 的既有事实「先 `mark_failed` 再 `mark_stale`」把 task 置回 STALE —— 直接 `mark_stale` 对 `running` task 是静默 no-op，会让重派永远派不出去。置成 STALE 而非 FAILED 是关键：`aall_repo_plans_ready` 把 FAILED 当「不阻塞 barrier」，若停在 FAILED，等待中的仓会被判成「可以往下走」。
- **⭐ 重派触发点落在真实端点（B2）**：`ReportBlueprintContextView._handle` 在 113-02 留下的接续点纯追加一次调用，位置严格在 `satisfy_waiters`（同事务置 `superseded`）之后 —— 顺序反了会重复重派烧额度。整段 `except Exception` 吞掉，`applied`/`200` 语义不变（有一条用例 monkeypatch 重派抛异常后断言 `applied is True` 且 waiter 仍被置位）。函数内 lazy import，`rg "^from services.process_runtime" mcp_tools/views.py` 零命中。
- **续作引用（prompt 不从零重做）**：`_aload_resume_hint` 只取该仓最新 `PartialPlan` 的 **id 与段名**，`_summarize_resume` 渲染成 prompt 末尾一段；非重派场景返回空串。有一条断言 `"看过了"`（上一轮正文）**不在** prompt 里 —— 续作引用绝不把半可信正文二次拼进执行指令。
- **互等环（登记瞬间判定，不靠超时）**：路径 3 用例全程零 `sleep`/零超时依赖（`rg "asyncio.sleep|time.sleep"` 零命中），断言第二次 `register_waiter` 即 `cycle_detected is True`、开出 1 条 blocking `ai_clarification`、`dispatcher.await_count == 0`、该 waiter 置 `superseded`、线程文本含两个仓 id 但**不含** reason 正文。`aplan_waves` 侧的环澄清另有一条断言 `return_stage == "repo_plan"`（B3）并验证幂等（第二次调用不叠开线程）。
- **观测**：新增事件全部带 `category` + `component` —— `blueprint_repo_plan_waves_planned` / `waiter_redispatch_completed` / `wave_cycle_clarification_failed` 走 `sampling`，`waiter_redispatched` / `wave_cycle_clarification_opened` / `blueprint_repo_plan_waiting_context_registered` 走 `caller` 并带 `initiated_by_user_id`（无触发用户记 `system`）。异常文本一律 `redact_secrets_in_text` + 截断 500；方案正文与条目正文零进日志、零进 `stage_state`。

## Task Commits

| Task | Commit | 内容 |
| ---- | ------ | ---- |
| 1 | `4b1569e5` | `blueprint_context_wait.py` 有界轮询 + 白名单第 10 项 + `_attach_await_handler`（工厂零改动）+ 16 例容器侧测试 + 三处既有计数守卫同步 |
| 2 | `0a5be7c8` | `blueprint_repo_waves.py` 纯函数 + `aplan_waves`/波次门控/`aredispatch_waiting_repos`/`aexpire_stale_waiters` + callbacks `waiting_context` 分支 + views 重派接线 + `resume_hints` 贯穿 + 14 例纯函数测试 |
| 3 | `0e7557c3` | 4 例真打端点（路径 1/2）+ 9 例编排与回调（路径 3、波次驱动、expire、事件）+ 变异验证 |

## Files

- `task/core/blueprint_context_wait.py`（新建 ~180 行：五段编号模块 docstring、四个常量、两个纯函数 + 一个解析 helper、`await_blueprint_context`）
- `task/core/knowledge_tools.py`（修改：+~90 行纯追加 —— 第 10 个表项 + 两个工具名常量 + `_attach_await_handler` + build 内 1 行调用；工厂 / `knowledge_allowed_tools` 一行未改）
- `task/tests/test_blueprint_context_wait.py`（新建 16 例）
- `server/services/process_runtime/blueprint_repo_waves.py`（新建 ~190 行：`build_api_waves` / `match_api` + 四个内部纯函数）
- `server/services/process_runtime/blueprint_repo_plan.py`（修改：+~290 行 —— `aplan_waves` / `_aopen_cycle_clarification` / `aredispatch_waiting_repos` / `aexpire_stale_waiters` / 两个只读边界 / 两个模块级纯函数 `_api_items`·`_current_wave`；`dispatch_plans` 加波次门控、`build_stage_state` 加 `waves` kwarg、`_normalize_locked_repos` 带出 `apis_*`）
- `server/services/process_runtime/blueprint_research_adapter.py`（修改：+~30 行，2 行 `-`（两处调用行加参数）—— `resume_hints` / `resume_hint` 四处 keyword-only 贯穿 + `_summarize_resume` + `_build_plan_prompt` 末尾追加一段）
- `server/subagent/api/callbacks.py`（修改：**纯追加** ~90 行 —— `_MAX_WAITING_KEYS` + `_ahandle_blueprint_waiting_context` + 完成钩子内 2 行探测；只跑 `ruff check`，**全程未跑 `ruff format`**）
- `server/mcp_tools/views.py`（修改：**纯追加** ~18 行 —— 重派接线 + `redispatched` 响应键）
- `server/tests/services/process_runtime/test_blueprint_repo_waves.py`（新建 14 例，零 DB）
- `server/tests/services/process_runtime/test_blueprint_context_wait_redispatch.py`（新建 9 例）
- `server/tests/mcp_tools/test_blueprint_context_redispatch.py`（新建 4 例，全部真打端点）

## Decisions

- **`aplan_waves` 返回摘要而不自己写 `stage_state`**：本仓既有约定是 adapter 返回 `stage_state_update`、handler 单点持久化（见 `blueprint_research_adapter.aadvance_reroute` 的 `"stage_state_update"` 返回键）。并行容器高频写单行 JSON 就是 PLAN prohibitions 点名的 lost-update 场景，波次摘要与 waiter 状态同理。故落法是 `aplan_waves` → `stage_state_summary` → `build_stage_state(waves=…)` → 113-06 handler 写一次。
- **`dispatch_plans` 返回形状不加键**：113-03 SUMMARY 把五键作为契约声明给下游，且有两条既有守卫用 `==` 全等断言。加键会撞它们且削弱「形状恒定」的价值，故波次信息只进日志与 `aplan_waves` 的返回值。
- **`waiting_context` 未成环时把 task 置 STALE 而不是留 FAILED**：`aall_repo_plans_ready` 视 FAILED 为「不阻塞 barrier」，停在 FAILED 会让等待中的仓被当成「可以往下走」，融合阶段拿不到该仓方案却照样推进 —— 这是比卡住更糟的静默降级。
- **重派用「该仓最新 `PartialPlan`」而不是 waiter 行里的 `partial_plan_id`**：`satisfy_waiters` 只返回仓 id 清单（113-01 契约），而 waiter 行此刻已被置 `superseded`。取最新 PartialPlan 更直接且始终是权威最新态；waiter 里的 `partial_plan_id` 仍原样保留供 115 时间线展示。
- **环澄清幂等按「该 artifact 有 OPEN 阻塞线程就不叠开」**：`aplan_waves` 每次 `dispatch_plans` 都会跑，逐轮开线程会刷爆 HITL 面板。已有阻塞线程时会话本就停着，再开一条零收益。
- **单次退出最多登记 5 条等待 key**：`waiting_context.keys` 是半可信输入，容器声明 100 个 key 不该炸出 100 条 waiter 行（每条都要跑一次环检测）。

## Deviations from Plan

共 5 处：2 处为 PLAN 内部自相矛盾/前提与本仓事实不符的修正，2 处为被既有契约与守护测试逼出的必要调整，1 处为范围外未修。

**1. [Rule 3 - PLAN 内部矛盾] `blueprint_context_wait.py` 保留一处**读取** `is_error` 的代码，未做到 acceptance 的「零命中」**

- **Found during:** Task 1
- **Issue:** PLAN 的 action 第 3 步明确要求「`is_error` 为真 → 视为本轮未命中并继续，不中断等待」（并有对应 must-have 用例），而同一 task 的 acceptance_criteria 又写 `rg -n "is_error" task/core/blueprint_context_wait.py` 零命中。两者不可同时满足 —— 除非把键名藏起来（纯混淆，反而更难审计）。
- **Fix:** 保留行为（有 `test_is_error_body_does_not_abort_wait` 覆盖），把 docstring/注释里的字面量改写成「工具错误标记」，使全文件只剩**一处**读取用途的 `is_error`（`raw.get("is_error")`）。等价且更强的验收改为：① `rg -n '"is_error"' | rg -v 'get\('` 零命中（从不**产出**该键）；② 单测直接断言返回 dict 与经 MCP 包装后的返回体都不含 `is_error` 键。`rg "httpx"` 零命中这条已按原样满足。
- **Files modified:** `task/core/blueprint_context_wait.py`
- **Commit:** `4b1569e5`

**2. [Rule 3 - 既有守护测试冲突] 白名单 9 → 10 撞三处既有计数快照**

- **Found during:** Task 1
- **Issue:** `task/tests/test_blueprint_context_tools_schema.py`（`== 9` ×2）、`task/tests/test_knowledge_tools.py`（`EXPECTED_TOOL_NAMES` 逐名列表，被两条用例消费）、`task/tests/test_claude_sdk_integration.py`（`== 9`）。同 113-02 偏差 2 的性质，PLAN 未预告。
- **Fix:** 计数改 10；`EXPECTED_TOOL_NAMES` 再拆一层 `_NEW_113_04_TOOL_NAMES`（逐名字面量守护强度未削弱，仍是逐名 + 计数双断言）。
- **Files modified:** 三个既有测试文件
- **Commit:** `4b1569e5`

**3. [Rule 3 - PLAN 的 files_modified 不完整] 续作引用注入必须改 `blueprint_research_adapter.py`（2 行 `-`）**

- **Found during:** Task 2
- **Issue:** PLAN action 要求「prompt 带 partial 引用续作 …… 在 113-03 的 `_build_plan_prompt` 里已预留位置则填充，否则在本 plan 追加一个可空串 section」，而 `_build_plan_prompt` 就在 `blueprint_research_adapter.py` —— 该文件既不在 `files_modified` 也不在 prohibitions（prohibitions 冻结的是同目录下**另一个**文件 `research_adapter.py`）。且 prompt 由 `dispatch` 内部构造，不加贯穿参数就无从注入。
- **Fix:** 加 `resume_hints`（`dispatch`）→ `resume_hint`（`_dispatch_deep_task` / `_build_prompt` / `_build_plan_prompt`）四处带默认值 keyword-only，`_build_plan_prompt` 末尾追加 `_summarize_resume(resume_hint)`（无 hint 恒空串）。改动共 2 行 `-`（两处调用行为传参而换行），`mode="research"` 与首轮 plan prompt 逐字不变（既有 16 例编排面测试全绿即证据）。
- **Files modified:** `server/services/process_runtime/blueprint_research_adapter.py`
- **Commit:** `0a5be7c8`

**4. [Rule 1 - 与既有契约冲突] `aplan_waves` 不直接写 `stage_state`，`dispatch_plans` 返回形状不加键**

- **Found during:** Task 2
- **Issue:** PLAN 写「结果写进 `stage_state["repo_plan"]["waves"]`」。但 ① 本仓没有任何 adapter 直接持久化 `stage_state`（一律返回 `stage_state_update` 由 handler 写），直接写就是 PLAN prohibitions 点名的 lost-update；② 先按 PLAN 把波次键加进 `dispatch_plans` 返回值后，113-03 的两条 `==` 全等守卫（`test_repo_with_existing_plan_is_not_redispatched` / `test_no_locked_repos_returns_constant_empty_shape`）立刻变红 —— 「形状恒定」是 113-03 明文交付的契约。
- **Fix:** `aplan_waves` 返回 `stage_state_summary`，`build_stage_state` 加 `waves=None` kwarg 落 `stage_state["repo_plan"]["waves"]`，由 113-06 的 handler 单点写（已写入 affects）。`dispatch_plans` 返回值回滚为原五键，波次信息只进日志与 `aplan_waves`。
- **Files modified:** `server/services/process_runtime/blueprint_repo_plan.py`
- **Commit:** `0a5be7c8`

**5. [Rule 3 - 范围外，未修] `tests/mcp_tools/test_skills_snapshot_guard.py::test_skill_files_discovered` 仍因子模块未 checkout 失败**

- **Found during:** verification
- **Issue:** 该守卫读 `skills/skills/*/SKILL.md`，本 worktree 的 `skills/` 子模块未 checkout。113-02 偏差 5 已登记，与本 plan 改动零因果。
- **Fix:** 按范围纪律不修。等价验收：`tests/mcp_tools/` 其余 231 例全绿，本 plan 新增 4 例全绿。⚠️ 113-02 留下的 CI 遗留提醒依然有效（`mcp/src/tools.ts` 需同步两个总线工具名）；**`await_blueprint_context` 不涉及该守卫**——它没有服务端 path，不进 `TOOL_SCHEMA_SNAPSHOT`（`git diff --stat mcp_tools/serializers.py mcp_tools/urls.py` 为空即证据）。
- **Files modified:** 无
- **Commit:** —

## 测试与验证

- `task/tests/test_blueprint_context_wait.py`：**16 passed**；`cd task && uv run pytest -q` → **263 passed, 3 skipped**（既有 247 例零扰动）
- `server/tests/services/process_runtime/test_blueprint_repo_waves.py`：**14 passed**（零 DB）
- `server/tests/services/process_runtime/test_blueprint_context_wait_redispatch.py`：**9 passed**
- `server/tests/mcp_tools/test_blueprint_context_redispatch.py`：**4 passed**（全部真打端点）
- **PLAN verification 全套**：`uv run pytest tests/services/process_runtime/ tests/subagent/ tests/delivery/ tests/mcp_tools/ -q` → **1235 passed, 2 skipped, 1 failed**（唯一失败是偏差 5 的子模块守卫）
- `uv run python manage.py makemigrations --check --dry-run`：退出码 **0**（本 plan 零模型改动）
- `uv run ruff check services/process_runtime/ subagent/`、`ruff check mcp_tools/views.py` 与四个测试文件、`cd task && ruff check core/`：全部 **All checks passed**。`subagent/api/callbacks.py` **全程未跑 `ruff format`**（P-10）
- ⭐ **变异验证（三条路径 + 两处机制的证伪能力实测，非声明）**：
  1. 把 read view 的 `since_seq` 写死 0 → `test_incremental_poll_sees_only_new_entry_after_report`（**路径 1**）fail；
  2. 把 views 的重派接线短路成 `if False` → `test_report_endpoint_redispatches_waiting_repo_with_partial_reference`（**路径 2**）fail；
  3. 把 `register_waiter` 的 `involved` 短路成 `[]` → `test_mutual_wait_cycle_opens_blocking_clarification_without_dispatch`（**路径 3**）fail；
  4. 去掉 `dispatch_plans` 的波次门控 → `test_dispatch_plans_only_dispatches_current_wave` fail；
  5. 让 `_ahandle_blueprint_waiting_context` 恒返 False → `test_waiting_context_registers_waiter_without_completing` fail。
  五处变异**已全部回滚**（`rg "MUTATION"` 零命中，`git diff` 干净）。三条路径的断言确实能逮住防线失效，不是恒真断言。
- **冻结面自检**：本 plan 三个 commit 触及 14 个文件，`repo_router_v2 / decompose_segments / research_adapter.py / architect_merge_adapter / merged_plan / clarify_adapter / render / resume / builtin_processes / entrypoint / blueprint_schema / blueprint_route / blueprint_spec_gate / blueprint_confirm_gate / blueprint_resume / blueprint_lifecycle_service / charter_service / system/{models,settings_service} / event_taxonomy` **零命中**（`blueprint_research_adapter.py` 与冻结的 `research_adapter.py` 是两个不同文件）；`git diff --name-only | rg "^web/"` 零命中
- **受限面自检**：`git diff | rg "^-"` 在 `server/subagent/api/callbacks.py` 与 `server/mcp_tools/views.py` 上**均为 0 行**（纯追加，113-02 的两个 view 主体与 113-03 的第四链一行未删改）；`task/core/knowledge_tools.py` 同为 0 行；`git diff --stat mcp_tools/serializers.py mcp_tools/urls.py builtin_processes.py entrypoint.py blueprint_resume.py` 输出为空
- **运行时验收（acceptance greps 逐条）**：`rg -c '"name": "' task/core/knowledge_tools.py` == 10；`rg -c "timeout=60.0"` == 1；`rg "callback"` 零命中；`rg "while " blueprint_context_wait.py | rg -v deadline` 零命中；`rg "httpx" blueprint_context_wait.py` 零命中；`rg "import.*models|objects\.|sync_to_async" blueprint_repo_waves.py` 零命中；`rg "apscheduler|CronTrigger|IntervalTrigger"` 在两个服务端模块零命中；`rg "satisfy_waiters" -A 14 mcp_tools/views.py | rg "aredispatch_waiting_repos"` 命中（顺序正确）；`rg "^from services.process_runtime" mcp_tools/views.py` 零命中；`rg "aredispatch_waiting_repos" test_blueprint_context_wait_redispatch.py` **零命中**（未绕过端点充当路径 2 证据）；`rg "asyncio.sleep|time.sleep" test_blueprint_context_wait_redispatch.py` 零命中

## Self-Check: PASSED

- 文件存在：14 个 key-files 全部命中（6 新建 + 8 修改）
- commit 存在：`4b1569e5` / `0a5be7c8` / `0e7557c3` 均在 `git log`
- artifacts contains 断言：`deadline` ∈ `blueprint_context_wait.py` ✓；`def build_api_waves` ∈ `blueprint_repo_waves.py` ✓；`waiting_context` ∈ `callbacks.py` ✓；`aredispatch_waiting_repos` ∈ `mcp_tools/views.py` ✓；`/api/mcp/tools/report_blueprint_context/` ∈ `tests/mcp_tools/test_blueprint_context_redispatch.py` ✓；`cycle_detected` ∈ `tests/services/process_runtime/test_blueprint_context_wait_redispatch.py` ✓
- key_links 断言：`read_blueprint_context` ∈ `blueprint_context_wait.py` 与 `knowledge_tools._attach_await_handler`（复用工厂 handler 作数据源）✓；`register_waiter` ∈ `callbacks.py` ✓；`repository_ids` ∈ `blueprint_repo_plan.aredispatch_waiting_repos`（`dispatch(mode="plan", repository_ids=…)`）✓
- must_haves truths 逐条：短等待命中即停（`polls == 2` + 1 次 sleep）✓／超时返正常结果无 `is_error` 且 `since_seq` 增量 ✓／长等待以 `waiting_context` 退出（source 未新增）→ 登记不判完成 → report 写入时置 `superseded` 并重派带 `partial_plan_id` ✓／重派触发点是真打 `POST /api/mcp/tools/report_blueprint_context/` ✓／互等环第二次登记即开 blocking 线程且零 dispatch ✓／波次按 provider 先行、成环如实上报不打平、纯函数可单测 ✓／白名单 10 项且工厂签名·超时·配额计数零改动 ✓

## Next Phase Readiness

- **113-05（融合投影）**：消费 `build_api_waves` 的 `unresolved_consumed` 作 `needs_support` 前置信号（找不到 provider 的 consumed 项已被点名，无需再自己对账一遍）；`edges` 可直接投影 `implementation_overview.items[].wave` 与跨仓 `depends_on`。⚠️ 波次预排只吃 `apis_provided` / `apis_consumed` 两个键，**不从 responsibility 文本猜接口** —— 投影侧若要更强的对账，请自己另建（本模块只在有结构化契约时建边）。
- **113-06（stage 注册 / barrier 续驱）**：① `_h_bp_repo_plan` 里 `aplan_waves(session)` → `build_stage_state(waves=result["stage_state_summary"], …)` 持久化（adapter 不自己写 stage_state）；② barrier 续驱路径**必须**调一次 `aexpire_stale_waiters(session)` 并把返回的仓清单喂 `aredispatch_waiting_repos(session, ids)`，否则「等的 key 永不出现」的仓永久卡住（本 plan 只提供方法，挂载点归 113-06）；③ `blueprint_resume.py` 本 plan **零触碰**，stage→status 映射与超时清理挂载仍归 113-06。
- **给后续 writer 的硬约束**：① 新增知识工具一律纯追加 `KNOWLEDGE_TOOL_SCHEMAS`，**绝不**改 `_make_knowledge_handler`（HTTP 超时常量 / 配额计数 / 不加回调参数三条）；需要循环或包装就照 `_attach_await_handler` 的范式复用已造好的 handler。② 容器等待类工具**超时一律返正常结果**，`is_error` 只留给参数错误与兜底异常。③ `waiting_context` 是 output 内平级段，**绝不**为它新增 `last_output.source` 值。④ waiter 状态与波次摘要都不由并发路径写 `stage_state`。⑤ 新增 `open_thread` 调用**必须**带 `return_stage="repo_plan"`；`callbacks.py` 只跑 `ruff check`。
