---
phase: 3
plan: "03-02"
status: complete
completed: 2026-06-08
requirements: [PROV-02, PROV-03, PROV-01, PROV-04, PROV-05]
---

# Plan 03-02 Summary — 前端两步向导 + 一键预设

## Delivered
- `lib/providerPresets.ts`：5 个一键预设（DeepSeek V4 Pro / MiMo V2.5 Pro / Kimi 2.6 / Anthropic 官方 / 自定义），含 baseUrl/model/contextLength/supportsVision/description；`DEFAULT_PRESET`。
- `api/setup.ts`：新增 `setupProvider()` + 类型，调用 `POST /providers/setup-wizard/`。
- `components/setup/SetupProviderStep.vue`：预设选择卡片（选中高亮、能力 badge：上下文/图像/纯文本）、base_url+model 自动填充（可编辑）、API Key 输入、提交触发后端编排、失败展示后端可操作中文提示、「稍后配置」次级动作。
- `pages/setup.vue`：升级为两步向导（步骤指示 1/2）；管理员创建成功后**原地切到供应商步骤**（不路由跳转，未改动 Phase 1 守卫），供应商完成/跳过后 `router.push('/')`。
- `locales/zh-CN.json`：新增 `setup.steps.*` + `setup.provider.*` 中文文案。

## Reuse verification
- ✅ 复用 `types/providerCredential` 概念与既有 `api/client` post 封装。
- ✅ 复用 `~/components/ui/{form,input,button}` + vee-validate + zod 既有表单范式（与 Phase 2 一致）。
- ✅ 供应商落库/健康校验/设默认/绑 Claude Code 全部经后端 03-01 编排端点（复用 Fernet/health/Claude Code service），前端不直接拼凭证存储。

## Tests
- `vitest run` 3 文件 16 用例全绿：
  - `api/__tests__/setup.spec.ts`（setupProvider 路径/参数 + 错误透传）
  - `lib/__tests__/providerPresets.spec.ts`（5 预设 + 自定义空 + 默认项）
  - `components/setup/__tests__/SetupProviderStep.spec.ts`（渲染预设、选预设自动填充、提交调用 + emit done、失败展示中文错误、skip emit）

## Notes
- 预设 base_url/model 为各供应商 Anthropic 兼容端点公开约定，字段可编辑以纠错；健康校验失败给可操作提示。
- 残留 lint 为 Tailwind 4 类名提示（`bg-gradient-to-br`/`flex-shrink-0`），与既有 setup.vue 风格一致，未改以保持一致性（warning 非 error）。
- 刷新到 /setup 的边界：已初始化后守卫会把匿名导向 /login、已登录 superuser 进首页；供应商也可稍后在设置页配置（与「稍后配置」一致）。
