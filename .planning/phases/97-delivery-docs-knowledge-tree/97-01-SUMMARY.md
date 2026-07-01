---
phase: 97-delivery-docs-knowledge-tree
plan: 01
subsystem: knowledge
tags: [api, access_scope, tree, observability]
requires: [knowledge.access_scope.resolve_allowed_project_ids, initiatives.models.Artifact]
provides: ["GET /api/knowledge/artifacts/tree/", ArtifactTreeView]
affects: [server/knowledge/api/urls.py]
tech-stack:
  added: []
  patterns: [adrf-async-apiview, sync_to_async-orm, best-effort-observability, three-level-clamp]
key-files:
  created:
    - server/knowledge/api/artifact_tree.py
    - server/tests/knowledge/test_artifact_tree_api.py
  modified:
    - server/knowledge/api/urls.py
decisions:
  - "嵌套树后端直出（项目→类型→工件），前端零拼装 —— 最优雅"
  - "范式 100% 镜像 Phase 96 artifact_overview（同 access_scope 口径 + 截断 + best-effort 观测）"
  - "全局硬顶 5000 切片 + 三级 clamp（200/50/100）+ truncated 标记防病态规模"
metrics:
  duration: ~15min
  completed: 2026-07-01
---

# Phase 97 Plan 01: 交付文档知识树后端接口 Summary

`GET /api/knowledge/artifacts/tree/` 按可见 Space 聚合 `initiatives.Artifact` 直出嵌套树（项目→类型→工件），access_scope fail-closed 过滤 + 三级 clamp + best-effort 观测，前端零拼装。

## What was built

- **`ArtifactTreeView`**（`server/knowledge/api/artifact_tree.py`）：adrf 异步 APIView + `IsAuthenticated`，`get` 走 `resolve_allowed_project_ids`（返回可见 Space id）→ 无可见 Space 直接返回 `{"total":0,"projects":[],"truncated":False}`（零 DB 越权），否则 `sync_to_async(_build_tree)` 聚合。
- **`_build_tree`**：`Artifact.objects.filter(project__space_id__in=allowed).select_related("type","project").order_by("project__name","type__name","-updated_at")[:5000]` 后单遍分组为嵌套结构；dict 保序 → 插入序即展示序；`count` 记桶内真实计数，列表按 `_MAX_PROJECTS=200 / _MAX_TYPES_PER_PROJECT=50 / _MAX_ARTIFACTS_PER_TYPE=100` clamp，任一 clamp 或命中全局硬顶置 `truncated=True`；`total` = 已纳入项目真实计数之和。叶子仅含 `artifact_id/title/carrier/url/updated_at`（不含冗余 project_id）。
- **观测**：`artifact_tree_started`（component=knowledge, category=caller）；`artifact_tree_completed`（allowed_space_count/project_count/total/truncated/duration_ms）；`_build_tree` 异常 `try/except` → `artifact_tree_failed` warning + 返回空结构，绝不 500。
- **路由**：`urls.py` 追加 `path("artifacts/tree/", ArtifactTreeView.as_view(), name="knowledge-artifact-tree")`。
- **测试**：`test_artifact_tree_api.py` 3 用例（access_scope 过滤 + 嵌套层级 + count/叶子字段校验、单项目双类型嵌套分组、空 scope 空结构）。

## 对外契约（供 97-02/97-03 消费）

```
{ total: int, projects: [{ project_id, project_name, count,
  types: [{ type_key, type_name, carrier, ragable, count,
    artifacts: [{ artifact_id, title, carrier, url, updated_at }] }] }],
  truncated: bool }
```

## Verification

- `python -c "...import ArtifactTreeView"` → `ok`（需 `django.setup()` / `DJANGO_SETTINGS_MODULE`）
- `uv run pytest tests/knowledge/test_artifact_tree_api.py -x -q` → **3 passed**
- `uv run ruff check knowledge/api/artifact_tree.py knowledge/api/urls.py` → **All checks passed**

## Deviations from Plan

**1. [Rule 3 - Blocking] import 验证需 Django 配置**
- **Found during:** Task 1 verify
- **Issue:** 计划的 `uv run python -c "from ... import ArtifactTreeView"` 因 adrf 在 import 时读取 `REST_FRAMEWORK` 设置而报 `ImproperlyConfigured`（与 overview 同款约束，非本接口引入）。
- **Fix:** 用 `DJANGO_SETTINGS_MODULE=friday.settings` + `django.setup()` 完成 import 冒烟；pytest 为权威验证已全绿。
- **Files modified:** 无（仅验证命令调整）

## Self-Check: PASSED
- FOUND: server/knowledge/api/artifact_tree.py
- FOUND: server/tests/knowledge/test_artifact_tree_api.py
- FOUND: server/knowledge/api/urls.py (artifacts/tree/ 路由)
