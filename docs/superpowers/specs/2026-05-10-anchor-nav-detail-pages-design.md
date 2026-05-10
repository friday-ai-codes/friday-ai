# 项目/仓库详情页锚点导航改造设计
## 背景
当前项目列表页和仓库列表页每个卡片都带有删除按钮，容易误触。本设计将删除操作集中到详情页，并将详情页改造为 GitHub Settings 风格的两栏锚点导航布局。
## 目标
1. 列表页移除删除按钮，减少误触风险
2. 详情页采用左侧粘性锚点导航 + 右侧垂直平铺区块
3. 两个资源（项目、仓库）统一布局模式
## 方案
### 1. 列表页改动
#### 项目列表页 (`projects/index.vue`)
- 移除每个卡片底部操作栏中的垃圾桶 `Button`（保留「查看详情」文字链接）
- 移除 `deleteDialogOpen`、`projectToDelete`、`deleting` 等删除相关状态
- 移除 `confirmDelete`、`handleDelete` 方法
- 移除底部 `<ConfirmDialog />`
#### 仓库列表页 (`repositories/index.vue`)
- 移除每个卡片底部操作栏中的垃圾桶 `Button`
- 移除 `deleteDialogOpen`、`repositoryToDelete`、`deleting` 等删除相关状态
- 移除 `confirmDelete`、`handleDelete` 方法
- 移除底部 `<ConfirmDialog />`
### 2. 详情页锚点导航布局
通用结构（项目、仓库共用模式）：
```
┌─────────────────────────────────────────────────────┐
│ 返回链接 │
├──────────┬────────────────────────────────────────────┤
│ │ 头部信息（标题 + 编辑按钮） │
│ 左侧导航 │ │
│ (sticky) │ ── 区块 1 ── │
│ │ ── 区块 2 ── │
│ - 锚点 1 │ ── 区块 3 ── │
│ - 锚点 2 │ ... │
│ - ... │ │
│ - 危险操作│ ── 危险操作 ── (红色边框) │
│ │ │
└──────────┴────────────────────────────────────────────┘
```
#### 组件设计
**新增 `AnchorNavLayout.vue`**
- Props: `sections: { id: string, label: string, icon?: string }`
- 使用 `IntersectionObserver` 监听右侧 section 可见性
- 当前可见 section 对应的左侧锚点高亮（`text-primary font-medium`）
- 点击锚点时 `scrollIntoView({ behavior: 'smooth', block: 'start' })`
- 移动端（< 768px）：左侧导航变为顶部横向滚动条
- 布局：左侧 `w-48 shrink-0`，右侧 `flex-1 min-w-0`
#### 项目详情页区块
| 锚点 | 对应内容 | ID |
|------|---------|-----|
| 基本信息 | 名称、描述、飞书 Key、创建/更新时间 | `basic-info` |
| 关联仓库 | 仓库列表 + 管理按钮 | `repositories` |
| 飞书配置 | 配置状态 + 管理入口 | `feishu` |
| Prompt 覆盖 | 管理入口 | `prompts` |
| Provider 凭证 | 凭证覆盖管理 | `providers` |
| Webhook Token | Token 展示 + 刷新/自定义 | `webhook-token` |
| 相关执行 | 最近 5 条执行记录 | `executions` |
| 危险操作 | 删除项目按钮（红色边框卡片） | `danger-zone` |
**编辑按钮位置**：头部信息区域保留，点击进入编辑页（`/projects/:id/edit`）
**删除确认**：保留现有的 `ConfirmDialog`，确认后跳转到 `/projects`
#### 仓库详情页区块
| 锚点 | 对应内容 | ID |
|------|---------|-----|
| 基本信息 | 平台、URL、分支、创建/更新时间、状态徽章 | `basic-info` |
| 分支索引 | 分支选择器 + 健康状态 + 重建索引 | `branch-index` |
| 索引统计 | RepositoryIndexCard + IndexStatsPanel + 历史 | `index-stats` |
| 关联项目 | 已关联项目列表 | `linked-projects` |
| 凭证配置 | 凭证状态 + 管理入口 | `credential` |
| Webhook 自动化 | WebhookConfigPanel | `webhook` |
| 危险操作 | 删除仓库按钮（红色边框卡片） | `danger-zone` |
**编辑按钮位置**：头部信息区域保留，点击打开 `EditRepositoryModal`
**删除确认**：保留现有的 `ConfirmDialog`，确认后跳转到 `/repositories`
### 3. 交互细节
- **锚点高亮阈值**：`IntersectionObserver` 设置 `rootMargin: '-20% 0px -60% 0px'`，确保当前视口中心附近的区块被高亮
- **平滑滚动偏移**：考虑到可能存在的固定头部，滚动时添加 `-80px` 的 scroll-margin-top
- **移动端降级**：`< md` 断点下隐藏左侧导航，右侧内容正常垂直滚动；或改为顶部水平滚动条
- **危险操作区样式**：红色边框 `border-destructive/30`，红色背景 `bg-destructive/5`，按钮使用 `variant="destructive"`
### 4. 文件改动清单
| 文件 | 改动类型 |
|------|---------|
| `web/src/components/layout/AnchorNavLayout.vue` | 新增 |
| `web/src/pages/projects/index.vue` | 删除按钮及状态移除 |
| `web/src/pages/projects/[id]/index.vue` | 改造为锚点导航布局 |
| `web/src/pages/repositories/index.vue` | 删除按钮及状态移除 |
| `web/src/pages/repositories/[id]/index.vue` | 改造为锚点导航布局 |
## 影响范围
- 不涉及后端 API 改动
- 不涉及路由结构变更
- 编辑页（`edit.vue`）保持独立页面不变
- 仓库编辑保持弹窗形式不变
