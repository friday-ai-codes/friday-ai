---
phase: 105
slug: 105-golden-set
status: draft
shadcn_initialized: false
preset: none
created: 2026-07-29
---

# Phase 105 — UI Design Contract（分数分解展开 + 确定性 confidence 透出）

> 本 phase 的 UI 面**极小**：在既有路由结果候选列表中为每个候选增加一个可展开的「分数分解」区域（信号名 → 贡献值，各项之和 == 总分），并让既有 confidence 徽标承载确定性分级语义。分组呈现 / 跨组标注 / 降级标注 UI 属于 Phase 107，本契约不涉及。
>
> AUTONOMOUS MODE：所有裁定按既有设计系统（`web/DESIGN.md`）与代码惯例自动采纳，逐条标注 `[默认决策]`。

---

## 落点与数据链路（侦察结论）

用户可见的「仓库路由结果候选列表」只有一处：

- **组件**：`web/src/components/chat/RoutingDecisionPanel.vue` — 聊天流中的路由决策卡片，逐候选渲染 `Checkbox + 仓库名 + Badge(score% 高/中/低) + evidence Tooltip`。
- **数据**：`useRoutingStore`（`web/src/stores/routing.ts`）→ `RoutingDecisionData.candidates: RoutingCandidate[]`（`web/src/types/routing.ts`），与后端 `RepositoryRelevanceCandidate` / `RepositoryRoutingTrace.candidates` 一一对应。
- **v2 已接通**：`server/agents/tools/repository_relevance.py` 的 v2 路径直接以 `RepoRouterV2` 候选构造 trace，且 `level = c.confidence`——即前端 Badge 的 高/中/低 **就是** confidence 分级。Phase 105 把 confidence 改为分数 margin 确定性推导后，该徽标语义自动升级，无需新组件。
- **伴生组件**：`RelevanceBadge.vue`（仓库列表处复用同一 store 的徽标）——本 phase 不改其结构，语义随 confidence 升级自动受益。
- **不落点**：`ConvergenceSession` 编排链路由结果目前无前端呈现（`router_version` / `auto_selected` 在 web 端零引用），其 UI 归 Phase 107/110；`REST /api/repositories/route/` 与 MCP `route_repositories` 为 API 消费方，无 UI。

**前端数据契约变更**（供 planner 提升为任务）：

```ts
// web/src/types/routing.ts
export interface RoutingCandidate {
  // ...既有字段不变（repository_id / repository_name / score / level / evidence / selected_by_ai / selected_by_user_final）
  breakdown?: Record<string, number> // [新增] 信号名 → 贡献值；Σ值 == score（后端不变量 INV-R1/R3 保证）
}
```

后端需把候选 `to_dict()` 的 `breakdown` 一路透传：`RepoRouterV2` 候选 → `RepositoryRelevanceCandidate`（新增可选字段）→ `RepositoryRoutingTrace.candidates` JSON → 前端。旧 trace / legacy 路径无 `breakdown`，前端按缺失优雅降级（见交互契约）。

---

## Design System

| Property | Value |
|----------|-------|
| Tool | none（shadcn-vue 风格组件手工维护于 `web/src/components/ui/`，无 `components.json`，不跑 shadcn init）[默认决策] |
| Preset | not applicable |
| Component library | reka-ui（经本仓 `ui/` 封装：`Collapsible` / `Badge` / `Tooltip` 均已存在，零新增依赖） |
| Icon library | Iconify `icon-[lucide--*]`（既有惯例） |
| Font | 继承全局；数值列用 `font-mono`（对齐 DESIGN.md「mono 值」规范） |

**Registry 安全**：不引入任何第三方 registry / 区块；仅复用 `web/src/components/ui/collapsible/`（Collapsible / CollapsibleTrigger / CollapsibleContent）。

---

## Spacing Scale

沿用项目既定 Tailwind 间距，全部为 4 的倍数。本 phase 增量 UI 只用到：

| Token | Value | Usage |
|-------|-------|-------|
| xs | 4px（`gap-1` / `py-1`） | 分解行内间距、trigger 图标与文字间距 |
| sm | 8px（`gap-2` / `px-2`） | 分解区域内边距、行间距 |
| md | 12px（`pl-3`） | 展开区域相对候选行的左缩进（对齐 checkbox 后内容列）[默认决策] |
| lg | 16px（`p-4`） | 卡片既有内边距，不改动 |

Exceptions: none（不引入新间距值）。

---

## Typography

沿用 `RoutingDecisionPanel` 既有层次，不新增字号字重：

| Role | Size | Weight | Line Height | 用途 |
|------|------|--------|-------------|------|
| Body | 14px（`text-sm`） | 500（`font-medium`） | 1.43（Tailwind 默认） | 仓库名（既有，不动） |
| Label | 12px（`text-xs`） | 400 | 1.33 | 信号名标签、trigger 文案、合计行标签 |
| Value | 12px（`text-xs` + `font-mono`） | 400 | 1.33 | 贡献值 / 总分数值 |
| 合计行 | 12px（`text-xs` + `font-mono`） | 600（`font-semibold`） | 1.33 | 「合计」行数值加重，与明细行区分 |

共 2 个字号（14/12px）、3 个字重中仅用 400/500/600 三档中的既有组合，无新增。[默认决策]

---

## Color

不引入任何新颜色；全部走既有语义 token（DESIGN.md 功能色系）：

| Role | Value | Usage |
|------|-------|-------|
| Dominant (60%) | `bg-white/60`（卡片既有玻璃底） | 展开区域继承卡片背景，不另设底色 |
| Secondary (30%) | `text-muted-foreground` / `border-border/50` | 信号名标签、展开区域上边框分隔线 |
| Accent (10%) | `text-foreground` | 贡献值与合计数值（清晰可读，禁过浅灰） |
| Confidence 徽标 | `variant="success"`（high）/ `warning`（medium）/ `secondary`（low） | **既有映射，不改**；语义升级为确定性分级 |

Accent reserved for: 数值文本与既有 Badge variant，无任何新强调元素。禁止给不同信号行分配不同颜色（DESIGN.md「彩虹卡片」禁令）。[默认决策]

---

## 交互契约（本 phase 唯一新交互）

### 展开/收起「分数分解」

- **触发器**：候选行下方一行 `CollapsibleTrigger`（`text-xs text-muted-foreground`，含 `icon-[lucide--chevron-right]`，展开时旋转 90°）。文案见 Copywriting。**不用整行点击**——候选行已承载 Checkbox 勾选与 evidence Tooltip，避免点击目标冲突。[默认决策]
- **组件**：每候选一个独立 `Collapsible`（`web/src/components/ui/collapsible/`），默认收起，多候选可同时展开（非手风琴）。[默认决策]
- **展开内容**：
  1. 明细行：每信号一行，两列布局 —— 左列信号中文标签（`text-xs text-muted-foreground`），右列贡献值（`text-xs font-mono text-foreground`，右对齐，保留 3 位小数，如 `0.412`）。[默认决策：3 位小数在 0–1 归一分数下可辨且不噪]
  2. 分隔线：`border-t border-border/50`。
  3. 合计行：左列「合计」，右列总分（同格式、`font-semibold`）。**合计值直接显示 `candidate.score`**，与明细各行之和一致由后端不变量（Σ贡献 == 总分，INV-R1/R3）保证；前端做一次 `Math.abs(sum - score) > 1e-6` 容差校验，不一致时仅 `console.warn`，照常渲染，不阻断（观测代码不反噬业务）。[默认决策]
- **信号名映射**：前端维护一个信号名 → 中文标签常量表（如 `text` → `文本相关`、`breadth` → `命中广度`、`activity` → `活跃度`；确切 key 以后端 breakdown 字典为准，executor 实现时对齐）。**未知 key 回退显示原始英文 key**——Phase 106 新增信号无需改前端即可展示。[默认决策]
- **优雅降级**：`candidate.breakdown` 缺失或为空（legacy 路径、历史 trace）→ **不渲染 trigger**，候选行外观与现状完全一致。沿用本组件家族 `v-if` 静默降级惯例，不显示「无数据」占位。[默认决策]

### Confidence 徽标（无结构改动）

- 既有 `Badge`（`{score%} 高/中/低`）保留原位原样；Phase 105 后其 level 来自确定性 margin 规则。
- 在徽标外包既有 `Tooltip`，悬停显示分级依据一句话（见 Copywriting），让「确定性」对用户可感知。成本为零新组件。[默认决策]
- `degraded` 标志本 phase 只落数据底座，**UI 不显示**（Phase 107 范围）。

---

## Copywriting Contract

组件家族（RoutingDecisionPanel / RelevanceBadge / RepoMultiSelector）现状为硬编码中文、未接 vue-i18n；本 phase 增量文案**沿用同一惯例**硬编码中文，不单独引入 i18n key。[默认决策：与既有组件保持一致优先于全局 i18n 约定；如后续该组件家族统一接 i18n 再一并迁移]

| Element | Copy |
|---------|------|
| 展开触发器（收起态） | `分数分解` |
| 展开触发器（展开态） | `分数分解`（仅 chevron 旋转指示状态，文案不变）[默认决策] |
| 合计行标签 | `合计` |
| Confidence tooltip（high） | `高置信：首位分数与领先幅度均超过阈值，由分数确定性推导` |
| Confidence tooltip（medium） | `中置信：首位分数达标但领先幅度不足，建议人工确认` |
| Confidence tooltip（low） | `低置信：候选分数整体偏低，请人工选择` |
| Empty state | 不适用——`breakdown` 缺失时不渲染 trigger（静默降级，无占位文案） |
| Error state | 不适用——纯展示组件，无网络请求；数据异常走静默降级 |
| Destructive | 本 phase 无破坏性操作 |

数值格式：贡献值与合计均为 `x.xxx`（3 位小数）；徽标内百分比格式（`Math.round(score*100)%`）维持现状不变。

---

## Registry Safety

| Registry | Blocks Used | Safety Gate |
|----------|-------------|-------------|
| 无（不使用 shadcn registry） | 仅复用本仓既有 `ui/collapsible`、`ui/badge`、`ui/tooltip` | not applicable — 零第三方引入（2026-07-29 确认） |

---

## UI Considerations

### Covered（本契约已覆盖，可直接提升为 must_haves）

1. **展开可见分解**：路由结果中每个带 `breakdown` 的候选可展开，逐信号显示中文标签 + 贡献值（3 位小数、font-mono），含分隔线与「合计」行，合计等于候选总分 —— 直接对应 Phase 105 success criterion 2。
2. **确定性 confidence 透出**：既有 高/中/低 Badge 语义升级为确定性分级，外包 Tooltip 显示分级依据一句话；`RelevanceBadge` 复用点自动受益，无结构改动。
3. **数据契约**：`RoutingCandidate` 新增可选 `breakdown?: Record<string, number>`；后端从 `RepoRouterV2` 候选 `to_dict()` 经 `RepositoryRelevanceCandidate` / `RepositoryRoutingTrace.candidates` 透传到前端。
4. **前向兼容**：信号名映射表未知 key 回退英文原名，Phase 106 新信号零前端改动即可展示。
5. **视觉零漂移**：不新增颜色/字号/间距值/第三方依赖；复用 `ui/collapsible`；遵守 DESIGN.md Badge 禁令（不 `:class` 覆色）与彩虹卡片禁令。

### Backstop（兜底行为，executor 必须实现但无需显式设计）

1. **breakdown 缺失静默降级**：legacy 路径 / 历史 trace / v1_fallback 候选无 `breakdown` → 不渲染 trigger，候选行与现状逐像素一致；无空态占位、无报错。
2. **和校验不反噬**：前端 `|Σbreakdown − score| > 1e-6` 时仅 `console.warn`，正常渲染（不变量由后端测试守护，前端不承担校验职责）。
3. **展开态不持久化**：展开状态为组件本地 `ref`，trace 更新（manual_override 写新 trace）后重置为收起，可接受。
4. **测试**：为 `RoutingDecisionPanel` 既有测试（`__tests__/RoutingDecisionPanel.test.ts`）补充：有 breakdown 时可展开且合计行等于 score、无 breakdown 时不渲染 trigger 两条用例。

### Unresolved（本 phase 明确不做，留给后续 phase）

1. **breakdown 信号 key 的最终清单**：取决于本 phase 后端打分函数重构落地的字典 key（现有信号：文本 max / 命中广度 / 活跃度封顶惩罚）；前端映射表在 executor 实现时与后端对齐，未知 key 有回退，不阻塞。
2. **`degraded` 降级标注 UI** → Phase 107（RELY-03）；本 phase 仅数据底座。
3. **分组呈现（in_project/global）、跨组标注、迟滞置顶提示** → Phase 107。
4. **编排链（ConvergenceSession）路由结果的前端呈现** → Phase 107/110；本 phase 快照只落 `ConvergenceSessionEvent`，无 UI。
5. **组件家族 i18n 迁移**：RoutingDecisionPanel 家族整体硬编码中文，本 phase 跟随现状；统一迁移 vue-i18n 属技术债，不在本 phase 处理。

---

## Checker Sign-Off

- [ ] Dimension 1 Copywriting: PASS
- [ ] Dimension 2 Visuals: PASS
- [ ] Dimension 3 Color: PASS
- [ ] Dimension 4 Typography: PASS
- [ ] Dimension 5 Spacing: PASS
- [ ] Dimension 6 Registry Safety: PASS

**Approval:** pending
