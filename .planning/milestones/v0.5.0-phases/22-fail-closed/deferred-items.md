# Phase 22 — Deferred / Out-of-Scope Items

记录执行期发现但**不属于本任务直接改动**的预存问题（per executor SCOPE BOUNDARY）。

## Plan 22-03
- status: acknowledged


- **预存 contract drift**：`tests/agents/test_tool_contracts.py::test_search_repository_code_input_schema_snapshot`
  在干净树（stash 掉本 plan 改动后）即 FAILED——`server/agents/tools/schemas/search_repository_code.py`
  docstring 含占位词 `implementation 灰度切换时`，与 fixture baseline `Phase 灰度切换时` 漂移。
  本 plan 未触碰该 schema 文件，属预存问题。修复方式：核对 docstring 后按提示重生成 fixture
  (`python -m tests.agents._generate_contract_fixtures`)。
- **预存 ruff F541**：`server/agents/tools/space_tools.py` `_diagnose_empty_search` 内一处
  无占位符 f-string（HEAD 即存在）。本 plan 未改该函数；为遵守"只改本任务相关代码"未顺手修。
- **RAG 旁路读取面（超出本 plan 范围，需后续 plan 覆盖）**：plan 22-03 verification 假设
  `search_rag` 是 `BranchAwareSearchService.search` 的唯一调用方，实际仍有两处直读旁路**未过滤
  被排除文件**，是 EXCL-02 fail-closed 缺口：
  - `server/repositories/index_views.py:720` `_vector_search`（仓库搜索 API 直读 RAG，返回 content）。
  - `server/codegraph/services/layered_search.py:241` `LayeredSearchService._l3_hybrid_search`
    （已标记 deprecated，但仍可经 compat 路径返回 RAG 结果）。
  二者均不经 `search_rag`，被排除文件可漏出。建议在收尾 plan 给这两处挂同一 `build_matcher_for_repo`
  过滤（或迁移到 `search_rag`）。本 plan 严守 files_modified 边界未扩改。
