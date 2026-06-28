# P1 技术方案：大盘布局重构（Dashboard 骨架）

**所属里程碑：** 项目作战室 / 工作区大盘（见 `MILESTONE-PROPOSAL.md`）
**Phase：** P1（Wave 1，前端为主，复用现有数据，可独立上线）
**产出方式：** Cursor 技术方案（非 GSD）；本文为 P1 执行依据。
**定稿：** 2026-06-27 · 状态：Ready to execute

---

## 1. 目标

把项目页从「`WorkbenchShell` 左导航 + 单 section 懒加载」改为「**单页平铺 Dashboard 大盘**」：所有交付分区一屏铺开，新增「健康总览」与 Feature「按状态/按模块」切换，并为右侧 AI 会话栏预留**可收起/展开/放大的壳**（实际对话在 P3 接入）。**纯前端、零新后端、复用现有 API。**

## 2. 范围

**做：** 布局重构、健康总览(实数据)、Feature 视图切换、各分区平铺、右侧会话栏壳(占位+状态)、响应式、i18n、测试。
**不做（后续 Phase）：** 实际 AI 对话（P3）、关系星图（P4）、分区就地编辑（P5）、任何后端改动。
**不破坏：** 现有各 section 组件（OverviewSection/FeatureListSection/DocsSection/DependenciesSection 等）行为；深链书签可降级。

## 3. 现状基线（已核对）

- 页面 `web/src/pages/projects/[id]/index.vue`：面包屑 + Header（名/状态/空间/飞书看板/状态流转）+ `WorkbenchShell`（sections=overview/docs/feature/deps，懒加载切换）。
- `WorkbenchShell.vue`：左导航 + 单列主区 + `#hash` 深链；**本期不再作为主布局**（保留文件，供其它处复用或后续删除）。
- 复用数据源（均已存在）：
  - `projectsApi.get / listMembers`
  - `projectWorkspaceApi.listDocs / getFeatureList / listWorkItems`
  - `mergeRequestsApi.list(projectId)`（status: open/merged/closed）
  - 现成分区组件：`OverviewSection`(含状态栏/人员/OverviewTab)、`FeatureListSection`、`DocsSection`、`DependenciesSection`、`WorkItemsTab`、`MemorySection`。

## 4. 布局架构

```
[id]/index.vue
└── ProjectWarRoom.vue（新，整页两栏）
    ├── 主区（可滚动 Dashboard 网格）
    │   ├── DashboardHeader（复用现有 Header 逻辑：名/状态/空间/飞书/状态流转）
    │   └── 网格 zones（lg 12 列 bento / md 双列 / <md 单列）
    │       ├── ProjectHealthCard（新）           ← 健康总览(实数据 + 下一步建议)
    │       ├── FeatureListSection（改）          ← 加 按状态/按模块 切换
    │       ├── WorkItemsTab / MR / People / Docs / Dependencies / Memory（平铺复用）
    │       └── [关系星图卡片占位]（P4 接）
    └── ProjectAssistantRail.vue（新，壳）
        states: collapsed(窄条) / expanded(侧栏) / maximized(全屏 Dialog)
        内容：占位「AI 会话（即将上线）」+ 收/展/放交互；实际对话 P3 注入
```

**布局/UX 规范（采纳 ui-ux-pro-max，配色字体沿用现有 design token）：**
- 网格：Tailwind `grid` + `lg:grid-cols-12`，zone 用 `lg:col-span-*`（健康总览/星图占大跨度，列表类中跨度）；`md:grid-cols-2`；`<md` 单列。
- 会话栏：`lg` 常驻右侧（`w-80`~`w-96`，可收为 `w-12` 窄条）；`<lg` 转 Drawer（reka-ui Dialog/Drawer），放大态全屏。
- 防 CLS：每个异步 zone 用固定 min-height / `LoadingState` 骨架占位；图片/头像声明尺寸。
- z-index 标度：内容 0 / sticky header 20 / 会话栏 40 / 放大 Dialog 100（统一，不用任意大值）。
- 视口：整页 `min-h-dvh`；放大会话 `h-dvh`。
- 动效：收/展/放 150–300ms transform/opacity；`prefers-reduced-motion` 降级为即时切换。
- 触控：按钮 ≥44px；图标统一 lucide，不用 emoji。

## 5. 任务分解（文件级）

### T1 — 新建整页容器 `ProjectWarRoom.vue`
- 路径：`web/src/components/project/warroom/ProjectWarRoom.vue`
- props：`project: Project`、`canManage: boolean`
- 职责：两栏布局（主区网格 + 右侧会话栏壳）、会话栏 collapsed/expanded/maximized 状态（`ref` + localStorage 记忆偏好）、响应式断点切换。
- 把现有 Header（面包屑/名/状态徽标/空间/飞书看板/状态流转按钮）从 `index.vue` 迁入或抽成 `DashboardHeader.vue`。

### T2 — 改造页面入口 `[id]/index.vue`
- 移除 `WorkbenchShell` + sections 懒加载用法；保留 query/loading/error/notFound。
- 渲染 `<ProjectWarRoom :project :can-manage />`。
- `useHead` 标题逻辑保留。

### T3 — 新建 `ProjectHealthCard.vue`（健康总览，实数据）
- 路径：`web/src/components/project/warroom/ProjectHealthCard.vue`
- 数据（并行 useQuery，复用现有 API）：
  - feature：`getFeatureList` → 拍平统计四态 `todo/in_progress/testing/done` 数量与总数。
  - MR：`mergeRequestsApi.list` → `status==='open'` 计数。
  - docs：`listDocs` → 同步态（复用 OverviewSection 的 syncing/error/synced 判定）。
  - work items：`listWorkItems` → 状态分布（可选）。
- **下一步建议（规则版，仅真实数据，无执行/ blocker）：**
  1. 有 `testing` feature → 「推进验收」
  2. 否则有 `in_progress` → 「继续开发中功能」
  3. 否则有 open MR → 「处理待合并 PR/MR」
  4. 否则 feature 总数为 0 → 「补充 feature list」
  5. 否则 → 「项目进展良好」
- 展示：紧凑统计 + 四态灯色（沿用 `FeatureListSection` 的 STATE_CLASS 语义色）+ 下一步建议条。

### T4 — Feature「按状态/按模块」视图切换
- 改 `FeatureListSection.vue`（或包一层 `FeatureBoard.vue`）：
  - 顶部加 `Segmented`/Tabs：「按模块」(现有折叠树) / 「按状态」。
  - 「按状态」：把 `getFeatureList` 的 模块→功能点 拍平，用功能点 `state` 分四组；每组内行展示 feature 名 + 模块名(`module_normalized`) + 验收项数；点开看验收项。
  - 数据同源、纯前端重组，不新增请求。

### T5 — 各分区平铺到网格
- 在 `ProjectWarRoom` 网格内直接渲染复用：`ProjectHealthCard` / `FeatureBoard` / `WorkItemsTab` / MR 列表(用 `mergeRequestsApi`) / `MembersTab`或 OverviewSection 人员块 / `DocsSection` / `DependenciesSection` / `MemorySection`。
- 各 zone 包统一 `card` 容器（沿用现有 `.card` 样式）+ 标题栏（icon + 标题，仿 OverviewSection header）。
- 注意：所有 zone 同时挂载会并发请求；heavy zone（docs/deps）用 `defineAsyncComponent` + 视口懒加载（`v-intersection` 或简单 `v-if` 折叠默认收起）控制首屏负载。

### T6 — 右侧会话栏壳 `ProjectAssistantRail.vue`
- 路径：`web/src/components/project/warroom/ProjectAssistantRail.vue`
- 三态：collapsed(窄条 + 展开按钮) / expanded(标题「项目助手」+ 占位空态「AI 会话即将上线」+ 新建/历史占位) / maximized(全屏 Dialog)。
- 暴露 `model`/emit 供 P3 注入真实对话容器（预留 slot `#default`）。
- 移动端：`<lg` 用 Drawer 从右侧滑入；放大 = 全屏。

### T7 — i18n
- 新增键（`web/src/locales` 现有结构，命名空间 `projects.warroom.*`）：健康总览标题/各统计标签/下一步建议文案/Feature 视图切换标签(按状态/按模块/四态)/会话栏占位文案/收展放 aria-label。
- 默认中文；保持既有 `projects.workbench.*` 键不动（可被新键引用或迁移）。

### T8 — 测试
- 组件测试（vitest + @vue/test-utils + happy-dom）：
  - `ProjectHealthCard`：mock 三个 API → 断言四态计数、open MR 数、下一步建议规则分支。
  - `FeatureBoard`：按状态分组正确（含 `module_normalized` 回填）、视图切换。
  - `ProjectAssistantRail`：三态切换 + aria-label + 移动端 Drawer。
  - `ProjectWarRoom`：渲染各 zone、`canManage=false` 时状态流转按钮隐藏。
- 回归：现有 `[id]/index.vue` 相关测试更新（移除 WorkbenchShell 断言）。
- 类型检查：`pnpm -C web typecheck`（vue-tsc）；lint：eslint。

## 6. 验收标准

- 项目页第一屏平铺呈现交付现状，无左导航 tab 切换。
- 健康总览展示真实 feature 四态计数 / open MR 数 / docs 同步态 / 规则化下一步建议（**无假数据、无执行/blocker 项**）。
- Feature 可「按状态/按模块」切换，数据同源、无新请求。
- 右侧会话栏可收起/展开/放大；`<lg` 转 Drawer；放大全屏；占位文案明确（实际对话 P3）。
- 沿用现有 design token，明暗双模正常；移动端单列不溢出、不重叠。
- `prefers-reduced-motion` 下动效降级；触控目标 ≥44px。
- 现有测试通过 + 新增组件测试通过 + typecheck/lint 通过。

## 7. 风险与缓解

- **首屏并发请求变多**（所有 zone 同时取数）：heavy zone 懒加载/默认折叠 + 骨架占位；后续可加视口懒挂载。
- **深链书签失效**（原 `#overview` 等 hash）：大盘平铺后 hash 锚点改为「滚动到 zone」（可选保留 `#feature` 等做 scrollIntoView），不强求。
- **Header 迁移回归**：状态流转/飞书入口/权限按钮逐一对照原 `index.vue` 迁移，测试覆盖 `canManage`。
- **会话栏壳与 P3 衔接**：壳预留 slot + 状态接口，P3 只注入对话容器，不返工布局。

## 8. 依赖与衔接

- 依赖：无（纯前端、复用现有 API）。
- 衔接：会话栏壳 → P3 注入；健康总览/星图卡占位 → P4 星图；各 zone 编辑能力 → P5。

## 9. 观测/规范

- 纯前端无新后端端点，无强制后端埋点；
- 若新增任何前端到后端的取数封装（如 MR 列表已存在则不新增），不新增 LLM/召回，无 RetrievalTrace 义务；
- 文案接 i18n；组件命名 PascalCase；遵循现有 eslint/antfu 配置。

---
*P1 大盘骨架 — 纯前端，复用现有数据，可独立上线；执行完回填 `MILESTONE-PROPOSAL.md` §11 进度表 P1 状态。*
