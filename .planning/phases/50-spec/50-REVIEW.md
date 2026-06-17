---
phase: 50-spec
reviewed: 2026-06-17T11:35:00Z
depth: deep
files_reviewed: 14
files_reviewed_list:
  - server/delivery/models/sdd_spec_review.py
  - server/delivery/models/__init__.py
  - server/delivery/migrations/0019_sddspecreview.py
  - server/delivery/services/sdd_spec_service.py
  - server/delivery/services/__init__.py
  - server/delivery/api/spec_views.py
  - server/delivery/api/serializers.py
  - server/delivery/spec_urls.py
  - server/friday/urls.py
  - web/src/api/specs.ts
  - web/src/components/spec/SpecTransitionActions.vue
  - web/src/components/spec/SpecReviewDialog.vue
  - web/src/components/spec/SpecReviewTimeline.vue
  - web/src/components/spec/SddSpecStatusBadge.vue
  - web/src/pages/specs/index.vue
  - web/src/pages/specs/[id].vue
  - web/src/locales/zh-CN.json
  - web/src/components/layout/AppSidebar.vue
findings:
  critical: 0
  warning: 1
  info: 2
  total: 3
status: issues_found
---

# Phase 50: Code Review Report

**Reviewed:** 2026-06-17T11:35:00Z
**Depth:** deep
**Files Reviewed:** 14（含跨文件追踪 service → view → serializer → 前端）
**Status:** issues_found

## Summary

对 Phase 50（spec 状态机 + 评审 + 前端展示）做了对抗式深审，重点核验了你列出的全部安全/正确性不变式：

- **状态机合法流转表**：5 个动作（submit/approve/reject/mark_implemented/archive）与 5 态映射正确；archive 用 `.exclude(status=archived)` 覆盖「任意非 archived → archived」。✓
- **幂等 fail-loud / 无竞态双推进**：三条流转路径（`_simple_transition` / `_archive` / `_review_transition`）一律 `filter(status=from).update(status=to)` 条件更新 + `updated == 0 → raise`。DB 行锁串行化两个并发 approve：先到者锁行更新成功，后到者重判 `status=in_review` 命中 0 行回滚——**无 0 行静默成功、无双推进**。✓
- **approve/reject 单一事务原子**：`transaction.atomic()` 内先建 `SddSpecReview` 再条件流转，0 行 `raise` 在事务内传播 → 回滚评审 → **无孤儿评审、无状态漂移**。✓（`test_illegal_transition_400` 等覆盖）
- **SddSpecReview 不可篡改**：模型仅 `__str__` 无 edit/delete/save；序列化器全 `read_only_fields = fields`；INV-6 grep 守护同时锚定 `SddSpec` 与 `SddSpecReview` 旁路写并自检 writer 实写。✓
- **权限 fail-closed**：approve/reject/archive/mark_implemented 在 **API 层** 显式 `request.user.is_superuser` 判定（非仅前端隐藏）；403 早于 404 不泄漏存在性（`test_forbidden_takes_precedence_over_not_found`）；reviewer 强制取 `request.user` 不接受 body。✓
- **INV-6 收口**：`SddSpec` / `SddSpecReview` 唯一写入点为 `SddSpecService`。✓
- **async ORM**：list/detail 均 `select_related` + `Prefetch(reviews→select_related(reviewer))`，序列化全 `sync_to_async` 包裹，无裸 lazy-FK。✓
- **前端**：按钮按 状态×权限 显隐与后端一致（前端仅 UX 隐藏，后端为边界）；reject comment 前端必填 + 后端二次拦截；transition 成功后 `invalidate(['specs'])` + `invalidate(['spec', id])`；i18n 单 `specs` 顶层键无重复。✓

实现整体质量高。仅发现 1 处健壮性 WARNING 与 2 处轻微 Info，均非安全/数据丢失级。

## Warnings

### WR-01: reject 流转对非字符串 `comment` 抛 500 而非 400

**File:** `server/delivery/api/spec_views.py:139-144`
**Issue:** `comment = request.data.get("comment") or ""` 不保证类型为 str。当请求体 `comment` 为非字符串真值（如 `{"action":"reject","comment":123}` 或 `["x"]`）时，`123 or "" → 123`，随后 `if action == "reject" and not comment.strip()` 触发 `int.strip()` → `AttributeError` 未捕获 → 返回 **500 Internal Server Error** 而非预期的 400。该路径受 superuser 限制（reject ∈ `_RESTRICTED_ACTIONS`），故影响面有限（非匿名/普通用户可达），但仍是对用户可控输入的未处理异常路径；approve 路径虽不 `.strip()`，但会把非 str 透传给 `SddSpecReview.comment`（TextField 落库时强转字符串，行为隐式）。
**Fix:** 读 comment 后统一强制为字符串再处理，使非法类型走既有 400 而非 500：

```python
comment_raw = request.data.get("comment")
comment = comment_raw if isinstance(comment_raw, str) else ""
if action == "reject" and not comment.strip():
    return Response(
        {"error": "驳回必须填写评审意见"},
        status=status.HTTP_400_BAD_REQUEST,
    )
```

## Info

### IN-01: 评审对话框确认后同时触发 `confirm` 与 `cancel` 事件（冗余）

**File:** `web/src/components/spec/SpecTransitionActions.vue:67-76`, `web/src/components/spec/SpecReviewDialog.vue:60-63`
**Issue:** 点击确认 → `onReviewConfirm` 内 `dialogOpen.value = false`，关闭会触发 Dialog 的 `@update:open(false)` → `emit('cancel')` → `onReviewCancel`。结果一次确认会先后跑 `onReviewConfirm`（真正流转）与 `onReviewCancel`（仅再次置 false）。当前无害（不会二次流转），但属冗余事件，后续若在 cancel 里加副作用（如埋点/重置）会出意外。
**Fix:** 确认路径不依赖 `dialogOpen` 关闭副作用即可，或在 `onReviewConfirm` 里加一次性标志位避免 cancel 二次执行；保持现状亦可（仅提示）。

### IN-02: 列表页 0 结果时仓库筛选标签显示「全部」但仍按旧 `repository_id` 过滤

**File:** `web/src/pages/specs/index.vue:49-65`
**Issue:** `repoOptions` 从当前查询结果 `specs.value` 派生。当叠加状态筛选导致结果为空时，`repoOptions` 为空 → `repoLabel` 回退为 `t('specs.filter.all')`，但 `repositoryFilter.value` 仍保留旧仓库 id，`queryParams` 仍下发 `repository_id`。此时下拉显示「全部」却仍在按某仓过滤，状态与展示不一致（边缘场景，非常规路径）。
**Fix:** `repoOptions` 改为不依赖筛选结果（例如独立拉取仓库列表或并入 `__all__` 兜底项），或在结果为空时清理无效的 `repositoryFilter`，使标签与实际过滤一致。

---

_Reviewed: 2026-06-17T11:35:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
