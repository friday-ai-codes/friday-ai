---
phase: 42-chat
plan: 01
subsystem: api
tags: [plan-orchestration, chat-tool, langchain, agent-tools, entrypoint, INV-2, ENTRY-02]

# Dependency graph
requires:
  - phase: 41-entry
    provides: AIPlanResearchNode 工作流入口 + 真实 adapters + PlanOrchestrationEngine 端到端
  - phase: 40-merge
    provides: ArchitectMergeAdapter + §7 MergedPlan + canonical TechnicalPlanService 落库
  - phase: 36-orchestration
    provides: PlanOrchestrationEngine 入口无关状态推进器 + PlanSessionService 单一写入入口
provides:
  - "plan_orchestration/entrypoint.py：start_orchestration + build_orchestration_engine 两入口共用薄 helper"
  - "agents/tools/plan_research_tools.py：start_plan_research @tool（chat 入口薄封装，复用同一 engine）"
  - "chat 入口经 entrypoint=chat + work_item=None 发起编排（INV-2 自然语言需求可追溯）"
  - "SC-2 入口无关一致性守护：chat↔workflow 结构等价 MergedPlan + 同序 §15 事件"
affects: [v0.8 多仓编码入口, v0.11 对外 adapter, chat 工具白名单]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "薄共享 helper：两入口共用建 session + 构建 engine，helper 不驱动（驱动是入口私有）"
    - "chat @tool 薄封装复用同一 engine + 既有 HITL（ask_clarification interrupt / deep_analysis fire-and-forget）"

key-files:
  created:
    - server/services/plan_orchestration/entrypoint.py
    - server/agents/tools/plan_research_tools.py
    - server/tests/agents/test_start_plan_research_tool.py
    - server/tests/services/test_orchestration_entry_consistency.py
  modified:
    - server/services/plan_orchestration/__init__.py
    - server/workflows/nodes/ai/plan_research.py
    - server/agents/tools/__init__.py
    - server/agents/chat_runner.py

key-decisions:
  - "抽薄共享 helper（start_orchestration + build_orchestration_engine），workflow 节点与 chat 工具同调一份——落「底层 engine 复用、不造两套」"
  - "helper 只建 session + 构建 engine，不驱动 advance（工作流 waiting_event / chat interrupt 两种运行时不混进 helper）"
  - "chat 挂起复用既有 HITL：clarifying→ask_clarification interrupt marker；researching→deep_analysis fire-and-forget blocking marker，不重实现"
  - "INV-2：chat 自然语言需求 work_item=None + entrypoint=chat 显式可追溯；canonical 融合仍 origin=orchestration，work_item=None 即「自然语言需求」标记"

patterns-established:
  - "Pattern: 入口无关性守护——同一 engine 经两 entrypoint 产结构等价 MergedPlan + 同序 §15 事件（test_orchestration_entry_consistency）"
  - "Pattern: chat @tool 复用既有 interrupt/resume marker，绝不在工具内重写 HITL"

requirements-completed: [ENTRY-02]

# Metrics
duration: ~35min
completed: 2026-06-16
---

# Phase 42 Plan 01: Chat 入口薄封装 Summary

**Chat 经 `start_plan_research` @tool 复用与工作流入口完全相同的 `PlanOrchestrationEngine` 发起多仓方案编排——两入口共用 `start_orchestration` + `build_orchestration_engine` 薄 helper，验证入口无关一致性（结构等价 MergedPlan + 同序 §15 事件），并以 `work_item=None` + `entrypoint=chat` 落地 INV-2。**

## Performance

- **Duration:** ~35 min
- **Completed:** 2026-06-16
- **Tasks:** 3
- **Files modified:** 8 (4 created + 4 modified)

## Accomplishments

- 抽出 `start_orchestration` + `build_orchestration_engine` 薄共享 helper（`plan_orchestration/entrypoint.py`），经 `__init__` curated re-export；Phase 41 `AIPlanResearchNode` 重构为复用同一对 helper，**行为零变更**（节点单测 5 + SC-2 e2e 3 全绿）。
- 新增 `start_plan_research` chat agent 工具（`@tool`，category=PROJECT，space_id/conversation_id 由 MCP 适配层自动注入、LLM 不可见）：建 `entrypoint=chat` + `work_item=None` 的 `PlanSession`，驱动同一 engine 到 done 产 canonical MergedPlan；挂起复用 chat 既有 HITL（ask_clarification interrupt / deep_analysis fire-and-forget marker），不重实现。
- 工具自动注册进 registry + 接线进 chat 工具白名单 `_INDEXED_TOOL_NAMES`（有已索引仓库即可在对话中发起编排）。
- 守护测试 4 类全绿：chat 驱动到 done、SC-2 chat↔workflow 结构等价 MergedPlan + 同序 §15 事件、SC-3/INV-2 null work_item 可追溯、工具注册 + 白名单。
- `makemigrations --check` 干净（无模型变更，无 migration）。

## Task Commits

1. **Task 1: 抽薄共享 helper + 重构 Phase 41 节点** - `0dd05317f` (feat)
2. **Task 2: 加 chat 工具 start_plan_research + 注册接线** - `30b553d4e` (feat)
3. **Task 3: 守护测试（chat 驱动 + SC-2 一致性 + SC-3 INV-2 + 注册）** - `20224d238` (test)

## Files Created/Modified

- `server/services/plan_orchestration/entrypoint.py` (created) - `start_orchestration`（薄包 create_session）+ `build_orchestration_engine`（注入与 Phase 41 完全相同的真实 adapters）
- `server/services/plan_orchestration/__init__.py` (modified) - curated re-export 两 helper
- `server/workflows/nodes/ai/plan_research.py` (modified) - `_create_session` / `_build_engine` 改用共享 helper（行为零变更）
- `server/agents/tools/plan_research_tools.py` (created) - `start_plan_research` @tool（chat 入口薄封装）+ actor/repo 过滤/挂起/终态映射 helper
- `server/agents/tools/__init__.py` (modified) - import + __all__ 导出 `start_plan_research`（含 ruff 导入排序修复）
- `server/agents/chat_runner.py` (modified) - 触发 @tool 注册 import + `_INDEXED_TOOL_NAMES` 加入 `start_plan_research`
- `server/tests/agents/test_start_plan_research_tool.py` (created) - chat 驱动到 done + 注册 + SC-3/INV-2 守护
- `server/tests/services/test_orchestration_entry_consistency.py` (created) - SC-2 入口无关一致性守护

## Decisions Made

- **抽薄 helper（两入口共用）** 而非 chat 工具各造一套：`start_orchestration` 薄包 `PlanSessionService.create_session`（entrypoint 合法性仍由 create_session 校验，helper 不重复校验）；`build_orchestration_engine` 注入与 Phase 41 完全相同的 5 个真实 adapters。落「底层 engine 复用、不造两套」（SC-1）。
- **helper 不驱动 advance**：驱动是入口私有（工作流 `waiting_event` 挂起 / chat interrupt + fire-and-forget），两种入口运行时不混进 helper，保持 helper 入口无关。
- **chat 挂起复用既有 HITL，不重实现**：clarifying（pending clarification）→ 返回 `marker=ask_clarification` interrupt；researching（容器在途）→ 返回 `__blocking_task__` deep_analysis 式 fire-and-forget marker + `register_blocking_task`。engine 状态全持久化 → 跨轮次/回调由既有 chat 机制 resume。
- **INV-2 落地**：chat `work_item=None` + `entrypoint=chat` 显式可追溯；canonical 融合产物仍 `origin=orchestration`（融合 adapter 既有语义），`TechnicalPlan.work_item=None` 即「自然语言需求」标记（DOMAIN §5.1：null + 来源标记，不另设 bool）。
- **真实 LLM/容器端到端 DEFERRED**：沿用既有 deferred，测试在 IO 边界 mock（router/recall/dispatch/synthesizer）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `agents/tools/__init__.py` 导入块排序修复**
- **Found during:** Task 2（工具注册接线）
- **Issue:** 该文件导入块本就 un-sorted（`delivery_knowledge_tools` 错位，I001 预先存在），新增 `start_plan_research` 导入后 `ruff check` 必报 I001，阻塞 Task 2 verify「ruff 干净」。
- **Fix:** 对本就在编辑的导入块跑 `ruff check --fix`（isort 排序，纯排序无语义变更）。
- **Files modified:** server/agents/tools/__init__.py
- **Verification:** `ruff check` 全绿。
- **Committed in:** `30b553d4e`（Task 2 commit）

---

**Total deviations:** 1 auto-fixed (1 blocking — 预先存在 lint 在已编辑文件内顺手收口)
**Impact on plan:** 无范围蔓延；仅排序本就在编辑的导入块。其余按 plan 原样执行。

## Issues Encountered

- 执行中一次误用 `git stash`（用于核对 I001 是否预先存在）导致 `git stash pop` 与 ruff-fix 冲突静默失败，Task 1/2 的已跟踪文件改动被暂存。已经 `git checkout -- <file>` 丢弃冲突的单文件 ruff-only 改动后 `git stash pop` 完整恢复全部改动并核验（无数据丢失），随后改用读工具核对而非 stash。

## Known Stubs

None - chat 工具驱动产出真实 canonical MergedPlan（IO 边界 mock 仅在测试内，生产路径走真实 adapters）。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- v0.7.0 末 phase 收口：chat 与 workflow 双入口经同一 engine 发起方案编排，入口无关一致性已守护。
- 真实 LLM/容器端到端验收沿用既有 deferred（需 runner + Docker + 真实模型）。
- 为 v0.8 多仓 wave 编码提供「对话即可发起 + canonical MergedPlan.execution_plan 拓扑」入口底座。

## Self-Check: PASSED

- FOUND: server/services/plan_orchestration/entrypoint.py
- FOUND: server/agents/tools/plan_research_tools.py
- FOUND: server/tests/agents/test_start_plan_research_tool.py
- FOUND: server/tests/services/test_orchestration_entry_consistency.py
- FOUND commit: 0dd05317f (Task 1), 30b553d4e (Task 2), 20224d238 (Task 3)

---
*Phase: 42-chat*
*Completed: 2026-06-16*
