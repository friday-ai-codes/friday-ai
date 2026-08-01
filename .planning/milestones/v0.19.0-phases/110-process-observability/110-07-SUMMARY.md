---
phase: 110-process-observability
plan: 07
subsystem: ui
tags: [vue, chat, orchestration, session-binding, dedup, plan-research-logs, vitest, no-stub]

# Dependency graph
requires:
  - phase: 110-03
    provides: "每条 `PlanResearchSession` 上的 `plan_session_id`（= `str(ConvergenceSession.id)`）—— 跨消息过滤的绑定键"
  - phase: 110-04
    provides: "store 的 `orchestrationSessions` 分桶 / `activeOrchestrationSessionId` / `planResearchSessions`（会话级扁平数组，快照整体替换）"
  - phase: 110-06
    provides: "`OrchestrationStageTimeline.vue`（prop `sessionId`，内部自带「桶存在 + 至少一条已知事实」两道门）"
provides:
  - "`PlanResearchLogGroup.vue`：按仓一张卡纵向堆叠的调研容器日志组（复用 `DeepAnalysisCard`，该组件零改动）"
  - "`ChatMessageBubble` 的编排在途挂载点：时间线与日志组插在 `tool-pill` 之后、`OrchestratedPlanCard` 之前"
  - "`resolveOrchestrationSessionId` / `orchestrationSessionIdFor`：result 优先、store 兜底的会话绑定"
  - "`lastOrchestrationToolItemId`：同一消息多条编排 tool call 时的单次渲染判定"
  - "`planResearchSessionsFor`：按 `plan_session_id` 的**跨消息**会话过滤（F-21 的落点）"
  - "29 条新用例（组件 16 + 气泡集成 13），全部在真实组件树上断言"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "「不对等的重复保护」必须被单独识别：按 session 分桶的状态换 id 即换桶、天然自限；被快照整体替换的扁平数组没有这层自限，消费方必须自己补会话维度过滤"
    - "跨消息缺陷的用例必须构造**两个** wrapper 并同时断言「该在的在 / 不该在的不在」—— 只断言前者时「完全不过滤」的实现同样为真"
    - "去重渲染位置（`lastOrchestrationToolItemId`）与取数（per-`item.result`）是两件事，合并即重开 109 修好的缺口；用「末条在途、前条终态」的用例把这条边界钉死"
    - "源码级断言读文件时用 `resolve(__dirname, …)`，不用 `fileURLToPath(import.meta.url)`（vitest 环境下 `import.meta.url` 非 file scheme）"

key-files:
  created:
    - web/src/components/chat/PlanResearchLogGroup.vue
    - web/src/components/chat/__tests__/PlanResearchLogGroup.spec.ts
  modified:
    - web/src/components/chat/ChatMessageBubble.vue
    - web/src/components/chat/__tests__/chatMessageBubble.parts.spec.ts
    - web/src/components.d.ts

key-decisions:
  - "会话绑定顺序按 plan 的 A 节实现（result 优先、store 兜底），与 UI-SPEC §A.7 表面上的「store 第一」相反；理由是跨轮编排——store 的活跃 id 已指向新会话，只有 result 能把第一条气泡钉回它自己那次编排。负向对照 4 证明这个顺序是承重的"
  - "`OrchestrationStageTimeline` / `PlanResearchLogGroup` 走**显式 import**，跟随本文件既有惯例（同目录 6 个业务组件全是显式 import），不吃 `components.d.ts` 的自动导入"
  - "109 回归锁不重复造：既有「两条编排工具 ⇒ 卡片挂在终态那条」的用例已是那把锁（负向对照 3 证实它会红）；本 plan 新增的是它的**互补面**——「末条在途 ⇒ 卡片仍挂在前面那条终态上」，锁的是「不要把 `lastOrchestrationToolItemId` 接进卡片条件」"
  - "日志组的 `key` 用 `session_id || repository_id-index`：`session_id` 在极早期快照里可能为空串，纯用它会让 v-for 的 key 撞车"

requirements-completed: [OBS-01, OBS-02, OBS-03]

# Metrics
duration: 16min
completed: 2026-07-31
---

# Phase 110 Plan 07: 编排气泡挂载与调研日志组 Summary

**把 110-06 的阶段时间线与新建的按仓日志组接到编排工具气泡上（121 行组件 + 112 行气泡改动），并补上 plan-checker 点名的那个零覆盖缺陷——`planResearchSessions` 是会话级扁平数组、被快照整体替换，没有 `plan_session_id` 过滤时第二轮编排的日志会挂到第一条编排消息上；8 条负向对照逐条破坏后全部命中 plan 点名的那条测试，其中会话过滤那条精确红在「S1 气泡里不存在」这一侧。**

## Performance

- **Duration:** 16 min（07:10Z → 07:26Z）
- **Tasks:** 3/3
- **Files created:** 2 · **modified:** 3（含 1 个生成物）
- **新增用例:** 29 条（组件 16 + 气泡集成 13）

## Accomplishments

- **F-21 的缺陷是被真的证明存在的，不是被顺手实现掉的。** 负向对照 2（把日志组换回未过滤的 `chatStore.planResearchSessions`）红 2 条，其中主证据那条的失败信息是 `expected [ DOMWrapper{…} ] to have a length of +0 but got 1`——**正是 S1 气泡「不存在」那一侧**。这确认了 plan 的警告：只断言 S2 气泡里存在的话，「完全不过滤」的实现同样为真，这条用例会静默通过。
- **`v-if` 与 `:sessions` 是同一个表达式。** 模板里两处都是 `planResearchSessionsFor(item)`；`rg -c ':sessions="chatStore.planResearchSessions"'` = **0**。plan 点名的「渲染了一个空组」形态在源码层面不可能出现。
- **单次渲染与 109 载重不变量被拆成两条互不替代的锁。** 负向对照 1（去掉 `item.id === lastOrchestrationToolItemId`）红 2 条：点名的单次渲染用例（`findAll().length` 从 1 变 2）+ 新增的 per-item 互补锁。负向对照 3（把取数改回 `toolCalls.find`）红的是**另外**两条：既有的 109 锁 + 同一条互补锁。两个破坏红的集合只交在互补锁上，说明「去重位置」与「取数方式」确实是被分别守住的。
- **会话绑定顺序是承重的，而且它的失守后果与 F-21 同型。** 负向对照 4（store 优先于 result）红 2 条：点名的「result 的 S1 优先」+ **F-21 那条**。后者不是失真——把顺序反过来后，第一条气泡会绑到 store 的活跃会话 S2，于是照样渲染出第二轮的日志组，用户看到的坏结果与「完全不过滤」逐字相同。
- **仓库名兜底的「不含 UUID」断言比「等于未知仓库」更强。** 负向对照 6（兜底改成回显 `repository_id`）精确红 1 条。这条用例同时断言 `.da-title` 文本等于 `未知仓库` **和** 整棵 DOM（`html()` + `text()` 两侧）不含那串 UUID——只有后半条挡得住「回显 UUID 前 8 位 + …」这类看起来更礼貌的坏兜底。
- **没有 stub 被测对象。** `PlanResearchLogGroup.spec.ts` 里零 `stubs`，组件树挂到真实的 `DeepAnalysisCard` 为止——所以「仓库名有没有真的进到卡片标题」「多仓是不是真的只有首张展开」是从真实卡片的 `.da-title` / `.da-logs` 上读出来的。气泡集成用例同样不 stub 两个新组件，会话绑定靠 `findComponent(OrchestrationStageTimeline).props('sessionId')` 断言。
- **`DeepAnalysisCard` / `DeepAnalysisGroup` / `SubStepTimeline` 一个字都没改。** 四个 commit 的 `git diff --name-only` 只含 5 个文件，三者都不在其中。
- **零新增依赖、零新增设计 token。** `git diff --exit-code web/pnpm-lock.yaml` 退出 0；组件里的每个 class（`mt-2` / `space-y-2` / `text-[11px]` / `font-semibold` / `text-primary` / `icon-[lucide--search-code]`）都能在 UI-SPEC §C.1 的 DOM 图或既有组件里找到出处。

## Task Commits

1. **Task 1: `PlanResearchLogGroup.vue` + 16 条用例** — `a938e41a` (feat)
2. **`components.d.ts` 生成物同步** — `b10e723c` (chore)
3. **Task 2: `ChatMessageBubble` 挂载 + 会话绑定 + 单次渲染 + 会话过滤** — `e79e5fc1` (feat)
4. **Task 3: 气泡集成用例 13 条** — `99531651` (test)

## Files Created/Modified

- `web/src/components/chat/PlanResearchLogGroup.vue` — **新建，121 行**。`props: { sessions, repoNames? }`；`COPY` 四串；`repoLabel()` 三级回退；`cardStatus()` 大小写不敏感映射；`cards` computed 做浅适配（`{ session_id, status, logs }` + `taskLabel` + `defaultExpanded: index === 0`）；`collapsed` 本地 ref。
- `web/src/components/chat/__tests__/PlanResearchLogGroup.spec.ts` — **新建，174 行 / 16 条**：卡片与标题 3、展开策略 2、空态与兜底 3、组标题与图标 1、折叠 1、状态映射 5（`it.each`）、源码走查 1。
- `web/src/components/chat/ChatMessageBubble.vue` — **+112 / −1**。新增 `resolveOrchestrationSessionId` / `orchestrationSessionIdFor` / `lastOrchestrationToolItemId` / `planResearchSessionsFor` 四个符号 + 两个组件的显式 import + 模板里两块新 UI。
- `web/src/components/chat/__tests__/chatMessageBubble.parts.spec.ts` — **+267 / −1**，新增 describe 一组 13 条。
- `web/src/components.d.ts` — unplugin 生成物，随新组件更新。

## Decisions Made

- **会话绑定顺序取 plan 的 A 节（result 优先），而不是 UI-SPEC §A.7 表面上的「store 第一」。** §A.7 把 store 列为第 1 项、tool result 列为第 3 项，但同一段的末句写着「与 1/2 不一致时**以 tool result 为准**（它明确属于这个气泡）」——两者其实是同一条规则的两种写法，plan 的 A 节把它写成了可执行的表达式。落地取 plan 的形态，理由在注释里点名了跨轮编排这个具体场景。负向对照 4 证明这个顺序不是装饰。
- **两个新组件走显式 `import`，不吃自动导入。** plan 给了「若走自动导入则跟随自动导入」的口子，但本文件同目录的 6 个业务组件（`DeepAnalysisGroup` / `OrchestratedPlanCard` / `TechPlanCard` / `ToolProcessGroup` / `DocSummaryCard` / `StructuredJsonView`）全是显式 import，跟随文件既有惯例更一致；也与 110-06 「显式 import `COPY`，不吃碰巧同名」是同一条纪律。
- **不新造一条 109 回归锁，而是补它的互补面。** 既有用例「异步路径：同一消息两条同名编排工具时，卡片挂在带 `artifact_version_id` 的那条上」（`:500`）就是 F-17 点名的那把锁，负向对照 3 证实它会红。新增的那条锁的是**另一个**失守方向：构造「前条终态 + 末条在途」，断言卡片仍挂在前条上——这条只有在有人把 `lastOrchestrationToolItemId` 顺手接进卡片渲染条件时才会红，而那正是 plan Task 2 的 🔴 边界。两条用例针对两种不同的坏实现，不是重复。
- **日志组的 `v-for` key 是 `session_id || \`${repository_id}-${index}\``。** 极早期快照里 `session_id` 可能是空串（容器刚建、id 未回填），纯用它会让多仓的 key 全撞成 `''`，Vue 复用节点后展开态会串到错误的卡上。

## 可观测性自检（`.cursor/rules/observability-logging.mdc`）

| 检查项 | 结论 |
|---|---|
| 结构化事件 + kv / `category` / `component` | 不适用：前端展示组件与模板挂载，无 `structlog` 面。**两处新增代码零日志**——编排在途每 2s 一份快照、SSE 每秒数条，打日志即刷屏 |
| 高频循环禁 INFO | ✅ 两个新增面 `console.*` **零处**；气泡集成用例统一 spy `console.warn` / `console.error`，「老会话两块都不渲染」与「两级来源都取不到会话」两条各自断言零调用 |
| 脱敏不可绕过 | ✅ 三道：① 容器日志由服务端 `redact_secrets_in_text` 脱敏（110-03）；② 前端**零新增解码路径**，复用既有 `decorateDeepLog`；③ 新增面全部 `{{ }}` 插值，`rg 'v-html'` 在两个文件里均为 **0** |
| 触发用户绑定 | 不适用（前端渲染，无请求、无落库） |
| 观测不反噬业务 | ✅ `resolveOrchestrationSessionId` 解析失败返回空串不抛；`planResearchSessionsFor` 对非数组回退 `[]`、对 `null` 元素用可选链；时间线组件内部还有一层 `try/catch`（110-06）。「老会话」「result 非 JSON」「logs 缺失」三条路径各有用例 |
| 新增请求入口 / LLM 调用 / 召回 / 队列 / webhook | 无（只读 store，零网络面） |

## Deviations from Plan

### 1. [Rule 3 - Blocking] `fileURLToPath(import.meta.url)` 在 vitest 环境下抛 `TypeError`

- **Found during:** Task 1 首轮跑测
- **Issue:** 源码级断言（零 `v-html`）用 `readFileSync(fileURLToPath(new URL('../PlanResearchLogGroup.vue', import.meta.url)))` 读文件，用例红：`TypeError: The URL must be of scheme file`——该环境下 `import.meta.url` 不是 file scheme。
- **Fix:** 改为 `readFileSync(resolve(__dirname, '../PlanResearchLogGroup.vue'), 'utf-8')`，与同目录 `OrchestrationStageTimeline.spec.ts:453` 的既有写法一致。断言内容未作任何放宽。
- **Files modified:** `web/src/components/chat/__tests__/PlanResearchLogGroup.spec.ts`
- **Commit:** `a938e41a`

### 2. [Rule 3 - Blocking] 提交 `web/src/components.d.ts` 生成物

- **Found during:** Task 1 收尾走查
- **Issue:** 新增 `.vue` 后 unplugin-vue-components 在跑 vitest 时重新生成了这份**已入库**的声明文件，留下游离 diff（与 110-04 Deviation 2 / 110-05 Deviation 2 / 110-06 Deviation 2 同因）。
- **Fix:** 单独一个 chore commit。
- **Files modified:** `web/src/components.d.ts`
- **Commit:** `b10e723c`

### 3. [Rule 3 - Blocking] 既有 spec 未导入 `afterEach`

- **Found during:** Task 3 首轮跑测
- **Issue:** `chatMessageBubble.parts.spec.ts` 原本没有 `afterEach`，新增的 describe 用它做 `vi.restoreAllMocks()`，整个 suite 直接 `ReferenceError: afterEach is not defined`（0 test 收集到）。
- **Fix:** 在既有 vitest import 里补 `afterEach`。既有 34 条用例零影响。
- **Files modified:** `web/src/components/chat/__tests__/chatMessageBubble.parts.spec.ts`
- **Commit:** `99531651`

### 4. [解释，非改动] 「`groupedDisplayItems` 逐字未改」的口径

- Task 2 验收条款写的是「`UNGROUPABLE_TOOLS` / `isProcessTool` / `groupedDisplayItems` 三处**逐字未改**（`git diff` 中不含它们所在的行）」。
- 实际 `git diff` 里有一处 `+` 行含 `groupedDisplayItems`：新增的 `lastOrchestrationToolItemId` computed **读**了 `groupedDisplayItems.value`。
- **口径澄清：三处的定义与实现无任何 `-` 行**，`git diff -- ChatMessageBubble.vue | rg '^-.*(UNGROUPABLE_TOOLS|isProcessTool|groupedDisplayItems)'` 零命中。条款意图是「不动分组算法」，读取它不构成改动——新 computed 不可能不读渲染用的 items 列表。

### 5. [解释，非改动] 负向对照 8 的粒度与 plan 表格不同（见下节）

---

**Total deviations:** 3 auto-fixed（1 处测试 API 在该环境不可用、1 处生成物、1 处既有 spec 的 import 缺口）+ 2 处口径说明
**Impact on plan:** 均在 plan 边界内，无范围蔓延。

## Verification

### 测试（全部带 `CI=true`，按 `Tests N passed` 行判定，**不看退出码**）

| 命令 | 改动前 | 改动后 |
|---|---|---|
| `src/components/chat/__tests__/PlanResearchLogGroup.spec.ts` | — | **16 passed / 1 file** |
| `src/components/chat/__tests__/chatMessageBubble.parts.spec.ts` | 34 passed | **47 passed**（+13） |
| `src/components/chat` | **305 passed / 26 files**（实测） | **334 passed / 27 files**（+29，零回归） |
| `src/components/chat src/components/execution src/composables src/stores` | **656 passed / 58 files**（实测） | **685 passed / 59 files**（+29，零回归） |

🔴 **基线口径**：plan `<verification>` 写的「基线 504 passed / 54 files」在本 worktree 的 `HEAD` 上不成立（110-04 / 110-05 / 110-06 已连续三次更正过同一处）。本次改动前后各实测一遍，四路径集 **656 / 58**、`src/components/chat` **305 / 26**，与编排任务给出的实测值逐字一致。

### 类型 / Lint / 依赖

| 项 | 结果 |
|---|---|
| `pnpm vue-tsc --noEmit -p tsconfig.json` | 退出码 **0**（Task 1 / Task 2 / Task 3 / 8 条负向对照还原后各跑一次） |
| `pnpm eslint`（4 个改动文件） | 退出码 **0**（首轮红过一次 `perfectionist/sort-imports`，`node:fs` 需排在 `@vue/test-utils` 之前，已修） |
| `git diff --exit-code web/pnpm-lock.yaml` | 退出码 **0**，零新增依赖（T-110-07-SC 缓解成立） |

### 源码走查（两个 Task 的验收条款逐条）

| 条款 | 核验方式 | 结论 |
|---|---|---|
| 组件内不出现 `DeepAnalysisGroup` | `rg -n` 命中 3 处**全在头部注释**（说明「为什么不用它」），代码区零命中；spec 有源码级断言（剥离注释行后不含该串） | ✅ |
| `DeepAnalysisGroup.vue` / `DeepAnalysisCard.vue` 本次未被修改 | `git diff --name-only HEAD~4 HEAD` 共 5 个文件，两者均不在其中 | ✅ |
| 仓库名三级回退且末级是常量 | `repoLabel()` 实读 + 「DOM 不含 UUID」用例 + 负向对照 6 | ✅ |
| `defaultExpanded` 基于索引是否为 0 | 源码 `index === 0`；负向对照 7 精确红 1 条 | ✅ |
| 组件内不出现 `localStorage` / `v-html` | `rg -n`：`localStorage` 1 处在注释、`v-html` **0** 处；spec 源码级断言（剥离注释）均为零命中 | ✅ |
| spec 中没有 stub `DeepAnalysisCard` 的语句 | `rg -c 'stubs\|vi.mock' PlanResearchLogGroup.spec.ts` = **0** | ✅ |
| spec 含「DOM 文本不含 UUID」与「组标题不含深度分析」断言 | 两条各自独立成 `expect`；前者同时打在 `html()` 与 `text()` | ✅ |
| 产物 ≥ 60 行 | `wc -l` | ✅ **121** |
| `resolveOrchestratedPlanData(item.result)` 调用形态未改动 | `git diff` 中该行无 `-`；`rg 'toolCalls.value.find(tc => isOrchestrationTool'` = **0** | ✅ |
| `lastOrchestrationToolItemId` 只被两块新 UI 的 `v-if` 使用 | `rg -n` 命中 3 处：定义 `:882`、时间线 `v-if` `:1354`、日志组 `v-if` `:1364`；`OrchestratedPlanCard` 的条件（`:1374`）不含它 | ✅ |
| `planResearchSessionsFor` 字面按 `plan_session_id === orchestrationSessionIdFor(item)` 过滤 | 实读；`v-if` 与 `:sessions` 同为 `planResearchSessionsFor(item)`；`rg ':sessions="chatStore.planResearchSessions"'` = **0** | ✅ |
| 两块新 UI 的模板行号早于 `OrchestratedPlanCard` | 时间线 `:1353` < 日志组 `:1363` < 卡片 `:1373` | ✅ |
| `UNGROUPABLE_TOOLS` / `isProcessTool` / `groupedDisplayItems` 未改 | `git diff` 中三者所在行零 `-`（读取算作新增，见 Deviation 4） | ✅ |
| 文件中不出现 `RoutingDecisionPanel` | `rg -c` = **0** | ✅ |

## 负向对照（8 条全部执行 → 确认变红 → 还原）

| # | 破坏方式 | plan 点名必红的测试 | 实际变红 | 结果 |
|---|---|---|---|---|
| 1 | 去掉 `item.id === lastOrchestrationToolItemId` | 单次渲染用例（`findAll().length` 变 2） | **该条** + per-item 互补锁 | ✅ 2 failed / 45 passed |
| 2 | 日志组换回未过滤的 `chatStore.planResearchSessions` | 「两条编排消息 ⇒ 日志组只挂在当前那条上」的 **S1 侧**断言 | **该条**（失败信息 `to have a length of +0 but got 1`，正是 S1 侧）+「过滤后为空 ⇒ 整组不渲染」 | ✅ 2 failed / 45 passed |
| 3 | 取数改回 `toolCalls.find(...)` | 109 回归锁（卡片拿到 `__blocking_task__` 那条） | **既有 109 锁**（`:500`）+ per-item 互补锁 | ✅ 2 failed / 45 passed |
| 4 | 会话绑定顺序反过来（store 优先） | 「result 的 S1 优先」用例 | **该条** + F-21 那条 | ✅ 2 failed / 45 passed |
| 5 | 日志组挂到 `OrchestratedPlanCard` 之后 | DOM 顺序断言 | **该条** | ✅ **1 failed / 46 passed** |
| 6 | 仓库名兜底改成回显 `repository_id` | 「DOM 不含 UUID」断言 | **该条** | ✅ **1 failed / 15 passed** |
| 7 | 多仓展开策略改成全部展开 | 「多仓仅首张展开」用例 | **该条** | ✅ **1 failed / 15 passed** |
| 8a | 在编排气泡内挂上 `RoutingDecisionPanel` | `partsApiIntegration.spec.ts` 既有的面板不渲染锁 | **仅**本 plan 新增的「107 边界」用例；既有锁**未红** | ⚠️ 1 failed / 52 passed（见粒度说明） |
| 8b | 无条件挂载 `RoutingDecisionPanel`（追加对照） | 同上 | **既有锁** + 新增的「107 边界」用例 | ✅ 2 failed / 51 passed |

**粒度说明**：

- **对照 8 与 plan 表格的预期不一致，这是真实结论不是执行偏差。** `partsApiIntegration.spec.ts:178` 那条锁走的是「普通消息 + `routing_trace_id` + store 有 trace」的场景，它守的是**通用挂载路径**；把面板挂在 `isOrchestrationTool(item.name)` 这个分支上时，那个 fixture 根本走不到，锁不会红。红的是本 plan 新增的「107 边界」用例。为了确认既有锁本身仍然承重（而不是已经腐化成恒真），追加执行了 8b（无条件挂载），既有锁如期变红。⇒ **两条锁互为补充**（这正是 plan Task 3 对这条用例的原话），单靠既有锁挡不住「顺手挂在编排气泡里」这个具体动作。
- **对照 2 的第二条是同族收紧**：「过滤后为空 ⇒ 整组不渲染」用的是 `plan_session_id === 'S-other'` 的容器，去掉过滤后它同样会上屏。两条一起红说明这个破坏的后果是「任何气泡都渲染任何轮次的日志」，比 F-21 描述的还宽。
- **对照 4 的第二条不是失真**：store 优先意味着第一条气泡绑到活跃会话 S2，于是渲染出第二轮的日志组——与「完全不过滤」的用户可见后果逐字相同。这条同时说明**绑定顺序与会话过滤是同一个缺陷的两个入口**，两者都必须正确。
- **对照 1 与对照 3 红的集合只交在 per-item 互补锁上**：前者另红单次渲染用例、后者另红既有 109 锁。这证明「去重渲染位置」与「取数方式」被两组不同的用例分别守住，没有混成一条。

还原方式一律为 `git checkout -- <单个文件>`（逐文件，**未使用任何 blanket reset / clean / stash**）。8 条全部还原后复跑：`src/components/chat` **334 passed / 27 files**、四路径集 **685 passed / 59 files**、`vue-tsc` 退出码 0、`git status` 对已提交版本干净。

## must_haves 逐条核对

| # | truth | 证据 |
|---|---|---|
| 1 | 调研日志按仓一张卡纵向堆叠，复用 `DeepAnalysisCard`（零改动） | `v-for` 内嵌 `DeepAnalysisCard`，外层 `div.space-y-2`（纵向）；「两个仓两张卡」用例；`git diff --name-only` 不含 `DeepAnalysisCard.vue` |
| 2 | 卡片标题三级回退，任何情况下不回显裸 UUID | `repoLabel()` 三级；三条用例（自带名 / `repoNames` 兜底 / 常量兜底 + `html()` 与 `text()` 两侧不含 UUID）；负向对照 6 |
| 3 | 组标题「方案调研 · {n} 个仓库」+ `icon-[lucide--search-code]`，与深度分析在图标 / 标题 / 排布三处不同 | 用例同时断言含「方案调研 · 2 个仓库」、**不含**「深度分析」、含 `search-code`、**不含** `layers`；排布差异由 `space-y-2` 与「不用 swiper」共同成立 |
| 4 | 单仓默认展开、多仓仅第一张展开；空数组整组不渲染 | 「单仓 `.da-logs` 恰 1」+「三仓 `.da-card` 3 张但 `.da-logs` 恰 1、后两仓日志文本不可见」+「空数组 `text()` 为空串」；负向对照 7 |
| 5 | 日志组不消失，整组可折叠 | 组件对 `status` 无渲染门（终态照常渲染）；折叠用例断言卡片消失但 `[data-test=plan-research-log-group]` 与 toggle **仍在**；`aria-expanded` / `aria-label` 两态断言 |
| 6 | 时间线与日志组挂在编排气泡内、`OrchestratedPlanCard` 之前；不动分组算法 | 模板行号 1353 / 1363 < 1373；DOM 顺序用例（`html().indexOf` 比较）；负向对照 5；三处禁改零 `-` 行 |
| 7 | 同一条消息多条编排 tool call ⇒ 只渲染一次（挂在末条） | `findAll(TIMELINE).length === 1` + `.tool-inline[0]` 无 / `[1]` 有；负向对照 1 |
| 8 | 🔴 跨消息不出现两遍：按 `plan_session_id` 过滤到本气泡绑定的会话 | `planResearchSessionsFor` 实现 + 两 wrapper 用例（S2 存在 **且** S1 不存在，且 S1 气泡 `text()` 不含「方案调研」与第二轮仓名）；负向对照 2 精确红在 S1 侧 |
| 9 | 会话绑定顺序：result 优先，取不到才回退 store | 三条用例（S1 优先 / 回退 S2 / 两级都无则不渲染不抛）；负向对照 4 |
| 10 | **backstop** — `OrchestratedPlanCard` 取数继续 per-`item.result`，绝不回退 `toolCalls.find` | 该行零 `-`；`rg` 零命中 `.find` 形态；既有 109 锁 + 新增互补锁；负向对照 3 红两条 |
| 11 | **backstop** — 历史消息 / 无编排会话 / 老后端三情形均不渲染，其余逐像素一致，不抛不 warn | 「老会话两块都不渲染且零 console 输出」（同时断言 pill 与产出卡片照常）+「两级来源都取不到」+「非编排工具」三条；`src/components/chat` 既有 305 条零回归 |
| 12 | **backstop** — 不挂 `RoutingDecisionPanel`、不渲染降级横幅与原因句，既有锁保持绿 | `rg -c 'RoutingDecisionPanel'` = 0；「107 边界」用例断言无 `routing-panel`、不含「未经 LLM 推理」/「置信度」；`partsApiIntegration.spec.ts` 全绿；负向对照 8a/8b |
| 13 | **backstop** — 不使用 / 不改 `DeepAnalysisGroup` | 代码区零命中（3 处均在解释「为什么不用」的注释里）+ spec 源码级断言；该文件未被本 plan 改动 |
| 14 | **backstop** — 新增面零 `v-html`，日志经既有 `decorateDeepLog` 解码，不新增解码路径 | 两个文件 `rg 'v-html'` = 0 + 源码级用例；日志渲染完全走 `DeepAnalysisCard`（它内部调 `decorateDeepLog`），本 plan 未新增任何解码函数 |

## Threat Flags

无。本 plan 是纯前端渲染与挂载，未引入网络端点 / 鉴权路径 / 文件访问模式 / 信任边界上的 schema 变更。`threat_model` 6 条 disposition 全部落地：

| Threat ID | 落地形态 |
|---|---|
| T-110-07-01（容器日志上屏） | 服务端 `redact_secrets_in_text`（110-03）为第一道；前端**零新增解码路径**，日志渲染完全交给 `DeepAnalysisCard` 的既有 `decorateDeepLog` |
| T-110-07-02（裸 UUID 回显） | 三级回退末级为常量；「DOM 不含 UUID」断言打在 `html()` 与 `text()` 两侧；负向对照 6 |
| T-110-07-03（会话绑定错投） | 绑定顺序以「属于这个气泡的 result」优先 + 日志组按 `plan_session_id` 过滤；三条绑定用例 + F-21 用例；负向对照 2 / 4 |
| T-110-07-04（新增文案渲染被篡改） | 全部 `{{ }}` 插值；两个新增面各有 `rg 'v-html'` = 0，组件侧另有源码级用例（剥离注释行） |
| T-110-07-05（新块打掉消息气泡） | 两块 `v-if` 条件严格；解析失败返回空串 / 空数组不抛；时间线内部还有 `try/catch`（110-06）；「老会话零 console 输出」用例 |
| T-110-07-SC（供应链） | 零新增依赖，未跑 `shadcn init` / `add`，`git diff --exit-code web/pnpm-lock.yaml` 退出码 0 |

## Known Stubs

无。两块新 UI 的每一处渲染都接在真实数据源上（store 桶 / `planResearchSessions` → 真实组件 → 真实 `DeepAnalysisCard` / `SubStepTimeline`）。

## Issues Encountered

- **首轮 suite 直接 0 test**（Deviation 3）：既有 spec 没导入 `afterEach`，新增 describe 用了它。值得记一笔的是失败形态是**整个文件收集不到用例**而不是某条红——若当时只看退出码或只扫「× 行」，会误以为一切正常。
- **`import.meta.url` 在该测试环境不是 file scheme**（Deviation 1）：同目录 `OrchestrationStageTimeline.spec.ts` 早就用了 `resolve(__dirname, …)`，抄近路写成 URL 形态就红了。
- **负向对照 8 打脸了 plan 的预期**（见粒度说明）：plan 表格预测既有的 `partsApiIntegration.spec.ts` 锁会红，实测不会——因为那条锁守的是通用挂载路径，而「顺手挂在编排气泡里」走的是另一条分支。这条如果不跑对照就发现不了，而它恰好说明本 plan 新增的「107 边界」用例不是冗余。

## 里程碑级缺口（`<assumptions>` #1，必须如实记录）

🔴 **`RoutingDecisionPanel` 今天在 SPA 里没有挂载点**：`web/src/**/*.vue` 里零个使用点，且 `partsApiIntegration.spec.ts:178` 有一条锁「该面板不渲染」的用例。本 plan 按边界**不挂它、不改它、未让那条锁变红**。

后果：落地后编排链上「路由」步行尾那个 `降级` 角标事实上是**唯一**的降级信号；ROUTE-01/02 与 RELY-03 的用户可见半边当前不可达。这是**里程碑级缺口**，不影响 Phase 110 的四条 SC，但影响 RELY-03 在用户侧是否真的成立——已单独向用户上报，不并入本 phase 范围。

## User Setup Required

None - 纯前端改动，无外部服务配置。

## Next Phase Readiness

- **Phase 110 的七个 plan 全部完成。** 两块 UI 已接到用户能看见的位置上，OBS-01 / OBS-02 / OBS-03 的前端半边闭合。
- **未验证面（UAT 必查）**：本 plan 与 110-02～110-06 全程为单测，**未跑过一次真实编排**。plan `<verification>` 的 `<human-check>` 六条逐条待验，其中三处最可能暴露问题：
  1. **在途期间的会话绑定**。前五个阶段没有 tool result，绑定完全靠 store 的 `activeOrchestrationSessionId`——它由 `process_event` 到达时写入。若 SSE 在挂起之前就断开，时间线会整段不出现（不报错，就是没有）。
  2. **日志组的出现时机**。它依赖 2s 轮询把 `plan_research_sessions` 带回来，比时间线的「并行调研」步进入 `active` 晚一到两拍。这是既定的传输分工，不是缺陷，但观感上会有短暂的「有进度、没日志」。
  3. **`plan_session_id` 与 `orchestrationSessionIdFor` 的跨进程同值**。110-03 给的是 `str(ConvergenceSession.id)`，tool result 里的 `session_id` 也应是同一个值——两侧各有后端用例，但**跨进程的端到端一致性尚未实测**。若 UAT 看到「时间线在跑、日志组永不出现」，第一嫌疑就是这两个串不等。
- **`DeepAnalysisGroup` 的 `title` prop**（UI-SPEC Unresolved #4）仍未做，按 plan 裁定留作后续：若要 swiper 形态，正确做法是给它加一个默认值为今日文案的 `title` prop，而不是在 chat 侧将就。

## Self-Check: PASSED

- `web/src/components/chat/PlanResearchLogGroup.vue`（121 行，含 `plan-research-log-group`，满足 `min_lines: 60`）与 `web/src/components/chat/__tests__/PlanResearchLogGroup.spec.ts`（174 行）均存在于磁盘；`ChatMessageBubble.vue` 含 `planResearchSessionsFor`（3 处）。两个 `contains` 断言字面量全部命中。
- 四个 commit（`a938e41a` / `b10e723c` / `e79e5fc1` / `99531651`）均可在 `git log` 中检索到。
- `key_links` 三条均成立：`ChatMessageBubble` → `OrchestrationStageTimeline`（import + 模板调用，位置在 `OrchestratedPlanCard` 之前）；`ChatMessageBubble` → `PlanResearchLogGroup`（`plan_session_id` 在文件中 3 处命中，`v-if` 与 `:sessions` 同表达式）；`PlanResearchLogGroup` → `DeepAnalysisCard`（import + `v-for` 调用点，`taskLabel` 传仓库名）。`vue-tsc` 退出码 0 提供类型层证据。

---
*Phase: 110-process-observability*
*Completed: 2026-07-31*
