---
status: complete
---

# Quick Task 260808-0fm: 项目列表倒序排列并支持无限滚动按需加载 — Summary

**Date:** 2026-08-07
**Status:** complete

## 改动

### 后端（`server/initiatives/views.py`）

- `ProjectListCreateView` 抽出 `_visible_qs`（可见性 + 筛选），显式
  `order_by("-created_at")` —— join + distinct 场景不再依赖模型 `Meta.ordering`。
- additive 分页：请求带 `limit`（1..100，非法回退 24）时返回
  `{results, total, limit, offset}` 分页包；不带 `limit` 保持原数组响应，
  `BlueprintsTabPanel` 等既有调用方零改动。`offset` 负数/非法回退 0。
- 新增守护测试 3 个（`server/tests/initiatives/test_project_api.py`）：
  倒序 + 数组响应兼容、分页包切片/翻页无重叠/越界空页、非法参数回退。

### 前端（`web/`）

- `api/projects.ts`：新增 `ProjectPage` 类型与 `listPaged(filters, {limit, offset})`；
  筛选参数构建抽 `filterParams` 复用。
- `pages/projects/index.vue`：`useQuery` → `useInfiniteQuery`（每页 24 条，
  `getNextPageParam` 按 `offset + results.length < total`）；卡片网格后挂加载哨兵，
  `useIntersectionObserver`（rootMargin 400px 预取）进入视口自动 `fetchNextPage`，
  拉取中显示 spinner。筛选变化 queryKey 变更自动重置分页。
- 测试 mock 从 `list` 切到 `listPaged`（分页包响应），新增哨兵挂载/卸载守护用例。

## 决策记录

- 未引入 `@tanstack/vue-virtual` 做 DOM windowing：响应式多列网格 + window 滚动下
  实现复杂、收益低；分页按需加载已满足"到那再加载"的无感体验。若未来项目数上千
  可再评估。

## 验证

- `uv run pytest tests/initiatives/test_project_api.py` — 10 passed。
- `pnpm vitest run src/pages/projects/__tests__/projects-list.spec.ts` — 13 passed。
- ruff check / eslint 对改动文件无新增问题（既有 warning 不属本次范围）。
