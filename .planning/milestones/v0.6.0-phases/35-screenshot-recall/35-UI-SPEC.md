---
phase: 35
slug: screenshot-recall
status: draft
shadcn_initialized: true
preset: shadcn-vue (reka-ui) — pre-existing, web/src/components/ui
created: 2026-06-15
---

# Phase 35 — UI Design Contract（截图识别需求）

> 截图上传 → 多模态 LLM 提语义 → 文本 query → 召回需求的最小面板。
> 由 gsd-ui-researcher 产出，gsd-ui-checker 校验。沿用 Phase 32 `IngestPanel` 既有约定，**不引入新字体/新色/第三方 registry**。

---

## Design System

| Property | Value |
|----------|-------|
| Tool | shadcn-vue（reka-ui 基座，组件已存在于 `web/src/components/ui/*`） |
| Preset | not applicable（项目早已初始化；复用既有 token，不新增） |
| Component library | reka-ui（radix-vue 后继） |
| Icon library | Lucide via iconify（`icon-[lucide--xxx]` 工具类，**不新增图标包**） |
| Font | 系统默认 sans（`web/src/styles/main.css` 既有，无自定义字体） |

复用既有组件（不新建基础组件）：`Button`、`Label`、`CompactEmptyState`、`Skeleton`、`card` 工具类、`useToast`、`useErrorHandler`、TanStack Query、vue-i18n。

---

## Spacing Scale

复用既有 8-point scale（与 `IngestPanel` 完全一致）：

| Token | Value | Usage |
|-------|-------|-------|
| xs | 4px | 图标与文字间距（`gap-1` / `gap-1.5`）、内联小间距 |
| sm | 8px | 紧凑元素间距（`gap-2`、`space-y-2`） |
| md | 16px | 表单/卡片内默认间距（`p-5` 的内距体系、`space-y-4`） |
| lg | 24px | 卡片间分隔（`space-y-6`） |
| xl | 32px | 主区块分隔（`space-y-8`，对齐 IngestPanel 根容器） |
| 2xl | 48px | 不在本 phase 使用 |
| 3xl | 64px | 不在本 phase 使用 |

Exceptions：
- 上传 dropzone 最小可点高度 ≥ 160px（`min-h-40`），保证拖拽热区与触控可达性。
- dropzone/移除按钮等可点元素命中区 ≥ 36px（沿用 `Button` size 默认 `h-9`）。

---

## Typography

复用既有层级（与 `ingest.vue` + `IngestPanel.vue` 一致），仅 3 个尺寸 + 2 个字重：

| Role | Size | Weight | Line Height |
|------|------|--------|-------------|
| Page heading | 20px (`text-xl`) | 600 (`font-semibold`) | 1.2 |
| Card title / 召回项标题 | 14px (`text-sm`) | 600 (`font-semibold`) / 500 (`font-medium`) | 1.4 |
| Body / 语义正文 | 14px (`text-sm`) | 400 | 1.5 |
| Helper / meta / 副标题 | 12px (`text-xs`) | 400 | 1.5 |

字重仅用 `font-normal (400)` 与 `font-medium/semibold (500/600)`；不引入第三种正文字重。

---

## Color

复用 `web/src/styles/main.css` 既有 token，60/30/10 分布：

| Role | Value | Usage |
|------|-------|-------|
| Dominant (60%) | `hsl(210 40% 98%)` slate-50（`--color-background`） | 页面背景、面板留白 |
| Secondary (30%) | `hsl(0 0% 100%)` 纯白（`--color-card`） | 卡片、dropzone、结果区表面 |
| Accent (10%) | `hsl(168 76% 42%)` teal-500（`--color-primary`） | 见下方 reserved-for 清单 |
| Destructive | `hsl(0 72% 51%)`（`--color-destructive`） | 校验错误、加载/提取错误文案与图标 |

Accent（teal `primary`）reserved for（**禁止"所有交互元素都用强调色"**）：
- 主操作按钮「开始识别」（`Button` 默认 variant，已是 primary 底）。
- 卡片头部标题图标（`text-primary`，对齐 IngestPanel header 图标）。
- 召回项外链「查看」、相关度高亮等次要 primary 文本链接（`text-primary hover:underline`）。
- 加载中 spinner（`icon-[lucide--loader-circle] animate-spin text-primary`）。
- dropzone 拖拽悬停态边框/底色（`border-primary` + `bg-primary/5`）。

语义状态色（非强调色，与文字并列，满足 WCAG 1.4.1 不靠颜色单独表意）：
- 成功/有结果：`text-emerald-600 dark:text-emerald-400`（沿用 IngestPanel `statusTextClass`）。
- 降级（无 vision 模型/提取失败）：`text-amber-700 dark:text-amber-400` + `icon-[lucide--alert-triangle]`（与"失败"区分：降级是可预期的非错误态）。
- 错误：`text-destructive` + `icon-[lucide--alert-circle]`。

---

## Copywriting Contract

i18n namespace：`screenshotRecall.*`（默认中文 zh-CN）。完整 key 见下方「i18n Keys」。

| Element | Copy |
|---------|------|
| Primary CTA | 开始识别（提交中：识别中…） |
| Empty state heading | 尚未上传截图 |
| Empty state body | 将截图拖到上方区域、点击选择，或直接粘贴（Ctrl/Cmd+V），识别结果将在此显示 |
| No-results（识别成功但无召回） | 未召回到相关需求 — 可尝试更清晰/信息更完整的截图后重试 |
| Error state | 识别失败，请稍后重试（含校验：请上传图片文件 / 图片超过 10 MB，请压缩后重试） |
| Degraded（无 vision 模型） | 当前未配置可用的多模态（vision）模型，无法从截图提取语义；请在「系统设置」配置具备视觉能力的模型后重试 |
| Destructive confirmation | 无破坏性操作（移除已选截图为非破坏性，无需二次确认） |

---

## Route / Placement / Component Inventory

| Item | Decision |
|------|----------|
| 路由 | `web/src/pages/knowledge/screenshot.vue`（归入「交付知识」族，与 `/knowledge/ingest` 同级） |
| 侧边栏 | `AppSidebar.vue` `mainNavItems` 追加 `{ to: '/knowledge/screenshot', label: '截图识需求', icon: 'lucide--scan-search' }`（紧随「一键摄取」之后） |
| 主组件 | `web/src/components/knowledge/ScreenshotRecallPanel.vue`（`<script setup lang="ts">`，编排上传+提交+结果） |
| API 模块 | `web/src/api/screenshotRecall.ts`（`screenshotRecallApi`，复用 `./client`） |
| i18n | `web/src/locales/zh-CN.json` 新增 `screenshotRecall` 顶层块 |
| 测试 | `web/src/components/knowledge/__tests__/ScreenshotRecallPanel.spec.ts`（vitest + @vue/test-utils + happy-dom） |

页面骨架（对齐 `ingest.vue`）：`PageContainer` → `div.space-y-4.max-w-3xl` → `h1.text-xl.font-semibold` + `<ScreenshotRecallPanel />`。

### 组件结构（ScreenshotRecallPanel.vue）

```
ScreenshotRecallPanel (root: div.space-y-8)
├─ 上传卡片 (div.card)
│  ├─ header (px-5 py-3.5 border-b)：icon-[lucide--scan-search].text-primary + 标题 + 副标题
│  └─ body (p-5 space-y-4)
│     ├─ Dropzone（拖拽/点击/粘贴，含隐藏 <input type="file">）—— 无选中时显示
│     ├─ Preview（缩略图 + 文件名 + 大小 + 移除按钮）—— 有选中时显示
│     ├─ 校验错误行 (p.text-xs.text-destructive, role 见 a11y)
│     └─ Button「开始识别」（w-full sm:w-auto，:disabled 见状态机）
└─ 结果区 (div[aria-live="polite"].space-y-6)
   ├─ Empty（CompactEmptyState, icon lucide--image）—— 未提交过
   ├─ Loading（Skeleton 行 + spinner 文案）—— 提交中
   ├─ Error（p.text-destructive，不清空已有结果）—— 请求失败
   ├─ Degraded 卡片（amber alert-triangle + 文案 + 「前往系统设置」链接）—— result.degraded
   └─ Success：
      ├─ 语义卡（可选，div.card，默认折叠/可展开）：text/ui_elements/business_intent 三段
      └─ 召回列表（ul）或 No-results（CompactEmptyState, icon lucide--search-x）
```

---

## Upload Interaction + Validation（核心交互契约）

### 三种上传入口（全部命中同一 `handleFile(file)`）
1. **点击选择**：dropzone 是可聚焦元素（`role="button"` + `tabindex="0"`），Enter/Space 触发隐藏 `<input type="file" accept="image/png,image/jpeg,image/webp" class="sr-only">`。
2. **拖拽**：`@dragover.prevent` 置 `isDragging=true` + 高亮（`border-primary bg-primary/5`）；`@dragleave` 复位；`@drop.prevent` 取 `e.dataTransfer.files[0]`。
3. **粘贴**：组件挂载时监听 `window` 的 `paste`（`onMounted`/`onBeforeUnmount` 成对），从 `e.clipboardData.items` 取首个 `type.startsWith('image/')` 的 `getAsFile()`。仅当面板可见/无 modal 时生效。

### 校验（前端为体验前置，后端为权威 —— 双校验）
| 规则 | 阈值 | 失败文案 key |
|------|------|------|
| 类型必须为图片 | MIME ∈ {`image/png`,`image/jpeg`,`image/webp`} | `screenshotRecall.validation.invalidType` |
| 体积上限 | ≤ 10 MB（`10 * 1024 * 1024`） | `screenshotRecall.validation.tooLarge` |
| 必填 | 提交时无文件 | `screenshotRecall.validation.required` |

- 校验失败：内联红字 + `toast`（`useToast().error` 或 `handleError`），不发请求，焦点回到 dropzone。
- 阈值（10MB / 允许的 MIME 列表）由前后端共享常量语义对齐；后端拒绝时回显后端 message（沿用 `useErrorHandler`）。

### 预览与移除
- 预览用 `URL.createObjectURL(file)`，`<img>` 设 `max-h-48 object-contain rounded-md`，`alt` = 文件名（i18n `previewAlt`）。
- 组件卸载/替换文件时 `URL.revokeObjectURL` 释放，避免内存泄漏。
- 移除按钮：`Button` ghost/outline + `icon-[lucide--x]`，清空文件与结果（回到 empty 态），无需二次确认。

---

## State Machine（6 pillars: states 覆盖）

提交采用 **同步 mutation**（`useMutation`，POST multipart 直接返回结果），无需轮询。若后端改异步派发，则降级为 dispatch+poll（沿用 IngestPanel 范式）——本契约以同步为准。

| State | 触发 | UI |
|-------|------|----|
| `empty` | 初始 / 移除文件后 | dropzone 可用；结果区 `CompactEmptyState`（`lucide--image`，empty 文案） |
| `selected` | 选中合法图片 | 显示 Preview；「开始识别」可点 |
| `invalid` | 校验未过 | 内联红字 + toast；不进入 loading |
| `loading` | mutation pending | dropzone+按钮 `disabled`；按钮内 spinner + 「识别中…」；结果区 Skeleton（2–3 行）+ `aria-busy="true"` |
| `error` | mutation rejected（网络/5xx） | 结果区红字 `error` 文案（保留上次成功结果不清空）；可直接重试 |
| `degraded` | 200 且 `result.degraded === true` | amber alert-triangle 卡片 + degraded 文案 + 「前往系统设置」链接（`/admin`）；**不视为错误**，不弹 error toast |
| `success` | 200 且有 `results` | 可选语义卡 + 召回列表 |
| `no-results` | 200 且 `results.length === 0` 且非 degraded | `CompactEmptyState`（`lucide--search-x`，noResults 文案） |

按钮 `disabled` 条件：`!file || isPending`。

---

## Results Rendering

### 语义卡（可选展示，默认折叠）
- 标题：`icon-[lucide--scan-text].text-primary` + 「识别到的语义」+ 右侧展开/收起按钮（`lucide--chevron-down`，`aria-expanded`）。
- 三段（任一为空则不渲染该段）：文字（`text`）、UI 元素（`ui_elements`）、业务意图（`business_intent`），各段 `text-sm` 正文 + `text-xs text-muted-foreground` 段标题。
- 长文本 `whitespace-pre-wrap break-words`。

### 召回需求列表
每项（`li`，对齐 IngestPanel step 行的图标+文字结构）：
- 左：`icon-[lucide--file-text] text-muted-foreground`（装饰性 `aria-hidden`）。
- 标题：`text-sm font-medium`，work_item `title`。
- meta 行（`text-xs text-muted-foreground`）：来源 work_item id（`code.font-mono.break-all`）+ 相关度（如有：`relevance` 百分比，`text-emerald-600` 高相关）。
- 外链「查看」：`a[target=_blank][rel=noopener]` + `icon-[lucide--external-link]` + `text-primary hover:underline`（仅 `link` 存在时）。
- 列表整体 `ul.space-y-3`；每项 `data-testid="recall-item-{idx}"`。

---

## API Contract（前端视角，字段名与后端 serializer 对齐）

`POST /delivery/screenshot-recall/`（multipart：`screenshot` file），`IsAuthenticated`，同步返回 200：

```ts
// web/src/api/screenshotRecall.ts
export interface ExtractedSemantics {
  text?: string            // OCR / 文字
  ui_elements?: string     // UI 控件描述
  business_intent?: string // 业务意图
}
export interface RecalledRequirement {
  work_item_id: string
  title: string
  link?: string            // 飞书/详情外链
  relevance?: number       // 0..1，可选
  source?: string          // 召回来源（rag / 反查）
}
export interface ScreenshotRecallResult {
  degraded: boolean            // 无 vision 模型/提取失败 → true
  degraded_reason?: string     // 后端已脱敏的降级原因
  semantics?: ExtractedSemantics
  query?: string               // 派生的文本 query（可选展示）
  results: RecalledRequirement[]
}
export const screenshotRecallApi = {
  recall: (file: File): Promise<ScreenshotRecallResult> => {
    const fd = new FormData()
    fd.append('screenshot', file)
    return post<ScreenshotRecallResult>('/delivery/screenshot-recall/', fd)
  },
}
```
> 注：若 `post` 默认 `Content-Type: application/json`，需让其在 body 为 `FormData` 时跳过 JSON 头（沿用/扩展 `client.ts`，由 executor 核对）。

---

## i18n Keys（zh-CN，新增 `screenshotRecall` 块）

```jsonc
"screenshotRecall": {
  "title": "截图识需求",
  "subtitle": "上传界面/原型截图，自动提取语义并召回相关需求（不建图片向量库）",
  "upload": {
    "dropzoneTitle": "拖入截图，或点击选择",
    "dropzoneHint": "支持 PNG / JPEG / WebP，单张 ≤ 10 MB；也可直接粘贴（Ctrl/Cmd+V）",
    "selectButton": "选择截图",
    "previewAlt": "截图预览",
    "remove": "移除",
    "submit": "开始识别",
    "submitting": "识别中…"
  },
  "validation": {
    "required": "请先上传截图",
    "invalidType": "请上传图片文件（PNG / JPEG / WebP）",
    "tooLarge": "图片超过 10 MB，请压缩后重试"
  },
  "empty": {
    "title": "尚未上传截图",
    "body": "将截图拖到上方区域、点击选择，或直接粘贴（Ctrl/Cmd+V），识别结果将在此显示"
  },
  "loading": "正在识别截图并召回需求…",
  "error": "识别失败，请稍后重试",
  "degraded": {
    "title": "未配置多模态（vision）模型",
    "body": "当前没有可用的视觉能力模型，无法从截图提取语义。请在系统设置配置具备视觉能力的模型后重试。",
    "settingsLink": "前往系统设置"
  },
  "noResults": {
    "title": "未召回到相关需求",
    "body": "可尝试更清晰、信息更完整的截图后重试"
  },
  "semantics": {
    "title": "识别到的语义",
    "expand": "展开",
    "collapse": "收起",
    "text": "文字",
    "uiElements": "UI 元素",
    "businessIntent": "业务意图"
  },
  "results": {
    "title": "召回的需求",
    "relevance": "相关度 {percent}%",
    "source": "来源",
    "viewLink": "查看"
  }
}
```

---

## Accessibility（6 pillars: a11y，重点上传可达性）

- Dropzone：`role="button"` + `tabindex="0"` + `aria-label`（含格式/大小约束）+ Enter/Space 激活隐藏 file input；隐藏 input 用 `sr-only`（仍可被聚焦/读屏），**禁止 `display:none`**。
- 约束说明用 `aria-describedby` 关联 dropzone 与 hint 文本。
- 拖拽态变化提供视觉（边框/底色）+ 不依赖颜色单独表意。
- 结果区 `aria-live="polite"`、loading 时 `aria-busy="true"`；校验/错误文案放入 live region 以便读屏播报。
- 状态图标 `aria-hidden`（装饰性），语义由相邻文本承载（沿用 IngestPanel）。
- 所有可点元素键盘可达，焦点环用既有 `--color-ring`（teal）。
- 文案对比度满足 WCAG AA（既有 token 已达标）。

---

## Responsive（6 pillars: responsive）

- 容器 `max-w-3xl`，移动端单列堆叠（dropzone → preview → 结果），桌面同列（面板本就窄）。
- 「开始识别」`w-full sm:w-auto`（沿用 IngestPanel）。
- 召回项 meta 行 `flex-wrap`，长 id/链接 `break-all` 防溢出。
- 预览图 `max-h-48 w-auto`，不撑破卡片。

---

## Feedback（6 pillars: feedback）

- 提交即时反馈：按钮 spinner + 文案切换 + 结果区 Skeleton。
- 成功：召回列表渲染（无额外 toast，避免噪音）；可选 `success` toast 仅在需要时。
- 失败：`handleError` + 红字（保留上次结果）。
- 降级：明确 amber 卡片 + 可操作链接（前往系统设置），区别于错误。
- 校验：内联红字 + toast，焦点回 dropzone。

---

## Reuse Notes（不重复造轮子）

| 复用 | 来源 |
|------|------|
| 卡片 `card` 工具类、header 排版、结果区 `aria-live` 骨架 | `IngestPanel.vue` |
| `CompactEmptyState`（empty / no-results） | `components/common/CompactEmptyState.vue` |
| `Button` / `Label` / `Skeleton` | `components/ui/*` |
| `useToast` / `useErrorHandler` | `composables/*` |
| 状态图标+文字配对、语义色类（emerald/amber/destructive） | `IngestPanel.statusTextClass / statusIconClass` |
| API client `post` + 类型化模块范式 | `api/ingest.ts` + `api/client.ts` |
| 侧边栏 nav item 范式 | `AppSidebar.vue mainNavItems` |
| i18n 命名分层（`xxx.form/empty/run/...`） | `locales/zh-CN.json` `ingest` 块 |

---

## Acceptance Criteria（gsd-ui-checker / executor 验收）

- [ ] 三种上传入口均工作：点击选择、拖拽、粘贴，且都进入同一校验+预览路径。
- [ ] 前端校验拒绝非图片与 >10MB，并显示对应 i18n 文案 + 焦点回 dropzone（不发请求）。
- [ ] 预览显示缩略图/文件名/大小 + 可移除；移除后回到 empty 态且 `revokeObjectURL` 释放。
- [ ] 状态机 6 态可视：empty / loading（Skeleton+spinner）/ error（保留旧结果）/ degraded（amber+设置链接）/ success / no-results 各有专属 UI。
- [ ] 降级态明确区分于错误态（amber alert-triangle + 可操作链接，不弹 error toast）。
- [ ] 召回列表渲染 title / 来源 work_item / 相关度（如有）/ 外链「查看」（`rel=noopener`）。
- [ ] 语义卡可展开/收起，三段（text/ui/intent）任一为空则不渲染该段。
- [ ] a11y：dropzone 键盘可激活、隐藏 input `sr-only` 可聚焦、约束 `aria-describedby`、结果区 `aria-live`、状态图标 `aria-hidden`。
- [ ] 全部文案走 `screenshotRecall.*` i18n（默认中文），无硬编码字符串。
- [ ] 仅用既有 token（teal primary / slate / 系统字体 / lucide），无新增字体/色/第三方 registry。
- [ ] 响应式：移动端单列、按钮 `w-full sm:w-auto`、长文本/链接不溢出。
- [ ] 复用既有组件与 client 范式，未新建重复基础组件。
- [ ] vitest 守护：上传校验、结果渲染、degraded/no-results/error 分支、i18n 文案存在。

---

## Registry Safety

| Registry | Blocks Used | Safety Gate |
|----------|-------------|-------------|
| shadcn-vue（既有项目内组件，非远程拉取） | Button, Label, Skeleton（均已存在） | not required（无第三方 registry，无远程 add） |

无第三方 registry 引入；无 `npx shadcn add` 远程拉取。

---

## Checker Sign-Off

- [ ] Dimension 1 Copywriting: PASS
- [ ] Dimension 2 Visuals: PASS
- [ ] Dimension 3 Color: PASS
- [ ] Dimension 4 Typography: PASS
- [ ] Dimension 5 Spacing: PASS
- [ ] Dimension 6 Registry Safety: PASS

**Approval:** pending
