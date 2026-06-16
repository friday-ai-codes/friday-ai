# Phase 42 — Deferred / Out-of-Scope Items

## Pre-existing test failure (out of scope, not introduced by 42-01)

- **Test:** `server/tests/agents/test_tool_contracts.py::test_search_repository_code_input_schema_snapshot`
- **Symptom:** snapshot 描述文本漂移 —— 期望 `'implementation 灰度切换时...'` vs 实际
  `'Phase 灰度切换时...'`（`search_repository_code` 工具 description 与冻结 fixture 不一致）。
- **Why out of scope:** 与 ENTRY-02 薄封装无关 —— 未触碰 `space_tools.py`、`search_repository_code`
  或任何 contract fixture；新增 `start_plan_research` 工具未触发任何 contract guard
  （同次运行 13 passed，仅此 1 例 search_repository_code 快照失败）。预先存在的快照漂移。
- **Action:** 不在本 phase 修复（SCOPE BOUNDARY：仅修复本 task 改动直接引入的问题）。
