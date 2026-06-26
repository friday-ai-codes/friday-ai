---
phase: 84
slug: project-workbench-ui
status: approved
shadcn_initialized: false
preset: none
created: 2026-06-27
reviewed_at: 2026-06-27
---

# Phase 84 — UI Design Contract（项目工作台前端 2.0）

> 前端视觉与交互契约，供 `gsd-planner` / executor / `gsd-ui-auditor` 消费。本期把 `web/src/pages/projects/[id]` 从「reka-ui Tabs 6 标签」升级为「**左导航栏 + 右主内容区**」的在线工作区，借鉴 `spaces/[id]` 的视觉语言。**全量 zh-CN、vue-tsc 绿、不破前端基线。**
>
> 本契约不引入新设计系统：复用既有 Tailwind 4 `@theme` token + `reka-ui` 封装（`web/src/components/ui/**`）+ Iconify(lucide) + 全局 `.card`。所有数值均为**实测自现有代码**，executor 必须沿用、不得另造。

---

## Design System

| Property | Value |
|----------|-------|
| Tool | none（不引入 shadcn；项目为 Vue 3 + Tailwind 4，无 `components.json`） |
| Preset | not applicable |
| Component library | `reka-ui`（经 `web/src/components/ui/**` 封装：`Button` `Badge` `Input` `Label` `Select` `Tabs` `Dialog` `AlertDialog` `Collapsible` `Separator` `Tooltip` `Skeleton` 等） |
| Icon library | Iconify + `@iconify/tailwind4`，lucide 前缀（`icon-[lucide--*]`） |
| Font | 继承应用默认 sans 栈（main.css 未显式声明，勿在本期覆盖字体） |
| Markdown 渲染 | 复用 `getMarkdownRenderer()`（markdown-it + Shiki，`html:false`）+ `MarkdownRenderer.vue` |
| 源码编辑 | `vue-codemirror`（CM6）+ `fridayLightTheme`；本期新增 `@codemirror/lang-markdown` |

---

## Layout Contract（锁定 — 来自 CONTEXT.md）

**左导航栏 + 右主内容区（split）。非单页锚点滚动 tab、非多子页路由：左栏点击切换右侧"当前区块"主内容（in-page active-section 状态机），支持 `#hash` 深链书签。** 借鉴 `spaces/[id]` 的 `AnchorNavLayout` 视觉语言（左轨 `w-48 shrink-0 sticky top-22`、active 指示条 `bg-primary/8 text-primary`、lucide 图标 + 可选 badge），但右侧用 **section 切换** 而非整页锚点滚动。

```
┌───────────────────────────────────────────────────────────────┐
│ 面包屑 项目 / {项目名}        [飞书看板↗] [状态流转] [重建工作区]   │  ← 顶部操作条
├──────────────┬────────────────────────────────────────────────┤
│ 左导航栏 w-48 │ 右主内容区 flex-1 min-w-0                         │
│ ─────────────│ ───────────────────────────────────────────────│
│ ◆ 大盘        │  渲染 activeSection 对应内容：                    │
│ ○ 文件 (5)    │   - 大盘：概览卡 + 人员(身份) + 状态栏 (WB-01)     │
│ ○ feature 树  │   - 文件：5 文件 列 + 查看/编辑区 (WB-03)          │
│ ○ 外部依赖    │   - feature：MODULE→功能点→验收项 树+进度灯 (WB-02)│
│ ○ 搜索        │   - 外部依赖：工件/分支/仓库/PR/知识 (WB-04)       │
│              │   - 加载：Skeleton / 空：EmptyState / 错：错误态  │
└──────────────┴────────────────────────────────────────────────┘
```

| 区块 | 约束 |
|------|------|
| 工作台外壳 | 新增 `WorkbenchShell`（或 `ProjectWorkbenchLayout`），`flex gap-8`；左 `aside.w-48.shrink-0`，`sticky top-22`，`hidden md:block`（窄屏左轨折叠为顶部下拉/横向 chips）；右 `flex-1 min-w-0 space-y-6` |
| 左导航项 | `<button>` 切换 `activeSection`（不用 `<RouterLink>` 子路由）；active：`bg-primary/8 text-primary font-medium` + 左侧 `w-0.5 bg-primary` 指示条；非 active：`text-muted-foreground hover:text-foreground hover:bg-muted/40`；项内距 `pl-4 pr-2.5 py-2` |
| 深链 | `activeSection` 与 `route.hash` 双向同步（如 `/projects/:id#docs`）；`onMounted` 读 hash 定位；切换时 `router.replace({ hash })` |
| section 卡片 | 复用 `.card` + 卡头 `px-5 py-3.5 border-b border-border/50`（含 `icon-[lucide--*] text-primary` + `text-sm font-semibold` 标题）+ 卡体 `p-5`；区块间距 `space-y-6` |
| 加载稳定 | 每区块首屏 `LoadingState variant="skeleton"` 占位；切区块不抖动（固定容器最小高度） |

---

## Spacing Scale

沿用 4px 基准（实测自 spaces/projects 现有页面）。

| Token | Value | Usage |
|-------|-------|-------|
| xs | 4px | 图标与文字间隙（`gap-1`）、pill 内距 |
| sm | 8px | 紧凑元素间距、左轨项纵向（`space-y-0.5`≈2px 例外见下） |
| md | 16px | 默认元素/栅格间距（`gap-4`） |
| lg | 24px | 区块/卡片纵向节奏（`space-y-6`）、左右栏间距（`gap-8`=32 见 xl） |
| xl | 32px | 左导航与主区间距（`gap-8`）、大栅格 |
| 2xl | 48px | 主要分段留白 |
| 3xl | 64px | 页级留白 |

卡头内距固定 `px-5 py-3.5`（20px / 14px），卡体 `p-5`（20px）。

Exceptions：左轨项列表用 `space-y-0.5`（2px，沿用 `AnchorNavLayout`，密集导航专用）；KPI 数字行用 `gap-1`（4px，对齐既有大盘）。

---

## Typography

实测自 spaces 详情页（页标题 `text-2xl font-bold`、区块标题 `text-sm font-semibold`、正文/元数据 `text-sm` / `text-xs`）。

| Role | Size | Weight | Line Height |
|------|------|--------|-------------|
| Body | 14px (`text-sm`) | 400 | 1.5 |
| Label | 12px (`text-xs`) | 400/500 | 1.4 |
| Heading（区块标题） | 14px (`text-sm`) | 600 (`font-semibold`) | 1.4 |
| Display（页标题 / KPI 数字） | 24px (`text-2xl`) | 700 (`font-bold`)；KPI 加 `tabular-nums` | 1.2 |

约定：3 档字号 + 14px 区块标题（与正文同号、靠字重区分），与全站一致。代码/源码区用 CM6 `13px`（`fridayLightTheme`）+ 等宽。

---

## Color

60/30/10 = 背景 / 卡片+导航 / teal 主色点缀（实测自 `main.css @theme`）。

| Role | Value | Usage |
|------|-------|-------|
| Dominant (60%) | `hsl(210 40% 98%)` `--color-background` | 页面底色、空白区 |
| Secondary (30%) | `hsl(0 0% 100%)` `--color-card` / `hsl(210 40% 96%)` `--color-muted` | 卡片、左导航栏、section 容器 |
| Accent (10%) | `hsl(168 76% 42%)` `--color-primary`(teal-500) | 见下"Accent reserved for" |
| Destructive | `hsl(0 72% 51%)` `--color-destructive` | 仅删除/移除/不可逆操作 |

Accent reserved for：左导航 **active 态**（指示条 + 文字 + `bg-primary/8`）、主操作按钮（`Button` 默认 variant）、区块标题图标 `text-primary`、KPI/进度强调数字、链接 hover、草稿/提议高亮边框（`border-primary/40`）。**不得**把 teal 铺到所有交互元素或大面积背景。

进度灯语义色（feature list，WB-02，复用既有语义 token，**非新增主题色**）：

| 状态 | 颜色 class | 含义 |
|------|-----------|------|
| 待开发 | `bg-muted text-muted-foreground` 圆点 | 未开始 |
| 进行中 | `bg-primary/15 text-primary`（teal） | WorkItem 进行中 |
| 测试中 | `bg-amber-500/15 text-amber-500` | WorkItem 测试中 |
| 已完成 | `bg-emerald-500/15 text-emerald-500` | WorkItem 已完成/归档完成态 |

身份徽章（WB-01 人员，复用 `Badge`）：PM / 开发负责人 / 开发者 / 测试 用 `Badge variant="secondary"` + 角色文案；主R（owner）加 `icon-[lucide--crown]`。

> **后端角色映射说明（plan 必读）**：后端 `ProjectRole` = `owner/pm/frontend/backend/qa`。前端身份展示映射：**PM**=`pm`、**开发负责人**=`owner`（主R）、**开发者**=`frontend`+`backend`、**测试**=`qa`。若产品要求独立"开发负责人"枚举，由 Phase 84 后端 plan 评估是否扩 `ProjectRole`（否则用 owner 呈现，UI 文案统一为"开发负责人/主R"）。

---

## Copywriting Contract（全量 zh-CN）

| Element | Copy |
|---------|------|
| Primary CTA（创建项目，列表页 WB-05） | `创建项目` |
| Primary CTA（保存文件编辑，WB-03） | `保存到飞书` |
| Primary CTA（确认 LLM 提议，WB-03 记忆） | `采纳入库` |
| Empty state heading（大盘无数据 WB-01） | `工作台尚未就绪` |
| Empty state body | `项目工作区文件正在创建中，稍后刷新即可查看大盘与文件。` |
| Empty state heading（feature 列表为空 WB-02） | `还没有 feature` |
| Empty state body | `feature list 工件同步后，这里会按"模块 → 功能点 → 验收项"展示进度。` |
| Empty state heading（搜索无结果 WB-05） | `没有匹配的内容` |
| Empty state body | `换个关键词试试，或调整空间 / 状态 / 成员筛选。` |
| Error state（区块加载失败，通用） | `加载{区块名}失败，请重试` + `重试` 按钮（沿用 `useErrorHandler` toast + 行内重试） |
| Error state（文件保存冲突 WB-03） | `飞书侧已有更新，已为你保留改动；请刷新后重新编辑人工区` |
| Destructive confirmation（移除成员 WB-01） | `移除成员：确定将该成员移出项目？移出后其将失去写权限。`（`AlertDialog` variant=destructive，确认按钮 `移除`） |
| Destructive confirmation（拒绝草稿 WB-03） | `拒绝提议：该 LLM 提议将被丢弃，确定？`（确认 `拒绝`） |
| 只读区提示（系统区 WB-03） | `系统区由 Friday 自动维护，只读；可编辑下方人工区` |
| 编辑态切换（WB-03） | 查看/编辑 切换：`查看` ↔ `编辑源码`；保存中 `保存中…`，成功 toast `已提交同步，飞书将很快更新` |

> i18n 落地：所有文案进 `web/src/locales/zh-CN.json`，命名空间 `projects.workbench.*`（沿用现有 `projects.*` 约定）；列表筛选沿用既有 `projects.filter.*`。守护测试以真实 `zh-CN.json` 断言关键文案（沿用 `projects-list.spec.ts` / `MemoryTab.spec.ts` 范式）。

---

## Component Inventory（复用优先；新增最小化）

| 组件/能力 | 复用 or 新增 | 来源 / 落点 | 用于 |
|-----------|-------------|------------|------|
| 工作台外壳（左轨+右区） | 新增 `WorkbenchShell.vue` | 借 `components/layout/AnchorNavLayout.vue` 视觉 | 全 WB |
| 大盘概览/人员/状态栏 | 改造 `OverviewTab.vue`→`OverviewSection.vue` | `components/project/workbench/` | WB-01 |
| 5 文件查看 | 复用 `MarkdownRenderer.vue` + `getMarkdownRenderer()` | `components/execution/` | WB-03 |
| 5 文件源码编辑 | 新增 `MarkdownSourceEditor.vue`（CM6 wrapper，仿 `PromptBodyEditor.vue`/`JsonEditor.vue`，加 `markdown()` lang + `fridayLightTheme` + `:readonly`） | `components/project/workbench/` | WB-03 |
| 系统区/人工区分区 | 新增（按后端 block `section` 标识渲染只读/可编辑） | — | WB-03 |
| 记忆条目 + 草稿确认 | 复用/扩展 `MemoryTab.vue` 逻辑 + `useConfirmDialog` | `components/project/workbench/MemoryTab.vue` | WB-03 |
| LLM 提议 vs 现状 diff（可选增强） | 复用 `PromptVersionDiff.vue`（`diffLines` + `.diff-added/.diff-removed`） | `components/prompts/` | WB-03 |
| feature 树 + 进度灯 | 新增 `FeatureListSection.vue`（`Collapsible` 折叠 + 进度灯圆点） | `components/project/workbench/` | WB-02 |
| 外部依赖/关联 | 改造 `ArtifactsTab.vue` + `LinksTab.vue`→`DependenciesSection.vue` | `components/project/workbench/` | WB-04 |
| 列表筛选/搜索/创建 | 改造 `pages/projects/index.vue` + 复用 `CreateProjectModal.vue` | `pages/projects/` | WB-05 |
| 加载/空/错 | `LoadingState`(skeleton) / `EmptyState` / `useErrorHandler` + 行内重试 | `components/common/` | 全 WB |
| 状态/身份徽章 | `Badge` / `StatusBadge` | `components/ui/badge`, `components/common/` | WB-01/02 |
| 派发→轮询（重建工作区/同步状态） | 复用 `ReconcilePanel.vue` 范式（`useMutation` + `enabled` + `refetchInterval`） | `components/repository/` | WB-01/03 |

---

## Interaction & State Contracts

| 维度 | 契约 |
|------|------|
| 数据获取 | `@tanstack/vue-query`；queryKey 沿用 `['project', id]` / `['project-*', idRef]` 约定；新增工作区 key：`['project-docs', idRef]`、`['project-doc', idRef, docType]`、`['project-features', idRef]`、`['project-search', filters]` |
| 写后刷新 | 编辑保存/采纳草稿后 `invalidateQueries` 对应 key；不整页刷新 |
| 派发→轮询 | "重建工作区" / "保存到飞书" 触发后，doc `sync_status` 轮询：`refetchInterval: q => q.state.data?.sync_status==='syncing' ? 2000 : false`（仿 `ReconcilePanel`） |
| 加载态 | 首次加载 `Skeleton`；切换 section 即时显示（已缓存不闪烁） |
| 空态 | 用 `EmptyState`（页/区块级）或行内居中空态（`spaces` 既有手写模式）；文案见上 |
| 错误态 | best-effort：toast（`useErrorHandler`）+ 行内 `重试` 按钮；**绝不**整页崩溃 |
| 只读保护 | 系统区 block 渲染为只读（CM `:readonly` 或纯渲染）；仅人工区可进编辑态并保存 |
| 编辑回灌 | 保存 = 调后端人工区写回端点（触发 Phase 83 `DocSyncService` block 级 push）；不在前端直写飞书 |
| 草稿确认 | LLM 提议(draft)：采纳走二次确认（`useConfirmDialog`）→ `confirmDraft`；拒绝 → `rejectDraft`；沿用 `MemoryTab` 交互与 `projects.memory.draft.*` 文案结构 |
| 搜索（WB-05） | 防抖输入 + 空间/状态/成员筛选；结果项标注"属哪个仓库/项目"；本期接基础/关键词+`/api/knowledge/search` 兜底，**深度项目域 RAG 留 Phase 85**（UI 预留 RAG 结果位） |
| 可访问性 | 左轨项可键盘聚焦/回车切换；折叠树 `aria-expanded`；图标按钮带 `Tooltip`/`aria-label` |
| 响应式 | `md` 以下左轨折叠为顶部 `Select`/横向 chips；主区单列；CM 编辑器 `lineWrapping` |

---

## Registry Safety

| Registry | Blocks Used | Safety Gate |
|----------|-------------|-------------|
| shadcn official | 无（项目未用 shadcn） | not required |
| 第三方 registry | 无 | not applicable |

本期不引入任何第三方 UI registry/组件；新增依赖仅 `@codemirror/lang-markdown`（CM6 官方语言包，走 pnpm catalog，非 UI registry）。

---

## Checker Sign-Off

- [x] Dimension 1 Copywriting: PASS
- [x] Dimension 2 Visuals: PASS
- [x] Dimension 3 Color: PASS
- [x] Dimension 4 Typography: PASS（FLAG 非阻断：声明 400/500/600/700 共 4 档字重，系全站既有阶梯；本期不再扩展第 5 档）
- [x] Dimension 5 Spacing: PASS（FLAG 非阻断：卡头 `py-3.5`=14px、`px-5`/`p-5`=20px、左轨 `space-y-0.5`=2px 为实测自现有页面的 Tailwind token，沿用不另造）
- [x] Dimension 6 Registry Safety: PASS

**Approval:** approved 2026-06-27（gsd-ui-checker：6/6 通过，2 处非阻断 FLAG）
