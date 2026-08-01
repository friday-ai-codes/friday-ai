---
phase: 110-process-observability
plan: 02
subsystem: ui
tags: [vue3, typescript, vitest, vue-test-utils, tailwind4, a11y, timeline]

# Dependency graph
requires: []
provides:
  - "TimelineStepItem：与 execution 域解耦的通用竖向时间线 item 契约"
  - "泛化后的 SubStepTimeline：6 态 / 可选 summary / 可选 badge / interactive 开关 / list 语义 / pulse 开关"
  - "SubStepTimeline.spec.ts：ExecutionNode 既有用法零回归锁 + 新增能力用例（该组件此前零测试）"
affects: [110-05, 110-06, chat 侧编排阶段时间线]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "共享组件的纯加性泛化：新增项全为可选 props / 可选字段，既有调用方零改动"
    - "泛化前先补『既有行为回归锁』并对改动前的组件跑绿，再动组件"
    - "状态用形状差异（空心点 vs 实心点）+ title + sr-only 文本传达，不靠颜色单独承载"
    - "被嵌套组件只用 role=alert，不自带 aria-live —— 播报归属留给外层单一 live region"

key-files:
  created:
    - web/src/components/execution/dag/__tests__/SubStepTimeline.spec.ts
  modified:
    - web/src/types/execution.ts
    - web/src/components/execution/dag/SubStepTimeline.vue

key-decisions:
  - "Unresolved #3 裁定：泛化共享 SubStepTimeline，不在 chat 下新建逐字复制的本地副本 —— 5 处缺口全是通用时间线关注点，且副本的漂移不报错不变红"
  - "Unresolved #5 裁定：skipped / unknown 并入组件内既有那份 stepStatusColor map，不迁 ~/config/status.ts，也不在 chat 侧另起第二份"
  - "skipped 与 unknown 共用同一空心点视觉，靠摘要文案区分 —— 把『不知道』画成『失败』是撒谎"
  - "aria-live 字样不得出现在 <template> 注释里：非生产构建下 Vue 保留模板注释，会污染『渲染结果不含 aria-live』的断言"

patterns-established:
  - "零回归锁前置：新写的 A 组用例先对**改动前**的组件跑绿，证明它描述的是今天的行为而不是改完之后的行为"
  - "截断类断言必须断长度与全等，不能只断『包含』—— 包含匹配对『没截断』的实现同样为真"

requirements-completed: [OBS-03]

# Metrics
duration: 19min
completed: 2026-07-31
---

# Phase 110 Plan 02: SubStepTimeline 加性泛化 Summary

**把 71 行的 `SubStepTimeline` 纯加性泛化为 6 态通用竖向时间线（可选 summary / badge / pulse、`interactive` 只读开关、list 语义与 sr-only 状态文本），并从零建起 27 条用例把唯一既有调用方 `ExecutionNode` 的行为机械钉死。**

## Performance

- **Duration:** 19 min
- **Started:** 2026-07-31T05:41:00Z
- **Completed:** 2026-07-31T06:00:00Z
- **Tasks:** 2
- **Files modified:** 3（新建 1 / 修改 2）

## Accomplishments

- `TimelineStepItem` 与 `SubStep` 解耦：`status` 从 4 值扩到 6 值，`summary` / `badge` / `pulse` / `output_data` 全部可选。`SubStep` 结构上满足它，`ExecutionNode.vue:341` 的调用点一个字都没改。
- 状态点扩为 6 态，`skipped` / `unknown` 并入**既有那一份** map（文件内 `const map` 仍恰为 1 处），用空心点（`bg-transparent border border-muted-foreground/50`）——同色 token 改用边框，是形状差异不是新色板。
- 状态不再只由颜色传达：每行带 `:title` 与 `sr-only` 状态文本（未开始 / 进行中 / 已完成 / 失败 / 已跳过 / 进度未知），`statusText` 可逐键覆盖。
- `interactive=false` 时行不可点：无 `cursor-pointer`、无 hover 背景、**根本不绑 click 监听**、不进 tab 序。
- 该组件此前**零测试**，现有 27 条用例（A 组 6 条零回归锁 + B 组 21 条新能力）。7 条负向对照逐条验证过用例真的会红。
- 零新增依赖、零新色板 / 字号 / 间距 token、零 `v-html`、`pnpm-lock.yaml` 未变。

## Task Commits

1. **Task 1: TimelineStepItem 类型 + SubStepTimeline 加性泛化** — `ed637c3b` (refactor)
2. **Task 2: SubStepTimeline spec（零回归锁 + 新增能力）** — `aaf01830` (test)

## Files Created/Modified

- `web/src/types/execution.ts` — 在 `SubStep` 之后新增 `TimelineStepItem` 接口（6 态 status，summary / badge / pulse / output_data 均可选）
- `web/src/components/execution/dag/SubStepTimeline.vue` — 纯加性泛化：`interactive` / `statusText` 两个 prop、6 态状态点、可选摘要行与行尾角标、`role=list` / `role=listitem` / `sr-only` 状态文本
- `web/src/components/execution/dag/__tests__/SubStepTimeline.spec.ts` — 新建，27 条用例

## Decisions Made

- **Unresolved #3（泛化 vs 副本）**：按 PLAN `<decision>` 采「加性泛化共享组件」。执行中没有出现推翻它的理由——`ExecutionNode` 的调用点确实一字未动，`vue-tsc` 也从类型层证明了 `SubStep[]` 可直接喂给 `TimelineStepItem[]`。
- **Unresolved #5（状态色 map 位置）**：新增两态并入组件内既有 map。既有技术债（DESIGN.md 禁止组件内 statusColors）不扩大、不新增第二处。
- **`skipped` 与 `unknown` 共用同一视觉**：两者都不是错误态，靠摘要文案区分。
- **摘要行的渲染条件保持与旧实现逐字等价**：条件写成 `Boolean(step.summary) || (failed && Boolean(output_data?.error))`，而不是「文案非空才渲染」。差别只在一种边角情形——`failed` 且 `error` 是非字符串真值时旧实现会渲染一个空 span；沿用旧条件确保这种情形下 DOM 也完全一致。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `aria-live` 字样从 `<template>` 注释移到 `<script>` 注释**

- **Found during:** Task 1（组件泛化）
- **Issue:** 按 PLAN 第 6 点写的模板注释里含 `aria-live` 字面量。Vue 编译器只在生产构建下剥离模板注释，dev / test 下注释会保留进渲染结果——`wrapper.html()` 因此会包含 `aria-live` 字符串，让「组件渲染结果不含 aria-live」这条断言恒假，同时也让对应的负向对照失去意义（改坏与没改坏产出同一结果）。
- **Fix:** 模板注释改写为不含该字面量的措辞，完整理由与该约束移入 `<script>` 段的 `summaryText` 文档注释（并写明「该字样不能出现在模板注释里」以防后人改回去）。
- **Files modified:** `web/src/components/execution/dag/SubStepTimeline.vue`
- **Verification:** `awk '/<template>/,/<\/template>/' … | rg aria-live` 无匹配；负向对照 6 确认加上 `aria-live="polite"` 后 3 条用例变红。
- **Committed in:** `ed637c3b`（Task 1 commit）

**2. [Rule 3 - Blocking] `@click` 改用 `v-on` 对象绑定实现「条件绑定」**

- **Found during:** Task 1
- **Issue:** PLAN 要求 `interactive === true` 才**绑** `@click`，但 `@click.stop="interactive && emit(...)"` 这种写法仍然会注册监听器并无条件 `stopPropagation`，只是不 emit——不满足验收项「不存在无条件的 @click」。
- **Fix:** 抽出 `onRowClick(event, step)`（内部显式 `event.stopPropagation()`），模板用 `v-on="interactive ? { click: … } : {}"`，`interactive=false` 时监听器根本不存在。
- **Files modified:** `web/src/components/execution/dag/SubStepTimeline.vue`
- **Verification:** 负向对照 2（改成无条件绑定）确认 `interactive: false` 那条用例变红。
- **Committed in:** `ed637c3b`（Task 1 commit）

---

**Total deviations:** 2 auto-fixed（1 bug、1 blocking）
**Impact on plan:** 两处都是为了让 PLAN 明写的验收项**真的成立**而非表面成立，未扩大范围。

## 验证结果（实测数字，非推断）

### 测试

| 命令 | 结果 |
|---|---|
| 基线（改动前）`CI=true pnpm vitest run --watch=false src/components/execution src/components/chat src/stores src/composables` | **504 passed / 54 files** |
| 终态同一路径集 | **531 passed / 55 files**（= 504 + 27 新增，既有 504 条零回归） |
| `CI=true pnpm vitest run --watch=false src/components/execution` | **51 passed / 4 files**（24 既有 + 27 新增），≥ 验收要求的 14 |

> 全程带 `CI=true`。无该变量时 vitest 会撞 `EMFILE: too many open files` 并**仍然退出 0**，因此上述结论一律取自 `Tests N passed` 行，不取退出码。

### 零回归的机械证据

A 组 6 条用例是**先于组件改动**写下并对**改动前的 `SubStepTimeline`** 跑绿的（30 passed），改动后同一组用例仍绿（30 passed）。这不是「改完之后补一组能过的用例」，而是「用例先描述了今天的行为，改动没有触碰它」。

`ExecutionNode` 未被波及的三重证据：
1. 调用点 `web/src/components/execution/dag/ExecutionNode.vue:341` 未出现在本 plan 任何一个 commit 的 diff 里。
2. `nodeSubSteps` 是显式的 `computed<SubStep[]>`，`pnpm vue-tsc --noEmit -p tsconfig.json` **exit 0** ⇒ `SubStep[]` 可赋给 `TimelineStepItem[]` 有类型层证据。
3. A 组逐条锁住：4 状态色、`output_data.error` 的 50 字截断、默认可点击并 emit `stepClick`、非 failed 不渲染摘要行、failed 摘要沿用 `text-red-400/70`。

### 其他门禁

| 项 | 结果 |
|---|---|
| `pnpm vue-tsc --noEmit -p tsconfig.json` | exit **0** |
| `pnpm eslint`（改动的 3 个文件） | exit **0** |
| `git diff --exit-code web/pnpm-lock.yaml` | exit **0**（零新增依赖） |
| `rg -c "const map" SubStepTimeline.vue` | **1**（未新建第二份状态色 map） |
| `<template>` 内 `aria-live` | 无匹配 |
| `v-html` | 无匹配 |
| `<Badge` 标签上的 `:class` | 无匹配 |
| 无条件 `cursor-pointer` 字面量 | 无（仅出现在 `:class="interactive ? … : undefined"` 内） |

### 负向对照（逐条破坏 → 确认变红 → 还原）

| # | 破坏方式 | 实际变红的用例 | 结果 |
|---|---|---|---|
| 1 | `interactive` 默认值 `true` → `false` | A 组「默认（不传 interactive）点击一行 ⇒ emit stepClick…」 | 1 failed / 26 passed ✅ |
| 2 | 去掉 `interactive` 条件，`click` 无条件绑定 | B 组「`interactive: false` ⇒ 点击不 emit stepClick…」 | 1 failed / 26 passed ✅ |
| 3 | 摘要优先级反转（`output_data.error` 优先于 `summary`） | B 组「failed + summary + error 三者齐全 ⇒ 渲染 summary，DOM 不含 error 内容」 | 1 failed / 26 passed ✅ |
| 4 | `skipped` / `unknown` 取值改为 `bg-red-400` | B 组空心点用例（`skipped` 与 `unknown` 各一条，含「不含 bg-red-400」断言） | 2 failed / 25 passed ✅ |
| 5 | `pulse` 默认值反转（`pulse !== true` 就去动画） | B 组「不传 pulse ⇒ 仍含 animate-pulse」+ A 组「4 个既有状态各渲染既有状态点类」 | 2 failed / 25 passed ✅ |
| 6 | 失败摘要行加上 `aria-live="polite"` | B 组「渲染结果整体不含 aria-live」+「failed 摘要行 aria-live 属性不存在」+「error 回退路径同样 role=alert」 | 3 failed / 24 passed ✅ |
| 7 | 删掉 `output_data.error` 的 `.slice(0, 50)` | A 组的长度断言用例 | 1 failed / 26 passed ✅ |

7 条全部命中 PLAN `<negative_control>` 表里点名的那条（或那条 + 额外收紧）。还原后复跑 **27 passed**，组件文件对已提交版本 `git diff --exit-code` 通过——破坏痕迹零残留。

> 第 6 条按 PLAN 的说明**归本 plan 独有**：失败摘要行住在 `SubStepTimeline.vue`，本 plan 是它的所有者；110-06 只对它做只读断言。
> 第 5 条比 PLAN 预期多红一条（A 组的 4 状态色用例也断言了 `running` 含 `animate-pulse`），是收紧不是失真。

## must_haves 逐条核对

| # | truth | 证据 |
|---|---|---|
| 1 | item 类型解耦为 `TimelineStepItem`，不新增组件原语 / 色板 / 字号 | `types/execution.ts` 新增接口；零新 Tailwind 值，`Badge` 复用既有 `warning` / `info` / `muted` |
| 2 | `ExecutionNode` 行为逐字不变 | A 组 6 条（改动前后各跑绿一次）+ `vue-tsc` exit 0 + 调用点零 diff |
| 3 | `skipped` / `unknown` 空心灰点，形状差异非颜色 | `bg-transparent border border-muted-foreground/50`；用例断言含 `border` 且**不含** `bg-red-400` |
| 4 | 每行 `title` + `sr-only` 六态状态文本 | 「不传 statusText ⇒ 用内置中文默认」逐行断言 6 个标签 |
| 5 | 失败摘要行 `role=alert` 且**不带** `aria-live` | 断言 `attributes('aria-live')` 为 `undefined`（属性不存在）；负向对照 6 |
| 6 | `interactive=false` 行不可点、不进 tab 序 | 「点击不 emit」+「无 tabindex、非 button、全组件无 button」两条 |
| 7 | summary 存在即渲染；failed 时 summary 优先，缺失回退 `output_data.error` | 三条用例（summary / 优先级 / 均缺省不渲染）+ A 组回退路径 |
| 8 | Badge 纯 variant，标签无 `:class` | `rg '<Badge[^>]*:class'` 无匹配；用例断言 `data-variant` |
| 9 | `running` + `pulse:false` 只去动画不改色 | 「含 `bg-primary` 但不含 `animate-pulse`」+ 默认值回归锁两条 |
| 10 | **backstop** — 状态色 map 仍是组件内那一份 | `rg -c "const map"` = **1** |
| 11 | **backstop** — 全部新增项可选，缺省渲染与改动前一致 | A 组对**改动前**组件先绿、改动后仍绿；`withDefaults` 里 `interactive: true` 字面可见 |
| 12 | **backstop** — 未知 status 回退灰实心不崩 | 「`status: 'weird'` ⇒ `bg-muted-foreground/50` 且不含 `bg-transparent`」，且全用例 `console.error` / `console.warn` 零调用 |
| 13 | **backstop** — 新增面零 `v-html` | `rg 'v-html'` 无匹配 |

## Issues Encountered

- **模板注释会进渲染结果**：见「Deviations #1」。这类问题的特征是「断言恒真、负向对照恒绿」——不报错、不变红，正是本里程碑反复强调要防的静默失真，所以在代码注释里写明了原因防回退。
- 用例的行选择器刻意选了泛化前后都成立的 `.relative.flex.items-start.gap-2`（而不是新加的 `[role="listitem"]`），否则 A 组无法在改动前先跑绿，「零回归锁」就退化成「改完之后补的用例」。

## User Setup Required

None - 纯前端改动，无外部服务配置。

## Next Phase Readiness

- `SubStepTimeline` 已可被 chat 侧直接复用：110-05 / 110-06 只需传 `:steps`（`TimelineStepItem[]`）与 `:interactive="false"`，无需新建组件原语。
- 阶段→状态的映射（`active → running`、`complete → completed`）由调用方负责，本组件不做语义翻译。
- 后续在 `SubStepTimeline` 内加 `aria-live` 会打破「一个事实播一次」，`<script>` 段注释与用例已双重防守。
- 遗留技术债（本 phase 不扩大）：组件内局部状态色 map 形式上违反 DESIGN.md 禁令，已记入 UI-SPEC Unresolved #5。

## Self-Check: PASSED

- 声称创建 / 修改的 4 个文件全部存在于磁盘。
- 声称的 2 个 commit（`ed637c3b` / `aaf01830`）在 `git log` 中可查。
- `git diff --stat ed637c3b~1..HEAD` 恰为 3 个文件，`ExecutionNode.vue` **不在其中**。

---
*Phase: 110-process-observability*
*Completed: 2026-07-31*
