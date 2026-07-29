---
phase: 105-golden-set
plan: 06
subsystem: ui
tags: [repo-routing, breakdown, collapsible, tooltip, vue, pydantic, vitest, pytest]

# Dependency graph
requires:
  - phase: 105-golden-set (plan 03)
    provides: "RepoRouterV2 候选携带 breakdown（to_dict round 6）且 Σ贡献==score；确定性 confidence 分级"
provides:
  - "RepositoryRelevanceCandidate.breakdown: dict[str, float]（default_factory=dict）——v2 候选 breakdown 经 trace.candidates JSON 一路可达前端"
  - "RoutingCandidate.breakdown?: Record<string, number> TS 契约"
  - "RoutingDecisionPanel 每候选「分数分解」Collapsible 展开区：信号中文标签 + 贡献值（toFixed(3) font-mono）+ 分隔线 + 合计行（font-semibold，直接显示 candidate.score）"
  - "confidence Badge 外包 Tooltip 透出确定性分级依据（high/medium/low 三档文案，UI-SPEC Copywriting 原文）"
  - "SIGNAL_LABELS（text/breadth/activity）未知 key 回退英文原名——Phase 106 新信号零前端改动"
  - "breakdown 缺失（legacy/历史 trace）静默降级：不渲染 trigger，候选行与现状一致"
affects: [105-07, phase-106, phase-107]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "展开态为组件本地 ref（Set<repository_id>，非手风琴），watch effectiveTraceId 重置——trace 更新（manual_override）自动收起"
    - "前端和校验只 console.warn 不阻断（immediate watch 每次 trace 数据变化跑一次）——不变量由后端测试守护"

key-files:
  created: []
  modified:
    - server/agents/tools/schemas/repository_relevance.py
    - server/agents/tools/repository_relevance.py
    - server/tests/agents/test_repository_relevance_tool.py
    - web/src/types/routing.ts
    - web/src/components/chat/RoutingDecisionPanel.vue
    - web/src/components/chat/__tests__/RoutingDecisionPanel.test.ts

key-decisions:
  - "candidate li 由 flex 行改为块容器 + 内层 flex 行——候选行视觉类名逐一保留（px-1 py-1.5 hover:bg-zinc-50 / gap-3），Collapsible 挂行下方，legacy 候选渲染结果与现状一致"
  - "schema snapshot fixture 零更新：fixture 只覆盖 RepositoryRelevanceInput，candidate 结构不在快照守护范围（计划条件分支未触发）"
  - "合计行直接显示 candidate.score 不前端求和（UI-SPEC 契约）；容差校验挂 immediate watch 而非渲染分支"

patterns-established:
  - "breakdown 透传链：RepoRouterV2 候选 → RepositoryRelevanceCandidate（pydantic 默认空 dict）→ RepositoryRoutingTrace.candidates JSON → useRoutingStore → RoutingDecisionPanel"

requirements-completed: [ROUTE-07]

coverage:
  - id: D1
    description: "后端 breakdown 透传：v2 路径 trace candidates JSON 含非空 breakdown 且 Σ值≈score（1e-6）；legacy 路径为空 dict；schema 默认值兼容历史 trace；selected = high or (medium and score>=threshold) 行为锁定"
    requirement: ROUTE-07
    verification:
      - kind: unit
        ref: "server/tests/agents/test_repository_relevance_tool.py#test_v2_path_trace_candidates_carry_breakdown_sum_equals_score / test_legacy_path_trace_candidates_breakdown_empty / test_candidate_breakdown_defaults_to_empty_dict"
        status: pass
    human_judgment: false
  - id: D2
    description: "前端展开区：有 breakdown 候选可展开，明细行数==键数、信号中文标签正确、未知 key 回退原名、合计行==score.toFixed(3)；无 breakdown（缺失/空 dict）不渲染 trigger 且候选行既有元素齐备；Σ偏差>1e-6 仅 console.warn 照常渲染"
    requirement: ROUTE-07
    verification:
      - kind: unit
        ref: "web/src/components/chat/__tests__/RoutingDecisionPanel.test.ts#routingDecisionPanel 分数分解（3 用例）"
        status: pass
      - kind: other
        ref: "cd web && pnpm exec vue-tsc --noEmit（通过）"
        status: pass
    human_judgment: false
  - id: D3
    description: "confidence Badge 外包 Tooltip 显示确定性分级依据一句话（视觉零漂移：Badge variant 映射不改、无覆色）"
    requirement: ROUTE-07
    verification:
      - kind: unit
        ref: "web/src/components/chat/__tests__/RoutingDecisionPanel.test.ts#badge 标签显示百分比 + 中文 level（既有用例零改动通过，结构未破坏）"
        status: pass
    human_judgment: true
    rationale: "Tooltip 悬停文案与视觉呈现（hover 交互、零漂移观感）需人工在聊天流中确认；测试只锁定 Badge 结构未破坏"

# Metrics
duration: 8min
completed: 2026-07-29
status: complete
---

# Phase 105 Plan 06: breakdown 透传 + 前端分数分解展开 Summary

**分数可解释性用户可感知：v2 候选 breakdown 经 RepositoryRelevanceCandidate（pydantic 可选字段）→ trace JSON → RoutingDecisionPanel 每候选 Collapsible 展开区（信号中文标签 + toFixed(3) 贡献值 + 合计行==score），confidence Badge 外包 Tooltip 透出确定性分级依据；legacy/历史 trace 无 breakdown 静默降级不渲染 trigger**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-07-29T04:50:02Z
- **Completed:** 2026-07-29T04:58:00Z
- **Tasks:** 3
- **Files modified:** 6

## Accomplishments

- **后端透传（Task 1）**：`RepositoryRelevanceCandidate` 新增 `breakdown: dict[str, float] = Field(default_factory=dict)`——legacy 路径为空 dict、历史 trace 反序列化零破坏；v2 路径候选构造透传 `breakdown=dict(c.breakdown or {})`；+3 测试锁定 v2 trace JSON 含非空 breakdown 且 Σ≈score（1e-6）、legacy 为空 dict、`selected = high or (medium and score>=threshold)` 编排解锁行为
- **前端展开区（Task 2）**：每候选独立 `Collapsible`（默认收起、非手风琴、多候选可同时展开）——chevron 旋转 trigger「分数分解」+ 两列明细行（信号中文标签 / `toFixed(3)` font-mono 贡献值）+ `border-t border-border/50` 分隔线 + 合计行（`font-semibold`，直接显示 `candidate.score` 不前端求和）；`SIGNAL_LABELS`（text→文本相关 / breadth→命中广度 / activity→活跃度）未知 key 回退英文原名；和校验 `|Σ−score|>1e-6` 仅 console.warn 不阻断；展开态本地 ref、trace 更新重置收起
- **confidence 语义透出（Task 2）**：既有 高/中/低 Badge 外包 Tooltip，悬停显示 `CONFIDENCE_TOOLTIPS` 三档分级依据（UI-SPEC Copywriting 原文）；Badge variant 映射不改、无 `:class` 覆色（DESIGN.md 禁令）、信号行无彩虹配色
- **静默降级（Backstop 1）**：`breakdown` 缺失或空 dict → `v-if` 不渲染 trigger，候选行既有元素（Checkbox/名称/Badge/evidence Tooltip）齐备、类名逐一保留
- **零新增依赖**：仅复用本仓 `ui/collapsible`；package.json 无 diff；间距只用 gap-1/gap-2/px-2/py-1/pl-3（UI-SPEC Spacing）
- 双端全绿：server 17 passed（14 既有零回归 + 3 新增）；web vue-tsc 通过 + vitest 10 passed（7 既有零改动 + 3 新增）

## Task Commits

Each task was committed atomically:

1. **Task 1: 后端 breakdown 透传（schema + v2 路径）** - `a2065f39` (feat)
2. **Task 2: 前端「分数分解」展开区 + confidence Tooltip** - `abd508fb` (feat)
3. **Task 3: 组件测试补用例** - `2c7f52d1` (test)

## Files Created/Modified

- `server/agents/tools/schemas/repository_relevance.py` - `RepositoryRelevanceCandidate.breakdown` 可选字段（default_factory=dict）
- `server/agents/tools/repository_relevance.py` - v2 路径候选构造透传 `breakdown=dict(c.breakdown or {})`
- `server/tests/agents/test_repository_relevance_tool.py` - +3 用例（默认值兼容 / v2 透传+Σ≈score+selected 行为 / legacy 空 dict）
- `web/src/types/routing.ts` - `RoutingCandidate.breakdown?: Record<string, number>`（注释 Σ值==score 由后端 INV-R1/R3 保证）
- `web/src/components/chat/RoutingDecisionPanel.vue` - `SIGNAL_LABELS` / `CONFIDENCE_TOOLTIPS` 常量、每候选 Collapsible 展开区、confidence Tooltip、和校验 watch、展开态重置
- `web/src/components/chat/__tests__/RoutingDecisionPanel.test.ts` - +3 用例（展开明细 / 静默降级两形态 / 容差告警）

## Decisions Made

- **candidate li 结构调整**：li 由 flex 行改为块容器 + 内层 `div.flex.items-start.gap-3` 行——候选行全部既有类名保留在 li（px-1 py-1.5 hover:bg-zinc-50）与内层 div（gap-3），legacy 候选（无 breakdown）渲染结果与现状一致（既有 7 条测试零改动通过佐证）
- **schema snapshot fixture 零更新**：fixture 只覆盖 `RepositoryRelevanceInput`（LLM 可见 input schema），candidate 结构不在快照守护范围——计划的条件分支（"若覆盖 candidate 结构则更新"）未触发
- **容差校验挂 immediate watch**：每次 trace 数据变化跑一次而非每次渲染，符合"挂一次容差校验"契约且观测不反噬渲染

## Deviations from Plan

None - plan executed exactly as written.

说明：Task 3 标注 `tdd="true"`，但其被测行为即 Task 2 产物（计划刻意先实现再补行为守护，同 105-03/105-05 先例）——无独立 RED 阶段，测试首跑即绿（10 passed, 1.77s），符合计划任务顺序而非偏差。

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 105 success criterion 2 用户侧成立：展开任一候选可见各信号贡献值且合计等于总分
- Phase 106 新增打分信号：`SIGNAL_LABELS` 未知 key 回退英文原名，零前端改动即可展示（补中文标签为可选优化）
- Phase 107（分组呈现/降级标注/跨组标注 UI）：`degraded` 数据底座已就位（105-03），本 plan 未消费——前端呈现留给 107

## Known Stubs

None——UI-SPEC Unresolved 2–5（degraded 标注/分组呈现/编排链呈现/i18n 迁移）为计划显式排除项（归 Phase 107/110），非 stub。

## Self-Check: PASSED

- FOUND: `rg -c "breakdown" server/agents/tools/schemas/repository_relevance.py` = 2（artifact contains 达标）
- FOUND: `rg -c "Collapsible" web/src/components/chat/RoutingDecisionPanel.vue` = 7 >= 3；`toFixed\(3\)` = 2 >= 2；`console\.warn` >= 1
- FOUND: commit a2065f39（Task 1）/ abd508fb（Task 2）/ 2c7f52d1（Task 3）
- 验证命令：`cd server && uv run pytest tests/agents/test_repository_relevance_tool.py -q` → 17 passed；`cd web && pnpm exec vue-tsc --noEmit` → 通过；`pnpm exec vitest run src/components/chat/__tests__/RoutingDecisionPanel.test.ts` → 10 passed
- package.json 无 diff（零新增依赖）

---
*Phase: 105-golden-set*
*Completed: 2026-07-29*
