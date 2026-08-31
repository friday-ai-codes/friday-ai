# Phase 100 — Deferred Items

## 既有失败（与 100-01 无关，不在本 plan 修复范围）
- status: acknowledged


- `tests/knowledge/test_triggers.py::TestWorkflowTriggers::test_workflow_plan_generation_delivers_on_success`
- `tests/knowledge/test_triggers.py::TestWorkflowTriggers::test_workflow_plan_generation_survives_runner_failure`

两用例均因 `ModuleNotFoundError: No module named 'workflows.nodes.ai.plan_generation'` 失败：
该模块在 Chassis v2 重构提交 `21116667`（`feat(workflow): 工作流底盘重构 Chassis v2`）中被移除，
而这两个 knowledge 触发器测试仍 import 它。属重构遗留的测试腐化，与 100-01 改动
（EntityKind 扩展 / migration 0008 / vector_recall 过滤）无关，需另行清理或随
工作流侧后续 phase 一并处理。
