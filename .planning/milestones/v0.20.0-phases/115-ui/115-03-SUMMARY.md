---
phase: 115-ui
plan: 03
subsystem: blueprint-block-rendering-and-citation-preview
requirements: [VIEW-01, VIEW-02, CLAR-01]
tags: [frontend, vue3, annotations, selection, citation-preview, a11y, tanstack-query, degradation]
requires:
  - "115-02 全部地基：`~/types/blueprint`、`~/utils/blueprintBlocks`（`blockText` / `iterBlocks`）、`~/utils/blueprintAnnotations`（`sliceBlockText` / `isValidAnchor` / `degradedThreadIds` / `anchorRangesForBlock` / `groupThreadsByBlock` / `rangeOffsets`）、`~/components/blueprint/annotationTokens`（`annotationClass` / `pickTopThread` / `MARK_BASE_CLASS`）、`~/api/blueprints`、`~/api/repositoryChunks`（`getChunkAt` 的 `usable`）、i18n `knowledge.blueprints.*`、safelist 12 图标"
  - "115-01 §1 五端点契约表（`getBlueprintDocument` 的响应七键）"
  - "既有可复用件（实测）：`MermaidDiagram.vue`（prop 名 `code`）、`CompactEmptyState.vue`（`icon` 收裸名、只有默认 slot）、`~/components/ui/{dialog,table,skeleton,badge}`、`~/api/knowledge` 的 `getEntity`"
provides:
  - "`web/src/components/blueprint/BlueprintBlock.vue`（约 330 行）—— ⭐ **批注层与引用层的唯一实现点**：五类块分发 + `<mark>` 字符区间 + 越界/强制整块降级 + 块底 citation chip 行"
  - "`web/src/components/blueprint/BlueprintBlockList.vue`（约 200 行）—— 段级三分支 + ⭐ **选区侦测唯一落点**；⭐ 导出 `interface SelectionPayload`（115-04/05/06 一律 `import type` 复用）"
  - "`web/src/components/blueprint/BlueprintCitationChip.vue`（约 175 行）—— 九档 `source_type` 图标/文案 + 外链三类走 `<a>` 其余走 `<button>` 的分流"
  - "`web/src/components/blueprint/CitationPreviewDialog.vue`（约 175 行）—— 第一层受控 Dialog + 五子件分发 + 缺关键定位直接兜底"
  - "`web/src/components/blueprint/citation/`：`CitationKnowledgePreview` / `CitationCodePreview`（⭐ 降级形态）/ `CitationCharterPreview` / `CitationBlueprintPreview` / `CitationFallback`"
  - "`web/src/components/blueprint/__tests__/BlueprintBlock.spec.ts`（27 例）与 `citationPreview.spec.ts`（16 例），合计 **43 例全绿**"
affects:
  - "115-05 九个 section 组件：一律经 `BlueprintBlockList` 透传 `blockCtx`，⛔ 不再自行处理批注与引用"
  - "115-04 侧栏与选区 popover：`import type { SelectionPayload } from '~/components/blueprint/BlueprintBlockList.vue'`；`thread-click` 的**第二个参数** `allThreadIds` 供「一个 mark 覆盖多条」的微型 Popover 使用"
  - "115-06 页面装配：`showClosed` 由 `useBlueprintViewerStore().showClosedAnnotations` 透传；`cross-block-selection` 由页面渲染 toast（`knowledge.blueprints.annotation.crossBlock`）"
  - "⭐ **源码守卫扫描面首次非空（11 个文件）**：断言 6（`refetchInterval`）与断言 10（`edit-block`）从本 plan 起真正生效，⛔ 不再是空集合平凡通过"
  - "⚠️ **回报给 115-06 的 i18n 缺口（4 个键）**：章程四分区小标题缺文案键，`CitationCharterPreview` 已按 §13.2 降级为「不渲染分区小标题」，见 §9"
tech-stack:
  added: []
  patterns:
    - "切分段渲染：`sliceBlockText` 返回的结构化数组 → `decorate()` 一次性算好着色/a11y 属性 → 模板纯 `v-for`，避免模板里反复查表"
    - "扁平串还原成行：`list` 与 `pseudocode` 的 offset 坐标系是「`\\n` 连接的扁平串」，切分在扁平串上做、再按 `\\n` 还原成 `<li>` / 行号行"
    - "选区侦测集中在列表层：`document` 级 `selectionchange` + 120ms 去抖 + `onUnmounted` 解绑，N 个块共用一个监听器"
    - "预览子件统一 `{ fallback }` prop：任何失败路径收敛到同一个 `CitationFallback`，弹层本身不含任何关闭自己的分支"
key-files:
  created:
    - web/src/components/blueprint/BlueprintBlock.vue
    - web/src/components/blueprint/BlueprintBlockList.vue
    - web/src/components/blueprint/BlueprintCitationChip.vue
    - web/src/components/blueprint/CitationPreviewDialog.vue
    - web/src/components/blueprint/citation/CitationKnowledgePreview.vue
    - web/src/components/blueprint/citation/CitationCodePreview.vue
    - web/src/components/blueprint/citation/CitationCharterPreview.vue
    - web/src/components/blueprint/citation/CitationBlueprintPreview.vue
    - web/src/components/blueprint/citation/CitationFallback.vue
    - web/src/components/blueprint/__tests__/BlueprintBlock.spec.ts
    - web/src/components/blueprint/__tests__/citationPreview.spec.ts
  modified:
    - web/src/components.d.ts
decisions:
  - "UI-SPEC §6.2 订正一：删除 `selection-comment` emit（plan-checker N6a）——`BlueprintBlock` 永远不会触发它，声明即死接口"
  - "UI-SPEC §6.2 扩写一：`thread-click` 载荷加第二个参数 `allThreadIds: string[]`，供 115-04 判断是否弹「一个 mark 覆盖多条」的选择器"
  - "UI-SPEC §6.2 扩写二：新增 `showClosed?: boolean` 与 `plainMermaid?: boolean` 两个 prop"
  - "`<mark>` 的 `:class` **只**用 `annotationClass()` 的返回，⛔ 不叠加 `MARK_BASE_CLASS`（会出现两条同优先级 background-color，正是 annotationTokens 刻意规避的）"
  - "`CitationKnowledgePreview` 不引 `MarkdownRenderer`：`getEntity` 只返回 14 个元数据键，全仓无「取知识实体正文」的读面 ⇒ 正文位改用 citation 的 `quote` 快照"
  - "`CitationCharterPreview` 不渲染分区小标题：全仓无章程四分区的 i18n 键，按 §13.2 回报而不自补 zh-CN.json"
  - "happy-dom 的 `createTreeWalker(SHOW_TEXT)` 会把注释节点一并返回（长度 0，不影响 offset），测试 helper 按内容找文本节点而不是取第一个"
metrics:
  duration: "约 1 小时"
  completed: 2026-08-01
  tasks: 3
  commits: 3
  tests_added: 43
---

# Phase 115 Plan 03: 块渲染 / 批注可视层 / 引用二级预览 Summary

**一句话**：把「蓝图正文怎么渲染 + 批注怎么显示 + 引用怎么二级预览」收敛成**两个可复用件 + 一套六件预览弹层**——9 个新建组件（约 1500 行）+ 2 个测试文件（**43 例全绿**），让 115-05 的九个 section 组件退化成纯粹的数据排版。全相位「最不能做错的一层」的可视半边（越界降级 ≠ 后端失锚 ≠ 无 anchor 三态）与「最容易假通过的一档」（`chunk-at` 的 200-空 chunks）各有**正反成对用例**，并已用**真实变异**证明它们会转红。**零既有源文件修改、零新增依赖、零 `v-html`、零颜色字面量、后端零改动。**

---

## 1. 门禁与基线（对比 115-02 的 1464/1）

| 门 | 结果 | 对比基线 |
|---|---|---|
| `pnpm exec vitest run` | **1507 passed / 1 skipped（1508 例，205 文件）** | 基线 1464 / 1（203 文件）⇒ **+43 例 / +2 文件，零回归** |
| `pnpm type-check`（`vue-tsc --noEmit`） | **通过（exit 0）** | 同基线 |
| `pnpm lint`（本 plan 触碰面） | `eslint src/components/blueprint/` → **0 problems** | ⭐ **零新增**；仓库 111 个既有问题与蓝图无关（判据见 115-02 §1「lint 基线的真相」） |

那 1 条 skip 是**既有**的 `src/layouts/__tests__/default.spec.ts:66`，与本 plan 无关。

新增用例分布：

| 文件 | 例数 | 锁住什么 |
|---|---|---|
| `components/blueprint/__tests__/BlueprintBlock.spec.ts` | 27 | 五类块 / mark 计数与重叠切分 / **越界整块含负向对照** / table·mermaid 强制整块 / orphaned 连色条都不给 / 已关闭默认不着色 / 无编辑入口 / chip 三档分流 / P-13 同源 / 选区四档 |
| `components/blueprint/__tests__/citationPreview.spec.ts` | 16 | 九档 source_type 分发 / **三条兜底并列** / 缺 `line_start` 零请求 / 不回显错误体 / 空 quote 走空态 / 预览不嵌套 |

### ⭐ 源码守卫首次在非空扫描面下生效

`blueprint-source-guard.spec.ts` 的扫描面（`src/components/blueprint` + `src/pages/knowledge/blueprints`，跳过 `__tests__`）本 plan 之后含 **11 个文件**：本 plan 新建的 9 个 `.vue` + 115-02 的 `BlueprintStatusBadge.vue` 与 `annotationTokens.ts`。⇒ 断言 6（`refetchInterval` 零命中）与断言 10（`edit-block` / `edit-blocks` / `editBlocks` 零命中）**首次在非空集合上通过，不再是平凡通过**。6 条断言全绿。

---

## 2. ⭐ `BlueprintBlock.vue` 的最终 props / emits（115-05 与 115-06 照此逐字接线）

### 2.1 props（8 项）

| prop | 类型 | 默认 | 说明 |
|---|---|---|---|
| `block` | `BlueprintBlock` | **必填** | 单个块 |
| `sectionPath` | `string` | `''` | 只用于降级定位与失锚回显文案，⛔ **不参与 DOM id** |
| `threads` | `BlueprintThreadDetail[]` | `[]` | 已按 `block_id` 预分组（`BlueprintBlockList` 会替你分好） |
| `citations` | `Record<string, Citation>` | `{}` | 文档级引用池 `content.citations`（是 object 不是 array） |
| `readonly` | `boolean` | `false` | ⚠️ 本组件**没有任何写入面**，该 prop 只为透传链签名一致而存在 |
| `activeThreadId` | `string \| null` | `null` | 命中时该 `<mark>` 走 `annotationClass(..., active=true)` |
| ⭐ `showClosed` | `boolean` | `false` | **UI-SPEC §6.2 扩写二**：`resolved`/`dismissed` 默认不着色，由顶栏开关放出（§7.5）。115-06 从 `useBlueprintViewerStore().showClosedAnnotations` 透传 |
| ⭐ `plainMermaid` | `boolean` | `false` | **UI-SPEC §6.2 扩写二**：为 `true` 时 mermaid 块退化为源码 `<pre>`。引用预览弹层内必须传 `true`（P-12 次生，T-115-26） |

### 2.2 emits（**恰好两项**）

```ts
'thread-click': [threadId: string, allThreadIds: string[]]
'citation-click': [citationId: string]
```

- ⭐ **扩写一（UI-SPEC §6.2 emits 签名）**：`thread-click` 的**第二个参数** `allThreadIds` 是该 `<mark>` 覆盖的**全部**线程 id。理由：UI-SPEC §7.6 要求「一个 mark 覆盖多条时弹微型 `Popover` 让用户选」，而那个 Popover 归 115-04 的侧栏交互层；本组件只负责派发**优先级最高**那条（第一参数）+ 全量清单（第二参数），由上层决定是否弹选择器。整块降级角标点击走同一签名。
- ⭐ **订正一（删除 `selection-comment`）**：UI-SPEC §6.2 原列了这一项，本 plan **删掉**。理由：选区侦测的唯一落点是 `BlueprintBlockList`，`BlueprintBlock` 永远不会触发它 —— 声明一个恒不触发的 emit 是死接口，会误导 115-05/06 的接线方去监听它（plan-checker N6a）。
- ⛔ **无 `edit-block` / `edit-blocks` / `editBlocks`**：`rg` 在 `web/src/components/blueprint/` 零命中，源码守卫断言 10 已在非空扫描面下复跑转绿。

### 2.3 `BlueprintBlockList.vue` 的 props / emits

props 在 `BlueprintBlock` 八项基础上把 `block` 换成 `blocks: BlueprintBlock[]`，另加三项：`loading?: boolean`（默认 `false`）、`skeletonRows?: number`（默认 `3`）、`threads` 语义变为**本段全部线程**（组件内部调 `groupThreadsByBlock` 分组，⛔ 调用方不必预分组）。

emits **恰好四项**：

```ts
'thread-click': [threadId: string, allThreadIds: string[]]      // 透传
'citation-click': [citationId: string]                          // 透传
'selection-comment': [payload: SelectionPayload]                // 本组件独有
'cross-block-selection': []                                     // 本组件独有
```

⭐ **载荷是具名导出的 interface**（在 `<script setup>` 顶部 `export interface`，已实测 vue-tsc 与运行期均支持）：

```ts
export interface SelectionPayload {
  blockId: string
  startOffset: number
  endOffset: number
  quotedText: string   // 上限 500 字符，超出截断
  rect: DOMRect        // ⚠️ happy-dom 下恒 0 矩形，定位属 UAT
}
```

115-04 / 115-05 / 115-06 一律 `import type { SelectionPayload } from '~/components/blueprint/BlueprintBlockList.vue'`，⛔ 不各自重写载荷形状。

---

## 3. ⭐ DOM 契约表（115-04/05/06 的组件测试按它定位）

| 位置 | 属性 | 值 |
|---|---|---|
| 块根元素 | `id` | `` `blk-${block.block_id}` ``（⛔ `section_path` 不参与，与 114 重锚定的 `block_id → quoted_text → orphaned` 判据同源） |
| 块根元素 | `data-block-id` | `block.block_id`（选区侦测靠它向上找宿主块） |
| 块根元素 | `data-block-type` | `block.type`（调试用） |
| 块根元素 | `data-testid` | `blueprint-block` |
| 整块降级角标（`<button>`） | `data-testid` | `blueprint-block-degraded` |
| 划线段（`<mark>`） | `data-testid` | `blueprint-annotation-mark` |
| `<mark>` | `data-thread-id` | 优先级最高那条线程的 id |
| `<mark>` | `data-severity` / `data-thread-status` | 同上那条的 `severity` / `status` |
| `<mark>` | `role` / `tabindex` / `aria-label` / `title` | `button` / `0` / `共 {count} 条批注（{kind}）` / 同 aria-label |
| `<mark>` 事件 | `@click` + `@keydown.enter.prevent` + `@keydown.space.prevent` | 三者等价，都派发 `thread-click` |
| citation chip | `data-testid` / `data-source-type` | `blueprint-citation-chip` / 九档之一 |
| 外链 chip | `data-citation-external` | `"true"` |
| 列表根 | `data-testid` | `blueprint-block-list` |
| 预览弹层 | `data-testid` | `citation-preview-dialog` |
| 兜底件 | `data-testid` | `citation-fallback` |
| 代码预览路径行 | `data-testid` | `citation-code-path` |
| 章程分区 | `data-testid` / `data-charter-section` | `citation-charter-section` / 后端字段名 |

**人工核对已完成**：`rg -n "section_path\|sectionPath" BlueprintBlock.vue` 的命中只在 props 声明与其注释处，**不在 `:id=` 附近**；`:id=` 的唯一命中是 `` `blk-${block.block_id}` ``。

---

## 4. ⭐ 五类块的渲染形态 与「是否可字符级划线」对照表

| `block.type` | 渲染形态 | 可字符级划线？ | 坐标系 |
|---|---|---|---|
| `paragraph` | `<p class="text-sm leading-relaxed">` + 切分段 | ✅ | `blockText` 直取 |
| `list` | `<ul class="list-disc pl-5 space-y-1 text-sm">` + `<li>` | ✅ | ⭐ **「条目间 `\n` 连接」的扁平串**：切分在扁平串上做，再按 `\n` 还原成 `<li>`，一个 `<li>` 内可含多个切分段。⛔ 不按条目各自从 0 计 offset |
| `table` | `~/components/ui/table` 的语义 `<table>` / `<th scope="col">` | ⛔ **强制整块** | 后端是「所有单元格扁平后 `\n` 连接」，与渲染出的 `<table>` **无法映射** |
| `pseudocode` | 语言徽标 + 复制按钮 + 行号列 + `<pre class="font-mono text-xs leading-6">` | ✅ | `blockText` 的返回（⚠️ 可能是 `text` 而非 `code.source`，见 P-13）。⛔ 无语法高亮引擎 |
| `mermaid` | `plainMermaid` ⇒ 源码 `<pre>`；否则 `v-if="blockText(block).trim()"` 才渲 `<MermaidDiagram :code="…" />` | ⛔ **强制整块** | 渲染产物是 SVG |
| **任意类型 + 越界 anchor** | 整块左侧 `border-l-2 pl-3` + `annotationClass(...)` 的色 + 右上角计数角标 | ⛔ | — |

### 4.1 三态在正文侧的分档（P-7 / §20 断言 8，⭐ 各有正反成对用例）

| 状态 | 判定 | 正文呈现 | 侧栏归属 |
|---|---|---|---|
| **前端越界降级** | `isValidAnchor` 判非整数 / 越界 / `start >= end` | 整块色条 + 计数角标（`blueprint-block-degraded`） | ⚠️ **仍按 `status` 归组，⛔ 不进失锚组** |
| **后端失锚** | `anchor_status === 'orphaned'` | ⭐ **完全不渲染任何标记**（连整块色条都不给） | 失锚组（115-02 的 `sidebarGroups` 保证） |
| **`table` / `mermaid` 强制整块** | 块类型 | 整块色条 + 计数角标 | 按 `status` 归组 |
| **无 anchor 的系统线程** | `anchor === null` | 正文无标记（`anchor.block_id` 对不上 ⇒ 不进本块） | 按 `status` 归组 |

### 4.2 三条 mermaid 契约的落地

1. **prop 名是 `code` 不是 `source`**：`rg ':code='` 命中、`rg ':source='` 零命中（写错不报错、只渲染一个空 `<pre>`）；
2. **空源码由调用方 `v-if` 判掉**：`v-if="blockText(block).trim()"`；为空时改渲一行 `block.diagramUnavailable` 文案（组件自身对空源码既不报错也不提示）；
3. **预览弹层内退化**：`plainMermaid: true` ⇒ 源码 `<pre>`。理由是 `MermaidDiagram` 的放大层用 `vue-final-modal`，与 reka-ui `Dialog` 是**两套模态栈**（T-115-26）。

### 4.3 颜色与安全

- ⭐ **零颜色字面量**：`rg "hsl\(|#[0-9a-fA-F]{6}"` 在 `components/blueprint/*.vue` 与 `citation/*.vue` **零命中**，颜色唯一来源是 `annotationTokens.annotationClass()`；
- ⭐ **零 `v-html`**：`rg -n "v-html" web/src/components/blueprint/` 零命中，切分产物是结构化数组、渲染层只做 `v-for` + mustache（T-115-21）；
- **焦点环**：citation chip 用不透明 `var(--color-primary-600)`（3.74:1），⛔ 未沿用既有 `.btn:focus-visible` 的 50% 透明 teal（实算 1.59:1，不过 WCAG 2.4.11）。

---

## 5. ⭐ 选区侦测的完整契约

| 项 | 结论 |
|---|---|
| **监听位置** | `BlueprintBlockList.vue`，`document` 上挂**一个** `selectionchange`（⛔ 不是每块一个）。`rg -l "selectionchange" web/src/components/blueprint/ \| wc -l` == **1** |
| **去抖** | `useDebounceFn(detectSelection, 120)`（`@vueuse/core`） |
| **解绑** | `onUnmounted` 内 `removeEventListener`（T-115-25），并有**卸载后再触发不 emit** 的专门用例 |
| **不抢别人的选区** | `root.contains(range.commonAncestorContainer)` 为假 ⇒ 直接 return |
| **折叠选区** | `isCollapsed` 或 `rangeCount === 0` ⇒ 直接 return（⛔ 不清状态，避免把已弹出的 popover 抖没） |
| **同块判据** | `range.startContainer` 与 `range.endContainer` 各自向上找到的 `[data-block-id]` **是同一个元素** |
| **跨块** | 两端宿主块不同（或有一端不在任何块内）⇒ `emit('cross-block-selection')`，页面渲染 toast `knowledge.blueprints.annotation.crossBlock` =「评论只能针对同一段落内的文字，请缩小选区」 |
| **offset** | `rangeOffsets(range, blockRoot)`（115-02，内部 `collectTextNodes` + `offsetInFlatText`）；返回 `null`（算不出）⇒ 不 emit |
| **`quotedText`** | `selection.toString().slice(0, 500)` |
| **`rect`** | `range.getBoundingClientRect()`，供 115-04 的虚拟锚点定位 |
| **`readonly` 不在此处拦截** | 本组件照常 emit；是否渲染「发起评论」按钮由 115-04 的 popover 依 `readonly` 决定（§7.9：`readonly` 时只留「复制原文」） |
| **定位方案（归 115-04）** | `import { PopoverAnchor } from 'reka-ui'` + 零尺寸虚拟锚点 div，容器/内容仍用 `~/components/ui/popover` 的 `Popover` / `PopoverContent`。⛔ 不从本地 barrel 导入 `PopoverAnchor`（它只导出三个）、⛔ 不引那个浮层定位库（基线虽有依赖但 `web/src/` 零引用，保持现状） |

**⭐ `rect` 的已知限制**：happy-dom 无布局引擎，`getBoundingClientRect` 恒返 0 矩形。⇒ 「有没有算出 offset / 走的是同块还是跨块分支」**已自动化**（4 条用例），「popover 落在屏幕哪儿」**归 UAT**。

---

## 6. ⭐ 引用二级预览：分发表与兜底判据

### 6.1 分发表（九档 → 去处）

| `source_type` | 去处 | 关键入参 |
|---|---|---|
| `work_item` / `feishu_doc` / `url` | ⭐ **根本不进弹层** —— chip 本身就是 `<a target="_blank" rel="noopener noreferrer">` | `locator.url` 或 `source_id`（⭐ **只接受 `http(s)`**，其余协议退化成非交互 `<span>`） |
| `knowledge_entity` | `CitationKnowledgePreview` | `source_id` → `entityId` |
| `repo_file` / `rag_chunk` | `CitationCodePreview` | `locator.repository_id` + `locator.file_path` + `locator.line_start` |
| `repo_charter` | `CitationCharterPreview` | `locator.repository_id`（+ `locator.section` 决定 2s ring 高亮哪一段） |
| `blueprint` / `artifact_version` | `CitationBlueprintPreview` | `locator.artifact_id` 或 `source_id`，+ `locator.version_id` / `locator.block_id` |
| 以上任一**缺关键定位** | 直接 `CitationFallback` | — |

弹层本体：`Dialog` + `DialogScrollContent`（`w-[92vw] max-w-4xl`）+ `DialogHeader` + **`DialogTitle`（必填，缺了 reka-ui 报 a11y 警告）**，内容区 `max-h-[72vh] overflow-auto`。

### 6.2 ⭐ 兜底判据（⛔ 不留白、⛔ 不关弹窗、⛔ 不回显后端错误体）

| 来源 | 判据 | 失败去处 |
|---|---|---|
| 知识实体 | `isError` 或 `!data`（含 404） | `CitationFallback` |
| 代码位置 | ⭐ **只看 `getChunkAt` 的 `usable`** —— 它已覆盖 400 / 404 / 5xx / 网络失败 / **200 + 空 `chunks`**。缺 `line_start`（或缺仓库 / 路径）⇒ **查询根本不启用，一次请求都不发** | `CitationFallback` |
| 仓库章程 | `getRepositoryCharter` 恒不抛，返 `null` 或四分区全空 | `CitationFallback` |
| 其它蓝图 | `isError` 或 `!content` | `CitationFallback` |

⭐ **与 analog 完全相反**：`pages/knowledge/index.vue:165-191` 的 `catch` 是「关弹窗 + toast」；本相位**弹窗保持打开**。`CitationPreviewDialog` 内因此**没有任何关闭自己的分支** —— 关闭只可能来自用户操作。已用源码扫描核实五个文件的 `catch` 附近无 `update:open`，并有专门用例断言 404 后 `wrapper.emitted('update:open')` 为 `undefined`。

⛔ **不回显错误体**：`rg -n "ApiError|detail" CitationCodePreview.vue` **零命中**（`chunk-at` 的错误体键是 `error`，通用键会回落成无意义的「请求失败」）。专门用例：抛 `ApiError(400, '请求失败', { error: '缺少必填参数 path' })` 后，渲染文本既不含「缺少必填参数」也不含「请求失败」。

### 6.3 ⭐ `CitationCodePreview` 的降级形态与证据链

**渲染的是**：文件路径面包屑 + `line_start..line_end` 行号区间徽标 + citation 的 `quote` 快照（`<pre class="font-mono text-xs leading-6">` + 行号列，与 `pseudocode` 块同一套渲染）+ 命中多个 chunk 时一行「共 {n} 个片段」。
**⛔ 没有源码正文、⛔ 没有代码编辑器内核、因而也没有行高亮。**

证据链（三条，115-02 已登记为 UI-SPEC §3.6/§10.1 的订正，本 plan 落地）：

1. `chunk_lookup._query_covering_chunks` 只 select `{chunk_id, file_path, line_start, line_end, chunk_index}`，`chunk_at_views` 返 `{path, line, chunks}` —— **不带正文**；
2. 全仓唯一带正文的读面是 `POST /api/repositories/<id>/search/`（向量检索：必须给 query、已重排过滤），**无法按 path + 行号区间取**；
3. 仓内没有只读代码编辑器封装（`components/execution/JsonViewer.vue` 自承是它的替代品）。

⇒ 该读面归 **Phase 116**，⛔ 115 不为此新增后端端点。ROADMAP 的 SC-3 与 REQUIREMENTS 的 VIEW-02 已在 plan 阶段同步改写，⛔ 执行期不按「代码片段带行高亮」的旧措辞验收。组件 docstring 逐字写明了这条降级与顺延目标。

### 6.4 `CitationBlueprintPreview` 的迷你只读三条

`readonly` + `threads: []`（**无批注层**）+ ⭐ `plainMermaid: true`。已有用例用 `findComponent(BlueprintBlockList).props()` 断言这三项。⭐ **不开第二层弹层**（§18.2）：不监听 `citation-click`、不引入上层弹层组件（`rg "CitationPreviewDialog"` 在该文件零命中），要继续追溯走底部的「打开完整蓝图」`RouterLink`。

---

## 7. ⭐ 变异验证（执行期实跑，两条关键路径都能真的红）

**变异一 —— 越界降级路径**：把 `const isDegraded = computed(() => degradedThreads.value.length > 0)` 改成 `=> false`：

```
× 3a. ⭐ 越界（end_offset > 文本长度）⇒ 出整块色条、mark 计数 0
× 3c. 整块色条角标点击派发优先级最高那条线程
× 4a. ⭐ table 挂合法 offset 的线程仍走整块
× 4b. ⭐ mermaid 挂合法 offset 的线程仍走整块
     Tests  4 failed | 23 passed (27)
```

⭐ **负向对照（3b「合法 offset ⇒ 有 mark、无 degraded」）与 5（「orphaned 连色条都不给」）在变异下仍绿** —— 这正确：它们断言的是「**不**出现 degraded」，若也跟着红反而说明断言写串了。

**变异二 —— `chunk-at` 的「只判非 2xx」错误实现**：把 `usable` 改成 `data.value !== undefined`（即「请求成功就算可用」）：

```
× 2c. ⭐ chunk-at 返回 200-空 chunks（usable=false）⇒ CitationFallback（P-3 最常见的一档）
     Tests  1 failed | 15 passed (16)
```

两次变异后源文件均已 `git status` 核实**逐字节还原**。

---

## 8. Task Commits

| Task | 内容 | Commit | 变更 |
|---|---|---|---|
| 1 | 蓝图正文单块渲染与引用角标（批注层唯一实现点） | `71d8f64f` | 2 文件 / +586 |
| 2 | 段级块序列渲染、选区侦测唯一落点与引用二级预览六件 | `7b2d8065` | 8 文件 / +917 |
| 3 | 块渲染/批注三态/选区分流/引用兜底的组件测试（43 例） | `10ae2675` | 2 文件 / +902 |

---

## 9. ⚠️ 回报给 115-06 的 i18n 缺口（⛔ 本 plan 按 §13.2 未自补）

`CitationCharterPreview` 需要章程四分区的小标题文案，而 **`knowledge.blueprints.repo.*` 子树里没有，全仓亦无任何 `charter*` 文案键**（实测只有 `citation.sourceRepoCharter` =「仓库章程」这一个）。i18n 三处追加点已由 115-02 一次做完并对本相位关闭 ⇒ **回报而不自补**。

建议补齐的 4 个键（放在 `knowledge.blueprints.repo.*` 下，与既有 `repo` 子树同域）：

| 建议键 | 建议文案 | 对应后端字段 |
|---|---|---|
| `repo.charterPositioning` | 仓库定位 | `positioning` |
| `repo.charterOwnedDomains` | 归属域 | `owned_domains` |
| `repo.charterBoundaries` | 边界禁区 | `boundaries` |
| `repo.charterPlacement` | 落点偏好 | `placement_preferences` |

**本 plan 的降级处理**：卡片整体用既有的「仓库章程」作标题，四个分区**不渲染文字小标题**，分区身份改由 `data-charter-section="<后端字段名>"` 属性承载（测试与后续接线按它定位）。补齐 4 个键后，只需在 `sections` 计算里加回 `label` 并在模板里渲染一行 `<p>` 即可，**无结构改动**。

⚠️ **不是 safelist 缺口**：本 plan 用到的九个 chip 图标（`book-open` / `file-code` / `scroll-text` / `file-text` / `list-checks` / `external-link`）与 `file-x` / `inbox` **全部已在 `main.css` 的 `@source inline` 里**（分布在既有的 13/14/15/21/23 行与 115-02 的 33/34 行）。字面量完整类名 `icon-[lucide--message-square-dot]` 按 115-02 §8.2 的纪律**不需要** safelist。

---

## 10. Deviations from Plan

### 1. `[Rule 1 - 缺陷规避] <mark> 的 :class 只用 annotationClass()，⛔ 不叠加 MARK_BASE_CLASS`

- **发现于**：Task 1
- **问题**：PLAN 的 §7.2 转述写 `:class="[MARK_BASE_CLASS, annotationClass(...)]"`。但 `annotationTokens.ts` 的文件头 docstring 明确写着：`annotationClass()` 的返回值**恒含且仅含一条 `bg-*`**，且「刻意不在共享前缀里再放一个 `bg-transparent`，否则同一元素上会出现两条同优先级的 `background-color`，谁生效取决于 Tailwind 的产出顺序」。而 `MARK_BASE_CLASS = MARK_SHAPE_CLASS + ' bg-transparent'` —— 两者叠加正好复现该缺陷。
- **处理**：`<mark>` 只用 `annotationClass(...)`（它已含 `MARK_SHAPE_CLASS`）；`MARK_BASE_CLASS` 改用在它 docstring 里注明的场景 —— **整块降级角标**（不经 `annotationClass()` 的元素）。
- **文件**：`BlueprintBlock.vue` ｜ **Commit**：`71d8f64f`

### 2. `[Rule 3 - 阻塞] 整块降级色条的着色形态`

- **发现于**：Task 1
- **问题**：PLAN 要求整块降级「`border-l-2 pl-3` + `annotationClass(...)` 给出的色」，但 `annotationClass()` 产出的是 `border-bottom` + `bg-*` 字面量类。想把它改写成 `border-left` 只能做字符串替换，而**运行期拼出来的任意值类名 Tailwind 根本不会生成规则**（`annotationTokens.ts` 的 docstring 专门警告过这一点，症状是底纹整片消失且不报错）。
- **处理**：按 PLAN 字面执行 —— 根元素同时挂 `border-l-2 pl-3` 与 `annotationClass(...)` 的返回。实际视觉是「中性色 2px 左描边 + 来自色相档的底纹与下边框」，**降级身份仍由 `data-testid="blueprint-block-degraded"` 与右上角计数角标明确承载**。⛔ 未在组件内引入任何颜色字面量（那会破坏「颜色单一来源」并触发零 `hsl(` 断言）。
- **登记**：左色条的**色相是否需要真正落在左边**属视觉判断，已列入 §11 UAT 清单第 6 条；若要做，正确的落点是给 `annotationTokens.ts` 增一个 `annotationBarClass()`（字面量表），**归 115-06 或后续 plan**，⛔ 不在组件里补。
- **文件**：`BlueprintBlock.vue` ｜ **Commit**：`71d8f64f`

### 3. `[Rule 3 - 阻塞] CitationKnowledgePreview 不引 MarkdownRenderer`

- **发现于**：Task 2
- **问题**：PLAN 要求「渲染元数据卡 + 正文（复用既有 `MarkdownRenderer.vue`）」。实测 `GET /knowledge/entities/<id>/` 的响应类型 `EntityMetadata`（`web/src/api/knowledge.ts:10-25`）只有 14 个元数据键，**没有任何正文字段**；实体详情页 `pages/knowledge/entities/[id].vue` 同样只渲染元数据 + 版本轨 + 关联。全仓不存在「取知识实体正文」的读面。传空串给 `MarkdownRenderer` 只会渲染一个空壳。
- **处理**：正文位改用 citation 自带的 `quote` 快照（与 `CitationCodePreview` 的降级同款处理），元数据卡渲染标题 / 版本 / 实体 ID / 生效时间，底部给「在知识库中打开」`RouterLink`。组件 docstring 写明了这条实测结论，避免后人当成遗漏。
- **文件**：`citation/CitationKnowledgePreview.vue` ｜ **Commit**：`7b2d8065`

### 4. `[§13.2 回报而不自补] CitationCharterPreview 的分区小标题缺 i18n 键`

- 详见 §9。分区身份改由 `data-charter-section` 承载，卡片用既有的「仓库章程」作标题。**⛔ 未修改 `zh-CN.json`。**
- **文件**：`citation/CitationCharterPreview.vue` ｜ **Commit**：`7b2d8065`

### 5. `[Rule 1 - 自洽修正] 四处 docstring 字面量会触发本 plan 自己的验收断言`

- **发现于**：Task 2 的验收复跑
- **问题**：验收要求若干 token 在 `web/src/components/blueprint/` **零命中**，而我在 docstring 里为了说明「⛔ 不要用它」恰好写了这些字面量：`@floating-ui/vue`（`BlueprintBlockList`）、`CitationPreviewDialog`（`CitationBlueprintPreview`）、`action-label` / `@action`（`CitationFallback`）、`getRelated`（`CitationKnowledgePreview`）。
- **处理**：四处一律改写成不含该字面量的等义中文表述（语义不变，纪律说明保留）。与 115-02 §12 第 3 条（`BlueprintStatusBadge` 的 `v-html` 字面量触发自己的守卫）**同一类**。
- **Commit**：`7b2d8065`

### 6. `[测试环境事实登记] happy-dom 的 createTreeWalker(SHOW_TEXT) 会把注释节点一并返回`

- **发现于**：Task 3
- **现象**：happy-dom 20.10.2 的 `createTreeWalker(root, NodeFilter.SHOW_TEXT)` **同时返回 Comment 节点**（Vue 的 `<!--v-if-->` 与模板注释），它们 `textContent` 为 `''`、`length` 为 0。115-02 的能力锁用的 fixture（`<div>abc<span>def</span>ghi</div>`）没有注释，故未暴露。
- **影响评估**：**对生产逻辑无影响** —— `offsetInFlatText` 按 `node.length ?? textContent?.length ?? 0` 累加，注释节点贡献 0，offset 计算结果正确（同块选区用例实测 `startOffset === 0` / `endOffset === 5` 完全正确）；真实浏览器的 `SHOW_TEXT` 本就不含注释。**只影响测试 helper**：「取第一个文本节点」会拿到一个长度 0 的节点，`range.setEnd(node, 5)` 直接 `IndexSizeError`。
- **处理**：测试 helper 改为**按内容找**文本节点（`textNodeWith(root, needle)`），并在 helper 的 docstring 里写明原因。⛔ 未改动 `collectTextNodes`（生产行为正确，改了反而是为测试环境让路）。
- **文件**：`__tests__/BlueprintBlock.spec.ts` ｜ **Commit**：`10ae2675`

### 7. `[测试断言修正] emitted() 会混入冒泡到组件根的原生 DOM 事件`

- **发现于**：Task 3
- **问题**：PLAN 的「`wrapper.emitted()` 的键集 ⊆ {thread-click, citation-click}」在 VTU 下不成立 —— 点击 chip 后，原生 `click` 冒泡到组件根元素也会被 `emitted()` 记下，键集实际是 `['citation-click', 'click', 'thread-click']`。
- **处理**：断言前先剔除原生事件名白名单（`click` / `keydown` / `keyup` / `focus` / `blur` / `mousedown` / `mouseup`），断言的才是 `defineEmits` 声明面而不是 VTU 行为。用例注释写明了这一点。
- **文件**：`__tests__/BlueprintBlock.spec.ts` ｜ **Commit**：`10ae2675`

### 8. `[执行事实登记] components.d.ts 是本 plan 唯一的既有文件改动`

- **性质**：`unplugin-vue-components` **自动生成**的声明文件，随新建组件自动重写。本次为**纯追加 9 行、零删除**（9 个新组件的类型声明），且被 eslint ignore。
- **判断**：与 115-02 §12 第 4 条同一判例 —— CREATE-ONLY 约束针对**手写源文件**，生成物随源码同步是既有工程约定（已在 git 跟踪）。不视为违规，如实登记以免边界核算把它当异常。`auto-imports.d.ts` 本 plan **未变动**（新组件全部走显式 import）。

### 9. `[环境事实] pnpm 10 的 workspace 漂移本次未出现`

- 115-02 §12 第 7 条提示 pnpm 10 会向 `web/pnpm-workspace.yaml` 回填 catalog 条目。本次全程多次 `pnpm exec vitest` / `type-check` / `eslint` 后 `git status` 均未出现该漂移，`git diff web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml` **零行**。后续 plan 仍应保留这项检查。

---

## 11. ⭐ UAT 清单（happy-dom 测不了的，交给 115-07 / 人工走查）

| # | 项 | 为什么自动化测不了 | 期望 |
|---|---|---|---|
| 1 | **选区 popover 的实际落点** | happy-dom 无布局引擎，`getBoundingClientRect` 恒 0 矩形 | 拖选后 popover 贴着选区、不出视口、滚动时跟随（115-04 实现后一并验） |
| 2 | **mermaid 实渲** | 测试里 `MermaidDiagram` 必 stub（否则要连带 `vue-final-modal` 插件） | 正文里出 SVG；⭐ **引用预览弹层内是源码 `<pre>` 而不是图**（两套模态栈不叠放） |
| 3 | **`<mark>` 的颜色对比度与可辨识度** | 无渲染引擎，只能断言类名字符串 | 五色相在浅色/深色主题下都能看清；重叠段取优先级最高那条着色 |
| 4 | **焦点环可见性** | 同上 | Tab 到 citation chip 时有清晰的不透明 teal 环（3.74:1） |
| 5 | **代码预览的行号对齐** | 无字体度量 | 行号列与 `<pre>` 的 `leading-6` 逐行对齐，长行横向滚动不错位 |
| 6 | **整块降级色条的视觉** | 同 3；且形态受 Deviation 2 影响 | 判断「中性左描边 + 色相底纹」是否足以表达降级；不够则给 `annotationTokens` 加 `annotationBarClass()` |
| 7 | **`table` 块的横向滚动** | 无布局 | 宽表在 `overflow-x-auto` 内滚动，不撑破章节 |
| 8 | **复制按钮** | happy-dom 无 `navigator.clipboard`（已 try/catch 吞掉） | 点击后真的复制、按钮切到「已复制」并 1.5s 后复原 |

---

## 12. 边界核算

| 检查 | 结果 |
|---|---|
| 本 plan 变更文件 | **11 个新建 + 1 个生成物**（`components.d.ts`，+9 行 / −0） |
| `git diff --name-only <base>..HEAD -- web/src \| rg -v "^web/src/components/blueprint/"` | 只有 `web/src/components.d.ts`（生成物，见 Deviation 8） |
| 四个禁改文件（`TechPlanCard.vue` / `RoutingDecisionPanel.vue` / `NodeDataTab.vue` / `ArtifactTimeline.vue`） | **`git diff` 全空** |
| 115-02 的三处追加点（`zh-CN.json` / `main.css` / `api/index.ts`） | **`git diff` 全空** |
| 115-04 所有权的 11 个组件 + 3 个测试 | **一个都未创建、未引用** |
| `git diff --name-only <base>..HEAD -- server/` | **0 个文件** |
| `git diff web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml` | **0 行**（零新增依赖） |
| `rg -n "v-html" web/src/components/blueprint/` | **零命中** |
| `rg -n "edit-block\|edit-blocks\|editBlocks" web/src/components/blueprint/` | **零命中** |
| `rg -n "refetchInterval" web/src/components/blueprint/` | **零命中** |
| `rg -n "hsl(" web/src/components/blueprint/*.vue web/src/components/blueprint/citation/*.vue` | **零命中** |
| `rg -n "@floating-ui/vue\|useFloating\|codemirror" web/src/components/blueprint/` | **零命中** |
| `rg -n "getRelated\|getArtifactAssociations" web/src/components/blueprint/` | **零命中** |
| `rg -n "ApiError\|detail" .../CitationCodePreview.vue` | **零命中** |
| 源码守卫扫描面 | **11 个文件**（首次非空），6 条断言全绿 |

---

## 13. 给 115-04 / 115-05 / 115-06 的四条注意

1. **批注与引用只有一个实现点**。九个 section 组件一律 `<BlueprintBlockList :blocks :threads :citations :readonly :active-thread-id :show-closed @thread-click @citation-click @selection-comment @cross-block-selection />`，⛔ 不在段组件里再长出第二套划线逻辑（`data-testid` 与 DOM id 一旦有第二份，114 的重锚定结果就会与前端错位）。
2. **`thread-click` 是两个参数**（`threadId`, `allThreadIds`）。只用第一个也能正常工作；要做 §7.6 的「一个 mark 覆盖多条」微型选择器时用第二个。
3. **`SelectionPayload` 从 `BlueprintBlockList.vue` `import type`**，⛔ 不各自重写。`rect` 只在真实浏览器里有意义。
4. **`CitationCodePreview` 是降级形态**（路径 + 行号 + quote 快照，⛔ 无源码正文）。⛔ 不要按「代码片段带行高亮」的旧措辞验收，也⛔ 不要为它新增后端端点 —— 那个读面归 Phase 116。

---

## Self-Check: PASSED

**创建的 11 个文件全部存在**——`BlueprintBlock.vue` / `BlueprintBlockList.vue` / `BlueprintCitationChip.vue` / `CitationPreviewDialog.vue` / `citation/CitationKnowledgePreview.vue` / `citation/CitationCodePreview.vue` / `citation/CitationCharterPreview.vue` / `citation/CitationBlueprintPreview.vue` / `citation/CitationFallback.vue` / `__tests__/BlueprintBlock.spec.ts` / `__tests__/citationPreview.spec.ts`，逐个 `[ -f ]` 命中。

**三个 commit 全部在 `git log`**：`71d8f64f` / `7b2d8065` / `10ae2675`。

**门禁实跑**：vitest **1507 passed / 1 skipped**（基线 1464 / 1，**+43 零回归**）、type-check **exit 0**、`eslint src/components/blueprint/` **0 problems**（零新增）。

**变异验证实跑**：`isDegraded` 恒 false ⇒ **4 例转红**（负向对照仍绿）；`chunk-at` 判据改成「请求成功即可用」⇒ **2c 转红**。两次变异后源文件均 `git status` 核实逐字节还原。

**边界核算**：四个禁改文件与 115-02 三处追加点 `git diff` 全空；`server/` 零改动；依赖零行变更；115-04 的 14 个文件一个都未创建。
