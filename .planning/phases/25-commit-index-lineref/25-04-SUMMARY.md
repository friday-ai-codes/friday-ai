---
phase: 25-commit-index-lineref
plan: 04
subsystem: api
tags: [rag, commit-index, indexer, search-rag, exclusion, fail-closed, incremental, best-effort]

# Dependency graph
requires:
  - phase: 25-commit-index-lineref
    provides: "25-03 services/commit_index.py::index_commits（git log → 排除过滤 → embedding → upsert kind=commit → 推进 commit_index_boundary_sha 边界）"
  - phase: 22-fail-closed
    provides: "services.retrieval.rag_search.search_rag chokepoint + build_matcher_for_repo（commit 文档同受排除约束自然召回）"
  - phase: 24-sensitive-ai-detect
    provides: "BL-01 修复经验：检测/摄取必须在 rmtree(temp_dir) 之前 await 完成（绝不后台派发去遍历即将删除的克隆目录）"
provides:
  - "clone_and_index_repository 内 _run_commit_index best-effort 派发挂接（base 路径全量+增量、rmtree 之前 await）"
  - "search_rag 召回 / 排除 / 增量端到端守护测试（IDX-01 闭环）"
affects: [search_rag commit 文档召回, 多仓检索]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "commit 索引派发对齐 _run_sensitive_detection fail-safe 范式：rmtree 前 await + 整段 try/except 吞异常 warning，绝不阻断索引 success（T-25-12）"
    - "端到端召回守护：mock BranchAwareSearchService.search 对捕获的 commit point 按 query substring 命中 content，模拟语义召回，验证 search_rag 排除/去重 chokepoint 对 commit 文档生效"

key-files:
  created:
    - server/tests/services/test_commit_index_integration.py
  modified:
    - server/services/indexer.py

key-decisions:
  - "_run_commit_index 仅 base 索引路径挂接（功能分支 overlay 不在范围），紧随 _run_sensitive_detection 之后、rmtree 之前 await"
  - "commit 索引失败/缺供应商绝不阻断既有索引 success 终态（best-effort，T-25-12）"
  - "召回守护用真实 build_matcher_for_repo（仅 builtin 全局默认）真正经过排除过滤；合成 file_path .friday/commits/{sha} 不被排除可召回"

patterns-established:
  - "全量/增量索引完成后（rmtree 之前）唯一 commit 索引挂接点 _run_commit_index；边界首轮/增量区分由 index_commits 内部 commit_index_boundary_sha 处理"

requirements-completed: [IDX-01]

# Metrics
duration: ~10min
completed: 2026-06-15
---

# Phase 25 Plan 04: Commit 索引挂接索引流程（IDX-01 闭环）Summary

**把 25-03 的 `index_commits` 以 best-effort 方式挂接进 `clone_and_index_repository`——仅 base 索引路径、紧随敏感检测之后、临时克隆 `rmtree` 之前 `await` 完成（沿用 Phase 24 BL-01 时序），全量与增量均流经；commit 索引失败仅 warning 绝不阻断索引 success；并以端到端守护测试验证 commit 文档经既有 `search_rag` 用关键字/author 召回、被排除文件不泄漏、增量只新增。**

## Performance

- **Duration:** ~10 min
- **Completed:** 2026-06-15
- **Tasks:** 2
- **Files modified:** 2（1 created + 1 modified）

## Accomplishments
- `_run_commit_index(repository_id, repo_path)`：照搬 `_run_sensitive_detection` best-effort 结构——`try: from services.commit_index import index_commits; await index_commits(...)` 成功 `logger.info("commit_index_completed")`，异常仅 `logger.warning("commit_index_dispatch_failed")` 不冒泡（T-25-12）。
- 挂接点：`clone_and_index_repository` 的 `if not branch:` 块内、`_run_sensitive_detection` 之后、`finally` 的 `shutil.rmtree(temp_dir)` 之前 `await _run_commit_index(repository_id, temp_dir)`——读真实克隆的 git 历史（全量与增量均流经此函数，首轮/增量区分由 `index_commits` 内部 `commit_index_boundary_sha` 边界处理）。
- 端到端守护测试 7 例全绿：dispatch 失败不冒泡 + 正常路径 rmtree 前完成；search_rag 用关键字/author 召回 kind=commit 文档、不相关 query 不召回；召回的 commit 文档摘要含普通文件、不含 `.env`/`*.pem`（fail-closed，T-25-13）；增量二次同 HEAD 0 条、新增 commit 只 +1（T-25-14）。

## Task Commits

Each task was committed atomically:

1. **Task 1: _run_commit_index best-effort 派发（rmtree 之前）** - `b8e652fc8` (feat)
2. **Task 2: search_rag 召回 + 排除 + 增量端到端守护测试** - `daa1b198b` (test)

## Files Created/Modified
- `server/services/indexer.py` - 新增模块级 `_run_commit_index` + `clone_and_index_repository` base 路径挂接（rmtree 之前 best-effort 摄取 commit 历史）
- `server/tests/services/test_commit_index_integration.py` - 召回/排除/增量/dispatch 端到端守护测试（真实临时 git 仓库驱动，mock embedding/sparse/qdrant/BranchAwareSearchService.search）

## Decisions Made
- **仅 base 路径挂接**：与 `_run_sensitive_detection` 同款 `if not branch:` 守护，功能分支 overlay 不触发 commit 索引（不在本阶段范围）。
- **rmtree 之前 await**：沿用 Phase 24 BL-01 修复经验——`index_commits` 需读真实克隆的 git 历史（git log / diff-tree），`await` 它保证读到的是真实克隆目录而非已删除/空目录；绝不后台派发去遍历一个即将被删除的目录。
- **best-effort 不阻断**：整段 try/except 吞异常仅 warning，commit 索引失败/缺供应商绝不影响 `return index_result` 的 success 终态（T-25-12）。
- **召回守护设计**：无真实 Qdrant，改为捕获 `index_commits` upsert 的 commit point，mock `BranchAwareSearchService.search` 对其按 query substring 命中 `content` 返回，模拟语义召回；`build_matcher_for_repo` 用真实实现（仅 builtin 全局默认），真正经过 search_rag 排除/去重 chokepoint，验证合成 `file_path=.friday/commits/{sha}` 不被排除、可召回。

## Deviations from Plan

None - plan executed exactly as written。

（说明：依 plan-checker W1 处理 Task 1 verify 与 Task 2 测试文件的前后依赖——Task 1 提交仅 `indexer.py`，其 verify 以 mypy `services/indexer.py`（clean）+ grep `_run_commit_index|index_commits`（仅 base 路径挂接、best-effort）+ 模块导入校验代替会依赖 Task 2 尚未提交文件的 `-k dispatch` pytest；Task 2 提交完整测试文件并跑全量 pytest 7 例绿。每个任务的 verify 在其提交时点均真实通过。）

## Issues Encountered
None。`ruff format` 提示 `indexer.py` 有一处**既有**（行 3217 附近，与本次改动无关）格式差异——属超范围预存格式，未触碰；本次新增代码 ruff check/format 均 clean。

## User Setup Required
None - 无外部服务配置；既有部署升级后首次索引完成即自动摄取 commit 历史（`commit_index_boundary_sha=NULL` 走首轮 bounded 全量），向后兼容。

## Next Phase Readiness
- IDX-01 闭环完成：commit 历史在索引完成后自动摄取、经 `search_rag` 用关键字/author 召回，被排除文件不泄漏，增量只新增。
- Phase 25 全部 4 个 plan 完成（25-01 行号回填、25-02 chunk-at 反查、25-03 commit 摄取服务、25-04 索引流程挂接 + 端到端召回）。
- 检索侧未改动：commit 文档落主 collection + `kind=commit`，下游若需「仅代码 chunk / 仅 commit」过滤可据此 payload 维度筛选。

## Self-Check: PASSED

---
*Phase: 25-commit-index-lineref*
*Completed: 2026-06-15*
