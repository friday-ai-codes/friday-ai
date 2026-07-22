# Phase 104 Deferred Items

## 104-01 执行期间发现（范围外，未修改）

- `tests/mcp_tools/test_work_item_execution.py` 5 例失败（`test_execute_work_item_repo_tasks_records_partial_multi_repo_results`、`test_execute_work_item_repo_tasks_reports_partial_when_feishu_writeback_fails`、`test_execute_tasks_schedules_learning_case_extraction`、`test_execute_tasks_extraction_failure_does_not_affect_result`、`test_execute_tasks_ingestion_and_writeback_bind_initiated_user`）：
  `TypeError: _dispatch_execution() got an unexpected keyword argument 'initiating_user'`。
  由 Phase 103-01（`48f98efd`，dispatch_execution 签名加 `initiating_user`）引入，测试内 fake `_dispatch_execution` 未同步签名。与 104-01 改动（improve 收敛/serializer/snapshot）无关，属既有 rot，留待独立修复。
