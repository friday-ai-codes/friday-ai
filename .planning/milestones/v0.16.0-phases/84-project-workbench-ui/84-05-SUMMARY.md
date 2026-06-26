# 84-05 Summary — 项目列表筛选（空间/状态/成员）+ 全局/RAG 搜索（带定位）+ 创建入口（WB-05）

**Plan:** `.planning/phases/84-project-workbench-ui/84-05-PLAN.md`
**Wave:** 3 · depends_on [84-01, 84-02, 84-03, 84-04]
**Requirements:** WB-05

## 交付内容

### Task 1 — 列表筛选增强 + ProjectSearchPanel

**`pages/projects/index.vue`（增强）**
- 沿用既有三筛 + 关键词：空间（`useLocalStorage` 本地记忆）/ 状态（`Select`）/ 成员（「仅我参与」→ `filters.member = authUser.id`）/ 列表 `q`（防抖 300ms），组合进 `ProjectListFilters` 走 `projectsApi.list`。
- 新增「全局搜索」折叠开关（`data-testid="global-search-toggle"`，`aria-expanded`），展开后渲染 `ProjectSearchPanel`，传入当前筛选可见的 `projects` 作为搜索范围。

**`components/project/ProjectSearchPanel.vue`（新增）**
- 全局 + 模糊搜索输入（防抖 300ms via `watchDebounced` + 回车即时触发）。
- 在「当前筛选可见」的项目范围内聚合调用 `projectWorkspaceApi.search(id, q)`（84-01 基础端点），`Promise.allSettled` best-effort（单项目失败不影响其余，全部失败才落错误态）。
- 结果项展示命中片段 + `locator` 定位（"属于 仓库X / 项目Y"）+ 可选 score；点击 `RouterLink → /projects/:id#search` 深链跳转对应项目工作台搜索区块。
- RAG 预留位（`data-testid="search-rag-slot"`）：诚实标注「项目域 RAG 深度召回将在 Phase 85 开放」，不杜撰端点。
- 加载 `LoadingState skeleton`、空态 `EmptyState`（"没有匹配的内容"）、错误行内重试 三态兜底。

### Task 2 — 创建入口（手动创建 + 绑定看板）

**`components/project/CreateProjectModal.vue`（增强）**
- 既有「手动创建项目」表单（空间 + 名称 + 描述）保持；将飞书看板字段聚合为独立「绑定看板（可选）」分区（`data-testid="bind-board-section"`），含飞书看板链接（`feishu-board-url`）+ 飞书项目 Key 幂等键（`feishu-project-key`），沿用 `ProjectCreate` 既有字段，幂等 `(space, feishu_project_key)`。
- 成功后沿用 `emit('confirm', project.id)` → 列表页 `router.push('/projects/:id')` 进工作台。

### i18n（`zh-CN.json`，命名空间 `projects.search.*`）
- `open/close/title/placeholder/hint/scope/scopeEmpty/loading/loadError/retry/emptyTitle/emptyDesc/resultCount/locator` + `rag.{title,deferred}`。

### 测试（`__tests__/projects-list.spec.ts` 扩展）
- 既有 7 条基线断言全部保留（筛选栏/卡片/空/错/localStorage 空间记忆/默认全部空间）。
- 新增：状态筛选控件渲染、成员筛选（勾选「仅我参与」→ `filters.member='u1'`）、全局搜索展开 + 结果渲染 + `locator` 定位 + RAG 预留位、搜索空态文案。
- 新增 `CreateProjectModal` describe：绑定看板字段渲染、提交携带看板字段 + `emit confirm(projectId)`。

## 验证结果
- `cd web && pnpm vue-tsc --noEmit` ✅ 通过（无错误）。
- `pnpm vitest run src/pages/projects/__tests__/projects-list.spec.ts` ✅ **12 passed**（基线 7 + 新增 5）。
- 全量 zh-CN；前端基线未破。

## 决策 / 缺口
- **成员筛选**沿用「仅我参与」（`filters.member = 当前用户`）：无现成「空间成员下拉」端点，按 plan 允许的"保留仅我参与 + 备注"路径取舍，避免为下拉新增数据成本。可选成员多选留后续。
- **全局搜索范围**：基础端点按项目维度，"全局"以"当前筛选可见项目聚合"实现，天然受空间/状态/成员筛选约束；深度项目域 RAG 召回留 Phase 85（UI 已预留结果位）。
- `components.d.ts`（auto-import 自动生成）已含 `ProjectSearchPanel` 行，但本组件在 `index.vue` 显式 import，不依赖该声明；该文件为并行 plan 共享的自动生成产物，未纳入本次提交。

## Must-Haves 校验
- [x] 项目列表可按 空间 / 状态 / 成员 筛选过滤
- [x] 全局 + 模糊搜索入口，结果定位上下文属哪个仓库/项目（locator）
- [x] 创建入口可手动创建项目并支持绑定看板
- [x] 列表/搜索有 加载 / 空 / 错 兜底
