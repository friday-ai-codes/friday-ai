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
