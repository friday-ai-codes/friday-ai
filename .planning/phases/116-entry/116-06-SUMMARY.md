---
phase: 116-entry
plan: 06
subsystem: mcp-protocol + blueprint-answer + spec-gate + feishu-delivery
tags: [gate-01, mcp-tools, shared-service, fail-closed, assumptions-tiers, observability, security]
requires: ["116-02", "116-03", "116-05"]
provides:
  - "delivery/services/blueprint_answer_action.aanswer_thread（作答调用序的唯一实现，REST 与 MCP 共享三道闸）"
  - "MCP 工具 get_technical_blueprint / answer_blueprint_clarification（四处落点齐全）"
  - "create_feishu_technical_plan 追加三键 + status=partial（仅 mcp 开关切蓝图时）"
  - "technical_plan_service 接上 116-03 交接的 work_item_context 形参"
  - "aload_spec_gate_config(tier=) + max_rounds 配置化（DEFAULT_SPEC_GATE_CONFIG 单一事实源）"
  - "ascore_ambiguity(tier=) —— sampling 日志阈值与判定阈值同源"
  - "services/process_runtime/blueprint_notify.anotify_blueprint_clarification（澄清飞书卡片送达唯一收口）"
affects: ["116-07"]
tech-stack:
  added: []
  patterns:
    [shared-action-service, gate-order-source-assertion, additive-only-tool-contract, literal-entry-key, single-source-config, single-file-delivery-convergence]
key-files:
  created:
    - server/delivery/services/blueprint_answer_action.py
    - server/services/process_runtime/blueprint_notify.py
    - server/tests/mcp_tools/test_blueprint_clarification_tools.py
    - server/tests/services/process_runtime/test_blueprint_assumptions_tiers.py
    - server/tests/services/process_runtime/test_blueprint_notify.py
  modified:
    - server/delivery/api/blueprint_review_views.py
    - server/mcp_tools/views.py
    - server/mcp_tools/urls.py
    - server/mcp_tools/serializers.py
    - server/mcp_tools/technical_plan_service.py
    - server/services/process_runtime/blueprint_ambiguity_score.py
    - server/services/process_runtime/blueprint_spec_gate.py
    - server/tests/delivery/test_blueprint_log_redaction_guard.py
    - server/tests/mcp_tools/test_schema_snapshot.py
    - server/tests/mcp_tools/test_skills_snapshot_guard.py
decisions:
  - "既有 View 保留一次 is_blueprint_editable 前置调用**只为保住响应顺序**（越界 400 原本在线程 404 之前），权威 fail-closed 闸在 service 内；同一共享谓词调两次 ⛔ 不是第二份实现"
  - "MCP 响应的蓝图状态键取名 current_status / blueprint_current_status，⛔ 不用 blueprint_status —— 后者作字典键会命中 INV-6 的 _RE_FIELD_DICT_KEY"
  - "create_feishu_technical_plan 在 mcp 开关切蓝图时一律回 status=partial：蓝图的 DONE 语义是「等人审」而不是「方案已终结」"
  - "blueprint_notify 的 project 从蓝图自身 meta.project_id 反查（⛔ 不依赖 ExecutionContext），space 取 project.space；调用方也可显式传 space 走 analog 路径"
  - "澄清卡片当前是**通知形态**：action 前缀 blueprint_clarify_answer 未注册 handler，作答走 REST / MCP / 查看器三条已实装通道"
metrics:
  duration: "~4h"
  completed: 2026-08-01
---

# Phase 116 Plan 06: MCP 异步澄清协议 + assumptions 档位 + 澄清送达 Summary

**One-liner:** 让 MCP 入口不再 skip_clarification —— 把 114-05 内联在 `BlueprintReviewThreadAnswerView.post` 里的作答调用序（三道闸 + `record_answer` + 同请求回灌）下沉成 `blueprint_answer_action.aanswer_thread` 这份**唯一实现**，两个新 MCP 工具据它继承全部闸门（「对 finding 线程作答 ⇒ 400 且线程状态从 DB 重读一字未变」有实跑变异背书）；补上 116-03 交接的 `work_item_context` 接线让 mcp 开关真的能用；把 CONTEXT 误判为「零新机制」的 `max_rounds` 识别为真实改动并配置化（**删掉** `_MAX_SPEC_GATE_ROUNDS`）、把档位透传到**三个**`aload_spec_gate_config` 调用点（含最容易漏的 `ascore_ambiguity` 体内那处，漏了就是 sampling 日志报的阈值与判定用的分叉）；澄清送达收敛进**一个** `blueprint_notify.py`，兑现 CLAR-04 的另一半。

## PHASE_BASE

```
PHASE_BASE = fb63c042517fdf81a5440f2e7d90818310913ed1
```

本 plan 全部冻结面 / 删除行 / `--name-only` 断言一律写作 `git diff $PHASE_BASE -- <file>`，⛔ 无一条裸 `git diff`（GSD 逐 Task 原子提交后裸 `git diff` 恒空、断言会静默恒真，B5）。计数型断言一律 `| grep -c '<pat>' || true` 再比对数字。

## Commits

| # | Hash | 内容 |
|---|---|---|
| 1 | `77748479` | Task 1：抽 `blueprint_answer_action` + 既有 View 改调 service + 守卫清单 |
| 2 | `229ce1da` | Task 2：两个新 MCP 工具四处落点 + `work_item_context` 接线 + 追加三键 |
| 3 | `0bae932b` | Task 3：assumptions 三档（含 `max_rounds` 真实新增）+ `blueprint_notify` + 两个测试文件 |

---

## ⭐ 1. `aanswer_thread` 的逐字签名与恒定返回键

```python
async def aanswer_thread(
    artifact, thread, *, body: str, user=None, session=None,
    initiated_by_user_id: str = "system",
    lifecycle_service=None, section_writer=None,
) -> dict
```

⚠️ **相对 PLAN 的签名增补一个 `session`**：既有 View 把 `session` 传给 `aapply_thread_answers`（→ `produced_by_session_id`），不透传会让回灌产出的版本丢掉会话归属。纯追加、缺省 `None`。

**恒定五键**：`{"status", "thread_id", "reflow", "detail", "current_status"}`，`reflow` 恒为六键投影 `{status, version_id, version_no, conflict_block_ids, thread_id, detail}`（逐字沿用改造前 View 的投影，⇒ 两个调用方共享同一形状）。

### 两个调用方的 status 映射表

| service `status` | REST（`BlueprintReviewThreadAnswerView`） | MCP（`answer_blueprint_clarification`） |
|---|---|---|
| `answered` | **200** + `{status, thread_id, reflow}` | **200** + `{status, thread_id, artifact_id, current_status, reflow, run_id}` |
| `not_editable` | **400** + `{detail}` | **400** + `error_response("not_editable", detail)` |
| `not_answerable` | **400** + `{detail}` | **400** + `error_response("not_answerable", detail)` |
| `invalid` | **400** + `{detail}` | **400** + `error_response("invalid_params", detail)` |
| （线程不存在，调用方判） | **404** `_THREAD_MISSING_DETAIL` | **404** `error_response("not_found", …)` 同一文案 |
| （范围闸，调用方判） | 400 / 中性 404 | 同源闸转译成 MCP 信封，**状态码与 detail 逐字保留** |

### 三道闸的顺序与各自理由

| # | 闸 | 位置 | 理由 |
|---|---|---|---|
| ① | 项目范围闸 | **调用方**（service docstring 明写「调用方必须先过」） | 需要 `request` / token owner 这类传输层身份，service ⛔ 不吃 `request`。REST 走 `_aassert_project_scope`，MCP **import 复用同一个实现** |
| ② | `is_blueprint_editable(artifact)` | service 内，**在任何写之前** | 114-MJ-04：作答会经回灌落新版本，已 `confirmed` 的蓝图不该被无声改写 ⇒ 越界时 **DB 一字未动** |
| ③ | `kind == ai_review_finding` 一律拒 | service 内，**在 `record_answer` 之前** | 114-CR-01：回灌链落版本成功后对被消费线程无条件 `resolve_thread` ⇒ 不分流即「在 BLOCKER 上回一句任意文本」就解开 confirm 门。与回灌链的 `REFLOW_KINDS` **双重堵** |

源码级断言（实跑输出 `gate order OK`）：

```
p_edit < p_rec  且  p_find < p_rec
```

⚠️ 执行期踩到一次：闸②原本那行注释里带 `record_answer` 字样，`src.index('record_answer')` 命中的是注释 ⇒ 断言假红。改写注释为「状态闸在**任何写之前**」后判据成立（判据未放宽）。

---

## ⭐ 2. 「既有 answer 端点对外契约逐字不变」的核算证据

- `git diff $PHASE_BASE -- server/tests/delivery/test_blueprint_review_views.py` → **0 行**（该文件**零改动**）；`uv run pytest tests/delivery/test_blueprint_review_views.py -q` → **全绿**（与 INV-6 / 脱敏守卫合计 **75 passed**）。这是「对外契约逐字不变」的唯一可核算形态。
- `git diff $PHASE_BASE -- server/delivery/api/blueprint_review_views.py | grep -c '^-[^-]'` → **56**（上界 60）。
- 该文件的 diff 只有**两个 hunk**：`@@ -75,11 +75,6 @@`（常量块下沉 `_FINDING_NOT_ANSWERABLE_DETAIL`）与 `@@ -626,92 +621,68 @@`（`BlueprintReviewThreadAnswerView`）⇒ **其余六个端点零改动行**（人工核对 + hunk 边界背书）。
- 删除行逐行归类：原内联调用序整体下沉（`is_blueprint_editable` 分支体 / `_aload_thread` 后的 finding 分流 / `body` 取值与空校验 / `record_answer` / `aapply_thread_answers` 的 try-except / `add_reviewer` / 响应体六键 `reflow` 投影 / 三个函数级懒 import 块）。⛔ 无一行是「顺手删掉的别的东西」。
- **finding 文案只有一份**：定义只在 service（`rg -n "_FINDING_NOT_ANSWERABLE_DETAIL\s*=" blueprint_review_views.py` **零命中**），View 侧在类 docstring 里以**跨模块指路**的形式引用它（`rg -c` 两个文件均命中）。

### ⚠️ 登记：View 保留一次 `is_blueprint_editable` 前置调用

改造前的调用序是 `范围闸 → is_blueprint_editable 400 → _aload_thread 404 → finding 400`。若把状态闸完全交给 service，则「蓝图不可编辑 **且** 线程不存在」时的状态码会从 400 漂成 404 —— 既有测试恰好没覆盖这个组合，但那是**对外契约的实质变化**。⇒ View 保留一次**同一个共享谓词**的前置调用（纯为顺序保真），权威 fail-closed 闸仍在 service 内且两个调用方都过。类 docstring 逐字写明了这个理由。⛔ 这不是第二份实现：`is_blueprint_editable` 与 `EDITABLE_BLUEPRINT_STATUSES` 的唯一定义仍在 `blueprint_lifecycle_service`。

---

## ⭐ 3. 两个新 MCP 工具的完整契约表

| 项 | `get_technical_blueprint` | `answer_blueprint_clarification` |
|---|---|---|
| `tool_name` | `get_technical_blueprint` | `answer_blueprint_clarification` |
| URL | `/api/mcp/tools/get_technical_blueprint/` | `/api/mcp/tools/answer_blueprint_clarification/` |
| `name` | `mcp-tool-get-technical-blueprint` | `mcp-tool-answer-blueprint-clarification` |
| request 键 | `artifact_id`（必填） | `thread_id`（必填）/ `body`（必填，允许空串以便走 `invalid` 分支）/ `artifact_id`（可选，仅二次校验） |
| response 键 | `artifact_id` / `session_id` / `current_status` / `title` / `version_no` / `sections` / `markdown` / `pending_clarifications` / `run_id` | `status` / `thread_id` / `artifact_id` / `current_status` / `reflow` / `run_id` |
| 401 | `_begin` 基类统一（`authentication_failed`） | 同 |
| 400 | `invalid_params`（serializer） | `invalid_params` / `not_editable` / `not_answerable` |
| 404 | `not_found`（artifact 不存在 **或** 非成员，**同一文案**） | `not_found`（线程不存在 / 非成员 / 自报归属不符，**同一文案**） |
| 503 | `pending_unavailable`（pending 读失败）/ `internal_error`（兜底） | `internal_error`（兜底） |
| 5xx | ⛔ 无（异常一律折成结构化信封） | ⛔ 无 |

**⭐ `current_status` 这个键名决定的理由**：INV-6 的字段级守卫 `_RE_FIELD_DICT_KEY = ['\"]blueprint_status['\"]\s*:` 扫全 `server/`，把「模型字段名当字典键」判为旁路写（那三条正则正是为了逮住绕过 CAS 的写法）。本工具只**读**该字段，但拿字段名当响应键会在纯读场景触发那道**正确**的守卫 ⇒ 换个键名，守卫保持满弦、本模块也无需豁免。这是 114-05 立的既有解法，115/116 的读侧全部沿用。`create_feishu_technical_plan` 的追加键同理取 `blueprint_current_status`。

**指标与鉴权零额外代码**：基类 `_record` 已落 `RequestMetric(route=f"mcp:{tool_name}")`、`_begin` 已处理 `bind_source(MCP)` + `request.auth is None → 401` ⇒ 两个新工具只要 `tool_name` 赋对，QPS / 错误率 / 时长自动纳入。观测调用另包一层 `try/except: pass`，⭐ **业务主体绝不包进 best-effort**。

**范围闸复用不复制**：`rg -c "_aassert_project_scope" mcp_tools/views.py` = **7**，`rg -c "async def _aassert_project_scope" mcp_tools/views.py` = **0**。

**MCP 层零直写 / 零自调 REST**：`BlueprintThread(` / `BlueprintThread*.objects.a?create|a?update` 正则**零命中**；`aanswer_thread` 命中；`reverse(` / `requests.` / `httpx.` 与 blueprint 的交集**零命中**。

**新增 View 恰为 +2**：`rg -c '^class .*View\(McpToolView\)'` 由 **31 → 33**。⛔ 无第三个 list 工具（`pending_clarifications` 内联在 `get_technical_blueprint` 里，用例 `test_no_third_list_tool_was_added` 背书）。

**六段摘要**（⛔ 不塞整份 content）：`repo_associations` / `current_state_analysis` / `implementation_overview` / `api_contracts` / `impact_analysis` / `interaction_flows`，每段 `{count, titles}`，标题过 `redact_secrets_in_text`。

**`markdown` 走 116-05 的 renderer 并传真实状态**：`render_blueprint_markdown(content, blueprint_status=current_status)`（单行，命中 116-05 立的极窄逐行豁免）；`rg -n 'blueprint_status=""'` **零命中**。用例正反并列：`pending_review` 首行含「未经确认」、`confirmed` 不含。

**P-12**：`pending_clarifications` 读失败 ⇒ **503 + 中性 detail**，响应体 `set(body)` 逐字**不含** `items` / `total`，且断言内部异常原文（`db down`）不出现在响应里。⛔ 不包成 200 空清单。

---

## ⭐ 4. `create_feishu_technical_plan` 的追加三键 + 开关两态对照

| | mcp 开关 = `technical_plan`（默认） | mcp 开关 = `technical_blueprint` |
|---|---|---|
| 响应键集 | **与改动前逐字相同**（既有 12 键 + `session_id`） | 既有键集 **+ 3**：`blueprint_artifact_id` / `blueprint_current_status` / `pending_clarifications` |
| `status` | 不变（`_map_status(delegate.status)`） | 一律 **`partial`**（既有三态之一） |
| `retry_state` | 不变 | `{retryable: True, failed_stage: "blueprint_pending"}`（形态照 `:411-413` 既有 `orchestration_pending`） |

实现形态是 `**blueprint_extras` 展开：`_ablueprint_response_extras(delegate)` 在开关关闭时返回**空 dict** ⇒ 该行展开为零键，响应逐字不变（用例 `test_response_extras_are_empty_when_the_mcp_switch_is_off` + 源码断言 `"**blueprint_extras," in src` 双背书）。

**`status="partial"` 的理由**：蓝图的 `DONE` 语义是「**等人审**」而不是「方案已终结」。对 MCP 调用方回 `completed` 会让它以为可以直接把方案喂给下游；回 `partial` + `pending_clarifications` 正好表达「还得作答 / 还得等审」，且 `partial` 是**既有三态之一**、`retry_state` 形态照旧 ⇒ 调用方零破坏。

**snapshot 同步追加的核算**（`report_blueprint_context` 那条 `redispatched` 的教训逐字适用：漏在 snapshot 里 = 外部客户端按已发布契约以为它不存在）：

```
snapshot entries OK
backward compatible OK     # 既有 12 个响应键一个不少、request 恰 9 键
switch literal OK          # aresolve_entry_process_type 实参是 ast.Constant
```

**⛔ 不动 `:488` 的既有 `"project_id"` 键**（它回的是 Space id，是既有契约；蓝图侧的项目归属由 `blueprint_artifact_id` 对应的 artifact 承载）。

### 116-03 交接的接线已完成

`technical_plan_service.py` 的 `delegate_process_runtime(...)` 现在传 `work_item_context=context`（源码断言 `test_work_item_context_is_wired_into_the_delegate_call`）。⛔ 不传即「推不出 `meta.project_id` ⇒ 拒绝发起」—— mcp 开关打开时蓝图链会恒不可用，正是 116-03 SUMMARY 交接第 ① 条点名的那条。

⚠️ `mcp_tools/views.py:1925/2107` 的另外两处 `delegate_process_runtime` 调用**有意未接** `work_item_context`：它们是 `create_coding_plan` / `improve_coding_plan` 的**单仓编码方案**面，`work_item=None`、根本没有 `McpWorkItemContext` 可传；蓝图入口只有 `create_feishu_technical_plan` 这一条。116-03 交接文里「三处调用点」的说法按实读收敛为**一处**。

---

## ⭐ 5. assumptions 三档的完整配置表

| 档位 | `threshold` | `max_rounds` | 语义 |
|---|---|---|---|
| `strict` | **0.10** | **5** | 更低阈值 = 更爱问，更多轮 |
| `balanced`（默认档） | **0.20** | **3** | ⭐ 与现状**逐字相等** |
| `assume_more` | **0.45** | **2** | 更高阈值 = 更少问，轮数更少 |

`balanced` 与现状相等的核对由 `test_balanced_tier_equals_the_current_behaviour` 直接断言两个字段等于 `DEFAULT_SPEC_GATE_CONFIG` 的对应项。运行时可经 `SettingKeys.BLUEPRINT_ASSUMPTIONS_TIERS` 覆盖（用例 `test_runtime_override_beats_the_builtin_preset`）。

### ⭐ `max_rounds` 这处真实新增的改动清单

| 项 | 改动 |
|---|---|
| 配置键 | `DEFAULT_SPEC_GATE_CONFIG["max_rounds"] = 3` —— **单一事实源**（⛔ 绝不反过来取 `blueprint_spec_gate` 的常量：该文件已从本模块 import，反向取值即循环 import，而这里是模块级 dict 字面量、没有懒 import 的落点） |
| 强转 | `_to_max_rounds`：`int()` + 下界 **1**（`0` / 负值会让规格门第 0 轮即 capped = 恒不澄清，那正是档位不该能表达的语义） |
| 使用处 ① | `blueprint_spec_gate:175` 轮数判定 → `round_no >= int(config["max_rounds"])` |
| 使用处 ② | `blueprint_spec_gate:183` cap 日志 → `max_rounds=int(config["max_rounds"])`（并新增 `assumptions_tier=`） |
| 注释 ① | 原 `:79` 的「唯一放行例外仍是显式轮数上界（`_MAX_SPEC_GATE_ROUNDS`…）」→ 指向配置键 `spec_gate.config.max_rounds` |
| 注释 ② | 原 `:225` 的「轮数由 `_MAX_SPEC_GATE_ROUNDS` 兜底」→ 「轮数由配置键 `spec_gate.config.max_rounds` 兜底」 |
| ⭐ 常量 | `_MAX_SPEC_GATE_ROUNDS = 3` 的定义**已删除** |
| 顺序 | ⚠️ 配置读取**上提到轮数判定之前**（`prior` 收集之后），同一个 `config` 对象复用给阈值判定与 `_lock_spec(config=config)` ⇒ ⛔ 不再读第二次 |

**收口断言**（真 assert，⛔ 不是只 print）：`test_the_old_module_level_constant_is_gone` 断言 `'_MAX_SPEC_GATE_ROUNDS' not in src`（含两处注释引用）+ `blueprint_spec_gate_cap_reached` 邻域切片里 `max_rounds` ≥ 2 次且出现 `config[`。默认行为逐字不变由 `test_default_round_cap_is_unchanged_without_any_configuration` 背书（不配任何东西时第 2 轮仍打分开线程、第 3 轮才 `capped`）。

### ⭐ `aload_spec_gate_config` 的三个调用点清单

| # | 位置 | 传的档位 | 漏掉的后果 |
|---|---|---|---|
| ① | `blueprint_spec_gate.run`（**上提后**的那次，原 `:211`） | `tier=tier` | 阈值与轮数上界都回默认 ⇒ 档位整个不生效 |
| ② | `blueprint_spec_gate._lock_spec` 的 `config is None` 兜底（原 `:361`） | `tier=tier`（新增 keyword-only 形参） | 调用方未传 config 时回默认阈值 |
| ③ | ⭐ **`blueprint_ambiguity_score.ascore_ambiguity` 体内**（原 `:434`） | `tier=tier`（新增 keyword-only 形参） | 紧接着 `:443-444` 把 `config["threshold"]` 打进 `blueprint_ambiguity_score_completed` 的 `threshold=` / `above_threshold=` ⇒ **那条 sampling 日志报的阈值与真正判定用的分叉**，静默且永不报错（T-116-53） |

`ascore_ambiguity` 的新签名（后来者新增第四个调用点时照它补）：

```python
async def ascore_ambiguity(
    *, goal: str, feature_points: list[dict[str, Any]],
    constraints: list | None = None, prior_context: str = "",
    session_id: str = "", tier: str = "",
) -> dict[str, Any] | None
```

⚠️ 该函数**没有** `session` 可用（签名里只有原语）⇒ 只能由调用方传 tier，这正是它必须加形参的原因。`spec_gate` 调 `self.scorer(...)` 时传**同一个** tier（用例 `test_scorer_receives_the_same_tier_the_gate_decides_with` 断言 `scorer.await_args.kwargs["tier"]`）。

**AST 收口断言扫描面是两个模块**（⛔ 不是只扫 spec_gate），实跑 `len(calls) >= 3` 且每处都带实参。

**档位落点**：`stage_state["decomposition"]["assumptions_tier"]`（`_current_round` 读的是 `stage_state["spec_gate"]["round"]`，不冲突）；留痕加进 `_ambiguity_report(...)`（`ambiguity_report` 的**唯一装配点**）的两个新键 `assumptions_tier` / `max_rounds`。

**⭐ `assume_more` ≠ `skip_clarification`**：`test_assume_more_still_scores_and_still_opens_a_blocking_thread` 断言 (a) 四维打分**仍然执行**（`scorer.assert_awaited_once()` + `ambiguity_report` 四维分数都在）、(b) **仍然开 blocking 线程**（DB 重读 `kind/blocking/status`）；反向对照 `test_strict_tier_is_the_reverse_control_for_the_same_requirement` 与非恒真对照 `test_a_score_between_the_two_tiers_shows_the_knob_actually_turns`（0.30 在 strict 下要问、在 assume_more 下不问）；源码断言两个模块里 `skip_clarification` **零命中**。

---

## ⭐ 6. 四条变异的红/绿实跑记录

⛔ 变异是**真跑的**，不是声明的。四条各自 apply → 跑 → 记首行 → 从备份恢复 → 复跑确认转绿。

| # | 变异 | 转红的用例 | 错误首行 |
|---|---|---|---|
| ① | `blueprint_answer_action` 里 finding 分流**整段挪到 `record_answer` 之后** | `test_finding_thread_cannot_be_answered_and_stays_byte_identical` | `AssertionError: assert ('answered', ...) == ('open', ...)` |
| ② | `assume_more` 实现成**跳过 spec_gate stage**（直接 `_lock_spec`） | `test_assume_more_still_scores_and_still_opens_a_blocking_thread`（并带红 `test_ambiguity_report_threshold_equals_the_deciding_threshold` / `test_scorer_receives_the_same_tier_the_gate_decides_with`） | `AssertionError: Expected mock to have been awaited once. Awaited 0 times.` |
| ③ | 三个调用点**只改两处**（spec_gate 上提处退回 `aload_spec_gate_config()`） | `test_all_three_config_call_sites_pass_a_tier_argument`（并带红 report 阈值与 max_rounds 两条） | `AssertionError: ('每处调用都必须带档位实参', 'services/process_runtime/blueprint_spec_gate.py', 187)` / `assert 0.2 == 0.45` |
| ④ | ⭐ 去掉 `ascore_ambiguity` 体内的 `tier=tier` | `test_sampling_log_threshold_comes_from_the_tiered_config`（并带红调用点扫描） | `AssertionError: 打 completed 日志之前那次配置读取必须带 tier` |

恢复后各自复跑：① `1 passed`、②③④ 各 `27 passed`。

---

## ⭐ 7. `blueprint_notify` —— 澄清送达的单文件收敛

```python
async def anotify_blueprint_clarification(
    *, artifact, session=None, questions: list[dict] | None = None,
    space=None, initiated_by_user_id: str = "system",
) -> None
```

| 项 | 取值 |
|---|---|
| **收件人口径** | `BlueprintReviewer` 名单 ∪ 蓝图会话 `created_by_id`，去重升序 —— 逐字抄 `blueprint_review_action._list_recipients`；⭐ **反查会话必须带 `process_type="technical_blueprint"` 过滤**（同 artifact 上可并存两条会话，T-116-58），用例造一条同 artifact 的 `technical_plan` 会话作对照断言它不影响收件人 |
| **调用序** | 题面逐条脱敏 → project（`meta.project_id` 反查 / 或调用方传 `space` 走 analog 的 `_aresolve_project`）→ space → 收件人 → `ProjectService().resolve_or_create_group` → `FeishuIMService.create(space)` → `send_card(receive_id=chat_id, receive_id_type="chat_id", card=card)`；每一步「取不到就 `return`」的早退 |
| **⭐ 唯一接线点** | `blueprint_spec_gate._open_clarification`（开完 blocking 线程之后）。用例 `test_there_is_exactly_one_production_wiring_point` 扫全 `server/`（剔 tests）断言**调用方集合恰为 `["services/process_runtime/blueprint_spec_gate.py"]`** 且该文件里只出现 2 次（一个 import + 一处调用）⇒ ⛔ 不在四个入口各接一次 |
| **best-effort** | 整段 `try/except Exception` 只 log（`# noqa: BLE001 — 发卡 best-effort，绝不反噬挂起`）；`send_card` / 建群抛异常时函数**不抛**、返回 `None`，落 `blueprint_clarification_card_failed`（`error` 过 `redact_secrets_in_text`） |
| **脱敏** | 题面与选项逐条过 `redact_secrets_in_text` + 截断 300；⛔ **题面正文不进日志，只记 `question_count`**（AST 用例断言 logger kwarg 里无 `question`/`questions`/`body`） |

**⭐ 「同步点 1 后只改这一个文件」的收敛承诺**逐字写进模块 docstring（用例断言 `"同步点 1" in src`）。

**与 analog 的两处 DIFFER（逐字写进 docstring）**：① analog 是工作流节点方法吃 `ExecutionContext`，本模块是**独立模块级函数** ⇒ ⛔ 不依赖 `ExecutionContext`（AST 用例断言代码里没有该 `ast.Name`，只允许 docstring 提及）；② 卡片当前是**通知形态**——`action` 前缀刻意用**未注册**的 `blueprint_clarify_answer`，`CardCallbackView` 按 `startswith` 匹配、无匹配即 warning 后优雅返回（⛔ 不抢占 `plan_clarify_` 的既有路由、⛔ 不 5xx，已实读 `feishu/views.py:302-305` 确认）。**作答通道是本 plan 已实装的三条**：REST 人审端点 / MCP `answer_blueprint_clarification` / 蓝图查看器。把卡片的交互回调接上属于同步点 1 之后换送达设施的同一批改动——**那时仍然只改本文件**。

---

## 受限面删除行逐行登记

| 文件 | 上界 | 实际 | 内容 |
|---|---|---|---|
| `delivery/api/blueprint_review_views.py` | 60 | **56** | 原内联调用序整体下沉（见 §2） ✅ |
| `mcp_tools/views.py` | 0 | **0** | 纯追加 ✅ |
| `mcp_tools/urls.py` | 0 | **0** | 纯追加 ✅（见下方 ⚠️） |
| `mcp_tools/serializers.py` | 1 | **0** | 纯追加 ✅ |
| `mcp_tools/technical_plan_service.py` | 4 | **0** | 纯追加 ✅ |
| `blueprint_ambiguity_score.py` | 8 | **6** | `aload_spec_gate_config` 签名行 / 早退 `return fallback` / `return {...}` 行 / `config = await aload_spec_gate_config()` / docstring 两行 ✅ |
| `blueprint_spec_gate.py` | 12 | **8** | `_MAX_SPEC_GATE_ROUNDS = 3` 定义 + 两处注释引用 + `:175` 判定行 + `:183` 日志行 + 两处 `config = await aload_spec_gate_config()` + `_lock_spec` docstring 首行 ✅ |
| `tests/delivery/test_blueprint_log_redaction_guard.py` | 0 | **0** | `_SCANNED_MODULES` 追加 2 行（16 → 18） ✅ |

⚠️ **`urls.py` 踩过一次 formatter 噪声**：`ruff format` 会把该文件**既有的**超长 `path(...)` 行全部重排（该文件在 `PHASE_BASE` 时本就不是 format-clean，实测 `ruff format --check` 在基线即 `Would reformat`），一次运行制造 19 行无关删除。⇒ 已把该文件**回退到 `PHASE_BASE` 后重新手工追加**，最终删除行 **0**，并**不对它跑 `ruff format`**（`ruff check` 通过）。

---

## 相位边界与冻结面核算

`git diff $PHASE_BASE --name-only` 恰为 12 个文件 + 5 个新建文件，全部在声明面内：

- 六个 `technical_plan` 冻结文件（`decompose_segments` / `research_adapter` / `architect_merge_adapter` / `merged_plan` / `clarify_adapter` / `render`）：逐个 `git diff` **为空** ✅
- `codegraph/services/repo_router_v2.py`：**为空** ✅
- `delivery/services/event_taxonomy.py`（`BLUEPRINT_EVENTS` 的 `len == 21` 双断言）：**为空** ✅
- `agents/call_source.py`（枚举清单锁）：**为空** ✅
- MCP 公共 handler 工厂：`git diff $PHASE_BASE --name-only | rg "knowledge_tools|handler_factory"` **为空** ✅
- `web/`：`git diff $PHASE_BASE --name-only | rg '^web/'` **零命中** ✅（前端零改动）
- 零 migration、零新依赖、零新 `CallSource` 枚举、零新事件常量：`makemigrations --check --dry-run` 退出码 **0** / `No changes detected`，`git status --porcelain 'server/*/migrations/'` **为空** ✅

### ⚠️ 另外改动了两个既有测试文件（守门跟随，非声明面）

| 文件 | 改的是什么 | 为什么必须改（Rule 3 阻塞） |
|---|---|---|
| `tests/mcp_tools/test_schema_snapshot.py` | `create_feishu_technical_plan` 条目追加三键 + 两条新工具条目 | `test_mcp_read_tool_schema_snapshot` 断言 `TOOL_SCHEMA_SNAPSHOT == {…完整字面量…}` ⇒ 不同步即转红。PLAN 只列了 `serializers.py` 侧的 snapshot，未计入测试侧那份**独立字面量副本**（该文件刻意不 import 常量，避免退化成自我比较） |
| `tests/mcp_tools/test_skills_snapshot_guard.py` | `_TOOL_TOKEN_RE` 动词前缀表追加 `answer` | `test_tool_token_prefixes_cover_all_snapshot_keys` 就是为「新前缀工具进 snapshot 时提醒扩前缀表」而设，报错文案逐字要求「请扩展前缀表」⇒ 这是该守卫的**预期动作**而非绕过 |

⛔ 无一条断言被削弱。

---

## 全量后端门（与基线逐条比对）

| | 基线（116-05 收口） | 本 plan 收口 | 差异 |
|---|---|---|---|
| passed | 8844 | **8916** | **+72** = 28 条 `test_blueprint_clarification_tools.py`（27 个 `def test_`，参数化展开）+ 29 条 `test_blueprint_assumptions_tiers.py`（22 个 `def test_`，参数化展开）+ 15 条 `test_blueprint_notify.py` |
| failed | 1 | **1** | **无新增失败** |

⚠️ **唯一失败逐条核对是同一条既有环境项**：`tests/mcp_tools/test_skills_snapshot_guard.py::test_skill_files_discovered`（本 worktree 的 `skills/` 是空目录，P-16）。本 plan 大量改动 `mcp_tools/`，特此显式登记它**与改动前是同一条**、⛔ 非本 plan 引入、⛔ 亦未尝试修它。

⚠️ 前哨提到的 `test_memory_mr_api` 排序 flake **本轮未出现**。

`ruff check` 对全部触及文件通过；`ruff format --check` 对全部触及文件通过（`mcp_tools/urls.py` 除外——见上方 ⚠️，它在基线即非 format-clean）。

## 事件目录（本 plan 新增）

| 事件名 | category | component | 关键字段 |
|---|---|---|---|
| `blueprint_thread_answer_completed` | caller | `blueprint_answer_action` | `artifact_id` / `thread_id` / `body_len` / `reflow_status` / `initiated_by_user_id` / `duration_ms` |
| `blueprint_answer_reflow_failed` | caller | `blueprint_answer_action` | `artifact_id` / `thread_id` / `error`（经 `_detail`） |
| `get_technical_blueprint_failed` | sampling | `mcp_tools` | `error`（经 `redact_secrets_in_text[:500]`） |
| `get_technical_blueprint_pending_unreadable` | caller | `mcp_tools` | `artifact_id` / `error` |
| `answer_blueprint_clarification_failed` | sampling | `mcp_tools` | `error` |
| `blueprint_assumptions_tier_unknown` | sampling | `process_runtime` | `tier` |
| `blueprint_assumptions_tiers_load_failed` | sampling | `process_runtime` | `tier` / `reason`（⛔ 不带异常文本） |
| `blueprint_clarification_card_sent` | caller | `blueprint_notify` | `artifact_id` / `session_id` / `question_count` / `recipient_count` / `chat_id` / `initiated_by_user_id` / `duration_ms` |
| `blueprint_clarification_card_failed` | caller | `blueprint_notify` | `artifact_id` / `session_id` / `error`（脱敏截断） |

⛔ **答案正文 / 澄清题正文 / 蓝图正文一律不进日志**（只记长度与条数）。`blueprint_ambiguity_score_completed` 新增 `assumptions_tier` 字段（标量）。两个新模块与模块创建**同 commit** 进 `_SCANNED_MODULES`（16 → 18）。

---

## ⭐ 存在性暴露口径分歧的登记（C5，与 116-05 同款）

本 plan 的两个 MCP 工具 **import 复用 `blueprint_review_views._aassert_project_scope`（含它的 400 分支）**，而 116-01 的 gate 链用的是更严变体（两个失败分支同一中性 404）。

**理由**：新端点走 400 变体是为**单一实现**（MJ-03，⛔ 不造第四份范围闸）——复制一份就是可漂移的副本，而这是**授权**判据。代价是 115-MN-03 的暴露面从 115 时的 **11** 个端点扩到 **15** 个：116-05 的两个导出端点 +2、本 plan 的两个 MCP 工具 +2。gate 链走 404 变体则是因为它的 404 本就混合三种语义、改 400 反而新开一种可区分状态。

⇒ **STATE 的 MN-03 Pending Todo 暴露面计数一次改到位：11 → 15**（116-05 有意未改、把两次合并到本 plan 的一次编辑里）。「四语义契约整体改版仍是独立工作项」的结论**保留不变**。

## ⭐ STATE 维护项（C6）：114-05 的「提醒渠道投递未实现」

STATE.md `:188` 那条 Pending Todo 原文是：

> `[Phase 114-05 有意边界] **提醒只到「记事件 + 写周期锚点」为止，渠道投递未实现**：…**用户收不到实际通知** ⇒ 115/116 接上通知面之前，CLAR-04 的用户可感知价值只兑现一半。收件人名单可经 BlueprintReviewer ∪ 蓝图会话发起人复算（⚠️ 反查会话必须带 process_type="technical_blueprint" 过滤）`

**结论：本 plan 关闭该条**（划掉并注明）。`blueprint_notify.anotify_blueprint_clarification` 落地了收敛的送达通道，收件人口径与该条描述的**逐字一致**（含 `process_type` 过滤），⭐ 并注明「同步点 1 后换 107 的送达设施只改这一个文件」。

⚠️ **残留半条如实登记**：本 plan 接的是**规格门开线程时的首次送达**；114-05 那条 **apscheduler 周期提醒**（`aremind_clarification_threads`）目前仍只写锚点、未调 `anotify_blueprint_clarification`。把周期提醒也接上是**一行调用**（且送达细节已收敛），但 `blueprint_review_action.py` **不在本 plan 的 `files_modified` 里** ⇒ 按相位边界纪律不改，登记为 116-07 / 里程碑收尾的顺手项。⇒ STATE 那条改为「首次送达已实装、周期提醒复用同一收口待接一行」。

---

## ⭐ 相位出口检查（B6）：116-07 的去留结论

**结论：`116-07` 纳入本相位执行，VIEW-02 由其闭合。**

理由：本里程碑正在被**自主驱动到完成**，116-07（VIEW-02 代码预览的源码正文读取面）是本相位唯一可独立顺延的 plan，但没有任何阻塞它的外部依赖（它不依赖同步点 1/2，也不依赖本 plan 的任何交付）。⇒ 下一步就执行它，`REQUIREMENTS.md` 的 VIEW-02 条目**无需改写**，其「若顺延则改写 VIEW-02」的escape clause 由「116-07 被执行」这一事实自然消解。

⚠️ **该义务的兜底口径**（供后来者）：若后续因不可抗力改判为顺延，改写 VIEW-02 顺延目标的动作**不能再指望 116-07 自己的验收去做**（它不执行就永远不会跑），必须由做出顺延决定的那一方在同一次改动里把 `REQUIREMENTS.md` 的顺延目标从 `116-07-PLAN.md` 改成**里程碑收尾的独立工作项**并提交 —— ⛔ 不得留下无主的「顺延 Phase 116」。

---

## ⭐ GATE-01 的最终完成度自评

本相位交付「**四入口实现路径 + per-entry 开关 + MCP 异步澄清协议**」：

- ✅ **四个入口都真的能走蓝图链**（116-03），改一个设置值即生效、回滚也是改一个设置值。
- ✅ **MCP 入口不再 skip_clarification**（本 plan）：`create_feishu_technical_plan` 立即返回 `status="partial"` + `blueprint_artifact_id` + pending 清单；`answer_blueprint_clarification` 可逐条作答并返回 `reflow`；`get_technical_blueprint` 可续取终稿（六段摘要 + 带「未经确认」标注的 markdown）。⭐ 既有工具名与 12 个响应键**一个都没改**，开关关闭时响应逐字与改动前相同。
- ✅ **作答通道只有一份实现**：REST 与 MCP 共享 `aanswer_thread`，三道闸的先后顺序有源码级断言；「对 finding 线程作答 ⇒ 400 且线程状态一字未变」把 114-CR-01 的对称面钉成事实。
- ✅ **assumptions 档位真的可运行时调**，且 `assume_more` 绝不等于跳过澄清（正反并列 + 源码零命中 + 实跑变异）。
- ✅ **CLAR-04 的另一半兑现**：澄清同时推飞书卡片，一处接线、单文件收敛。
- ⏭ **顺延同步点 2 的只剩四项**：默认切换（四键翻 `technical_blueprint`）、旧 `technical_plan` process 收口退役、三处触点升级、workflow 终态 `pending_review → waiting_event` 的 HITL 挂起（`plan_research._map_terminal` 至今一行未改——现在翻默认 = 让编码代理拿着未经人审的蓝图去建分支写代码，正面违反 RELY-01）。

---

## Deviations from Plan

### 1. [Rule 3 - 阻塞] `tests/mcp_tools/test_schema_snapshot.py` 与 `test_skills_snapshot_guard.py` 必须同步

- **Found during:** Task 2
- **Issue:** 两个守门测试都持有 snapshot 的**独立字面量副本 / 前缀表**，追加工具与响应键后立即转红。PLAN 的 `files_modified` 未列它们。
- **Fix:** 同步追加（见上表）。两处都是守卫的**预期动作**（`test_tool_token_prefixes_cover_all_snapshot_keys` 的报错文案逐字写着「请扩展前缀表」），⛔ 无断言被削弱。
- **Commit:** `229ce1da`

### 2. [Rule 1 - 顺序保真] View 保留一次 `is_blueprint_editable` 前置调用

见 §2 末尾的登记。若完全交给 service，「不可编辑 **且** 线程不存在」时状态码会从 400 漂成 404 —— 既有测试恰好没覆盖该组合，但那是对外契约的实质变化。选择保住顺序。

### 3. [登记] `aanswer_thread` 签名比 PLAN 多一个 `session`

纯追加、缺省 `None`。不透传会让回灌产出的版本丢掉 `produced_by_session_id`（既有 View 是传的）。

### 4. [登记] 状态键名与 PLAN 的字面提法不同

PLAN 在 `create_feishu_technical_plan` 处写的是追加 `blueprint_status`，同时给了「执行期二选一但两侧必须一致」的口子。实测该名字作**响应字典键**会命中 INV-6 的 `_RE_FIELD_DICT_KEY` ⇒ 两侧统一取 **`blueprint_current_status`**（snapshot 与 `technical_plan_service` 逐字一致）；`get_technical_blueprint` 用 `current_status`（与 114-05 立的既有解法同名）。

### 5. [登记] 一条验收断言按语义而非字面满足

| PLAN 的字面断言 | 实际形态 | 为什么等价或更强 |
|---|---|---|
| `assert 'blueprint_status"' not in src`（`blueprint_answer_action.py`） | 改为断言 INV-6 的**真实两条正则**在该文件零命中：`['\"]blueprint_status['\"]\s*:` 与 `\bblueprint_status\s*=\s*[^=]` | 字面判据会把**纯读**形态 `.values_list("blueprint_status", flat=True)` 也判为违规（重读状态是 PLAN 自己第 7 条要求的动作），而 INV-6 守卫的靶子是「绕过 CAS 改状态 / 拿字段名当响应键」。改用守卫本身的正则 ⇒ 判据与靶子对齐且**更严**（多覆盖了赋值形态）。权威核算是 `tests/delivery/test_blueprint_inv6_guard.py` 全绿 |

### 6. [登记] `work_item_context` 接线是**一处**不是 116-03 交接文说的三处

`mcp_tools/views.py:1925/2107` 的两处 delegate 调用属 `create_coding_plan` / `improve_coding_plan` 单仓编码方案面（`work_item=None`、无 `McpWorkItemContext`），蓝图入口只有 `create_feishu_technical_plan`。按实读收敛。

### 7. [登记] 三个删除行上界均低于 PLAN 预算，`urls.py` 踩过 formatter 噪声

见「受限面删除行逐行登记」的 ⚠️。

## Threat Flags

无。本 plan 新增的两个 MCP 端点已在 `<threat_model>` 内（T-116-48…T-116-51）并逐条配了用例；未引入威胁模型之外的网络端点 / 鉴权路径 / 文件访问形态 / 信任边界处的 schema 变更。飞书卡片是既有出站通道（analog `plan_research._send_clarify_card` 的同一条），题面经 `redact_secrets_in_text`，`action` 前缀未注册 ⇒ 不新增入站回调面。

## Known Stubs

两处**有意的**边界，均在上文逐条写明：

1. **澄清飞书卡片当前是通知形态**：`action="blueprint_clarify_answer"` 无注册 handler ⇒ 卡片上的提交按钮点了不会记答案（`CardCallbackView` warning 后优雅返回，⛔ 不 5xx、⛔ 不抢占既有路由）。作答的**三条通道都已实装**（REST / MCP / 查看器），卡片承担的是「有澄清待答」的可感知通知。接上交互回调属同步点 1 之后换 107 送达设施的同一批改动，⭐ **届时仍只改 `blueprint_notify.py` 一个文件**。
2. **apscheduler 周期提醒尚未复用该送达收口**（见 §「STATE 维护项」的残留半条）：一行调用，但 `blueprint_review_action.py` 不在本 plan 的 `files_modified` 里。

⛔ 两处都不阻碍本 plan 的目标（「MCP 入口不再 skip_clarification」已完整闭环）。

## Self-Check: PASSED

- 创建文件存在：`server/delivery/services/blueprint_answer_action.py`、`server/services/process_runtime/blueprint_notify.py`、`server/tests/mcp_tools/test_blueprint_clarification_tools.py`、`server/tests/services/process_runtime/test_blueprint_assumptions_tiers.py`、`server/tests/services/process_runtime/test_blueprint_notify.py`、`.planning/phases/116-entry/116-06-SUMMARY.md`。
- 三个实现提交 `77748479` / `229ce1da` / `0bae932b` 均在 `git log` 中。
- 四个变异备份（`/tmp/mut1_backup.py` … `/tmp/mut4_backup.py`）在仓库**之外**；变异全部恢复且复跑转绿。
- 分支 `milestone/v0.20.0-blueprint`，全程在 worktree `.claude/worktrees/v0.20-blueprint` 内作业，⛔ 未触碰主检出。
