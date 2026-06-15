---
phase: 25-commit-index-lineref
plan: 01
subsystem: database
tags: [indexer, chunk-registry, line-numbers, typeddict, idx-02, tree-sitter]

# Dependency graph
requires:
  - phase: 24-sensitive-detect
    provides: 索引流程基线（_build_points / _bulk_upsert_registry_atomic 写入链路）
provides:
  - ChunkRegistryRow 携带 1-based 闭区间 line_start/line_end
  - _build_points 透传 CodeChunk.start_line/end_line 进 registry_rows
  - _bulk_upsert_registry_atomic create + update 双路径落库行号，行号位移触发 update
affects: [25-02 file:line→chunk_id 反查, 25-03 commit 索引, chunk-at API]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "ChunkRegistryRow TypedDict 作为 _build_points → _bulk_upsert 的同源契约，新增键 mypy 静态拦截调用方漏传"
    - "行号写入与 Qdrant payload start_line/end_line 同源，保证 payload 与 ChunkRegistry 行号一致"
    - "update 判定显式纳入行号变化，line-only shift（hash/路径/index 未变）仍更新"

key-files:
  created:
    - server/tests/services/test_chunk_line_backfill.py
  modified:
    - server/code_relations/types.py
    - server/services/indexer.py
    - server/tests/code_relations/test_indexer_chunk_id.py
    - server/tests/code_relations/test_indexer_registry_upsert.py

key-decisions:
  - "无新 migration（line_start/line_end 字段及 chunkreg_line_range_valid 约束已存在于 0003/0004，per D-02）"
  - "行号直接取 CodeChunk 既有 start_line/end_line 属性，与同处写入 Qdrant payload 同源"
  - "update 判定额外纳入「仅行号变化」分支，避免 hash/路径未变时漏更新导致 25-02 反查错位"
  - "None 行号合法落 NULL（历史/非 AST 回退兼容），错乱区间由 DB CheckConstraint 兜底拒绝"

patterns-established:
  - "TypedDict 契约扩展：新增可选键后同步更新所有构造点 + 键集合回归测试"
  - "DB 层 CheckConstraint 作为 indexer 错乱行号的兜底防线（守护测试断言 IntegrityError）"

requirements-completed: [IDX-02]

# Metrics
duration: 9min
completed: 2026-06-15
---

# Phase 25 Plan 01: ChunkRegistry 行号回填 Summary

**索引时把每个 chunk 的 1-based 闭区间源码起止行写入 ChunkRegistry（line_start/line_end），打通 `file:line → chunk_id` 反查的数据地基——create + update 双路径落库，重切分行号位移触发更新，复用既有 CheckConstraint 无新 migration**

## Performance

- **Duration:** ~9 min
- **Started:** 2026-06-14T22:46:49Z
- **Completed:** 2026-06-14T22:55:16Z
- **Tasks:** 2 (TDD: RED + GREEN each)
- **Files modified:** 5 (1 created, 4 modified)

## Accomplishments
- `ChunkRegistryRow` TypedDict 新增 `line_start: int | None` / `line_end: int | None`，docstring 注明 1-based 闭区间与 NULL 语义
- `_build_points` 在构建 registry_rows 时透传 `chunk.start_line` / `chunk.end_line`，与同处写入 Qdrant payload 同源
- `_bulk_upsert_registry_atomic` 在 get_or_create defaults（create 路径）与既有 save 分支（update 路径）写入行号，更新判定显式纳入「行号变化」检测
- 9 例行号回填守护测试（4 build_points + 5 upsert），覆盖 create/update/重切分位移/仅行号变/None 落 NULL/错乱区间 IntegrityError

## Task Commits

每个 TDD 任务原子提交（RED → GREEN）：

1. **Task 1 RED: _build_points 行号测试** - `19f9d0d4b` (test)
2. **Task 1 GREEN: ChunkRegistryRow + _build_points 透传行号** - `e51db7eb5` (feat)
3. **Task 2 RED: _bulk_upsert_registry_atomic 行号测试** - `3614a48cd` (test)
4. **Task 2 GREEN: upsert create+update 落库行号** - `cd14492cb` (feat)

**Plan metadata:** _(本次 docs 提交，见末尾)_

## Files Created/Modified
- `server/code_relations/types.py` - `ChunkRegistryRow` 新增 line_start/line_end 键 + docstring
- `server/services/indexer.py` - `_build_points` 透传行号；`_bulk_upsert_registry_atomic` create+update 双路径落库 + 行号变化检测
- `server/tests/services/test_chunk_line_backfill.py` - 新建，9 例行号回填守护测试
- `server/tests/code_relations/test_indexer_chunk_id.py` - 既有键集合回归测试更新为 8 字段
- `server/tests/code_relations/test_indexer_registry_upsert.py` - `_make_row` helper 扩展 line_start/line_end 键（契约对齐）

## Decisions Made
- **无新 migration**：`line_start`/`line_end` 字段及 `chunkreg_line_range_valid` CheckConstraint 已存在（migration 0003 + 0004），本 plan 仅打通写入链路（per D-02）。`makemigrations --check` 输出 "No changes detected"。
- **行号同源**：直接取 `CodeChunk.start_line/end_line`（已是 1-based 闭区间，tree-sitter `node.start_point[0] + 1`），与写入 Qdrant payload 的 `start_line`/`end_line` 同一来源，保证两侧行号一致。
- **update 判定纳入行号变化**：`obj.line_start != row["line_start"] or obj.line_end != row["line_end"]`，避免「仅行号位移、hash/路径/index 未变」时漏更新（否则 25-02 反查命中错位区间，T-25-03）。
- **错乱区间 DB 兜底**：`line_end < line_start` 由既有 CheckConstraint 拒绝（IntegrityError），indexer 不静默落错乱区间（T-25-01）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] 更新既有 registry-row 契约测试以匹配新键集合**
- **Found during:** Task 1 (GREEN) / Task 2 (GREEN)
- **Issue:** `ChunkRegistryRow` 新增 line_start/line_end 后，既有 `test_build_points_registry_row_fields_complete`（断言 6 字段精确键集合）与 `test_indexer_registry_upsert.py::_make_row`（构造缺新键的 dict，会触发 `row["line_start"]` KeyError）会回归失败。
- **Fix:** 键集合断言更新为 8 字段；`_make_row` helper 增加 `line_start`/`line_end` 形参（默认 None）。两者均为契约同步，非新增行为。
- **Files modified:** server/tests/code_relations/test_indexer_chunk_id.py, server/tests/code_relations/test_indexer_registry_upsert.py
- **Verification:** 两文件全绿（test_indexer_chunk_id 8 passed / test_indexer_registry_upsert 4 passed）
- **Committed in:** e51db7eb5 (Task 1) / cd14492cb (Task 2)

---

**Total deviations:** 1 auto-fixed (1 blocking — 契约测试同步)
**Impact on plan:** 仅为 TypedDict 契约扩展的必要测试同步，无范围蔓延。

## Issues Encountered
- 一次 mypy 调用瞬时报 "can't read file"（疑似 logging 初始化副作用切换 cwd），以绝对路径重跑后 `Success: no issues found in 2 source files`，无实质问题。

## Verification Results
- `pytest tests/services/test_chunk_line_backfill.py tests/code_relations/test_chunkregistry_line_fields.py` → **13 passed**
- `pytest -k "build_points or indexer"`（无回归）→ **117 passed**
- `makemigrations --check --dry-run code_relations` → **No changes detected**
- `mypy services/indexer.py code_relations/types.py` → **Success: no issues found**
- `ruff check`（改动文件）→ **All checks passed**

## Threat Model Coverage
- **T-25-01**（错乱行号写入）: ✅ 复用 `chunkreg_line_range_valid` CheckConstraint，守护测试断言 `line_end < line_start` 触发 IntegrityError
- **T-25-03**（重切分行号位移未更新）: ✅ update 分支显式纳入行号变化判定 + `test_upsert_update_refreshes_line_fields_when_only_lines_move` 覆盖
- **T-25-02**（信息泄露）: accept — 仅写既有字段，不引入新读取面

## Known Stubs
None - 行号回填链路完整打通，无占位/桩。

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- ChunkRegistry 行号回填地基就绪，25-02 可基于 `repo + file_path + line_start<=line<=line_end` 实现 `find_chunk_at` 反查
- 历史 row 仍为 NULL（未强制回填，per D-02），25-02 反查需对 NULL 行号 graceful 处理（仅命中已回填 row）

## Self-Check: PASSED

- Files: server/code_relations/types.py, server/services/indexer.py, server/tests/services/test_chunk_line_backfill.py, 25-01-SUMMARY.md — all FOUND
- Commits: 19f9d0d4b, e51db7eb5, 3614a48cd, cd14492cb — all FOUND

---
*Phase: 25-commit-index-lineref*
*Completed: 2026-06-15*
