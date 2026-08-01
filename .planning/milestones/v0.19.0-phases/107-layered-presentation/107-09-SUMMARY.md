---
phase: 107-layered-presentation
plan: 09
subsystem: ui
tags: [vue3, routing-panel, grouped-presentation, cross-group, degraded-banner, pinia-store, a11y, tdd]

# Dependency graph
requires:
  - phase: 107-layered-presentation
    provides: "107-08 的 detail payload 9 键与 override 响应 4 键回传（router_version / degraded / degrade_reason / block_order）；107-03 的 6 值 degrade_reason 闭集与 block_order 结果级字段；107-07 的候选级 group / trust / score_ranked 透传链"
  - phase: 106-signal-expansion
    provides: "RoutingDecisionPanel 的 SIGNAL_LABELS 硬编码中文 map 惯例与分数分解展开区"
provides:
  - "web 端路由候选按后端 block_order 分区呈现（本项目关联仓 / 全局候选），区内按 score_ranked ?? score 降序，空组不渲染"
  - "每组 Top-3 + 已选候选 pin-in + 溢出披露（显示其余 n 个候选）"
  - "跨组两层标注（组级常驻说明句 + 候选级 info 徽标带 aria-label 完整句）与迟滞置顶提示条（role=status）"
  - "降级横幅（role=alert / aria-live=polite）+ 6 值中文原因闭集 + 徽标灰化 + 折叠态降级徽标"
  - "前端数据契约：RoutingGroup / RoutingTrust / RoutingDegradeReason 三类型 + 候选 4 个与 trace 4 个 optional 字段 + ManualOverrideResponse 4 键"
  - "applyManualOverride 的「响应优先 + original 兜底」四键继承（Pitfall 3 前端半边闭合）"
affects: [109, 110, 107-UAT]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "呈现顺序的权威在后端：前端只按 block_order 分区、按 score_ranked 排序，绝不做全局重排——一次 sort 就能悄悄推翻后端的分组与置顶决策"
    - "旁路排序分不进可见文案：score_ranked 只喂 sort，徽标与分数分解合计继续用 score，避免「徽标 87% 却排在 91% 前面」的无法解释现象"
    - "受控枚举的未命中回退分两类：可扩展枚举（信号名）回显原始 key 求前向兼容，异常分类枚举（降级原因）一律回退固定文案，因为回显即泄漏面"
    - "折叠态不得吞掉可信度事实：面板收起时用紧凑徽标承载降级，展开态由横幅承载，两者互斥不重复"
    - "pin-in 优先于 Top-N 截断：候选行承载 Checkbox 时，隐藏已选项等于让用户无法取消勾选"
    - "本地折叠态用 `ref<boolean | null>`：null = 跟随派生默认态，用户点过后本地态优先，trace 变化时置回 null 重算——比「初始化时快照默认值」少一个「trace 迟到」的错态"

key-files:
  created: []
  modified:
    - web/src/types/routing.ts
    - web/src/stores/routing.ts
    - web/src/stores/chat.ts
    - web/src/components/chat/RoutingDecisionPanel.vue
    - web/src/stores/__tests__/routing.test.ts
    - web/src/components/chat/__tests__/RoutingDecisionPanel.test.ts

key-decisions:
  - "删除 sortedCandidates 的全局 score 重排（Pitfall 4）：改为「按 block_order 分区 → 区内 score_ranked ?? score 降序 → repository_id 升序 tie-break」，区顺序前端零重排"
  - "applyManualOverride 用 ?? 而非 || 做兜底：响应显式给 degraded=false 时不能被 original 的 true 盖回（|| 会把 false 当缺失）"
  - "deep_analysis 分支不补四键：该链的 payload 只有候选数组，结果级事实压根不存在 → 一律留 undefined，填 false 等于把「未知」谎报成「没降级过」"
  - "全局组折叠与溢出披露改用原生 button + aria-expanded + v-if，而非 Collapsible（详见 Deviations 第 1 条）"
  - "跨组说明句渲染在折叠区之外：全局组收起时说明句仍可见，符合 UI-SPEC「常驻可见、不依赖 hover」"
  - "trust 不渲染第二个徽标：本 phase 与 group === 'global' 语义完全重合，双份同义标注是噪音"
  - "degradeReasonLabel 的未命中回退与 signalLabel 刻意相反：一律「未知原因」，绝不回显原始值（T-107-02）"

patterns-established:
  - "归零断言与注释共存的纪律：`v-html` / `degraded: false` 这类被断言归零的字面量不写进注释（改写措辞），而不是放宽断言"
  - "script setup 的派生函数经 wrapper.vm 断言：Tooltip 内容未打开时不入 DOM，直接测喂给它的 confidenceTooltip(level) 比模拟 hover 稳"

requirements-completed: [ROUTE-01, ROUTE-02, RELY-03]

coverage:
  - id: D1
    description: "区顺序严格等于后端 block_order、区内按 score_ranked ?? score 降序、全局重排代码删除（Pitfall 4 闭合）"
    requirement: "ROUTE-01"
    verification:
      - kind: unit
        ref: "web/src/components/chat/__tests__/RoutingDecisionPanel.test.ts#区顺序严格等于后端 block_order（global 置顶时全局组标题先出现）"
        status: pass
      - kind: unit
        ref: "web/src/components/chat/__tests__/RoutingDecisionPanel.test.ts#区内按 score_ranked 降序（与 score 顺序相反时以 score_ranked 为准）"
        status: pass
      - kind: unit
        ref: "web/src/components/chat/__tests__/RoutingDecisionPanel.test.ts#score_ranked 为 null / 缺失 → 回退 score 参与排序（混合不抛）"
        status: pass
      - kind: other
        ref: "rg -c 'b\\.score - a\\.score' web/src/components/chat/RoutingDecisionPanel.vue == 0"
        status: pass
    human_judgment: false
  - id: D2
    description: "Top-3 截断 + 已选候选 pin-in + 溢出披露 trigger 文案 + 组标题计数为组总数"
    requirement: "ROUTE-01"
    verification:
      - kind: unit
        ref: "web/src/components/chat/__tests__/RoutingDecisionPanel.test.ts#每组 Top-3 截断 + 已选候选 pin-in；溢出 trigger 文案与组标题总数"
        status: pass
    human_judgment: false
  - id: D3
    description: "全局组默认折叠两分支（本项目在前且首位高置信 → 折叠；否则展开）+ 用户操作后本地态优先 + trace 变化重算"
    requirement: "ROUTE-01"
    verification:
      - kind: unit
        ref: "web/src/components/chat/__tests__/RoutingDecisionPanel.test.ts#本项目在前且首位高置信 → 全局组默认折叠（标题在、候选不可见）"
        status: pass
      - kind: unit
        ref: "web/src/components/chat/__tests__/RoutingDecisionPanel.test.ts#本项目首位非高置信 → 全局组默认展开"
        status: pass
      - kind: unit
        ref: "web/src/components/chat/__tests__/RoutingDecisionPanel.test.ts#用户手动展开后本地态优先；trace 变化后重算默认态"
        status: pass
    human_judgment: false
  - id: D4
    description: "跨组两层标注（组级常驻说明句 + 每个全局候选的 info 徽标带 aria-label 完整句；本项目候选无徽标；缺 group 视为 global）"
    requirement: "ROUTE-02"
    verification:
      - kind: unit
        ref: "web/src/components/chat/__tests__/RoutingDecisionPanel.test.ts#跨组两层：组级说明句常驻 + 每个全局候选带跨组 Badge（本项目候选无）"
        status: pass
      - kind: unit
        ref: "web/src/components/chat/__tests__/RoutingDecisionPanel.test.ts#缺 group 的候选视为 global（分组启用时也带跨组 Badge）"
        status: pass
    human_judgment: false
  - id: D5
    description: "迟滞置顶提示按 block_order[0] 出现/消失（role=status），与降级横幅并存时降级在上"
    requirement: "ROUTE-02"
    verification:
      - kind: unit
        ref: "web/src/components/chat/__tests__/RoutingDecisionPanel.test.ts#block_order[0]===global → 出现 role=status 置顶提示；in_project 在前则无"
        status: pass
      - kind: unit
        ref: "web/src/components/chat/__tests__/RoutingDecisionPanel.test.ts#降级横幅在 query 行与置顶提示之上（并存时降级在上）"
        status: pass
    human_judgment: false
  - id: D6
    description: "降级横幅（role=alert / aria-live=polite）+ 6 值中文原因闭集 + 原因缺失只出主句 + 非受控值回退「未知原因」且 DOM 无原始串"
    requirement: "RELY-03"
    verification:
      - kind: unit
        ref: "web/src/components/chat/__tests__/RoutingDecisionPanel.test.ts#degraded=true → amber 告警条（role=alert / aria-live=polite）含主句"
        status: pass
      - kind: unit
        ref: "web/src/components/chat/__tests__/RoutingDecisionPanel.test.ts#6 个受控 degrade_reason 各自渲染对应中文次行"
        status: pass
      - kind: unit
        ref: "web/src/components/chat/__tests__/RoutingDecisionPanel.test.ts#degrade_reason 缺失 → 只出主句，不渲染原因次行"
        status: pass
      - kind: unit
        ref: "web/src/components/chat/__tests__/RoutingDecisionPanel.test.ts#degrade_reason 为非受控值 → 回退「未知原因」，DOM 不含原始串"
        status: pass
    human_judgment: false
  - id: D7
    description: "降级态徽标灰化（variant=muted）+ Tooltip 换降级三句 + 折叠态降级徽标；level / score / 分数分解合计不变"
    requirement: "RELY-03"
    verification:
      - kind: unit
        ref: "web/src/components/chat/__tests__/RoutingDecisionPanel.test.ts#degraded=true → 全部 confidence 徽标 variant=muted，百分比仍取 score"
        status: pass
      - kind: unit
        ref: "web/src/components/chat/__tests__/RoutingDecisionPanel.test.ts#degraded 切换 confidence Tooltip 文案；未降级沿用既有三句"
        status: pass
      - kind: unit
        ref: "web/src/components/chat/__tests__/RoutingDecisionPanel.test.ts#面板折叠时标题行仍渲染 Badge warning「降级」"
        status: pass
      - kind: unit
        ref: "web/src/components/chat/__tests__/RoutingDecisionPanel.test.ts#degraded 下 level / score / 分数分解合计一律不变"
        status: pass
      - kind: other
        ref: "rg -n 'score_ranked' RoutingDecisionPanel.vue | rg -c 'toFixed|Math.round' == 0"
        status: pass
    human_judgment: false
  - id: D8
    description: "override 不丢字段（Pitfall 3 前端半边）：响应优先 + original 兜底继承四键，候选保留 group / trust / score_ranked，original 缺失不抛"
    requirement: "ROUTE-01"
    verification:
      - kind: unit
        ref: "web/src/stores/__tests__/routing.test.ts#响应缺四键 → 从 original 兜底继承（降级横幅与分区不消失）"
        status: pass
      - kind: unit
        ref: "web/src/stores/__tests__/routing.test.ts#响应带四键 → 响应值优先（degraded=false 不被 original 的 true 覆盖）"
        status: pass
      - kind: unit
        ref: "web/src/stores/__tests__/routing.test.ts#override 后候选保留 group / trust / score_ranked"
        status: pass
      - kind: unit
        ref: "web/src/stores/__tests__/routing.test.ts#original 不在 store 且响应也没给 → 四键为 undefined，不抛"
        status: pass
    human_judgment: false
  - id: D9
    description: "三条链路透传：detail hydrate 整对象透传、chat_tool 补四键、deep_analysis 不填假值"
    requirement: "RELY-03"
    verification:
      - kind: unit
        ref: "web/src/stores/__tests__/routing.test.ts#upsertTrace 整对象透传（detail hydrate 契约：不得改成字段白名单）"
        status: pass
      - kind: integration
        ref: "web/src/stores/__tests__/routing.test.ts#chat_tool：工具 data 含四键 → 构造的 trace 携带四键"
        status: pass
      - kind: integration
        ref: "web/src/stores/__tests__/routing.test.ts#deep_analysis：无结果级四键 → 四键为 undefined（不填假值）"
        status: pass
    human_judgment: false
  - id: D10
    description: "历史 trace 与无项目上下文入口保持平铺渲染（无组标题 / 跨组徽标 / 提示条），空组不渲染，既有 12 个用例零回归"
    verification:
      - kind: unit
        ref: "web/src/components/chat/__tests__/RoutingDecisionPanel.test.ts#历史 trace（无 block_order / group / score_ranked）→ 单个平铺 ul、零新增标注"
        status: pass
      - kind: unit
        ref: "web/src/components/chat/__tests__/RoutingDecisionPanel.test.ts#block_order 长度 1（无项目上下文）→ 平铺、无组标题与跨组标注"
        status: pass
      - kind: unit
        ref: "web/src/components/chat/__tests__/RoutingDecisionPanel.test.ts#空组不渲染（block_order 长度 2 但全局组 0 条）"
        status: pass
      - kind: unit
        ref: "web/src/components/chat/__tests__/RoutingDecisionPanel.test.ts#block_order 缺失但存在 in_project 候选 → 按 [in_project, global] 启用分组"
        status: pass
      - kind: other
        ref: "cd web && pnpm vitest run src/components/chat src/stores → 324 passed（40 files）"
        status: pass
    human_judgment: false
  - id: D11
    description: "视觉零漂移：零新依赖 / 零新 ui 组件 / 零新色板（仅 amber-500 与 teal-500·700 两族）/ 无 Badge :class 追加颜色 / 无原始 HTML 注入"
    verification:
      - kind: other
        ref: "git diff --name-only <plan range> 恰 6 个文件，无 package.json / pnpm-lock.yaml / src/components/ui/"
        status: pass
      - kind: other
        ref: "rg -o 'amber-[0-9]+|teal-[0-9]+' RoutingDecisionPanel.vue | sort -u == 3 值；rg '<Badge' -A 2 | rg -c ':class' == 0；rg -c 'v-html' == 0；rg -c 'cross_group_note' == 0"
        status: pass
      - kind: other
        ref: "pnpm exec vue-tsc --noEmit 干净；pnpm exec eslint（types/routing.ts、stores/routing.ts、stores/chat.ts、RoutingDecisionPanel.vue）零报错"
        status: pass
    human_judgment: false
  - id: D12
    description: "人工视觉验收：两组分区 / 跨组徽标 / 置顶提示 / 降级横幅与徽标灰化与 107-UI-SPEC 的间距·字号·配色一致"
    verification: []
    human_judgment: true
    rationale: "视觉一致性（含玻璃底卡片内的对比度、组标题与候选行的缩进观感、amber/teal 提示条在真实数据密度下是否过载）无法由 DOM 断言证明，需在真实对话页对照 UI-SPEC 目视确认；记入 107-UAT"

# Metrics
duration: 24min
completed: 2026-07-30
status: complete
---

# Phase 107 Plan 09: 分层呈现的前端可见面 Summary

**候选列表从「一条按 score 重排的平铺列表」变成「按后端 `block_order` 分区、区内按 `score_ranked` 排序、Top-3 + 已选 pin-in 的两区呈现」，全局组带常驻跨组说明句与候选级「跨组」徽标、迟滞置顶时给出因果提示条，路由降级时先出 amber `role="alert"` 横幅（6 值中文原因闭集、非受控值一律「未知原因」）并把全部 confidence 徽标灰化、收起面板也仍留一枚「降级」徽标；同时修掉两个必修既有缺陷——覆盖后端决策的全局重排与 override 重建 trace 丢四键。**

## Performance

- **Duration:** 约 24 min
- **Started:** 2026-07-30T00:13:00Z
- **Completed:** 2026-07-30T00:37:00Z
- **Tasks:** 3（全部走 TDD：RED → GREEN，无 REFACTOR 轮）
- **Files modified:** 6（新建 0）

## Accomplishments

- **前端不再推翻后端的路由决策（Pitfall 4 闭合）。** `sortedCandidates` 的全局 `score` 重排被删除，改为 `groupedBlocks`：区顺序**严格**等于 `block_order`（前端零重排），区内按 `score_ranked ?? score` 降序、同分按 `repository_id` 升序 tie-break（与后端同口径，保证渲染稳定）。守护它的用例构造了「`score_ranked` 与 `score` 排序相反」的候选：实现若回退成按 `score` 排就红。`score_ranked` **只**喂 sort——徽标百分比与分数分解合计仍用 `score`（有静态断言：含 `score_ranked` 的行不得同时含 `toFixed` / `Math.round`），避免「徽标 87% 却排在 91% 前面」的无法解释现象。
- **用户改一次勾选后降级横幅与分区不再消失（Pitfall 3 前端半边闭合）。** `applyManualOverride` 重建 trace 时四个 trace 级事实改为「响应优先、`original` 兜底」，且刻意用 `??` 而非 `||`——后者会把响应显式给的 `degraded=false` 当成缺失、被 `original` 的 `true` 盖回。有一条专门断言 `false` 不被覆盖的用例。候选级 `group` / `trust` / `score_ranked` 由后端浅拷保留（107-08 已有断言），前端补了一条渲染侧的对应断言。
- **分组呈现的四条判定全部落地且各有用例。** 启用条件只看 `block_order?.length === 2`（后端契约：有项目上下文时恒为长度 2，即使一组为空），长度 1 → 平铺（此时标「跨组」反而误导），完全缺失时才按候选自带 `group === 'in_project'` 兜底；空组整块不渲染；组标题计数是该组**总数**而非可见数；全局组默认折叠判定 = 本项目在前 **且** 本项目首位高置信。
- **Top-3 叠加 pin-in 是硬要求而非优化。** 可见集 = `Top-3 ∪ (selected_by_ai || selected_by_user_final)`——候选行承载 `Checkbox`，被折叠的已选候选将无法取消勾选，用户还会看到「勾了的仓不见了」。用例构造「5 个候选、排第 5 的已被用户勾选」，断言可见 4 个、溢出 trigger 文案为「显示其余 1 个候选」、组标题仍显示总数 5。
- **跨组标注做成两层，且组级说明句不被折叠吞掉。** 组级完整句「未关联当前平台，可能涉及跨组协作」渲染在折叠区**之外**（全局组收起时仍可见，符合 UI-SPEC「常驻可见、不依赖 hover」）；候选级是 `Badge variant="info"`「跨组」，完整句由 `Tooltip` 与 `aria-label` 承载。缺 `group` 的候选按 `'global'` 处理，同样带徽标。`trust` 不渲染第二个徽标（本 phase 与 `group === 'global'` 语义完全重合）。
- **降级三件套：横幅、灰化、折叠也藏不住。** `degraded === true`（后端派生的事实，前端零推断）时，在**候选之前**渲染 amber `role="alert" aria-live="polite"` 横幅（DOM 形状逐字沿用 `CommitConfirmCard.vue:100-105`），主句 + 中文原因次行；全部 confidence 徽标 `variant` 降为 `muted`、Tooltip 换降级三句，而 `level` / `score` / `breakdown` 与 1e-6 容差 `console.warn` 一律未动；面板收起时标题行留一枚 `Badge variant="warning"`「降级」（展开态由横幅承载，两者互斥不重复）。
- **降级原因不给原始异常文本任何回显路径（T-107-02 前端最后一道）。** `DEGRADE_REASON_LABELS` 是 6 值闭集，未命中一律回退「未知原因」——与同文件 `signalLabel`「回显原始英文 key」的惯例**刻意相反**，函数上方注释写明差异与理由（信号名是可扩展枚举，降级原因的上游是异常分类）。用例注入 `'APIStatusError: sk-ant-abc123'`，断言渲染「降级原因：未知原因」且 `wrapper.html()` **不含** `sk-ant-` 与 `APIStatusError`。后端自由文本字段（候选级留痕说明）在组件里零引用（静态断言），所有新文案走 `{{ }}` 插值。
- **历史 trace 逐像素兼容有据可查。** 无 `block_order` / `group` / `score_ranked` / `degraded` 的 trace 走平铺分支：单个 `ul`、不截断、无组标题、无跨组徽标、无提示条、按 `score` 降序，既有 12 个用例逐字未改且全绿；定向套 `src/components/chat` + `src/stores` 共 **324 passed**（40 files）。

## Task Commits

1. **Task 1: 类型契约 + store 透传与 override 兜底继承** — `9d206f3e` (test, RED：3 failed / 10 passed) → `e0122d3a` (feat, GREEN：13 passed)
2. **Task 2: 分区渲染 + Top-3/pin-in/折叠 + 跨组标注 + 置顶提示** — `264fdf27` (test, RED：10 failed / 16 passed) → `bd02216e` (feat, GREEN：26 passed)
3. **Task 3: 降级横幅 + 徽标灰化 + 折叠态徽标 + 文案闭集** — `91c25548` (test, RED：8 failed / 28 passed) → `eaef7bff` (feat, GREEN：36 passed)

_三个 task 的 REFACTOR 轮均无改动（GREEN 实现即最终形态）。各 RED 阶段有若干新增用例即为绿——它们是**兜底行为的回归守护**（`score_ranked` 缺失回退 `score`、`block_order` 长度 1 平铺、历史 trace 平铺、`degraded` 缺失零提示、override 后候选字段不丢），守护的是既有行为而非本 plan 的新行为，故不视为 RED 失效。_

## Files Created/Modified

- `web/src/types/routing.ts` — 新增 `RoutingGroup` / `RoutingTrust` / `RoutingDegradeReason`（6 值闭集，注释写明「闭集本身即编译期泄漏防线」）；`RoutingCandidate` 加 `group?` / `trust?` / `score_ranked?: number | null` / 后端留痕用的自由文本字段（注释标注**前端不渲染**）；`RoutingDecisionData` 与 `ManualOverrideResponse` 各加 `router_version?` / `degraded?` / `degrade_reason?` / `block_order?`。全部 optional（历史 trace 兼容）。
- `web/src/stores/routing.ts` — `applyManualOverride` 的 `newTrace` 从 5 键补到 9 键，四个新键走「响应优先 + `original` 兜底」；注释写明因果与「为何是 `??` 不是 `||`」。
- `web/src/stores/chat.ts` — `chat_tool` 分支的 `data` 类型补四键并按类型守卫透传（`typeof` / `Array.isArray` 检查，缺则 `undefined`）；`deep_analysis` 分支补注释固化「该链无结果级四键 → 一律 `undefined`，不填假值」；detail hydrate 处补注释固化「整对象透传，不得改成字段白名单」。
- `web/src/components/chat/RoutingDecisionPanel.vue` — 303 → 595 行。script：删 `sortedCandidates`，加 `allCandidates` / `rankKey` / `byRankDesc` / `groupingEnabled` / `blockOrder` / `groupedBlocks` / `isCrossGroup` / `showPromotionNotice` / `defaultGlobalOpen` / `globalGroupOpenOverride` / `overflowOpenGroups` / `rowsOf` 与 `degraded` / `degradeReasonText` / `degradeReasonLabel` / `confidenceTooltip`，`variantOf` 加 degraded 分支，`levelCounts` 与容差 `watch` 改吃扁平化全量候选，`watch(effectiveTraceId)` 一并重置折叠与溢出态。template：标题行包一层 flex 容器以并排容纳折叠态降级徽标（Badge 根是 `div`，塞进 `<button>` 属无效嵌套）、降级横幅、置顶提示条、组标题（全局组可折叠 / 本项目组静态）、组级跨组说明句、候选级跨组徽标、溢出披露 trigger。
- `web/src/stores/__tests__/routing.test.ts` — 6 → 13 passed。新增 override 四键继承 5 条（含「响应 `false` 不被覆盖」与「`original` 缺失不抛」）+ chat store 两处手工构造 trace 的透传 2 条（经 `_dispatchSSE` 真实走 `part_completed` 分派路径，而非直接调内部函数）。
- `web/src/components/chat/__tests__/RoutingDecisionPanel.test.ts` — 12 → 36 passed。新增分组分区 11 条 + 跨组/置顶 3 条 + 降级 10 条；既有 12 条逐字未改。

## Decisions Made

- **`??` 而非 `||` 做 override 兜底**：`||` 会把响应显式给的 `degraded=false` 当缺失、被 `original` 的 `true` 盖回，等于把「本次没降级」谎报成「降级了」。有定向用例。
- **`deep_analysis` 分支不补四键**：该链的 payload（`[cross_repo_relevance:<id>]` + 候选数组）压根没有结果级事实，填 `false` 等于把「未知」谎报成「没降级过」；候选级 `group` / `score_ranked` 随数组自然透传。
- **跨组说明句放在折叠区之外**：UI-SPEC 要求「常驻可见」，若随全局组一起收起，默认折叠场景下 ROUTE-02 的主载体就永远看不到。
- **组标题计数用组总数**：与「Top-3 + pin-in 后的可见数」刻意不同，否则「（3）」与用户展开后看到的条数不符。
- **`trust` 不渲染第二个徽标**：与 `group === 'global'` 语义完全重合，双份同义标注只是噪音；字段作契约留存供后续 phase 用。
- **`degradeReasonLabel` 与 `signalLabel` 的回退刻意相反**：前者一律「未知原因」（异常分类，回显即泄漏面），后者回显原始 key（可扩展信号枚举，前向兼容）。差异与理由写进函数上方注释。
- **全局组折叠与溢出披露用原生 `button` + `aria-expanded`**（详见 Deviations 第 1 条）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] 折叠机制从 `Collapsible` 换成原生 `button` + `aria-expanded` + `v-if`**

- **Found during:** Task 2（plan action 步骤 2/4 要求全局组与溢出披露各包一个 `Collapsible`）
- **Issue:** 三条路都走不通：(a) 把候选行整块 markup（`Checkbox` + 名称 + 两/三个 `Tooltip` + 分数分解 `Collapsible`，约 55 行）复制进 `CollapsibleContent` → 同一段交互逻辑两份副本，日后单边修改即行为漂移；(b) 只放 `CollapsibleTrigger` 不放 `Content` → `aria-controls` 指向不存在的 id，是实打实的可达性缺陷（与 backstop 6 相抵）；(c) 给平铺分支也套一层 `Collapsible` + `CollapsibleContent` → reka-ui 的 `Presence` 包裹会给历史 trace 的渲染引入 `data-state` / `hidden` 语义与额外包裹层，与 backstop 1「与今日渲染逐像素一致」相抵，且既有 12 条用例都在 mount 后**同步**读 `wrapper.text()`。
- **Fix:** 全局组标题与溢出披露 trigger 都用原生 `<button type="button" :aria-expanded>`，chevron 图标与 `rotate-90` 惯例逐字沿用「分数分解」trigger；折叠用 `v-if`；溢出展开的候选按 rank 续在同一个 `ul` 内（`rowsOf`）。**分数分解区仍用既有 `Collapsible`**，未动。
- **为何等价：** UI-SPEC backstop 6 对折叠 trigger 的要求原文是「为原生 `button`（Collapsible 既有行为）」——`CollapsibleTrigger` 渲染出来的正是原生 `button`，本实现直接满足该要求，并额外显式声明了 `aria-expanded`。
- **Files modified:** web/src/components/chat/RoutingDecisionPanel.vue
- **Verification:** 折叠两分支 / 本地态优先 / trace 变化重算 / 溢出 trigger 文案与展开后新增候选，共 4 条用例全绿；既有 12 条零回归
- **Committed in:** `bd02216e`

**2. [Rule 3 - Blocking] 两处注释措辞改写以避开归零断言的字面量**

- **Found during:** Task 1 收尾与 Task 2 收尾（plan `<verification>` 的「归零断言纪律」第 1 条）
- **Issue:** 两条归零断言的模式串本身出现在我写的说明性注释里，导致断言必红：`stores/chat.ts` 的 `test "$(rg -n 'degraded:' ... | rg -c 'false')" = "0"` 被注释「degraded: false 会把「未知」谎报成…」命中；`RoutingDecisionPanel.vue` 的 `rg -c 'v-html' == 0` 被注释「全部走 {{ }} 插值，无 v-html」命中。两条断言在 plan 中均**未**要求滤注释行。
- **Fix:** 按纪律改写措辞而非放宽断言——分别改为「把降级事实填成 `false` 等于…」与「组件内不使用任何原始 HTML 注入指令」。语义完全保留。
- **Files modified:** web/src/stores/chat.ts, web/src/components/chat/RoutingDecisionPanel.vue
- **Verification:** 两条断言实测均为 `0`
- **Committed in:** `e0122d3a`（第一处）、`bd02216e`（第二处）

**3. [Rule 3 - Blocking] 新增用例标题首字改写以过 eslint**

- **Found during:** Task 2 的 `pnpm exec eslint`
- **Issue:** `it('Top-3 截断 + …')` 触发 `test/prefer-lowercase-title`（`it` 标题不得以大写字母开头）。
- **Fix:** 改为 `it('每组 Top-3 截断 + …')`，断言与语义未变。
- **Files modified:** web/src/components/chat/__tests__/RoutingDecisionPanel.test.ts
- **Verification:** 该文件 eslint 只剩一条**先于本 plan**的报错（见 Deferred Issues）
- **Committed in:** `bd02216e`

---

**Total deviations:** 3 auto-fixed（1 条机制等价替换、2 条为让验收命令可执行的措辞/命名调整）
**Impact on plan:** 均不改变任何设计决策与用户可见行为。第 1 条是 plan 的实现手段替换（呈现与可达性契约逐条仍满足），已在上方写明三条备选路各自的失效点。无 scope creep：改动清单恰为 plan `files_modified` 的 6 个文件，`package.json` / `pnpm-lock.yaml` / `src/components/ui/` / `STATE.md` / `ROADMAP.md` 均无命中。

## Deferred Issues

- **`RoutingDecisionPanel.test.ts:265` 的既有 lint 报错未修（超出本 plan 范围）。** `it('Σbreakdown 与 score 偏差 > 1e-6：…')` 触发 `test/prefer-lowercase-title`（`Σ` 是大写希腊字母）。用 `git show HEAD~2:<path> | eslint --stdin` 确认该报错**先于本 plan**存在；且 plan 级 `<verification>` 的 eslint 清单只含 4 个源文件、不含测试文件。修它要改一条既有用例的标题，属无关变更，故记录而不动。

## Issues Encountered

- **Tooltip 内容未打开时不进 DOM，降级 Tooltip 文案无法用 DOM 断言。** reka-ui 的 `TooltipContent` 走 `Presence` + Portal，未 hover 时不渲染，模拟 hover 又脆。改为直接断言喂给它的派生函数 `confidenceTooltip(level)`（经 `wrapper.vm`，仓内 `WorkflowCanvas.slot.test.ts` 已有同款用法），并对「降级 / 未降级」两态各断言一次。
- **`Badge` 根元素是 `div`，塞进标题行的 `<button>` 属无效 HTML 嵌套。** 折叠态降级徽标改为与折叠按钮同级：标题行包一层 `flex items-center gap-2` 容器、按钮取 `flex-1`。非降级态渲染结果与今日一致（无徽标时 flex 容器内只有一个 `flex-1` 子元素），既有「点第一个 button 折叠」的用例也不受影响。
- **本地折叠态用 `ref<boolean | null>` 而非在 setup 时快照默认值。** 后者在「组件先挂载、trace 稍后到达 store」的时序下会把默认态算错（此时无 trace，派生结果恒为「展开」）；`null = 跟随派生默认态` 让默认判定始终实时，且用户点过之后本地态优先，`watch(effectiveTraceId)` 置回 `null` 即完成重算。

## Explicit Scope Boundaries

- **编排链（`ConvergenceSession.routing` / `EVENT_REPO_ROUTING`）无前端面**：本 plan 只覆盖 chat 链的 `RepositoryRoutingTrace`（UI-SPEC unresolved 3）→ Phase 110。
- **降级原因的排障下钻不做**：脱敏后的原始异常文本只进事件 payload / `SystemLogEntry`，面板内看原文需 superuser 可见性设计（UI-SPEC unresolved 4）。
- **RELY-02 的澄清 pending 可见性 / 未澄清假设标注无前端渲染面**（UI-SPEC unresolved 5）→ Phase 109/110 或 v0.20.0。
- **组件家族 i18n 迁移未做**：跟随 `SIGNAL_LABELS` 的硬编码中文惯例（UI-SPEC unresolved 6），统一迁移 `vue-i18n` 属技术债。
- **`107-08` 记录的 `[:top_k]` 残留风险未收口**：最坏情形（`block_order[0] === 'in_project'` 但本项目组被整组截空）在前端表现为「只渲染全局候选单区、无置顶提示」，观感等同未启用分组。本 plan 的空组不渲染逻辑对此是正确行为，是否改后端配额需 golden-set 评估。
- **未触碰 `STATE.md` / `ROADMAP.md`**（本次执行的显式约束）。

## User Setup Required

None — 零新增依赖、零新增配置项、零新增 ui 组件。

## Next Phase Readiness

- **ROUTE-01 / ROUTE-02 / RELY-03 的用户可见面已全部就位**，剩下的是 D12 的人工视觉验收（记入 107-UAT）：需在真实对话页确认两组分区、跨组徽标、置顶提示、降级横幅与徽标灰化与 107-UI-SPEC 的间距/字号/配色一致。
- **若 OQ-1（放开候选硬过滤）最终回退**，`global` 组会恒空 → 前端表现为「只渲染本项目组」，行为仍正确，但需在 VERIFICATION 中如实记录 ROUTE-01/02 无实际效果（UI-SPEC unresolved 2）。
- **Phase 109/110** 若要复用分区呈现：`groupedBlocks` 的分区/排序/pin-in 逻辑与呈现耦合在组件内，若编排侧也要这套呈现，届时可抽 composable（本 plan 未提前抽，避免为单一消费者做抽象）。
- 无阻塞项。

## Self-Check: PASSED

- 6 个改动文件均在磁盘（`types/routing.ts` / `stores/routing.ts` / `stores/chat.ts` / `RoutingDecisionPanel.vue` + 2 个测试文件）
- 6 个 task 提交均在 git 历史：`9d206f3e` / `e0122d3a` / `264fdf27` / `bd02216e` / `91c25548` / `eaef7bff`
- `git diff --name-only` 覆盖本 plan 全区间恰 6 个文件；`package.json` / `pnpm-lock.yaml` / `src/components/ui/` / `STATE.md` / `ROADMAP.md` 均无命中；区间内零文件删除
- 全部 task 的 `<acceptance_criteria>` 已逐条执行并 PASS（含 `original?.degraded != 0`、`degraded:` 行不含 `false`、`b.score - a.score == 0`、非注释行 `cross_group_note == 0`、`v-html == 0`、`score_ranked` 行不含 `toFixed|Math.round`、amber/teal 色板 3 值 ≤ 4、`<Badge` 窗口 `:class == 0`、组件 595 行 ≥ 380）
- plan 级 `<verification>` 全绿：`pnpm vitest run src/components/chat src/stores` → **324 passed**（40 files）、`pnpm exec vue-tsc --noEmit` 干净、4 个源文件 `pnpm exec eslint` 零报错
- 无 stub / 无占位实现：三个 task 的行为由 31 条新增用例覆盖（其中 21 条在 RED 阶段确为红），既有 18 条（12 + 6）逐字未改且全绿

---
*Phase: 107-layered-presentation*
*Completed: 2026-07-30*
