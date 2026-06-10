---
phase: 4
slug: security-integrations
status: approved
shadcn_initialized: false
preset: none
created: 2026-06-08
---

# Phase 4 — UI Design Contract

> 在 Phase 1/2/3 已交付的 `/setup` 多步向导外壳（glass 卡片 + `~/components/ui/{form,input,button}` +
> vee-validate/zod，步骤 admin → provider）之上，**追加三步**：步骤 3「安全校验」（只读风险提示，非阻塞）、
> 步骤 4「飞书集成」（可跳过表单）、步骤 5「向量检索」（可跳过表单，末步进入首页）。无人值守生成，
> 复用 `web/` 既有设计系统（Tailwind 4 CSS 主题 + reka-ui + lucide），自校验通过。
> 本阶段 UI 面：仍是单张 `/setup` glass 卡片，内部按 `step` 切换；步骤指示由 2 标签升级为 N 圆点 + 文字进度；
> 新增风险提示条（warning）、可跳过表单与"跳过"次级动作。无新增页面/路由。

---

## Design System

| Property | Value |
|----------|-------|
| Tool | none（项目自有 shadcn-vue 风格组件 `~/components/ui/*`，非 shadcn CLI 注册） |
| Preset | not applicable |
| Component library | reka-ui（Radix 风格）+ 项目自有 `~/components/ui/{button,form,input}` |
| Icon library | lucide（经 `@iconify/tailwind4`，用法 `icon-[lucide--*]`） |
| Font | 应用默认无衬线栈（Tailwind 默认 sans） |

复用既有主题令牌（`web/src/styles/main.css` `@theme`）：`--color-primary`（teal-500）、`--color-card`、
`--color-border`、`--color-muted-foreground`、`--color-destructive`、`--shadow-glass`。**不新增主题令牌、不做主题化定制**。

风险提示用 amber 语义（`bg-amber-500/8 border-amber-500/15 text-amber-600`，与密码强度"中"档同色系）；
"安全"全通过态用 primary（`text-primary` + `icon-[lucide--shield-check]`）。

---

## Spacing Scale

复用 Tailwind 默认 4px 基准刻度（与现有 `setup.vue` 一致）：

| Token | Value | Usage |
|-------|-------|-------|
| xs | 4px | 图标与文字间距（`gap-1`）、圆点指示间距 |
| sm | 8px | 风险条内间距、字段标签间距（`gap-2`） |
| md | 16px | 表单字段间距（`space-y-4`） |
| lg | 24px | 步骤标题与表单间距（`mb-6`） |
| xl | 32px | 外壳卡片内边距（`p-8`） |

Exceptions: none（沿用现有 `max-w-lg`/`rounded-2xl`）。

---

## Typography

沿用现有 `setup.vue` 排版（Tailwind 文本刻度）：

| Role | Size | Weight | Line Height |
|------|------|--------|-------------|
| Heading（步骤标题） | 24px (`text-2xl`) | 700 (`font-bold`) | 1.3 |
| 副标题 / 进度文字 | 14px (`text-sm`) | 400/500 | 1.5 |
| Label（字段标签） | 14px (`text-sm font-medium`) | 500 | 1.4 |
| 风险项 / Hint | 12-14px (`text-xs`/`text-sm`) | 400 | 1.4 |
| Error message | 12-14px (`text-sm` destructive) | 400 | 1.4 |

---

## Color

| Role | Value | Usage |
|------|-------|-------|
| Dominant (60%) | `--color-background`（slate-50） | 页面背景、mesh 渐变底 |
| Secondary (30%) | `--color-card`（半透明 `bg-card/70` 玻璃卡片） | 外壳卡片表面 |
| Accent (10%) | `--color-primary`（teal-500） | 品牌图标、主 CTA、聚焦 ring、当前步骤圆点、安全全通过态 |
| Warning | amber-500/600 | 安全风险提示条（非阻塞） |
| Destructive | `--color-destructive` | 字段错误、保存失败提示 |

Accent reserved for: 品牌徽标、主 CTA、加载指示、聚焦 ring、当前步骤圆点、安全"全通过"图标。**不**用于普通文本；
风险提示一律用 warning（amber），与 destructive 区分（提示≠错误，不阻塞）。

---

## Copywriting Contract

本阶段全部用户可见文案经 `vue-i18n`（zh-CN 默认）取用（`setup.*` 命名空间）。新增如下（沿用 Phase 1/2/3 既有键风格）：

| Element | i18n Key | Copy |
|---------|----------|------|
| 步骤 3 标签 | `setup.steps.security` | 安全校验 |
| 步骤 4 标签 | `setup.steps.feishu` | 飞书集成 |
| 步骤 5 标签 | `setup.steps.rag` | 向量检索 |
| 步骤进度 | `setup.steps.indicator` | 第 {current} / {total} 步（已存在） |
| 安全步骤标题 | `setup.security.title` | 安全密钥校验 |
| 安全步骤副标题 | `setup.security.subtitle` | 检查加密与签名密钥是否安全配置，仅作提示不阻塞 |
| 安全 - 全通过 | `setup.security.allClear` | 密钥配置安全：SECRET_KEY 与 FRIDAY_ENCRYPTION_KEY 均已自定义且相互独立 |
| 安全 - 校验中 | `setup.security.checking` | 正在检查密钥配置… |
| 安全 - 无法校验 | `setup.security.unavailable` | 暂时无法读取密钥状态，可稍后在部署环境核对（不影响继续） |
| 风险 - SECRET_KEY 默认 | `setup.security.risk.secretKeyDefault` | SECRET_KEY 仍为默认值，请在生产环境通过环境变量设置为随机强密钥 |
| 风险 - 加密密钥未设置 | `setup.security.risk.encryptionKeyUnset` | 未单独设置 FRIDAY_ENCRYPTION_KEY，加密将回退派生自 SECRET_KEY，建议单独配置 |
| 风险 - 密钥不独立 | `setup.security.risk.keysNotIndependent` | FRIDAY_ENCRYPTION_KEY 与 SECRET_KEY 相同，建议使用相互独立的密钥 |
| 安全 - 风险提醒标题 | `setup.security.riskTitle` | 检测到密钥安全风险（不影响完成向导） |
| 安全 - 继续 | `setup.security.cta` | 继续配置可选集成 |
| 飞书步骤标题 | `setup.feishu.title` | 配置飞书集成（可选） |
| 飞书步骤副标题 | `setup.feishu.subtitle` | 填写飞书应用凭证以启用飞书需求拉取与通知，可稍后在设置中配置 |
| 飞书 - App ID | `setup.feishu.fields.appId` | App ID |
| 飞书 - App Secret | `setup.feishu.fields.appSecret` | App Secret |
| 飞书 - App ID 占位 | `setup.feishu.fields.appIdPlaceholder` | cli_xxxxxxxx |
| 飞书 - App Secret 占位 | `setup.feishu.fields.appSecretPlaceholder` | 粘贴飞书应用的 App Secret |
| 飞书 - 校验 appId | `setup.feishu.validation.appIdRequired` | 请填写 App ID |
| 飞书 - 校验 secret | `setup.feishu.validation.appSecretRequired` | 请填写 App Secret |
| 飞书 - CTA | `setup.feishu.cta` | 保存并继续 |
| 飞书 - 保存中 | `setup.feishu.saving` | 正在保存… |
| 飞书 - 跳过 | `setup.feishu.skip` | 跳过，稍后在设置中配置 |
| 飞书 - 错误默认 | `setup.feishu.error.default` | 飞书配置保存失败，请重试 |
| 向量步骤标题 | `setup.rag.title` | 配置向量检索（可选） |
| 向量步骤副标题 | `setup.rag.subtitle` | 配置 Qdrant 与 Embedding 以启用代码语义检索，可稍后在设置中配置 |
| 向量 - Qdrant URL | `setup.rag.fields.qdrantUrl` | Qdrant 地址 |
| 向量 - Qdrant Key | `setup.rag.fields.qdrantApiKey` | Qdrant API Key（可选） |
| 向量 - Embedding URL | `setup.rag.fields.embeddingApiUrl` | Embedding 接口地址（可选） |
| 向量 - Embedding Key | `setup.rag.fields.embeddingApiKey` | Embedding API Key（可选） |
| 向量 - Embedding 模型 | `setup.rag.fields.embeddingModel` | Embedding 模型（可选） |
| 向量 - Embedding 维度 | `setup.rag.fields.embeddingDimension` | 向量维度（可选） |
| 向量 - Qdrant URL 占位 | `setup.rag.fields.qdrantUrlPlaceholder` | http://qdrant:6333 |
| 向量 - 校验 qdrantUrl | `setup.rag.validation.qdrantUrlRequired` | 请填写 Qdrant 地址 |
| 向量 - CTA | `setup.rag.cta` | 保存并完成 |
| 向量 - 保存中 | `setup.rag.saving` | 正在保存… |
| 向量 - 跳过 | `setup.rag.skip` | 跳过并进入系统 |
| 向量 - 错误默认 | `setup.rag.error.default` | 向量检索配置保存失败，请重试 |
| 完成 | `setup.finish.success` | 配置完成，正在进入系统… |

> 后端返回的可操作中文 `detail` 直接展示，不在前端二次翻译。

---

## Interaction & States

| State | Behavior |
|-------|----------|
| 步骤指示 | N 枚圆点（admin/provider/security/feishu/rag），当前步 primary 高亮，已完成步 muted-filled；下方 `setup.steps.indicator` 文字「第 {current} / {total} 步 · {当前步标签}」。 |
| 进入步骤 3（安全） | onMounted 调 `GET /api/system/security-check/`；加载中显示 `checking` spinner。 |
| 安全 - 全通过 | primary `icon-[lucide--shield-check]` + `allClear`；单一 `继续配置可选集成` 主按钮 → 步骤 4。 |
| 安全 - 有风险 | amber 提示块标题 `riskTitle` + 逐条风险项（`risk.*`，按后端 code 映射）；**仍显示** `继续` 主按钮（永不禁用/阻塞）。 |
| 安全 - 端点失败 | 中性 `unavailable` 提示；`继续` 按钮照常可用（不阻塞）。 |
| 步骤 4（飞书） | App ID + App Secret 表单（vee-validate/zod，提交时校验非空）；`保存并继续` 提交 `POST /api/system/setup-feishu/` 成功 → 步骤 5；`跳过` 次级文本按钮 → 步骤 5（不调用端点）。 |
| 步骤 5（向量） | Qdrant URL（必填若提交）+ 可选 Key/Embedding 字段；`保存并完成` 提交 `POST /api/system/setup-rag/` 成功 → `router.push('/')`；`跳过并进入系统` → `router.push('/')`（不调用端点）。 |
| 提交中（飞书/向量） | CTA 显示 `icon-[lucide--loader-circle] animate-spin` + saving 文案，按钮 `disabled`。 |
| 保存失败 | 顶部 destructive 错误条展示后端可操作 `detail`；表单保持可编辑供修正重试，**不阻塞**「跳过」。 |
| 敏感字段输入 | App Secret / API Key 用 `type="password"`，`autocomplete="off"`。 |

非阻塞契约（SEC-01）：安全步骤的「继续」按钮在任何校验结果（通过/有风险/无法读取）下都可点击，绝不 disable。

---

## Registry Safety

| Registry | Blocks Used | Safety Gate |
|----------|-------------|-------------|
| 项目自有 `~/components/ui/*`（仓库内） | Button, Form*（FormField/Item/Label/Control/Message）, Input | not required |
| reka-ui | 由上述 ui 组件内部封装 | not required |
| 第三方 shadcn registry | 无 | 不涉及 |

风险提示条、圆点步骤指示均用原生 `div`/`span` + Tailwind class 实现，不引入新组件/registry，无需安全门。

---

## Checker Sign-Off

- [x] Dimension 1 Copywriting: PASS — 安全/飞书/向量全部文案具体中文；风险项含可操作建议；后端 detail 直透
- [x] Dimension 2 Visuals: PASS — 复用 glass 卡片与 lucide 图标；风险条/圆点为原生元素，无新视觉债
- [x] Dimension 3 Color: PASS — 60/30/10 明确；warning(amber) 与 destructive 区分（提示≠错误）；accent 克制
- [x] Dimension 4 Typography: PASS — 沿用 Tailwind 文本刻度，层级清晰
- [x] Dimension 5 Spacing: PASS — 全部 4px 倍数，复用现有间距写法
- [x] Dimension 6 Registry Safety: PASS — 仅用仓库内既有组件 + 原生元素，无第三方 registry

**Approval:** approved 2026-06-08（无人值守自校验；UI 面在 Phase 1/2/3 外壳内增量，安全校验非阻塞，无阻塞项）
