---
phase: 116-entry
plan: 01
subsystem: process_runtime + delivery-api
requirements: [GATE-01]
tags: [engine-dispatch, entry-switch, gate-scope, observability, security]
requires: []
provides:
  - "build_engine_for_session（engine + driver 二元组分派器）"
  - "aresolve_entry_process_type（per-entry 运行时开关）"
  - "SettingKeys.BLUEPRINT_ENTRY_SWITCH / BLUEPRINT_ASSUMPTIONS_TIERS"
  - "start_orchestration 的 entry_key 形参与 technical_plan_entry_used 事件"
  - "_aassert_gate_scope（blueprint-gate 八端点项目范围闸）"
  - "confirm/ 两处 409 的 blocked_reason 键"
affects: [116-02, 116-03, 116-06]
tech-stack:
  added: []
  patterns: [lazy-import-config-read, type-identity-self-check, ast-source-scan-guard, neutral-404-scope-gate]
key-files:
  created:
    - server/services/process_runtime/blueprint_entry_switch.py
    - server/tests/services/process_runtime/test_blueprint_entry_switch.py
    - server/tests/services/process_runtime/test_engine_dispatch.py
    - server/tests/delivery/test_blueprint_gate_scope.py
  modified:
    - server/system/models.py
    - server/services/process_runtime/entrypoint.py
    - server/services/process_runtime/resume.py
    - server/services/process_runtime/builtin_processes.py
    - server/delivery/api/blueprint_gate_views.py
    - server/tests/delivery/test_blueprint_gate_api.py
decisions:
  - "分派器返回 (engine, driver) 二元组而非单个 engine —— 只换 engine 不换 driver 仍会把健康蓝图会话推成 advance_step_limit FAILED（已实测）"
  - "deps 自检的判据作用域限定在 services.process_runtime 自己拥有的类型（包内 allow-list），包外测试替身维持既有 pass-through"
  - "repo_research 补一条 needs_clarification 出边 —— 该 stage 原先没有，自检返回未登记 event 会 raise ValueError 打穿续驱器"
  - "gate 链范围闸用更严变体：两个失败分支回同一个 _GATE_NOT_OPEN_DETAIL 中性 404，⛔ 不复用 review 链那个带 400 分支的整体闸"
metrics:
  duration: "~2h"
  completed: 2026-08-01
---

# Phase 116 Plan 01: 分派闸 + per-entry 开关 + gate 范围闸 Summary

**One-liner:** 把 engine/driver 按 `process_type` 分派做成返回二元组的单一入口并给两个方向都加上 LOUD 守卫（三条变异用例各实跑一次真实变异背书），落地 per-entry 运行时开关与旧链退役观察事件，并给 `blueprint-gate/` 八端点（含三条破坏性写）补上零新增存在性暴露面的项目范围闸。

## PHASE_BASE

```
PHASE_BASE = 0e208ba93e1318e75bc98b5318f31e754edd608d
```

本相位后续六个 plan 各自开工时同样取一次自己的 base。本 plan 所有边界 / 删除行 / `--name-only` 断言一律写作 `git diff $PHASE_BASE -- <file>`，⛔ 无一条裸 `git diff`（GSD 逐 Task 原子提交后裸 `git diff` 恒空、断言会静默恒真）。

## Commits

| # | Hash | 内容 |
|---|---|---|
| 1 | `3afba499` | Task 1：两个 SettingKeys + `blueprint_entry_switch.py` + ast 字面量守卫及其守护的守护 |
| 2 | `ab9b42f7` | Task 2：`build_engine_for_session` + deps 类型身份自检 + resume 对称守卫 + `entry_key` 与退役观察 |
| 3 | `dd8c0f74` | Task 3：gate 八端点范围闸 + 两处 409 `blocked_reason` + 新测试文件 |

---

## ⭐ `build_engine_for_session` 的逐字签名与返回契约（116-03 直接照它改六个续驱点）

```python
def build_engine_for_session(
    session: Any,
    *,
    session_service: Any = None,
    node_execution_id: str = "",
    skip_clarification: bool = False,
    force_confirm: bool = False,
) -> tuple[ProcessEngine, Any]:
```

落在 `server/services/process_runtime/entrypoint.py`（engine 工厂唯一集中点纪律），**同步函数**（`inspect.iscoroutinefunction` 断言背书）。

调用形态：

```python
engine, adrive = build_engine_for_session(session)
session = await adrive(engine, session)          # 两个 driver 签名逐字相同，⛔ 无参数适配层
```

| `session.process_type` | 返回的 engine | 返回的 driver | 附带事件 |
|---|---|---|---|
| `technical_blueprint` | `build_blueprint_engine(session_service=…, node_execution_id=…)` | `blueprint_resume.adrive_blueprint_session_to_pause_or_terminal` | 传了非默认 `skip_clarification` / `force_confirm` 时每个各一条 `blueprint_engine_ignored_legacy_flag` |
| `technical_plan` / `echo` / `""` | `build_orchestration_engine(…全部四个形参透传…)` | `resume.adrive_convergence_session_to_pause_or_terminal` | 无 |
| 其它任意值 | 同上（**回落旧链，⛔ 不抛**） | 同上 | `engine_dispatch_unknown_process_type` |

硬契约三条：

1. **返二元组是硬要求**：旧续驱器的 `waiting_clarification` 短路判据是 `ClarificationService().ahas_pending`（`resume.py:53-57`），对蓝图会话恒 False ⇒ 只换 engine 不换 driver，健康会话会被推到 `max_steps` 落 `advance_step_limit` FAILED。**已实测**（见变异 C）。
2. ⛔ **绝不把 `skip_clarification` / `force_confirm` 透传进蓝图工厂**（`build_blueprint_engine` 只接两个形参、蓝图链没有 `clarify` dep）；传了只记事件、**响亮而不失败**。
3. **未知 `process_type` 不抛**：抛异常会让「将来注册第五个 process」的调用直接崩。

两个 driver 的签名实测逐字相同：`(engine, session, *, max_steps: int = 20)`。

---

## ⭐ Wave 0 探针的实测终局

**只动一个变量**：`build_orchestration_engine()`（**错工厂**）+ `blueprint_resume.adrive_blueprint_session_to_pause_or_terminal`（**对的 driver**），从 `intake` 驱一条 `technical_blueprint` 会话到底。

```
current_stage = 'reroute'
status        = 'failed'
error         = {'stage': 'reroute',
                 'exception': 'AttributeError',
                 'message': "'ResearchDispatchAdapter' object has no attribute 'aadvance_reroute'"}
```

**结论：与 RESEARCH §A.3 / Assumptions A1 的逐 stage 推演逐字吻合，假设 A1 就此解除。** 落点没有前移（`_h_bp_route` 取 `deps.route` 为 None ⇒ pass-through 不写 `routing`；`ResearchDispatchAdapter.dispatch` 对空 routing 返 `{"skipped": "no_candidates"}` 不抛；零 task 时 `aall_research_tasks_terminal` 返 True ⇒ 直进 `reroute` 撞 `AttributeError`）。

**变异用例 A 的期望值是否据此调整：否，无需调整。** 采用的判据落在白名单的 **(b) + (c)** 两条：

- (c) 出边是 `needs_clarification` **且**存在一条 `blueprint_stage_wrong_adapter`（`got == "ResearchDispatchAdapter"` / `stage == "repo_research"`）；
- (b) `ArtifactVersion.objects.acount()` 与调用前相等。

⛔ 全部判据都是正向白名单，无任何「不是 X」形态。

⚠️ **时效性（供后续 plan 判断能否复用该落点）**：本探针结论**只在 wave 1 成立**。116-02 落地后 `intake` / `decompose` 不再是空 handler pass-through，同样的错工厂会**更早**停下，落点会前移；届时若要复用需重跑探针。

---

## ⭐ 三条变异验证的红/绿实跑记录（各实跑一次真实变异）

| 变异 | 删了什么 | 转红的用例 | 错误首行 |
|---|---|---|---|
| **A** | `_h_bp_repo_research` 的 `_abp_dep_is_foreign_adapter` 分支 | `test_mutation_a_wrong_factory_at_repo_research_is_rejected` | `AssertionError: assert 'research_complete' == 'needs_clarification'` |
| **B** | `_h_bp_merge` 的 `_abp_dep_is_foreign_adapter` 分支 | `test_mutation_b_wrong_factory_at_merge_never_writes_a_v0_version` | `assert 0 == 1` （`len(_events(logs, "blueprint_stage_wrong_adapter")) == 0`） |
| **C** | `resume.py` 的对称守卫（改成 `if False and …`） | `test_mutation_c_wrong_driver_is_a_no_op_not_a_failure` | `assert 0 == 1` （`len(_events(logs, "wrong_driver_for_blueprint_session")) == 0`） |

三条恢复后全绿（`tests/services/process_runtime/ -q` → 671 passed）。

**变异 C 的终局另跑了一次探针坐实**（守卫禁用状态，从 `spec_gate` 驱一条健康蓝图会话）：

```
current_stage = 'spec_gate'
status        = 'failed'
error         = {'reason': 'advance_step_limit', 'steps': 21}
```

—— 与 RESEARCH「只换 engine 不换 driver 仍然坏」的第二把锁逐字吻合；该用例的 `(status, current_stage)` 逐字相等断言与 `error.reason != advance_step_limit` 断言在变异下**同样会翻**，不止事件那一条。

⚠️ **变异 B 的诚实登记**：在本用例的 fixture 下（阶段 1 形态蓝图、无 `PartialPlan`），去掉自检后 `ArchitectMergeAdapter.merge` 返回的是非 `passed` 状态、**并未真的落一份 v0 版本** ⇒ 翻红的是「事件存在」那一条，而不是 `ArtifactVersion` 计数那一条。计数与「全库无 `schema_version != blueprint/v1` 的版本」两条作为正向白名单守在原地（它们是 T-116-03 的真正靶心，只是在这个 fixture 下不是翻转位）。要让计数条成为翻转位需要装配一份完整的旧链 `stage_state`，成本远超收益，登记在此不做。

---

## per-entry 运行时开关

```python
async def aresolve_entry_process_type(entry: str) -> str
```

模块：`server/services/process_runtime/blueprint_entry_switch.py`。

| 常量 | 值 |
|---|---|
| `ENTRY_WORKFLOW` / `ENTRY_CHAT` / `ENTRY_MCP` / `ENTRY_FEATURE_LIST` | `"workflow"` / `"chat"` / `"mcp"` / `"feature_list"` |
| `ENTRY_KEYS` | 上面四个组成的 tuple |
| `PROCESS_TECHNICAL_PLAN` / `PROCESS_TECHNICAL_BLUEPRINT` | `"technical_plan"` / `"technical_blueprint"` |
| `DEFAULT_ENTRY_SWITCH` | **四键全 `"technical_plan"`**（安全默认：不配置 = 与切换前逐字等价） |

三层 fail-soft：未知 `entry` ⇒ `blueprint_entry_switch_unknown_entry`（caller）+ 回旧链；读设置整段异常 ⇒ `blueprint_entry_switch_load_failed`（sampling）+ 回旧链；内层值非法（`aget_json_setting` **只保证外层是 dict**）⇒ `blueprint_entry_switch_invalid_value`（sampling）+ 回旧链。模块内 **`error` 实参零命中**（刻意不进 `_SCANNED_MODULES`，与 analog `blueprint_ambiguity_score.py` 同口径），且 `session` 只出现在 docstring 纪律段（逐行人工核对：第 9 / 12 / 82 行，签名内零命中）。

### ⭐ 「实参必须是字面量」扫描器的覆盖面（116-03 新增调用点自动纳入）

扫描面 = `services/process_runtime/` 目录下全部 `*.py` **+** 四个入口文件：

- `workflows/nodes/ai/plan_research.py`
- `agents/tools/plan_research_tools.py`
- `mcp_tools/orchestration_delegate.py`
- `initiatives/services/feature_solution_service.py`

两条谓词（同一个扫描器 `_literal_violations`）：

1. `aresolve_entry_process_type` 的第一个位置实参（或 `entry=` keyword）必须 `isinstance(arg, ast.Constant) and isinstance(arg.value, str)`；
2. `start_orchestration` / `start_blueprint_orchestration` 上任何 `entry_key=` keyword 的值同样必须是字符串字面量（**无 `entry_key` keyword 不算违规** —— 默认空串是 116-03 之前的合法过渡态）。

**「守护的守护」**：合成源码里两条反面各一行（`aresolve_entry_process_type(session.entrypoint)` 与 `start_orchestration(..., entry_key=session.entrypoint)`），断言扫描器对两条**都**报违规且 `len(violations) == 2`；同一段合成源码里三条正面（字面量两条 + 无 `entry_key` 一条）不得被误报。

## 两个 SettingKeys（零 migration）

| 键名 | JSON 形状 | 默认值 |
|---|---|---|
| `blueprint.entry.switch` | `{"workflow"\|"chat"\|"mcp"\|"feature_list": "technical_plan"\|"technical_blueprint"}` | 未配置 ⇒ 四键全 `technical_plan` |
| `blueprint.assumptions_tiers` | `{"strict"\|"balanced"\|"assume_more": {"threshold": float, "max_rounds": int}}` | 默认档 `balanced`；未配置回落 `DEFAULT_SPEC_GATE_CONFIG` 的 threshold 与 `max_rounds=3`（**消费方由 116-06 落地**，本 plan 只声明键与形状注释） |

两键逐字照 `system/models.py:173-200` 的「常量 + JSON 形状注释 + 消费方文件名」体例；`makemigrations --check --dry-run` 退出码 0、`git status --porcelain server/*/migrations/` 为空。

## `technical_plan_entry_used`（旧链退役观察，供运维写聚合 SQL）

落在 `start_orchestration` 内部（四入口全经它建会话，**唯一能覆盖全部四个入口且不碰冻结文件**的位置）。字段：

| 字段 | 取值 |
|---|---|
| `category` | `"caller"` |
| `component` | `"process_runtime"` |
| `entry_key` | `str(entry_key or "unknown")` |
| `entrypoint` | `str(entrypoint or "")` |
| `initiated_by_user_id` | `str(initiated_by_user_id or "system")` |
| `session_id` | `str(session.id)` |

⭐ **必须按 `entry_key` 聚合，⛔ 不能按 `entrypoint`**：MCP 入口给 `start_orchestration` 传的 `entrypoint` 实测是 `"workflow"`（`mcp_tools/orchestration_delegate.py:171-178`，该文件 `:4` / `:131` 的 docstring 逐字写明这是既有约定而非笔误）⇒ 按 `entrypoint` 分桶会把 MCP 全部记进 workflow 桶，**静默且永不报错**。`entrypoint` 的既有取值一字未改（有用例断言）。

## `_aassert_gate_scope`（gate 链范围闸）

`server/delivery/api/blueprint_gate_views.py`，签名 `async def _aassert_gate_scope(request, artifact) -> Response | None`。四条语义：

1. `request.user.is_superuser` ⇒ `None`（直通）。
2. `_ablueprint_project_id(artifact)` 非 UUID / 读不到 ⇒ **中性 404**（⭐ 不是 400）。
3. 非 `_ais_project_member` ⇒ **同一个中性 404 常量对象**。
4. 放行 `None`。

**中性 404 常量的逐字文案**：复用本文件既有的

```python
_GATE_NOT_OPEN_DETAIL = {"detail": "确认门未开启"}
```

⛔ 不造第二个常量（少一份可漂移副本）。gate 链的 404 本就混合三种语义（门未开 / artifact 不存在 / 无蓝图会话），前端 115-07 按「非 200 只决定挂载点是否渲染、不进错误分档」实现 ⇒ **零新增存在性暴露面**，由 `assert a.json() == b.json()` 背书。

**为何不 import review 链那个整体范围闸（`blueprint_review_views:254-281`）**：它的 fail-closed 分支是 **400**，而那正是 115-MN-03 判为「设计决策、本轮不改」的存在性暴露面；import 会把它一次性扩到这八个端点上。本文件因此**只 import 一个零件** `_ais_project_member`（`blueprint_review_views:244-251`），import 行逐字为：

```python
from delivery.api.blueprint_review_views import _ais_project_member
```

`rg -n "_aassert_project_scope" server/delivery/api/blueprint_gate_views.py` **零命中**（连注释里的字面提及都已改写）。

**挂载点（判据只有一份、挂载点多处）**：

| 挂法 | View |
|---|---|
| 经 `_aapply_action` 内部一处生效 | `Confirm` / `RemoveRepo` / `AddRepo` / `ReclassifyRole` / `EditResponsibility` |
| View 内直挂 | `Snapshot` / `RejectedToBoundary` / `UpgradeResearch` |

`BlueprintRejectedToBoundaryView` 的既有 `_ablueprint_project_id` 单点调用**保留**，但它现在只推导**写入范围**、不再承担授权 —— 授权判据全文件只有 `_aassert_gate_scope` 一份（源码断言 `src.count("async def _aassert_gate_scope") == 1`）。其 400 分支对普通用户已不可达（闸先回中性 404），只剩 superuser 直通后会走到；已加注释说明。

## `confirm/` 两处 409 的 `blocked_reason` 取值表

| 位置 | 取值 | 对应前端既有用例 |
|---|---|---|
| 未决阻塞澄清线程分支 | 字面量 `"pending_clarification"` | `web/src/components/blueprint/__tests__/gatePanel.spec.ts:577`（出现「前往未决线程」并 emit `goto-unresolved`） |
| `alock` 未落锁分支 | `str(lock.get("reason") or "")` **原样透传**（`snapshot_changed` / `pending_research` 等） | `gatePanel.spec.ts:591`（其余取值只回显 detail） |

**前端零改动**：`git diff $PHASE_BASE --name-only | rg "^web/"` 零命中；`pnpm exec vitest run src/components/blueprint/__tests__/gatePanel.spec.ts` → 22 passed。

---

## 受限面删除行逐行登记

| 文件 | 上界 | 实际 | 删掉的行 |
|---|---|---|---|
| `server/system/models.py` | 0 | **0** | — |
| `server/services/process_runtime/builtin_processes.py` | 0 | **0** | — |
| `server/services/process_runtime/resume.py` | 0 | **0** | — |
| `server/services/process_runtime/entrypoint.py` | 2 | **1** | `    return await ConvergenceSessionService().create_session(`（改为先接 `session =` 再 `return session`，为退役观察事件让位） |
| `server/delivery/api/blueprint_gate_views.py` | 6 | **2** | `            return Response({"detail": "存在未解决的阻塞澄清线程"}, status=status.HTTP_409_CONFLICT)`（单行 Response 展开成多行以补键）；`                    )`（第二处 409 的 `Response({...})` 重排） |

## 冻结面核算

- 六个 technical_plan 冻结文件（`decompose_segments.py` / `research_adapter.py` / `architect_merge_adapter.py` / `merged_plan.py` / `clarify_adapter.py` / `render.py`）：`git diff $PHASE_BASE --name-only | rg …` **零命中**。
- `server/codegraph/services/repo_router_v2.py`：`git diff $PHASE_BASE -- …` **输出为空**。
- `web/`：**零命中**。
- `register_process_type("technical_plan", …)` **仍在注册**（在途会话续驱依赖它，注销即崩），注册项上方已加三行退役观察注释。
- 零新增 migration、零新依赖、零新 `CallSource` 枚举、`BLUEPRINT_EVENTS` 未动。

## 全量后端门（与基线逐条比对）

| | 基线 | 本 plan 收口 | 差异 |
|---|---|---|---|
| passed | 8609 | **8671** | **+62**（25 `test_blueprint_entry_switch` + 12 `test_engine_dispatch` + 25 `test_blueprint_gate_scope`） |
| failed | 1 | **1** | **无新增失败** —— 唯一失败仍是 `tests/mcp_tools/test_skills_snapshot_guard.py::test_skill_files_discovered`（本 worktree `skills/` 为空目录的环境产物，⛔ 不属本相位） |

`uv run python manage.py makemigrations --check --dry-run` 退出码 **0**；`git status --porcelain server/delivery/migrations/ server/system/migrations/` **为空**。
`ruff check` / `ruff format --check` 对全部触及文件通过。

---

## Deviations from Plan

### 1. [Rule 3 - 阻塞] `repo_research` 补一条 `needs_clarification` 出边

- **Found during:** Task 2 ③（写 `_h_bp_repo_research` 自检时）
- **Issue:** 计划要求自检返回「`needs_clarification` 出边的 `StageOutcome`」，但 `_TECHNICAL_BLUEPRINT_STAGES["repo_research"].transitions` **原先只有 `research_dispatched` / `research_complete` 两条**（`merge` 有 `needs_clarification` 自环，`repo_research` 没有）。返回未登记 event 会让 `ConvergenceSessionService.transition` 直接 `raise ValueError`，而该异常在 `ProcessEngine.advance` 的 handler `try` 块**之外** ⇒ 会冲出续驱器打穿 REST / 回调链。
- **Fix:** 给该 StageDef 追加一行 `"needs_clarification": "repo_research"`（自环，`wait_status` 沿用 `waiting_event`），并加注释写明理由。**删除行仍为 0**；蓝图链「零 failed 出边」不变量不受影响；`test_blueprint_process_graph.py` 只对**旧链** transitions 做逐字快照，蓝图侧只校验可达性与目标合法性，全绿。
- **Files:** `server/services/process_runtime/builtin_processes.py`
- **Commit:** `ab9b42f7`

### 2. [Rule 4→自主决断] deps 自检的判据作用域限定在 `services.process_runtime` 自己拥有的类型

- **Found during:** Task 2 ③
- **Issue:** 计划要求「`deps.merge` 若不是 `BlueprintMergeAdapter` 实例即拒」的严格 allow-list。但既有的十条 handler 用例（`test_blueprint_merge_gate.py` 的 `_engine(merge=SimpleNamespace(merge=AsyncMock(...)))` 等）注入的是鸭子类型替身 —— 严格 allow-list 会把它们全部拒掉，而那些文件在本 plan 声明的九个文件之外、按相位边界纪律不得改动。
- **Fix:** 判据仍是**类型身份**（`type(dep).__module__` + `__name__`，⛔ 不是方法探测），但只在 dep 的类型**属于 `services.process_runtime` 包**时生效：包内任何「不是本 stage 期望的那个 adapter」一律拒（含将来新增的第三个 adapter —— 比两项黑名单更严），包外对象（`types.SimpleNamespace` / `unittest.mock.AsyncMock`）维持既有 pass-through 语义。两个真实靶子 `ResearchDispatchAdapter`（`services.process_runtime.research_adapter`）与 `ArchitectMergeAdapter`（`services.process_runtime.architect_merge_adapter`）都在包内 ⇒ T-116-03 完整闭合，变异 A/B 均转红背书。
- **Files:** `server/services/process_runtime/builtin_processes.py`（`_abp_dep_is` / `_abp_dep_is_foreign_adapter`）
- **Commit:** `ab9b42f7`

### 3. [Rule 3 - 阻塞] 修改了第十个文件 `server/tests/delivery/test_blueprint_gate_api.py`

- **Found during:** Task 3 ②
- **Issue:** 补上 fail-closed 的范围闸后，该文件 **37 / 53 条用例转红** —— 样例蓝图的 `meta.project_id` 默认是 `"proj-0001"`（非 UUID，见 `tests/helpers/blueprint_samples.py:41`）、且测试 `user` 不是任何项目成员 ⇒ 全部被中性 404 挡在服务之前。这是「给八端点补范围闸」的**必然连带**，不是回归。plan 的 `files_modified` 只声明九个文件，故「边界只含九文件」这条验收断言无法同时满足。
- **Fix:** 按 114-05 给人审七端点补闸时的**同款处置**（`test_blueprint_review_views.py:83-110` 的 `_SCOPE_PROJECT_ID` / `_make_project` / autouse `_project_scope`）做最小改动：① 加 `_SCOPE_PROJECT_ID` + `_make_project` + autouse `_project_scope(user)`；② `_stage1_blueprint()` 把 `meta.project_id` 指向该 project；③ `_bind_blueprint_project(..., member=user)` 在重指项目后一并授予成员；④ `test_rejected_to_boundary_requires_scope` 的期望由 **400 → 404**（这正是更严变体的**预期语义变化**，已在该用例 docstring 里写明理由）。改完 53 条全绿，⛔ 无一条断言被削弱。
- **备选与否决理由:** 「project_id 读不到时放行」可保住那 37 条且不碰该文件，但会让无 `meta.project_id` 的蓝图对任意登录用户完全敞开（正是 T-116-01），且与 Task 3 第 2 条「两个失败分支响应体逐字相同」直接冲突 ⇒ 否决。
- **Files:** `server/tests/delivery/test_blueprint_gate_api.py`
- **Commit:** `dd8c0f74`

### 4. [登记] 两条源码计数型验收断言按语义而非字面满足

- `builtin_processes.py` 的 `src.count('blueprint_stage_wrong_adapter') >= 2`：事件的 **emit 点只有一处**（共享 helper `_abp_reject_wrong_adapter`，避免两份漂移），两个 handler 各自的调用点以注释逐字点名该事件 ⇒ 计数与语义（两个 handler 都覆盖）同时成立；真正的覆盖证据是变异 A/B 分别断言 `stage == "repo_research"` / `"merge"`。
- `rg -c "blocked_reason" blueprint_gate_views.py == 2`：该文件**改动前**就已有一处 `result.get("blocked_reason")`（读 service 返回值），本 plan 新增的是**两个响应键** ⇒ 实际计数为 **3**，字面 `== 2` 不可达。两个响应键的取值由 `test_blueprint_gate_scope.py` 的两条行为用例逐字背书。

### 5. [登记] 变异 B 的翻转位

见上文「三条变异验证」的 ⚠️ 段：翻红的是事件断言而非 `ArtifactVersion` 计数断言。

## Threat Flags

无。本 plan 未引入 `<threat_model>` 之外的新网络端点 / 鉴权路径 / 文件访问形态 / 信任边界处的 schema 变更；`blueprint-gate/` 八端点的攻击面是**收窄**而非扩大，且两个失败分支不可区分。

## Known Stubs

无。`BLUEPRINT_ASSUMPTIONS_TIERS` 是**有意的纯声明**（计划明确「本 plan 只声明键与形状注释，消费方由 116-06 落地」），已在 `system/models.py` 的注释里逐字写明消费方与相位。

## Self-Check: PASSED

- 创建文件全部存在：`blueprint_entry_switch.py` / `test_blueprint_entry_switch.py` / `test_engine_dispatch.py` / `test_blueprint_gate_scope.py`。
- 三个提交 `3afba499` / `ab9b42f7` / `dd8c0f74` 均在 `git log` 中。
- 两个一次性探针文件（`test_wave0_probe_tmp.py` / `test_probe_c_tmp.py`）已删除，`git status` 无残留。
