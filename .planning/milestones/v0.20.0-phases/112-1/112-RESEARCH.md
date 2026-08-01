# Phase 112: 规格门与双面路由（阶段 1） - Research（编排面契约）

**Researched:** 2026-07-30
**Domain:** process_runtime stage graph 编排面 / blueprint schema 演进 / SystemSetting 运行时配置
**Confidence:** HIGH（全部结论来自本 worktree 代码直读，附文件:行号）

## Scope Note

本文档**只覆盖 4 个编排面主题**：stage graph 契约、`ProcessEngine.advance` 契约、`blueprint_schema` 加必填 `intent` 的影响面、`SystemSetting` 键注册与读取。
analog 模块结构要点（`research_adapter` / `decompose_segments` / `repo_router_v2` 的内部范式）已由 `112-PATTERNS.md` 覆盖，**本文不重复**。

所有路径相对 worktree 根 `/Users/zaneliu/Projects/open-source/friday-clean/.claude/worktrees/v0.20-blueprint`。

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions（与本文 4 主题直接相关的子集）
- `builtin_processes.py` 新增 `technical_blueprint` process 注册项（**仅加字典项**，不动既有 `technical_plan` stage graph）——`112-CONTEXT.md:52`
- 本相位 stage 骨架：`intake → decompose → spec_gate(pausable) → route → repo_research(pausable) → reroute → repo_confirmation(pausable)`；`repo_plan / merge` 由 Phase 113 接续注册——`112-CONTEXT.md:53`
- 状态映射：阶段 0/1 全程蓝图状态 = `researching`；有 open+blocking 线程时派生显示 `needs_clarification`（记 `return_stage`），一律经 `BlueprintLifecycleService`——`112-CONTEXT.md:54`
- reroute 上界 ≤2 轮，**计数存 `ConvergenceSession.stage_state`**——`112-CONTEXT.md:42`
- 歧义阈值与四维权重**外置到 `SystemSetting`**（运行时可调，默认总分阈值 0.20），镜像 v0.19.0 权重外置做法——`112-CONTEXT.md:25`
- `intent` 落位 = `blueprint_schema` 的 `feature_points[]` 补**必填枚举**字段 `intent: greenfield | brownfield | fix`（schema 演进，既有测试样例工厂同步补字段）——`112-CONTEXT.md:28`

### Claude's Discretion
- 各 adapter 内部函数切分、prompt 措辞、breakdown 字段命名细节、REST 序列化器组织、测试组织结构自行决定，遵循 CONVENTIONS.md 与 Phase 111 已建立的 `blueprint_*` 模块风格（`112-CONTEXT.md:58`）。

### Deferred Ideas（OUT OF SCOPE）
- 容器 MCP 白名单扩 charter/context 工具 → Phase 113
- charter_match 权重自动调参 → Future Requirements
- 确认门前端 UI → Phase 115
</user_constraints>

## Project Constraints (from .cursor/rules/)

`.cursor/rules/observability-logging.mdc` 对本相位新增 stage handler / adapter / REST 的强制要求（编排面相关部分）：
- 用 `structlog.get_logger(__name__)`，事件名 snake_case（`xxx_started/completed/failed`），字段用 kv。
- **每条事件必须带 `category`（`caller` | `sampling`）+ `component`**。既有 `builtin_processes.py` handler 全部走 `category="sampling", component="process_runtime"`（`builtin_processes.py:67-72`、`89-94`）——新 stage handler 照此。
- 观测代码 best-effort，绝不反噬业务；高频循环禁 INFO 刷屏。
- 新增 LLM 调用点须赋 `call_source`（`spec_gate` 用 `blueprint_spec_gate`，已在 `server/agents/call_source.py` 注册，`call_source.py:110-111` 注明「调用点在 112 落地」）。

---

## 主题 1：stage graph 契约

### 1.1 `StageDef` 的确切数据结构

定义在 **`server/services/process_runtime/registry.py:33-44`**（`@dataclass(frozen=True)`）：

```python
@dataclass(frozen=True)
class StageDef:
    key: str                                          # registry.py:36
    handler: StageHandler                             # registry.py:37
    transitions: dict[str, str] = field(default_factory=dict)   # registry.py:40
    pausable: bool = False                            # registry.py:42
    wait_status: str = "waiting_event"                # registry.py:44
```

字段语义（`registry.py:6-8`、`39-44`）：

| 字段 | 类型 | 取值语义 |
|------|------|----------|
| `key` | `str` | stage 自身 key；**必须等于 `stages` dict 的键**（`_TECHNICAL_PLAN_STAGES` 全部如此，`builtin_processes.py:208-251`） |
| `handler` | `StageHandler` | `Callable[[Any, ProcessEngine], Awaitable[StageOutcome]]`（`registry.py:26`） |
| `transitions` | `dict[event, target]` | target ∈ `{另一 stage key, 自身 key(self-loop), STAGE_DONE, STAGE_FAILED}`；**event 不在表内 → `transition` 抛 `ValueError`**（`convergence_session_service.py:157-162`） |
| `pausable` | `bool` | 仅影响 **self-loop**（`target == from_stage`）时的 status：`True` → `wait_status`；`False` → `RUNNING`（`convergence_session_service.py:168-174`） |
| `wait_status` | `str` | self-loop 挂起时写入 `session.status`；实际取值须 ∈ `ConvergenceSessionStatus`（`waiting_clarification` / `waiting_event`，见 1.4） |

终态哨兵（`registry.py:29-30`）：`STAGE_DONE = "__done__"`、`STAGE_FAILED = "__failed__"`。

### 1.2 `_TECHNICAL_PLAN_STAGES` 逐 stage 实态

`builtin_processes.py:207-252`。**只读参考，本相位不动**（`112-CONTEXT.md:52`）：

| stage | 行号 | transitions | pausable | wait_status |
|-------|------|-------------|----------|-------------|
| `decompose` | 208-212 | `{decomposed: route}` | — | — |
| `route` | 213-217 | `{routed: recall}` | — | — |
| `recall` | 218-222 | `{recalled: classify}` | — | — |
| `classify` | 223-227 | `{classified: clarify}` | — | — |
| `clarify` | 228-234 | `{clarified: research, needs_clarification: clarify}` | `True` | `"waiting_clarification"` |
| `research` | 235-241 | `{research_dispatched: research, research_complete: merge}` | `True` | `"waiting_event"` |
| `merge` | 242-251 | `{merged: __done__, validation_failed_reclarify: clarify, validation_failed_reresearch: research, exhausted: __failed__}` | — | — |

**pausable 的实现事实：挂起 = handler 返回 self-loop event。** `clarify` 用 `needs_clarification → clarify`（`builtin_processes.py:231`），`research` 用 `research_dispatched → research`（`:238`）。handler 自己**不**写 status。

### 1.3 handler 函数签名与返回类型

签名（`registry.py:26`，实例见 `builtin_processes.py:45`、`107`、`169`）：

```python
async def _h_xxx(session: Any, engine: Any) -> StageOutcome
```

`StageOutcome` 定义在 **`server/services/process_runtime/engine.py:33-46`**：

| 字段 | 行号 | 类型 | 语义 |
|------|------|------|------|
| `event` | `engine.py:43` | `str`（必填） | 查 `StageDef.transitions` 的 key |
| `stage_state_update` | `engine.py:44` | `dict \| None` | **浅合并**进 `session.stage_state`；`None` 不改（`engine.py:103-105`） |
| `current_artifact_version` | `engine.py:45` | `Any = None` | 本步产出的 `ArtifactVersion` id |
| `error` | `engine.py:46` | `dict \| None` | 仅 `__failed__` 路径写入（见 2.4） |

四种典型返回形（可直接照抄）：
- 纯转移：`StageOutcome(event="classified")` —— `builtin_processes.py:143`
- 带 state：`StageOutcome(event="routed", stage_state_update={"routing": result})` —— `:117`
- 带产物：`StageOutcome(event="merged", current_artifact_version=result.get("artifact_version_id"))` —— `:186-189`
- 带 error 落 failed：`StageOutcome(event="exhausted", error={"stage": "merge", "reason": ..., "report": ...})` —— `:191-198`

### 1.4 process 注册入口函数名与新增 process 的确切位置

- 注册函数：**`register_process_type(definition: ProcessDefinition)`**，定义 `registry.py:95-97`；导入路径 `from services.process_runtime.registry import register_process_type`（`builtin_processes.py:28-34`）。
- 查询函数：`get_process_definition(process_type)`（`registry.py:100-101`）；`ProcessDefinition.stage(key)`（`registry.py:58-59`）。
- `ProcessDefinition` 字段（`registry.py:47-56`）：`process_type` / `artifact_type` / `initial_stage` / `stages: dict[str, StageDef]` / `config: dict = {}`（流程级配置，handler 自取）。
- **惰性注册机制**：`ProcessTypeRegistry._ensure_builtins()`（`registry.py:87-92`）在首次 `get/is_registered/registered_types` 时 `import services.process_runtime.builtin_processes`（顶层 side-effect 注册）。**新 process 必须写在 `builtin_processes.py` 顶层**，否则不会被惰性导入触发。

**新增一个 process 需要动的确切位置（`server/services/process_runtime/builtin_processes.py`）：**

| 动作 | 位置 |
|------|------|
| 新 stage handler 函数（7 个 `_h_bp_*`） | 追加在 `_ECHO_STAGES`（:295-301）之后、`# === registration ===`（:304）之前；或独立新文件后在 `builtin_processes.py` import（顶层） |
| 新 `_TECHNICAL_BLUEPRINT_STAGES` dict | 同上区段（**不要插入 `_TECHNICAL_PLAN_STAGES` 内部，:207-252 冻结**） |
| `register_process_type(ProcessDefinition(...))` 第三次调用 | 追加在 **`builtin_processes.py:322` 之后**（现有两次调用：`:306-313` technical_plan、`:315-322` echo） |
| `artifact_type` | 复用 Phase 111 的 blueprint artifact type（校验入口 `server/delivery/artifacts/builtin_types.py:23-25`，content 带 `schema_version == "blueprint/v1"` 即改走 `validate_blueprint`） |

模块 docstring（`builtin_processes.py:1-13`）声明「注册两个 ProcessDefinition」——新增第三个时须同步改 docstring（否则文档与实态背离）。

### 1.5 CONTEXT 锁定骨架 → 契约映射（供 planner 直接落 StageDef）

依 `112-CONTEXT.md:53-54` + 上表机制，`technical_blueprint` 的 `initial_stage="intake"`，transitions 形如：

| stage | transitions（建议） | pausable | wait_status |
|-------|--------------------|----------|-------------|
| `intake` | `{intaken: decompose}` | — | — |
| `decompose` | `{decomposed: spec_gate}` | — | — |
| `spec_gate` | `{spec_locked: route, needs_clarification: spec_gate}` | `True` | `waiting_clarification` |
| `route` | `{routed: repo_research}` | — | — |
| `repo_research` | `{research_dispatched: repo_research, research_complete: reroute}` | `True` | `waiting_event` |
| `reroute` | `{reroute_needed: repo_research, converged: repo_confirmation, exhausted: repo_confirmation}` | — | — |
| `repo_confirmation` | `{awaiting_confirmation: repo_confirmation, confirmed: __done__}`（113 接续时改为 `repo_plan`） | `True` | `waiting_clarification` |

关键约束（源自机制而非偏好）：
- **reroute 不收敛不能落 `__failed__`**（`112-CONTEXT.md:42`「绝不静默失败」）→ `exhausted` 必须指向 `repo_confirmation` 而非 `STAGE_FAILED`。
- reroute 轮次计数写 `stage_state`（`StageOutcome.stage_state_update`），engine 负责持久化（见 2.2）。
- 113 接续只需把 `repo_confirmation.transitions["confirmed"]` 从 `__done__` 改成 `"repo_plan"` 并加两个 StageDef——transitions 是数据，无需改 engine。

---

## 主题 2：`ProcessEngine.advance` 契约

文件 **`server/services/process_runtime/engine.py`**。

### 2.1 签名与构造

```python
class ProcessEngine:                                              # engine.py:49
    def __init__(self, *, session_service: Any = None, deps: Any = None) -> None   # engine.py:52
    async def advance(self, session: Any) -> Any                  # engine.py:59
```

- `session_service` 缺省 `ConvergenceSessionService()`（`engine.py:53-55`）。
- `deps` 是**任意 namespace**（`engine.py:56-57`），handler 自取：`engine.deps.router.route(session)`（`:109`）、`engine.deps.recall.recall`（`:122`）、`engine.deps.clarify.clarify`（`:164`）、`engine.deps.research.dispatch`（`:173`）、`engine.deps.merge.merge`（`:181`）。**软取范式**（旧构造兼容）：`getattr(getattr(engine, "deps", None), "classify", None)`（`builtin_processes.py:145-147`）——新 adapter 注入照此，缺失即 pass-through 不报错。
- `advance` 返回**传入的同一 session 对象**（内存态已被 `_apply_transition_sync` 同步，见 2.2），不 re-fetch；`resume.py:67` 由调用方 `ConvergenceSession.objects.aget(id=...)` 重读。

### 2.2 `stage_state` 的读写方式与持久化责任

- **读**：handler 直接读 `session.stage_state`（`builtin_processes.py:277`）或 `session.decomposition`（`:57`、`:141`）。
- **写**：handler **只返回增量** `StageOutcome.stage_state_update`；engine 做浅合并：
  ```python
  merged_state = {**(session.stage_state or {}), **outcome.stage_state_update}   # engine.py:103-105
  ```
  → 顶层 key 级覆盖，**嵌套 dict 不深合并**（reroute 计数器等嵌套结构须 handler 自己读旧值再整段回写）。
- **持久化责任 = `ConvergenceSessionService.transition`**（engine 只传参，`engine.py:110-116`）。engine **绝不直接 mutate** `session.status` / `current_stage`（`engine.py:5-6`、`registry.py` 同调；`resume.py:8-9` 称 INV-6「engine 纯度」）。
- 落库为 **CAS 更新**：`_apply_transition_sync`（`convergence_session_service.py:191-237`）以 `filter(id=session.id, current_stage=from_stage).update(...)` 为前置条件（`:219-221`），`updated != 1` 抛 `ConcurrentTransitionError`（`:222-227`）；成功后回写内存态（`:228-237`）。
- `stage_state is None` → **不进 update_values**（`:210-211`），即「不改」而非清空。

`transition` 签名（`convergence_session_service.py:126-135`）：

```python
async def transition(self, session, event, *, stage_state=None,
                     current_artifact_version=_UNSET, error=None, event_time=None) -> ConvergenceSession
```

### 2.3 pause 如何表达

三层协同，**没有任何一层直接写 status**：

1. handler 返回 **self-loop event**（`transitions[event] == 自身 key`）。
2. `transition` 判 `target == from_stage` → status 取 `stage_def.wait_status if stage_def.pausable else RUNNING`（`convergence_session_service.py:168-174`）。
3. 驱动 helper `adrive_convergence_session_to_pause_or_terminal(engine, session, *, max_steps=20)`（`resume.py:23-25`）**据 status 短路**：
   - `WAITING_CLARIFICATION` 且 `ClarificationService().ahas_pending(session.id)` → 直接 return（`resume.py:52-57`）
   - `WAITING_EVENT` 且 `not await aall_research_tasks_terminal(session.id)` → 直接 return（`resume.py:59-64`）
   - 循环 `engine.advance` + `aget` 重读（`resume.py:66-67`）

⚠️ **对本相位的硬约束**：`resume.py` 的两个短路判据写死在 helper 里，分别绑 `ClarificationService`（`resume.py:37`、`55`）与 `aall_research_tasks_terminal`（`:38`、`62`）。本相位澄清载体是 `BlueprintThread(blocking=true)` 而非 `delivery.Clarification`（`112-CONTEXT.md:26`）——若复用 `resume.py`，`spec_gate` / `repo_confirmation` 的 `waiting_clarification` 短路**判据不匹配**（`ahas_pending` 查不到 blueprint 线程 → 不短路 → 继续 advance → 再次 self-loop，靠 `max_steps=20` 兜底为 fail）。planner 须显式决策：(a) 新写 blueprint 专用 drive helper（推荐：不动冻结面），或 (b) 由调用方单步 `engine.advance` 不用 helper。

### 2.4 失败如何表达（三条路径）

| 路径 | 触发 | 落库方式 | 行号 |
|------|------|----------|------|
| handler 抛异常 | 除 `NotImplementedError` 外任意 `Exception` | engine 捕获 → `transition(session, "fail", error={"stage", "exception", "message"})` | `engine.py:94-101` |
| handler 显式失败 | 返回 `event` 映射到 `STAGE_FAILED` + `error=` | `transition` 写 status=`failed` + `error`（**仅 `target == STAGE_FAILED` 时才落 error**，`:185`） | `builtin_processes.py:190-198` / `convergence_session_service.py:166-167,185` |
| 步数超限 | `resume.py` 步数 > `max_steps` | `transition(session, "fail", error={"reason": "advance_step_limit", "steps": steps})` | `resume.py:44-50` |

- `event == "fail"` 是**特判旁路**：不查 transitions，任意非终态 stage → `failed`（`convergence_session_service.py:141-142`，`_fail` 在 `:239-259`）。终态再 fail 为**幂等 no-op**（保留首因，`:247-258`）。
- `NotImplementedError` **原样上抛**（`engine.py:92-93`）——开发期显式暴露未接入 stage，本相位骨架 stage 可用它做占位。
- `ConcurrentTransitionError` 被 engine 吞掉并记 `sampling` 日志（`engine.py:117-126`），**绝不落 fail**（否则覆盖并发正确推进的状态）。

### 2.5 terminal 哨兵值（两套，勿混）

| 层 | 常量 | 取值 | 位置 |
|----|------|------|------|
| stage graph transitions 目标 | `STAGE_DONE` / `STAGE_FAILED` | `"__done__"` / `"__failed__"` | `registry.py:29-30` |
| session 运行时态 | `_TERMINAL = {ConvergenceSessionStatus.DONE, ConvergenceSessionStatus.FAILED}` | `"done"` / `"failed"` | `engine.py:30` |

- `advance` **入口即短路**：`if session.status in _TERMINAL: return session`（`engine.py:68-69`）。
- 落终态时 **`current_stage` 保持 `from_stage` 不变**（`convergence_session_service.py:164-167`）——终态由 status 表达，stage 保留出错/完成现场。
- `ConvergenceSessionStatus` 全枚举（`server/delivery/models/convergence_session.py:30-38`）：`created` / `running` / `waiting_clarification` / `waiting_event` / `done` / `failed`。**`wait_status` 只能取 `waiting_clarification` 或 `waiting_event` 两值**（本相位三个 pausable stage 须复用其一，不新增状态值）。
- 前置守卫：`definition is None` → fail `{"reason": "unknown_process_type", ...}`（`engine.py:71-78`）；`stage_def is None` → fail `{"reason": "unknown_stage", ...}`（`engine.py:81-88`）。

---

## 主题 3：`blueprint_schema` 加必填 `intent` 字段的影响面

### 3.1 `feature_points` schema 现状

**`server/services/process_runtime/blueprint_schema.py:173-209`**（`requirement_spec.properties.feature_points`）：

```python
"feature_points": {                                   # :173
    "type": "array",
    "items": {
        "type": "object",
        "required": ["id", "title"],                  # :178  ← 加 "intent" 的确切位置
        "properties": {
            "id":                  {...minLength: 1}, # :180-184
            "title":               {...minLength: 1}, # :185-189
            "description":         {"$ref": "#/$defs/block_list"},  # :190-193
            "source_ref":          {"type": "string"},              # :194-197
            "acceptance_criteria": {"type": "array", items str},    # :198-202
            "test_cases":          {"type": "array"},               # :203-206
        },
    },
},
```

相关事实：
- `requirement_spec.required = ["goal", "feature_points"]`（`:169`）。
- **`additionalProperties` 全局保持默认允许**（`:40` 注释「保持默认允许（兼容演进）」；全文仅 `:743` citations pool 用到）→ 加 `intent` 到 `properties` 不会连带拒绝其他字段；但加进 `required`（`:178`）就是**破坏性演进**。
- `intent` 字段**当前不存在**（`rg -n "intent" blueprint_schema.py blueprint_samples.py` 无匹配）。
- **生产侧尚无 feature_points 写入方**：`server/agents/call_source.py:110-111` 明确「v0.20.0 Phase 112：……feature_points（调用点在 112 落地）」。故加必填字段**只影响测试数据与 fixture，不影响任何现存生产写入路径**。
- 后置检查对 feature_points 的两处依赖（与 `intent` 无关，加字段不受影响）：id 唯一性（`:886-900`，label `"requirement_spec.feature_points"`）、`items[].feature_point_id` 可解析性（`:823-840`）。
- `iter_blocks` 只走 `fp["description"]`（`:940-947`），路径形 `requirement_spec.feature_points[fp_01].description`——`intent` 是标量，不进 block 走查。

### 3.2 `make_blueprint` 工厂现状

`server/tests/helpers/blueprint_samples.py`：
- `_BASE_BLUEPRINT["requirement_spec"]["feature_points"]` = **2 条**（`fp_01` :49-54、`fp_02` :55-60），字段集 = `id / title / description / acceptance_criteria`（**无 `source_ref`、无 `intent`**）。
- 工厂：`def make_blueprint(**overrides) -> dict`（`:352-356`）—— `copy.deepcopy(_BASE_BLUEPRINT)` + `blueprint.update(overrides)`，**overrides 只浅覆盖顶层 key**（`:12`、`:353`）。即 `make_blueprint(requirement_spec=...)` 会整段替换，无法只补 `intent`。
- 导出 `__all__ = ["make_blueprint"]`（`:20`）。

### 3.3 需要同步修改的文件清单（rg 全量核查结果）

**必须改（内含 feature_points 字面数据）——共 2 个文件：**

| # | 文件 | 位置 | 需补 intent 的条目 |
|---|------|------|--------------------|
| 1 | `server/tests/helpers/blueprint_samples.py` | `:48-61` | `fp_01`（后端接口 → `greenfield`）、`fp_02`（前端入口 → `greenfield`） |
| 2 | `server/tests/fixtures/blueprint_golden/gaokao_boost.json` | `:34-...` | `fp_01`（描述自称 brownfield，`:42`）、`fp_02`（描述自称 greenfield 净新增，`:55`）、`fp_03`（`:62-69`，onion-practice 专项练习） |

fixture 的三条 description 已在正文自述 brownfield/greenfield（`gaokao_boost.json:42`、`:55`）→ `intent` 取值有现成依据，且正好覆盖 `greenfield`/`brownfield` 两种枚举；`fp_03` 建议 `greenfield`（新增组卷能力）。高三提分 case 是本相位验收靶子（`112-CONTEXT.md:91`），三值分布对 route 加权断言有直接价值。

**只消费工厂/fixture，工厂改完即自动通过（无需改动，但需回归验证）——共 6 个测试文件：**

| 文件 | 消费方式 |
|------|----------|
| `server/tests/services/test_blueprint_schema.py` | `make_blueprint` × 21 处（`:20` import；`:43` 整体 validate 通过） |
| `server/tests/services/test_blueprint_execution.py` | `make_blueprint` × 13 处（`:16`） |
| `server/tests/services/test_blueprint_quality.py` | `make_blueprint` × 6 处（`:19`） |
| `server/tests/delivery/test_blueprint_artifact_wiring.py` | `make_blueprint` × 3 处（`:17`） |
| `server/tests/delivery/test_evaluate_blueprint_golden.py` | `make_blueprint` + `_write_case`（`:18`、`:58,69,85`）；`:40-44` 跑默认目录（读真 fixture） |
| `server/tests/delivery/test_blueprint_integration.py` | 直读 `gaokao_boost.json`（`:46`，注释称「单一事实源不再手造第二份大样例」） |

**逐条核查过的断言，确认加字段后**不**破**（无一处做 feature_points 全等比较）：
- `test_blueprint_schema.py:283` — 断言 `"requirement_spec.feature_points[fp_01].description" in paths`（`iter_blocks` 路径集合，`in` 判定，不受新字段影响）。
- `test_blueprint_schema.py:166-190` `test_duplicate_ids_rejected` — `copy.deepcopy(records[0])` 再改 `id`（`:183-184`），深拷贝自动带上 `intent`，仍触发重复 id 拒绝。
- `test_blueprint_schema.py:204-212` `test_validation_error_truncated` — 整段替换 `requirement_spec` 为 list（`:207`），与 feature_points 内部结构无关。
- `test_blueprint_schema.py:53-70` 顶层缺段拒绝、`:157-163` 引用池 key 不一致 — 均不触及 feature_points 字段集。
- `evaluate_blueprint_golden.py:106-110` — 只取 `fp.get("id")` 做 `required_feature_point_ids` 子集判定；`:69-71` 跑 `validate_blueprint` 必须通过（**所以 fixture 不补 intent 会让 golden command 与 `test_evaluate_blueprint_golden.py:40` 一起红**）。
- `delivery/artifacts/builtin_types.py:23-25` — `schema_version == "blueprint/v1"` 时改走 `validate_blueprint`；无字段级断言。

**结论：2 个文件必改（1 个工厂 + 1 个 golden fixture），6 个测试文件零改动但必须回归。**

### 3.4 「加必填字段而不破坏既有测试」的最小改法建议

推荐 **A（单提交同步演进）**——本相位 `intent` 是下游 route 加权的输入（`112-CONTEXT.md:32`），可选字段会让加权逻辑长出 `None` 分支，违背「必填枚举」锁定决策：

1. `blueprint_schema.py:178` 改 `"required": ["id", "title", "intent"]`；在 `properties` 内（`:189` 之后、`description` 之前，紧跟 `title` 保持语义相邻）加：
   ```python
   "intent": {
       "type": "string",
       "enum": ["greenfield", "brownfield", "fix"],
       "description": "功能点意图分类（净新增 / 存量改造 / 缺陷修复；驱动路由加权，DESIGN §5.7）",
   },
   ```
2. `blueprint_samples.py:48-61` 两条 fp 各补 `"intent": "greenfield"`（与 description 语义一致；如需覆盖 brownfield 分支可把 `fp_02` 设 `brownfield` 并同步 `test_blueprint_quality.py` 无关断言——已核查无断言依赖）。
3. `gaokao_boost.json` 三条 fp 补 `intent`：`fp_01="brownfield"`（`:42` 自述改造）、`fp_02="greenfield"`（`:55` 自述净新增）、`fp_03="greenfield"`。
4. **新增一条负向测试**锁住必填性（否则「required」演进无回归保护）：在 `test_blueprint_schema.py` 加 `content["requirement_spec"]["feature_points"][0].pop("intent")` → `validate_blueprint` 返回 `(False, ...)`；再加一条非法枚举值（如 `"refactor"`）被拒。
5. 同步 `blueprint_schema.py` 模块 docstring / `blueprint_samples.py:3-12` docstring 中的字段说明（两处都逐字列了样例形状）。

**不推荐 B（先可选后必填两阶段）**：本相位所有 feature_points 写入方都在本相位内落地（`call_source.py:110-111`），没有需要兼容的存量生产数据；两阶段只增加一次 schema 改动与一轮回归，无收益。

**风险点（planner 须显式覆盖）**：`server/tests/fixtures/blueprint_golden/` 若在本相位新增 golden case（`112-CONTEXT.md:93` 提到本相位首次有真实数据可评），新 case 必须自带 `intent`，否则 `evaluate_blueprint_golden` 的 `validate_blueprint` 门（`evaluate_blueprint_golden.py:69-71`）直接判 FAIL。

---

## 主题 4：`SystemSetting` 键注册与读取

### 4.1 模型与键定义位置

- 模型 **`SystemSetting`**：`server/system/models.py:13-28` —— `key`（`CharField(max_length=100, primary_key=True)`，`:16`）、`value`（`TextField(blank=True, null=True)`，`:17`）、`is_encrypted`（`:18`）、`description`（`:19`）、`updated_at`（`auto_now`，`:20`）；`db_table = "system_settings"`（`:23`）。
- **`class SettingKeys`**：`server/system/models.py:31-163` —— 纯常量类（无 Enum、无 metaclass），**只加类属性即完成注册，无迁移**（`:148` 明确「仅常量，无新键迁移」）。

### 4.2 命名惯例（两代并存，新键必须用点分）

| 代 | 形态 | 例 |
|----|------|-----|
| 旧 | 扁平下划线 | `GIT_HTTP_PROXY = "git_http_proxy"`（`:40`）、`QDRANT_URL = "qdrant_url"`（`:52`） |
| **新（必须遵循）** | **点分命名空间** | `CODE_INDEX_EXCLUSION_GLOBAL_DEFAULTS = "code_index.exclusion.global_defaults"`（`:95`）、`LOG_LEVEL = "log.level"`（`:130`）、`METRIC_RETENTION_DAYS = "metric.retention_days"`（`:142`）、`ALERT_EVAL_INTERVAL_SECONDS = "alert.eval_interval_seconds"`（`:149`）、`LEARNING_CASE_AUTO_EXTRACT = "learning_case.auto_extract_enabled"`（`:160`） |

`:128` 明确「点分命名与 `code_index.exclusion.*` 风格一致」。**本相位新键建议 `blueprint.spec_gate.*`**（阈值 + 四维权重），对齐 `112-CONTEXT.md:25` 的权重外置要求。

值类型惯例（`:48`、`:87`、`:92-93`、`:131` 等注释）：非标量一律 **JSON 字符串存 `value`**，注释内逐字写出 JSON 形状 + 默认值 + 消费方。既有多值配置全部走「一个 JSON 键」而非「N 个标量键」——四维权重 map 用一个 JSON 键更贴合惯例。

### 4.3 新增键的步骤（照 LOG-06 / ALERT-01 现行做法）

1. 在 `server/system/models.py` 的 `SettingKeys` 内追加常量（点分值），**注释必须写出**：value 类型/JSON 形状、默认值、消费方模块（照 `:127-136` 的 LOG_* 段落格式）。位置：追加在 `:163` `PR_REVIEW_CAPTURE` 之后。
2. **无需 migration**（常量非模型字段；`:148` 有明确先例声明）。
3. 消费侧用 `system.settings_service` 的 typed getter 读，**永远带 `default=`**（缺键即回默认，`get_*` 全部 fail-safe 不抛，`settings_service.py:34-41` `_get_raw` 连 DB 异常都吞成 `None`）。
4. 若需写入即生效，走既有 signal 失效缓存机制（`:129` 「写入即经 signal 失效缓存」）；本相位阈值/权重读取频率低，60s 缓存已足够，**无需新增 signal**。

### 4.4 运行时读取函数签名

**`server/system/settings_service.py`** —— 同步 typed getter（带 60s django cache，`CACHE_PREFIX = "sys_setting:"` `:19`、`CACHE_TIMEOUT = 60` `:20`；缺失值以 `"__none__"` 哨兵缓存，`:30-40`）：

| 函数 | 行号 | 语义 |
|------|------|------|
| `get_setting(key: str, default: str = "") -> str` | `:44-47` | 原样字符串 |
| `get_bool_setting(key: str, default: bool = False) -> bool` | `:50-55` | 真值集 `("true","1","yes","on")`（小写比较） |
| `get_int_setting(key: str, default: int = 0) -> int` | `:58-66` | `ValueError` → default |
| **`get_float_setting(key: str, default: float = 0.0) -> float`** | `:69-77` | 阈值（0.20）用它 |
| **`get_json_setting(key: str, default: dict \| None = None) -> dict`** | `:80-93` | 权重 map 用它；**非 dict 或解析失败 → 回默认**（`:81`） |

Async 版（**无缓存，每次 `afirst()` 打 DB**，`:96-121`）：`aget_setting(key, default="")`（`:96-102`）、`aget_bool_setting(key, default=False)`（`:105-110`）、`aget_int_setting(key, default=0)`（`:113-121`）。

⚠️ **缺口（planner 须显式决策）**：**没有 `aget_float_setting` / `aget_json_setting`**（`rg "def aget_.*_setting"` 只返回 str/bool/int 三个）。stage handler 是 async 上下文（`builtin_processes.py:45` 等），读阈值/权重有三条路：
- (a) `await aget_setting(key, "")` + 自行 `float()` / `json.loads()` 包 try（不新增公共 API，最小侵入）；
- (b) 在 `settings_service.py` 补 `aget_float_setting` / `aget_json_setting`（对称补齐，属改动共享模块，需评估回归面）；
- (c) `sync_to_async(get_json_setting)`（复用 60s 缓存，与项目 async ORM 约定一致）。
加密值走另一路：`server/chat/services.py:118-131` 的 `get_setting_value` / `aget_setting_value`（自动 `decrypt_value`，`:124-126`）——本相位阈值/权重**非敏感，不用加密路径**（`is_encrypted` 保持 False）。

### 4.5 测试中如何设值（现行范式）

范式来自 `server/tests/test_log_runtime_config.py`（同款「运行时可配」键的测试）：

1. **写值必须用 `instance.save()`，不能用 `queryset.update()`**（后者不触发 `post_save` signal）：
   ```python
   def _save_setting(key: str, value: str) -> None:      # test_log_runtime_config.py:69-74
       obj, created = SystemSetting.objects.get_or_create(key=key, defaults={"value": value})
       if not created:
           obj.value = value
           obj.save()
   ```
2. **必须清 60s 缓存做隔离**（否则跨测试污染）——`autouse` fixture 前后各清一次：
   ```python
   from system.settings_service import _cache_key      # :37-43 键清单 + :47-52 清缓存
   cache.delete(_cache_key(key))                       # :50
   ```
   `_isolate` fixture 形状见 `:55-66`（`@pytest.fixture(autouse=True)`，yield 前后对称清理）。
3. 测试须标 `@pytest.mark.django_db`（`:80`）。
4. 只读断言可直接建对象：`SystemSetting.objects.create(key=SettingKeys.X, value="7")`（`tests/test_system_log_api.py:258`、`tests/test_system_alert_api.py:178`）；读回断言用 `SystemSetting.objects.get(key=SettingKeys.X).value`（`tests/test_setup_integrations.py:117`）。
5. 默认值回退测试：不建对象直接调 getter 断言等于 default（`test_log_runtime_config.py:170`、`:181` 覆盖非法值回默认）。

---

## Package Legitimacy Audit

**不适用**：本相位 4 主题均基于仓内既有模块（`process_runtime` / `system` / `jsonschema` 已在 `server/pyproject.toml`），**无新增外部依赖** → 无需跑 slopcheck / 注册表校验。

## Environment Availability

**不适用**：本文 4 主题为纯代码/配置面契约，无新增外部工具、服务或运行时依赖。

## Validation Architecture

`nyquist_validation: true`（`.planning/config.json`）。

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest + pytest-django + pytest-asyncio（`server/pyproject.toml`） |
| Config file | `server/pyproject.toml`（`[tool.pytest.ini_options]`） |
| Quick run command | `cd server && uv run pytest tests/services/test_blueprint_schema.py -x -q` |
| Full suite command | `cd server && uv run pytest -q` |

### 主题 → 测试映射

| 主题 | 行为 | Test Type | Automated Command | File Exists? |
|------|------|-----------|-------------------|--------------|
| 1 stage graph | `technical_blueprint` 注册项存在、transitions 表与骨架一致、pausable/wait_status 取值合法 | unit | `uv run pytest tests/services/ -k "blueprint and process" -x -q` | ❌ Wave 0（新文件） |
| 1 冻结面 | `_TECHNICAL_PLAN_STAGES` 逐字未变（7 stage / transitions 快照） | unit | 同上 | ❌ Wave 0（回归护栏） |
| 2 advance | self-loop → wait_status、reroute 计数经 stage_state 持久化、exhausted 不落 `__failed__` | unit | 同上 | ❌ Wave 0 |
| 3 schema | 缺 `intent` 被拒 / 非法枚举被拒 / `make_blueprint()` 仍通过 | unit | `uv run pytest tests/services/test_blueprint_schema.py -x -q` | ✅ 扩充既有文件 |
| 3 回归 | 6 个消费文件全绿 + golden command PASS | integration | `uv run pytest tests/services/test_blueprint_execution.py tests/services/test_blueprint_quality.py tests/delivery/test_blueprint_artifact_wiring.py tests/delivery/test_evaluate_blueprint_golden.py tests/delivery/test_blueprint_integration.py -q` | ✅ |
| 4 SystemSetting | 新键缺失回默认 / 设值后生效 / 非法值回默认 | unit | `uv run pytest tests/ -k "blueprint and setting" -x -q` | ❌ Wave 0 |

### Sampling Rate
- 每 task commit：对应主题的 quick run
- 每 wave merge：`uv run pytest tests/services/ tests/delivery/ -q`
- Phase gate：full suite green + `python manage.py evaluate_blueprint_golden` PASS

### Wave 0 Gaps
- [ ] `server/tests/services/test_blueprint_process_graph.py` — 主题 1/2（含 `_TECHNICAL_PLAN_STAGES` 冻结快照断言）
- [ ] `server/tests/services/test_blueprint_schema.py` 扩充 — 主题 3 两条负向断言
- [ ] `server/tests/helpers/blueprint_samples.py` + `server/tests/fixtures/blueprint_golden/gaokao_boost.json` — 主题 3 数据同步
- [ ] `blueprint.spec_gate.*` 设置读取测试（含 `_isolate` 清缓存 fixture，照 `test_log_runtime_config.py:47-66`）

## Security Domain

`security_enforcement: true`，ASVS L1。本文 4 主题的适用面：

| ASVS Category | Applies | Standard Control |
|---------------|---------|------------------|
| V2 Authentication | no | 本文无认证面（确认门 REST 的鉴权在 PATTERNS/REST 面） |
| V3 Session Management | no | `ConvergenceSession` 是业务会话，非用户会话 |
| V4 Access Control | no | — |
| V5 Input Validation | **yes** | `intent` 用 jsonschema `enum` 白名单（`blueprint_schema.py` 内，非手写判断）；`SystemSetting` 权重值经 `get_json_setting` 校验非 dict 即回默认（`settings_service.py:80-93`），阈值经 `get_float_setting` 校验（`:69-77`）——**绝不 `eval` / 绝不信任 DB 里的配置字符串形状** |
| V6 Cryptography | no | 阈值/权重非敏感，`is_encrypted=False`；敏感值才走 `chat/services.py:118-131` 的 `decrypt_value` 路 |

| 威胁 | STRIDE | 缓解 |
|------|--------|------|
| 运行时配置被写入非法值致 stage 崩溃 | Tampering / DoS | 所有 getter fail-safe 回默认（`settings_service.py:34-41,72-77,86-93`），权重再做 clamp（照 `models.py:140` `sample_gauges` 的 `clamp(30..300)` 先例） |
| `error` dict 回显含凭证/上游正文 | Information Disclosure | `StageOutcome.error` 只写结构化 `{stage, reason, ...}`（`builtin_processes.py:191-198`）；正文类字段先过 `redact_secrets_in_text`（`.cursor/rules/observability-logging.mdc`）；schema 报错出口已强制截断（`test_blueprint_schema.py:204-212`） |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | 建议的 `technical_blueprint` transitions 表（1.5）是从锁定骨架 + 机制事实推导的**建议**，非代码既有事实 | 主题 1.5 | planner 可自行调整 event 命名；机制约束（exhausted 不落 failed、self-loop 表 pause）为硬事实 |
| A2 | 新键命名空间 `blueprint.spec_gate.*` 是按点分惯例的建议 | 主题 4.2 | 仅命名偏好，改名无机制影响 |
| A3 | `gaokao_boost.json` 三条 fp 的 `intent` 取值（brownfield/greenfield/greenfield）依据 description 自述文本推断 | 主题 3.4 | 取值影响 route 加权断言的期望，planner 应与验收靶子（`112-CONTEXT.md:91`）对齐后确认 |
| A4 | `server/pyproject.toml` 的 pytest 配置节名与 `uv run pytest` 调用形未在本次逐字读取（沿用仓内惯例） | Validation Architecture | 命令前缀可能需微调，不影响测试映射 |

## Open Questions

1. **`resume.py` 的 pause 短路判据与 blueprint 澄清载体不匹配**
   - 已知：`resume.py:52-64` 的两个短路判据写死 `ClarificationService().ahas_pending` 与 `aall_research_tasks_terminal`；本相位澄清载体是 `BlueprintThread(blocking=true)`（`112-CONTEXT.md:26`）。
   - 不清：`resume.py` 是否属冻结面（`112-CONTEXT.md` 未列入禁改清单，但 INV-6 与「不造两套 engine」纪律指向谨慎）。
   - 建议：新写 blueprint 专用 drive helper（新文件，不动 `resume.py`），短路判据换成「查 open+blocking `BlueprintThread`」+ 复用 `aall_research_tasks_terminal`。

2. **async typed getter 缺 float/json 版本**
   - 已知：`settings_service.py` 只有 async 的 str/bool/int（`:96-121`）。
   - 建议：优先 (c) `sync_to_async(get_json_setting)` 复用 60s 缓存；若 planner 选择补齐 async 版本，须同步加 getter 自身的单测。

3. **`repo_confirmation` 的 wait_status 取值**
   - 已知：`ConvergenceSessionStatus` 只有 `waiting_clarification` / `waiting_event` 两个挂起值（`convergence_session.py:35-36`），不新增状态值是稳妥做法。
   - 建议：确认门取 `waiting_clarification`（同为 HITL 等人），与 `spec_gate` 一致；stage 身份（`current_stage`）自带区分，无需新状态。

## Sources

### Primary (HIGH confidence，全部为本 worktree 代码直读)
- `server/services/process_runtime/registry.py` — StageDef / ProcessDefinition / 注册与惰性导入
- `server/services/process_runtime/engine.py` — ProcessEngine.advance / StageOutcome / 终态哨兵
- `server/services/process_runtime/builtin_processes.py` — `_TECHNICAL_PLAN_STAGES` / handler 实例 / 注册调用位置
- `server/services/process_runtime/resume.py` — pause 短路与步数上限
- `server/delivery/services/convergence_session_service.py:126-259` — transition / CAS / fail 特判
- `server/delivery/models/convergence_session.py:30-38` — 状态枚举
- `server/services/process_runtime/blueprint_schema.py:166-223, 786-947` — feature_points schema / 后置检查 / iter_blocks
- `server/tests/helpers/blueprint_samples.py`、`server/tests/fixtures/blueprint_golden/gaokao_boost.json`
- `server/system/models.py:13-163`、`server/system/settings_service.py`
- `server/tests/test_log_runtime_config.py:37-90` — 设置类测试范式
- rg 全量引用核查：`feature_points` / `make_blueprint` / `requirement_spec` / `SettingKeys\.` / `validate_blueprint`
- `.planning/phases/112-1/112-CONTEXT.md`、`.planning/config.json`、`.cursor/rules/observability-logging.mdc`

### Secondary / Tertiary
无——本文未使用外部检索（4 主题均为仓内契约，代码即最高权威源）。

## Metadata

**Confidence breakdown:**
- 主题 1 stage graph 契约：HIGH — dataclass 定义与全部 7 个既有 StageDef 逐字读取
- 主题 2 advance 契约：HIGH — advance 全文 + transition/CAS 全文读取
- 主题 3 影响面：HIGH — rg 全量核查引用点并逐条读断言，无遗漏；`intent` 取值建议为 A3 假设
- 主题 4 SystemSetting：HIGH — 模型/常量类/getter/测试范式全部直读；async float/json 缺口已确认

**Research date:** 2026-07-30
**Valid until:** 仓内契约，随 `process_runtime` / `blueprint_schema` 改动失效；建议 Phase 112 执行期内有效（≤14 天）
