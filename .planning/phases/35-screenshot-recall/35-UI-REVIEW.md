# Phase 35 — UI Review（截图识需求）

**Audited:** 2026-06-15
**Baseline:** 35-UI-SPEC.md（已批准设计契约）
**Screenshots:** 未捕获（无 dev server，端口 3000/5173/8080/10240 均无响应）→ 代码审计
**Scope note:** 工具/管理类面板（utility/admin），按此标准评判（功能正确性 > 视觉表现力）
**Verdict:** ADVISORY（非阻断）

---

## Pillar Scores

| Pillar | Score | Key Finding |
|--------|-------|-------------|
| 1. Copywriting | 4/4 | 全量走 `screenshotRecall.*` i18n，无硬编码；`results.source` 为未使用死 key |
| 2. Visuals（布局/层级） | 4/4 | 层级清晰，所有图标均与文字配对且 `aria-hidden`，无裸 icon 按钮 |
| 3. Color | 4/4 | accent（teal）严格按 reserved 清单使用；emerald/amber/destructive 语义色到位；无硬编码色值 |
| 4. Typography | 4/4 | 仅 `text-xl/sm/xs` 三档 + `font-semibold/medium/normal` 两字重，符合契约 |
| 5. Spacing | 4/4 | 严格 8pt scale（`space-y-8/6`、`p-5`、`px-5 py-3.5`、`min-h-40`），无 arbitrary `[..px]` |
| 6. Experience Design（状态/a11y/响应式/反馈） | 3/4 | 6 态 + 上传 a11y 覆盖优秀；首次失败 error 与 empty 双重渲染、`/admin` 整页跳转两处瑕疵 |

**Overall: 23/24**

---

## Top 3 Priority Fixes

1. **首次识别失败时 error 文案与空态「尚未上传截图」同时出现** — 用户在失败后看到"识别失败"红字 *下方* 还显示"尚未上传截图"空态，信息相互矛盾，弱化错误感知 — 把 empty `CompactEmptyState` 改为 `v-else-if="!isError"`，或将 error 并入 `isPending → result → empty` 链，确保 error 态下不渲染 empty。
2. **降级卡片「前往系统设置」用 `<a href="/admin">` 触发整页刷新** — SPA 状态丢失、白屏闪烁，与项目内部导航惯例不一致 — 改用 `<RouterLink to="/admin">`（保留 `inline-flex … text-primary hover:underline` 类）。
3. **契约字段/文案未落地：`results.source`（"来源"）i18n key 与 API `source`/`query` 字段均未渲染** — 死 key 与未用字段让契约失真，后续易误判 — 要么在召回项 meta 行渲染 `source`（"来源 {source}"），要么删除 `results.source` key 并在 API 注释标注 `source`/`query` 暂不展示。

---

## Detailed Findings

### Pillar 1: Copywriting (4/4)
- 全部用户可见文案经 `t('screenshotRecall.*')`，组件内无硬编码中文字符串（`ScreenshotRecallPanel.vue` 全文核对）。
- i18n 块 `zh-CN.json:271-317` 与 UI-SPEC「i18n Keys」逐项一致：CTA「开始识别/识别中…」、empty/noResults/error/degraded/validation/semantics/results 全覆盖。
- 校验三态文案到位：`invalidType` / `tooLarge` / `required`（`handleFile`、`onSubmit`）。
- 次要：`screenshotRecall.results.source`（"来源"，`zh-CN.json:314`）为**未使用死 key**——召回项 meta 行（`ScreenshotRecallPanel.vue:376-384`）只渲染 `work_item_id` + `relevance`，未渲染 `source`。
- 次要：侧边栏与标题统一用缩写「截图识需求」（`AppSidebar.vue:87`、`zh-CN.json:272`），与契约一致（契约本身即此缩写），但与口语「截图识别需求」略有差异——属一致的有意命名，不扣分。

### Pillar 2: Visuals (4/4)
- 焦点明确：上传卡片 dropzone（`min-h-40` 大热区）为主视觉，结果区次之。
- 视觉层级通过 size/weight 区分：页 `h1.text-xl.font-semibold` → 卡标题 `text-sm.font-semibold` → 正文 `text-sm` → meta `text-xs.text-muted-foreground`。
- 无裸 icon 按钮：移除（`icon + 移除`）、提交（`spinner + 文案`）、语义折叠（`icon + 标题 + 展开/收起 + chevron`）、降级链接（`icon + 文案`）均文字配图标，所有装饰 icon `aria-hidden="true"`。
- header 结构与 `IngestPanel.vue:163-173` 同构（`icon-[lucide--scan-search].text-primary` + 标题 + 副标题）。

### Pillar 3: Color (4/4)
- accent（`primary`/teal）严格限定于契约 reserved 清单：header 图标（`:164`）、提交按钮默认 primary 底（`:246`）、语义卡 toggle 图标（`:318`）、外链「查看」（`:390`）、降级链接（`:298`）、loading spinner（`:273`）、dropzone 悬停/拖拽态（`hover:border-primary/60`、`border-primary bg-primary/5`，`:183-184`）。
- 语义状态色与文字并列（满足 WCAG 1.4.1）：relevance `text-emerald-600`（`:380`）、degraded `text-amber-700`（`:289`）、error/validation `text-destructive`（`:239,:264`）。
- 无硬编码 `#hex`/`rgb()`，全部经既有 token。
- 轻微：dropzone 内「选择截图」用 `text-primary`（`:200`）作为非交互文本——看似链接但整块 dropzone 即 `role=button`，可接受。

### Pillar 4: Typography (4/4)
- 文本尺寸仅 `text-xl`（页标题）/`text-sm`（标题+正文）/`text-xs`（meta），符合契约「3 个尺寸」（`text-2xl` 仅用于装饰 icon，非文本）。
- 字重仅 `font-semibold`（标题）/`font-medium`（召回项标题、文件名）/默认 `font-normal`，符合「2 字重 + 默认」。

### Pillar 5: Spacing (4/4)
- 根容器 `space-y-8`（对齐 IngestPanel 与契约 xl）；结果区 `space-y-6`（lg）；卡片体 `p-5 space-y-4`（md）；header `px-5 py-3.5`（与 IngestPanel 逐像素一致）。
- dropzone `min-h-40`（≥160px，满足契约触控/拖拽热区例外）。
- 召回列表 `ul.space-y-3`、meta `gap-2`、段内 `space-y-0.5`——全部命中标准 scale。
- 无 arbitrary `[..px]`/`[..rem]` 值。

### Pillar 6: Experience Design (3/4)
**状态机（8 态）覆盖完整：**
- `empty`（`:410` CompactEmptyState `lucide--image`）、`selected`（`:214` preview）、`invalid`（`:237` 红字 `role=alert` + toast + `focusDropzone`）、`loading`（`:271` Skeleton×3 + spinner + `aria-busy`）、`degraded`（`:284` amber `alert-triangle` 卡 + `/admin` 链接，经 `onSuccess` 不弹 error toast）、`success`、`no-results`（`:399` `lucide--search-x`）均有专属 UI。
- error 保留上次结果：`isError` 的 `<p>`（`:262`）独立于 `result` 渲染链，重试后旧结果不清空——符合契约。

**a11y（上传可达性）非常强：**
- dropzone `role="button"` + `tabindex="0"` + `aria-label` + `aria-describedby="recall-dropzone-hint"`（`:179-182`），Enter/Space 激活（`:187-188`）。
- 隐藏 input 用 `class="sr-only"`（`:207`，可聚焦/读屏，未用 `display:none`）。
- 结果区 `aria-live="polite"` + `:aria-busy="isPending"`（`:260`）；校验文案 `role="alert"` 即时播报。
- 图片预览 `:alt`（`:217`）；`revokePreview()` 在替换/移除/卸载三处调用（`:80,:121,:154`），无 objectURL 泄漏。
- 焦点管理：校验失败/移除后 `focusDropzone()`（`nextTick` + dropzone v-if 重渲染保证可聚焦）。

**响应式 / 反馈：** `max-w-3xl`、按钮 `w-full sm:w-auto`、meta `flex-wrap` + `break-all`、预览 `max-h-48 w-auto` —— 均符合契约。反馈链路（spinner+文案切换+skeleton / 内联红字+toast / amber 可操作卡）完整。

**扣分点（两处真实瑕疵，故 3/4 而非 4/4）：**
1. **首次失败 error + empty 双显**：`isError` 的 `<p>` 是独立 `v-if`，不在 `isPending → result → empty` 链内。首次提交失败（`result` 仍为 null、非 pending）时，error 红字与末尾 `CompactEmptyState`（empty「尚未上传截图」`v-else`，`:410`）**同时渲染**，信息矛盾。
2. **`/admin` 整页跳转**：降级链接 `<a href="/admin">`（`:297`）触发浏览器整页刷新，丢失 SPA 状态；项目内部路由应走 `RouterLink`。
3. **未用字段**：API `query`、`source`（`screenshotRecall.ts:32,45`）声明但 UI 未展示（契约标注 `query` 为"可选展示"，可接受；`source` 配套 i18n key 存在却未渲染，建议补齐或清理）。

---

## Consistency with IngestPanel（既有面板对齐）
- ✓ 根 `space-y-8`、header `px-5 py-3.5 border-b`、卡片 `card` 工具类、结果区 `aria-live`、`CompactEmptyState`、`Button`、`Skeleton`、`useToast`/`useErrorHandler`、外链 `rel="noopener"` 模式全部复用，无重复造轮子。
- ✓ 语义色（emerald/amber/destructive）与 IngestPanel `statusTextClass/statusIconClass` 同源。
- 小改进：ScreenshotRecall 给 header 图标补了 `aria-hidden`（IngestPanel `:165` 未加），属正向。

## Registry Safety
Registry 审计：UI-SPEC「Registry Safety」声明无第三方 registry、无 `npx shadcn add` 远程拉取（仅复用既有 `components/ui/*`：Button/Label/Skeleton）。无需第三方 block 安全门。已检查 0 个第三方 block，无 flag。

---

## Files Audited
- `web/src/components/knowledge/ScreenshotRecallPanel.vue`（主组件，420 行）
- `web/src/pages/knowledge/screenshot.vue`（页面骨架，对齐 ingest.vue）
- `web/src/api/screenshotRecall.ts`（API 模块 + 类型）
- `web/src/locales/zh-CN.json:271-317`（`screenshotRecall` i18n 块）
- `web/src/components/layout/AppSidebar.vue:87`（nav item）
- `web/src/components/common/CompactEmptyState.vue`（props 核对）
- `web/src/components/knowledge/IngestPanel.vue`（一致性基线）
