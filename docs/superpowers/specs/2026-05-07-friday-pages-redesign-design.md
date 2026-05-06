# Friday AI 列表页与新建仓库流程重新设计 — Spec
- 日期: 2026-05-07
- 范围: `/workflows`, `/projects`, `/repositories`, 新建仓库 Modal
- 设计语言: 沿用 `web/DESIGN.md` 中已定义的 Sub2API Clean Card 风格,本 spec 不更换设计语言
- 共识骨架: 工作台骨架 (KPI + 活动脱水 + 筛选 + 卡片网格)
---
## 1. 目标
1. 把三个列表页拉齐到 DESIGN.md 的 Sub2API Clean Card 语言,消除 `/workflows` 现存的 `bg-card/80 backdrop-blur` 与 teal/cyan 渐变 icon 等违规。
2. 引入统一的"工作台骨架"(KPI 概览 + 最近活动 + 筛选 + 卡片网格),提升信息密度与可扫描性,达到成熟开发者工具(GitHub Repos / Vercel / Linear)级别。
3. 把单一长表单的新建仓库 Modal 拆为 3 步,降低复杂度并强调"测试连接"的关键路径。
## 2. 不在范围
- 不更换设计语言(继续 Sub2API Clean Card)。
- 不改导航与路由结构。
- 不实现批量操作 / 收藏 / 导入导出 / 用户偏好持久化(YAGNI)。
- 后端字段缺口在第 8 节列出,但实施时若涉及后端改动,需另起 plan。
## 3. 硬约束(继承 DESIGN.md)
- 统一 `text-primary` 强调色,**禁止**为不同卡片分配 violet / amber / teal / cyan 等不同颜色 icon。
- 列表页卡片必须用语义 CSS 类 `.card .card-interactive`,不得用 shadcn `<Card>` 包裹。
- 文字层次仅使用 `text-foreground` / `text-muted-foreground`,不得使用过浅灰色组合(如 `text-xs text-muted-foreground uppercase tracking-wider`)。
- 状态徽标统一使用 `StatusBadge` + `~/config/status.ts`,不得在页面内自建 status map。
- 图标使用 Iconify SVG,禁用 emoji。
---
## 4. 通用骨架组件
### 4.1 PageHeader (已存在)
继续使用 `~/components/common/PageHeader.vue`,无改动。
### 4.2 StatCardRow (新增)
**职责**: 包装 4 张水平排列的 KPI Stat。
```
布局: grid grid-cols-2 sm:grid-cols-4 gap-4
单卡: 复用现有 StatCard,iconClass="stat-icon-primary"
加载: loading 状态显示 skeleton
点击: 每张支持 to 跳转(可选)
```
API:
```ts
defineProps<{
 stats: Array<{
 title: string
 value: number | string
 icon: string
 to?: string
 trend?: { value: number; direction: 'up' | 'down' }
 }>
 loading?: boolean
}>
```
### 4.3 ActivityFeed (新增) — 最近活动区
**职责**: 通用"最近活动"列表卡片,各列表页注入不同 source。
视觉规范:
- 容器: `.card`
- Header: `px-5 py-3.5 border-b border-border/50` + 标题 + 右上"查看全部"链接
- 行高: 每行 32px,`px-5 py-2`,hover 背景 `bg-muted/30`
- 每行结构: `[●状态点] [icon] 实体名 — 事件文 · 相对时间 [→]`
- 状态点: 4px 圆点(emerald / blue / amber / destructive / muted)
- 上限: 5 行,溢出由"查看全部"承接
- 空态: "暂无活动" + 引导插画
- 错误态: 简洁错误条 + 重试按钮
API:
```ts
defineProps<{
 items: Array<{
 id: string
 statusType: 'success' | 'running' | 'warning' | 'error' | 'idle'
 icon: string
 title: string
 subtitle: string
 timestamp: string
 to?: string
 }>
 loading?: boolean
 viewAllTo?: string
 emptyText?: string
}>
```
### 4.4 FilterBar (已存在,需扩展)
现有 `~/components/common/FilterBar.vue` 提供搜索 + 清除。本 spec 不改其 API,而在每个列表页内部组合:
- 搜索 `Input`(name + description 模糊匹配)
- 状态多选 `Select`
- 排序 `Select`(选项: 最近更新 / 创建时间 / 名称)
- 视图切换 `ToggleGroup`(网格 / 列表),默认网格
- 清除按钮(由 FilterBar `showClear` 控制)
### 4.5 ResourceListSkeleton (新增)
- 网格视图: 6 张卡片占位 skeleton(类似 WorkflowDataTable 现有 loading)
- 列表视图: 8 行 64px skeleton
---
## 5. 列表页详细设计
### 5.1 `/workflows` 工作流列表
**骨架**:
```
PageHeader [+ 新建工作流]
 ↓
StatCardRow [总工作流 | 启用中 | 正在执行 | 今日执行]
 ↓
ActivityFeed (最近 5 次执行,viewAllTo=/logs/executions)
 ↓
FilterBar [搜索 | 状态: 全部/启用/禁用 | 排序 | 视图切换]
 ↓
WorkflowGrid 或 WorkflowListView
```
**KPI 维度**:
| KPI | 数据来源 | 跳转 |
|---|---|---|
| 总工作流 | `workflows.length` | 当前页 |
| 启用中 | `workflows.filter(w => w.is_active).length` | 同页 + 状态筛选 |
| 正在执行 | `executionsStore.runningCount` (后端补) | `/logs/executions?status=running` |
| 今日执行 | `executionsStore.todayCount` (后端补) | `/logs/executions?date=today` |
**卡片(网格)** — 重写 `WorkflowDataTable.vue`:
- 容器改为 `.card .card-interactive`,**移除** `bg-card/80 backdrop-blur-sm` 与所有 teal/cyan 渐变。
- MiniMap 顶部区域: 100px 高度,白底 + `border-b border-border/50`,不再渐变背景。
- icon 容器统一: `.5 rounded-lg bg-primary/10` + `icon-[lucide--workflow] text-primary`。
- 禁用状态: 整卡 `opacity-60`,不再用 `bg-muted/30` 整体染灰(保留卡片白底,仅文字与 icon 透明度降低)。
- 节点类型 chip: `bg-muted/50 text-muted-foreground`(中性灰,保持现状)。
- 底部操作行: 与 DESIGN.md 卡片标准一致,`px-4 py-2.5 border-t border-border/50 bg-muted/20`,左侧"查看详情 →",右侧 Switch + Execute Button + Delete ghost。
**卡片(列表视图,新)**: 表格化,每行高度 64px。
| 状态点 | 名称 + 描述 | 节点摘要 | 最近执行 | 操作(执行/删除) |
### 5.2 `/projects` 项目列表
**骨架**:
```
PageHeader [+ 新建项目]
StatCardRow [总项目 | 关联仓库 | 总执行 | 本周执行]
ActivityFeed (最近 5 次项目级事件,viewAllTo=/logs/triggers)
FilterBar [搜索 | 活动度: 全部/7天内活跃/休眠 | 排序]
ProjectGrid 或 ProjectListView
```
**KPI 维度**:
| KPI | 来源 | 备注 |
|---|---|---|
| 总项目数 | `projects.length` | |
| 关联仓库数 | sum(`p.repositories.length`) | 后端建议提供聚合字段 `total_repositories_count` |
| 总执行次数 | sum(`p.execution_count`) | 已有 |
| 本周执行 | 后端补 `weekly_execution_count` | 缺,降级方案: 隐藏此 KPI 直到字段就绪 |
**卡片** — 在现有结构上微调:
- icon 容器保持 `bg-primary/10`(已合规)。
- 描述固定 `line-clamp-2`(已合规)。
- 最近工作项最多 3 条(已合规)。
- **新增** 底部统计行第 3 项: "最后活动 · 相对时间"(用 `last_activity_at` 字段,后端补)。
- 删除按钮 hover 样式从 `hover:bg-red-50!` 改为 `hover:bg-destructive/10 hover:text-destructive`,与 DESIGN.md 功能色对齐。
### 5.3 `/repositories` 仓库列表
**骨架**:
```
PageHeader [+ 新建仓库]
StatCardRow [总仓库 | 已索引 | 索引中/失败 | 本周新增]
ActivityFeed (最近 5 次索引/连接事件)
FilterBar [搜索 | 平台 | 索引状态 | 排序]
RepositoryGrid 或 RepositoryListView
```
**KPI 维度**:
| KPI | 来源 | 备注 |
|---|---|---|
| 总仓库数 | `repositories.length` | |
| 已索引 | `filter(r.index_status === 'indexed').length` | |
| 索引中/失败 | `filter('indexing').length` 主数 + `filter('failed').length` 副数 | 单卡双数字: 主数字 primary,副数字 destructive 小字 |
| 本周新增 | 前端 `created_at >= week_start` 过滤 | 不依赖后端 |
**卡片** — 在现有结构上微调:
- 顶部 0.5px 状态条(已合规,保持)。
- 平台 icon 容器统一 `bg-primary/10` + `text-primary`(当前已是)。
- URL 行: `font-mono text-xs muted truncate`,加 hover tooltip 显示完整 URL。
- 索引时间行: `text-xs muted` + `lucide--clock` icon。
- 底部操作图标按钮的 hover 样式与 DESIGN.md 功能色对齐(同 5.2 删除按钮)。
---
## 6. 新建仓库 Modal — 分步流程
### 6.1 步骤切分
**Step 1 — 基本信息**
- 仓库名称 *
- Git 平台 (Select with platform icons)
- 仓库 URL * (HTTPS 校验,placeholder 跟随平台联动)
- 默认分支 (默认 main)
- 仓库简介 (可选 Markdown)
**Step 2 — 凭证 & 测试连接**
- Access Token *
- Git 用户名 (默认 `Friday Codes AI Agent`)
- Git 邮箱 (默认 `ai@friday.codes`)
- Git 代理 URL (可选)
- **[测试连接]** 按钮 — 主操作,大尺寸,放表单底部
- 测试结果区: 成功显示分支数 + emerald 状态条;失败显示原因 + destructive 状态条 + "如何获取 Token" 帮助链接
- **门控**: 测试连接成功才能进入 Step 3
**Step 3 — 索引设置**
- 基础分支 (BranchCombobox,从 Step 2 测试结果中的分支列表选择)
- 默认值: Step 2 返回的 `recommended_branch`
- 提示: "用于代码索引的基准分支,通常与默认分支相同"
- 提交按钮 [创建仓库]
### 6.2 视觉规范
- **icon 颜色**: 头部 icon 改为 `text-primary`,**移除现存的 `text-violet-600` 与 `text-amber-600`**,与 DESIGN.md 统一。
- **Header**: `.5 rounded-xl bg-primary/10` icon 容器 + 标题 + 步骤指示器(横向 1—2—3,当前高亮 primary,已完成显示 emerald check)。
- **Body**: 单列表单,顶部固定 stepper 指示器,中段 scrollable,字段间距 `space-y-5`(与现有节奏一致)。
- **Footer**: `[取消] [上一步] [下一步 / 创建仓库]`。
 - "下一步"在当前步必填字段未通过时禁用。
 - 第 1 步无"上一步"。
 - 第 3 步显示"创建仓库"主按钮。
### 6.3 验证策略
- 字段级: onBlur 校验。
- 步骤级: 点击"下一步"时校验当前步必填,不通过则聚焦首个错误字段。
- Step 2 → Step 3 门控: 必须"测试连接"成功(`testResult.success === true`)。
- 提交级: Step 3 提交时调 `repositoriesStore.createRepository`,失败保持在 Step 3 + 错误提示。
### 6.4 关键交互
- 关闭 Modal 时若已填写过任意字段: 弹 `ConfirmDialog` "放弃填写吗?"。
- 测试连接失败: 不阻塞用户回切 Step 1 修改 URL / 平台。
- 平台切换时,URL placeholder 联动:
 - github → `https://github.com/user/repo.git`
 - gitlab → `https://gitlab.com/group/repo.git`
 - gitea / bitbucket → 同理
- 平台切换时若 `git_url` 为空,自动填入 placeholder 主域(可选,本期可不做)。
---
## 7. 实施清单(供 writing-plans 使用)
### Phase A — 通用骨架组件
1. 新建 `web/src/components/common/StatCardRow.vue`
2. 新建 `web/src/components/common/ActivityFeed.vue`
3. 验证 `FilterBar.vue` 已支持本 spec 用法,补 `ToggleGroup` 视图切换 slot 若缺
4. 新建 `web/src/components/common/ResourceListSkeleton.vue`
### Phase B — workflows 重做
1. 重写 `WorkflowDataTable.vue` 卡片(移除 backdrop-blur,对齐 .card)
2. 新建 `WorkflowListView.vue` 列表视图
3. 重写 `pages/workflows/index.vue` 接入新骨架
4. 后端补: running_count / today_count(若不存在,降级隐藏 KPI)
### Phase C — projects 重做
1. 重写 `pages/projects/index.vue` 接入新骨架
2. 卡片增加"最后活动时间"
3. 新建 `ProjectListView.vue`
4. 后端补: total_repositories_count / weekly_execution_count / recent-activity API
### Phase D — repositories 重做
1. 重写 `pages/repositories/index.vue` 接入新骨架
2. 卡片信息层次微调
3. 新建 `RepositoryListView.vue`
4. 后端补: recent-events API
### Phase E — 新建仓库 Modal 分步
1. 重写 `CreateRepositoryModal.vue` 为 Stepper 模式
2. icon 颜色改 `text-primary`(同时排查并修正项目内其他类似违规)
3. 字段拆 3 步,加未保存确认
4. 平台 placeholder 联动
### Phase F — 验收
1. 三页视觉与 DESIGN.md 一致性自查
2. 加载 / 空态 / 错误态完整覆盖
3. 暗色模式对比度自检
4. 移动端 375px / 平板 768px 视觉验证
5. 键盘导航 + aria-label 验证
---
## 8. 数据 / 后端依赖清单
| 字段 / API | 现状 | 行动 | 影响 |
|---|---|---|---|
| `workflows.running_count` (全局) | 缺 | 新增字段或 endpoint | KPI 缺则降级隐藏 |
| `workflows.today_executions` (全局) | 缺 | 同上 | 同上 |
| `projects.total_repositories_count` | 通过逐项 length 算 | 建议聚合字段 | 不阻塞 |
| `projects.weekly_execution_count` | 缺 | 新增字段 | KPI 缺则隐藏 |
| `projects.last_activity_at` | 缺 | 新增字段 | 卡片底部行降级 |
| `projects/recent-activity` API | 缺 | 新增 endpoint | ActivityFeed 缺则隐藏整块 |
| `repositories/recent-events` API | 缺 | 新增 endpoint | 同上 |
**降级策略统一**: 后端字段未就绪时,前端隐藏对应 KPI 卡或 ActivityFeed 整块,保持骨架完整不报错。
---
## 9. YAGNI 清单(本期不做)
- 批量操作(批量删除 / 批量启用)
- 导出 / 导入
- 收藏 / 标签
- 用户偏好持久化(列表/网格视图记忆)
- 高级搜索语法(filter:active type:workflow)
## 10. 验收标准
- 三个列表页加载首屏视觉与 DESIGN.md 描述一致(spot check 5 处)
- 全站无 `bg-card/80 backdrop-blur-sm` / 彩色渐变 icon 残留
- 三页骨架(KPI / ActivityFeed / FilterBar / Cards)结构对齐
- 新建仓库 Modal 分 3 步,Step 2 必须"测试连接"成功才能 next
- icon 颜色 violet / amber 等违规已清理
- 加载 / 空态 / 错误态完整
- 移动端 375px 与桌面 1440px 都不溢出
- 暗色模式 4.5:1 对比度
- 键盘 Tab 顺序与视觉顺序一致
