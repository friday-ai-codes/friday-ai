# 前端设计规范 — Sub2API Clean Card 风格
## 设计理念（来自 sub2api 参考）
- **统一主色**：全站只用 primary（teal）作为强调色，不给每个卡片分配不同颜色
- **干净卡片**：纯白底 + 极细边框 + 微阴影，不使用彩色 glow/blur 背景层
- **清晰文字层次**：`text-foreground` 用于标题和值，`text-muted-foreground` 用于标签，禁止灰到看不见
- **紧凑间距**：卡片内边距 ``~``，卡片间距 `gap-4`，避免大面积空白
## 核心特征
| 元素 | 类名 |
| ---------------- | ----------------------------------------------------------------- |
| 标准卡片 | `.card`（白底、`rounded-2xl`、`shadow-card`、`border-border/50`） |
| 可交互卡片 | `.card .card-interactive`（hover 上浮 + 加深阴影） |
| 卡片头部 | `px-5 py-3.5 border-b border-border/50` + 图标 + 标题 |
| 卡片内容 | `` |
| 图标容器（小） | `.5 rounded-lg bg-primary/10` |
| 图标容器（大） | ` rounded-lg bg-primary/10` |
| 悬浮效果 | `.card-interactive`（translateY + shadow-card-hover） |
| 玻璃卡片（特殊） | `glass-card rounded-2xl`（仅用于 Hero/登录等特殊场景） |
## CSS 双轨分层原则
项目同时使用 **shadcn 原语组件** 和 **语义 CSS 类** 两套体系，各有分工：
| 体系 | 用途 | 示例 |
| ----------- | -------- | ----------------------------------------------- |
| shadcn 原语 | 交互组件 | `<Button>` `<Badge>` `<Select>` `<Dialog>` |
| 语义 CSS 类 | 纯视觉 | `.btn` `.card` `.card-interactive` `.stat-icon` |
**核心规则：同一元素上不得同时叠加两套体系。**
```vue
<!-- 正确：交互用 shadcn -->
<Button variant="outline" @click="handleClick">操作</Button>
<!-- 正确：纯视觉用语义类 -->
<button class="btn btn-primary" @click="handleClick">操作</button>
<!-- 错误：混用两套体系 -->
<Button class="btn btn-primary">操作</Button>
```
## 卡片模式
### 详情页卡片（统一风格）
```vue
<!-- 正确：干净的 .card + 统一 primary 图标 -->
<div class="card">
 <div class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2">
 <span class="icon-[lucide--info] text-primary" />
 <h3 class="text-sm font-semibold">卡片标题</h3>
 </div>
 <div class="">内容</div>
</div>
<!-- 错误：每个卡片用不同彩色 glow -->
<div class="relative">
 <div class="absolute -inset-1 bg-gradient-to-r from-violet-500/10 ..." />
 <Card class="relative bg-card/80 backdrop-blur-sm">...</Card>
</div>
```
### 列表页卡片
```vue
<RouterLink class="card card-interactive group flex flex-col">
 <div class=" flex-1 space-y-3">...</div>
 <div class="px-4 py-2.5 border-t border-border/50">操作栏</div>
</RouterLink>
```
### 文字层次
| 用途 | 类名 | 说明 |
| ------- | --------------------------- | --------------------------- |
| 标题 | `text-foreground` | 深色，清晰可读 |
| 值/数据 | `text-foreground` | 与标题同色 |
| 标签 | `text-muted-foreground` | 灰色辅助文字 |
| 描述 | `text-muted-foreground` | 配合 `text-xs` 或 `text-sm` |
| mono 值 | `font-mono text-foreground` | 代码/URL/Token |
## 功能色系
- 主要强调：`text-primary`（所有卡片图标统一用 primary）
- 成功状态：`text-emerald-500`（仅用于状态指示器）
- 警告提示：`text-amber-500`（仅用于警告提示框）
- 错误状态：`text-destructive`（仅用于错误/危险操作）
## Badge 使用规范
### 可用 variant
| variant | 用途 | 色系 |
| ------------- | ----------- | ---------- |
| `default` | 主色调 | primary |
| `secondary` | 辅助信息 | secondary |
| `destructive` | 错误/危险 | red |
| `outline` | 边框强调 | foreground |
| `success` | 成功/完成 | emerald |
| `warning` | 警告/等待 | amber |
| `info` | 信息/进行中 | blue |
| `muted` | 灰化/停用 | gray |
### Badge 规则
- 所有颜色通过 `variant` prop 控制：`<Badge variant="success">`
- **禁止**在 Badge 上使用 `:class` 追加颜色类覆盖样式
```vue
<!-- 正确 -->
<Badge variant="success">已完成</Badge>
<!-- 错误 -->
<Badge:class="'bg-emerald-100 text-emerald-700'">已完成</Badge>
```
## StatusBadge 使用规范
所有状态类标签统一使用 `StatusBadge` 组件：
```vue
<StatusBadge type="execution":status="execution.status" />
<StatusBadge type="runner":status="runner.status" size="sm" />
<StatusBadge type="codingTask":status="task.status":show-label="false" />
```
### Props
| prop | 类型 | 默认值 | 说明 |
| ----------- | -------------------------------------------------------------------- | ------ | ------------ |
| `type` | `'execution' \| 'runner' \| 'codingTask' \| 'index' \| 'triggerLog'` | 必填 | 状态类型 |
| `status` | `string` | 必填 | 状态值 |
| `showLabel` | `boolean` | `true` | 是否显示文字 |
| `showIcon` | `boolean` | `true` | 是否显示图标 |
| `size` | `'sm' \| 'md' \| 'lg'` | `'md'` | 尺寸 |
### StatusBadge 规则
- **禁止**在页面或组件内部定义 `statusColors` / `statusMap` / `statusConfig` 局部常量
- 所有状态配置从 `~/config/status.ts` 导入
## 通用组件规范
### PageHeader — 页面标题栏
所有列表页标题区统一使用：
```vue
<PageHeader
 icon="lucide--folder-git-2"
 icon-gradient="from-primary/20 to-primary/10"
 icon-color="text-primary"
 title="项目管理"
 description="管理您的 Git 仓库项目和凭证配置"
>
 <template #actions>
 <button class="btn btn-primary" @click="create">新建</button>
 </template>
</PageHeader>
```
| prop | 类型 | 说明 |
| -------------- | --------- | -------------- |
| `icon` | `string` | Iconify 图标名 |
| `iconGradient` | `string?` | 图标容器渐变 |
| `iconColor` | `string?` | 图标颜色 |
| `title` | `string` | 标题 |
| `description` | `string?` | 描述 |
Slots: `#title-suffix` `#actions`
### StatCard — KPI 统计卡片
```vue
<StatCard
 title="项目总数":value="42"
 icon="lucide--folder-git-2"
 icon-class="stat-icon-primary"
 to="/projects":loading="loading"
/>
```
| prop | 类型 | 说明 |
| ----------- | ----------------------------------------------- | ------------------------------- |
| `title` | `string` | 标题 |
| `value` | `string \| number` | 数值 |
| `icon` | `string` | 图标名 |
| `iconClass` | `string?` | 图标容器颜色类 |
| `loading` | `boolean?` | 加载状态 |
| `to` | `string?` | 链接（有值时渲染为 RouterLink） |
| `trend` | `{ value: number, direction: 'up' \| 'down' }?` | 趋势 |
### FilterBar — 筛选区域容器
```vue
<FilterBar:show-clear="hasActiveFilters" @clear="resetFilters">
 <Input v-model="search" placeholder="搜索..." />
 <Select v-model="status">...</Select>
</FilterBar>
```
| prop | 类型 | 说明 |
| ----------- | ---------- | ---------------- |
| `showClear` | `boolean?` | 是否显示清除按钮 |
Emits: `clear`
## 动画
- 进入动画：`animate-fade-in`、`animate-slide-up`、`animate-slide-down`
- 侧边滑入：`animate-slide-in-right`
- 弹出缩放：`animate-scale-in`
- 加载效果：`animate-shimmer`
- 光效循环：`animate-glow`
## 阴影
- 玻璃阴影：`shadow-glass` — 柔和的半透明投影
- 辉光阴影：`shadow-glow` — 青色辉光效果
- 卡片阴影：`shadow-card` — 基础卡片投影
- 悬浮阴影：`shadow-card-hover` — 悬浮时增强投影
## 禁止
- **彩虹卡片**：给同一页面的不同卡片分配不同颜色（violet、emerald、orange、rose 等）
- **Glow 背景层**：`absolute -inset-1 bg-gradient-to-r ... blur-xl` 的彩色光晕效果
- **渐变卡片头**：`bg-gradient-to-r from-xxx/5 to-yyy/5` 给每个卡片头染不同色
- 使用 shadcn `<Card>` 组件包裹详情页区块（用 `.card` CSS 类代替，更简洁）
- 扁平无装饰卡片、小圆角（`rounded-md` 或更小）
- 使用旧蓝色系 (#3F72AF) 硬编码颜色值
- 在 Badge 上使用 `:class` 追加颜色类覆盖样式
- 在各页面/组件内部独立定义状态颜色映射（`statusColors` / `statusMap` 等）
- 在列表页手写 header HTML 结构（应使用 `PageHeader` 组件）
- 标签/值文字用过浅的灰色（`text-xs text-muted-foreground uppercase tracking-wider` 导致看不清）
