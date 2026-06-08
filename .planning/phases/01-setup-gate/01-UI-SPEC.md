---
phase: 1
slug: setup-gate
status: approved
shadcn_initialized: false
preset: none
created: 2026-06-08
---

# Phase 1 — UI Design Contract

> 首启向导「门禁 + 外壳」的视觉与交互契约。无人值守生成，复用 `web/` 既有设计系统（Tailwind 4 CSS 主题 + reka-ui + lucide），自校验通过。
> 本阶段 UI 面很小：**(a) 向导外壳页 `/setup`**（容器 + 检测/欢迎占位，后续 Phase 填充步骤）与 **(b) 路由守卫的重定向行为**（无独立可见 UI）。管理员表单沿用现有 `setup.vue`，UX 增强属 Phase 2。

---

## Design System

| Property | Value |
|----------|-------|
| Tool | none（项目自有 shadcn-vue 风格组件，位于 `~/components/ui/*`，非 shadcn CLI 注册） |
| Preset | not applicable |
| Component library | reka-ui（Radix 风格）+ 项目自有 `~/components/ui/{button,form,input}` |
| Icon library | lucide（经 `@iconify/tailwind4`，用法 `icon-[lucide--*]`） |
| Font | 应用默认无衬线栈（Tailwind 默认 sans，未自定义字体） |

复用既有主题令牌（`web/src/styles/main.css` `@theme`）：`--color-primary: hsl(168 76% 42%)`（teal-500）、`--color-background: hsl(210 40% 98%)`、`--color-card`、`--color-border`、`--shadow-glass`。**不新增主题令牌、不做主题化定制**（遵循 Out of Scope）。

---

## Spacing Scale

复用 Tailwind 默认 4px 基准刻度（与现有 `setup.vue`/`login.vue` 一致）：

| Token | Value | Usage |
|-------|-------|-------|
| xs | 4px | 图标与文字间距（`gap-1` / `mr-1`） |
| sm | 8px | 紧凑元素间距（`space-y-2`、`gap-2`） |
| md | 16px | 默认元素/表单字段间距（`space-y-4`、`p-4`） |
| lg | 24px | 卡片区块内边距、标题与内容间距（`mb-6`） |
| xl | 32px | 外壳卡片内边距（`p-8`，对齐现有 setup 卡片） |
| 2xl | 48px | 步骤区块大间隔（按需） |
| 3xl | 64px | 页面级留白（按需） |

Exceptions: none（沿用现有页面的 `max-w-md`、`rounded-2xl` 等既有写法）。

---

## Typography

沿用现有 `setup.vue` 排版（Tailwind 文本刻度）：

| Role | Size | Weight | Line Height |
|------|------|--------|-------------|
| Body | 14px (`text-sm`) | 400 | 1.5 |
| Label | 14px (`text-sm font-medium`) | 500 | 1.4 |
| Heading | 24px (`text-2xl`) | 700 (`font-bold`) | 1.3 |
| Display | 24px (`text-2xl`) | 700 | 1.3 |

> 本阶段无更大标题层级；外壳标题复用现有 `text-2xl font-bold`，副标题用 `text-sm text-muted-foreground`。

---

## Color

| Role | Value | Usage |
|------|-------|-------|
| Dominant (60%) | `hsl(210 40% 98%)`（`--color-background` slate-50） | 页面背景、mesh 渐变底 |
| Secondary (30%) | `hsl(0 0% 100%)`（`--color-card`，半透明 `bg-card/70` 玻璃卡片） | 外壳卡片、容器表面 |
| Accent (10%) | `hsl(168 76% 42%)`（`--color-primary` teal-500） | 品牌图标、主按钮、加载 spinner、聚焦态 ring |
| Destructive | `hsl(0 72% 51%)`（`--color-destructive`） | 仅错误提示（无法连接 / 检测失败） |

Accent reserved for: 品牌徽标图标、主 CTA 按钮、加载指示、表单聚焦 ring。**不**用于普通文本或所有交互元素。

---

## Copywriting Contract

本阶段全部用户可见文案经 `vue-i18n`（zh-CN 默认）取用（`setup.*` 命名空间），默认中文如下：

| Element | Copy |
|---------|------|
| 外壳标题（heading） | 首次设置 |
| 外壳副标题（body） | 欢迎使用 Friday AI，开始初始化你的实例 |
| 检测中状态 | 正在检测系统状态… |
| Primary CTA（沿用现有表单按钮） | 创建管理员账户 |
| 提交进行中 | 创建中… |
| Empty/占位（后续步骤未就绪） | 即将开始引导设置 |
| Error — 无法连接后端 | 无法连接到服务器，请检查后端服务后重试 |
| Error — 已初始化访问向导 | （无文案，路由守卫静默重定向到登录页） |

> 文案以 `t('setup.title')` 等键访问；键名与默认 zh-CN 文本由执行阶段落地到 `web/src/locales/zh-CN.*` 与 `main.ts`。

---

## Registry Safety

| Registry | Blocks Used | Safety Gate |
|----------|-------------|-------------|
| 项目自有 `~/components/ui/*`（已在仓库内） | Button, Form*（FormField/FormItem/FormLabel/FormControl/FormMessage）, Input | not required（仓库内既有组件，非外部 registry） |
| reka-ui | 由上述 ui 组件内部封装 | not required |
| 第三方 shadcn registry | 无 | 不涉及 |

无引入任何第三方 registry 区块，无需 shadcn view + diff 安全门。

---

## Checker Sign-Off

- [x] Dimension 1 Copywriting: PASS — 关键状态（标题/检测/错误/CTA）均有具体中文文案，错误文案含解决路径
- [x] Dimension 2 Visuals: PASS — 复用现有 glass 卡片与 lucide 图标，无新视觉债
- [x] Dimension 3 Color: PASS — 60/30/10 明确，accent 限定品牌/CTA/加载/聚焦，destructive 仅错误
- [x] Dimension 4 Typography: PASS — 沿用现有 Tailwind 文本刻度，层级清晰
- [x] Dimension 5 Spacing: PASS — 全部为 4px 倍数，复用现有间距写法
- [x] Dimension 6 Registry Safety: PASS — 仅用仓库内既有组件，无第三方 registry

**Approval:** approved 2026-06-08（无人值守自校验；UI 面最小，无阻塞项）
