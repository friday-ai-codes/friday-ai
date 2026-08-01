# 同步点 2 · 三道边界接缝与终态映射的闭合记录

**分支**：`milestone/v0.20.0-blueprint`　**基线**：`b85e99f4`（v0.19.0 已并入 main，main 已并入本分支）
**范围**：v0.20.0 里程碑审计 `§4.1` 的 **G1 / G3 / G4** 三道边界接缝 + **终态映射**（RELY-01）
**⛔ 不在本次范围**：翻四个入口开关默认值、三处前端触点升级、旧 `technical_plan` process 退役

> ⚠️ 本文件**不改** `REQUIREMENTS.md` 的 GATE-01 状态，也**不改**审计报告的 status。翻开关与触点升级
> 仍未做，三者由后续那一步一并对账。

---

## 0. 为什么这三处能跨六个相位不被发现

三道接缝**都不属于任何单个相位**，也不属于相位与相位之间 —— 它们在**蓝图链与其消费方之间**。
每个相位都在自己的边界内验证过：蓝图链验「会话确实停在 `waiting_clarification`、`BlueprintThread`
建好了」，入口侧验「拿到 pending 就挂起」。两边各自都对，中间那道**翻译**（旧链模型 ↔ 蓝图模型）
没有任何一条测试跨过去。

三处的失败形态还都是**静默**的：G1 报的是一个看起来很正常的 `failed`，G3 返回的是**结构合法**的
十二键响应，G4 是一个永远停在 `researching` 的进度。默认开关全 `technical_plan` ⇒ 生产零暴露 ⇒
也没有任何线上信号。

**对照组是 chat**：`plan_research_tools._map_terminal_blueprint` 是四个入口里唯一按 `blueprint_status`
分档、把 `pending_review` 计成「成功 + 等人审」的。本次三处新分档一律照它的形状做，
⛔ 不造第四套约定；并加了一条**表漂移守卫**（见 §5）把「同一份状态文案表」这件事锁死。

---

## 1. G1 · workflow 入口：每一次澄清都把会话判死

### 修复前（实测）

`server/workflows/nodes/ai/plan_research.py` `_maybe_suspend` 的 `waiting_clarification` 分支用
**旧链**判据 `ClarificationService().ahas_pending(session.id)`。蓝图链**从不写** `Clarification` 行
（全仓该模型的唯一写入点在 `delivery/services/clarification_service.py:110`），蓝图侧写的是
`BlueprintThread`。

因此判据**恒 False 且不抛异常**，链路是：

```
pending=None → 不发飞书卡 → 不建 WorkflowEventSubscription → suspend=None
            → 落 _map_terminal 非 DONE 分支
            → status="failed" / error_code="plan_session_failed" / next_handle="error"
```

**每一次规格门提问、每一次确认硬门，都把工作流判死。** 这比审计原先登记的「DONE→completed 一行」
严重一档：不只是终态映射错，是**所有中间挂起都映射成失败**。

变异实测（M1，见 §6）直接复现了审计原文：`execute` 返回 `'failed'`。

### 修复后

`plan_research.py`：

- `_maybe_suspend` 开头按 `process_type` **早返回**到 `_amaybe_suspend_blueprint`
  （`plan_research.py:~500`）。⛔ 不往旧链两个分支里插条件 —— 开关关闭时旧链逐字不变。
- `_amaybe_suspend_blueprint` 两档，与 chat 逐档对齐：
  - `waiting_clarification`（或终态分档 `force_clarification=True`）且有 **open + blocking**
    `BlueprintThread` ⇒ `NodeResult(status="waiting_event", kind="clarification")`，
    输出携 `artifact_id` / `current_status` / `pending_clarifications[]` /
    `suspension{clarification_id=thread_id, thread_id, question}`。
    ⭐ **不按 `kind` 过滤**：`ai_clarification` 与 `repo_confirmation` 两类都算，与
    `blueprint_resume` 的 pause 短路判据同源。只认一类会让确认门挂起的会话继续被判死。
  - `waiting_event` 且仍有在途调研 ⇒ 沿用旧链判据 `aall_research_tasks_terminal`
    （这条对蓝图**本来就有效**，蓝图确实建 `RepoResearchTask`）。⛔ 不另写一套。

**⛔ 刻意不发旧链澄清卡**：`build_clarification_card` 携带的是 `clarification_id`，回调侧
`PlanClarifyCallback` 按它查 `Clarification` 行 —— 对蓝图线程发那张卡，用户点了也答不进去。
蓝图线程的作答面是蓝图确认门 / 审查 REST 端点与 `answer_blueprint_clarification` MCP 工具。

**超时兜底**：挂起时建 `WorkflowEventSubscription(event_type="BlueprintGateCallback",
timeout_action="fail")`。它**不是唤醒通路**，只保证「等不到人回答」不会变成无声的永久挂起
（`check_timeouts` 是按 `timeout_at` + `timeout_action` 通配扫描的，不认事件类型）。
取独立事件类型 ⇒ 既有 `PlanClarifyCallback` 消费者必不命中。
新增可配置项 `BLUEPRINT_REVIEW_TIMEOUT_HOURS`（默认 72，`settings.py:399`）；澄清那一档
沿用既有 `CLARIFICATION_TIMEOUT_HOURS`（24）。

**唤醒通路**：`services/process_runtime/blueprint_resume.py` 新增
`_aresume_workflow_node_if_any(session)`，挂在 `aresume_after_gate_action` 这个**全部作答链的
共同出口**上（与既有 `_afeedback_chat_barrier_if_any` 并列，形状同源）。按
`output_data__session_id` 反查仍在 `waiting_event` 的 `NodeExecution` → 打 `_resume_from_callback`
标记 → `WorkflowEngine._continue_after_node` 重入。节点重入后自己重读会话与蓝图状态，**幂等**：
状态没变就再挂起一次。整段吞异常，⛔ 绝不反噬已持久化的门动作。

> **判断依据**：不接这一挂就只是把「判死」换成「无声挂死」，不算修好。做法复用容器回调
> `_schedule_workflow_resume` 的同一范式与 `tasks/agent_tasks.py` 既有的
> `output_data__session_id` 反查，⛔ 不新造调度。

### file:line 证据

| 位置 | 内容 |
|---|---|
| `server/workflows/nodes/ai/plan_research.py:499-501` | `is_blueprint_session` 早返回分流 |
| `server/workflows/nodes/ai/plan_research.py:~547-620` | `_amaybe_suspend_blueprint` 两档 |
| `server/workflows/nodes/ai/plan_research.py:~622-665` | `_asubscribe_blueprint_timeout` 超时兜底 |
| `server/services/process_runtime/blueprint_resume.py:200-247` | `_aresume_workflow_node_if_any` |
| `server/services/process_runtime/blueprint_resume.py:~285` | 挂进 `aresume_after_gate_action` |
| `server/friday/settings.py:399-404` | `BLUEPRINT_REVIEW_TIMEOUT_HOURS` |

---

## 2. 终态映射 · `pending_review` = 等人审，⛔ 不是完成

### 修复前（实测）

`_map_terminal` 把 `ConvergenceSessionStatus.DONE` **无条件**映射成 `completed` + `next_handle="default"`，
并把 `plan` 载荷交给下游 `human_approval(plan_feishu)` / `ai_coding`。而蓝图链的 `DONE` 语义是
**「等人审」**（`review_passed → STAGE_DONE` 把 `blueprint_status` 置成 `pending_review`）。

⇒ 一份**未经人审**的蓝图会被直接交给编码代理去建分支写代码。正面违反 RELY-01（T-116-18）。
变异实测（M2 / M3′）复现：`assert 'completed' == 'waiting_event'`。

### 修复后

分档在 `execute` 里按 `process_type` 分流到 `_amap_terminal_blueprint`
（⛔ **不插进 `_map_terminal`**，理由见下方判断记录）：

| 蓝图状态 | NodeResult |
|---|---|
| `needs_clarification` | `waiting_event`（复用 §1 的挂起档，⛔ 不复制第二份线程查询） |
| **`pending_review`** | ⭐ **`waiting_event` / `kind="human_review"`**（⛔ 不产出 `plan` 载荷） |
| `confirmed` / `implementing` / `implemented` | `completed` + **派生后**的 execution_plan |
| `failed`（或会话 FAILED） | `failed` / `error_code="blueprint_session_failed"` |
| 其余中间态 | `failed` / `error_code="blueprint_unreviewed"` |

**调用方现在看到什么（`pending_review`）**：节点状态 `waiting_event` ⇒ 调度器走
`amark_waiting_event` 并**直接返回，不遍历任何出边**（`scheduler.py:1179-1191`）⇒ 工作流挂起，
下游 `ai_coding` 拿不到任何东西。输出体为
`{session_id, kind:"human_review", artifact_id, current_status:"pending_review",
suspension:{type:"await_human_review", artifact_id, message:"技术蓝图已产出，等待人工终审。"}}`。
人审 approve / reject 经 `aresume_after_gate_action` → §1 的重入 hook → 节点重跑：
此时状态已是 `confirmed` ⇒ 走 `completed` 那一档，闭环。

> ⭐ 真正的闸不是 `next_handle`（`waiting_event` 下它无意义），而是**不产出 `plan` 载荷** ——
> 下游读的就是它。测试断言的正是 `"plan" not in result.output`。

**`completed` 那一档喂下游的是派生后的 technical_plan 形状**：下游读 `plan.execution_plan`，
而 blueprint/v1 **没有**这个顶层必填键（它是「确认后确定性派生」的可选段，
`blueprint_schema.py:741`）。直接内联 blueprint/v1 就是在工作流侧复刻 G3 的静默降级。
故经 `blueprint_execution.derive_execution_plan` 派生后内联，原始 content 以 `blueprint_content`
键并列保留（不丢信息）。

---

## 3. G4 · feature_list 入口：永久 `researching` + 空问题列表

### 修复前（实测）

`server/initiatives/services/feature_solution_service.py` `_abuild_state`（原 `:485-512`）是旧链形态：
`FAILED→failed`、`DONE→completed`+旧形态 attach、其余一律 `STATUS_RESEARCHING`，
待答问题取自 `ClarificationQuestion`（旧链**子题**模型）。

⇒ 阻塞在 `BlueprintThread` 上的蓝图会话在该面**永久显示 `researching`、问题列表恒空**。
调用方看不到要答什么，也就无从解阻。变异实测（M4）：`assert 'researching' == 'awaiting_confirmation'`。

附带的第二个洞：`confirm` 查不到 `Clarification` 待答轮 ⇒ 落进「没有待答轮 ⇒ 续驱后原样返回」
分支 ⇒ 调用方拿到一个**状态没变的 200** 并读成「答复已收下」，实际一个字都没写进去
（Phase 115 MJ-04 的同一形状）。

### 修复后

`_abuild_state` 按 `process_type` 早返回到 `_aapply_blueprint_state`：

| 情形 | 对外状态 |
|---|---|
| 有 open+blocking 线程 | `awaiting_confirmation` + 题面清单 |
| `failed` / 会话 FAILED | `failed` |
| `pending_review` / `confirmed` / 实施中 / 完成 | `completed`（+ `current_status` 如实标明） |
| 其余中间态 | `researching` |

- **对外四态闭集一字不扩**（`awaiting_confirmation` / `researching` / `completed` / `failed`）——
  调用方（MCP 工具、对话 agent tool、前端）都按这四个值分支，加第五个值等于让所有调用方同时回退。
  蓝图特有信息走**纯追加**的两个键：`current_status`（⛔ 键名不叫 `blueprint_status`，那会命中
  INV-6 的字段级旁路守卫）与 `artifact_id`。两键在旧链恒为空串 ⇒ 既有调用方零破坏。
- 问题项键集与旧链对齐：`question_id` 位放 `thread_id`，另以显式 `thread_id` 键并列。
- markdown 走 `render_blueprint_markdown`（v0 的 `render_feature_solution_markdown` 对 blueprint/v1
  只会渲出一篇结构合法而内容为空的文档）。
- `confirm` 对蓝图会话**如实拒绝**：抛 `FeatureSolutionError("blueprint_thread_answer_required")`，
  文案指向蓝图澄清作答接口。⛔ 不返回一个「状态没变的 200」。

> **判断记录**：`pending_review` 在这一面计入「已产出 ⇒ `completed`」，与工作流入口**刻意不同**。
> 判据是下游不同：工作流的 `completed` 会把载荷交给编码代理（故必须挂起），feature_list 这一面
> 没有下游编码代理，方案**确实已产出**、调用方读得到，「还没过人审」由 `current_status` 如实标明。
> 这与 chat 的口径一致（chat 也把 `pending_review` 计成成功 + 等人审）。

### file:line 证据

| 位置 | 内容 |
|---|---|
| `server/initiatives/services/feature_solution_service.py:~500-505` | 早返回分流 |
| `server/initiatives/services/feature_solution_service.py:~594-655` | `_aapply_blueprint_state` 分档 |
| `server/initiatives/services/feature_solution_service.py:~657-675` | `_aattach_blueprint_plan` |
| `server/initiatives/services/feature_solution_service.py:~186-200` | `confirm` 的蓝图拒绝 |
| `server/initiatives/services/feature_solution_service.py:52-66` | 两个纯追加键 + 状态集合常量 |

---

## 4. G3 · MCP 入口：主载荷结构合法而语义为空

### 修复前（实测）

`server/mcp_tools/technical_plan_service.py:440` 的 `_map_execution_plan_to_repository_tasks` 读
`content["execution_plan"]`。blueprint/v1 的 required 键表（`blueprint_schema.py:123-134`）**不含**
这个顶层键 —— 它是「确认后确定性派生」的**可选**段（`:741`）。

⇒ `repository_tasks` 恒 `[]`。响应的十二键**结构合法、语义为空**：调用方读不出任何一个仓库任务，
也拿不到任何错误信号。**静默降级**。标题与摘要同理（在 `meta` 下而非顶层）。
`_load_canonical` 的 markdown 用的也是 v0 渲染器 —— 而那份 markdown 正是写进飞书文档的那一份。

变异实测（M5）：`assert 0 == 1`（`len([])`）。（M6）：markdown 为 `''`。

> GATE-01 的**异步澄清那一半是真接通的**（`blueprint_artifact_id` / `blueprint_current_status` /
> `pending_clarifications` 三键装饰 + 两个新工具）；空的一直是主载荷。

### 修复后

- 新增纯投影 `_project_canonical_for_legacy_mapping(content)`：blueprint/v1 经**既有权威派生器**
  `blueprint_execution.derive_execution_plan`（纯函数、同输入逐字节一致、产物过
  `validate_technical_plan`）派生出 `execution_plan`，并从 `meta` 捞回 `title` / `summary`
  （Block[] → 纯文本）。⛔ 本模块不写第二份派生逻辑。
  **非 blueprint/v1 恒等返回同一个对象** ⇒ 旧链映射链逐字不变（有 `is` 断言背书）。
- 既有 `_map_execution_plan_to_repository_tasks` **一行未改**，改的是喂给它的东西。
- `canonical_content` 仍落**原始** blueprint content（不丢信息、可追踪）；`_map_plan_payload`
  新增 `summary` 纯追加形参，缺省 `None` 时逐字回退读 `content["summary"]`。
- `_load_canonical` 对蓝图会话换用 `render_blueprint_markdown`（水印由渲染器按状态无条件加）。
- **补埋点**：`_log_blueprint_payload_projection` —— 派生结果为空而蓝图确实有实现项时落
  `warning`（那是真异常：`repo_associations` 与 `items` 的 `repository_id` 对不上，派生器整批丢弃），
  正常派生落 `sampling` 级 info，旧链恒等穿过时**不打**（不给旧链加噪声）。
  ⭐ **G3 能潜伏六个相位，正因为空载荷不打任何信号。**

### file:line 证据

| 位置 | 内容 |
|---|---|
| `server/mcp_tools/technical_plan_service.py:~109-145` | `_project_canonical_for_legacy_mapping` |
| `server/mcp_tools/technical_plan_service.py:~147-178` | `_log_blueprint_payload_projection` |
| `server/mcp_tools/technical_plan_service.py:~180-200` | `_blocks_to_plain_text` |
| `server/mcp_tools/technical_plan_service.py:~497-505` | 投影接入主载荷映射 |
| `server/mcp_tools/orchestration_delegate.py:63-110` | `_load_canonical` 换渲染器 + `_arender_blueprint` |

**未改动、并说明理由**：`technical_plan_service` 里既有的「有 `blueprint_extras` ⇒ 一律回
`status="partial"`」（116-06 定的）保留不动 —— 它与本次终态映射的原则同向（绝不在人审前把蓝图
报成「已终结」），且改它会破坏 GATE-01 已交付的调用方契约。

---

## 5. 共享读侧与跨接缝纪律

新增 `server/services/process_runtime/blueprint_observation.py`（纯读侧，无写、无状态转移，
模型 import 全部函数内 lazy）：

- `is_blueprint_session(session)` —— 三处分流的**唯一**判据。⛔ 绝不按 `entrypoint` 判：
  MCP 入口记的 `entrypoint` 实测就是 `"workflow"`（既有约定）。
- `ablueprint_observation(session, *, with_threads=True)` → `BlueprintObservation(artifact_id,
  current_status, threads)`。
- `aload_blocking_threads(artifact_id)` —— open + blocking，**不按 `kind` 过滤**，显式
  `order_by("created_at")`（`BlueprintThread.Meta` 无 `ordering`，不排序会让「首题」漂移）。
  题面逐条过 `redact_secrets_in_text`。**异常不吞** —— 读失败必须让调用方看到失败，
  ⛔ 绝不包成「空清单」（调用方会读成「没有待澄清」并据此推进）。
- `BLUEPRINT_STATUS_MESSAGES` —— 状态文案表。
- `render_observed_blueprint(content, current_status)` —— 三个消费方共用的渲染调用点。
  ⚠️ 收成一处不只是去重：INV-6 字段级守卫的「读状态 → 传进纯渲染器」豁免是**逐行**匹配的，
  散在三处随时可能被 formatter 折行判成旁路写。

**漂移守卫**：`test_status_message_table_does_not_drift_from_the_chat_reference` 断言
`plan_research_tools._BLUEPRINT_STATUS_MESSAGES == blueprint_observation.BLUEPRINT_STATUS_MESSAGES`。

> **判断记录（为什么不直接让 chat import 共享表）**：`agents/tools/plan_research_tools.py` 刻意把
> 所有 `delivery` / `process_runtime` import 放在函数内以规避 chat→delivery 循环；给它加一个
> 模块级 import 有循环风险，而 chat 那条路径**当前是对的、有完整测试背书**。选择「两份定义 +
> 一条相等守卫」而不是冒险重构一个正在工作的入口。守卫使它不可能漂移。

**枚举对齐守卫**：`test_blueprint_status_literals_match_the_enum` 断言三处分档字面量 ==
`BlueprintStatus` 枚举，并显式锁死 `PENDING_REVIEW ∉ _BLUEPRINT_REVIEWED_STATUSES`（工作流的放行闸）
且 `PENDING_REVIEW ∈ _BLUEPRINT_PRODUCED_STATUSES`（feature_list 的已产出集）—— 两面口径不同这件事
本身被测试固定下来，不会被当成 bug「顺手统一」掉。

---

## 6. 变异证据（每道接缝：回退 → 变红 → 恢复）

测试文件 `server/tests/services/process_runtime/test_blueprint_consumer_seams.py`（30 条）
在未变异时**全绿**。逐条回退后：

| # | 回退内容 | 红的用例 | 关键断言输出 |
|---|---|---|---|
| **M1** | 删掉 `_maybe_suspend` 的蓝图早返回（G1） | 5 | `execute` 返回 `'failed'`（≠`'waiting_event'`）；`_maybe_suspend` 返回 `None` |
| **M2** | 删掉 `execute` 里的终态分流 | 2 | `assert 'completed' == 'waiting_event'` |
| **M3** | 把 `pending_review` 塞进 `_BLUEPRINT_REVIEWED_STATUSES` | 2 | 两条**守卫**红（枚举对齐 + 源码防线）；行为面未翻 —— 因为显式分支在集合判定**之前**，属纵深防御 |
| **M3′** | 删掉 `pending_review → waiting_event` 那一档（外科变异） | 1 | `assert 'completed' == 'waiting_event'`（RELY-01 闸的**孤立**证明） |
| **M4** | 删掉 `_abuild_state` 的蓝图早返回（G4） | 2 | `assert 'researching' == 'awaiting_confirmation'` |
| **M5** | 把 `_project_canonical_for_legacy_mapping` 改成恒等（G3 载荷） | 2 | `assert 0 == 1`（`len([])`）—— 即审计说的「恒为 `[]`」 |
| **M6** | 删掉 `_load_canonical` 的蓝图渲染器分支（G3 markdown） | 1 | `assert '登录超时修复跨仓蓝图' in ''` |

每次变异后均 `git checkout -- <file>` 恢复，恢复后复跑全绿。

M3 的结果值得单记：它证明「`pending_review` 不在放行集合」这条是**纵深**而非唯一防线（显式分支
先命中），两条源码/枚举守卫补上了这一层的覆盖。M3′ 才是行为闸的孤立证明。

---

## 7. 回归与验收

| 项 | 结果 |
|---|---|
| `uv run pytest tests/ -q` | **9780 passed / 61 skipped / 2 failed**（基线 9751 passed / 1 failed） |
| 失败 ①：`tests/mcp_tools/test_mcp_package_alignment.py` | **已知基线失败**，`mcp` npm 包（独立仓、submodule）缺本里程碑新增的四个工具。⛔ 不在本次范围 |
| 失败 ②：`tests/test_migrate_coding_sessions_to_plans.py::test_command_basic_creates_plans` | **顺序相关的既有 flake**：单独跑 8 条全过；与本次改动无交集（coding sessions 迁移，不碰蓝图）。同一份代码的上一轮全量跑它是绿的 |
| `uv run python manage.py makemigrations --check --dry-run` | `No changes detected` ⇒ **零新增迁移** |
| `ruff check` / `ruff format --check`（全部改动文件） | 通过 |
| INV-6 守卫（`test_blueprint_inv6_guard` / `test_clarification_service`） | 通过（过程中被绊过两次，见下） |
| ⭐ `DEFAULT_ENTRY_SWITCH` 四键 | **未改动**：`git diff b85e99f4 -- blueprint_entry_switch.py` 为空；另有 `test_entry_switch_defaults_are_untouched` 断言四值全 `technical_plan` |
| 前端 | **零改动**（三道接缝全在后端读侧与映射层，无契约外形破坏需要前端配合）；`pnpm exec vitest run` 作为基线核对 |

**过程中被 INV-6 源码守卫绊住两次，都是我的问题、都已改正**（记在这里因为它们是这套守卫**有效**的证据）：

1. 文档字符串里写了 `Clarification.objects.create` 字面量 ⇒ 命中「旁路写 Clarification」扫描。
   改为不含该字面量的表述。
2. `render_blueprint_markdown(..., blueprint_status=...)` 被 formatter 折成两行 ⇒ 命中字段级
   旁路写扫描（豁免是逐行匹配的）。改为收口到 `render_observed_blueprint` 一个调用点。

---

## 8. 判断记录（Judgment calls）

1. **终态分流放在 `execute` 而不是 `_map_terminal` 开头。** 先做的是加 `context` 形参 + 函数内早返回，
   结果打断了 `tests/knowledge/test_triggers.py` 里按**两参签名**做的 `_map_terminal` 替身。
   改成在 `execute` 里分流后，`_map_terminal` **逐字未改**（签名也未动）—— 对「旧链零回归」这条硬约束
   反而更强。

2. **工作流的「其余中间态」如实报失败，chat 那档不报。** 会话到终态而蓝图仍停在 `researching` /
   `drafting` 是可诊断异常。chat 只把结果讲给对话里的人看，报失败会让用户以为方案没了；工作流的
   `completed` 会把载荷**交给编码代理**，此时既不能放行（未经人审）也不能装作还在跑（没有人会再推进
   它）⇒ 走 `error` 出边、`error_code="blueprint_unreviewed"`，产物仍在库里可人工续推。
   **判据是下游不同，不是口径漂移**，且该差异被 §5 的枚举守卫固定。

3. **`pending_review` 在 feature_list 计 `completed`、在 workflow 计挂起。** 同上，判据是下游不同。
   两面都由测试正反锁死。

4. **给工作流挂起补了唤醒通路，超出「三道接缝」的字面范围。** 不补的话 G1 的修复只是把「判死」换成
   「无声挂死」。做法是复用既有范式（`aresume_after_gate_action` 的共同出口 hook +
   `output_data__session_id` 反查 + `_continue_after_node`），⛔ 未新造调度、未加模型字段。

5. **`confirm` 对蓝图会话改成抛错，而不是接一条蓝图作答路径。** 蓝图线程已有作答面（MCP 工具 +
   两组 REST 端点），再接一条等于第二份实现；而 MCP 共享 handler factory 是冻结面。
   如实拒绝比静默 200 正确，且不新增重复入口。

6. **`_BLUEPRINT_STATUS_MESSAGES` 保留两份定义 + 相等守卫**，理由见 §5。

7. **`ConvergenceSessionEvent` 未新增任何类型**（约束 2）：三处修复全是读侧与映射，
   没有需要新事件才能表达的语义。

---

## 9. 提交

| commit | 内容 |
|---|---|
| `c5985bdb` | `refactor(blueprint): 抽出蓝图观测共享读侧 helper` |
| `aa63bcf0` | `fix(blueprint): G1 workflow 入口按蓝图判据挂起，终态 pending_review 改人审 HITL` |
| `dd10cbcb` | `fix(blueprint): G4 feature_list 入口待答问题改取 BlueprintThread` |
| `2f002b90` | `fix(blueprint): G3 MCP 入口主载荷从蓝图确定性派生 execution_plan` |
| `1f9048a6` | `test(blueprint): 三道边界接缝的跨边界守卫` |

---

## 10. 仍未做（同步点 2 的剩余部分）

1. **翻四个入口开关默认值** —— 现在才具备前提条件：三道接缝正确了，翻 workflow / feature_list 后的
   **第一次澄清**不再撞 G1/G4，翻 mcp 后主载荷不再恒空，翻任一入口后到终态也不会把未审蓝图送进
   `ai_coding`。
2. **三处前端触点升级**（`TechPlanCard` / `NodeDataTab` / `ArtifactTimeline`）。
3. **旧 `technical_plan` process 退役收口。**
4. **对账**：`REQUIREMENTS.md` GATE-01 状态、审计 `§4.1` 三张判定表与 `tech_debt.116-entry`、
   `STATE.md` Pending Todo 第 1 条 —— 本次**刻意未动**，由后续那一步一并改，避免出现「接缝已修但
   开关未翻」的中间态在三份文档里各写一个版本。

---
---

# 同步点 2 收尾（第二步）

**基线**：`25b66d85`（第一步的五个 commit 已在树上）　**分支**：`milestone/v0.20.0-blueprint`
**范围**：§10 里列的**剩余三件** —— ① 三处前端触点升级 ② 翻四个入口开关默认值
③ 旧 `technical_plan` process 退役收口。**GATE-01 就此闭合。**

> 三件必须同批做，理由在第一步 §10 已登记：翻默认之前，触点会把蓝图渲染成空壳、旧链的
> 退役状态也无从谈起；翻默认之后再补触点，则中间那段时间生产界面是坏的。

---

## 11. Part 1 · 三处前端触点识别 blueprint/v1

### 11.1 为什么这三处此前一定是错的

三个组件都早于 Phase 115，都只懂 v0 `technical_plan` 形态。而蓝图**刻意不新增
`artifact_type`**（DESIGN §3.1：按 `content.schema_version` 判别）⇒ 在这三处的数据面上，
蓝图与 v0 **长得一模一样**：

| 触点 | 蓝图与 v0 共用什么 | 此前的实际呈现 |
|---|---|---|
| `ArtifactTimeline` | 同 `artifact_type="technical_plan"`、同标题形态 | 两条同名条目并列，用户分不出哪条是带批注与人审的蓝图（115-06 §9 登记的 P-17 重叠） |
| `NodeDataTab` | 同 `node_type="ai_plan_research"`，输出同有 `session_id` / `plan` / `plan_markdown` | 蓝图挂在 `pending_review` 时抽屉画面与 v0「跑完了」几乎一样，看不出是**在等人终审** |
| `TechPlanCard` | 同一个 `CodingPlan` 投影 | `map_merged_plan_to_coding_plan` 读 v0 的 `execution_plan[]`、走 v0 渲染器，而 blueprint/v1 **没有那个顶层键** ⇒ `tech_plan` 是一份结构合法而内容为空的壳、`affected_files` 恒 `[]` ⇒ 卡片渲染出「（暂无方案正文）」 |

⭐ 第三条与审计 §4.1 的 **G3 是同一形状**：结构合法、语义为空、零错误信号。

### 11.2 判别与文案收在一处

新增 `web/src/config/blueprintArtifact.ts`（纯配置，无组件依赖）：

| 位置 | 内容 |
|---|---|
| `web/src/config/blueprintArtifact.ts:25` | `BLUEPRINT_SCHEMA_VERSION = 'blueprint/v1'` |
| `:34` | `isBlueprintSchemaVersion` —— **允许清单**：只有严格等于才为真，`undefined` / `''` / 将来的 `blueprint/v2` 一律按 v0 |
| `:44` | `BLUEPRINT_STATUS_TEXT` —— 12 档中文（11 态 + `''` 旧版方案） |
| `:63` | `blueprintStatusText`（`''` 命中「旧版方案」而非未知兜底） |
| `:73` | `BLUEPRINT_ATTENTION_STATUSES`（`needs_clarification` / `pending_review` ⇒ 徽标用琥珀） |
| `:83` | `blueprintViewerPath` —— 三处共用，查看器路由改名只改一处 |

> **判断记录（为什么不复用 `~/config/blueprintStatus.ts`）**：那张表存的是 **i18n key**，
> 服务 115 相位的新页面；三处触点**都不接 vue-i18n**（`ArtifactTimeline` docstring 逐字
> 写了「文案内联中文，避免改动整份 i18n 资源」，`TechPlanCard` 家族有 `COPY` 常量表的
> 既定惯例）。强行合并等于逼一边改掉自己的既定约定。取**两份定义 + 一条漂移守卫**，
> 形状与第一步 §5 给 `_BLUEPRINT_STATUS_MESSAGES` 用的同一招 ——
> `config/__tests__/blueprintArtifact.spec.ts` 逐键断言它与 `zh-CN.json` 的
> `knowledge.blueprints.status.*` **逐字相等**，且键集与 `BLUEPRINT_STATUS_CONFIG` 一致。

### 11.3 三处触点的落点

| 触点 | 判别 | 呈现 |
|---|---|---|
| `ArtifactTimeline.vue:143` `isBlueprint()` | 响应体 `schema_version` | 切换 tab 上一枚 11 态徽标（`:222`）；正文区一条告示 + 深链（`:241` / `:258`） |
| `NodeDataTab.vue:90` `isBlueprintOutput` | `output_data.schema_version`，另**兜底**读 `output_data.blueprint_content.schema_version` | 输出区上方告示（`:346`）+ 11 态徽标（`:354`）+ **挂起语义**一句话（`:357`）+ 深链（`:364`） |
| `TechPlanCard.vue:347` `isBlueprint` | 新 prop `schemaVersion` | 头部两枚徽标（形态 + 状态，`:653`）；正文区**换成**蓝图告示 + 深链（`:724` / `:741`）；折叠态摘要也换（`:1028`） |

⭐ `NodeDataTab` 的**兜底那一级不可省**：本次追加顶层 `schema_version` 之前，completed 分支
已经把原始 blueprint content 并列保留在 `blueprint_content` 里 ⇒ 少了这一级，改动前跑过的
蓝图执行记录在抽屉里仍会被当 v0 渲染。

⭐ `TechPlanCard` 的蓝图档**必须排在「正文为空 ⇒ 占位」之前**：否则那份空壳落到
「（暂无方案正文）」，把「形态不同」讲成「方案没了」—— 正是本次要消除的静默降级。

### 11.4 供数面三处**纯追加**（零迁移）

| 位置 | 追加内容 |
|---|---|
| `server/delivery/api/artifact_serializers.py:67/98/111` | `ArtifactListSerializer` 加 `schema_version` / `current_status` 两个 `SerializerMethodField`（详情序列化器派生自它，⛔ 不各写一份）。既有八键一字未动 |
| `server/chat/serializers.py:736-738` + `server/chat/views.py:2762/2916` | 投影响应加 `schema_version` / `blueprint_artifact_id` / `current_status`；读侧是新的 `_aload_blueprint_marks`（纯读、异常吞成空三键、⛔ 绝不把一次已成功的投影变成 500） |
| `server/workflows/nodes/ai/plan_research.py:96` + `:630/655/1007/1023/1059/1080` | 蓝图**五个分档**的输出加 `schema_version`；常量 `_BLUEPRINT_SCHEMA_VERSION` 与 `blueprint_schema.BLUEPRINT_SCHEMA_VERSION` 有对齐守卫 |

⛔ **`map_merged_plan_to_coding_plan` 一行未改**（判断记录）：它是旧链投影的唯一实现，改它
等于在 chat 侧再造一条派生链（工作流侧已有 `blueprint_execution.derive_execution_plan`
这一份权威派生）。本次只补**判别信息**，让前端如实呈现并把用户导向查看器。⚠️ 这意味着
「从蓝图版本投影出来的 CodingPlan 内容仍是空的」这一条**依然成立**，只是不再静默 ——
测试 `test_projection_marks_a_blueprint_source_version` 显式断言 `affected_files == []`
并把理由写在用例里。真要让它有内容，得在 chat 侧接派生器，那是独立工作项。

⚠️ **INV-6**：两处响应键名都用 `current_status` 而**不是**模型字段名 —— 字段级守卫扫全
`server/` 的 `['"]<那个字段名>['"]\s*:` 形态。这是 114-05 立的既有解法，全仓统一。

### 11.5 v0 逐像素不变

三处的全部新增标记都在判别之下；判别是允许清单 ⇒ v0（`schema_version` 为 `''` / 缺键）
一律走原路径。证据：

- `ArtifactTimeline.spec.ts` 既有 6 条 v0 用例**一字未改即通过**；
- 新增 v0 反向用例逐条断言三个蓝图 testid **不存在**；
- `TechPlanCard.spec.ts` 既有 63 条全绿；新增用例断言 v0 空正文仍落「（暂无方案正文）」
  （蓝图那一档不得抢它）；
- 后端 `test_v0_branches_never_carry_the_schema_version` 用源码扫描锁死 v0 的
  `_map_terminal` / `_maybe_suspend` 两个函数体内**零** `schema_version` 写入。

---

## 12. Part 2 · 四个入口开关默认值翻到 `technical_blueprint`

### 12.1 翻的是哪四行

`server/services/process_runtime/blueprint_entry_switch.py:72-77`：四键从
`PROCESS_TECHNICAL_PLAN` 翻成 `PROCESS_TECHNICAL_BLUEPRINT`。

**开关机制一字未动**：`aresolve_entry_process_type` 的签名、`entry_key` 字面量常量纪律与
它的 `ast` 扫描守卫、per-entry `SystemSetting` override —— 全部原样。运维把某个键显式置成
`"technical_plan"` 仍然精确、单入口、免发布地回退。

### 12.2 ⭐ fail-soft 落点从「硬写旧链」改成「该入口的声明默认值」

三条 fail-soft 分支（读设置整段异常 / 外层非 dict / 内层值域外）此前都 `return
PROCESS_TECHNICAL_PLAN`。默认值本来就是它的时候，这两种写法读起来一样；**翻默认之后就不
一样了**。

改为 `_default_for(entry)`（`:80`）。**这不是洁癖，是必需的** —— 变异实测（M-D，见 §14）
暴露出一个远比「抖动回落」严重的形态：

> `aget_json_setting` **原样回落库的那个 dict、不与默认值做合并**
> （`system/settings_service.py:139-153`）。运维只写要 override 的那一两个键（**正常做法**）
> 时，其余入口在解析里读到的是「没有这个键」⇒ 落进内层值域外那一档。若那一档硬回旧链，
> 一条 `{"mcp": "technical_plan"}` 就把 **workflow / chat / feature_list 三个入口一起拖回
> 旧链** —— per-entry 独立性当场失效，而且没有任何信号。

顺带修掉同一处的观测噪声：**「该键缺席」≠「配置非法」**（`:169`）。缺席是绝大多数请求的
正常态，此前会逐次落一条 `blueprint_entry_switch_invalid_value` **warning**；现在缺席静默
取默认，真写了值域外的值才落事件。两向由
`test_an_absent_key_is_silent_not_an_invalid_value_event` /
`test_an_illegal_value_does_emit_the_invalid_value_event` **并列**锁死。

**未知 entry 仍回旧链**（唯一保留旧链的分支，`_default_for` 的 `.get` 兜底）：它不是入口、
没有声明默认值，且**不构成「某个入口的默认」**，与退役这条不冲突；生产不可达（`ast` 扫描
强制字面量常量），走到那里意味着调用方有 bug。

### 12.3 四个入口 × 两向的端到端证明

`tests/services/process_runtime/test_entry_dispatch_wiring.py` 重写：每个入口的蓝图向
**参数化成两态** —— `None`（**零配置 = 新默认**）与显式 `technical_blueprint`：

| 入口 | 零配置驱动蓝图链 | 显式回滚仍走旧链 |
|---|---|---|
| workflow | `test_workflow_entry_drives_the_blueprint_chain[None]` | `test_workflow_entry_explicit_rollback_is_byte_identical` |
| chat | `test_chat_entry_drives_the_blueprint_chain[None]` | `test_chat_entry_explicit_rollback_is_byte_identical` |
| mcp | `test_mcp_context_resolves_to_project_not_space[None]` | `test_mcp_entry_explicit_rollback_is_byte_identical` |
| feature_list | `test_feature_list_entry_drives_the_blueprint_chain[None]` | `test_feature_list_entry_explicit_rollback_is_byte_identical` |

零配置那一态断言的是「建出 `process_type == "technical_blueprint"` 的会话且
`decomposition.project_id` 非空」——**一条真实需求确实驱动蓝图链**，⛔ 不靠显式设置蒙混。

开关单测另补：单入口回滚 / 双入口回滚（同一份配置里两向并列）/ 显式蓝图 == 默认。

### 12.4 ⭐ 翻默认的实际爆炸半径：18 个既有用例

全量跑出 **18 个新失败**（外加已知的 `test_mcp_package_alignment`），分布在 6 个模块。
逐条看过：**全部是「冲着旧链行为写的用例，此前靠『默认恰好是旧链』隐式到达那条链」**，
不是回归。

处置：新增 `tests/conftest.py::legacy_plan_entry_switch` fixture，把「我要测的是旧链」
**说出来**。这些用例因此测的是**显式 override 路径** —— 旧链退役后唯一合法的到达方式，
与 §13 的口径一致。

| 模块 | 条数 | 挂法 |
|---|---|---|
| `tests/workflows/test_plan_research_node.py` | 6 | 模块级 `pytestmark` |
| `tests/mcp_tools/test_create_feishu_technical_plan_delegate.py` | 4 | ⭐ **逐条挂**（见下） |
| `tests/mcp_tools/test_feature_tech_plan_tools.py` | 4 | 模块级 |
| `tests/agents/test_start_plan_research_tool.py` | 2 | 模块级 |
| `tests/services/test_plan_research_e2e.py` | 1 | 模块级 |
| `tests/services/test_process_runtime_extra_evidence.py` | 1 | 模块级 |

> **判断记录（为什么 MCP delegate 那个模块要逐条挂）**：它**两类用例并存** —— 旧链那几条，
> 与冲着蓝图链写的那一组（`_switch_mcp_to_blueprint()`，用真 `SystemSetting`）。fixture
> patch 的是解析函数本身，模块级挂会把蓝图那一组的真配置**一起吞掉**。第一次就是这么挂的，
> `test_blueprint_intake_rejection_surfaces_the_neutral_detail_and_is_not_retryable` 当场转红
> —— 那条红是对的，已改成逐条挂。
>
> fixture 取 monkeypatch 而不是写真 `SystemSetting`：四个入口对开关模块的 import 全在函数内
> （lazy）⇒ patch 模块属性必然生效，且不受 60s 设置缓存与事务边界干扰。**真配置那条路径**
> 由 `test_entry_dispatch_wiring.py` 用真 `SystemSetting` 覆盖（四入口 × 两向），⛔ 不重复。

---

## 13. Part 3 · 旧 `technical_plan` process 退役收口

### 13.1 退役在本仓的定义（三条缺一不可）

1. **不再是任何入口的默认** —— `DEFAULT_ENTRY_SWITCH` 四键无它（Part 2 已成立）；
2. **注册仍在，且写明了为什么还在** —— 在途会话续驱与显式回滚 override 都要它，注销即崩；
3. **状态是程序可查的**，不是只写在注释里。

⛔ **退役 ≠ 注销 ≠ 删除**：六个 technical_plan 冻结文件（`decompose_segments` /
`research_adapter` / `architect_merge_adapter` / `merged_plan` / `clarify_adapter` /
`render`）**一行不改**。

### 13.2 落点

| 位置 | 内容 |
|---|---|
| `server/services/process_runtime/builtin_processes.py:1241` | `TECHNICAL_PLAN_RETIREMENT` 五键：`retired` / `retired_in="v0.20.0"` / `successor="technical_blueprint"` / `retained_reason` / `residual_traffic_event` |
| `:1257` | 经既有 `ProcessDefinition.config` 字段挂进注册（**零迁移**）⇒ `get_process_definition("technical_plan").config` 即可读 |
| `server/services/process_runtime/entrypoint.py:39` | `_technical_plan_retired()` —— 从注册表**读**那一份标记，⛔ 不复制第二份 |
| `:147` | `technical_plan_entry_used` 事件补 `process_retired` |

`retained_reason` 把「为什么还留着注册」写进**数据**，而不是注释 —— 避免下一个人把它当残留
顺手清理掉，那会同时打断在途会话与回滚通路。

`process_retired` 让残余流量的读数**自带语义**：翻默认之后落到旧链的每一次都是**显式
override 或在途会话续驱**，聚合的人不必回去翻代码才知道这个读数该怎么读。

### 13.3 守卫

`tests/services/process_runtime/test_technical_plan_retirement.py`（9 条）：

- 注册面：五键齐全 + **继任者没有这个标记**（反面对照，证明它不是人人都有的装饰）；
- 行为面：`test_no_entry_defaults_to_the_retired_process` 把「退役」与「翻默认」**钉在一起**
  —— 只标不翻 = 挂个牌子说退役而流量照旧；只翻不标 = 下一个人看不出这条链的处境；
- `test_residual_traffic_is_an_explicit_override_not_a_default` —— 「残余流量是 override」
  这句话的**可执行**形态：不配置 ⇒ 四个入口一个都不落旧链；显式写才落；
- `test_the_retirement_flag_is_read_from_the_registry_not_recopied` —— 观测侧读注册表那一份；
- 退役 ≠ 删除：六个冻结文件逐个 `exists()` + stage 图 handler 全部可调用
  （「注册还在但 handler 被摘空」是最坏的中间态：不报未注册，而是安静空转到
  `advance_step_limit`）。

---

## 14. 变异证据（本步四条）

| # | 变异 | 红的用例 | 关键输出 |
|---|---|---|---|
| **M-A** | `ArtifactTimeline.isBlueprint` 改用**朴素判据** `artifact_type === 'technical_plan'` | 2 | `expected true to be false` —— v0 条目被当成蓝图；「未知 schema 按 v0」那条同时红 |
| **M-B** | 删掉 `TechPlanCard` 正文区的蓝图分档（`v-else-if="isBlueprint"` → `false`） | 2 | `expected false to be true` —— 告示条消失，蓝图退回渲染空壳 |
| **M-C** | `DEFAULT_ENTRY_SWITCH` 四键**回退**成 `technical_plan` | **29** | ⭐ 四个入口的 `[None]`（零配置）变体全红、`[technical_blueprint]`（显式）变体全绿 —— 精确证明**驱动蓝图链的是翻过的默认**，不是显式设置 |
| **M-D** | `_default_for` 硬写回 `PROCESS_TECHNICAL_PLAN` | 9 | ⭐ 除 6 条 fail-soft 用例外，**`test_per_entry_rollback_only_affects_the_configured_entry` 一并转红** —— 这就是 §12.2 那个「一条 `{"mcp": ...}` 把另外三个入口一起拖回旧链」的实证，也是把 fail-soft 落点改掉的**决定性理由** |

每次变异后均 `git checkout --` / 备份还原，还原后复跑全绿。

⭐ M-C 与 M-D 的组合值得单记：M-C 证明「默认翻了」，M-D 证明「翻了之后**在真实配置形态下
仍然成立**」。只做 M-C 会漏掉 M-D 那个洞 —— 而那个洞的表现是「运维回滚一个入口，四个一起
回退」，静默且完全符合直觉之外。

---

## 15. 回归与验收（本步）

| 项 | 结果 |
|---|---|
| `uv run pytest tests/ -q` | **9813 passed / 61 skipped / 1 failed**（本步开工前实测基线 9781 passed / 1 failed）⇒ **+32 例，零回归** |
| 唯一失败 `tests/mcp_tools/test_mcp_package_alignment.py` | **已知基线失败**（`mcp` npm 包是独立仓 / submodule，缺本里程碑新增的四个工具）。⛔ 不在本次范围，与第一步同一条 |
| `uv run python manage.py makemigrations --check --dry-run` | `No changes detected` ⇒ **零新增迁移** |
| `ruff check` / `ruff format --check`（全部改动文件） | 通过 |
| `pnpm exec vitest run` | **2095 passed / 1 skipped**（基线 2053 / 1）⇒ **+42 例，零回归** |
| `pnpm type-check` | **exit 0** |
| `pnpm lint` | **111 problems**（与基线**逐个相同** ⇒ 触点文件零新增；中途出现过 2 条 `perfectionist/sort-imports`，已改正） |
| `pnpm build` | 通过 |
| 生成物 `web/src/components.d.ts` | ⚠️ `pnpm build` 又一次顺带裁掉 29 条既有条目（115-06 Deviation 6 预警过的现象）。本次**无新增组件** ⇒ 直接 `git checkout --` 还原，最终 diff 为空 |
| `web/package.json` / `pnpm-lock.yaml` / `pnpm-workspace.yaml` | **零行变更**（本次未出现 catalog 回填） |
| 六个 technical_plan 冻结文件 + `codegraph/services/repo_router_v2.py` + MCP 共享 handler factory | `git diff 25b66d85 -- <path>` **全空** |
| `ConvergenceSessionEvent` | **零新增类型**（本步全是读侧、判别与配置） |

---

## 16. 判断记录（本步）

1. **fail-soft 落点从硬写旧链改成 `_default_for`，超出「翻四个字面量」的字面范围。**
   不改的话，一条正常的单入口回滚配置会把另外三个入口一起拖回旧链（M-D 实证），
   「翻了默认」这件事在最常见的运维配置形态下根本不成立。同时把「该键缺席」从
   `invalid_value` 里拆出来，否则未配置入口每次编排都刷一条 warning。

2. **未知 entry 保留回旧链。** 它不是入口、没有声明默认值，因此不构成「某个入口的默认」，
   与退役不冲突；把一个身份不明的调用方送进需要 `project_id` 的蓝图链只会换一种失败形态。
   这条差异写进了 `_default_for` 的 docstring 与用例名。

3. **18 个既有用例显式 override 回旧链，而不是改写它们的断言。** 它们测的是旧链的
   stage 图与 content 形态，那些行为**没有变**；变的只是「怎么到达那条链」。改断言等于
   丢掉旧链的回归覆盖 —— 而旧链恰恰还要为在途会话服务。

4. **MCP delegate 模块逐条挂而非模块级挂。** 该模块两类用例并存，模块级 patch 会吞掉蓝图
   那一组的真配置（第一次就这么挂并当场转红）。

5. **⛔ 不改 `map_merged_plan_to_coding_plan`。** 从蓝图版本投影出来的 CodingPlan 内容
   仍然是空的 —— 本次让这件事**不再静默**（前端如实说明 + 导向查看器 + 用例显式断言
   `affected_files == []` 并写明理由），但**没有**在 chat 侧接第二条派生链。真要补内容，
   应复用 `blueprint_execution.derive_execution_plan`，那是独立工作项。

6. **三处触点不接 vue-i18n，另立一张中文表 + 漂移守卫。** 理由见 §11.2；形状与第一步 §5
   给 `_BLUEPRINT_STATUS_MESSAGES` 用的同一招。

7. **`NodeDataTab` 不把 `ai_plan_research` 加进 `AI_NODE_TYPES`。** 那会顺带改变 **v0**
   执行记录的渲染（markdown 智能渲染 + 模式切换按钮），违反「v0 逐像素不变」。蓝图那一档
   只加告示条，⛔ 不动既有渲染分支。

8. **退役标记落 `ProcessDefinition.config` 而不是新加字段/新加迁移。** 既有字段、零迁移、
   程序可查，三者同时满足；`retained_reason` 进数据是为了防「顺手清理」。

---

## 17. 提交（本步）

| commit | 内容 |
|---|---|
| `789a1c0a` | `feat(blueprint): 三处前端触点识别 blueprint/v1 并导向蓝图查看器` |
| `39b84961` | `feat(blueprint): 四个入口开关默认值翻到 technical_blueprint` |
| `e3184cef` | `chore(blueprint): 旧 technical_plan process 标记退役并收口` |

对账（`REQUIREMENTS.md` / `MILESTONE-AUDIT.md` / `STATE.md`）单独一个 commit。

---

## 18. GATE-01 状态

**满足。** 第一步（三道接缝 + 终态映射）与本步（触点 + 翻默认 + 退役）合起来，
`REQUIREMENTS.md` 里 GATE-01 那条 ⏭ 清单的四项**全部交付**：

| 原 ⏭ 项 | 落点 |
|---|---|
| 把开关默认值翻成 `technical_blueprint` | §12（`blueprint_entry_switch.py:72-77`） |
| 旧 `technical_plan`「不再是任何入口默认」的收口 | §13（`builtin_processes.py:1241/1257`） |
| `TechPlanCard` / `NodeDataTab` / `ArtifactTimeline` 三处触点升级 | §11 |
| workflow 节点终态改人审 HITL 挂起 | **第一步 §2** 已交付（`_amap_terminal_blueprint`） |
