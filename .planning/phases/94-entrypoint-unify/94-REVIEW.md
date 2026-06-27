---
phase: 94-entrypoint-unify
reviewed: 2026-06-28T00:40:00Z
depth: deep
files_reviewed: 11
files_reviewed_list:
  - server/services/plan_orchestration/entrypoint.py
  - server/services/plan_orchestration/render.py
  - server/mcp_tools/orchestration_delegate.py
  - server/mcp_tools/technical_plan_service.py
  - server/mcp_tools/planning_service.py
  - server/mcp_tools/views.py
  - server/agents/tools/plan_research_tools.py
  - server/workflows/nodes/ai/plan_research.py
  - server/workflows/nodes/ai/plan_generation.py
  - server/workflows/nodes/base.py
  - server/workflows/templates/technical_plan_generation.json
findings:
  critical: 0
  warning: 3
  info: 4
  total: 7
status: fixes_applied
fixes_applied: 2026-06-28T00:55:00Z
resolution:
  WR-01: resolved
  WR-02: resolved
  WR-03: resolved
  IN-02: resolved
  IN-03: resolved
  IN-01: deferred
  IN-04: deferred
---

# Phase 94: Code Review Report

**Reviewed:** 2026-06-28T00:40:00Z
**Depth:** deep（含跨文件调用链：delegate → orchestration → 下游 execution / chat graph）
**Files Reviewed:** 11 源文件（+ 9 测试文件抽查）
**Status:** fixes_applied

> **修复状态（2026-06-28）**：WR-01 / WR-02 / WR-03 + IN-02 / IN-03 已修复并补守护测试
> （`tests/mcp_tools/test_create_feishu_technical_plan_delegate.py`、`test_planning_tools.py`，
> 27 passed；ruff/mypy 通过）。IN-01（跨仓回退）/ IN-04（范围外提交）**deferred**：IN-04 系
> 其它会话 WIP，本次不处理。

## Summary

入口统一（entrypoint-unify）整体方向落地扎实，重点契约多数成立：

- **UNIFY-02 通过**：`ai_plan_generation` 仍 `@register_node` + `deprecated=True`（`base.py` 新增 `deprecated: ClassVar[bool]` 基类默认），仅从 `NodePalette.vue` 移除暴露——既有实例兼容、新建不可选，符合预期。
- **UNIFY-05 通过**：plan 澄清独立 marker `PLAN_CLARIFICATION_RENDER_MARKER = "plan_clarification"` 与 chat 单题物理隔离已验证——`orchestration/graph.py:_extract_pending_clarification` 双条件（`tc.name == "ask_clarification"` AND `payload.marker == "ask_clarification"`）对 `start_plan_research`（工具名不符 + marker 不符）**必不命中**；`blocking_marker_seen` 仅由 `__blocking_task__` 触发，亦不受影响。
- **UNIFY-06 通过**：`render_merged_plan_markdown` 仅读结构化字段（title/summary/execution_plan name/description/coding_instruction/compat_risks），截断 instruction（300），不 dump LLM 原文；done 出口 schema 声明 `plan_markdown` 规避 field_not_found。
- **skip_clarification 接线正确**：`ClarifyAdapter(policy=_no_clarify)` 签名与 `default_needs_clarification` 一致，MCP 单次同步入口直推不挂澄清；`engine.advance` 内部 `except Exception → transition("fail")` 保证多数 stage 异常落 FAILED 而非抛穿。

**主要问题集中在 UNIFY-03/04 的「显式字段映射白名单」与下游消费方的字段契约错配**：新映射丢弃了下游 execution 路径实际读取的 `steps`/`test_strategy`/`risks`/`rollback`，且最富信息的 `coding_instruction` 未被下游消费（WR-01）；嵌套 `plan` 对象外形整体替换为 canonical content（WR-02）；create_coding_plan 移除了 model_usage 落库导致 MCP run 维度 token 归因丢失（WR-03）。无 BLOCKER。

## Warnings

### WR-01: feishu 工作项 → 编码执行链路丢失方案细节（steps/test/risks/rollback + coding_instruction 未透传）

**File:** `server/mcp_tools/technical_plan_service.py:60-86`（`_map_execution_plan_to_repository_tasks`）；下游消费 `server/mcp_tools/work_item_execution_service.py:206-218`（`_coding_plan_body`）

**Issue:** 新映射产出的 `repository_tasks` 项仅含 `{order, repository_id, repository_name, planned_branch, change_goal, coding_instruction, candidate_files, dependencies}`。但下游 `_coding_plan_body(task)` 从 `task.task_body` 读取的是旧矩阵的键：

```python
"steps": list(body.get("steps") or []),          # 新映射无 steps → 恒 []
"test_plan": list(body.get("test_strategy") or []), # 新映射无 test_strategy → 恒 []
"risks": list(body.get("risks") or []),          # 新映射无 risks → 恒 []
"rollback": str(body.get("rollback") or ""),     # 新映射无 rollback → 恒 ""
```

更关键：映射把 LLM 最富信息的 `coding_instruction` 写进 task_body，但 `_coding_plan_body` **从不读取它**。`change_goal = description or coding_instruction or name`——当 canonical task 同时有 `description` 与 `coding_instruction`（§7 常态）时，`change_goal` 取较短的 `description`，详细 `coding_instruction` 被彻底丢弃。结果：经 `create_feishu_technical_plan` 落库 → `create_repo_tasks_from_technical_plan` → `ai_coding` 执行的编码代理，拿到的 plan body 退化为「title + 简短 change_goal + 候选文件」，相比被取代的确定性矩阵（含步骤/测试/风险/回滚）**信息保真度明显下降**。

**Fix:** 在映射端把 `coding_instruction` 落进下游会读取的字段（最小改动，复用既有消费契约）：

```python
tasks.append(
    {
        "order": index,
        "repository_id": str(item.get("repository_id") or ""),
        "repository_name": str(item.get("repository_name") or ""),
        "planned_branch": str(item.get("branch_strategy") or ""),
        "change_goal": change_goal,
        "coding_instruction": coding_instruction,
        "candidate_files": candidate_files,
        "dependencies": [str(dep) for dep in dependencies],
        # 下游 _coding_plan_body 读取 steps，把详细指令落为单步，避免编码代理拿空步骤
        "steps": [coding_instruction] if coding_instruction else [],
    }
)
```

或对称地让 `_coding_plan_body` 读取 `coding_instruction`（`requirement`/`steps` 回退到 instruction）。任选其一，保证 instruction 真正抵达编码代理。

**✅ Resolution（resolved）：** 两端均修。`_map_execution_plan_to_repository_tasks` 现产出下游读取的 `steps`/`test_strategy`/`risks`/`rollback`（canonical task 含同名字段则直取；缺 `steps` 时把 `coding_instruction` 落为单步），`coding_instruction` 始终透传；`_coding_plan_body` 亦回退 `requirement`/`steps` 到 `coding_instruction`。守护断言见 `test_create_feishu_technical_plan_delegate::test_create_feishu_technical_plan_response_shape_and_persistence`（steps/test_strategy/risks/rollback 非空）。

---

### WR-02: 嵌套 `plan` / `plan_body` 外形整体替换为 canonical content，违背「不透传内部键」白名单原则

**File:** `server/mcp_tools/technical_plan_service.py:389,406`；`server/mcp_tools/views.py:1902,1915`

**Issue:** 两个 MCP 入口虽保留了**顶层**响应键（`technical_plan_id`/`plan`/`markdown`/`repository_tasks`/... + 新增 `session_id`/`status`），但**嵌套 `plan` 对象与落库 `plan_body` 的内部结构被整体替换**：

- 旧 `create_feishu_technical_plan` 的 `plan`/`plan_body` 含 `{title, summary, work_item, repository_task_matrix, linked_documents, similar_cases, evidence, context_preview}`；
- 新值 = canonical §7 content（`{execution_plan, compat_risks, title, ...}`）。

调用方若解析 `response.plan.repository_task_matrix` / `plan.work_item` / `plan.summary` 将取不到。这与本 phase 对 `repository_tasks` 刻意施加的「显式白名单、绝不透传 content 内部键」（T-94-03/04-INFO）**自相矛盾**——`plan` 字段恰恰把 canonical 内部键原样透传。属契约外形变更而非纯兼容。

**Fix:** 明确二选一并固化为契约：
1. 若 `plan` 须保持旧外形：用映射后的 payload（feishu 侧用旧 plan_body 形态、coding 侧用 `plan_payload`）填 `plan`，canonical content 仅入 `plan_body` 或新增独立键 `canonical_content`；或
2. 若有意切到 canonical：在 `docs/workflows/ai-plan-generation-deprecation.md` 显式记录「`plan` 字段外形已变更为 canonical MergedPlan」，并补一条响应外形回归测试断言新键集，让破坏面可见、可追踪。

**✅ Resolution（resolved，选项 1）：** 新增 `_map_plan_payload` 把 canonical 显式映射回旧关键键（`title`/`summary`/`work_item`/`repository_task_matrix`/`linked_documents`/`similar_cases`/`evidence`/`context_preview`），响应 `plan` 与落库 `plan_body` 均用旧外形；canonical content 以独立 `canonical_content` 键保留（不丢信息）。`_LEGACY_PLAN_KEYS` 外形守护见 `test_create_feishu_technical_plan_delegate`。

---

### WR-03: `create_coding_plan` 移除 `_record_model_usage`，MCP run 维度 token/成本归因丢失

**File:** `server/mcp_tools/views.py`（删除 `await self._record_model_usage(run, result.model_usage)`，约 1918 行附近）

**Issue:** 旧 `build_coding_plan` 返回 `model_usage` 并落到本 MCP tool-call 的 `InteractionRun`。改 delegate 后该行被删，依据 delegate docstring「编排内部 LLM/召回埋点由 plan_orchestration adapters 承担」。但 orchestration 的 LLM 用量记录在其**自身的 run/session**，与本 MCP `run` 通过 `session_id` 软关联——本 MCP tool-call 的 `InteractionRun` 不再挂任何 `ModelUsageRecord`。按可观测性强制规范（新增 LLM 调用须上报 token，且调用类 `caller` 需可归因触发用户/请求），MCP `create_coding_plan` 的 token/成本将无法直接按本次调用聚合。

**Fix:** 二选一并验证：
- 确认并文档化「MCP run 经 `session_id` 关联到 orchestration run 的 model usage」，在 `LOGGING-SPEC` 注明该跨 run 关联键；或
- 在 delegate 返回里带回本次编排聚合的 `model_usage`，由 view 仍调用 `_record_model_usage(run, ...)`，保持 MCP run 维度 token 归因不回退。

**✅ Resolution（resolved，选项 2）：** `DelegateResult` 新增 `model_usage`；`delegate_plan_orchestration` best-effort 聚合本次驱动窗口内 `run` 未绑定的 `ModelUsageRecord`（token/duration）回传；`CreateCodingPlanView` 重新 `_record_model_usage(run, delegate.model_usage)`（非空才落，不落零行）。编排 adapters 的 call_source 维度记录仍在原行保留（不重复/不互相复制）。守护见 `test_planning_tools::test_create_coding_plan_stores_version_and_evidence` + `test_create_feishu_technical_plan_delegate::test_delegate_aggregates_orchestration_model_usage`。

## Info

### IN-01: `map_canonical_to_coding_plan` 跨仓回退可能把他仓 task 放进单仓响应

**File:** `server/mcp_tools/planning_service.py:340-347`

**Issue:** 无 `repository_id` 精确匹配时 `task = execution_plan[0]`（首项回退）。单仓约束（`include_repos=[repository_id]`）下编排理应只产该仓 task，但若编排异常产出他仓 task，回退首项会让**他仓 task 进单仓响应**，与文档「他仓 task 不进单仓响应」承诺冲突。

**Fix:** 无精确匹配时返回最小空结构（不回退首项），或断言首项 `repository_id` 与目标一致再采用：

```python
if not task and execution_plan and isinstance(execution_plan[0], dict):
    first = execution_plan[0]
    if str(first.get("repository_id") or "") in ("", repo_id):
        task = first  # 仅当无归属或匹配本仓时才回退
```

**⏸️ Resolution（deferred）：** 本次未处理（单仓约束下编排理应只产该仓 task，回退首项为防御性 best-effort，风险窄）；留待后续随跨仓语义收口处理。

### IN-02: 新 `repository_tasks` 映射丢弃 `base_branch`，下游回退到 repo 默认分支

**File:** `server/mcp_tools/technical_plan_service.py:80`；消费 `server/mcp_tools/work_item_execution_service.py:119`

**Issue:** 旧 `_build_repo_task_matrix` 产 `base_branch`，新映射不产。下游 `target_branch = item.get("base_branch") or repo.base_branch or repo.default_branch` 恒走仓库默认分支回退。canonical 若含目标基线分支信息则丢失。属可接受降级，但目标分支语义被静默改变。

**Fix:** 若 canonical execution_plan 项含基线分支字段，映射进 `base_branch`；否则在文档注明「per-task base_branch 已统一回退仓库默认分支」。

**✅ Resolution（resolved）：** `_map_execution_plan_to_repository_tasks` 现透传 `base_branch`（`str(item.get("base_branch") or "")`）；canonical 含基线分支则下游不再静默回退仓库默认分支。守护断言（`base_branch == "release/2026.06"`）见 `test_create_feishu_technical_plan_delegate`。

### IN-03: `delegate_plan_orchestration` 无异常护栏（窄面残留 500 风险）

**File:** `server/mcp_tools/orchestration_delegate.py:84-110`

**Issue:** `engine.advance` 内部已 `except Exception → transition("fail")`，多数 stage 异常落 FAILED 不抛穿；但 `start_orchestration`（create_session/DB）、`PlanSession.objects.aget`、`_load_canonical` 的 `PlanVersion` 查询，以及 advance 中 `NotImplementedError` 的 re-raise（`engine.py:96`）仍可抛穿 delegate → MCP `handle_exception` 兜底 DRF 500。相比旧确定性 `build_coding_plan`，失败面有所扩大。

**Fix:** 在 delegate 外层包 try/except，把未预期异常映射为 `DelegateResult(status="failed", content={}, ...)`（best-effort 埋 `mcp_plan_delegate_failed`），让 MCP 入口与工作流引擎一样具备「异常 → failed 终态」对称护栏，杜绝 5xx 回退。

**✅ Resolution（resolved）：** `delegate_plan_orchestration` 外层已包 try/except：未预期异常 → `warning mcp_plan_delegate_failed`（best-effort 脱敏）+ `DelegateResult(status="failed", content={}, ...)`，session 未建时占位 `SimpleNamespace(id="")` 保调用方 `str(.id)` 安全。守护见 `test_create_feishu_technical_plan_delegate::test_delegate_guards_unexpected_exception_as_failed`。

### IN-04: 范围外变更混入 94-04 提交

**File:** `server/mcp_tools/views.py:2757-2811`（`_resolve_projects_by_branch` / `_resolve_report_project_id`）

**Issue:** commit `13ce88a5d`（94-04）同时引入 report_* 工具的「按 branch 反查项目」逻辑，与 entrypoint-unify 主题无关。功能本身实现合理（`@sync_to_async` 包同步 ORM、fail-soft 跳过），但与 plan 入口统一无关的改动混入同一 phase 提交，增大评审/回滚耦合。

**Fix:** 后续遵循单一主题提交；本次仅记录，不阻断。

**⏸️ Resolution（deferred）：** `report_*` 变更属其它会话 WIP（非本修复会话误入），按约定不处理。

---

_Reviewed: 2026-06-28T00:40:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
