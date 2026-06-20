---
phase: 62-crawl
plan: 02
subsystem: durable
tags: [durable, page_index, corpus_tree, repositories, idempotency]

# Dependency graph
requires:
  - phase: 60-durable
    provides: DurableTaskService 门面、durable.queues（QUEUE_PAGE_INDEX）、In/Procrastinate 双后端
  - phase: 61-migrate
    provides: durable_page_index 双后端注册（tasks.py 包壳 + handlers.py adapter）、keyword-only 任务体范式
  - phase: 62-crawl/01
    provides: tasks_impl 双后端薄封装范式、durable 队列动作端点派发范式
provides:
  - CorpusTreeSnapshot.source_hash 列 + 迁移 0038
  - CorpusTreeService.compute_source_hash（全仓 id/ai_summary/facets 确定性 sha256 指纹）
  - run_page_index 真实生成（CorpusTreeService.build_full + target-hash 跳过，重复执行无重复 snapshot）
  - KnowledgeTreeRebuildView 收口到 DurableTaskService.defer(QUEUE_PAGE_INDEX)
affects: [63-deploy per-repo summary dispatch（OQ-2 跟踪项）]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "target hash = 域树输入指纹（全仓 id/ai_summary/facets，剔除 _ 私有 facet 键，sort_keys sha256）落 snapshot.source_hash，下次比对据此跳过重 LLM 聚类（OQ-3）"
    - "run_page_index 薄封装天然幂等的 build_full：hash 未变 skipped 不调，hash 变重建落新 source_hash 供下次比对"
    - "入队点（rebuild view）算 target_hash 透传 payload，与任务体内 compute_source_hash 同源，idempotency_key=queueing_lock 去重"

key-files:
  created:
    - server/repositories/migrations/0038_corpustreesnapshot_source_hash.py
    - server/tests/durable/test_page_index.py
    - server/tests/repositories/test_knowledge_tree.py
  modified:
    - server/repositories/models.py
    - server/codegraph/services/corpus_tree.py
    - server/durable/tasks_impl.py
    - server/repositories/tree_views.py
    - server/tests/durable/test_idempotency.py
    - server/tests/durable/test_business_tasks.py

key-decisions:
  - "OQ-3 target hash = 域树输入指纹存 snapshot.source_hash：CharField(64) blank/default 不回填存量，确定性 sha256（A2）"
  - "compute_source_hash 与 build_full 同源（build_full 内调 compute_source_hash 落 hash）：避免 build_full 切片(500)与 hash 全仓口径不一致致 >500 仓永不命中跳过"
  - "OQ-2 范围声明落实：仅收口 tree_views.py build_full 路径；per-repo summary dispatch（_schedule_auto_summary 经 Runner）明确留 Phase 63，不在本阶段静默落空"

patterns-established:
  - "页面/树生成 durable 化：入队点算 target_hash → defer(QUEUE_PAGE_INDEX, idempotency_key) → 任务体 hash 未变跳过、变则真实重建落 source_hash"

requirements-completed: [PAGEIDX-01]

# Metrics
duration: 12min
completed: 2026-06-21
---

# Phase 62 Plan 02: PageIndex/知识树生成接入 durable 队列 + target-hash 幂等 Summary

**run_page_index 由占位 noop 填充为真实生成（CorpusTreeService.build_full + target-hash 跳过）+ CorpusTreeSnapshot.source_hash 列与确定性指纹 helper + KnowledgeTreeRebuildView 裸 run_in_background 收口到 DurableTaskService.defer(QUEUE_PAGE_INDEX)，按 target hash 幂等（未变跳过、变则重建落 source_hash），重复执行无重复 snapshot**

## Performance

- **Duration:** ~12 min
- **Tasks:** 2（+1 Rule 1 守护同步）
- **Files modified:** 9（3 created, 6 modified）

## Accomplishments
- `CorpusTreeSnapshot.source_hash`（`repositories/models.py`）：`CharField(max_length=64, blank=True, default="")` + 迁移 `0038`（AddField，依赖 0037，存量不回填）
- `CorpusTreeService.compute_source_hash`（`codegraph/services/corpus_tree.py`）：读非删除 Repository 的 `(id, ai_summary, facets)`（沿用 `.only(...)`，剔除 `_` 前缀私有 facet 键），按 repo_id 排序后 `json.dumps(sort_keys=True, ensure_ascii=False)` → `sha256`；`_activate_new_snapshot` 增 `source_hash` 形参写入新 snapshot，`build_full` 调用处算 hash 传入并回写返回值
- `run_page_index`（`durable/tasks_impl.py`）：keyword-only `(*, target_id, target_hash="", **kwargs)`；先算 `current = compute_source_hash()`，`target_hash` 命中 → `{"status":"skipped","reason":"hash_unchanged"}` **不调 build_full**；否则调天然幂等的 `build_full()`（自身落 snapshot），返回含 `source_hash`
- `KnowledgeTreeRebuildView.post`（`repositories/tree_views.py`）：删 `run_in_background(lambda: build_full())`，改 `await DurableTaskService.defer("durable_page_index", {"target_id":"corpus_tree","target_hash":...}, queue=QUEUE_PAGE_INDEX, idempotency_key="page_index:corpus_tree")`，返回 `202 + job_id`；保持 `IsAdminUser`
- 守护测试：`test_page_index.py`（5：hash 未变 skip 不调 build_full / hash 缺省调一次 / 真实 build→skip 无重复 snapshot / compute_source_hash 确定性 + 输入敏感 / 私有 facet 键不参与指纹）、`test_knowledge_tree.py`（4：defer 入参契约 + 202 / 非 admin 403 / 未认证拒 / 源码无 run_in_background 与 procrastinate）

## Task Commits

每个任务原子提交（Conventional Commits，中文 subject）：

1. **Task 1: source_hash 列 + 真实 run_page_index（hash 跳过/重建）** - `e51b3927b` (feat)
2. **Task 2: tree_views.py 收口 durable defer(QUEUE_PAGE_INDEX)** - `7b86655e4` (feat)
3. **Rule 1 守护同步: page_index 占位幂等守护改 hash 跳过契约** - `f55ba115e` (test)

## Files Created/Modified
- `server/repositories/models.py`（改）- CorpusTreeSnapshot 增 source_hash 列
- `server/repositories/migrations/0038_corpustreesnapshot_source_hash.py`（新）- AddField source_hash
- `server/codegraph/services/corpus_tree.py`（改）- compute_source_hash + _activate_new_snapshot/build_full 落 source_hash
- `server/durable/tasks_impl.py`（改）- run_page_index 真实生成 + target-hash 跳过
- `server/repositories/tree_views.py`（改）- KnowledgeTreeRebuildView 改 durable defer
- `server/tests/durable/test_page_index.py`（新）- run_page_index + compute_source_hash 守护（5 用例）
- `server/tests/repositories/test_knowledge_tree.py`（新）- rebuild 端点 durable defer 契约（4 用例）
- `server/tests/durable/test_idempotency.py`（改）- page_index 段同步为 hash 跳过契约
- `server/tests/durable/test_business_tasks.py`（改）- Test 3 占位幂等守护同步为 hash 跳过契约

## Decisions Made
- 见 frontmatter key-decisions（OQ-3 target hash 存 snapshot、compute_source_hash 与 build_full 同源避免切片口径不一致、OQ-2 范围仅收口 tree_views）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] page_index 占位幂等守护同步（两处）**
- **Found during:** Task 1 后全量套件验证
- **Issue:** `run_page_index` 由占位 noop 改真实生成后，两处既有守护断言旧 `{"status":"noop"}` 必然失败：`tests/durable/test_idempotency.py::test_page_index_idempotent_no_side_effect`、`tests/durable/test_business_tasks.py::test_page_index_placeholder_is_idempotent`（由本 plan 任务体改动直接引发）。
- **Fix:** 二者更新为新契约——`target_hash` 命中当前 hash → 连续两次恒等 `skipped` 且 spy 验证 `build_full` 未被调用（mock compute_source_hash/build_full，无 DB/触网）。
- **Files modified:** server/tests/durable/test_idempotency.py、server/tests/durable/test_business_tasks.py
- **Verification:** 两文件相关用例全绿；ruff All checks passed。
- **Committed in:** test_idempotency.py 随 Task 1（`e51b3927b`）；test_business_tasks.py 单独 `f55ba115e`

---

**Total deviations:** 1 类（2 处守护同步，本 plan 任务体改动直接引发）。
**Impact on plan:** 守护与新任务体契约保持一致，无 scope creep。

## Issues Encountered
- **预存（out-of-scope）失败**：`tests/repositories/test_index_retry_resume.py::test_failed_partial_index_with_checkpoint_resumes_full_index_not_incremental` 与 `tests/repositories/test_index_history_changed_files.py::test_changed_files_populated_after_incremental_index` 在本 plan 执行前即失败（用户已知基础设施失败），与本 plan 改动无关，按 SCOPE BOUNDARY 不修复。其余 durable + repositories 套件 332 passed。

## User Setup Required
None - 零新依赖、零外部服务配置（SQLite 默认 in-process 后端开箱即用；Postgres durable 路径由 Phase 60 锁定）。

## Verification
- `cd server && uv run pytest tests/durable tests/repositories -q` → 332 passed, 2 failed（仅用户已知的预存基础设施失败 test_index_retry_resume / test_changed_files_populated）, 15 deselected。
- `cd server && uv run python manage.py check` → System check identified no issues。
- `cd server && uv run python manage.py makemigrations --check --dry-run` → No changes detected（干净）。
- `tests/durable/test_no_direct_import.py` → passed（tree_views 经 DurableTaskService + durable 常量，零直接 import procrastinate）。
- ruff check 本 plan 所有改动文件 → All checks passed。

## Known Stubs
None - run_page_index 为真实接入（薄封装 build_full），rebuild 端点真实经 DurableTaskService.defer。per-repo summary dispatch（OQ-2）非 stub 而是显式范围外，跟踪到 Phase 63。

## Self-Check: PASSED
