---
phase: 2
slug: admin-account
status: approved
shadcn_initialized: false
preset: none
created: 2026-06-08
---

# Phase 2 — UI Design Contract

> 在 Phase 1 已交付的 `/setup` 向导外壳（glass 卡片 + `~/components/ui/{form,input,button}` + vee-validate/zod）之上，增强**管理员账号创建表单**的交互：密码强度校验与可视化指示、二次确认、字段级错误回填，提交成功后**自动登录并直达系统首页**。无人值守生成，复用 `web/` 既有设计系统（Tailwind 4 CSS 主题 + reka-ui + lucide），自校验通过。
> 本阶段 UI 面：仍是单张 `/setup` 卡片内的表单（不新增页面/路由）。复用 Phase 1 外壳与三字段结构，新增「密码强度指示」与提交成功后的跳转目标变化（`/login` → `/`）。

---

## Design System

| Property | Value |
|----------|-------|
| Tool | none（项目自有 shadcn-vue 风格组件 `~/components/ui/*`，非 shadcn CLI 注册） |
| Preset | not applicable |
| Component library | reka-ui（Radix 风格）+ 项目自有 `~/components/ui/{button,form,input}` |
| Icon library | lucide（经 `@iconify/tailwind4`，用法 `icon-[lucide--*]`） |
| Font | 应用默认无衬线栈（Tailwind 默认 sans） |

复用既有主题令牌（`web/src/styles/main.css` `@theme`）：`--color-primary`（teal-500）、`--color-background`、`--color-card`、`--color-border`、`--color-destructive`、`--shadow-glass`。**不新增主题令牌、不做主题化定制**（遵循 Out of Scope）。

强度指示档位仅借用既有语义色，不引入新令牌：
- 弱 → `--color-destructive`（红）
- 中 → `amber-500`（Tailwind 内置工具色，琥珀）
- 强 → `--color-primary`（teal，与主品牌一致）

---

## Spacing Scale

复用 Tailwind 默认 4px 基准刻度（与现有 `setup.vue`/`login.vue` 一致）：

| Token | Value | Usage |
|-------|-------|-------|
| xs | 4px | 图标与文字间距（`gap-1`）、强度条圆角 |
| sm | 8px | 强度条与提示文字间距（`mt-2`/`space-y-2`） |
| md | 16px | 表单字段间距（`space-y-4`） |
| lg | 24px | 标题与表单间距（`mb-6`） |
| xl | 32px | 外壳卡片内边距（`p-8`） |

Exceptions: none（沿用现有 `max-w-md`、`rounded-2xl`、强度条 `h-1.5 rounded-full`）。

---

## Typography

沿用现有 `setup.vue` 排版（Tailwind 文本刻度）：

| Role | Size | Weight | Line Height |
|------|------|--------|-------------|
| Heading（外壳标题） | 24px (`text-2xl`) | 700 (`font-bold`) | 1.3 |
| Body / 副标题 | 14px (`text-sm`) | 400 | 1.5 |
| Label（字段标签） | 14px (`text-sm font-medium`) | 500 | 1.4 |
| Hint / 强度文字 | 12px (`text-xs`) | 400/500 | 1.4 |
| Error message（FormMessage） | 12-14px (`text-sm` destructive) | 400 | 1.4 |

> 强度等级文字用 `text-xs`，与档位色对应；错误提示沿用 `FormMessage` 既有样式。

---

## Color

| Role | Value | Usage |
|------|-------|-------|
| Dominant (60%) | `--color-background`（slate-50） | 页面背景、mesh 渐变底 |
| Secondary (30%) | `--color-card`（半透明 `bg-card/70` 玻璃卡片） | 外壳卡片表面 |
| Accent (10%) | `--color-primary`（teal-500） | 品牌图标、主 CTA、聚焦 ring、强度=强 |
| Warning | `amber-500` | 强度=中（仅强度条/标签） |
| Destructive | `--color-destructive` | 字段错误、强度=弱、连接失败提示 |

Accent reserved for: 品牌徽标、主 CTA 按钮、加载指示、聚焦 ring、强度达「强」。**不**用于普通文本。强度条颜色随档位在 destructive/amber/primary 间切换，是唯一的多色元素。

---

## Copywriting Contract

本阶段全部用户可见文案经 `vue-i18n`（zh-CN 默认）取用（`setup.*` 命名空间）。沿用 Phase 1 既有键，新增如下：

| Element | i18n Key | Copy |
|---------|----------|------|
| 字段：确认密码（已存在） | `setup.fields.confirmPassword` | 确认密码 |
| 密码占位提示（更新） | `setup.fields.passwordPlaceholder` | 至少 8 位，建议字母与数字组合 |
| 强度标题前缀 | `setup.strength.label` | 密码强度 |
| 强度 - 弱 | `setup.strength.weak` | 弱 |
| 强度 - 中 | `setup.strength.medium` | 中 |
| 强度 - 强 | `setup.strength.strong` | 强 |
| 即时校验 - 长度不足 | `setup.validation.passwordMin` | 密码至少 8 位 |
| 即时校验 - 两次不一致 | `setup.validation.passwordMismatch` | 两次输入的密码不一致 |
| 即时校验 - 纯数字 | `setup.validation.passwordNumeric` | 密码不能全为数字 |
| 即时校验 - 用户名必填 | `setup.validation.usernameRequired` | 请输入用户名 |
| Primary CTA（已存在） | `setup.cta` | 创建管理员账户 |
| 提交进行中（已存在） | `setup.submitting` | 创建中… |
| 自动登录跳转提示 | `setup.success` | 创建成功，正在进入系统… |
| Error — 无法连接（已存在） | `setup.error.connection` | 无法连接到服务器，请检查后端服务后重试 |
| Error — 默认（已存在） | `setup.error.default` | 设置失败，请重试 |

> 后端 Django 密码校验器返回的中文错误消息（如「这个密码太常见了。」「密码与 用户名 太相似了。」「密码不能全部为数字。」）直接展示，不在前端二次翻译。

---

## Interaction & States

| State | Behavior |
|-------|----------|
| 初始 | 三字段（用户名/密码/确认密码），强度条隐藏或置「弱」灰态；CTA 可点（提交时由校验拦截）。 |
| 输入密码 | 实时计算强度（长度 + 字符类别：小写/大写/数字/符号），渲染强度条（弱红/中琥珀/强 teal）+ 等级文字。 |
| 字段校验失败 | vee-validate/zod 即时显示 `FormMessage`（中文）；不阻断其他字段输入。 |
| 提交中 | CTA 显示 `icon-[lucide--loader-circle] animate-spin` + 「创建中…」，按钮 `disabled`。 |
| 提交成功 | 顶部短暂提示 `setup.success`（或直接跳转）；写入 auth store 会话；`router.push('/')` 进入首页。 |
| 后端 400（密码过弱/常见/相似/纯数字、用户名占用） | 将后端字段错误回填到对应字段的 `FormMessage` 或顶部 destructive 错误条，文案用后端中文消息。 |
| 后端连接失败 | 顶部 destructive 错误条显示 `setup.error.connection`。 |

强度算法（指引，执行阶段可微调）：满足条件数（长度 ≥8、含字母、含数字、含符号或长度 ≥12）→ 0-1 弱 / 2-3 中 / 4 强。仅作 UX 提示，不阻止提交（提交以 zod + 后端校验为准）。

---

## Registry Safety

| Registry | Blocks Used | Safety Gate |
|----------|-------------|-------------|
| 项目自有 `~/components/ui/*`（仓库内） | Button, Form*（FormField/Item/Label/Control/Message）, Input | not required |
| reka-ui | 由上述 ui 组件内部封装 | not required |
| 第三方 shadcn registry | 无 | 不涉及 |

强度指示用原生 `div` + Tailwind class 实现（`h-1.5 bg-* rounded-full`），不引入新组件/registry，无需安全门。

---

## Checker Sign-Off

- [x] Dimension 1 Copywriting: PASS — 新增强度/校验/成功/错误文案均有具体中文，错误含解决信息；后端校验消息直透
- [x] Dimension 2 Visuals: PASS — 复用 glass 卡片与 lucide 图标；强度条为原生 div，无新视觉债
- [x] Dimension 3 Color: PASS — 60/30/10 明确；强度条多色限定于 destructive/amber/primary 三档，accent 用途克制
- [x] Dimension 4 Typography: PASS — 沿用 Tailwind 文本刻度，新增 `text-xs` 强度提示层级清晰
- [x] Dimension 5 Spacing: PASS — 全部 4px 倍数，复用现有间距写法
- [x] Dimension 6 Registry Safety: PASS — 仅用仓库内既有组件 + 原生元素，无第三方 registry

**Approval:** approved 2026-06-08（无人值守自校验；UI 面在 Phase 1 外壳内增量，无阻塞项）
