# Phase 17 Deferred Items
- status: acknowledged


发现于执行过程、超出当前任务范围、未修复的事项：

- **[17-02] `server/tests/workflows/test_template_loader.py` 存量 ruff F401**：`Path` / `WorkflowEdge` / `WorkflowNode` 三个未使用导入在 HEAD 即存在（已用 `git show HEAD` 核实为存量问题），与本计划改动无关，未顺手修复。可在任意清理任务中 `ruff check --fix` 解决。
- **[17-02 已知缺口，计划内记录] 工作流导入路径（`Workflow.from_json`）不设置 short_id，导入即漂移**：按 ROADMAP 本阶段只锁 bulk-update，移交 Phase 20（RESEARCH OQ#2 已 RESOLVED）。
- **[17-04] 后端全量冒烟有 113 个 workflows 之外的失败**（orchestration/coding-session/chat/codegraph-retrieval 等子系统，详见 17-04-SUMMARY「全量冒烟分诊」）：失败测试文件零引用 workflows 模块，且与并发会话未提交的工作区改动（`agents/llm_factory.py`、`codegraph/*`、`knowledge/llm_grader.py`、`repositories/summary_service.py`、`subagent/api/callbacks.py` 等）属同一子系统，与 Phase 17 无关，未处置。待该并发会话收敛后复跑确认。
