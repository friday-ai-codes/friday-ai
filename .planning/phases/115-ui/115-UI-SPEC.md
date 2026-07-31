---
phase: 115
slug: ui
status: draft
shadcn_initialized: true
preset: "shadcn-vue（既有 web/components.json）；主题令牌在 web/src/styles/main.css 的 @theme 块（Tailwind 4），无 preset 字符串"
created: 2026-07-31
requirements: [VIEW-01, VIEW-02, VIEW-03, VIEW-04, CLAR-01, FLOW-08]
upstream: [".planning/phases/115-ui/115-CONTEXT.md", ".planning/technical-blueprint/DESIGN.md §3/§4.2/§6/§7/§8/§13.2", ".planning/phases/114-ai/114-05-SUMMARY.md", ".planning/phases/114-ai/114-REVIEW.md", ".planning/STATE.md"]
boundary: "前端 CREATE-ONLY（§13.2 第 4 条）；唯一例外是 web/src/pages/knowledge/index.vue 的 tab 列表纯追加"
---

# Phase 115 — UI 设计契约（结构化查看器 / 批注层 / 知识库管理面 / 人审终审）

> 由 gsd-ui-researcher 产出，供 gsd-planner 拆 plan、gsd-executor 逐字实现、gsd-ui-checker 校验、gsd-ui-auditor 回溯审计。
> **本文件是设计契约，不是建议**：两个不同实现者照此实现应得到实质相同的 UI。凡本文件写死的形状、状态码分档、渲染分流、颜色令牌与 i18n key，均不得在实现期再行发明。
>
> **实测起点**：`rg -ni "blueprint" web/src` **零命中** —— 前端侧彻底绿地；111–114 的 `blueprint-gate/` 八端点与 `blueprint-review/` 七端点目前**没有任何界面可达**。
> **设计基线**：Vue 3 `<script setup>` + TS + Tailwind 4 + reka-ui（`~/components/ui/*`）+ TanStack Query（服务端态）+ Pinia（客户端态）+ `unplugin-vue-router` 文件路由 + `vue-i18n`（默认 zh-CN）。视觉沿用 `web/DESIGN.md` 的 Sub2API Clean Card 风格与 `main.css` 的 `@theme` 令牌，**不另立平行令牌系统**。

---

## 0. 边界与本文件做出的设计判定

### 0.1 硬边界（违反 = 计划不通过）

| 约束 | 来源 | 本契约的落地 |
|------|------|-------------|
| 前端**只新建**组件 | STATE §13.2 第 4 条 | 除 `pages/knowledge/index.vue` 的 tab 纯追加外，本文件不指定任何既有组件的修改 |
| 不动 `TechPlanCard` / `RoutingDecisionPanel` / 执行时间线 / `ArtifactTimeline` / `NodeDataTab` | §13.2、REQUIREMENTS Out of Scope | 触点升级归 Phase 116（同步点 2 之后），本文件零涉及 |
| 不新建推送通道 | CONTEXT，§13.2 第 3 条 | 实时进展一律「只读事件端点 + 状态驱动轮询」，消费点收敛到**一个** composable `useBlueprintLive.ts` |
| 不改 `config/status.ts` 的联合类型 | CREATE-ONLY | 11 态配置新建 `config/blueprintStatus.ts`，`StatusConfig` 类型从 `~/config/status` **import 复用**（见 §0.2 判定 3） |
| 蓝图任何新增读写端点必须挂 `_aassert_project_scope` | 114-REVIEW MJ-03 | §3 五个新端点逐条标注 |
| 404 中性、不区分「无权限」与「不存在」 | 114-REVIEW MJ-03 | §8.2 只允许**一句**文案，且写成 i18n 单键 |

### 0.2 本文件做出的设计判定（CONTEXT 未覆盖，按「最贴合 CONTEXT 决策 + 既有代码库」选定并在此登记）

1. **路由参数名取 `id` 而非 `artifactId`。** 文件路由 `pages/**/[id].vue` 是全仓唯一惯例（`specs/[id].vue` / `knowledge/entities/[id].vue` / `repositories/[id]/` / `workflows/[id].vue` … 14 处，零例外），`route.params.id` 即 artifact_id。取 `[artifactId].vue` 会造出全仓唯一的参数命名，`useRoute('/knowledge/blueprints/[id]')` 的类型化路由名也会跟着分叉。**深链形态不变**：`/knowledge/blueprints/<artifact_id>`。

2. **必须再新增两个端点（CONTEXT 只登记了三个），否则 SC-2 与 CLAR-01 无法实现。** 实测 `blueprint-review/` GET 快照的线程条目 `_thread_row`（`blueprint_review_views.py:174`）只有 `{thread_id, kind, severity, status, blocking, anchor_status, anchor, return_stage, created_at}` —— **既无 `options`（澄清候选选项），也无任何 `BlueprintThreadMessage`**；且全仓无「按选区新开 `human_comment` 线程」的端点（`delivery/urls.py` 的七条 `blueprint-review/` 路由里，唯一开人工评论线程的路径是 `reject/` 的副作用）。因此本契约追加：
   - `GET  artifacts/<uuid:artifact_id>/blueprint-review/threads/`（线程 + 多轮消息 + options）
   - `POST artifacts/<uuid:artifact_id>/blueprint-review/threads/`（选区评论建 `human_comment` 线程）
   两者与既有三个新端点同样**必须**照挂 `_aassert_project_scope`。路由为字面段 `threads/` 的精确匹配，与既有 `threads/<uuid:thread_id>/<动作>/` 互不遮挡（`delivery/urls.py:189` 注释已声明该顺序纪律）。

3. **11 态徽标不进 `config/status.ts`。** `web/DESIGN.md` 禁止在组件内散落状态色映射、要求集中配置；但 `getStatusConfig` 的 `type` 联合类型属既有面，加值即改既有面。取**集中到新模块** `web/src/config/blueprintStatus.ts`（`import type { StatusConfig } from '~/config/status'` 复用类型契约），既守 CREATE-ONLY 又守「不散落」的设计意图。

4. **通知渠道投递不在本相位。** STATE「115 必读三条」点名的通知面缺口，CONTEXT `<deferred>` 已明确顺延到通知面（同步点 1 后）。本契约只兑现**界面可感知**：顶栏「待澄清」计数徽标 + 线程侧栏 `open` 组常驻 + 澄清线程条目显示「已提醒 N 次 / 上次提醒时间」（若 `last_reminded_at` 经 §3.4 端点回传）。

5. **`blueprint_quality` 三项统计的消费面 = 人审面板**（闭 114-REVIEW MN-05）。三项经 §3.1 端点的 `quality` 键回传，`None` 渲染「暂无数据」，**绝不显示 0**。

6. **`fitness.verdict == "unsuitable"` 的「替代建议」按 `fitness.reasons` 自由文本原样展示**，不为呈现去改已锁定的 schema（同时定夺 STATE 登记的「Phase 112 残留 PARTIAL / FLOW-02」）。

---

## 1. Design System

| Property | Value |
|----------|-------|
| Tool | shadcn-vue（已初始化，`web/components.json`）；原语在 `~/components/ui/*` |
| Preset | 无 preset 字符串；主题令牌定义于 `web/src/styles/main.css` 的 `@theme` 块（Tailwind 4） |
| Component library | reka-ui。本相位复用：`dialog`（含 `DialogScrollContent`）/ `sheet` / `skeleton` / `tabs` / `badge` / `popover` / `tooltip` / `scroll-area` / `table` / `pagination` / `select` / `input` / `textarea` / `button` / `collapsible` / `separator` / `alert-dialog`（经 `useConfirmDialog`） |
| 布局原语 | `~/components/layout/PageContainer.vue`、`~/components/layout/AnchorNavLayout.vue`（**六段目录导航直接复用**，`NavSection` 已带 `badge` / `badgeTone` 与 IntersectionObserver 高亮） |
| 图表 / 代码 | `mermaid@^11`（经 `~/components/project/warroom/MermaidDiagram.vue` 复用，自带渲染失败回退源码 + 放大）；CodeMirror（`~/components/codemirror/fridayLightTheme.ts`）只读实例用于代码片段预览 |
| Diff | `diff` 包（已在依赖）：块级用 `block_id` 集合运算，块内文本用 `diffWords`；视觉范式对齐 `~/components/prompts/PromptVersionDiff.vue` |
| 浮层定位 | `@floating-ui/vue`（已在依赖）——仅用于选区评论 popover |
| Icon library | Iconify via `@iconify/tailwind4`，class 形态 `icon-[lucide--*]`；**动态拼接的图标必须进 `main.css` 的 `@source inline(...)` safelist** |
| Font | 系统默认字体栈（未自定义 `--font-*`）；`font-feature-settings: 'rlig' 1, 'calt' 1` |
| Dark mode | 全站无 `.dark` 主题块（`main.css` 只有浅色 `@theme`）；本相位**不引入**深色变体，`MermaidDiagram` 既有的 `document.documentElement.classList.contains('dark')` 判定原样复用即可 |

**Registry gate:** 不引入任何第三方 shadcn registry / block。全部为既有 `ui/` 原语的组合 + 新建业务组件，registry 安全门**不适用**（§13）。

---

## 2. Spacing Scale

沿用 Tailwind 4 的 4px 基准刻度与 `web/DESIGN.md` 的卡片密度（`p-4`~`p-5`、`gap-4`）。

| Token | Value | Usage |
|-------|-------|-------|
| xs | 4px | 图标—文字间隙（`gap-1`）、徽标内边距、chip 行内间距 |
| sm | 8px | 紧凑元素间距（`gap-2`）、线程卡内元素、块内 citation chip 行 |
| md | 16px | 卡片内边距（`p-4`）、段内块间距（`space-y-4`）、筛选栏元素间距 |
| lg | 24px | 段与段之间（`space-y-6`）、卡片头 `px-5`（20px 归入本档，见例外） |
| xl | 32px | 三栏列间隙（`gap-8` 由 `AnchorNavLayout` 提供）、页面主区块分隔 |
| 2xl | 48px | 空态/错误态的纵向留白 |
| 3xl | 64px | 页面级顶部留白（由 `PageContainer` 提供） |

**Exceptions（沿用既有密度，改动即造成与邻近页面不一致）:**
- `12px`（`p-3` / `gap-3` / `space-y-3`）：线程卡、mermaid 容器内边距、diff 行内边距 —— 与 `MermaidDiagram.vue`、`PromptVersionDiff.vue` 既有值一致。
- `20px`（`px-5` / `py-3.5`）：卡片头与卡片内容内边距 —— `web/DESIGN.md` 明列的标准卡片模式。
- `44px`：图标-only 触控目标最小尺寸（线程侧栏的折叠箭头、选区 popover 的按钮），保证移动端可点。
- `88px`：`AnchorNavLayout.scrollTo` 的锚点偏移常量（既有），六段导航跳转沿用，不得另设。

---

## 3. 数据契约（新增端点 + 复用端点）

> 全部前端调用集中在**新建**的 `web/src/api/blueprints.ts`（barrel 追加到 `web/src/api/index.ts`）。
> 五个新端点全部 `IsAuthenticated` + `_aassert_project_scope`（非成员 → 中性 **404**；蓝图读不到 `meta.project_id` → **400**）。

### 3.1 `GET /api/delivery/artifacts/<uuid:artifact_id>/blueprint/` — 蓝图正文（新增）

可选 `?version_id=<uuid>`（缺省取 current）。

```ts
interface BlueprintDocumentResponse {
  version_id: string
  version_no: number
  is_current: boolean
  produced_by_ref: string          // 四前缀之一或 AI 产出
  created_at: string               // ISO8601
  content: BlueprintV1             // schema_version === 'blueprint/v1'
  quality: {
    citation_coverage: number | null      // 纯函数，0..1
    ai_rejection_rate: number | null      // 无数据 → null（绝不渲染成 0）
    human_edit_volume: number | null
    clarification_rounds: number | null
  }
}
```

**为什么必须新增**：`blueprint-review/` 快照不返回 content；`ArtifactTimelineView` 只给 `current_version_markdown`（结构已丢，做不了 block 锚定与 block 级 diff）。**不把 content 内联进快照**——快照要被高频重取。

### 3.2 `GET .../blueprint/events/` — 阶段事件（新增，只读）

只取 `ConvergenceSessionEvent` 中 `event` ∈ `BLUEPRINT_EVENTS`（21 个常量，`delivery/services/event_taxonomy.py`）。

```ts
interface BlueprintEventsResponse {
  session_id: string
  current_stage: string
  events: Array<{ id: string, event: string, payload: Record<string, unknown>, ts: string }>  // ts 升序
}
```

### 3.3 `GET /api/delivery/blueprints/` — 蓝图列表（新增）

Query：`project_id` / `blueprint_status` / `repository_id` / `q`（标题+摘要 icontains）/ `page` / `page_size`。DRF 分页体。

```ts
interface BlueprintListItem {
  artifact_id: string
  title: string
  summary: string                 // meta.summary 首块纯文本截断
  blueprint_status: BlueprintStatus
  project_id: string | null
  project_name: string
  repositories: Array<{ id: string, name: string, role: 'direct' | 'indirect' }>
  thread_count: number
  unresolved_blocker_count: number
  revision_round: number
  current_version_no: number
  updated_at: string
}
```

**不改 `ArtifactListView`**：那是通用面且已被 `components/delivery/ArtifactTimeline.vue` 消费，挂闸会改既有面行为。**不用 `searchDeliveryKnowledge`**：向量召回做不了状态精确筛选与稳定分页（语义搜索留 116/Future）。

### 3.4 `GET .../blueprint-review/threads/` — 线程 + 多轮消息（新增，§0.2 判定 2）

```ts
interface BlueprintThreadDetail {
  thread_id: string
  kind: 'ai_clarification' | 'ai_review_finding' | 'human_comment' | 'repo_confirmation'
  severity: '' | 'blocker' | 'warning' | 'info'
  status: 'open' | 'answered' | 'resolved' | 'dismissed'
  blocking: boolean
  anchor_status: 'anchored' | 'orphaned'
  anchor: { section_path?: string, block_id?: string, start_offset?: number, end_offset?: number, quoted_text?: string } | null
  return_stage: string
  options: Array<{ label: string, value: string, note?: string }>
  created_at: string
  last_reminded_at: string | null
  messages: Array<{ id: string, author_type: 'ai' | 'human', author_user_id: string | null, author_display: string, body: string, created_at: string }>
}
```

### 3.5 `POST .../blueprint-review/threads/` — 选区评论建线程（新增，CLAR-01 后半句）

入参 `{ body: string, anchor: { block_id, start_offset, end_offset, quoted_text, section_path? } }`。
后端一律建 `kind="human_comment"`、`blocking=false`（评论不得把蓝图钉死）、`initiated_by_user_id=<uid>`。
状态码：`200`（含 `thread_id`）/ `body` 空 **400** / 蓝图状态 ∉ 可编辑白名单 **400**（与 `answer` 同闸）/ 非成员 **404**。

### 3.6 复用的既有端点（零新增）

| 用途 | 端点 / 前端 API | 备注 |
|------|----------------|------|
| 版本轨 | `deliveryArtifacts.getArtifactTimeline(artifactId)` | 已含 `version_no` / `produced_by_ref` / `supersedes_id` / `is_current` —— **版本切换器零新端点** |
| 人审快照 | `GET .../blueprint-review/` | findings 三级分组 / `orphaned_threads` / `unresolved_blocker_thread_ids` / `revision_round` / `current_status` |
| 人审动作 | `approve/` `reject/` `edit-blocks/` `threads/<id>/answer/` `threads/<id>/resolve/` `threads/<id>/dismiss/` | 状态码映射逐字见 §8 |
| 确认门 | `blueprint-gate/` 快照 + 七动作 | `confirm` / `remove-repo` / `add-repo` / `reclassify-role` / `edit-responsibility` / `rejected-to-boundary` / `upgrade-research` |
| 引用预览 | `knowledgeApi.getEntity` / `GET /api/repositories/<id>/chunk-at/?path=&line=` / `GET /api/repositories/<id>/charter/` | 后两者**前端尚无 API 封装**，本相位在 `api/repositories.ts` 之外新建 `api/repositoryChunks.ts`（CREATE-ONLY） |
| 关联区 | `knowledgeApi.getRelated` / `knowledgeApi.getArtifactAssociations` | 蓝图互引与知识关联双向可查（SC-4） |

### 3.7 TanStack Query queryKey 契约

| key | 说明 | staleTime |
|-----|------|-----------|
| `['blueprint', 'doc', artifactId, versionId ?? 'current']` | 正文 | 30_000 |
| `['blueprint', 'snapshot', artifactId]` | 人审快照 | 0（动作后必 invalidate） |
| `['blueprint', 'threads', artifactId]` | 线程 + 消息 | 0 |
| `['blueprint', 'events', artifactId]` | 阶段事件 | 0 |
| `['blueprint', 'timeline', artifactId]` | 版本轨 | 30_000 |
| `['blueprint', 'gate', artifactId]` | 确认门快照 | 0 |
| `['blueprint', 'list', filters]` | 列表 | 30_000 |
| `['blueprint', 'citation', sourceType, sourceId]` | 引用预览 | 5 分钟 |

**任何动作端点 2xx 后**：以响应体 `current_status` 为准写回本地展示态，**并**立即 `invalidateQueries({ queryKey: ['blueprint'] , predicate: 命中该 artifactId })` 重取快照/线程/正文。**前端不得自行乐观推断下一状态**（114-REVIEW MJ-01 第二点：状态在续驱之后才是真值）。

---

## 4. 路由契约

### 4.1 查看器路由页（唯一权威渲染面）

| 项 | 值 |
|----|----|
| 文件 | `web/src/pages/knowledge/blueprints/[id].vue` |
| 路径 | `/knowledge/blueprints/:id`，`:id` = `artifact_id`（UUID） |
| 类型化 route | `useRoute('/knowledge/blueprints/[id]')` |
| `definePage` meta | `{ title: 'knowledge.blueprints.pageTitle' }`（与 `pages/knowledge/entities/[id].vue` 同范式，`useHead` 设文档标题） |

**query 参数（全部可选，与 ref 双向同步 + `normalize*` 兜底，范式抄 `pages/knowledge/index.vue`）:**

| query | 取值 | 语义 |
|-------|------|------|
| `version` | version_id (uuid) | 查看历史版本；缺省 = current |
| `diff` | version_id (uuid) | 与 `version`（或 current）做 block 级 diff；存在即进入 diff 视图 |
| `diff_mode` | `inline`(默认) \| `split` | diff 呈现形态 |
| `section` | 段 key（见 §6.1） | 进入后滚动到该段 |
| `thread` | thread_id (uuid) | 打开线程侧栏并选中该条；窄屏自动展开抽屉 |
| `panel` | `gate` \| `review` | 直接展开确认门 / 人审面板 |

**深链格式（对外唯一形态，Phase 116 的入口收编与导出一律指向它）:**
```
/knowledge/blueprints/{artifact_id}
/knowledge/blueprints/{artifact_id}?section=api_contracts
/knowledge/blueprints/{artifact_id}?thread={thread_id}
/knowledge/blueprints/{artifact_id}?version={version_id}&diff={base_version_id}&diff_mode=split
```

**⛔ 不做「全屏 Dialog 形态」的第二套实现。** 理由（CONTEXT 决定性论证）：DESIGN §8.3 要求引用预览是「查看器之上再弹一层」；若查看器本身是 Dialog，预览就成了**嵌套 Dialog**（§8.3 自承代码库无先例、需新造 z-index/焦点管理封装）。改成路由页后引用预览就是**第一层** `Dialog`，直接复用既有 `components/ui/dialog/`，零新封装。

### 4.2 知识库 tab 深链

| 项 | 值 |
|----|----|
| 宿主 | `web/src/pages/knowledge/index.vue`（**本相位唯一被允许修改的既有文件**，且只做纯追加） |
| 追加内容 | `KnowledgeTab` 联合类型加 `'blueprints'`；`TABS` 数组加 `'blueprints'`；`TabsTrigger` 循环数组加 `{ value: 'blueprints', icon: 'icon-[lucide--file-text]' }`；新增一个 `<TabsContent value="blueprints">` 渲染 `<BlueprintsTabPanel />` |
| 不得改 | `normalizeTab` 实现、`?tab=` 双向同步 watcher、既有四个 tab 的任何一行 |
| 深链 | `/knowledge?tab=blueprints&bp_status=pending_review&project_id=<uuid>&repository_id=<uuid>&q=<kw>&page=2` |

query 键取 `bp_status` 而非 `status`，避免与知识库将来可能的通用 `status` 冲突；与既有 `dep_type` 的「模块前缀」命名习惯一致。

### 4.3 出站深链

| 从 | 到 | 组件 |
|----|----|------|
| 仓库关联卡 | `/repositories/{repository_id}`（`pages/repositories/[id]/index.vue`） | `RepoAssociationCard.vue`，`RouterLink`（SC-3） |
| 引用预览 · 知识实体 | `/knowledge/entities/{entity_id}`（弹层内「在知识库中打开」） | `CitationKnowledgePreview.vue` |
| 引用预览 · 其他蓝图 | `/knowledge/blueprints/{artifact_id}` | `CitationBlueprintPreview.vue` |
| 项目物料卡 | `/knowledge/blueprints/{artifact_id}` | `ProjectBlueprintsCard.vue`（SC-4） |
| 列表项 | `/knowledge/blueprints/{artifact_id}` | `BlueprintListCard.vue`（SC-4，深链直达查看器） |

---

## 5. 布局与响应式

### 5.1 三栏骨架（对齐 DESIGN §8.1）

```
┌──────────────────────────────────────────────────────────────────────┐
│ BlueprintViewerHeader（sticky top）                                   │
│  标题 · 11 态徽标 · [未决BLOCKER n][待澄清 n][失锚 n] · 版本切换器      │
│                                            ┊ 阅读区操作 ┊ 终审操作区   │
├───────────┬──────────────────────────────────┬───────────────────────┤
│ 左：六段   │ 中：结构化正文                    │ 右：线程侧栏           │
│ 目录导航   │  BlueprintStageTimeline           │  未决 / 已回答 /       │
│ (w-48)    │  6 × Section（含骨架/空/错误态）   │  已关闭(折叠) /        │
│ sticky    │  BlueprintGatePanel（条件渲染）    │  失锚批注              │
│           │  BlueprintQualityPanel（人审态）   │  (w-80)  sticky        │
└───────────┴──────────────────────────────────┴───────────────────────┘
```

### 5.2 断点行为

代码库实测断点使用分布：`sm:` 134 处 / `md:` 40 / `lg:` 57 / `xl:` 9 / `2xl:` 0。本契约只用既有四档，**不引入 `2xl`**。

| 断点 | 宽度 | 布局 |
|------|------|------|
| `< md`（<768px） | 单栏 | 左栏 → 顶部 `Select` 下拉段跳转；右栏 → `Sheet`（side="right"，由顶栏「批注 n」按钮唤起）；顶栏计数徽标折成一行可横向滚动 |
| `md`（≥768px） | 两栏 | 左栏显示（`AnchorNavLayout` 自带 `hidden md:block w-48`）；右栏仍为 `Sheet` |
| `lg`（≥1024px） | 两栏 + 宽正文 | 正文最大宽度放开；卡片网格 `lg:grid-cols-2`（API 契约卡、仓库关联卡） |
| `xl`（≥1280px） | 三栏 | 右侧线程侧栏**常驻**（`hidden xl:flex w-80 shrink-0`），`Sheet` 停用；此即 CONTEXT「窄屏 <1280px 右栏收成抽屉」的字面落点 |

**侧栏折叠**：`xl` 及以上仍允许用户手动折叠右栏（顶栏 toggle，状态存 Pinia `useBlueprintViewerStore().sidebarCollapsed`，`@vueuse/core` 的 `useLocalStorage` 持久化）。折叠后正文占满，`?thread=` 深链会强制展开。

### 5.3 滚动与粘性

- 页面级滚动（`window`），与 `AnchorNavLayout.scrollTo` 的 `window.scrollTo` 一致；**不做正文内独立滚动容器**，否则 IntersectionObserver 的 `rootMargin` 与既有实现不兼容。
- 顶栏 `sticky top-0 z-30`；左栏 `sticky top-22`（`AnchorNavLayout` 既有值）；右栏 `sticky top-22 max-h-[calc(100vh-6rem)]` 内部用 `ScrollArea`。
- z-index 分层：正文高亮 `z-0` → 选区 popover `z-40` → `Sheet` `z-50`（reka-ui 默认）→ 引用预览 `Dialog` `z-50`（**第一层**，无嵌套）→ `GlobalConfirmDialog` 最高。

---

## 6. 六段渲染规则

### 6.1 段 key、导航与顺序（与后端 content 顶层键逐字一致）

| # | 段 key（导航 key = DOM `id`） | 中文标题 | 图标 | badge |
|---|------------------------------|---------|------|-------|
| 0 | `requirement_spec` | 需求规格 | `icon-[lucide--target]` | 功能点数 |
| 1 | `repo_associations` | 仓库关联 | `icon-[lucide--folder-git-2]` | 仓库数（direct/indirect 分色 tone） |
| 2 | `current_state_analysis` | 现状分析 | `icon-[lucide--scan-eye]` | findings 数 |
| 3 | `implementation_overview` | 实现概述 | `icon-[lucide--layers]` | 实现项数 |
| 4 | `api_contracts` | API 契约 | `icon-[lucide--plug]` | 接口数（needs_support 时 tone=warning） |
| 5 | `impact_analysis` | 影响范围 | `icon-[lucide--alert-triangle]` | 受影响功能数 |
| 6 | `interaction_flows` | 交互流程 | `icon-[lucide--workflow]` | 流程数 |
| 7 | `decision_log` | 决策记录 | `icon-[lucide--gavel]` | 条目数 |
| 8 | `associations` | 关联 | `icon-[lucide--link]` | 关联数 |

导航 badge 的 `badgeTone` 规则：该段内**存在未决 BLOCKER 线程** → `danger`；**存在 open 澄清线程** → `warning`；生成中 → `primary`；其余 → `muted`。
「批注数」以 `AnchorNavLayout` 的 badge 承载，形如 `3`（该段锚定线程总数），tone 按上表。

> 所有新增的 `icon-[lucide--*]` 若为**动态拼接**（如按 `change_type` 取图标），必须在 `main.css` 追加一行 `@source inline(...)`，否则生产构建被 tree-shake 掉。静态写在模板里的图标无需 safelist。

### 6.2 通用块渲染 —— `BlueprintBlock.vue`（**批注层与引用层的唯一实现点**）

一个 `Block`（DESIGN §3.2，schema 见 `blueprint_schema.py` 的 `$defs.block`）进，一段 DOM 出。**六段各自不重复实现批注与引用**。

```ts
// props
{
  block: BlueprintBlock            // { block_id, type, text?, code?, rows?, citations? }
  sectionPath: string              // iter_blocks 的点分 + [标识] 约定，仅作降级定位与失锚回显文案
  threads: BlueprintThreadDetail[] // 已按 block_id 预分组（由 useBlueprintAnnotations 提供）
  citations: Record<string, Citation>   // 文档级引用池
  readonly: boolean                // current_status ∉ 可编辑白名单
  activeThreadId: string | null
}
// emits
{
  'thread-click': [threadId: string]                       // 正文划线 → 侧栏选中
  'selection-comment': [payload: { blockId, startOffset, endOffset, quotedText }]
  'citation-click': [citationId: string]
  'edit-block': [blockId: string]                          // readonly 时该入口不渲染
}
```

**DOM 契约（重锚定与测试都依赖它）：**
- 根元素 `:id="\`blk-${block.block_id}\`"`、`:data-block-id="block.block_id"`、`data-testid="blueprint-block"`。
- **块级 DOM id 用 `block_id`**（111 保证版本间稳定：编辑保留、新增才生成）。⛔ 前端**不得**自造第三套 DOM 标识——114 的重锚定判据就是 `block_id → quoted_text → orphaned`，自造标识必然与重锚定结果错位。
- `section_path` **只**用于两处：降级定位（`block_id` 找不到时的兜底）与失锚回显文案；不参与 DOM id。

**块类型分发（五类，与 schema `enum` 逐字对齐）：**

| `type` | 渲染 |
|--------|------|
| `paragraph` | `<p class="text-sm leading-relaxed">`，纯文本（mustache，**禁 `v-html`**） |
| `list` | `text` 为条目字符串数组 → `<ul class="list-disc pl-5 space-y-1 text-sm">`；每个条目独立参与字符区间切分（offset 以「条目间用 `\n` 连接」的扁平串计） |
| `table` | `rows[0]` 为表头，其余为数据行；用 `~/components/ui/table`；表格块**不做字符级划线**，只做整块左侧色条（见 §7.3） |
| `pseudocode` | `code.language` + `code.source`；`<pre class="font-mono text-xs leading-6">` + 语言徽标 + 复制按钮；**不引入语法高亮引擎**（伪代码非真实语言，高亮易误导），只做等宽 + 行号 |
| `mermaid` | `text` 作为 mermaid 源码传给 `MermaidDiagram.vue`（复用：渲染失败自动回退源码 + 放大查看）；mermaid 块**不做字符级划线**，只做整块左侧色条 |

**citation chip**：块底部一行 `BlueprintCitationChip.vue`，形如 `[1] onion-practice/src/x.py:10-42`。
chip 视觉：`inline-flex items-center gap-1 rounded-md border border-border bg-muted/60 px-1.5 py-0.5 text-[11px] font-mono text-muted-foreground hover:border-primary/40 hover:text-primary`；前缀图标按 `source_type` 取（`knowledge_entity`→`lucide--book-open`、`repo_file`/`rag_chunk`→`lucide--file-code`、`repo_charter`→`lucide--scroll-text`、`blueprint`/`artifact_version`→`lucide--file-text`、`work_item`→`lucide--list-checks`、`feishu_doc`/`url`→`lucide--external-link`）。
chip 是 `<button>`（外链类型除外，那是 `<a target="_blank" rel="noopener noreferrer">`），`aria-label` = `t('knowledge.blueprints.citation.open', { title })`。

### 6.3 段 1 —— 仓库关联卡（`RepoAssociationCard.vue`）

```
┌───────────────────────────────────────────────────────────┐
│ [direct] onion-practice          fitness: suitable   →跳转 │  ← role 徽标 + 仓名 + fitness 徽标 + RouterLink
│ 职责：<Block[]>                                            │
│ ▸ 选仓理由（可展开）                                        │  ← Collapsible，展开后 Block[] + citation chips + constraint_refs
│ ▸ 适配判定（可展开）  verdict / reasons Block[]             │
│ direct 专属：本仓改动摘要 <Block[]>                         │
│ indirect 专属：会被用到的能力（name / location / how_used） │
│ [需要配合] support_needed <Block[]>                        │  ← 有值才渲染
│ routing: score 0.83 · confidence high · 本项目组 / 跨组标注 │  ← routing_evidence
│ 决定人：AI 提议 / 人工确认  · 已在确认门锁定 ✓              │  ← decided_by / confirmed_at_gate
└───────────────────────────────────────────────────────────┘
```

| 字段 | 渲染契约 |
|------|---------|
| `role` | `direct` → `<Badge variant="default">直接改动</Badge>`；`indirect` → `<Badge variant="secondary">间接依赖</Badge>`。**双色，不发明第三色** |
| `fitness.verdict` | `suitable`→`variant="success"`；`partial`→`variant="warning"`；`unsuitable`→`variant="destructive"` |
| `fitness.reasons` | Block[] 经 `BlueprintBlock` 渲染。**`unsuitable` 时的「替代建议」按 `reasons` 自由文本原样展示，不补 schema 字段**（§0.2 判定 6） |
| 跳转 | 卡右上角 `RouterLink to="/repositories/{repository_id}"`，图标 `icon-[lucide--external-link]`，文案 `t('knowledge.blueprints.repo.openRepository')`（SC-3） |
| `routing_evidence.cross_team === true` | 追加 `<Badge variant="warning">跨组协作</Badge>` |
| `confirmed_at_gate === false` | 追加 `<Badge variant="outline">未经确认门锁定</Badge>` |
| 布局 | `lg:grid-cols-2` 网格；卡片用 `.card` + `p-4` |

### 6.4 段 2 —— 现状分析（`CurrentStateSection.vue`）

按 `repository_id` 分组（组头显示仓名 + finding 计数），组内每条 finding：
- `kind` 徽标：`capability`→`variant="info"` 能力 / `gap`→`variant="warning"` 缺口 / `risk`→`variant="destructive"` 风险 / `convention`→`variant="secondary"` 约定。
- `topic` 作小标题（14px/600），`text` 走 `BlueprintBlock`。
- `related_feature_points` 渲染成可点 chip，点击滚动到 `requirement_spec` 段对应功能点并短暂高亮（`animate-fade-in` + 2s ring）。
- **`citations` 为空时**渲染 `<Badge variant="destructive">缺引用</Badge>`（schema 要求必填，缺失是质量信号，不隐藏）。

### 6.5 段 3 —— 实现概述（`ImplementationOverviewSection.vue` + `ImplementationItemCard.vue`）

三层：`requirement_narrative`（Block[]） → `modules`（卡片，展示 `name` / 关联功能点 chips / 关联仓 chips / `narrative`） → `items`（实现项卡）。

实现项卡锚定信息条（一行 mono 小字）：`change_type` 徽标 · 所属模块 · 所属仓 · `wave W` · `depends_on` chips。

| `change_type` | 徽标 | 图标 |
|---------------|------|------|
| `create` | `variant="success"` 新建 | `icon-[lucide--file-plus]` |
| `modify` | `variant="info"` 改动 | `icon-[lucide--file-pen-line]` |
| `remove` | `variant="destructive"` 删除 | `icon-[lucide--file-x]` |
| `indirect_refine` | `variant="secondary"` 间接完善 | `icon-[lucide--file-cog]` |

卡内分区：`how`（Block[]，常含 `pseudocode` 块）、`existing_integration`（Block[]，仅 `modify`/`indirect_refine` 有值时渲染，标题「与既有功能如何配合」）、`files_touched`（紧凑表：path / action 徽标 / note，path 用 `font-mono text-xs`）、`test_strategy`（Block[]）。

**波次可视化**：段头给一条 `wave` 泳道条（`wave 1 · 3 项 | wave 2 · 5 项 …`），点击筛选该波次的实现项。纯客户端筛选，不改 URL。

### 6.6 段 4 —— API 契约卡（`ApiContractCard.vue`）

```
┌──────────────────────────────────────────────────────────┐
│ [provided] [http] POST /api/practice/generate            │  ← direction 徽标 + kind 徽标 + method + path(mono)
│ 生成习题                                    仓：xxx-api   │
│ 描述 <Block[]>                                            │
│ ┌ 请求示例 ─────────┬ 响应示例 ─────────┐                  │  ← lg:双栏，<lg 上下堆叠；<pre> JSON，带复制
│ │ {...}             │ {...}             │                  │
│ └───────────────────┴───────────────────┘                  │
│ ▸ 数据来源（consumed 专属）                                │
│   from_service / from_api / fields_needed chips           │
│   [已有] 或 [需 xxx 仓支持产出]                             │  ← availability 徽标
│ 消费方：mod_01, mod_02                                     │
└──────────────────────────────────────────────────────────┘
```

| 字段 | 渲染契约 |
|------|---------|
| `direction` | `provided`→`variant="default"` 本方案提供；`consumed`→`variant="secondary"` 需要调用 |
| `kind` | `http`/`rpc`/`event`/`mq` → `variant="outline"`，mono 小写 |
| `method` | 单色 mono 徽标（`GET`/`POST`/`PUT`/`DELETE`/`PATCH` 不分色 —— `web/DESIGN.md` 禁彩虹） |
| `request_example` / `response_example` | `JSON.stringify(v, null, 2)` 进 `<pre class="font-mono text-xs">`，**禁 `v-html`**；超 20 行折叠为「展开全部」 |
| `data_source.availability` | `existing`→`variant="success"` 数据已有；`needs_support`→`variant="warning"` 需 `{support_repository_name}` 支持产出，且该仓名可点跳转 `/repositories/{support_repository_id}` |
| ⚠️ 读取位置 | `availability` / `support_repository_id` **只在 `data_source` 内**，顶层零残留（113-05 决策）。前端**不得**回落读顶层，读不到即渲染「未标注」 |
| 布局 | `lg:grid-cols-2` 卡片网格；卡内示例双栏在 `lg` 以上生效 |

### 6.7 段 5 —— 影响矩阵（`ImpactMatrixTable.vue`）

- `business_impact`：Block[]，置顶，业务语言优先。
- `affected_features`：**矩阵表**（`~/components/ui/table`），列 = `功能` / `涉及仓库` / `影响类型` / `说明` / `证据`。
  - `kind` 徽标：`behavior_change`→`warning` 行为变更 / `perf`→`info` 性能 / `compat`→`warning` 兼容 / `data`→`destructive` 数据 / `none`→`muted` 无影响。
- `regression_scope`：紧凑表，`level` 徽标 `full`→`destructive` 全量回归 / `smoke`→`warning` 冒烟 / `none`→`muted` 无需回归。
- `compat_risks` / `rollback_plan`：Block[]。
- `data_migrations`：条目列表，`reversible === false` 加 `<Badge variant="destructive">不可逆</Badge>`。
- 窄屏（`< md`）矩阵表降级为卡片堆叠（每行一卡，字段变成「标签: 值」），**不做横向滚动表**。

### 6.8 段 6 —— 交互流程（`InteractionFlowsSection.vue`）

每条 flow 一张卡：
1. 卡头：`name` + `trigger`（前缀图标 `icon-[lucide--mouse-pointer-click]`）。
2. **mermaid 图**：`flow.mermaid` 直接给 `MermaidDiagram.vue`（复用其失败回退源码 + 放大弹窗）。`mermaid` 为空时不渲染容器，只显示步骤表。
3. **步骤表**：列 = `seq` / `actor` / `action` / `component` / `api_ref` / `data_in` / `data_out`。
   - `actor` 徽标：`user`→`default` 用户 / `frontend`→`info` 前端 / `backend`→`secondary` 后端 / `service:*`→`outline` 显示服务名。
   - `api_ref` 渲染成 chip，点击滚动到 `api_contracts` 段对应卡并 2s ring 高亮。
   - `note` 为 Block[]，作为该行的展开行（`Collapsible`）。
4. `alternative_paths`：每条一个 `Collapsible`，标题 = `condition`，内容 = 同构步骤表。

---

## 7. 批注层机制（CLAR-01，本相位最不能做错的一层）

### 7.1 划线粒度与切分算法

**粒度 = block 内字符区间。** 以 block 为最小渲染单元，按 `anchor.start_offset` / `end_offset` 在该 block 的**纯文本**上切分并用 `<mark>` 包裹。

```
输入：blockText（string）、该 block 上的 threads[]
1. 过滤：只取 anchor_status === 'anchored' 且 anchor.block_id === block.block_id 的线程
2. 校验每条 anchor：start/end 必须是整数、0 ≤ start < end ≤ blockText.length —— 否则进「降级集合」
3. 把合法区间按 start 升序排；重叠区间**不合并**，改为切成不相交子段，每个子段携带其覆盖的 threadId 集合
   （一个字符可同时属于多条线程：视觉取「优先级最高的一条」着色，`title`/`aria-label` 列出全部）
4. 按切点生成 [纯文本段 | <mark> 段] 序列，用 v-for 渲染。**全程 mustache，禁 v-html**（XSS 面 = 0）
```

优先级（决定重叠时的着色）：`blocker` > `warning` > `human_comment` > `info`/`ai_clarification`；同级时 `open` > `answered` > `resolved`/`dismissed`。

**⛔ 不引入 tiptap / ProseMirror 只读实例**：只读渲染面不需要编辑器内核，装饰层的复杂度远高于自己切区间。

### 7.2 `<mark>` 元素契约

```html
<mark
  :data-thread-id="threadId"
  :data-severity="severity"
  :data-thread-status="status"
  :class="annotationClass(kind, severity, status)"
  role="button"
  tabindex="0"
  :aria-label="t('knowledge.blueprints.annotation.markLabel', { count, kind })"
  data-testid="blueprint-annotation-mark"
  @click="emit('thread-click', threadId)"
  @keydown.enter.prevent="emit('thread-click', threadId)"
  @keydown.space.prevent="emit('thread-click', threadId)"
>{{ segment }}</mark>
```

`<mark>` 的浏览器默认黄底必须被重置（`background: transparent` 起手），颜色一律由 §7.5 的令牌类给出。

### 7.3 越界与失锚的**两种不同**降级（不得混为一谈）

| 情形 | 判定方 | 呈现 |
|------|--------|------|
| **前端越界降级** | 前端：offset 非整数 / 越界 / `start >= end` / block 类型为 `table` 或 `mermaid`（不做字符级切分） | 该块渲染**整块左侧色条**（`border-l-2` + 对应色 + `pl-3`），块右上角一个 `icon-[lucide--message-square-dot]` 计数角标；侧栏该条目附一行小字「无法精确定位到原文片段，已标注整块」 |
| **后端失锚** | 后端：`anchor_status === 'orphaned'`（`areanchor_threads` 判定） | 正文**完全不渲染**任何标记（原文已不存在）；线程只出现在侧栏「失锚批注」分组，条目展示 `anchor.quoted_text` 快照 + 「原文已变更，无法定位」说明，**且仍可回复 / 处置** |

**`orphaned_threads` 直接渲染，前端不再二次过滤** —— 114-REVIEW MJ-02 已保证里面只有真失锚（`_has_anchor_locator` 前置，无定位的系统线程判 `skipped` 而非 `orphaned`）。前端再过滤只会把真失锚也滤掉。

### 7.4 选区 → 评论（CLAR-01 后半句）

1. 在正文容器上监听 `selectionchange`（`@vueuse/core` 的 `useDebounceFn` 120ms 去抖）。
2. 选区必须**完全落在同一个 `[data-block-id]` 子树内**；跨块选区 → 不弹 popover，改在顶部 toast 提示 `t('knowledge.blueprints.selection.crossBlock')`。
3. 计算 `start_offset` / `end_offset`：以该 block 的 `textContent` 为坐标系（`Range` 的 `startContainer/startOffset` → 用 `TreeWalker` 累加前序文本节点长度）。`quoted_text` = 选中原文（**上限 500 字符，超出截断并在提交时保留前 500**）。
4. `@floating-ui/vue` 的 `useFloating`（`placement: 'top'`、`offset(8)`、`flip()`、`shift({padding: 8})`）浮出 `BlueprintSelectionPopover.vue`：一个「发起评论」按钮 + 一个「复制原文」按钮。
5. 点击「发起评论」→ 右栏（窄屏 `Sheet`）顶部插入一张**草稿线程卡**（`textarea` 聚焦 + 引文预览），提交走 §3.5 的 `POST threads/`。
6. **`readonly === true`（`current_status` ∉ 可编辑白名单）时，popover 的「发起评论」按钮不渲染**（只留「复制原文」）。

### 7.5 颜色令牌（`web/src/components/blueprint/annotationTokens.ts` 单一来源）

底纹一律为对应色相的低透明度叠加（白底上），文字保持 `text-foreground`（`hsl(215 28% 17%)`），保证正文对比度 ≥ 10:1；下划线为 2px `border-bottom`（飞书式）。

| 语义 | 下划线色（≥3:1 vs 白，WCAG 1.4.11 非文本对比） | 底纹 |
|------|---------------------------------------------|------|
| `ai_review_finding` · `blocker` | `hsl(0 72% 45%)` ≈ #c62828 · **5.9:1** | `hsl(0 72% 51% / 0.12)` |
| `ai_review_finding` · `warning` | `hsl(26 90% 37%)` = #b45309（`main.css` 已用于 `.btn-warning:hover`） · **4.6:1** | `hsl(38 92% 50% / 0.12)` |
| `ai_review_finding` · `info` | `hsl(215 16% 40%)` slate · **6.4:1** | `hsl(215 16% 47% / 0.10)` |
| `ai_clarification` | `hsl(167 76% 32%)` = `--color-primary-600` #0d9488 · **3.5:1** | `hsl(168 76% 42% / 0.12)` |
| `human_comment` | `hsl(263 70% 50%)` = #7c3aed（`main.css` 已用于 `.stat-icon-violet`） · **6.5:1** | `hsl(263 70% 50% / 0.10)` |
| `repo_confirmation` | `hsl(167 76% 32%)` 同澄清 | `hsl(168 76% 42% / 0.12)`，另加 `icon-[lucide--shield-check]` 前缀 |

**⛔ 不使用 `--color-primary` 原值 `hsl(168 76% 42%)`（#14b8a6）作下划线**：它在白底上只有 **2.29:1**，不满足 WCAG 1.4.11 的 3:1 非文本对比。teal 必须降一档到 `--color-primary-600`。同理 amber `hsl(38 92% 50%)`（2.15:1）只能作底纹，不能作描边。

**状态叠加（正交于色相）：**

| `status` | 描边 | 底纹 | 默认可见性 |
|----------|------|------|-----------|
| `open` | 2px `solid` | 满档（上表值） | 常显 |
| `answered` | 2px `dashed` | 上表值 × 0.6 | 常显 |
| `resolved` | 1px `dotted`，色改 `hsl(215 16% 47%)` | 无 | **默认隐藏**，顶栏「显示已关闭批注」开关打开后可见 |
| `dismissed` | 同 `resolved` | 无 | 同上 |
| `orphaned` | —— | —— | 正文不渲染（§7.3） |
| **选中态**（`activeThreadId` 命中） | 描边加粗到 3px + `outline: 2px solid hsl(168 76% 42% / 0.5); outline-offset: 1px` | 底纹 × 1.4（封顶 0.20） | —— |

四档色相 + 一档灰，**均取自 `main.css` 既有色值或其暗一档**，不引入新色相 —— 与 `web/DESIGN.md`「禁彩虹卡片」不冲突：这些是**语义色**（严重级/种类的功能编码），不是装饰色，且集中在一个令牌模块内。

### 7.6 正文 ↔ 侧栏双向同步（`useBlueprintAnnotations.ts`）

单一状态源：`activeThreadId: Ref<string | null>`。

| 触发 | 行为 |
|------|------|
| 点击正文 `<mark>` | 设 `activeThreadId` → 侧栏该条 `scrollIntoView({ block: 'nearest', behavior: 'smooth' })` + 展开其所在分组 + 卡片 ring 高亮；窄屏同时打开 `Sheet` |
| 点击侧栏线程卡 | 设 `activeThreadId` → 正文 `document.getElementById('blk-'+blockId)` 滚动（偏移 88px，与 `AnchorNavLayout` 一致）+ `<mark>` 进入选中态；失锚线程**不滚动**，只在卡内展开 `quoted_text` 快照 |
| `?thread=` 深链 | 挂载后（线程数据就绪）执行一次「点击侧栏条目」的等效动作，并从 URL 移除该 query（`router.replace`），避免刷新反复跳 |
| 一个 `<mark>` 覆盖多条线程 | 点击弹出微型 `Popover` 列出这几条（每条一行：severity 点 + kind + 首条消息前 40 字），选一条后再设 `activeThreadId` |

### 7.7 线程侧栏 —— `BlueprintThreadSidebar.vue`

**分组（四组，`Collapsible`，组头带计数）：**

| 组 | 判据 | 默认 |
|----|------|------|
| 未决 | `status === 'open'` | 展开 |
| 已回答 | `status === 'answered'` | 展开 |
| 已关闭 | `status ∈ {resolved, dismissed}` | 折叠 |
| 失锚批注 | `anchor_status === 'orphaned'`（**直接取快照的 `orphaned_threads`**，跨越上面三组独立成组） | 折叠，但计数 > 0 时组头标 `variant="warning"` |

**组内排序**：severity（`blocker` → `warning` → `info` → 无）→ `created_at` 升序。

**顶部工具条**：`kind` 多选筛选 chips（AI 提问 / AI 审查 / 人工评论 / 确认门）+「显示已关闭批注」开关（与 §7.5 联动）。

### 7.8 ⛔ 线程动作按 `kind` **硬分流**（来自 114-REVIEW CR-01，本相位最不能错的一条）

**分流做在渲染层 —— 压根不给错的入口 —— 而不是提交层按 kind 切端点。**

| `kind` | 侧栏渲染的动作 | 端点 |
|--------|---------------|------|
| `ai_review_finding` | **不渲染「回复」输入框**。只给两个按钮：「已修复」/「误报忽略」，各自弹出**必填 `reason`** 的确认框 | `threads/<id>/resolve/` · `threads/<id>/dismiss/` |
| `ai_clarification` | 回复输入框 + `options` 候选选项（有 `options` 时渲染为可点选项组，点选即填入输入框，仍可改写后再提交） | `threads/<id>/answer/` |
| `human_comment` | 回复输入框 | `threads/<id>/answer/` |
| `repo_confirmation` | 回复输入框 + 一条指向 `BlueprintGatePanel` 的「前往确认门」链接 | `threads/<id>/answer/` |

**理由（不可妥协）**：114 对 finding 走 `answer` 通道**一律 400**，且回灌链 `REFLOW_KINDS` fail-closed 过滤。UI 若给统一输入框再按 kind 切端点，必然稳定撞 400 或误处置。
**`reason` 弹窗**：`BlueprintFindingActions.vue` 内的受控 `Dialog`（不是 `useConfirmDialog`，因为需要输入框）。空白/纯空格 → 提交按钮 `disabled` + 输入框下方 `text-destructive` 提示。后端把结论写成 `[已修复|误报忽略] {reason}（处置人：{uid}）`，前端在提交成功后重取线程即可看到该条消息，**不自行拼装该文本**。

### 7.9 `readonly` 白名单（114-REVIEW MJ-04 前置到 UI）

```ts
// web/src/config/blueprintStatus.ts
export const EDITABLE_BLUEPRINT_STATUSES = new Set(['', 'researching', 'drafting', 'ai_reviewing', 'needs_clarification', 'pending_review'])
export function isBlueprintEditable(status: string): boolean { return EDITABLE_BLUEPRINT_STATUSES.has(status) }
```

`isBlueprintEditable(current_status) === false` 时（即 `confirmed` / `implementing` / `implemented` / `archived` / `superseded` / `failed`）：

- **「编辑 block」入口与澄清作答输入框一律不渲染 —— 是「不存在于 DOM」，不是 `disabled`。**
- 选区 popover 的「发起评论」按钮不渲染。
- 在正文顶部渲染一条常驻 `Alert` 条：`t('knowledge.blueprints.readonly.notice')` = 「已确认的蓝图不可直接改写，要改请先驳回」。
- **finding 处置（resolve/dismiss）不受该闸约束**（后端未对其加状态闸，且那是死锁出口）。

---

## 8. 状态矩阵（加载 / 生成中 / 空 / 错误）

### 8.1 四态呈现

| 态 | 判据 | 呈现 |
|----|------|------|
| **首屏加载** | `docQuery.isLoading` | 顶栏骨架（标题条 + 徽标条）+ 左栏 6 条 `Skeleton h-8` + 正文 3 个段骨架。用 `~/components/ui/skeleton` |
| **生成中（按段增量）** | `current_status ∈ {researching, drafting, ai_reviewing}` 且该段在 content 中缺失/为空数组 | **该段渲染骨架屏 + 一行进度文案；已产出的段立即实渲**（SC-1 字面要求：增量填充，**不做全页 loading**）。进度文案取该段最近一条 `blueprint_*` 事件的中文映射（如 `blueprint.repo_research.started` → 「正在调研 {repository_name}…」），无事件时回落状态文案（「调研中…」/「起草中…」/「AI 审查中…」） |
| **空** | 段存在但条目数为 0，且**不在**生成中状态 | `CompactEmptyState`（复用 `~/components/common/CompactEmptyState.vue`），图标 + 一句「本方案未涉及{段名}」。**不显示「加载失败」**——空是合法结果 |
| **错误** | 见 §8.2 | `BlueprintErrorState.vue` |

段骨架形状（按段差异化，不用统一矩形）：
- 仓库关联 / API 契约：2 张 `h-40 rounded-xl` 卡骨架（`lg:grid-cols-2`）。
- 现状分析 / 实现概述：1 条 `h-5 w-40` 组头 + 3 条 `h-16` 行。
- 影响范围：表头条 + 4 行 `h-9`。
- 交互流程：1 张 `h-56` 图区 + 表头条 + 3 行。

### 8.2 错误分档（**全部读 `ApiError.status` / `.detail` / `.body`**，`~/api/client.ts` 已提供三者）

| 码 | 触发 | 呈现契约 |
|----|------|---------|
| **404** | artifact 不存在 **或** 调用者非蓝图所属项目成员 | **一律渲染同一句中性文案**：`t('knowledge.blueprints.error.notFoundOrForbidden')` = 「无权访问或该蓝图不存在」。⛔ **前端不得把 404 翻译成两种文案**（多一句「该蓝图不存在」就把 MJ-03 刻意不泄露存在性的闸门破了）。页面渲染全页 `CompactEmptyState`（图标 `icon-[lucide--lock]`）+「返回知识库」按钮，**不渲染任何蓝图元信息** |
| **409 · approve `blocked`** | 存在未决 BLOCKER finding | `Dialog` 形态的「不可确认」面板：一句说明 + **`unresolved_blocker_thread_ids` 逐条渲染成可点击条目**（显示 severity 点 + finding 首行摘要），点击 = 关闭 Dialog → 打开侧栏 → 选中该线程 → 正文滚动定位。⛔ **只显示一句「不可确认」即视为不合格**——那份清单是超界死锁的唯一解药入口（114-05 原话） |
| **409 · approve `conflict`** | CAS 冲突 / 非法边 | Toast `variant="destructive"` + 回显 `detail` + 「刷新重试」按钮（触发 `invalidateQueries`） |
| **409 · reject `conflict`** | 版本已落但 CAS 冲突（响应体带 `version_no`） | Toast 回显 `detail` + 「当前版本已到 v{version_no}，请刷新后重试」，并自动 `invalidateQueries(['blueprint'])` |
| **400** | `invalid` / ops 非法 / body 空 / finding 走 answer / 蓝图不可编辑 | **原样回显后端 `detail`**（`ApiError.detail`），不自行改写；就近渲染（表单内联错误优先于 toast） |
| **401 / 403** | 未登录 / 全局禁止 | 交由 `api/client.ts` 既有机制（自动刷新 / `auth:forbidden` 事件），本相位零处理 |
| **5xx / 网络** | —— | `BlueprintErrorState` 全页 + 「重试」按钮（`refetch()`），文案 `t('knowledge.blueprints.error.unavailable')` |

**answer 端点的特殊纪律**：无论 `reflow.status` 为何，端点**恒 200**。前端据 `reflow.status` 给差异化 toast，**绝不当作失败**：
`applied` → 成功 toast「答案已回灌，已产出 v{version_no}」并重取正文；`unchanged`/`noop` → info toast「答案已记录，本次未产生新版本」；`conflict` → warning toast + 列出 `conflict_block_ids`；`failed`/`invalid` → warning toast「答案已保存，回灌未成功，可稍后重试」。

### 8.3 实时进展 —— `useBlueprintLive.ts`（**唯一轮询消费点**）

```ts
export function useBlueprintLive(artifactId: Ref<string>, currentStatus: Ref<string>) {
  const LIVE_STATUSES = new Set(['researching', 'drafting', 'ai_reviewing'])
  const isLive = computed(() => LIVE_STATUSES.has(currentStatus.value))
  const refetchInterval = computed(() => (isLive.value ? 5_000 : false))
  // events / snapshot / doc 三个 query 共用同一个 refetchInterval
  // …
  return { isLive, events, stageTimeline, sectionProgress }
}
```

- **只在 `researching` / `drafting` / `ai_reviewing` 三态开启轮询**；进入人审态（`pending_review`）与任一终态自动停。节奏对齐既有 `composables/usePolling.ts` 惯例（2s 是日志级，蓝图阶段级取 **5s**）。
- **⛔ 绝不新建推送通道**：`ConvergenceSessionEvent` 全仓既无 REST 也无 WS；唯一现成 WS 是 `ws/projects/{id}/`，用它就必须在蓝图 stage handler 里新增 emit —— 那是往 §13.2 受限面上加推送侧写，且事件时间线契约归属 v0.19.0 Phase 110（同步点 2 才成立）。
- **同步点 2 之后**若 0.19 的推送契约就位，**只改这一个文件**（把 `refetchInterval` 换成订阅）。这是本相位对并行纪律最实际的交代 —— 因此 `refetchInterval` 字面量**不得**出现在任何组件里。
- 页面不可见时暂停：`useDocumentVisibility()` 为 `hidden` 时 `refetchInterval = false`。

### 8.4 阶段时间线 —— `BlueprintStageTimeline.vue`

视觉范式对齐 `~/components/repository/IndexProgressTimeline.vue`。消费 §3.2 的事件流，按 stage 聚合成节点（`spec_gate` → `route` → `repo_research` → `confirmation` → `repo_plan` → `merge` → `ai_review` → `pending_review`），每节点三态（未开始 `muted` / 进行中 `info`+`animate-spin` / 完成 `success` / 失败 `destructive`）。节点可展开看该 stage 下的原始事件行（`event` 中文名 + `ts` + payload 的标量键值）。

**不呈现「人审驳回导致的会话复位」** —— 该动作当前无事件常量（114-REVIEW 可再议项），同步点 2 后与 0.19 的时间线契约一并定。

---

## 9. 版本切换与 block 级 diff

### 9.1 版本切换器 —— `BlueprintVersionSwitcher.vue`

数据源：`deliveryArtifacts.getArtifactTimeline(artifactId)`（**零新端点**）。顶栏一个 `Select`/`Popover` 列表，每行：`v{version_no}` + 当前徽标 + 版本原因徽标 + 相对时间。

**版本原因由 `produced_by_ref` 四前缀映射（唯一判据）：**

| 前缀 | 徽标文案 | variant | 图标 |
|------|---------|---------|------|
| `human_edit:` | 人工编辑 | `secondary` | `icon-[lucide--user-pen]` |
| `ai_review_reflow:` | 澄清回灌 | `info` | `icon-[lucide--refresh-cw]` |
| `human_block_restore:` | 人工块保护 | `warning` | `icon-[lucide--shield]` |
| `blueprint_review_reject:` | 人审驳回 | `destructive` | `icon-[lucide--undo-2]` |
| 其余 | AI 产出 | `muted` | `icon-[lucide--sparkles]` |

切换版本 = 改 `?version=`；非 current 版本时正文顶部常驻一条 `Alert`：「正在查看历史版本 v{n}，操作已禁用」+「回到当前版本」按钮，且**所有写动作（作答/编辑/处置/终审/确认门）在此模式下不渲染**。

### 9.2 block 级 diff —— `BlueprintBlockDiff.vue`

**diff 在前端算，不为 diff 新增后端端点**（111 的 `diff_blueprint_blocks` 是服务端纯函数，为它开 REST 属净新增面，且与「前端两版都在手」的现实重复）。

```
输入：contentA（基线）、contentB（目标）——各经 §3.1 端点带 version_id 取回
1. 用与 iter_blocks 等价的前端走查（web/src/utils/blueprintBlocks.ts）拿到 (sectionPath, block)[]
2. 按 block_id 建索引：
   - 仅在 B 中 → added
   - 仅在 A 中 → removed
   - 两者都有且规范化 JSON 不等 → modified
3. modified 的块内文本用 diff 包的 diffWords 求词级 Change[]
```

**呈现**（视觉与颜色令牌逐字对齐 `PromptVersionDiff.vue` 的 `.diff-added / .diff-removed / .diff-unchanged`）：

| 项 | 契约 |
|----|------|
| 默认形态 | **单栏 inline**：`added` 块整块绿底 + 左边框；`removed` 块整块红底 + 左边框 + 内容 `line-through` 弱化；`modified` 块内 `diffWords` 结果逐段着色 |
| 可切换 | 左右并排（`?diff_mode=split`），左栏基线视角（unchanged + removed），右栏目标视角（unchanged + added） |
| 颜色 | `.diff-added` `background: hsl(142 71% 45% / 0.12); color: hsl(142 71% 20%); border-left: 3px solid hsl(142 71% 45%)`；`.diff-removed` `background: hsl(0 72% 51% / 0.1); color: hsl(0 72% 30%); border-left: 3px solid hsl(0 72% 51%)` —— **逐字沿用 `PromptVersionDiff.vue`** |
| 摘要 | 顶部一行 `aria-live="polite"`：「v{a} 对比 v{b}：新增 {n} 块、删除 {n} 块、修改 {n} 块」 |
| 段分组 | diff 结果按段分组呈现，未变化的段整段折叠（组头显示「本段无变化」） |
| 性能 | `shallowRef<Change[]>` 存 diff 结果（抄 `PromptVersionDiff.vue`），避免深响应式 |
| 安全 | 全程 mustache + `<pre>`，**禁 `v-html`**（XSS 面 = 0） |
| diff 模式下 | 批注层与所有写动作**关闭**（diff 是纯对照视图） |

---

## 10. 引用二级预览（VIEW-02）

### 10.1 `CitationPreviewDialog.vue`

单一受控 `Dialog`（`~/components/ui/dialog` 的 `Dialog` + `DialogScrollContent`，范式即 `pages/knowledge/index.vue` 的工件查看弹窗）。**它是第一层 Dialog，无嵌套**（因为查看器是路由页）。

尺寸 `class="w-[92vw] max-w-4xl"`，内容区 `max-h-[72vh] overflow-auto`。头部：`source_type` 徽标 + `title` 快照 + 右上「在新页面打开」（若该来源有独立路由）。

**按 `source_type` 分发到已有读取面（不为每类新建端点）：**

| `source_type` | 读取 | 子组件 | 渲染 |
|---------------|------|--------|------|
| `knowledge_entity` | `knowledgeApi.getEntity(source_id)` | `CitationKnowledgePreview.vue` | 元数据卡 + 正文（`MarkdownRenderer`）+「在知识库中打开」 |
| `repo_file` / `rag_chunk` | `GET /api/repositories/{repo}/chunk-at/?path={locator.file_path}&line={locator.line_start}` | `CitationCodePreview.vue` | CodeMirror **只读**实例（`fridayLightTheme`）+ **行高亮** `locator.line_start..line_end` + 文件路径面包屑 + 复制。命中多个 chunk 时取第一个并给「共 {n} 个片段」提示 |
| `repo_charter` | `GET /api/repositories/{repo}/charter/` | `CitationCharterPreview.vue` | 定位 / owned_domains / boundaries / 落点偏好分区；`locator` 指向某条时该条 ring 高亮 |
| `blueprint` / `artifact_version` | §3.1 端点（带 `version_id`） | `CitationBlueprintPreview.vue` | **迷你只读渲染**：只渲染 `meta.title` + `meta.summary` + 被引段的对应块（`readonly`、无批注层、无操作栏）+「打开完整蓝图」 |
| `work_item` / `feishu_doc` / `url` | 不请求 | —— | 直接 `<a target="_blank" rel="noopener noreferrer">` 新标签打开；Dialog 不弹（chip 本身就是 `<a>`） |

**兜底不留白（强制）**：任何来源取不到（404 / 5xx / 网络）时，**渲染 citation 自带的 `title` / `quote` 快照** + 一行 `text-muted-foreground`「原始来源不可达，以下为引用时的快照」。⛔ 不渲染空白弹窗，不把 Dialog 直接关掉。

### 10.2 「关联」区（SC-4 双向可查）

查看器最后一段 `associations`，由 `BlueprintAssociationsSection.vue` 渲染，三块：
- **本蓝图引用了**：`citations` 引用池按 `source_type` 分组统计 + 可点 chip（走同一预览弹层）。
- **引用了本蓝图 / 关联知识**：`knowledgeApi.getRelated` + `knowledgeApi.getArtifactAssociations`（复用，零新端点）。
- **关联项目**：项目名 + `RouterLink` 到项目页。

---

## 11. 人审终审（FLOW-08）与确认门

### 11.1 终审操作区 —— `BlueprintReviewActions.vue`

**位置与视觉分离（防误触第一层）**：顶栏**最右侧**独立区块，与左侧阅读/编辑动作之间用 `Separator`（`~/components/ui/separator`）+ `ml-auto` 隔开，容器 `pl-4 border-l border-border`。

| 按钮 | 样式 | 可用性 |
|------|------|--------|
| 通过 | `<Button variant="default">` + `icon-[lucide--check-circle]` | 仅 `current_status === 'pending_review'` 时可用 |
| 驳回 | `<Button variant="destructive">` + `icon-[lucide--undo-2]` | 同上 |

**可用性由 `current_status` 驱动**：非 `pending_review` 一律 `disabled` **并**用 `Tooltip` 给出原因（`t('knowledge.blueprints.review.disabledReason', { status: 状态中文名 })`，如「当前状态为『AI 审查中』，需等待进入待人类审查」）。⚠️ 这里是 `disabled` + tooltip，与 §7.9 的「不渲染」不同：终审按钮的存在本身是有信息量的（告诉人「这里将来能做什么」），而可编辑闸拦的是会撞 400 的写路径。

**二次确认（防误触第二层）**：
- **通过**：`useConfirmDialog().confirm({ title: '确认通过该技术方案？', description: '通过后蓝图状态变为「已确认」，你将被记入本方案的评审人名单，且蓝图不可再直接改写。', confirmText: '确认通过', variant: 'default' })`。
- **驳回**：**不走** `useConfirmDialog`（需要输入框），走 `BlueprintRejectDialog.vue` 受控 `Dialog`：
  - `comment` **必填非空**（可预填选区评论，也可在弹窗内直接写）；空/纯空格 → 提交按钮 `disabled` + 内联 `text-destructive` 提示。
  - 可选「关联到某条划线」：若用户此前有选区，弹窗顶部显示引文预览与「保留此划线」开关（勾选则带 `anchor` 提交）。
  - 弹窗底部常驻提示：「驳回后蓝图回到『产出中』，修订轮次将变为 {revision_round + 1}」。
  - 主按钮 `variant="destructive"`，文案「确认驳回」。

**成功后**：以响应体 `current_status` 为准更新展示，`invalidateQueries(['blueprint'])` 重取；成功 toast 分别为「已通过，蓝图进入『已确认』」/「已驳回，蓝图回到『产出中』（第 {revision_round} 轮修订）」。**不做乐观更新。**

### 11.2 质量面板 —— `BlueprintQualityPanel.vue`（闭 114-REVIEW MN-05）

仅在 `current_status ∈ {pending_review, confirmed}` 时渲染于正文尾部。四个指标格：

| 指标 | 有值 | `null` |
|------|------|--------|
| 引用覆盖率 | `{(v*100).toFixed(1)}%` | 「暂无数据」 |
| AI 打回率 | `{(v*100).toFixed(1)}%` | 「暂无数据」 |
| 人审修改量 | `{v} 次人工编辑` | 「暂无数据」 |
| 澄清轮次 | `{v} 轮` | 「暂无数据」 |

⛔ **绝不把 `null` 显示成 0** —— 那正是 114-05 三态并列用例要防的口径事故。指标格用 `text-muted-foreground` 呈现「暂无数据」，数值用 `text-2xl font-semibold text-foreground`。

### 11.3 确认门 —— `BlueprintGatePanel.vue`（范围增量，可顺延）

> **显式登记这是相对 ROADMAP SC 的范围增量**：112 只交付后端，全仓零前端 ⇒ 不做则 FLOW-03 在 UI 上**不可达**，用户永远走不到 113 的阶段 2，整条链在界面上断在第一关。
> **范围控制**：若 plan-checker 判定超载，拆成本相位**最后一个可独立顺延的 plan**（顺延目标 116），**不得**混进查看器主干 plan，更**不得**默默丢掉。

渲染条件：`GET blueprint-gate/` 返回 200（门已开）。404「确认门未开启」= 正常态，不渲染面板、不报错。

面板结构：顶部说明条（「确认仓库集与职责后才进入方案拟定；确认后锁定，后续变更须重开确认门」）+ 仓库行列表（`BlueprintGateRepoRow.vue`）+ 底部主操作。

| 动作 | 交互 | 端点 |
|------|------|------|
| 移除仓 | 行内「移除」→ `useConfirmDialog`（`variant: 'destructive'`） | `remove-repo/` |
| 手动加仓 | 底部「添加仓库」→ 复用 `~/components/workflow/RepositoryPicker.vue` | `add-repo/` |
| 改判 role | 行内 direct/indirect 二选一 segmented control（即时提交） | `reclassify-role/` |
| 修改职责 | 行内「编辑职责」→ 小 `Dialog` + `Textarea` | `edit-responsibility/` |
| 升级深调研 | 行内（`indirect` 仓）「升级为深调研」，带「重新调研该仓」勾选（`{rerun: true}`） | `upgrade-research/` |
| rejected 沉淀禁区 | 面板底部次级动作「把被否决的候选沉淀为章程禁区」 | `rejected-to-boundary/` |
| **确认锁定** | 底部主按钮，`useConfirmDialog` 二次确认（`description` 含「确认后锁定，后续变更必须重开确认门」） | `confirm/` |

**七个动作统一范式**：一次 POST + 重取快照（`invalidateQueries(['blueprint','gate',artifactId])` + `['blueprint','snapshot']`），与人审操作栏共用同一「动作条 + 二次确认」范式。
`pending_research_repository_ids` 命中的行显示 `icon-[lucide--loader-2] animate-spin` + 「调研中」，且该行动作 `disabled`；确认主按钮在存在 pending 时 `disabled` + tooltip 回显后端 `_LOCK_BLOCKED_MESSAGES` 语义（「有仓库正在调研，暂不能确认」）。
`confirm/` 的 **409**：`blocked_reason === 'pending_clarification'` → 提示「存在未解决的阻塞澄清线程」+ 一键跳侧栏未决组；其余 409 回显 `detail` + 刷新重试。

---

## 12. 知识库 tab 与项目关联（VIEW-03 / VIEW-04）

### 12.1 `BlueprintsTabPanel.vue`

```
FilterBar：[搜索框 q] [状态 Select（11 态 + 全部）] [项目 Select] [仓库 Select] (清除)
  ↓
BlueprintListCard × N（grid gap-3 sm:grid-cols-2 lg:grid-cols-3）
  ↓
Pagination（~/components/ui/pagination）
```

- 筛选栏复用 `~/components/common/FilterBar.vue`（`web/DESIGN.md` 指定的标准容器），`showClear` 由「是否有任一筛选生效」驱动。
- 搜索：输入框当前值与「已提交」查询词分离，**仅回车/点按钮才提交**（抄 `pages/knowledge/index.vue` 的 `queryInput` / `submittedQuery` 范式，避免输入即请求）。
- 所有筛选与分页与 URL query 双向同步（§4.2），刷新可复现。
- 加载：`Skeleton h-32 rounded-2xl × 6` 网格。空态：`CompactEmptyState`（图标 `icon-[lucide--file-x]`，标题「没有匹配的技术方案」，描述「换个筛选条件，或在项目里发起一次方案编排」）。

**`BlueprintListCard.vue`**（`.card .card-interactive`，整卡是 `RouterLink to="/knowledge/blueprints/{artifact_id}"`）：

```
┌────────────────────────────────────────┐
│ [11态徽标]  标题（truncate 2 行）        │
│ 摘要（text-xs muted，clamp 2 行）        │
│ 📁 项目名   ·  v{n}  ·  第 {r} 轮修订    │
│ [仓库 chip × ≤3] +{n}                   │
│ 💬 {thread_count}  ⛔ {blocker_count}    │  ← blocker_count > 0 时红色，= 0 时不渲染
│ 更新于 {相对时间}                        │
└────────────────────────────────────────┘
```

### 12.2 项目物料卡 —— `ProjectBlueprintsCard.vue`

- **新建组件**，挂进 `ProjectMaterialsPanel.vue` 的扁平分区流（该文件用 `defineAsyncComponent` 懒加载各分区，追加一行 import + 一处使用 —— 属新增组件而非改造既有组件的语义）。
- 只读：列该项目的蓝图（`GET /delivery/blueprints/?project_id={id}`）+ 11 态徽标 + 更新时间 + 跳查看器。
- 分区头范式沿用该面板既有的 `.flat-section` / `.flat-header` + `section-chip`。
- 无数据时**整块不渲染**（对齐 `HumanTaskInbox` 的 `hide-when-empty` 习惯，空项目不突兀）。

---

## 13. 组件清单（全部新建，文件路径逐字）

### 13.1 页面与容器

| 文件 | 职责 | 组合自 |
|------|------|--------|
| `web/src/pages/knowledge/blueprints/[id].vue` | 查看器路由页；query↔ref 同步、三栏编排、所有 query 装配、错误分档路由 | `PageContainer`、`AnchorNavLayout`、`ui/sheet`、`ui/skeleton` |

### 13.2 查看器骨架

| 文件 | props / emits | 组合自 |
|------|---------------|--------|
| `components/blueprint/BlueprintViewerHeader.vue` | `props: { doc, snapshot, counts, versions, readonly, isLive }`；`emits: ['toggle-sidebar','change-version','open-diff','approve','reject','toggle-closed-annotations']` | `ui/badge`、`ui/tooltip`、`ui/separator`、`BlueprintStatusBadge`、`BlueprintVersionSwitcher`、`BlueprintReviewActions` |
| `components/blueprint/BlueprintStatusBadge.vue` | `props: { status: string, size?: 'sm'\|'md'\|'lg', showIcon?: boolean }` | `ui/badge` + `config/blueprintStatus.ts` |
| `components/blueprint/BlueprintStageTimeline.vue` | `props: { events, currentStage, currentStatus }` | `ui/collapsible`、`ui/badge` |
| `components/blueprint/BlueprintSectionNav.vue` | `props: { sections: NavSection[] }`；`emits: ['navigate']`；窄屏渲染 `Select` | `AnchorNavLayout`（≥md）+ `ui/select`（<md） |
| `components/blueprint/BlueprintErrorState.vue` | `props: { status: number, detail: string }`；`emits: ['retry']` | `CompactEmptyState`、`ui/button` |

### 13.3 内容渲染

| 文件 | props / emits |
|------|---------------|
| `components/blueprint/BlueprintBlock.vue` | 见 §6.2（**批注 + 引用的唯一实现点**） |
| `components/blueprint/BlueprintBlockList.vue` | `props: { blocks, sectionPath, threads, citations, readonly, activeThreadId, loading }`；透传 `BlueprintBlock` 的全部 emits；`loading` 时出该段骨架 |
| `components/blueprint/BlueprintCitationChip.vue` | `props: { citation: Citation, index: number }`；`emits: ['click']` |
| `components/blueprint/sections/RequirementSpecSection.vue` | `props: { spec, ...blockCtx }` |
| `components/blueprint/sections/RepoAssociationsSection.vue` | `props: { associations, ...blockCtx }` |
| `components/blueprint/sections/CurrentStateSection.vue` | `props: { analysis, repoNames, ...blockCtx }` |
| `components/blueprint/sections/ImplementationOverviewSection.vue` | `props: { overview, ...blockCtx }` |
| `components/blueprint/sections/ApiContractsSection.vue` | `props: { contracts, ...blockCtx }` |
| `components/blueprint/sections/ImpactAnalysisSection.vue` | `props: { impact, ...blockCtx }` |
| `components/blueprint/sections/InteractionFlowsSection.vue` | `props: { flows, ...blockCtx }` |
| `components/blueprint/sections/DecisionLogSection.vue` | `props: { decisionLog }`；`emits: ['open-thread']` |
| `components/blueprint/BlueprintAssociationsSection.vue` | `props: { artifactId, citations }` |
| `components/blueprint/RepoAssociationCard.vue` | `props: { association, ...blockCtx }` |
| `components/blueprint/ImplementationItemCard.vue` | `props: { item, moduleName, repoName, ...blockCtx }` |
| `components/blueprint/ApiContractCard.vue` | `props: { contract, repoName, supportRepoName, ...blockCtx }` |
| `components/blueprint/ImpactMatrixTable.vue` | `props: { impact, repoNames, ...blockCtx }` |

> `blockCtx` = `{ threads, citations, readonly, activeThreadId }` 四个 prop 的简写，各段一律原样透传给 `BlueprintBlockList`，**不在段组件里自行处理批注**。

### 13.4 批注与线程

| 文件 | props / emits |
|------|---------------|
| `components/blueprint/BlueprintThreadSidebar.vue` | `props: { threads, orphanedThreads, activeThreadId, readonly, showClosed }`；`emits: ['select','answer','resolve','dismiss','create-comment']` |
| `components/blueprint/BlueprintThreadCard.vue` | `props: { thread, active, readonly }`；`emits: ['select','answer','resolve','dismiss']`。**按 `kind` 硬分流渲染动作（§7.8）** |
| `components/blueprint/BlueprintThreadComposer.vue` | `props: { options, submitting }`；`emits: ['submit']`。**仅非 finding 且 `!readonly` 时被渲染** |
| `components/blueprint/BlueprintFindingActions.vue` | `props: { threadId, submitting }`；`emits: ['resolve','dismiss']`。内含必填 `reason` 的受控 `Dialog` |
| `components/blueprint/BlueprintSelectionPopover.vue` | `props: { anchorRect, canComment }`；`emits: ['comment','copy','dismiss']` | 
| `components/blueprint/annotationTokens.ts` | 导出 `annotationClass(kind, severity, status, active)` 与 `ANNOTATION_PRIORITY`；§7.5 令牌的唯一来源 |

### 13.5 版本 / diff / 人审 / 确认门

| 文件 | props / emits |
|------|---------------|
| `components/blueprint/BlueprintVersionSwitcher.vue` | `props: { versions, currentVersionId }`；`emits: ['change','compare']` |
| `components/blueprint/BlueprintBlockDiff.vue` | `props: { baseDoc, targetDoc, mode: 'inline'\|'split' }`；`emits: ['update:mode']` |
| `components/blueprint/BlueprintReviewActions.vue` | `props: { currentStatus, revisionRound, submitting }`；`emits: ['approve','reject']` |
| `components/blueprint/BlueprintRejectDialog.vue` | `props: { open, revisionRound, presetAnchor }`；`emits: ['update:open','submit']` |
| `components/blueprint/BlueprintBlockedDialog.vue` | `props: { open, threadIds, threads }`；`emits: ['update:open','goto-thread']`（approve 409 的解药面板，§8.2） |
| `components/blueprint/BlueprintQualityPanel.vue` | `props: { quality }` |
| `components/blueprint/BlueprintGatePanel.vue` | `props: { artifactId, snapshot, submitting }`；`emits: ['action']` |
| `components/blueprint/BlueprintGateRepoRow.vue` | `props: { repo, pending, submitting }`；`emits: ['remove','reclassify','edit-responsibility','upgrade-research']` |

### 13.6 引用预览

| 文件 | props |
|------|-------|
| `components/blueprint/CitationPreviewDialog.vue` | `props: { open, citation }`；`emits: ['update:open']`；按 `source_type` 分发 |
| `components/blueprint/citation/CitationKnowledgePreview.vue` | `props: { entityId, fallback }` |
| `components/blueprint/citation/CitationCodePreview.vue` | `props: { repositoryId, locator, fallback }` |
| `components/blueprint/citation/CitationCharterPreview.vue` | `props: { repositoryId, locator, fallback }` |
| `components/blueprint/citation/CitationBlueprintPreview.vue` | `props: { artifactId, versionId, blockId, fallback }` |
| `components/blueprint/citation/CitationFallback.vue` | `props: { title, quote }` —— §10.1 的兜底不留白 |

### 13.7 知识库 / 项目侧

| 文件 | 说明 |
|------|------|
| `components/knowledge/BlueprintsTabPanel.vue` | tab 面板：筛选 + 列表 + 分页 |
| `components/knowledge/BlueprintListCard.vue` | 列表卡 |
| `components/project/warroom/ProjectBlueprintsCard.vue` | 项目物料只读卡 |

### 13.8 数据层与工具

| 文件 | 说明 |
|------|------|
| `web/src/api/blueprints.ts` | 五个新端点 + 复用端点的薄封装；barrel 追加到 `api/index.ts` |
| `web/src/api/repositoryChunks.ts` | `chunk-at` 与 `charter` 的前端封装（既有 REST，前端尚无 API 模块） |
| `web/src/types/blueprint.ts` | `BlueprintV1` / `BlueprintBlock` / `Citation` / `BlueprintThreadDetail` / `BlueprintStatus` 等 TS 类型 |
| `web/src/config/blueprintStatus.ts` | 11 态 `StatusConfig` 映射 + `EDITABLE_BLUEPRINT_STATUSES` + `isBlueprintEditable` + `PRODUCED_BY_PREFIXES` |
| `web/src/composables/useBlueprintLive.ts` | **唯一轮询消费点**（§8.3） |
| `web/src/composables/useBlueprintAnnotations.ts` | 线程按 block 分组、区间切分、正文↔侧栏同步（§7.1/§7.6） |
| `web/src/composables/useCitationPreview.ts` | 预览弹层的开关与 citation 装配 |
| `web/src/utils/blueprintBlocks.ts` | 前端版 `iter_blocks`（走查顺序与 `blueprint_schema.iter_blocks` 逐段对齐）+ diff 分类 |
| `web/src/stores/useBlueprintViewerStore.ts` | 客户端态：`sidebarCollapsed` / `showClosedAnnotations` / `kindFilters`（Pinia） |

### 13.9 11 态徽标配置（`config/blueprintStatus.ts` 逐字）

| status | label | icon | variant | animate |
|--------|-------|------|---------|---------|
| `researching` | 调研中 | `lucide--scan-eye` | `info` | ✓ |
| `drafting` | 产出中 | `lucide--pen-line` | `info` | ✓ |
| `ai_reviewing` | AI 审查中 | `lucide--shield-check` | `info` | ✓ |
| `needs_clarification` | 需要澄清 | `lucide--help-circle` | `warning` | |
| `pending_review` | 待人类审查 | `lucide--user-check` | `warning` | |
| `confirmed` | 已确认 | `lucide--check-circle` | `success` | |
| `implementing` | 实施中 | `lucide--hammer` | `info` | ✓ |
| `implemented` | 实施完成 | `lucide--check-check` | `success` | |
| `archived` | 已归档 | `lucide--archive` | `muted` | |
| `failed` | 已失败 | `lucide--x-circle` | `destructive` | |
| `superseded` | 已废弃 | `lucide--file-x` | `muted` | |
| `''`（v0 旧数据） | 旧版方案 | `lucide--file-text` | `outline` | |

新增的动态图标须追加进 `main.css` 的 `@source inline(...)`（这批经 `getBlueprintStatusConfig` 拼接，必须 safelist）。

---

## 14. Typography

沿用既有字号阶（`text-xs/sm/base/2xl`）。**声明 4 档 + 2 个字重。**

| Role | Size | Weight | Line Height | Tailwind |
|------|------|--------|-------------|----------|
| Label（徽标、元信息、chip、表头） | 12px | 400 / 500 | 1.4 | `text-xs` |
| Body（正文 Block、线程消息、卡片内容） | 14px | 400 | **1.6**（长文阅读，`leading-relaxed`） | `text-sm leading-relaxed` |
| Heading（段标题、卡片标题、面板标题） | 16px | 600 | 1.4 | `text-base font-semibold` |
| Display（页面 h1 蓝图标题） | 24px | 600 | 1.25 | `text-2xl font-semibold` |

**字重契约 = 400 regular + 600 semibold（两档）。**

**Exceptions（沿用既有，不得扩散）:**
- `font-bold`(700) 仅允许出现在**页面 h1**（`pages/knowledge/index.vue` 既有为 `text-2xl font-bold`；蓝图查看器 h1 与之对齐时可用），其余一律 600 封顶。
- Mono 正文：`pseudocode` 块、JSON 示例、diff 行、文件路径 —— 12px `font-mono leading-6`（与 `PromptVersionDiff.vue` 的 `text-xs leading-6` 一致）。
- `text-[11px]`：仅用于 citation chip 与 mermaid 容器条 —— 与 `MermaidDiagram.vue` / `AnchorNavLayout` badge 既有值一致，不得扩散到正文。

---

## 15. Color

| Role | Value | Usage |
|------|-------|-------|
| Dominant (60%) | `--color-background` `hsl(210 40% 98%)` slate-50 | 页面底色 |
| Secondary (30%) | `--color-card` `hsl(0 0% 100%)` 白 + `--color-border` `hsl(214 32% 91%)` hairline | 卡片、侧栏、顶栏、面板 |
| Accent (10%) | `--color-primary` `hsl(168 76% 42%)` teal-500 | **见下方 reserved-for 清单** |
| Destructive | `--color-destructive` `hsl(0 72% 51%)` | 仅危险动作 |

**Accent（teal）reserved for（穷举，不得扩散）:**
1. 主操作按钮：确认门「确认锁定」、人审「通过」、列表页「搜索」。
2. 左栏当前段的高亮条与文字（`AnchorNavLayout` 既有 `bg-primary/8 text-primary` + `w-0.5` 竖条）。
3. tab 选中态（`data-[state=active]:bg-primary`，`pages/knowledge/index.vue` 既有）。
4. `ai_clarification` / `repo_confirmation` 的划线色（降档到 `--color-primary-600`，§7.5）。
5. citation chip 的 hover 态描边与文字。
6. 卡片头图标芯片 `.section-chip`（既有）。
7. 焦点环 `outline: 2px solid hsl(168 76% 42% / 0.5)`（`main.css` 既有）。

**⛔ 不得**给不同段/不同卡片分配不同色相（`web/DESIGN.md`「禁彩虹卡片」）；徽标颜色一律通过 `<Badge variant="...">` 控制，**禁止在 Badge 上用 `:class` 追加颜色类**。

**Phase-Local 语义色（功能编码，非装饰）：** 批注四色（§7.5）+ diff 二色（§9.2）。两者都集中在单一模块（`annotationTokens.ts` / 复用 `PromptVersionDiff.vue` 的 `.diff-*`），组件内**不得**再写颜色字面量。

---

## 16. Copywriting Contract（zh-CN 定稿）

| Element | Copy |
|---------|------|
| 页面 CTA · 人审通过 | 通过方案 |
| 页面 CTA · 人审驳回 | 驳回修订 |
| 页面 CTA · 确认门 | 确认仓库集并进入方案拟定 |
| 页面 CTA · 选区评论 | 发起评论 |
| 页面 CTA · finding 处置 | 已修复 / 误报忽略 |
| 列表页 CTA | 搜索 |
| 空态 · 列表 | 标题「没有匹配的技术方案」／正文「换个筛选条件，或在项目里发起一次方案编排」 |
| 空态 · 某段无内容 | 「本方案未涉及{段名}」 |
| 空态 · 无批注 | 标题「暂无批注」／正文「AI 的划线提问与你的评论都会出现在这里；选中正文任意片段即可发起评论」 |
| 空态 · 失锚组 | 「没有失锚批注」 |
| 加载中 · 生成态 | 「调研中…」／「起草中…」／「AI 审查中…」（按段可覆盖为「正在调研 {repository_name}…」） |
| 错误 · 404 | **「无权访问或该蓝图不存在」**（唯一一句，⛔ 不得拆成两句） |
| 错误 · 409 approve blocked | 「还有 {n} 条阻塞级审查发现未处置，处置完成后即可通过」+ 可点清单 |
| 错误 · 409 conflict | 「方案已被其它操作更新，请刷新后重试」 |
| 错误 · 400 | 原样回显后端 `detail` |
| 错误 · 5xx/网络 | 「暂时读取不到该方案，请稍后重试」 |
| 只读提示 | 「已确认的蓝图不可直接改写，要改请先驳回」 |
| 历史版本提示 | 「正在查看历史版本 v{n}，操作已禁用」 |
| 失锚条目说明 | 「原文已变更，无法定位」 |
| 越界降级说明 | 「无法精确定位到原文片段，已标注整块」 |
| 引用兜底 | 「原始来源不可达，以下为引用时的快照」 |
| 指标无数据 | 「暂无数据」 |
| 破坏性确认 · 通过 | 标题「确认通过该技术方案？」／正文「通过后蓝图状态变为「已确认」，你将被记入本方案的评审人名单，且蓝图不可再直接改写。」／按钮「确认通过」 |
| 破坏性确认 · 驳回 | 标题「驳回该技术方案」／正文「驳回后蓝图回到「产出中」，修订轮次将变为 {n}。请写明驳回理由（必填）。」／按钮「确认驳回」 |
| 破坏性确认 · 移除仓 | 标题「从方案中移除该仓库？」／正文「移除后该仓的调研结论与职责将不再参与本方案，并可沉淀为仓库章程的边界禁区候选。」／按钮「确认移除」 |
| 破坏性确认 · 确认锁定 | 标题「确认仓库集并锁定？」／正文「确认后仓库集与职责被锁定，后续变更必须重开确认门。你将被记入本方案的评审人名单。」／按钮「确认锁定」 |
| 跨块选区提示 | 「评论只能针对同一段落内的文字，请缩小选区」 |

---

## 17. i18n

- **命名空间（本相位唯一新增顶层子树）**：`knowledge.blueprints.*`，写入 `web/src/locales/zh-CN.json` 的既有 `knowledge` 节（纯追加）。
- **tab 标题**：`knowledge.tabs.blueprints` = 「技术方案」（追加到既有 `knowledge.tabs` 对象）。
- **⛔ 不新增顶层节**、不修改 `knowledge` 下既有任何键。

子命名空间划分：

```
knowledge.blueprints.
  pageTitle / pageDescription
  tabPanel.*        列表页：筛选标签、搜索占位、结果计数、空态
  status.*          11 态中文名（与 config/blueprintStatus.ts 的 label 同源，配置里引 t() key）
  section.*         九段标题（requirementSpec / repoAssociations / … / associations）
  block.*           块级：复制、展开全部、语言标签、编辑
  repo.*            仓库关联卡：role/fitness/routing/openRepository/supportNeeded
  api.*             API 卡：direction/kind/availability/request/response/dataSource
  impact.*          影响矩阵：kind/level/dataMigration/rollback
  flow.*            交互流程：trigger/actor/steps/alternativePaths
  annotation.*      批注：markLabel/degraded/orphaned/selection/crossBlock
  thread.*          线程：分组名/kind 名/severity 名/composer 占位/options 提示/提醒信息
  finding.*         finding 处置：resolve/dismiss/reasonLabel/reasonRequired
  version.*         版本：切换/原因四前缀/历史版本提示/回到当前
  diff.*            diff：摘要/模式切换/无变化
  review.*          人审：approve/reject/disabledReason/确认弹窗全文
  gate.*            确认门：说明/七动作/pending/锁定确认
  quality.*         四项指标名 + noData
  citation.*        预览：各 source_type 名/open/fallback
  error.*           notFoundOrForbidden / blocked / conflict / unavailable
  readonly.notice
```

**纪律**：本相位**所有**用户可见文案走 `t()`，包括错误文案与徽标 label。`ArtifactTimeline.vue` 那类「只读展示组件内联中文」的先例**不适用**于新页面（CONTEXT 明示：新页面走 i18n）。

---

## 18. 无障碍（a11y）

### 18.1 键盘导航

| 区域 | 契约 |
|------|------|
| 六段导航 | `AnchorNavLayout` 的 `<button>` 天然可 Tab；`Enter`/`Space` 跳段。窄屏 `Select` 由 reka-ui 提供完整键盘语义 |
| 正文 `<mark>` | `tabindex="0"` + `role="button"` + `Enter`/`Space` 触发；`aria-label` 说明「此处有 {n} 条批注（{kind}）」 |
| 线程侧栏 | 侧栏根 `role="complementary"` + `aria-label`；分组用 `ui/collapsible`（`aria-expanded` 由 reka-ui 提供）；线程卡为 `<button>`，`↑`/`↓` 在同组内移动焦点，`Esc` 清除 `activeThreadId`（不关闭侧栏） |
| 侧栏（窄屏 `Sheet`） | reka-ui 提供焦点陷阱与 `Esc` 关闭；关闭后焦点**必须**回到唤起它的顶栏「批注」按钮 |
| 所有 Dialog | reka-ui 自带焦点陷阱 + `Esc`；`DialogTitle` 必填（否则 reka-ui 报 a11y 警告） |
| 选区 popover | 出现后焦点**不自动抢占**（会打断选区）；`Tab` 可进入，`Esc` 关闭并保留选区 |
| 表格 | 使用语义 `<table>`/`<th scope="col">`，不用 div 模拟 |

### 18.2 焦点管理（预览弹层）

- 查看器是**路由页**，所以 `CitationPreviewDialog` 是**第一层** Dialog —— **不存在嵌套 Dialog**，无需自造 z-index/焦点管理封装（这正是 §4.1 选路由页而非全屏 Dialog 的决定性收益）。
- 预览弹层内的 `CitationBlueprintPreview` 里的 citation chip **不再打开第二层弹层**（避免真的嵌套）：改为「打开完整蓝图」的 `RouterLink`（新页），弹层随导航自然卸载。
- 关闭预览后焦点回到触发它的 citation chip（reka-ui `DialogTrigger` 默认行为；非 Trigger 触发的受控场景须手动 `chipRef.focus()`）。
- `BlueprintRejectDialog` / `BlueprintFindingActions` 打开时初始焦点落在 `Textarea`（`autofocus` 由 reka-ui 的 `@open-auto-focus` 指定）。

### 18.3 对比度

| 项 | 要求 | 落地 |
|----|------|------|
| 正文文字 | ≥ 4.5:1（WCAG AA） | `text-foreground` `hsl(215 28% 17%)` on 白 = **14.8:1**；底纹叠加 ≤12% 后仍 > 10:1 |
| 辅助文字 | ≥ 4.5:1 | `text-muted-foreground` `hsl(215 16% 47%)` on 白 = **4.8:1** ✓（`web/DESIGN.md` 明令「禁止灰到看不见」） |
| **划线描边** | ≥ **3:1**（WCAG 1.4.11 非文本） | §7.5 逐条标注：5.9 / 4.6 / 6.4 / 3.5 / 6.5 —— **teal-500 与 amber-500 原值不达标，必须降档** |
| 徽标 | 由 `ui/badge` 既有 variant 保证 | 不覆写 |
| 焦点环 | 可见且 ≥3:1 | `outline: 2px solid hsl(168 76% 42% / 0.5); outline-offset: 2px`（`main.css` 既有） |
| **不以颜色为唯一信息载体** | 强制 | 批注同时用**线型**编码状态（实线/虚线/点线）；`change_type`、`fitness`、`availability` 徽标一律**图标 + 文字 + 颜色**三重编码 |

### 18.4 动效

`main.css` 已有 `@media (prefers-reduced-motion: reduce)` 全局兜底（动画时长压到 0.01ms、`scroll-behavior: auto`）。本相位新增动效**只用既有 `animate-*` 令牌**（`animate-fade-in` / `animate-slide-in-right` / `animate-scale-in` / `animate-spin`），不写裸 `transition` 长动画；`scrollTo({ behavior: 'smooth' })` 由该媒体查询自动降级。

### 18.5 其他

- 生成中区域用 `aria-busy="true"`；进度文案区 `aria-live="polite"`。
- diff 摘要行 `aria-live="polite"`（抄 `PromptVersionDiff.vue`）。
- `<mark>` 默认黄底必须被重置（浏览器默认样式会破坏色彩语义）。
- 所有图标-only 按钮必须有 `aria-label`。

---

## 19. 安全

| 面 | 契约 |
|----|------|
| XSS | 蓝图正文、线程消息、citation `quote`/`title`、JSON 示例、diff 段 **一律 mustache + `<pre>`**，**禁 `v-html`**。唯一允许 `v-html` 的地方是 `MermaidDiagram.vue` 既有的 SVG 注入（`securityLevel: 'strict'`，既有面，本相位不改） |
| Markdown | 若某处需渲染 markdown（引用预览的知识实体正文），复用既有 `MarkdownRenderer.vue`，不新引渲染器 |
| 外链 | 一律 `target="_blank" rel="noopener noreferrer"` |
| 存在性泄露 | §8.2 的 404 单一文案是唯一实现；**前端不得**因为「列表里能看到」就推断某 artifact 存在 |
| 权限 | **前端不自建权限判断**：不做「只读模式 / 可编辑模式」二态，一律以后端状态码为准（成员即全权，DESIGN §6.4；非成员列表里看不到、直链中性 404）。同时定夺 111-REVIEW 跳过项 **MN-12** |
| 凭证 | 前端零 token 管理（cookie-JWT 既有机制）；日志/埋点不打印蓝图正文与批注正文 |

---

## 20. 契约断言（必须写成用例；括号内为变异，变异后用例应转红）

> 来自 CONTEXT `<specifics>`「本相位最容易做错、必须能证伪的三条」，本契约再补五条。

1. **finding 线程的侧栏渲染不出「回复」输入框**。（变异：把 finding 也渲成可回复 ⇒ 用例转红）
2. **`current_status` 处于可编辑白名单外时，编辑入口与作答框不存在于 DOM**（是不渲染，**不是** `disabled`）。（变异：改成 `disabled` ⇒ 转红）
3. **approve 409 时，`unresolved_blocker_thread_ids` 每一项都渲染成可点跳转的处置入口**。（变异：只渲染一句「不可确认」⇒ 转红）
4. **404 只有一句文案**：断言组件树里针对 404 的文案节点数 == 1，且 i18n 只有 `error.notFoundOrForbidden` 一个键被用于 404 分支。（变异：加一句「该蓝图不存在」⇒ 转红）
5. **`orphaned_threads` 直接渲染、不二次过滤**：给一条「无 anchor 的系统线程」和一条「真失锚线程」，断言失锚组条数 == 后端返回的 `orphaned_threads.length`。（变异：前端加 `.filter(t => t.anchor?.block_id)` ⇒ 转红）
6. **`refetchInterval` 字面量只出现在 `useBlueprintLive.ts`**：源码扫描断言 `web/src/components/blueprint/**` 与 `pages/knowledge/blueprints/**` 对 `refetchInterval` **零命中**。（变异：在组件里直接写轮询 ⇒ 转红）
7. **质量指标 `null` 渲染「暂无数据」而非 0**：三态并列（`null` / `0` / 正值）各一条用例。（变异：`v ?? 0` ⇒ `null` 用例转红而 `0` 用例仍绿 —— 正是要逮的陷阱形状）
8. **offset 越界降级 ≠ 失锚**：构造一条 `end_offset > text.length` 的 anchored 线程，断言该块出现整块色条、**且该线程不出现在「失锚批注」组**。（变异：把越界也归入失锚组 ⇒ 转红）

`data-testid` 命名：一律 `blueprint-` 前缀（`blueprint-block` / `blueprint-annotation-mark` / `blueprint-thread-card` / `blueprint-thread-composer` / `blueprint-finding-actions` / `blueprint-blocked-dialog` / `blueprint-version-switcher` / `blueprint-diff` / `blueprint-review-approve` / `blueprint-review-reject` / `blueprint-gate-panel` / `blueprint-quality-panel` / `blueprint-citation-chip` / `blueprint-citation-preview` / `blueprint-list-card` / `blueprint-error-state`）。

---

## 21. Registry Safety

| Registry | Blocks Used | Safety Gate |
|----------|-------------|-------------|
| shadcn 官方（已随 `web/components.json` 落地于 `~/components/ui/*`） | dialog / sheet / skeleton / tabs / badge / popover / tooltip / scroll-area / table / pagination / select / input / textarea / button / collapsible / separator / alert-dialog | not required（既有代码，非本次拉取） |
| 第三方 registry | **无** | not applicable —— 本相位**不引入**任何第三方 registry / block，无需 `shadcn view` 审查 |

新增运行时依赖：**零**。`mermaid` / `diff` / `@floating-ui/vue` / `codemirror` 均已在 `web/package.json`。

---

## 22. 6-Pillar 设计契约自检

| 支柱 | 落点 |
|------|------|
| Copywriting | §16 全量定稿（含四条破坏性确认全文、404 单一文案、指标无数据文案）；§17 i18n 命名空间 |
| Visuals | §5 三栏与断点、§6 九段渲染锚定图、§13 组件清单与 props/emits 契约 |
| Color | §15 60/30/10 + accent 七项穷举；§7.5 批注四色（含 WCAG 1.4.11 实算）；§9.2 diff 二色沿用既有 |
| Typography | §14 四档字号 + 两档字重 + 三条例外 |
| Spacing | §2 八档刻度 + 四条例外（12/20/44/88px） |
| Registry Safety | §21 零第三方 registry、零新增依赖 |

---

## Checker Sign-Off

- [ ] Dimension 1 Copywriting: PASS
- [ ] Dimension 2 Visuals: PASS
- [ ] Dimension 3 Color: PASS
- [ ] Dimension 4 Typography: PASS
- [ ] Dimension 5 Spacing: PASS
- [ ] Dimension 6 Registry Safety: PASS

**Approval:** pending
