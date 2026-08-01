---
phase: 109
slug: 109-spine-convergence
audited: 2026-07-31T11:52:00+08:00
status: pass-with-findings
baseline: 109-UI-SPEC.md
diff_base: 256899d5
screenshots: not-captured
advisory: true
scores:
  copywriting: 4
  visuals: 3
  color: 4
  typography: 4
  spacing: 4
  experience_design: 3
  total: 22
  max: 24
findings:
  high: 1
  medium: 2
  low: 2
---

# Phase 109 — UI Review（双脊柱合流 · 6 维度代码级审计）

**Audited:** 2026-07-31
**Baseline:** `109-UI-SPEC.md`（重点 §B 草稿横幅 + 常驻徽标、§C 阻断式确认弹层）
**Diff base:** `256899d5..HEAD`（`git diff 256899d5 HEAD -- web/`，12 文件 / +2216 −42）
**Screenshots:** 未捕获（localhost 3000 / 5173 / 10240 / 8080 均无 dev server，纯代码级审计）
**Scope:** `OrchestratedPlanCard.vue`（新建）、`TechPlanCard.vue`、`ChatMessageBubble.vue`、`useToolDisplay.ts`
**测试基线:** 4 个 spec 文件 / 126 用例全绿（`vitest run`，本次实跑）
**性质：** 顾问性 / 非阻塞（advisory）。真实浏览器下的焦点顺序、屏幕阅读器播报、对比度需 UAT 复核。

---

## 维度评分总览

| # | 维度 | 判定 | 分 | 关键发现 |
|---|------|------|----|---------|
| 1 | Copywriting | PASS | 4/4 | §Copywriting Contract 全表 22 条**逐字落地**；后端 `message`/`placeholder`/`detail` 零上屏 |
| 2 | Visuals | FLAG | 3/4 | 卡片结构与 §A.3 逐行一致；但编排工具 pill 的展开箭头成了**死交互**（MN-01） |
| 3 | Color | PASS | 4/4 | **零新色板**：新增色仅 `amber-500/5`、`amber-500/30`、`text-amber-500`（契约预声明且 `CommitConfirmCard` 已在用）；新增两个 Badge 纯 `variant` |
| 4 | Typography | PASS | 4/4 | **零新字号字重**：仅 `text-sm`/`text-xs` + `font-medium`/`font-semibold`；无 arbitrary value |
| 5 | Spacing | PASS | 4/4 | **零新间距值**：全部落在 §Spacing Scale 已声明的 token 与既有半步例外内 |
| 6 | Experience Design | FLAG | 3/4 | 状态覆盖 / 幂等 / 重试 / 弹层重置 / plan_id 守卫齐备；但**确认 Checkbox 无可访问名称**（HI-01） |

**总分：22 / 24** — 设计契约达成度很高，视觉零漂移这条硬约束**完全守住**。无阻塞项；1 项 high a11y 建议合流前修复。

---

## 优先修复（Top 3）

1. **HI-01 · 风险确认 Checkbox 对屏幕阅读器是一个无名控件** — `TechPlanCard.vue:980-983`
   用户影响：**真实用户可见问题**（限读屏用户）。这是 RELY-01 唯一的人工签名点，读屏只播报「复选框 未勾选」，听不到「我已了解风险，仍要用该草稿送编码」，而「仍要送编码」按钮又恰好被它锁死。
   修复：给 `Checkbox` 加 `id`、把 `<label>` 改成 `for` 关联（reka-ui `CheckboxRoot` 内建 `[for=id]` → `aria-label` 推导，零新组件）。

2. **MN-01 · 编排工具 pill 的展开箭头点了没反应** — `ChatMessageBubble.vue:1230` / `:1256`
   用户影响：**真实用户可见问题**。箭头会转，面板永远不出现；编排在途 / 失败时（按 D-4 不渲染卡片）整条 pill 变成一个没有任何产出的可点元素。
   修复：把 `:1256` 的抑制条件从「是编排工具」收窄成「是编排工具**且卡片已渲染**」。

3. **MN-02 · 同一条消息内两个编排工具会渲染两张一模一样的卡片** — `ChatMessageBubble.vue:791` / `:1253`
   用户影响：**真实用户可见问题（低概率）**。`orchestratedPlanData` 取 `find(...)`（首个），而 `v-if` 逐 item 判定 ⇒ 第二张卡片带着**第一个工具的** `artifact_version_id`，点进去投影出错误的方案。
   修复：把解析函数改成按 `item.id` 取当前工具的 result。

---

## 详细发现

### 维度 1 · Copywriting — 4/4（PASS）

§Copywriting Contract 界面侧全表逐条比对，**22 条文案全部逐字一致**，无近似、无遗漏：

| 契约位置 | 落点 | 结果 |
|---|---|---|
| 编排卡标题 / 徽标 / 说明句 | `OrchestratedPlanCard.vue:36-38` | 逐字 ✅ |
| CTA / loading / 已投影说明 | `:39-41` | 逐字 ✅ |
| 三条投影 toast | `:42-44` | 逐字 ✅ |
| 草稿横幅主句 + 次行 | `TechPlanCard.vue:616` / `:619` | 逐字 ✅ |
| 折叠态徽标「未经调研」 | `TechPlanCard.vue:578` | 逐字 ✅ |
| 弹层标题 / 正文 / 必勾项 / 双按钮 | `TechPlanCard.vue:973-998` | 逐字 ✅ |
| gate 拒绝 toast | `TechPlanCard.vue:303` | 逐字 ✅ |
| 空正文占位「（暂无方案正文）」 | `TechPlanCard.vue:632` | 逐字 ✅ |
| 工具标签 / 图标 / 三分支摘要 | `useToolDisplay.ts:51-52`、`:85-86`、`:389-401` | 逐字 ✅ |

**「后端自由文本不上屏」纪律守住**（这是本 phase 反复强调的一条，逐项复核通过）：

- `OrchestratedPlanCard` 全组件用 `COPY` 常量对象，后端 `message` 未被读取；
- `useToolDisplay.ts:389-401` 三分支全取本文件常量，`placeholder` 未回显；
- `TechPlanCard.vue:392-395` gate 拒绝走前端常量，**不回显 `detail`**；
- `isDraftGateRejection`（`:378-383`）按 `body.code` 判定，**未做任何文案匹配** —— 契约要求 #4 落地。

**`provenance` 原始取值零上屏**：全仓 4 处引用（prop 声明 / computed 比较 / 赋值 / 传参），**无一进入渲染路径**，未知取值也不会泄漏到界面。

一处良性偏离：`toolAction` 兜底分支在 `requirement` 为空时返回 `TOOL_LABELS[bare]` 而非契约的 `编排「…」`（`useToolDisplay.ts:399-401`）—— 空需求文本下 `编排「」` 反而更差，实现判断更优，**不计缺陷**。

---

### 维度 2 · Visuals — 3/4（FLAG）

**契约达成部分**：`OrchestratedPlanCard.vue:106-152` 的 DOM 与 §A.3 结构图**逐行对得上** —— `.card mt-2 animate-fade-in` → 头部 `px-4 py-3 border-b border-border/50 flex items-center gap-2` + `icon-[lucide--workflow] text-primary` + `text-sm font-semibold` + `Badge variant="success" ml-auto` → 正文 `px-4 py-3` 一句 `text-xs text-muted-foreground` → 操作区 `px-4 pb-4 pt-1`。**不折叠、无展开区、无骨架屏、无任何进度 / 阶段 UI**，D-4「在途完全不呈现」的边界守得很干净。

图标全部为仓内既有：`workflow` / `arrow-right` / `loader-2` / `alert-triangle`。契约点名禁用的 `file-check-2` 未出现。`alert-triangle` 与 `TechPlanCard` 组件内既有用法（`:890`）同名，未混入 `triangle-alert` 别名。

头部徽标共存布局（§B.3）逐条正确（`TechPlanCard.vue:577-593`）：草稿徽标 `ml-auto` / 状态徽标降 `ml-1` / chevron `ml-1`；草稿徽标不渲染时 chevron 回到 `!isUnresearched && status === 'draft' ? 'ml-auto' : 'ml-1'` —— 与今日现状完全一致。

**扣分项 — MN-01（medium，真实用户可见）**

```
web/src/components/chat/ChatMessageBubble.vue:1230   ← 箭头渲染条件
web/src/components/chat/ChatMessageBubble.vue:1256   ← 详情面板抑制条件
```

`:1230` 的展开箭头只要 `item.input` 非空就渲染，而编排工具的 input 有 `space_id` / `requirement` ⇒ **箭头必然出现**。但 `:1256` 无条件排除了编排工具：

```
v-if="expandedTools.has(item.id) && !isCodingPlanTool(item.name) && !isOrchestrationTool(item.name)"
```

于是三种情况都成了死交互：

| 编排状态 | 卡片 | 点箭头 |
|---|---|---|
| 在途（`__blocking_task__`） | 不渲染（D-4，正确） | 箭头转，**什么都不出** |
| 失败 | 不渲染（D-4，正确） | 箭头转，**什么都不出** |
| 完成 | 渲染 | 箭头转，无新内容 |

在途 / 失败两格尤其糟：用户看到一条「方案编排调研进行中」的 pill，点开想看看发生了什么，得到一片空白 —— 这不是 D-4 要的「不预建进度 UI」，而是把**既有的通用排障面板**一起关掉了。`create_coding_plan` 用同样写法没暴露，是因为它 `done` 时必然有卡片顶上。

**具体修复**（把抑制条件与「卡片是否真的渲染了」绑定，在途 / 失败自动恢复既有 `StructuredJsonView` 面板）：

```diff
-<div v-if="expandedTools.has(item.id) && !isCodingPlanTool(item.name) && !isOrchestrationTool(item.name)" class="tool-detail">
+<div v-if="expandedTools.has(item.id) && !isCodingPlanTool(item.name) && !(isOrchestrationTool(item.name) && orchestratedPlanData)" class="tool-detail">
```

这不违反「不回显后端自由文本」：`StructuredJsonView` 是所有工具共用的原始排障面板，与卡片正文的渲染纪律是两回事。

---

### 维度 3 · Color — 4/4（PASS）

**零新色板这条硬约束完全守住。** 对全 diff 抽取新增颜色类，结果只有三个值：

```
bg-amber-500/5     border-amber-500/30     text-amber-500
```

三者均为 §Color 表预声明、且 `CommitConfirmCard.vue:100-105` 已在使用的告警条配色 —— 不是新引入的色板项。横幅（`TechPlanCard.vue:608`）与弹层内风险块（`:978`）用**同一组值**，双侧口径一致。

**DESIGN.md 三条禁令逐条复核：**

- ✅ **不给编排产出卡换配色**：`OrchestratedPlanCard` 用 `.card`，无自定义底色，与 `TechPlanCard` 同族同色，仅靠 `workflow` 图标 + `success` 徽标区分语义。
- ✅ **新增 Badge 不用 `:class` 追加颜色**：草稿徽标 `<Badge variant="warning" class="ml-auto">`、编排徽标 `<Badge variant="success" class="ml-auto">` —— `class` 只承载 `ml-auto` 布局，无任何颜色类。契约 §Color 点名的既有违规（`:583` 状态徽标的 `:class="[badgeClass]"`）**未被复制**，也未被顺手重构（符合 §Unresolved #3 的边界裁定）。
- ✅ **不用 shadcn `<Card>`**：两处都是 `.card` CSS 类。

`variant="warning"` / `variant="success"` 在 `ui/badge/index.ts:18-19` 均已存在（`amber-500/10` / `emerald-500/10`），零新增 variant。

确认按钮未染 destructive（`TechPlanCard.vue:991`，`AlertDialogAction` 走 `buttonVariants()` 默认）—— 与 §C.2「风险语义由 amber 风险块 + 必勾 Checkbox 承担，染红会稀释 destructive 信号」的裁定一致。

---

### 维度 4 · Typography — 4/4（PASS）

对全 diff 抽取新增字号 / 字重类，全集为：

```
text-sm   text-xs   font-medium   font-semibold
```

即 §Typography 表的 4 个 Role（Card title / Body / Label / Caption）所需的全部值，**未新增任何字号或字重**。逐条对位：

| Role | 契约 | 落点 |
|---|---|---|
| Card title | `text-sm` + `font-semibold` | `OrchestratedPlanCard.vue:111` ✅ |
| Body（横幅主句 / 弹层正文） | `text-sm` + `font-medium` | `TechPlanCard.vue:615` ✅ |
| Caption（横幅次行 / 说明句 / 占位） | `text-xs` | `TechPlanCard.vue:618`、`:631`、`OrchestratedPlanCard.vue:118`、`:130` ✅ |

新增标记中**零 arbitrary 字号**（`rg "text-\[...\]"` 在新增行上无命中）；既有的 `text-[11px]` / `text-[10px]` 是 diff 之外的存量行，未被扩散。

---

### 维度 5 · Spacing — 4/4（PASS）

新增标记的间距类全部落在 §Spacing Scale 与其显式例外内，**未引入任何新值**，且**零 arbitrary 间距**（`rg "\[[0-9]+(px|rem)\]"` 在新增行上无命中）：

| Token | 值 | 新增落点 |
|---|---|---|
| xs `gap-1` / `space-y-1` / `pt-1` | 4px | 横幅内文案组 `TechPlanCard.vue:614`、操作区 `OrchestratedPlanCard.vue:123` |
| sm `gap-2` / `mr-2` | 8px | 横幅图标间距 `:612`、弹层勾选项 `:980`、loading 图标 `OrchestratedPlanCard.vue:143` |
| md `p-3` / `px-4` / `py-3` | 12px / 16px | 横幅内边距 `:608`、风险块 `:978`、卡片头部与正文 `OrchestratedPlanCard.vue:109`、`:117` |
| lg `pb-4` | 16px | 操作区 `OrchestratedPlanCard.vue:123` |
| 例外（既有半步值） | `mt-0.5`(2px)、`mr-1`(4px) | 告警图标基线微调 `:613`、`:981`；CTA 图标 `OrchestratedPlanCard.vue:147` |

横幅 DOM 逐字沿用了 `CommitConfirmCard.vue:100-113` 的形状（`p-3 rounded-lg border` → `flex items-start gap-2` → `shrink-0 mt-0.5` 图标 → `space-y-1 min-w-0` 文案组），间距体系与既有告警条完全同构。

---

### 维度 6 · Experience Design — 3/4（FLAG）

**契约达成部分（覆盖面确实厚）：**

- **加载态**：`projecting` → 按钮 `disabled` + `loader-2 animate-spin` + 文案切换（`OrchestratedPlanCard.vue:135-150`）。
- **错误态**：投影失败 `catch` → 常量 toast → `finally` 复位 `projecting`，按钮回 idle 可重试（`:96-102`）。
- **空态**：空正文渲染 `（暂无方案正文）` 占位而非空 `prose` 块（`TechPlanCard.vue:631-633`）；`watchEffect`（`:476-483`）在正文清空时同步清 `renderedPlan`，避免上一份正文残留 —— 契约没要求，实现主动补上了。
- **幂等中性呈现**：`created=false` 走 `toastSuccess` 而非 error 通道（`:94`），卡片表现与首次一致。
- **不留死按钮**：投影后按钮**替换为**说明行而非保留可重复点击的按钮（`:128-134`）。
- **弹层状态纪律**：`acknowledged` 为组件本地 `ref`，每次打开重置 `false`（`:326`）；`handleUnresearchedConfirm` 二次校验（`:339`）确保 `true` 只可能来自勾选；`onUnresearchedDialogOpenChange`（`:344-354`）用一次微任务防止内置关闭把用户确认吞成取消，且 `openUnresearchedDialog`（`:323`）会把上一次未结算的 promise 按「取消」结算防悬挂 —— 这三处都超出契约要求，是扎实的实现。
- **`acknowledge_unresearched` 不变量**：`ensureUnresearchedAcknowledged`（`:365-370`）是前端**唯一**产生点；编排方案走早退分支 ⇒ 字段**不发送**而非发 `false`；重试路径（`:428-430`）显式用三元避免把 `undefined` 当第三参传入。三条路径（创建态 / 追加态 / 单仓重试）全覆盖，`handleConfirm` legacy 路径按 §Unresolved #2 明确不加，注释写明了理由。
- **不串态守卫**：`codingPlanRuntime`（`:116-123`）把 `plan_id` 守卫**下沉到 runtime 入口**，比契约要求的「每个消费点各写一遍」更好 —— 注释里记录了原写法漏掉 `sessions` 那一支导致的真实缺陷。
- **焦点陷阱**：由 reka-ui `AlertDialog` 提供（`ui/alert-dialog/`，既有封装）。

**扣分项 — HI-01（high，真实用户可见 · 限读屏用户）**

```
web/src/components/chat/TechPlanCard.vue:980-983
```

```vue
<label class="flex items-start gap-2 text-sm">
  <Checkbox v-model="acknowledged" class="mt-0.5 shrink-0" data-test="ack-checkbox" />
  <span>我已了解风险，仍要用该草稿送编码</span>
</label>
```

计划里记录的可访问性保障是「checkbox 用 `<label>` 包裹使点击文字也能勾选」。核对实际渲染产物（reka-ui 2.9.10，`dist/Checkbox/CheckboxRoot.js`）后，这个保障**只兑现了一半**：

- `CheckboxRoot` 的 `as` 默认值是 `"button"` ⇒ 渲染出的是 `<button type="button" role="checkbox">`，**不是** `<input>`；
- 隐藏的 `VisuallyHiddenInput` 只在 `isFormControl && props.name` 时渲染 —— 此处未传 `name`、也不在 `<form>` 内 ⇒ **不存在**；
- `aria-label` 的取值是 `$attrs['aria-label'] || ariaLabel.value`，而 `ariaLabel` 的实现是 `props.id && currentElement ? document.querySelector('[for="'+id+'"]')?.innerText : undefined` —— **此处既没传 `id`，`<label>` 也没有 `for`** ⇒ `aria-label` 为 `undefined`；
- 按钮自身的内容只有 `CheckboxIndicator`（勾选时才出现的一个 `Check` 图标）⇒ 无文本可作为 name from content。

按 HTML-AAM，`<button>` 的可访问名称来源是 aria-labelledby → aria-label → **子树内容** → title，`<label>` 关联**不是** `<button>` 的命名来源（label 命名只适用于 input / select / textarea / meter / progress / output）。⇒ **这个 checkbox 对屏幕阅读器是一个无名控件**：只播报「复选框 未勾选」，用户听不到自己正在确认什么，而「仍要送编码」按钮又恰好被它锁死（`:993`）。整个 RELY-01 的人工签名语义对读屏用户塌掉了。

点击文字能否勾选是**次要**问题：`<button>` 属于 labelable element，规范上 label 的激活行为会向它派发合成 click，主流浏览器基本支持，所以这一半大概率是成立的 —— 但没有测试能证明，因为 `TechPlanCard.spec.ts:145-157` 把 `Checkbox` **stub 成了原生 `<input type="checkbox">`**，而原生 input 恰好是 label 关联最可靠的那种元素。测试因此对这个缺陷完全无感（126 用例全绿）。

**具体修复**（零新组件、零新样式，且能同时坐实命名与点击转发 —— reka-ui 内建了 `[for=id]` → `aria-label` 的推导，正是为这个写法准备的）：

```diff
-<label class="flex items-start gap-2 text-sm">
-  <Checkbox v-model="acknowledged" class="mt-0.5 shrink-0" data-test="ack-checkbox" />
+<label for="ack-unresearched" class="flex items-start gap-2 text-sm">
+  <Checkbox id="ack-unresearched" v-model="acknowledged" class="mt-0.5 shrink-0" data-test="ack-checkbox" />
   <span>我已了解风险，仍要用该草稿送编码</span>
 </label>
```

> 顺带确认一处**实现优于契约**的偏离：UI-SPEC §C.2 写的是 `v-model:checked="acknowledged"`，实现用的是 `v-model`。reka-ui 2.9.10 的 `CheckboxRoot` 已改用 `modelValue` / `update:modelValue`（`emits: ["update:modelValue"]`），**实现是对的、契约是过期的**。仓内 `EntityDetailToolbar.vue:39` 仍在用 `v-model:checked`，那处是存量失效绑定，超出本 phase 边界，仅备录。

**扣分项 — MN-02（medium，真实用户可见 · 低概率）**

```
web/src/components/chat/ChatMessageBubble.vue:791   ← const orchestratedPlanData = ... find(...)
web/src/components/chat/ChatMessageBubble.vue:1253  ← v-if 逐 item 判定
```

`orchestratedPlanData` 用 `toolCalls.value.find(tc => isOrchestrationTool(tc.name))` 取**首个**编排工具，但 `:1253` 的 `v-if` 是**逐 item** 判定的。同一条 assistant 消息里若出现两个编排工具（`start_plan_research` + `start_feature_solution`，或同工具两次调用），会渲染**两张外观完全相同的卡片**，且第二张携带的是第一个工具的 `artifact_version_id` —— 点「进入编码」投影出的是**另一份方案**。这与本 phase 在 `plan_id` 守卫上反复强调的「不串态」是同一类缺陷，只是换了个轴。

该写法是从既有 `codingPlanData` 照抄的（同样的 `find` + 逐 item 渲染），属于沿袭而非新造；编排工具是长耗时阻塞调用，单条消息里出现两个的概率不高 —— 故记 medium 而非 high。

**具体修复**：把 `orchestratedPlanData` 从 computed 改为按当前 item 解析的函数（如 `orchestratedDataFor(item)`），`v-if` 与 `:artifact-version-id` 都取它的返回值。

**扣分项 — LO-01（low，polish）· 折叠卡展开时 `role="alert"` 会打断读屏**

```
web/src/components/chat/TechPlanCard.vue:606-610
```

§B.2 给横幅定 `role="alert"` 且不加 `aria-live`，理由是「横幅随卡片首次渲染出现（非动态插入）」。该前提对**初始展开**的卡片成立，但 `computedInitialCollapsed()`（`:447-451`）会让 `status !== 'draft'` 的卡片默认折叠 —— 用户手动展开时，横幅是**动态插入**的，而 `role="alert"` 隐含 `aria-live="assertive"`，会抢断当前播报。反复折叠 / 展开就会反复抢断，正是 §B.2 想避免的效果。

影响很小（展开是用户主动操作，此时播报风险提示反而合理），列为 polish。若要收严：把 `role="alert"` 换成 `role="note"`，风险语义由 amber 视觉 + 徽标 + 弹层承担已经足够。

**扣分项 — LO-02（low，polish）· 徽标区嵌在 `<button>` 内**

头部是 `<button>`（`:566-594`），内含两个 `Badge`（渲染为 `<div>`）。`<button>` 的内容模型是 phrasing content，`<div>` 属 flow content，严格说是无效嵌套。**存量形状**（既有状态徽标已如此），本 phase 只是多挂了一个草稿徽标，未加重结构问题；不建议在本 phase 顺手重构（会牵动既有断言，与 §Unresolved #3 同理）。仅备录。

---

## RELY-01 存量标注的观感校准（专项结论）

**结论：无需调低视觉权重，不建议改动。**

迁移 0033 把 `provenance` 默认为 `"draft"` ⇒ 全部历史方案渲染草稿横幅与徽标，这是 RELY-01 的预期结果（`109-UI-SPEC.md` Backstop #2 已如实记录）。就「会不会被误读成系统故障」这个具体问题，逐项核对后判断是**不会**：

| 可能引发误读的因素 | 实际实现 |
|---|---|
| 配色 | amber 而非 destructive 红；`bg-amber-500/5` 是极浅底，非实心告警块 |
| 字重 | 主句 `text-sm font-medium text-foreground` —— 与正常正文强调同级，未加粗、未用告警色 |
| 措辞 | 「本方案未经代码调研」是**陈述句**，不含「错误」「失败」「异常」等故障词；次行是解释性说明而非行动告警 |
| 形状熟悉度 | 逐字复用 `CommitConfirmCard` / `ContextExceededCard` / `ReconcilePanel` 三处已在用的告警条范式 —— 用户对这个形状的既有心智是「注意事项」，不是「出错了」 |
| 出现密度 | `computedInitialCollapsed()` 让 `status !== 'draft'` 的卡片默认折叠 ⇒ 历史会话回滚时，已完成 / 运行中的方案卡**只露一个徽标**，横幅不出现，不会形成「满屏琥珀」 |

需要如实指出的一点：历史卡片中 `status === 'draft'` 的那批**默认展开**，横幅会直接可见。这批恰恰是「建了但从未送编码」的方案 —— 对它们把「未经调研」讲全，正是 RELY-01 想要的效果，不构成误报。

**若 UAT 仍判为偏重**，给一个不动色板、不动文案的收敛选项（**非本次建议，仅备选**）：对 `status` 已进入终态（`completed` / `failed`）的卡片只保留头部徽标、不渲染横幅 —— 这类方案的编码早已发生，横幅的决策价值已经过期，徽标足以留档。改动量是横幅 `v-if` 上加一个条件。

---

## Registry Safety

| 检查项 | 结果 |
|---|---|
| `web/components.json` | 存在，但本 phase **未执行** `shadcn init` / `shadcn add` |
| 第三方 registry 拉块 | **无** —— §Registry Safety 声明 not applicable，diff 复核成立 |
| `web/pnpm-lock.yaml` | **未改动**（`git diff --name-only` 无命中） |
| `web/package.json` | **未改动** |
| 新增 `ui/` 组件 | **无** —— 仅复用既有 `badge` / `alert-dialog` / `checkbox` / `button` / `input` / `dialog` |
| `web/src/components.d.ts` | 仅 +1 行（`OrchestratedPlanCard` 自动注册），无第三方来源 |

**Registry 审计：0 个第三方块，无需 `shadcn view` 审源门，零 flag。**

---

## 契约符合性速查（UI-SPEC §UI Considerations · Covered 20 条）

| # | 契约要点 | 结果 |
|---|---|---|
| 1 | 新建 `OrchestratedPlanCard`，最小可操作面 | ✅ `OrchestratedPlanCard.vue:106-152` |
| 2 | 渲染三条件同时成立 | ✅ `ChatMessageBubble.vue:791-814`（`status==='done'` + 非空 `artifact_version_id`）+ `:1253`（`item.status==='done'`） |
| 3 | 两个编排工具同判定同卡片 | ✅ `isOrchestrationTool`（`:775-778`） |
| 4 | `UNGROUPABLE_TOOLS` 加两工具 | ✅ `:500-512`，且注释写明静默失守点 |
| 5 | 投影 + 就地交棒（不等 runtime 刷新） | ✅ `OrchestratedPlanCard.vue:84-94`、`:155-168` |
| 6 | 幂等中性 toast | ✅ `:94` |
| 7 | 工具展示三处登记 | ✅ `useToolDisplay.ts:51-52`、`:85-86`、`:389-401` |
| 8 | 允许清单判定（`!== 'orchestrated'`） | ✅ `TechPlanCard.vue:291`，纯字面比较不触碰 `undefined` 属性 |
| 9 | 草稿横幅位于正文之前 | ✅ `:606-623` 在 `:634` 的 `prose` 之前 |
| 10 | 徽标头部常驻 + 布局共存规则 | ✅ `:577-593` |
| 11 | 局部 `AlertDialog` + 必勾 Checkbox | ✅ `:967-1001`，未动 `GlobalConfirmDialog` |
| 12 | `acknowledge_unresearched` 仅由勾选产生，三路径覆盖 | ✅ `:365-370`、`:172`、`:422` |
| 13 | 编排方案零摩擦（字段不发送） | ✅ `:366-367` 早退 + `:428-430` 三元 |
| 14 | 按 `code` 分支，不匹配 `detail` | ✅ `:378-383` |
| 16 | `techPlan` 多级优先 + `plan_id` 守卫 + 空正文占位 | ✅ `:116-123`、`:247-256`、`:631-633` |
| 17 | 契约扩字段（`provenance` 含 `\| string`） | ✅ `:74`（`string \| null`，未收窄成枚举） |
| 19 | `change_type` 不做前端兼容映射 | ✅ `:661` 原样渲染，漂移可见 |
| 20 | 视觉零漂移 | ✅ 见维度 3 / 4 / 5，零新色板 / 字号 / 字重 / 间距 / 组件 / 依赖 |
| Backstop 8 | 新增标记无 `v-html` | ✅ 全组件仅 `:634` 一处既有 markdown 渲染路径 |
| Backstop 7 | `provenance` 原始取值不上屏 | ✅ 4 处引用均不进渲染路径 |

未在本审计覆盖：#15、#18（后端 `_compose_plan_markdown` 与序列化器，非前端面）。

---

## 建议人工 UAT（浏览器下复核，不计分）

1. 读屏（VoiceOver / NVDA）走一遍草稿送编码弹层，确认 HI-01 修复后能播报必勾项全文。
2. 点击弹层内文案（非勾选框本体）确认能切换勾选 —— 现有测试因 stub 了 `Checkbox` 无法覆盖。
3. 亮 / 暗主题下 `bg-amber-500/5` + `text-muted-foreground` 次行的对比度。
4. 历史长会话滚动，实地确认草稿横幅密度（对应上文观感校准结论）。

---

## Files Audited

| 文件 | 性质 | 审计深度 |
|---|---|---|
| `web/src/components/chat/OrchestratedPlanCard.vue` | 新建（170 行） | 全文件 |
| `web/src/components/chat/TechPlanCard.vue` | 改（+353） | 全文件（1014 行） |
| `web/src/components/chat/ChatMessageBubble.vue` | 改（+114） | diff + 渲染分支上下文 |
| `web/src/composables/useToolDisplay.ts` | 改（+23） | diff |
| `web/src/components/ui/checkbox/Checkbox.vue` | 未改（依赖） | 全文件 + reka-ui 2.9.10 `CheckboxRoot` 产物 |
| `web/src/components/ui/badge/index.ts` | 未改（依赖） | variant 表 |
| `web/src/components/ui/alert-dialog/AlertDialogAction.vue` | 未改（依赖） | 全文件 |
| `web/src/components/chat/__tests__/TechPlanCard.spec.ts` | 改（+732） | stub 定义 + 草稿相关用例 |
| `web/src/components/chat/__tests__/OrchestratedPlanCard.spec.ts` | 新建（374） | 实跑 |
| `web/src/components/chat/__tests__/chatMessageBubble.parts.spec.ts` | 改（+301） | 实跑 |
| `web/src/composables/__tests__/useToolDisplay.spec.ts` | 改（+63） | 实跑 |
| `web/src/{api/chat.ts,stores/chat.ts,types/chat.ts}` | 改（支撑面） | 仅核对未引入视觉面 |
