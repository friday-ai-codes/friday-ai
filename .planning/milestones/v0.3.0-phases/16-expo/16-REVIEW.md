---
phase: 16-expo
reviewed: 2026-06-12T12:00:00Z
depth: standard
files_reviewed: 18
files_reviewed_list:
  - server/knowledge/exposure.py
  - server/knowledge/api/views.py
  - server/knowledge/api/urls.py
  - server/agents/tools/delivery_knowledge_tools.py
  - server/workflows/nodes/ai/delivery_knowledge_search.py
  - server/workflows/nodes/ai/plan_generation.py
  - server/mcp_tools/views.py
  - server/mcp_tools/urls.py
  - server/mcp_tools/serializers.py
  - web/src/api/knowledge.ts
  - web/src/pages/knowledge/index.vue
  - web/src/pages/knowledge/entities/[id].vue
  - web/src/components/knowledge/EntityDetailToolbar.vue
  - web/src/components/knowledge/EntityMetadataCard.vue
  - web/src/components/knowledge/EntityVersionTimeline.vue
  - web/src/components/knowledge/EntityRelationTree.vue
  - web/src/components/knowledge/EntityKindBadge.vue
  - web/src/components/knowledge/ProvenanceLinkButton.vue
findings:
  critical: 2
  warning: 5
  info: 2
  total: 9
status: issues_found
---

# Phase 16: Code Review Report

**Reviewed:** 2026-06-12T12:00:00Z
**Depth:** standard
**Files Reviewed:** 18
**Status:** issues_found

## Summary

Phase 16 四入口（MCP / chat tools / workflow 节点 / JWT REST）+ 前端详情页整体架构清晰，`exposure.py` 统一 DTO 序列化避免了字段漂移，权限经 `DeliveryKnowledgeSearchService` + `access_scope` fail-closed 收口，与 Phase 16 CONTEXT 决策一致。

发现 **2 个 BLOCKER**（均已在本轮审查中修复）：
1. 前端关联实体树在默认 `max_hops=2` 时会静默丢失第二跳节点；
2. REST `related` 端点未校验 `direction`，非法值触发 graph_store `ValueError` → HTTP 500。

另有 5 个 WARNING（workflow 错误吞没、工具异常处理不一致、provenance URL 未校验等）建议在合并前或后续小 PR 处理。

## Critical Issues

### CR-01: EntityRelationTree 丢失多跳关联实体

**File:** `web/src/components/knowledge/EntityRelationTree.vue:18-38`（已修复）
**Issue:** `buildTree` 在找到 `depth - 1` 父节点时仅将子节点记入 `childIds`，从未挂入树结构。当同时存在 depth=1 与 depth=2 结果时，depth≥2 的实体从 UI 完全消失，违背 ENH-03「关联链」展示要求（默认 `max_hops=2`）。
**Fix:** 已改为按 `depth` 缩进的扁平列表，过滤当前实体后全部渲染：

```typescript
const tree = computed<TreeNode[]>(() =>
  props.related
    .filter(item => item.entity_id !== props.currentEntityId)
    .map(entity => ({ entity, children: [] })),
)
```

### CR-02: REST related 端点非法 direction 导致 500

**File:** `server/knowledge/api/views.py:151`（已修复）
**Issue:** `direction` 查询参数直接传入 `graph_store.traverse`，非法值（如 `direction=foo`）在 `RelationalGraphStore.neighbors` 抛出 `ValueError`，DRF 未捕获 → HTTP 500。
**Fix:** 已在视图中校验并返回 400：

```python
if direction not in ("both", "out", "in"):
    return Response(
        {"detail": "direction must be one of: both, out, in"},
        status=400,
    )
```

## Warnings

### WR-01: Workflow 节点吞没检索异常

**File:** `server/workflows/nodes/ai/delivery_knowledge_search.py:172-183`
**Issue:** `search_similar` 任意异常被捕获后仍以 `status="completed"` 返回空结果，下游无法区分「无命中」与「检索失败」。虽符合 CONTEXT「失败降级为空上下文」，但缺少 `warning` 字段或 `next_handle="error"` 选项，运维难以察觉 Qdrant/embedding 故障。
**Fix:** 至少在 `output` 中增加 `degraded: true` 与 `error_message`，或提供节点配置项选择 fail-fast。

### WR-02: Chat tools timeline/related 缺少异常兜底

**File:** `server/agents/tools/delivery_knowledge_tools.py:173-180,218-220`
**Issue:** `search_delivery_knowledge` 对 service 异常有 `try/except` 并返回 `ToolResult(success=False)`，但 `get_entity_timeline` 与 `get_related_entities` 直接 `await` service，异常会穿透 agent 运行时，行为不一致。
**Fix:** 与 search 对齐，包裹 `try/except` 返回结构化错误。

### WR-03: ProvenanceLinkButton 未校验 URL scheme

**File:** `web/src/components/knowledge/ProvenanceLinkButton.vue:34`
**Issue:** `provenance` 中的 `feishu_url` / `mr_url` / `session_link` 直接作为 `<a href>`。`metadata_hydrate._feishu_url` 可从 payload 读取任意字符串；若摄取数据被污染，`javascript:` 等 scheme 可导致点击型 XSS。
**Fix:** 渲染前过滤，仅允许 `http:`/`https:`；`session_link` 若非 URL 应渲染为文本而非链接。

### WR-04: Workflow 节点 user=None 时静默空结果

**File:** `server/workflows/nodes/ai/delivery_knowledge_search.py:125-136`
**Issue:** 无法解析 `triggered_by` 时返回 `completed` + 空结果，而 chat tools 同场景 fail-closed 拒绝检索。自动/系统触发的工作流可能误以为「无相似历史」。
**Fix:** 与 chat 对齐返回 `failed` + `next_handle="error"`，或至少在 output 中标注 `skipped_reason`。

### WR-05: session_link 可能非 URL 却被渲染为链接

**File:** `server/knowledge/metadata_hydrate.py:46`, `web/src/components/knowledge/ProvenanceLinkButton.vue:20-21`
**Issue:** `TECH_PLAN` 的 `session_link` 可能取自 `session_id`（非完整 URL），作为 `href` 会产生相对路径导航（如 `/knowledge/entities/abc123` 页内跳转到 `/session-id`）。
**Fix:** 后端规范化 session 链接为完整 URL，或前端检测 scheme 后再渲染 Button。

## Info

### IN-01: 知识库索引页为占位 stub

**File:** `web/src/pages/knowledge/index.vue`
**Issue:** `/knowledge` 路由仅展示说明文字，无搜索或列表入口；侧边栏已挂载该路由，用户体验不完整（深链场景可用）。
**Fix:** 后续增加搜索入口或重定向到文档说明即可，非本阶段阻塞项。

### IN-02: EntityRelationTree 无组件级测试

**File:** `web/src/components/knowledge/__tests__/entity-components.spec.ts`
**Issue:** 测试覆盖 `EntityKindBadge` 与 `EntityVersionTimeline`，未覆盖 `EntityRelationTree` 多跳渲染（CR-01 类回归无法自动捕获）。
**Fix:** 补充 depth=1/2 混合 fixture 的 vitest。

---

_Reviewed: 2026-06-12T12:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
