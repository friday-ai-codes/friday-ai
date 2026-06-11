---
phase: 12-kmod
plan: "02"
status: complete
requirements_addressed: [KMOD-04, KMOD-02]
subsystem: knowledge
tags: [graph-store, recursive-cte, bi-temporal, sqlite-pg-portable, raw-sql-audit]
dependency_graph:
  requires:
    - "Plan 12-01（KnowledgeEntity/KnowledgeEntityVersion/KnowledgeEdge 三模型 + tests/knowledge/ conftest 工厂）"
  provides:
    - "GraphStore Protocol（add_edge/invalidate_edge/expire_edge/neighbors/traverse，全 async + keyword-only）"
    - "RelationalGraphStore 实现 + 模块级单例 graph_store（Phase 13+ 唯一图访问入口）"
    - "TraversalResult / EdgeRecord frozen dataclass"
    - "invalidate_entity_version 单事务级联失效原语（Phase 13 重摄取消费）"
    - "raw SQL 收口 grep 审计测试（WITH RECURSIVE / knowledge_knowledgeedge 仅限 graph_store.py）"
  affects:
    - "Plan 12-03（collection 生命周期，与本计划正交）"
    - "Phase 13 摄取（add_edge / invalidate_entity_version 消费方）"
    - "Phase 15 检索（traverse/neighbors 图扩散；接口 keyword-only 预留 scope 参数位）"
key-files:
  created:
    - server/knowledge/graph_store.py
    - server/tests/knowledge/test_graph_store.py
  modified: []
decisions:
  - "TraversalResult 首版只返回 (entity_id, depth)（Open Question 2 定案）；路径重建需求出现时再扩展字段"
  - "direction=\"both\" 在 traverse 中 raise NotImplementedError（接口预留，Phase 15 需要时扩展）；neighbors 支持 both（ORM 并集）"
  - "connection.vendor 白名单 (sqlite, postgresql)，MySQL 响亮 NotImplementedError（A1 定案）"
  - "防环用字符串 path + NOT LIKE（SQLite/PG 通吃），不用 PG 专属数组/CYCLE 子句"
metrics:
  duration: ~12min（含续接核验）
  tasks: 3
  files: 2
  tests: 19（18 默认收集 + 1 perf）
completed: 2026-06-11
---

# Phase 12 Plan 02: GraphStore 图访问收口 Summary

GraphStore service 接口落地：1–3 跳递归 CTE 遍历（SQLite/PG 双后端可移植）、bi-temporal 有效性过滤、字符串 path 防环、深度 clamp 全部内化于接口，`WITH RECURSIVE` 与边表 raw SQL 全仓收口到 `knowledge/graph_store.py` 并由 grep 审计测试固化。

## What Was Built

- **`server/knowledge/graph_store.py`（456 行，全仓唯一边表 raw SQL 存在地）**：
  - 模块 docstring 锁定三条实现契约：图访问唯一收口（换图引擎逃生门）/ 默认语义 = 当前有效（`invalid_at IS NULL AND expired_at IS NULL`，历史走显式 `as_of`）/ 接口全 keyword-only（Phase 15 权限 scope 参数扩展位，ASVS V4 预埋）。
  - `GraphStore(Protocol)` 五方法 + `RelationalGraphStore` 实现：写路径（`add_edge`/`invalidate_edge`/`expire_edge`）与单跳 `neighbors` 走 ORM（`sync_to_async` 桥接）；`add_edge` 做 relation 白名单、target XOR 接口层先行校验与 `_require_aware`。
  - `traverse`：`max(1, min(int(max_hops), MAX_HOPS=3))` clamp 后桥接 `_traverse_sync`；`_build_sql` 生成 `WITH RECURSIVE walk(entity_id, depth, path)`——anchor 1 跳邻居、递归项 `w.depth < %s` 深度上限 + path `NOT LIKE` 防环、外层 `GROUP BY entity_id` 取 `MIN(depth)` + `LIMIT 1000` fail-safe；占位符统一 `%s`，validity 谓词仅两个固定模板，relations 白名单后才生成占位符（T-12-01 零拼接）。
  - Pitfall 1 防线：`_prep_uuid`（`get_db_prep_value` 跨后端 UUID 格式分叉）/ `_to_uuid`（SQLite str / PG UUID 还原）；`connection.vendor` 白名单（MySQL 响亮失败）。
  - `invalidate_entity_version`：`transaction.atomic()` 内同时失效 latest 版本行与该实体全部活跃出入边（P2 级联失效原语；is_latest 翻转与重摄取触发在 Phase 13）。
  - structlog 事件：`knowledge_edge_added` / `knowledge_edge_invalidated` / `knowledge_entity_version_invalidated` / `knowledge_graph_traversed`（含 elapsed_ms）。
  - 模块尾部单例 `graph_store = RelationalGraphStore()`。
- **`server/tests/knowledge/test_graph_store.py`（425 行，19 用例）**：
  - 遍历行为：线性链 1–3 跳 / A→B→C→A 环终止（每实体一条 MIN depth）/ max_hops=10 clamp 到 3 / relations 过滤与非法值 ValueError / direction="in" 反向 / chunk 边不参与实体遍历。
  - 有效性与 as-of（KMOD-02）：失效边默认 traverse/neighbors 不可见、as_of=失效前时点可见、多跳中段失效下游不可达、expired_at 作废同样不可见、naive datetime 拒绝。
  - 级联失效：`invalidate_entity_version(B)` 后 B 的 latest 版本与出入边均失效，traverse(A, 3) 不再含 C。
  - UUID prep 专测：uuid.UUID 入参命中数据；对照组绕过 prep 用 `str(uuid)` 手工 cursor 查询为空。
  - grep 审计（P9 固化）：`WITH RECURSIVE` 与 `knowledge_knowledgeedge` 字面量的非测试源码文件集合 ⊆ {`knowledge/graph_store.py`}。
  - perf 基准（`@pytest.mark.perf`，CI 默认 deselect）：2000 实体 / 10000 边 3 跳 < 2s。

## Deviations from Plan

None - plan executed exactly as written.

（执行说明：三个任务 commit 由前一执行会话完成；本会话为续接执行，核验全部 acceptance criteria（grep 断言、`_build_sql` 递归项无 LIMIT、用例数、`-k "invalid or as_of"` 7 条全绿）后补交 SUMMARY 与状态更新，未重做任何任务。）

## Commits

| Task | Commit | Message |
|------|--------|---------|
| 1 | `91365ecb` | feat(12-02): GraphStore 接口、ORM 写路径与级联失效原语 |
| 2 | `37c520a4` | feat(12-02): 递归 CTE 遍历实现（SQLite/PG 双后端可移植） |
| 3 | `a4139f81` | test(12-02): GraphStore 行为、防线与 raw SQL 收口审计全套测试 |

## Known Stubs

- `traverse(direction="both")`：`_build_sql` 显式 raise NotImplementedError——计划内接口预留（docstring 注明 Phase 15 需要时扩展），非未完成项。

## Threat Flags

None — 本计划交付面与 PLAN.md `<threat_model>` 一致：T-12-01（全参数化 + relations 白名单 + validity 固定模板 + grep 审计测试）、T-12-03（clamp ≤3 + path 防环 + LIMIT 1000 + perf 基准）、T-12-02（keyword-only 扩展位）、T-12-04（只提供置位方法不提供 delete + structlog 留痕）全部落地，无新增安全面。

## Self-Check: PASSED

- 2 个交付文件存在（graph_store.py 456 行 ≥ 200；test_graph_store.py 425 行）
- `uv run pytest tests/knowledge/ -x` → 40 passed, 1 deselected（12-01 既有 22 条无回归）
- `uv run pytest tests/knowledge/test_graph_store.py -k "invalid or as_of"` → 7 passed（≥3）
- grep 审计：`WITH RECURSIVE` / `knowledge_knowledgeedge` 非测试源码仅 `knowledge/graph_store.py` 命中
- `rg -c "def (add_edge|...|traverse)"` = 10；`_require_aware` 命中 7（≥5）；`transaction.atomic` / `get_db_prep_value` / vendor 白名单源码断言全部命中
- `uv run python manage.py check` → 0 issues
- 3 个任务 commit（91365ecb / 37c520a4 / a4139f81）均在 git log
