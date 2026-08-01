---
phase: 109-spine-convergence
plan: 06
subsystem: ui
tags: [vue3, composition-api, pinia, vitest, computed, chat, schema-narrowing, backward-compat]

# Dependency graph
requires:
  - phase: 109-02
    provides: CodingPlan.provenance / source_artifact_version_id 两列（runtime 扩字段的后端对侧）
  - phase: 109-04
    provides: CodingPlanRuntime 的 tech_plan / affected_files 扩字段与 OrchestratedPlanCard 的投影响应交棒 props（本 plan 的第 1、2 级数据源）
  - phase: 109-05
    provides: tech_plan / affected_files 已从两个 @tool 的 schema 移除（本 plan 处置的正是这次收窄的前端连带面）
provides:
  - TechPlanCard.resolvedTechPlan / resolvedAffectedFiles —— 方案正文与影响文件的三级优先解析（props > runtime[过 plan_id 守卫] > 空）
  - 空正文占位「（暂无方案正文）」：正文为空时不再渲染空 prose 块
  - codingPlanData 的 tool input 取值显式降级为历史消息兜底（保留不删）
  - 串态防护用例（runtime.plan_id 不匹配时不采用 runtime 正文）+ 负控实测背书
  - 历史 runtime 缺字段（undefined）时挂载零抛错、console.warn/error 零调用的用例
affects: [SPINE-02, RELY-01, Phase-110]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "全局 runtime 与卡片实例不是一对一：任何对 activeCodingPlan 的消费都必须过 `runtime.plan_id === props.codingPlanId` 守卫，否则多方案会话会把新方案内容渲染到旧卡上 —— 不报错、不崩，只是内容串了"
    - "同一个 prop 承载两个来源时，用注释显式标注而不是拆成两个 prop：props.techPlan 同时是「投影响应本地态」与「历史消息 tool input 兜底」，拆 prop 会让 ChatMessageBubble 与 OrchestratedPlanCard 两个调用方都要改，收益为零"
    - "schema 收窄的前端连带面要与收窄同 wave 落地：入参消失只让正文变空串，既有 v-html 渲染成一个空 prose 块 —— 不报错不崩，是「上线后才被用户发现」的一类缺陷"
    - "护栏断言做负控实测：写完 plan_id 守卫的串态防护用例后，实际把守卫从组件里删掉跑一遍，确认该用例转红"

key-files:
  created: []
  modified:
    - web/src/components/chat/TechPlanCard.vue
    - web/src/components/chat/ChatMessageBubble.vue
    - web/src/components/chat/__tests__/TechPlanCard.spec.ts
    - web/src/components/chat/__tests__/chatMessageBubble.parts.spec.ts

key-decisions:
  - "第 1 级与第 3 级共用 props.techPlan：历史消息路径上该 prop 本来就来自 codingPlanData.techPlan，两级的差别只在数据来源而非取值方式。不新增 prop，但在注释里明确标注它承载两个来源"
  - "watchEffect 在正文为空时把 renderedPlan 清空而非保留上一份：留着旧 HTML 在 ref 里是一颗定时炸弹 —— 今天占位分支的 v-if 挡住了它，明天任何新分支读到 renderedPlan 都会渲染出上一个方案的正文"
  - "占位文案在模板里写字面量而非提取常量：与本组件既有的「（无方案文本）」等硬编码中文一致（UI-SPEC §Copywriting 明确本组件家族不引入 vue-i18n key），提常量反而破坏一致性"
  - "change_type 不做前端 create → add 兼容映射：前端偷偷把 create 显示成 add 会掩盖后端映射缺陷，使该漂移变成永远查不出的问题；正确性由 109-03 的后端映射纯函数保证"
  - "parts.spec 的 TechPlanCard stub 扩透出 codingPlanId / techPlan / affectedFiles 三个属性：本文件只断言 bubble 传了什么，卡片内部的三级优先归 TechPlanCard.spec.ts —— 两件事不绞在一起"

patterns-established:
  - "三级优先解析的注释纪律：每一级写清「数据来自哪」而不只是「取什么」，并在守卫处写清「省掉会怎样」（本次逐字沿用 feishuDocUrl 的口径）"
  - "串态类缺陷的用例要断言「没被采用」而不只是「有内容」：本次断言的是别的 plan 的正文与文件路径都不出现，且落到占位文案"

requirements-completed: [SPINE-02]

# Coverage metadata
coverage:
  - id: D1
    description: "方案正文与影响文件走三级优先解析（props > runtime > 空），SPINE-02 收窄后新消息的方案卡仍能显示正文"
    requirement: "SPINE-02"
    verification:
      - kind: unit
        ref: "web/src/components/chat/__tests__/TechPlanCard.spec.ts#第 1 级：techPlan prop 非空时优先于 runtime 正文"
        status: pass
      - kind: unit
        ref: "web/src/components/chat/__tests__/TechPlanCard.spec.ts#第 2 级：prop 为空且 runtime.plan_id 匹配时采用 runtime 的 tech_plan / affected_files"
        status: pass
    human_judgment: false
  - id: D2
    description: "🔴 plan_id 守卫在位：多方案多轮会话里 runtime.plan_id 与本卡不匹配时不采用 runtime 正文/影响文件，落到占位（不串态）"
    requirement: "SPINE-02"
    verification:
      - kind: unit
        ref: "web/src/components/chat/__tests__/TechPlanCard.spec.ts#多方案会话不串态：runtime.plan_id 与本卡不匹配时不采用 runtime 正文，落到占位"
        status: pass
      - kind: other
        ref: "负控实测：把 TechPlanCard 两处 `runtime.plan_id === props.codingPlanId` 守卫改为裸 `if (runtime)` 后重跑 → 1 failed / 39 passed，随后原样恢复（git diff 空）"
        status: pass
    human_judgment: false
  - id: D3
    description: "历史会话方案卡不变空：tool input 取值降级为历史兜底但未删除，历史消息正文经 props 传下正常渲染"
    requirement: "SPINE-02"
    verification:
      - kind: unit
        ref: "web/src/components/chat/__tests__/TechPlanCard.spec.ts#第 3 级：历史消息（runtime 无 tech_plan，正文由 tool input 经 prop 传下）正常渲染且零报错/零 warn"
        status: pass
      - kind: unit
        ref: "web/src/components/chat/__tests__/chatMessageBubble.parts.spec.ts#历史消息形态（input 含 tech_plan / affected_files）→ 正文与影响文件经 props 传下"
        status: pass
    human_judgment: false
  - id: D4
    description: "空正文渲染一行占位文案「（暂无方案正文）」而非空 prose 块；占位走插值不用 v-html；折叠态既有「（无方案文本）」兜底保持不变"
    requirement: "SPINE-02"
    verification:
      - kind: unit
        ref: "web/src/components/chat/__tests__/TechPlanCard.spec.ts#第 4 级：三者皆空 → 渲染占位文案，且不出现空的 .prose 块"
        status: pass
      - kind: unit
        ref: "web/src/components/chat/__tests__/TechPlanCard.spec.ts#折叠态三者皆空时保留既有「（无方案文本）」兜底"
        status: pass
      - kind: other
        ref: "源码级断言：`rg -n 'v-html' TechPlanCard.vue | rg -v 'renderedPlan' | rg -v '^[0-9]+:[[:space:]]*(//|\\*|<!--)'` 无匹配（退出码 1）"
        status: pass
    human_judgment: false
  - id: D5
    description: "新消息形态（tool input 无 tech_plan / affected_files）下 TechPlanCard 仍渲染，codingPlanId 正确传下，不因正文为空而崩"
    requirement: "SPINE-02"
    verification:
      - kind: unit
        ref: "web/src/components/chat/__tests__/chatMessageBubble.parts.spec.ts#新消息形态（input 不含 tech_plan / affected_files）→ 卡片仍渲染且 codingPlanId 正确传下"
        status: pass
    human_judgment: false
  - id: D6
    description: "历史数据零报错：runtime 缺 provenance / tech_plan / affected_files 三字段（undefined）与 activeCodingPlan 为 null 时挂载与渲染不抛、console.warn/error 零调用"
    requirement: "SPINE-02"
    verification:
      - kind: unit
        ref: "web/src/components/chat/__tests__/TechPlanCard.spec.ts#历史 runtime 缺 provenance / tech_plan / affected_files 三字段（undefined）→ 挂载与渲染不抛、零 warn"
        status: pass
      - kind: unit
        ref: "web/src/components/chat/__tests__/TechPlanCard.spec.ts#无 store runtime（activeCodingPlan 为 null）时正文仍走 prop，不抛错"
        status: pass
    human_judgment: false
  - id: D7
    description: "change_type 保持原样显示，无前端 create → add 兼容映射（后端映射缺陷保持可见）"
    requirement: "SPINE-02"
    verification:
      - kind: other
        ref: "源码级核对：`rg -n \"change_type|'create'\" TechPlanCard.vue` 仅 3 处命中（两处类型声明 + 模板裸字段 `{{ file.change_type }}`），组件内不存在以 'create' 为键/比较值并产出 'add' 的映射结构"
        status: pass
    human_judgment: false
  - id: D8
    description: "真实浏览器下多方案多轮会话的方案卡正文观感：新方案卡显示新正文、旧方案卡不被串改、历史会话卡不变空"
    verification: []
    human_judgment: true
    rationale: "串态是「不报错不崩、只是内容串了」的一类缺陷，单测只能覆盖已设想的 plan_id 组合；真实多轮会话里 activeCodingPlan 的刷新时序与卡片实例数量由后端 runtime polling 决定，需在浏览器里连开两轮方案实际观察。另需一并观察 109-04 已记录的 lark_md 方言观感（`•` 项目符号在 GFM 下显示为纯文本）"

# Metrics
duration: 12min
completed: 2026-07-30
status: complete
---

# Phase 109 Plan 06: SPINE-02 前端连带影响 —— TechPlanCard 方案正文数据源迁移 Summary

**把方案正文与影响文件的取值从「LLM 写进工具 input 的 tech_plan」迁到「投影响应 / runtime」的三级优先解析（第 2 级过 `plan_id` 守卫防串态），同时保住历史消息不变空、空正文渲染占位而非空 prose 块。**

## Performance

- **Duration:** 约 12 min
- **Started:** 2026-07-30T08:31Z
- **Completed:** 2026-07-30T08:43Z
- **Tasks:** 2
- **Files modified:** 4（0 新建）
- **Tests:** 新增 11 条（TechPlanCard 9 / parts 2），chat 组件全量 **244 passed / 25 files**（改动前 233，零回归）

## Accomplishments

- **SPINE-02 的前端连带面已闭合**：`resolvedTechPlan` / `resolvedAffectedFiles` 两个 computed 取代了直接读 `props.techPlan` / `props.affectedFiles` 的渲染路径。收窄 schema 后新消息的 tool input 已无正文，正文改由投影响应（`OrchestratedPlanCard` 直接喂的 props）或 `runtime.coding_plan` 承载 —— 方案卡不会再出现「卡在那儿但里面没有方案」。
- **🔴 `plan_id` 守卫在位且经负控实测背书**：两个 computed 的 runtime 分支都要求 `runtime.plan_id === props.codingPlanId`。串态防护用例断言的是**别的 plan 的正文与文件路径都不出现**、并落到占位文案。写完后把守卫从组件里删掉重跑一遍 —— 该用例立刻转红（1 failed / 39 passed），确认它不是在同义重复当前实现，随后原样恢复。
- **历史会话不变空**：`props.techPlan` 这一级同时承载「投影响应本地态」与「历史消息 tool input 兜底」两个来源。`ChatMessageBubble` 的 `codingPlanData` 取值**保留未删**，只在旁边加注释把它降级定位为历史兜底。砍掉这一级会让 SPINE-02 之前的所有会话方案卡集体变空 —— 这是本 plan 最容易被「顺手清理」掉的一行。
- **空正文有占位而非空块**：`（暂无方案正文）` 走 `{{ }}` 插值，与既有 `v-html="renderedPlan"` 是互斥的 `v-else-if` / `v-else` 分支。折叠态既有的 `（无方案文本）` 兜底原样保留（另有用例锁）。
- **`change_type` 保持原样显示**：组件内不存在任何以 `'create'` 为键或比较值、产出 `'add'` 的映射结构。前端偷偷把 `create` 显示成 `add` 会掩盖后端映射缺陷，让这条漂移变成永远查不出的问题。
- **零新增依赖、零新增设计 token、零新增 `v-html` 面**：`git diff --exit-code web/pnpm-lock.yaml` 退出码 0；源码级 `v-html` 断言（过滤 `renderedPlan` 与注释行）无匹配。

## Task Commits

1. **Task 1: techPlan / affectedFiles 三级优先解析 + plan_id 守卫 + 空正文占位** — `b12a2530` (refactor)
2. **Task 2: codingPlanData 降级为历史兜底 + 三级优先与串态防护的用例** — `c4869180` (test)

## Files Created/Modified

- `web/src/components/chat/TechPlanCard.vue` — 新增 `resolvedTechPlan` / `resolvedAffectedFiles` 两个 computed（含三级优先与 `plan_id` 守卫的注释纪律）；`watchEffect`、影响文件区块、折叠态摘要三处改读 resolved 值；模板新增空正文占位分支
- `web/src/components/chat/ChatMessageBubble.vue` — `codingPlanData` 的 `tech_plan` / `affected_files` 取值处加注释降级为历史消息兜底（**取值保留未删**）
- `web/src/components/chat/__tests__/TechPlanCard.spec.ts` — 新增 `109-06 方案正文三级优先解析` describe（9 用例：四级各一 + 串态防护 + 缺字段零 warn + null runtime + 折叠态两条）
- `web/src/components/chat/__tests__/chatMessageBubble.parts.spec.ts` — TechPlanCard stub 扩透出 `codingPlanId` / `techPlan` / `affectedFiles`；新增 `109-06 coding plan 正文数据源` describe（2 用例：新消息形态 / 历史消息形态）

## Decisions Made

- **第 1 级与第 3 级共用 `props.techPlan`**：历史消息路径上该 prop 本来就来自 `codingPlanData.techPlan`，两级的差别只在数据来源而非取值方式。不新增 prop（新增会让 `ChatMessageBubble` 与 `OrchestratedPlanCard` 两个调用方都要改而收益为零），改用注释显式标注它承载两个来源。
- **占位文案在模板里写字面量而非提取为常量**：plan 的 artifacts 一节把它记作「文案常量」，但本组件既有的 `（无方案文本）` / `编码失败，未提供错误信息` 等中文全是模板内字面量，且 UI-SPEC §Copywriting 明确本组件家族不引入 vue-i18n key。提常量会在一个全字面量的文件里造出唯一一个例外，反而破坏一致性；acceptance criteria 要求的也是「模板中存在文案 `（暂无方案正文）`」。
- **`parts.spec` 的 stub 扩属性而非改用真实组件**：真实 `TechPlanCard` 依赖 chat store 与 markdown renderer，在 bubble 测试里挂载它会把「bubble 传了什么」和「卡片怎么解析」两件事绞在一起。stub 透出三个 data 属性即可完成传参断言，解析归 `TechPlanCard.spec.ts`（沿用 109-04 对 `OrchestratedPlanCard` 的同款处理）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `watchEffect` 在正文为空时清空 `renderedPlan` 而非保留上一份**

- **Found during:** Task 1（`watchEffect` 改读 `resolvedTechPlan`）
- **Issue:** 原实现是 `if (mdInstance.value && props.techPlan) { renderedPlan.value = ... }` —— 正文由非空变空时**不进赋值分支**，`renderedPlan` 里会留着上一份渲染结果。今天占位分支的 `v-else-if="!resolvedTechPlan"` 恰好把它挡在屏幕外，但一个装着过期 HTML 的响应式 ref 是定时炸弹：任何后续分支（如 RELY-01 的草稿横幅路径）读到它就会渲染出上一个方案的正文，而这正是本 plan 花最大篇幅防的那类串态缺陷。
- **Fix:** 改为 `if (!mdInstance.value) return` 早退 + 三元赋值，正文为空时显式写入 `''`。
- **Files modified:** `web/src/components/chat/TechPlanCard.vue`
- **Verification:** `第 4 级：三者皆空 → 渲染占位文案，且不出现空的 .prose 块` 与既有 31 条断言全绿。
- **Committed in:** `b12a2530`（Task 1 commit）

### 主动补强（超出 plan 字面要求，均为验收强度而非新增范围）

**2. plan_id 守卫的负控实测**

plan 只要求「存在一条串态防护用例」。参照 109-04 建立的纪律（护栏断言最容易写成「断言当前实现」），实际把 `TechPlanCard.vue` 两处守卫改为裸 `if (runtime)` 重跑一遍：串态防护用例转红（`expected '编码方案# 别的方案的正文…' not to contain '别的方案的正文'`），其余 39 条仍绿 —— 证明该用例精确命中守卫本身。随后原样恢复，`git diff` 为空。

**3. 三条 plan 未点名的补充用例**

- `无 store runtime（activeCodingPlan 为 null）时正文仍走 prop，不抛错` —— Backstop 第 1 条的另一半（plan 只点了「缺字段」，没点「整个 runtime 为 null」）。
- `折叠态摘要同样读三级优先解析结果` —— plan 要求折叠态改读 resolved 值，但未要求用例；不锁的话把这行改回 `techPlan` 不会有任何测试转红。
- `折叠态三者皆空时保留既有「（无方案文本）」兜底` —— plan 明令该兜底「保持不变」，用例即该约束的锁。

---

**Total deviations:** 1 auto-fixed（Rule 1 bug）+ 2 主动补强（1 负控实测、3 条补测）
**Impact on plan:** 全部围绕本 plan 已交付性质的验收强度，无范围扩张。plan 的两个 task 各一次提交完成，未触发任何拆分。

## Issues Encountered

- **`vue-tsc` 的退出码在管道里取不到**：首次用 `pnpm vue-tsc ... | tail` + `${PIPESTATUS[0]}` 在 zsh 下取到空值（zsh 用 `$pipestatus`）。改为重定向到文件后单独取 `$?` 复核：退出码 0、输出 0 行，全仓类型检查确实零错误。

## Verification Results

| 命令 | 结果 |
|---|---|
| `pnpm vitest run src/components/chat/__tests__/TechPlanCard.spec.ts` | **40 passed**（既有 31 + 新增 9） |
| `pnpm vitest run src/components/chat/__tests__/` | **244 passed / 25 files**（改动前 233，零回归） |
| `pnpm vue-tsc --noEmit -p tsconfig.json` | 退出码 0、零输出（零类型错误） |
| `pnpm eslint`（4 个改动文件） | 零 error |
| `git diff --exit-code web/pnpm-lock.yaml` | 退出码 0（零新增依赖） |
| `rg -n 'v-html' TechPlanCard.vue \| rg -v 'renderedPlan' \| rg -v '注释行'` | 无匹配（无新增 `v-html` 面） |
| 负控：删掉两处 `plan_id` 守卫 | **1 failed / 39 passed**（串态防护用例有效），已原样恢复 |
| `git diff --diff-filter=D HEAD~2 HEAD` | 无输出（两次提交零文件删除） |

## Threat Model Coverage

| Threat ID | 落法 |
|---|---|
| T-109-06-01（Tampering，runtime 跨 plan 串数据） | `resolvedTechPlan` / `resolvedAffectedFiles` 的 runtime 分支均要求 `runtime.plan_id === props.codingPlanId`；串态防护用例断言别的 plan 的正文与文件路径都不出现、落到占位；负控实测证明该用例会转红 |
| T-109-06-02（Tampering，新增文案渲染面） | 占位文案走 `{{ }}` 插值；源码级 `rg` 断言除既有 `renderedPlan` 外无 `v-html`（同时过滤注释行，避免注释提及让断言自我失效） |
| T-109-06-03（Information Disclosure，空正文降级） | 占位只显示中性常量 `（暂无方案正文）`，不回显任何后端 `detail` 或原始取值 |
| T-109-06-SC（供应链） | 零新增依赖；`git diff --exit-code web/pnpm-lock.yaml` 退出码 0；未执行任何 `pnpm add` / `shadcn add` |

## Observability

本 plan 为纯前端渲染路径改动，**无新增请求入口、无 LLM 调用点、无召回、无队列任务或 webhook**，不涉及 `.cursor/rules/observability-logging.mdc` 的 `call_source` / `RequestMetric` / `RetrievalTrace` 埋点要求。数据源本身（投影端点与 runtime 序列化）的观测已分别在 109-03 / 109-04 就位，前端不重复上报。

## Known Stubs

无占位实现。以下是**按 plan 设计**分派到后续 plan 的下游接线，不是本 plan 的 stub：

- `TechPlanCard` 的草稿横幅 / 折叠态徽标 / 送编码确认弹层（RELY-01，UI-SPEC §B/§C）不在本 plan 范围。⚠️ 该 plan 的执行者会新增第三个 `runtime.provenance` 消费点 —— 按 UI-SPEC §Backstop 第 6 条，它**同样必须**过 `runtime.plan_id === props.codingPlanId` 守卫，本 plan 的两个 computed 已是可逐字沿用的形状。
- 后端 `ConversationRuntimeCodingPlanSerializer` 尚未透出 `tech_plan` / `affected_files` / `provenance`（109-04 Next Phase Readiness 已记）。因此本 plan 的**第 2 级目前在生产环境拿不到值**，实际生效的是第 1 级（投影响应经 `OrchestratedPlanCard` 直接喂 props）与第 3 级（历史 tool input）。这不影响本 plan 的正确性 —— 三级优先的判定与守卫已就位、有用例锁，后端透出后自动生效；但 UAT 时若想实测第 2 级，需先确认后端序列化面已落。
- `render_merged_plan_markdown` 的 lark_md 方言（`•` 在 GFM 下显示为纯文本）：UI-SPEC §Unresolved 第 7 条裁定接受现状，若 UAT 判观感不可接受则给该函数加 `flavor` 参数，**不 fork 渲染器**。

## User Setup Required

None —— 无外部服务配置需求，零新增依赖、零新增迁移。

## Next Phase Readiness

- **SPINE-02 的前端连带面已闭合**：109-05 收窄 schema 后新消息方案卡不会变空，历史会话不受影响，两条路径各有用例锁。
- ⚠️ **提醒 RELY-01 执行者**：`runtime.provenance` 是 `runtime.coding_plan` 的第三个消费点，**必须过同一道 `plan_id` 守卫**（UI-SPEC §Backstop 第 6 条）。漏守卫的后果与正文串态同形：把别的方案的 provenance 渲染到本卡上，导致编排产出被误标「未经调研」或草稿被漏标 —— 后者是安全性方向的失守。本 plan 的两个 computed 是现成模板。
- ⚠️ **提醒后端**：runtime 序列化器透出 `tech_plan` / `affected_files` 之前，三级优先的第 2 级在生产上恒不命中（不报错，只是这一级空跑）。该透出落地后建议在真实会话里复验一次第 2 级路径。
- **技术债（不在本 plan 范围）**：`TechPlanCard:350-357` 状态 Badge 的 `:class="[badgeClass]"` 仍违反 DESIGN.md Badge 禁令（UI-SPEC §Unresolved 第 3 条明令本 phase 不顺手修）；本 plan 未新增任何 Badge，也未复制该形状。

## Self-Check: PASSED

- 4 个改动文件均存在于磁盘且已提交：`TechPlanCard.vue` / `ChatMessageBubble.vue` / `TechPlanCard.spec.ts` / `chatMessageBubble.parts.spec.ts`
- 两个 task commit 均可在 `git log` 中定位：`b12a2530` / `c4869180`
- `git diff --diff-filter=D --name-only HEAD~2 HEAD` 无输出（零文件删除）
- 未修改 `.planning/STATE.md` 与 `.planning/ROADMAP.md`（编排器职责）
- 负控实测后的组件源码已原样恢复（`git diff` 空）

---
*Phase: 109-spine-convergence*
*Completed: 2026-07-30*
