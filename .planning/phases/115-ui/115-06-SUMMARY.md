---
phase: 115-ui
plan: 06
subsystem: blueprint-viewer-page-and-entries
tags: [frontend, vue3, routing, anchor-nav, error-grading, i18n-handoff, mutation-tested, append-only]
requires:
  - "115-02 地基：`~/types/blueprint`、`~/api/blueprints`、`~/api/deliveryArtifacts`、`~/config/blueprintStatus`、`~/utils/blueprintBlocks`、`~/stores/useBlueprintViewerStore`、`~/composables/{useBlueprintLive,useBlueprintAnnotations,useCitationPreview}`、i18n 子树、源码守卫 spec"
  - "115-03：`BlueprintBlockList`（`SelectionPayload`）、`CitationPreviewDialog`"
  - "115-04：11 个写路径组件与 §3 接线契约（六动作响应处理 + reflow 五档）"
  - "115-05：十段组件的 props/emits、跨段锚点 `fp-<id>` / `api-<id>`、各段空态规则"
  - "既有件：`AnchorNavLayout`（两栏布局 + mount-only 观察）、`PageContainer`、`CompactEmptyState`、`ui/{select,sheet,scroll-area,pagination,skeleton,switch,collapsible,separator}`、`useToast`"
provides:
  - "`web/src/pages/knowledge/blueprints/[id].vue`（约 900 行）—— 查看器路由页：六 query 双向同步与一次性消费 / 三栏装配 / ⭐ 十段无条件渲染 / 错误四档含两条例外 / 六动作接线 / gate 挂载点预留"
  - "`web/src/components/blueprint/BlueprintViewerHeader.vue` —— sticky 顶栏（11 态徽标 + 三计数 + 版本切换 + 阅读区开关 + 终审区透传）"
  - "`web/src/components/blueprint/BlueprintSectionNav.vue` —— 仅 `< md` 的段跳转下拉"
  - "`web/src/components/blueprint/BlueprintErrorState.vue` —— 错误三档（404 单一中性文案 / 400 就近回显 / 5xx 重试）"
  - "`web/src/components/blueprint/BlueprintStageTimeline.vue` —— 八节点 × 四态，payload 只渲染标量"
  - "`web/src/components/common/FilterBar.vue` —— 按 `web/DESIGN.md:198-211` 契约补上的通用筛选容器"
  - "`web/src/components/knowledge/BlueprintsTabPanel.vue` / `BlueprintListCard.vue` —— 列表面板与深链卡"
  - "`web/src/components/project/warroom/ProjectBlueprintsCard.vue` —— 项目侧只读蓝图卡"
  - "两个页面测试共 **16 例**：`blueprintViewer.spec.ts`(9) / `blueprintsTab.spec.ts`(7)"
  - "i18n **69 个新叶子键（0 删除 / 0 修改）**：其中 42 个是 115-03/04/05 回报的缺口，27 个是本 plan 自身所需"
affects:
  - "115-07 确认门：在本页 `blueprint-gate-mount` 挂载点做一次纯追加即可，详见 §8"
  - "⭐ 115-03/04/05 的 12 个组件已把降级渲染换回真实 i18n 键，⛔ 后续不要再当成「缺口」处理"
  - "SC-1 / SC-2 / SC-3 / SC-4 / SC-5 首次在界面上可达：111–114 的十五个端点有了人能点到的入口"
tech-stack:
  added: []
  patterns:
    - "query ↔ ref 双向同步做成一个泛型 `useQueryParam(key, normalize)`：写回一律 `router.replace({ query: { ...route.query, key } })` 展开写法，空值直接摘掉参数"
    - "段容器无条件渲染 + 段内三态：把「有没有数据」的判断全部下沉到容器内部，容器本身对数据零依赖"
    - "自证伪的深链消费：`?thread=` / `?panel=` 各配一个 `consumed` 闸，执行一次等效动作后把 query 摘掉"
    - "生成物声明文件按字典序**手工增行**：构建会顺带裁剪一批与本次无关的既有条目，直接提交等于夹带删除"
key-files:
  created:
    - web/src/pages/knowledge/blueprints/[id].vue
    - web/src/components/blueprint/BlueprintViewerHeader.vue
    - web/src/components/blueprint/BlueprintSectionNav.vue
    - web/src/components/blueprint/BlueprintErrorState.vue
    - web/src/components/blueprint/BlueprintStageTimeline.vue
    - web/src/components/common/FilterBar.vue
    - web/src/components/knowledge/BlueprintsTabPanel.vue
    - web/src/components/knowledge/BlueprintListCard.vue
    - web/src/components/project/warroom/ProjectBlueprintsCard.vue
    - web/src/pages/knowledge/__tests__/blueprintViewer.spec.ts
    - web/src/pages/knowledge/__tests__/blueprintsTab.spec.ts
  modified:
    - web/src/locales/zh-CN.json
    - web/src/pages/knowledge/index.vue
    - web/src/components/project/warroom/ProjectMaterialsPanel.vue
    - web/src/components/blueprint/RequirementSpecSection.vue 等 12 个 115-03/04/05 组件（仅 i18n 换回）
    - web/src/components/blueprint/__tests__/sections.spec.ts
    - web/src/components/blueprint/__tests__/reviewActions.spec.ts
    - web/src/typed-router.d.ts
    - web/src/components.d.ts
decisions:
  - "⭐ 对 UI-SPEC §6.9 的订正：`must_haves` / `decision_log` 无内容时**段容器与导航项仍渲染**，只是段内不出内容（理由 P-4）"
  - "⭐ 对 UI-SPEC §9.2 的订正：diff 视图下十段容器**仍在**（段内不出内容），⛔ 不「替换正文区」——容器无条件渲染优先"
  - "仓内没有 `ui/alert`：历史版本与只读提示改用带语义描边的 `div` + `role=\"status\"`，⛔ 不新建 alert 组件（那是通用件，超出本 plan 边界）"
  - "顶栏删掉 PLAN 列的 `snapshot` prop（零消费的死接口），新增 `open-annotations` emit（窄屏抽屉与 xl 折叠是两个目标）"
  - "`TABS` 用 `TABS.push('blueprints')` 追加而不改写既有那一行，换来两处追加点的删除行严格为 0"
  - "生成物 `components.d.ts` 手工按字典序增 4 行：`vite build` 的重写会顺带裁掉 29 条既有条目"
metrics:
  duration: "约 2.5 小时"
  completed: 2026-08-01
  tasks: 3
  commits: 5
  tests_added: 16
---

# Phase 115 Plan 06: 查看器路由页 / 知识库 tab / 项目物料卡 Summary

**一句话**：把前四个 plan 的零件装配成**用户真正能打开的两个面** —— 9 个新建组件与页面（约 2200 行）+ 2 个页面测试（**16 例全绿**）+ 两处**零删除行**的宿主追加 + **69 个 i18n 键的一次性补齐**，让 111–114 的十五个端点第一次有了人能点到的入口。全相位「会静默假通过」清单里最隐蔽的一条（P-4：段容器条件渲染会让左栏高亮永久失效，而点击跳转照常工作）被**物理堵死并用真实变异证明可证伪**；两条错误分档特例（404 不泄露存在性、确认门非 200 不进分档）各有一条形状正确的用例。**零新增依赖、后端零改动、四个禁改文件 `git diff` 全空。**

---

## 1. 门禁与基线（对比 115-05 的 1602/1）

| 门 | 结果 | 对比基线 |
|---|---|---|
| `pnpm exec vitest run` | **1618 passed / 1 skipped（1619 例，212 文件）** | 基线 1602 / 1（210 文件）⇒ **+16 例 / +2 文件，零回归** |
| `pnpm type-check`（`vue-tsc --noEmit`） | **通过（exit 0）** | 同基线 |
| `pnpm lint`（`eslint .`） | **111 problems（106 errors / 5 warnings）** | ⭐ **与基线逐个相同 ⇒ 零新增** |
| `pnpm build`（`vue-tsc -b && vite build`） | **通过（✓ built in 5.4s）** | 新页面进得了路由与打包 |
| 源码守卫 `blueprint-source-guard.spec.ts` | **6 条全绿**，扫描面 36 → **41 个文件** | 三条断言在完整代码面下生效 |

那 1 条 skip 是**既有**的 `src/layouts/__tests__/default.spec.ts:66`。lint 判据沿用 115-02 §1 的结论：「自己碰的文件零新增问题」，⛔ 不是整体退出码为 0。

新增用例分布：

| 文件 | 例数 | 锁住什么 |
|---|---|---|
| `pages/knowledge/__tests__/blueprintViewer.spec.ts` | 9 | ⭐ P-4 十段无条件渲染 / badge 空串 / 404 单文案 / gate 非 200 不报错 / 409 blocked 解药面板 / reflow `noop` 不当失败 / 零乐观更新 / 生成中增量 / 历史版本只读 |
| `pages/knowledge/__tests__/blueprintsTab.spec.ts` | 7 | 深链直达 / 消费 `current_status` / 阻塞计数正反并列 / 筛选写回且保留 `tab` / 搜索输入提交分离 / 五键分页 / 空态裸图标名 |

### ⭐ 变异验证（执行期实跑）

给第一个段容器加 `v-if="content"`（P-4 的实例形状）→ 复跑 `blueprintViewer.spec.ts`：

```
× 1. doc 查询还在 loading 时，section[id] 计数就已经是 10
     Tests  1 failed | 8 passed (9)
```

**转红，且只有那一条红** —— 其余八条（含「gate 404 不报错」「404 单文案」）保持绿，说明断言没写串。变异后 `git checkout --` 还原并核实工作树干净。

---

## 2. ⭐ 查看器路由页的完整契约

### 2.1 路由与六个 query

| 项 | 值 |
|---|---|
| 文件 / 路径 | `web/src/pages/knowledge/blueprints/[id].vue` → `/knowledge/blueprints/:id`（`:id` = `artifact_id`） |
| 类型化 route | `useRoute('/knowledge/blueprints/[id])`；`src/typed-router.d.ts` 由 unplugin 重新生成（**+15 行 / −0**） |
| 标题 | `useHead({ title: t('knowledge.blueprints.pageTitle') + ' - Friday AI' })`。⛔ **不用 `definePage` 承载 i18n key** —— `layouts/default.vue` 把 `route.meta.title` 原样渲染进 `<h1>`，传 key 会让页面标题印出键名 |

| query | 取值 | 语义 | 一次性消费？ |
|---|---|---|---|
| `version` | version_id | 查看历史版本；缺省 = current | 否（常驻） |
| `diff` | version_id | 与当前版本做 block 级 diff | 否（常驻） |
| `diff_mode` | `inline`(默认) \| `split` | diff 呈现形态 | 否 |
| `section` | 十个段 key 之一 | 进入后滚动到该段；也是窄屏下拉的回显值 | 否（位置标记） |
| `thread` | thread_id | 打开侧栏并选中该条 + 正文滚动定位 | ⭐ **是** |
| `panel` | `gate` \| `review` | 滚动到目标面板并 2s ring | ⭐ **是** |

六个都走同一个 `useQueryParam(key, normalize)`：读侧 `watch(() => route.query[key])`、写侧
`router.replace({ query: { ...route.query, [key]: value } })`（⭐ 展开写法 ⇒ `tab` / `bp_status`
等其它 query 天然保留），**空值直接从 query 里摘掉**，⛔ 不留 `?panel=` 这种空壳。
`diff_mode` 的 normalize 刻意允许返回 `''`（缺省态），否则一进页面就会往 URL 里写一个
`diff_mode=inline`。

### 2.2 `?panel=` 缺席兜底的**实际行为**

| 值 | 目标存在的条件 | 存在时 | ⭐ 不存在时 |
|---|---|---|---|
| `gate` | `gateQuery` 落到 200 | 滚动到 `#gate` + 2s ring，然后摘掉 query | **静默忽略**：不滚动、不报错、**不弹任何提示**，只摘掉 query。确认门未开启是绝对多数的正常态，为它弹提示等于把正常态渲染成异常 |
| `review` | `current_status ∈ {pending_review, confirmed}` | 滚动到 `#blueprint-quality` + 2s ring | 滚动到正文顶部 + 一条 **info** 提示 `review.panelUnavailable`，然后摘掉 query。这是用户拿旧链接来的信息缺口，静默会让人以为页面坏了 |

两者各配一个 `consumed` 闸，`{ immediate: true }` 的 watch 在依赖就绪后执行一次，刷新不重复触发。
`?thread=` 同纪律：线程数据就绪后设 `activeThreadId` + 打开抽屉 + 按 `anchor.block_id` 滚到
`blk-<id>`，然后摘掉 query。

---

## 3. ⭐ `sections` 十项逐项表（恒 10 项 / badge 传空串）

`NavSection.icon` 收**完整类名**（那个布局件直接把它拼进 `:class`）—— 与 `CompactEmptyState` /
`StatusBadge` 收裸名的契约**不同，两者都对，⛔ 不要统一**。

| # | id（= DOM `id`，静态字面量） | labelKey 尾段 | icon（完整类名） | badge 表达式 | tone |
|---|---|---|---|---|---|
| 0 | `requirement_spec` | `section.requirementSpec` | `icon-[lucide--target]` | `badgeOf('requirement_spec')` = 功能点数 | `toneOf(...)` |
| 1 | `repo_associations` | `section.repoAssociations` | `icon-[lucide--folder-git-2]` | 仓库数 | 同上 |
| 2 | `current_state_analysis` | `section.currentStateAnalysis` | `icon-[lucide--scan-eye]` | findings 总数 | 同上 |
| 3 | `implementation_overview` | `section.implementationOverview` | `icon-[lucide--layers]` | 实现项数 | 同上 |
| 4 | `api_contracts` | `section.apiContracts` | `icon-[lucide--plug]` | 接口数 | 同上 |
| 5 | `impact_analysis` | `section.impactAnalysis` | `icon-[lucide--alert-triangle]` | 受影响功能数 | 同上 |
| 6 | `interaction_flows` | `section.interactionFlows` | `icon-[lucide--workflow]` | 流程数 | 同上 |
| 7 | `must_haves` | `section.mustHaves` | `icon-[lucide--clipboard-check]` | `truths + artifacts + key_links` | 同上 |
| 8 | `decision_log` | `section.decisionLog` | `icon-[lucide--gavel]` | 条目数 | 同上 |
| 9 | `associations` | `section.associations` | `icon-[lucide--link]` | 引用池条数 + 有项目则 +1 | 同上 |

- ⭐ **`badgeOf(key)` 恒返回字符串**：`count > 0 ? String(count) : ''`。那个布局件的空值判定是
  `badge !== undefined && badge !== null && badge !== ''` —— **它不排除 `0`** ⇒ 传数字 0 会渲染出
  一个灰色的 `0`，被读成「有一项待办」（P-18）。用例 2 逐个断言八个零内容段的 badge **=== `''`**，
  同时断言有内容那段是 `'1'`（只断言空串会漏掉「全都不显示」的假通过）。
- **`toneOf(key)` 规则**：段内存在「`severity=blocker` 且 `blocking` 且 `status ∈ {open, answered}`」
  的线程 → `danger`；存在 `kind=ai_clarification` 且 `status=open` → `warning`；生成中 → `primary`；
  其余 → `muted`。段归属由线程 `anchor.section_path` 的**首段**反查（取不到则不计入任何段）。
- ⛔ **数组长度恒为 10**，⛔ 零 `.filter(` / 条件增删。源码扫描与 `props('sections')` 断言双证。

### ⭐ 对 UI-SPEC 的两处订正登记

| # | 原措辞 | 订正 | 理由 |
|---|---|---|---|
| 1 | §6.9「`must_haves` 全空时整段与导航项都不渲染」 | **段容器与导航项照旧渲染**，只是段内不出内容（段高度可为 0） | 那个布局件只在 `onMounted` 按 `sections` 逐个 `getElementById`，既无 watch 也无 MutationObserver。条件渲染 ⇒ observer 一个也挂不上 ⇒ 左栏高亮永远停在第一段，**而点击跳转照常工作**（P-4） |
| 2 | §9.2「diff 模式正文区替换」 | **十段容器仍在**（段内内容由 `v-if="!isDiffMode"` 收起），diff 面板作为正文列的一块渲染在段序列之前 | 同上。「容器无条件渲染」优先于「替换正文」的措辞；否则一进 diff 视图 observer 全部失效，退出 diff 后也不会恢复（组件没有重挂载） |

---

## 4. 错误分档的最终落点表

| 来源 | 状态 | 落点 |
|---|---|---|
| **四个主查询**（`blueprint/` 正文 / `blueprint-review/` 快照 / `threads/` / `blueprint/events/`） | 404 | **整页** `BlueprintErrorState`，**唯一一句** `error.notFoundOrForbidden`，⛔ 不渲染任何蓝图元信息（顶栏与十段容器一起消失，用例 3 断言 `section[id]` 计数 == 0） |
| 同上 | 5xx / 网络失败（无 `ApiError`） | 整页 + 「重试」→ `refetchAll()` |
| 同上 | 400 | 就近渲染在正文列顶部，**原样回显** `ApiError.detail` |
| 同上 | 401 / 403 | ⭐ **跳过不分档**，交给 `~/api/client.ts` 既有的刷新与全局事件机制 |
| ⭐ `blueprint-gate/` 快照 | **任何非 200** | **只让挂载点不渲染**。⛔ 不进分档、不报错、不弹提示、不写任何错误态 |
| ⭐ `chunk-at` / `charter`（引用预览） | 任何失败 | 由 115-03 的预览子件内部走快照兜底，页面完全不感知 |
| `deliveryArtifacts.getArtifactTimeline`（版本轨） | 任何失败 | `retry: false`，只让版本切换器为空 |
| diff 基线正文 | 任何失败 | `retry: false`，只让 diff 面板不渲染 |

⭐ **gate 例外的判据为什么只靠用例、不靠源码正则**（plan-checker C3 已删除原扫描项）：`gate`
这个词在页面里出现在注释、queryKey、`?panel=gate` 分支里，而 `?panel=review` 不可用时**本来就
应该**弹一条 info 提示 —— 任何「gate 附近 N 字符内不得出现 toast」的正则都会把正确实现判红。
真正形状正确且可证伪的判据是 `blueprintViewer.spec` 用例 4：**gate 端点抛 404 而四个主查询正常
⇒ 页面正常渲染 10 段、`blueprint-error-state` 不存在、六个 toast mock 一次都没被调用**。变异
（把 gate 失败接进错误分档）会让它转红。

---

## 5. 六个动作端点的接线实现

通则：**任何 2xx 之后以响应体的 `current_status` 为准 + `invalidateQueries({ queryKey: ['blueprint'] })`
前缀失效重取**；⛔ 零乐观更新、⛔ 零 `setQueryData`、⛔ 不用 `predicate`。用例 7 双向断言。

| 动作 | 成功 | 异常分支 |
|---|---|---|
| **approve** | success 提示 `review.approveSuccess` =「已通过，蓝图进入「已确认」」 | ⭐ **409 且响应体带 `unresolved_blocker_thread_ids`** ⇒ 打开 `BlueprintBlockedDialog` 逐条渲染可点处置入口（用例 5 断言条目数 == 2）；409 无清单 ⇒ 错误提示 + `error.conflict` + 自动失效；400 ⇒ 原样回显 `detail` |
| **reject** | success `review.rejectSuccess` =「已驳回，蓝图回到「产出中」（第 {n} 轮修订）」，`n` 取响应体 `revision_round` | 409 ⇒ `error.conflictVersion` 插值响应体 `version_no` + 自动失效 |
| **answer** | ⭐ 端点**恒 200**，按 `reflow.status` 五档（见下） | ⛔ **任何分支都不当失败**、不渲染红色错误态、不回滚 UI |
| **resolve / dismiss** | `status === 'noop'` ⇒ info `finding.noopNotice`；否则 success `finding.resolveSuccess` / `dismissSuccess` | 400 ⇒ 原样回显 `detail` |
| **选区评论** | `POST threads/` 200 ⇒ success `thread.commentCreated` + 清空草稿 + 失效 | 400 ⇒ 原样回显；跨块选区 ⇒ 一条 info `annotation.crossBlock` |

### `reflow.status` 五档的实际文案

| `reflow.status` | 语气 | 文案 |
|---|---|---|
| `applied` | success | 「答案已回灌，已产出 v{version_no}」 |
| `unchanged` | info | 「答案已记录，本次未产生新版本」 |
| `noop` | info | 同上（幂等，⛔ 不提示用户重试） |
| `conflict` | warning | 「答案已保存，部分块存在冲突需人工确认」+ 描述行列出 `conflict_block_ids` |
| `failed` / `invalid`（及任何未知值） | warning | 「答案已保存，回灌未成功，可稍后重试」 |

⚠️ **`useToast` 没有 `variant` 概念**（它是 `success/error/warning/info/loading/promise` 六个函数）
⇒ 「destructive toast」在本仓的落点就是 `toast.error()`。用例 6 因此断言 `noop` 分支下
**`toast.error` 零调用、`toast.info` 被调用**。

---

## 6. 三栏装配与断点

```
PageContainer
├─ BlueprintViewerHeader      sticky top-0 z-30
├─ BlueprintSectionNav        md:hidden sticky top-14 z-20
└─ AnchorNavLayout            ⭐ 页面直接使用（它自身 = 左栏 aside + 正文 slot）
   └─ <div class="flex gap-6">     ← 在它的默认 slot 内再开一层
      ├─ <div class="min-w-0 flex-1 space-y-6">
      │   400 内联错误 → 历史版本/只读提示 → StageTimeline → (diff 面板)
      │   → ⭐ 十个 <section id> → gate 挂载点 → 质量面板
      └─ <aside class="sticky top-22 hidden max-h-[calc(100vh-6rem)] w-80 shrink-0 xl:flex">
          └─ ScrollArea > BlueprintThreadSidebar
└─ Sheet(side="right")        ← < xl 的批注抽屉，由顶栏「批注 {n}」按钮唤起
```

- ⛔ **`AnchorNavLayout` 一行未改**：它的 `md:` 两栏与本页的 `xl:` 三栏正交叠加。
- §18.1 焦点回归：`watch(sheetOpen)` 在关闭后把焦点还给
  `[data-testid="blueprint-header-open-annotations"]`。
- 跨段跳转统一在页面处理：`document.getElementById(domId)` +
  `window.scrollTo({ top: rect.top + scrollY - 88 })` + 2s ring。⭐ **偏移常量 88 与
  `AnchorNavLayout.scrollTo` 逐字一致**，⛔ 段组件内零滚动实现（115-05 已扫描核实）。

---

## 7. 段内三态与骨架形状

| 态 | 判据 | 呈现 |
|---|---|---|
| 首屏加载 | `docQuery.isLoading` | 段内骨架（形状按段差异化） |
| ⭐ 生成中（按段增量） | `isLive && 该段条目数 === 0` | 段内骨架 + 一行进度文案，`aria-busy="true"` / `aria-live="polite"`。**已产出的段立即实渲**，⛔ 不做全页 loading（用例 8：`drafting` 下需求规格段实渲、API 契约段出骨架 + 「起草中…」） |
| 实渲 / 空态 | 其余 | 交给 115-05 的段组件（各段空态规则见 115-05-SUMMARY §7） |

进度文案取 `sectionProgress[key]`（composable 已按 P-8 做过「插值键缺失 ⇒ 回落 `*Generic`」的降级），
未被任何事件覆盖的段回落 `statusProgressKey`。骨架形状（§8.1）：仓库关联 / API 契约 2 张
`h-40 rounded-xl`；现状分析 / 实现概述 / 需求规格 组头 + 3 条 `h-16`；影响范围 表头 + 4 行 `h-9`；
交互流程 `h-56` + 表头 + 3 行；验收锚点 3 条 `h-4` + 表头 + 2 行；决策记录 / 关联 3 条 `h-12`。

---

## 8. ⭐ 给 115-07 的 gate 面板插槽（本 plan 唯一的对外预留）

页面正文列在**质量面板之前**有：

```html
<!-- gate-panel-mount：115-07 在此挂确认门面板，挂载条件 = `gateQuery` 成功且返回 200。
     ⛔ 本 plan 不渲染面板本体，只预留挂载点与滚动锚点；
     gate 查询非 200 时该挂载点整块不出现，且不产生任何错误态或提示。 -->
<div v-if="gateAvailable" id="gate" data-testid="blueprint-gate-mount" :class="…ring…" />
```

115-07 需要的三样东西**已就位**：

1. `gateQuery`（`queryKey: ['blueprint', 'gate', artifactId]`，`retry: false`）与派生的
   `gateAvailable` / `gateSettled`；
2. DOM 锚点 `id="gate"` —— `?panel=gate` 与侧栏线程卡的 `goto-gate` 都已经指向它；
3. `BlueprintThreadSidebar` 的 `:gate-available="gateAvailable"` 已接上（面板缺席时线程卡不渲染
   「前往确认门」链接）。

⇒ 115-07 的追加面就是把 `<BlueprintGatePanel />` 塞进那个 `<div>` 里 + 一行 import，**其余零改动**，
仍可独立推迟。⭐ **该挂载点必须保持 `v-if="gateAvailable"`**：那是「gate 非 200 不进分档」在
DOM 上的唯一落点。

---

## 9. 知识库 tab 与项目物料卡的追加点 diff 摘要（⭐ 删除行 = 0）

`git diff web/src/pages/knowledge/index.vue web/src/components/project/warroom/ProjectMaterialsPanel.vue | rg "^-[^-]"` → **空输出**。

### 追加点 #1 —— `pages/knowledge/index.vue`（+11 行 / −0）

| 位置 | 追加内容 |
|---|---|
| import 区 | `import BlueprintsTabPanel from '~/components/knowledge/BlueprintsTabPanel.vue'`（按字典序插在 `BatchIngestPanel` 之后） |
| `KnowledgeTab` 联合 | 新起一行 `  \| 'blueprints'`（⭐ **既有那行逐字不变**） |
| `TABS` 数组 | ⭐ 新起一行 `TABS.push('blueprints')` —— **不改写既有那行**。tab 兜底函数在调用时才读 `TABS`，新 tab 自动被它认可（其实现一行未改） |
| `TabsTrigger` 内联 `as const` 数组 | 追加 `{ value: 'blueprints', icon: 'icon-[lucide--file-text]' }` |
| `TabsContent` 群 | 新增一个 `<TabsContent value="blueprints"><BlueprintsTabPanel /></TabsContent>` |

⛔ 未触及：tab 兜底函数实现、`?tab=` 双向同步的两个 watch、既有四个 tab 的任何一行、既有
`CompactEmptyState` 的完整类名写法（那是既有面，不在本相位修复范围）。
源码扫描 `git diff -U0` 不含那个兜底函数名、不含 `watch(` ⇒ 实跑输出 `tab host append-only OK`。

### 追加点 #2 —— `ProjectMaterialsPanel.vue`（+5 行 / −0）

| 位置 | 追加内容 |
|---|---|
| `defineAsyncComponent` 组 | 第五行 `const ProjectBlueprintsCard = defineAsyncComponent(() => import('./ProjectBlueprintsCard.vue'))` + 两行说明注释 |
| 分区流 | `<ProjectBlueprintsCard :project-id="project.id" hide-when-empty />`，⭐ **排在既有 `<ArtifactTimeline>` 之前** |

### ⭐ 新卡与既有 `ArtifactTimeline` 的文案区分方案（P-17）

蓝图与旧 `technical_plan` **共用同一个 `artifact_type`**，而版本轨那块正是按
`artifact_type="technical_plan"` 过滤的 ⇒ 同一份交付物会同时出现在两个区域，内容看着很像。
用户会以为系统重复展示，或者更糟——误读成「两份不同的方案」。三条区分：

1. **分区标题不同**：新卡用「技术方案」，既有那块是「交付物版本轨 / 时间线」；
2. **描述点明形态差异**：新卡第一行渲染 `pageDescription` =「查看 AI 产出的结构化技术方案：
   逐段审阅、划线提问、完成终审」，明确它是**带批注与人审的结构化蓝图**；
3. **数据面天然收窄**：新卡走 `GET /delivery/blueprints/`，该端点只返回走过蓝图状态机的
   artifact（`blueprint_status != ''`），旧 technical_plan 不会出现在这里；
4. **顺序**：排在版本轨之前，让更新的形态先被看到。

组件 docstring 逐字登记了这条重叠与区分策略。

---

## 10. `FilterBar` 的最终 API 与「它是通用件」的核对

```ts
props:  { showClear?: boolean }     // 默认 false
emits:  { clear: [] }
slots:  default                      // 承载 Input / Select / chip 等筛选控件
```

容器 `.card` + `p-4` + `flex flex-wrap items-center gap-3`；清除按钮 `variant="ghost" size="sm"`
靠右（`ml-auto`），文案走**新增的通用键** `common.clearFilters`。

核对：`node -e "…/blueprint|artifact|bp_status/i…"` 实跑输出 **`FilterBar generic OK`** ——
组件内零业务专属概念，下一个页面可以直接复用。契约来源 `web/DESIGN.md:198-211`
（写了却一直零实现，本相位按它补上，属新建而非改造）。

---

## 11. ⭐ i18n 一次性补齐：69 个新键，0 删除 0 修改

对 115-05 的基线（`293276ae`）做键集差分：**added 69 / removed 0 / changed 0**，
`git diff web/src/locales/zh-CN.json | rg "^-[^-]"` **空输出**。

> ⚠️ 为拿到「零删除行」，新键一律**插在各对象的最后一项之前**（直接追加在末尾会给原来的最后
> 一行补一个逗号，在 diff 里表现为一删一增）。后续 plan 补键时请沿用这个落位习惯。

### 11.1 42 个是 115-03/04/05 回报的缺口（含全部三档降级）

| 来源 | 键数 | 键 | 换回的降级形态 |
|---|---|---|---|
| **115-03** | 4 | `repo.charterPositioning` / `charterOwnedDomains` / `charterBoundaries` / `charterPlacement` | 章程四分区加回 `label` 与一行 `<p>`（无结构改动，`data-charter-section` 仍在，测试与接线不受影响） |
| **115-04** | 5 | `review.disabledReason`（带 `{status}` 插值）/ `review.rejectKeepAnchor` / `quality.noKeyConclusions` / `thread.draftCancel` / `diff.mustHavesExcluded` | 终审 Tooltip 换成带状态插值的版本；驳回锚点开关标签换回；质量面板旁注换回（三段名说明降级为 `title`）；草稿卡**补上可见「取消」按钮**（`Esc` 放弃仍保留）；diff 占位行文案换回 |
| **115-05** | 33 | `section.goal` / `background` / `currentStateSummary` / `deferredIdeas`；`spec.intent*`(3)；`state.kind*`(4) + `missingCitations`；`impl.changeType*`(4) + `existingIntegration` / `testStrategy` / `waveCount`；`api.availabilityUnknown`；`impact.irreversible`；`flow.actor*`(4)；`repo.rationale` / `capabilitiesUsed` / `crossTeam` / `confirmedAtGate` / `notConfirmedAtGate`；`decision.gotoThread`；`associations.citedByThis` / `relatedProject` | 见下 |

⭐ **优先换回的是「③ 档：枚举 / 布尔徽标渲染 schema 原样 token」** —— 这一档此前在界面上直接印
英文枚举值（`greenfield` / `gap` / `indirect_refine` / `backend` / `cross_team` /
`reversible=false`），颜色与图标承载全部语义，是可读性最差的一档：

| 枚举 | 换回前 | 换回后 |
|---|---|---|
| 功能点 `intent` | `greenfield` / `brownfield` / `fix` | 净新增 / 存量改造 / 缺陷修复 |
| finding `kind` | `capability` / `gap` / `risk` / `convention` | 能力 / 缺口 / 风险 / 约定 |
| 实现项 `change_type` | `create` / `modify` / `remove` / `indirect_refine` | 新建 / 改动 / 删除 / 间接完善 |
| 步骤 `actor` | `user` / `frontend` / `backend`（`service:*` 保持原样） | 用户 / 前端 / 后端 / 服务 |
| routing `cross_team` | `cross_team` | 跨组协作 |
| 数据迁移 | `reversible=false` | 不可逆 |
| `availability` 读不到 | 「暂无数据」（借的质量面板键） | 未标注 |

四档枚举一律保留「未知值回落 schema 原样 token」的分支，⛔ 不发明第五档文案；`data-*` 身份属性
全部原样保留，既有用例按它们定位，零改动。

⭐ **三处跨子树借用已全部换回本子树**：关联能力（原借 `knowledge.entity.associations.capabilities`）
→ `repo.capabilitiesUsed`；引用文档（原借 `knowledge.relation.REFERENCES`）→
`associations.citedByThis`；关联项目（原借 `projects.workbench.deps.projectsTitle`）→
`associations.relatedProject`。⇒ 蓝图文案不再跟着别的功能一起改。

### 11.2 27 个是本 plan 自身所需

| 子树 | 键数 | 用途 |
|---|---|---|
| `stage.*` | 14 | 阶段时间线：`title` / `empty` / 八个节点名 / 四态名 |
| `viewer.*` | 3 | `live`（生成中指示）/ `sectionNavLabel`（窄屏下拉 aria）/ `highlightJump` |
| `annotation.count*` | 3 | 顶栏三个计数徽标（未决阻塞 / 待澄清 / 失锚） |
| `review.approveSuccess` / `rejectSuccess` | 2 | approve / reject 的成功提示 |
| `finding.resolveSuccess` / `dismissSuccess` / `noopNotice` | 3 | 处置动作的三档提示 |
| `thread.commentCreated` | 1 | 选区评论提交成功 |
| `common.clearFilters` | 1 | ⭐ **新的顶层 `common` 子树** —— 服务 `FilterBar` 这个通用件，⛔ 不能挂在 `knowledge.*` 下 |

⚠️ **两个既有 spec 的手写最小 i18n 键树同步补键**（`sections.spec.ts` / `reviewActions.spec.ts`）：
它们不 import `zh-CN.json`，缺键会让断言读到键名而不是文案（`sections.spec.ts` 的用例 5b 与 8d
就是这么先红的）。`sections.spec.ts` 里一处硬编码旧降级文案的断言（`'暂无数据'` → `'未标注'`）
一并改正。

---

## 12. Deviations from Plan

### 1. `[Rule 3 - 阻塞] 仓内没有 ui/alert，历史版本与只读提示改用语义描边 div`

- **发现于**：Task 2
- **问题**：PLAN 与 UI-SPEC §9.1 都写「用 `~/components/ui/alert`」，但 `web/src/components/ui/`
  下的 34 个目录里**没有 `alert`**（只有 `alert-dialog`，那是确认弹窗，语义完全不同）。
- **处理**：两处提示改为带语义描边的 `div` + `role="status"` + 图标 + 文案 + 行内动作按钮，
  `data-testid` 分别是 `blueprint-history-notice` / `blueprint-readonly-notice`。⛔ 不新建
  `ui/alert` —— 那是通用设计系统件，形态要与 DESIGN 对齐，超出本 plan 的边界。
- **文件**：`pages/knowledge/blueprints/[id].vue` ｜ **Commit**：`ee1e8dce`

### 2. `[Rule 1 - 死接口 / Rule 2 - 契约缺口] 顶栏的两处签名调整`

- **删掉** PLAN 列的 `snapshot` prop：顶栏需要的 `currentStatus` / `revisionRound` / 三个计数都由
  页面派生后单独传入，快照原件在顶栏没有任何消费者（沿用 115-03 订正一「零消费的接口是死接口，
  会误导接线方」的判例）。
- **新增** `open-annotations` emit：窄屏「批注 {n}」按钮唤起的是**抽屉**，与 `xl` 常驻侧栏的
  **折叠**是两个不同目标；共用一个 emit 会让页面无法区分，而页面不该去猜当前断点。
- **文件**：`BlueprintViewerHeader.vue` ｜ **Commit**：`4665daf2`

### 3. `[订正登记] diff 视图下十段容器仍在（不「替换正文区」）`

- 见 §3 的订正表第 2 行。UI-SPEC §9.2 说「正文区替换为 diff」，但那样一进 diff 视图那个布局件的
  observer 就全部失效，**退出 diff 后也不会恢复**（页面没有重挂载）。取「容器无条件渲染优先」：
  diff 面板渲染在段序列之前，十段容器保留、段内内容由 `v-if="!isDiffMode"` 收起。

### 4. `[Rule 1 - 自洽修正] 三处字面量会触发本 plan 自己的验收断言`

- **发现于**：Task 2 / Task 3 的验收复跑
- **问题**：① `BlueprintSectionNav` 的 docstring 为说明「本组件**不**组合那个布局件」而写了它的
  名字，正好命中「组件目录内该名零命中」的扫描；② 页面的 gate 挂载点注释写了 115-07 那个面板
  组件名，命中「页面内该名零命中」；③ 追加点 #1 的注释写了 tab 兜底函数名，命中「diff 不得触及
  该函数」的扫描。
- **处理**：三处一律改写成不含该字面量的等义中文表述（语义与纪律说明完整保留）。与 115-02 §12.3、
  115-03 Deviation 5、115-04 Deviation 6、115-05 Deviation 4 **同一类**。
- **Commit**：`ee1e8dce` / `dff05278`

### 5. `[验收脚本自身缺陷] 「组件目录内那个布局件名零命中」这条已不可能满足`

- **核实**：115-05 的三个段组件（`MustHavesSection` / `CurrentStateSection` /
  `RequirementSpecSection`）的 docstring**在本 plan 之前**就各写了一次它的名字（用来解释「为什么
  段容器要由页面无条件渲染」）。本 plan 不得restructure 那三个文件（只允许 i18n 换回）⇒ 字面量
  零命中这条**在 115-05 落地那一刻就已经不成立**。
- **判断**：该条的真实意图是「⛔ 任何组件都不得**包**它」。改用形状正确的判据复核：
  `rg -n "<AnchorNavLayout" web/src/components/blueprint/` → **零命中**（无任何组件渲染它）；
  唯一的非注释引用是 `BlueprintSectionNav` 的 `import type { NavSection }` —— 那个接口就导出在
  那个文件里，是**类型依赖**而非组合。⛔ 未为此改动 115-05 的三个文件。

### 6. `[Rule 3 - 阻塞] 生成物 components.d.ts 必须手工增行`

- **发现于**：Task 3 收尾
- **问题**：`pnpm build` 重写 `src/components.d.ts` 时，除了加上本 plan 的 4 个新组件，还**顺带
  裁掉 29 条既有条目**（`AccountSettingsModal` / `ActionNode` / `CodingTaskList` … 等未进本次构建
  图的懒加载件）。直接提交等于在生成物里夹带 29 行删除，与「纯追加」纪律冲突，也会给别人的分支
  制造无意义冲突。
- **处理**：`git checkout` 还原后，按字典序**手工插入那 4 行**（`BlueprintListCard` /
  `BlueprintsTabPanel` / `FilterBar` / `ProjectBlueprintsCard`），最终 diff 为 **+4 / −0**。
  `src/typed-router.d.ts` 无此问题（**+15 / −0**，纯追加）。
- **登记**：⭐ 后续 plan 跑完 `pnpm build` 后请检查 `git diff src/components.d.ts`，只留自己的增行。

### 7. `[环境事实] pnpm 10 的 workspace 漂移本次出现并已还原`

- 跑完前端门后 `web/pnpm-workspace.yaml` 出现 +4 行 catalog 回填（`@types/three` /
  `@types/wordcloud` / `3d-force-graph`，115-02 §12.7 预警的现象）。提交前已 `git checkout --`
  还原，五个提交内 `git diff web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml` **零行**。

### 8. `[判据澄清] 「destructive toast」在本仓的落点`

- `useToast` 返回的是 `success/error/warning/info/loading/promise` 六个函数，**没有 `variant`
  参数**。PLAN 与 UI-SPEC 里的「`variant="destructive"` 的 toast」在本仓即 `toast.error()`。
  用例 6 因此断言「`toast.error` 零调用 + `toast.info` 被调用」，⛔ 不去断言一个不存在的 variant。

---

## 13. Task Commits

| Task | 内容 | Commit | 变更 |
|---|---|---|---|
| 0（i18n 交接） | 补齐 115-03/04/05 回报的缺口并换回降级渲染 | `38f6eb35` | 19 文件 / +246 / −54 |
| 1 | 查看器骨架四件（错误态 / 段导航 / 顶栏 / 阶段时间线） | `4665daf2` | 5 文件 |
| 2 | 查看器路由页装配 | `ee1e8dce` | 4 文件 |
| 3a | 知识库 tab 四件 + 两处宿主纯追加 | `dff05278` | 7 文件 |
| 3b | 两个页面测试（16 例） | `9bb23f0f` | 3 文件 |

---

## 14. 边界核算

| 检查 | 结果 |
|---|---|
| 四个 0.19 归属面（`TechPlanCard.vue` / `RoutingDecisionPanel.vue` / `NodeDataTab.vue` / `ArtifactTimeline.vue`） | **`git diff` 全空** |
| 其余零改动清单（`AnchorNavLayout.vue` / `CompactEmptyState.vue` / `PromptVersionDiff.vue` / `MermaidDiagram.vue` / `config/status.ts` / `api/client.ts` / `styles/main.css` / `api/index.ts`） | **`git diff` 全空** |
| 两处宿主追加点删除行 | **0**（`rg "^-[^-]"` 空输出） |
| `web/src/locales/zh-CN.json` | **+69 键 / −0 / 改 0**（键集差分实测） |
| 后端 | `git diff --name-only server/` → **0 个文件** |
| 依赖 | `git diff web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml` → **0 行** |
| `rg "refetchInterval\|edit-block\|edit-blocks\|editBlocks" src/components/blueprint/ src/pages/knowledge/blueprints/` | **零命中** |
| `rg "v-html\|hsl(" src/pages/knowledge/blueprints/ src/components/common/FilterBar.vue src/components/knowledge/Blueprint*.vue src/components/project/warroom/ProjectBlueprintsCard.vue` | **零命中** |
| `rg "predicate\|setQueryData" src/pages/knowledge/blueprints/[id].vue` | **零命中** |
| `rg "<AnchorNavLayout" src/components/blueprint/` | **零命中**（无组件包它） |
| 源码守卫扫描面 | **41 个文件**（≥35），6 条断言全绿 |

---

## 15. ⭐ UAT 清单（happy-dom 测不了的，交给 `/gsd-verify-work`）

| # | 项 | 为什么自动化测不了 | 期望 |
|---|---|---|---|
| 1 | ⭐ **左栏高亮随滚动推进**（P-4 的真实验证） | happy-dom 无 `IntersectionObserver` 布局回调、无滚动几何 | 慢慢往下滚，左栏高亮**逐段推进**并停在当前段；⛔ 不许「一直停在第一段而点击跳转正常」。**这是本 plan 头号靶子的最终人证** |
| 2 | **跨段跳转与深链的滚动定位** | 无布局引擎 | 点功能点 chip / `api_ref` chip / 左栏项 / `?section=` 深链后，目标滚到位、**顶栏不遮挡**（88px 偏移）、目标 2s ring 高亮后自然消失 |
| 3 | **mermaid 实渲** | 测试里图表组件必 stub | 交互流程段每条 flow 出 SVG；引用预览弹层内是源码 `<pre>` 而不是图 |
| 4 | **三栏断点四档** | 媒体查询不生效（双份结构在 DOM 里同时存在） | `< md` 只见下拉、`md` 出左栏、`lg` 卡片两列、`xl` 右栏常驻且 `Sheet` 停用 |
| 5 | **`Sheet` 焦点陷阱与关闭后焦点回归** | Portal + 焦点模型不完整 | 抽屉打开后 `Tab` 不跑出抽屉；`Esc` / 点遮罩关闭后焦点回到「批注 {n}」按钮 |
| 6 | **选区 popover 的落点** | `getBoundingClientRect` 恒 0 矩形 | 拖选后浮层贴着选区、不出视口、滚动跟随；「发起评论」→ 侧栏草稿卡出现且自动展开抽屉 |
| 7 | **颜色对比度** | 无渲染引擎 | 顶栏三个计数徽标、段 badge 五档 tone、历史版本/只读提示条在浅色与深色主题下都可读 |
| 8 | **diff 并排视图** | 同 4 | `?diff_mode=split` 下左右两栏对齐、可横向滚动；⭐ **十段容器仍在但段内为空**（订正 2 的视觉确认：会不会让人觉得页面下方是一片空白？若观感不佳，后续可在段内补一行「diff 视图下不展示正文」） |
| 9 | **Tooltip 悬停** | Portal + 悬停延迟，测试里被拍平 | 悬停 disabled 的「通过方案」能看到「当前状态为「AI 审查中」，需等待进入待人类审查」 |
| 10 | **物料面板的重叠观感（P-17）** | 需要真实项目数据 | 同一项目下新卡与「交付物版本轨」并列时，用户能一眼分清两者；若仍混淆，按 §9 的四条再加强 |
| 11 | **列表页筛选与分页的刷新可复现** | 需要真实 URL 栈 | 改筛选 → 刷新 → 筛选与页码原样恢复；`?tab=blueprints&bp_status=…&page=2` 深链直接可用 |
| 12 | **21 处 i18n 换回后的可读性** | 缺键已补，只剩观感 | 走查各段徽标与小标题的中文是否贴切（尤其 `impl.waveCount` 的「wave {n} · {c} 项」） |

---

## 16. 六条 REQ → 实现落点与测试用例映射

| REQ | 实现落点 | 测试用例 |
|---|---|---|
| **VIEW-01**（结构化蓝图逐段可读） | `pages/knowledge/blueprints/[id].vue` 的十段容器 + 115-05 的十段组件 + `AnchorNavLayout` 左栏 | `blueprintViewer.spec` 1 / 2 / 8；UAT 1 |
| **VIEW-02**（引用可追溯） | 页面 `onCitationClick` → `useCitationPreview.openWithSnapshot` → `CitationPreviewDialog`（115-03） | 115-03 `citationPreview.spec` 16 例；本 plan 只做接线 |
| **VIEW-03**（知识库入口可筛可搜） | `BlueprintsTabPanel` + `FilterBar` + 追加点 #1 | `blueprintsTab.spec` 1 / 4 / 5 / 6 / 7 |
| **VIEW-04**（项目侧可见） | `ProjectBlueprintsCard` + 追加点 #2（反向「被谁引用」顺延 Phase 116） | `blueprintsTab.spec` 1 / 2；115-05 `sections.spec` 9a（关联段零端点） |
| **CLAR-01**（划线提问与评论） | 页面 `onSelectionComment` → `BlueprintSelectionPopover` → 侧栏草稿卡 → `POST threads/` | 115-03 选区四档 + 115-04 断言 1/2；本 plan `blueprintViewer.spec` 6（answer 分档） |
| **FLOW-08**（人审终审闭环） | 顶栏透传 `BlueprintReviewActions` + 页面的 approve / reject / 409 解药面板 | `blueprintViewer.spec` 5 / 7；115-04 `reviewActions.spec` 19 例 |

---

## 17. 给 115-07 与后续的四条注意

1. **gate 面板就挂在 `#gate` 那个 `div` 里**（§8）。⭐ 保持 `v-if="gateAvailable"` —— 那是「gate 非
   200 不进分档」在 DOM 上的唯一落点；改成无条件渲染会让「确认门未开启」这个正常态变成一块空白。
2. **十段容器与 `sections` 长度是硬约束**。要加第十一段？那就同时加导航项与容器，⛔ 永远不要让
   `sections` 的长度随数据变化。
3. **i18n 缺口已清零**（§11）。115-03/04/05 三份 SUMMARY 里的「回报给 115-06 的 i18n 缺口」章节
   **已全部兑现**，⛔ 不要再照着它们去改组件结构。
4. **两个既有 spec 的手写 i18n 键树需要跟着补**：它们刻意不 import `zh-CN.json`，加了新键并在组件里
   用上之后，对应 spec 的最小键树必须同步，否则断言读到的是键名。

---

## Self-Check: PASSED

**创建的 11 个文件全部存在**——`pages/knowledge/blueprints/[id].vue` / 四个查看器骨架组件 /
`common/FilterBar.vue` / `knowledge/{BlueprintsTabPanel,BlueprintListCard}.vue` /
`project/warroom/ProjectBlueprintsCard.vue` / 两个 spec，逐个 `[ -f ]` 命中。

**五个实现 commit 全部在 `git log`**：`38f6eb35` / `4665daf2` / `ee1e8dce` / `dff05278` / `9bb23f0f`。

**门禁实跑**：vitest **1618 passed / 1 skipped**（基线 1602 / 1，**+16 零回归**）、type-check
**exit 0**、`eslint .` **111 problems**（与基线逐个相同 ⇒ 零新增）、`pnpm build` **通过**、
源码守卫 **6 条全绿**（扫描面 41 文件）。

**变异验证实跑**：给第一个段容器加 `v-if="content"` ⇒ `blueprintViewer.spec` 用例 1 **转红**
（其余八条保持绿）；还原后 9 例全绿，工作树逐字节干净。

**边界核算**：四个禁改文件与其余零改动清单 `git diff` 全空；两处宿主追加点删除行 = 0；
`zh-CN.json` 键集差分 added 69 / removed 0 / changed 0；`server/` 零改动；依赖零行变更
（pnpm 漂移已还原）；生成物 `components.d.ts` 手工按字典序增 4 行、零删除。
