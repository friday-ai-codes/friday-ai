---
phase: 91-clarification-outlets-resume
plan: 05
subsystem: ui
tags: [clarification, chat, vue3, i18n, multi_select, tdd, frontend, plan_orchestration]

# Dependency graph
requires:
  - phase: 91-04
    provides: runtime 新键 pending_plan_clarification（结构化轮 questions[]）+ 会话端专路由 POST /api/chat/conversations/{id}/plan-clarification/answer/
  - phase: 90-02
    provides: ClarificationQuestion 结构化模型（qtype/options/recommended/selected/freeform_text）
provides:
  - 前端类型 PlanClarificationPayload / PlanClarificationAnswerRequest（多题多选契约）
  - api postPlanClarificationAnswer(conversationId, {answers}) 命中 91-04 专路由
  - ClarificationCard.vue 多题多选扩展（按 payload 形态分支，chat 单题零回归）
  - store pendingPlanClarifications（conversation 维度隔离）+ markPlanClarificationAnswered + runtime 回灌
  - 守护 spec ClarificationCard.spec.ts（Wave 0 缺口补齐）
affects: [94 入口统一, 会话端 plan 澄清 UI 后续迭代]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "出口面前端物理隔离：同一 ClarificationCard 按 payload 形态（含 questions[]）分支渲染 plan 多题轮 vs chat 单题轮，两条路径互不串"
    - "i18n 守护：spec 以真实 zh-CN.json 作 createI18n messages，锁关键文案不被改空（Phase 24 范式）"
    - "多选 Set 语义：整行 button 承接点击 toggle，Checkbox 组件作只读视觉指示（pointer-events-none）"

key-files:
  created:
    - web/src/components/chat/__tests__/ClarificationCard.spec.ts
  modified:
    - web/src/types/clarification.ts
    - web/src/types/chat.ts
    - web/src/api/chat.ts
    - web/src/stores/chat.ts
    - web/src/components/chat/ClarificationCard.vue
    - web/src/components/chat/ChatMessageArea.vue
    - web/src/locales/zh-CN.json

key-decisions:
  - "扩展现有 ClarificationCard 而非新建专组件（CONTEXT 锁定）：以 isPlan = Array.isArray(payload.questions) 判别，plan/chat 两分支共用头部/底部壳"
  - "多选用整行 button 承接 toggle + Checkbox 只读视觉（pointer-events-none），既满足 A5「用 Checkbox 组件」又保证测试可点击稳定"
  - "store 新增独立 Map pendingPlanClarifications 与单题 pendingClarifications 物理隔离；runtime 回灌仅在 questions 非空时进 plan 面（与 91-04「旧单题行不渲染 plan 卡」对齐）"
  - "组件直调 api postPlanClarificationAnswer（mirror 既有 postClarificationAnswer 范式）+ store markPlanClarificationAnswered，满足 key_links 契约"

patterns-established:
  - "Pattern: 单组件按 payload 形态分支承载多种澄清轮，store 各持独立 conversation 维度 Map 防跨会话串渲染"
  - "Pattern: 前端守护 spec 以真实 locale json 作 i18n messages 断言关键文案存在（反 i18n 改空）"

requirements-completed: [CLARIFY-04]

# Metrics
duration: ~18min
completed: 2026-06-27
---

# Phase 91 Plan 05: AI 会话出口面前端（plan 多题多选澄清卡）Summary

**扩展 `ClarificationCard.vue` 按 payload 形态分支渲染 plan 结构化多题轮（每题 single button / multi Checkbox + ⭐推荐默认选中 + 每题可选自由输入），聚合 `answers:[{question_id,selected,freeform_text}]` 打 91-04 专路由 `postPlanClarificationAnswer`，提交后切「已回复」，与既有 chat 单题澄清卡共存物理隔离、零回归。**

## Performance

- **Duration:** ~18 min
- **Started:** 2026-06-27T09:02:00Z
- **Completed:** 2026-06-27T09:20:00Z
- **Tasks:** 2（Task 2 为 TDD：RED → GREEN）
- **Files modified:** 8（1 新建 spec + 7 改）

## Accomplishments
- **前端契约接线（CLARIFY-04）**：`types/clarification.ts` 新增 `PlanClarificationQuestion`/`PlanClarificationPayload`/`PlanClarificationAnswerItem`/`PlanClarificationAnswerRequest`（与 chat 单题 `ClarificationPayload` 并存不改既有）；`api/chat.ts` 新增 `postPlanClarificationAnswer(conversationId, {answers})` 打专路由 `POST /chat/conversations/{id}/plan-clarification/answer/`；`types/chat.ts` 的 `ConversationRuntime` 增 `pending_plan_clarification` 透传字段。
- **store 接 runtime 新键（conversation 维度隔离）**：`stores/chat.ts` 新增独立 `pendingPlanClarifications` Map + `upsertPlanClarification`/`getPlanClarification`/`markPlanClarificationAnswered`；`restoreConversationRuntime` 回灌 `pending_plan_clarification`（仅 questions 非空时），切换/fork 会话时一并清空防串台。
- **多题多选渲染（CLARIFY-04 / Pattern 1）**：`ClarificationCard.vue` 按 `isPlan`（payload 含 `questions[]`）分支——多题 `v-for`，每题 `qtype==='single'` 走 button radiogroup（独立 selectedId）/`qtype==='multi'` 走整行 button toggle + `Checkbox` 只读视觉（Set 语义），⭐推荐项标记 + 默认选中（single 取 recommended[0]、multi 取全部 recommended）+ 每题可选 `Textarea` freeform；提交聚合 answers[]（single=str / multi=string[]）→ `postPlanClarificationAnswer` → `markPlanClarificationAnswered`。`ChatMessageArea.vue` 增 plan 澄清卡渲染分支（`visiblePlanClarifications` 按 conversation 过滤），与单题卡共存不串。
- **i18n 默认中文 + 守护**：新增 `chat.clarification` 文案区（title/recommended/multiHint/submit/freeform 等）进 `zh-CN.json`，组件全程 `t(...)`；新建 spec 以真实 `zh-CN.json` 作 `createI18n` messages，锁「推荐」「提交答复」「可多选」不被改空。
- **TDD 守护 spec（Wave 0 缺口）**：`__tests__/ClarificationCard.spec.ts` 6 用例——多题渲染 + 单/多选默认选中推荐 + 切换语义 + answers[] 聚合提交 + 提交切已回复 + i18n 真实文案 + 既有单题路径零回归。

## Task Commits

Each task was committed atomically:

1. **Task 1: 前端类型/api/store 接线 plan 多题轮** - `42d0bd011` (feat)
2. **Task 2 (RED): 新增 ClarificationCard 多题多选守护用例** - `9b99ba42a` (test)
3. **Task 2 (GREEN): ClarificationCard 多题多选渲染 + answers[] + i18n** - `761d940c1` (feat)

**Plan metadata:** (final docs commit)

## Files Created/Modified
- `web/src/types/clarification.ts` - 新增 plan 多题多选类型（PlanClarificationPayload/AnswerRequest 等），与 chat 单题类型并存
- `web/src/types/chat.ts` - `ConversationRuntime` 增 `pending_plan_clarification` 结构化轮透传字段
- `web/src/api/chat.ts` - 新增 `postPlanClarificationAnswer` 打 91-04 专路由 + 默认导出
- `web/src/stores/chat.ts` - 独立 `pendingPlanClarifications` Map + upsert/get/markAnswered + runtime 回灌 + 切换/fork 清理
- `web/src/components/chat/ClarificationCard.vue` - 按 payload 形态分支：plan 多题多选渲染 + answers[] 聚合提交；chat 单题路径零回归（文案改 t(...)）
- `web/src/components/chat/ChatMessageArea.vue` - 增 `visiblePlanClarifications` + plan 澄清卡渲染分支（conversation 维度过滤）
- `web/src/locales/zh-CN.json` - 新增 `chat.clarification` 文案区（默认中文）
- `web/src/components/chat/__tests__/ClarificationCard.spec.ts` - 新建 6 守护用例（TDD）

## Decisions Made
- **扩展而非新建组件**：CONTEXT 锁定「扩展现有 ClarificationCard」，以 `isPlan` 判别两分支共用头/底壳，避免回归面扩大。
- **多选交互**：整行 button 承接 toggle + `Checkbox` 只读视觉（pointer-events-none），满足 A5「用 Checkbox」且测试点击稳定，避免 reka-ui Checkbox 与行 button 双重 toggle。
- **store 独立 Map + runtime 回灌守门**：plan 澄清独立 `pendingPlanClarifications`，runtime 仅在 `questions` 非空时回灌（对齐 91-04 旧单题行不进 plan 面），按 conversation 维度防跨会话串。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] ConversationRuntime 增 pending_plan_clarification 类型字段**
- **Found during:** Task 1（store runtime 回灌）
- **Issue:** plan Task 1 的 `files_modified` 未列 `types/chat.ts`，但 store 从 `runtime.pending_plan_clarification` 读数据需要类型声明，否则 `vue-tsc` 报未知字段、前端拿不到数据。
- **Fix:** `ConversationRuntime` 增 `pending_plan_clarification?` 可空结构化轮字段（mirror 既有 `pending_clarification`）。
- **Files modified:** web/src/types/chat.ts
- **Verification:** `pnpm vue-tsc --noEmit` 通过。
- **Committed in:** `42d0bd011`（Task 1 commit）

---

**Total deviations:** 1 auto-fixed（1 missing critical）
**Impact on plan:** 仅补齐 runtime 数据出 API 后前端读取的必要类型声明，无 scope creep；归入 Task 1 接线语义。

## Issues Encountered
- **执行环境恢复**：执行期间工作树存在大量**与本 plan 无关的预存未提交改动**（server/* 与 web/* 多文件，来自他人/其他分支 WIP）。各 task commit 严格只 `git add` 本 plan 8 个目标文件，未污染无关改动。

## Deferred Issues（out-of-scope）
- `web/src/components/__tests__/ProviderCredentialForm.spec.ts` 2 个用例失败（available_models emit 断言），与本 plan 无关、由工作树预存的 ProviderCredentialForm 相关未提交改动引发，非本 plan 触碰文件（`git diff --name-only` 确认本 plan 仅改 8 个 chat/类型/locale 文件）。按 SCOPE BOUNDARY 不在本 plan 修复范围。

## Threat Surface Scan
threat_model 两项 mitigate 均落实：
- **T-91-05-02（Info Disclosure 跨会话串渲染）**：`pendingPlanClarifications` 按 conversation_id 维度绑定（store upsert 回退当前会话），`ChatMessageArea` 的 `visiblePlanClarifications` 按 `currentConversationId` 过滤（mirror 既有 pendingClarifications 防污染模式）。
- **T-91-05-03（Spoofing i18n 文案被改空）**：spec 以真实 `zh-CN.json` 作 messages 断言「推荐/提交答复/可多选」存在。
- **T-91-05-01（Tampering 越界 answers，accept）**：前端为非权威面，仅组装 UI 选择；越界/越权由 91-04 服务端 owner gate + question_id 归属校验把关（前端不做最终防线）。

无新增网络入口/schema/认证面（仅消费 91-04 已有 endpoint + runtime key）。

## Known Stubs
None - 本 plan 渲染真实 runtime `pending_plan_clarification` 数据并提交至 91-04 专路由，无 mock 数据 / 占位。

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- 会话端 CLARIFY-04 前端闭环就绪：runtime 暴露结构化轮 → ClarificationCard 渲染多题多选 → 提交到 91-04 专路由 → 后台续推方案生成。
- 验收全绿：`ClarificationCard.spec.ts`(6) 全 pass；`src/components/chat` + `src/stores`(267) 无回归；`pnpm vue-tsc --noEmit` 通过；受改文件 `pnpm eslint` 干净。
- 94 入口统一可复用本 plan 的 `PlanClarificationPayload` 类型 + ClarificationCard 多题分支。

---
*Phase: 91-clarification-outlets-resume*
*Completed: 2026-06-27*

## Self-Check: PASSED
- FOUND: web/src/types/clarification.ts（PlanClarificationPayload/AnswerRequest）
- FOUND: web/src/api/chat.ts（postPlanClarificationAnswer）
- FOUND: web/src/stores/chat.ts（pendingPlanClarifications + markPlanClarificationAnswered + runtime 回灌）
- FOUND: web/src/components/chat/ClarificationCard.vue（plan 多题多选分支）
- FOUND: web/src/components/chat/ChatMessageArea.vue（plan 澄清卡渲染分支）
- FOUND: web/src/locales/zh-CN.json（chat.clarification 文案区）
- FOUND: web/src/components/chat/__tests__/ClarificationCard.spec.ts
- FOUND: .planning/phases/91-clarification-outlets-resume/91-05-SUMMARY.md
- FOUND commit 42d0bd011 (Task 1 feat)
- FOUND commit 9b99ba42a (Task 2 RED test)
- FOUND commit 761d940c1 (Task 2 GREEN feat)
- 验收：ClarificationCard.spec.ts(6) 全 pass；src/components/chat + src/stores(267) 无回归；vue-tsc --noEmit 通过；受改文件 eslint 干净。预存无关 ProviderCredentialForm 失败 out-of-scope。
