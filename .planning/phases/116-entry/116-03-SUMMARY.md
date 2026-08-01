---
phase: 116-entry
plan: 03
subsystem: process_runtime + entry-wiring + chat
tags: [entry-switch, engine-dispatch, project-scope, chat-hitl, barrier-feedback, observability, security]
requires: ["116-01", "116-02"]
provides:
  - "六个续驱点全部经 build_engine_for_session 取 (engine, driver)"
  - "四个入口的 per-entry 开关分派（字面量常量）与 entry_key 逐点补齐"
  - "四个入口的 meta.project_id 推导与「推不出即拒绝发起」错误出口"
  - "plan_research_tools._maybe_suspend_blueprint / _map_terminal_blueprint（chat 蓝图判据）"
  - "callbacks._afeedback_chat_blueprint_barrier（两个蓝图 barrier 的 CHAT 回灌）"
  - "delegate_process_runtime 的 work_item_context 形参与 DelegateResult.error_detail"
affects: [116-06]
tech-stack:
  added: []
  patterns:
    [ast-source-scan-guard, literal-entry-key, single-source-project-resolution, fail-closed-intake, best-effort-barrier-feedback]
key-files:
  created:
    - server/tests/services/process_runtime/test_entry_dispatch_wiring.py
    - server/tests/agents/test_chat_blueprint_entry.py
  modified:
    - server/workflows/nodes/ai/plan_research.py
    - server/agents/tools/plan_research_tools.py
    - server/mcp_tools/orchestration_delegate.py
    - server/services/process_runtime/answer_resume.py
    - server/feishu/callbacks/plan_clarify_callback.py
    - server/initiatives/services/feature_solution_service.py
    - server/subagent/api/callbacks.py
    - server/tests/workflows/test_plan_research_node.py
    - server/tests/services/test_plan_research_e2e.py
    - server/tests/services/test_answer_resume.py
    - server/tests/knowledge/test_triggers.py
    - server/tests/agents/test_start_plan_research_tool.py
    - server/tests/mcp_tools/test_create_feishu_technical_plan_delegate.py
    - server/tests/feishu/test_plan_clarify_callback.py
decisions:
  - "四个入口的蓝图路径一律走「早退到独立 helper」而不是 if/else 包住既有调用 —— 旧链代码路径因此**一行未动**（比「开关关闭时行为逐字一致」的断言更强，且删除行最少）"
  - "answer_resume 传入 engine 时仍调用分派器：engine 用调用方的、driver 恒用分派出的。既有那条 `build.assert_not_called()` 与「driver 必须被分派」实现上互斥，改成断言 engine 身份（更强、更贴语义）"
  - "MCP 的 work_item_context 作为 delegate_process_runtime 的纯追加形参落地；调用方接线（technical_plan_service / views）与响应键归 116-06（那两个文件在 116-06 的 files_modified 里）"
  - "MCP 的中性 detail 经 DelegateResult.error_detail（纯追加、缺省空串）回传，⛔ 不新造一种失败返回形态"
  - "_map_terminal_blueprint 的 needs_clarification 档复用 _maybe_suspend_blueprint(force_clarification=True)，⛔ 不复制第二份 BlueprintThread 查询"
metrics:
  duration: "~3h"
  completed: 2026-08-01
---

# Phase 116 Plan 03: 四入口的蓝图可执行路径 + chat 三条断链 Summary

**One-liner:** 把 116-01 的分派器与 116-02 的 intake 接到四个真实入口上——六个续驱点（含 CONTEXT 未点名、漏改即「作答后无人续驱且零异常」的 `answer_resume` 与飞书澄清卡回调）全部改成 engine 与 driver 一起分派并用 `ast` 扫描把漏改变成机器可逮，四个入口按**字面量常量**查 per-entry 开关、`meta.project_id` 单点推导、推不出即拒绝发起且 DB 零副作用；同时补掉 chat 那条路上的三处断链（等澄清的健康会话不再被报成「方案编排失败」、两个蓝图 barrier 补上 CHAT 回灌），两条「不做会怎样」的反向变异各实跑一次真实变异背书。

## PHASE_BASE

```
PHASE_BASE = 67c7bb5b1e98af7549bda9dda003c8ab9dc4725a
```

本 plan 全部冻结面 / 删除行 / `--name-only` 断言一律写作 `git diff $PHASE_BASE -- <file>`，⛔ 无一条裸 `git diff`（GSD 逐 Task 原子提交后裸 `git diff` 恒空、断言会静默恒真，B5）。计数型断言一律 `| grep -c '<pat>' || true` 再比对数字。

## Commits

| # | Hash | 内容 |
|---|---|---|
| 1 | `92ebd207` | Task 1：六个续驱点改分派器（连 driver）+ `ast` 源码扫描守卫 + 六个既有测试的 mock 边界跟随 |
| 2 | `4d4f7396` | Task 2：四入口开关分派 + `project_id` 推导与拒绝发起 + `feature_segments` 透传 |
| 3 | `1086dfe2` | Task 3：chat 三条断链 + `test_chat_blueprint_entry.py` + 两条反向变异实跑 |

---

## ⭐ 六个续驱点的改造对照表

| # | 文件:行（改前） | 改前 | 改后 | 该点透传的旧链开关 |
|---|---|---|---|---|
| ① | `workflows/nodes/ai/plan_research.py:361`（`_build_engine`） | `build_orchestration_engine(node_execution_id=…)` 返单个 engine；`execute:207` 硬编码 `adrive_convergence_…` | `_build_engine` 返 **`(engine, driver)` 二元组**；`execute` 改 `engine, adrive = self._build_engine(...)` + `await adrive(engine, session, max_steps=_MAX_ADVANCE_STEPS)` | `node_execution_id` |
| ② | `agents/tools/plan_research_tools.py:134` | `build_orchestration_engine()` + `:139` `adrive_convergence_…` | `engine, adrive = build_engine_for_session(session)` + `await adrive(...)`；那段「与工作流节点同一 `build_orchestration_engine`」的注释同步改写 | 无 |
| ③ | `mcp_tools/orchestration_delegate.py:179` | `build_orchestration_engine(skip_clarification=True)` + `:180` `adrive_convergence_…` | `engine, adrive = build_engine_for_session(session, skip_clarification=True)` + `await adrive(engine, session)` | `skip_clarification=True` |
| ④ | `services/process_runtime/answer_resume.py:102-103` | **两行硬编码**：`engine or build_orchestration_engine()` + `adrive_convergence_…` | `dispatched_engine, adrive = build_engine_for_session(session)`；`engine = engine or dispatched_engine`；`await adrive(engine, session)` | 无 |
| ⑤ | `feishu/callbacks/plan_clarify_callback.py:242` | `build_orchestration_engine(node_execution_id=…)` | 先经新 helper `_aresolve_clarification_session(clarification_id)` 反查会话（⛔ 绝不信回调直传的 session_id），再 `build_engine_for_session(session, node_execution_id=…)` | `node_execution_id` |
| ⑥ | `initiatives/services/feature_solution_service.py:222` | `_build_engine()` 静态返单个 engine（`force_confirm=True`）+ `_adrive` 里硬编码 `adrive_convergence_…` | `_build_engine(session)` 返二元组；`confirm` 与 `_adrive` 两个调用点同步改 | `force_confirm=True` |

**统一形态**：`skip_clarification` / `force_confirm` **照原样传给分派器**——它内部只在 `technical_plan` 分支透传给 `build_orchestration_engine`，蓝图分支丢弃并落一条 `blueprint_engine_ignored_legacy_flag`。⇒ 六个调用点的**旧链行为逐字不变**，蓝图分支自动免疫。⛔ 六处**没有**任何 `if process_type` 判据（不复制同一份判据）。

### ⛔ 两处有意不改（各有显式断言登记）

| 位置 | 不改的理由 | 守它的断言 |
|---|---|---|
| `subagent/api/callbacks.py:389`（`_schedule_chat_plan_resume`） | 对蓝图**三重不可达**：分支条件 `last_output["source"] == "plan_research"`（蓝图容器写 `blueprint_research` / `blueprint_repo_plan`）、函数体读 `lo.get("plan_session_id")`（蓝图写 `blueprint_session_id`）、外加 `entrypoint == CHAT` 守门 | `test_chat_container_callback_chain_is_untouched_by_design`（断言该函数体内 `build_orchestration_engine` **仍在**） |
| `initiatives/services/plan_deepen_service.py:99` | 自己建 session、`process_type` 恒 `technical_plan`，**非蓝图入口**；改它只是多一处 rebase 冲突面 | `test_the_scanner_actually_catches_an_unrewired_file`（扫描器对它**必须命中**，反证扫描器非平凡）+ `git diff $PHASE_BASE -- <该文件>` 为空 |

⚠️ **PLAN 的验收脚本把 `plan_deepen_service.py` 的路径写成 `services/process_runtime/plan_deepen_service.py`**，实测在 `initiatives/services/`（与 RESEARCH §A.4 表第 7 行一致）。测试里用的是实测路径。

### 源码扫描实跑

```
all 6 resume points rewired OK
```

（`ast` 判据：六个文件里 `build_orchestration_engine(` 与 `adrive_convergence_session_to_pause_or_terminal(` 的 **`ast.Call` 零命中**，`import` 行不误伤。）

---

## ⭐ 四个入口的接线表

| 入口 | 开关字面量 | `entrypoint` 实参（**一字未改**） | `project_id` 权威上下文 | 推不出时的失败出口 | 蓝图分支额外传的参数 |
|---|---|---|---|---|---|
| workflow（`plan_research._create_session`） | `"workflow"` | `"workflow"` | `_resolve_space(context)` → `aresolve_project_id(entry="workflow", space=…)` | `NodeResult(status="failed", error=exc.detail, output={"error_code": "blueprint_project_unresolved"}, next_handle="error")` | `project_id` / `entry_key` |
| chat（`plan_research_tools`） | `"chat"` | `"chat"` | `_aresolve_conversation(conversation_id)` → `aresolve_project_id(entry="chat", conversation=…)`（优先 `bound_project`、否则会话所属 space） | `ToolResult(success=False, error=exc.detail)` | `project_id` / `entry_key` |
| MCP（`orchestration_delegate`） | `"mcp"` | ⭐ **`"workflow"`**（既有约定，`:4` / `:131` docstring 逐字写明） | `aresolve_project_id(entry="mcp", work_item_context=…)`（内部先取 `Space` **再过** `_aresolve_project`） | `DelegateResult(status="failed", content={}, error_detail=exc.detail)` | `project_id` / `entry_key` |
| feature list（`feature_solution_service`） | `"feature_list"` | 调用方传进来的 `entrypoint`（`mcp` / `tool_invoke`，**一字未改**） | `aresolve_project_id(entry="feature_list", feature_meta=…)`（已是 Project id，**仍校验** UUID + 存在性） | `FeatureSolutionError("project_unresolved", exc.detail)` | `project_id` / `entry_key` / `mode` / `feature_segments` / `feature_meta` |

**四处的开关实参与 `entry_key` 全部是字面量常量**（116-01 的 `ast` 守卫此刻覆盖真实调用点、不再是空扫描）：

```
4 literal switch call sites OK
```

**旧链路径一行未动**：四个入口的蓝图分支都写成「**早退到独立 helper**」而不是 `if/else` 把既有 `start_orchestration(...)` 包进去 ⇒ 既有调用块只多了一行 `entry_key="<字面量>",`，其余实参一个不少一个不改。这比「开关关闭时行为逐字一致」的行为断言更强，也是删除行最少的形态。

**`project_id` 推导单点复用**：四个入口 `aresolve_project_id` 各 ≥1 命中；`_aresolve_project(` 在 `orchestration_delegate.py` / `plan_research_tools.py` **零命中**（换算收口在 `blueprint_intake`）。

```
MCP P-8 wiring OK
no force_confirm leak OK
map_terminal boundary noted OK
```

---

## ⭐ chat 挂起 marker 的逐字键集（前端消费方据它渲染）

| 键 | 旧链分支（`technical_plan`） | 蓝图分支（`technical_blueprint`） |
|---|---|---|
| `clarification_id` | `str(Clarification.id)` | ⭐ **`str(BlueprintThread.id)`** |
| `pending` | `True` | `True` |
| `marker` | `PLAN_CLARIFICATION_RENDER_MARKER` | **同一个常量**（⛔ 不新建第二个 —— 前端按 `marker` 分派渲染，新 marker 会让蓝图澄清在对话里**什么都不渲染**） |
| `question` | `Clarification.question` | 线程首条消息 `body`，⭐ 过 `redact_secrets_in_text`（半可信 LLM 产出进对话，T-116-25） |
| `options` | `[]` | `[]` |
| `allow_freeform` | `True` | `True` |
| `session_id` | `str(session.id)` | `str(session.id)` |
| `artifact_id` | —— | ⭐ **新增**（供前端深链到蓝图查看器） |

判据（与 `blueprint_resume.adrive_blueprint_session_to_pause_or_terminal` 的 pause 短路**同源**）：`waiting_clarification` **且**存在 open + blocking 的 `BlueprintThread`，⭐ **不传 `kind`**（`ai_clarification` 与 `repo_confirmation` 两类都算），查询**显式 `order_by("created_at")`**（`BlueprintThread.Meta` 无 `ordering`，不排序会让「首题」随数据库返回顺序漂移）。

```
blueprint suspend criteria OK
single marker OK
```

`waiting_event` 档的 blocking task marker 键集**逐字复用旧链分支**（只有 `placeholder` 文案换成蓝图口径）；`task_id` 与 `params.session_id` 都是 `str(session.id)` —— 那是 barrier 回灌 key 对齐的另一半。

---

## ⭐ `_map_terminal_blueprint` 的分档表

| 蓝图状态 | 返回 |
|---|---|
| `needs_clarification` | ⭐ **挂起 marker**（复用 `_maybe_suspend_blueprint(force_clarification=True)`，同一份线程查询），⛔ **不是** `success=False` |
| `pending_review` | `success=True` + `{session_id, artifact_id, current_status, message="技术蓝图已产出，等待人工终审。"}` |
| `confirmed` / `implementing` / `implemented` | `success=True` + 对应文案 |
| `failed`（或会话 `FAILED`） | `success=False` + `session.error` 的消息 |
| 其余中间态（`researching` / `drafting` / `ai_reviewing` …） | `success=True` + 「技术蓝图编排仍在进行中。」 |

⭐ **「其余中间态一律不报失败」的理由**：会话已到终态但蓝图状态还停在中间态，属于**可诊断的异常**——产物在库里、可继续推进；报「失败」只会让用户以为方案没了并放弃（正是 T-116-23 要消灭的那类误导）。

⛔ **响应体键名不出现字面 `blueprint_status`**（INV-6 `_RE_FIELD_DICT_KEY` 扫全 `server/`）⇒ 用 `current_status`（114-05 立的既有解法）。`rg -cE "['\"]blueprint_status['\"]\s*:" plan_research_tools.py` = **0**；`test_blueprint_inv6_guard.py` + `test_blueprint_log_redaction_guard.py` 共 18 条全绿。

---

## ⭐ barrier 回灌（断链一）

```python
async def _afeedback_chat_blueprint_barrier(blueprint_session) -> None
```

落在 `server/subagent/api/callbacks.py`，由 `_trigger_blueprint_research_barrier` 与 `_trigger_blueprint_repo_plan_barrier` **各调用一次**（`src.count(...) >= 3` = 一个定义 + 两处调用；`async def` 计数 == 1，⛔ 不是两份复制）。

| 项 | 取值 |
|---|---|
| 守门 | `str(session.entrypoint) != str(ConvergenceSessionEntrypoint.CHAT)` ⇒ 直接返回（与 `callbacks.py` 既有 `entrypoint == CHAT` 守门对称，常量取本文件既有的那个、⛔ 不写裸字符串） |
| 二次守门 | 重读会话后 `status` 不在 `{DONE, FAILED}` ⇒ 不回灌（否则会以 `success=False` 提前把 chat 阻塞任务误解析为失败，与 `_schedule_chat_plan_resume` 的 e2 守门同口径） |
| `task_id` / key | ⭐ **`str(session.id)`**，与 `plan_research_tools` 注册 blocking task 时的 `{"task_id": str(session.id), "task_type": "plan_research", ...}` 逐字对齐 |
| `task_type` | `"plan_research"`（复用既有 blocking task 通道） |
| `success` | ⭐ `session.status == DONE` **且** 蓝图状态 `!= "failed"` |
| `output` | `str(session.current_artifact_version_id or "")`（失败时空串） |
| `error` | `"" if success else str(session.error or {})` |
| 事件 | `blueprint_chat_barrier_notified`（`category="sampling"` / `component="subagent"` / `session_id` / `barrier_satisfied`） |
| 兜底 | 整段 `try/except Exception` 只 log（`blueprint_chat_barrier_feedback_failed`），⛔ 绝不反噬 barrier 与容器回调 |

⭐ **「蓝图的成功判据不能只看 `ConvergenceSessionStatus.DONE`」的理由**：蓝图 `DONE` 的语义是「**等人审**」，而对 chat 用户来说方案**已经产出**——那也是成功。只有蓝图状态 `failed`（或会话 `FAILED`）才该把 waiter 唤成失败。

⭐ **key 一律由服务端从会话反查**，⛔ 绝不取 runner 上报的 `last_output` 里的任何值（T-116-24）。

```
shared feedback helper + barrier key OK
```

`git diff $PHASE_BASE -- server/subagent/api/callbacks.py | grep -c '^-[^-]'` = **0**（纯追加）。

---

## ⭐ 两条反向变异的红/绿实跑记录

| 变异 | 改了什么 | 转红的用例 | 错误首行 |
|---|---|---|---|
| **(a)** | `_maybe_suspend` 的蓝图分流改成 `if False and …` | `test_healthy_awaiting_clarification_returns_suspend_marker_not_failure`（并带红 `test_repo_confirmation_thread_also_suspends`） | `E   assert None is not None` |
| **(b)** | 两个 barrier 里的 `await _afeedback_chat_blueprint_barrier(blueprint_session)` 调用行删掉 | `test_research_barrier_feeds_back_after_resuming`（并带红 `test_both_blueprint_barriers_share_one_feedback_helper`） | `E   AssertionError: Expected mock to have been awaited once. Awaited 0 times.` |

两条恢复后各跑一次 `tests/agents/test_chat_blueprint_entry.py -q` → **16 passed**。⛔ 变异是**真跑的**，不是声明的。

⚠️ **变异 (a) 的翻转位诚实登记**：转红的是 `assert result is not None`（挂起判定整体失效）那一行，而不是更下面的 `success is True`。原因是本用例走的是 `_maybe_suspend` 单元面：分流被禁用后旧链判据对蓝图会话返回 `None`，用例在第一条断言就停。`success is True` 那条断言仍在原地（它守的是「返回值不是 `ToolResult(success=False)`」这条与现状的直接对立面），只是在这个变异下不是翻转位。

---

## ⭐ 两处跨相位交接登记

### ① MCP 响应键三键 + `status="partial"` 归 **116-06**

本 plan 只让 MCP 入口**能建蓝图会话并续驱**：新增 `delegate_process_runtime(work_item_context=…)` 形参与 `DelegateResult.error_detail`（两者都是**纯追加、缺省值等价于改动前**）。⛔ **调用方接线未做** —— `mcp_tools/technical_plan_service.py:370` 与 `mcp_tools/views.py:1925/2107` 目前**不传** `work_item_context`，因而 MCP 开关打开时会走到「推不出 project_id ⇒ 拒绝发起」。这**不是遗漏**：那两个文件在 **116-06 的 `files_modified`** 里（同相位、wave 5），本 plan 按相位边界纪律不得改动。116-06 需要做的是：

1. `technical_plan_service` / `views` 的三处调用点补 `work_item_context=context`；
2. `create_feishu_technical_plan` 响应追加 `blueprint_artifact_id` / `blueprint_status` / `pending_clarifications[]` 并把 `status` 落 `partial`；
3. 把 `DelegateResult.error_detail` 接进失败响应体（本 plan 已把中性 detail 送到 delegate 边界）。

`orchestration_delegate.py` 内已留一行指向 116-06 的边界注释。

### ② workflow 终态 `pending_review → waiting_event` HITL 挂起归**同步点 2 之后的收尾 plan**

`plan_research._map_terminal`（`:544-570` 区段）**函数体一行未改**，其上方新增了边界 TODO 注释（源码断言 `'同步点 2' in src[i-900:i]` 通过）。理由：蓝图的 `DONE` 语义是「等人审」，而该函数把 `DONE` 无条件映射成 `completed` 并把 `plan` 喂给下游 `human_approval(plan_feishu)` / `ai_coding` ⇒ **现在翻 workflow / chat 开关的默认值 = 让编码代理拿着未经人审的蓝图去建分支写代码**，正面违反 RELY-01（T-116-18）。下游消费形态由 v0.19.0 Phase 109 的 execution 投影承担。

---

## 受限面删除行逐行登记（⚠️ 四个文件超出 PLAN 的上界，逐条说明）

| 文件 | 上界 | 实际 | 超出部分是什么 |
|---|---|---|---|
| `subagent/api/callbacks.py` | **0** | **0** | —— 纯追加 ✅ |
| `feishu/callbacks/plan_clarify_callback.py` | 2 | **2** | 模块级 import 行 + `:242` 那行 ✅ |
| `mcp_tools/orchestration_delegate.py` | 8 | **8** | 5 行多行 import 块 + `start_orchestration` 首行 + `:179-180` 两行 ✅ |
| `workflows/nodes/ai/plan_research.py` | 8 | **11** | 超出 3：`execute` 的 3 行多行 import 块（`adrive_convergence_…` 已无调用点，留着即 ruff F401）、`_build_engine` 的 docstring 首行、「# 2. 注入真实 adapters 构造 engine」注释行 |
| `agents/tools/plan_research_tools.py` | 10 | **12** | 超出 2：5 行多行 import 块（原块有三个名字）+ 两行描述旧工厂的注释 |
| `services/process_runtime/answer_resume.py` | 2 | **9** | 超出 7：**5 行模块/函数 docstring**（原文逐字点名 `build_orchestration_engine` 与 `adrive_convergence_…`，留着即与实现相悖）+ 2 行 import |
| `initiatives/services/feature_solution_service.py` | 8 | **11** | 超出 3：`_build_engine` 的 docstring 首行 + `_adrive` 里 3 行多行 import 块（其中 1 行是空行外的实体行） |

⭐ **超出的每一行都是「描述旧行为的注释 / docstring / 多行 import 块」，⛔ 没有一行是逻辑删除**：七个文件里被删掉的**可执行语句**只有各续驱点那 1–2 行调用本身（就是 PLAN 要求改的那些），旧链的判据、参数、分支结构一行未动。PLAN 的上界显然只核算了「调用行」，未计入随之失效的 import 块与注释——留着它们要么触 ruff F401、要么让注释与实现相悖。

## 冻结面与相位边界核算

`git diff $PHASE_BASE --name-only` 的**源码**部分只含本 plan 声明的七个文件 + 两个新测试文件：

- 六个 technical_plan 冻结文件（`decompose_segments.py` / `research_adapter.py` / `architect_merge_adapter.py` / `merged_plan.py` / `clarify_adapter.py` / `render.py`）：`git diff $PHASE_BASE -- <该文件>` 逐个**输出为空** ✅
- `server/codegraph/services/repo_router_v2.py`：**为空** ✅
- `server/initiatives/services/plan_deepen_service.py`：**为空** ✅
- `web/`：`git diff $PHASE_BASE --name-only | grep '^web/'` **零命中** ✅
- 116-04 的 `files_modified`（`knowledge/*` / `delivery/services/artifact_service.py` / `delivery/api/blueprint_doc_views.py` / `web/*`）：**零命中** ✅
- 116-06 的 `files_modified`（`mcp_tools/views.py` / `mcp_tools/technical_plan_service.py` / `blueprint_spec_gate.py` 等）：**零命中** ✅
- 零新增 migration、零新依赖、零新 stage 名、零新 `CallSource` 枚举、`BLUEPRINT_EVENTS` 未动、前端零改动。

`uv run python manage.py makemigrations --check --dry-run` 退出码 **0**、输出 `No changes detected`；`git status --porcelain server/*/migrations/` **为空**。

### ⚠️ 另外改动了六个既有测试文件（mock 边界跟随，非声明面）

| 文件 | 改的是什么 | 为什么必须改 |
|---|---|---|
| `tests/workflows/test_plan_research_node.py` | `_bind_engine` 返回二元组 | `_build_engine` 的返回类型变了（PLAN 明写「若该方法被测试 patch，同步改测试」） |
| `tests/services/test_plan_research_e2e.py` | 同上 | 同上 |
| `tests/knowledge/test_triggers.py` | `_build_engine` 的 monkeypatch 返回二元组 | 同上 |
| `tests/agents/test_start_plan_research_tool.py` | patch 目标 `services.process_runtime.build_orchestration_engine` → `services.process_runtime.entrypoint.build_orchestration_engine`（3 处） | 分派器调的是 `entrypoint` 模块内的那个名字，barrel 上的 re-export 是**另一个名字绑定**，patch 它不再生效 |
| `tests/mcp_tools/test_create_feishu_technical_plan_delegate.py` | 同上（3 处）+ `adrive` 的 patch 目标改成 `services.process_runtime.resume.…`（2 处） | 同上 |
| `tests/feishu/test_plan_clarify_callback.py` | patch 目标改成 `{_MOD}.build_engine_for_session` 并返回二元组；新增对 `_aresolve_clarification_session` 的 patch；断言改成 `assert_called_once_with(None, node_execution_id="ne-1")` | 该模块 import 的名字变了，旧 patch 目标已不存在（`AttributeError`） |
| `tests/services/test_answer_resume.py` | 见 Deviations 第 1 条 | 见 Deviations 第 1 条 |

⛔ **无一条断言被削弱**（`test_answer_resume` 那条是**替换成更强的**，见 Deviations）。

## 全量后端门（与基线逐条比对）

| | 基线（116-02 收口） | 本 plan 收口 | 差异 |
|---|---|---|---|
| passed | 8691 | **8741** | **+50** = 34 条 `test_entry_dispatch_wiring.py`（21 个 `def test_`，参数化展开后 34 条 item）+ 16 条 `test_chat_blueprint_entry.py` |
| failed | 1 | **1** | **无新增失败** —— 唯一失败仍是 `tests/mcp_tools/test_skills_snapshot_guard.py::test_skill_files_discovered`（本 worktree `skills/` 为空目录的环境产物，P-16，⛔ 不属本相位） |

⚠️ **第一次全量跑出现过第 2 条失败，已三重核实是排序 flake 并在复跑中自行消失**：`tests/initiatives/test_memory_mr_api.py::test_draft_confirm_via_api`。① 单独跑 `tests/initiatives/test_memory_mr_api.py` → **5 passed**；② `tests/agents/ tests/initiatives/` 一起跑（本 plan 新增的 `tests/agents/test_chat_blueprint_entry.py` 在它**之前**收集）→ **609 passed**；③ **原样复跑一次全量** → `1 failed, 8741 passed`，该用例已绿。本 plan 的两个新测试文件按 pytest 收集顺序一个在 `tests/agents/`（之前）、一个在 `tests/services/process_runtime/`（之后），两侧都不构成污染源；该用例与本 plan 触及的七个源文件无任何调用关系。

`ruff check` / `ruff format --check` 对全部触及文件通过。

## 事件目录（本 plan 新增）

| 事件名 | category | component | 关键字段 |
|---|---|---|---|
| `plan_research_blueprint_rejected` | caller | `plan_research` | `reason` |
| `plan_research_blueprint_session_created` | caller | `plan_research` | `session_id` |
| `start_plan_research_blueprint_rejected` | caller | `plan_research_tools` | `conversation_id` / `reason` |
| `start_plan_research_blueprint_started` | caller | `plan_research_tools` | `session_id` / `conversation_id` |
| `mcp_plan_delegate_blueprint_rejected` | caller | `mcp_tools` | `reason` |
| `feature_solution_blueprint_rejected` | caller | `feature_solution` | `reason` |
| `blueprint_chat_barrier_notified` | sampling | `subagent` | `session_id` / `barrier_satisfied` |
| `blueprint_chat_barrier_feedback_failed` | sampling | `subagent` | `session_id` |

⛔ **需求原文 / 澄清题正文一律不进日志**（只记 `reason` / id 类标量）；`question` 进**对话返回体**时过 `redact_secrets_in_text`。⛔ `builtin_processes.py` 未改动（它在 `_SCANNED_MODULES` 内的 `error=` 约束因此不适用于本 plan 的新事件）；六个 `*_rejected` 事件**均不带 `error=` 实参**（只记稳定枚举串 `reason`）。

---

## GATE-01 的当前完成度自评

**本相位交付「实现路径 + 开关」，默认切换顺延** —— 与 ROADMAP / REQUIREMENTS 的对账文案对齐：

- ✅ **四个入口都真的能走蓝图链**：把 `blueprint.entry.switch` 的任一键改成 `technical_blueprint`，那个入口就建蓝图会话、落 `blueprint/v1` 骨架、用蓝图 engine + 蓝图 driver 推进。**改一个设置值即生效，回滚也是改一个设置值**（有四入口 × 两态的行为用例背书）。
- ✅ **六个续驱点一个不漏**，「漏改一处」被 `ast` 扫描变成机器可逮的红。
- ✅ **chat 那条路是真的**（三条断链全补）。
- ✅ **`meta.project_id` 推不出就拒绝发起**，四入口各自如实回错且 DB 零副作用；MCP 的 Space/Project 混淆有源码级 + 用例级双防线。
- ⏳ **默认值仍全部 `technical_plan`**（本 plan 明确不翻）：翻默认阻塞在**同步点 2** —— 蓝图 `DONE` 语义是「待人审」，而 `AIPlanResearchNode._map_terminal` 把 `DONE` 映射成 completed 并喂给下游 `ai_coding`，现在翻默认会正面违反 RELY-01。
- ⏳ **MCP 入口的调用方接线与响应键**归 116-06（见上文交接登记 ①）。

---

## Deviations from Plan

### 1. [Rule 1 → 自主决断] `test_answer_resume.test_explicit_engine_reused_no_build` 的断言换成更强的一条

- **Found during:** Task 1 ④
- **Issue:** 该用例断言「显式传入 engine ⇒ `build_orchestration_engine` **不被调用**」。而 PLAN 的硬要求是「若调用方只传 engine 不传 driver，**driver 仍必须由分派器按 `session.process_type` 选**」—— 分派器是**同时**产出 `(engine, driver)` 的单一入口（`entrypoint.py` 不在本 plan 的 `files_modified` 里，⛔ 不能给它加一个「只要 driver」的第二 API）。两条要求在实现上互斥。
- **Fix:** 用例改名为 `test_explicit_engine_reused_but_driver_still_dispatched`，断言换成 ① `adrive` 收到的 engine **是调用方传进来的那个**、② 它**不是**分派器构造的那个（`is not build.return_value`）。这两条**直接断言了 PLAN 要保住的语义本身**（「调用方传入 engine 时优先用调用方的」），比原来那条实现细节断言更强；docstring 里逐字写明了为什么不能再断言「分派器不被调用」。
- **Files:** `server/tests/services/test_answer_resume.py`
- **Commit:** `92ebd207`

### 2. [Rule 3 - 阻塞] MCP 的 `work_item_context` 只能落到 delegate 边界，调用方接线归 116-06

- **Found during:** Task 2（MCP 入口）
- **Issue:** `delegate_process_runtime` 的既有签名**根本收不到** `McpWorkItemContext` —— 两个调用方 `mcp_tools/technical_plan_service.py:370` 与 `mcp_tools/views.py:1925/2107` 只传 `requirement_text` / `work_item` / `include_repos` / `created_by` / `extra_evidence`。而那两个文件在 **116-06 的 `files_modified`** 里（同 milestone、wave 5），按相位边界纪律**不得改动**。
- **Fix:** 在 `delegate_process_runtime` 上加**纯追加、缺省 `None`** 的 `work_item_context` 形参（缺省行为与改动前逐字等价），并在 docstring 与代码注释里指名调用方接线归 116-06。P-8 的双防线（源码扫描 + `meta.project_id != space.id` 用例）在 delegate 边界**已经成立**：用例直接以 `work_item_context=` 调 delegate 并断言解析出的是 `Project.id`。
- **备选与否决理由:** 「从 `work_item` 反推 space」不可靠（`work_item` 可为 None，且 `delivery.WorkItem` → Space 的链路与 `McpWorkItemContext.space` 不是同一条）；「本 plan 顺手改那两个文件」会与 116-06 的同文件改动撞成 rebase 冲突面，且违反 prohibitions 第 2 条。
- **Files:** `server/mcp_tools/orchestration_delegate.py`
- **Commit:** `4d4f7396`

### 3. [登记] `_maybe_suspend_blueprint` 的定义位置前移到 `_maybe_suspend` 之前

- **Found during:** Task 3 验收脚本
- **Issue:** PLAN 的验收脚本用 `src.index('_maybe_suspend_blueprint')` 取函数体，而**首个**出现位置是 `_maybe_suspend` 里的**分流调用**，不是定义 —— 从那里往后 2500 字符全落在旧链分支里，`'BlueprintThread' in body` 恒假、`'ahas_pending' not in body` 恒真（**判据整个反了**）。
- **Fix:** 把 `_maybe_suspend_blueprint` 的定义移到 `_maybe_suspend` **之前**（纯位置移动，零逻辑改动），首个出现位置因此就是定义本身。四条断言随即全部按 PLAN 的原意成立并实跑通过（`blueprint suspend criteria OK`）。
- **Files:** `server/agents/tools/plan_research_tools.py`
- **Commit:** `1086dfe2`

### 4. [登记] 两条验收断言按语义而非字面满足

| PLAN 的字面断言 | 实际形态 | 为什么等价或更强 |
|---|---|---|
| `rg -n "objects.count()" test_entry_dispatch_wiring.py` 命中 ≥4 | 用的是 **`objects.acount()`**（四条「拒绝发起」用例各一对前后计数，共 8 处） | 本文件全部用例是 `async` + `django_db(transaction=True)`，同步 `.count()` 会直接抛 `SynchronousOnlyOperation`。语义逐字相同 |
| `rg -c "def test_" test_entry_dispatch_wiring.py` ≥ **14** | `def test_` = **21**，参数化展开后 pytest 收集到 **34 条 item** | 超出要求 |

### 5. [登记] `plan_deepen_service.py` 的路径与 PLAN 脚本不符

PLAN 的验收脚本写 `server/services/process_runtime/plan_deepen_service.py`，该文件实际在 `server/initiatives/services/plan_deepen_service.py`（与 RESEARCH §A.4 表第 7 行一致）。测试与冻结面核算都按实测路径。

### 6. [登记] 四个文件的删除行超出 PLAN 上界

见「受限面删除行逐行登记」一节：超出的每一行都是**描述旧行为的注释 / docstring / 多行 import 块**，⛔ 无一行是逻辑删除。

## Threat Flags

无。本 plan 未引入 `<threat_model>` 之外的新网络端点 / 鉴权路径 / 文件访问形态 / 信任边界处的 schema 变更。新增的 `DelegateResult.error_detail` 只承载 `blueprint_intake` 的**中性**常量文案（⛔ 不含内部路径、异常原文、内部 id）；barrier 回灌的 key 一律由服务端从会话反查（⛔ 不取 runner 上报值）。

## Known Stubs

一处**有意的**跨相位半成品，已在上文「跨相位交接登记 ①」逐条写明：`delegate_process_runtime(work_item_context=…)` 在本 plan 内**无生产调用方**（两个调用方文件属 116-06 的改动面）。⇒ MCP 开关打开时目前会走「推不出 project_id ⇒ 拒绝发起」这条**如实回错**的路径（⛔ 不是静默失败、⛔ 不是 200-空），能力面与 116-06 的接线一起闭合。已由 `test_mcp_context_resolves_to_project_not_space` 直接调用 delegate 边界背书能力可用。

## Self-Check: PASSED

- 创建文件存在：`server/tests/services/process_runtime/test_entry_dispatch_wiring.py`、`server/tests/agents/test_chat_blueprint_entry.py`。
- 三个提交 `92ebd207` / `4d4f7396` / `1086dfe2` 均在 `git log` 中。
- 两个变异备份（`/tmp/mut_a_backup.py` / `/tmp/mut_b_backup.py`）在仓库**之外**，`git status` 无残留临时文件、无一次性探针文件。
