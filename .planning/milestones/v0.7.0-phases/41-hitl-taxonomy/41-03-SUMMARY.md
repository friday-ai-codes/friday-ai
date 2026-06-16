---
phase: 41-hitl-taxonomy
plan: 03
subsystem: orchestration
tags: [workflow-node, ai-plan-research, engine-entry, node-fixture, e2e, plan-orchestration]

requires:
  - phase: 41-01
    provides: §15 事件持久化
  - phase: 41-02
    provides: ClarifyAdapter + engine._clarify
  - phase: 36-40
    provides: PlanSession + engine + router/recall/research/merge adapters
provides:
  - AIPlanResearchNode 工作流入口节点（auto-registered，config_schema/ports SSOT）
  - 端到端编排驱动（建 session → 注入真实 adapters → engine.advance → 终态/挂起映射）
  - SC-2 端到端编排测试（IO 边界 mock）+ 澄清回路 e2e（仅 affected partial 重跑）
  - 刷新 node fixture（含 ai_plan_research，前后端漂移守护绿）
affects: [42, v0.8]

tech-stack:
  added: []
  patterns:
    - "工作流入口节点驱动 engine.advance；clarifying/researching 处复用 waiting_event 挂起"
    - "节点 _build_engine 抽出可测试 override（生产默认真实 adapter）"
    - "engine 驱动循环最大步数防活锁"

key-files:
  created:
    - server/workflows/nodes/ai/plan_research.py
    - server/tests/workflows/test_plan_research_node.py
    - server/tests/services/test_plan_research_e2e.py
  modified:
    - server/workflows/nodes/ai/__init__.py
    - server/services/plan_orchestration/research_adapter.py
    - web/src/types/workflow/__fixtures__/node-types.fixture.json

key-decisions:
  - "节点继承 AIAgentBaseNode 复用 plumbing 但覆盖 execute（engine 驱动，不走 LangChain loop）"
  - "research_adapter dispatch session_id 附 uuid 后缀（修 stale 重派 AgentSession UNIQUE 冲突，Rule 1）"
  - "async DB e2e/node 测试用 django_db(transaction=True)（对齐 callback 测试，避免跨测试脏读）"

patterns-established:
  - "Pattern: 工作流节点 = engine 入口；session_id 持久化于节点 output 支持 resume"
  - "Pattern: e2e 真实 engine+service，仅 IO 边界（router/recall LLM、容器调度/回调、merge synth）mock"

requirements-completed: [ENTRY-01]

duration: ~40min
completed: 2026-06-16
---

# Phase 41 Plan 03: 工作流入口端到端 Summary

**AIPlanResearchNode 把整条编排端到端串起：从需求建 PlanSession(entrypoint=workflow) 注入真实 adapters 驱动 engine.advance，经 拆分→路由→召回→澄清→并行调研→融合 产出带跨仓依赖的 canonical MergedPlan；clarifying/researching 处复用既有 waiting_event 挂起恢复。**

## Performance
- **Tasks:** 3
- **Files modified:** 6（3 created + 3 modified）
- **Completed:** 2026-06-16

## Accomplishments
- `AIPlanResearchNode`（`workflows/nodes/ai/`，auto-registered）：建/恢复 session + 注入真实 adapters 驱动 engine + 终态/挂起映射
- clarifying（pending clarification）/ researching（在途调研）→ `waiting_event`（复用 ask_user_question 卡片 / 容器回调 resume，无新 HITL infra）
- 节点 config_schema + ports SSOT 经 `/api/node-types/` 自动渲染（无新 Vue 组件）；刷新 node fixture（34 节点，含 ai_plan_research）
- SC-2 端到端测试：需求 → 六段编排 → 带跨仓依赖 MergedPlan（dependency_dag + execution_plan[].dependencies）+ §15 事件覆盖
- 澄清回路 e2e：merge 验证失败 → 澄清（affected=taskA）→ answer → 仅 taskA 重跑、taskB 复用 → done

## Task Commits
1. **Task 1: AIPlanResearchNode + auto-register** - `(feat 41-03 T1)` + docstring fix `(fix 41-03)`
2. **Task 2: 节点单测 + node fixture 刷新** - `(test 41-03 T2)`
3. **Task 3: SC-2 端到端测试 + stale 重派冲突修复** - `(test 41-03 T3)`

## Decisions Made
- 节点继承 `AIAgentBaseNode` 复用 provider/挂起 plumbing 但**覆盖 execute** 走 engine 推进（不走 LangChain agent loop）；abstract get_system/user_prompt 提供占位空实现。
- `_build_engine(context, session)` 抽出独立方法，生产默认真实 adapters，测试 monkeypatch override 在 IO 边界注入 mock。
- async DB 测试统一 `django_db(transaction=True)`（对齐 `test_research_completion_callback`），避免 async ORM 跨测试脏读。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] research_adapter stale 重派 session_id 冲突**
- **Found during:** Task 3（澄清回路 e2e）
- **Issue:** `ResearchDispatchAdapter._dispatch_deep_task` 用确定性 `session_id=f"research-{task.id.hex[:12]}"`；stale 重派（澄清 affected 重跑 / 重索引）对同一 task 再次 dispatch 撞 `agents_agentsession.session_id` UNIQUE，单仓失败隔离把 task 误标 failed——破坏 §14 affected 重跑（SC-1）。
- **Fix:** session_id 附 `uuid4().hex[:6]` 后缀；回调侧经 `last_output.research_task_id` 反查 task（不依赖 session_id 命名），后缀不影响幂等/回调路由。
- **Files modified:** server/services/plan_orchestration/research_adapter.py
- **Verification:** 澄清回路 e2e（仅 affected 重跑 → done）绿；research_adapter/callback 既有套件无回归（22 passed）。

**2. [Rule 1 - Bug] 节点 suspend 返回值误用下标 + INV-6 docstring 误判**
- **Found during:** Task 2
- **Issue:** execute 内 `suspend["output"]`（NodeResult 不可下标）；docstring 含 `PlanSession(` 触发 INV-6 源码守护误报。
- **Fix:** 改 `suspend.output`；docstring 改 `PlanSession``（entrypoint=workflow）`。
- **Files modified:** server/workflows/nodes/ai/plan_research.py
- **Verification:** 节点测试 + INV-6 plan_session 守护绿。

**Total deviations:** 2 auto-fixed (2 bug)
**Impact on plan:** stale 重派修复是 SC-1 端到端成立的必要修正（编排可靠性）；其余为接线 bug。无 scope 蔓延。

## Issues Encountered
- async DB 测试跨测试脏读 → 统一 `transaction=True`（既有约定）。

## Verification Results
- `tests/workflows/test_plan_research_node.py`（5）+ `tests/services/test_plan_research_e2e.py`（2）全绿。
- 前后端漂移守护 `node-sync.test.ts`（5）绿（fixture 含 ai_plan_research）。
- 全量回归：tests/workflows 504 passed、tests/delivery 298+ passed、Phase 41 套件 63 passed。
- `makemigrations --check` 干净（本 plan 不新增迁移）；engine 纯度 + INV-6 守护绿；`ruff` 通过。
- 真实 LLM/容器 E2E deferred（IO 边界 mock，沿用 39/40 决策）。

## Next Phase Readiness
- engine 入口无关性已验证（工作流为第一个真实入口）；Phase 42 Chat 入口可薄封装复用同一 engine + adapters。

---
*Phase: 41-hitl-taxonomy*
*Completed: 2026-06-16*
