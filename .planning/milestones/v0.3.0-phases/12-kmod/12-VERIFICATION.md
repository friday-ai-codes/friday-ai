---
phase: 12-kmod
verified: 2026-06-11T11:56:00Z
reverified: 2026-06-11T12:05:00Z
status: passed
score: 6/6 must-haves verified
overrides_applied: 0
human_verification: []
---

# Phase 12: 知识模型与图存储地基 Verification Report

**Phase Goal:** 交付知识有统一、可审计、带时间语义的存储底座，图访问唯一收口于 GraphStore 接口
**Verified:** 2026-06-11T11:56:00Z
**Status:** passed（初验 human_needed；PG 实跑闭环后复核通过）
**Re-verification:** Yes — orchestrator 以临时 `postgres:17-alpine` 容器实跑 PG 方言路径，原 Manual-Only 项已自动化闭环

## Goal Achievement

### Observable Truths

| #   | Truth   | Status     | Evidence       |
| --- | ------- | ---------- | -------------- |
| 1 | SC1：四类实体（work_item/tech_plan/code_change/document）统一模型落库，携带 source_kind+source_id、origin、event_time | ✓ VERIFIED | `server/knowledge/models.py`（334 行）：`KnowledgeEntity` + `EntityKind`/`EntityOrigin` 枚举 + `uniq_kentity_natural_key` 唯一约束 + `kentity_kind_valid`/`kentity_origin_valid` CheckConstraint；`generate_entity_id` uuid5 幂等实测通过；`test_models.py` 22 用例全绿（含同 natural key 二次 create IntegrityError、非法枚举值 DB 兜底） |
| 2 | SC2：bi-temporal 四时间戳边，失效置位不删除，默认遍历不可见但历史（as_of）可查 | ✓ VERIFIED | `KnowledgeEdge` 含 valid_at/invalid_at/created_at/expired_at + `kedge_valid_range`/`uniq_kedge_active`/`kedge_target_xor` 约束；`graph_store.py` 默认谓词 `invalid_at IS NULL AND expired_at IS NULL`，as_of 走 4 参数固定模板；`test_graph_store.py` 失效不可见/as_of 历史可见/expired 不可见/中段失效下游不可达用例全绿；WR-03/04 修复后置位不可覆盖（防改写历史，3+2 个新增测试锁定） |
| 3 | SC3：GraphStore 1–3 跳递归遍历，自动施加有效性过滤、深度上限、防环；边表 raw SQL 仅存在于 GraphStore 实现内 | ✓ VERIFIED | `graph_store.py`（489 行）：`MAX_HOPS=3` clamp（`max(1, min(int(max_hops), MAX_HOPS))` 源码确认）、字符串 path `NOT LIKE` 防环、外层 LIMIT 1000、`connection.vendor` 白名单；独立 grep 复核：`WITH RECURSIVE` 与 `knowledge_knowledgeedge` 在非测试源码中仅命中 `server/knowledge/graph_store.py`；`test_raw_sql_audit_*` 两条审计测试存在且通过；环终止/clamp 用例（`test_cycle_terminates_each_entity_once`/`test_max_hops_clamp_to_three`）全绿 |
| 4 | SC4：supersedes 版本链，旧版本保留且可按版本号回溯 | ✓ VERIFIED | `KnowledgeEntityVersion`：supersedes self FK（`on_delete=PROTECT`）+ `uniq_kversion_entity_version` + `uniq_kversion_one_latest` 条件唯一 + `kversion_valid_range`；test_models.py v1→v2→v3 链回溯、双 latest 撞约束、删除被引用版本 ProtectedError 用例全绿 |
| 5 | SC5：delivery_knowledge collection 显式生命周期——mismatch 响亮拒绝绝不删库，payload schema（含权限维度）第一天定型 | ✓ VERIFIED | `collection.py`（253 行）：8 索引字段恰为 {entity_kind, entity_id, version, is_latest, project_id, repository_id, source_kind, event_time}（运行时断言通过）；`rg "delete_collection" collection.py`=0；mismatch 三分支（非 hybrid/维度/缺 sparse，WR-02 补全）均 raise `KnowledgeCollectionMismatchError` 且 message 含 `rebuild_delivery_knowledge --yes` 指引；`rebuild_delivery_knowledge` 命令注册可发现，无 `--yes` 零副作用；test_collection.py 含 `delete_collection.assert_not_called()` 断言，全绿 |
| 6 | （Plan 02 增项）invalidate_entity_version 单事务内同时失效版本与出入边，失效后下游多跳不可达 | ✓ VERIFIED | `graph_store.py:449-485`：`transaction.atomic()` 内版本行（`is_latest=True, invalid_at__isnull=True`）与活跃出入边（双时间戳 NULL 过滤，WR-04 修复）同步置位；级联失效测试 + 防覆盖 2 个新增测试全绿 |

**Score:** 6/6 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `server/knowledge/models.py` | 三模型 + 三枚举 + generate_entity_id，≥150 行，含 `class KnowledgeEntity` | ✓ VERIFIED | 334 行；`__all__` 8 项齐备；10 个约束 + 6 个索引（含条件索引 `idx_kedge_active_fanout`）与计划一致 |
| `server/knowledge/migrations/0001_initial.py` | 三表 + 全部约束/索引 | ✓ VERIFIED | 345 行；10 个约束名全部命中；`makemigrations --check --dry-run` → No changes detected |
| `server/knowledge/graph_store.py` | GraphStore Protocol + RelationalGraphStore + 单例 + invalidate_entity_version，≥200 行 | ✓ VERIFIED | 489 行；6 个导出全部 import 成功；`_prep_uuid` 走 `get_db_prep_value`；relations 白名单后才生成 `%s` 占位符 |
| `server/knowledge/collection.py` | schema 常量 + ensure 函数 | ✓ VERIFIED | 253 行；`QdrantService.get_client` 唯一 client 路径（`QdrantClient(`=0）；`return False`=0；WR-01 边界值防线（空/非法 dimension 回退 1024）已落地 |
| `server/knowledge/exceptions.py` | KnowledgeError + KnowledgeCollectionMismatchError | ✓ VERIFIED | 35 行，含 `class KnowledgeCollectionMismatchError`，import 成功 |
| `server/knowledge/management/commands/rebuild_delivery_knowledge.py` | --yes 确认流程 | ✓ VERIFIED | 95 行；无 --yes 仅打印 WARNING 横幅后 return；delete 调用仅在 `_rebuild` 内且仅 `--yes` 触达；IN-03 修复后改用公开 `get_expected_dimension` |
| `server/tests/knowledge/conftest.py` | 4 个 fixture | ✓ VERIFIED | 114 行；entity/version/edge factory + mock_qdrant_client 齐备，aware datetime |
| `server/tests/knowledge/test_models.py` | KMOD-01/02/03 全套约束测试 | ✓ VERIFIED | 300 行；含 EXPLAIN QUERY PLAN `idx_kedge_fanout` 断言 |
| `server/tests/knowledge/test_graph_store.py` | 遍历/防环/clamp/有效性/as-of/级联/审计/perf | ✓ VERIFIED | 510 行；审计/环/clamp/中段失效测试函数名 rg 命中 5 处；`@pytest.mark.perf` 基准存在 |
| `server/tests/knowledge/test_collection.py` | 生命周期/维度校验/重建命令测试 | ✓ VERIFIED | 299 行；含 `assert_not_called` P8 核心断言 |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | --- | --- | ------ | ------- |
| `friday/settings.py` | knowledge app | INSTALLED_APPS | ✓ WIRED | `settings.py:100` `"knowledge",` |
| `test_models.py` | `knowledge/models.py` | import 模型与枚举 | ✓ WIRED | `from knowledge.models import` 命中 |
| `graph_store.py` | knowledge_knowledgeedge 表 | 递归 CTE raw SQL | ✓ WIRED | `WITH RECURSIVE` 仅此文件（独立 grep + 审计测试双重确认） |
| `graph_store.py` | 异步调用方 | sync_to_async 桥接 | ✓ WIRED | `sync_to_async(self._traverse_sync)` 命中（`traverse():309`） |
| `collection.py` | QdrantService.get_client | 唯一 client 路径 | ✓ WIRED | 命中 1 处，无自建 `QdrantClient(` |
| `rebuild_delivery_knowledge.py` | `collection.py` | ensure 调用复用 | ✓ WIRED | `ensure_delivery_knowledge_collection` 命中 3 处 |
| `system/models.py` | collection 元信息 | SettingKeys 新键 | ✓ WIRED | `KNOWLEDGE_COLLECTION_META = "knowledge_collection_meta"`（`models.py:76`） |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| 阶段测试套件全绿 | `uv run pytest tests/knowledge/ -q` | 60 passed, 1 deselected (perf) | ✓ PASS |
| 模型与 migration 同步 | `manage.py makemigrations --check --dry-run` | No changes detected | ✓ PASS |
| generate_entity_id uuid5 幂等 / 异 kind 异 id | python 内联断言 | OK | ✓ PASS |
| `_build_sql` 双后端规格 | 含 WITH RECURSIVE / NOT LIKE / LIMIT，无 `?` 占位符 | OK | ✓ PASS |
| schema 常量契约 | 8 索引字段键集合精确匹配 | OK | ✓ PASS |
| 命令可发现 | `get_commands()['rebuild_delivery_knowledge'] == 'knowledge'` | OK | ✓ PASS |
| raw SQL 收口 grep 复核 | `rg -l` 非测试源码 | 两个模式均仅 `knowledge/graph_store.py` | ✓ PASS |
| PG 方言路径实跑 | `postgres:17-alpine` 容器 + `DATABASE_URL` → `pytest tests/knowledge/` | test_graph_store 23 passed；全套 59 passed + 1 skip（EXPLAIN 断言为 SQLite 专属，已加 vendor skipif，commit ae24b421） | ✓ PASS |

### Probe Execution

无声明 probe（非 migration/CLI probe 阶段）——SKIPPED。

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| KMOD-01 | 12-01, 12-03 | 统一实体模型（四类实体 + 稳定业务引用 + 来源 + 事件时间） | ✓ SATISFIED | Truth 1 + Truth 5（payload schema 含 entity 维度字段） |
| KMOD-02 | 12-01, 12-02 | bi-temporal 四时间戳边，失效置位，历史可审计 | ✓ SATISFIED | Truth 2（DB 面 + 行为面 + WR-03/04 防改写历史加固） |
| KMOD-03 | 12-01 | supersedes 版本链，按版本号回溯 | ✓ SATISFIED | Truth 4 |
| KMOD-04 | 12-02 | 图读写收敛于 GraphStore（遍历/有效性/防环/深度上限），无裸 SQL 旁路 | ✓ SATISFIED | Truth 3 + Truth 6（SQLite 与 PG 双后端实跑均全绿） |

无 ORPHANED requirement：REQUIREMENTS.md 映射至 Phase 12 的 4 个 ID 全部被 plan frontmatter 认领。

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| `server/knowledge/management/commands/rebuild_delivery_knowledge.py` | 10 | `TODO(Phase 13)` 全量重嵌入扩展 | ℹ️ Info | 引用 ROADMAP Phase 13 正式后续工作（REVIEW IN-04 已记录），当前 collection 无数据，重建=删+建语义自洽，非债务 |
| `server/knowledge/graph_store.py` | 380-383 | `direction="both"` 多跳 `NotImplementedError` | ℹ️ Info | 计划 Task 2 字面要求的接口预留（Phase 15 扩展位）；单跳 neighbors 的 both 已实现 |
| `server/knowledge/models.py` | 71 | `MODIFIES_CHUNK` 枚举占位 | ℹ️ Info | 计划内 Phase 14 占位（docstring 注明），XOR 约束已测试 |

无 TBD/FIXME/XXX 债务标记；无 PLACEHOLDER/空实现/硬编码空数据 stub（`placeholders` SQL 变量名为误匹配排除）。REVIEW 发现的 WR-01..04 + IN-03 五项已修复，6 个修复 commit（b476f8d1/ab15c074/9d56418f/672446c9/62333455/45ffd174）与 9 个任务 commit 全部在 git log 中核实存在。

### Human Verification Required

无 —— 原 Manual-Only 项「PostgreSQL 后端递归 CTE 实跑」已由 orchestrator 闭环：

- 临时容器 `postgres:17-alpine`（端口 55433），`DATABASE_URL=postgres://...` 实跑
- `tests/knowledge/test_graph_store.py` → **23 passed**（递归 CTE PG 方言、psycopg 原生 UUID 回传分支实证）
- 全套 `tests/knowledge/` → 59 passed + 1 skip（`test_edge_fanout_query_uses_fanout_index` 使用 SQLite 专有 `EXPLAIN QUERY PLAN` 且 PG planner 小数据集下可合法选 seq scan，已标记 `skipif(vendor != "sqlite")`，commit `ae24b421`）

### Gaps Summary

无 gap。6 项必真陈述全部在代码层证实：三张地基表的全部 DB 不变量（10 约束）有 migration 落库与 22 条直接 create 测试固化；GraphStore 收口经独立 grep 与审计测试双重确认（`WITH RECURSIVE` / 边表字面量仅 `graph_store.py`）；bi-temporal 失效语义在 code review 后进一步加固为"置位不可覆盖"（防改写历史）；collection 生命周期零删库路径（`delete_collection` 在 ensure 中 0 次出现 + `assert_not_called` 测试）。全仓 108 个 pre-existing failures（test_orchestration_* / workflows/test_engine）已在基线 commit 2ae0d8a1 确认与本阶段无关，不计入。唯一余项为 PG 方言路径人工验证（外部服务依赖）。

---

_Verified: 2026-06-11T11:56:00Z_
_Verifier: Claude (gsd-verifier)_
