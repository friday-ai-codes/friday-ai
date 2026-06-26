# 84-04 SUMMARY — 工作台 feature 树 + 进度灯（WB-02）+ 外部依赖关联（WB-04）

**Plan:** 84-04 | **Phase:** 84 项目工作台前端 2.0 | **Wave:** 2 | **Requirements:** WB-02, WB-04
**Status:** ✅ Done | **Completed:** 2026-06-27

## What shipped

补全 84-02 占位的两个工作台区块组件，复用 84-01 端点与 84-02 API 模块，未引入新依赖、未杜撰端点。

### WB-02 — `FeatureListSection.vue`（feature 树 + 进度灯）
- 调 `projectWorkspaceApi.getFeatureList(id)`，queryKey `['project-features', idRef]`。
- 三层 `reka-ui Collapsible` 折叠树：**模块 → 功能点 → 验收项**，每层可折叠（trigger 带 reka-ui `data-state` / `aria-expanded`），默认展开。
- 功能点行右侧**进度灯**（圆点 + 文案），按 WorkItem 状态四态映射 UI-SPEC 语义色：
  - 待开发 `bg-muted text-muted-foreground`
  - 进行中 `bg-primary/15 text-primary`
  - 测试中 `bg-amber-500/15 text-amber-500`
  - 已完成 `bg-emerald-500/15 text-emerald-500`
- 加载 `LoadingState skeleton` / 空 `EmptyState`（"还没有 feature"）/ 错误行内重试。

### WB-04 — `DependenciesSection.vue`（外部依赖 / 关联）
- **外部工件**：`artifactsApi.list` 按 `type_name` 分组（原型 / Spec / UI 稿 / 评审 / 复盘…，缺陷以工作项呈现，UI 文案标注映射来源）+ 在线查看弹窗（复用 `ArtifactsTab` view 模式，`MarkdownRenderer` 不解析 HTML、外链 `rel="noopener noreferrer"`）。
- **关联分支**：Phase 85 占位标注（不杜撰 ProjectBranch 端点）。
- **关联仓库**：经项目 `space_id`（`projectsApi.get`）→ `getSpaceRepositories`，`enabled` 守门。
- **知识关联 / 关联项目**：`projectsApi.graph` 节点，按 `kind` 拆分（非 project → 知识；project → 关联项目）。
- **关联 PR / MR**：`mergeRequestsApi.list` 只读列表 + 外链 + 状态徽章。
- 各分组独立 query + 加载/空/错兜底。

## Files

**Modified**
- `web/src/components/project/workbench/FeatureListSection.vue`（占位 → WB-02 实现）
- `web/src/components/project/workbench/DependenciesSection.vue`（占位 → WB-04 实现）
- `web/src/locales/zh-CN.json`（新增 `projects.workbench.feature.noFeatures/noAcceptance` + `projects.workbench.deps.*` 分组文案）

**Created**
- `web/src/components/project/workbench/__tests__/FeatureListSection.spec.ts`
- `web/src/components/project/workbench/__tests__/DependenciesSection.spec.ts`

## Verification
- `pnpm vue-tsc --noEmit` ✅ 通过（exit 0）
- `pnpm vitest run FeatureListSection DependenciesSection` ✅ 2 files / 8 tests passed
  - 树三层渲染、四态进度灯 class + zh-CN 文案、空态、错误重试
  - 工件分组 + PR 列表 + 仓库渲染 + 各分组空态文案
- ESLint：无新增告警（ReadLints 干净）

## Honest gaps（按 plan 诚实标注）
- **ProjectBranch 多绑定**：UI 预留"关联分支"位并标注 "Phase 85 开放"，本期不接端点。
- **关联项目**：依赖 `graph` 返回 `kind==='project'` 节点；后端暂未必产出该类节点时显示空态。
- 工件类别"缺陷/原型"无内置类型者：以工件类型注册表 `type_name` 实际归类，UI 文案注明缺陷以工作项呈现。
