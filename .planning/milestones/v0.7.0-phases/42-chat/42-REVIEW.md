---
phase: 42-chat
reviewed: 2026-06-16T13:55:00Z
depth: standard
files_reviewed: 6
files_reviewed_list:
  - server/services/plan_orchestration/entrypoint.py
  - server/services/plan_orchestration/__init__.py
  - server/agents/tools/plan_research_tools.py
  - server/agents/tools/__init__.py
  - server/workflows/nodes/ai/plan_research.py
  - server/agents/chat_runner.py
findings:
  critical: 0
  warning: 2
  info: 1
  total: 3
status: fixed
fixed_at: 2026-06-16T14:06:00Z
resolution:
  WR-01: fixed   # placeholder/description 文案如实化 + deferred-items.md 登记接线缺口 (9350c576e)
  WR-02: fixed   # 空 requirement_text fail-closed 守护 + 参数化测试 (e69334422)
  IN-01: fixed   # include_repos 全部被过滤时记醒目 warning 日志 (9d9dd6fd1)
---

# Phase 42: Code Review Report

**Reviewed:** 2026-06-16T13:55:00Z
**Depth:** standard
**Files Reviewed:** 6
**Status:** fixed（全部 3 项已处理，见 42-REVIEW-FIX.md）

## Summary

Phase 42（ENTRY-02，Chat 入口薄封装）的目标是「同一 engine、同一状态机」的薄入口收口：抽
`start_orchestration` + `build_orchestration_engine` 薄 helper，重构 Phase 41 工作流节点复用之，
再加 chat 工具 `start_plan_research`。逐项核验三条特别关注点：

- **(a) 共享 helper 重构无回归** —— ✅ 干净。对比 `0dd05317f^` 旧实现，`build_orchestration_engine`
  注入的 5 个 adapter（`RepoRouterV2Adapter` / `DeliveryKnowledgeRecallAdapter` /
  `ResearchDispatchAdapter(node_execution_id=...)` / `ArchitectMergeAdapter` / `ClarifyAdapter`）
  与 Phase 41 **逐字相同**。**CR-02 resume 修复存活**：节点 `_build_engine` 仍从 `context.node_execution`
  取 `node_execution_id` 并经 `build_orchestration_engine(node_execution_id=node_execution_id)`
  透传（`plan_research.py:251-254`），researching 段 waiting_event resume 通路完整保留。
- **(b) 入口无关真正复用同一 engine** —— ✅。workflow 与 chat 两入口均调同一 `start_orchestration`
  / `build_orchestration_engine`（grep 守护成立），chat 不另造编排逻辑，SC-1/SC-2 成立。
- **(c) INV-2 chat null work_item 可追溯** —— ✅。chat 工具显式 `work_item=None` + `entrypoint=chat`
  落 `PlanSession`，融合经 `ArchitectMergeAdapter` → `TechnicalPlanService.create_from`
  产 canonical `work_item=None`，测试 `test_start_plan_research_inv2_null_work_item` 守护。

其余正确性面核验通过：
- **async lazy-FK** —— `entrypoint.py` / `plan_research_tools.py` 全程 `*_id` 标量 /
  `.values()` / `afirst` / `aget`，无裸 lazy-FK。`session.current_plan_version` 是 `UUIDField`
  软引用（非 FK），`session.error` 是 `JSONField`，`_map_terminal`（同步函数）访问它们安全。
- **INV-6 / engine 纯度** —— session 写入只经 `PlanSessionService.create_session` /
  `transition`，chat 工具仅在步数超限时 `transition(session, "fail", ...)`，不旁路写 status。
- **工具注册 / 白名单** —— `@tool(category="PROJECT")` 自动注册；`agents/tools/__init__.py`
  导入 + `__all__`；`chat_runner.py` 触发导入 + `_INDEXED_TOOL_NAMES` 白名单。`space_id` /
  `conversation_id` 在 `required` 中声明，但 `mcp_adapter._adapt_tool` 会从 `properties` **与**
  `required` 同步移除并注入（`mcp_adapter.py:46-48`），无 schema 不一致。
- **不同步阻塞 / 不死锁** —— researching 在途时 chat 工具**立即返回** fire-and-forget marker，
  不同步等待容器；happy-path（`research.dispatch` 直通）在 `_MAX_ADVANCE_STEPS` 内驱动到 done。
- **security** —— 无硬编码密钥；`created_by` 由 `Conversation.created_by` 解析、None 时召回
  fail-closed（T-42-01）；`include_repos` 经 `projects__id=space_id` 过滤越权仓（T-42-01）；
  `space_id`/`conversation_id` 由适配层注入不可伪造（T-42-02）；步数上限防死循环（T-42-03）。

无 BLOCKER。两个 WARNING 围绕 chat fire-and-forget 的 resume 实际接线缺口（已显式 deferred，
但用户可见 placeholder 文案过度承诺）与 chat 入口缺少空 requirement 守护（与节点不对称）。

## Warnings

### WR-01: chat fire-and-forget 调研挂起无 resume 消费者，placeholder 文案过度承诺「自动继续」

**File:** `server/agents/tools/plan_research_tools.py:216-240`（结合 `server/subagent/api/callbacks.py:100-138, 193-200`）

**Issue:**
当 chat 发起的编排进入 RESEARCHING 且容器在途时，`_maybe_suspend` 返回 deep_analysis 式
`__blocking_task__` marker 并 `register_blocking_task`，placeholder 文案写明
「调研完成后将自动继续融合并返回主方案」。但实际 resume 通路对 **chat 入口未接线**：
- `_schedule_agent_session_resume`（callbacks.py:121-133）对 `task_type=="plan_research"`
  **短路**（barrier 唯一驱动，不触发 agent resume）。
- `_schedule_workflow_resume`（callbacks.py:193-200）仅在有 `node_execution` 时驱动——chat 入口
  **无 node_execution_id**（`build_orchestration_engine()` 不传），直接 `no_node_execution_skip_resume`。

结果：研究容器完成后 `_handle_research_completion` 通知 barrier，但**没有任何消费者**为 chat
入口重新驱动 engine（researching→merging→done）或用 `blocking_results` resume chat graph 的
`waiting_node` interrupt。深入调研路径的 chat 编排会在 WAITING 阶段静默挂起、永不回流——与
placeholder 承诺的「自动继续」不符。E2E resume 本身已按 Phase 39/40/41 决策**显式 deferred**
（IO 边界 mock），故非 BLOCKER；但用户可见承诺应与实际能力对齐，且缺口需被显式跟踪。

**Fix:** 二选一——
1. 调整 placeholder 文案为如实表述（如「已启动调研，完成后可在本会话继续；自动回流能力在后续里程碑接入」），避免过度承诺；并在 `deferred-items.md` 显式登记「chat 入口 plan_research 容器完成 → 重新驱动 engine / resume chat graph」的接线缺口。
2. 或补 chat 入口 resume 接线：在 barrier 完成回调中，对无 `node_execution` 的 `plan_research` 容器，按 `session_id` 关联 conversation 并调度一次 engine 续驱 + chat graph resume（注入 `blocking_results`）。

```python
# 方案 1（最小、与 deferred 一致）：文案如实化
"placeholder": (
    f"已启动方案编排调研（session={session.id}）；"
    "调研完成后可在本会话继续推进融合。"
),
```

### WR-02: `start_plan_research` 未守护空白 `requirement_text`，与工作流节点 fail-closed 不对称

**File:** `server/agents/tools/plan_research_tools.py:69-103`

**Issue:**
`AIPlanResearchNode._create_session`（`plan_research.py:194-197`）对空 `requirement_text`
显式 fail-closed（返回 `failed` + `missing_requirement`）。chat 工具则无任何空值守护：LLM
若传入空串 / 纯空白（`requirement_text` 属半可信输入，见 threat model「chat LLM → 工具」边界），
工具会照样 `start_orchestration` 建 session 并驱动 engine，路由 / 召回拿到空需求只能降级产出，
浪费一次编排并落一条语义空洞的 `PlanSession`。属「缺失输入校验」类（review scope #2）。

**Fix:** 在建 session 前补一行守护（薄、零编排逻辑），与节点对称：

```python
if not requirement_text or not requirement_text.strip():
    return ToolResult(
        success=False,
        error="缺少需求文本（requirement_text）",
    )
```

## Info

### IN-01: `_filter_repos_in_space` 在显式仓库全部被过滤 / 查询异常时静默回退到自动路由

**File:** `server/agents/tools/plan_research_tools.py:163-183`

**Issue:**
`_filter_repos_in_space` 在「用户显式传了 `include_repos` 但全部不属于该 space / 含非法 UUID /
查询异常」时一律返回 `[]`，与「用户根本没传 `include_repos`」无法区分。下游
`start_orchestration(..., include_repos=[])` 会被当作「按召回/路由自动选取」，即用户的显式
限定意图被静默丢弃、回退到全空间自动路由。当前为 best-effort 设计（已文档化、有 warning 日志），
但「显式限定全部失效」与「未限定」语义合并可能让用户困惑（以为限定生效）。

**Fix:** 可选改进——区分两种情形：当传入 `include_repos` 非空但过滤结果为空时，记一条更醒目的
日志（含 requested vs kept 计数），或在 `ToolResult` 文案中提示「指定仓库均不在当前空间，已回退
自动选仓」。非阻断，按需取舍。

```python
if include_repos and not kept:
    logger.warning(
        "start_plan_research_include_repos_all_filtered",
        space_id=space_id, requested=len(include_repos),
    )
```

---

_Reviewed: 2026-06-16T13:55:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
