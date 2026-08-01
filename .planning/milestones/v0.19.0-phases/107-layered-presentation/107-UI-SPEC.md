---
phase: 107
slug: 107-layered-presentation
status: draft
shadcn_initialized: false
preset: none
created: 2026-07-30
---

# Phase 107 — UI Design Contract（分组呈现 + 跨组标注/置顶提示 + 降级可见）

> 本 phase 的 UI 面集中在**唯一一个组件**：`web/src/components/chat/RoutingDecisionPanel.vue`。三块增量：
> ① 候选列表分「本项目关联仓 / 全局候选」两区呈现（ROUTE-01）；
> ② 全局组候选带跨组标注 + 迟滞触发时置顶提示（ROUTE-02）；
> ③ 路由降级时面板级醒目提示 + 降级原因 + confidence 徽标降级样式（RELY-03）。
>
> RELY-02（澄清必达/超时出口）与 RELY-05（Stage 1 有界）本 phase **无前端面**——前者出口只写 `stage_state` 与事件（D-6），后者纯后端；两者不在本契约内。
>
> AUTONOMOUS MODE：所有未决问题按既有设计系统（`web/DESIGN.md`）与代码惯例自行裁定，逐条标注 `[默认决策]`。

---

## 落点与数据链路（侦察结论）

**唯一组件落点**：`web/src/components/chat/RoutingDecisionPanel.vue`（303 行，实读）。现状结构：

```
Card
└─ button（折叠切换：「→ 路由决策（N 个仓库相关）」+「高 N · 中 N · 低 N」+ 展开/收起）
   └─ div v-if="!collapsed"
      ├─ query + 阈值行（text-xs text-zinc-500）
      ├─ TooltipProvider > ul > li（逐候选）
      │    ├─ Checkbox + 仓库名(text-sm font-medium) + Badge(score% 高/中/低, Tooltip) + evidence(Tooltip)
      │    └─ Collapsible「分数分解」（105-06 加，106-05 加 SIGNAL_LABELS 中文标签）
      └─ 两个 Button（创建编码方案 / 手动调整选择）
```

**必改的既有行为（研究已定位，两条都是本 phase 的正确性前提）**：

1. `sortedCandidates`（`:50-54`）当前 `[...candidates].sort((a,b) => b.score - a.score)` —— **会覆盖后端的分组分区与 block 置顶**（107-RESEARCH Pitfall 4）。必须改为「按 `block_order` 分区 → 区内按 `score_ranked ?? score` 降序」。
2. `web/src/stores/routing.ts` `applyManualOverride`（`:74-80`）重建 trace 时只保留 5 个键 —— 用户改一次勾选后 `degraded` / `degrade_reason` / `router_version` / `block_order` 全丢，**降级横幅会消失**（Pitfall 3）。必须从 `original` 兜底继承。

**已就位可复用资产（零新依赖、零新色板）**：

| 资产 | 位置 | 本 phase 用法 |
|------|------|--------------|
| `Badge` 8 variant | `web/src/components/ui/badge/index.ts` | 跨组标注用 `info`（teal-500/10）；降级态 confidence 徽标降为 `muted`（gray-500/10）；折叠态降级提示用 `warning`（amber-500/10） |
| `Collapsible / Trigger / Content` | `web/src/components/ui/collapsible/` | 全局组默认折叠、组内溢出候选折叠（已在本组件 import） |
| `Tooltip` 家族 | `web/src/components/ui/tooltip/` | 跨组标注全文、降级态 confidence 依据（已在本组件 import） |
| 告警条范式（**三处同款**） | `CommitConfirmCard.vue:100-105`、`ContextExceededCard.vue:79-81`、`ReconcilePanel.vue:132-138` | 降级横幅与置顶提示逐字沿用同一 DOM 形状（`flex items-start gap-2 rounded-lg border border-X/30 bg-X/5 px-3 py-2.5` + `icon-[lucide--*] shrink-0 mt-0.5`） |
| 降级徽标先例 | `ChatMessageBubble.vue:1210-1213`（`降级回答 · {reason}` + `icon-[lucide--triangle-alert]`） | 面板折叠态的紧凑降级徽标沿用同一语义与图标 |
| `SIGNAL_LABELS` 硬编码中文 map | `RoutingDecisionPanel.vue:84`（106-05 既定） | 新增分组/trust/降级原因文案沿用同一惯例（硬编码中文常量，不接 vue-i18n） |

**无 `ui/alert` 组件**（`web/src/components/ui/` 33 个目录只有 `alert-dialog`）→ 提示条按上述内联 Tailwind 类写，**不新建 alert 组件**。[默认决策]

---

## 前端数据契约变更（供 planner 提升为任务）

```ts
// web/src/types/routing.ts
export type RoutingGroup = 'in_project' | 'global'
export type RoutingTrust = 'trusted' | 'needs_confirmation'
/** 降级原因受控闭集（6 值，与后端 classify_degrade_reason 字面对齐）。 */
export type RoutingDegradeReason
  = 'timeout' | 'upstream_error' | 'provider_missing'
    | 'unparsable' | 'no_node_index' | 'unknown'

export interface RoutingCandidate {
  // ...既有字段不变（repository_id / repository_name / score / level / evidence /
  //    selected_by_ai / selected_by_user_final / breakdown?）
  group?: RoutingGroup // [新增] 归属组；缺失视为 'global'
  trust?: RoutingTrust // [新增] 信任标记；缺失不渲染
  score_ranked?: number | null // [新增] 凸组合排序分（旁路字段）；排序用 score_ranked ?? score
  cross_group_note?: string // [新增] 后端留痕用；**前端不渲染**（见 T-107-06）
}

export interface RoutingDecisionData {
  // ...既有字段不变（trace_id / query / candidates / threshold / triggered_by）
  router_version?: string // [新增] v2_stage0_only / v1_fallback / ...
  degraded?: boolean // [新增] 后端计算的事实，前端不推断
  degrade_reason?: RoutingDegradeReason // [新增] 6 值枚举
  block_order?: RoutingGroup[] // [新增] 区顺序权威；长度 2 = 有项目上下文
}
```

**后端侧硬性契约要求（planner 必须落进后端 task，否则前端无法区分两种 all-global 场景）**：

- **有项目上下文时，`block_order` 必须恒为长度 2**（`["in_project","global"]` 或 `["global","in_project"]`），**即使某一组为空**；
- **无项目上下文时**（MCP / REST / skill_steps 等），`block_order` 省略或为 `["global"]`。

前端以此判定「是否启用分组呈现」，**不按候选内容猜**。[默认决策]

透传链（105-06 铺 `breakdown` 的同一条路，逐跳都要补）：`RepoRouteCandidateV2.to_dict()` → `RepositoryRelevanceCandidate` → `RepositoryRoutingTrace.candidates` / `degrade_reason` 列 → `chat/views.py` `routing_trace_payload`（**当前只出 5 键，必补 4 键**）→ `stores/chat.ts`（三处 upsertTrace）→ `stores/routing.ts`（**override 兜底继承**）→ 本组件。

---

## Design System

| Property | Value |
|----------|-------|
| Tool | none（shadcn-vue 风格组件手工维护于 `web/src/components/ui/`，无 `components.json`，不跑 shadcn init）[默认决策，沿用 105-UI-SPEC] |
| Preset | not applicable |
| Component library | reka-ui（经本仓 `ui/` 封装：`Badge` / `Collapsible` / `Tooltip` / `Checkbox` / `Card` 全部已存在，**零新增依赖**） |
| Icon library | Iconify `icon-[lucide--*]`（既有惯例） |
| Font | 继承全局；数值列 `font-mono`（DESIGN.md「mono 值」） |

---

## Spacing Scale

沿用本组件既有 Tailwind 间距，增量**不引入任何新值**：

| Token | Value | Usage |
|-------|-------|-------|
| xs | 4px（`gap-1` / `py-1`） | 提示条图标与文字间距、组标题图标间距 |
| sm | 8px（`gap-2` / `space-y-2` / `mt-2`） | 提示条内部横向间距、区块纵向间距 |
| md | 12px（`px-3` / `pl-3`） | 提示条内边距、组内候选相对组标题的左缩进 |
| lg | 16px（`p-4`） | 卡片既有内边距，不改动 |

**Exceptions（既有半步值，本 phase 沿用不新增）**：`space-y-1.5`（6px，候选行间距）、`py-1.5`（6px）、`py-2.5`（10px，告警条既有内边距）、`mt-0.5`（2px，图标基线微调）。这四个值在 `RoutingDecisionPanel` / `CommitConfirmCard` / `ReconcilePanel` 中均已存在，增量复用它们比引入新的 4 倍数值更一致。[默认决策]

---

## Typography

沿用既有层次，**不新增字号字重**（共 2 字号 / 3 字重，与 105-UI-SPEC 一致）：

| Role | Size | Weight | Line Height | 用途 |
|------|------|--------|-------------|------|
| Body | 14px（`text-sm`） | 500（`font-medium`） | 1.43 | 仓库名（既有）、降级横幅主句 |
| Group header | 12px（`text-xs`） | 600（`font-semibold`） | 1.33 | 「本项目关联仓」/「全局候选」组标题 |
| Label | 12px（`text-xs`） | 400 | 1.33 | 组标题计数、跨组说明句、降级原因行、置顶提示句、溢出 trigger |
| Value | 12px（`text-xs` + `font-mono`） | 400 / 600 | 1.33 | 分数分解明细与合计（既有，不动） |

---

## Color

**零新色板**——全部走既有语义 token 与 Badge variant（DESIGN.md 功能色系 + Badge 规范）：

| Role | Value | Usage |
|------|-------|-------|
| Dominant (60%) | `bg-white/60`（卡片既有玻璃底） | 两个分组区共享卡片背景，**不给分组另设底色** |
| Secondary (30%) | `text-muted-foreground` / `text-zinc-500` / `border-border/50` | 组标题计数、说明句、区间分隔 |
| Accent (10%) | `text-foreground` / `text-zinc-900` | 仓库名与数值（既有） |
| 警告（降级横幅） | `border-amber-500/30` + `bg-amber-500/5` + `icon-[lucide--triangle-alert] text-amber-500` + 文字 `text-foreground` / `text-muted-foreground` | **仅降级横幅**（DESIGN.md：amber 仅用于警告提示框） |
| 信息（置顶提示） | `border-teal-500/30` + `bg-teal-500/5` + `text-teal-700` + `icon-[lucide--arrow-up-narrow-wide]` | **仅迟滞置顶提示**。teal 已是 `Badge variant="info"` 的既有色系（`bg-teal-500/10 text-teal-700`），非新色板 [默认决策] |
| 跨组 Badge | `variant="info"` | 全局组候选的「跨组」标注 |
| Confidence 徽标（正常） | `variant="success"`(high) / `warning`(medium) / `secondary`(low) | **既有映射，不改** |
| Confidence 徽标（降级态） | `variant="muted"`（全部候选一律灰化） | 灰化 = 「这个颜色信号本次不可信」 |
| 折叠态降级徽标 | `variant="warning"` | 面板收起时仍能看见「降级」 |

Accent reserved for: 仓库名与数值文本、既有 Badge variant、上述两条提示条。**禁止**给不同分组染不同底色（DESIGN.md「彩虹卡片」禁令）；**禁止**在 Badge 上用 `:class` 追加颜色（DESIGN.md Badge 规则）。[默认决策]

---

## 交互契约

### A. 分组分区呈现（ROUTE-01）

**启用条件**：`trace.block_order?.length === 2`。否则（长度 1 / 缺失 / 历史 trace）→ **完全走现状**：无组标题、无跨组 Badge、无置顶提示，平铺一个 `ul`。
兜底：`block_order` 缺失但存在 `group === 'in_project'` 的候选 → 按 `['in_project','global']` 启用分组。[默认决策]

**区顺序**：严格等于 `block_order`，**前端不重排区**。
**区内排序**：`score_ranked ?? score` 降序（`score_ranked` 为 `null`/`undefined` 时回退 `score`）。**移除**现有全局 `b.score - a.score` 重排。
**空组**：某组 0 条 → 该组整块（标题 + 列表）不渲染，无空态占位。[默认决策：面板已足够密集，空态文案是噪音]

**组标题**：
- 结构：一行 `text-xs`，左侧组名（`font-semibold text-foreground`）+ 计数（`text-muted-foreground`，格式 `（{n}）`）；全局组标题额外在同一行右侧或次行承载跨组说明句（见 B）。
- 本项目组：**纯静态标题，不可折叠**（默认可见内容不应需要额外点击）。[默认决策]
- 全局组：整块包在 `Collapsible` 内，标题作 `CollapsibleTrigger`，含 `icon-[lucide--chevron-right]`（展开时 `rotate-90`），沿用「分数分解」trigger 的同款图标与旋转惯例。

**全局组默认折叠判定**（纯呈现派生，不是对降级/分组事实的推断）：
```
defaultGlobalCollapsed =
     block_order[0] === 'in_project'                       // 迟滞未触发（未置顶）
  && inProjectCandidates[0]?.level === 'high'              // 本项目首位高置信
```
两条同时成立 → 折叠；否则展开。用户手动展开/收起后以本地 `ref` 为准；`effectiveTraceId` 变化（override 写新 trace）后重算默认态——与既有 `expandedBreakdowns` 的重置惯例一致。[默认决策]

**Top-3 与溢出披露**：
- 每组默认渲染 **Top-3**（按区内排序）。
- 🔴 **必须叠加 pin-in 规则**：`selected_by_ai === true || selected_by_user_final === true` 的候选**无论排名一律可见**。理由：候选行承载 `Checkbox` 与 manual override，被隐藏的已选候选将无法取消勾选，且用户会看到「勾了的仓不见了」。默认可见集 = `Top-3 ∪ 已选候选`。[默认决策]
- 剩余候选放进组内第二个 `Collapsible`，trigger 文案见 Copywriting；无剩余则不渲染 trigger。
- 组标题计数显示**该组候选总数**（不是可见数），避免「（3）」与实际不符。

### B. 跨组标注 + 置顶提示（ROUTE-02）

**跨组标注（两层，缺一不可）**：
1. **组级说明句（常驻可见，不依赖 hover）**：全局组标题下方一行 `text-xs text-muted-foreground`，渲染完整句「未关联当前平台，可能涉及跨组协作」。这是 ROUTE-02「明确标注」的主载体。
2. **候选级紧凑 Badge**：全局组每个候选行渲染 `Badge variant="info"`，文案「跨组」，外包 `Tooltip` 显示完整句，并带 `aria-label` 为完整句。理由：候选行已有 名称 + score 徽标 + evidence，塞完整长句会挤爆行宽。[默认决策]

> **文案来源纪律（T-107-06）**：跨组说明句与降级原因**一律取前端常量**，`cross_group_note` / 后端自由文本**不渲染**。后端字段只用于留痕与排障。Vue 插值天然转义且组件内无 `v-html`（实读确认），此为双重保险。

**trust 标记**：`trust === 'needs_confirmation'` 与 `group === 'global'` 在本 phase 语义完全重合 → **不额外渲染第二个徽标**（避免同义标注双份）。`trust` 仅作数据契约留存，供后续 phase（如 in-project 内部也需确认时）使用。[默认决策]

**置顶提示（迟滞触发）**：
- 触发条件：`block_order[0] === 'global'`（后端 delta 迟滞判定的结果，前端不算 delta）。
- 位置：**两个分组区之上**（query/阈值行之后、第一个组标题之前），使其与「为什么全局组在前面」的因果相邻。
- 形态：`role="status"` 的 info 提示条，`icon-[lucide--arrow-up-narrow-wide]` + 单句文案「更匹配的仓不在本项目关联范围内」。
- 与降级横幅并存时：**降级横幅在上**（可信度问题优先级高于排序解释）。[默认决策]

### C. 降级可见（RELY-03）

**触发条件**：`trace.degraded === true`（后端计算的事实）。前端**绝不**按 `router_version` 或候选内容自行推断降级。缺失 `degraded` 字段 → 视为 `false`，零提示（历史 trace 现状不变）。

**面板级醒目提示（展开态）**：
- 位置：折叠切换按钮之下、query/阈值行**之上**（即用户看到任何候选之前先看到它）。
- 形态：`role="alert" aria-live="polite"` 的 amber 告警条（逐字沿用 `CommitConfirmCard.vue:100-105` 的 DOM 形状）：
  - 图标 `icon-[lucide--triangle-alert] text-amber-500 shrink-0 mt-0.5`
  - 主句 `text-sm font-medium text-foreground`：「本次未经 LLM 推理，置信度仅供参考」
  - 次行 `text-xs text-muted-foreground`：「降级原因：{中文枚举文案}」；`degrade_reason` 缺失时**不渲染次行**（只出主句）。

**折叠态不隐藏降级**：面板 `collapsed === true` 时，标题行右侧渲染紧凑 `Badge variant="warning"`「降级」（沿用 `ChatMessageBubble.vue:1210` 的 `icon-[lucide--triangle-alert]` + 简短文字惯例）。理由：降级是可信度事实，不能被一次折叠操作藏起来。[默认决策]

**confidence 徽标降级样式**：
- `degraded === true` → **所有**候选的 confidence 徽标 `variant` 强制为 `muted`；文案格式保持 `{score%} 高/中/低` 不变（分数与分级仍是真实的 Stage 0 事实，只是未经 LLM 校验）。
- 徽标 `Tooltip` 文案切换为降级版（见 Copywriting），覆盖既有 `CONFIDENCE_TOOLTIPS`。
- **不改** `level` 值本身、不改分数、不改「分数分解」区（`score`/`breakdown` 口径由后端不变量守护，前端零介入）。

**降级原因枚举 → 中文文案（前端常量，闭集 6 值）**：

| enum | 中文文案 |
|------|---------|
| `timeout` | 上游超时 |
| `upstream_error` | 网关错误 |
| `provider_missing` | 未配置模型 |
| `unparsable` | 解析失败 |
| `no_node_index` | 无能力树索引 |
| `unknown` | 未知原因 |

🔴 **未知 key 的回退与 `SIGNAL_LABELS` 故意不同**：`SIGNAL_LABELS` 未命中时回显原始英文 key（前向兼容新信号）；`DEGRADE_REASON_LABELS` 未命中时**一律回退「未知原因」，绝不回显原始值**。理由：`degrade_reason` 的上游是异常分类，一旦后端出现非受控值（如异常名或截断的上游 body），回显即泄漏面（T-107-02 / Pitfall 10）。[默认决策]

---

## Copywriting Contract

沿用本组件家族硬编码中文惯例（`SIGNAL_LABELS` 先例，106-05 既定），**不引入 vue-i18n key**。[默认决策：与既有组件一致优先于全局 i18n 约定；该家族整体迁移属技术债]

| Element | Copy |
|---------|------|
| 本项目组标题 | `本项目关联仓（{n}）` |
| 全局组标题 | `全局候选（{n}）` |
| 跨组说明句（组级常驻） | `未关联当前平台，可能涉及跨组协作` |
| 跨组 Badge（候选级） | `跨组`（Tooltip 与 `aria-label` = 上面的完整句） |
| 置顶提示 | `更匹配的仓不在本项目关联范围内` |
| 溢出披露 trigger（收起态） | `显示其余 {n} 个候选` |
| 溢出披露 trigger（展开态） | `收起其余候选` |
| 降级横幅主句 | `本次未经 LLM 推理，置信度仅供参考` |
| 降级横幅次行 | `降级原因：{timeout→上游超时 / upstream_error→网关错误 / provider_missing→未配置模型 / unparsable→解析失败 / no_node_index→无能力树索引 / unknown→未知原因}` |
| 折叠态降级徽标 | `降级` |
| Confidence tooltip（降级态 · high） | `本次未经 LLM 推理：分级由检索分数确定性推导，未经语义校验，仅供参考` |
| Confidence tooltip（降级态 · medium） | `本次未经 LLM 推理：首位领先幅度不足且未经语义校验，请人工确认` |
| Confidence tooltip（降级态 · low） | `本次未经 LLM 推理：候选分数整体偏低，请人工选择` |
| Confidence tooltip（正常态） | 沿用既有 `CONFIDENCE_TOOLTIPS` 三条（105-UI-SPEC 原文），不改 |
| Primary CTA | `基于这些仓库创建编码方案`（既有，不改） |
| Empty state | 不适用——空组不渲染、缺字段静默降级，无占位文案 |
| Error state | 不适用——纯展示组件；manual override 失败沿用既有 `console.warn` 路径 |
| Destructive | 本 phase 无破坏性操作 |

数值格式：徽标百分比 `Math.round((score_ranked ?? score) * 100)%`？→ **不改**，徽标继续显示 `score`（Stage 0 口径，与「分数分解」合计行一致）；`score_ranked` **只用于排序**，不出现在任何可见文案中。[默认决策：避免出现「徽标 87% 但排在 91% 前面」的无法解释现象——排序差异由分组与置顶提示解释，用户不需要看到两个分数]

---

## Registry Safety

| Registry | Blocks Used | Safety Gate |
|----------|-------------|-------------|
| 无（不使用 shadcn registry / 任何第三方 registry） | 仅复用本仓既有 `ui/badge`、`ui/collapsible`、`ui/tooltip`、`ui/checkbox`、`ui/card` | not applicable — 零第三方引入，零新依赖（2026-07-30 确认；`web/pnpm-lock.yaml` 不变） |

---

## UI Considerations

### Covered（本契约已覆盖，可直接提升为 must_haves）

1. **分组分区呈现（ROUTE-01）**：`block_order?.length === 2` 时渲染「本项目关联仓（n）」/「全局候选（n）」两区；区顺序严格等于后端 `block_order`，区内按 `score_ranked ?? score` 降序；空组不渲染。**必须删除** `sortedCandidates` 的全局 `b.score - a.score` 重排（Pitfall 4）。
2. **Top-3 + pin-in + 溢出披露**：每组默认可见集 = `Top-3 ∪ (selected_by_ai || selected_by_user_final)`；剩余进组内 `Collapsible`（`显示其余 {n} 个候选`）；组标题计数为该组总数。
3. **全局组默认折叠**：`block_order[0] === 'in_project' && inProject[0]?.level === 'high'` 时默认折叠，否则展开；用户操作后本地态优先，trace 变化后重算。
4. **跨组标注两层（ROUTE-02）**：全局组标题下常驻完整句「未关联当前平台，可能涉及跨组协作」+ 每候选 `Badge variant="info"`「跨组」（Tooltip/`aria-label` 承载完整句）。
5. **迟滞置顶提示（ROUTE-02）**：`block_order[0] === 'global'` 时在两区之上渲染 info 提示条「更匹配的仓不在本项目关联范围内」（`role="status"`）；与降级横幅并存时降级在上。
6. **降级横幅（RELY-03）**：`degraded === true` 时在候选列表之前渲染 amber `role="alert"` 告警条，主句「本次未经 LLM 推理，置信度仅供参考」+ 次行「降级原因：{中文枚举}」；`degrade_reason` 缺失只出主句。
7. **折叠态降级徽标**：面板收起时标题行渲染 `Badge variant="warning"`「降级」，降级事实不被折叠隐藏。
8. **confidence 徽标降级样式**：`degraded` 时全部候选徽标 `variant="muted"`，Tooltip 切换为降级三句；`level` / `score` / `breakdown` 一律不改。
9. **降级原因文案闭集 + 不回显原始值**：前端 `DEGRADE_REASON_LABELS` 6 值 map；未命中回退「未知原因」，**绝不**回显原始字符串（T-107-02 / Pitfall 10）。`cross_group_note` 等后端自由文本一律不渲染。
10. **前端数据契约**：`RoutingCandidate` 新增 `group?` / `trust?` / `score_ranked?` / `cross_group_note?`；`RoutingDecisionData` 新增 `router_version?` / `degraded?` / `degrade_reason?` / `block_order?`（全部 optional）。
11. **后端契约要求（planner 必须落进后端 task）**：有项目上下文时 `block_order` **恒为长度 2**（即使一组为空）；无项目上下文时省略或 `["global"]`。这是前端区分两种 all-global 场景的唯一依据。
12. **override 不丢字段（Pitfall 3，必修既有缺陷）**：`stores/routing.ts` `applyManualOverride` 重建 trace 时必须从 `original` 继承 `router_version` / `degraded` / `degrade_reason` / `block_order`，且新候选保留 `group` / `trust` / `score_ranked`；后端 override 响应同步回传这些值。验收：勾选一次后降级横幅与分组分区仍在。
13. **视觉零漂移**：不新增颜色 / 字号 / 字重 / 间距值 / 组件 / 依赖；不新建 `ui/alert`；遵守 DESIGN.md Badge `:class` 禁令与彩虹卡片禁令。

### Backstop（兜底行为，executor 必须实现但无需显式设计）

1. **历史 trace 完全兼容**：无 `group` / `trust` / `degraded` / `block_order` / `score_ranked` 的 trace → 平铺列表、无组标题、无跨组 Badge、无提示条、按 `score` 降序，与今日渲染**逐像素一致**，且不抛错、不打 warn。
2. **部分字段缺失**：某候选缺 `group` → 视为 `'global'`；`score_ranked` 为 `null`/`undefined` → 回退 `score`；`degraded` 缺失 → `false`；`degrade_reason` 非受控值 → 「未知原因」。
3. **无项目上下文入口**（MCP / REST / skill_steps 产出的 trace）→ 平铺、无跨组标注（此时「跨组」无意义，标了反而误导）。
4. **展开态不持久化**：全局组折叠态与溢出披露态均为组件本地 `ref`，trace 更新后重置/重算，与既有 `expandedBreakdowns` 惯例一致。
5. **无 `v-html`**：所有新文案走 `{{ }}` 插值（组件现状实读无 `v-html`，保持）。
6. **可访问性**：降级横幅 `role="alert" aria-live="polite"`；置顶提示 `role="status"`；跨组 Badge 带 `aria-label` 完整句；折叠 trigger 为原生 `button`（Collapsible 既有行为）。
7. **测试扩充**（`web/src/components/chat/__tests__/RoutingDecisionPanel.test.ts`，现 12 passed，既有用例零回归）：
   - 区顺序等于后端 `block_order`（含 `["global","in_project"]` 置顶场景）
   - 区内按 `score_ranked` 排序（构造 `score_ranked` 与 `score` 排序相反的数据，断言按 `score_ranked`）
   - 全局组默认折叠 / 默认展开两条判定分支
   - Top-3 截断 + 已选候选 pin-in 可见 + 溢出 trigger 计数
   - 跨组说明句常驻可见 + 每个全局候选有「跨组」Badge；本项目候选无该 Badge
   - 置顶提示按 `block_order[0]` 出现/消失
   - `degraded=true` → 横幅 + 6 个枚举文案 + 徽标 `muted`；`degraded=false`/缺失 → 零提示
   - `degrade_reason` 为非受控值 → 渲染「未知原因」且不含原始值
   - 折叠面板后仍可见「降级」徽标
   - 缺全部新字段的历史 trace → 平铺渲染且既有断言全绿
   - `stores/__tests__/routing.test.ts`：override 后 `degraded` / `block_order` / 候选 `group` 不丢

### Unresolved（本 phase 明确不做 / 依赖后端裁决）

1. **「本项目关联仓」的实际口径**由后端 D-2 裁决（Space ∪ verified RepoAssociation 宽口径）；前端只消费 `group` 字段，口径变化零前端改动。
2. **OQ-1（候选范围硬过滤 → 分组依据）**：若 planner 最终不放开硬过滤，`global` 组将恒空 → 前端表现为「只渲染本项目组标题 + 列表」，行为正确但 ROUTE-01/02 无实际效果。前端无需改动，但需在 VERIFICATION 中如实记录。
3. **编排链（`ConvergenceSession`）路由结果的前端呈现**：`session.routing` / `EVENT_REPO_ROUTING` 在 web 端仍零引用（105-UI-SPEC 已记录）；本 phase 的 UI 只覆盖 chat 链的 `RepositoryRoutingTrace`。编排侧呈现 → Phase 110。
4. **降级原因的排障下钻**（脱敏后的原始异常文本）：仅入事件 payload / `SystemLogEntry`，**不做前端展开区**（A6：若开发者需要面板内看原文，那是额外权限面，需 superuser 可见性设计）→ 留后续。
5. **澄清 pending 可见性 / 超时出口标注的 UI**（RELY-02）：出口只写 `stage_state.clarification_exit`（D-6，产出渲染受 v0.20.0 DEPTH 冻结约束），本 phase 无前端渲染面。「未澄清假设」的用户可见呈现 → Phase 109/110 或 v0.20.0。
6. **组件家族 i18n 迁移**：`RoutingDecisionPanel` 家族整体硬编码中文，本 phase 跟随现状（`SIGNAL_LABELS` 惯例）；统一迁移 vue-i18n 属技术债。
7. **`trust` 字段的独立可视化**：本 phase 与 `group === 'global'` 语义重合，不渲染第二个徽标；若后续 in-project 内部也需确认态，再设计。

---

## Checker Sign-Off

- [ ] Dimension 1 Copywriting: PASS
- [ ] Dimension 2 Visuals: PASS
- [ ] Dimension 3 Color: PASS
- [ ] Dimension 4 Typography: PASS
- [ ] Dimension 5 Spacing: PASS
- [ ] Dimension 6 Registry Safety: PASS

**Approval:** pending
