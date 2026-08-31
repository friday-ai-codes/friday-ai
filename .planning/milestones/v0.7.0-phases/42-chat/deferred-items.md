# Phase 42 — Deferred / Out-of-Scope Items

## Chat 入口 plan_research 容器完成 → 重新驱动 engine / resume chat graph（接线缺口，WR-01）
- status: acknowledged


- **Gap:** chat 发起的编排进入 RESEARCHING 且容器在途时，`start_plan_research`
  返回 deep_analysis 式 `__blocking_task__` marker 并 `register_blocking_task`，但**没有任何
  消费者**为 chat 入口在调研容器完成后重新驱动 engine（researching→merging→done）或用
  `blocking_results` resume chat graph 的 `waiting_node` interrupt。
- **Why:** resume 实际接线对 chat 入口未打通——`_schedule_agent_session_resume`
  （`server/subagent/api/callbacks.py`）对 `task_type=="plan_research"` 短路（barrier 唯一驱动），
  而 `_schedule_workflow_resume` 仅在有 `node_execution` 时驱动，chat 入口无 `node_execution_id`
  （`build_orchestration_engine()` 不传）→ `no_node_execution_skip_resume`。深入调研路径的 chat
  编排会在 WAITING 阶段静默挂起、不会自动回流。
- **Status:** 显式 deferred（与 Phase 39/40/41 真实 LLM/容器 E2E resume deferred 决策一致，IO 边界
  mock）。本 phase 已将工具 placeholder / description 文案如实化（不再承诺自动继续，WR-01）。
- **Future wiring（待接入）:** 在 barrier 完成回调中，对无 `node_execution` 的 `plan_research`
  容器，按 `session_id` 关联 conversation，调度一次 engine 续驱 + chat graph resume（注入
  `blocking_results`）。

## Pre-existing test failure (out of scope, not introduced by 42-01)
- status: acknowledged


- **Test:** `server/tests/agents/test_tool_contracts.py::test_search_repository_code_input_schema_snapshot`
- **Symptom:** snapshot 描述文本漂移 —— 期望 `'implementation 灰度切换时...'` vs 实际
  `'Phase 灰度切换时...'`（`search_repository_code` 工具 description 与冻结 fixture 不一致）。
- **Why out of scope:** 与 ENTRY-02 薄封装无关 —— 未触碰 `space_tools.py`、`search_repository_code`
  或任何 contract fixture；新增 `start_plan_research` 工具未触发任何 contract guard
  （同次运行 13 passed，仅此 1 例 search_repository_code 快照失败）。预先存在的快照漂移。
- **Action:** 不在本 phase 修复（SCOPE BOUNDARY：仅修复本 task 改动直接引入的问题）。
