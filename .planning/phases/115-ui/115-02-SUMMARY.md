---
phase: 115-ui
plan: 02
subsystem: blueprint-frontend-foundation
requirements: [VIEW-01, VIEW-02, VIEW-03, VIEW-04, CLAR-01, FLOW-08]
tags: [frontend, vue3, tanstack-query, pure-functions, polling, i18n, source-guard, a11y]
requires:
  - "115-01 五端点契约表（`types/blueprint.ts` 的字段逐字照它，含两处 UI-SPEC §3.3 订正）"
  - "114-05 人审七端点 / 确认门八端点契约（`api/blueprints.ts` 一并薄封装）"
  - "server/delivery/services/blueprint_anchor.py `_block_text`（`blockText` 四分支的唯一同源依据）"
  - "server/services/process_runtime/blueprint_schema.py `iter_blocks` / `_item_key` / `_block_fingerprint`"
  - "server/delivery/services/blueprint_lifecycle_service.py:92 `EDITABLE_BLUEPRINT_STATUSES`（含 `''`）"
  - "server/delivery/services/event_taxonomy.py `BLUEPRINT_EVENTS`（21 常量）"
  - "既有前端设施：`api/client.ts` 的 `get`/`post`/`ApiError`、`config/status.ts` 的 `StatusConfig`、`components/ui/badge` 八 variant、`@tanstack/vue-query`、`reka-ui@2.9.10`"
provides:
  - "`web/src/types/blueprint.ts`（650 行）—— 全相位 TS 契约唯一来源；`BlueprintStatus` / `BlueprintBlock` / `Citation` / `BlueprintV1` / `BlueprintDocumentResponse` / `BlueprintEventsResponse` / `BlueprintThreadDetail` / `BlueprintListItem`（键 **`current_status`**）/ `BlueprintListResponse`（**五键** `{total, items, page, page_size, has_next}`）"
  - "`web/src/api/blueprints.ts`（284 行）—— 19 个函数：五个新端点 + 人审六动作 + 确认门八动作；`export default` 汇总；⛔ 零 `edit-blocks`、零 `getRelated`/`getArtifactAssociations`"
  - "`web/src/api/repositoryChunks.ts`（118 行）—— `getChunkAt() -> {chunks, usable}`（**P-3 判据封装在此，调用点不各自判**）/ `getRepositoryCharter() -> RepoCharter | null`"
  - "`web/src/config/blueprintStatus.ts`（145 行）—— 12 态配置（存 `labelKey` 不存中文）+ `getBlueprintStatusConfig` 兜底 + `EDITABLE_BLUEPRINT_STATUSES`（六值含 `''`）+ `isBlueprintEditable` + `LIVE_BLUEPRINT_STATUSES`（三值）+ `PRODUCED_BY_PREFIXES` 五档 + `producedByReason`"
  - "`web/src/utils/blueprintBlocks.ts`（443 行）—— `blockText` / `itemKey` / `iterBlocks` / `canonicalBlockFingerprint` / `classifyBlockDiff` / `sectionKeyForEvent` / `progressKeyForEvent` / `stageForEvent` / `summaryText` + `BLUEPRINT_STAGES` / `BLUEPRINT_EVENT_NAMES`"
  - "`web/src/utils/blueprintAnnotations.ts`（292 行）—— `sliceBlockText` / `isValidAnchor` / `degradedThreadIds` / `collectTextNodes`（触 DOM）/ `offsetInFlatText`（纯数据）/ `rangeOffsets` / `groupThreadsByBlock` / `anchorRangesForBlock` / `sidebarGroups` / `annotationCounts` / `hasAnchorLocator`"
  - "`web/src/components/blueprint/annotationTokens.ts`（217 行）—— `annotationClass(kind, severity, status, active)` 是 `<mark>` 类名的**唯一来源**；`annotationHue` / `ANNOTATION_PRIORITY` / `pickTopThread` / `MARK_BASE_CLASS`"
  - "`web/src/composables/useBlueprintLive.ts`（257 行）—— **全相位唯一轮询消费点**，返回 `{isLive, currentStatus, doc, snapshot, eventsQuery, events, stageTimeline, sectionProgress, statusProgressKey, refetchAll}`"
  - "`web/src/composables/useBlueprintAnnotations.ts` / `useCitationPreview.ts` / `web/src/stores/useBlueprintViewerStore.ts`"
  - "`web/src/__tests__/blueprint-source-guard.spec.ts` —— 6 条源码扫描守卫（§20 断言 4/6/10 + 扫描面自锁 + 中文竞品文案 + 零 v-html）"
  - "i18n `knowledge.blueprints.*` 全量子树（25 个顶层键）+ `knowledge.tabs.blueprints = 技术方案`；safelist 12 图标；api barrel 两组导出"
affects:
  - "115-03 / 115-04 / 115-05 / 115-06 / 115-07：全部照本 SUMMARY 的 §2–§8 逐字消费，⛔ 不再发明契约"
  - "⭐ `zh-CN.json` / `main.css` / `api/index.ts` 三个文件**全相位只由本 plan 修改**，后续 plan 只消费不再改（消除五向冲突面）"
  - "⭐ A2 假设已 settle：happy-dom 四项能力**全部支持** ⇒ 批注层 offset 测试走**自动化**，不进 UAT"
  - "同步点 2 换 v0.19.0 推送契约时**只改 `useBlueprintLive.ts` 一个文件**"
tech-stack:
  added: []
  patterns:
    - "TanStack Query 两形态 refetchInterval：自带状态字段的查询读自身 `query.state.data`；无状态字段的查询读外部 ref 并配 `watch` 的 refetch 踢动"
    - "两段式 offset 计算：触 DOM 的薄函数 + 纯数据函数，把环境不确定性隔离在一层"
    - "前端源码扫描守卫（`node:fs` 递归 + 违规清单聚合 + 断言消息内写修法），形态平移自后端 INV-6 守卫"
    - "能力锁 `toMatchInlineSnapshot()`：记录现实而非期望，环境能力变化即转红"
key-files:
  created:
    - web/src/types/blueprint.ts
    - web/src/api/blueprints.ts
    - web/src/api/repositoryChunks.ts
    - web/src/config/blueprintStatus.ts
    - web/src/config/__tests__/blueprintStatus.spec.ts
    - web/src/components/blueprint/BlueprintStatusBadge.vue
    - web/src/components/blueprint/annotationTokens.ts
    - web/src/utils/blueprintBlocks.ts
    - web/src/utils/blueprintAnnotations.ts
    - web/src/utils/__tests__/blueprintBlocks.test.ts
    - web/src/utils/__tests__/blueprintAnnotations.test.ts
    - web/src/utils/__tests__/domCapabilities.test.ts
    - web/src/stores/useBlueprintViewerStore.ts
    - web/src/composables/useBlueprintLive.ts
    - web/src/composables/useBlueprintAnnotations.ts
    - web/src/composables/useCitationPreview.ts
    - web/src/composables/__tests__/useBlueprintLive.spec.ts
    - web/src/__tests__/blueprint-source-guard.spec.ts
  modified:
    - web/src/api/index.ts
    - web/src/styles/main.css
    - web/src/locales/zh-CN.json
    - web/src/auto-imports.d.ts
    - web/src/components.d.ts
decisions:
  - "UI-SPEC §8.3 订正：轮询写两形态（快照读自身 data / doc·events 读 isLive 且配 watch 踢动），并删掉 useDocumentVisibility 那一条"
  - "UI-SPEC §10.1 订正：chunk-at 可用判据是 `!ok || chunks.length === 0`（200-空 chunks 也不可用），封装进返回类型 `{chunks, usable}`"
  - "UI-SPEC §3.6/§10.1 订正：代码正文来源降级为「文件路径 + 行号区间 + citation quote 快照」，⛔ 不引 CodeMirror、⛔ 不加后端端点（顺延 Phase 116）"
  - "UI-SPEC §7.4 订正：选区 popover 用 reka-ui 直接导入的 PopoverAnchor（已核实 2.9.10 导出），⛔ 不用 @floating-ui/vue、⛔ 不改本地 ui/popover barrel"
  - "P-5 范围收窄：SC-4 的 associations 段本相位只做「本蓝图引用了」+「关联项目」，「引用了本蓝图 / 关联知识」顺延 Phase 116"
  - "unknown 兜底的 labelKey 放在 `knowledge.blueprints.statusUnknown` 而非 `status.*` 子树内，保住「status 子树 12 键 ↔ 配置 12 档」的一一对应等式"
  - "api barrel 按字典序落位（blueprints 插在 auth 与 chat 之间）而非文件末尾追加，避免 perfectionist/sort-exports 报错又不触发既有分组重排"
metrics:
  duration: "约 3 小时（含被 provider 资源限制中断后的续跑收口）"
  completed: 2026-08-01
  tasks: 3
  commits: 3
  tests_added: 150
---

# Phase 115 Plan 02: 蓝图前端地基（契约 / 纯函数 / 唯一轮询消费点）Summary

**一句话**：把 115 相位前端侧所有会被多处复用的地基一次建齐——13 个新建源文件（TS 契约 650 行、API 封装 402 行、纯函数 735 行、composable/store 483 行、令牌与徽标 278 行）+ 6 个测试文件（**150 例全绿**）+ 三处**零删除行**纯追加，让后面四个 plan 只写组件、不再发明契约。四条会**静默假通过**的陷阱（P-13 圈错字 / P-9 进度冻结 / P-3 状态码误判 / P-14 走查越界）全部被固化成可证伪的纯函数与源码扫描；RESEARCH 挂着的 **A2 假设正式 settle：happy-dom 20.10.2 四项能力全部支持**，批注层 offset 测试因此走自动化而非 UAT。**零新增运行时依赖、零既有组件改动、后端零改动。**

---

## 1. 门禁与基线（本相位第一个前端 plan，⭐ 后续 plan 照此比对）

| 门 | 结果 | 说明 |
|---|---|---|
| `pnpm exec vitest run` | **202 passed / 1 skipped（203 文件）**，**1464 passed / 1 skipped（1465 例）** | 全绿。1 条 skip 是**既有**的 `src/layouts/__tests__/default.spec.ts:66`，与本 plan 无关 |
| `pnpm type-check`（`vue-tsc --noEmit`） | **通过**（exit 0） | — |
| `pnpm lint`（`eslint .`） | **111 problems（106 errors, 5 warnings）—— 全部既有** | ⚠️ 见下方「lint 基线的真相」 |

**推导出的 115-02 之前基线**：**197 测试文件 / 1315 例**（= 203 − 6 / 1465 − 150）。本 plan 新增 **6 文件 / 150 例**，零回归。

新增用例分布：

| 文件 | 例数 | 锁住什么 |
|---|---|---|
| `utils/__tests__/blueprintBlocks.test.ts` | 58 | P-13 四分支 / 13 处 collect / P-14 排除四段 / canonical 指纹 / 21 事件穷举 |
| `utils/__tests__/blueprintAnnotations.test.ts` | 48 | 切分六边界 + 拼接还原 / P-7 三态不混 / 两段式 offset |
| `config/__tests__/blueprintStatus.spec.ts` | 34 | 12 态逐档 / `''` 命中 legacy / labelKey 全部能在 zh-CN.json 查到 |
| `__tests__/blueprint-source-guard.spec.ts` | 6 | §20 断言 4/6/10 + 扫描面自锁 + 中文竞品文案 + 零 v-html |
| `composables/__tests__/useBlueprintLive.spec.ts` | 3 | **BLOCKER-1 的 1 → 2 启动断言** + 终态停 + 恒非活跃不轮询 |
| `utils/__tests__/domCapabilities.test.ts` | 1 | happy-dom 七项能力的 inline snapshot |

### ⚠️ lint 基线的真相（计划的验收假设不成立，⭐ 后续 plan 别被它误导）

计划的验收写「`pnpm lint` 通过」，**该前提在本 worktree 从一开始就不成立**：仓库范围内既有 **111 个 lint 问题**分布在 **27 个文件**（`pages/tasks/index.vue`、`types/workflow/node-definitions/node-definitions.json`、`components/project/warroom/*` 等），与蓝图无关。

**本 plan 自身的 23 个变更文件是干净的**——单独跑 `CI=true pnpm exec eslint <23 个文件>` 只有 **1 个 error**，且它是**既有**的：

```
src/api/index.ts
  41:1  error  Expected "./artifacts" to come before "./notifications"  perfectionist/sort-exports
```

已核实为基线既有：`git show 02ab1684:web/src/api/index.ts` 里 `notifications`（:32）本就排在 `artifacts`（:35）之前，同一违规。本 plan 对该文件的追加是**纯增行**且刻意按字典序落位，未新增任何 lint 问题。

⇒ **后续 plan 的 lint 判据应当是「自己碰的文件零新增问题」，⛔ 不是「`pnpm lint` 整体退出码为 0」**（那需要先清 106 个历史 error，超出 115 相位边界）。

---

## 2. ⭐ A2 假设的正式 settle：happy-dom 能力锁（决定 115-03/04 批注层测试形态）

`web/src/utils/__tests__/domCapabilities.test.ts` 用 `toMatchInlineSnapshot()` 落盘一张**能力布尔映射**（⛔ 不是 `expect.soft`、⛔ 未删除）。实测快照值：

```
{
  "createRange": true,
  "createTreeWalker": true,
  "getSelection": true,
  "rangeGetBoundingClientRect": true,
  "rangeSelectsNodeContents": true,
  "selectionReturnsObject": true,
  "treeWalkerFlattensText": true,
}
```

**settle 结论（七项全 `true`，happy-dom 20.10.2）**：

| 能力 | 存在性 | 行为实测 |
|---|---|---|
| `document.createTreeWalker` | ✅ 支持 | ✅ `NodeFilter.SHOW_TEXT` 遍历 `<div>abc<span>def</span>ghi</div>` 累加得 `'abcdefghi'` |
| `document.createRange` | ✅ 支持 | ✅ `selectNodeContents(el)` 后 `range.toString() === el.textContent` |
| `Range.prototype.getBoundingClientRect` | ✅ 支持 | ⚠️ **只锁存在性**——happy-dom 无布局引擎，恒返 0 矩形，这是已知且可接受的 |
| `window.getSelection` | ✅ 支持 | ✅ 返回非 null 的 Selection 对象 |

### 对 115-03 / 115-04 的直接含义（⭐ 这是本节存在的理由）

- **`collectTextNodes` 走自动化单测，不进 UAT**。已在 `blueprintAnnotations.test.ts:165` 落了 `describe('collectTextNodes —— 触 DOM 的薄函数（能力锁判定 happy-dom 支持 TreeWalker）')`，**未 `it.skip`**。
- **`rangeOffsets` 可在 happy-dom 里端到端测**（`createRange` + `selectNodeContents` 都真实可用）。
- **唯一仍归 UAT 的是「定位精度」**：`getBoundingClientRect` 恒 0 矩形 ⇒ 选区 popover 的**落点坐标**测不了，只能测「有没有算出 offset」。115-05 写选区 popover 时按此规划：逻辑层自动化、视觉落点 UAT。
- 快照任一值变化 = happy-dom 升级改了能力，**不是业务回归**；改快照前先按文件头 docstring 重估 `collectTextNodes` 的测试策略。

---

## 3. ⭐ 唯一轮询消费点：`useBlueprintLive` 的两形态设计与**变异验证实证**

### 实现形态（三查询两形态，⛔ 不得统一）

```ts
// ① snapshot —— 响应体自带 current_status，读**它自己的** data，链条自持
refetchInterval: query =>
  LIVE_BLUEPRINT_STATUSES.has(String(query.state.data?.current_status ?? ''))
    ? LIVE_REFETCH_MS : false,

// ② doc / events —— 响应体**没有**状态字段，只能读外部 isLive
refetchInterval: () => (isLive.value ? LIVE_REFETCH_MS : false),

// ③ ⭐ 启动保证（⛔ 不得删除）
watch(isLive, (on) => {
  if (on) { docQuery.refetch(); eventsQuery.refetch() }
})
```

`LIVE_REFETCH_MS = 5_000`；`LIVE_BLUEPRINT_STATUSES = {researching, drafting, ai_reviewing}`（从 `~/config/blueprintStatus` import，⛔ composable 内不另写一份）。

### ⭐ 变异验证（执行期实跑，结论如下）

按计划要求做了一次真实变异：把 `watch(isLive, ...)` 整段注释掉 → 复跑 `useBlueprintLive.spec.ts`：

```
× ⭐ 非活跃 → 活跃：doc/events 的调用次数从 1 变 2（BLOCKER-1）
AssertionError: expected 1 to be 2 // Object.is equality
 Test Files  1 failed (1)
      Tests  1 failed | 2 passed (3)
```

**转红，且失败信息正是预测的症状**（doc/events 停在 1 次 = 永不装定时器）。恢复 `watch` 后复跑 **3 passed**，且 `git status` 确认 `useBlueprintLive.ts` **逐字节还原**（工作树干净）。

⇒ **BLOCKER-1 被一条可证伪用例真正堵死，不是纸面声明。** 另两条用例（终态自动停 / 恒非活跃不轮询）在变异下**仍绿**——这正确：它们不依赖启动路径，若也跟着红反而说明断言写串了。

### 为什么这条 `watch` 非有不可（后人删它之前请先读这段）

函数式 `refetchInterval` **只在本查询自己的 state 更新、或 options 触发 `setOptions` 时重算**；函数体里读外部 ref **不是被追踪的响应式依赖**（vue-query 的 `cloneDeepUnref` 不下探函数体）。打开一个 `drafting` 蓝图时三查询近乎同时发出，doc/events 先落地而共享的 `currentStatus` 此刻还是 `''` ⇒ 算出 `false`、**永不装定时器、也永不再重算**。症状是**首屏有内容、无报错、快照徽标还在跳，而章节进度冻结在打开那一刻**——正是 P-9 那种静默假通过。

仓内唯一「函数体读外部 ref」的先例 `pages/admin/observability/index.vue:83` 恰好**反证**了这一点：那一页真正驱动刷新的是页面自建的 `setInterval` + `invalidateQueries`（:47-76）。本文件用 `watch` + `refetch()` 承担同一职责，⛔ 不复制它的 `setInterval` 方案（会绕开 TanStack Query 的窗口失焦策略）。

### 返回契约（115-03/04/06 逐字消费）

```ts
useBlueprintLive(artifactId: Ref<string>, versionId?: Ref<string | undefined>) => {
  isLive:            ComputedRef<boolean>
  currentStatus:     ComputedRef<string>          // 一律以快照响应体为准，⛔ 不乐观推断
  doc:               UseQueryReturnType<BlueprintDocumentResponse>
  snapshot:          UseQueryReturnType<BlueprintReviewSnapshot>
  eventsQuery:       UseQueryReturnType<BlueprintEventsResponse>
  events:            ComputedRef<BlueprintEvent[]>
  stageTimeline:     ComputedRef<StageTimelineNode[]>
  sectionProgress:   ComputedRef<Record<string, SectionProgress>>
  statusProgressKey: ComputedRef<string>          // 段无事件时的状态级回落
  refetchAll:        () => void
}

interface StageTimelineNode { stage: string; state: 'idle'|'running'|'done'|'failed'; events: BlueprintEvent[]; latestTs: string }
interface SectionProgress   { key: string; fallbackKey: string; payload: Record<string, unknown>; ts: string }
```

**`sectionProgress` 的形状要点**：`Record<sectionKey, SectionProgress>`，一段取其命中事件中 `ts` 最大的一条。`key` 是插值文案键、`fallbackKey` 是 `<key>Generic` 无参兜底；**payload 缺插值键时 `key` 自动降级为 `fallbackKey`**（P-8：payload 的键 schema 层零保证，⛔ 别指望 vue-i18n 报错，它会渲染成「正在调研 undefined…」）。未被任何事件覆盖的段（`impact_analysis` / `interaction_flows` / `must_haves` / `associations`）**不出现在表里** ⇒ 调用方回落 `statusProgressKey`。

### TanStack Query key 约定（⭐ 全相位统一，⛔ 别发明第四种）

| 查询 | queryKey | staleTime |
|---|---|---|
| 正文 | `['blueprint', 'doc', artifactId, versionId ?? 'current']` | `30_000` |
| 人审快照 | `['blueprint', 'snapshot', artifactId]` | `0` |
| 阶段事件 | `['blueprint', 'events', artifactId]` | `0` |

一律 `queryKey: computed(() => [...])`；失效走**前缀匹配** `invalidateQueries({ queryKey: ['blueprint'] })`（⛔ 不用 UI-SPEC §3.7 的 `predicate` 写法，仓内零先例且本页只有一个 artifact，全域失效无副作用）。

---

## 4. 数据契约层：TS 类型与 API 函数签名（115-03…07 直接照抄）

### 4.1 与 115-01 契约表的逐键核对结论：**全部一致**

| 115-01 契约 | `types/blueprint.ts` 实现 | 核对 |
|---|---|---|
| ① `version_id`/`version_no`/`is_current`/`produced_by_ref`/`created_at`/`content`/`quality` | `BlueprintDocumentResponse` 七键 | ✅ 逐字 |
| ② `session_id`/`current_stage`/`events[]{id,event,payload,ts}` | `BlueprintEventsResponse` | ✅ |
| ③ `threads[]`（十二键） | `BlueprintThreadsResponse` / `BlueprintThreadDetail` | ✅ |
| ④ `thread_id`/`current_status` | `CreateBlueprintCommentResponse` | ✅ |
| ⑤ **`current_status`**（⛔ 不是 `blueprint_status`） | `BlueprintListItem.current_status` | ✅ **订正已落地** |
| ⑤ 五键分页 `{total, items, page, page_size, has_next}` | `BlueprintListResponse` | ✅ **五键齐全** |

`blueprint_status` 在前端**只作为 query 参数名**出现（`ListBlueprintsParams.blueprint_status` 与 `api/blueprints.ts:98`），响应键零使用——这是刻意的，且两处都有注释说明「后端 query 参数名 ≠ 响应键」。

### 4.2 `api/blueprints.ts` 全部 19 个函数

```ts
// —— 115-01 五个新端点 ——
getBlueprintDocument(artifactId: string, params?: { version_id?: string }): Promise<BlueprintDocumentResponse>
getBlueprintEvents(artifactId: string): Promise<BlueprintEventsResponse>
getBlueprintThreads(artifactId: string): Promise<BlueprintThreadsResponse>
createBlueprintComment(artifactId: string, payload: CreateBlueprintCommentPayload): Promise<CreateBlueprintCommentResponse>
listBlueprints(params?: ListBlueprintsParams): Promise<BlueprintListResponse>

// —— 114-05 人审面（六动作） ——
getBlueprintReviewSnapshot(artifactId: string): Promise<BlueprintReviewSnapshot>
approveBlueprint(artifactId: string): Promise<BlueprintApproveResponse>
rejectBlueprint(artifactId: string, payload?: { comment?: string, anchor?: Record<string, unknown> }): Promise<BlueprintRejectResponse>
answerThread(artifactId: string, threadId: string, payload: { body: string }): Promise<BlueprintAnswerResponse>
resolveFinding(artifactId: string, findingId: string, payload: { reason: string }): Promise<BlueprintFindingActionResponse>
dismissFinding(artifactId: string, findingId: string, payload: { reason: string }): Promise<BlueprintFindingActionResponse>

// —— 确认门（快照 + 七动作） ——
getBlueprintGate(artifactId: string): Promise<BlueprintGateSnapshot>
confirmGate(artifactId: string): Promise<BlueprintGateActionResult>
removeRepo(artifactId, payload: { repository_id: string }): Promise<BlueprintGateActionResult>
addRepo(artifactId, payload: { repository_id: string, role?: string, responsibility?: string }): Promise<BlueprintGateActionResult>
reclassifyRole(artifactId, payload: { repository_id: string, role: 'direct'|'indirect' }): Promise<BlueprintGateActionResult>
editResponsibility(artifactId, payload: { repository_id: string, responsibility: string, rerun?: boolean }): Promise<BlueprintGateActionResult>
rejectedToBoundary(artifactId, payload?: { repository_id?: string }): Promise<BlueprintBoundaryDraftResult>
upgradeResearch(artifactId, payload): Promise<BlueprintGateActionResult>
```

`export default { …全部 19 个 }`；barrel 已导出 `blueprintsApi`。

**⛔ 三条零调用纪律（源码已核实零命中）**：`edit-blocks` / `editBlocks`（本相位无 block 编辑面）、`getRelated` / `getArtifactAssociations`（P-5：它们查 `initiatives.Artifact` 投影的 KnowledgeEntity，拿蓝图的 `delivery.Artifact.id` 去调**必然 404/空**）。版本轨**继续用既有 `deliveryArtifacts.getArtifactTimeline`**，⛔ 本模块不 re-export（避免同一端点两个入口）。

### 4.3 `api/repositoryChunks.ts`（P-3 判据封装在此）

```ts
interface RepoChunkRef  { chunk_id: string; file_path: string; line_start: number; line_end: number; chunk_index: number }
interface ChunkAtResult { chunks: RepoChunkRef[]; usable: boolean }

getChunkAt(repositoryId: string, params: { path: string, line: number, branch_name?: string }): Promise<ChunkAtResult>
getRepositoryCharter(repositoryId: string): Promise<RepoCharter | null>
```

⭐ **`usable` 覆盖全部不可用情形**：400 / 404 / 5xx / 网络失败，**以及最容易漏的那一种——200 但 `chunks` 为空**（无命中与「文件被排除规则挡掉」在后端 `chunk_at_views.py:60` 刻意不可区分）。任何异常一律 `catch` 成 `{chunks: [], usable: false}`，**不上抛**。

⛔ **调用点只看 `usable`，不看状态码、不读错误体**——`chunk-at` 的错误体键是 `error` 不是 `detail`，`ApiError.detail` 会回落成无意义的 `'请求失败'`（`client.ts:237,242`）。

---

## 5. 纯函数层：完整导出清单（⭐ 标注哪些触 DOM）

### 5.1 `utils/blueprintBlocks.ts` —— 全部**纯函数，零 DOM**

| 函数 | 签名 | 契约要点 |
|---|---|---|
| `blockText` | `(block: unknown) => string` | ⭐ **四分支字段优先级，⛔ 绝不看 `block.type`**（见下） |
| `itemKey` | `(item: Record<string, unknown>, field: string, index: number) => string` | 复刻后端 `_item_key`：优先取标识字段，缺失回退位置下标字符串化 |
| `iterBlocks` | `(content: unknown) => IteratedBlock[]` | 13 处 collect 逐段对齐；⛔ 不走查 `must_haves`/`decision_log`/`deferred_ideas`/`execution_plan` |
| `canonicalBlockFingerprint` | `(block: unknown) => string` | **递归排序键**后再 stringify（后端是 `json.dumps(sort_keys=True)`） |
| `classifyBlockDiff` | `(contentA, contentB) => BlockDiffResult` | `added` / `removed` / `modified` 三类，按 `block_id` 建索引 |
| `sectionKeyForEvent` | `(eventName: string) => string[]` | 21 事件映射；`repo_research.*` 与 `spec_gate.locked` 映射**两段**；未映射返 `[]` |
| `progressKeyForEvent` | `(eventName: string) => string` | 事件 → i18n 进度文案 key |
| `stageForEvent` | `(eventName: string) => string` | 事件 → stage（供阶段时间线聚合） |
| `summaryText` | `(blocks: unknown, maxLen = 200) => string` | `meta.summary` 首块纯文本截断 |
| `BLUEPRINT_STAGES` | `readonly string[]` | 阶段时间线的固定顺序 |
| `BLUEPRINT_EVENT_NAMES` | `readonly string[]` | 21 个事件名 |

**`IteratedBlock` = `{ sectionPath: string, sectionKey: string, block: BlueprintBlock }`。**

⭐ **`blockText` 的四分支为什么不能按 `type` 分派（P-13，全相位最难逮的一类错）**：后端 `_block_text` 完全不看 `block.type`，而 schema 对 `text` 无任何类型约束 ⇒「`type: pseudocode` 且 `text` 非空」的块**完全合法**。按 type 分派会得到与后端不同的坐标系，后果是 offset 偏移后**仍在合法范围内** ⇒ 不触发越界降级、不报错、`<mark>` 照渲，**只是圈错了字**。

优先级：① `text` 非空 string → 直取；② `text` 是数组 → `map(String).join('\n')`；③ `code.source` 非空 string → 取它；④ `rows` 数组 → 逐行逐格扁平后 `join('\n')`；⑤ 其余 → `''`。

已上双证：`blueprintBlocks.test.ts` 有「pseudocode 同时带非空 `text` 与 `code.source` ⇒ 取 `text`」的 fixture 用例，且源码扫描断言 `blockText` 函数体内 `.type` 零命中（实跑输出 `blockText field-priority OK`）。

### 5.2 `utils/blueprintAnnotations.ts` —— ⭐ 只有 `collectTextNodes` / `rangeOffsets` 触 DOM

| 函数 | 签名 | 触 DOM？ |
|---|---|---|
| `isValidAnchor` | `(anchor: {start?, end?}, textLength: number) => boolean` | ❌ 纯函数 |
| `sliceBlockText` | `(text: string, anchors: readonly BlockAnchorRange[]) => TextSegment[]` | ❌ 纯函数 |
| `degradedThreadIds` | `(text: string, anchors: readonly BlockAnchorRange[]) => string[]` | ❌ 纯函数 |
| `groupThreadsByBlock` | `(threads) => Record<string, BlueprintThreadDetail[]>` | ❌ 纯函数 |
| `anchorRangesForBlock` | `(threads, blockId) => BlockAnchorRange[]` | ❌ 纯函数 |
| `sidebarGroups` | `(threads, orphanedThreads?) => SidebarGroups` | ❌ 纯函数 |
| `annotationCounts` | `(groups: SidebarGroups) => {unresolvedBlocker, pendingClarification, orphaned}` | ❌ 纯函数 |
| `hasAnchorLocator` | `(anchor: BlueprintAnchor \| null \| undefined) => boolean` | ❌ 纯函数 |
| `offsetInFlatText` | `(nodes: Text[], container: Node, offset: number) => number` | ❌ **纯数据，恒可单测** |
| `collectTextNodes` | `(root: Node \| null) => Text[]` | ⭐ **触 DOM**（`createTreeWalker`；`null` 入参返 `[]`） |
| `rangeOffsets` | `(range: Range \| null, root: Node \| null) => {start, end} \| null` | ⭐ **触 DOM**（= 上面两者的组合） |

**类型**：
```ts
interface BlockAnchorRange { threadId: string; start: number; end: number }
interface TextSegment      { text: string; threadIds: string[] }
interface SidebarGroups    { open: BlueprintThreadDetail[]; answered: ...; closed: ...; orphaned: ... }
```

**`sliceBlockText` 契约**：校验（`Number.isInteger` 且 `0 <= start < end <= text.length`，不合法者剔除并计入降级集合）→ 按 start 升序 → **重叠不合并**，切成不相交子段，每段携带其覆盖的 threadId 集合。⛔ **返回结构化数组而非 HTML 串**（渲染层 `v-for` + mustache，XSS 面 = 0，T-115-13）。测试含 `result.map(s => s.text).join('') === text` 的拼接还原断言——能逮住任何切点算术错误。

**`sidebarGroups` 四组判据（⭐ 前三组的 `anchor_status !== 'orphaned'` 否定项不可省）**：失锚是**锚定维度**、`status` 是**处置维度**，两者正交；漏掉否定项会让一条 `open` 的失锚线程在侧栏出现两次、计数重复。`orphanedThreads` 参数缺省时从 `threads` 自行筛，传入时直接用快照的 `orphaned_threads`（⛔ 前端不再二次过滤，114 MJ-02 已保证里面只有真失锚）。

**⚠️ 第三态别漏（P-7）**：`anchor === null` 但 `anchor_status === 'anchored'` 的系统线程（规格门/确认门/无划线驳回评论）**必须出现在侧栏按 status 分组，但正文无任何标记**。`hasAnchorLocator` 就是给这一态用的识别器。三条并列断言已在测试里落地：① `open` 且 `orphaned` 的线程只出现一次；② `anchor === null` 的系统线程仍进 status 组；③ 越界线程走降级但**不进**失锚组。

---

## 6. 批注令牌：`annotationClass` 的签名与全部分档（⭐ 组件只调它，⛔ 不写颜色）

```ts
annotationClass(kind: string, severity: string, status: string, active = false): string
```

返回值**恒含且仅含一条 `bg-*`**（无底纹档是 `bg-transparent`），可直接作为 `<mark>` 的 `:class`——浏览器默认黄底一定被压掉。

**五色相**（`annotationHue(kind, severity)` 决定；⚠️ Tailwind 任意值语法用**下划线**代替空格）：

| 色相 | 触发 | 描边 | WCAG | 底纹 |
|---|---|---|---|---|
| `blocker` | `ai_review_finding` + `blocker` | `hsl(0_72%_45%)` | 5.83:1 | `hsl(0_72%_51%/…)` |
| `warning` | `ai_review_finding` + `warning` | `hsl(26_90%_37%)` | 5.02:1 | `hsl(38_92%_50%/…)` |
| `info` | `ai_review_finding` + `info` | `hsl(215_16%_40%)` | 6.08:1 | `hsl(215_16%_47%/…)` |
| `teal` | `ai_clarification` / `repo_confirmation` | `hsl(167_76%_32%)` | 3.74:1 | `hsl(168_76%_42%/…)` |
| `violet` | `human_comment` | `hsl(263_70%_50%)` | 7.24:1 | `hsl(263_70%_50%/…)` |

**状态叠加（正交于色相）**：`open` 2px solid + 满档底纹；`answered` 2px dashed + 底纹 ×0.6；`resolved`/`dismissed` 1px dotted + 改用 `hsl(215_16%_47%)` + 无底纹；`active` 描边加粗 3px + `[outline:2px_solid_hsl(167_76%_32%)] [outline-offset:1px]`（**不透明**）+ 底纹 ×1.4 封顶 0.20。

⭐ **两条已核实的 WCAG 纪律**：teal 描边用的是**降档后**的 `hsl(167_76%_32%)`，⛔ 全文件零命中 teal-500 原值 `hsl(168 76% 42%)` 作描边（原值白底仅 2.49:1，不过 1.4.11 的 3:1）；amber `hsl(38_92%_50%)`（2.14:1）**只作底纹**。`annotationTokens.ts` 有 26 处 `hsl(`，而 `BlueprintStatusBadge.vue` **零 `hsl(`**——颜色单一来源成立。

**辅助导出**：`ANNOTATION_PRIORITY`（`blocker > warning > human_comment > info/ai_clarification`）、`ANNOTATION_STATUS_PRIORITY`（`open > answered > resolved/dismissed`）、`compareAnnotationPriority`、`pickTopThread(threads)`（一个 `<mark>` 覆盖多条时取最高优先级着色）、`MARK_BASE_CLASS`、`annotationHue`、`AnnotationHue` 类型。

---

## 7. 配置、store、其余两个 composable

### 7.1 `config/blueprintStatus.ts` 12 态表（存 `labelKey`，⛔ 零中文字面量）

| status | labelKey 尾段 | icon（裸名） | variant | animate |
|---|---|---|---|---|
| `researching` | `status.researching` | `lucide--scan-eye` | `info` | ✅ |
| `drafting` | `status.drafting` | `lucide--pen-line` | `info` | ✅ |
| `ai_reviewing` | `status.ai_reviewing` | `lucide--shield-check` | `info` | ✅ |
| `needs_clarification` | `status.needs_clarification` | `lucide--help-circle` | `warning` | — |
| `pending_review` | `status.pending_review` | `lucide--user-check` | `warning` | — |
| `confirmed` | `status.confirmed` | `lucide--check-circle` | `success` | — |
| `implementing` | `status.implementing` | `lucide--hammer` | `info` | ✅ |
| `implemented` | `status.implemented` | `lucide--check-check` | `success` | — |
| `archived` | `status.archived` | `lucide--archive` | `muted` | — |
| `failed` | `status.failed` | `lucide--x-circle` | `destructive` | — |
| `superseded` | `status.superseded` | `lucide--file-x` | `muted` | — |
| `''`（v0 旧数据） | `status.legacy` | `lucide--file-text` | `outline` | — |

⭐ **`''` 命中 legacy 档而非 unknown**（用 `in` 判定而非真值判定）；未知态兜底 `{labelKey: 'knowledge.blueprints.statusUnknown', icon: 'lucide--help-circle', variant: 'muted'}`——**兜底键刻意不放在 `status.*` 子树下**，以保住「子树 12 键 ↔ 配置 12 档」的一一对应等式（配置单测锁死该等式）。

- `EDITABLE_BLUEPRINT_STATUSES`（六值）= `{'', researching, drafting, ai_reviewing, needs_clarification, pending_review}`，逐字对齐后端 `blueprint_lifecycle_service.py:92`。⚠️ 后端入参是 **artifact**、前端是 **status 字符串**，这是刻意差异。`isBlueprintEditable(status)` **只驱动渲染与否，不是权限**（权限一律以后端状态码为准，T-115-20）。
- `LIVE_BLUEPRINT_STATUSES`（三值）= `{researching, drafting, ai_reviewing}`。
- `PRODUCED_BY_PREFIXES` **五档**：`human_edit:` → `version.reasonHumanEdit`/`lucide--user-pen`/`secondary`；`ai_review_reflow:` → `reasonAiReviewReflow`/`lucide--refresh-cw`/`info`；`human_block_restore:` → `reasonHumanBlockRestore`/`lucide--shield`/`warning`；`blueprint_review_reject:` → `reasonBlueprintReviewReject`/`lucide--undo-2`/`destructive`；兜底 → `reasonAiGenerated`/`lucide--sparkles`/`muted`。查表函数 `producedByReason(ref)`。

### 7.2 `stores/useBlueprintViewerStore.ts` —— **只放三项客户端偏好**

```ts
useBlueprintViewerStore() => {
  sidebarCollapsed:       Ref<boolean>                        // useLocalStorage 'blueprint-sidebar-collapsed'
  showClosedAnnotations:  Ref<boolean>                        // useLocalStorage 'blueprint-show-closed-annotations'
  kindFilters:            Ref<BlueprintThreadKindFilter[]>    // useLocalStorage 'blueprint-kind-filters'；空数组 = 不筛选
  toggleSidebar(): void
  toggleKindFilter(kind: BlueprintThreadKindFilter): void
  resetKindFilters(): void
}
```

**与 analog（`analyticsFilters.ts` 明确不持久化）的 DIFFER**：这三项走 `useLocalStorage` 持久化，因为它们是**用户偏好**而非查询语境。⛔ **服务端态（doc/threads/snapshot/events/timeline/gate/list）一律不进 store**，全部走 TanStack Query（源码已核实 store 内零命中）。`kindFilters` 用空数组表达「全选」，⛔ 不用 `null`（避免两种空态）。

### 7.3 `composables/useBlueprintAnnotations.ts` —— 选中态的唯一状态源

```ts
useBlueprintAnnotations(threads: Ref<BlueprintThreadDetail[]>, orphanedThreads?: Ref<BlueprintThreadDetail[]|undefined>) => {
  activeThreadId: Ref<string | null>
  groups:         ComputedRef<SidebarGroups>
  threadsByBlock: ComputedRef<Record<string, BlueprintThreadDetail[]>>
  counts:         ComputedRef<{unresolvedBlocker, pendingClarification, orphaned}>
  selectThread(threadId: string | null): void
  clearActive(): void
  findThread(threadId: string): BlueprintThreadDetail | undefined
}
```
⛔ 组件内不得各自持有第二份 `activeThreadId`；侧栏与正文点击都走 `selectThread`。`findThread` 供深链 `?thread=` 与「一个 mark 覆盖多条」的微型 Popover 使用。

### 7.4 `composables/useCitationPreview.ts` —— ⭐ catch 分支与 analog **完全相反**

```ts
useCitationPreview() => { open, loading, citation, data, fallback, sourceType, openCitation, openWithSnapshot, close }
```
analog（`pages/knowledge/index.vue:165-191`）失败时关弹窗 + toast；**本相位 UI-SPEC §10.1 明令兜底不留白** ⇒ 任何失败一律把 `fallback` 置为 citation 自带的 `title` / `quote` 并**保持弹窗打开**，⛔ 不关弹窗、⛔ 不回显后端错误体。源码扫描已实跑核实 catch 分支内无 `open.value = false`（输出 `citation fallback OK`）。

---

## 8. 三处纯追加点（⭐ 全相位只此一次，后续 plan 不再碰）

`git diff 02ab1684..HEAD -- web/src/api/index.ts web/src/styles/main.css web/src/locales/zh-CN.json | rg "^-[^-]"` → **空输出，删除行 = 0**。

### 8.1 i18n `knowledge.blueprints.*`（324 行）—— 25 个顶层键

```
pageTitle pageDescription tabPanel status statusUnknown section sectionEmpty mustHaves
progress block repo api impact flow annotation thread finding version diff review gate
quality citation error readonly
```
外加 `knowledge.tabs.blueprints = "技术方案"`。`status` 子树 **12 键**（与配置 12 档一一对应）、`section` 子树 **10 键**、`progress` 子树 **34 键**。

⭐ **`progress.*` 的「带插值 + `*Generic` 兜底」配对规则**：34 个 progress 键中 **10 条带插值**，每条都配了同名 `+Generic` 的无参兜底键（实跑校验输出 `progress fallback OK`）。需要兜底的插值键：`question_count` / `decision_log_count` / `candidate_count` / `repository_name` / `fitness_verdict` / `attempt` / `round` / `seq` / `to_key` / `satisfied_count`。**消费方在 payload 缺键时用 `fallbackKey`**——`useBlueprintLive` 的 `resolveProgressKeys` 已自动完成这个降级，组件直接用 `SectionProgress.key` 即可。

⭐ **404 单键纪律**：`error.notFoundOrForbidden = "无权访问或该蓝图不存在"` 是 404 的**唯一**键；`error` 子树其余键为 `blocked` / `conflict` / `conflictVersion` / `unavailable` / `retry` / `refresh` / `backToKnowledge`，**无任何** `notFound` / `notExist` / `forbidden` 独立键。理由：后端对「artifact 不存在」与「非项目成员」刻意返回**逐字相同**的 404（MJ-03 存在性防线），前端翻成两种文案那道防线就被差分枚举破了（T-115-17）。

### 8.2 safelist 12 图标（`main.css` +9 行，删除 0）

追加两条 `@source inline(...)`（上方一段中文注释说明来源），12 个图标全部命中：`pen-line` `hammer` `check-check` `archive` `file-plus` `file-pen-line` `file-cog` `book-open` `scroll-text` `list-checks` `user-pen` `refresh-cw`。

⭐ **safelist 只服务「运行期拼接的裸名」**（`getBlueprintStatusConfig` 等查表函数把裸名拼成 `` `icon-[${config.icon}]` ``，源扫描看不到成品类名）。⛔ **写在 `.vue` 源码里的字面量完整类名不需要 safelist**（如 `icon-[lucide--target]`、115-03 的 `icon-[lucide--message-square-dot]`、115-05 的 `icon-[lucide--mouse-pointer-click]`）——Tailwind content 扫描直接命中，**缺席不是遗漏**。后续 plan 发现某图标不在 safelist 时**先判断它是不是字面量**，⛔ 别据此回报「115-02 漏了」。

⚠️ **两种 icon 契约不要统一**（抄错就出不来图标）：`CompactEmptyState`（:17）与 `StatusBadge`（:38）内部做 `` :class="`icon-[${icon}]`" `` ⇒ 收**裸名**；`AnchorNavLayout` 的 `NavSection.icon`（:91）⇒ 收**完整类名**。

### 8.3 api barrel（`api/index.ts` +10 行，删除 0）

`blueprintsApi` + `repositoryChunksApi` 各两行成组。⚠️ **落位与计划不同**：计划说「追加在文件末尾」，实测末尾追加会被 `perfectionist/sort-exports` 判为乱序，而对该文件跑 `eslint --fix` 会**重排既有分组**（违反纯追加纪律）。改为**按字典序插入**（`blueprints` 在 `auth` 与 `chat` 之间、`repositoryChunks` 在 `repositories` 之后），既零删除行也零新增 lint 问题。已在源码注释里写明这个取舍。

---

## 9. 源码扫描守卫（`blueprint-source-guard.spec.ts`，6 条，后续每个 plan 都要复跑）

形态平移自后端 `test_blueprint_inv6_guard.py`：常量正则 + `node:fs` 递归遍历 + 违规清单聚合 + **断言消息把「为什么存在」和「怎么修」都写进去**。扫描面 `SCAN_DIRS = ['src/components/blueprint', 'src/pages/knowledge/blueprints']`，跳过 `__tests__`。

| # | 断言 | 内容 |
|---|---|---|
| 1 | 扫描面自锁 | 目录被改名而扫描常量没跟着改时，防止「扫了 0 个文件所以全绿」静默通过 |
| 2 | §20 断言 6 | `refetchInterval` 零命中 —— 轮询只能在 `useBlueprintLive.ts` |
| 3 | §20 断言 10 | `edit-block` / `edit-blocks` / `editBlocks` 零命中 |
| 4 | §20 断言 4 | `knowledge.blueprints.error.*` 只允许登记过的 8 个键 |
| 5 | §20 断言 4（续） | 中文竞品文案零命中（`该蓝图不存在` / `无权限访问` / `方案不存在` 等） |
| 6 | T-115-13 | 扫描面零 `v-html` |

⚠️ **本阶段两个扫描目录几乎为空 ⇒ 用例平凡通过**，这是刻意的：守卫先就位，才能在第一个违规出现的那一刻拦住，而不是等相位结束回头审。115-03 起每个 plan 都会把它压实。

---

## 10. 边界核算（受限面 / 冻结面 / 依赖）

| 检查 | 结果 |
|---|---|
| 三处追加点删除行 | **0**（`rg "^-[^-]"` 空输出） |
| 零改动清单 12 个文件 | **全部 `git diff` 为空**（`TechPlanCard.vue` / `RoutingDecisionPanel.vue` / `NodeDataTab.vue` / `ArtifactTimeline.vue` / `config/status.ts` / `api/client.ts` / `api/deliveryArtifacts.ts` / `api/knowledge.ts` 等） |
| 依赖变更 | `git diff web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml` → **0 行** |
| 后端改动 | `git diff --name-only 02ab1684..HEAD -- server/` → **0 个文件** |
| 变更总量 | 23 个文件、**+4372 行 / −1 行** |

**唯一那 1 行删除**在 `BlueprintStatusBadge.vue`——**是本 plan 自己新建的文件**（commit 2 建、commit 3 改），把 docstring 里的「⛔ 全程 mustache，零 \`v-html\`」改写为「不走任何原始 HTML 注入指令」。原因：该文件位于源码守卫的扫描面内，docstring 里的**字面量** `v-html` 会触发守卫断言 6 自己。属自洽修正，不违反纯追加纪律（后者只约束既有文件）。

---

## 11. Task Commits

| Task | 内容 | Commit | 变更 |
|---|---|---|---|
| 1 | 打通前端环境、settle happy-dom 能力假设并建齐蓝图数据契约 | `3055e623` | 4 文件 / +1083 |
| 2 | 蓝图 API 封装、12 态配置、批注令牌与状态徽标 | `6e345dd3` | 7 文件 / +1006 |
| 3 | 蓝图纯函数层、唯一轮询消费点、store/composable 与源码守卫 | `02563897` | 13 文件 / +2284 / −1 |

---

## 12. Deviations from Plan

### 1. `[Rule 3 - 阻塞] api barrel 改按字典序插入，不追加在文件末尾`
- **发现于**：Task 1
- **问题**：计划要求「文件末尾新起一组」，但 `perfectionist/sort-exports` 会把末尾追加判为乱序；而 `eslint --fix` 会重排既有分组，违反 CREATE-ONLY 纯追加纪律。
- **处理**：按字典序插入（`blueprints` 在 `auth`/`chat` 之间、`repositoryChunks` 在 `repositories` 之后），源码注释写明取舍。删除行仍为 0，且零新增 lint 问题。
- **文件**：`web/src/api/index.ts` ｜ **Commit**：`3055e623`

### 2. `[Rule 2 - 缺失的关键防护] unknown 兜底 labelKey 移出 status.* 子树`
- **发现于**：Task 2
- **问题**：计划要求兜底用 `knowledge.blueprints.status.unknown`，但那会让 `status` 子树变成 13 键，破坏「子树键数 ↔ 配置档数」的一一对应等式（配置单测正要锁这个等式）。
- **处理**：兜底键改为 `knowledge.blueprints.statusUnknown`（平级），子树严格 12 键。
- **文件**：`web/src/config/blueprintStatus.ts`、`web/src/locales/zh-CN.json` ｜ **Commit**：`6e345dd3`

### 3. `[Rule 1 - 自洽修正] BlueprintStatusBadge docstring 里的字面量 v-html 会触发自己的守卫`
- **发现于**：Task 3
- **问题**：源码守卫断言 6 扫描 `src/components/blueprint/**` 的 `v-html` 字面量，而该组件 docstring 恰好写了「零 \`v-html\`」。
- **处理**：改写为「不走任何原始 HTML 注入指令」，语义不变。**这是本 plan 唯一的 1 行删除**，发生在自建文件内。
- **文件**：`web/src/components/blueprint/BlueprintStatusBadge.vue` ｜ **Commit**：`02563897`

### 4. `[执行事实登记] auto-imports.d.ts / components.d.ts 是第 4、5 处既有文件改动`
- **性质**：unplugin（`unplugin-auto-import` / `unplugin-vue-components`）**工具自动生成**的声明文件，随新建 composable/store/组件自动重写，非手工编辑。两者均**纯追加**（+17 / +1 行，零删除），且被 eslint ignore。
- **判断**：计划的「只允许改三个既有文件」约束针对**手写源文件**；生成物随源码同步是既有工程约定（它们已在 git 跟踪）。不视为违规，但如实登记以免后续 plan 的边界核算把它当异常。

### 5. `[验收脚本自身缺陷，非实现缺陷] 计划的 404 竞品键正则会误伤获批键`
- **发现于**：续跑核查
- **问题**：计划的验收脚本用 `/notFound$|notExist|forbidden/i` 过滤 `error` 子树键名。由于带 `/i` 且 `forbidden` 是**子串匹配**，它会把**唯一获批**的 `notFoundOrForbidden` 自己判为竞品键 ⇒ 脚本恒抛错。
- **核实**：这是脚本缺陷，**实现是正确的**。用修正后的判据（先排除获批键再扫竞品）复跑通过：`error` 子树只有 `notFoundOrForbidden` 一个 404 键，值逐字 `无权访问或该蓝图不存在`，其余 7 键（`blocked`/`conflict`/`conflictVersion`/`unavailable`/`retry`/`refresh`/`backToKnowledge`）均非 404 竞品。
- **处理**：不改代码。后续 plan 若复用该验收脚本，请用修正版判据。

### 6. `[基线事实修正] "pnpm lint 通过" 的前提不成立`
- **核实**：仓库既有 111 个 lint 问题（106 errors / 5 warnings），分布在 27 个与蓝图无关的文件。本 plan 的 23 个文件零新增问题（唯一命中是 `api/index.ts` 的 `artifacts`/`notifications` 排序，已核实基线既有）。
- **处理**：不修历史 lint（超出相位边界，且会污染零改动清单）。⭐ **后续 plan 的 lint 判据改为「自己碰的文件零新增问题」。**

### 7. `[环境事实登记] pnpm 10 会改写 web/pnpm-workspace.yaml`
- **现象**：在本 worktree 跑**任何** `pnpm` 命令（含 `pnpm exec vitest`），pnpm 10.34.2 会自动向 `catalogs` 回填缺失条目（`three` / `mermaid` / `wordcloud` / `3d-force-graph` / `medium-zoom` / `@types/*`），产生非预期的工作树修改。
- **处理**：本次收口已 `git checkout -- web/pnpm-workspace.yaml` 还原，三个提交内**零依赖变更**。⭐ **后续 plan 跑完前端门后请检查 `git status`，把这个漂移还原再提交**，否则会被误当成依赖变更。

---

## 13. Decisions（四处 UI-SPEC 订正 + 两处范围定夺）

| # | 订正/定夺 | 内容 |
|---|---|---|
| 1 | **UI-SPEC §8.3 轮询写法** | 改「快照函数式读自身 `data` + doc/events 函数式读 `isLive` **且配 `watch(isLive)` 踢动**」两形态；**删掉** `useDocumentVisibility()` 那一条（TanStack Query 内建 `refetchIntervalInBackground: false`，仓内 10 处先例都没写）。已实跑变异验证（§3）。 |
| 2 | **UI-SPEC §10.1 chunk-at 判据** | 可用判据是 `!ok \|\| chunks.length === 0`（**200-空 chunks 也不可用**），⛔ 不是「非 2xx」；判据封装进返回类型 `{chunks, usable}`，调用点不各自判。 |
| 3 | **UI-SPEC §3.6/§10.1 代码正文来源** | `chunks[]` 只有 `{chunk_id, file_path, line_start, line_end, chunk_index}`，**没有代码正文**；全仓也没有「按 path + 行区间取源码」的读面。⇒ `CitationCodePreview` 本相位降级为「**文件路径 + 行号区间 + citation 的 `quote` 快照**」，用与 `pseudocode` 块同一套 `<pre class="font-mono">` + 行号渲染。⛔ 不引 CodeMirror、⛔ 不新增后端端点（该读面归属 Phase 116）。 |
| 4 | **UI-SPEC §7.4 选区 popover** | 用 **reka-ui 直接导入**的 `PopoverAnchor` + 零尺寸虚拟锚点 div。**已核实**：`reka-ui@2.9.10` 的 `dist/index.d.ts` 与 `dist/index.js` **都导出 `PopoverAnchor`**（`_default$120 as PopoverAnchor, PopoverAnchorProps`）⇒ **无需降级到 `PopoverTrigger` 方案**。本地 barrel `~/components/ui/popover/index.ts` 确认**只导出 `Popover`/`PopoverContent`/`PopoverTrigger` 三个**（plan-checker C1 属实），⛔ 别从那里导入、⛔ 别给它加导出（那是第 6 处既有文件修改）。容器/内容仍用 `~/components/ui/popover` 的 `Popover`/`PopoverContent`。<br>⚠️ **补充核实**：`@floating-ui/dom` 与 `@floating-ui/vue` **在基线就已是 `web/package.json` 的直接依赖**（`git show 02ab1684:web/package.json` :33-34），并非本 plan 引入——计划「不引入它的首个调用点」的措辞需按此校正。当前 `web/src/` 对它**零引用**，纪律照旧：⛔ 不写 `useFloating`、⛔ 不手搓定位。<br>⭐ **115-02 自身零 `PopoverAnchor` 用量**（本 plan 不建 popover，该组件归 115-05）。 |
| 5 | **P-5：SC-4 范围收窄** | `associations` 段本相位**只做**「本蓝图引用了」+「关联项目」；**「引用了本蓝图 / 关联知识」顺延 Phase 116** 的知识图谱物化。理由：`knowledgeApi.getRelated` / `getArtifactAssociations` 查的是 `initiatives.Artifact` 投影的 KnowledgeEntity（`artifact_associations.py:75`），而蓝图在 `delivery.Artifact` ⇒ 拿蓝图 id 去调**必然 404/空**。⭐ **已同步写入 STATE.md 的 Pending Todos。** |
| 6 | **P-14：`iterBlocks` 排除四段** | `must_haves` / `decision_log` / `deferred_ideas` / `execution_plan` **不走查**（后端 `iter_blocks` 对它们零 `collect` ⇒ 后端不会往那里挂线程）。类型上它们是零约束裸 array ⇒ `unknown[]`。 |

---

## 14. 给下游四个 plan（115-03/04/05/06）的五条注意

1. **契约照本 SUMMARY 的 §4–§7 逐字消费，⛔ 不要回头看 UI-SPEC 的对应段落**——§3.3（两处）、§8.3、§10.1、§3.6、§7.4 都已被订正，UI-SPEC 原文在这些点上是过时的。
2. **`refetchInterval` 一个字都不许出现在组件/页面里**（源码守卫断言 6 会红）。要实时数据就消费 `useBlueprintLive()` 的返回值。
3. **404 分支只有一个 i18n 键** `knowledge.blueprints.error.notFoundOrForbidden`；判据用 `err instanceof ApiError && err.status === 404`（仓内先例 `pages/knowledge/entities/[id].vue:93`）。
4. **`zh-CN.json` / `main.css` / `api/index.ts` 已经写全，⛔ 别再改**。缺 key 或缺 safelist 时先回本 SUMMARY §8 核对——大概率是「字面量类名不需要 safelist」或「兜底键在 `statusUnknown` 而非 `status.unknown`」这两类误判。
5. **跑完前端门检查 `git status`**：pnpm 10 会漂移 `web/pnpm-workspace.yaml`（§12 第 7 条），提交前还原它。

---

## Self-Check: PASSED

**创建的文件（18 个）全部存在**——`types/blueprint.ts` / `api/blueprints.ts` / `api/repositoryChunks.ts` / `config/blueprintStatus.ts` / `config/__tests__/blueprintStatus.spec.ts` / `components/blueprint/BlueprintStatusBadge.vue` / `components/blueprint/annotationTokens.ts` / `utils/blueprintBlocks.ts` / `utils/blueprintAnnotations.ts` / `utils/__tests__/blueprintBlocks.test.ts` / `utils/__tests__/blueprintAnnotations.test.ts` / `utils/__tests__/domCapabilities.test.ts` / `stores/useBlueprintViewerStore.ts` / `composables/useBlueprintLive.ts` / `composables/useBlueprintAnnotations.ts` / `composables/useCitationPreview.ts` / `composables/__tests__/useBlueprintLive.spec.ts` / `__tests__/blueprint-source-guard.spec.ts`，逐个 `[ -f ]` 命中。

**三个 commit 全部在 `git log`**：`3055e623` / `6e345dd3` / `02563897`。

**门禁实跑**：vitest **1464 passed / 1 skipped（既有）**、type-check **exit 0**、lint **本 plan 文件零新增问题**（仓库 111 个既有问题详见 §1）。

**变异验证实跑**：注释 `watch(isLive)` → `useBlueprintLive.spec.ts` **转红**（`expected 1 to be 2`）；恢复 → **3 passed**，源文件逐字节还原。

**工作树干净**：`git status --short` 空输出（pnpm 漂移已还原）。
