---
phase: 115
slug: ui
doc: UI-REVIEW
status: fixed
blocking: false
audited: 2026-08-01
auditor: gsd-ui-auditor
fixed: 2026-08-01
fixer: "Claude (gsd-code-fixer)"
baseline: ".planning/phases/115-ui/115-UI-SPEC.md（22 节，经 ui-checker BLOCK 轮订正后的committed 版）"
diff_range: "88da0d21..HEAD -- web/"
method: code-only
screenshots: none
screenshot_reason: "无运行中的 dev server（3000 / 5173 / 8080 / 10240 均无响应）；判据取源码、Tailwind 类、main.css 令牌与组件组合"
scores:
  copywriting: 3
  visuals: 3
  color: 3
  typography: 2
  spacing: 4
  registry_safety: 4
  overall: 19
  max: 24
scores_after_fix:
  copywriting: 3
  visuals: 4
  color: 4
  typography: 4
  spacing: 4
  registry_safety: 4
  overall: 23
  max: 24
findings:
  high: 2
  medium: 6
  low: 11
fix_result:
  fixed: 13
  skipped: 4
clean_pillars: [spacing, registry_safety]
clean_pillars_after_fix: [visuals, color, typography, spacing, registry_safety]
lint_new_problems: 0
---

# Phase 115 — UI 视觉审计（回溯，6 支柱）

> **本报告是咨询性质、不阻塞。** 目的是给一份可在几分钟内逐条落手的 punch list。
> 已在 `<known_and_accepted>` 中登记的四项（代码预览降级、反向引用顺延、无 `ui/alert`、既有焦点环 1.6:1）**不在本报告内**。

---

## 一句话结论

115 的前端在**颜色令牌纪律、间距刻度、i18n 覆盖、状态分档、契约条款的逐条落地**上完成度很高（`pnpm eslint` 在 71 个相位文件上零问题、零硬编码色值、零裸中文、364 个 i18n 键无一缺失、十段容器无条件渲染这条头号靶子守住了）。punch list 集中在三处：**新增可聚焦元素的焦点环没按 §18.3 落地**（`<mark>` 甚至被 `outline-none` 抹掉且无替代）、**窄屏抽屉没做断点闸导致 xl 下侧栏重复渲染**、以及**标题字号整体比契约矮一档（14px vs 16px）**。

---

## 支柱评分

| 支柱 | 分数 | 关键判据 |
|------|:----:|---------|
| 1. Copywriting | **3**/4 | 364 键零缺失、404 单一中性文案守住、四条破坏性确认全文到位；但 `mustHaves.empty` 写了没接、3 处 key 复用错位、质量面板丢单位、7 个死键 |
| 2. Visuals | **3**/4 | 三栏 DOM 归属逐字照 §5.1、十段容器恒渲染、按段差异化骨架；但 `Sheet` 缺 `xl` 闸导致侧栏双份，`must_haves` 空态是一个光秃秃的标题 |
| 3. Color | **3**/4 | 零 hex/rgb、批注四色全在 `annotationTokens.ts`、Badge 无 `:class` 覆色、accent 收敛；唯一污点是历史版本条用了原生 `amber-500` 而非 `--color-warning` |
| 4. Typography | **2**/4 | 字号档数（4）与字重档数（2+1 例外）都合规，但 **22 个标题里 21 个是 `text-sm`（14px）**，§14 要求 Heading = `text-base`（16px）⇒ 标题与正文同号，只靠字重区分 |
| 5. Spacing | **4**/4 | **无发现。** 零任意值（`p-*`/`m-*`/`gap-*`/`space-*` 全为刻度值），四条例外（12/20/44/88px）逐条可见 |
| 6. Registry Safety | **4**/4 | **无发现。** 零第三方 registry、零新增运行时依赖、`PopoverAnchor` 取自既有 `reka-ui`，`shadcn view` 审查不适用（§21） |

**总分 19 / 24。**

---

## Top 3（先修这三条）

1. **正文 `<mark>` 用 Tab 走过去看不见任何焦点指示** —— `MARK_SHAPE_CLASS` 里的 `outline-none` 抹掉了浏览器默认环，且没有 `focus-visible:` 替代。这是新代码引入的 WCAG 2.4.7 失效，且 §18.3 点名 `<mark>` 必须用不透明 `--color-primary-600`。改 `annotationTokens.ts:117` 一行即可。
2. **`Sheet` 没做断点闸，xl 下线程侧栏渲染两份** —— 在 ≥1280px 选中正文发起评论（或走 `?thread=` 深链、409 解药面板跳转），常驻侧栏与抽屉会同时显示同一个 `BlueprintThreadSidebar`，草稿卡与选中态 ring 各出现两次。§5.2 明写 `xl` 及以上 `Sheet` 停用。
3. **标题层级塌陷到正文字号** —— 十个段标题 + 各面板/卡片标题共 21 处 `text-sm font-semibold`，§14 声明的 Heading 档是 `text-base font-semibold`。视觉后果是长页面里段与段的边界只剩字重，扫读成本明显上升。

---

## HIGH

### H-1 · `<mark>` 与整块降级角标的键盘焦点完全不可见（a11y / 契约 §18.3）

**证据**

```117:117:web/src/components/blueprint/annotationTokens.ts
const MARK_SHAPE_CLASS = 'text-foreground rounded-sm cursor-pointer align-baseline outline-none'
```

`annotationClass()`（`annotationTokens.ts:203-217`）与 `MARK_BASE_CLASS`（`:123`）都以它打头，被这些可聚焦元素消费：

- `BlueprintBlock.vue:306-320`（paragraph 的 `<mark tabindex="0" role="button">`）
- `BlueprintBlock.vue:329-343`（list）
- `BlueprintBlock.vue:386`（pseudocode）
- `BlueprintBlock.vue:289-301`（整块降级的 `<button :class="MARK_BASE_CLASS">`）

`ACTIVE_OUTLINE_CLASS`（`:126`）只在 `activeThreadId` 命中时挂上 —— 那是**选中态**，不是焦点态。全相位只有两个文件实现了 §18.3 的焦点契约：

```70:70:web/src/components/blueprint/BlueprintCitationChip.vue
const CHIP_FOCUS_CLASS = 'outline-none focus-visible:[outline:2px_solid_var(--color-primary-600)] focus-visible:[outline-offset:2px]'
```

（另一处是 `BlueprintSelectionPopover.vue:53`。）§18.3 逐字点名的四个新增焦点目标里，`<mark>` 与 线程卡 两个没有落地。

**影响**：批注层是本相位的核心交互面，键盘用户 Tab 进正文后完全不知道焦点在哪一段划线上。

**改法**：把 `CHIP_FOCUS_CLASS` 的内容并进 `MARK_SHAPE_CLASS`（`outline-none` 已在，只需追加两个 `focus-visible:` 变体）。选中态的 `ACTIVE_OUTLINE_CLASS` 与焦点环互不干扰（前者是 `[outline:…]` 常态、后者是 `focus-visible:` 变体，同一元素上后者优先级更高，符合预期）。

---

### H-2 · `Sheet` 缺 `xl` 断点闸 ⇒ 宽屏下线程侧栏渲染两份（契约 §5.2 / §7.6）

**证据**

抽屉本体无任何断点类：

```1279:1284:web/src/pages/knowledge/blueprints/[id].vue
      <Sheet v-model:open="sheetOpen">
        <SheetContent side="right" class="w-full sm:max-w-md" data-testid="blueprint-sidebar-sheet">
          <SheetHeader>
            <SheetTitle>{{ t('knowledge.blueprints.annotation.sidebarToggleEmpty') }}</SheetTitle>
          </SheetHeader>
```

而 `sheetOpen = true` 在四条路径上**无条件**置真：

| 路径 | 行 |
|------|----|
| 选区 →「发起评论」`startDraft()` | `[id].vue:545` |
| 确认门 409 解药 `onGotoUnresolved()` | `[id].vue:580` |
| approve 409 清单跳转 `onGotoBlockedThread()` | `[id].vue:762` |
| `?thread=` 深链一次性消费 | `[id].vue:788` |

常驻侧栏在 `[id].vue:1247-1274`（`hidden … xl:flex`）。两者渲染的是**同一个** `BlueprintThreadSidebar`，同一份 `draft` / `activeThreadId`。

**影响**：≥1280px 下选一段文字点「发起评论」，屏幕右侧会盖出一层抽屉，草稿输入框同时存在于抽屉与常驻侧栏两处；用户在其中一个里打字，另一个是空的（`draftBody` 是各自组件实例的局部 `ref`，`BlueprintThreadSidebar.vue:106`）。UI-SPEC §5.2 `xl` 行逐字写着「`Sheet` 停用」。

**改法**：在页面加一个 `const isWide = useMediaQuery('(min-width: 1280px)')`（`@vueuse/core` 已在依赖），把四处置真收敛成一个 `function revealSidebar() { if (isWide.value && !viewerStore.sidebarCollapsed) return; sheetOpen.value = true }`。顶栏那颗「批注 {n}」按钮已经是 `xl:hidden`（`BlueprintViewerHeader.vue:191`），所以只需要堵这四条程序化路径。

---

## MEDIUM

### M-1 · 「批注 {n}」显示的 n 不是批注数（重复计数 + 漏计）

```111:113:web/src/components/blueprint/BlueprintViewerHeader.vue
const annotationTotal = computed(
  () => props.counts.blocker + props.counts.clarification + props.counts.orphaned,
)
```

三个加数的口径彼此不正交（`web/src/utils/blueprintAnnotations.ts:306-320`）：

- `unresolvedBlocker` 刻意作用在**全量 threads** 上（`:316`，判据 `:294-298`，含失锚线程 —— 这对它自己的用途是对的）；
- `pendingClarification` 取 `groups.open`（**已排除失锚**）；
- `orphaned` 取 `groups.orphaned`。

于是：一条 `open` 的失锚 blocker 被数**两次**；而 open 的人工评论、全部 `answered`、全部已关闭线程**一次都不数**。同一页里侧栏自己算的总数（`BlueprintThreadSidebar.vue:157-159`）是另一个值，两处对「批注共几条」给出不同答案。

**改法**：顶栏另收一个 `annotationTotal` prop，由页面用 `sidebarGroups` 的四组之和算出；三个语义计数徽标保持现状（它们各自的口径是对的）。

---

### M-2 · 线程卡选中区没有契约焦点环（§18.3 点名目标）

```188:193:web/src/components/blueprint/BlueprintThreadCard.vue
    <button
      type="button"
      data-testid="blueprint-thread-card-select"
      class="flex w-full flex-wrap items-center gap-1.5 text-left"
      :aria-pressed="active"
      @click="onSelect"
```

无 `focus-visible:` 类。它比 H-1 轻（浏览器默认环还在，看得见），但侧栏的 `↑`/`↓` 焦点移动（`BlueprintThreadSidebar.vue:191-218`）正是围绕这颗按钮设计的，焦点指示应当是契约里那道 3.74:1 的 teal 环。

**改法**：复用 `BlueprintCitationChip.vue:70` 的常量（建议提到 `annotationTokens.ts` 里导出一个 `FOCUS_RING_CLASS`，三处共用，正好也满足「令牌集中在单一模块」）。

---

### M-3 · 侧栏「显示已关闭批注」开关没有可访问名

```249:256:web/src/components/blueprint/BlueprintThreadSidebar.vue
      <div class="flex items-center gap-2">
        <Switch
          data-testid="blueprint-show-closed"
          :model-value="showClosed"
          @update:model-value="emit('update:showClosed', $event)"
        />
        <span class="text-xs text-foreground">{{ t('knowledge.blueprints.annotation.showClosed') }}</span>
      </div>
```

`<div>` 而非 `<label>`，`Switch` 上既无 `aria-label` 也无 `id`/`for` 关联 ⇒ 读屏念出来是一个无名 switch，且点文字不切换。顶栏的同一个开关写法是对的，可直接照抄：

```165:174:web/src/components/blueprint/BlueprintViewerHeader.vue
    <label class="inline-flex items-center gap-2 text-xs text-muted-foreground">
      <Switch
        :model-value="showClosed"
        data-testid="blueprint-header-show-closed"
        @update:model-value="emit('toggle-closed-annotations', $event)"
      />
      <span>
        {{ t('knowledge.blueprints.annotation.showClosed') }}
      </span>
    </label>
```

**改法**：`<div>` → `<label>`。

---

### M-4 · 引用预览关闭后焦点不回到 citation chip（§18.2 明列的受控场景）

预览弹层是**纯受控**的，没有 `DialogTrigger`：

```563:567:web/src/pages/knowledge/blueprints/[id].vue
function onCitationClick(citationId: string): void {
  const citation = citations.value[citationId]
  if (citation)
    openWithSnapshot(citation)
}
```

全相位只有 `Sheet` 做了焦点归还（`[id].vue:514-520`），`CitationPreviewDialog` 没有对应处理。§18.2 原文：「非 Trigger 触发的受控场景须手动 `chipRef.focus()`」。没有触发元素时 reka-ui 的 `onCloseAutoFocus` 会把焦点丢回 `<body>`，键盘用户关掉弹层后要从文档顶部重新 Tab。

**改法**：在 `onCitationClick` 里存 `const trigger = document.activeElement as HTMLElement | null`，`watch(previewOpen, v => { if (!v) nextTick(() => trigger?.focus()) })`；范式与 `[id].vue:514-520` 一致。

---

### M-5 · 验收锚点空态没有落地，段内是一个光秃秃的标题

```90:90:web/src/components/blueprint/sections/MustHavesSection.vue
  <div v-if="hasContent" data-testid="blueprint-must-haves" class="space-y-4">
```

而段容器与导航项由页面**无条件**渲染（`[id].vue:1160-1173`，这是 P-4 的正确取舍）。两者叠加的结果：`must_haves` 三块全空时，页面上留下一个 `<h2>验收锚点</h2>` 加零内容，左栏导航项照样可点、点过去也是空的。

文案其实已经写好了但**从未被引用**：`knowledge.blueprints.mustHaves.empty` = 「本方案未登记验收锚点」（`web/src/locales/zh-CN.json`，全仓零命中）。

**改法**：`<div v-if="hasContent">` 后补一个 `<p v-else class="text-sm text-muted-foreground">{{ t('knowledge.blueprints.mustHaves.empty') }}</p>`。同理值得扫一遍其余九段——其中八段的段组件内部都有 `CompactEmptyState`（`RepoAssociationsSection.vue` / `CurrentStateSection.vue` / … 逐个确认过），只有 `must_haves` 这一段漏了。

---

### M-6 · Heading 档整体矮一号：21 处 `text-sm`，契约是 `text-base`

**证据**（标题元素的 class 分布，相位触及文件）：

| class | 次数 |
|-------|-----:|
| `text-sm font-semibold`（含带 `text-foreground` / `flex-1` / `line-clamp-2` 等变体） | **21** |
| `text-2xl font-bold tracking-tight`（页面 H1，§14 唯一例外，✔） | 1 |

典型落点：十个段标题 `[id].vue:963 / 990 / 1018 / 1047 / 1076 / 1104 / 1132 / 1161 / 1176 / 1196`，面板标题 `BlueprintQualityPanel.vue:89`、`BlueprintStageTimeline.vue:148`。

UI-SPEC §14 的四档表里 Heading（段标题、卡片标题、面板标题）= **16px / 600 / `text-base font-semibold`**，Body = 14px。当前实现把 Heading 压到 14px，与 Body **同号**，只剩 `font-semibold` 一个区分维度。字号档数（xs/sm/base/2xl = 4）与字重档数（medium/semibold + bold 例外）本身都合规，问题纯粹在 Heading 用错了档。

**改法**：把这 21 处的 `text-sm` 换成 `text-base`（`text-[11px]` / mono / Label 档一律不动）。改动是纯样式类替换，无逻辑风险。

---

## LOW

| # | 位置 | 问题 | 改法 |
|---|------|------|------|
| L-1 | `[id].vue:924` | 历史版本提示条用原生调色板 `border-amber-500/40 bg-amber-500/10`，而 `--color-warning: hsl(38 92% 50%)` 就在 `main.css:90`。**这是全相位唯一一处裸 Tailwind 调色板色**（其余 71 个文件零命中） | 换成 `border-warning/40 bg-warning/10` |
| L-2 | `BlueprintReviewActions.vue:77-78` | 同时渲染 `<Separator orientation="vertical">` 与相邻容器的 `border-l`，中间只隔 `gap-2`(8px) ⇒ 视觉上是**两条平行竖线**。UI-SPEC §11.1 字面上确实两者都要，实现是忠实的 —— 属契约自身的冗余 | 去掉其中一条（建议留 `border-l`，与 `pl-4` 同属一个容器） |
| L-3 | `[id].vue:1282` | 抽屉标题复用按钮文案键 `annotation.sidebarToggleEmpty`（「批注」）。渲染结果可接受，但键语义错位，后续改按钮文案会连带改标题 | 新增 `annotation.sidebarTitle`，或复用 `section.*` 风格的独立键 |
| L-4 | `BlueprintThreadSidebar.vue:225` | `<aside role="complementary">` 的 `aria-label` 用了 `sidebarToggleAria`（「查看批注，共 N 条」）。landmark 名应是名词短语，不是动作描述 | 用一个静态的「批注」类键；计数已由各分组 Badge 提供 |
| L-5 | `BlueprintQualityPanel.vue:127-129` | 指标值渲染成裸数字，§11.2 写的是 `{v} 次人工编辑` / `{v} 轮`（单位丢失）。metric-card 形态下「标签在上、大数在下」本身是常见范式，故仅列为 LOW | 若要严格对齐契约，在 `plain()` 里带上单位；或在 §11.2 上登记这处刻意简化 |
| L-6 | `BlueprintQualityPanel.vue:76-84` | 「无关键结论」徽标的 `title` 复用了空态串 `sectionEmpty`，渲染成「本方案未涉及现状分析 / 仓库关联 / 影响范围」——作为解释性 tooltip 读起来像在陈述事实而非解释指标口径 | 新增一个 `quality.noKeyConclusionsDetail` 键 |
| L-7 | `BlueprintErrorState.vue:116` | 5xx 档 `:description="detail"` 原样回显后端错误体。§8.2 的 5xx 行只规定 `error.unavailable` 一句，回显 detail 不在契约内，且上游 5xx 的 detail 可能带栈信息 | 5xx 档不传 `detail`（400 档的回显是契约要求的，保留） |
| L-8 | `BlueprintThreadSidebar.vue:315` | 分组折叠触发器 `py-1.5` ≈ 30px 高，§2 的 44px 例外点名「线程侧栏的折叠箭头」。全相位只有选区 popover 落地了 `min-h-11`（`BlueprintSelectionPopover.vue:95,105`） | `CollapsibleTrigger` 加 `min-h-11`（窄屏抽屉里的实际触控目标） |
| L-9 | `zh-CN.json` | 7 个死键：`tabPanel.repoRoleDirect` / `tabPanel.repoRoleIndirect` / `viewer.highlightJump` / `repo.fitnessReasons` / `api.direction` / `flow.steps` / `review.disabledReadonly`（`mustHaves.empty` 见 M-5）。`progress.*Generic` 那批是动态拼接消费的，**不算死键** | 删除，或补上对应渲染点 |
| L-10 | `BlueprintViewerHeader.vue:124` | 顶栏用 `flex-wrap`；§5.2 的 `< md` 行写的是「计数徽标折成一行可横向滚动」。换行在窄屏会把顶栏撑高，挤压 `sticky` 之下的正文可视区 | 计数徽标那一段包一层 `flex-nowrap overflow-x-auto` |
| L-11 | `useCitationPreview.ts:68-99` | `openCitation` / `loading` / `data` / `fallback` / `close` 在页面侧零消费 —— `[id].vue:566` 只调 `openWithSnapshot`，各 `Citation*Preview` 子件自行取数。§13.8 给该 composable 的职责是「预览弹层的开关与 citation 装配」，当前只用到「开关」 | 删掉未消费的分支，或把子件取数收编进来；沿用 115-03 自己立的规矩「零消费的接口是死接口」 |

---

## 无发现的检查项（逐条确认过，不是没查）

| 检查项 | 结论 |
|--------|------|
| 硬编码色值 | `#rrggbb` / `rgb()` **零命中**；`hsl()` 仅出现在 `annotationTokens.ts`（唯一令牌源）与 `BlueprintBlockDiff.vue:326-337`（`.diff-added/.diff-removed`，已登记为可接受的 `PromptVersionDiff.vue` 复制） |
| `Badge` 上 `:class` 覆色 | 零命中（唯一一处 `:class` 是 `BlueprintStatusBadge.vue:50` 的 `sizeClass`，非颜色） |
| 间距任意值 | `p-*`/`m-*`/`gap-*`/`space-*` 的 `[...]` 形式**零命中**；分布集中在 gap-2 / space-y-2 / gap-1 / p-4 / p-3 / px-5 / py-3.5，四条例外（12/20/44/88px）逐条可见（`SCROLL_OFFSET = 88` 在 `[id].vue:88`） |
| 字号 / 字重档数 | 字号 4 档（xs/sm/base/2xl）符合 §14 声明；字重 medium/semibold + 单处 bold（页面 H1，§14 唯一例外） |
| `@source inline` safelist | 运行期拼接的图标（12 态徽标 / 4 档 change_type / 9 档 citation source_type / 5 档 produced_by / 全部 `CompactEmptyState` 裸名）**逐个比对 main.css，无一遗漏** |
| i18n 键解析 | 相位内全部静态 `t()` 键在 `zh-CN.json` 中**零缺失**；动态拼接的 29 个模板（`stage.${node.stage}` 等）命名空间齐备（8 个 stage 名全在） |
| 模板内裸中文 / 裸英文枚举 | 裸中文零命中（残留全是注释续行）；裸枚举 6 处，均为 `v-else` 的未知值兜底（`RepoAssociationCard.vue:163` / `ApiContractCard.vue:151` / `ImpactMatrixTable.vue:186,228` 等），`ApiContractCard.vue:155` 的 `contract.kind` 是 §6.6 明写的「mono 小写原样」 |
| XSS 面 | 相位内 `v-html` **零命中**，正文 / 消息 / quote / JSON 示例 / diff 全程 mustache + `<pre>`；外链 `rel="noopener noreferrer"` 且 `BlueprintCitationChip.vue:117-121` 只放行 `http(s)` |
| 十段容器无条件渲染 | ✔ `[id].vue:962-1214`，十个 `<section id="…">` 为静态字面量，`sections` 数组恒 10 项（`:859-870`） |
| 404 / 409 / 400 三档可区分且可操作 | ✔ 404 单一中性文案 + 「返回知识库」（+ 失效 `?version=` 时的「回到当前版本」出口）；409 approve blocked 走 `BlueprintBlockedDialog` 逐条可点；400 就近内联回显 `detail`（`BlueprintErrorState.vue:100-109`） |
| 列表页四档（loading / error / 有数据 / 空） | ✔ `BlueprintsTabPanel.vue:276-325`，`isError` 档在 `items.length` **之前**，未与空态合并 |
| Registry Safety | 零第三方 registry、零新增运行时依赖；`PopoverAnchor` 直接取自既有 `reka-ui`（`BlueprintSelectionPopover.vue:30`），未给 `ui/popover` barrel 加导出 |
| Lint 增量 | `npx eslint` 覆盖全部相位触及前端文件 ⇒ **0 problems**（仓库既有的 111 个问题不在这些文件里） |

---

## 审计范围

**契约**：`.planning/phases/115-ui/115-UI-SPEC.md`（22 节）、`115-CONTEXT.md`
**代码**（`88da0d21..HEAD`，`web/` 下 83 文件 / +18906 行，测试文件不计入评分）：

`web/src/components/blueprint/**`（含 `sections/` 9 件、`citation/` 5 件、`annotationTokens.ts`）、
`web/src/pages/knowledge/blueprints/[id].vue`、`web/src/pages/knowledge/index.vue`、
`web/src/components/knowledge/{BlueprintsTabPanel,BlueprintListCard}.vue`、
`web/src/components/common/FilterBar.vue`、`web/src/components/project/warroom/ProjectBlueprintsCard.vue`、
`web/src/utils/{blueprintBlocks,blueprintAnnotations}.ts`、`web/src/config/blueprintStatus.ts`、
`web/src/composables/{useBlueprintLive,useBlueprintAnnotations,useCitationPreview}.ts`、
`web/src/stores/useBlueprintViewerStore.ts`、`web/src/locales/zh-CN.json`、`web/src/styles/main.css`

## Fix Log

**修复于：** 2026-08-01 · 分支 `milestone/v0.20.0-blueprint`（worktree `v0.20-blueprint`）
**结论：13 fixed / 4 skipped。** 两条 HIGH 全修、六条 MEDIUM 全修、十一条 LOW 修 7 跳 4。
**总分 19 → 23 / 24**（Typography 2→4、Visuals 3→4、Color 3→4；Copywriting 维持 3，理由见文末）。

⚠️ **先核实再动手**：本报告是 code-only 产出，且 Phase 116 在审计之后又落了十余个 commit
（`8c1a54d4` 为修复起点），**报告里的行号普遍已漂移**。每条 findings 都按内容重新定位并
复核过，其中**一条与实测不符**：L-9 说 `flow.steps` 是死键，实际 `flow.steps` 在
`InteractionFlowsSection.vue:174,201` 与 `blueprintBlocks.ts:221` 有命中 —— 但那是**数据字段
访问**（`flow.steps` 数组）不是 i18n 键，i18n 键侧的结论仍成立。另有一处报告未覆盖：
`BlueprintViewerHeader.vue` 的「未经确认」横幅（116-05 新增，不在审计 diff 范围内）
与 L-1 是**同一处违规**，已一并修掉，判断记录在 L-1 行。

**每条都配了非恒真对照**——「一律加焦点环」「一律不开抽屉」「一律回显 detail」这类同样能让
主断言变绿的错误实现都会被拦住。新增 **38 条**用例（1706 → 1744）。

### HIGH

| ID | 结论 | commit | 说明 |
|---|---|---|---|
| H-1 | **fixed** | `42fce716` | §18.3 的不透明 `--color-primary-600`（3.74:1）抽成 `FOCUS_RING_CLASS` 并入 `MARK_SHAPE_CLASS` ⇒ 四种 `<mark>` 落点与整块降级 `<button>` 一并生效。选中态 `ACTIVE_OUTLINE_CLASS` 是常态 outline、焦点环是 `focus-visible:` 变体，同元素上后者优先级更高，两者不互相吃掉 |
| H-2 | **fixed** | `4dd132bb` | 四条程序化路径收敛成唯一入口 `revealAnnotations()`：宽屏只展开常驻侧栏（§5.2「`Sheet` 停用」+「`?thread=` 深链强制展开」），窄屏才开抽屉；抽屉本体再加 `v-if="!isWide"` 从 DOM 摘掉 |

**修前红 / 修后绿证据**

- **H-1**：`BlueprintBlock.spec.ts` 新增三条 —— 令牌全组合（四色 × 四处置态 × 选中态）、
  三种 `<mark>` 落点（paragraph / list / pseudocode）、整块降级角标。只回滚
  `annotationTokens.ts` 时 **3 条转红**；修后 30/30。每条都带「`outline-none` 仍在」的
  非恒真对照 —— ⛔ 防止靠**删掉** `outline-none` 蒙混（那样浏览器默认环会与契约环叠成
  两圈，且默认环本身不达 3:1）。
- **H-2**：⚠️ **评审建议的 `xl:hidden` 单独用是不够的**（判断记录）：`SheetContent` 被
  `display:none` 之后 reka-ui 的**焦点陷阱会锁进一个不可见容器**，`sheetOpen` 也仍为
  `true`，两个侧栏实例的 `draftBody` 分叉问题一个都没解决 —— 只是把第二份藏起来。
  故取「JS 闸为主（`useMediaQuery('(min-width: 1280px)')`）+ `v-if` 摘 DOM」，⛔ 没有再叠
  一个用不上的 `xl:hidden`（本仓自己立的规矩：零消费的接口是死接口）。
  另补一条 `watch(isWide)`：拉宽时收起抽屉，否则再拉回窄屏抽屉会「自己」弹出来。
  新增六条用例，只回滚页面时 **3 条转红**：宽屏深链后侧栏实例数实测 **2**（与评审记录一致）。
  ⚠️ happy-dom 无布局引擎 ⇒ 「任一宽度恰好一份」由两条**互补**断言表达：常驻侧栏带
  `hidden`+`xl:flex`（<xl 不可见，类断言）、抽屉在 ≥xl **不存在于 DOM**（结构断言）。
  另把 `Sheet` 桩从「恒渲染」改成「按 `open` 挂载/卸载」（reka-ui 的真实行为），
  否则实例计数从一开始就失真。断点字面量 `1280` 由一条独立用例钉死（写成 `lg`/`2xl` 即转红）。

### MEDIUM

| ID | 结论 | commit | 说明 |
|---|---|---|---|
| M-1 | **fixed** | `3d1a0798` | `annotationCounts` 增出 `total` = 侧栏四组之和（四组互斥且穷尽，§20 断言 11 已钉死），顶栏改收 `annotationTotal` prop；三个语义徽标口径**一字不动**（它们各自是对的） |
| M-2 | **fixed** | `48caf6ae` | 采纳评审建议把焦点环收敛成 `annotationTokens.FOCUS_RING_CLASS` 单一实现，`BlueprintCitationChip` / `BlueprintSelectionPopover` 原本各写一串的同值字面量一并改为消费它 |
| M-3 | **fixed** | `7ab58976` | `<div>` → `<label>`，照抄顶栏同名开关的写法 |
| M-4 | **fixed** | `ce34e71f` | 在**开弹层之前**记 `document.activeElement`，`watch(previewOpen)` 关闭时 `nextTick` 归还。⚠️ 按次记录而不是写死选择器 —— 触发元素是被点的**那一枚** chip |
| M-5 | **fixed** | `a912bc55` | 补 `v-else` 一行文案接上 `mustHaves.empty`（⛔ 仍不出空态**卡**，与 `deferred_ideas` 的处理一致）；零新增 i18n 键 |
| M-6 | **fixed** | `6d89f4b2` | 21 处 `text-sm font-semibold` → `text-base font-semibold`；`text-[11px]` / mono / Label 档一律不动，字号与字重档数不变 |

**修前红 / 修后绿证据**

- **M-1**：`total` 落进既有纯函数而不是页面里现算 —— 判据单一实现。用例带**非恒真对照**：
  同一组数据下 `unresolvedBlocker + pendingClarification + orphaned` 实测 **2**、`total` **4**，
  两者不相等才证明断言有效（老口径把失锚 blocker 数两次、把人工评论/已作答/已关闭全漏掉）。
  另加两条源码守卫：组件源码不再出现 `counts.blocker + `。
- **M-4**：修前红 2 / 修后绿 26。⚠️ 第一版「两枚 chip 各自归还」的用例**修前即绿** ——
  漏了「真的把焦点移走」这一步，「什么都不做」也能过。已补 `expect(activeElement).not.toBe(chip)`
  的中途断言后转红。这条记下来：焦点类断言必须先制造焦点位移。
- **M-5**：§6.9 原文是「整段与其导航项都不渲染，不出空态卡」，但那半句已被 **P-4 订正**
  （段容器与导航项改为无条件渲染，否则 `AnchorNavLayout` 的 observer 挂不上）⇒ 「不出空态卡」
  留在原地就变成「只剩一个 `<h2>`」。⛔ 本次**没有**改成空态卡，只补一行文案，
  既有用例 4a/4b（`blueprint-must-haves` 内容卡不存在）**未被放宽**，仍全绿。
- **M-6**：守卫挂进既有 `blueprint-source-guard.spec.ts`（扫描面内 `text-sm font-semibold`
  零命中），只回滚组件时转红。21 处与评审计数逐字一致。

### LOW

| ID | 结论 | commit | 说明 |
|---|---|---|---|
| L-1 | **fixed** | `d01e12ef` | 换成 `border-warning/40 bg-warning/10`。⭐ 顺带把 116-05 加进顶栏的「未经确认」横幅一并改掉（同相位创建的文件、同一处违规，留一半反而制造不一致）。两个色值实算几乎逐位相同 ⇒ **零视觉变化的纪律修正**。另加一条源码守卫：扫描面内零裸调色板色 |
| L-2 | **skipped** | — | 见下方理由 |
| L-3 | **fixed** | `fea56bdf` | 新增 `annotation.sidebarTitle`（i18n 追加点，纯追加一个键，文案「批注」不变） |
| L-4 | **fixed** | `1ae4ec88` | landmark 名改用 L-3 刚加的静态键（零新增键）；计数已由各分组 Badge 提供 |
| L-5 | **skipped** | — | 见下方理由 |
| L-6 | **fixed** | `780a5f59` | 新增 `quality.noKeyConclusionsDetail`，把「分母为 0 ⇒ 这里的 100% 不算数」讲明白，⛔ 不再复用空态串 |
| L-7 | **fixed** | `835b945b` | 5xx 档去掉 `:description`；400 档的回显是契约要求的，保留（有非恒真对照钉死） |
| L-8 | **fixed** | `d74d35c1` | `CollapsibleTrigger` 加 `min-h-11`，并补一个 `data-testid`（此前无可定位标记） |
| L-9 | **skipped** | — | 见下方理由 |
| L-10 | **fixed** | `c0085fdb` | 三个徽标包一层 `flex min-w-0 flex-nowrap overflow-x-auto`，徽标加 `shrink-0 whitespace-nowrap`（⛔ 均非颜色类，Badge 的 variant 口径不动） |
| L-11 | **skipped** | — | 见下方理由 |

### 跳过项的完整理由

#### L-2（`Separator` 与 `border-l` 两条平行竖线）—— **skipped**

**这不是实现缺陷，是契约自身的冗余，评审自己也这么写。** §11.1 逐字要求：「与左侧阅读/编辑
动作之间用 `Separator`（`~/components/ui/separator`）+ `ml-auto` 隔开，**容器 `pl-4 border-l
border-border`**」—— 两者都点名了，`BlueprintReviewActions.vue:77-78` 是**忠实实现**。

删掉其中一条 = 单方面偏离一条写死的契约条款。本轮的定位是「按契约修实现」，⛔ 不是
「按观感改契约」；正确形态是**在 §11.1 上改掉那半句**（选定留 `border-l` 还是留
`Separator`），再让实现跟上 —— 那是一次契约修订，应当与 UI-SPEC 的下一次订正同批走，
而不是在一条 LOW 的修复里悄悄推翻。已登记进 `.planning/STATE.md`。

**成本侧**：改动本身只有两行（删 `<Separator>` + 删 import），⛔ 不是「太难所以不做」。

#### L-5（质量面板指标丢单位）—— **skipped**

评审给了两条并列改法，本轮取**后者**（「在 §11.2 上登记这处刻意简化」），三条理由：

1. **metric-card 形态本身已经承载了单位。** 四个格子一律「标签在上、大数在下」，标签写的是
   「人工编辑量」「澄清轮次」。把 §11.2 的 `{v} 次人工编辑` 塞进那个 `text-2xl font-semibold`
   的数值位，读出来是「人工编辑量 / **12 次人工编辑**」—— 标签与值互相复述。
2. **会破坏 §14 的 Display 档。** 数值位是 24px，「12 次人工编辑」在 `sm:grid-cols-2` 的窄格
   里必然换行，四个格子高度参差 —— 为了补一个已在标签里的单位，牺牲的是这一排的对齐。
3. **评审自己判它是 LOW 且给了这条出路**，措辞是「metric-card 形态下…本身是常见范式，
   故仅列为 LOW」。这属于评审口径里的「设计决策而非缺陷」。

⇒ 按评审给的第二条改法**登记为刻意简化**，已写进 `.planning/STATE.md`（下次修订 UI-SPEC
时把 §11.2 那两格的期望值改成「标签携带单位、值为裸数字」）。

#### L-9（7 个死 i18n 键）—— **skipped**

1. **零用户可见影响、零运行时代价。** 它们不渲染、不参与打包体积的有意义部分，
   属纯清洁度项 —— 而本轮每一条 commit 都要付「改动面」的账。
2. **其中两条不是「垃圾」，是有价值的缺口标记。** `review.disabledReadonly`（只读态下终审
   按钮的禁用原因）与 `viewer.highlightJump`（命中高亮后的跳转提示）命名的都是契约描述过、
   实现尚未接上的**affordance**。删掉它们等于把「这里还缺一句话」这条信息一起删掉；
   而把它们**接上**属于新增交互，远超一条 LOW 的边界。
3. **删除本身也不是零风险。** `review.disabledReadonly` / `repo.fitnessReasons` 目前活在
   两个 spec 的 i18n fixture 里，删主文件会留下悬空 fixture；真要删得连测试一起清。
4. ⚠️ **评审这条的证据有一处不准**：`flow.steps` 在 `InteractionFlowsSection.vue:174,201` 与
   `blueprintBlocks.ts:221` 有命中 —— 那是**数据字段**访问不是 i18n 键，结论侥幸仍成立，
   但说明这份清单是文本匹配得来的，逐条删除前需要再核一遍。

⇒ 登记进 `.planning/STATE.md`，与「接上那两个 affordance」一并定夺。
（`mustHaves.empty` 不在此列 —— 它已由 M-5 接上消费方。）

#### L-11（`useCitationPreview` 的零消费分支）—— **skipped**

**这条的两个改法都不是「小改动」，是架构取舍。**

- **改法 A「删掉未消费的分支」**：`openCitation` / `loading` / `data` / `fallback` / `close` 全删之后，
  `openWithSnapshot` 里的 `snapshotOf` 与 `CitationFallback` 接口也跟着失去意义，composable
  塌缩成 4 行的 `{ open, citation }` 包装 —— 而 §13.8 给它的职责是「预览弹层的开关**与
  citation 装配**」，且它的 docstring 里那段「⭐ 兜底不留白（强制）：任何非 2xx 一律走快照兜底，
  ⛔ 不关弹窗、⛔ 不渲染空白弹窗、⛔ 不回显后端错误体」是 §10.1 的**契约原文**。
  删掉它等于把契约的一处落地实现删掉，只留下五个子件里各自的副本。
- **改法 B「把子件取数收编进来」**：要把 `CitationCodePreview` / `CitationKnowledgePreview` /
  `CitationCharterPreview` / `CitationBlueprintPreview` 四个子件的取数（各自不同的端点、
  各自不同的兜底判据，其中 `CitationCodePreview` 还是 116-07 刚做的双数据源）搬进页面层。
  那是一次跨五个文件的重构，且会翻掉 `citationPreview.spec.ts` 里 20 余条按子件组织的用例。

⇒ 两条路都超出一条 LOW 的边界（也超出本轮「按 punch list 逐条落手」的定位）。
登记进 `.planning/STATE.md`：**正确时机是 §13.8 下一次修订**，那时一并定夺「装配职责归
composable 还是归子件」，⛔ 不是单点删几个 `return` 键。

### 支柱重新评分

| 支柱 | 审计 | 修后 | 依据 |
|------|:----:|:----:|------|
| 1. Copywriting | 3 | **3** | `mustHaves.empty` 已接（M-5）、三处 key 复用错位全改（L-3 / L-4 / L-6）；但 L-5 的单位与 L-9 的死键**按登记方式收口而非修掉** ⇒ ⛔ 不给自己涨这一分 |
| 2. Visuals | 3 | **4** | 该支柱被点名的两条（`Sheet` 缺 `xl` 闸 / `must_haves` 空态是光秃秃的标题）**全修**，各有修前红证据 |
| 3. Color | 3 | **4** | 「唯一污点」已消除，且加了源码守卫锁死；顺带把 116 的同款违规一并清了 |
| 4. Typography | 2 | **4** | 唯一被点名的问题（21 处 Heading 矮一档）**全修**；字号档数（4）与字重档数（2+1 例外）本来就合规 ⇒ 无残留 |
| 5. Spacing | 4 | **4** | 无发现，维持；L-8 另把 44px 例外的最后一处落地补齐 |
| 6. Registry Safety | 4 | **4** | 无发现，维持；本轮**零新增运行时依赖**（`@vueuse/core` 的 `useMediaQuery` 取自既有依赖） |

**总分 19 → 23 / 24。**

### 门禁

| 门 | 结果 |
|---|---|
| 前端 `pnpm exec vitest run` | **1744 passed / 1 skipped**（基线 1706/1，**+38** 全为本轮新增；唯一 skip 仍是既有的 `layouts/__tests__/default.spec.ts`） |
| 前端 `pnpm type-check` | **exit 0** |
| 前端 `pnpm lint` | **111 problems**（与基线逐字相同）；本轮 30 个改动文件与 27 个告警文件**交集为空**（`comm -12` 实测）⇒ 零新增 |
| 前端 `pnpm build` | 成功。⚠️ 它按既知行为改写 `src/components.d.ts`（**纯删除 29 条**无关项）—— 已 `git checkout` 还原，**未提交**；`pnpm-workspace.yaml` 本轮无 catalog 回填 |
| 后端 | **未触碰**：`git diff --name-only 8c1a54d4..HEAD` 的 30 个文件**全部在 `web/src/` 下**，`server/` 零改动 ⇒ 无需复跑（基线 8980 passed / 1 failed，那 1 条是 worktree 环境产物 `test_skills_snapshot_guard`） |

### 硬约束自检

| # | 约束 | 结论 |
|---|---|---|
| 1 | §13.2 前端 CREATE-ONLY / 四个零改动组件 | ✓ 改动的 30 个文件里，`web/src/locales/zh-CN.json` 是**五个追加点之一且只追加了 2 个键**（`annotation.sidebarTitle` / `quality.noKeyConclusionsDetail`，⛔ 零删除、零修改既有键）；其余 29 个**全部是 115/116 自己新建的**。`TechPlanCard` / `RoutingDecisionPanel` / `NodeDataTab` / `ArtifactTimeline` **零改动**（`git diff` 实测无输出） |
| 2 | 不弱化已锁定的形状 | ✓ **十段 `<section>` 恒渲染 + 静态字面量 id**（用例 1「loading 时 section[id] == 10」未被放宽，仍绿）；**finding 不可达作答通道**（`threadSidebar.spec.ts` 断言 1a/1c 未动，仍绿）；**「未经确认」横幅结构性不可关闭**（本轮只改它的**颜色类**，`v-if="unconfirmed"` 与「横幅内零按钮」用例一字未动）；**未决 BLOCKER 仍取快照权威字段**（M-1 只加 `total`，⛔ 没碰 `unresolvedBlockerCount` 那条 `??` 链，用例 10/11 仍绿） |
| 3 | 零新增运行时依赖 / 技术栈不变 | ✓ `package.json` / `pnpm-workspace.yaml` 一字未动；`useMediaQuery` 取自既有 `@vueuse/core` |
| 4 | 只用设计令牌 | ✓ L-1 把最后两处裸调色板色换成 `--color-warning` 并加守卫；批注四色与 diff 二色仍**只**在 `annotationTokens.ts` / `.diff-*`；焦点环由三处各写一串**收敛成单一令牌**（M-2） |
| 5 | zh-CN | ✓ 新增注释 / docstring / commit message 全中文；两个新 i18n 键均走 `t()` |

### 本轮顺带发现（**未修**，已登记 STATE）

- **`ui/badge` 的 `warning` variant 自己也绕开了 `--color-warning`**：
  `components/ui/badge/index.ts:19` 写的是 `bg-amber-500/10 text-amber-700`，而
  `--color-warning: hsl(38 92% 50%)` 在 `main.css:90` **全仓零消费方**（L-1 修完后才有两处）。
  两个色值实算几乎相同 ⇒ 当下无视觉后果，但「令牌定义了却没人用、大家各写调色板色」这条
  是全站级的 —— `ui/badge` 是**既有共享原语**，不在本相位 CREATE-ONLY 边界内，故只登记不改。

---

_Fixed: 2026-08-01_
_Fixer: Claude (gsd-code-fixer)_
_Scope: 13 fixed / 4 skipped · 19 → 23 / 24_
