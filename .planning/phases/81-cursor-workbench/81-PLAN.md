# Phase 81 PLAN — Cursor 回流 + 前端项目工作台

**Created:** 2026-06-26
**Requirements:** CURSOR-01~03, UI-01~03
**Depends on:** Phase 77–80（聚合根/工件/记忆/MR/召回/context packer/MCP 地基 已就绪）

## 目标（5 Success Criteria）

1. MCP 分支→项目反查 + 召回（`lookup_project_by_branch`），MCP 链写 `RetrievalTrace`。
2. Cursor rules 模板（强制先关联本分支项目、召回再编码）随项目下发 + 文档化。
3. Cursor 沉淀上报写回（认证 + 归因 + 脱敏 + 质量门槛 → memory draft，绝不直接 active）。
4. 前端项目工作台：列表（筛选 + 创建）+ 详情（概览/成员/工作项/工件/记忆/关联）。
5. 记忆 LLM 提议确认 UI + 工件类型后台管理页。

## 复用（不 re-implement）

- MCP 地基：`McpToolView`（`_begin`/`_validate`/`_record`）+ `mcp_tools/urls.py` + `serializers.py` `TOOL_SCHEMA_SNAPSHOT`。
- `services/project_context_packer.py` `pack_project_context(project, user, query=, ...)` → `PackedContext`（fail-closed + RetrievalTrace）。
- `ProjectWorkItemLink` / `Project.work_items` / `delivery.WorkItem.work_item_id`。
- `MemoryService.create_draft`（pending + redact）/ `ProjectService.attach_work_item/detach_work_item`。
- 前端：`web/src/pages/spaces/` 范式、`api/client.ts`、`projects.ts`、`CreateProjectModal.vue`、`ui/*`、`useConfirmDialog`、`usePermission`、`authStore.isAdmin`、TanStack Query（仿 `specs/`、`admin/git-credentials/`）。

## Waves

### Wave 1 — CURSOR-01 分支反查 MCP 工具 + RetrievalTrace
- `server/services/branch_parsing.py`（新）：`parse_work_item_id_from_branch(branch_name) -> int | None`（对称解析 `feat/xxxx-m{id}-slug`，宽松 `-m(\d+)` 兜底；fail-soft 返回 None）。
- `mcp_tools/serializers.py`：`LookupProjectByBranchRequestSerializer{branch_name}` + `TOOL_SCHEMA_SNAPSHOT` 条目。
- `mcp_tools/views.py`：`LookupProjectByBranchView(McpToolView, tool_name="lookup_project_by_branch")`——解析 id → `ProjectWorkItemLink.work_item__work_item_id` 反查 distinct Project；**单命中**经 `pack_project_context(project, request.user, query=branch_name)` 召回，写 RetrievalTrace（payload counts/layer_timing_ms/scores/included_layers，source=`mcp_lookup_project_by_branch`，显式 user_id）；**多/无命中 fail-soft**（matches 候选列表 / 空，绝不抛）。
- `mcp_tools/urls.py` 注册。
- commit `feat(81): MCP lookup_project_by_branch 分支反查召回 + RetrievalTrace`。

### Wave 2 — CURSOR-02 rules 模板 API + 概览 surface
- `server/initiatives/services/cursor_rules.py`（新）：`build_project_cursor_rules(project) -> str`（.mdc 文本：强制先 `lookup_project_by_branch` 关联项目、召回上下文再编码；含项目名/space/feishu key）。
- `initiatives/views.py` `ProjectCursorRulesView` + url `GET /api/projects/<id>/cursor-rules/`（读权限）→ `{filename, content}`。
- 前端概览 Tab：复制/下载入口（见 Wave 8）。
- commit `feat(81): 项目专属 Cursor rules 模板生成 API`。

### Wave 3 — CURSOR-03 上报写回（draft + 质量门槛）
- `server/services/cursor_writeback.py`（新）：`evaluate_quality(content, existing_contents, *, min_length, ...) -> (ok, reason)`（长度/低信息量/与既有 active 记忆重复度过滤；阈值经 `SystemSetting` 可配，缺省合理默认）。
- `mcp_tools/serializers.py`：`ReportProjectKnowledgeRequestSerializer{project_id, content, source_conversation_id?}` + schema 条目。
- `mcp_tools/views.py` `ReportProjectKnowledgeView`：PAT 鉴权（McpToolView）→ 归因 `request.user`（initiated_by_user_id）→ 质量门槛 gate（不达标 200 + `{accepted:false, reason}`）→ `MemoryService().create_draft(proposed_by=request.user, ...)`（成员校验 fail-closed → 403；脱敏不可绕过；**默认 pending draft 不入 active**）。
- `mcp_tools/urls.py` 注册。
- commit `feat(81): MCP report_project_knowledge 上报写回（归因/脱敏/质量门槛→draft）`。

### Wave 4 — 后端工作台缺口（surface 既有 service）
- `initiatives/views.py`：`ProjectWorkItemListView`（GET 列出 link 派生的 work item 摘要）+ `POST attach`（work_item_id 三元组或 delivery id 并入）+ `ProjectWorkItemDetailView` DELETE detach。url 注册 `/api/projects/<id>/work-items/`、`/<wid>/`。
- `ProjectListCreateView.get`：增可选 query 过滤 `space_id`/`status`/`q`/`member`（additive，缺省=现状，零回归）。
- commit `feat(81): 项目工作项 REST（attach/detach/list）+ 列表筛选参数`。

### Wave 5 — 后端测试 + 门禁
- `tests/services/test_branch_parsing.py`、`tests/mcp_tools/test_lookup_project_by_branch.py`（happy/no-match/multi fail-soft/RetrievalTrace 写入/非成员 fail-closed scope）、`test_report_project_knowledge.py`（auth/归因/脱敏/质量门槛→draft 非 active）、`tests/initiatives/test_cursor_rules.py`、`test_project_work_items_api.py`、`test_schema_snapshot.py`（+2 工具）。
- 全量 `uv run pytest -q`；`makemigrations --check --dry-run`。
- commit `test(81): MCP 反查/上报 + rules + 工作项 + schema 守护`。

### Wave 6 — 前端 API 模块 + barrel
- 扩展 `web/src/api/projects.ts`：`listWithFilters`、`workItems`(list/attach/detach)、`graph`、`cursorRules`、`memories`(list/create/edit/supersede)、`memoryDrafts`(list/distill/confirm/reject)、`mergeRequests`(list)。
- 新 `web/src/api/artifacts.ts`、`artifactTypes.ts`（含 carriers）、`projectMemory.ts`（若拆分；否则并入 projects）、`mergeRequests.ts`。注册 `api/index.ts` barrel。
- commit `feat(81): 前端项目工作台 API 模块（工件/记忆/MR/类型/工作项）`。

### Wave 7 — UI-01 列表 `/projects/index.vue`
- PageHeader + 创建（复用 `CreateProjectModal`）+ 筛选（Space 下拉 / 状态多选 / 搜索 / 仅我参与）+ 卡片网格（状态/space/成员/飞书徽标）+ Loading/Empty/Error。TanStack Query。
- commit `feat(81): UI-01 项目列表页（筛选 + 创建 + 卡片）`。

### Wave 8 — UI-02 详情 `/projects/[id]/index.vue` + 子组件
- 头部（名/space 面包屑/状态切换/飞书链接）+ reka-ui Tabs 懒加载：概览(+Cursor rules 复制/下载) / 成员(角色 + 转主R 确认) / 工作项(并入/移除) / 工件(类型分组 + 在线查看抽屉) / 记忆(时间线 + 编辑 + 草稿区) / 关联(graph nodes)。子组件落 `web/src/components/project/workbench/`。
- commit `feat(81): UI-02 项目详情工作台（6 Tab 懒加载）`。

### Wave 9 — UI-03 记忆确认 + 工件类型管理 + i18n
- 记忆 Tab 内草稿确认（accept/edit-then-accept/reject + useConfirmDialog）。
- `/admin/artifact-types/index.vue`（`requiresAdmin`）：类型表 + 新增 + 启停 + 删除（builtin/有实例禁删按钮 disabled + tooltip）。
- `zh-CN.json` 新增 `projects` + `artifactTypes` namespace（全量中文）。
- commit `feat(81): UI-03 记忆草稿确认 + 工件类型管理页 + zh-CN i18n`。

### Wave 10 — 前端测试 + 门禁
- vitest 守护：`projects/index` 筛选/空/错/载 + `cursor rules` 复制 + 记忆草稿 accept/reject + `artifact-types` disable/delete-protection + 真实 zh-CN messages。
- `pnpm vue-tsc --noEmit`（绿）+ `pnpm test`（不破坏 ~130 基线）。
- commit `test(81): 前端工作台守护测试（筛选/草稿/类型保护/i18n）`。

### Docs
- 81-SUMMARY.md / 81-VERIFICATION.md（status mapping 5 criteria）+ ROADMAP/REQUIREMENTS/STATE 收官（completed_phases 5→6, percent 100）。

## 风险 / 约束
- schema snapshot 测试断言精确相等 → 新工具必须同步加 `TOOL_SCHEMA_SNAPSHOT` + 测试。
- 零新增回归：baseline 38 failed（`/tmp/phase76_baseline_failures.txt`）+ 1 flaky cross-suite ordering。
- 真实 Cursor 端 MCP + 真实飞书在线查看 = human_needed / deferred（里程碑级）。
- 后端写入仍唯一经既有 service（INV-6）；async ORM 走 sync_to_async。
