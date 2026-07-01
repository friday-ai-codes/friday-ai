---
phase: 96-external-deps-search-overview
plan: 03
subsystem: knowledge-api
tags: [knowledge, aggregation, artifact, access-scope, KDEP-03]
requires: []
provides:
  - ArtifactOverviewView 聚合接口（类型分组计数 + 截断条目列表）
  - GET /api/knowledge/artifacts/overview/ 路由
affects:
  - server/knowledge/api/artifact_overview.py
  - server/knowledge/api/urls.py
tech-stack:
  added: []
  patterns: [access-scope-fail-closed, sql-annotate-count, truncation-guard, best-effort-no-500]
key-files:
  created:
    - server/knowledge/api/artifact_overview.py
    - server/tests/knowledge/test_artifact_overview_api.py
  modified:
    - server/knowledge/api/urls.py
decisions:
  - resolve_allowed_project_ids 返回可见 Space id → 工件按 project__space_id__in 过滤（已核对 get_user_projects 返回 Space）
  - items 截断 LIMIT=500 + truncated 标记；计数走 SQL annotate 不物化行
  - 聚合异常 best-effort 捕获返回空结构 + warning，绝不 500 反噬
metrics:
  duration: ~20min
  completed: 2026-07-01
---

# Phase 96 Plan 03: 后端聚合接口 Summary

新增知识总览「交付文档 / 外部依赖」区块所需聚合接口：按当前用户可见 Space 聚合 `initiatives.Artifact`，返回按 `ArtifactType` 分组计数 + 截断的工件条目列表，带 `access_scope` 过滤与截断保护。

## What Changed

### Task 1 — ArtifactOverviewView 聚合视图
- 新建 `server/knowledge/api/artifact_overview.py`：`ArtifactOverviewView(adrf APIView, IsAuthenticated)`，async `get`，全部 ORM 经 `sync_to_async`。
- 权限：`resolve_allowed_project_ids(request.user)`（返回可见 Space id）；空 → 空结构 `{total:0,types:[],items:[],truncated:false}`（fail-closed，零 DB 越权）。
- 已核对 `PermissionService.get_user_projects` 返回 `projects.Space` → 工件按 `project__space_id__in=allowed` 过滤（Artifact → initiatives.Project → Space），与 planner 注记一致。
- 计数：`.values("type__key","type__name","type__carrier","type__ragable").annotate(count=Count("id")).order_by("-count")` → `types`。`total = sum(count)`。
- 条目：`.select_related("type","project").order_by("-updated_at")[:LIMIT]`（`_ITEM_LIMIT=500` 截断保护），每项 `{artifact_id,title,type_key,type_name,carrier,url,project_id,project_name,updated_at}`。`truncated = total > limit`。
- 可选 `?type_key=` 预筛（非法值 fail-soft 自然收窄为空）；可选 `?limit=` clamp `[1, 500]`。
- 观测：`artifact_overview_started/completed`（kv：allowed_space_count/type_group_count/item_count/duration_ms，category=caller, component=knowledge）；聚合异常 → `artifact_overview_failed` warning + 返回空结构。

### Task 2 — 路由登记 + API 测试
- `server/knowledge/api/urls.py`：`path("artifacts/overview/", ArtifactOverviewView.as_view(), name="knowledge-artifact-overview")`（对外 `/api/knowledge/artifacts/overview/`）。
- `server/tests/knowledge/test_artifact_overview_api.py`：3 用例——access_scope 过滤（他 Space 工件不可见）、type_key 预筛、无可见 project 空结构。

## Verification Results
- `uv run pytest tests/knowledge/test_artifact_overview_api.py -x -q` → **3 passed**
- `uv run python -c "...import ArtifactOverviewView..."` → ok（可 import）
- `uv run ruff check` 目标文件 → All checks passed

## 对外契约（供 96-05 前端消费）
`GET /api/knowledge/artifacts/overview/[?type_key=&limit=]` →
```
{
  total: int,
  types: [{type_key, type_name, carrier, ragable, count}],
  items: [{artifact_id, title, type_key, type_name, carrier, url, project_id, project_name, updated_at}],
  truncated: bool
}
```

## Deviations from Plan
None —— 计划按原样执行。（planner 关于 `resolve_allowed_project_ids` 返回 Space id 的注记已对照 `PermissionService.get_user_projects` 源码核实为真。）

## Known Stubs
None。

## Self-Check: PASSED
- `server/knowledge/api/artifact_overview.py` 含 `resolve_allowed_project_ids`（FOUND）
- `server/knowledge/api/urls.py` 含 `artifacts/overview`（FOUND）
- 测试 3 passed（FOUND）
