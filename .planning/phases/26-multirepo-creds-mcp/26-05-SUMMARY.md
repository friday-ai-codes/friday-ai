---
phase: 26-multirepo-creds-mcp
plan: 05
subsystem: mcp-tools
tags: [mcp, rag, multi-repo, fail-closed, exclusion, REPO-02]

# Dependency graph
requires:
  - phase: 22-fail-closed
    plan: 03
    provides: "search_rag 单一 chokepoint：per-repo build_matcher_for_repo fail-closed + 每项打 repository_id"
provides:
  - "search_rag_chunks 多仓 / 全仓检索参数（repository_ids / all_repositories / max_repos）"
  - "跨多仓合并召回 + 每项来源仓库标注（item.repository_id）"
  - "省略多仓参数维持既有单仓行为与响应形状（向后兼容）"
affects: [MCP RAG 调用方（agent/feishu 技术方案/跨仓检索）]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "MCP 多仓范式：repository_id 单仓便捷参数 + repository_ids 显式多仓 + all_repositories 全量（受 max_repos 限制），serializer.validate 产出 target_repository_ids（mirror grep_repository）"
    - "多仓 RAG 经一次 HybridSearchService.search(repository_ids=[...]) → search_rag chokepoint，每仓 fail-closed 排除复用 Phase 22，view 不绕过直读向量库"
    - "来源仓库标注取 item.repository_id（search_rag 已逐项打），非 view 硬编码单仓"

key-files:
  created:
    - server/tests/mcp_tools/test_search_rag_multi_repo.py
  modified:
    - server/mcp_tools/serializers.py
    - server/mcp_tools/views.py
    - server/tests/mcp_tools/test_schema_snapshot.py

key-decisions:
  - "repository_ids max_length=20 与 max_repos 上限对齐（grep 用 10），控跨仓上限（T-26-21）"
  - "多仓模式标量 repository_id / branch 输出置 None，新增 repository_ids 回显实际检索范围；单仓保留标量字段向后兼容"
  - "测试设 ENABLE_GRAPHRAG_ENRICHMENT=False 强制走 _search_rag_only → search_rag，经真实 build_matcher_for_repo 验证排除（非绕过过滤层）"

requirements-completed: [REPO-02]

# Metrics
duration: ~12min
completed: 2026-06-15
---

# Phase 26 Plan 05: search_rag_chunks 多仓 / 全仓检索参数 Summary

**为 MCP RAG 检索工具 `search_rag_chunks` 增加多仓（`repository_ids`）/ 全仓（`all_repositories`，受 `max_repos` 限制）检索参数，跨多仓合并召回并按 `item.repository_id` 标注结果来源仓库；多仓解析严格对齐 `grep_repository` 范式（serializer 产出 `target_repository_ids`，view 逐仓校验 + 一次性 `HybridSearchService.search(repository_ids=valid_ids)`），每仓仍经 Phase 22 `search_rag` chokepoint `build_matcher_for_repo` fail-closed 排除——被排除文件跨仓不可见；省略多仓参数时维持既有单仓行为与响应形状（向后兼容）。**

## Performance

- **Duration:** ~12 min
- **Tasks:** 3
- **Files modified:** 4（1 新增测试 + serializer + view + schema 快照测试同步）

## Accomplishments
- `SearchRagChunksRequestSerializer`：`repository_id` 改可选（单仓便捷参数）+ 新增 `repository_ids`（ListField，`max_length=20`）/ `all_repositories` / `max_repos`（默认 10，上限 20）；`validate` 复用 grep 写法构建 `target_repository_ids`（`repository_id` 去重插头部），三者缺失报中文错误，`branch` 仅单仓允许；同步 `TOOL_SCHEMA_SNAPSHOT["search_rag_chunks"]` request/response 字段。
- `SearchRagChunksView.post`：解析 `target_repository_ids`；`all_repositories` 时列 `is_deleted=False, index_status=INDEXED` 仓 `order_by("name")[:max_repos]`（无则 404）。逐仓 `_get_indexed_repo` 校验——单仓失败保留旧 404/400，多仓不存在/未索引仓跳过（不越权、不致命）。**一次** `HybridSearchService(get_provider()).search(repository_ids=valid_ids, ...)`，复用 `search_rag` 每仓 fail-closed 排除 + 跨仓合并去重，不在 view 再循环各仓、不绕过 chokepoint。结果每项来源仓库取 `item.repository_id`（search_rag 已逐项打），分支标签单仓取 `graph_branch`、多仓取该仓 base 分支；输出新增 `repository_ids` 回显实际检索范围，单仓保留 `repository_id`/`branch` 标量字段。
- 守护测试 5 例（`test_search_rag_multi_repo.py`）经真实 `build_matcher_for_repo`：多仓召回 + 来源标注 / 跨仓 fail-closed（`config/secret.json` 内置默认排除跨仓不可见）/ 单仓向后兼容 / `all_repositories` 仅已索引非删除仓 / 不存在仓跳过——全绿。
- 回归：`tests/services/test_retrieval_exclusion.py tests/mcp_tools/` 90 passed（含既有单仓 search_rag、schema 快照、跨工具 fail-closed 守护未破）。

## Task Commits

1. **Task 1: serializer 多仓参数 + schema 快照** - `b360d8c69` (feat)
2. **Task 2: view 多仓解析 + 合并检索 + 来源标注** - `db1223306` (feat)
3. **Task 3: 多仓守护测试 + schema 快照测试同步** - `3e31c4e81` (test)

## Files Created/Modified
- `server/mcp_tools/serializers.py` - `SearchRagChunksRequestSerializer` 多仓参数 + `validate` 产出 `target_repository_ids` + `TOOL_SCHEMA_SNAPSHOT` 同步。
- `server/mcp_tools/views.py` - `SearchRagChunksView.post` 多仓解析 + 一次性合并检索 + 来源仓库标注（顺带修复本文件 pre-existing ruff I001 import 排序）。
- `server/tests/mcp_tools/test_search_rag_multi_repo.py` - 多仓 / 全仓 / fail-closed / 单仓兼容 / 范围 5 例守护测试（新增）。
- `server/tests/mcp_tools/test_schema_snapshot.py` - `search_rag_chunks` schema 快照同步多仓参数。

## Decisions Made
- **`repository_ids` max_length=20**：与 `max_repos` 上限对齐（grep 用 10），控跨仓检索上限（T-26-21 DoS）。
- **多仓标量字段置 None**：多仓模式输出 `repository_id`/`branch` 标量为 `None`，新增 `repository_ids` 回显实际检索范围；单仓保留标量字段不破坏既有调用方契约。
- **测试经真实 chokepoint**：`ENABLE_GRAPHRAG_ENRICHMENT=False` 强制 `_search_rag_only` → `search_rag`，仅 mock embedding/sparse/`BranchAwareSearchService.search` 重型副作用，`build_matcher_for_repo` 用真实实现，验证排除走真实过滤层而非绕过。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] views.py pre-existing ruff I001 import 排序**
- **Found during:** Task 2（`uv run ruff check mcp_tools/views.py` verify gate）
- **Issue:** `mcp_tools/views.py` 顶部 import 块存在 pre-existing I001（import 未排序，HEAD 上即存在，非本 plan 引入），阻塞 plan 明确的 ruff verify gate。
- **Fix:** `ruff check --fix mcp_tools/views.py` 仅整理 import 顺序（first-party 与 local `.` import 分组），不改任何逻辑。
- **Files modified:** server/mcp_tools/views.py
- **Verification:** `ruff check mcp_tools/views.py` 干净；既有单仓 search_rag 测试 + 90 例回归全绿。
- **Committed in:** db1223306（Task 2 提交）

**2. [Rule 3 - Blocking] test_schema_snapshot 需同步新 schema**
- **Found during:** Task 3（回归 `tests/mcp_tools/`）
- **Issue:** Task 1 改 `search_rag_chunks` schema 后，`test_schema_snapshot.py` 的 golden 断言失配（plan files_modified 未列该测试，但同步是保持回归绿的必需项）。
- **Fix:** 更新 `test_schema_snapshot.py` 的 `search_rag_chunks` request/response 字段，与 `TOOL_SCHEMA_SNAPSHOT` 一致。
- **Files modified:** server/tests/mcp_tools/test_schema_snapshot.py
- **Verification:** `tests/mcp_tools/` 全绿。
- **Committed in:** 3e31c4e81（Task 3 提交）

---

**Total deviations:** 2 auto-fixed（均为保持 verify gate / 回归绿所必需，无范围蔓延）
**Impact on plan:** 多仓每仓 fail-closed 排除语义未削弱，访问范围（已索引非删除仓）未扩大；单仓行为/响应形状向后兼容。

## Threat Surface Notes
- T-26-18（跨仓被排除文件泄漏）：view 不绕过 `search_rag`，跨仓排除由 chokepoint 逐仓 `build_matcher_for_repo` 保证，Test 2 守护。
- T-26-19（检索越权仓库）：target 仅取存在 + INDEXED + 非删除仓（复用 grep 访问模型），不存在仓跳过，Test 4/5 守护。
- T-26-21（全仓检索成本）：`max_repos`（默认 10，上限 20）+ `repository_ids` max_length=20 控上限。
- 无新增网络端点 / auth 路径 / schema 变更，未引入计划外威胁面。

## Self-Check: PASSED
