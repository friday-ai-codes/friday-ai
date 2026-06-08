---
phase: 4
plan: "04-02"
wave: 2
status: complete
completed: 2026-06-08
requirements: [SEC-01, FEISHU-01, FEISHU-02, RAG-01, RAG-02]
---

# Plan 04-02 Summary — 前端向导安全校验 + 可选集成步骤

## 交付
- `web/src/api/setup.ts`（改）：`SecurityCheck`/`SetupFeishuRequest`/`SetupRagRequest` 类型 +
  `getSecurityCheck`/`setupFeishu`/`setupRag` 三函数。
- `web/src/components/setup/SetupSecurityStep.vue`（新建）：onMounted 拉安全校验，全通过/风险/失败三态，
  「继续」按钮任何态都不 disable（非阻塞）。
- `web/src/components/setup/SetupFeishuStep.vue`（新建）：App ID/Secret 表单 + 保存 + 跳过。
- `web/src/components/setup/SetupRagStep.vue`（新建）：Qdrant URL 必填 + 可选 Key/Embedding + 保存 + 跳过。
- `web/src/pages/setup.vue`（改）：步骤机扩为 `admin→provider→security→feishu→rag`；圆点指示 + 进度文字；
  provider 完成/跳过推进到 security；rag 末步 done/skip → 进首页。
- `web/src/locales/zh-CN.json`（改）：`setup.steps.{security,feishu,rag}` + `security/feishu/rag/finish` 子树。

## 复用与边界
- 复用 `~/components/ui/{form,input,button}` + vee-validate/zod + vue-i18n（zh-CN）+ glass 卡片设计系统。
- 不改 Phase 1 路由守卫 / Phase 2 自动登录 / Phase 3 provider 组件与端点契约（仅改 provider 的 done/skip 目标步骤）。
- 安全校验非阻塞；飞书/RAG 跳过 = 不调用端点。

## 测试
- `src/api/__tests__/setup.spec.ts`（9）+ `SetupSecurityStep.spec.ts`（3）+ `SetupFeishuStep.spec.ts`（3）+
  `SetupRagStep.spec.ts`（3）+ 回归 `SetupProviderStep.spec.ts`（5）→ 23 passed。
- `eslint --fix` 干净（仅 Tailwind v4 类名建议级 warning，与既有 Phase 1-3 组件一致，未改）。
