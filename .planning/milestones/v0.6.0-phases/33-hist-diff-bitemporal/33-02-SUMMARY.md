---
phase: 33-hist-diff-bitemporal
plan: 02
subsystem: knowledge
tags: [bitemporal, modifies-chunk, as-of, reconcile, invalidate, reindex, hdiff-02]

# Dependency graph
requires:
  - phase: 33-hist-diff-bitemporal
    plan: 01
    provides: MODIFIES_CHUNK 边 metadata.chunk_content_hash（冻结当年指纹）+ commit 锚定 valid_at
  - phase: 12-knowledge-graph
    provides: knowledge.graph_store（invalidate_edge 失效收口 + chunk_in_edges 反查 + neighbors bi-temporal 谓词）
  - phase: 14-knowledge-diff
    provides: MODIFIES_CHUNK 边写入收口（apply_edge_specs / EdgeSpec / target_chunk_id 弱引用）
provides:
  - knowledge.modifies_chunk.amodifies_chunk_edges（as-of 查询 helper：chunk/repo-scoped + 历史/当前视图）
  - knowledge.modifies_chunk.areconcile_modifies_chunk_edges（重索引对账：过期 MODIFIES_CHUNK 边置 invalid_at）
  - knowledge.graph_store.bitemporal_as_of_q（公开 bi-temporal as-of 谓词，单一收口）
  - knowledge.graph_store.chunk_in_edges 的 as_of 可选参数（历史回溯，既有调用方零回归）
  - services.indexer._run_modifies_chunk_reconcile（base 重索引完成 best-effort 钩子）
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "as-of 查询复用单一 bi-temporal 谓词 bitemporal_as_of_q（避免跨模块复刻 raw 过滤导致语义漂移）"
    - "target_chunk_id 反查恒经 graph_store.chunk_in_edges chunk-lookup chokepoint；repo-scoped 在 relation/repo 上叠加同款谓词"
    - "过期双信号：target_chunk_id 存在性 + content_hash 漂移（缺指纹边仅按存在性保守判定）"
    - "边失效唯一经 graph_store.invalidate_edge（置位不删、不覆盖原失效时间）；逐边 try/except 降级不掀翻批次"
    - "对账挂既有 reindex base 路径 best-effort 钩子（与 _run_sensitive_detection/_run_commit_index 同款 fail-safe）"

key-files:
  created:
    - server/knowledge/modifies_chunk.py
    - server/tests/knowledge/test_modifies_chunk_reconcile.py
  modified:
    - server/knowledge/graph_store.py
    - server/services/indexer.py

key-decisions:
  - "as-of 谓词提升为公开 helper bitemporal_as_of_q（同 require_aware 公开理由：跨模块依赖私有符号易在重构时悄然破坏）"
  - "扩展 chunk_in_edges 增 as_of 可选参数（默认 None=当前视图零回归），而非在 modifies_chunk 复刻 target_chunk_id 过滤（尊重 chunk-lookup chokepoint）"
  - "repository_id-scoped 路径直接查 relation+repo（不触 target_chunk_id 过滤，不违反 chunk-lookup chokepoint），叠加同款 bi-temporal 谓词并加守护测试"
  - "对账边 materialize 后再逐条置位（避免开着读游标同时写库的 SQLite 锁竞争）"

requirements-completed: [HDIFF-02]

# Metrics
duration: ~25min
completed: 2026-06-15
---

# Phase 33 Plan 02: bi-temporal 失效对账 + as-of 查询 Summary

**为 MODIFIES_CHUNK 边落地 HDIFF-02：新增 `amodifies_chunk_edges` as-of 查询 helper（历史 as_of 见当年成立边、当前视图只见未失效边），新增 `areconcile_modifies_chunk_edges` 重索引对账（target_chunk_id 不存在 ∪ content_hash 漂移 → 经 `graph_store.invalidate_edge` 置 `invalid_at`，置位不删），并把对账挂在 `clone_and_index_repository` 收尾 base 路径作 best-effort 钩子（失败仅 warning，绝不阻断索引 success）。**

## Performance

- **Duration:** ~25 min
- **Tasks:** 3
- **Files created:** 2；**modified:** 2

## Accomplishments
- `graph_store.bitemporal_as_of_q(as_of)`：把 neighbors/traverse 的 as-of 谓词（`valid_at<=as_of AND (invalid_at IS NULL OR invalid_at>as_of) AND created_at<=as_of AND (expired_at IS NULL OR expired_at>as_of)`）提升为公开单一收口；`chunk_in_edges` 增 `as_of` 可选参数（默认 None=当前视图，既有调用方零回归）。
- `amodifies_chunk_edges(*, repository_id=None, target_chunk_id=None, as_of=None)`：target_chunk_id-scoped 经 `chunk_in_edges` chunk 反查收口 + 过滤 MODIFIES_CHUNK；repository_id-scoped 在 `relation=MODIFIES_CHUNK` + `source_entity__repository_id` 上叠加同款 bi-temporal 谓词；naive as_of 经 `require_aware` 拒绝。
- `areconcile_modifies_chunk_edges(repository_id, *, invalid_at)`：取该 repo base（branch_name=""）`ChunkRegistry` 指纹快照 + 活跃 MODIFIES_CHUNK 边，双信号判过期（① target_chunk_id 不存在 ② content_hash 漂移），过期边逐条经 `graph_store.invalidate_edge` 置位；缺指纹边仅按存在性保守判定；逐边 try/except 隔离（`IntegrityError`/`DoesNotExist` 仅 warning），返回失效计数。
- `indexer._run_modifies_chunk_reconcile(repository_id)`：与 `_run_sensitive_detection`/`_run_commit_index` 同款 best-effort fail-safe，挂在 `clone_and_index_repository` 收尾 `if not branch:` base 路径（功能分支 overlay 不触发）。

## Task Commits

Each task was committed atomically (TDD RED→GREEN for Task 1/2)：

1. **Task 1: as-of 查询 helper** — `0e9d47d4` (test, RED) → `e335ca27` (feat, GREEN)
2. **Task 2: 重索引对账置 invalid_at** — `4006600d`/`b4ee1ee2` (test, RED) → `66d9733b` (feat, GREEN)
3. **Task 3: 挂载对账到 reindex base 钩子** — `ff02fade` (feat)
4. **收尾去重: 去掉重复 TestReconcile 类** — `cb2bbde8` (fix)

## Files Created/Modified
- `server/knowledge/modifies_chunk.py` —（新建）`amodifies_chunk_edges` as-of 查询 helper + `areconcile_modifies_chunk_edges` 重索引对账失效。
- `server/knowledge/graph_store.py` — 新增公开 `bitemporal_as_of_q` 谓词；`chunk_in_edges` 增 `as_of` 可选参数（as-of 历史回溯，as_of=None 零回归）。
- `server/services/indexer.py` — 新增 `_run_modifies_chunk_reconcile` best-effort 钩子 + 在 `clone_and_index_repository` 收尾 base 路径调用。
- `server/tests/knowledge/test_modifies_chunk_reconcile.py` —（新建）`TestAsOfQuery`/`TestReconcile`/`TestReconcileHookFailSafe` 守护测试（11 用例）。

## Decisions Made
- as-of 谓词提升为公开 `bitemporal_as_of_q`（单一收口，避免在 modifies_chunk 复刻 raw 过滤导致与 neighbors/traverse 语义漂移）。
- 扩展 `chunk_in_edges` 增 `as_of`（尊重 chunk-lookup chokepoint），repo-scoped 路径直接查 relation+repo（不触 target_chunk_id 过滤，不违反 chokepoint）并加专门守护测试。
- 对账边先 materialize 再逐条 invalidate（规避 SQLite 读游标 + 写库锁竞争）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Task 2 RED 阶段产生重复 `TestReconcile` 类**
- **Found during:** 收尾自检（TDD Task 2 期间先后落了两版等价的 `TestReconcile`：一版用模块级 `_delete_chunk` helper（6 用例）、一版用内联 `ChunkRegistry` 删除（7 用例））。
- **Issue:** 同名类二次定义触发 ruff `F811`（redefinition），且 pytest 下后定义遮蔽前者——同文件两个 `TestReconcile` 是真实缺陷。
- **Fix:** 保留 helper 用法一致的那版（`_delete_chunk` 被引用），删除重复类；顺手删掉未被引用的 `_set_chunk_content_hash`（消除 unused-symbol）；`TestReconcileHookFailSafe` 原样保留。
- **Files modified:** server/tests/knowledge/test_modifies_chunk_reconcile.py
- **Commit:** `cb2bbde8`

---

（PLAN-CHECKER 澄清已遵守：target_chunk_id-scoped 走 `chunk_in_edges` chokepoint；repository_id-scoped 叠加同款 bi-temporal 谓词，并新增 `test_repository_scoped_as_of_and_current_view` 守护 repo 路径，避免欠规格。）

## Known Stubs
None —— 无悬空数据/占位渲染；`amodifies_chunk_edges` 为 CONTEXT 授权的最小 knowledge 内部查询面（不新建对外检索 UI）。

## Threat Flags
None —— 未引入计划 `<threat_model>` 之外的新信任边界。对账输入为本仓库自身 `ChunkRegistry` 状态（内部可信）；边失效唯一经 `graph_store.invalidate_edge` 收口（不裸写 update，不删除、不覆盖原失效时间，T-33-04）；整段 + 逐边 try/except 降级（T-33-05）；跨 repo 严格按 `source_entity.repository_id` 隔离、缺指纹保守不误失效（T-33-06）。

## Test Results
- 去重后：`pytest tests/knowledge/test_modifies_chunk_reconcile.py tests/knowledge/test_modifies_chunk.py -q --disable-socket` → **21 passed**（reconcile 文件 11 用例：4 AsOf + 6 Reconcile + 1 HookFailSafe；modifies_chunk 10 用例零回归）。
- `ruff check tests/knowledge/test_modifies_chunk_reconcile.py` → All checks passed（无 F811）。
- 既有图查询/反查零回归（test_modifies_chunk 全绿）。
- （无关 `tests/knowledge/test_triggers.py` 失败按指示忽略，未触碰。）

## Next Phase Readiness
- HDIFF-02 闭环：commit 锚定（33-01）+ 失效对账 + as-of 查询就位；PF-08 修复。
- 无新增 model 字段/migration；无阻断项。

## Self-Check: PASSED

- Files: `server/knowledge/modifies_chunk.py` / `server/tests/knowledge/test_modifies_chunk_reconcile.py` / `server/knowledge/graph_store.py` / `server/services/indexer.py` all FOUND.
- Commits: `0e9d47d4` / `e335ca27` / `4006600d` / `b4ee1ee2` / `66d9733b` / `ff02fade` / `cb2bbde8` all present in git log.

---
*Phase: 33-hist-diff-bitemporal*
*Completed: 2026-06-15*
