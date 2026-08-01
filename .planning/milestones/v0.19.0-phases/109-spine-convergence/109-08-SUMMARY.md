---
phase: 109-spine-convergence
plan: 08
subsystem: ui
tags: [vue3, composition-api, pinia, vitest, alert-dialog, checkbox, badge, allow-list, rely-01, chat]

# Dependency graph
requires:
  - phase: 109-07
    provides: 请求体字段名 acknowledge_unresearched、拒绝响应稳定机器码 draft_requires_explicit_confirm、orchestrated 时该字段被忽略的服务端契约
  - phase: 109-06
    provides: resolvedTechPlan / resolvedAffectedFiles 两个三级优先 computed —— resolvedProvenance 逐字沿用其 plan_id 守卫形状
  - phase: 109-04
    provides: OrchestratedPlanCard 的 localProvenance 本地态（投影响应带回）与内嵌 TechPlanCard 的交棒 props
  - phase: 109-02
    provides: CodingPlan.provenance 列与 default="draft" 迁移（存量方案落到保守分支的事实基础）
provides:
  - TechPlanCard 新增 prop provenance?: string | null（投影响应本地态入口）
  - TechPlanCard.resolvedProvenance —— runtime.coding_plan 的第三个消费点，过 runtime.plan_id === props.codingPlanId 守卫
  - TechPlanCard.isUnresearched —— 允许清单判定（仅严格等于 'orchestrated' 免标注）
  - 展开态 amber 草稿横幅（role="alert"、无 aria-live、位于方案正文之前）+ 头部常驻 Badge variant="warning"「未经调研」
  - ensureUnresearchedAcknowledged() —— 创建态/追加态确认与单仓重试三条路径共用的阻断式确认闸门
  - 局部 AlertDialog + label 包裹的必勾 Checkbox；acknowledged 为组件本地 ref，每次打开重置
  - isDraftGateRejection() / handleDraftGateRejection() —— 按响应体 code 分支的兜底呈现（前端常量 toast + 重开弹层）
  - stores/chat.ts submitRepoMultiSelector 第 4 参 / retrySingleRepository 第 3 参 acknowledgeUnresearched（严格 === true 才放键）
  - api/chat.ts createSessionsForPlan payload 可选 acknowledge_unresearched?: boolean（不传即不发键）
  - OrchestratedPlanCard 把 localProvenance 作为 provenance prop 下传（编排方案零摩擦的接线）
affects: [RELY-01, Phase-110, 109-VERIFICATION]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "闸门返回三态对象而非裸布尔：`{ proceed: boolean, acknowledge?: true }` —— `acknowledge` 只在「用户勾选并确认」的分支上存在且类型收窄为字面 `true`，让「编排方案不发送该字段」在类型层就是结构性的，而不是靠调用点自觉过滤 undefined"
    - "允许清单判定要有负控实测背书：把 `!== 'orchestrated'` 改成 `=== 'draft'` 重跑 → 7 failed，证明四种保守分支用例锁的是「允许清单」这条性质本身，不是与当前实现同义的重复断言"
    - "被新闸门打红的既有用例统一补 `provenance: 'orchestrated'` 而非「在用例里走完弹层」：这三条用例的原始覆盖意图是「确认即提交 / 实参正确透传」，补 orchestrated 让它们回到零摩擦路径、断言逐字保留；草稿闸门由新增用例专门覆盖，两件事不绞在一起"
    - "错误分支按响应体 code 判定并有反向用例：造一条 detail 与草稿拒绝文案逐字相同但 code 不同的错误，断言它不走草稿分支 —— 锁的是「按 code 而非按 detail」这条纪律"

key-files:
  created: []
  modified:
    - web/src/components/chat/TechPlanCard.vue
    - web/src/components/chat/OrchestratedPlanCard.vue
    - web/src/stores/chat.ts
    - web/src/api/chat.ts
    - web/src/components/chat/__tests__/TechPlanCard.spec.ts

key-decisions:
  - "resolvedProvenance 的第 3 级返回 undefined 而非 'draft'：让「取不到」在类型上保持为「取不到」，标注由 isUnresearched 的允许清单统一裁决 —— 若这里返回 'draft'，判定就分散成两处，将来放宽某一处会静默失守"
  - "AlertDialogCancel 显式绑 @click 结算取消，而不只依赖 reka-ui 的内置关闭事件：意图更明确，也让「取消 → 不提交」可测；内置关闭（Esc / 遮罩）走 onUnresearchedDialogOpenChange 的微任务兜底，两条路径都有用例"
  - "重试路径用 `gate.acknowledge === true ? retry(a, b, true) : retry(a, b)` 的分支调用，而不是把 undefined 当第三参传下去：让「编排方案不发送该字段」在调用点也是结构性的，不依赖下游过滤 undefined"
  - "handleDraftGateRejection 只 toast + 重开弹层，绝不自动补 ack 静默重放请求：重放必须让用户在新弹层里重新勾选，否则前端就替用户签了第二次名"
  - "草稿徽标与既有状态 Badge 的 ml-auto / ml-1 共存写成模板内三元，而不是抽 computed：既有状态 Badge 的 `:class=\"[badgeClass]\"` 是 UI-SPEC Unresolved #3 记录的技术债，抽 computed 会诱导顺手重构它并牵动既有 spec 断言"

patterns-established:
  - "同一条纪律要在正反两侧都有锁：允许清单有「四种保守分支均标注」（正）+ 负控改拒绝清单转红（反）；code 分支有「命中 code 走草稿 toast」（正）+ 「detail 逐字相同但 code 不同不误判」（反）"
  - "闸门类改动的既有用例处置在 plan 里穷举、在代码里逐处注释：三条被打红的用例各自注释「provenance: 'orchestrated' 是 109-08 草稿闸门生效的预期连带影响，不是回归；本用例测的是 X，不是闸门」"

requirements-completed: [RELY-01]

# Coverage metadata
coverage:
  - id: D1
    description: "草稿方案在界面上显式标注：展开态 amber 横幅位于方案正文之前，头部 warning 徽标展开与折叠态常驻"
    requirement: "RELY-01"
    verification:
      - kind: unit
        ref: "web/src/components/chat/__tests__/TechPlanCard.spec.ts#provenance=draft → 草稿横幅与头部徽标都出现（含 role=\"alert\" 与 aria-live 缺席断言）"
        status: pass
      - kind: unit
        ref: "web/src/components/chat/__tests__/TechPlanCard.spec.ts#折叠后徽标仍可见（事实不被一次折叠操作藏起来）"
        status: pass
      - kind: other
        ref: "源码级：横幅模板行号 607 < v-html=\"renderedPlan\" 行号 635（横幅在正文之前）；Badge variant=\"warning\" 标签上无 :class 属性"
        status: pass
    human_judgment: false
  - id: D2
    description: "标注判定为允许清单：仅严格等于 orchestrated 免标注，draft / 未知取值 / null / undefined / 空串一律标注，且判定是纯字面比较不对 undefined 做属性访问"
    requirement: "RELY-01"
    verification:
      - kind: unit
        ref: "web/src/components/chat/__tests__/TechPlanCard.spec.ts#it.each 四种保守分支（undefined / null / 空串 / 未知取值）→ 均渲染横幅与徽标"
        status: pass
      - kind: unit
        ref: "web/src/components/chat/__tests__/TechPlanCard.spec.ts#历史 runtime 缺 provenance 字段 → 挂载与渲染不抛，console.warn / error 零调用"
        status: pass
      - kind: other
        ref: "负控实测：把 isUnresearched 改成拒绝清单形态（=== 'draft'）重跑 → 7 failed / 53 passed，随后原样恢复（git diff 空）"
        status: pass
    human_judgment: false
  - id: D3
    description: "🔴 串态防护：runtime.provenance 是 runtime.coding_plan 的第三个消费点，过 runtime.plan_id === props.codingPlanId 守卫"
    requirement: "RELY-01"
    verification:
      - kind: unit
        ref: "web/src/components/chat/__tests__/TechPlanCard.spec.ts#多方案会话不串 provenance：runtime.plan_id 与本卡不匹配时不采用其 provenance（落到保守分支标注）"
        status: pass
      - kind: unit
        ref: "web/src/components/chat/__tests__/TechPlanCard.spec.ts#runtime.plan_id 匹配时采用 runtime.provenance（orchestrated ⇒ 免标注）—— 正向对照，证明守卫不是恒不命中"
        status: pass
      - kind: other
        ref: "负控实测：把 resolvedProvenance 的守卫改为裸 if (runtime) 重跑 → 1 failed / 59 passed（精确命中串态用例），随后原样恢复"
        status: pass
    human_judgment: false
  - id: D4
    description: "草稿送编码前弹出阻断式确认，必勾解锁；每次打开重置勾选，不跨次记忆、不入 store / localStorage"
    requirement: "RELY-01"
    verification:
      - kind: unit
        ref: "web/src/components/chat/__tests__/TechPlanCard.spec.ts#草稿路径点确认 → 弹层出现，确认按钮初始 disabled 且带 aria-disabled；勾选后启用"
        status: pass
      - kind: unit
        ref: "web/src/components/chat/__tests__/TechPlanCard.spec.ts#弹层每次打开重置勾选（打开→勾选→取消→再打开，按钮回到 disabled）"
        status: pass
      - kind: unit
        ref: "web/src/components/chat/__tests__/TechPlanCard.spec.ts#取消弹层 → 不调任何提交 / esc · 遮罩关闭（update:open=false）等同取消，不提交"
        status: pass
      - kind: other
        ref: "源码级：acknowledged 为组件本地 ref(false)，rg 全文无 localStorage / store 写入；AlertDialogAction 不带 variant=\"destructive\"；Checkbox 被 <label> 包裹"
        status: pass
    human_judgment: false
  - id: D5
    description: "🔴 acknowledge_unresearched: true 只能由用户勾选产生，覆盖创建态确认、追加态确认与单仓重试三条路径；前端任何代码路径都不自行填该值"
    requirement: "RELY-01"
    verification:
      - kind: unit
        ref: "web/src/components/chat/__tests__/TechPlanCard.spec.ts#勾选后确认 → 提交请求体含 acknowledge_unresearched: true"
        status: pass
      - kind: unit
        ref: "web/src/components/chat/__tests__/TechPlanCard.spec.ts#重试路径同样弹层：确认后 retrySingleRepository 的请求体带 ack（未勾选前 createSessionsForPlan 零调用）"
        status: pass
      - kind: other
        ref: "源码级逐处走查：`rg -n 'acknowledge' TechPlanCard.vue stores/chat.ts api/chat.ts` 共 18 处命中，无任何一处在「用户未勾选」的分支上产出 true（走查明细见正文表格）"
        status: pass
      - kind: other
        ref: "负控实测：把 ensureUnresearchedAcknowledged 改成无条件 return { proceed: true } 重跑 → 7 failed / 53 passed，随后原样恢复"
        status: pass
    human_judgment: false
  - id: D6
    description: "编排方案零摩擦：弹层永不出现，acknowledge_unresearched 不发送（而非发 false），提交行为与今日一致"
    requirement: "RELY-01"
    verification:
      - kind: unit
        ref: "web/src/components/chat/__tests__/TechPlanCard.spec.ts#provenance=orchestrated → 横幅与徽标皆无，且送编码时弹层不出现（dialogOpen 为 false、请求直接发出）"
        status: pass
      - kind: unit
        ref: "web/src/components/chat/__tests__/TechPlanCard.spec.ts#编排路径提交请求体不含 acknowledge_unresearched 键（断言 `'acknowledge_unresearched' in payload === false`，而非断言值为 false）"
        status: pass
      - kind: unit
        ref: "既有三条提交/重试用例（:577 / :598 / :629）补 provenance: 'orchestrated' 后断言逐字未改且全绿"
        status: pass
    human_judgment: false
  - id: D7
    description: "服务端拒绝按响应体 code 字段分支，绝不匹配 detail 文案；命中 draft_requires_explicit_confirm 时用前端常量 toast 并重开弹层"
    requirement: "RELY-01"
    verification:
      - kind: unit
        ref: "web/src/components/chat/__tests__/TechPlanCard.spec.ts#code=draft_requires_explicit_confirm 的拒绝 → 前端常量 toast + 重新打开弹层（且勾选被重置）"
        status: pass
      - kind: unit
        ref: "web/src/components/chat/__tests__/TechPlanCard.spec.ts#其它错误（别的 code、但 detail 与草稿拒绝文案逐字相同）→ 沿用既有 toast，不误报为草稿拒绝"
        status: pass
      - kind: other
        ref: "源码级：`rg -n 'detail' TechPlanCard.vue` 仅 3 处命中且全在注释里，不存在对 detail 文本的包含匹配代码"
        status: pass
    human_judgment: false
  - id: D8
    description: "不回显 provenance 原始取值；新增横幅 / 徽标 / 弹层 / 占位文案零 v-html；零新增依赖"
    requirement: "RELY-01"
    verification:
      - kind: unit
        ref: "web/src/components/chat/__tests__/TechPlanCard.spec.ts#未知取值不回显：wrapper.text() 与 wrapper.html() 均不含 'weird_value'"
        status: pass
      - kind: other
        ref: "源码级：`rg -n 'v-html' TechPlanCard.vue | rg -v 'renderedPlan' | rg -v 注释行` 无匹配（退出码 1）；`git diff --exit-code web/pnpm-lock.yaml` 退出码 0"
        status: pass
    human_judgment: false
  - id: D9
    description: "真实浏览器下的双侧观感与端到端对齐：草稿卡横幅/徽标呈现、弹层拦截与勾选解锁的操作手感、导出物告示与界面主句是否逐字一致"
    verification: []
    human_judgment: true
    rationale: "文案逐字一致已由 109-07 的字面量断言在后端侧锁住，前端侧文案也是常量；但「用户在界面与飞书文档之间是否建立了同一心智」「弹层是否让人觉得是合理的一道闸而非骚扰」只能在真实会话里观察。另需实测编排链路产出 → 点「进入编码」→ 内嵌卡片零摩擦（弹层不出现）这条完整路径，以及存量历史方案卡集体出现草稿标注的观感冲击程度（预期行为，但需确认不至于让用户误判为故障）"

# Metrics
duration: 35min
completed: 2026-07-31
status: complete
---

# Phase 109 Plan 08: RELY-01 界面半边 —— 草稿标注 + 送编码阻断式确认 Summary

**`TechPlanCard` 上落地 RELY-01 的界面半边：`provenance` 驱动的允许清单判定（仅严格等于 `orchestrated` 免标注）产出「方案正文之前的 amber 横幅 + 头部常驻 warning 徽标」，送编码前由一道必勾解锁的局部 `AlertDialog` 闸住创建态/追加态/单仓重试三条路径，`acknowledge_unresearched: true` 在前端只有「用户勾选并确认」这一个产生点，服务端拒绝按响应体 `code` 分支兜底 —— 三条不变量各有正反两侧用例 + 负控实测背书。**

## Performance

- **Duration:** 约 35 min（实现 3 次提交 08:53–09:02，续跑会话补验证与 SUMMARY 09:15–09:28）
- **Tasks:** 3
- **Files modified:** 5（0 新建）
- **Tests:** `TechPlanCard.spec.ts` 新增 20 条（40 → **60 passed**），chat 组件 + stores 全量 **383 passed / 41 files**

## Accomplishments

- **草稿标注是数据驱动的允许清单，而非文案匹配**：`isUnresearched = resolvedProvenance !== 'orchestrated'` —— 一行纯字面比较，`'draft'` / 未知取值 / `null` / `undefined` / `''` 全部落到标注侧。组件内不存在对 `tech_plan` 正文做「草稿 / 未经调研」关键词匹配的代码。四种保守分支各有用例（`it.each`），且**负控实测**把判定改成拒绝清单形态（`=== 'draft'`）后 **7 条转红**，证明这些用例锁的是「允许清单」这条性质本身。
- **🔴 `runtime.provenance` 的 `plan_id` 守卫在位（109-06 / 109-07 两份 Next Phase Readiness 的头号提醒）**：`resolvedProvenance` 逐字沿用 `resolvedTechPlan` 的三级优先形状，第 2 级要求 `runtime.plan_id === props.codingPlanId`。串态防护用例 + 正向对照用例各一条；**负控实测**把守卫改为裸 `if (runtime)` 后精确 **1 条转红**。漏这道守卫的后果比正文串态更严重 —— 正文串了看得出来，来源标志串了看不出来，一份草稿会被静默漏标。
- **`acknowledge_unresearched: true` 在前端只有一个产生点**：`ensureUnresearchedAcknowledged()` 的 `confirmed ? { proceed: true, acknowledge: true } : { proceed: false }` 这一行。闸门返回值刻意是三态对象、`acknowledge` 的类型收窄为字面 `true`，让「编排方案不发送该字段」在类型层就是结构性的。store 与 api 两层均无默认值、无缓存、无记忆，且 store 是**有条件放键**（`if (acknowledgeUnresearched === true)`）而不是无条件展开。**负控实测**把闸门改成无条件放行后 **7 条转红**。
- **三条路径覆盖一致，legacy 路径的不覆盖有明文边界**：创建态与追加态共用 `handleMultiConfirm` ⇒ 天然都过闸门；单仓重试 `handleSessionRowRetry` 单独过一次闸门（重试同样**创建** session，服务端会一致地拒绝，若前端因「刚才确认过」自行补 `true` 就等于替用户签名）。legacy 单仓 `handleConfirm` 不加闸门，理由写在函数 docstring 里（此时前端无 `provenance`、服务端无 `plan_id`，且它确认的是**已存在**的 session）。
- **错误面同守「不靠文案」的纪律**：`isDraftGateRejection` 只读 `ApiError.body.code`。反向用例造了一条 `code` 不同但 `detail` 与草稿拒绝文案**逐字相同**的错误，断言它不走草稿分支 —— 锁的是判定依据本身，不是当前实现。命中时 `toastError` 用前端常量并**重新打开弹层**，不自动补 ack 静默重放。
- **零新增依赖 / 零新增设计 token / 零新增 `v-html` 面**：只复用既有 `ui/alert-dialog`、`ui/checkbox`、`ui/badge`；横幅 DOM 形状逐字沿用 `CommitConfirmCard`；徽标纯 `variant` 无 `:class`（不复制 UI-SPEC Unresolved #3 记录的既有违规形状）。`git diff --exit-code web/pnpm-lock.yaml` 退出码 0。

## Task Commits

1. **Task 1: isUnresearched 允许清单判定 + 草稿横幅 + 头部常驻徽标** — `37c5306b` (feat)
2. **Task 2: 送编码显式确认弹层 + ack 透传三条路径 + code 分支兜底呈现** — `be2f6605` (feat)
3. **Task 3: 界面标注与确认路径的用例扩充** — `0149964b` (test)

## Files Created/Modified

**实现**

- `web/src/components/chat/TechPlanCard.vue` — 新增 `provenance` prop；`resolvedProvenance`（三级优先 + `plan_id` 守卫）与 `isUnresearched`（允许清单，三条硬性纪律与失败代价不对称的理由写进注释）；展开态 amber 横幅（正文之前、`role="alert"`、无 `aria-live`）；头部常驻 `Badge variant="warning"` 与既有状态 Badge / chevron 的 `ml-auto` / `ml-1` 共存规则；`ERROR_CODE_DRAFT_REQUIRES_CONFIRM` / `DRAFT_GATE_REJECTED_MESSAGE` 两个前端常量；`acknowledged` 本地 ref 与 `openUnresearchedDialog` / `settleUnresearchedDialog` / `onUnresearchedDialogOpenChange` 的 promise 结算机；`ensureUnresearchedAcknowledged()` 闸门；`isDraftGateRejection()` / `handleDraftGateRejection()`；局部 `AlertDialog` 弹层
- `web/src/components/chat/OrchestratedPlanCard.vue` — `localProvenance` 作为 `:provenance` 下传给内嵌 `TechPlanCard`（漏传会让编排产出落到保守分支、被误挂横幅并多一次弹层），注释相应从「本 phase 不渲染」改写为「109-08 起作为判定输入」
- `web/src/stores/chat.ts` — `submitRepoMultiSelector` 第 4 参 `acknowledgeUnresearched`（严格 `=== true` 才放键，注释写明「不发字段而非发 false」的留痕理由）；`retrySingleRepository` 第 3 参原样转发
- `web/src/api/chat.ts` — `createSessionsForPlan` payload 类型加可选 `acknowledge_unresearched?: boolean`，注释写明「该值代表一次用户签名，调用方不传时不得注入 false」

**测试**

- `web/src/components/chat/__tests__/TechPlanCard.spec.ts` — 新增 `techPlanCard — 109-08 草稿标注与送编码确认` describe（20 条）；既有 `:577` / `:598` / `:629` 三条用例补 `provenance: 'orchestrated'` 挂载参数与说明注释（用例名与断言逐字保留）

## `acknowledge` 逐处走查结论（Task 2 acceptance criteria 要求写进 SUMMARY）

`rg -n 'acknowledge' web/src/components/chat/TechPlanCard.vue web/src/stores/chat.ts web/src/api/chat.ts` 共 **18 处**命中，逐处形态如下 —— **没有任何一处在「用户未勾选」的分支上产出 `true`**（含默认参数值、对象字面量默认展开、重试路径自动补值三类高危形态）：

| 位置 | 形态 | 是否可能在未勾选时产出 true |
|---|---|---|
| `api/chat.ts:479` | `acknowledge_unresearched?: boolean` 类型声明 | 否（纯类型，无默认值） |
| `stores/chat.ts:2571` / `:2630` | 可选参数声明 `acknowledgeUnresearched?: boolean` ×2 | 否（无默认值，缺省即 `undefined`） |
| `stores/chat.ts:2593` | `if (acknowledgeUnresearched === true)` | 否（严格布尔判定，truthy 字符串/数字不通过） |
| `stores/chat.ts:2594` | `payload.acknowledge_unresearched = true` | 否（受上一行守卫，且**有条件放键**而非无条件展开） |
| `stores/chat.ts:2644` | `acknowledgeUnresearched,` 原样转发 | 否（不补值、不默认） |
| `TechPlanCard.vue:163` | `gate.acknowledge` 作为第 4 实参 | 否（编排分支上该属性不存在 ⇒ `undefined`） |
| `TechPlanCard.vue:316` | `const acknowledged = ref(false)` | 否（初值 false） |
| `TechPlanCard.vue:332` | `acknowledged.value = false` | 否（每次打开重置） |
| `TechPlanCard.vue:345` | `if (!acknowledged.value) return` | 否（确认路径双保险） |
| `TechPlanCard.vue:365` / `:368` | 注释 ×2 | 否 |
| `TechPlanCard.vue:371` | 函数签名 `acknowledge?: true` | 否（类型收窄为字面 true，但可选） |
| **`TechPlanCard.vue:375`** | `confirmed ? { proceed: true, acknowledge: true } : { proceed: false }` | **这是唯一产生点**，条件是 `openUnresearchedDialog()` 解析为 true，即用户勾选后点了确认按钮 |
| `TechPlanCard.vue:429` | `gate.acknowledge === true ? retry(a, b, true) : retry(a, b)` | 否（分支调用，编排路径根本不传第三参） |
| `TechPlanCard.vue:982` / `:994` / `:995` | Checkbox `v-model`、按钮 `:disabled` / `:aria-disabled` | 否（UI 绑定） |

另核：`ensureUnresearchedAcknowledged()` 的早退分支条件是 `isUnresearched.value === false`，**不存在**任何无条件 `return true`、测试环境短路或 `import.meta.env` 分支（负控实测已反向验证）。

## Decisions Made

- **`resolvedProvenance` 第 3 级返回 `undefined` 而非 `'draft'`**：让「取不到」在类型上保持为「取不到」，标注归属由 `isUnresearched` 的允许清单**单点**裁决。若这里替换成 `'draft'`，判定就分散成两处，将来任何一处被放宽都会静默失守。
- **`AlertDialogCancel` 显式绑 `@click` 结算，而不只依赖 reka-ui 内置关闭**：意图更明确，也让「取消 → 不提交」可测。Esc / 遮罩关闭走 `onUnresearchedDialogOpenChange` 的微任务兜底（用一次 `Promise.resolve()` 让同一次点击里的显式确认先结算，避免内置关闭把用户的确认吞成取消），两条路径各有用例。
- **重试路径用分支调用而非把 `undefined` 当第三参传下去**：`gate.acknowledge === true ? retry(a, b, true) : retry(a, b)`。让「编排方案不发送该字段」在调用点也是结构性的，不依赖下游把 `undefined` 过滤掉。
- **`handleDraftGateRejection` 只 toast + 重开弹层，绝不自动补 ack 静默重放**：重放必须让用户在新弹层里重新勾选，否则前端就替用户签了第二次名 —— 与 C.1 的不可协商不变量同源。
- **`ml-auto` / `ml-1` 共存写成模板内三元而不抽 computed**：既有状态 Badge 的 `:class="[badgeClass]"` 是 UI-SPEC Unresolved #3 明令本 phase 不顺手修的技术债，抽 computed 会诱导把两者一起重构并牵动既有 spec 断言。

## Deviations from Plan

### 主动补强（超出 plan 字面要求，均为验收强度而非新增范围）

**1. [Rule 2 - Missing Critical] `OrchestratedPlanCard.vue` 的 `:provenance` 接线**

- **Found during:** Task 1（plan 的 `files_modified` 只列了 4 个文件，第 79 行称「`OrchestratedPlanCard` 已在 109-04 传入」）
- **Issue:** 实读 109-04 的产物发现 `localProvenance` 确实**已存在**（投影响应带回并存了本地态），但**没有作为 prop 下传**给内嵌的 `TechPlanCard` —— 当时的注释明写「本 phase 不渲染它，仅作留痕」。若不补这一行，编排产出的方案在投影后会因拿不到 `provenance` 而落到保守分支：被误挂草稿横幅、送编码时多一次弹层。这直接推翻 must_have「编排方案零摩擦」，且是一个**不报错、不崩、只是多了摩擦**的静默失守点。
- **Fix:** 内嵌 `<TechPlanCard>` 补 `:provenance="localProvenance"`，并把 `localProvenance` 的注释从「本 phase 不渲染」改写为「109-08 起作为判定输入 —— 不传就会让编排产出落到保守分支」。
- **Files modified:** `web/src/components/chat/OrchestratedPlanCard.vue`
- **Verification:** `pnpm vitest run src/components/chat/__tests__/OrchestratedPlanCard.spec.ts` 及 chat 全量绿；`vue-tsc` 零错误。
- **Committed in:** `37c5306b`（Task 1 commit）

**2. 三条负控实测（plan 只要求正向用例）**

参照 109-06 / 109-07 建立的纪律（护栏断言最容易写成「断言当前实现」），对本 plan 的三条不可协商不变量各做一次负控：

| 负控改动 | 结果 | 恢复 |
|---|---|---|
| `isUnresearched` 允许清单 → 拒绝清单（`=== 'draft'`） | **7 failed / 53 passed** | 已原样恢复（`git diff` 空） |
| `resolvedProvenance` 的 `plan_id` 守卫 → 裸 `if (runtime)` | **1 failed / 59 passed**（精确命中串态用例） | 已原样恢复 |
| `ensureUnresearchedAcknowledged()` → 无条件 `return { proceed: true }` | **7 failed / 53 passed** | 已原样恢复 |

三次恢复后 `git status --short` 除 `.planning/STATE.md`（编排器职责）外为空，复跑 60 passed。

**3. 两条 plan 未点名的补充用例**

- `runtime.plan_id 匹配时采用 runtime.provenance（orchestrated ⇒ 免标注）` —— plan 只要求串态防护（不匹配时不采用）。缺这条正向对照的话，把第 2 级整个删掉也不会有任何测试转红（守卫会伪装成「恒不命中」而绿）。
- `esc / 遮罩关闭（update:open=false）等同取消，不提交` —— plan 只点了「取消弹层 → 不调任何提交」。`onUnresearchedDialogOpenChange` 的微任务兜底是本 plan 新增的一段非平凡逻辑（防 promise 悬挂 / 防把确认吞成取消），不锁的话删掉它不会转红。

### 未做（有意，附理由）

- **既有状态 Badge 的 `:class="[badgeClass]"` 违规未顺手修**：UI-SPEC Unresolved #3 与 plan Task 1 第 7 条均明令本 plan 不动它（重构会牵动既有 spec 断言且超边界）。新增的草稿徽标是纯 `variant`，未复制该形状。技术债保留。
- **legacy 单仓 `handleConfirm` 未加闸门**：UI-SPEC Unresolved #2 与 plan Task 2 第 8 条的既定边界，理由已写进该函数的 docstring。

---

**Total deviations:** 1 auto-fixed（Rule 2 missing-critical 接线）+ 2 主动补强（3 次负控实测、2 条补测），0 架构变更，0 Rule 4 触发
**Impact on plan:** 唯一的实现类偏离（`OrchestratedPlanCard` 接线）是 must_have「编排方案零摩擦」的必要条件，不是范围扩张。三个 task 各一次提交完成，未触发任何拆分。

## Issues Encountered

- **`vitest` 首跑 `EMFILE: too many open files, watch`**：macOS 默认 `ulimit -n` 过低，vitest 的 FSWatcher 打满句柄；更麻烦的是这条错误以 **Unhandled Rejection** 形式出现而进程**退出码仍为 0**，直接看退出码会把一次根本没跑起来的测试误判为通过。处置：`ulimit -n 20480` 后重跑，并改为断言输出里的 `Tests  N passed` 行而不是只看退出码。这条记下来给后续前端 plan 的执行者。

## Verification Results

| 命令 | 结果 |
|---|---|
| `pnpm vitest run src/components/chat src/stores`（任务书指定验证面） | **383 passed / 41 files** |
| `pnpm vitest run src/components/chat/__tests__/ src/composables/__tests__/`（plan 级 `<verification>`） | **349 passed / 35 files** |
| `pnpm vitest run src/components/chat/__tests__/TechPlanCard.spec.ts`（三个 task 的 per-task 验证） | **60 passed**（既有 40 + 新增 20） |
| `pnpm vue-tsc --noEmit -p tsconfig.json` | **退出码 0**、零行输出 |
| `pnpm eslint`（4 个改动源文件 + spec） | **退出码 0**，零 error |
| `git diff --exit-code web/pnpm-lock.yaml` | 退出码 0（零新增依赖） |
| `rg -n 'v-html' TechPlanCard.vue \| rg -v 'renderedPlan' \| rg -v 注释行` | 无匹配（退出码 1，无新增 `v-html` 面） |
| `rg -n 'acknowledge' TechPlanCard.vue stores/chat.ts api/chat.ts` | 18 处命中，逐处走查见上表，无未勾选即 true 的路径 |
| `rg -n 'detail' TechPlanCard.vue` | 3 处，全在注释里（无 detail 文案匹配代码） |
| `rg -n 'useConfirmDialog\|GlobalConfirmDialog' TechPlanCard.vue` | 1 处，在注释里说明「为何不复用」（无 import） |
| 负控 ①：允许清单 → 拒绝清单 | **7 failed**，已恢复并复跑 60 passed |
| 负控 ②：摘掉 `resolvedProvenance` 的 `plan_id` 守卫 | **1 failed**（精确命中串态用例），已恢复 |
| 负控 ③：闸门无条件放行 | **7 failed**，已恢复 |
| `git diff --diff-filter=D --name-only HEAD~3 HEAD` | 无输出（三次提交零文件删除） |

## Threat Model Coverage

| Threat ID | 落法 |
|---|---|
| T-109-08-01（Spoofing，前端伪造用户确认） | `acknowledge_unresearched: true` 在前端只有 `ensureUnresearchedAcknowledged()` 的确认分支这一个产生点；store 有条件放键、api 无默认值；三层各有源码级走查（18 处逐处列表）+ 负控实测（闸门无条件放行 → 7 failed） |
| T-109-08-02（Tampering，判定被软化成拒绝清单） | `isUnresearched` 是与 `'orchestrated'` 的不等于字面比较；四种保守分支各有用例；负控改成 `=== 'draft'` → 7 failed |
| T-109-08-03（Info Disclosure，`provenance` 原始取值上屏） | 任何情况不渲染原始取值；`wrapper.text()` 与 `wrapper.html()` 双重断言不含 `weird_value`；横幅/徽标/弹层文案全部前端常量 |
| T-109-08-04（Tampering，新增文案渲染面） | 新增横幅、徽标、弹层、必勾项一律 `{{ }}` 插值；源码级 `rg` 断言除既有 `renderedPlan` 外零 `v-html`（过滤注释行避免断言自我失效） |
| T-109-08-05（EoP，绕过前端弹层） | **transfer** —— 真防线是 109-07 的服务端 fail-closed gate。本 plan 显式不把前端当安全边界：组件注释开头即写明「服务端 fail-closed gate 是唯一真防线，本弹层只是 UX」；`code` 分支的兜底呈现正是「前端保守判定与后端不一致」时的收口 |
| T-109-08-06（Repudiation，错误分支误判） | 按 `ApiError.body.code` 判定；反向用例造了 `detail` 逐字相同但 `code` 不同的错误，断言不误报为草稿拒绝 |
| T-109-08-SC（供应链） | 零新增依赖，只复用既有 `ui/alert-dialog` / `ui/checkbox` / `ui/badge` / `ui/button`；未执行任何 `pnpm add` / `shadcn init` / `shadcn add`；`git diff --exit-code web/pnpm-lock.yaml` 退出码 0 |

## Observability

本 plan 为**纯前端渲染与交互路径**改动：无新增请求入口（复用既有 fan-out 端点，只在请求体上加一个可选布尔）、无新增 LLM 调用点（无 `call_source` 义务）、无新增召回（无 `RetrievalTrace` 义务）、无新增队列任务 / webhook。

- **留痕在服务端侧已就位，前端不重复上报**：草稿送编码的确认与拒绝两条事件（`draft_plan_coding_confirmed` / `draft_plan_coding_rejected`，均 `category="caller"` / `component="chat"`，带 `coding_plan_id` / `user_id`）已在 109-07 落地。fan-out 是 HTTP 入口 ⇒ 触发用户由统一中间件自动注入，`RequestMetric` 的 QPS / 错误率 / 时长自动覆盖新增的 400 分支。
- **「不发字段而非发 false」直接服务于留痕可信度**：这条前端纪律让后端日志里「带了 ack」严格等价于「用户确实在弹层里勾选过」，否则 `draft_plan_coding_confirmed` 会被无意义的 `false` 稀释成噪音。
- **无脱敏义务**：新增的仅是一个布尔字段与固定中文常量文案，不含凭证、不含方案正文；且前端**不回显**后端 `detail` 与 `provenance` 原始取值（gate 拒绝走前端常量 toast），从渲染侧也切断了上游文本上屏这条泄漏面。

## Known Stubs

无占位实现。以下是**按既定边界**不覆盖的出口，不是本 plan 的 stub：

- **legacy 单仓 `handleConfirm` 路径不加草稿闸门**（UI-SPEC §Unresolved #2）：仅在 `codingPlanId` 缺失时可达，此时前端无 `provenance`、服务端无 `plan_id` 可判定，且它确认的是**已存在**的 session。边界与理由写在该函数 docstring 里。
- **`TechPlanCard:350-357` 状态 Badge 的 `:class` 颜色违规**（UI-SPEC §Unresolved #3）：技术债保留，本 plan 未复制该形状。
- **`source_artifact_version_id` 的用户可见追溯**（UI-SPEC §Unresolved #9）：字段透出但不渲染，追溯 UI 留后续。

## User Setup Required

None —— 零新增依赖、零迁移、零外部服务配置。

## Next Phase Readiness

- **RELY-01 双侧闭合**：服务端 fail-closed gate + dispatch 标志 + 飞书导出告示（109-07）与界面横幅 + 头部徽标 + 阻断式确认弹层 + `code` 分支兜底（本 plan）合流，RELY-01 的两个出口（界面 / 飞书导出）与一道防线（服务端）全部就位。
- ⚠️ **存量方案将集体出现草稿标注 —— 这是预期行为，不是回归**：109-02 的迁移带 `default="draft"`，存量 `CodingPlan` 确实全是 SPINE-02 之前徒手创作的产物。因此升级后**所有历史方案卡**都会出现「未经调研」横幅与徽标、送编码时都会先弹一次确认。这正是 RELY-01 要达到的效果（保守标注在事实层就是对的）。**请 UAT / VERIFICATION 如实记录，不要判为缺陷。** 唯一需要观察的是观感冲击程度是否会让用户误判为故障。
- ⚠️ **`runtime.provenance` 是 `runtime.coding_plan` 的第三个消费点，`plan_id` 守卫已补齐**（109-06 / 109-07 两份提醒的落地确认）。**后续任何新增的 `runtime.coding_plan` 消费点都必须过同一道守卫**（UI-SPEC §Backstop 第 6 条）—— 目前已有四处同形实现（`feishuDocUrl` / `resolvedTechPlan` / `resolvedAffectedFiles` / `resolvedProvenance`）可逐字沿用。
- **第 2 级数据源的生产可用性取决于后端序列化面**：`ConversationRuntimeCodingPlanSerializer` 若尚未透出 `provenance`，则实际生效的是第 1 级（投影响应经 `OrchestratedPlanCard` 直接喂 props）与保守分支。这不影响正确性 —— 判定与守卫已就位且有用例锁，后端透出后自动生效；但 UAT 若想实测第 2 级需先确认后端序列化面已落（109-06 已记同一条）。
- **遗留给 UAT 的人工判断**（见 coverage D9）：编排链路端到端零摩擦路径（产出 → 进入编码 → 内嵌卡片、弹层不出现、无空窗）、草稿路径的弹层拦截与勾选解锁手感、导出物告示与界面主句的逐字一致观感（后端侧已有字面量断言锁住，人工只需确认「读起来是同一口径」）。
- **`vitest` 的 `EMFILE` 坑**：后续前端 plan 的执行者请注意 —— 该错误以 Unhandled Rejection 出现但进程退出码为 0，只看退出码会把「根本没跑起来」误判为通过。先 `ulimit -n 20480`，并断言输出里的 `Tests  N passed` 行。

## Self-Check: PASSED

- 5 个改动文件均存在于磁盘且已提交：`TechPlanCard.vue` / `OrchestratedPlanCard.vue` / `stores/chat.ts` / `api/chat.ts` / `TechPlanCard.spec.ts`
- 三个 task commit 均可在 `git log` 中定位：`37c5306b` / `be2f6605` / `0149964b`
- `git diff --diff-filter=D --name-only HEAD~3 HEAD` 无输出（三次提交零文件删除）
- 三次负控实测后的组件源码均已原样恢复（`git diff web/src/components/chat/TechPlanCard.vue` 空），复跑 60 passed
- 验证命令均**实际执行**：`vitest`（383 / 349 / 60 passed）、`vue-tsc`（退出码 0、零输出）、`eslint`（退出码 0）、`pnpm-lock` diff（退出码 0）—— 无一条为推断或复述
- 未修改 `.planning/ROADMAP.md`（由本 plan 收尾时按任务书指令调用 `roadmap.update-plan-progress` 更新）

---
*Phase: 109-spine-convergence*
*Completed: 2026-07-31*
