# 84-04 Summary — 工作台 feature 树 + 进度灯（WB-02）+ 外部依赖关联展示（WB-04）

**Plan:** `.planning/phases/84-project-workbench-ui/84-04-PLAN.md`
**Wave:** 2 · depends_on [84-01, 84-02]
**Requirements:** WB-02, WB-04

## 交付内容

### WB-02 — FeatureListSection.vue（feature 树 + 进度灯）
- 调 `projectWorkspaceApi.getFeatureList(id)`（queryKey `['project-features', idRef]`）。
- 渲染 **模块 → 功能点 → 验收项** 三层 `Collapsible` 折叠树；trigger 带 `aria-expanded` + chevron `group-data-[state=open]:rotate-90`。
- 功能点右侧进度灯（圆点 + 文案），按 84-01 WorkItem 状态映射四态语义色（UI-SPEC）：
  - 待开发 `bg-muted text-muted-foreground`
  - 进行中 `bg-primary/15 text-primary`
  - 测试中 `bg-amber-500/15 text-amber-500`
  - 已完成 `bg-emerald-500/15 text-emerald-500`
- 加载 `LoadingState skeleton`、空 `EmptyState`（“还没有 feature”）、错 行内重试。
- 模块无功能点 / 功能点无验收项 各有兜底文案。

### WB-04 — DependenciesSection.vue（外部依赖 / 关联）
- 六个分组卡片，各自独立 query + 加载/空/错兜底：
  - **外部工件**：`artifactsApi.list` 按类型分组 + 在线查看 `Dialog`（复用 ArtifactsTab view 模式，markdown/text/link/records 分支，外链 `rel="noopener noreferrer"`）；UI 文案标注覆盖 原型/Spec/缺陷/UI 稿/评审/复盘 的归类来源。
  - **关联分支**：占位标注「Phase 85 开放」（ProjectBranch 多绑定不杜撰端点）。
  - **关联仓库**：`projectsApi.get` 取 `space_id` → `getSpaceRepositories(spaceId)`（dependent query，enabled on space_id）。
  - **知识关联** / **关联项目**：`projectsApi.graph(direction=both, maxHops=1)`，按 `kind === 'project'` 拆分知识节点与关联项目节点。
  - **关联 PR / MR**：`mergeRequestsApi.list` 只读列表 + 外链 + 状态徽标。

### i18n（zh-CN.json，命名空间 `projects.workbench.*`）
- `feature.*`：`noFeatures` / `noAcceptance` + 既有 `state.{todo,in_progress,testing,done}`。
- `deps.*`：`artifactsTitle/artifactsHint/artifactsEmpty/artifactsLoadError`、`branchesTitle/branchesDeferred`、`repositoriesTitle/repositoriesEmpty/repositoriesLoadError`、`knowledgeTitle/knowledgeEmpty/knowledgeLoadError`、`projectsTitle/projectsEmpty`、`mergeRequestsTitle/mrEmpty/mrLoadError`。

### 测试
- `__tests__/FeatureListSection.spec.ts`：三层树渲染、四态灯 class+文案、折叠 aria-expanded 切换、空态、错误态重试。
- `__tests__/DependenciesSection.spec.ts`：六分组渲染（含分支占位）、PR 列表、工件按类型分组可查看、各分组空态文案。

## 验证结果
- `cd web && pnpm vue-tsc --noEmit` ✅ 通过（无错误）。
- `pnpm vitest run` 两个 spec ✅ **9 passed**。
- 全量 zh-CN；不破前端基线。

## 说明 / 缺口
- ProjectBranch 多绑定按计划诚实标注 Phase 85，未杜撰端点。
- 本 plan 与并行 84-03（DocsSection 等）共享 `zh-CN.json`：仅本 plan 的 feature/deps 键由本次落地，其余键归属对应 plan。

## Must-Haves 校验
- [x] 模块→功能点→验收项 三层折叠树
- [x] 功能点四态进度灯（看板 WorkItem 状态点亮）
- [x] 外部依赖：工件（原型/Spec/缺陷/UI 稿/评审/复盘）+ 分支/知识/仓库/项目/PR
- [x] 树折叠与依赖列表均有 加载/空/错 兜底
