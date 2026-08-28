---
phase: 144-capture
plan: "02"
subsystem: knowledge-retrieval
tags: [qdrant, source-kind, session-capture, project-context, pytest]
requires:
  - phase: 144-capture
    provides: Wave 0 向量召回与 packer RED 契约
  - phase: 143-eval
    provides: DOCUMENT/source_kind=session_capture 精华投影
provides:
  - Qdrant source_kind MatchAny 闭集过滤与空列表短路
  - MCP/Chat 可复用的仓库优先会话知识检索 helper
  - 按当前项目收窄且保留全部 DOCUMENT 来源的项目上下文 RAG
affects: [144-04, 144-05, session-knowledge, project-context]
tech-stack:
  added: []
  patterns: [optional source_kinds passthrough, repository-first session recall, inclusive document recall]
key-files:
  created:
    - server/knowledge/session_capture_retrieval.py
    - server/tests/knowledge/test_retrieval.py
    - server/tests/knowledge/test_session_capture_retrieval.py
  modified:
    - server/knowledge/vector_recall.py
    - server/knowledge/retrieval.py
    - server/services/project_context_packer.py
key-decisions:
  - "source_kinds 默认 None，不改变既有交付知识检索召回面；空列表在 embedding 前短路。"
  - "会话专用 helper 固定 repository + DOCUMENT + session_capture，project 仅作可选 AND 收窄。"
  - "项目上下文 RAG 只增加 project_ids 收窄，不使用 session_capture 排他过滤。"
patterns-established:
  - "来源闭集过滤必须进入 Qdrant must，禁止 hydrate 后过滤。"
  - "MCP 与 Chat 会话召回通过 search_session_knowledge 共享同一过滤合同。"
requirements-completed: [RECALL-01, RECALL-02]
duration: 6min
completed: 2026-08-28
---

# Phase 144 Plan 02: 来源闭集与共享会话召回 Summary

**交付 `source_kind` 向量闭集、仓库优先会话知识共享 helper，以及保留既有文档来源的项目级 RAG 收窄。**

## Performance

- **Duration:** 6 min
- **Started:** 2026-08-28T12:00:51Z
- **Completed:** 2026-08-28T12:07:07Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments

- `search_similar` 与 `recall_similar_chunks` 支持可选 `source_kinds`，非空值进入两路 Qdrant `must`，空列表不触发 embedding。
- 新增 `search_session_knowledge`，固定仓库主作用域、可选项目 AND、DOCUMENT 与 `session_capture` 三件套。
- `_layer_rag` 按当前项目收窄，同时继续允许 `session_capture`、项目文档等全部 DOCUMENT 来源。

## Task Commits

1. **Task 1 RED: 检索来源类型透传契约** - `e36c9e9c7` (test)
2. **Task 1 GREEN: 来源类型闭集过滤** - `11de1556a` (feat)
3. **Task 2 RED: 会话知识共享检索契约** - `7ec0719b6` (test)
4. **Task 2 GREEN: 共享 helper 与项目 RAG 收窄** - `ad2c49985` (feat)

## Files Created/Modified

- `server/knowledge/vector_recall.py` - 构造 `source_kind MatchAny`，并在空来源列表时提前返回。
- `server/knowledge/retrieval.py` - 将可选 `source_kinds` 原样下传向量召回。
- `server/knowledge/session_capture_retrieval.py` - 提供 MCP/Chat 共用的会话知识检索合同。
- `server/services/project_context_packer.py` - RAG 层补充当前项目过滤，保留 inclusion 语义。
- `server/tests/knowledge/test_retrieval.py` - 验证显式来源闭集与默认 `None` 的 service 透传。
- `server/tests/knowledge/test_session_capture_retrieval.py` - 验证共享 helper 的完整 kwargs 合同。

## Verification

- `pytest tests/knowledge/test_session_capture_retrieval.py tests/knowledge/test_retrieval.py tests/services/test_project_context_packer.py tests/knowledge/test_vector_recall.py -x --tb=short`：34 passed。
- `ruff check`：全部计划生产文件与新增测试通过。
- IDE lint：计划修改文件无诊断。

## Decisions Made

- 通用检索继续以 `source_kinds=None` 表达不排他，避免默认过滤导致旧调用回归。
- 专用会话 helper 不写 `RetrievalTrace`，由后续 MCP/Chat adapter 按各自关联键留痕。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] 修复触及文件的既有 import 排序**
- **Found during:** Task 2 验证
- **Issue:** `ruff check` 报告 `project_context_packer.py` 局部 import 顺序不符合 I001。
- **Fix:** 仅按 ruff 规则重排同一行 import，不改变运行时行为。
- **Files modified:** `server/services/project_context_packer.py`
- **Verification:** 计划生产文件 `ruff check` 全绿。
- **Committed in:** `ad2c49985`

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** 仅做无行为变化的格式修复，无范围扩张。

## Issues Encountered

- 并发 Plan 03 修改并提交 lookup 相关文件；本计划未触碰其所有权文件，并在每次提交时仅暂存 144-02 文件。
- 一次并行历史 RED 测试与当前测试共用 PostgreSQL 测试库，产生 teardown 占用警告；最终目标套件仍为 34 passed。

## Known Stubs

None. `project_id=None` 是会话 helper 的已决议可选过滤语义，不是占位实现。

## Threat Flags

None. 本计划未新增网络入口、认证路径、schema 或文件访问边界。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 04/05 可直接复用 `search_session_knowledge` 接入 MCP 与 Chat，无需重复拼接过滤条件。
- `source_kinds` 已在 Qdrant `must` 层闭集过滤，`allowed_projects` fail-closed 与无项目仓库逃生支保持不变。

## Self-Check: PASSED

- 6 个计划代码/测试文件均存在。
- 4 个 TDD 原子提交均可在 git 历史中定位。

---
*Phase: 144-capture*
*Completed: 2026-08-28*
