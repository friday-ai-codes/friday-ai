---
phase: 50
slug: spec
status: draft
shadcn_initialized: false
preset: none
created: 2026-06-17
---

# Phase 50 — UI Design Contract（SPECST-03 前端部分）

> spec 治理界面（列表 / 详情 / 状态流转 / 评审）的视觉与交互契约。复用既有设计系统（reka-ui + Tailwind 4），**不引入新依赖**，默认中文 i18n。由 gsd-ui-researcher 产出，gsd-ui-checker 校验。

---

## Design System

| Property | Value |
|----------|-------|
| Tool | none（既有 reka-ui 设计系统，非 shadcn-React；Vite + Vue 3，无 `components.json`） |
| Preset | not applicable |
| Component library | reka-ui（radix 的 Vue 移植）+ 项目内 `~/components/ui/*` 封装 |
| Icon library | `@iconify` lucide 子集（`icon-[lucide--*]` class 范式） |
| Font | 沿用全局 `main.css` 字体栈（不在本 phase 改字体） |

**约束（CONTEXT D-50-5）：** 复用既有 `~/components/ui`（Badge / Button / Select / Dialog）、`MarkdownRenderer`、`useConfirmDialog`、`usePermission`、TanStack Query 派发→invalidate 范式。禁止新增第三方组件库 / registry。

---

## Spacing Scale

沿用 Tailwind 默认 4px 基准刻度（既有页面 `px-4/py-3/gap-2/space-y-5` 等已遵循）。

| Token | Value | Usage |
|-------|-------|-------|
| xs | 4px | 徽标内边距、图标与文字间隙（`gap-1`、`py-0.5`） |
| sm | 8px | 紧凑元素间距、按钮组间距（`gap-2`、`px-2`） |
| md | 16px | 卡片内边距、表单字段间距（`p-4`、`gap-4`） |
| lg | 24px | 区块分隔、详情段落间距（`space-y-5/6`、`px-5`） |
| xl | 32px | 页面主区块间距（`gap-8`） |
| 2xl | 48px | 空态 / 加载态垂直留白 |
| 3xl | 64px | 页面级顶部留白（沿用 `PageContainer`） |

Exceptions: 徽标使用 `text-[10px]` / `text-xs` 与 `px-1.5 py-0.5`（镜像 `SddMethodologyBadge` / `EntityKindBadge`，非整 4 的内边距属既有徽标既定范式，沿用以保持一致）。

---

## Typography

沿用既有页面层级（`PageHeader` 标题、`text-sm` 正文、`text-xs` 次要信息）。

| Role | Size | Weight | Line Height |
|------|------|--------|-------------|
| Display（页面标题，PageHeader） | 20px (`text-xl`) | 600 (`font-semibold`) | 1.2 |
| Heading（卡片/区块标题） | 16px (`text-base`) | 600 (`font-semibold`) | 1.4 |
| Body（spec 正文 markdown、表格行、时间线条目） | 14px (`text-sm`) | 400 | 1.5（`leading-relaxed`） |
| Label（徽标、过滤器、元信息、时间戳） | 12px (`text-xs`) | 500 (`font-medium`) | 1.4 |

声明 4 个尺寸（20/16/14/12）、2 个常用权重（400 regular + 600 semibold；500 medium 仅用于 Label 强调，沿用既有徽标范式）。

---

## Color

复用既有语义色板（`badgeVariants` + Tailwind palette），不新增主题色。60/30/10 遵循既有控制台基调。

| Role | Value | Usage |
|------|-------|-------|
| Dominant (60%) | `--background` / `bg-background` | 页面底色、主内容区 |
| Secondary (30%) | `--card` / `bg-card`、`bg-muted/20`、`border-border/50` | 卡片、列表行、时间线、过滤栏、详情面板 |
| Accent (10%) | `--primary`（`text-primary` / `bg-primary/10`） | 仅用于：主 CTA 按钮、可点击 spec 标题 hover、关联链接（work_item/plan/repo）、区块标题图标 |
| Destructive | `--destructive`（`text-destructive` / `bg-destructive/10`） | 仅用于：驳回（reject）按钮、归档二次确认的危险态文案 |

Accent reserved for: 主操作按钮（提交评审 / 批准）、spec 标题链接 hover 态、关联实体链接、区块标题图标。**不**用于普通文字、边框、所有交互元素。

### spec 状态徽标色彩映射（D-50-6，5 态）

| Status | Tone | Class（明/暗） | i18n label |
|--------|------|----------------|------------|
| `draft` | 灰 | `bg-gray-500/10 text-gray-600 border-gray-200 dark:text-gray-300 dark:border-gray-600/40` | 草稿 |
| `in_review` | 琥珀 | `bg-amber-500/10 text-amber-700 border-amber-200 dark:text-amber-300 dark:border-amber-400/30` | 评审中 |
| `approved` | 绿 | `bg-emerald-500/10 text-emerald-700 border-emerald-200 dark:text-emerald-300 dark:border-emerald-400/30` | 已批准 |
| `implemented` | 蓝 | `bg-blue-500/10 text-blue-700 border-blue-200 dark:text-blue-300 dark:border-blue-400/30` | 已实现 |
| `archived` | 中性 | `bg-muted text-muted-foreground border-border/40`（去饱和、低强调，区别于 draft 的 gray） | 已归档 |

> draft 与 archived 都是灰调，靠**饱和度/强调度**区分：draft 用实色 `gray-600`，archived 用 `text-muted-foreground` 低强调，并可选附 `lucide--archive` 图标以强化语义。

---

## Copywriting Contract

| Element | Copy |
|---------|------|
| 列表页主标题 | spec 治理 |
| 列表页副标题 | 查看与评审 spec-driven 开发的需求规格，按状态流转生命周期 |
| Primary CTA（详情页 draft 态） | 提交评审 |
| Empty state heading（列表无 spec） | 暂无 spec |
| Empty state body | 为 SDD 仓库编排方案后，系统会自动产出 spec draft；产出后将在此列出 |
| Empty state（过滤无结果） | 当前筛选条件下没有匹配的 spec，试试调整状态 / 仓库筛选 |
| Empty state（评审历史为空） | 暂无评审记录 |
| Error state（加载失败） | 加载 spec 失败，请稍后重试 |
| Error state（流转失败/非法） | 操作失败：当前状态不允许该流转，请刷新后重试 |
| Destructive confirmation（驳回 reject） | 驳回 spec：将退回 draft 并要求修订，请填写驳回意见。确认驳回？ |
| Destructive confirmation（归档 archive） | 归档 spec：归档后不可再流转，且不在常规列表突出展示。确认归档？ |
| Confirmation（批准 approve） | 批准 spec：批准后将进入 approved 状态，可附评审意见。确认批准？ |
| Confirmation（标记已实现 mark_implemented） | 标记为已实现：确认该 spec 已落地实现？ |
| Toast（提交评审成功） | 已提交评审 |
| Toast（批准成功） | 已批准 |
| Toast（驳回成功） | 已驳回，已退回草稿 |
| Toast（归档成功） | 已归档 |

文案接入 `vue-i18n`，守护测试以真实 `zh-CN.json` 断言关键文案（对齐 D-50-5 + Phase 24 范式）。

---

## Component Inventory（组件清单）

### 新建组件

| 文件 | 职责 | reuse-first 依赖 |
|------|------|------------------|
| `web/src/api/specs.ts` | API client（`list` / `detail` / `transition`）+ TS 类型（`SddSpecStatus` / `SddSpec` / `SddSpecReview` / `SpecTransitionAction`） | 复用 `~/api/client`、barrel 导出范式 |
| `web/src/pages/specs/index.vue` | spec 列表页（路由 `/specs`）：状态/仓库过滤 + 列表行 + 状态徽标 + 点击进详情 | `PageContainer` / `PageHeader` / `EmptyState` / `LoadingState` / `ui/select` / `SddSpecStatusBadge` / TanStack Query |
| `web/src/pages/specs/[id].vue` | spec 详情页（`/specs/[id]`）：markdown 正文 + 状态徽标 + 关联链接 + 评审时间线 + 操作区 | `PageContainer` / `MarkdownRenderer` / `SddSpecStatusBadge` / `SpecReviewTimeline` / `SpecTransitionActions` |
| `web/src/components/spec/SddSpecStatusBadge.vue` | 5 态状态徽标（列表 + 详情共用） | `~/components/ui/badge`（镜像 `SddMethodologyBadge` / `EntityKindBadge` class-map 范式） |
| `web/src/components/spec/SpecReviewTimeline.vue` | 评审历史时间线（reviewer / decision / comment / time，倒序） | 镜像 `EntityVersionTimeline.vue` 结构；decision 用 approve(绿)/reject(红) 小徽标 |
| `web/src/components/spec/SpecTransitionActions.vue` | 状态流转操作区：按当前状态 + 权限显隐按钮 | `ui/button` / `usePermission` / `useConfirmDialog` / `SpecReviewDialog` / TanStack `useMutation` + invalidate |
| `web/src/components/spec/SpecReviewDialog.vue` | 批准 / 驳回的 comment 输入 + 二次确认对话框（`useConfirmDialog` 无输入框，需带 textarea 的 Dialog） | `~/components/ui/dialog`（reka-ui）+ `ui/button` + `ui/textarea`（如无则 `ui/select` 同级的原生 `<textarea>` + 既有样式类） |

### 复用既有组件（reuse-first 映射）

| 需求 | 复用 | 不重复造 |
|------|------|----------|
| 页面骨架 / 标题 | `PageContainer`、`PageHeader`、`AppSidebar` 导航入口（新增 `{ to: '/specs', label: 'spec 治理', icon: 'lucide--file-check-2' }`） | 不新建布局壳 |
| 列表加载 / 空态 | `LoadingState`（`variant="card"`）、`EmptyState` | 不新写 loading/empty |
| 徽标基座 | `~/components/ui/badge` `Badge` | 不新写徽标盒子 |
| markdown 正文渲染 | `~/components/execution/MarkdownRenderer.vue`（markdown-it + Shiki，已含 `.markdown-body` 样式） | 不引新 markdown 库 |
| 过滤器 | `~/components/ui/select`（状态 / 仓库下拉） | — |
| 无输入二次确认（归档 / 标记已实现） | `useConfirmDialog`（`variant: 'destructive'` 用于归档） | 复用全局 ConfirmDialog |
| 带 comment 二次确认（批准 / 驳回） | `SpecReviewDialog`（reka-ui `Dialog`）；驳回用 destructive 态 | — |
| 权限显隐 | `usePermission().isSystemAdmin`（= superuser，对齐 D-50-3） | 不新写权限判断 |
| 派发 / 反馈 | `useMutation` + `queryClient.invalidateQueries` + `useToast` + `useErrorHandler` | 复用 Phase 24 范式 |
| 时间线 | 镜像 `EntityVersionTimeline.vue` 视觉范式 | — |

---

## State × Action Matrix（状态-操作矩阵）

合法流转（D-50-1）+ 权限分流（D-50-3）。`✓认证` = 任意认证用户可见可用；`✓SU` = 仅 superuser 可见可用；`—` = 不显示。

| 当前状态 | 提交评审 `submit_for_review` | 批准 `approve` | 驳回 `reject` | 标记已实现 `mark_implemented` | 归档 `archive` |
|----------|:---:|:---:|:---:|:---:|:---:|
| `draft` | ✓认证 → in_review | — | — | — | ✓SU |
| `in_review` | — | ✓SU → approved（带 comment） | ✓SU → draft（带 comment，必填） | — | ✓SU |
| `approved` | — | — | — | ✓SU → implemented | ✓SU |
| `implemented` | — | — | — | — | ✓SU |
| `archived` | — | — | — | — | —（终态） |

**交互规则：**
- 非 superuser 进入 `in_review` 详情：操作区仅显示「等待管理员评审」提示，不渲染 approve/reject/archive 按钮（既不可见也不可用，对齐 fail-closed）。
- `approve` / `reject` 点击 → 打开 `SpecReviewDialog`（textarea + 确认）；**reject 的 comment 必填**（前端校验，空则禁用确认按钮），approve 的 comment 可选（placeholder「可选：填写批准意见」）。
- `archive` / `mark_implemented` 点击 → `useConfirmDialog`（无输入，archive 用 `variant: 'destructive'`）。
- 所有流转走 `POST /api/specs/<id>/transition/`（D-50-4）→ 成功后 `invalidateQueries(['specs'])` + `['spec', id]` + toast；失败（含 400 非法流转）走 `useErrorHandler` 显示错误文案。
- 流转进行中按钮 `disabled` + loading 图标（`lucide--loader-circle animate-spin`），防重复派发。

---

## 关联链接区（详情页，D-50-5）

详情页头部下方展示关联摘要（来自 detail API：work_item / plan_version / repository）：

| 关联 | 展示 | 链接目标 | 缺失时 |
|------|------|----------|--------|
| repository | 仓库名 + `SddMethodologyBadge` | `/repositories/<repo_id>` | 隐藏该项 |
| work_item | 需求标题 / ID | 既有 work-item 日志页 `/logs/work-items/<id>`（若有）否则纯文本 | 隐藏该项 |
| plan_version | 方案版本号 | 纯文本 / 既有方案入口（若有路由） | 隐藏该项 |

链接用 `text-primary underline-offset-2 hover:underline`，前缀 `icon-[lucide--*]`，缺失的关联项不渲染（不显示空占位）。

---

## i18n Key 草案（`web/src/locales/zh-CN.json` → `specs` 命名空间）

```jsonc
"specs": {
  "title": "spec 治理",
  "subtitle": "查看与评审 spec-driven 开发的需求规格，按状态流转生命周期",
  "loading": "正在加载 spec…",
  "loadError": "加载 spec 失败，请稍后重试",
  "empty": "暂无 spec",
  "emptyDescription": "为 SDD 仓库编排方案后，系统会自动产出 spec draft；产出后将在此列出",
  "emptyFiltered": "当前筛选条件下没有匹配的 spec，试试调整状态 / 仓库筛选",
  "filter": {
    "status": "状态",
    "repository": "仓库",
    "all": "全部"
  },
  "columns": {
    "title": "spec 标题",
    "repository": "仓库",
    "status": "状态",
    "updatedAt": "更新时间"
  },
  "status": {
    "draft": "草稿",
    "in_review": "评审中",
    "approved": "已批准",
    "implemented": "已实现",
    "archived": "已归档"
  },
  "detail": {
    "body": "spec 正文",
    "relations": "关联",
    "workItem": "关联需求",
    "planVersion": "关联方案",
    "repository": "所属仓库",
    "reviewHistory": "评审历史",
    "reviewEmpty": "暂无评审记录",
    "reviewer": "评审人",
    "decisionApprove": "批准",
    "decisionReject": "驳回",
    "unknownReviewer": "未知用户"
  },
  "actions": {
    "submit": "提交评审",
    "approve": "批准",
    "reject": "驳回",
    "markImplemented": "标记已实现",
    "archive": "归档",
    "awaitingReview": "等待管理员评审"
  },
  "reviewDialog": {
    "approveTitle": "批准 spec",
    "approveDescription": "批准后将进入 approved 状态，可附评审意见。确认批准？",
    "rejectTitle": "驳回 spec",
    "rejectDescription": "将退回 draft 并要求修订，请填写驳回意见。确认驳回？",
    "commentLabel": "评审意见",
    "commentOptional": "可选：填写批准意见",
    "commentRequired": "请填写驳回意见",
    "confirm": "确认",
    "cancel": "取消"
  },
  "confirm": {
    "archiveTitle": "归档 spec",
    "archiveDescription": "归档后不可再流转，且不在常规列表突出展示。确认归档？",
    "archiveConfirmText": "确认归档",
    "implementTitle": "标记为已实现",
    "implementDescription": "确认该 spec 已落地实现？"
  },
  "toast": {
    "submitted": "已提交评审",
    "approved": "已批准",
    "rejected": "已驳回，已退回草稿",
    "implemented": "已标记为已实现",
    "archived": "已归档"
  },
  "error": {
    "transition": "操作失败：当前状态不允许该流转，请刷新后重试"
  }
}
```

> 注：状态 label 在 `SddSpecStatusBadge` 内通过 `specs.status.<status>` 取词，列表 + 详情共用，保证一致性。

---

## 6 支柱自检（信息层级 / 一致性 / 反馈 / 可达性 / 响应式 / 复用优先）

| 支柱 | 落点 |
|------|------|
| **信息层级** | 列表：标题(text-sm/medium) > 仓库+状态徽标 > 更新时间(text-xs/muted)。详情：状态徽标 + 标题置顶 → 关联 → 正文 → 评审历史 → 操作区固定可见。 |
| **一致性** | 徽标镜像 `SddMethodologyBadge`/`EntityKindBadge` class-map；时间线镜像 `EntityVersionTimeline`；过滤/卡片/按钮沿用既有 ui 封装；状态色彩语义与 `config/status` 同族（绿=成功/琥珀=待办/红=危险）。 |
| **反馈** | 加载（skeleton/loader）、空态（区分无数据 vs 无筛选结果）、错误（toast + 行内文案）、流转中按钮 disabled+spinner、成功 toast、二次确认。 |
| **可达性** | 按钮含图标 + 文字标签；徽标带 `title`；color 不单独承载语义（徽标含文字）；确认对话框可键盘操作（reka-ui Dialog 自带焦点管理）；链接 `underline-offset` + hover 态；暗色模式色对均声明。 |
| **响应式** | 列表移动端单列、桌面表格/卡片网格（`sm:` 断点）；详情页正文与侧栏在窄屏堆叠；操作按钮组在窄屏换行（`flex-wrap`）。 |
| **复用优先** | 7 类既有组件/composable 复用（见 reuse-first 映射）；仅新建 4 个 spec 专属组件 + 1 API client，无新依赖、无新 registry。 |

---

## Registry Safety

| Registry | Blocks Used | Safety Gate |
|----------|-------------|-------------|
| 既有项目内 `~/components/ui/*`（reka-ui 封装） | Badge / Button / Select / Dialog / Skeleton | not required（项目自有，非外部 registry） |
| 第三方 registry | none | not applicable |

本 phase 不引入任何第三方组件 registry（CONTEXT 明确「不引新依赖」），无需 registry 安全审查门。

---

## Checker Sign-Off

- [ ] Dimension 1 Copywriting: PASS
- [ ] Dimension 2 Visuals: PASS
- [ ] Dimension 3 Color: PASS
- [ ] Dimension 4 Typography: PASS
- [ ] Dimension 5 Spacing: PASS
- [ ] Dimension 6 Registry Safety: PASS

**Approval:** pending
