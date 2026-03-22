# 前端设计规范 — Glassmorphism 玻璃拟态
## 核心特征
| 元素 | 类名 |
| ---------------- | -------------------------------------------------------------------- |
| 玻璃卡片 | `bg-card/80 backdrop-blur-sm border-border/50 rounded-2xl` |
| 玻璃卡片（增强） | `glass-card rounded-2xl`（使用 sub2api 风格阴影） |
| 环境光晕 | 背景用 `blur-3xl` 渐变圆形 |
| 图标容器 | `bg-gradient-to-br from-primary/20 to-primary/10 rounded-lg ` |
| 渐变文字 | `bg-gradient-to-r bg-clip-text text-transparent` |
| 悬浮效果 | `group-hover:shadow-lg group-hover:border-primary/30 transition-all` |
| Glow 光效 | `shadow-glow`（青色辉光效果） |
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
## 功能色系
- 主要：`from-teal-500 to-cyan-400`（青色系）
- 任务：`from-violet-500 to-purple-400`
- 警示：`from-amber-500 to-orange-400`
- 成功：`from-emerald-500 to-teal-400`
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
 icon-gradient="from-blue-500/20 to-cyan-500/10"
 icon-color="text-blue-500"
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
- 扁平无装饰卡片、小圆角（`rounded-md` 或更小）
- 单调 hover 效果（仅变色，无阴影/光效）
- 使用旧蓝色系 (#3F72AF) 硬编码颜色值
- 在 Badge 上使用 `:class` 追加颜色类覆盖样式
- 在各页面/组件内部独立定义状态颜色映射（`statusColors` / `statusMap` 等）
- 在列表页手写 header HTML 结构（应使用 `PageHeader` 组件）
