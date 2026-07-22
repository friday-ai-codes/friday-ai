# Phase 101 Deferred Items

执行中发现、超出当前 plan 范围的问题（不修，仅记录）。

## 101-03 执行时发现

- **存量腐坏测试**：`server/tests/test_sub_step_coding_node.py::test_plan_generation_node_still_works`
  引用不存在的模块 `workflows.nodes.ai.plan_generation`（模块早已删除，测试未随删）。
  与 101-03 改动无关（`git stash` 前后同样失败——ModuleNotFoundError）。
  建议：删除该用例或改为引用现存节点。

## 101-04 执行时发现

- **第三处摄取投递缺归因**：`server/mcp_tools/work_item_execution_service.py`
  `execute_work_item_repo_tasks` 末尾的 `mcp_technical_plan`/`mcp_tasks_executed` 投递
  （Phase 13 旧点）同样未传 `initiated_by_user_id`。100-REVIEW LO-02 仅点名 2 处 service
  层投递（本次已按指示补齐那 2 处），此第三处未被点名故不越权修改。函数内 L595 已有
  `initiated_by` 变量，补传是一行改动。建议：下次触碰该文件时顺手补齐。
