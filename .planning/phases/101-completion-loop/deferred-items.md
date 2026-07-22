# Phase 101 Deferred Items

执行中发现、超出当前 plan 范围的问题（不修，仅记录）。

## 101-03 执行时发现

- **存量腐坏测试**：`server/tests/test_sub_step_coding_node.py::test_plan_generation_node_still_works`
  引用不存在的模块 `workflows.nodes.ai.plan_generation`（模块早已删除，测试未随删）。
  与 101-03 改动无关（`git stash` 前后同样失败——ModuleNotFoundError）。
  建议：删除该用例或改为引用现存节点。
