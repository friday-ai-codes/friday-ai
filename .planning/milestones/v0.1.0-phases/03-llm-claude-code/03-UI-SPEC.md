---
phase: 3
slug: llm-claude-code
status: approved
shadcn_initialized: false
preset: none
created: 2026-06-08
---

# Phase 3 — UI Design Contract

> 在 Phase 1/2 已交付的 `/setup` 向导外壳（glass 卡片 + `~/components/ui/{form,input,button}` + vee-validate/zod）之上，把单步管理员表单升级为**两步向导**，新增**步骤 2「供应商配置」**：一键模型预设选择（含模型能力展示）+ API Key 输入 + 落库前健康校验反馈，成功后绑定 Claude Code 并进入系统首页。无人值守生成，复用 `web/` 既有设计系统（Tailwind 4 CSS 主题 + reka-ui + lucide），自校验通过。
> 本阶段 UI 面：仍是单张 `/setup` glass 卡片，内部按 `step` 切换；新增步骤指示（1/2）、预设选择卡片、能力 badge、健康校验中/失败/成功状态。无新增页面/路由。

---

## Design System

| Property | Value |
|----------|-------|
| Tool | none（项目自有 shadcn-vue 风格组件 `~/components/ui/*`，非 shadcn CLI 注册） |
| Preset | not applicable |
| Component library | reka-ui（Radix 风格）+ 项目自有 `~/components/ui/{button,form,input}` |
| Icon library | lucide（经 `@iconify/tailwind4`，用法 `icon-[lucide--*]`） |
| Font | 应用默认无衬线栈（Tailwind 默认 sans） |

复用既有主题令牌（`web/src/styles/main.css` `@theme`）：`--color-primary`（teal-500）、`--color-background`、`--color-card`、`--color-border`、`--color-muted-foreground`、`--color-destructive`、`--shadow-glass`。**不新增主题令牌、不做主题化定制**（遵循 Out of Scope）。

预设选中态用 `--color-primary` 边框/底色（`border-primary bg-primary/5`）；能力 badge 用既有语义色（图像能力=primary，文本=muted）。

---

## Spacing Scale

复用 Tailwind 默认 4px 基准刻度（与现有 `setup.vue` 一致）：

| Token | Value | Usage |
|-------|-------|-------|
| xs | 4px | 图标与文字间距（`gap-1`）、badge 圆角 |
| sm | 8px | 预设卡片内间距、badge 间距（`gap-2`） |
| md | 16px | 表单字段 / 预设列表项间距（`space-y-4`） |
| lg | 24px | 步骤标题与表单间距（`mb-6`） |
| xl | 32px | 外壳卡片内边距（`p-8`） |

Exceptions: none（沿用现有 `max-w-md`/`rounded-2xl`；供应商步骤为容纳预设列表可放宽至 `max-w-lg`）。

---

## Typography

沿用现有 `setup.vue` 排版（Tailwind 文本刻度）：

| Role | Size | Weight | Line Height |
|------|------|--------|-------------|
| Heading（外壳标题） | 24px (`text-2xl`) | 700 (`font-bold`) | 1.3 |
| 步骤指示 / 副标题 | 14px (`text-sm`) | 400/500 | 1.5 |
| Label（字段标签） | 14px (`text-sm font-medium`) | 500 | 1.4 |
| 预设标题 | 14px (`text-sm font-medium`) | 500 | 1.4 |
| Hint / 能力 badge / 预设描述 | 12px (`text-xs`) | 400 | 1.4 |
| Error message | 12-14px (`text-sm` destructive) | 400 | 1.4 |

---

## Color

| Role | Value | Usage |
|------|-------|-------|
| Dominant (60%) | `--color-background`（slate-50） | 页面背景、mesh 渐变底 |
| Secondary (30%) | `--color-card`（半透明 `bg-card/70` 玻璃卡片） | 外壳卡片表面、预设卡片 |
| Accent (10%) | `--color-primary`（teal-500） | 品牌图标、主 CTA、聚焦 ring、预设选中态、步骤当前态、图像能力 badge |
| Destructive | `--color-destructive` | 字段错误、健康校验失败提示 |

Accent reserved for: 品牌徽标、主 CTA、加载指示、聚焦 ring、预设选中态、当前步骤、图像能力 badge。**不**用于普通文本。

---

## Copywriting Contract

本阶段全部用户可见文案经 `vue-i18n`（zh-CN 默认）取用（`setup.*` 命名空间）。新增如下（沿用 Phase 1/2 既有键）：

| Element | i18n Key | Copy |
|---------|----------|------|
| 步骤 1 标签 | `setup.steps.admin` | 管理员账户 |
| 步骤 2 标签 | `setup.steps.provider` | AI 供应商 |
| 步骤进度 | `setup.steps.indicator` | 第 {current} / {total} 步 |
| 供应商步骤标题 | `setup.provider.title` | 配置 AI 供应商 |
| 供应商步骤副标题 | `setup.provider.subtitle` | 选择模型预设并填写 API Key，Claude Code 将使用该供应商运行 |
| 预设区标签 | `setup.provider.presetLabel` | 模型预设 |
| 字段：API Key | `setup.provider.fields.apiKey` | API Key |
| 字段：Base URL | `setup.provider.fields.baseUrl` | 接口地址（Base URL） |
| 字段：模型 | `setup.provider.fields.model` | 默认模型 |
| API Key 占位 | `setup.provider.fields.apiKeyPlaceholder` | 粘贴该供应商的 API Key |
| 能力：上下文 | `setup.provider.caps.context` | 上下文 {n} |
| 能力：图像 | `setup.provider.caps.vision` | 支持图像 |
| 能力：纯文本 | `setup.provider.caps.textOnly` | 纯文本 |
| 校验 - API Key 必填 | `setup.provider.validation.apiKeyRequired` | 请填写 API Key |
| 校验 - Base URL 必填 | `setup.provider.validation.baseUrlRequired` | 请填写接口地址 |
| 校验 - 模型必填 | `setup.provider.validation.modelRequired` | 请填写默认模型 |
| Primary CTA | `setup.provider.cta` | 校验并完成配置 |
| 校验中 | `setup.provider.testing` | 正在校验连通与鉴权… |
| 成功 | `setup.provider.success` | 配置成功，正在进入系统… |
| 次级动作（稍后配置） | `setup.provider.skip` | 稍后在设置中配置 |
| 错误 - 健康校验失败前缀 | `setup.provider.error.healthPrefix` | 连接或鉴权失败 |
| 错误 - 默认 | `setup.provider.error.default` | 供应商配置失败，请检查后重试 |

> 后端 `setup-wizard` 返回的可操作中文提示（如「连接/鉴权失败：…请检查 API Key / Base URL」）直接展示，不在前端二次翻译。

---

## Interaction & States

| State | Behavior |
|-------|----------|
| 步骤 1（管理员） | 复用 Phase 2 表单；提交成功（自动登录）后**原地切到步骤 2**（不路由跳转）。 |
| 步骤 2 初始 | 渲染步骤指示（1/2 当前为 2）+ 预设列表（默认选中第一个非自定义预设，自动填充 base_url/model）+ API Key 输入。 |
| 选择预设 | 选中卡片高亮（`border-primary bg-primary/5`）；base_url/model 字段自动填充（可编辑）；能力 badge 随预设更新；选「自定义」时 base_url/model 清空且必填。 |
| 字段校验失败 | vee-validate/zod 即时显示 `FormMessage`（中文）。 |
| 提交中 | CTA 显示 `icon-[lucide--loader-circle] animate-spin` + `setup.provider.testing`，按钮 `disabled`。 |
| 健康校验失败 | 顶部 destructive 错误条展示后端可操作中文提示；保持表单可编辑供修正重试。 |
| 提交成功 | 顶部短暂 `setup.provider.success`；`router.push('/')` 进入首页。 |
| 稍后配置 | 次级文本按钮，点击直接 `router.push('/')`（与刷新即回首页一致）。 |

预设能力展示（指引）：每个预设以 badge 列出「上下文 {n}」与「支持图像 / 纯文本」，数据来源 `lib/providerPresets.ts` 常量。

---

## Registry Safety

| Registry | Blocks Used | Safety Gate |
|----------|-------------|-------------|
| 项目自有 `~/components/ui/*`（仓库内） | Button, Form*（FormField/Item/Label/Control/Message）, Input | not required |
| reka-ui | 由上述 ui 组件内部封装 | not required |
| 第三方 shadcn registry | 无 | 不涉及 |

预设卡片、步骤指示、能力 badge 均用原生 `div`/`button` + Tailwind class 实现，不引入新组件/registry，无需安全门。

---

## Checker Sign-Off

- [x] Dimension 1 Copywriting: PASS — 新增预设/能力/校验/成功/错误文案均有具体中文，错误含解决信息；后端可操作提示直透
- [x] Dimension 2 Visuals: PASS — 复用 glass 卡片与 lucide 图标；预设卡片/badge 为原生元素，无新视觉债
- [x] Dimension 3 Color: PASS — 60/30/10 明确；accent 用于预设选中/当前步骤/图像能力，用途克制
- [x] Dimension 4 Typography: PASS — 沿用 Tailwind 文本刻度，新增 `text-xs` 能力/描述层级清晰
- [x] Dimension 5 Spacing: PASS — 全部 4px 倍数，复用现有间距写法
- [x] Dimension 6 Registry Safety: PASS — 仅用仓库内既有组件 + 原生元素，无第三方 registry

**Approval:** approved 2026-06-08（无人值守自校验；UI 面在 Phase 1/2 外壳内增量，无阻塞项）
