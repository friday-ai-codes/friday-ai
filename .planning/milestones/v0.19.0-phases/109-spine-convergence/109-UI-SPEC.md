---
phase: 109
slug: 109-spine-convergence
status: draft
shadcn_initialized: true
preset: none（既有 web/components.json，本 phase 不跑 init、不拉 registry 块）
created: 2026-07-30
---

# Phase 109 — UI Design Contract（编排产出「进入编码」入口 + 草稿「未经代码调研」双侧标注）

> 本 phase 的 UI 面有两块，落在**一个新组件 + 一个既有组件**上：
> ① **「进入编码」入口（SPINE-01）**：新建 `OrchestratedPlanCard.vue`——编排产出后在 chat 内呈现一张最小可操作卡片，点「进入编码」触发投影，随后就地交棒给既有 `TechPlanCard.vue` 走完「选目标仓 → 配置分支 → 确认编码 → 飞书导出」四步。
> ② **草稿「未经代码调研」标注（RELY-01）**：`TechPlanCard.vue` 增量——界面横幅 + 折叠态徽标 + 送编码前的显式确认弹层；导出侧标注由后端 `_compose_plan_markdown` 渲染（文案同样在本契约内定稿，保证双侧口径一致）。
>
> **裁决 D-4 边界**：`start_plan_research` 的 chat 呈现**只做最小可操作面**。阶段流式、阶段时间线、容器日志严格留给 Phase 110，本 phase **不预建**任何进度/阶段 UI——编排在途时**不渲染任何卡片**（见 §交互契约 A.1）。
>
> AUTONOMOUS MODE：所有未决问题按既有设计系统（`web/DESIGN.md`）与代码惯例自行裁定，逐条标注 `[默认决策]`。

---

## 落点与数据链路（侦察结论）

### 落点一览

| # | 文件 | 性质 | 本 phase 增量 |
|---|------|------|--------------|
| 1 | `web/src/components/chat/OrchestratedPlanCard.vue` | **新建** | 编排产出卡片 + 「进入编码」按钮 + 就地内嵌 `TechPlanCard` |
| 2 | `web/src/components/chat/TechPlanCard.vue`（716 行，实读） | 改 | 草稿横幅、折叠态徽标、送编码确认弹层、`techPlan` 数据源三级优先、空正文占位 |
| 3 | `web/src/components/chat/ChatMessageBubble.vue` | 改 | `UNGROUPABLE_TOOLS` 加编排工具；新增 `OrchestratedPlanCard` 渲染分支；`codingPlanData` 的 `techPlan` 降级为历史兜底 |
| 4 | `web/src/composables/useToolDisplay.ts` | 改 | 登记编排工具的 `TOOL_LABELS` / `TOOL_ICONS` / `toolAction` 三处 |
| 5 | `web/src/stores/chat.ts` | 改 | `projectPlanToCodingPlan` action；fan-out 提交透传确认标志 |
| 6 | `web/src/api/chat.ts` + `web/src/types/chat.ts` | 改 | 投影端点客户端 + `CodingPlanRuntime` 契约扩字段 |
| 7 | `server/feishu/coding_plan_exporter.py::_compose_plan_markdown` | 改（后端） | 导出侧草稿告示块（文案见 §Copywriting） |

### 关键现状事实（实读，planner 直接采信）

**A. 编排产出目前在 SPA 里零可操作面**（109-RESEARCH C-3 已确认，本次复核成立）：
- `useToolDisplay.ts` 的 `TOOL_LABELS`（:23-62）与 `TOOL_ICONS`（:65-82）**无** `start_plan_research` / `start_feature_solution` 条目；`toolAction`（:291-386）的 `switch` 无对应 `case`，落到 `default` 分支产出「`space_id: xxx, requirement: xxx`」这类裸入参摘要。
- ⇒ 入口必须新建；三处登记是让它「不再是一个未翻译的 pill」的最小成本。

**B. 编排工具有两个，返回体同形**（本次侦察补充，RESEARCH 只列了前者）：

| 工具 | 位置 | 终态返回 |
|------|------|---------|
| `start_plan_research` | `server/agents/tools/plan_research_tools.py:46` | `{session_id, artifact_version_id, status:"done", message}`（`_map_terminal`，:277-292） |
| `start_feature_solution` | `server/agents/tools/feature_solution_tools.py:34` | 同族（feature list 方案编排的对话入口） |

⇒ 呈现分支**按同一套契约同时覆盖两者**（同一 `isOrchestrationTool()` 判定 + 同一张卡片）。只登记 `start_plan_research` 会让另一条编排入口继续没有编码入口，SC-1 在该入口下不成立。[默认决策]

**C. 编排在途有独立返回形态，必须显式排除**：`plan_research_tools.py:255-273` 的挂起路径返回 `{__blocking_task__: true, task_type:"plan_research", task_id, session_id, params, placeholder}`——**无 `artifact_version_id`**。这是 D-4 边界的天然抓手：卡片仅在 `status === 'done' && artifact_version_id` 非空时渲染，在途/失败一律不渲染，**无需**任何进度 UI 即可正确收边。

**D. `TechPlanCard` 的渲染触发与数据源现状**：
- 触发绑在 `isCodingPlanTool(item.name) && item.status === 'done' && codingPlanData`（`ChatMessageBubble.vue:1139-1151`）。
- `codingPlanData.techPlan` 取自 **tool input**（`:764-767`：`input.tech_plan` / `input.affected_files`）。
- ⚠️ **SPINE-02 收窄 schema 后这两个入参不存在** ⇒ 新消息的 `techPlan` 恒为空串。既有 `v-html="renderedPlan"`（`:377`）会渲染成一个空 `prose` 块（不报错、不崩，只是「方案卡里没有方案」）。这是本 phase 必须一并处置的连带面，见 §交互契约 E。
- ✅ 可直接照抄的精度纪律：`feishuDocUrl`（`:185-192`）已建立「**先本地态、再 `runtime.plan_id === props.codingPlanId` 匹配、否则空**」的三级优先，明确注释了「不串其它 plan 的已导出态」。`techPlan` 的新数据源**逐字沿用同一形状**。

**E. `CodingPlanRuntime` 字段不足**（`web/src/types/chat.ts:637-643）：现仅 `plan_id / title / sessions / feishu_doc_token / feishu_doc_url`。承载 `tech_plan` / `affected_files` / `provenance` 需两侧同步扩字段（手工对齐、无代码生成，漏一侧 TS 不报错）。

### 已就位可复用资产（零新依赖、零新色板、零新组件）

| 资产 | 位置 | 本 phase 用法 |
|------|------|--------------|
| `Badge` 8 variant | `web/src/components/ui/badge/index.ts`（实读） | 草稿折叠态徽标用 `warning`（amber-500/10）；编排产出徽标用 `success`（emerald-500/10） |
| `AlertDialog` 家族 | `web/src/components/ui/alert-dialog/`（9 文件） | 草稿送编码的显式确认弹层（阻断式风险确认，非普通 `Dialog`） |
| `Checkbox` | `web/src/components/ui/checkbox/` | 弹层内「我已了解风险」必勾项 |
| `Button` / `Input` / `Dialog` | 已在 `TechPlanCard` import | 「进入编码」按钮沿用既有 `Button`；不新增 |
| **告警条范式（同款三处）** | `CommitConfirmCard.vue:100-105`（实读）、`ContextExceededCard.vue:79-81`、`ReconcilePanel.vue:132-138` | 草稿横幅**逐字沿用**：`p-3 rounded-lg border border-amber-500/30 bg-amber-500/5` + `flex items-start gap-2` + `icon-[lucide--alert-triangle] text-amber-500 shrink-0 mt-0.5` + 主句 `text-sm font-medium text-foreground` + 次行 `text-xs text-muted-foreground` |
| `TechPlanCard` 自身的 alert 图标惯例 | `TechPlanCard.vue:633` 用 `icon-[lucide--alert-triangle]` | 草稿横幅用**同一图标名**（组件内一致优先于跨组件统一；`triangle-alert` 是同一图标的别名，不在本组件混用） |
| 折叠态徽标先例 | 107-UI-SPEC「折叠态降级徽标」+ `ChatMessageBubble.vue:1210` | 草稿徽标沿用同一语义：**事实不能被一次折叠操作藏起来** |
| 硬编码中文常量惯例 | `TOOL_LABELS`（`useToolDisplay.ts:23`）、`SIGNAL_LABELS`（106-05 既定） | 新增文案沿用硬编码中文常量，**不接 vue-i18n** |

**图标可用性已核验**（`rg` 计数）：`workflow`(11 文件)、`arrow-right`(21)、`alert-triangle`(32)、`loader-2`(48)、`shield-alert`(5) 均已在仓内使用；**`file-check-2` 仓内零使用，本契约不采用**。

---

## 前端数据契约变更（供 planner 提升为任务）

```ts
// web/src/types/chat.ts

/**
 * 编码方案来源标志（RELY-01）。与后端 CodingPlanProvenance TextChoices 字面对齐。
 *
 * 类型故意保留 `| string`：后端未来新增取值时前端不该编译失败，而应走
 * 保守分支（视为未经调研）。这让「未知取值按保守处理」成为类型层的默认，
 * 而不是依赖每个消费点自觉。
 */
export type CodingPlanProvenance = 'orchestrated' | 'draft'

export interface CodingPlanRuntime {
  plan_id: string
  title: string
  sessions: CodingPlanSessionRuntime[]
  feishu_doc_token?: string
  feishu_doc_url?: string
  // ---- [新增 109] ----
  /** 来源标志；缺失 / 未知 → 保守视为未经调研（见 §交互契约 B.1）。 */
  provenance?: CodingPlanProvenance | string | null
  /** 方案正文。SPINE-02 后前端取正文的权威来源（tool input 仅作历史兜底）。 */
  tech_plan?: string
  affected_files?: Array<{ file_path?: string, path?: string, change_type: string }>
  recommended_repository_ids?: string[]
  /** 投影来源留痕；前端**不渲染**，仅用于排障与测试断言。 */
  source_artifact_version_id?: string | null
}

/** 投影端点响应（惰性投影：点「进入编码」时触发）。 */
export interface ProjectPlanToCodingResponse {
  coding_plan_id: string
  /** false = 幂等命中既有投影（同一 ArtifactVersion 重复点击）。 */
  created: boolean
  title: string
  tech_plan: string
  affected_files: Array<{ file_path: string, change_type: string }>
  recommended_repository_ids: string[]
  provenance: CodingPlanProvenance
}
```

**后端侧硬性契约要求（planner 必须落进后端 task，否则前端无法正确渲染）**：

1. **`ConversationRuntimeCodingPlanSerializer` 与 `CodingPlanSerializer` 双侧透出 `provenance` / `tech_plan` / `affected_files` / `recommended_repository_ids`**。`provenance` **必须 read-only**（`CodingPlanSerializer` 已是全字段 read-only，保持；runtime 序列化器同理）——客户端不得伪造 `orchestrated`。
2. **投影端点响应必须直接带 `tech_plan` + `affected_files` + `provenance`**，不要求前端投影后再拉一次 runtime。理由：少一次往返 = 「进入编码」点击到卡片出现之间没有空窗，也避免 runtime 刷新时序竞态。
3. **fan-out 端点请求体新增布尔字段**（裁决 D-5，不新开端点）：
   ```
   POST /api/chat/coding-plans/{plan_id}/sessions/
   { repository_ids, branch_template?, target_branch?, acknowledge_unresearched?: boolean }
   ```
4. 🔴 **fan-out 端点的草稿拒绝响应必须带稳定机器码**，例如 `{"code": "draft_requires_explicit_confirm", "detail": "..."}`。前端**按 `code` 分支，绝不按 `detail` 文案匹配**——与「标注不靠文案硬编码」同一条纪律（错误面同样适用）。缺 `code` 则前端只能字符串匹配后端文案，一次文案微调就静默失效。
5. **`acknowledge_unresearched` 在服务端是「按需生效」的**：`provenance != draft` 时该字段被忽略、不影响结果。这是前端保守默认（缺字段视为草稿）能安全落地的前提——见 §交互契约 B.1 的理由链。

透传链（逐跳都要补）：`CodingPlan.provenance` / `.tech_plan` 列 → `chat/serializers.py`（runtime + plan 两个序列化器）→ `web/src/types/chat.ts` → `stores/chat.ts`（`activeCodingPlan`）→ `TechPlanCard.vue`。投影链：`OrchestratedPlanCard` → `stores/chat.ts::projectPlanToCodingPlan` → `api/chat.ts` → 投影端点（路径由 planner 定）。

---

## Design System

| Property | Value |
|----------|-------|
| Tool | **shadcn-vue（已初始化）**——`web/components.json` 存在：`style: new-york` / `baseColor: slate` / `cssVariables: true` / `aliases.ui = ~/components/ui`。本 phase **不跑 `shadcn init`、不从任何 registry 拉块**，仅复用 `web/src/components/ui/` 下 34 个已手工维护的组件 |
| Preset | not applicable（无 preset 串；`tailwind.config` 字段为空串，样式走 `src/styles/main.css` 的 CSS variables） |
| Component library | reka-ui（经本仓 `ui/` 封装：`Badge` / `AlertDialog` / `Checkbox` / `Button` / `Input` / `Dialog` 全部已存在，**零新增依赖**） |
| Icon library | Iconify `icon-[lucide--*]`（既有惯例）；本 phase 只用仓内已出现的图标名 |
| Font | 继承全局；分支名 / 文件路径 / 仓库名沿用 `font-mono`（DESIGN.md「mono 值」） |

> 📌 **对 107-UI-SPEC 的一处事实修正**：107-UI-SPEC 记「无 `components.json`，不跑 shadcn init」——**前半句不成立**，`web/components.json` 确实存在（本次实读）。但**结论完全不变**：既有 `ui/` 组件是手工维护的、不从 registry 拉块、不跑 init、`web/pnpm-lock.yaml` 不变。此处如实更正只为避免后续 phase 继续沿用错误前提去做「要不要 init」的判断。

---

## Spacing Scale

沿用 `TechPlanCard` / `CommitConfirmCard` 既有 Tailwind 间距，增量**不引入任何新值**：

| Token | Value | Usage |
|-------|-------|-------|
| xs | 4px（`gap-1` / `pt-1`） | 徽标与文字间距、影响文件行内间距（既有） |
| sm | 8px（`gap-2` / `space-y-2` / `pt-2` / `pb-3`→12 见下） | 横幅内图标与文案间距、弹层勾选项与正文间距、卡片区块纵向间距 |
| md | 12px（`p-3` / `px-3` / `space-y-3` / `py-3`） | 草稿横幅内边距（沿用 `CommitConfirmCard:102` 的 `p-3`）、卡片头部纵向内边距（既有）、卡片正文区块间距（既有 `space-y-3`） |
| lg | 16px（`p-4` / `px-4` / `pb-4`） | 卡片内容区内边距（既有，不改动） |

**Exceptions（既有半步值，本 phase 沿用不新增）**：`gap-1.5` / `mr-1.5`（6px，按钮图标与文字）、`py-2.5`（10px）、`mt-0.5`（2px，告警图标基线微调）、`pb-3 pt-1`（既有按钮行内边距组合）。四者在 `TechPlanCard` / `CommitConfirmCard` 中均已存在，增量复用比引入新的 4 倍数值更一致。[默认决策，沿用 107-UI-SPEC 同款裁定]

---

## Typography

沿用既有层次，**不新增字号字重**（2 主字号 / 3 字重，与 105 / 107-UI-SPEC 一致）：

| Role | Size | Weight | Line Height | 用途 |
|------|------|--------|-------------|------|
| Card title | 14px（`text-sm`） | 600（`font-semibold`） | 1.43 | 卡片头部标题（既有：`TechPlanCard:349`） |
| Body | 14px（`text-sm`） | 500（`font-medium`） | 1.43 | 草稿横幅主句、弹层正文（沿用 `CommitConfirmCard:108`） |
| Label | 12px（`text-xs`） | 500（`font-medium`） | 1.33 | 区块标签「目标仓库」/「影响文件」（既有） |
| Caption | 12px（`text-xs`） | 400 | 1.33 | 草稿横幅次行、编排卡说明句、按钮内文案、错误提示 |

**Exceptions（既有微字号，本 phase 沿用不新增）**：`text-[11px]`（仓库名 Badge，`TechPlanCard:387`）、`text-[10px]`（文件图标，`:402`）。均为既有值，增量不引入新的微字号。[默认决策]

---

## Color

**零新色板**——全部走既有语义 token 与 Badge variant（DESIGN.md 功能色系 + Badge 规范）：

| Role | Value | Usage |
|------|-------|-------|
| Dominant (60%) | `.card`（白底 `rounded-2xl` `shadow-card` `border-border/50`） | 编排产出卡与 `TechPlanCard` 共享同一卡片底，**不给新卡另设底色** |
| Secondary (30%) | `text-muted-foreground` / `border-border/50` / `divide-border/30` | 区块标签、说明句、次行文案、分隔线（既有） |
| Accent (10%) | `text-primary` / `text-foreground` | 卡片头部图标（DESIGN.md：所有卡片图标统一 primary）、标题与值文本、「进入编码」主按钮（`Button` 默认 primary） |
| 警告（草稿标注） | `border-amber-500/30` + `bg-amber-500/5` + `icon-[lucide--alert-triangle] text-amber-500` + 主句 `text-foreground` / 次行 `text-muted-foreground` | **仅草稿横幅与弹层内风险块**（DESIGN.md：amber 仅用于警告提示框） |
| 草稿折叠态徽标 | `Badge variant="warning"` | 面板收起时仍能看见「未经调研」 |
| 编排产出徽标 | `Badge variant="success"` | 编排产出卡的「已编排」（emerald 已是 `success` 既有色系，非新色板） |
| Destructive | `text-destructive`（既有，不新增用法） | 沿用 `TechPlanCard:632` 的 failed 态；**本 phase 不新增 destructive 面** |

**Accent reserved for**：卡片头部图标、卡片标题与数值文本、「进入编码」主按钮、既有 Badge variant、上述草稿横幅。

**禁止（DESIGN.md 显式禁令，本 phase 必守）**：
- ❌ **不给编排产出卡换一套配色**（彩虹卡片禁令）——它与 `TechPlanCard` 同族同色，仅靠图标 + 徽标区分语义。
- ❌ **不在新增 Badge 上用 `:class` 追加颜色**（DESIGN.md Badge 规则）。草稿徽标与编排徽标一律纯 `variant`。
  > ⚠️ 既有 `TechPlanCard:350-357` 的状态 Badge **已经违反**这条（`:class="[badgeClass]"`）。本 phase **不顺手重构它**（超出边界、会牵动 `TechPlanCard.spec.ts` 既有断言），但**新增的两个 Badge 绝不复制这个违规形状**。记入 Unresolved。
- ❌ 不用 shadcn `<Card>` 包裹（用 `.card` CSS 类，DESIGN.md 禁止项）。

---

## 交互契约

### A. 编排产出「进入编码」入口（SPINE-01）

落点采**方案 A（chat 内新增编排产出卡片）**，`ArtifactTimeline.vue` 加按钮的方案 B **本 phase 不做**——裁决 D-3 已把投影限定在 chat 入口，而项目工作台不在 chat 上下文里（投影需合成会话 + space 反查歧义）。[默认决策，与 D-3 一致]

#### A.1 渲染条件（D-4 边界的机械抓手）

新增判定（与既有 `isCodingPlanTool` 平级）：

```ts
function isOrchestrationTool(name: string): boolean {
  const bare = name.replace(/^mcp__[^_]+__/, '')
  return bare === 'start_plan_research' || bare === 'start_feature_solution'
}
```

`OrchestratedPlanCard` 仅在**三条同时成立**时渲染：

| # | 条件 | 不成立时的表现 |
|---|------|---------------|
| 1 | `isOrchestrationTool(item.name)` | 不渲染 |
| 2 | `item.status === 'done'` | 不渲染（沿用 `TechPlanCard` 的同款守卫） |
| 3 | 解析 result 得 `status === 'done'` **且** `artifact_version_id` 非空 | 不渲染 |

⇒ **编排在途**（`__blocking_task__` 形态，无 `artifact_version_id`）→ 只有既有 tool pill，**零卡片、零进度条、零阶段文案**。
⇒ **编排失败**（`ToolResult.success=false`）→ 同上，沿用既有 tool pill 失败呈现。
**这正是 D-4「最小可操作面」的落法**：不是「先做个简版进度」，而是**在途完全不呈现**，把阶段可见性整块留给 Phase 110。[默认决策]

result 解析沿用 `codingPlanData` 既有的**防御性双轨**（`ChatMessageBubble.vue:778-799`）：`result` 可能是 JSON string（snapshot / langchain_runner 路径）也可能是 dict（chat_runner 历史路径），两种都吃，解析失败返回 `null` 不抛。

#### A.2 `UNGROUPABLE_TOOLS` 必须同步

`ChatMessageBubble.vue:499` 的 `UNGROUPABLE_TOOLS` 需加入两个编排工具：

```ts
const UNGROUPABLE_TOOLS = new Set([
  'deep_analysis',
  'create_coding_plan',
  'update_coding_plan',
  'start_plan_research',      // [新增 109]
  'start_feature_solution',   // [新增 109]
])
```

🔴 **漏这一步则卡片根本不会出现**：`TechPlanCard` / `OrchestratedPlanCard` 的渲染分支只存在于 `item.kind === 'tool'` 的**单例分支**（`:1126-1151`）；未列入 `UNGROUPABLE_TOOLS` 的工具会被 `isProcessTool` 归入「分析过程」折叠面板，那条路径不渲染专属卡片。这是一个**不报错、不崩、只是入口不见**的静默失守点，验收必须显式断言。

#### A.3 卡片结构（最小可操作面）

```
.card mt-2 animate-fade-in
└─ 头部 px-4 py-3 border-b border-border/50 flex items-center gap-2
│   ├─ span.icon-[lucide--workflow].text-primary
│   ├─ span.text-sm.font-semibold  「技术方案已产出」
│   └─ Badge variant="success" class="ml-auto"  「已编排」
├─ 正文 px-4 py-3
│   └─ p.text-xs.text-muted-foreground  说明句（前端常量）
└─ 操作 px-4 pb-4 pt-1
    └─ Button（primary，默认尺寸）
         ├─ idle:    span.icon-[lucide--arrow-right].mr-1  + 「进入编码」
         └─ loading: span.icon-[lucide--loader-2].animate-spin.mr-2 + 「正在准备编码方案…」+ :disabled
```

**不渲染方案正文**：前端此刻只持有 `{session_id, artifact_version_id, status, message}`，**没有**方案标题或正文。正文在投影后由 `TechPlanCard` 承载（A.4）。因此本卡**不折叠、无展开区、无正文骨架屏**——它是一个入口，不是一个阅读面。[默认决策：这既是 D-4 的最小面，也避免为了「先展示点什么」而新开一个 `GET artifact-version` 端点]

🔴 **后端 `message` 字段不渲染**：说明句取**前端常量**。沿用 107-UI-SPEC 的 T-107-06 纪律——后端自由文本只用于留痕与排障，不进渲染路径。此处 `message` 虽是后端固定串而非 LLM 产物，但让「后端文本可直接上屏」成为惯例，下一个新增产出路径就会带着 LLM 原文上屏。[默认决策]

#### A.4 点击「进入编码」→ 投影 → 就地交棒

```
点击
 ├─ projecting = true，按钮 disabled（幂等由服务端 DB 唯一约束兜底，前端 disable 只为减少无效往返）
 ├─ await chatStore.projectPlanToCodingPlan(artifactVersionId)
 ├─ 成功 → localCodingPlanId = resp.coding_plan_id
 │          localTechPlan / localAffectedFiles / localProvenance ← resp
 │          toast：created ? 「编码方案已就绪，请选择目标仓库」: 「已复用既有编码方案」
 │          ⇒ 卡片下方就地渲染 <TechPlanCard>（四步全通）
 ├─ 失败 → toast 错误文案；projecting = false；按钮回到 idle（可重试）
 └─ finally → projecting = false
```

**交棒方式（关键设计决策）**：`OrchestratedPlanCard` 在拿到 `coding_plan_id` 后**就地内嵌** `<TechPlanCard>`，把投影响应的 `tech_plan` / `affected_files` / `provenance` / `recommended_repository_ids` 直接作为 props 传下去。

- 理由：研究 §4.3 指出投影出的 `CodingPlan` 会自动成为 `activeCodingPlan`（runtime 返回「对话内最近 CodingPlan」），**但那依赖一次 runtime 刷新**。就地内嵌 + 用投影响应直接喂 props ⇒ 点击到卡片出现之间**没有空窗、不依赖刷新时序**。`activeCodingPlan` 仍作为 sessions 状态的实时来源（`TechPlanCard` 内部既有行为，不改）。[默认决策]
- **按钮不消失**：投影完成后「进入编码」按钮**替换为**一行 `text-xs text-muted-foreground` 的已投影说明（见 §Copywriting），而不是留一个可反复点击的按钮。理由：幂等虽保证安全，但一个点了没反应的按钮是坏体验。[默认决策]

**幂等的用户可见口径**：`created === false`（同一 `ArtifactVersion` 重复投影 / 并发命中）→ **不报错、不提示异常**，只用「已复用既有编码方案」的中性 toast，卡片表现与首次一致。理由：幂等是系统正确性，不是用户需要理解的状态。[默认决策]

#### A.5 工具展示三处登记（`useToolDisplay.ts`）

| 位置 | 增量 |
|------|------|
| `TOOL_LABELS` | `start_plan_research: '方案编排调研'`、`start_feature_solution: '功能方案编排'` |
| `TOOL_ICONS` | 两者均 `'icon-[lucide--workflow]'` |
| `toolAction` | 新增 `case`：终态出 `跨仓方案编排已完成`；在途（`__blocking_task__`）出 `方案编排调研进行中`；否则回退需求文本 `编排「{truncate(requirement, 32)}」`。**不回显后端 `placeholder` / `message` 原文**（同 A.3 纪律） |

⇒ 用户在「分析过程」与 tool pill 上看到的不再是裸入参串。这三处是「最小可操作面」的**下限**，不是可选项：没有它们，用户看不出这一步做了什么。

---

### B. 草稿「未经代码调研」界面标注（RELY-01 · 界面侧）

#### B.1 判定规则（数据驱动，允许清单形式）

```ts
/**
 * 是否需要标注「未经代码调研」。
 *
 * 采**允许清单**而非拒绝清单：只有严格等于 'orchestrated' 才免标注，
 * 其余一切（'draft' / 未知取值 / null / undefined / ''）一律标注。
 */
const isUnresearched = computed(
  () => resolvedProvenance.value !== 'orchestrated',
)
```

三条硬性纪律：

1. 🔴 **不靠文案硬编码判定**：判定只读 `provenance` 字段，**绝不**匹配 `tech_plan` 正文里是否含「草稿」「未经调研」等字样。理由：新增产出路径时正文格式不可控，文案判定必然漏标。
2. 🔴 **未知取值按保守处理**：`provenance` 出现契约外取值（后端加了新枚举而前端未同步）→ **视为草稿并标注**。理由同 107-UI-SPEC 的 `DEGRADE_REASON_LABELS` 裁定——保守分支的代价是一条多余横幅，激进分支的代价是一份不可信方案看起来可信。
3. 🔴 **缺字段（`undefined` / `null`）同样标注**，且**渲染不得报错**。

**第 3 条的理由链（兼容降级口径，须显式记录）**：

- **事实基础**：后端迁移 `provenance` 带 `default="draft"`（研究 §9.3，硬约束），⇒ 迁移后**每一行都有值**；`undefined` 只可能来自「序列化器尚未透出」或「旧缓存 payload」两种过渡态。
- **存量语义对齐**：`coding_plans` 存量行**全部**是 SPINE-02 之前徒手创作的产物（研究 §9.3 / Runtime State），`undefined ≈ draft` 在事实层就是对的。
- **失败代价不对称**：把 `undefined` 当可信（不标注）= RELY-01 存在的意义被静默取消；把 `undefined` 当草稿（标注）= 过渡窗口里可能给编排产出多挂一条横幅。前者是安全缺陷，后者是观感瑕疵。
- **无功能副作用**：保守默认会让前端在送编码时弹一次确认并带上 `acknowledge_unresearched: true`。因为服务端 gate 只在 DB 里 `provenance == draft` 时才生效（后端契约要求 #5），对真正的编排方案这个标志**是无操作的**——保守默认不会误伤正常流程，只多一次点击。
- ⇒ **裁定：缺字段与未知取值一律标注，且实现必须是纯 computed 的字面比较**（不对 `undefined` 做属性访问），保证历史数据渲染零报错。[默认决策]

**不回显原始取值**：任何情况下**不把 `provenance` 的原始字符串渲染到界面上**（未知取值时尤其）。沿用 107-UI-SPEC 的 T-107-02 纪律——上游非受控值上屏即泄漏面。

#### B.2 展开态：草稿横幅

- **位置**：`TechPlanCard` 展开内容区的**最顶部**，在 markdown 正文（`:377`）**之前**——用户在读到任何方案内容前先看到「这份东西未经调研」。
- **形态**：逐字沿用 `CommitConfirmCard.vue:100-113` 的 DOM 形状：
  ```
  div.p-3.rounded-lg.border.border-amber-500/30.bg-amber-500/5   role="alert"
  └─ div.flex.items-start.gap-2
     ├─ span.icon-[lucide--alert-triangle].text-amber-500.shrink-0.mt-0.5
     └─ div.space-y-1.min-w-0
        ├─ p.text-sm.font-medium.text-foreground     主句
        └─ p.text-xs.text-muted-foreground           次行
  ```
- **可访问性**：`role="alert"`。**不加** `aria-live`——横幅随卡片首次渲染出现（非动态插入），`aria-live` 在此场景不产生播报价值反而可能重复朗读。[默认决策；与 107 的降级横幅不同，那处是可动态出现的]

#### B.3 折叠态：草稿徽标（事实不被折叠隐藏）

`TechPlanCard` 折叠态只渲染一行摘要（`:649-653`），横幅随之消失 ⇒ 必须在**始终可见的头部**补一个紧凑徽标。

- **形态**：`<Badge variant="warning">` 文案「未经调研」，**纯 variant、无 `:class` 颜色**。
- **位置与布局**：头部 Badge 区。与既有状态 Badge（`status !== 'draft'` 时渲染）的**共存规则**：
  - 草稿徽标渲染时取 `ml-auto`（占据右推位）；
  - 此时既有状态 Badge 降为 `ml-1`；
  - chevron 保持 `ml-1`；
  - 草稿徽标不渲染时，一切**回到今日现状**（状态 Badge `ml-auto`，chevron 按 `status === 'draft' ? 'ml-auto' : 'ml-1'`）。
- **展开态是否也显示徽标**：**显示**。头部常驻，与折叠态一致 ⇒ 无需在 `collapsed` 上分支，实现更简单且不会出现「展开后徽标闪没」。横幅与徽标同时可见不算重复：徽标是持久标识，横幅是解释。[默认决策]

#### B.4 影响文件 `change_type` 显示

`:404` 原样渲染 `file.change_type`。投影映射漏做 `create → add` 转换时，这里会**静默显示成 `create`**（研究 Pitfall 3）。

**本 phase 前端裁定：不在前端做兼容映射**。前端保持原样显示，**让漂移可见**。理由：前端偷偷把 `create` 显示成 `add` 会掩盖后端映射缺陷，使 Pitfall 3 变成一个永远查不出的问题。正确性由后端映射纯函数 + 显式断言保证（研究已列入测试映射）。[默认决策]

---

### C. 草稿送编码防护（RELY-01 · 显式确认）

**服务端 fail-closed 是唯一真防线**（研究 Pitfall 6）；以下前端设计只是 UX，**不是安全边界**。

#### C.1 触发范围

| 入口 | 是否走确认弹层 | 说明 |
|------|--------------|------|
| 创建态内嵌 selector 确认（`handleMultiConfirm`，`:135`） | ✅ | 主路径 |
| 追加态 Dialog 确认（同一 `handleMultiConfirm`） | ✅ | 同一处理函数，天然覆盖 |
| 单仓重试（`handleSessionRowRetry` → `retrySingleRepository`，`:213`） | ✅ | 见下方理由 |
| legacy 单仓 `handleConfirm`（`:294`，仅 `codingPlanId` 缺失时可达） | ❌ | 见 Unresolved #2 |

**重试为何也要弹层**：服务端 gate 落在 session **创建**上（`create_sessions_for_plan`），重试同样创建 session ⇒ 服务端会一致地拒绝。若前端为「用户之前已确认过」而自行补 `acknowledge_unresearched: true`，就等于前端替用户签名。

🔴 **不可协商的不变量**：**前端在任何代码路径下都不得自行填 `acknowledge_unresearched: true`。该值只能由用户在弹层里勾选 Checkbox 后产生。** 不缓存、不记忆、不因「刚才确认过」而复用。[默认决策]

#### C.2 弹层形态

用 `AlertDialog`（**不是**普通 `Dialog`）——阻断式风险确认，需要焦点陷阱与显式取消。不复用 `GlobalConfirmDialog` / `useConfirmDialog`：后者的 `ConfirmOptions` 只有 `title / description / confirmText / cancelText / variant`（实读 `useConfirmDialog.ts:3-9`），**无法承载必勾 Checkbox**；为它加一个 checkbox 字段会改动一个被 20+ 处复用的全局组件。⇒ 在 `TechPlanCard` 内局部落一个 `AlertDialog`。[默认决策]

```
AlertDialog
└─ AlertDialogContent
   ├─ AlertDialogHeader
   │   ├─ AlertDialogTitle        「该方案未经代码调研」
   │   └─ AlertDialogDescription  风险说明（见 §Copywriting）
   ├─ div.p-3.rounded-lg.border.border-amber-500/30.bg-amber-500/5   ← 与横幅同款风险块
   │   └─ label.flex.items-start.gap-2.text-sm   （label 包裹 ⇒ 点文字也能勾选）
   │      ├─ Checkbox v-model:checked="acknowledged"
   │      └─ span  「我已了解风险，仍要用该草稿送编码」
   └─ AlertDialogFooter
      ├─ AlertDialogCancel   「取消」
      └─ AlertDialogAction   「仍要送编码」  :disabled="!acknowledged"
```

**确认按钮不用 destructive 配色**。判断依据：送编码不销毁数据、不可逆性有限（产出 PR，可关闭）；destructive 红在本仓的既有语义是「错误/危险操作」（DESIGN.md 功能色系）与「删除类」（`GlobalConfirmDialog` 的 destructive 分支）。风险语义由 amber 风险块 + 必勾 Checkbox 承担已经足够；把它染红会稀释 destructive 在其他地方的信号强度。[默认决策]

**每次打开重置 `acknowledged = false`**——不跨次记忆（与 C.1 的不变量同源）。

**编排方案零摩擦**：`isUnresearched === false` 时弹层**永不出现**，`handleMultiConfirm` 行为与今日完全一致，`acknowledge_unresearched` 字段不发送（而非发 `false`）。理由：正常路径不该为异常路径付摩擦成本；不发字段也让后端日志里「带了 ack」等价于「用户确实确认过」。[默认决策]

#### C.3 服务端拒绝的兜底呈现

即便前端弹层齐备，仍可能拿到 `draft_requires_explicit_confirm`（并发改 provenance、绕过前端、前端保守判定与后端不一致等）。

- 按响应体 **`code` 字段**分支（**不匹配 `detail` 文案**，后端契约要求 #4）。
- 命中该 code → `toastError` 用**前端常量**文案（见 §Copywriting），并把弹层重新打开让用户走正规确认。
- 其余错误 → 沿用既有 `toastError(e?.message || '批量创建编码失败')`（`:160`），不改。

---

### D. 飞书导出侧标注（RELY-01 · 第二出口，后端渲染）

**渲染位置**：`server/feishu/coding_plan_exporter.py::_compose_plan_markdown`（`:184`）——界面与导出的共同瓶颈点，读 `coding_plan.provenance`，在 `parts.append(coding_plan.tech_plan)`（`:191-193`）**之前**插入告示块。

文案见 §Copywriting（与界面侧同源同口径）。三条与界面一致的纪律：

1. 判定读 `provenance` 字段，**不匹配正文文案**；
2. **允许清单**：仅 `provenance == ORCHESTRATED` 免标注，其余（含未知取值）一律标注；
3. 不把 `provenance` 原始取值写进文档。

**导出前不额外加二次警告弹层**：`ExportConfirmDialog` 保持现状。理由：草稿横幅就在同一张卡上、紧邻「导出到飞书」按钮，用户导出时已经看到标注；导出物本身也带告示。再加一层弹层是纯摩擦。[默认决策]

---

### E. SPINE-02 对前端的连带影响（`techPlan` 数据源迁移）

**必须与 SPINE-02 同 wave 落地**，否则新消息的方案卡里没有方案正文。

`TechPlanCard` 的 `techPlan` / `affectedFiles` 取值改为**三级优先**，逐字沿用 `feishuDocUrl`（`:177-192`）已建立的形状与注释纪律：

| 优先级 | 来源 | 条件 |
|--------|------|------|
| 1 | 投影响应本地态（`OrchestratedPlanCard` 传入的 props） | 非空即用 |
| 2 | `runtime.coding_plan.tech_plan` | 🔴 **必须**满足 `runtime.plan_id === props.codingPlanId`，否则不采用 |
| 3 | tool input（`codingPlanData.techPlan`） | **历史消息兜底**——SPINE-02 之前的消息里 `tech_plan` 仍在 input 里，砍掉这一级会让历史会话的方案卡集体变空 |
| 4 | `''` | 走空正文占位（见下） |

🔴 **第 2 级的 `plan_id` 匹配守卫不可省**：`activeCodingPlan` 只指向「对话内最近 CodingPlan」，多轮多方案会话里若不匹配就采用，会把**新方案的正文渲染到旧方案卡上**——不报错、不崩，只是内容串了，是最难查的一类缺陷。既有 `feishuDocUrl` 注释已经踩过并记录了这个坑（「不串其它 plan 的已导出态」），此处逐字沿用。

**空正文占位**：`techPlan` 为空且 `mdReady` 为真时，**不渲染空 `prose` 块**，改渲染一行 `text-xs text-muted-foreground` 占位文案（见 §Copywriting）。折叠态既有 `'（无方案文本）'` 兜底（`:651`）保持不变。

---

## Copywriting Contract

沿用本组件家族硬编码中文常量惯例（`TOOL_LABELS` / `SIGNAL_LABELS` 先例），**不引入 vue-i18n key**。[默认决策：与既有组件一致优先于全局 i18n 约定；该家族整体迁移属技术债，见 Unresolved #6]

### 界面侧（前端常量）

| Element | Copy |
|---------|------|
| 编排产出卡标题 | `技术方案已产出` |
| 编排产出卡徽标 | `已编排` |
| 编排产出卡说明句 | `已完成仓库路由、代码召回与并行调研，可直接进入编码执行。` |
| **Primary CTA** | `进入编码` |
| CTA loading 态 | `正在准备编码方案…` |
| CTA 完成后替换说明 | `已进入编码，请在下方选择目标仓库` |
| 投影成功 toast（`created=true`） | `编码方案已就绪，请选择目标仓库` |
| 投影幂等 toast（`created=false`） | `已复用既有编码方案` |
| 投影失败 toast | `未能进入编码，请稍后重试` |
| 草稿横幅主句 | `本方案未经代码调研` |
| 草稿横幅次行 | `由对话直接生成，未经仓库路由、代码召回与并行调研，文件清单与实现步骤可能不准确。` |
| 草稿折叠态徽标 | `未经调研` |
| 确认弹层标题 | `该方案未经代码调研` |
| 确认弹层正文 | `它由对话直接生成，未经仓库路由、代码召回与并行调研。继续送编码可能产出偏离预期的改动。建议先经技术方案编排产出正式方案。` |
| 确认弹层必勾项 | `我已了解风险，仍要用该草稿送编码` |
| 确认弹层确认按钮 | `仍要送编码` |
| 确认弹层取消按钮 | `取消` |
| 服务端 gate 拒绝 toast（按 `code` 命中） | `草稿方案需显式确认后才能送编码` |
| 空方案正文占位 | `（暂无方案正文）` |
| 工具标签 · `start_plan_research` | `方案编排调研` |
| 工具标签 · `start_feature_solution` | `功能方案编排` |
| 工具摘要 · 终态 | `跨仓方案编排已完成` |
| 工具摘要 · 在途 | `方案编排调研进行中` |
| 工具摘要 · 兜底 | `编排「{需求文本截断 32 字}」` |
| Empty state | **不适用**——编排在途/失败不渲染卡片（A.1），无空态占位文案（阶段可见性 → Phase 110） |
| Error state | 投影失败走 toast（上表）；编排失败沿用既有 tool pill 呈现，本 phase 不新增错误面 |
| Destructive | **本 phase 无破坏性操作**。草稿送编码是「有后果但可逆」，用 amber 风险块 + 必勾 Checkbox + 非 destructive 确认按钮（理由见 §C.2） |

### 导出侧（后端 `_compose_plan_markdown` 渲染，与界面同源口径）

```markdown
> ⚠️ **本方案未经代码调研**
>
> 由对话直接生成，未经仓库路由、代码召回与并行调研，文件清单与实现步骤可能不准确。正式方案请经技术方案编排产出。
```

主句与次行前半段**与界面侧逐字一致**（`本方案未经代码调研` / `由对话直接生成，未经仓库路由、代码召回与并行调研，文件清单与实现步骤可能不准确。`），导出侧仅追加一句行动指引（`正式方案请经技术方案编排产出。`）。理由：双侧口径一致才能让用户在界面与文档间建立同一心智；导出物脱离上下文流转，多一句指引值得。[默认决策]

---

## Registry Safety

| Registry | Blocks Used | Safety Gate |
|----------|-------------|-------------|
| 无（不从 shadcn 官方 registry 或任何第三方 registry 拉块） | 仅复用本仓既有手工维护组件：`ui/badge`、`ui/alert-dialog`、`ui/checkbox`、`ui/button`、`ui/input`、`ui/dialog` | not applicable — 零第三方引入、零新依赖、不执行 `shadcn add` / `shadcn init`（2026-07-30 确认；`web/pnpm-lock.yaml` 不变） |

> `web/components.json` 虽存在（见 §Design System 的事实修正），但本 phase **不触发任何 registry 拉取动作**，故无需 `shadcn view` 审源门。

---

## UI Considerations

### Covered（本契约已覆盖，可直接提升为 must_haves）

1. **新建 `OrchestratedPlanCard.vue`（SPINE-01 入口）**：`.card` 同族形态，头部 `icon-[lucide--workflow]` + 「技术方案已产出」+ `Badge variant="success"`「已编排」，正文一句前端常量说明，操作区一个 primary「进入编码」按钮。**不渲染方案正文、不折叠、无进度 UI**。
2. **渲染条件三条同时成立**：`isOrchestrationTool(name)` && `item.status === 'done'` && result 解析得 `status === 'done'` 且 `artifact_version_id` 非空。**编排在途（`__blocking_task__`，无 `artifact_version_id`）与失败一律不渲染任何卡片**——这是 D-4「最小可操作面」的机械落法。
3. **两个编排工具同时覆盖**：`start_plan_research` **与** `start_feature_solution` 走同一判定、同一卡片。只做前者会让另一条编排入口继续没有编码入口。
4. 🔴 **`UNGROUPABLE_TOOLS` 必须加入两个编排工具**（`ChatMessageBubble.vue:499`）。漏改则卡片被归入「分析过程」折叠面板、**渲染分支根本不执行**——不报错、只是入口不见。必须有显式断言。
5. **投影交互与就地交棒**：点击 → `projecting` disabled → `projectPlanToCodingPlan(artifactVersionId)` → 成功后**就地内嵌 `<TechPlanCard>`**，props 直接取投影响应（不等 runtime 刷新）；按钮替换为已投影说明行；失败可重试。
6. **幂等的中性呈现**：`created === false` 用「已复用既有编码方案」中性 toast，卡片表现与首次一致，不报错、不提示异常。
7. **工具展示三处登记**（`useToolDisplay.ts`）：`TOOL_LABELS` 两条、`TOOL_ICONS` 两条（均 `icon-[lucide--workflow]`）、`toolAction` 一个 `case`（终态/在途/兜底三分支）。
8. **草稿判定为数据驱动的允许清单**：`isUnresearched = provenance !== 'orchestrated'`。**只有严格等于 `'orchestrated'` 免标注**；`'draft'` / 未知取值 / `null` / `undefined` / `''` 一律标注。**禁止**匹配 `tech_plan` 正文文案判定。
9. **草稿横幅（展开态）**：位于 markdown 正文**之前**，逐字沿用 `CommitConfirmCard.vue:100-113` 的 amber 告警条 DOM 形状，主句 `本方案未经代码调研` + 次行说明，`role="alert"`。
10. **草稿徽标（头部常驻）**：`Badge variant="warning"`「未经调研」，展开与折叠态**都渲染**；渲染时取 `ml-auto`、既有状态 Badge 降 `ml-1`；不渲染时布局回到今日现状。**纯 variant，禁止 `:class` 追加颜色**。
11. **送编码确认弹层（RELY-01 显式确认）**：局部 `AlertDialog`（不复用 `useConfirmDialog`——其 `ConfirmOptions` 无法承载 Checkbox）+ amber 风险块 + 必勾 `Checkbox` 解锁「仍要送编码」+ 非 destructive 确认按钮 + 每次打开重置勾选。
12. 🔴 **`acknowledge_unresearched` 只能由用户勾选产生**：前端任何路径都不得自行填 `true`、不缓存、不记忆。覆盖创建态确认、追加态确认、**单仓重试**三条路径（重试同样创建 session、同样被服务端 gate 拦，因此必须同样走弹层）。
13. **编排方案零摩擦**：`isUnresearched === false` 时弹层永不出现，`acknowledge_unresearched` **不发送**（而非发 `false`），`handleMultiConfirm` 行为与今日一致。
14. **服务端拒绝按 `code` 分支**：命中 `draft_requires_explicit_confirm` → 前端常量 toast + 重新打开弹层；其余错误沿用既有 `toastError` 路径。**绝不匹配 `detail` 文案**。
15. **导出侧标注（RELY-01 第二出口）**：`_compose_plan_markdown` 在正文之前插 amber 告示 blockquote，判定同样读 `provenance` 的允许清单，主句与次行前半段与界面**逐字一致**。
16. **`techPlan` 数据源三级优先（SPINE-02 连带，必须同 wave）**：投影响应本地态 > `runtime.coding_plan.tech_plan`（🔴 **必须** `runtime.plan_id === props.codingPlanId` 守卫）> tool input（历史消息兜底，不可删）> `''`；空正文渲染 `（暂无方案正文）` 占位而非空 `prose` 块。
17. **前端数据契约扩字段**：`CodingPlanRuntime` 增 `provenance?: CodingPlanProvenance | string | null` / `tech_plan?` / `affected_files?` / `recommended_repository_ids?` / `source_artifact_version_id?`（后者不渲染）；新增 `ProjectPlanToCodingResponse`。`provenance` 类型故意含 `| string`，让未知取值走保守分支而非编译失败。
18. **后端契约要求（planner 必须落进后端 task）**：① runtime + plan 两个序列化器双侧透出新字段，`provenance` read-only；② 投影响应直接带 `tech_plan` / `affected_files` / `provenance`，不要求前端二次拉取；③ fan-out 请求体加 `acknowledge_unresearched?: boolean`；④ **拒绝响应必须带稳定 `code` 字段**；⑤ `acknowledge_unresearched` 在 `provenance != draft` 时被忽略（这是前端保守默认能安全落地的前提）。
19. **`change_type` 不做前端兼容映射**：原样显示，让 `create → add` 漂移（Pitfall 3）可见，不掩盖后端映射缺陷。
20. **视觉零漂移**：不新增颜色 / 字号 / 字重 / 间距值 / `ui/` 组件 / npm 依赖；遵守 DESIGN.md 的彩虹卡片禁令、Badge `:class` 禁令、`<Card>` 禁令；新卡与 `TechPlanCard` 同族同色，仅靠图标与徽标区分语义。

### Backstop（兜底行为，executor 必须实现但无需显式设计）

1. **历史数据零报错**：无 `provenance` / `tech_plan` / `affected_files` 字段的 runtime 与历史消息 → 判定走纯字面比较（不对 `undefined` 做属性访问）、正文走 tool input 兜底、卡片正常渲染，**不抛错、不打 warn**。
2. **存量方案将集体出现草稿标注**：迁移 `default="draft"` ⇒ 历史会话里所有徒手创作的 `CodingPlan` 卡片都会出现「未经调研」横幅与徽标。这是 **RELY-01 的预期行为**（存量确实全是徒手产物，保守标注是正确的），**不是回归**——需在 UAT/VERIFICATION 中如实记录，避免被判为缺陷。
3. **result 解析防御性双轨**：编排工具 result 为 JSON string / dict 两种形态都吃，解析失败返回 `null` 不抛（沿用 `codingPlanData:778-799` 既有形状）。
4. **`artifact_version_id` 为 `null`**（`_map_terminal` 在 `current_artifact_version_id` 为空时会返回 `null`）→ 视为不满足渲染条件，不渲染卡片、不抛错。
5. **投影期间的重复点击**：按钮 `disabled` 期间不重复发请求；即便重复到达，服务端 DB 唯一约束 + `IntegrityError` 分支保证只产一行，前端按 `created=false` 走幂等 toast。
6. **多方案会话不串态**：`runtime.coding_plan` 的任何消费（`techPlan` / `affectedFiles` / `provenance` / `feishuDocUrl`）都必须过 `runtime.plan_id === props.codingPlanId` 守卫。
7. **不回显后端自由文本**：编排工具的 `message` / `placeholder`、错误响应的 `detail`、`provenance` 原始取值一律不进渲染路径；说明句与错误文案全部取前端常量。
8. **无 `v-html` 新增面**：新文案全走 `{{ }}` 插值。`TechPlanCard:377` 既有 `v-html="renderedPlan"` 是 markdown 渲染路径（既有，不动）；**新增的横幅、徽标、弹层、占位文案一律不得使用 `v-html`**。
9. **可访问性**：草稿横幅 `role="alert"`（不加 `aria-live`，理由见 §B.2）；弹层焦点陷阱由 reka-ui `AlertDialog` 提供；Checkbox 用 `<label>` 包裹使点击文字也能勾选；确认按钮 `disabled` 时携带 `aria-disabled`。
10. **弹层状态不持久化**：`acknowledged` 为组件本地 `ref`，每次打开重置 `false`；不写 store、不入 localStorage。
11. **测试扩充**：
    - `web/src/components/chat/__tests__/OrchestratedPlanCard.spec.ts`（**新**）：三条渲染条件各自不成立时不渲染；`__blocking_task__` 形态不渲染；点击触发投影 action 并把 `coding_plan_id` 交给内嵌 `TechPlanCard`；`created=false` 走幂等 toast；投影失败按钮可重试；result 为 string / dict 两形态都解析。
    - `web/src/components/chat/__tests__/TechPlanCard.spec.ts`（**加用例**，既有断言零回归）：`provenance='draft'` → 横幅 + 徽标；`'orchestrated'` → 两者皆无且弹层不出现；`undefined` / `null` / `'weird_value'` → **均**渲染横幅且**不含**原始取值字符串；折叠后徽标仍可见；草稿路径点确认 → 弹层出现且确认按钮初始 disabled；勾选后启用；确认后提交体含 `acknowledge_unresearched: true`；编排路径提交体**不含**该字段；重试路径同样弹层；`code=draft_requires_explicit_confirm` → 常量文案 toast；空 `techPlan` → 渲染占位而非空 prose。
    - `web/src/composables/__tests__/useToolDisplay.spec.ts`（**加用例**）：两个编排工具的 label / icon / action 三分支。
    - `web/src/components/chat/__tests__/chatMessageBubble.parts.spec.ts`（**加用例**）：两个编排工具在 `UNGROUPABLE_TOOLS` 内（不被归入「分析过程」）；`techPlan` 三级优先各分支（含 `plan_id` 不匹配时不采用 runtime）。
    - 后端：`tests/test_coding_plan_exporter.py` 加 draft 告示用例（含未知 provenance 取值也标注）。

### Unresolved（本 phase 明确不做 / 依赖后端裁决）

1. **`ArtifactTimeline.vue` 加「进入编码」按钮（研究 §6.1 方案 B）**：**本 phase 不做**。裁决 D-3 把投影限定 chat 入口；项目工作台无 conversation，投影需建合成会话且 `space` 反查有歧义（`ConvergenceSession` 无 space FK）。该组件保持纯只读。→ 覆盖 workflow / MCP 入口的投影入口留后续。
2. **legacy 单仓 `handleConfirm` 路径不加草稿 gate**：该路径仅在 `codingPlanId` 缺失时可达，此时前端拿不到 `provenance`、服务端也无 `plan_id` 可据以判定；且它确认的是**已存在**的 session（session 创建才是 gate 落点）。故不覆盖。若后续该路径仍有真实流量，需先补 plan 关联再谈 gate。
3. **`TechPlanCard` 状态 Badge 的 `:class` 颜色违规不顺手修**：`:350-357` 的 `:class="[badgeClass]"` 违反 DESIGN.md Badge 禁令，但重构会牵动 `TechPlanCard.spec.ts` 既有断言且超出本 phase 边界。**本 phase 新增的两个 Badge 不复制该形状**。→ 记为技术债。
4. **阶段进展 / 流式输出 / 阶段时间线 / 容器日志**：裁决 D-4 明确留给 **Phase 110**（复用 107 事件源）。本 phase 编排在途完全不呈现，**不预建任何进度 UI**。
5. **导出前二次警告弹层**：不做（§D 理由：草稿横幅已紧邻导出按钮，导出物本身带告示，再加弹层是纯摩擦）。
6. **组件家族 i18n 迁移**：`TechPlanCard` / `useToolDisplay` 家族整体硬编码中文，本 phase 跟随现状（`TOOL_LABELS` / `SIGNAL_LABELS` 惯例）；统一迁移 vue-i18n 属技术债。
7. **`render_merged_plan_markdown` 的 lark_md 方言（研究 Pitfall 8）**：投影出的 `tech_plan` 用 `•` 而非 `- ` 列表，在 `TechPlanCard` 的 markdown-it（GFM）下会显示为纯文本项目符号而非 `<ul>`。**本 UI-SPEC 的裁定：接受现状，不 fork 渲染器**（可读、语义不丢）。若 UAT 判为观感不可接受，处置方式是给该函数加 `flavor: 'lark_md' | 'gfm'` 参数，**绝不新建第二个渲染器**。planner 应把这个二选一写进任务而非留给 executor 现场发挥。
8. **`provenance` 之外的可信度分级**（如「部分调研」中间态）：本 phase 只有二元 `orchestrated | draft`。若后续出现中间态，允许清单判定（`!== 'orchestrated'` 即标注）会把它归入草稿侧——**这是有意的保守default**，届时需显式扩展判定而非依赖现状。
9. **`source_artifact_version_id` 的用户可见追溯**（从编码方案点回编排产物）：本 phase 字段透出但**不渲染**。追溯 UI 留后续。

---

## Checker Sign-Off

- [ ] Dimension 1 Copywriting: PASS
- [ ] Dimension 2 Visuals: PASS
- [ ] Dimension 3 Color: PASS
- [ ] Dimension 4 Typography: PASS
- [ ] Dimension 5 Spacing: PASS
- [ ] Dimension 6 Registry Safety: PASS

**Approval:** pending
