---
phase: 81
title: Cursor 回流 + 前端项目工作台
milestone: v0.15.0
status: complete
completed: 2026-06-26
requirements: [CURSOR-01, CURSOR-02, CURSOR-03, UI-01, UI-02, UI-03]
---

# Phase 81 SUMMARY — Cursor 回流 + 前端项目工作台（里程碑收官）

## 落点决策

- **MCP 工具复用既有 `mcp_tools/` 模式**（View + urls + serializer + `TOOL_SCHEMA_SNAPSHOT`，无 decorator registry）；
  鉴权沿用 `AccessTokenAuthentication`（PAT `friday_pat_` / `env_FRIDAY_TASK_USER_TOKEN`）+ `CookieJWTAuthentication`。
- **召回复用 Phase-80 `pack_project_context`**（fail-closed），不重复实现召回；MCP 链经基类 `_record`
  写 `RetrievalTrace`（补齐 Phase-80 标注的 MCP 链）。
- **写回默认入 memory draft**（`MemoryService.create_draft`，pending，绝不直接 active），与 MEM-04 一致防共享记忆污染。
- **前端 TanStack Query 范式**（仿 `specs/` + `admin/git-credentials/`），不沿用 spaces 的 Pinia-only 旧范式；
  详情 Tab 经 `defineAsyncComponent` + `v-if` 懒加载。

## 后端新增/改动

### CURSOR-01 分支反查 + 召回（MCP 链 RetrievalTrace）
- **`server/services/branch_parsing.py`（新）**：`parse_work_item_id_from_branch`——对称解析
  `feat/xxxx-m{id}-slug`（严格）+ 宽松 `-m{digits}` 兜底；fail-soft 返回 `None`，绝不抛。
- **`mcp_tools` 新工具 `lookup_project_by_branch`**（`LookupProjectByBranchView` + serializer + url + schema）：
  解析 id → `ProjectWorkItemLink.work_item__work_item_id` 反查 distinct `Project`；**单命中**经
  `pack_project_context(project, request.user, query=branch_name)` 召回，写 `RetrievalTrace`
  （payload 含 `counts`/`layer_timing_ms`/`scores`/`included_layers`，source=`mcp_lookup_project_by_branch`）；
  **多/无命中 fail-soft**（`matched=False` + 候选列表，绝不抛）。召回经 packer 内置 fail-closed（非成员零召回）。

### CURSOR-02 Cursor rules 模板
- **`server/initiatives/services/cursor_rules.py`（新）**：`build_project_cursor_rules` 生成项目专属 `.mdc`
  （frontmatter `alwaysApply: true` + 强制「先 `lookup_project_by_branch` 关联项目 → 召回 → 编码 → `report_project_knowledge` 上报沉淀」）+ `cursor_rules_filename`。
- **`GET /api/projects/<id>/cursor-rules/`**（`ProjectCursorRulesView`，读权限）→ `{filename, content}`；前端概览 Tab 复制/下载。

### CURSOR-03 上报写回（认证 + 归因 + 脱敏 + 质量门槛 → draft）
- **`server/services/cursor_writeback.py`（新）**：`evaluate_writeback_quality`——质量门槛过滤
  （`too_short` / `low_information`（CJK 按字计 token）/ `duplicate`（与既有 active 记忆 Jaccard ≥ 阈值）），
  阈值经 `SettingKeys.CURSOR_WRITEBACK_CONFIG`（JSON）可配，缺省合理默认；读取异常回退默认。
- **`mcp_tools` 新工具 `report_project_knowledge`**（`ReportProjectKnowledgeView` + serializer + url + schema）：
  PAT 鉴权 → 归因 `request.user`（`initiated_by_user_id`）→ 质量门槛（不达标 200 + `{accepted:false, reason}`）→
  `MemoryService.create_draft`（**脱敏不可绕过** `redact_secrets_in_text` + **成员校验 fail-closed** → 403；
  默认 **pending draft 不入 active**）。
- **`SettingKeys.CURSOR_WRITEBACK_CONFIG`** 新增（`server/system/models.py`）。

### 工作台后端缺口（surface 既有 service，COMPOSE-01/02）
- **项目工作项 REST**：`GET /api/projects/<id>/work-items/`（link 派生摘要）+ `POST`（手动并入，复用
  `ProjectService.attach_work_item`）+ `DELETE /<work_item_id>/`（`detach_work_item`）。
- **项目列表筛选**：`ProjectListCreateView.get` 增可选 query `space_id`/`status`/`member`/`q`（additive，缺省=现状，零回归）。
- **`ArtifactTypeSerializer` 补 `instance_count`**（SerializerMethodField，镜像 `member_count` 范式）——前端删除保护依据。

## 前端新增（UI-01~03）

- **API 模块（新）**：`web/src/api/artifacts.ts`、`artifactTypes.ts`（+ `ARTIFACT_CARRIERS`）、`projectMemory.ts`、
  `mergeRequests.ts`；**扩展** `projects.ts`（`list(filters)` / `listWorkItems`·`attachWorkItem`·`detachWorkItem` /
  `graph` / `cursorRules`）；全部注册 `api/index.ts` barrel。
- **UI-01 `web/src/pages/projects/index.vue`**：PageHeader + 创建（复用 `CreateProjectModal`）+ 筛选（Space 下拉 /
  状态 / 仅我参与 / 防抖搜索）+ 卡片网格（状态/空间/成员/飞书徽标）+ 骨架/空/错/重试。
- **UI-02 `web/src/pages/projects/[id]/index.vue`** + 6 懒加载 Tab 组件 `web/src/components/project/workbench/`：
  - `OverviewTab`（描述 + 计数 + **Cursor rules 复制/下载**）
  - `MembersTab`（成员 + 角色变更 + 转主R 确认 + 移除）
  - `WorkItemsTab`（并入/移除 + story/缺陷类型徽标）
  - `ArtifactsTab`（按类型分组 + 在线查看 Dialog：md/text/link/records）
  - `MemoryTab`（时间线 + 编辑/废弃 + **LLM 草稿确认**：接受/编辑后入库/拒绝）
  - `LinksTab`（MR 列表 + 知识图谱关联节点）
  - 头部：状态机切换（合法流转 + 终止 destructive 确认）、飞书看板外链、面包屑。
- **UI-03**：记忆草稿确认（`MemoryTab` 内）+ **`web/src/pages/admin/artifact-types/index.vue`**
  （`requiresAdmin`，类型表 + 新增 + 启停 + 删除：builtin/有实例 disabled 按钮 + tooltip 提示）。
- **i18n**：`zh-CN.json` 新增 `projects` + `artifactTypes` namespace（全量中文）。危险操作走 `useConfirmDialog`。

## 文件改动清单

- 后端新增（5）：`services/branch_parsing.py`、`services/cursor_writeback.py`、
  `initiatives/services/cursor_rules.py`、+ 5 测试文件。
- 后端改动（5）：`mcp_tools/serializers.py`、`mcp_tools/views.py`、`mcp_tools/urls.py`、
  `initiatives/views.py`、`initiatives/urls.py`、`initiatives/serializers.py`、`system/models.py`、
  `tests/mcp_tools/test_schema_snapshot.py`。
- 前端新增（13）：4 API 模块 + `projects/index.vue` + `projects/[id]/index.vue` + 6 workbench Tab +
  `admin/artifact-types/index.vue` + 3 测试 spec。
- 前端改动（4）：`api/index.ts`、`api/projects.ts`、`locales/zh-CN.json`、生成态
  `components.d.ts`/`typed-router.d.ts`。
- **无新增 migration**（仅新增 `SettingKeys` 常量字符串与 SerializerMethodField，无模型字段变更）。

## 测试结果

### 后端
- **新增 30 用例全绿**：
  - `test_branch_parsing.py`（解析 happy/no-match/大小写/宽松/fail-soft，11）
  - `test_lookup_project_by_branch.py`（happy 单命中 + 召回 + RetrievalTrace 写入 / 无法解析 fail-soft /
    解析无项目 fail-soft / 多命中候选 fail-soft / 非成员 fail-closed 空 context / 鉴权，6）
  - `test_report_project_knowledge.py`（成员→pending draft 非 active / 质量门槛 too_short·duplicate /
    脱敏不可绕过 / 非成员 403 / 归因令牌用户，6）
  - `test_cursor_rules.py`（生成强制流程 + 文件名 + API 权限，4）
  - `test_project_work_items_api.py`（attach/list/detach + 幂等 409 + 404 + 非成员 403，3）
- **全量后端**：**6421 passed / 39 failed / 61 skipped / 8 xfailed / 26 deselected**（~430s）。
- **零新增回归**：39 failed = Phase-76 baseline 38（`/tmp/phase76_baseline_failures.txt` `comm` 逐条一致）
  + 唯一非 baseline 项 `tests/test_auto_index_trigger.py::...::test_webhook_dedup_same_sha` = prompt 明示的
  已知 flaky cross-suite ordering（单跑通过，已验证）。
- `makemigrations --check --dry-run` 干净（`No changes detected`）。

### 前端
- `pnpm vue-tsc --noEmit` **绿**。
- **新增 12 用例全绿**（3 spec：列表筛选/空/错/数据 + 工件类型删除保护 disabled+启停 + 记忆草稿接受/拒绝/空态，
  全部以真实 `zh-CN.json` messages 断言）。
- **全量 vitest**：**1109 passed / 2 failed / 1 skipped（共 1112）**。
  2 failed = `ProviderCredentialForm.spec.ts`，**PRE-EXISTING**（stash 本期全部 web 改动后仍同样失败，已验证），
  与 Phase 81 无关、零新增回归。

## 偏差 / caveats

- **真实 Cursor 端 MCP 反查 + 上报端到端**、**真实飞书凭证在线查看**为里程碑级 deferred（human_needed，需真实环境）。
- 工件类型「有实例禁删」tooltip 文案由 reka-ui 在 hover 时渲染，守护测试以「删除按钮 disabled」断言（等价保护）。
- 记忆「编辑后入库」实现为「以编辑后内容 `create` 新记忆 + `reject` 原草稿」（无 confirm-with-edit 后端入口，等价人工内容入库）。
- 工作项手动并入以 delivery WorkItem UUID 输入（最小闭环）；更丰富的工作项选择器留后续。
- MCP 链 `RetrievalTrace` 的 source 落在 `payload.source`（基类 `_record` 不设 model.source 列），与 chat 链
  （model.source=`chat_project_context`）口径不同但同写 trace；查询经 `payload__source` 命中。
