---
phase: 13-ingest
reviewed: 2026-06-11T14:18:00Z
depth: quick
files_reviewed: 10
files_reviewed_list:
  - server/knowledge/ingestion.py
  - server/knowledge/chunking.py
  - server/knowledge/vector_ops.py
  - server/knowledge/sources/__init__.py
  - server/knowledge/sources/coding_plan.py
  - server/knowledge/sources/mcp_plan.py
  - server/knowledge/management/commands/reconcile_delivery_knowledge.py
  - server/knowledge/management/commands/rebuild_delivery_knowledge.py
  - server/chat/models.py
  - server/mcp_tools/work_item_execution_service.py
findings:
  critical: 0
  warning: 1
  info: 3
  total: 4
status: issues_found
---

# Phase 13: Code Review Report

**Reviewed:** 2026-06-11T14:18:00Z
**Depth:** quick
**Files Reviewed:** 10
**Status:** issues_found

## Summary

对 Phase 13「统一摄取与版本化」10 个文件做 quick 单遍扫描（模式匹配 + 重点契约核对）。
反模式 grep（硬编码凭证 / eval / debug 残留 / 空 except）零命中。Phase 重点契约逐项核对结果：

- **三态幂等判定**：`_persist_sync` 在 `select_for_update` 锁内做权威判定，hash 相等分支（skipped / needs_revector）均返回既有 latest、绝不建新版本行；锁前预短路仅作 embed 成本优化，语义正确。✓
- **六步翻转次序与失败语义**：步 3 upsert 失败 raise（`upsert_knowledge_points` 将 `False` 转译为 `KnowledgeError`）、`vector_synced=True` 仅在 upsert 成功后置位；步 4 tombstone 失败 error 日志不再上抛（reconcile 检查项 2 兜底）；步 5 物理删点纯优化吞错。✓
- **对话原文不入 content**：`coding_plan.py` content 仅由 `plan.title + tech_plan` 拼成，零接触 conversation 消息。✓
- **payload 键集合**：`vector_ops.build_knowledge_points` 的 `_SCHEMA_KEYS` 来自 `knowledge.collection` 常量并在写入处自检 raise。✓
- **触发点接线**：三处宿主接线（`acreate_plan` / `aupdate_plan` / `execute_work_item_repo_tasks`）均经 `aschedule_ingestion` 唯一入口，函数体内 try/except 全吞 + warning；`run_in_background` 收到的是无参 coroutine factory（契约匹配）。✓（见 IN-02 的边界备注）
- **reconcile dry-run 默认零写**：六检查项全部在 `fix_mode` 判定之后才执行写动作；`rebuild` 无 `--yes` 仅打印退出。✓
- **aware datetime**：`ingest_events` 对每个 event 执行 `_require_aware`。✓
- **GraphStore 收口**：边读写全部经 `graph_store.neighbors / invalidate_edge / add_edge` 原语，reconcile 检查项 6 同样收口，未发现绕过。✓

发现 1 个 Warning（`revectorize_version` 在 chunk 数收缩时遗留不可对账的 stale 点）与 3 个 Info。

## Warnings

### WR-01: revectorize_version 在 chunk 数收缩时遗留 reconcile 检测不到的 stale latest 点

**File:** `server/knowledge/ingestion.py:357-361`
**Issue:** 当 `len(point_ids) != len(chunks)` 时直接用新派生 ids 覆写 `version.qdrant_point_ids`。`derive_point_ids` 对同一 `version_id` 是按 index 确定性派生的，因此当新 chunk 数**少于**旧值（典型场景：调大 `MAX_CHUNK_CHARS` 后 rebuild/reconcile 重嵌入，模块注释明确允许调整该常量），index ≥ 新数量的旧点会残留在 Qdrant 且 `is_latest=true`。这些残留点对六检查项全部免疫：`version_id` 在 PG 存在 → 非孤儿（检查项 4）；所属版本仍是 latest → 检查项 2 不适用；同 entity 同 version → 非 multi_latest（检查项 3）；检查项 1 只核对覆写后的新 ids。结果是召回面永久污染且无兜底可修。
**Fix:** 覆写前先下线被丢弃的旧 ids：

```python
old_ids = [str(pid) for pid in version.qdrant_point_ids]
if len(old_ids) != len(chunks):
    point_ids = derive_point_ids(version.id, len(chunks))
    dropped = [pid for pid in old_ids if pid not in set(point_ids)]
    if dropped:
        await tombstone_points(dropped)
        await delete_points(dropped)
    version.qdrant_point_ids = point_ids
    await version.asave(update_fields=["qdrant_point_ids"])
```

## Info

### IN-01: coding_plan content 与 event.title 在空标题时不一致

**File:** `server/knowledge/sources/coding_plan.py:44-55`
**Issue:** `title` 变量带 `plan.title or first_line[:200]` 回退，但 content 拼接固定用 `plan.title`、payload["title"] 也是 `plan.title`。当 `plan.title` 为空时，实体 title 是 tech_plan 首行，而 content 以空串开头（chunker strip 后无害）、payload.title 为空——三处"标题"语义分叉。若属 OQ-3 锁定拼法的有意结果，建议在注释中点明空标题分叉；否则 content/payload 应统一用回退后的 `title`。
**Fix:** `content=f"{title}\n\n{plan.tech_plan}"`（注意会改变既有实体的 content_hash，触发一次版本翻转），或注释说明现状。

### IN-02: 宿主接线的 lazy import 与请求构造位于异常吞噬边界之外

**File:** `server/chat/models.py:279-283, 296-300`; `server/mcp_tools/work_item_execution_service.py:598-603`
**Issue:** `aschedule_ingestion` 内部全吞异常，但三处宿主调用点的 `from knowledge import ingestion` 与 `IngestionRequest(...)` 构造发生在该边界之外。import 失败（如 knowledge 依赖链异常）会直接打断宿主主流程，违背"触发点异常全吞不阻塞宿主"的字面纪律。现实概率极低（依赖缺失时整个应用大概率起不来），故仅记 Info。
**Fix:** 如需绝对纪律，可将 import + 构造 + 调用整体包一层 `try/except Exception: logger.warning(...)`。

### IN-03: 跨模块 import 私有符号 `_require_aware`

**File:** `server/knowledge/ingestion.py:39`
**Issue:** 从 `knowledge.graph_store` import 下划线私有的 `_require_aware`，跨模块依赖私有 API，graph_store 重构时易悄然破坏。
**Fix:** 在 graph_store（或 knowledge 公共 util 模块）将其提升为公开符号 `require_aware` 并加入 `__all__`。

---

_Reviewed: 2026-06-11T14:18:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: quick_
