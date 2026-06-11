# Quick Task 260611-fky: 打磨仓库列表索引完成界面视觉

用户反馈：仓库管理页在仓库已索引后视觉显得粗糙，截图中顶部状态条、重阴影、底部操作栏和内容层级不协调。

## Task 1: 锁定新列表结构

- 新增 `web/src/pages/repositories/__tests__/index.spec.ts`
- mock 仓库 store、router、modal、PageHeader、StatusBadge、Tooltip 等依赖
- 验证已索引仓库卡片渲染为更克制的管理台卡片结构：
  - 仓库名和索引状态在同一标题区
  - Git URL 位于 `repo-url-chip` 代码条中
  - 索引时间位于 `repo-meta-item`
  - 底部操作区包含代码索引和凭证管理入口

验收：先运行目标测试看到失败，再实现页面让测试通过。

## Task 2: 重做仓库列表卡片视觉

- 修改 `web/src/pages/repositories/index.vue`
- 移除突兀顶部状态条，改为右上角状态 pill + 柔和 accent 背景
- URL 改为浅色代码条，分支/空间/索引时间统一为扫描友好的元信息行
- 底部栏从厚重分隔区改为轻量操作区，主动作“查看详情”明确，二级入口使用 icon button + tooltip
- 维持现有 `RouterLink`、`StatusBadge`、`Badge`、`Button`、`Tooltip` 交互和路由

验收：`pnpm test:unit -- web/src/pages/repositories/__tests__/index.spec.ts` 通过；`pnpm type-check` 通过；浏览器截图无明显文字重叠。
