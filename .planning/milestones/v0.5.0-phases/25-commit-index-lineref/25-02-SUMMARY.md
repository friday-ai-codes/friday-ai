---
phase: 25-commit-index-lineref
plan: 02
subsystem: api
tags: [idx-02, chunk-lookup, reverse-lookup, fail-closed, exclusion, adrf, rest]

# Dependency graph
requires:
  - phase: 25-commit-index-lineref
    provides: ChunkRegistry.line_start/line_end 行号回填（25-01）
  - phase: 22-fail-closed
    provides: build_matcher_for_repo / is_excluded / normalize_rel_path / log_exclusion_blocked 单一匹配器
provides:
  - "find_chunk_at(repository_id, file_path, line, *, branch_name) service：区间命中 + 最具体优先 + fail-closed 排除"
  - "GET /api/repositories/<id>/chunk-at/?path=&line= REST 端点（认证保护，存在性不泄漏）"
affects: [v0.6 片段→需求反查（复用 find_chunk_at 地基）]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "反查入口复用 Phase 22 排除范式（对齐 rag_search.py）：matcher 构造/判定/归一异常一律 fail-closed 返回空"
    - "被排除文件与无命中对外同形（{\"chunks\": []} 200），避免存在性泄漏"
    - "多 chunk 命中按覆盖区间宽度升序（最具体优先），次序稳定按 chunk_index"
    - "异步 ORM 经 sync_to_async；仅读 ChunkRegistry，NULL 行号 row 天然排除（line_start/end__isnull=False）"

key-files:
  created:
    - server/services/chunk_lookup.py
    - server/repositories/chunk_at_views.py
    - server/tests/services/test_find_chunk_at.py
    - server/tests/repositories/test_chunk_at_view.py
  modified:
    - server/repositories/urls.py

key-decisions:
  - "多 chunk 命中返回全部（per Claude's Discretion），按区间宽度升序使最具体 chunk 居首"
  - "find_chunk_at 入口先构造 matcher 再查询：构造失败即 fail-closed，绝不放行（T-25-04）"
  - "REST 被排除文件与无命中均返回空 chunks 200，对外不可区分（T-25-05）"
  - "line 校验为正整数（<1 → 400），path 必填；service 不抛 past view（T-25-07）"

patterns-established:
  - "file:line → chunk_id 反查复用单一排除匹配器，与 RAG/索引读取面 fail-closed 一致"

requirements-completed: [IDX-02]

# Metrics
duration: 5min
completed: 2026-06-15
---

# Phase 25 Plan 02: file:line → chunk_id 反查（service + REST）Summary

**给定 repo+file+line 定位覆盖该行的 chunk(s)：`find_chunk_at` 服务按 1-based 闭区间命中、最具体（区间最小）优先，复用 Phase 22 单一排除匹配器对被排除文件全程 fail-closed；`GET /api/repositories/<id>/chunk-at/` REST 端点认证保护，被排除文件与无命中对外同形返回空 chunks 不泄漏存在性。**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-06-14T23:00:26Z
- **Completed:** 2026-06-14T23:05:00Z
- **Tasks:** 2（Task 1 TDD: RED + GREEN；Task 2 实现 + 守护测试）
- **Files modified:** 5（4 created, 1 modified）

## Accomplishments
- `find_chunk_at(repository_id, file_path, line, *, branch_name="")` service：(1) `build_matcher_for_repo` 取匹配器，构造异常 → 埋点 + 返回 `[]`；(2) `normalize_rel_path` 归一，None → `[]`；(3) `matcher.is_excluded` 命中（含判定异常视为 True）→ 埋点 + `[]`；(4) `sync_to_async` 查 ChunkRegistry 闭区间命中；(5) 按区间宽度升序（最具体优先）返回全部命中。
- `ChunkAtView` APIView：`IsAuthenticated`，`GET ?path=&line=&branch_name=`，缺/非法参数 400，不存在仓库 404，命中返回 `{path, line, chunks}`。
- 路由 `<uuid:repository_id>/chunk-at/` 注册于 router include 之后（UUID 通配安全）。
- 11 例 service 守护测试 + 9 例 view 守护测试，全绿。

## Task Commits

1. **Task 1 RED: find_chunk_at 区间 + fail-closed 守护测试** - `b2d03a3d1` (test)
2. **Task 1 GREEN: find_chunk_at 反查服务** - `e9902388c` (feat)
3. **Task 2: chunk-at REST 端点 + 路由** - `f6477be3b` (feat)

**Plan metadata:** _(本次 docs 提交，见末尾)_

## Files Created/Modified
- `server/services/chunk_lookup.py` - 新建，`find_chunk_at` 反查服务 + `_query_covering_chunks` sync ORM 查询
- `server/repositories/chunk_at_views.py` - 新建，`ChunkAtView` APIView
- `server/repositories/urls.py` - import `ChunkAtView` + 注册 `chunk-at/` 路由
- `server/tests/services/test_find_chunk_at.py` - 新建，11 例 service 守护测试
- `server/tests/repositories/test_chunk_at_view.py` - 新建，9 例 REST 守护测试

## Decisions Made
- **返回全部命中、最具体优先**：多 chunk 覆盖同一行时返回全部，按 `(line_end - line_start)` 升序排序（次序稳定按 `chunk_index`），使最小覆盖区间居首（per Claude's Discretion）。
- **入口即 fail-closed**：先 `build_matcher_for_repo` 再查询，构造失败立即埋点返回空，对齐 `rag_search.py` 范式，绝不在排除判定缺失时放行（T-25-04）。
- **存在性不泄漏**：REST 对被排除文件与无命中均返回 `{"chunks": []}` 200，对外不可区分（T-25-05）。
- **NULL 行号 graceful**：查询条件含 `line_start__isnull=False, line_end__isnull=False`，历史未回填 row 天然不被命中（25-01 Next Phase Readiness 要求）。

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- 裸 `python -c "from repositories.urls import urlpatterns"` 因未配置 `DJANGO_SETTINGS_MODULE` 报 `ImproperlyConfigured`；以 `DJANGO_SETTINGS_MODULE=friday.settings + django.setup()` 重跑 → `urls ok`（路由 import 无误）。非交付物问题。

## Verification Results
- `pytest tests/services/test_find_chunk_at.py tests/repositories/test_chunk_at_view.py` → **20 passed**
- urls import（含 django.setup）→ **urls ok**
- `ruff check`（改动文件）→ **All checks passed**
- `mypy services/chunk_lookup.py repositories/chunk_at_views.py` → **Success: no issues found in 2 source files**

## Threat Model Coverage
- **T-25-04**（被排除文件 chunk_id/行位置泄漏）: ✅ `find_chunk_at` 入口 `build_matcher_for_repo` + `is_excluded` fail-closed；构造/判定/归一异常一律视为排除；`test_excluded_file_failclosed` / `test_excluded_pem_failclosed` / `test_matcher_build_failure_failclosed` 断言空返回。
- **T-25-05**（「无命中」vs「被排除」可区分 → 存在性泄漏）: ✅ 两情形统一返回空 chunks 200；`test_excluded_file_no_existence_leak` + `test_no_hit_returns_empty` 同形断言。
- **T-25-06**（未认证访问）: ✅ `permission_classes=[IsAuthenticated]`；`test_unauthenticated_blocked` 断言 401/403。
- **T-25-07**（恶意 path 越界/异常 DoS）: ✅ `normalize_rel_path` None → 空返回（`test_illegal_path_returns_empty`）；line 正整数校验（400）；service 不抛 past view。

## Known Stubs
None - find_chunk_at + chunk-at REST 完整可用，无占位/桩。

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `file:line → chunk_id` 反查地基就绪，v0.6「片段 → 需求反查」可直接复用 `find_chunk_at`。
- 历史 NULL 行号 row 仍不可反查（per 25-01 D-02 不强制回填）；重索引后自然补齐。
- 前端 chunk-at UI 留后续（per Phase 25 deferred）。

## Self-Check: PASSED

---
*Phase: 25-commit-index-lineref*
*Completed: 2026-06-15*
