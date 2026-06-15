# Phase 32 — UI Review（一键摄取编排）

**Audited:** 2026-06-15
**Baseline:** `.planning/phases/32-one-click-ingest/32-UI-SPEC.md`
**Screenshots:** 未捕获（dev server 在 :5173 返回 302，路由受登录鉴权拦截；本次为代码级审计）
**Status:** ADVISORY（非阻断）

---

## Pillar Scores

| Pillar | Score | Key Finding |
|--------|-------|-------------|
| 1. Copywriting | 4/4 | 全文案取自 `zh-CN.json` `ingest.*`，与契约逐字一致，守护测试以真实 JSON 断言 |
| 2. Visuals (hierarchy + states) | 3/4 | 7 态全覆盖、层级清晰；派发成功到首轮轮询之间有短暂空窗，failed 与 partial 复用同一文案 |
| 3. Color | 3/4 | 状态语义色严格映射、严守 `@theme` 令牌；`text-primary` 外溢到「查看」外链，超出 reserved-for 清单 |
| 4. Typography | 3/4 | 3 档字号达标；使用了 `font-medium`（第 3 档字重），超出契约声明的 2 档（但与 ReconcilePanel/SPEC 组件分解一致）|
| 5. Spacing | 4/4 | 8-pt 体系，`p-5 / space-y-8 / space-y-4 / space-y-3`，header `py-3.5` 与 ReconcilePanel 完全对齐 |
| 6. Experience Design | 3/4 | 状态全覆盖 + toast + 错误处理 + 聚焦首个错误字段 + `aria-invalid`；首轮拉取空窗、装饰图标缺 `aria-hidden` |

**Overall: 20/24**

---

## Top 3 Priority Fixes

1. **编排级 `status==='failed'` 复用「部分步骤未完成」文案** — 硬失败被描述成"部分未完成"，对用户语义误导。`IngestPanel.vue:227` 在 `run.status === 'failed'` 分支渲染 `ingest.run.partial`。建议在 `ingest.run` 增加 `failed` 文案（如「摄取失败，请查看下方各步骤详情后重试」）并在该分支引用，同步更新契约 Copywriting 表。
2. **派发成功到首轮 `getRun` 返回之间存在空白闪烁** — `runId` 已置位 → 空态被隐藏，但 `run` 仍为 `undefined` → `v-else-if="run"` 不成立，结果区短暂空白，用户失去即时反馈。建议在「`runId` 存在但 `run` 未到」时渲染一个轻量 running 占位（顶部 spinner + 三行 pending 骨架），与契约 States「Running」预期对齐。
3. **强调色 `text-primary` 外溢到「查看」外链** — 契约 Color「Accent reserved-for」仅列出 CTA / 卡片标题图标 / running spinner 三处，未含外链。`IngestPanel.vue:256` 的链接用了 `text-primary`。建议二选一：将外链颜色改为中性（如 `text-muted-foreground hover:text-foreground`），或在契约 reserved-for 显式追加「结果外链」以使实现合规。

---

## Detailed Findings

### Pillar 1: Copywriting (4/4)
- 页面/卡片标题、副标题、表单 label/placeholder、CTA、校验错误、空态、run 状态、三步骤名、四状态文案全部经 `t('ingest.*')` 渲染，无硬编码字符串。
- `web/src/locales/zh-CN.json:229-268` 的 `ingest` 命名空间与契约 i18n Keys 逐字一致。
- 守护测试 `IngestPanel.spec.ts:69-71` 直接断言真实 `zh-CN.json`（标题/CTA/步骤名），符合契约 Acceptance #9。
- 唯一瑕疵归入 Pillar 2/6：契约未提供编排级 `failed` 专属文案，实现复用 `partial`（语义偏差，非文案缺失）。

### Pillar 2: Visuals — hierarchy + states (3/4)
- 视觉层级清晰：卡片 header（teal 引导图标 + semibold 标题 + muted 副标题）与 ReconcilePanel 完全同构，结果区焦点为顶部 run 状态行 + 固定三步。
- 状态全覆盖（契约 States 表 7 态）：Idle/Empty、Field invalid、Dispatching、Running、Partial、Success、Run load error 均有对应渲染分支。
- 固定三行渲染（`IngestPanel.vue:83-90, 233-266`）保证布局可预期，无值步骤回退 `pending`（`circle-dashed`）。
- **WARNING** `IngestPanel.vue:227` — 硬失败 (`run.status==='failed'`) 文案复用 `ingest.run.partial`；图标为 destructive `alert-circle`、文案却是"部分未完成"，图文语义不一致。
- **WARNING** 派发成功后、首轮 `getRun` 返回前结果区空白（无 Running 占位），与 States「Running」即时反馈预期有缺口。

### Pillar 3: Color (3/4)
- 状态语义色严格对齐契约：ok→`text-emerald-600 dark:text-emerald-400`、failed→`text-destructive`、skipped→`text-amber-700 dark:text-amber-400`、pending→`text-muted-foreground`（`IngestPanel.vue:108-134`），比 ReconcilePanel（`emerald-500`）更贴合契约。
- 无硬编码 hex / rgb；全部走 Tailwind 令牌类。
- Accent（`text-primary`）用于 CTA、header 图标、running spinner —— 符合 reserved-for。
- **WARNING** `IngestPanel.vue:256` 外链使用 `text-primary`，超出契约 Accent reserved-for 三项白名单（轻度泛用）。

### Pillar 4: Typography (3/4)
- 字号 3 档：`text-xl`（页面 h1）、`text-sm`（标题/正文）、`text-xs`（label/元信息/error），符合契约「3 档」。`CompactEmptyState` 的 `text-2xl` 为装饰图标，不计入文本层级。
- **WARNING** 字重出现 `font-medium`（`IngestPanel.vue:218, 243`）即第 3 档，超出契约 Typography 表声明的「regular + semibold 共 2 档」。但契约自身 Component Breakdown（`StepRow` 步骤名 `text-sm font-medium`）已要求该字重，且 ReconcilePanel 同样使用 —— 属契约内部表述不一致，实现忠于细化分解，故判轻微。

### Pillar 5: Spacing (4/4)
- 8-pt 体系达标：外层 `space-y-8`（表单卡片 ↔ 结果区）、表单 `p-5 space-y-4`、字段组 `space-y-1.5`(6px)、结果卡片 `p-5 space-y-4`、步骤列表 `space-y-3`、图标文字 `gap-2`。
- header `px-5 py-3.5`(14px) 虽非 8 倍数，但与 ReconcilePanel `:109` 完全一致（reuse-first，跨面板视觉对齐优先），可接受。
- 无任意值 `[..px]`/`[..rem]`（仅 CompactEmptyState 内部 `text-[10px]` 属既有组件，不在本期范围）。

### Pillar 6: Experience Design (3/4)
- 反馈完整：派发 `useToast` 成功提示 + `useErrorHandler` 异常兜底（`IngestPanel.vue:63-67`）。
- 校验交互：空/非 http(s) 内联报错且 `focusField` 聚焦首个错误字段（`:51-58`），不发起请求 —— 符合 Acceptance #3。
- 轮询范式：`refetchInterval` running→2000ms、completed/failed 停轮（`:76`），与 reconcile 一致。
- 加载错误不清空已有结果（`v-if="isRunError"` 错误行与 `v-else-if="run"` 结果并存，`:202-215`）—— 符合 Acceptance #8。
- 无障碍增强：`aria-invalid` 绑定到 Input（超出契约要求）。
- **WARNING** 首轮拉取空窗（同 Pillar 2）。
- **WARNING** 装饰性状态/spinner 图标 `<span>` 未加 `aria-hidden="true"`；多为空 span 通常被 AT 忽略，影响轻微但建议补全以稳健。

---

## Spec Compliance Spot-Check（用户指定校验点）

| 校验点 | 结果 | 证据 |
|--------|------|------|
| 路由 `/knowledge/ingest` | PASS | `pages/knowledge/ingest.vue` 存在；`typed-router.d.ts:216` 注册 |
| 侧边栏入口 | PASS | `AppSidebar.vue:86` `{ to:'/knowledge/ingest', label:'一键摄取', icon:'lucide--download' }` |
| 三步结果 + 语义色 | PASS | `IngestPanel.vue:233-266` 固定三行，状态色映射 `:108-134` |
| dispatch → poll | PASS | `useMutation` 派发 + `useQuery` 条件 `refetchInterval`（`:43-77`）|
| i18n zh-CN | PASS | `zh-CN.json:229-268` 与契约逐字一致 |
| API 契约对齐 | PASS | `api/ingest.ts` 类型/端点与契约 §API Contract 一致；`api/index.ts` barrel 导出（见 spec 要求）|
| 复用既有组件/令牌 | PASS | `.card`/`Input`/`Button`/`Label`/`CompactEmptyState`/`PageContainer`，无新增字体/颜色变量/第三方 registry |
| 无障碍（Label/aria-live/noopener/非仅色彩） | PASS | `:160,174`(for/id)、`:200`(aria-live)、`:255`(rel=noopener)、状态并列文字 |

---

## Registry Safety
契约声明无第三方 registry（仅复用已落地 `~/components/ui/*`），实现未引入新 registry，安全门不适用。Registry audit: 0 third-party blocks，no flags。

---

## Files Audited
- `.planning/phases/32-one-click-ingest/32-UI-SPEC.md`（基线）
- `web/src/pages/knowledge/ingest.vue`
- `web/src/components/knowledge/IngestPanel.vue`（核心）
- `web/src/api/ingest.ts`
- `web/src/locales/zh-CN.json`（`ingest` 命名空间）
- `web/src/components/layout/AppSidebar.vue`（nav entry）
- `web/src/components/common/CompactEmptyState.vue`（复用组件）
- `web/src/components/repository/ReconcilePanel.vue`（一致性对照基准）
- `web/src/components/knowledge/__tests__/IngestPanel.spec.ts`（守护测试佐证）
- `web/src/typed-router.d.ts`（路由注册佐证）
