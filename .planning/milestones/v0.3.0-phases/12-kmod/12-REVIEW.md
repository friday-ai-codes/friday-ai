---
phase: 12-kmod
reviewed: 2026-06-11T11:35:05Z
depth: quick
files_reviewed: 8
files_reviewed_list:
  - server/knowledge/models.py
  - server/knowledge/graph_store.py
  - server/knowledge/collection.py
  - server/knowledge/exceptions.py
  - server/knowledge/management/commands/rebuild_delivery_knowledge.py
  - server/knowledge/migrations/0001_initial.py
  - server/tests/knowledge/conftest.py
  - server/system/models.py
findings:
  critical: 0
  warning: 4
  info: 4
  total: 8
status: fixed
fixed_at: 2026-06-11T11:55:00Z
fixed_findings: [WR-01, WR-02, WR-03, WR-04, IN-03]
---

# Phase 12: Code Review Report

**Reviewed:** 2026-06-11T11:35:05Z
**Depth:** quick
**Files Reviewed:** 8
**Status:** issues_found

## Summary

对 Phase 12「知识模型与图存储地基」8 个文件做了快速单遍扫描，重点按用户指定方向核查：raw SQL 参数化与注入面、双后端 UUID 处理、约束完整性、Qdrant 生命周期语义、时区 aware datetime。

**安全面结论（无 Critical）**：

- `graph_store._build_sql` 注入面干净：列名仅来自固定二分支（`source_entity_id`/`target_entity_id`），validity 谓词为两个固定模板，relations 经白名单校验后只生成 `%s` 占位符，`as_of`/`prep_id`/`hops`/`LIMIT` 全部参数绑定；`NOT LIKE` 中的字面 `%` 已正确转义为 `%%`（params 非空，转义必然生效）。参数顺序与 SQL 中占位符顺序逐一核对一致。
- 双后端 UUID 处理正确：进 SQL 经 `_prep_uuid`（`get_db_prep_value`），出结果经 `_to_uuid`（SQLite hex str / PG UUID 对象分流）。
- 时区防线到位：所有写路径入口走 `_require_aware`，测试 fixture 统一 `timezone.now()`。
- Qdrant 生命周期语义符合契约：mismatch 一律 raise 不删库，重建仅 `--yes` 命令；无硬编码密钥、无 eval/exec、无空 catch。

发现 4 个 Warning（边界值崩溃、hybrid 校验不完整、置位操作可覆盖历史）和 4 个 Info。

## Warnings

### WR-01: `_expected_dimension` 对空值 setting 直接 `int()` 崩溃

**Status:** ✅ fixed（commit `b476f8d1`）—— 空值/空白回退默认 1024；非数字值回退默认并 structlog warning；新增 4 个边界测试。
**File:** `server/knowledge/collection.py:82`
**Issue:** `SystemSetting.value` 是 `TextField(blank=True, null=True)`（见 `server/system/models.py:15`）。当 `embedding_dimension` 这条 setting 存在但 value 为 `None` 或空串时，`int(dimension_setting.value)` 抛 `TypeError`/`ValueError`，而非回退默认 1024。`ensure_delivery_knowledge_collection` 是启动路径，会被这个边界值打挂。
**Fix:**

```python
async def _expected_dimension() -> int:
    dimension_setting = await SystemSetting.objects.filter(
        key=SettingKeys.EMBEDDING_DIMENSION
    ).afirst()
    if dimension_setting and dimension_setting.value:
        return int(dimension_setting.value)
    return 1024
```

### WR-02: hybrid 结构校验只验 dense 维度，未验 sparse 存在性

**Status:** ✅ fixed（commit `ab15c074`）—— dense 维度比对后追加 sparse named vector 存在性校验，缺失即 raise KnowledgeCollectionMismatchError 且不删库；新增 2 个测试。
**File:** `server/knowledge/collection.py:152-197`
**Issue:** 模块文档声称"collection 存在且**维度/hybrid 结构**匹配 → 通过"，但实际校验只覆盖两种情况：非 dict（单向量）→ raise；dict 中 `dense` 维度不符 → raise。从未检查 `sparse_vectors_config` 是否存在 `sparse` named vector。一个只有 named dense（无 sparse）的既存 collection 会静默通过校验，Phase 13 写 sparse 向量时才在摄取路径上失败——这正是本模块要防的"写入错库比报错更危险"。
**Fix:** 在维度比对后追加 sparse 校验：

```python
sparse_config = collection_info.config.params.sparse_vectors
if not sparse_config or "sparse" not in sparse_config:
    raise KnowledgeCollectionMismatchError(
        "delivery_knowledge collection 缺少 sparse named vector（非 hybrid 结构）。...",
        details={"existing_sparse": False},
    )
```

### WR-03: `invalidate_edge` / `expire_edge` 可重复置位，静默覆盖既有时间戳

**Status:** ✅ fixed（commit `9d56418f`，格式对齐 `672446c9`）—— 仅在目标时间戳为 NULL 时置位；0 行更新时区分"边不存在"（raise DoesNotExist）与"已置位"（幂等 no-op + warning 日志）；新增 3 个测试锁定语义。
**File:** `server/knowledge/graph_store.py:192, 202`
**Issue:** 两个置位方法都是无条件 `filter(id=edge_id).aupdate(...)`。对一条已失效（`invalid_at` 已置位）的边再次调用 `invalidate_edge` 会**覆盖**原失效时间——bi-temporal 模型里这等于改写历史，与"失效置位不删除、历史可审计"（locked decision / T-12-04 防线）直接冲突。`as_of` 历史查询的结果会随之漂移。`expire_edge` 同理。
**Fix:** 过滤条件加 `invalid_at__isnull=True`（已失效则 0 行更新，按需 raise 或幂等返回）：

```python
updated = await KnowledgeEdge.objects.filter(
    id=edge_id, invalid_at__isnull=True
).aupdate(invalid_at=invalid_at)
```

并区分"边不存在"与"边已失效"两种 0 行情况给出明确错误。

### WR-04: `invalidate_entity_version` 同样可覆盖已置位的 `invalid_at`，且边过滤遗漏 `expired_at`

**Status:** ✅ fixed（commit `62333455`）—— 版本行过滤补 `invalid_at__isnull=True`（防覆盖），级联边过滤补 `expired_at__isnull=True`（已作废边不再触碰）；新增 2 个测试锁定语义。
**File:** `server/knowledge/graph_store.py:434-442`
**Issue:** 两个问题：
1. 版本行过滤只有 `is_latest=True`，没有 `invalid_at__isnull=True`——对已失效的 latest 版本重复调用会覆盖其原失效时间（同 WR-03 的历史改写问题）。
2. 边过滤只有 `invalid_at__isnull=True`，缺 `expired_at__isnull=True`——已被系统时间线作废（expired）的边会被再补一个业务失效时间戳，污染已作废记录。
**Fix:**

```python
version_count = KnowledgeEntityVersion.objects.filter(
    entity_id=entity_id, is_latest=True, invalid_at__isnull=True
).update(invalid_at=invalid_at)
edge_count = KnowledgeEdge.objects.filter(
    Q(source_entity_id=entity_id) | Q(target_entity_id=entity_id),
    invalid_at__isnull=True,
    expired_at__isnull=True,
).update(invalid_at=invalid_at)
```

## Info

### IN-01: `uniq_kedge_active` 不覆盖 chunk 边（NULLS DISTINCT 漏洞）

**File:** `server/knowledge/models.py:295-300`
**Issue:** 活跃边唯一约束含 `target_entity` 字段；当 `target_entity` 为 NULL（MODIFIES_CHUNK chunk 边）时，SQLite/PG 默认 NULLS DISTINCT，约束完全不生效——同 (source, relation, target_chunk_id) 可产生任意多条重复活跃边。Phase 14 交付 MODIFIES_CHUNK 写入路径前需补充针对 chunk 边的唯一约束（或在写入路径做 upsert 去重）。本阶段无写入路径，仅提示。
**Fix:** Phase 14 时追加约束，例如 `UniqueConstraint(fields=["source_entity", "target_chunk_id", "relation"], condition=Q(target_entity__isnull=True, invalid_at__isnull=True, expired_at__isnull=True), name="uniq_kedge_active_chunk")`。

### IN-02: `invalidate_entity_version` 对不存在的实体静默成功

**File:** `server/knowledge/graph_store.py:434-445`
**Issue:** 实体不存在时 update 计数为 0，函数只记录 `version_count=0, edge_count=0` 日志后正常返回；而同文件的 `invalidate_edge`/`expire_edge` 对不存在目标 raise `DoesNotExist`。行为不一致，调用方 typo entity_id 时不会得到任何信号。
**Fix:** 与边方法对齐——`version_count == 0` 且实体不存在时 raise，或在 docstring 明示幂等语义。

### IN-03: rebuild 命令跨模块 import 私有函数 `_expected_dimension`

**Status:** ✅ fixed（commit `45ffd174`）—— 更名为公开函数 `get_expected_dimension` 并加入 `__all__`，rebuild 命令同步改用公开 API（公开名避开 ensure 内同名局部变量的遮蔽）。
**File:** `server/knowledge/management/commands/rebuild_delivery_knowledge.py:25, 95`
**Issue:** 从 `knowledge.collection` import 下划线前缀的 `_expected_dimension`（且该函数不在 `collection.__all__` 中），跨模块依赖私有 API。
**Fix:** 在 `collection.py` 中将其更名为公开函数（如 `expected_dimension`）并加入 `__all__`，或由 `ensure_delivery_knowledge_collection` 返回维度供命令复用。

### IN-04: TODO 占位（Phase 13 全量重嵌入）

**File:** `server/knowledge/management/commands/rebuild_delivery_knowledge.py:10`
**Issue:** `TODO(Phase 13)`——接入摄取管线后 rebuild 需扩展"从 PG 全量重嵌入"步骤。属于已声明的阶段边界占位，非缺陷；记录在案以便 Phase 13 跟踪，避免出现"重建后 collection 为空但 PG 有数据"的静默不一致。
**Fix:** Phase 13 计划中显式列入该扩展项。

---

_Reviewed: 2026-06-11T11:35:05Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: quick_
