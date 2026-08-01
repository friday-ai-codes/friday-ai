---
phase: 112-1
plan: 04
subsystem: process_runtime / 逐仓容器调研与有界重路由
requirements: [FLOW-02, FLOW-04]
provides:
  - "`BlueprintResearchAdapter.dispatch(session, *, force_deep_repository_ids=None) -> {dispatched: int, synthesized: int, degraded: bool, tasks: list[str]}`：形状恒定（零候选与正常路径逐键一致）"
  - "dispatch 的**增量候选来源**：`stage_state[\"routing\"].candidates` ∪ `stage_state[\"confirmation\"]` 内 `pending_research is True` 的仓（按 `repository_id` 去重，确认门条目覆盖路由条目）；派发白名单恒为 `PENDING` / `STALE`，`running` / `done` / `failed` 一律 skip"
  - "分桶规则：`role_suggestion == \"direct\"` → deep 起容器；`\"indirect\"` → light 服务端合成；两者皆缺时才回退 `confidence ∈ {high, medium}`"
  - "`aupgrade_to_deep(session, repository_id: str) -> bool`：112-05 第七个端点（`POST .../blueprint-gate/upgrade-research/`）直接调用。`True` = 已受理；`False` = 该仓不在候选与既有 task 内（→404）或依赖不可用（→503）"
  - "`decide_reroute(*, fitness, round_no, max_rounds=MAX_REROUTE_ROUNDS) -> {action, unsuitable_repository_ids, next_round, reason}` 纯函数三分支：`converged` / `reroute` / `escalate`(`reason=\"reroute_exhausted\"`)；**返回值里不存在 failed 类动作**"
  - "`aadvance_reroute(session) -> {event, stage_state_update, escalation, decision}`；`event ∈ converged | reroute_needed | exhausted`；`stage_state_update` 是浅合并后的**整字典**（112-05 handler 直接传给 `transition(stage_state=)`）"
  - "`acollect_fitness(session) -> {repository_id: {verdict, role_suggestion, responsibility, findings, task_status}}`：每 task 只取 `valid=True` 的最新一条 PartialPlan"
  - "`PartialPlan.content` 的 fitness 形状：`fitness{verdict ∈ suitable|partial|unsuitable, reasons[], citations[]}` + `role_suggestion ∈ direct|indirect` + `responsibility` + `findings[{title, detail, citations}]`，与既有 §7 键平级"
  - "`stage_state` 两个新键：`reroute{count, excluded[], last_reason}` 与 `repo_research_fitness{repository_id: {verdict, role_suggestion, task_status}}`（只存标量摘要，正文按 id 自取）"
  - "callbacks 的 `blueprint_research` 约定：`last_output = {source: \"blueprint_research\", blueprint_session_id, research_task_id, repository_id}` 是回调路由唯一依据；`CallSource.BLUEPRINT_REPO_RESEARCH` 映射已补"
  - "容器 env 三键契约：`env_FRIDAY_TASK_TOOLS_ENDPOINT` = `{FRIDAY_BASE_URL}/api/tools/execute/`、`env_FRIDAY_TASK_KNOWLEDGE_ENDPOINT` = 裸 base、`env_FRIDAY_TASK_USER_TOKEN` = `mint_task_token` 明文；**空值一律不注入该键**"
affects:
  - "112-05：`_h_bp_repo_research` 调 `dispatch()`；`_h_bp_reroute` 用 `aadvance_reroute()` 的 `event` 映射 StageOutcome、`stage_state_update` 整字典回写；确认门直接消费 `escalation` 快照与 `acollect_fitness` 聚合；第七个端点直调 `aupgrade_to_deep`"
  - "112-05 的 blueprint_resume：callbacks 的 barrier 在全部 task 终态时尝试调用 `services.process_runtime.blueprint_resume.aresume_blueprint_session(session)`（模块未落地时静默 no-op）——该函数名即接线契约"
  - "115：`blueprint.repo_research.started|completed|failed` 与 `blueprint.reroute.triggered` 四个事件 payload 在此定型（只含标量与关联键）"
tech-stack:
  added: []
  patterns:
    - "复制冻结 analog 的范式到独立新文件（零改动、零 import），派发五步与幂等白名单逐条镜像"
    - "单仓错误隔离（WR-02）：dispatch 异常只标该 task 失败 + emit + continue，绝不上抛"
    - "容器 metadata 逐键 env + 空值不注入；明文 token 只在内存直进 env"
    - "纯函数与 IO 分离：reroute 判定是无 DB 纯函数，轮次读写与事件在 async 入口"
    - "stage_state 浅合并整体回写 + session 重读新实例（整字典替换语义下的 lost-update 缓解）"
key-files:
  created:
    - server/services/process_runtime/blueprint_research_adapter.py
    - server/tests/subagent/test_blueprint_research_callback.py
    - server/tests/services/process_runtime/test_blueprint_research_stage.py
    - server/tests/services/process_runtime/test_blueprint_reroute.py
  modified:
    - server/subagent/api/callbacks.py
    - server/tests/services/test_event_taxonomy_alignment.py
decisions:
  - "dispatch 增加 `force_deep_repository_ids` 关键字：否则 `aupgrade_to_deep` 会被重新分回 light 桶再合成一遍，「升级为深调研」在生产上静默失效"
  - "轻量合成的 `fitness.verdict` 取 `partial`：没有容器读过代码，声称 `suitable` 会让确认门误以为已核实，声称 `unsuitable` 会误触发重路由"
  - "`role_suggestion` 非法/缺失回落 `direct`：把「要改的仓」误判成「不用改」的代价远高于反过来"
  - "`verdict` 非法即判不可解析 → mark_failed：宁可重跑，也不把编造结论落进蓝图投影数据"
  - "barrier 只负责「全部终态时叫醒续驱器」，轮次递增留在 `aadvance_reroute` 单点——回调路径永不触碰计数"
completed: 2026-07-30
---

# Phase 112-1 Plan 04: 逐仓容器调研与有界重路由 Summary

**一行结论**：`blueprint_research_adapter.py` 以独立新文件复制了冻结 analog 的派发范式（`research_adapter.py` 逐字未动、未被 import），PLAN 链首次接通容器上下文——`mint_task_token` 在 `SubAgentSession` 建行之后铸出的明文只经 dispatch metadata 进容器，三个 `FRIDAY_TASK_*` 键各自遵守「空值不注入」，dispatch 失败路径主动 `arevoke`；章程随 prompt 注入（不扩 MCP 白名单），direct 仓 fan-out 起 `SubAgentSession(TaskType.PLAN)` 容器、indirect 仓服务端轻量合成，结论一律经 `ResearchService.record_partial` 落 `PartialPlan.content` 的 `fitness`/`role_suggestion`/`responsibility`/`findings`；`callbacks.py` 以**纯追加**加了与 `repo_verify` 完全对称的第三条链；重路由判定是可单测纯函数，上界 2 轮，超限带全部现状升确认门——返回值里根本不存在 failed 类动作。

## Accomplishments

- **派发面（Task 1）**：`dispatch` 天然增量——候选取 `routing.candidates` ∪ 确认门 `pending_research` 仓并去重，只对 `PENDING`/`STALE` 的 task 起容器或合成，已 `done` 的仓连 `PartialPlan` 行数都不变（实测断言）。deep 桶前查在线 runner（3 倍心跳窗口 120s），无 runner 则**整体降级轻量不阻断**并记 `blueprint_repo_research_degraded_to_light`。单仓 dispatch 异常只 `mark_failed(dispatch_failed)` + emit + `continue`；缺 `git_url` 直接判失败不起占位容器；自实现重试上界 `_MAX_ATTEMPTS = 2`（既有 service 的重试入口硬编码 stage 名 `"research"`，本 stage 为 `repo_research` 会恒 raise，故未复用、也未改它）。

- **容器上下文接通（Task 1，ROADMAP SC3）**：`_build_dispatch_metadata` 在 explore 双键 + Claude runtime + git token 之上补三键。endpoint 由 `settings.FRIDAY_BASE_URL` 推导（`rg callback_url` 零命中），`FRIDAY_BASE_URL` 为空则两键均不注入；`dispatch_user` 只取 `session.created_by` 真实 `User` 实例（经 `sync_to_async`），为空则省略 token 键降级不挂（绝不伪造 actor）。顺带修掉 analog 的瑕疵：`env_FRIDAY_TASK_CLAUDE_BASE_URL` 改为空值不注入。实测 `AccessToken` 落 `kind="task"` + `session_id == subagent session_id` 行，且 `token_hash == hash_token(明文)`、明文不等于 DB 任何存储值。

- **章程 prompt 注入与轻量合成（Task 1）**：prompt 由服务端权威状态构造（需求目标 + 功能点 + 路由证据 + `## 仓库章程` 的 positioning/owned_domains/boundaries/evolution），写死 JSON 输出形状并附「判不出填 partial 并说明缺什么，不要猜」。轻量合成产出与深调研**同形**的 content，findings 来自路由期已有证据（能力树命中 / 章程领域 / 历史召回可得性），不编造。

- **回调第三条链（Task 2）**：`_is_blueprint_research` / `_parse_blueprint_fitness` / `_aload_blueprint_research_task` / `_handle_blueprint_research_completion|_failure` + barrier，形状与 `repo_verify` 分支完全对称；`_handle_completed` / `_handle_failed` 各加一段 `if ...: try/except`（注释沿用「永不阻塞主流程」）；`last_output.source → CallSource` 补一条。`git diff` 对 `callbacks.py` **无任何删除行**，既有两链与 `arevoke_task_tokens` 调用位置逐字未动，未新增吊销钩子。解析防御：缺 `fitness.verdict` → `mark_failed({"reason": "empty_or_unparseable_result"})` 且**不产生 PartialPlan 行**；`role_suggestion` 非法回落 `direct`；`reasons`/`citations`/`findings` 白名单归一 + 条数上界；`repository_id` 由服务端权威写入不采信容器上报值。

- **reroute 有界循环（Task 3）**：`decide_reroute` 纯函数三分支；`aadvance_reroute` 重读 session 新实例后 `{**state, ...}` 浅合并整体回写（`stage_state` 是整字典替换，只写增量会清空 `decomposition`/`routing`——有专项断言）；`escalate` 时 `escalation` 带每仓 verdict/role/responsibility 的全量快照，`stage_state` 里只留标量摘要（单字段 <2KB）；真正的 `transition` 留给 112-05 的 handler（engine 纯度）；计数递增在任何回调路径上都不存在。

- **观测面**：`blueprint_repo_research_dispatch_started|completed|failed` 与 `blueprint_reroute_decided` 等均带 `category="sampling"` / `component="process_runtime"` / `duration_ms`；容器动作与升级动作另记 `category="caller"` + `initiated_by_user_id`（无触发用户记 `system`）；四个 112-01 事件常量全部接上 emit 点，payload 只含标量与关联键。异常文本一律经 `redact_secrets_in_text`；明文 token / prompt 正文 / git token / 需求原文一律不进日志与事件 payload（`friday_pat_` 反向断言 + stdout 捕获断言双守）。

## Task Commits

| Task | Commit | 内容 |
| ---- | ------ | ---- |
| 1 | `40c096df` | 派发面：fan-out + token/env 三键 + 章程 prompt + 轻量合成 + aupgrade_to_deep |
| 2 | `1de751fa` | callbacks 第三条 PLAN 链（三件套 + 两挂载点 + CallSource 映射）+ 13 例回调测试 |
| 3 | `57cd9ec2` | reroute 判定面（纯函数 + 浅合并单点递增 + escalation 快照）+ 40 例测试 + 事件守护白名单 |

## 测试与验证

- 新增 **53 例**全绿：
  - `tests/subagent/test_blueprint_research_callback.py`：**13 passed**
  - `tests/services/process_runtime/test_blueprint_research_stage.py`：**20 passed**
  - `tests/services/process_runtime/test_blueprint_reroute.py`：**20 passed**
- PLAN verification 逐条实测：
  - `pytest tests/services/process_runtime/ tests/subagent/ tests/delivery/ -q` → **787 passed**
  - `pytest tests/test_task_token_lifecycle.py -q` → **16 passed**（既有 token 生命周期未被新链打破）
  - `pytest tests/services/ tests/delivery/ tests/subagent/ -q` → **1627 passed, 1 skipped**
  - `python manage.py makemigrations --check --dry-run` → `No changes detected`，退出码 **0**
- 冻结面自检：本 plan 三个 commit 只触及 6 个文件（2 源 + 4 测试）；`repo_router_v2.py` / `process_runtime/{decompose_segments,research_adapter,architect_merge_adapter,merged_plan,clarify_adapter,render,resume,builtin_processes}.py` / `research_service.py` / `access_tokens/services.py` / `workflows/nodes/ai/coding.py` / `event_taxonomy.py` **零命中**。
- 并行自检：`blueprint_spec_gate.py`（112-02 独占）/ `blueprint_route.py`（112-03 独占）/ `blueprint_lifecycle_service.py` 零命中。
- 受限面自检：`git diff HEAD~3 HEAD -- server/subagent/api/callbacks.py | rg "^-" | rg -v "^---"` 输出为空（纯追加）。
- acceptance rg 逐条：三个 env 键 / `FRIDAY_BASE_URL` / `mint_task_token` / `arevoke_task_tokens` / `use_call_source(CallSource.BLUEPRINT_REPO_RESEARCH)` / `pending_research` / `mark_stale` / `MAX_REROUTE_ROUNDS = 2` / `reroute_exhausted` / `{**state` / `valid=True` 全部命中；`callback_url` / `plan_research` / `retry_task` / `friday_pat_` / `STAGE_FAILED` / `"failed"`（排除 `mark_failed`/`RepoResearchTaskStatus.FAILED`/`task_status` 后）/ `import.*research_adapter` / adapter 内 `RepoResearchTask|PartialPlan.objects.(create|acreate|update|aupdate)` **全部零命中**；`rg -c _is_blueprint_research callbacks.py` = 5（定义 + 2 挂载点 + 2 handler 内判定）。
- 代码风格：改动文件经 `uv run ruff format` + `ruff check --fix`（`callbacks.py` 只跑 `check`，见 Deviations 4），All checks passed。

## Deviations from Plan

共 6 处，其中 3 处为按现实修正的事实性偏差、3 处为完成 PLAN 要求所必需的加性扩展。无功能缩水。

**1. [Rule 3 - 阻塞修复] `dispatch` 增加 `force_deep_repository_ids` 关键字参数**

- **Found during:** Task 1（实现 `aupgrade_to_deep` 时）
- **Issue:** PLAN 要求 `aupgrade_to_deep` = 「置 `STALE` 后重跑 `dispatch`，增量白名单天然只派发它一个」，但分桶依据是 `role_suggestion`——被升级的仓在 `routing.candidates` 里恰恰写着 `indirect`，重跑 `dispatch` 会把它**再次分进 light 桶重新合成一遍**，容器永不启动。「人工升级为深调研」会在生产上静默失效（PLAN Task 3 的 `aupgrade_to_deep` 断言 `dispatcher.await_count == 1` 正是这条的可证伪形式）。
- **Fix:** `dispatch(session, *, force_deep_repository_ids=None)`，`_bucket` 对该集合内的仓无条件进 deep 桶。默认 `None` ⇒ 与 PLAN 原签名行为逐字一致。
- **Files modified:** `server/services/process_runtime/blueprint_research_adapter.py`
- **Commit:** `40c096df`（`test_upgrade_to_deep_restages_done_light_repo` 锁死）

**2. [Rule 3 - 契约补全] `_build_dispatch_metadata` 签名增加 `repo` 与 `subagent_session_id`**

- **Found during:** Task 1
- **Issue:** PLAN 给的签名是 `(self, session, task)`，但同一处又要求「mint 必须在 `SubAgentSession` 建行之后，且 token 的 `session_id` 与 session 一致」——原签名没有承载 `subagent_session_id` 的入口；`repo` 也已在调用方取过一次（重复取会多打一次库）。
- **Fix:** `(self, session, task, *, repo, subagent_session_id)`。属 PLAN 授予的「adapter 内部函数切分自行决定」范围。
- **Files modified:** `server/services/process_runtime/blueprint_research_adapter.py`
- **Commit:** `40c096df`

**3. [Rule 3 - 契约补全] `BlueprintResearchAdapter.__init__` 增加第 4 个可注入依赖 `session_service`**

- **Found during:** Task 1
- **Issue:** PLAN 列了 3 个注入依赖（`research_service` / `dispatcher_factory` / `charters_loader`），但同时要求 emit 三类 `ConvergenceSessionEvent`——emit 通道 `ConvergenceSessionService._emit_event` 没有注入位。与 112-02 的同款偏差同源。
- **Fix:** 补 `session_service`（`x or DefaultX()` 兜底，生产零参构造）。
- **Files modified:** `server/services/process_runtime/blueprint_research_adapter.py`
- **Commit:** `40c096df`

**4. [Rule 1 - 事实修正] `callbacks.py` 只跑 `ruff check`，不跑 `ruff format`**

- **Found during:** Task 2 verify（跑「纯追加」验收时发现 diff 里有删除行）
- **Issue:** `callbacks.py` 存在**先于本 plan** 的 format 漂移（三处：`adrive_convergence_session_to_pause_or_terminal` 调用、`CodingSession.objects.filter(...)`、CODING 分支的 elif 条件）。对它跑 `ruff format` 会顺手重排这三处，直接打破 PLAN「callbacks.py 纯追加、既有分支一字不动」的硬约束。
- **Fix:** 手工回滚那三处重排，此后对该文件只跑 `ruff check`；我新增的 elif 写成单行条件形态，使 formatter 不会波及紧随其后的既有 elif。`git diff | rg "^-"` 现为空。既有 format 漂移属超出本 plan 范围的既存状态，**不顺手修**（scope boundary）。
- **Files modified:** `server/subagent/api/callbacks.py`
- **Commit:** `1de751fa`

**5. [Rule 3 - 阻塞修复] 事件守护测试白名单并入 `BLUEPRINT_EVENTS`（PLAN `files_modified` 之外的第 6 个文件）**

- **Found during:** Task 3 verify（`pytest tests/services/` 出现 1 红）
- **Issue:** `tests/services/test_event_taxonomy_alignment.py::test_referenced_constants_in_all_events` 扫 `callbacks.py` 的 emit 点并断言引用的常量 ∈ `ALL_EVENTS`。而蓝图事件按 112-01 的设计**刻意不进 `ALL_EVENTS`**（放独立 `BLUEPRINT_EVENTS`，正是为了避开同文件另一条「producer 覆盖性反查」的误挂）。112-02/03 从 `blueprint_*.py` emit 时不在扫描清单内所以没撞上；本 plan 首次从 `callbacks.py` emit 蓝图事件，必然撞。
- **Fix:** 守护断言改为 `referenced <= ALL_EVENTS | BLUEPRINT_EVENTS` 并在 docstring 写明理由。**没有**把蓝图事件塞进 `ALL_EVENTS`（那会同时改既有 taxonomy 语义并触发 producer 反查，违反 §13.2 第 3 条）。守护强度不变——仍然「不能引用任何未登记的事件常量」。
- **Files modified:** `server/tests/services/test_event_taxonomy_alignment.py`
- **Commit:** `57cd9ec2`

**6. [Rule 1 - 事实修正] 三处 PLAN 字面与现状不符的小口径**

- **Found during:** Task 1 / Task 2 / Task 3
- **Issue 与 Fix：**
  - **零候选短路的判据**：PLAN 写「缺 `"routing"` 键或 `candidates` 为空 → 返回零派发」，但它同时要求候选来源是 `routing` ∪ `confirmation` 两条并集。按字面实现会让「routing 为空但确认门 `add_repo` 加了新仓」的场景永不派发。实现改为**并集为空**才短路（PLAN 给的测试用例仍逐条通过，因其 `confirmation` 也为空）。
  - **`_aload_blueprint_research_task` 返回元组**：PLAN 写「返 `None` 使调用方 no-op」，但 emit 事件需要 `ConvergenceSession`。照既有 `_aload_research_task` 的 analog 返 `(task, session)`，不可用位各自为 `None`；测试断言 `[0] is None`。
  - **prompt 的「该仓 feature_point 子集」= 全集**：`stage_state["routing"]` 契约里没有 feature_point → 仓的映射（112-03 是整单需求级路由），无法真实切子集。写入全部功能点（各带 `intent`），并在 prompt 里附该仓的路由证据供容器自行核对——伪造一个"子集"反而会误导容器。
  - **Task 1 的 verify 命令**：PLAN 写 `-k "blueprint_research or blueprint_reroute"`，但两个测试文件按 PLAN 编排在 Task 3 交付，Task 1 时该过滤器收集不到用例（pytest 退出码 5）。Task 1 实际跑了整个 `tests/services/process_runtime/`（180 passed）作为无回归证据，Task 3 完成后原命令口径全绿。
- **Files modified:** 上述源文件与测试
- **Commit:** `40c096df` / `1de751fa` / `57cd9ec2`

## Known Stubs

一处**有意的接线占位**，非数据面缺口：

- `callbacks._trigger_blueprint_research_barrier`：全部 `RepoResearchTask` 终态后尝试 `from services.process_runtime import blueprint_resume` 并调 `aresume_blueprint_session(session)`；该模块由 **112-05** 交付，当前 `ImportError` → 记一条 `blueprint_research_barrier_reached`（`driver="pending_112_05"`）后 no-op。这是 wave 边界的必然状态（PLAN prohibitions 明令蓝图续驱走 112-05 的 `blueprint_resume.py`，本 plan 不得新建它），且不影响本 plan 的任何交付物：task 终态、`PartialPlan` 落库、事件 emit 全部已生效。**112-05 只需提供该函数名即自动接通。**

其余返回值均有真实数据源（`RepoRouterV2` 路由候选 / `RepoCharter` / `PartialPlan` / `Runner` 在线数），降级路径返回的空结构均带显式原因（`degraded` / `history_match_unavailable` / `error.reason`），不是未接线的占位。

## Threat Flags

无新增安全面。本 plan 引入的三处跨信任边界交互均落在 PLAN threat register 内且逐条落实：

- **T-112-15 / T-112-17（明文 token）**：明文只经 dispatch metadata；DB 只有 `hash_token`；日志只记 `has_user_token` 布尔与 `session_id`；事件 payload 无 token 材料。`dispatch_user` 只取 `session.created_by` 真实 User，为空则不注入该键。双向断言：`rg friday_pat_` 对源文件零命中 + 测试断言事件 payload 与 stdout 均不含该前缀串。
- **T-112-16（token 生命周期）**：mint 在 `SubAgentSession` 建行之后且 `session_id` 一致；终态吊销复用既有无条件 `arevoke_task_tokens`（未新增钩子）；dispatch 失败路径主动 `arevoke` 并实测 `revoked_at` 非空。**残余风险照 PLAN 接受**：`amark_timeout`/`amark_cancelled` 路径不吊销，靠 `expires_at`（timeout + 10min）自过期兜底——修它需改 callbacks 终态钩子，超出「加一条新链」的允许改动形状。
- **T-112-18（伪造 fitness）**：白名单 + 枚举校验 + 缺 verdict 即判不可解析 → `mark_failed`；`role_suggestion` 非法回落 `direct`；findings/reasons/citations 条数与文本长度双上界；`repository_id` 服务端权威覆写。
- **T-112-19 / T-112-20（无界 reroute 与 lost-update）**：`MAX_REROUTE_ROUNDS = 2` 纯函数判定 + 计数持久化；递增只在 barrier 后单点串行处，session 为刚读新实例，`{**state, ...}` 浅合并整体回写并有「不丢 routing/decomposition」断言。
- **T-112-21（异常文本含凭证）**：所有异常经 `redact_secrets_in_text`；git token 解析失败静默吞掉不记正文。
- **T-112-SC**：零新增外部依赖，零模型改动（`makemigrations --check` 退出码 0）。

## Self-Check: PASSED

- 文件存在：6 个 `key-files` 全部命中（4 新建 + 2 修改）
- commit 存在：`40c096df` / `1de751fa` / `57cd9ec2` 均在 `git log`
- artifacts `contains` 断言：`env_FRIDAY_TASK_USER_TOKEN` ∈ blueprint_research_adapter.py ✓；`_is_blueprint_research` ∈ callbacks.py ✓（×5）；`reroute_count` ∈ test_blueprint_reroute.py ✓（×3）
- key_links 断言：`mint_task_token` 在 `SubAgentSession` 建行之后调用（`_build_dispatch_metadata` 由 `_dispatch_deep_task` 第 4 步调用，第 3 步已 `acreate`）✓；`record_partial` ∈ callbacks.py ✓；`last_output={"source": "blueprint_research", ...}` 是回调路由唯一依据（测试断言不依赖 session_id 命名）✓
- 冻结面/受限面/并行面三项自检输出均为空 ✓

## Next Phase Readiness

- **112-05（stage 注册 + 确认门）**：
  - `_h_bp_repo_research` → `await deps.research.dispatch(session)`，`StageOutcome(event="research_dispatched", ...)` 走 self-loop 挂起（`wait_status="waiting_event"`）。
  - `_h_bp_reroute` → `result = await deps.research.aadvance_reroute(session)`，用 `result["event"]`（`converged` / `reroute_needed` / `exhausted`）映射转移，`stage_state_update=result["stage_state_update"]`（**已是浅合并后的整字典，直接传给 `transition(stage_state=)`，不要再取增量**）；`exhausted` 转 `repo_confirmation` 且把 `result["escalation"]` 塞进确认门线程 options。
  - 确认门写快照时，需重调研的仓打 `pending_research: True`（形状 `stage_state["confirmation"]["repos"] = [{repository_id, role_suggestion, pending_research}]`，兼容裸 list），下一次 `dispatch()` 只会为它们起容器。
  - 第七个端点 `POST /artifacts/<uuid:artifact_id>/blueprint-gate/upgrade-research/` 直调 `aupgrade_to_deep(session, repository_id)`：`False` → 404（仓不在候选/无 task）或 503（依赖不可用），二者在服务层不区分，端点可按需先自行校验仓存在性再落 404。
  - **必须提供** `services/process_runtime/blueprint_resume.py` 的 `aresume_blueprint_session(session)`，否则 fan-out barrier 到达后无人续驱（见 Known Stubs）。
- **113（repo_plan）**：`acollect_fitness` 的聚合视图即分仓方案的输入面；`PartialPlan.content` 的 `fitness`/`role_suggestion`/`responsibility`/`findings` 可直接投影进蓝图 `repo_associations` 与 `current_state_analysis`。
- **可调旋钮**：`MAX_REROUTE_ROUNDS = 2` / `_MAX_ATTEMPTS = 2` / `_RESEARCH_TIMEOUT = 30min` / `_RUNNER_HEARTBEAT_WINDOW_SECONDS = 120` 均为模块常量；若实战需运行时可调，按 112-02 的 `SettingKeys` 范式外置（模块常量留作缺省兜底）。
