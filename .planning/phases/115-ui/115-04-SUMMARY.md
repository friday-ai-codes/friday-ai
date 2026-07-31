---
phase: 115-ui
plan: 04
subsystem: blueprint-threads-review-and-diff
tags: [frontend, vue3, annotations, human-review, diff, a11y, i18n-gap, mutation-tested]
requires:
  - "115-02 全部地基：`~/utils/blueprintAnnotations` 的 `sidebarGroups`、`~/utils/blueprintBlocks` 的 `classifyBlockDiff` / `iterBlocks` / `blockText`、`~/config/blueprintStatus` 的 `getBlueprintStatusConfig` / `producedByReason`、`~/types/blueprint` 全量契约、i18n `knowledge.blueprints.*`"
  - "114-05 人审七端点契约（approve/reject/answer/resolve/dismiss 的入参键与全部状态码，含 approve 409 的 `unresolved_blocker_thread_ids`）"
  - "既有可复用件：`~/composables/useConfirmDialog`、`~/components/ui/{dialog,collapsible,popover,tooltip,separator,switch,textarea,badge,button}`、`~/components/common/CompactEmptyState`、`reka-ui@2.9.10` 的 `PopoverAnchor`、`diff` 包的 `diffWords`"
provides:
  - "`web/src/components/blueprint/BlueprintThreadSidebar.vue` —— 四组 Collapsible + kind 筛选 chips + 显示已关闭开关 + 草稿卡 + 两数据源合并；⭐ 导出 `interface BlueprintCommentDraft`"
  - "`web/src/components/blueprint/BlueprintThreadCard.vue` —— ⭐ CR-01 的落点：按 kind 在渲染层硬分流（`v-if` / `v-else` 物理互斥）"
  - "`web/src/components/blueprint/BlueprintThreadComposer.vue` —— 作答框 + options 候选；⭐ 只在非 finding 且 `!readonly` 时被渲染"
  - "`web/src/components/blueprint/BlueprintFindingActions.vue` —— 已修复/误报忽略 + 必填理由受控 Dialog；⭐ 不受可编辑闸约束"
  - "`web/src/components/blueprint/BlueprintSelectionPopover.vue` —— reka-ui `PopoverAnchor` + 零尺寸虚拟锚点"
  - "`web/src/components/blueprint/BlueprintReviewActions.vue` —— 终审两按钮（视觉分离 + disabled&Tooltip + 通过走二次确认）"
  - "`web/src/components/blueprint/BlueprintRejectDialog.vue` —— 受控 Dialog，`comment` 必填；⭐ 导出 `BlueprintRejectAnchor` / `BlueprintRejectPayload`"
  - "`web/src/components/blueprint/BlueprintBlockedDialog.vue` —— ⭐ approve 409 的解药面板：未决清单逐条可点跳转"
  - "`web/src/components/blueprint/BlueprintQualityPanel.vue` —— 四指标格三态；闭 114-REVIEW MN-05"
  - "`web/src/components/blueprint/BlueprintVersionSwitcher.vue` —— 版本轨；⭐ 导出 `interface BlueprintVersionEntry`"
  - "`web/src/components/blueprint/BlueprintBlockDiff.vue` —— 前端算的 block 级 diff（canonical 指纹 + diffWords + shallowRef + inline/split）"
  - "三个测试文件共 **58 例**：`__tests__/threadSidebar.spec.ts`(24) / `reviewActions.spec.ts`(19) / `blockDiff.spec.ts`(15)"
affects:
  - "115-06 页面装配：按本 SUMMARY §2 的 props/emits 表与 §3 的接线契约接线，⛔ 不再发明契约"
  - "115-07 确认门：`BlueprintThreadCard` 的 `gateAvailable` prop 与 `goto-gate` emit 已就位，面板缺席时链接不渲染"
  - "⚠️ **回报给 115-06 的 i18n 缺口（5 个键）**：见 §7，本 plan 按 §13.2 一律回报而不自补"
  - "源码守卫扫描面从 11 个文件增至 **22 个**，6 条断言全绿"
tech-stack:
  added: []
  patterns:
    - "渲染层硬分流：把「哪个动作可用」做成模板里两条物理互斥的 `v-if`/`v-else` 分支，而不是统一入口 + 提交时分派 —— 让错误的入口在 DOM 里根本不存在"
    - "选中区与内容区拆成兄弟节点：卡片需要既可聚焦又内含表单控件时，用一个只含 phrasing 内容的 `<button>` 承担选中/焦点，长正文与交互控件放它外面"
    - "分组身份做成字段而不是字面量比较：`isOrphanGroup` / `isClosedGroup` 让模板零判据，判据只留在纯函数里（也顺带让源码扫描守卫可以精确断言）"
    - "i18n 缺口降级：缺文案键时用既有键组合出等义表述（`sectionEmpty` + 三个段名），或把身份交给 `data-*` 属性承载，⛔ 不改 i18n 追加点"
key-files:
  created:
    - web/src/components/blueprint/BlueprintThreadComposer.vue
    - web/src/components/blueprint/BlueprintFindingActions.vue
    - web/src/components/blueprint/BlueprintThreadCard.vue
    - web/src/components/blueprint/BlueprintThreadSidebar.vue
    - web/src/components/blueprint/BlueprintSelectionPopover.vue
    - web/src/components/blueprint/BlueprintReviewActions.vue
    - web/src/components/blueprint/BlueprintRejectDialog.vue
    - web/src/components/blueprint/BlueprintBlockedDialog.vue
    - web/src/components/blueprint/BlueprintQualityPanel.vue
    - web/src/components/blueprint/BlueprintVersionSwitcher.vue
    - web/src/components/blueprint/BlueprintBlockDiff.vue
    - web/src/components/blueprint/__tests__/threadSidebar.spec.ts
    - web/src/components/blueprint/__tests__/reviewActions.spec.ts
    - web/src/components/blueprint/__tests__/blockDiff.spec.ts
  modified:
    - web/src/components.d.ts
decisions:
  - "线程卡的选中区与内容区拆成兄弟节点：`<button>` 只含徽标行，消息列表/引文快照/作答框在它之外（表单控件与 `<ul>`/`<pre>` 嵌进 button 是非法 DOM 且点输入框会连带触发外层按钮）"
  - "kind 多选筛选对四组一视同仁地生效（含失锚组）—— 它是用户显式动作，与「⛔ 按锚点字段隐式二次过滤」不是一回事"
  - "线程卡新增 `degraded` / `gateAvailable` 两个 prop：越界降级判据需要块正文才能算，由持有正文的父层判定后传入"
  - "侧栏草稿卡不 import 115-03 的 `SelectionPayload`（同波次隔离），改为本地导出结构子集 `BlueprintCommentDraft`，115-06 可直接把 `SelectionPayload` 传进来"
  - "相对时间退化为本地化绝对时间：仓内无共享相对时间工具，`knowledge.blueprints.*` 也无相对时间单位键"
  - "`must_haves` 段在 diff 里保留一行占位，身份由 `data-diff-excluded=\"true\"` 承载（沿用 115-03 的 `data-charter-section` 判例）"
metrics:
  duration: "约 1.5 小时"
  completed: 2026-08-01
  tasks: 3
  commits: 3
  tests_added: 58
---

# Phase 115 Plan 04: 线程侧栏 / 人审终审 / 版本与 diff Summary

**一句话**：把「用户能对蓝图做什么」的写路径全集做成 11 个独立可测组件（约 2100 行）+ 3 个测试文件（**58 例全绿**），让 115-06 的页面只负责装配与接线。本相位**最不能做错的一条**（finding 线程不得走作答通道）被**物理锁死在渲染层**——finding 卡里根本没有 Composer 这个 DOM 节点——并已用真实变异证明用例会转红；approve 409 的超界死锁有了唯一的正向出口（可点跳转清单）；`blueprint_quality` 三项统计有了唯一消费面且 `null` 绝不显示 0。**零既有源文件修改、零新增依赖、零原始 HTML 注入、颜色字面量只有一个合法出处、后端零改动。**

---

## 1. 门禁与基线（对比 115-03 的 1507/1）

| 门 | 结果 | 对比基线 |
|---|---|---|
| `pnpm exec vitest run` | **1565 passed / 1 skipped（1566 例，208 文件）** | 基线 1507 / 1（205 文件）⇒ **+58 例 / +3 文件，零回归** |
| `pnpm type-check`（`vue-tsc --noEmit`） | **通过（exit 0）** | 同基线 |
| `pnpm lint`（本 plan 触碰面） | `eslint src/components/blueprint/` → **0 problems** | ⭐ **零新增**；仓库 111 个既有问题与蓝图无关（判据见 115-02 §1） |

那 1 条 skip 是**既有**的 `src/layouts/__tests__/default.spec.ts:66`，与本 plan 无关。

新增用例分布：

| 文件 | 例数 | 锁住什么 |
|---|---|---|
| `__tests__/threadSidebar.spec.ts` | 24 | §20 断言 1（kind 四类参数化）/ 2（三条并列）/ 5 / 11 + 组内排序 + options 正反 + 空 `author_display` + 失锚仍可回复 + finding 理由必填 |
| `__tests__/reviewActions.spec.ts` | 19 | 终审 disabled+Tooltip 三档 + 二次确认两层 + §20 断言 3（含负向对照）+ §20 断言 7 三态并列 + 驳回 `comment` 必填与 anchor 开关 |
| `__tests__/blockDiff.spec.ts` | 15 | 三类分类 + 键序不算 modified + `diffWords` 真跑（A3 settle）+ inline/split 正负成对 + 摘要 aria-live + diff 模式零写动作 + 段折叠 + 版本原因五档 |

### 源码守卫扫描面

`blueprint-source-guard.spec.ts` 的扫描面从 115-03 的 11 个文件增至 **22 个**（+11 个新组件），6 条断言全绿。

---

## 2. ⭐ 11 个组件的 props / emits 逐字表（115-06 照此接线）

### 2.1 `BlueprintThreadSidebar.vue`

```ts
props: {
  threads?: BlueprintThreadDetail[]            // 默认 []，来自 threads/ 端点
  orphanedThreads?: BlueprintThreadDetail[]    // 默认 []，来自人审快照的 orphaned_threads
  activeThreadId?: string | null               // 默认 null
  readonly?: boolean                           // 默认 false，= !isBlueprintEditable(current_status)
  showClosed?: boolean                         // 默认 false，来自 useBlueprintViewerStore().showClosedAnnotations
  kindFilters?: string[]                       // 默认 []（空数组 = 全选）
  degradedThreadIds?: string[]                 // 默认 []，越界降级线程 id 集合
  gateAvailable?: boolean                      // 默认 false
  submitting?: boolean                         // 默认 false
  draft?: BlueprintCommentDraft | null         // 默认 null，选区草稿
}
emits: {
  select:              [threadId: string | null]        // null = Esc 清选中态
  answer:              [threadId: string, body: string]
  resolve:             [threadId: string, reason: string]
  dismiss:             [threadId: string, reason: string]
  'goto-gate':         [threadId: string]
  'create-comment':    [body: string, draft: BlueprintCommentDraft | null]
  'cancel-comment':    []
  'update:kindFilters':[kinds: string[]]
  'update:showClosed': [value: boolean]
}
export interface BlueprintCommentDraft { blockId: string; startOffset: number; endOffset: number; quotedText: string }
```

⚠️ **与 PLAN 的差异（三处，均为必需扩展）**：新增 `degradedThreadIds` / `draft` 两个 prop 与 `cancel-comment` / `goto-gate` 两个 emit；`select` 的载荷放宽成 `string | null` 以承载 §18.1 的「`Esc` 清 `activeThreadId`」。

⭐ **`BlueprintCommentDraft` 是 115-03 `SelectionPayload` 的结构子集** —— 115-06 可以把 `SelectionPayload` 直接传进来，无需转换（刻意不 import 115-03 的产物，同波次文件隔离）。

### 2.2 `BlueprintThreadCard.vue`

```ts
props: {
  thread: BlueprintThreadDetail                // 必填
  active?: boolean; readonly?: boolean; submitting?: boolean
  degraded?: boolean                           // 越界降级（判据需块正文 ⇒ 父层算）
  gateAvailable?: boolean
}
emits: {
  select:  [threadId: string]
  answer:  [threadId: string, body: string]
  resolve: [threadId: string, reason: string]
  dismiss: [threadId: string, reason: string]
  'goto-gate': [threadId: string]
}
```

### 2.3 `BlueprintThreadComposer.vue`

```ts
props:  { options?: Array<{label?, value?, note?}>; submitting?: boolean; placeholder?: string }
emits:  { submit: [body: string] }   // 载荷已 trim
```
⭐ 自身**不接受 `readonly`** —— 它一旦出现在 DOM 里就意味着「此刻可作答」，闸在父层做成 `v-if`。

### 2.4 `BlueprintFindingActions.vue`

```ts
props: { threadId: string; submitting?: boolean }
emits: { resolve: [threadId: string, reason: string]; dismiss: [threadId: string, reason: string] }
```

### 2.5 `BlueprintSelectionPopover.vue`

```ts
props: { rect: DOMRect | null; canComment?: boolean }   // rect === null ⇒ 关闭
emits: { comment: []; copy: []; dismiss: [] }
```

### 2.6 `BlueprintReviewActions.vue`

```ts
props: { currentStatus: string; revisionRound?: number; submitting?: boolean }
emits: { approve: []; reject: [] }   // approve 已在组件内过了二次确认
```

### 2.7 `BlueprintRejectDialog.vue`

```ts
props: { open: boolean; revisionRound?: number; presetAnchor?: BlueprintRejectAnchor | null; submitting?: boolean }
emits: { 'update:open': [boolean]; submit: [payload: BlueprintRejectPayload] }

export interface BlueprintRejectAnchor  { blockId: string; startOffset: number; endOffset: number; quotedText: string }
export interface BlueprintRejectPayload {
  comment: string                      // 已 trim、恒非空
  anchor?: { block_id: string; start_offset: number; end_offset: number; quoted_text: string }  // ⭐ 已是后端入参的蛇形键
}
```
⭐ **`submit` 的载荷可以直接喂给 `rejectBlueprint(artifactId, payload)`**，⛔ 115-06 不需要再做键名转换。

### 2.8 `BlueprintBlockedDialog.vue`

```ts
props: { open: boolean; threadIds?: string[]; threads?: BlueprintThreadDetail[] }
emits: { 'update:open': [boolean]; 'goto-thread': [threadId: string] }
```
点条目会**先 emit `goto-thread` 再 emit `update:open(false)`**，父层负责：打开侧栏 → 设 `activeThreadId` → 正文滚动定位。

### 2.9 `BlueprintQualityPanel.vue`

```ts
props: { quality: BlueprintQuality; hasKeyConclusions?: boolean }   // 默认 true
emits: 无
```
`hasKeyConclusions` 由父层判定：`current_state_analysis` / `repo_associations` / `impact_analysis` 三处**是否至少一处非空**。

### 2.10 `BlueprintVersionSwitcher.vue`

```ts
props: { versions?: BlueprintVersionEntry[]; currentVersionId?: string | null }
emits: { change: [versionId: string]; compare: [baseVersionId: string] }

export interface BlueprintVersionEntry {
  id: string; version_no: number; produced_by_ref: string
  is_current: boolean; supersedes_id: string | null; created_at: string
}
```
⭐ 结构与既有 `deliveryArtifacts.ArtifactVersionTimelineEntry` **兼容** —— 父层把 `getArtifactTimeline(artifactId).versions` 直接传进来即可（**零新端点**）。

### 2.11 `BlueprintBlockDiff.vue`

```ts
props: { baseDoc: BlueprintDocumentResponse; targetDoc: BlueprintDocumentResponse; mode?: 'inline' | 'split' }
emits: { 'update:mode': ['inline' | 'split'] }   // ⭐ 声明面只有这一项，零写动作
```

---

## 3. ⭐ 接线契约（给 115-06 的六个动作端点处理规则）

### 3.1 通则（⛔ 不做乐观更新）

任何动作端点 2xx 后：**以响应体的 `current_status` 为准**写回展示态，并 `invalidateQueries({ queryKey: ['blueprint'] })` 前缀失效重取。⛔ 前端不得自行推断下一状态（114-REVIEW MJ-01 第二点）。**本 plan 的组件一律只 emit，不发请求、不持有服务端态。**

### 3.2 `answer/` 的 `reflow.status` 五档 toast 分档表（⛔ 任何分支都不是错误态）

| `reflow.status` | toast | i18n 键 | 附加动作 |
|---|---|---|---|
| `applied` | success | `review.answerApplied`（插值 `version_no`） | 重取正文 |
| `unchanged` | info | `review.answerUnchanged` | — |
| `noop` | info | `review.answerUnchanged` | 幂等，⛔ 不重复提交 |
| `conflict` | warning | `review.answerConflict` | 列出 `conflict_block_ids` |
| `failed` / `invalid` | warning | `review.answerFailed` | — |

⭐ **端点恒 200**，`reflow.status` 只决定语气。⛔ 任何分支都不得渲染成红色错误态或回滚 UI。

### 3.3 状态码分档

| 场景 | 处理 |
|---|---|
| approve **409 `blocked`** | 用响应体的 `unresolved_blocker_thread_ids` 打开 `BlueprintBlockedDialog`；接住 `goto-thread` → 开侧栏 + 设 `activeThreadId` + 正文滚动 |
| approve **409 `conflict`** | toast `destructive` + 回显 `detail` + 「刷新重试」→ `invalidateQueries(['blueprint'])` |
| reject **409 `conflict`** | toast 回显 `error.conflictVersion`（插值响应体的 `version_no`）+ 自动 `invalidateQueries(['blueprint'])` |
| **400** | 原样回显 `ApiError.detail`，就近渲染（表单内联优先于 toast），⛔ 不改写 |
| **404** | 唯一一句 `error.notFoundOrForbidden`，⛔ 不拆成两种文案 |
| resolve/dismiss **200 `noop`** | 幂等（首次结论不被覆盖）⇒ info toast + 重取，⛔ 不当失败 |

### 3.4 历史版本模式

`BlueprintVersionSwitcher` emit `change` 后，页面改 `?version=`；**非 current 版本时**由页面渲染常驻提示条（`version.historyNotice` + `version.backToCurrent`），并让本 plan 的**全部写动作组件不渲染**（把 `readonly` 置真即可关掉作答框与选区评论；终审/驳回/finding 处置三处由页面 `v-if` 掉整块）。

---

## 4. ⭐ 变异验证（执行期实跑，六条断言各自被逼红）

每条变异后都 `git checkout --` 还原并核实工作树干净。

| # | 变异 | 结果 | 负向对照 |
|---|---|---|---|
| MUT-1 | `BlueprintThreadCard` 的 finding 分支里也塞一个 `BlueprintThreadComposer` | **1a / 1c 转红**（`2 failed \| 22 passed`） | 2c、断言 5/11 仍绿 ✅ |
| MUT-2 | finding 分支加 `&& !readonly`（把处置也关掉） | **2c 转红**（`1 failed \| 23 passed`） | 1a、2a 仍绿 ✅ |
| MUT-3 | 侧栏对失锚组加 `.filter(t => t.anchor?.block_id)` | **断言 5 转红**（`1 failed \| 23 passed`） | 断言 11 仍绿 ✅ |
| MUT-4 | `BlueprintBlockedDialog` 只保留一句说明、不渲染清单 | **3a / 3b / 3c 转红**（`3 failed \| 16 passed`） | 质量三态仍绿 ✅ |
| MUT-5 | 质量面板把空值合并成零 | **7a 转红、7b（`0` 那条）仍绿**（`1 failed \| 18 passed`） | ⭐ 正是要逮的陷阱形状 |
| MUT-6 | `sidebarGroups` 去掉前三组的「排除失锚」否定项（改 115-02 的纯函数） | **断言 11 转红**（`1 failed \| 23 passed`） | 断言 5 仍绿 ✅ |

⭐ **MUT-5 的形状最值得记**：把 `null` 归一成 0 后，「`null` 用例」转红而「`0` 用例」仍绿 —— 三态并列用例的存在理由就在这里，只写其中一条都逮不住。

---

## 5. §20 断言 → 绿色用例名映射表

| 断言 | 用例 | 变异 | 会转红？ |
|---|---|---|---|
| 1 | `1a. ai_review_finding ⇒ 作答框不存在于 DOM，只有处置按钮`；`1b`（三类参数化反向）；`1c` | finding 也渲成可回复 | ✅ MUT-1 |
| 2 | `2a`（作答框不存在于 DOM）/ `2b`（选区「发起评论」不存在）/ `2c`（**finding 处置仍在**）/ `2d`（反向） | 改成 disabled；把 finding 处置也关掉 | ✅ MUT-2 |
| 3 | `3a`（条目数 == 3，含查不到的那条）/ `3b`（emit `goto-thread` + 关弹窗）/ `3c`（负向对照：不只一句说明） | 只渲染一句「不可确认」 | ✅ MUT-4 |
| 5 | `5. orphanedThreads 直接渲染不二次过滤（含一条无 anchor 的系统线程）` | 加 `.filter(t => t.anchor?.block_id)` | ✅ MUT-3 |
| 7 | `7a`（`null` ⇒ 暂无数据且不含 0）/ `7b`（`0` ⇒ 含 0 且不含暂无数据）/ `7c`（正值）/ `7d`（百分比） | 空值合并成零 | ✅ MUT-5（7a 红、7b 绿） |
| 11 | `11. open 且 orphaned 的线程：四组总数 == 线程总数，且只在失锚组` | 去掉前三组的排除失锚否定项 | ✅ MUT-6 |

---

## 6. 关键实现决断

### 6.1 ⭐ kind 硬分流的落地形态（本 plan 头号靶子）

`BlueprintThreadCard.vue` 的模板里是两条**物理互斥**的兄弟分支：

```html
<div v-if="isFinding">  <BlueprintFindingActions ... />  </div>
<div v-else>            <BlueprintThreadComposer v-if="!readonly" ... />  </div>
```

三层防线：① 渲染层互斥（⛔ 不是 `v-show`、⛔ 不是 `disabled`）；② 源码级早期兜底（三条 `node -e` 断言，含「必须用 `v-if` 不是 `v-show`」与「finding 那一个标签内不得带 `v-if="!readonly"`」）；③ **真正的防线是 §20 断言 1/2 的用例**，已由 MUT-1 / MUT-2 证明能转红。

⚠️ **`v-else-if="!readonly"` 是不行的**（会同时破坏可读性与源码断言）：`v-else` 里再嵌一个 `v-if="!readonly"` 才让「finding 不受闸约束」这件事在模板上一眼可见。

### 6.2 ⭐ `readonly`（不渲染）与终审（disabled+Tooltip）的刻意不对称

| 面 | 形态 | 理由 |
|---|---|---|
| 作答框 / 选区「发起评论」 | **不存在于 DOM** | 渲染一个必撞 400 的写入口 = 把用户送进死路 |
| finding 处置 | **不受闸约束，恒渲染** | 后端未对 `resolve/` `dismiss/` 加状态闸，且那是超界死锁的唯一正向出口 |
| 终审通过 / 驳回 | **`disabled` + Tooltip** | 按钮的存在本身有信息量（告诉人「这里将来能做什么」） |

三者各有用例，⛔ 后人不要「统一」它们。

### 6.3 侧栏两数据源合并

前三组来自 `threads/`，第四组来自快照的 `orphaned_threads`。合并规则落在 `mergedOrphaned`：**按 `thread_id` 用 `threads/` 的条目覆盖快照条目**（它带多轮消息与 `options`），查不到时用快照条目占位。⛔ 这一步不做任何锚点维度的过滤。

四组判据一律调 `sidebarGroups(visibleThreads, visibleOrphaned)`，组件内**零判据**——连模板里都没有锚定态的字面量比较（改用 `isOrphanGroup` / `isClosedGroup` 字段），源码扫描 `=== 'orphaned'` 在该文件零命中。

### 6.4 A3 假设正式 settle

`blockDiff.spec.ts` **真实 import `diff` 包、⛔ 不 mock**（`vi.mock('diff')` 零命中），用例 3「modified 块渲染出 `.diff-added` / `.diff-removed` / `.diff-unchanged` 三类片段」跑绿。
⇒ **A3 settle：`diffWords` 与 `diffLines` 同包同族，返回同构 `Change[]`（`{value, added?, removed?, count}`）**，`filter(c => !c.added)` / `filter(c => !c.removed)` 的视角切分对它同样成立（用例 4a 正负成对断言）。

### 6.5 `PopoverAnchor` 的实测结论

`node -e "require('reka-ui').PopoverAnchor"` → **`object`（reka-ui 2.9.10 确实导出）** ⇒ **无需降级到 `PopoverTrigger` 方案**，`pnpm type-check` 亦 exit 0。
⛔ 本地 barrel `~/components/ui/popover/index.ts` 只导出 `Popover` / `PopoverContent` / `PopoverTrigger`，**未为此改动它**（那会是第七处既有文件修改）。容器与内容仍用本地 wrapper，只有 `PopoverAnchor` 从 `reka-ui` 直取——与本地 wrapper 自身的写法同源。

### 6.6 `data-testid` 完整清单（本 plan 新增 20 个）

| 组件 | testid |
|---|---|
| 侧栏 | `blueprint-thread-sidebar` / `blueprint-thread-group-{open\|answered\|closed\|orphaned}` / `blueprint-kind-chip` / `blueprint-show-closed` / `blueprint-thread-empty` / `blueprint-thread-draft` / `blueprint-thread-draft-input` / `blueprint-thread-draft-submit` |
| 线程卡 | `blueprint-thread-card`（卡根，计数按它）/ `blueprint-thread-card-select`（选中区 `<button>`，`↑`/`↓` 按它移动焦点）/ `blueprint-thread-message` / `blueprint-thread-orphaned` / `blueprint-thread-degraded` / `blueprint-thread-goto-gate` |
| 作答框 | `blueprint-thread-composer`（⭐ 断言 1/2 的定位点）/ `blueprint-thread-composer-input` / `blueprint-thread-composer-submit` / `blueprint-thread-option` |
| finding | `blueprint-finding-actions`（⭐ 断言 2c）/ `blueprint-finding-resolve` / `blueprint-finding-dismiss` / `blueprint-finding-reason-dialog` / `blueprint-finding-reason-input` / `blueprint-finding-reason-submit` |
| 选区 | `blueprint-selection-popover` / `blueprint-selection-comment`（⭐ 断言 2b）/ `blueprint-selection-copy` |
| 终审 | `blueprint-review-approve` / `blueprint-review-reject` |
| 驳回 | `blueprint-reject-dialog` / `blueprint-reject-comment` / `blueprint-reject-submit` / `blueprint-reject-anchor` / `blueprint-reject-keep-anchor` |
| 409 | `blueprint-blocked-dialog` / `blueprint-blocked-item`（⭐ 断言 3） |
| 质量 | `blueprint-quality-panel` / `blueprint-quality-metric`（配 `data-metric`）/ `blueprint-quality-no-key-conclusions` |
| 版本 | `blueprint-version-switcher` / `blueprint-version-item` / `blueprint-version-reason` / `blueprint-version-compare` |
| diff | `blueprint-diff` / `blueprint-diff-summary` / `blueprint-diff-mode-inline` / `blueprint-diff-mode-split`；块级 `data-diff-block` + `data-diff-kind`；段级 `data-diff-section`；`data-diff-excluded="true"`；分栏 `data-diff-column="left\|right"` |

---

## 7. ⚠️ 回报给 115-06 的 i18n 缺口（5 个键，⛔ 本 plan 按 §13.2 未自补）

i18n 三处追加点已由 115-02 一次做完并对本相位关闭 ⇒ **回报而不自补**（沿用 115-03 §9 的判例）。五处都有**可用的降级实现**，补键后各只需换一处 `t()` 调用，**无结构改动**。

| 建议键 | 建议文案 | 用在哪 | 当前降级 |
|---|---|---|---|
| `review.disabledReason` | 当前状态为「{status}」，需等待进入待人类审查 | 终审按钮 Tooltip（UI-SPEC §11.1 要的是带插值的版本） | 用无参的 `review.disabledReadonly` + 状态中文名两段并列 |
| `review.rejectKeepAnchor` | 保留此划线 | 驳回弹窗的锚点开关标签 | 用 `annotation.quotedSnapshot`（「引用时的原文快照」）作标签 |
| `quality.noKeyConclusions` | 无关键结论 | 引用覆盖率格的旁注徽标 | 用 `sectionEmpty` 拼三个段名 ⇒「本方案未涉及现状分析 / 仓库关联 / 影响范围」（**恰是该条件的字面含义**，全部走 `t()`） |
| `thread.draftCancel` | 取消 | 侧栏草稿卡的取消按钮 | **不渲染可见按钮**，改为焦点在草稿卡内按 `Esc` 放弃草稿（并 emit `cancel-comment`） |
| `diff.mustHavesExcluded` | 验收锚点不参与块级对比 | diff 的 `must_haves` 占位行 | 身份由 `data-diff-excluded="true"` 承载，可见文案退化为「本段无变化」徽标 |

⚠️ **不是 safelist 缺口**：本 plan 运行期拼接的图标只有版本原因五档（`user-pen` / `refresh-cw` / `shield` / `undo-2` / `sparkles`）与空态的 `messages-square`，**全部已在 `main.css` 的 `@source inline` 里**。写在模板里的字面量完整类名按 115-02 §8.2 的纪律**不需要** safelist。

---

## 8. Task Commits

| Task | 内容 | Commit | 变更 |
|---|---|---|---|
| 1 | 线程侧栏四件与选区浮层，按 kind 在渲染层硬分流 | `e3e09381` | 5 文件 / +1002 |
| 2 | 人审终审四件，approve 409 给出可点跳转的解药清单 | `4ce29602` | 4 文件 / +558 |
| 3 | 版本切换与 block 级 diff，并为 §20 六条断言补齐可证伪用例 | `43632326` | 6 文件 / +1410 |

---

## 9. Deviations from Plan

### 1. `[Rule 1 - 非法 DOM] 线程卡的选中区与内容区拆成兄弟节点`

- **发现于**：Task 1
- **问题**：PLAN 要求「卡片本体是 `<button>`，内含头部 / 消息列表 / 动作区」。但 `<button>` 的内容模型是 phrasing content —— 把 `Textarea`、处置按钮、`<ul>`、`<pre>` 塞进去既是非法 DOM，**也会让点输入框连带触发外层按钮**（嵌套交互控件的经典症状）。
- **处理**：卡根改为 `<div data-testid="blueprint-thread-card">`（计数与测试仍按它定位），内含一个只放徽标行的 `<button data-testid="blueprint-thread-card-select">` 承担选中与焦点（侧栏 `↑`/`↓` 也按它移动），消息列表 / 引文快照 / 动作区作为它的**兄弟节点**。§18.1 的「线程卡为 `<button>`、可 Tab、`Enter`/`Space` 触发」在选中区上完整成立。
- **文件**：`BlueprintThreadCard.vue` ｜ **Commit**：`e3e09381`

### 2. `[Rule 2 - 契约缺口] 线程卡与侧栏各加两个 prop`

- **发现于**：Task 1
- **问题**：① 越界降级的判据是 `isValidAnchor(anchor, blockText.length)`，**需要块正文**，而线程卡只拿得到线程；② 草稿卡需要选区数据，而 PLAN 的 props 表里没有承载它的字段。
- **处理**：线程卡加 `degraded?: boolean` / `gateAvailable?: boolean`；侧栏加 `degradedThreadIds?: string[]` / `draft?: BlueprintCommentDraft | null`，并新增 `cancel-comment` / `goto-gate` 两个 emit。全部有默认值，115-06 可按需接。
- **Commit**：`e3e09381`

### 3. `[§13.2 回报而不自补] 五处 i18n 缺口`

- 详见 §7。五处都有可用降级，⛔ **未修改 `zh-CN.json`**（`git diff` 为空）。

### 4. `[Rule 3 - 阻塞] 相对时间退化为本地化绝对时间`

- **发现于**：Task 1
- **问题**：UI-SPEC §7.7 / §9.1 要「相对时间」，但仓内**没有共享的相对时间工具**（`src/utils/` 只有 5 个文件，均与时间无关），`knowledge.blueprints.*` 也没有相对时间单位的文案键。自造一套要么硬编码中文单位（违反 i18n 纪律），要么新增依赖（违反零新增依赖）。
- **处理**：`formatTime()` 用 `toLocaleString('zh-CN', { hour12: false })`，非法输入原样返回。线程卡与版本切换器同款处理。
- **Commit**：`e3e09381` / `43632326`

### 5. `[判据澄清] kind 筛选对失锚组同样生效`

- **性质**：PLAN 禁的是「按**锚点字段**对 `orphaned_threads` 做隐式二次过滤」（那会把真失锚滤掉）。顶部工具条的 kind 多选是**用户显式动作**，§7.7 也没把失锚组排除在外 ⇒ 对四组一视同仁地生效。
- **核实**：源码扫描 `orphanedThreads[\s\S]{0,80}\.filter\(` 零命中；§20 断言 5 的用例在默认（空筛选）下断言「失锚组条数 == `orphanedThreads.length`」，MUT-3 证明加锚点过滤会转红。
- **文件**：`BlueprintThreadSidebar.vue` ｜ **Commit**：`e3e09381`

### 6. `[Rule 1 - 自洽修正] 三处 docstring 字面量会触发本 plan 自己的验收断言`

- **发现于**：Task 2 / Task 3 的验收复跑
- **问题**：验收要求若干 token 在特定文件零命中，而我在 docstring 里为了说明「⛔ 不要用它」恰好写了这些字面量：`useConfirmDialog`（`BlueprintRejectDialog`）、`deep: true`（`BlueprintBlockDiff`）；Task 1 亦按同一纪律全程避开 `v-html` 字面量。
- **处理**：改写成不含该字面量的等义中文表述（语义不变，纪律说明保留）。与 115-02 §12.3、115-03 Deviation 5 **同一类**。
- **Commit**：`4ce29602` / `43632326`

### 7. `[执行事实登记] components.d.ts 是本 plan 唯一的既有文件改动`

- **性质**：`unplugin-vue-components` **自动生成**的声明文件，随新建组件自动重写。本次为**纯追加 11 行、零删除**（11 个新组件的类型声明），且被 eslint ignore。
- **判断**：与 115-02 §12.4、115-03 Deviation 8 同一判例 —— CREATE-ONLY 约束针对**手写源文件**。`auto-imports.d.ts` 本 plan **未变动**（新组件全部走显式 import）。

### 8. `[环境事实] pnpm 10 的 workspace 漂移本次未出现`

- 全程多次 `pnpm exec vitest` / `type-check` / `eslint` 后 `git diff web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml` **零行**。后续 plan 仍应保留这项检查（115-02 §12.7）。

---

## 10. ⭐ UAT 清单（happy-dom 测不了的，交给人工走查）

| # | 项 | 为什么自动化测不了 | 期望 |
|---|---|---|---|
| 1 | **选区浮层的实际落点与跟随** | happy-dom 无布局引擎，`getBoundingClientRect` 恒 0 矩形 | 拖选后浮层贴着选区上方 8px、不出视口、滚动时跟随；虚拟锚点的 `pointer-events: none` 不挡正文选择 |
| 2 | **选区浮层的焦点语义** | 无真实焦点管理与选区对象 | 浮层出现后**焦点不被抢走**（选区不消失）；`Tab` 能进入；`Esc` 关闭且**选区仍在** |
| 3 | **终审 Tooltip 的悬停呈现** | Tooltip 走 Portal + 悬停延迟，测试里被 stub 拍平 | 悬停 disabled 的「通过方案」能看到「当前状态下不可执行该操作 · {状态中文名}」 |
| 4 | **diff 三色的对比度与可辨识度** | 无渲染引擎，只能断言类名 | 浅色/深色主题下 `.diff-added` / `.diff-removed` 都能看清；`removed` 的 `line-through` 不影响可读 |
| 5 | **侧栏 `↑`/`↓` 键盘导航** | happy-dom 的焦点模型不完整 | 焦点在某组的线程卡上时 `↑`/`↓` 只在**同组内**移动，跨组不越界 |
| 6 | **`Esc` 的两种语义** | 同上 | 焦点在草稿卡内 ⇒ 放弃草稿；在别处 ⇒ 清选中态且**侧栏不关闭** |
| 7 | **两个受控 Dialog 的初始焦点** | `@open-auto-focus` 在 stub 下不触发 | 打开 finding 理由弹窗 / 驳回弹窗时，光标直接落在 `Textarea` 而不是关闭按钮 |
| 8 | **触控目标与焦点环** | 无字体度量与布局 | 选区浮层两个按钮 ≥44px；Tab 到它们时有不透明 teal 焦点环（3.74:1） |
| 9 | **草稿卡缺少可见「取消」** | 属文案缺口而非行为缺陷 | 确认 `Esc` 放弃草稿这条路径够不够用；补 i18n 键后应改回可见按钮（§7） |

---

## 11. 边界核算

| 检查 | 结果 |
|---|---|
| 本 plan 变更文件 | **14 个新建 + 1 个生成物**（`components.d.ts`，+11 行 / −0） |
| `git diff --name-only <base>..HEAD -- web/src \| rg -v "^web/src/components/blueprint/"` | 只有 `web/src/components.d.ts`（生成物，见 Deviation 7） |
| 四个禁改文件（`TechPlanCard.vue` / `RoutingDecisionPanel.vue` / `NodeDataTab.vue` / `ArtifactTimeline.vue`） | **`git diff` 全空** |
| 115-02 三处追加点（`zh-CN.json` / `main.css` / `api/index.ts`） | **`git diff` 全空** |
| 115-03 所有权文件（`BlueprintBlock.vue` / `BlueprintBlockList.vue` / `BlueprintCitationChip.vue` / `CitationPreviewDialog.vue` / `citation/**` / `annotationTokens.ts` / `BlueprintStatusBadge.vue`） | **一个都未修改、未 import** |
| `git diff --name-only <base>..HEAD -- server/` | **0 个文件** |
| `git diff web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml` | **0 行**（零新增依赖） |
| 原始 HTML 注入指令 | 扫描面零命中（源码守卫断言 6 绿） |
| `rg -n "refetchInterval\|edit-block\|edit-blocks\|editBlocks" src/components/blueprint/` | 源码零命中（只有 115-03 测试文件里一处断言字符串，`__tests__` 不在扫描面） |
| `rg -n "@floating-ui/vue\|useFloating\|codemirror" src/components/blueprint/` | **零命中** |
| `rg -l "hsl(" src/components/blueprint/ \| rg -v "annotationTokens.ts\|BlueprintBlockDiff.vue"` | **为空**（颜色只有两个合法出处） |
| 源码守卫扫描面 | **22 个文件**，6 条断言全绿 |

---

## 12. 给 115-06 / 115-07 的四条注意

1. **组件只 emit，不发请求**。六个动作端点的调用、`invalidateQueries`、toast 分档全部归页面（§3 是逐档契约表）。⛔ 不要在组件里加请求，那会让 `readonly` / 历史版本两条闸各出现两份判据。
2. **`BlueprintRejectDialog` 的 `submit` 载荷已经是后端入参形状**（`anchor` 用蛇形键），直接喂 `rejectBlueprint(artifactId, payload)`。
3. **`BlueprintBlockedDialog` 的 `goto-thread` 是超界死锁的唯一出口**，务必接住并完成「开侧栏 → 设 `activeThreadId` → 正文滚动」三步；只关弹窗等于把用户又锁回去。
4. **五个 i18n 键待补**（§7）。补之前请先读那一节的降级说明——五处都能正常工作，⛔ 不要当成 bug 去改组件结构。

---

## Self-Check: PASSED

**创建的 14 个文件全部存在**——`BlueprintThreadComposer.vue` / `BlueprintFindingActions.vue` / `BlueprintThreadCard.vue` / `BlueprintThreadSidebar.vue` / `BlueprintSelectionPopover.vue` / `BlueprintReviewActions.vue` / `BlueprintRejectDialog.vue` / `BlueprintBlockedDialog.vue` / `BlueprintQualityPanel.vue` / `BlueprintVersionSwitcher.vue` / `BlueprintBlockDiff.vue` / `__tests__/threadSidebar.spec.ts` / `__tests__/reviewActions.spec.ts` / `__tests__/blockDiff.spec.ts`，逐个 `[ -f ]` 命中。

**三个 commit 全部在 `git log`**：`e3e09381` / `4ce29602` / `43632326`。

**门禁实跑**：vitest **1565 passed / 1 skipped**（基线 1507 / 1，**+58 零回归**）、type-check **exit 0**、`eslint src/components/blueprint/` **0 problems**（零新增）。

**变异验证实跑**：六条变异（MUT-1…MUT-6）分别把 §20 断言 1 / 2 / 5 / 3 / 7 / 11 的用例逼红，负向对照全部保持绿；每次变异后 `git checkout --` 还原并核实工作树干净。

**边界核算**：四个禁改文件、115-02 三处追加点、115-03 的 11 个产物 `git diff` 全空；`server/` 零改动；依赖零行变更；颜色字面量只出现在 `BlueprintBlockDiff.vue` 的 scoped style 里。
