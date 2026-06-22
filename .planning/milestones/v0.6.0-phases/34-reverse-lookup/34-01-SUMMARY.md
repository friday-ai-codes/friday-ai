---
phase: 34-reverse-lookup
plan: 01
subsystem: api
tags: [reverse-lookup, knowledge-graph, mcp, rest, fail-closed, bi-temporal, rag]

# Dependency graph
requires:
  - phase: 25-chunk-index
    provides: find_chunk_at fail-closed chunk 定位 + ChunkRegistry 行号回填
  - phase: 12-kmod
    provides: graph_store chunk_in_edges/neighbors + KnowledgeEntity/EdgeRelation
  - phase: 33-hdiff
    provides: bi-temporal as-of 默认当前视图（过期 MODIFIES_CHUNK 边排除）
provides:
  - 片段→需求反查 service（services/reverse_lookup.py，纯读、fail-closed、当前视图）
  - REST 端点 GET /api/repositories/<id>/reverse-lookup/（IsAuthenticated）
  - MCP 工具 reverse_lookup_requirements（AccessToken/CookieJWT + IsAuthenticated）
affects: [35-vision, v0.7-comment-trigger, v0.8-coding]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "反查 service 复用 find_chunk_at + graph_store 既有只读接口，零新建底层"
    - "chunk_id 直接入参经 ChunkRegistry 复判 file_path 排除，fail-closed 不绕过安全边界"
    - "REST/MCP 同形结构化契约 {chunks, related_work_items, related_documents, paths}"

key-files:
  created:
    - server/services/reverse_lookup.py
    - server/repositories/reverse_lookup_views.py
    - server/tests/services/test_reverse_lookup.py
    - server/tests/repositories/test_reverse_lookup_view.py
    - server/tests/mcp_tools/test_reverse_lookup_tool.py
  modified:
    - server/repositories/urls.py
    - server/mcp_tools/serializers.py
    - server/mcp_tools/views.py
    - server/mcp_tools/urls.py
    - server/tests/mcp_tools/test_schema_snapshot.py

key-decisions:
  - "反查多跳逐跳 neighbors（非 traverse），方向语义按 §interfaces 核对：code_change←IMPLEMENTED_BY tech_plan←HAS_PLAN work_item→REFERENCES document"
  - "chunk_id 直接入参单独 _resolve_chunk_by_id：ChunkRegistry 取 file_path → 同一 build_matcher_for_repo fail-closed 复判"
  - "MCP view 命名 ReverseLookupView（mcp_tools），tool_name=reverse_lookup_requirements，与 REST 同名类按包隔离，避免歧义"

patterns-established:
  - "反查纯读纪律：service 源码 grep 守护无 add_edge/invalidate/save/upsert/create 写调用"
  - "默认 as_of=None 当前视图天然排除失效边，反查不补建/不写历史"

requirements-completed: [RREF-01]

# Metrics
duration: 22min
completed: 2026-06-15
---

# Phase 34 Plan 01: 片段→需求反查 service + REST + MCP Summary

**纯读片段→需求反查：复用 find_chunk_at + graph_store 反向多跳（chunk←code_change←tech_plan←work_item→document），fail-closed 排除 + 默认当前视图，经 REST(IsAuthenticated) 与 MCP 工具 reverse_lookup_requirements 暴露结构化 {chunks, related_work_items, related_documents, paths}**

## Performance

- **Duration:** ~22 min
- **Started:** 2026-06-15T14:04:00Z
- **Completed:** 2026-06-15T14:26:00Z
- **Tasks:** 3
- **Files modified:** 10 (5 created src/test, 5 modified)

## Accomplishments
- `reverse_lookup` service：给定 (repository_id, file_path, line) 或 chunk_id，反查关联 work_item / document 与多跳路径；纯读、fail-closed、默认当前视图（衔接 Phase 33 as-of）。
- REST 端点 `GET /api/repositories/<id>/reverse-lookup/`（IsAuthenticated，adrf），被排除/无命中与有结果同走 service 不区分存在性。
- MCP 工具 `reverse_lookup_requirements`（McpToolView，AccessToken/CookieJWT + IsAuthenticated），同形结构化返回 + related_* EDGE traces，注册进 mcp_tools 四面（serializer/view/urls/snapshot）。
- 21 个守护用例全绿（9 service + 7 REST + 4 MCP + 1 schema snapshot），覆盖多跳/去重/失效边排除/排除文件 fail-closed（含 chunk_id 直接入参）/部分图谱降级/鉴权/参数校验。

## Task Commits

Each task was committed atomically:

1. **Task 1: reverse_lookup 反查 service（TDD）** - `d709ca49` (feat; test+impl 同提交)
2. **Task 2: ReverseLookup REST 端点** - `85c77ade` (feat)
3. **Task 3: reverse_lookup_requirements MCP 工具** - `88867e66` (feat)

_Note: Task 1 为 tdd 任务，本仓库惯例 test 与 impl 同一原子提交（RED→GREEN 在一次提交内验证）。_

## Files Created/Modified
- `server/services/reverse_lookup.py` - 反查 service：find_chunk_at + chunk_in_edges + 三跳 neighbors，hydrate KnowledgeEntity，组装结构化结果；chunk_id 直接入参 fail-closed 复判。
- `server/repositories/reverse_lookup_views.py` - `ReverseLookupView(APIView)` REST 端点 + 参数校验。
- `server/repositories/urls.py` - 新增 `reverse-lookup/` 路由（紧随 chunk-at，UUID 通配安全）。
- `server/mcp_tools/serializers.py` - `ReverseLookupRequestSerializer` + `TOOL_SCHEMA_SNAPSHOT` 新增条目。
- `server/mcp_tools/views.py` - `ReverseLookupView(McpToolView)` MCP 工具（tool_name=reverse_lookup_requirements）。
- `server/mcp_tools/urls.py` - 注册 `tools/reverse_lookup_requirements/`。
- `server/tests/services/test_reverse_lookup.py` - 9 service 守护用例（含纯读纪律 grep）。
- `server/tests/repositories/test_reverse_lookup_view.py` - 7 REST 守护用例。
- `server/tests/mcp_tools/test_reverse_lookup_tool.py` - 4 MCP 守护用例。
- `server/tests/mcp_tools/test_schema_snapshot.py` - 同步 schema 快照。

## Decisions Made
- 多跳遍历用 `graph_store.neighbors` 逐跳（direction="in"/"out" 按 §interfaces 方向语义），不用 traverse —— 需逐跳取对端实体 id 重建路径，traverse 仅返回 (entity_id, depth)。
- chunk_id 直接入参绕过 find_chunk_at，故单独 `_resolve_chunk_by_id` 查 ChunkRegistry 取 file_path 后经同一排除匹配器 fail-closed 复判（T-34A-02）。
- MCP 工具响应字段直接展开 service 结果 + run_id；related_work_items/related_documents 各组一条 `RetrievalTrace.Kind.EDGE`（source=reverse_lookup）。

## Deviations from Plan

None - plan executed exactly as written.

（plan 列出的 9 个 truths/done 用例与 §interfaces 方向语义全部按原文实现；唯一与模板的次要偏差是 TDD 任务 test+impl 同原子提交而非分两次 commit，遵循本仓库既有 tdd 提交惯例。）

## Issues Encountered
- 纯读审计测试初版因 service docstring 字面包含 `add_edge`/`invalidate_edge`/`save`/`upsert` 被 grep 守护误判；改写 docstring 表述（不再字面列写接口名）即过，保证 plan 的纯读 grep 守护（`grep -v '^#' | grep -cE ... == 0`）真实有效。
- `repositories/urls.py` 与 `mcp_tools/urls.py` 的 import 块在新增导入后触发 ruff I001；仅对所改文件运行 `ruff check --fix`（未 reformat 全树）。

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- RREF-01（片段→需求反查 API/MCP）交付，作 Phase 35 截图召回与 v0.7/v0.8 方案/编码反查底座就绪。
- RREF-02（评论入图）仍由本 phase 的另一 plan 承接（34-02，未在本 plan 范围）。
- 无新 model、无 migration；反查依赖既有图谱边存在（不补建历史边，符合 phase 范围守护）。

## Self-Check: PASSED
- 创建文件均存在（service/views/3 test files）。
- 提交 d709ca49 / 85c77ade / 88867e66 均在 git log。
- 21 测试全绿；ruff 对所改文件全过；纯读 grep == 0。

---
*Phase: 34-reverse-lookup*
*Completed: 2026-06-15*
