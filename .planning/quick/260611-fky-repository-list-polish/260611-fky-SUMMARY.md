---
status: complete
---

# Quick Task 260611-fky: 打磨仓库列表索引完成界面视觉

## 完成内容

- `web/src/pages/repositories/index.vue`：重做仓库列表卡片结构，去掉突兀的顶部索引状态条，改为轻量状态 pill、柔和顶部 accent、代码 URL 条、统一元信息行和更安静的底部操作区。
- 外层卡片从整卡 `RouterLink` 改为 `article` + 主内容链接 + 独立操作链接，避免嵌套链接，同时保留“查看详情 / 代码索引 / 凭证管理”入口。
- `web/src/pages/repositories/__tests__/index.spec.ts`：新增页面渲染测试，锁定已索引仓库卡片的新结构。

## 验证

- RED：`pnpm test:unit -- web/src/pages/repositories/__tests__/index.spec.ts` 失败于 `.repo-card` 不存在；同次全量匹配里还暴露既有 `gsap` 解析失败，与本改动无关。
- GREEN：`pnpm vitest run src/pages/repositories/__tests__/index.spec.ts` 通过（1 test）。
- Lint：`pnpm eslint src/pages/repositories/index.vue src/pages/repositories/__tests__/index.spec.ts` 通过。
- Type check：`pnpm type-check` 通过。

## 提交

- `fa5e1b0a` — `fix(web): polish repository indexed cards`

## 备注

- Browser 已打开 `http://127.0.0.1:10240/repositories`，但当前 in-app browser 无登录态，路由展示登录页；data URL 预览壳被 Browser 安全策略拒绝，未继续绕过。
