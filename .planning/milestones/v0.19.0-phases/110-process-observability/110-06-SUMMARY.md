---
phase: 110-process-observability
plan: 06
subsystem: ui
tags: [vue, chat, timeline, a11y, live-region, collapse, vitest, no-stub]

# Dependency graph
requires:
  - phase: 110-02
    provides: "泛化后的 `SubStepTimeline`（`interactive` 开关 / 可选 `summary` / `badge` / 六态 / 失败行 `role=\"alert\"` 且不带实时播报属性）"
  - phase: 110-04
    provides: "store 桶 `orchestrationSessions[sessionId] = { sessionId, snapshot, events, eventsTruncated }` 与 `orchestrationRuntimeActive`"
  - phase: 110-05
    provides: "`buildOrchestrationTimeline` 与 `COPY` —— 组件侧不做任何状态判定，只负责渲染条件、终态收敛与可访问性"
provides:
  - "`OrchestrationStageTimeline.vue`：与 `OrchestratedPlanCard` 同族同色的在途阶段时间线卡（prop `sessionId: string`）"
  - "三条渲染条件的组件侧落点（会话 id / store 桶 / 至少一条已知事实）"
  - "终态一次性自动折叠 + 单一 live region + 唯一 tab stop 的可访问性契约"
  - "29 条 DOM / 交互用例，全部在真实组件树（含真实 `SubStepTimeline`）上断言"
affects: [110-07 ChatMessageBubble 挂载点]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "把「渲染条件」而不是「空态渲染」作为默认：composable 对空输入返回全 pending，组件必须自己把门，否则历史消息会渲染全灰空壳"
    - "`sessionId` 与 `phase` 合成同一个 watch 源，让「换会话重置」与「新会话已终态」在同一拍里按语义顺序发生，而不是靠两个 watch 的注册顺序"
    - "两条同族断言拆成两个 it：合成一个时先失败的那条会挡住另一条，哪条真的被守住就成了运气"
    - "跨 plan 共享文件只读不改：`SubStepTimeline` 的 `role=\"alert\"` 用只读断言核验，不顺手改别人的文件"

key-files:
  created:
    - web/src/components/chat/OrchestrationStageTimeline.vue
    - web/src/components/chat/__tests__/OrchestrationStageTimeline.spec.ts
  modified:
    - web/src/components.d.ts

key-decisions:
  - "`:aria-expanded` 用 `collapsed ? 'false' : 'true'` 而不是 plan 伪码的 `String(!collapsed)`——后者的返回类型是 `string`，Vue 的 `Booleanish` 不接受，`vue-tsc` 直接报 TS2322"
  - "折叠按钮的两句 `aria-label` 定义为组件本地 `A11Y_COPY`，不去扩 110-05 的 `COPY`：那是别人 plan 的文件，为两个串跨 plan 改共享文件不划算"
  - "「步骤行未 emit」的断言写成 `emitted('stepClick')` 而不是 `emitted()` 全等空对象：VTU 会把冒泡到根元素的原生 click 记进 `emitted()`，全等空对象是个恒假断言"
  - "显式 `import { COPY }`，不吃 110-05 泄漏进全局的 auto-import"

requirements-completed: [OBS-01, OBS-03]

# Metrics
duration: 11min
completed: 2026-07-31
---

# Phase 110 Plan 06: 编排阶段时间线卡 Summary

**把 110-05 算好的时间线画成一张与 `OrchestratedPlanCard` 同族同色的卡（164 行），落实「终态自给自足 + 一次性折叠 + 单一播报区 + 唯一 tab stop」四条契约，并用 29 条挂在真实组件树上的用例锁住；5 条负向对照逐条破坏后全部命中 plan 点名的那条测试。**

## Performance

- **Duration:** 11 min（06:55:55Z → 07:06:15Z）
- **Tasks:** 2/2
- **Files created:** 2 · **modified:** 1（生成物）
- **新增用例:** 29 条

## Accomplishments

- **「至少一条已知事实」这道门真的在组件里，而且有机械抓手。** 110-05 交棒时明确 `buildOrchestrationTimeline` 对空输入返回的是**六步全 pending**而不是空数组，所以这道门只能由组件把。负向对照 5（把渲染条件放宽成「有 sessionId 就渲染」）精确红 2 条：「桶不存在 ⇒ 不渲染」与「空桶 ⇒ 不渲染」——正是 UI-SPEC §E.3 末行禁止的那个全灰空壳。
- **一次性折叠语义是被单独证明的，不是被顺带覆盖的。** 负向对照 1（去掉 `autoCollapsed` flag）**只红 1 条**：「自动折叠 → 用户手动展开 → 再来一次 done 更新 ⇒ 仍保持展开」。其余 28 条对这个破坏完全不敏感——如果缺了这条用例，「每次 done 更新都重折」的坏实现会静默通过「done 即折叠」那条。
- **`failed` 不折叠有独立断言。** 负向对照 2（让 `failed` 也自动折叠）红 2 条：点名的「failed 保持展开」，外加「失败摘要行有 role=alert」（折叠后正文区被卸载，红步与原因行一起消失）。第二条是同族收紧，不是失真——它恰好说明「failed 折叠」这个 bug 的真实后果是**失败原因看不见**。
- **`interactive=false` 的两条断言拆开了。** 原本写成一个 `it`，负向对照跑出来只红 1 条——因为 class 断言先失败，`emit` 断言根本没执行。拆成两个独立用例后再破坏，**精确红 2 条**：「行不含 cursor-pointer」与「点击不 emit」各自成立。这正是 plan 的负向对照表要求的两条。
- **没有 stub 掉被测对象。** spec 里 `stubs` 只有 `Badge` 一项（`rg -n 'stubs'` 恰 1 处）。因此「`:interactive="false"` 是否真的传到位」「失败行是否真的挂着 `role="alert"`」两条是在**真实的 `SubStepTimeline` 实例**上读出来的，不是空断言。负向对照 3 能红，本身就是这条的证明：如果 stub 掉了，把 `interactive` 改成 `true` 不会有任何测试变红。
- **live region 不含计数有两条覆盖（在途 + 两个终态）。** 负向对照 4（在播报区拼上 `{{ doneCount }}/{{ totalCount }}`）红 2 条。
- **跨 plan 边界守住了。** `SubStepTimeline.vue` 归 110-02，本 plan **一个字都没改**——`role="alert"` 用 `rg` 与 spec 的只读断言核验成立（`SubStepTimeline.vue:132`），失败行 `aria-live` 属性为 `undefined` 也是只读断言。plan 明令的「若不成立不要顺手改」没有触发，因为它成立。
- **零新增依赖、零新增设计 token。** `git diff --exit-code web/pnpm-lock.yaml` 退出 0；组件内出现的每一个 class 都能在 `OrchestratedPlanCard` / `DeepAnalysisCard` / 既有 Tailwind 工具类里找到出处；不用 shadcn `<Card>`（用 `.card` CSS 类），Badge 上无 `:class`（本组件根本不渲染 Badge，角标由 `SubStepTimeline` 画）。

## Task Commits

1. **Task 1: OrchestrationStageTimeline.vue** — `dda66c3d` (feat)
2. **components.d.ts 生成物同步** — `b63ee7c8` (chore)
3. **Task 2: spec 28 条** — `8b871d2d` (test)
4. **负向对照驱动的用例拆分（28 → 29 条）** — `52857a33` (test)

## Files Created/Modified

- `web/src/components/chat/OrchestrationStageTimeline.vue` — **新建，164 行**。`props: { sessionId }`；`view` computed（三条渲染条件 + `try/catch` → `null` ⇒ 整块不渲染）；`collapsed` / `autoCollapsed` 两个本地 ref；一个合成源的 `watch`（`[sessionId, phase]`）承载「换会话重置」与「首次 done 折叠」；`bodyId = useId()` 供 `aria-controls`。
- `web/src/components/chat/__tests__/OrchestrationStageTimeline.spec.ts` — **新建，476 行 / 29 条**：渲染条件 6、卡头三态与步数 4、终态收敛 6、可访问性 8、零自由文本 4、兜底 1。
- `web/src/components.d.ts` — unplugin 生成物，随新组件更新。

## Decisions Made

- **`:aria-expanded="collapsed ? 'false' : 'true'"`，不用 plan 伪码的 `String(!collapsed)`。** 后者返回 `string`，Vue 的 `aria-expanded` 类型是 `Booleanish`（`boolean | 'true' | 'false'`），`vue-tsc` 报 TS2322。三元返回字面量联合类型，渲染结果与伪码逐字相同。
- **折叠按钮的 `aria-label` 用组件本地 `A11Y_COPY`，不扩 110-05 的 `COPY`。** UI-SPEC 的 Copywriting 表里有「展开编排进度」/「收起编排进度」两句，但 110-05 的 `COPY` 没有它们（那份常量服务的是纯函数，不涉及交互）。补进去意味着为两个串去改另一个 plan 拥有的文件——跨 plan 改共享文件会让两边的验收各自失真（这正是 plan 对 `SubStepTimeline` 的裁定，同一条理由适用）。容器的 `aria-label="方案编排进度"` 保持静态字面量，与 §A.6 的 DOM 结构逐字一致。
- **「步骤行未 emit」断言写成 `emitted('stepClick')`。** 首轮写的是 `expect(wrapper.emitted()).toEqual({})`，用例红——VTU 会把冒泡到根元素的原生 `click` 记进 `emitted()`。全等空对象在这里是个**恒假**断言，改成按事件名断言后，它守的才是「组件没有把步骤点击变成一个对外事件」这件事。
- **显式 `import { COPY } from '~/composables/useOrchestrationTimeline'`。** 110-05 交棒时点名的 footgun：`COPY` 已经进了全局 auto-import 命名空间，靠注入拿到的是「碰巧同名」而不是「明确依赖」。
- **正文区的存在性用 `findComponent(SubStepTimeline).exists()` 判定，不用 class 选择器。** 折叠与否的唯一可观察后果就是「真实的 `SubStepTimeline` 在不在树上」，这个判据同时也证明了「折叠卸载的是正文区、不是按钮」。

## 可观测性自检（`.cursor/rules/observability-logging.mdc`）

| 检查项 | 结论 |
|---|---|
| 结构化事件 + kv / `category` / `component` | 不适用：前端展示组件，无 `structlog` 面。**本组件零日志**——它在编排在途期间每次事件到达都会重渲染（秒级数次），打日志即刷屏 |
| 高频循环禁 INFO | ✅ 组件内 `console.*` **零处**；29 条用例统一 spy `console.warn` / `console.error` 并在 `afterEach` 断言零调用（含「桶不存在」「解析异常」两条最容易漏 warn 的路径） |
| 脱敏不可绕过 | ✅ 三道：① 服务端已剥离自由文本（110-01）；② 110-05 的纯函数根本不读那些键；③ 本组件全部 `{{ }}` 插值、零 HTML 注入面，且不接受任何后端串作为 prop（唯一的 prop 是 `sessionId`）。有「payload 塞满 `question` / `summary` / `candidate_files` / `error` ⇒ 一个字都不上屏」的用例 |
| 触发用户绑定 | 不适用（前端渲染，无请求、无落库） |
| 观测不反噬业务 | ✅ 视图 computed 包 `try/catch` → `null` ⇒ 整块不渲染；有「`buildOrchestrationTimeline` 抛 ⇒ 不渲染、不上抛、不打 warn」用例 |
| 新增请求入口 / LLM 调用 / 召回 / 队列 / webhook | 无（组件只读 store，零网络面） |

## Deviations from Plan

### 1. [Rule 3 - Blocking] `String(!collapsed)` 过不了 `vue-tsc`

- **Found during:** Task 1 收尾类型检查
- **Issue:** plan `<action>` 的 DOM 伪码写的是 `:aria-expanded="String(!collapsed)"`。`String()` 的返回类型是 `string`，而 Vue 对 `aria-expanded` 的类型约束是 `Booleanish`（`boolean | 'true' | 'false'`）⇒ `error TS2322`，`vue-tsc` 退出码 2。
- **Fix:** 改为 `:aria-expanded="collapsed ? 'false' : 'true'"`，返回字面量联合类型。渲染结果与伪码逐字相同（`'true'` / `'false'`），spec 的断言未作任何放宽。
- **Files modified:** `web/src/components/chat/OrchestrationStageTimeline.vue`
- **Commit:** `dda66c3d`

### 2. [Rule 3 - Blocking] 提交 `web/src/components.d.ts` 生成物

- **Found during:** Task 1 收尾走查
- **Issue:** 新增 `.vue` 后 unplugin-vue-components 在跑 vitest 时重新生成了这份**已入库**的声明文件，留下游离 diff（与 110-04 Deviation 2 / 110-05 Deviation 2 同因）。
- **Fix:** 单独一个 chore commit。
- **Files modified:** `web/src/components.d.ts`
- **Commit:** `b63ee7c8`

### 3. [Rule 1 - Bug] 「步骤行未 emit」的首版断言是恒假的

- **Found during:** Task 2 首轮跑测
- **Issue:** 按 plan 的「点击任一步骤行后组件**未 emit** 任何事件」直译成 `expect(wrapper.emitted()).toEqual({})`，用例直接红：VTU 把冒泡到根元素的原生 `click` 也记进了 `emitted()`。这个写法**在正确实现上也永远为假**，属于测试自身的 bug。
- **Fix:** 改为按事件名断言两处：真实子组件 `findComponent(SubStepTimeline).emitted('stepClick')` 与外层 `wrapper.emitted('stepClick')` 均为 `undefined`。覆盖比原写法更准（点名了那个唯一可能被 emit 出来的事件）。
- **Files modified:** `web/src/components/chat/__tests__/OrchestrationStageTimeline.spec.ts`
- **Commit:** `8b871d2d`

### 4. [Rule 2 - Missing critical] 「步骤行非交互」拆成两个独立用例

- **Found during:** 负向对照 3
- **Issue:** 两条断言写在同一个 `it` 里，破坏 `:interactive` 后**只红 1 条**——class 断言先失败，`emit` 断言根本没执行。plan 的负向对照表要求这条破坏让「点击未 emit」+「行不含 cursor-pointer」**两条**变红，合成一个 `it` 时第二条实际上没有被证明。
- **Fix:** 拆成 `步骤行非交互 ①` / `②` 两个用例，重跑负向对照，**精确红 2 条**。用例数 28 → 29。
- **Files modified:** `web/src/components/chat/__tests__/OrchestrationStageTimeline.spec.ts`
- **Commit:** `52857a33`

### 5. [解释，非改动] 「三处 COPY 文案在模板可见」按 DOM 判定

- Task 1 验收条款写的是「三处 COPY 文案在模板可见：`正在生成技术方案` / `方案编排已完成` / `方案编排失败`」。这三个串由 110-05 的 `buildOrchestrationTimeline` 算成 `view.title`，模板里是 `{{ view.title }}`——把字面量再抄进模板正好违反同一 plan 的「复用 110-05 导出的那份，避免两处各写一份中文串漂移」。
- **落法：按渲染结果判定**，三条独立用例分别断言三个状态下 `[data-test="timeline-title"]` 的文本恰等于对应中文串（`toBe` 全等，不是 `toContain`）。

---

**Total deviations:** 4 auto-fixed（1 处 plan 伪码过不了类型、1 处生成物、1 处测试自身 bug、1 处负向对照暴露的用例粒度不足）+ 1 处验收条款的口径说明
**Impact on plan:** 均在 plan 边界内，无范围蔓延。第 4 条是负向对照直接产生的收紧。

## Verification

### 测试（全部带 `CI=true`，按 `Tests N passed` 行判定，不看退出码）

| 命令 | 改动前 | 改动后 |
|---|---|---|
| `src/components/chat/__tests__/OrchestrationStageTimeline.spec.ts` | — | **29 passed / 1 file** |
| `src/components/chat` | **276 passed / 25 files**（实测，`--exclude` 排除新 spec） | **305 passed / 26 files**（+29） |
| `src/components/chat src/components/execution src/composables src/stores` | **627 passed / 57 files**（实测） | **656 passed / 58 files**（+29，零回归） |

- Task 2 验收门 `N ≥ 既有基线 + 20`（按 `src/components/chat` 的实测基线 276 算）：**+29 ≥ +20 ✅**。
- 🔴 **基线口径更正（沿用 110-04 / 110-05 的更正）**：plan `<verification>` 写的「基线 504 passed / 54 files」在本 worktree 的 `HEAD` 上不成立。四路径集实测 **627 / 57**，`src/components/chat` 单独实测 **276 / 25**。两个数本次都在改动前后各跑过。

### 类型 / Lint / 依赖

| 项 | 结果 |
|---|---|
| `pnpm vue-tsc --noEmit -p tsconfig.json` | 退出码 **0**（Task 1 / Task 2 / 5 条负向对照还原后各跑一次） |
| `pnpm eslint`（新增 2 个文件） | 退出码 **0** |
| `git diff --exit-code web/pnpm-lock.yaml` | 退出码 **0**，零新增依赖 |

### 源码走查（Task 1 验收条款逐条）

| 条款 | 核验方式 | 结论 |
|---|---|---|
| 根节点 `data-test` / `role="group"` / `aria-label` / `card mt-2 animate-fade-in` | 用例断言 `attributes()` 与 `classes()` | ✅ |
| 头部 class 与 `OrchestratedPlanCard` 逐字一致 | `rg -n 'px-4 py-3 border-b border-border/50 flex items-center gap-2'` 同时命中两个文件 | ✅（`OrchestratedPlanCard.vue:109` / 本组件 `:132`） |
| `icon-[lucide--workflow]` + `text-primary` | `rg` | ✅ |
| `aria-live` 恰 1 次 | `rg -c 'aria-live'` | ✅ **1** |
| 折叠按钮带 `aria-expanded` + `aria-controls`，后者指向真实节点 | 用例用 `aria-controls` 的取值反查 `[id="…"]` 存在 | ✅ |
| 传给 `SubStepTimeline` 的 `interactive` 字面为 `false` | 模板 `:interactive="false"`；负向对照 3 证实这个字面是承重的 | ✅ |
| 不出现 `<Card` / `v-html` / `localStorage` | `rg -c -F` 逐串 | ✅ 全部 **0** |
| 不出现 §D.1 归属他处的文案 | `rg -c -F`：`未经 LLM 推理` / `置信度` / `进入编码` | ✅ 全部 **0**（源码与 DOM 两侧都有断言） |
| 三处标题文案 | 三条 `toBe` 全等用例（见 Deviation 5） | ✅ |
| 产物 ≥ 90 行 | `wc -l` | ✅ **164** |
| spec 未 stub `SubStepTimeline` | `rg -n 'stubs'` 恰 1 处且只含 `Badge` | ✅ |

### 跨 plan 只读核验（不改别人的文件）

| 核验项 | 结论 |
|---|---|
| `rg -n 'role="alert"' web/src/components/execution/dag/SubStepTimeline.vue` | ✅ 命中 `:132`（`:role="step.status === 'failed' ? 'alert' : undefined"`）⇒ plan Task 1 的前置条件成立，**未触发**「报为偏差」分支 |
| 该文件是否被本 plan 改动 | ✅ `git status` 全程未出现该文件 |

## 负向对照（5 条全部执行 → 确认变红 → 还原）

| # | 破坏方式 | plan 点名必红的测试 | 实际变红 | 结果 |
|---|---|---|---|---|
| 1 | 去掉自动折叠的一次性 flag（每次 `done` 更新都折叠） | 「自动折叠 → 用户展开 → 再次更新仍展开」 | **该条** | ✅ **1 failed / 27 passed** |
| 2 | 让 `failed` 也自动折叠 | 「failed 保持展开」 | **该条** + 「失败摘要行有 role=alert」 | ✅ 2 failed / 26 passed |
| 3 | 把 `:interactive` 改成 `true` | 「点击步骤行未 emit」+「行不含 cursor-pointer」两条 | **两条各自变红** | ✅ 2 failed / 27 passed |
| 4 | 在 live region 里拼上 `{{ doneCount }}/{{ totalCount }}` | live region 不含 `/` 的断言 | **在途那条** + 「done / failed 终态同样不含 `/`」 | ✅ 2 failed / 27 passed |
| 5 | 把渲染条件放宽为「有 sessionId 就渲染」 | 「桶不存在 ⇒ 不渲染」+「空桶 ⇒ 不渲染」 | **两条** | ✅ 2 failed / 27 passed |

**粒度说明**：

- 对照 1 只红 **1 条**——其余 28 条对这个破坏完全不敏感，这正是那条一次性用例必须单独存在的证明。
- 对照 2 的第二条是**同族收紧**：折叠后正文区被卸载，`role="alert"` 的原因行随之消失。它说明「failed 折叠」这个 bug 的真实后果是**失败原因看不见**，不是失真。
- 对照 3 在拆分用例**之前**只红 1 条（class 断言先失败挡住了 emit 断言）。这是 Deviation 4 的来源，拆分后才达到 plan 表格要求的两条。
- 对照 5 未波及「空 sessionId ⇒ 不渲染」那条——因为 `sessionId` 非空是一道独立的前置判定，本次破坏只放宽了「桶存在」与「至少一条事实」两条。粒度与 plan 表格描述一致。
- **plan 表格第 6 行（`stubs: { SubStepTimeline: true }`）按 plan 明示不执行**：它自陈「无测试会红」，由源码级验收（`rg -n 'stubs'` 恰 1 处且只含 `Badge`）堵住。已在上表「源码走查」里核验。

还原方式一律为 `git checkout -- src/components/chat/OrchestrationStageTimeline.vue`（逐文件，**未使用任何 blanket reset / clean / stash**）。5 条全部还原后复跑：spec **29 passed**、`src/components/chat` **305 passed / 26 files**、四路径集 **656 passed / 58 files**、`vue-tsc` 退出码 0、`eslint` 退出码 0、`git status` 对已提交版本干净。

## must_haves 逐条核对

| # | truth | 证据 |
|---|---|---|
| 1 | 卡底与卡头骨架逐字沿用 `OrchestratedPlanCard` | `rg` 同一串 class 命中两个文件；`classes()` 断言含 `card` / `mt-2` / `animate-fade-in` |
| 2 | 时间线自身的终态就是完成信号（`done` ⇒ 标题变「方案编排已完成」） | 三态标题三条 `toBe` 全等用例；组件不引用 `OrchestratedPlanCard`，标题只取 `view.title` |
| 3 | `done` 自动折叠且只触发一次；用户展开后不再被折回 | 「初次即 done ⇒ 正文不渲染」+「在途 → done 折叠一次」+「展开后再更新仍展开」三条；负向对照 1 只红第三条 |
| 4 | `failed` 保持展开，红点 + 红标签 + `role=alert` 原因行可见 | 「failed 保持展开」+「失败摘要行 role=alert 且文本为闭集文案」；负向对照 2 |
| 5 | 卡内有且只有一处 `sr-only role=status aria-live=polite`，且不含 `{done}/{total}` | `findAll('[aria-live]')` 长度 1 + `role` / `aria-live` / `sr-only` 三个属性断言 + 两条 `not.toContain('/')`；源码 `rg -c 'aria-live'` = 1；负向对照 4 |
| 6 | 失败行 `role=alert` 且不加 `aria-live` | `attributes('aria-live')` **`toBeUndefined()`**（断言属性不存在，不是断言等于某值）；只读核验 `SubStepTimeline.vue:132`，本 plan 未改该文件 |
| 7 | 步骤行非交互；唯一 tab stop 是折叠按钮 | 拆分后的两条非交互用例 + 「可聚焦元素恰 1 个且是 `timeline-toggle`」；负向对照 3 精确红 2 条 |
| 8 | 自动折叠不移动焦点、不 autofocus；折叠按钮不被卸载 | 「焦点在按钮上 → 触发折叠 → `document.activeElement` 仍是该按钮」（`attachTo: document.body` 真实挂载）+ 折叠后 `find(TOGGLE).exists()` 仍为 true，同时 `[id=bodyId]` 已消失 |
| 9 | 三条渲染条件任一不成立即整块不渲染，不抛错、不打 warn | 渲染条件 6 条用例 + 全局 `console.warn` / `console.error` 零调用断言；负向对照 5 |
| 10 | **backstop** — 折叠态为本地 ref，不写 store、不入 localStorage；`sessionId` 变化后重算 | 「sessionId 变化 ⇒ 重置」+「卸载重挂后按新状态重算」两条；源码 `rg -c 'localStorage'` = 0，组件对 store 只读不写 |
| 11 | **backstop** — 零 `v-html`，全部插值，不渲染任何后端自由文本 | 源码级用例（读文件、排除注释行、断言无匹配）+「payload 塞满四类自由文本 ⇒ 一个字都不上屏」+「未受控 `reason_code` ⇒ 含『未知原因』且不含原值」 |
| 12 | **backstop** — 零新增颜色 / 字号 / 字重 / 间距 / ui 组件 / npm 依赖；不用 `<Card>`；Badge 无 `:class` | `rg -c -F '<Card'` = 0；`git diff --exit-code web/pnpm-lock.yaml` 退出 0；本组件不渲染任何 Badge（角标由 `SubStepTimeline` 画），有「无降级时卡内 Badge 数为 0」的用例 |
| 13 | **backstop** — 解析异常被吞掉，绝不影响对话正文与工具气泡 | computed 级 `try/catch` → `null`；「`buildOrchestrationTimeline` 抛 ⇒ 不渲染、不上抛、不打 warn」用例（用 `importOriginal` 包一层可开关的 throw，其余用例仍走真实实现） |

## Threat Flags

无。本 plan 是纯前端渲染组件，未引入网络端点 / 鉴权路径 / 文件访问模式 / 信任边界上的 schema 变更。`threat_model` 5 条 disposition 全部落地：

| Threat ID | 落地形态 |
|---|---|
| T-110-06-01（新增文案渲染被篡改） | 全部 `{{ }}` 插值；源码级用例断言零 HTML 注入面（读文件、排除注释行） |
| T-110-06-02（后端自由文本 / 未受控 `reason_code` 上屏） | 唯一的 prop 是 `sessionId`，文案全取 `COPY` / `A11Y_COPY`；`weird_unmapped` 不出现在 DOM 的用例 + 四类自由文本串不出现的用例 |
| T-110-06-03（进度解析异常打掉消息气泡） | computed 包 `try/catch` → `null` ⇒ 整块不渲染；有专门用例 |
| T-110-06-04（屏幕阅读器重复播报） | 单一 live region（`findAll` 长度 1）+ 失败行 `aria-live` 属性 `toBeUndefined()`；两条都是属性级断言 |
| T-110-06-SC（供应链） | 零新增依赖，未跑 `shadcn init` / `add`，`git diff --exit-code web/pnpm-lock.yaml` 退出码 0 |

## Known Stubs

无。本组件的每一处渲染都接在真实数据源上（store 桶 → 110-05 纯函数 → 真实 `SubStepTimeline`）。**唯一尚未接通的是挂载点**——`ChatMessageBubble` 里还没有 `<OrchestrationStageTimeline />`，这是 plan 明确划给 110-07 的边界（`<objective>` 逐字写着「本 plan 不改 `ChatMessageBubble`」），不是未完成的桩。

## Issues Encountered

- **首轮一条用例红，是用例自身写错**（Deviation 3）：`expect(wrapper.emitted()).toEqual({})` 在正确实现上也为假，VTU 记录了冒泡到根的原生 `click`。改成按事件名断言。
- **负向对照 3 首跑只红 1 条**（Deviation 4）：合成的 `it` 里前一条断言挡住了后一条。这条是负向对照的直接产出——如果不跑对照，这个粒度问题在 28 条全绿的 spec 里完全不可见，而它恰好是这个里程碑反复被咬到的形状。
- **`String(!collapsed)` 与 Vue 的 `Booleanish`**（Deviation 1）：plan 伪码里的写法过不了 `vue-tsc`。值得记一笔的是 `eslint` 对此完全无感（退出 0），只有 `vue-tsc` 抓到——这是「lint 绿不等于类型绿」的一个具体样本。

## User Setup Required

None - 纯前端组件，无外部服务配置。

## Next Phase Readiness

- **110-07（挂载 + 调研日志组）** 可直接在 `ChatMessageBubble.vue` 的单例 tool 分支内、`OrchestratedPlanCard` **之前**插 `<OrchestrationStageTimeline :session-id="…" />`。组件只要一个 `sessionId`：
  - **§A.5 条件 1（`isOrchestrationTool`）与条件 2 的「绑到会话」仍归 110-07**——本组件只把「桶存在 + 至少一条已知事实」这两道门（条件 2 的后半与条件 3）。绑不到会话时传空串即可，组件不渲染、不抛。
  - **§A.7 的「同一消息多个编排 tool call 只渲染一次」也归 110-07**：本组件不做去重，挂几次画几次。
  - 组件对 store **只读**，不写任何状态、不做持久化，重复挂载彼此无干扰。
- **未验证面**：本 plan 全程为组件单测，**未跑过一次真实编排**。三处最可能在 UAT 才暴露的地方：① 折叠动效在真实卡片里的观感（本组件不引入新动画，只用既有 `animate-fade-in`；折叠是 `v-if` 直接卸载，无过渡——UI-SPEC 未要求过渡，若 UAT 觉得突兀属可调项）；② `useId()` 生成的 `bodyId` 在同一条消息里挂多个实例时是否唯一（Vue 保证 app 内唯一，但多实例场景本身归 110-07 去重）；③ 110-05 交棒时标注的三处后端 payload 未实测面（`classified.summary` 键名、`merge.started` 的 `ts` 跨链一致、`segment_count` 的首 2 秒空窗）在本组件上的表现都是「该行不渲染」，不会报错。

## Self-Check: PASSED

- `web/src/components/chat/OrchestrationStageTimeline.vue`（164 行，含 `orchestration-stage-timeline`）与 `web/src/components/chat/__tests__/OrchestrationStageTimeline.spec.ts`（476 行，含 `aria-expanded`）均存在于磁盘，两个 `contains` 断言字面量命中，`min_lines: 90` 满足。
- 四个 commit（`dda66c3d` / `b63ee7c8` / `8b871d2d` / `52857a33`）均可在 `git log` 中检索到。
- `key_links` 两条均成立：组件 `rg 'buildOrchestrationTimeline'` 命中（import + 调用各一处）；`rg 'SubStepTimeline'` 命中（import + `:steps` / `:interactive="false"` 的调用点）。`vue-tsc` 退出码 0 提供类型层证据。

---
*Phase: 110-process-observability*
*Completed: 2026-07-31*
