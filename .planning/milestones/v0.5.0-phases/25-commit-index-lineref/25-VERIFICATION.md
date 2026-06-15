---
phase: 25-commit-index-lineref
verified: 2026-06-15T07:32:00Z
status: passed
score: 15/15 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: none
  note: initial verification
---

# Phase 25: Commit 历史索引 + 行号反查 Verification Report

**Phase Goal:** commit 历史可检索 + 行级 → chunk 反查打底。
**Verified:** 2026-06-15T07:32:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Roadmap Success Criteria

| # | Success Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | commit message/author/变更 可被语义检索召回 | ✓ VERIFIED | `commit_index.py::index_commits` 构建含 message+author+committed_at+变更路径摘要的文档，embedding 入主 collection 打 `kind=commit` payload + 合成 `file_path=.friday/commits/{sha}`；`_run_commit_index` 挂接进 `clone_and_index_repository`；`search_rag` chokepoint 存在且未改（commit 文档经既有入口自然召回）；集成测试 `test_commit_index_integration.py` 用真实 `build_matcher_for_repo` 经过 search_rag 排除/去重链路断言关键字/author 召回 |
| 2 | ChunkRegistry.line_start/line_end 回填；file:line → chunk_id API 可用 | ✓ VERIFIED | `_build_points` 透传 `chunk.start_line/end_line`；`_bulk_upsert_registry_atomic` create+update 双路径落库；`find_chunk_at` 区间命中 + fail-closed；`GET /api/repositories/<id>/chunk-at/` 路由注册 + 认证保护 |

### Observable Truths (merged from PLAN must_haves)

| #   | Truth   | Status     | Evidence       |
| --- | ------- | ---------- | -------------- |
| 1 | 新索引每个 ChunkRegistry row 携带 1-based 闭区间 line_start/line_end | ✓ VERIFIED | `indexer.py:3340-3341` `_build_points` 取 `chunk.start_line/end_line`（`code_chunk.py:24-25,53-54` 1-based 闭区间）；`types.py:42-43` 键存在 |
| 2 | 重切分时 line_start/line_end 被更新而非保留旧值 | ✓ VERIFIED | `indexer.py:3217-3228` `line_changed` 判定 + update_fields 含 line 字段；测试 `test_upsert_update_refreshes_line_fields_when_only_lines_move` 绿 |
| 3 | 历史未回填 row 仍可为 NULL（向后兼容） | ✓ VERIFIED | `models.py:62-63` PositiveIntegerField null=True；CheckConstraint `chunkreg_line_range_valid` 允许任一 NULL（`models.py:86-94`） |
| 4 | find_chunk_at 返回覆盖该行的 chunk_id（line_start<=line<=line_end） | ✓ VERIFIED | `chunk_lookup.py:91-99` 闭区间 filter；`:80` 按区间宽度升序最具体优先 |
| 5 | 被排除文件的 chunk-at 查询 fail-closed | ✓ VERIFIED | `chunk_lookup.py:51-74` matcher 构造异常/normalize None/is_excluded 三段均返回 `[]` + 埋点 |
| 6 | GET chunk-at 返回 chunk_id 及行范围，认证保护 | ✓ VERIFIED | `chunk_at_views.py:27` `IsAuthenticated`；`:32-52` 参数校验 400；`:60` 返回 chunks；`urls.py:255-257` 路由 |
| 7 | 被排除文件与无命中对外不可区分（无存在性泄漏） | ✓ VERIFIED | `chunk_at_views.py:56-60` 两情形统一 `{"chunks": []}` 200；测试 `test_excluded_file_no_existence_leak` 绿 |
| 8 | commit message/author/变更摘要构建为 RAG 文档 embedding 入 Qdrant，payload kind=commit | ✓ VERIFIED | `commit_index.py:289-304` payload；`:309-347` embedding+upsert |
| 9 | 被排除文件不出现在 commit 变更摘要中（fail-closed） | ✓ VERIFIED | `commit_index.py:168-186` `_filter_changed_files` 复用 22 matcher，判定异常视为排除；测试 `test_excluded_file_not_in_summary` 绿 |
| 10 | 增量：仅索引 boundary..HEAD 的新 commit；二次同 HEAD 不重复 | ✓ VERIFIED | `commit_index.py:117-153` `boundary..HEAD` / 首轮 bounded 回退；`:263-272` 无新 commit 返回 0；测试 `test_incremental_only_new_commits` 绿 |
| 11 | 大 diff/超长变更摘要经既有截断 helper 截断 | ✓ VERIFIED | `commit_index.py:196-198` `truncate_diff_lines`（`git_platform/base.py:8`） |
| 12 | 全量与增量索引完成后（rmtree 前）触发 commit 索引 | ✓ VERIFIED | `indexer.py:3748-3752` `if not branch:` 块内 `_run_sensitive_detection` 后、`return` 前；finally rmtree `:3803` |
| 13 | commit 索引失败绝不阻断既有索引 success（best-effort） | ✓ VERIFIED | `indexer.py:3391-3416` `_run_commit_index` try/except 仅 warning；测试 dispatch 失败不冒泡绿 |
| 14 | search_rag 用关键字/author 召回到对应 commit 文档 | ✓ VERIFIED | `search_rag` chokepoint 存在（`rag_search.py:30`）；commit 文档落主 collection 经既有入口召回；集成测试经真实排除链路断言召回 |
| 15 | 二次索引同 HEAD 不新增 commit 文档（增量边界正确） | ✓ VERIFIED | uuid5 确定性 point id（`commit_index.py:211-213`）；upsert 成功才推进 boundary（`:347-357`）；集成测试断言增量 +1 |

**Score:** 15/15 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | ----------- | ------ | ------- |
| `server/code_relations/types.py` | ChunkRegistryRow line_start/line_end | ✓ VERIFIED | 键 + docstring 存在（`:27-43`） |
| `server/services/indexer.py` | _build_points 透传 + _bulk_upsert create+update 落库 | ✓ VERIFIED | `:3340-3341`, `:3209-3238`；wiring `:3752` |
| `server/services/chunk_lookup.py` | find_chunk_at service | ✓ VERIFIED | 闭区间命中 + fail-closed，exports `find_chunk_at` |
| `server/repositories/chunk_at_views.py` | ChunkAtView APIView | ✓ VERIFIED | IsAuthenticated + 参数校验 + 无泄漏 |
| `server/repositories/urls.py` | chunk-at 路由 | ✓ VERIFIED | `:255-257` `<uuid:repository_id>/chunk-at/` |
| `server/services/commit_index.py` | index_commits 摄取服务 | ✓ VERIFIED | 完整 git log→过滤→截断→embedding→upsert→边界推进 |
| `server/repositories/migrations/0035_*.py` | boundary AddField nullable | ✓ VERIFIED | 单 AddField，null=True，依赖 0034 |
| `server/repositories/models.py` | commit_index_boundary_sha 独立字段 | ✓ VERIFIED | `:225` 独立于 `:220` last_indexed_commit_sha |

### Key Link Verification

| From | To | Via | Status |
| ---- | --- | --- | ------ |
| `_build_points` | `ChunkRegistry.line_start/line_end` | registry_rows → `_bulk_upsert` get_or_create/save | ✓ WIRED |
| `ChunkAtView` | `find_chunk_at` | `await find_chunk_at(...)` | ✓ WIRED (`chunk_at_views.py:57`) |
| `find_chunk_at` | `build_matcher_for_repo` | fail-closed 排除判定 | ✓ WIRED (`chunk_lookup.py:52`) |
| `index_commits` | `build_matcher_for_repo` | 变更摘要 fail-closed 过滤 | ✓ WIRED (`commit_index.py:274`) |
| `index_commits` | `QdrantService.upsert_vectors` | commit point embedding 入库 | ✓ WIRED (`commit_index.py:347`，返回 bool 严格判定) |
| `clone_and_index_repository` | `index_commits` | rmtree 前 best-effort await | ✓ WIRED (`indexer.py:3752`) |
| commit 文档 (kind=commit) | `search_rag` | 既有 chokepoint 召回 | ✓ WIRED（合成 file_path 不被排除，chokepoint 存在未改） |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| 全部 phase 测试 | pytest (5 test files) | 43 passed, 18 warnings | ✓ PASS |
| 无残留 migration diff | makemigrations --check repositories code_relations | No changes detected | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Status | Evidence |
| ----------- | ---------- | ------ | -------- |
| IDX-01 | 25-03, 25-04 | ✓ SATISFIED | commit 摄取服务 + 索引流程挂接 + search_rag 召回闭环 |
| IDX-02 | 25-01, 25-02 | ✓ SATISFIED | 行号回填 + find_chunk_at/chunk-at REST fail-closed |

### Anti-Patterns Found

None. SUMMARY「Known Stubs: None」claim 经源码核对成立 —— 无 TODO/FIXME/XXX 调试标记、无占位 return、无悬空 fetch；fail-closed 路径均有真实实现与测试覆盖。

### Human Verification Required

None. commit 召回的语义排序质量依赖运行期真实 embedding 模型 + Qdrant，属固有 RAG 质量范畴而非本阶段交付物；本阶段交付的结构契约（文档构建、kind=commit payload、search_rag chokepoint 经排除/去重过滤、增量边界、行号回填、反查 API fail-closed）已全部由源码与 43 例测试验证。

### Gaps Summary

无 gap。两条 ROADMAP success criteria 与 15 条 PLAN must-have truths 全部经实际源码（非 SUMMARY 声明）验证为已落地并连通：IDX-02 行号回填链路 create+update 双路径完整、find_chunk_at + chunk-at REST 全程 fail-closed 且不泄漏存在性；IDX-01 commit 摄取经 Phase 22 单一匹配器过滤被排除文件、uuid5 去重、upsert 成功才推进独立增量边界、best-effort 挂接 rmtree 之前不阻断索引 success。migration 0035 干净、模型字段独立。

---

_Verified: 2026-06-15T07:32:00Z_
_Verifier: Claude (gsd-verifier)_
