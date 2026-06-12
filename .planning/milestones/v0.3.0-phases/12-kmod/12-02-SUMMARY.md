---
phase: 12-kmod
plan: "02"
status: complete
requirements_addressed: [KMOD-04, KMOD-02]
subsystem: knowledge
tags: [graph-store, recursive-cte, bi-temporal, sqlite-pg-portable, raw-sql-audit]
dependency_graph:
  requires:
    - "Plan 12-01（KnowledgeEntity/KnowledgeEntityVersion/KnowledgeEdge 三模型 + tests/knowledge/ 基建）"
  provides:
    - "GraphStore Protocol + RelationalGraphStore 实现 + 模块级单例 graph_store"
    - "1–3 跳递归 CTE 遍历（SQLite/PG 双后端，防环/深度 clamp/有效性过滤内置）"
    - "invalidate_entity_version 单事务级联失效原语"
    - "raw SQL 收口 grep 审计测试（WITH RECURSIVE / knowledge_knowledgeedge ⊆ graph_store.py）"
  affects:
    - "Phase 13 摄取（import graph_store 单例写边；invalidate_entity_version 重摄取消费）"
    - "Phase 15 检索（traverse/neighbors 图扩散；接口 keyword-only 留权限 scope 扩展位）"
key-files:
  created:
    - server/knowledge/graph_store.py
    - server/tests/knowledge/test_graph_store.py
  modified: []
decisions:
  - "递归 CTE anchor path 不含起点：环回到起点计 1 次后终止（A→B→C→A 结果含 A），与 Task 3 用例及 must_haves 对齐"
  - "direction='both' 多跳遍历本阶段 raise NotImplementedError（接口预留，Phase 15 需要时扩展）"
  - "MySQL/MariaDB 后端 _traverse_sync 响亮 NotImplementedError（A1 定案）"
metrics:
  duration: ~12min
  tasks: 3
  files: 2
  tests: 18 (+22 既有不回归)
completed: 2026-06-11
---

# Phase 12 Plan 02: GraphStore 图存储服务 Summary

GraphStore 图访问唯一收口落地：SQLite/PG 双后端可移植的 `WITH RECURSIVE` 1–3 跳遍历（字符串 path 防环 + 深度 clamp + 外层 LIMIT fail-safe），bi-temporal 有效性过滤埋进接口（默认当前有效、显式 as_of 查历史），并交付单事务级联失效原语与 grep 审计测试固化 raw SQL 收口。

## What Was Built

- **`server/knowledge/graph_store.py`（456 行，全仓唯一边表 raw SQL 存在地）**：
  - `TraversalResult` / `EdgeRecord` frozen dataclass；`GraphStore` Protocol 五方法（`add_edge` / `invalidate_edge` / `expire_edge` / `neighbors` / `traverse`，全 async、keyword-only——Phase 15 权限 scope 参数扩展位）。
  - `RelationalGraphStore`：写路径与单跳 `neighbors` 走 ORM（`acreate` / `aupdate`，目标缺失 raise `DoesNotExist`）；`traverse` 接口层 `max(1, min(int(max_hops), MAX_HOPS=3))` clamp 后经 `sync_to_async` 桥接到 `_traverse_sync`。
  - `_build_sql` 递归 CTE：`%s` 统一占位、字符串 path `NOT LIKE` 防环、递归项 `w.depth < %s`（LIMIT 仅最外层，PG 兼容）、validity 谓词仅两个固定模板（默认 / as_of 四参数绑定）、relations 经 `EdgeRelation.values` 白名单后才生成占位符（T-12-01 零拼接）、`e.target_entity_id IS NOT NULL` 排除 chunk 边。
  - `_prep_uuid`（`get_db_prep_value`，Pitfall 1 跨后端 UUID 格式分叉防线）/ `_to_uuid` 结果还原；`connection.vendor` 白名单（非 sqlite/postgresql 响亮 `NotImplementedError`）。
  - `invalidate_entity_version`：单 `transaction.atomic()` 内同时失效实体 latest 版本与全部活跃出入边；`_require_aware` P2 防线覆盖全部写路径与 as_of。
  - structlog 事件：`knowledge_edge_added` / `knowledge_edge_invalidated` / `knowledge_edge_expired` / `knowledge_entity_version_invalidated` / `knowledge_graph_traversed`（含 elapsed_ms）。
  - 模块尾部 `graph_store = RelationalGraphStore()` 单例。
- **`server/tests/knowledge/test_graph_store.py`（425 行，18 用例 + 1 perf）**：线性链 1–3 跳 / 环终止（{B,C,A} 每实体一条）/ clamp（max_hops=10 → 3）/ relations 过滤与非法值 ValueError / direction="in" / chunk 边排除 / 失效与作废默认不可见 / as_of 历史可见 / 中段失效下游不可达 / naive datetime 三入口拒绝 / 级联失效 / UUID prep 对照组（str(uuid) 手工查询为空）/ grep 审计两条 / `@pytest.mark.perf` 基准（2000 实体 / 10000 边 3 跳实测通过 < 2s）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] 递归 CTE anchor path 不含起点（计划内部规格冲突修正）**
- **Found during:** Task 2
- **Issue:** Task 2 action 给出的 path 初值 `',' || CAST(source) || ',' || CAST(target) || ','` 把起点写进 path，会使环边 C→A 被 `NOT LIKE` 防环判重拦截——与 Task 3 用例及 must_haves「A→B→C→A 结果集合 = {B, C, A}」矛盾。
- **Fix:** anchor path 只含首跳目标 `',' || CAST(target) || ','`：环回到起点时起点计 1 次（depth=3）后因进入 path 而终止，终止性不受影响（path 严格增长 + 深度上限双保险）。已在 `_build_sql` docstring 注明。
- **Files modified:** server/knowledge/graph_store.py
- **Commit:** 37c520a4

**2. [Minor] grep 审计用例位于模块级 `pytestmark = pytest.mark.django_db(transaction=True)` 之下**
- Task 3 注明审计用例"不标 django_db"，但模块级 pytestmark 按 pytest 语义作用于全模块。审计用例为纯文本扫描，django_db 标记仅引入无害的 DB fixture 开销；为满足验收标准「文件含 `pytest.mark.django_db(transaction=True)`」保留模块级标记。

## Commits

| Task | Commit | Message |
|------|--------|---------|
| 1 | `91365ecb` | feat(12-02): GraphStore 接口、ORM 写路径与级联失效原语 |
| 2 | `37c520a4` | feat(12-02): 递归 CTE 遍历实现（SQLite/PG 双后端可移植） |
| 3 | `a4139f81` | test(12-02): GraphStore 行为、防线与 raw SQL 收口审计全套测试 |

## Known Stubs

- `direction="both"` 多跳遍历：`_build_sql` 显式 `NotImplementedError`（接口预留，Phase 15 需要时扩展）——计划内有意预留（Task 2 action 字面要求），不阻塞本计划目标；单跳 `neighbors(direction="both")` 已实现。
- MySQL/MariaDB 后端：`_traverse_sync` 响亮 `NotImplementedError`（A1 定案，compose 官方栈为 PG）。

## Threat Flags

None — 本计划交付面与 PLAN.md `<threat_model>` 一致：T-12-01（全参数化 + relations 白名单 + validity 固定模板 + grep 审计测试）、T-12-03（clamp ≤3 + path 防环 + LIMIT 1000 + perf 基准实测通过）、T-12-02（keyword-only + docstring 扩展位注明）、T-12-04（只置位不删除 + structlog 留痕）均已落地，无新增安全面。

## Self-Check: PASSED

- 2 个交付文件存在（graph_store.py 456 行 ≥ 200；test_graph_store.py 425 行）
- `uv run pytest tests/knowledge/ -x` → 40 passed（18 新增 + 22 既有不回归，perf deselected）
- `uv run pytest tests/knowledge/test_graph_store.py -k "invalid or as_of"` → 7 passed ≥ 3
- `uv run pytest tests/knowledge/test_graph_store.py -m perf` → 1 passed（3 跳 < 2s 实测）
- grep 审计通过（`WITH RECURSIVE` 与 `knowledge_knowledgeedge` ⊆ {knowledge/graph_store.py}，审计测试本身即守护）
- `manage.py makemigrations --check --dry-run` → No changes detected
- 3 个任务 commit（91365ecb / 37c520a4 / a4139f81）均在 git log
