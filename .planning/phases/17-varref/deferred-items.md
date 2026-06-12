# Phase 17 Deferred Items

发现于执行过程、超出当前任务范围、未修复的事项：

- **[17-02] `server/tests/workflows/test_template_loader.py` 存量 ruff F401**：`Path` / `WorkflowEdge` / `WorkflowNode` 三个未使用导入在 HEAD 即存在（已用 `git show HEAD` 核实为存量问题），与本计划改动无关，未顺手修复。可在任意清理任务中 `ruff check --fix` 解决。
- **[17-02 已知缺口，计划内记录] 工作流导入路径（`Workflow.from_json`）不设置 short_id，导入即漂移**：按 ROADMAP 本阶段只锁 bulk-update，移交 Phase 20（RESEARCH OQ#2 已 RESOLVED）。
