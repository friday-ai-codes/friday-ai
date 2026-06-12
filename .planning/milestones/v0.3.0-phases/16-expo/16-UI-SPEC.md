---
phase: 16
slug: expo
status: draft
shadcn_initialized: false
preset: none
created: 2026-06-12
---

# Phase 16 — UI Design Contract

> 交付知识实体只读详情页（`/knowledge/entities/:id`）：metadata + 版本时间线 + 关联实体树/列表 + 可选 as-of 历史时点查询。
> 复用 `web/` 既有设计系统（Tailwind 4 CSS 主题 + reka-ui + lucide + vue-i18n），不引入新设计系统或第三方 registry。
> 来源：`16-CONTEXT.md` ENH-03/ENH-04；后端 DTO 对齐 `server/knowledge/retrieval_types.py`。

---

## Design System

| Property | Value |
|----------|-------|
| Tool | none（项目自有 shadcn-vue 风格组件 `~/components/ui/*`，非 shadcn CLI 注册） |
| Preset | not applicable |
| Component library | reka-ui（Radix 风格）+ 项目自有 `~/components/ui/{button,badge,input,checkbox,collapsible,popover,tooltip,skeleton}` |
| Icon library | lucide（经 `@iconify/tailwind4`，用法 `icon-[lucide--*]`） |
| Font | 应用默认无衬线栈（Tailwind 默认 sans）；实体 ID / source_id 用 `font-mono text-sm` |

复用既有主题令牌（`web/src/styles/main.css` `@theme`）：`--color-primary`（teal-500）、`--color-card`、
`--color-border`、`--color-muted-foreground`、`--color-destructive`、`--shadow-card`。**不新增主题令牌**。

实体 kind 语义色（Badge outline 变体 + 低饱和背景，**非** accent 主色）：

| kind | Badge 样式 | 图标 |
|------|-----------|------|
| `work_item` | `bg-slate-500/10 text-slate-700 border-slate-200` | `icon-[lucide--clipboard-list]` |
| `tech_plan` | `bg-primary/10 text-primary border-primary/20` | `icon-[lucide--file-text]` |
| `code_change` | `bg-emerald-500/10 text-emerald-700 border-emerald-200` | `icon-[lucide--git-pull-request]` |

---

## Page Architecture

### Route & Shell

| Item | Value |
|------|-------|
| 路由 | `/knowledge/entities/:id`（`web/src/pages/knowledge/entities/[id].vue`） |
| 布局 | `default.vue` 工作台壳（sticky header + `main.p-6 bg-mesh-gradient`） |
| 容器 | `PageContainer`（`max-w-[1400px]`） |
| 区块导航 | `AnchorNavLayout` 三区块：metadata / timeline / related |
| 页面标题 | `useHead`：`{entity.title} - 交付知识 - Friday AI`；header `route.meta.title` = `交付知识` |
| 权限 | 已登录 JWT；403/404 fail-closed（与 service 层一致，不泄露跨项目实体） |
| 编辑能力 | **无**（只读；不出现表单提交、删除、inline edit） |

### 组件拆分（planner 可微调命名，须保持职责边界）

| 组件 | 路径建议 | 职责 |
|------|---------|------|
| 页面壳 | `pages/knowledge/entities/[id].vue` | 路由参数、TanStack Query、as-of 状态、区块编排 |
| 工具栏 | `components/knowledge/EntityDetailToolbar.vue` | as-of 选择、include_superseded 开关、重置 |
| Metadata 卡 | `components/knowledge/EntityMetadataCard.vue` | kind/version/title/时间戳/provenance 外链 |
| 版本时间线 | `components/knowledge/EntityVersionTimeline.vue` | 垂直时间线 + 版本节点 + 嵌套 code_change |
| 关联树 | `components/knowledge/EntityRelationTree.vue` | work_item→tech_plan→code_change 层级 + 扁平回退 |
| Kind Badge | `components/knowledge/EntityKindBadge.vue` | kind 中文标签 + 语义色 |
| 外链按钮 | `components/knowledge/ProvenanceLinkButton.vue` | 飞书 / MR / session 出处（有则显示） |
| API 模块 | `api/knowledge.ts` | timeline / related / entity（barrel 导出） |

### 数据获取（TanStack Query）

| Query key | Endpoint（Phase 16 对外 REST，基于 Phase 15 service） | 参数 |
|-----------|------------------------------------------------------|------|
| `['knowledge','entity',id,asOf]` | `GET /api/knowledge/entities/:id/` | `as_of`（ISO8601，可选） |
| `['knowledge','timeline',id,asOf,superseded]` | `GET /api/knowledge/timeline/:id/` | `as_of`, `include_superseded` |
| `['knowledge','related',id,asOf]` | `GET /api/knowledge/related/:id/` | `as_of`, `direction=both`, `max_hops=2` |

> 注：Phase 15 测试面仅有 timeline/related/search；Phase 16 执行须扩展 entity detail 端点并透传 `as_of`（ENH-04）。
> 响应字段对齐 `EntityMetadata` / `TimelineNodeDTO` / `RelatedEntityDTO`（`retrieval_types.py`）。

`staleTime`: 30_000ms；`as_of` 或 `include_superseded` 变更时 invalidate 并重 fetch 三 query。

---

## Spacing Scale

复用 Tailwind 默认 4px 基准刻度（与 `TriggerLogDetail.vue` / `repositories/[id]` 一致）：

| Token | Value | Usage |
|-------|-------|-------|
| xs | 4px | Badge 内 icon gap（`gap-1`） |
| sm | 8px | 时间线节点圆点与文字（`gap-2`） |
| md | 16px | 卡片内字段间距（`space-y-4`）、工具栏控件间距 |
| lg | 24px | `AnchorNavLayout` 左右栏间距（`gap-8`）、区块间距（`space-y-6`） |
| xl | 32px | 页面级 `PageContainer` 垂直 rhythm |
| 2xl | 48px | 空状态垂直 padding（`py-12`） |

Exceptions:

- 时间线垂直连线：`left-[7px]`（SubStepTimeline 同模式，非 4px 倍数，沿用既有组件惯例）
- 卡片 header：`px-5 py-3.5`（项目 card 骨架标准，见 `IndexProgressTimeline.vue`）

---

## Typography

沿用现有详情页排版（Tailwind 文本刻度）：

| Role | Size | Weight | Line Height |
|------|------|--------|-------------|
| 页面实体标题（Metadata 卡内） | 20px (`text-xl`) | 600 (`font-semibold`) | 1.3 |
| 卡片标题 | 14px (`text-sm font-semibold`) | 600 | 1.4 |
| Body / 字段值 | 14px (`text-sm`) | 400 | 1.5 |
| Label（dl dt） | 14px (`text-sm font-medium text-muted-foreground`) | 500 | 1.4 |
| 时间线节点标题 | 14px (`text-sm font-medium`) | 500 | 1.4 |
| 时间线摘要 / Hint | 12px (`text-xs text-muted-foreground`) | 400 | 1.4 |
| Mono（entity_id, source_id） | 12px (`text-xs font-mono`) | 400 | 1.4 |

---

## Color

| Role | Value | Usage |
|------|-------|-------|
| Dominant (60%) | `--color-background`（slate-50）+ `bg-mesh-gradient` | 页面背景 |
| Secondary (30%) | `.card` 白底 + `border-border` | Metadata / Timeline / Related 卡片 |
| Accent (10%) | `--color-primary`（teal-500） | 当前版本高亮、活跃锚点导航、主外链 hover、as-of 已生效指示 |
| Destructive | `--color-destructive` | 加载失败横幅、404 提示 |
| Success / Muted | emerald-500/600、muted-foreground | code_change 语义、次要时间戳 |

Accent reserved for:

- `AnchorNavLayout` 当前区块指示条与 active 文字
- Metadata 卡「当前版本」Badge（`variant` 默认 primary）
- as-of 工具栏「已应用历史视点」状态点（`bg-primary` 圆点）
- 可点击关联实体 hover 边框（`hover:border-primary/30`）

**不**用于：kind Badge 底色（用语义色表）、普通正文、时间线已完成节点圆点（用 emerald-400，同 SubStepTimeline）。

---

## Layout Wireframe

```
┌─ PageContainer ─────────────────────────────────────────────────────────┐
│ ┌─ Toolbar (.card, px-5 py-3) ────────────────────────────────────────┐ │
│ │ [icon history] 历史视点  [datetime-local]  [☐ 含已取代版本]  [重置]   │ │
│ └─────────────────────────────────────────────────────────────────────┘ │
│ ┌ AnchorNav ─┐ ┌─ Content (space-y-6) ────────────────────────────────┐ │
│ │ 基本信息 ● │ │ #entity-metadata (.card)                            │ │
│ │ 版本历史   │ │   title + kind badge + version + dl grid + 出处链接  │ │
│ │ 关联实体   │ │ #entity-timeline (.card)                            │ │
│ └────────────┘ │   vertical timeline (newest first)                  │ │
│                │ #entity-related (.card)                             │ │
│                │   tree: work_item                                    │ │
│                │     └ tech_plan                                      │ │
│                │         └ code_change                                │ │
│                └──────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

移动端（`< md`）：隐藏 `AnchorNavLayout` 侧栏，三区块纵向堆叠；工具栏控件换行（`flex-wrap gap-3`）。

---

## Copywriting Contract

全部用户可见文案经 `vue-i18n`（zh-CN 默认），命名空间 `knowledge.entity.*`。
后端返回的可操作中文 `detail` 直接展示，不在前端二次翻译。

| Element | i18n Key | Copy |
|---------|----------|------|
| 页面 meta 标题 | `knowledge.entity.pageTitle` | 交付知识 |
| 区块 - 基本信息 | `knowledge.entity.sections.metadata` | 基本信息 |
| 区块 - 版本历史 | `knowledge.entity.sections.timeline` | 版本历史 |
| 区块 - 关联实体 | `knowledge.entity.sections.related` | 关联实体 |
| kind - work_item | `knowledge.entity.kind.workItem` | 需求/缺陷 |
| kind - tech_plan | `knowledge.entity.kind.techPlan` | 技术方案 |
| kind - code_change | `knowledge.entity.kind.codeChange` | 代码变更 |
| 字段 - 版本 | `knowledge.entity.fields.version` | 版本 |
| 字段 - 来源类型 | `knowledge.entity.fields.sourceKind` | 来源类型 |
| 字段 - 来源 ID | `knowledge.entity.fields.sourceId` | 来源 ID |
| 字段 - 生效时间 | `knowledge.entity.fields.validAt` | 生效时间 |
| 字段 - 失效时间 | `knowledge.entity.fields.invalidAt` | 失效时间 |
| 字段 - 事件时间 | `knowledge.entity.fields.eventTime` | 事件时间 |
| 字段 - 项目 | `knowledge.entity.fields.project` | 所属项目 |
| 字段 - 仓库 | `knowledge.entity.fields.repository` | 所属仓库 |
| 字段 - 实体 ID | `knowledge.entity.fields.entityId` | 实体 ID |
| 当前版本 Badge | `knowledge.entity.badges.currentVersion` | 当前版本 |
| 已取代 Hint | `knowledge.entity.badges.superseded` | 已被新版本取代 |
| 出处 - 飞书 | `knowledge.entity.provenance.feishu` | 在飞书中查看 |
| 出处 - MR | `knowledge.entity.provenance.mr` | 查看合并请求 |
| 出处 - 会话 | `knowledge.entity.provenance.session` | 查看编码会话 |
| as-of 标签 | `knowledge.entity.asOf.label` | 历史视点 |
| as-of 占位 | `knowledge.entity.asOf.placeholder` | 选择日期与时间 |
| as-of 已生效 | `knowledge.entity.asOf.active` | 正在查看 {datetime} 时点数据 |
| as-of 重置 | `knowledge.entity.asOf.reset` | 恢复当前 |
| include_superseded | `knowledge.entity.includeSuperseded` | 显示已取代版本 |
| 关联 - 关系 HAS_PLAN | `knowledge.entity.relation.hasPlan` | 技术方案 |
| 关联 - IMPLEMENTED_BY | `knowledge.entity.relation.implementedBy` | 代码实现 |
| 关联 - RELATES_TO | `knowledge.entity.relation.relatesTo` | 相关 |
| 关联树 - 展开 | `knowledge.entity.related.expand` | 展开子项 |
| 关联树 - 跳转 | `knowledge.entity.related.viewEntity` | 查看详情 |
| Primary CTA（出处外链） | `knowledge.entity.cta.openSource` | 打开出处 |
| 空 - 时间线 | `knowledge.entity.empty.timelineTitle` | 暂无版本历史 |
| 空 - 时间线说明 | `knowledge.entity.empty.timelineBody` | 该实体尚未记录版本迭代 |
| 空 - 关联 | `knowledge.entity.empty.relatedTitle` | 暂无关联实体 |
| 空 - 关联说明 | `knowledge.entity.empty.relatedBody` | 尚未建立与需求、方案或代码变更的关联 |
| 错误 - 404 | `knowledge.entity.error.notFound` | 实体不存在或你无权访问 |
| 错误 - 404 动作 | `knowledge.entity.error.notFoundAction` | 返回上一页 |
| 错误 - 通用 | `knowledge.entity.error.loadFailed` | 加载交付知识失败，请稍后重试 |
| 错误 - 重试 | `knowledge.entity.error.retry` | 重试 |
| 加载中 | `knowledge.entity.loading` | 正在加载实体详情… |

Destructive confirmation：**不适用**（只读页，无删除/编辑/覆盖操作）。

---

## Interaction & States

### 加载

| State | Behavior |
|-------|----------|
| 初次加载 | 三区块各显示 `Skeleton` 占位（Metadata 6 格 grid；Timeline 4 行；Related 3 行）；工具栏 disabled |
| 部分失败 | 失败区块内 `CompactEmptyState` + 重试 `Button variant="outline"`；其他已成功区块正常展示 |
| 全局 404 | 居中 `CompactEmptyState`（`icon-[lucide--file-x]`）+ `notFound` 文案 + `Button` 返回（`router.back()` 或 `/`） |

### Metadata 卡

| State | Behavior |
|-------|----------|
| 默认 | `dl` 响应式 grid（1/2/3 列）；kind 用 `EntityKindBadge`；version 旁「当前版本」Badge（`is_latest` 或 invalid_at 为空） |
| superseded_hint 非空 | 字段下方 amber 提示条（`bg-amber-500/8 border-amber-500/15 text-amber-700 text-xs`），文案用后端 hint 或 i18n fallback |
| provenance | 飞书/MR/session 链接各一 `Button variant="outline" size="sm"` + `icon-[lucide--external-link]`；无链接则隐藏 |
| entity_id | 单行 mono + `Tooltip` 展示完整 UUID；可选 copy（`useClipboard` + toast「已复制」） |

### as-of 工具栏（ENH-04）

| State | Behavior |
|-------|----------|
| 默认 | `as_of = null`（当前有效数据）；工具栏仅显示 label + 空 datetime input |
| 选择时点 | `Input type="datetime-local"`；on change 转为 timezone-aware ISO8601（本地→UTC）写入 query state；三 query 重拉 |
| 已生效 | input 下方 `text-xs text-primary` 显示 `asOf.active`（含格式化 datetime） |
| 重置 | 文本按钮 `asOf.reset`：清空 input、`as_of=null`、恢复当前视图 |
| 无效输入 | 忽略或 inline `text-destructive text-xs`「请选择有效日期时间」；不发起请求 |
| include_superseded | `Checkbox` + label；切换仅影响 timeline query |

### 版本时间线

| State | Behavior |
|-------|----------|
| 排序 | **新→旧**（version 降序）；最新节点 accent 高亮（圆点 `bg-primary`，标题 `text-foreground`） |
| 节点结构 | 左：垂直连线 + 圆点（`w-2.5 h-2.5`，完成态 `bg-emerald-400`）；右：version + title + summary（最多 3 行 `line-clamp-3`）+ 时间戳 |
| 嵌套 code_change | 节点下缩进 `pl-4 border-l border-border/50` 列表；每项 kind badge + title + provenance 外链 |
| 空 | `CompactEmptyState` + timeline empty copy |
| 点击节点 | 只读：无跳转；若未来需深链 code_change，点击子项 `RouterLink` 到 `/knowledge/entities/:id` |

### 关联实体树

| State | Behavior |
|-------|----------|
| 首选形态 | **树形**：根=当前实体；按 relation 分层：work_item → HAS_PLAN → tech_plan → IMPLEMENTED_BY → code_change |
| 回退形态 | 无法组树时（图非链式）：**扁平列表**，每行 kind badge + title + relation 标签 + depth badge + 跳转链接 |
| 展开 | 默认展开 2 层；更深层用 `Collapsible`（同 `CodingProgressCard` 模式） |
| 节点交互 | 行 hover `bg-muted/30`；点击标题 `RouterLink` 同路由不同 id（SPA 导航，保留 as-of 查询参数可选） |
| depth 指示 | `Badge variant="outline"` 显示「{n} 跳」仅 depth > 0 |
| 空 | `CompactEmptyState` + related empty copy |

### 导航入口

| Entry | Phase 16 行为 |
|-------|--------------|
| 深链 | `/knowledge/entities/:id` 可直接访问（主入口） |
| 侧边栏 | **不强制**新增顶级 nav；若 planner 添加，用 `lucide--book-open` + label「交付知识」链到占位说明或后续列表页 |
| 跨页链接 | Phase 16 可选：chat 检索结果 / workflow 日志中 entity_id 链到本页（非 UI-SPEC 阻塞项） |

---

## Accessibility

- 工具栏 `datetime-local` 带可见 `<label>`（非仅 placeholder）
- 时间线列表用 `<ol>` / `<li>` 语义结构
- 外链按钮：`aria-label="{provenance label}: {title}"`；`target="_blank" rel="noopener noreferrer"`
- 加载 Skeleton 容器 `aria-busy="true"`；完成后移除
- 色觉：状态不仅靠颜色——当前版本额外加「当前版本」文字 Badge

---

## Registry Safety

| Registry | Blocks Used | Safety Gate |
|----------|-------------|-------------|
| 项目自有 `~/components/ui/*` | Badge, Button, Checkbox, Collapsible, Input, Popover, Skeleton, Tooltip | not required |
| reka-ui | 由上述 ui 组件内部封装 | not required |
| 第三方 shadcn registry | 无 | 不涉及 |

时间线、关联树均用原生 `div`/`ol` + Tailwind + 既有 Collapsible 实现，不引入新 registry。

---

## Checker Sign-Off

- [ ] Dimension 1 Copywriting: PASS — 全部中文 i18n key 已定义；empty/error/CTA 具体可执行
- [ ] Dimension 2 Visuals: PASS — 复用 card/AnchorNavLayout/SubStepTimeline 模式；wireframe 明确
- [ ] Dimension 3 Color: PASS — 60/30/10 + accent reserved-for 列表；kind 用语义色非 accent 滥用
- [ ] Dimension 4 Typography: PASS — 4 级字号 + 2 字重；mono 用于 ID
- [ ] Dimension 5 Spacing: PASS — 4px 倍数为主；card header 例外有文档
- [ ] Dimension 6 Registry Safety: PASS — 仅仓库内组件，无第三方 registry

**Approval:** pending
