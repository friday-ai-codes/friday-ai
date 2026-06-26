---
phase: 84-project-workbench-ui
plan: 01
type: execute
status: complete
completed_at: 2026-06-27
requirements: [WB-02, WB-03, WB-05]
---

# 84-01 SUMMARY — 工作台后端支撑（文档内容/人工区回写/feature 树/进度灯/项目搜索）

## 目标达成

为 Phase 84 前端工作台补齐缺失的后端只读/写回 REST 支撑面（WB-02/03/05 后端部分），全部复用
Phase 82/83 既有服务层（`ProjectDocService` / `DocSyncService` / `MemoryService` / 知识检索），
不旁路区段所有权与权限（INV-6）。

## must_haves 真值（全部满足）

- ✅ 可经 REST 取单文档渲染 markdown + block 列表，每 block 标注 system/human 分区
  （`GET /api/projects/{id}/workspace/docs/{doc_type}/`）。
- ✅ 成员可经 REST 提交人工区文本，触发 Phase 83 `durable_doc_sync_push` block 级回灌（非整篇覆盖）
  （`PUT/PATCH .../human-blocks/`）。
- ✅ 可经 REST 取 feature list 模块→功能点→验收项 树，功能点带 待开发/进行中/测试中/已完成 四态灯
  （`GET .../feature-list/`）。
- ✅ 项目工作项列表返回含 WorkItem 状态字段（`status_state_key`/`status_display_name`/`module_normalized`）。
- ✅ 可经 REST 对项目做基础模糊搜索，结果标注其所属仓库/项目（`GET .../search/?q=`）。

## 新增/改动端点

| 方法 | 路由 | 视图 | 说明 |
|------|------|------|------|
| GET | `projects/<id>/workspace/docs/<doc_type>/` | `ProjectWorkspaceDocContentView` | 单文档渲染 + block 分区；非法 doc_type 400，缺失 404，非可见 403 |
| PUT/PATCH | `projects/<id>/workspace/docs/<doc_type>/human-blocks/` | `ProjectWorkspaceDocHumanBlocksView` | 人工区写回（仅成员）→ 触发 push；写 system block 409；非成员 403 |
| PATCH | `projects/<id>/workspace/state-apis/<api_id>/` | `ProjectStateApiDetailView.patch` | 更新单条 API 清单字段（method/path/params/status）；缺失 404 |
| GET | `projects/<id>/feature-list/` | `ProjectFeatureListView` | feature 三层树 + 进度灯；空工件返回空树 |
| GET | `projects/<id>/search/?q=` | `ProjectSearchView` | 项目基础模糊搜索 + 知识检索兜底；写 RetrievalTrace |
| GET（扩展） | `projects/<id>/work-items/` | `ProjectWorkItemListView` | 返回项新增 WorkItem 状态字段 |

## 文件清单

新增：
- `server/initiatives/services/doc_content_service.py` — `DocContentService`（`get_doc_render` / `update_human_blocks`）
- `server/initiatives/services/feature_list_service.py` — `FeatureListService`（`build_tree` + `progress_light` 四态映射）
- `server/initiatives/services/project_search_service.py` — `ProjectSearchService`（关键词召回 + 知识兜底 + RetrievalTrace）
- `server/tests/initiatives/test_workspace_doc_content_api.py`（11 用例）
- `server/tests/initiatives/test_feature_list_api.py`（6 用例）

改动：
- `server/initiatives/services/project_doc_service.py` — 新增 `update_state_api` + `write_human_block`（人工区写收口，INV-6）
- `server/initiatives/views.py` — 4 新视图 + StateApi PATCH + work-items 状态字段
- `server/initiatives/serializers.py` — 契约 serializer（见下）
- `server/initiatives/urls.py` — 路由注册
- `server/initiatives/services/__init__.py` — 导出新 service

## Wire 契约（serializer = 单一来源，84-02 TS 须对齐）

- `ProjectDocContentSerializer`：`doc_type` / `sync_status` / `last_synced_revision` /
  `rendered_markdown` / `blocks[]`；block：`block_id` / `db_ref` / `section`(system|human) /
  `text` / `editable`(=section==human)。
- `ProjectDocHumanBlocksWriteSerializer`（请求）：`blocks:[{block_id, text}]`；写回响应
  `{doc_type, written, sync_status:"syncing"}`（瞬态同步态，前端据此轮询 doc 内容 GET）。
- `ProjectFeatureTreeSerializer`：`modules[].module` + `features[]{name, acceptance[], progress, status_display_name}`；
  四态文案 `待开发/进行中/测试中/已完成`。
- `ProjectSearchResultSerializer`：`kind` / `title` / `snippet` / `score` / `source` /
  `locator{project_id, project_name, repository_id?}`；列表外层 `{query, results[]}`。
- `ProjectWorkItemSerializer`：新增 `status_state_key` / `status_display_name` / `module_normalized`。

## LOCKED 约束遵守

- ✅ 人工区写回收口到 `ProjectDocService.write_human_block`（append-only 留痕 + 刷新映射指纹）
  并 enqueue 既有 `durable_doc_sync_push`，**永不整篇覆盖**；系统区只读（写 system block → 409）。
- ✅ 复用 Phase 82/83 service，无旁路写表（`test_project_doc_inv6_guard` / `test_doc_sync_inv6_guard` 全绿）。
- ✅ 搜索写 `RetrievalTrace`（payload 经 ledger `redact_for_ledger` 脱敏）。
- ✅ serializer 为前端契约单一来源；全量 zh-CN。

## 可观测性

- 结构化事件：`project_doc_content_read`、`project_doc_human_write_started/completed/failed`
  （带 `duration_ms` / 写回 block 数 / sync 调度结果）、`project_state_api_updated`、
  `project_feature_list_built`、`project_search_started/completed/failed`（带 `duration_ms` /
  召回条数 / 分层耗时 / top score）。全部 `category=caller`、`component=initiatives.workspace`
  或 `initiatives.search`，绑定触发用户；异常文本经 `redact_secrets_in_text`，观测 best-effort 不反噬。
- 新 REST 入口经统一中间件自动纳入 `RequestMetric`（QPS/错误率/时长）。

## 测试结果

- `uv run pytest tests/initiatives -q` → **220 passed**（含新增 17 + INV-6 守护）。
- ruff check：All checks passed；mypy（新增/改动 4 模块）：Success: no issues found。

## 前端（84-02~05）应消费

- WB-03：`docs/<doc_type>/` 渲染 + blocks（按 `section`/`editable` 渲染只读/可编辑）；保存调
  `human-blocks/` PUT；轮询响应 `sync_status:"syncing"` → 转回 doc GET 的 DB `sync_status`。
- WB-02：`feature-list/` 三层树 + 四态进度灯；`work-items/` 状态字段做里程碑/进度灯映射。
- WB-05：`search/?q=` 基础结果（带 `locator`）；UI 预留 RAG 结果位。

## 延期 / 边界

- 人工区→飞书的**系统区渲染器**仅覆盖 MEMORY/STATE（Phase 83 既有边界）；MILESTONES/RESEARCH/
  PREFLIGHT 的人工区文本已落 DB 留痕 + 刷新指纹并调度 push，飞书侧 block 级落地随同步引擎渲染器
  扩展（不在本 plan）。
- 项目搜索本期为基础关键词 + 知识检索兜底；**深度项目域 RAG 标注留 Phase 85**（service docstring 注明）。
- `sync_status:"syncing"` 为写回响应瞬态提示（非 `DocSyncStatus` DB 枚举），不引入新迁移。
