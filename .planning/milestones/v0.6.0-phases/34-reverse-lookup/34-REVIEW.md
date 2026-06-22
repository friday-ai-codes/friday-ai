---
phase: 34-reverse-lookup
reviewed: 2026-06-15T22:55:00Z
depth: deep
files_reviewed: 8
files_reviewed_list:
  - server/services/reverse_lookup.py
  - server/repositories/reverse_lookup_views.py
  - server/repositories/urls.py
  - server/mcp_tools/views.py
  - server/mcp_tools/serializers.py
  - server/mcp_tools/urls.py
  - server/knowledge/sources/feishu_work_item.py
  - server/delivery/services/comment_event_service.py
findings:
  critical: 0
  warning: 1
  info: 2
  total: 3
status: clean
fix_note: "WR-01 已修复（view 层 chunk_id UUID 校验 → 400 + 守护测试 test_malformed_chunk_id_400）；IN-01/IN-02 均已修复（裁剪 hydrate 集合、paths 按字段元组去重保序）。无 INFO 留作 advisory。"
---

# Phase 34: Code Review Report

**Reviewed:** 2026-06-15T22:55:00Z
**Depth:** deep
**Files Reviewed:** 8
**Status:** issues_found

## Summary

反查链路（RREF-01）与评论入图（RREF-02）整体实现稳健，核心安全/正确性约束均成立：

- **边方向全部正确**（对照生产写边约定核验）：`chunk ←MODIFIES_CHUNK code_change`（`chunk_in_edges`，source=code_change）、`code_change ←IMPLEMENTED_BY tech_plan`（`neighbors(direction="in")`，生产 `IMPLEMENTED_BY=tech_plan→code_change`）、`tech_plan ←HAS_PLAN work_item`（生产 `HAS_PLAN=work_item→tech_plan`）、`work_item →REFERENCES document`（`direction="out"`）。
- **当前视图正确**：`chunk_in_edges`/`neighbors` 均以 `as_of=None` 调用，过滤 `invalid_at IS NULL AND expired_at IS NULL`，过期 `MODIFIES_CHUNK` 边天然排除，历史失效关联不污染当前反查。
- **fail-closed 完整、无图路径泄漏**：`(file,line)` 走 `find_chunk_at`（既有 fail-closed）；`chunk_id` 直入经 `_resolve_chunk_by_id` 由 `ChunkRegistry` 复判 `file_path` 并经同一 matcher 复检（matcher 构造失败/路径越界/命中排除一律返回 `[]`），无绕过。反查只从**已放行的 chunk** 出发遍历，输出仅含需求/文档实体与该 chunk 自身关联路径——被排除文件的 chunk_id/行号/关联不会经图谱路径泄漏。
- **只读纪律**：service 仅调用 `chunk_in_edges` / `neighbors` / `_query_chunk_row` / `_hydrate_entities`，无任何图谱写/失效。
- **鉴权**：REST `IsAuthenticated`；MCP 继承 `McpToolView`（AccessToken/CookieJWT + `IsAuthenticated`）。
- **评论入图（INV-3）**：复用 `EntityKind.WORK_ITEM`，不新增枚举；评论树确定性渲染（`_render_comment_section` 按既有排序拍平）保证 hash-no-version；重投影仅 `created_count>0` 触发、`best-effort`（内层 `aschedule_ingestion` 全吞 + 外层 try/except），不阻塞/回滚评论落库。

发现 1 个 WARNING（REST `chunk_id` 入参未做 UUID 形态校验，畸形输入触 500）与 2 个 INFO。无 BLOCKER。

## Warnings

### WR-01: REST 反查端点未校验 `chunk_id` 形态，畸形入参触发 500

**File:** `server/repositories/reverse_lookup_views.py:35,63-69`
**Issue:** REST `ReverseLookupView` 从 `request.query_params.get("chunk_id")` 取**原始字符串**直接透传给 service。当只给 `chunk_id`（不给 `path`）时，畸形（非 UUID）值最终流到 `services.reverse_lookup._query_chunk_row` → `ChunkRegistry.objects.filter(chunk_id=<非UUID>)`，`ChunkRegistry.chunk_id` 为 `UUIDField`，会抛 `django.core.exceptions.ValidationError`。该异常不被 DRF 默认 exception handler 捕获，也未在 view/service 层兜底 → 返回 **HTTP 500**，而非 fail-closed 的空结果或 400。MCP 面已由 `ReverseLookupRequestSerializer` 的 `UUIDField` 保护，唯独 REST 面缺校验，行为不对齐（`line` 已显式校验，`chunk_id` 却未校验）。无数据/安全泄漏，但属可由外部入参触发的崩溃（健壮性/可用性缺陷）。
**Fix:** 在 view 层显式解析并 fail 到 400，与 `line` 校验同位置：
```python
import uuid
...
chunk_id = request.query_params.get("chunk_id")
if chunk_id:
    try:
        uuid.UUID(chunk_id)
    except (TypeError, ValueError):
        return Response(
            {"error": "chunk_id 必须为合法 UUID"},
            status=status.HTTP_400_BAD_REQUEST,
        )
```
（或在 `_query_chunk_row` 内 `try: uuid.UUID(chunk_id) except ValueError: return None` 与既有 fail-closed 返回空对齐。）

## Info

### IN-01: 多余的实体 hydrate（`tech_plan`/`code_change` 取回后未使用）

**File:** `server/services/reverse_lookup.py:137-138`
**Issue:** `entity_ids = set(work_item_ids) | set(document_ids) | tech_plan_ids | code_change_ids`，但 `_hydrate_entities` 的结果只用于序列化 `related_work_items` 与 `related_documents`；`tech_plan_ids` / `code_change_ids` 对应实体取回后从未使用，徒增一次查询的取回体量。
**Fix:** 仅 hydrate 需要序列化的 id：`entity_ids = set(work_item_ids) | set(document_ids)`（`paths` 仅需 id 字符串，不依赖 hydrate）。

### IN-02: `paths` 未去重，同 work_item 经多 chunk/多 tech_plan 可产生重复路径项

**File:** `server/services/reverse_lookup.py:124-134`
**Issue:** `related_work_items` / `related_documents` 经 `seen_*` 去重，但 `paths` 在每个 (chunk × code_change × tech_plan × work_item × document) 组合下无条件 `append`。若同一 code_change 被多个入参 chunk 命中、或同一 work_item 经多个 tech_plan 抵达，会产生语义重复（或近重复）路径项，客户端需自行去重。属契约清晰度/输出整洁问题，非正确性缺陷。
**Fix:** 如需稳定契约，可对 `paths` 按其字段元组去重，或在文档中明确「paths 为逐边组合、可能含重复起点」。

---

_Reviewed: 2026-06-15T22:55:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
