---
phase: 110
slug: 110-process-observability
audited: 2026-07-31T17:08:00+08:00
status: pass-with-findings
baseline: 110-UI-SPEC.md
diff_base: f3292256
screenshots: not-captured
advisory: true
scores:
  copywriting: 4
  visuals: 3
  color: 4
  typography: 4
  spacing: 4
  experience_design: 2
  total: 21
  max: 24
findings:
  high: 1
  medium: 2
  low: 3
---

# Phase 110 — UI Review（过程可观测 · 6 维度代码级审计）

**Audited:** 2026-07-31
**Baseline:** `110-UI-SPEC.md`（重点 §A 阶段时间线、§B 失败呈现、§C 容器日志、§E.2/E.3 直播态与中断态）
**Diff base:** `f3292256..HEAD`（`git diff f3292256 HEAD -- web/`，17 文件 / +4150 −26）
**Screenshots:** 未捕获（3000 / 10240 / 8080 无服务；5173 是另一个无关项目 `onion-practice`）⇒ 纯代码级审计
**Scope:** `OrchestrationStageTimeline.vue`（新建）、`PlanResearchLogGroup.vue`（新建）、`SubStepTimeline.vue`（泛化）、`useOrchestrationTimeline.ts`（新建）、`ChatMessageBubble.vue`、`stores/chat.ts`
**测试基线:** 6 个 spec 文件 / 223 用例全绿（`vitest run`，本次实跑）
**行为核验:** 用 `tsx` 直接跑 `buildOrchestrationTimeline` 三个场景（直播前半程 / 单条不可识别事件 / 快照到达），下文 HI-01 与 MN-01 的结论是**实测输出**，不是代码推读
**性质：** 顾问性 / 非阻塞（advisory）。真实浏览器下的焦点顺序、读屏播报、对比度需 UAT 复核。

---

## 维度评分总览

| # | 维度 | 判定 | 分 | 关键发现 |
|---|------|------|----|---------|
| 1 | Copywriting | PASS | 4/4 | §Copywriting Contract 时间线 30 条 + 日志组 4 条**逐字落地**；失败闭集 6 值 + 兜底，原始值零回显；禁渲染的 payload 自由文本一个都没进渲染路径 |
| 2 | Visuals | FLAG | 3/4 | 卡骨架逐字沿用 `OrchestratedPlanCard:109`，终态收敛为一行；但**脉冲动画与真实实时性正好相反**（MN-01） |
| 3 | Color | PASS | 4/4 | **零新色板**：4 个状态点色全部是 `f3292256` 时的存量值；`skipped`/`unknown` 用同 token + 边框（形状差异） |
| 4 | Typography | PASS | 4/4 | **零新字号字重**：仅 `text-sm` / `text-[11px]` / `text-[10px]` / `font-semibold` |
| 5 | Spacing | PASS | 4/4 | **零新间距值**：全部落在 §Spacing Scale 与其显式例外内 |
| 6 | Experience Design | FLAG | 2/4 | 六态 / 幂等 / 中断 / 刷新补齐 / 分桶防串台全部到位；但**前半程失败永远不翻红**（HI-01），命中的正是本 phase 的头号需求 OBS-03 |

**总分：21 / 24** — 视觉零漂移这条硬约束**完全守住**（色板 / 字号 / 字重 / 间距 / 组件原语 / npm 依赖六项全部零新增）。扣分集中在一个共同根因：**`phase` 与 `pulse` 都只由运行时快照决定，而编排前半程根本没有快照。**

---

## 优先修复（Top 3）

1. **HI-01 · 编排在前半程失败时，时间线永远停在「正在生成技术方案」** — `useOrchestrationTimeline.ts:439-441` / `:79-92`
   用户影响：**真实用户可见问题**。这是本 phase 的头号交付物 OBS-03（「失败停在哪一步一目了然」）在最常见的失败路径上失效 —— 用户看到的是一条永久转着的进度条，而编排早已挂了。刷新页面才会自愈。
   修复：在折叠逻辑里认 `fail` / `process.session.failed` 两个事件名，命中即 `phase='failed'`、把指针那一步标红（**摘要行留空**，原因文案照旧等快照补齐 —— §A.4 本就允许缺数据时整行不渲染）。

2. **MN-01 · 真·直播的前半程不脉冲，2s 轮询的后半程才脉冲** — `useOrchestrationTimeline.ts:470-471`
   用户影响：**真实用户可见问题**。活跃度信号与真实实时性**正好相反**：SSE 逐事件推进的拆分→澄清五步是静止实心点，改由 2s 快照驱动的并行调研→融合反而在闪。
   修复：`shouldPulse` 的条件里补一条「无快照但指针已被事件推进过」的分支。

3. **MN-02 · 调研日志组的折叠按钮把可见文案盖掉了** — `PlanResearchLogGroup.vue:98-108`
   用户影响：**真实用户可见问题（限读屏用户）**。按钮里写着「方案调研 · 3 个仓库」，但 `aria-label` 把可访问名称覆盖成「展开方案调研日志」—— 读屏用户永远听不到有几个仓库，且违反 WCAG 2.5.3 Label in Name（Level A，可访问名称必须包含可见文案）。
   修复：**删掉 `aria-label`**（可见文案 + `aria-expanded` 已经把名称和状态讲全了），补 `aria-controls` 指向日志区。

---

## 详细发现

### 维度 1 · Copywriting — 4/4（PASS）

§Copywriting Contract 两张表逐条比对，**34 条文案全部逐字一致**：

| 契约位置 | 落点 | 结果 |
|---|---|---|
| 卡头标题三态 / 步数计数 | `useOrchestrationTimeline.ts:99-103` | 逐字 ✅ |
| live region 三句 | `:109-111` | 逐字 ✅ |
| 七套阶段摘要模板 + 澄清子表 5 条 | `:116-130` | 逐字 ✅ |
| 阶段标签 7 个（含新增的「功能点分类」） | `:45-53` | 逐字 ✅ |
| 状态文本 6 个 | `SubStepTimeline.vue:27-34` | 逐字 ✅ |
| 失败原因闭集 6 值 | `useOrchestrationTimeline.ts:61-68` | 逐字 ✅ |
| 折叠 / 容器 `aria-label` | `OrchestrationStageTimeline.vue:41-44`、`:129` | 逐字 ✅ |
| 组标题 / 组折叠 `aria-label` / 仓库名兜底 | `PlanResearchLogGroup.vue:41-46` | 逐字 ✅ |

**「后端自由文本不上屏」纪律守住**，逐项复核通过：

- §A.4 点名禁渲染的六类字段（`clarification.asked.question`、`repo.research.completed.summary` / `candidate_files` / `api_contracts_exposed`、`repo.research.failed.error`、`validation.failed.reasons`、`repo.routing` 的 `stage0` / `stage1` / `weight_config` / `repo_meta`）在 `useOrchestrationTimeline.ts` 全文**零读取** —— 折叠逻辑只碰 `candidates.length` / `hits` / `summary.{new,modify,unclear}` / `round_no` / `degraded` 与三个去重自然键；
- 失败原因走 `FAIL_REASON_LABELS[...] ?? COPY.unknownReason`（`:459`），未命中回退闭集常量，**绝不回显原始 `reason_code`**；
- 仓库名三级兜底（`repository_name` → `repoNames[id]` → `未知仓库`，`PlanResearchLogGroup.vue:54-62`），**任何路径不回显裸 UUID**；
- 卡内步数与空态明确**不覆写** `DeepAnalysisCard` 既有文案，与契约一致。

一处良性重复（不计缺陷）：`COPY.unknownRepo` 在 composable（`:112`）与 `PlanResearchLogGroup`（`:45`）各写了一份。composable 的 `resolveRepoName` 只有两级解析、日志组需要三级，确实不能直接复用；但常量串本身可以从 composable import，避免将来两处漂移。**polish**。

---

### 维度 2 · Visuals — 3/4（FLAG）

**契约达成部分**：`OrchestrationStageTimeline.vue:125-163` 与 §A.6 结构图**逐行对得上** —— `.card mt-2 animate-fade-in` + `role="group"` → 头部 `px-4 py-3 border-b border-border/50 flex items-center gap-2` + `icon-[lucide--workflow] text-primary` + `text-sm font-semibold` + `text-[10px] ml-auto` 步数 + 折叠 `button` → 单一 `sr-only` live region → 正文 `px-4 pb-3 pt-1` 包 `<SubStepTimeline :interactive="false" />`。步数计数用**纯文本**而非 Badge，与契约「Badge 在 11px 行里过重」的裁定一致。

图标全部为仓内既有：`workflow` / `chevron-right` / `search-code`。契约点名禁用的 `folder-search` / `route` / `merge` / `microscope` 一个都没出现。

`classify` 的可选规则落地正确且顺序对（`useOrchestrationTimeline.ts:478-521`）：**序号在完整 7 键上算，可见性过滤放到最后一步**（`filter(step => step.id !== 'classify')`）—— 实测确认非 feature_list 流程下该行**在 DOM 里根本不存在**，而不是渲染一个永远跳过的灰步；且后续步骤不会整体错位一格。

终态收敛（§A.6）实现干净：`watch` 把 `sessionId` 与 `phase` 合成一个源（`OrchestrationStageTimeline.vue:103-116`），`autoCollapsed` 一次性 flag 保证用户手动展开后不再被抢走，`failed` 不自动折叠。

**扣分项 — MN-01（medium，真实用户可见）· 脉冲动画与真实实时性正好相反**

```
web/src/composables/useOrchestrationTimeline.ts:470-471   ← shouldPulse
web/src/stores/chat.ts:2403-2408                          ← 轮询只在 waiting 后启动
```

```ts
const shouldPulse = input?.runtimeActive === true
  && (status === 'running' || status === 'waiting_clarification' || status === 'waiting_event')
```

`status` 只来自 `snapshot?.status`（`:439`）。而运行时轮询是在 graph 进入 `waiting` / `waiting_clarification` **之后**才启动的（`chat.ts:2403-2408`）—— 编排前半程（拆分 → 路由 → 召回 → 分类 → 澄清）SSE 流正开着、graph 还没挂起，**这段时间一份快照都不会到达**。

实测（`buildOrchestrationTimeline`，snapshot=null + 两条真实事件）：

```
拆分 : completed
路由 : running   pulse=false   命中 2 个候选仓     ← 正在跑，但不闪
召回 : pending
```

对比快照到达后（后半程，2s 轮询驱动）：

```
并行调研 : running   pulse=true                     ← 每 2 秒才更新一次，反而在闪
```

于是「哪一步在动」这个信号被**反着**给了：真正逐事件流式推进的前半程是静止的实心点，靠 2s 轮询挪动的后半程才有脉冲。用户在最有实时感的那段时间看到的是一条像卡住的时间线。

不算 high 的理由：`pulse:false` 只去掉 `animate-pulse`、色值仍是 `bg-primary`（`SubStepTimeline.vue:53-56`），与 pending 的 `bg-muted-foreground/50` 仍可区分，状态本身没有传达错误 —— 丢的是活跃度信号。

契约层面这是**契约自身的盲区而非实现擅自偏离**：§E.2 原文把脉冲挂在 `orchestration.status` 上，前提是快照恒存在。

**具体修复**（无快照但事件已把指针推进过 ⇒ 视为在跑）：

```diff
-const shouldPulse = input?.runtimeActive === true
-  && (status === 'running' || status === 'waiting_clarification' || status === 'waiting_event')
+const liveByEvents = status === null && folded.lastTransitionStage !== null
+const shouldPulse = input?.runtimeActive === true
+  && (liveByEvents || status === 'running' || status === 'waiting_clarification' || status === 'waiting_event')
```

---

### 维度 3 · Color — 4/4（PASS）

**零新色板这条硬约束完全守住。** 对全 diff 抽取新增颜色类，全集只有四个值：

```
bg-emerald-400    bg-red-400    text-red-400    text-red-400/70
```

四者**全部**是 `f3292256` 时 `SubStepTimeline.vue` 已有的取值（`git show f3292256:...` 逐字核对：`stepStatusColor` 的 4 键 map 与失败摘要行的 `text-red-400/70` 一字未改）—— 属于「重排后在 diff 里显示为新增行」，不是新引入的色板项。**十六进制 / `rgb()` 硬编码色零命中。**

`skipped` / `unknown` 走 `bg-transparent border border-muted-foreground/50`（`SubStepTimeline.vue:50-51`）—— 与 pending 同一个 token，靠**空心 vs 实心的形状差异**区分，§Color 的裁定逐字落地，同时满足「不靠颜色单独传达状态」。

**DESIGN.md 三条禁令逐条复核：**

- ✅ **不给时间线卡换配色**：`.card` 无自定义底色，与 `OrchestratedPlanCard` 同族同色，仅靠标题文案区分三态。
- ✅ **Badge 不用 `:class` 追加颜色**：`SubStepTimeline.vue:138` 是 `<Badge :variant="step.badge.variant" class="shrink-0 mt-0.5">`，`class` 只承载布局。
- ✅ **不用 shadcn `<Card>`**：走 `.card` CSS 类。

§D.2 的边界守得很干净：`routingDegraded` 严格 `=== true`（`useOrchestrationTimeline.ts:475`、`:514`），**不按 `router_version` 或候选内容自行推断**，字段缺失视为 `false`；角标只有「降级」两个字，**无解释句、无 Tooltip**。裁决 D-3 落地成立 —— 时间线不是第二个降级渲染者。

> 如实记录（非本 phase 缺陷）：`RoutingDecisionPanel` 在 SPA 里仍无挂载点（`110-UI-SPEC.md` §D.3 已实读确认，属 107 收尾遗漏）。⇒ 落地后这个「降级」角标事实上是编排链**唯一**的降级信号，用户看得到「这一步降级了」但看不到「降级意味着什么」。已按指示不计入本 phase findings。

---

### 维度 4 · Typography — 4/4（PASS）

对全 diff 抽取新增字号 / 字重类，全集为：

```
text-sm(1)   text-[11px](2)   text-[10px](2)   font-semibold(2)
```

即 §Typography 表 5 个 Role 所需的全部值，**未新增任何字号或字重**。逐条对位：

| Role | 契约 | 落点 |
|---|---|---|
| Card title | `text-sm` + `font-semibold` | `OrchestrationStageTimeline.vue:134` ✅ |
| Step label | `text-[11px]` + `leading-tight` | `SubStepTimeline.vue:122`（存量行，未改） ✅ |
| Step summary | `text-[10px]` | `SubStepTimeline.vue:130`、步数计数 `OrchestrationStageTimeline.vue:136` ✅ |
| Group label | `text-[11px]` + `font-semibold` | `PlanResearchLogGroup.vue:107` ✅ |

`text-[11px]` / `text-[10px]` 两档均为 §Typography「Exceptions（既有微字号）」显式声明的存量值。折叠头步数计数**用纯文本而非 Badge**，与契约一致。

---

### 维度 5 · Spacing — 4/4（PASS）

新增标记的间距类全集，**未引入任何新值**：

```
gap-2(7)  mt-2(6)  px-4(3)  px-1(2)  py-3(2)  space-y-2(1)
pb-3(1)   pb-2(1)  pt-1(1)  pl-1(1)  mt-0.5(1)  py-0.5(1)  ml-auto(1)
```

逐条落在 §Spacing Scale 的 4 个 token（xs 4px / sm 8px / md 12px / lg 16px）与其显式声明的 5 个既有半步例外（`px-1 py-0.5` / `pl-1` / `w-2.5 h-2.5` / `left-[7px] top-4` / `mt-0.5`）之内。

**零新 arbitrary 间距**：`rg '\[[0-9]+(px|rem)\]'` 在新增行上只命中 `[10px]` / `[11px]` 两个**字号**（上表已声明）；`left-[7px]` 与 `h-[calc(100%)]` 是 `f3292256` 时就存在的存量行，未被扩散。

时间线卡头部 `px-4 py-3 border-b border-border/50 flex items-center gap-2` 与 `OrchestratedPlanCard:109` **逐字相同**，正文 `px-4 pb-3 pt-1` 与契约结构图一致 —— 「在途 → 完成」在版面上确实是同一张卡在变。

---

### 维度 6 · Experience Design — 2/4（FLAG）

**契约达成部分（覆盖面确实厚，这些都值得记账）：**

- **六态状态机**完整（`useOrchestrationTimeline.ts:478-518`），且优先级排对：`failed` > `unknown`（中断）> `skipped`（澄清穿过且无 `clarification.*` 事件）> `completed` > `running` > `pending`。
- **阶段指针权威顺序**正确（`:445-451`）：快照 `current_stage` 优先于折叠事件流，冲突时以快照为准且**不打 warn**；一条证据都没有时全 pending，不假装「拆分正在跑」。
- **回退转移**被正确处理（`TRANSITION_TO_STAGE` 取「最后一条可识别转移」而非「见过的最大序号」，`:70-92`）—— 融合校验不过退回 clarify 时时间线会跟着退，不会卡在 merge 上撒谎。
- **计数幂等**（`:197-200` 自然键 + `chat.ts:110-142` 去重键 `event|ts|自然键`）：SSE 与快照必然重复投递，实测重复不翻倍。
- **单仓调研失败 ≠ 编排失败**（`:361-370`）：只进摘要的 ` · {k} 个失败`，**不把该步标红**，B.4 裁定落地。
- **调研分母取 `research.started` 的去重 repo 数**而非路由候选数（`:364`）—— light path 的仓不起容器，用候选数当分母会让进度永远到不了满。
- **中断态**（`:467`）：`waiting_clarification` + 不活跃**不算**中断，`running` / `waiting_event` 才转 `unknown` + 「进度未知，可能已中断」；`unknown` 与 `skipped` 都不用红色。
- **刷新补齐 / 直播零差异**：`applyOrchestrationRuntime` 写的是与 SSE **完全相同**的那份分桶状态（`chat.ts:984-1027`），组件不知道数据从哪条链来。`chat.ts:1005` 那条注释（`applyRuntimeSnapshot` 只在 `active===true` 时调用、而终态那一拍 `active` 恰好变 false）是实打实的坑，实现绕对了。
- **分桶防串台**：`orchestrationSessions` 按 `session_id` upsert 而非整体替换；`planResearchSessionsFor(item)` 按 `plan_session_id` 二次过滤（`ChatMessageBubble.vue:906-913`），避免第二轮编排的容器日志挂到第一条气泡上。这一层过滤只有日志组需要（时间线天然按桶自限），注释把不对等的理由写清了。
- **观测不反噬**：`buildOrchestrationTimeline` 外层 `try/catch` → 保守视图（`:425-433`），组件 `view` computed 再包一层 → 整块不渲染（`OrchestrationStageTimeline.vue:58-83`），store 的 `process_event` 分支与 `applyOrchestrationRuntime` 各包一层。四道防线，编排跑通优先于进度可见。
- **零 `v-html`**：三个组件全文零命中，全部走 `{{ }}` 插值。
- **单一 live region** 且**不含步数计数**（`:102-111` 注释写明「五个仓完成会让屏幕阅读器连播五次」）；失败摘要行只挂 `role="alert"`、**整个 `SubStepTimeline` 无 `aria-live`**（`:132`）—— 一个事实播一次。
- **`prefers-reduced-motion`** 由 `main.css:544-552` 的全局块覆盖 `animate-pulse`，新增组件未引入任何自定义动画。
- **`SubStepTimeline` 泛化确是纯加性**：与 `f3292256` 版本逐字比对，`interactive` 默认 `true`、`pulse` 缺省即旧行为、`failed` 时 `summary` 缺失回退 `output_data.error.slice(0,50)` 路径**一字未改** ⇒ `ExecutionNode` 零回归，且 391 个用例把这条锁住了。
- **`ChatMessageBubble` 的两处加固**都做对了：`lastOrchestrationToolItemId` 只用于**去重渲染位置**、卡片取数仍逐条走 `resolveOrchestratedPlanData(item.result)`（109 的载重不变量没被合并掉）；`orchestrationSessionIdFor` 的「有 result 却解析不出会话 ⇒ 宁可不渲染」是对的保守分支。

**扣分项 — HI-01（high，真实用户可见）· 前半程失败永远不翻红，时间线停在「正在生成技术方案」**

```
web/src/composables/useOrchestrationTimeline.ts:439-441   ← isFailed 只看 snapshot.status
web/src/composables/useOrchestrationTimeline.ts:79-92     ← TRANSITION_TO_STAGE 不含 fail
web/src/composables/useOrchestrationTimeline.ts:263-306   ← switch 无 fail / process.session.failed 分支
web/src/stores/chat.ts:2403-2408                          ← 轮询只在 waiting 后启动
```

```ts
const status = typeof snapshot?.status === 'string' ? snapshot.status : null
const isFailed = status === 'failed'
```

`phase` / `title` / 红步**全部**只由快照决定。折叠逻辑对 `fail` 与 `process.session.failed` 两个事件名**完全无感** —— `TRANSITION_TO_STAGE` 有意把它们排除在外（注释：「它们不推进 stage，只翻状态」），但 `switch` 里也没有为「翻状态」留分支，于是这两条事件到达后**什么都不发生**。

契约对这件事是有明确要求的（§落点 C / §B.3）：

> SSE 的失败事件只负责「**立刻把状态翻红**」，原因文案在同一次快照/下一次轮询里补齐。

「翻红」那一半没做，只留了「等快照」那一半。后果取决于快照会不会到：

| 失败位置 | 轮询是否在跑 | 结果 |
|---|---|---|
| 后半程（`research` / `merge`） | ✅ 在跑（graph 已 `waiting`） | ≤2s 后翻红，**正确** |
| **前半程**（`decompose` / `route` / `recall` / `classify` / `clarify`） | ❌ **不在跑** | 工具返回错误 → SDK 继续 → 助手写文字 → 流正常结束，`currentPhase` 从未进 `waiting` ⇒ `scheduleRuntimePoll` 不触发 ⇒ **一份快照都不会到** |

前半程失败时用户看到的是：标题「**正在生成技术方案**」、某一步是实心主色的 `running`、其后全 pending —— 一条**永久转着**的进度条，而编排早就挂了。只有刷新页面（`restoreConversationRuntime` → `applyOrchestrationRuntime`）才自愈。

这恰好命中本 phase 的头号需求 OBS-03「失败停在哪一步一目了然」，且按 §落点 D 的实读，`engine.py:94-101` 的 stage 内未捕获异常是**最常见**的失败路径 —— 它对每一个前半程 stage 都成立。契约 §A.3 反复强调的「时间线撒谎」，这是最标准的一例。

**具体修复**（只认事件名、不碰 payload，与「失败原因永不出网」纪律无冲突）：

```diff
 // foldEvents 内新增
+      case 'fail':
+      case 'process.session.failed':
+        folded.sawFailure = true
+        break
```

```diff
 // buildInner 内
-const isFailed = status === 'failed'
+const isFailed = status === 'failed' || (status === null && folded.sawFailure)
```

`failureStage` 在无快照时回退到 `pointerStage`（指针那一步就是它停下的地方），`failReason` 走既有 `?? COPY.unknownReason` 兜底 —— 或者更保守：**无快照时摘要行整行不渲染**（§A.4 本就允许缺数据时不渲染），等下一次快照把原因补上。红步 + 「方案编排失败」标题已经把「停在哪一步」讲全了。

> 建议 UAT 用一次真实的前半程失败（例如把 route stage 打断）跑通确认 —— 上表「轮询不在跑」这一格是按 `chat.ts:2403-2408` 的分支条件推的，值得一次实跑坐实。

**扣分项 — MN-02（medium，真实用户可见 · 限读屏用户）· 日志组折叠按钮盖掉了可见文案**

```
web/src/components/chat/PlanResearchLogGroup.vue:98-108
```

```vue
<button
  type="button"
  class="flex items-center gap-2 px-1 pb-2"
  :aria-expanded="collapsed ? 'false' : 'true'"
  :aria-label="collapsed ? COPY.expand : COPY.collapse"
  @click="collapsed = !collapsed"
>
  <span class="icon-[lucide--search-code] text-[11px] text-primary" />
  <span class="text-[11px] font-semibold">{{ COPY.groupTitle(cards.length) }}</span>
</button>
```

按钮**内部**已经有可见文案「方案调研 · 3 个仓库」，`aria-label` 会**覆盖**它成为可访问名称。两个后果：

1. **WCAG 2.5.3 Label in Name（Level A）不满足** —— 可访问名称（「展开方案调研日志」）不包含可见文案（「方案调研 · 3 个仓库」）。语音控制用户念屏幕上看到的字触发不了这个按钮。
2. **读屏用户永远听不到有几个仓库** —— 而「并行调研跑了几个仓」正是本组要传达的核心事实（§C.3 把「排布 = 纵向堆叠」列为「即使不读字也能看出这是两种东西」的三条差异之一，读屏用户恰恰读不到排布）。

对照写法：时间线的折叠按钮（`OrchestrationStageTimeline.vue:139-152`）只有一个图标、没有可见文案，那里的 `aria-label` 是**正确且必需**的。两处形态不同，不该套同一个写法。

顺带一处不一致：时间线的按钮有 `aria-controls`（`:144`）指向正文 id，日志组的按钮**没有**，日志区也没有 id。

**具体修复**：

```diff
 <button
   type="button"
   class="flex items-center gap-2 px-1 pb-2"
   :aria-expanded="collapsed ? 'false' : 'true'"
-  :aria-label="collapsed ? COPY.expand : COPY.collapse"
+  :aria-controls="listId"
   data-test="plan-research-log-toggle"
   @click="collapsed = !collapsed"
 >
```

（`const listId = useId()` 挂到 `div.space-y-2` 上；`COPY.expand` / `COPY.collapse` 两个串随之成为死常量，可一并删除或保留待用。若确实想保住契约文案，正确写法是把组标题**拼进**可访问名称而不是覆盖它 —— 即 `aria-label` 的值以 `COPY.groupTitle(cards.length)` 开头、再接展开/收起文案。）

**扣分项 — LO-01（low，polish）· §C.4 的「编排完成后整组默认收起」未实现**

```
web/src/components/chat/PlanResearchLogGroup.vue:48
```

`const collapsed = ref(false)` —— 恒为展开，且没有任何 watch 会在编排终态时收起它。契约 §C.4 写的是：

> **消失时机**：不消失。编排完成后日志组仍在（OBS-02 要的是"可查"而不只是"可见"），**但整组默认收起**。

于是编排完成后的版面是：时间线自动收敛成一行（做对了），紧跟着一个**完全展开**的日志组 —— 首张卡的日志区最高 22rem，把刚产出的 `OrchestratedPlanCard` 挤到屏幕外。两块新 UI 的收敛策略不一致，而契约要求它们一起让位给结果。

修复：给 `PlanResearchLogGroup` 加一个可选的 `converged?: boolean` prop（或直接读同一个 `session_id` 的桶状态），终态首次到达时一次性置 `collapsed = true` —— 与时间线的 `autoCollapsed` 一次性 flag 同款语义，用户手动展开后不再被抢走。

**扣分项 — LO-02（low，polish）· 折叠后 `aria-controls` 指向一个已被移除的节点**

```
web/src/components/chat/OrchestrationStageTimeline.vue:144 / :160
```

正文区是 `v-if="!collapsed"`，收起时该节点**从 DOM 里消失**，而按钮上的 `aria-controls="{bodyId}"` 仍然指着它。`:48` 的注释写的是「`aria-controls` 必须指向真实存在的节点」—— 恰好是收起态下不成立的那一条。

影响很小（`aria-expanded="false"` 已经把状态讲清楚，主流读屏对悬空 `aria-controls` 是容错的），列为 polish。修复是把 `v-if` 换成 `v-show`（节点常驻、`aria-controls` 恒有效），代价是折叠态下 `SubStepTimeline` 仍在渲染树里 —— 六行 DOM，可以接受。

**扣分项 — LO-03（low，polish）· 指针无证据时 live region 会播报一个 pending 的阶段**

```
web/src/composables/useOrchestrationTimeline.ts:527 / :533
```

`pointerIndex === -1`（一条可识别转移事件都没有、也没有快照）时，`pointerLabel` 回退到 `STAGE_ORDER[0]` = 「拆分」，live region 播报「**当前阶段：拆分**」，而界面上「拆分」是 `pending`。实测该形态：

```
拆分:pending 路由:pending 召回:pending 澄清:pending 并行调研:pending 融合:pending
0/6 步   标题「正在生成技术方案」   live「当前阶段：拆分」
```

—— 这正是 §E.3 末行明令禁止的**全灰空壳**。组件的「至少一条已知事实」那道门（`OrchestrationStageTimeline.vue:68-71`）把任何一条事件都算作事实，但一条**无法识别**的事件不构成指针意义上的事实。

**当前不可达**（已核验后端：`event_taxonomy.py` 里 process 级事件只有 `process.session.failed` 一个，而编排的第一条事件必然是 `decomposed` 这条可识别转移），故记 polish。但 fan-out 挂在通用的 `_emit_event` 上，后端将来任何一条「早于 `decomposed` 的会话级事件」都会把这个形态打开。

修复：把渲染门从「有事件」收严成「有快照 **或** 有可识别转移事件」，即在 `OrchestrationTimelineView` 上多导出一个 `hasPointer` 布尔，组件按它决定是否 `return null`。顺带解决 live region 的措辞矛盾。

**非扣分观察（存量形态，非本 phase 引入）**

- 两个新 `<button>` 都没有 `focus-visible` 焦点环 —— `main.css:537-538` 的焦点环只覆盖 `.btn` / `.sidebar-s2a-link`，chat 家族的裸 `<button>`（如 `DeepAnalysisCard.vue:50` 的 `.da-head`）一直如此。仅备录。
- `SubStepTimeline` 的行同时有 `role="listitem"`、`title` 与一个 `sr-only` 状态文本，部分读屏会把状态念两遍（`title` 作为描述 + `sr-only` 作为内容）。契约 §F 同时要求了这两者，实现照做无误；若 UAT 实测确认重复朗读，去掉 `title` 即可（视觉 tooltip 对非读屏用户的价值有限，状态文本已在 DOM 里）。
- `SubStepTimeline` 的局部状态色 map 形式上仍违反 DESIGN.md「禁止组件内定义 statusColors」—— 按 §Color 的裁定，本 phase 只在既有 map 内加分支、不迁 `~/config/status.ts`，实现遵守了这条边界。已记为 §Unresolved #5 的技术债。

---

## Registry Safety

| 检查项 | 结果 |
|---|---|
| `web/components.json` | 存在，但本 phase **未执行** `shadcn init` / `shadcn add` |
| 第三方 registry 拉块 | **无** —— §Registry Safety 声明 not applicable，diff 复核成立 |
| `web/pnpm-lock.yaml` / `web/package.json` / `web/components.json` | **均未改动**（`git diff --name-only` 三者零命中） |
| 新增 `ui/` 组件 | **无** —— 仅复用既有 `badge` |
| `web/src/components.d.ts` | +2 行（`OrchestrationStageTimeline` / `PlanResearchLogGroup` 自动注册），无第三方来源 |

**Registry 审计：0 个第三方块，无需 `shadcn view` 审源门，零 flag。**

---

## 契约符合性速查（UI-SPEC §UI Considerations · Covered 22 条）

| # | 契约要点 | 结果 |
|---|---|---|
| 1 | 时间线卡骨架逐字沿用 `OrchestratedPlanCard:109` | ✅ `OrchestrationStageTimeline.vue:132-153` |
| 2 | 六标签 + `classify` 可选步，非 feature_list 时**整步不渲染** | ✅ `useOrchestrationTimeline.ts:45-53`、`:473`、`:521`（实测 DOM 无该行） |
| 3 | 单步六态，`skipped`/`unknown` 用空心灰点 | ✅ `SubStepTimeline.vue:44-57` |
| 4 | 阶段指针以 `current_stage` 为权威、冲突不打 warn | ✅ `:445-451` |
| 5 | 七套结构化摘要、缺数据整行不渲染 | ✅ `:316-405`、`:504-506` |
| 6 | payload 自由文本一律不上屏 | ✅ 全文件零读取（见维度 1） |
| 7 | 失败步红点 + 红标签 + `role="alert"` 原因行、后续步保持 pending | ✅ `SubStepTimeline.vue:123`、`:132`；`useOrchestrationTimeline.ts:480-493` |
| 8 | 失败原因闭集 + 未命中回退「未知原因」 | ✅ `:459` |
| 9 | 单仓调研失败 ≠ 编排失败 | ✅ `:361-370`（不标红，只进摘要计数） |
| 10 | 调研日志按仓一张 `DeepAnalysisCard`、纵向堆叠、仅首张展开 | ✅ `PlanResearchLogGroup.vue:77-119` |
| 11 | 不使用 `DeepAnalysisGroup` | ✅ 无引用 |
| 12 | 与 107 的边界：只渲染「路由」步的降级角标、不自行推断 | ✅ `:475`、`:514`（严格 `=== true`） |
| 13 | 刷新补齐走同一份 store 状态、直播态与补齐态视觉零差异 | ✅ `chat.ts:984-1027` |
| 14 | 中断态 `unknown`；`waiting_clarification` 不算中断；`orchestration` 缺失整块不渲染 | ✅ `:467`、`OrchestrationStageTimeline.vue:64-71` |
| 15 | 事件折叠幂等、计数不按到达次数累加 | ✅ `:197-200` + `chat.ts:110-142` |
| 16 | 终态收敛：`done` 自动折叠一次、`failed` 保持展开、标题即完成信号 | ✅ `OrchestrationStageTimeline.vue:103-116`；⚠️ 但 `failed` 的到达路径在前半程有洞（HI-01） |
| 17 | `orchestratedPlanData` 的 `.find` 加固为逐条解析 | ✅ `ChatMessageBubble.vue` 的 `resolveOrchestratedPlanData(item.result)`（109-MN-02 已修，本 phase 未回退） |
| 18 | `SubStepTimeline` 纯加性泛化、`ExecutionNode` 零回归 | ✅ 与 `f3292256` 逐字比对通过 + 391 用例锁住 |
| 19 | 单一 live region 不含步数计数；失败行不加 `aria-live`；步骤行不进 tab 序 | ✅ `:102-111`、`SubStepTimeline.vue:132`、`:105` |
| 20 | 前端数据契约三类型 + `ConversationRuntime` 扩两字段 | ✅ `types/chat.ts`、`types/execution.ts:122-144` |
| 22 | 视觉零漂移（色板 / 字号 / 字重 / 间距 / 组件 / 依赖） | ✅ 见维度 3 / 4 / 5 |
| Backstop 9 | 新增组件零 `v-html` | ✅ 三文件零命中 |
| Backstop 11 | 观测代码不反噬业务 | ✅ 四道 `try/catch` 防线 |

未在本审计覆盖：#21（后端 fan-out / `reason_code` 压闭集 / 快照分支，非前端面）。

---

## 关于 2s 轮询是否「诚实呈现进度」（专项结论）

**结论：后半程是诚实的；不诚实的是前半程，而那一段恰恰是真直播。**

任务简报把「后半程走 2s 快照轮询」列为已知架构事实、非缺陷。就「2s 节拍下 UI 有没有撒谎」这个具体问题逐项核对：

| 可能撒谎的点 | 实际实现 |
|---|---|
| 进度会不会退回去 | 不会 —— 指针取 `current_stage`（`:445-451`），事件截断只丢摘要精度 |
| 会不会卡在早期阶段 | 不会 —— 快照优先于折叠事件流，且回退转移被正确建模（`:70-92`） |
| 计数会不会翻倍 | 不会 —— 双链去重键 + 自然键，实测重复投递不累加 |
| 调研分母会不会永远到不了满 | 不会 —— 分母取实际派了容器的去重 repo 数，不取路由候选数（`:364`） |
| 2s 空窗期会不会显示假状态 | 不会 —— 空窗期显示的是上一拍的真实快照，不做任何插值或乐观推进 |
| 会不会告诉用户「这是补齐的」 | 不会 —— §E.2 的「视觉零差异」守住，无「已恢复」徽标、无时间戳 |

⇒ **2s 节拍本身没有引入任何谎言。** 唯一的表达问题是 MN-01：脉冲动画把「在动」的信号给了 2s 轮询的后半程、没给逐事件流式的前半程 —— 这不是节拍的错，是脉冲条件挂在了快照上。修好 MN-01 之后，两段的活跃度表达就一致了。

真正的诚实性缺口是 HI-01：前半程失败时**没有任何机制**把状态翻红，时间线会一直宣称「正在生成技术方案」。这与轮询节拍无关，是「失败信号只走快照、而前半程没有快照」的单点问题。

---

## 建议人工 UAT（浏览器下复核，不计分）

1. 制造一次**前半程失败**（打断 route 或 recall stage），确认 HI-01 的复现与修复后行为 —— 这是本次审计唯一需要实跑坐实的结论。
2. 跑一次真实跨仓编排，肉眼确认前半程（拆分→澄清）的活跃步是否在脉冲（MN-01）。
3. 读屏（VoiceOver / NVDA）走一遍调研日志组的折叠按钮，确认能听到仓库数（MN-02）。
4. 编排完成后看版面：时间线收敛成一行之后，日志组是否把 `OrchestratedPlanCard` 挤出视口（LO-01）。
5. 亮 / 暗主题下 `bg-transparent border border-muted-foreground/50` 空心点的可辨识度 —— 它是 `skipped` / `unknown` 唯一的形状信号。
6. 五个仓并行调研时，确认 live region **只播报阶段变化**、不随各仓完成连播（契约 §F 的硬要求，代码层面已守住，值得实测一次）。

---

## Files Audited

| 文件 | 性质 | 审计深度 |
|---|---|---|
| `web/src/composables/useOrchestrationTimeline.ts` | 新建（536 行） | 全文件 + `tsx` 实跑三场景 |
| `web/src/components/chat/OrchestrationStageTimeline.vue` | 新建（164 行） | 全文件 |
| `web/src/components/chat/PlanResearchLogGroup.vue` | 新建（121 行） | 全文件 |
| `web/src/components/execution/dag/SubStepTimeline.vue` | 改（+109 −38） | 全文件 + 与 `f3292256` 版本逐字比对 |
| `web/src/components/chat/ChatMessageBubble.vue` | 改（+122） | diff + 单例 tool 分支上下文 |
| `web/src/stores/chat.ts` | 改（+241） | diff + 轮询调度链（`scheduleRuntimePoll` 全部 12 个调用点） |
| `web/src/types/execution.ts` / `web/src/types/chat.ts` | 改（支撑面） | 仅核对未引入视觉面 |
| `web/src/components/chat/DeepAnalysisCard.vue` | 未改（依赖） | 头部 / 空态 / 日志区样式 |
| `web/src/components/ui/badge/index.ts` | 未改（依赖） | variant 表 |
| `web/src/styles/main.css` | 未改（依赖） | 焦点环 + `prefers-reduced-motion` 块 |
| `server/delivery/services/event_taxonomy.py` / `convergence_session_service.py` | 未改（核验用） | process 级事件常量与 `_emit_event` 调用点 |
| 6 个 spec 文件（223 用例） | 新建 / 改 | 实跑全绿 |
