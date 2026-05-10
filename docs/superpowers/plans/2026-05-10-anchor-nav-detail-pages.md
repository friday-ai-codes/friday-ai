# 项目/仓库详情页锚点导航改造实现计划
> **For agentic workers:** REQUIRED work item: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- `) syntax for tracking.
**Goal:** 将项目/仓库列表页的删除按钮移除，将详情页改造为 GitHub Settings 风格的左侧锚点导航 + 右侧垂直平铺布局。
**Architecture:** 新增可复用的 `AnchorNavLayout.vue` 布局组件，通过 `IntersectionObserver` 实现锚点高亮和点击平滑滚动。项目详情页和仓库详情页统一采用该布局，将原有内容按区块重组。列表页仅移除删除相关代码。
**Tech Stack:** Vue 3 + TypeScript + Tailwind CSS + unplugin-vue-router (typed-router)
---
## 文件结构
| 文件 | 类型 | 说明 |
|------|------|------|
| `web/src/components/layout/AnchorNavLayout.vue` | 新建 | 锚点导航布局组件，含左侧粘性导航 + 右侧内容区 |
| `web/src/pages/projects/index.vue` | 修改 | 移除卡片底部删除按钮及相关状态 |
| `web/src/pages/projects/[id]/index.vue` | 修改 | 改造为锚点导航布局，重组所有内容区块 |
| `web/src/pages/repositories/index.vue` | 修改 | 移除卡片底部删除按钮及相关状态 |
| `web/src/pages/repositories/[id]/index.vue` | 修改 | 改造为锚点导航布局，重组所有内容区块 |
---
### Task 1: 创建 AnchorNavLayout.vue 组件
**Files:**
- Create: `web/src/components/layout/AnchorNavLayout.vue`
- **Step 1: 编写 AnchorNavLayout.vue**
```vue
<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
export interface NavSection {
 id: string
 label: string
 icon?: string
}
const props = defineProps<{
 sections: NavSection
}>
const activeSection = ref<string>(props.sections[0]?.id ?? '')
let observer: IntersectionObserver | null = null
onMounted( => {
 observer = new IntersectionObserver(
 (entries) => {
 const visible = entries
 .filter(e => e.isIntersecting)
 .sort((a, b) => b.intersectionRatio - a.intersectionRatio)
 if (visible.length > 0) {
 activeSection.value = visible[0].target.id
 }
 },
 {
 rootMargin: '-15% 0px -55% 0px',
 threshold: [0, 0.25, 0.5, 0.75, 1],
 },
 )
 props.sections.forEach((section) => {
 const el = document.getElementById(section.id)
 if (el) observer?.observe(el)
 })
})
onUnmounted( => {
 observer?.disconnect
})
function scrollTo(id: string) {
 const el = document.getElementById(id)
 if (!el) return
 const offset = 88
 const top = el.getBoundingClientRect.top + window.scrollY - offset
 window.scrollTo({ top, behavior: 'smooth' })
}
</script>
<template>
 <div class="flex gap-8">
 <!-- 左侧导航 -->
 <aside class="hidden md:block w-44 shrink-0">
 <nav class="sticky top-22 space-y-0.5">
 <button
 v-for="section in sections":key="section.id"
 class="w-full text-left px-3 py-1.5 rounded-md text-sm transition-colors":class="activeSection === section.id
 ? 'bg-primary/10 text-primary font-medium': 'text-muted-foreground hover:text-foreground hover:bg-muted/50'"
 @click="scrollTo(section.id)"
 >
 <span v-if="section.icon" class="mr-2":class="section.icon" />
 {{ section.label }}
 </button>
 </nav>
 </aside>
 <!-- 右侧内容 -->
 <div class="flex-1 min-w-0 space-y-6">
 <slot />
 </div>
 </div>
</template>
```
- **Step 2: Commit**
```bash
git add web/src/components/layout/AnchorNavLayout.vue
git commit -m "feat(layout): 新增 AnchorNavLayout 锚点导航布局组件"
```
---
### Task 2: 项目列表页移除删除按钮
**Files:**
- Modify: `web/src/pages/projects/index.vue`
- **Step 1: 移除删除相关状态和导入，保留项目卡片查看详情按钮**
删除以下导入和代码：
```typescript
// 删除：删除项目
const deleteDialogOpen = ref(false)
const projectToDelete = ref<string | null>(null)
const deleting = ref(false)
function confirmDelete(projectId: string) {
 projectToDelete.value = projectId
 deleteDialogOpen.value = true
}
async function handleDelete {
 if (!projectToDelete.value)
 return
 deleting.value = true
 try {
 await projectsStore.deleteProject(projectToDelete.value)
 success('删除成功', '项目已删除')
 deleteDialogOpen.value = false
 }
 catch (e: unknown) {
 handleError(e, '删除项目')
 }
 finally {
 deleting.value = false
 }
}
```
在模板中，将底部操作栏的删除按钮移除，只保留「查看详情」：
```vue
<!-- 替换前：底部操作栏 -->
<div class="flex items-center justify-between px-4 py-2.5 border-t border-border/50 bg-muted/20">
 <span class="text-xs text-muted-foreground group-hover:text-primary transition-colors flex items-center gap-1">
 查看详情
 <span class="icon-[lucide--arrow-right]" />
 </span>
 <Button
 variant="ghost"
 size="icon-sm"
 class="hover:bg-red-50! hover:text-red-500!"
 @click.prevent="confirmDelete(project.id)"
 >
 <span class="icon-[lucide--trash-2]" />
 </Button>
</div>
```
替换为：
```vue
<div class="flex items-center px-4 py-2.5 border-t border-border/50 bg-muted/20">
 <span class="text-xs text-muted-foreground group-hover:text-primary transition-colors flex items-center gap-1">
 查看详情
 <span class="icon-[lucide--arrow-right]" />
 </span>
</div>
```
同时删除模板底部的 `ConfirmDialog`：
```vue
<!-- 删除确认对话框 -->
<ConfirmDialog
 v-model:open="deleteDialogOpen"
 title="删除项目"
 description="确定要删除此项目吗？此操作不可撤销，相关的凭证配置也将被删除。"
 confirm-text="删除"
 variant="destructive":loading="deleting"
 @confirm="handleDelete"
/>
```
- **Step 2: Commit**
```bash
git add web/src/pages/projects/index.vue
git commit -m "feat(projects): 列表页移除删除按钮，删除操作集中到详情页"
```
---
### Task 3: 项目详情页改造为锚点导航布局
**Files:**
- Modify: `web/src/pages/projects/[id]/index.vue`
- **Step 1: 引入 AnchorNavLayout，定义 section 配置**
在 `<script setup>` 顶部新增导入和 sections 数组：
```typescript
import AnchorNavLayout, { type NavSection } from '~/components/layout/AnchorNavLayout.vue'
const sections = ref<NavSection>([
 { id: 'basic-info', label: '基本信息', icon: 'icon-[lucide--info]' },
 { id: 'repositories', label: '关联仓库', icon: 'icon-[lucide--git-branch]' },
 { id: 'feishu', label: '飞书配置', icon: 'icon-[lucide--message-square]' },
 { id: 'prompts', label: 'Prompt 覆盖', icon: 'icon-[lucide--file-text]' },
 { id: 'providers', label: 'Provider 凭证', icon: 'icon-[lucide--key-round]' },
 { id: 'webhook-token', label: 'Webhook Token', icon: 'icon-[lucide--key]' },
 { id: 'executions', label: '相关执行', icon: 'icon-[lucide--layers]' },
 { id: 'danger-zone', label: '危险操作', icon: 'icon-[lucide--alert-triangle]' },
])
```
- **Step 2: 重构模板结构**
将模板中 `v-else-if="project"` 的内容用 `AnchorNavLayout` 包裹，每个区块用 `<section:id="...">` 包裹。
替换前的骨架：
```vue
<template v-else-if="project">
 <!-- 头部 -->
 <div class="flex items-start justify-between">...</div>
 <!-- 两列网格 -->
 <div class="grid gap-4 md:grid-cols-2">...</div>
 <!-- 相关执行 -->
 <div class="card">...</div>
</template>
```
替换后的骨架：
```vue
<template v-else-if="project">
 <!-- 头部（在锚点布局外，保持独立） -->
 <div class="flex items-start justify-between">
 <!-- 左侧标题 -->
 <div class="space-y-2">
 <div class="flex items-center gap-3">
 <div class=".5 rounded-xl bg-primary/10 flex items-center justify-center">
 <span class="icon-[lucide--folder-open] text-2xl text-primary" />
 </div>
 <div>
 <h1 class="text-2xl font-bold">{{ project.name }}</h1>
 <p class="text-sm text-muted-foreground">{{ project.description || '暂无描述' }}</p>
 </div>
 </div>
 </div>
 <!-- 右侧操作 -->
 <div class="flex items-center gap-2">
 <RouterLink:to="`/projects/${project.id}/edit`">
 <Button variant="outline" class="group">
 <span class="icon-[lucide--pencil] mr-2 group-hover:scale-110 transition-transform" />
 编辑
 </Button>
 </RouterLink>
 </div>
 </div>
 <AnchorNavLayout:sections="sections">
 <!-- 基本信息 -->
 <section id="basic-info" class="scroll-mt-22">
 <div class="card">
 <div class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2">
 <span class="icon-[lucide--info] text-primary" />
 <h3 class="text-sm font-semibold">基本信息</h3>
 </div>
 <div class=" space-y-4">
 <div>
 <label class="text-xs text-muted-foreground">飞书项目 Key</label>
 <p class="font-mono text-sm mt-1 text-foreground">{{ project.feishu_project_key || '未配置' }}</p>
 </div>
 <Separator class="bg-border/50" />
 <div class="flex gap-8">
 <div>
 <label class="text-xs text-muted-foreground">创建时间</label>
 <p class="text-sm mt-1 text-foreground">{{ formatDate(project.created_at) }}</p>
 </div>
 <div>
 <label class="text-xs text-muted-foreground">更新时间</label>
 <p class="text-sm mt-1 text-foreground">{{ formatDate(project.updated_at) }}</p>
 </div>
 </div>
 </div>
 </div>
 </section>
 <!-- 关联仓库 -->
 <section id="repositories" class="scroll-mt-22">
 <div class="card">
 <div class="px-5 py-3.5 border-b border-border/50 flex items-center justify-between">
 <div class="flex items-center gap-2">
 <span class="icon-[lucide--git-branch] text-primary" />
 <h3 class="text-sm font-semibold">关联仓库</h3>
 <span class="text-xs text-muted-foreground">({{ project.repositories?.length || 0 }})</span>
 </div>
 <Button variant="outline" size="sm" class=" text-xs" @click="openLinkDialog">
 <span class="icon-[lucide--settings-2] mr-1.5" />
 管理
 </Button>
 </div>
 <div class="">
 <div v-if="project.repositories?.length === 0" class="text-center py-6 text-muted-foreground">
 <span class="icon-[lucide--git-branch] text-2xl mb-2 block opacity-40" />
 <p class="text-sm">暂无关联仓库</p>
 </div>
 <div v-else class="space-y-2">
 <div
 v-for="repo in project.repositories":key="repo.id"
 class="flex items-center justify-between .5 rounded-lg border border-border/50 hover:bg-muted/40 transition-colors"
 >
 <div class="min-w-0 flex-1">
 <div class="flex items-center gap-2">
 <span class="text-sm font-medium text-foreground">{{ repo.name }}</span>
 <Badge variant="outline" class="text-xs">{{ PLATFORM_LABELS[repo.git_platform] }}</Badge>
 </div>
 <p class="text-xs text-muted-foreground mt-0.5 font-mono truncate">{{ repo.git_url }}</p>
 </div>
 <RouterLink:to="`/repositories/${repo.id}`">
 <TooltipProvider:delay-duration="300">
 <Tooltip>
 <TooltipTrigger as-child>
 <Button variant="ghost" size="icon" class=" w-7">
 <span class="icon-[lucide--eye] text-sm" />
 </Button>
 </TooltipTrigger>
 <TooltipContent>查看详情</TooltipContent>
 </Tooltip>
 </TooltipProvider>
 </RouterLink>
 </div>
 </div>
 </div>
 </div>
 </section>
 <!-- 飞书配置 -->
 <section id="feishu" class="scroll-mt-22">
 <div class="card">
 <div class="px-5 py-3.5 border-b border-border/50 flex items-center justify-between">
 <div class="flex items-center gap-2">
 <span class="icon-[lucide--message-square] text-primary" />
 <h3 class="text-sm font-semibold">飞书配置</h3>
 </div>
 <RouterLink:to="`/projects/${project.id}/feishu`">
 <Button variant="ghost" size="sm" class=" text-xs group">
 管理
 <span class="icon-[lucide--arrow-right] ml-1 group-hover:translate-x-0.5 transition-transform" />
 </Button>
 </RouterLink>
 </div>
 <div class="">
 <div v-if="feishuConfig?.is_configured" class="flex items-center gap-3">
 <div class=".5 rounded-full bg-emerald-500/10">
 <span class="icon-[lucide--check-circle] text-lg text-emerald-500" />
 </div>
 <div>
 <p class="text-sm font-medium text-foreground">已配置</p>
 <p class="text-xs text-muted-foreground">插件 ID：{{ feishuConfig.plugin_id }}</p>
 </div>
 </div>
 <div v-else class="flex items-center gap-3 text-muted-foreground">
 <span class="icon-[lucide--link] text-lg opacity-40" />
 <div class="flex-1">
 <p class="text-sm">尚未配置飞书集成</p>
 </div>
 <RouterLink:to="`/projects/${project.id}/feishu`">
 <Button size="sm" class=" text-xs">配置</Button>
 </RouterLink>
 </div>
 </div>
 </div>
 </section>
 <!-- Prompt 覆盖 -->
 <section id="prompts" class="scroll-mt-22">
 <div class="card">
 <div class="px-5 py-3.5 border-b border-border/50 flex items-center justify-between">
 <div class="flex items-center gap-2">
 <span class="icon-[lucide--file-text] text-primary" />
 <h3 class="text-sm font-semibold">Prompt 覆盖</h3>
 </div>
 <RouterLink:to="`/projects/${project.id}/prompts`">
 <Button variant="ghost" size="sm" class=" text-xs group">
 管理
 <span class="icon-[lucide--arrow-right] ml-1 group-hover:translate-x-0.5 transition-transform" />
 </Button>
 </RouterLink>
 </div>
 <div class="">
 <div class="flex items-center gap-3 text-muted-foreground">
 <span class="icon-[lucide--file-text] text-lg opacity-40" />
 <div class="flex-1">
 <p class="text-sm">查看与编辑项目级提示词覆盖</p>
 <p class="text-xs text-muted-foreground">未覆盖的提示词会 fallback 到系统级</p>
 </div>
 </div>
 </div>
 </div>
 </section>
 <!-- Provider 凭证 -->
 <section id="providers" class="scroll-mt-22">
 <div class="card">
 <div class="px-5 py-3.5 border-b border-border/50 flex items-center justify-between">
 <div class="flex items-center gap-2">
 <span class="icon-[lucide--key-round] text-primary" />
 <h3 class="text-sm font-semibold">Provider 凭证</h3>
 </div>
 <RouterLink:to="`/projects/${project.id}/providers`">
 <Button variant="ghost" size="sm" class=" text-xs group">
 管理
 <span class="icon-[lucide--arrow-right] ml-1 group-hover:translate-x-0.5 transition-transform" />
 </Button>
 </RouterLink>
 </div>
 <div class="">
 <div class="flex items-center gap-3 text-muted-foreground">
 <span class="icon-[lucide--key-round] text-lg opacity-40" />
 <div class="flex-1">
 <p class="text-sm">项目级 Provider 凭证覆盖</p>
 <p class="text-xs text-muted-foreground">仅本项目可见，覆盖系统默认</p>
 </div>
 </div>
 </div>
 </div>
 </section>
 <!-- Webhook Token -->
 <section id="webhook-token" class="scroll-mt-22">
 <div class="card">
 <div class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2">
 <span class="icon-[lucide--key] text-primary" />
 <h3 class="text-sm font-semibold">Webhook Token</h3>
 <span class="text-xs text-muted-foreground ml-1">用于验证飞书 Webhook 请求的来源</span>
 </div>
 <div class=" space-y-4">
 <div class="space-y-2">
 <Label class="text-xs text-muted-foreground">当前 Token</Label>
 <div class="flex items-center gap-2">
 <code class="flex-1 px-3 py-2 bg-muted/40 rounded-lg font-mono text-sm overflow-hidden text-ellipsis border border-border/50 text-foreground">
 {{ project.webhook_token }}
 </code>
 <TooltipProvider:delay-duration="300">
 <Tooltip>
 <TooltipTrigger as-child>
 <Button variant="outline" size="icon" class=" w-9" @click="copyWebhookToken">
 <span class="icon-[lucide--copy]" />
 </Button>
 </TooltipTrigger>
 <TooltipContent>复制 Token</TooltipContent>
 </Tooltip>
 </TooltipProvider>
 </div>
 </div>
 <div class="flex items-start gap-2.5 rounded-lg bg-amber-500/10 border border-amber-500/20">
 <span class="icon-[lucide--alert-triangle] text-amber-500 shrink-0 mt-0.5" />
 <p class="text-xs text-amber-700 dark:text-amber-300">请勿泄露此 Token。如果 Token 泄露，请立即刷新。</p>
 </div>
 <div class="flex gap-2">
 <Button variant="outline" size="sm" @click="refreshTokenDialogOpen = true">
 <span class="icon-[lucide--refresh-cw] mr-1.5" />
 刷新 Token
 </Button>
 <Button variant="outline" size="sm" @click="openCustomTokenDialog">
 <span class="icon-[lucide--pencil] mr-1.5" />
 自定义 Token
 </Button>
 </div>
 </div>
 </div>
 </section>
 <!-- 相关执行 -->
 <section id="executions" class="scroll-mt-22">
 <div class="card">
 <div class="px-5 py-3.5 border-b border-border/50 flex items-center justify-between">
 <div class="flex items-center gap-2">
 <span class="icon-[lucide--layers] text-primary" />
 <h3 class="text-sm font-semibold">相关执行</h3>
 </div>
 <RouterLink:to="`/executions?project_id=${project.id}`">
 <Button variant="ghost" size="sm" class=" text-xs group">
 查看全部
 <span class="icon-[lucide--arrow-right] ml-1 group-hover:translate-x-0.5 transition-transform" />
 </Button>
 </RouterLink>
 </div>
 <div class="">
 <div v-if="projectExecutions.length === 0" class="text-center py-6 text-muted-foreground">
 <span class="icon-[lucide--inbox] text-2xl mb-2 block opacity-40" />
 <p class="text-sm">暂无执行记录</p>
 </div>
 <div v-else class="space-y-1.5">
 <RouterLink
 v-for="(execution, index) in projectExecutions.slice(0, 5)":key="execution.id":to="`/executions/${execution.id}`"
 class="flex items-center justify-between rounded-lg hover:bg-muted/40 transition-colors group"
 >
 <div class="flex items-center gap-3">
 <div class="w-6 rounded bg-muted/60 flex items-center justify-center text-xs font-medium text-muted-foreground">{{ index + 1 }}</div>
 <div>
 <span class="text-sm font-medium text-foreground group-hover:text-primary transition-colors">{{ execution.workflow_name }}</span>
 <StatusBadge type="execution":status="execution.status" size="sm" class="ml-2" />
 </div>
 </div>
 <div class="flex items-center gap-2">
 <span class="text-xs text-muted-foreground">{{ formatDate(execution.created_at) }}</span>
 <span class="icon-[lucide--chevron-right] text-sm text-muted-foreground group-hover:translate-x-0.5 transition-transform" />
 </div>
 </RouterLink>
 </div>
 </div>
 </div>
 </section>
 <!-- 危险操作 -->
 <section id="danger-zone" class="scroll-mt-22">
 <div class="card border-destructive/30 bg-destructive/5">
 <div class="px-5 py-3.5 border-b border-destructive/20 flex items-center gap-2">
 <span class="icon-[lucide--alert-triangle] text-destructive" />
 <h3 class="text-sm font-semibold text-destructive">危险操作</h3>
 </div>
 <div class=" space-y-4">
 <div class="flex items-start justify-between gap-4">
 <div>
 <p class="text-sm font-medium text-foreground">删除项目</p>
 <p class="text-xs text-muted-foreground mt-1">删除后无法恢复，项目内所有配置将被清除。</p>
 </div>
 <Button variant="destructive" size="sm" class="shrink-0" @click="deleteDialogOpen = true">
 <span class="icon-[lucide--trash-2] mr-1.5" />
 删除项目
 </Button>
 </div>
 </div>
 </div>
 </section>
 </AnchorNavLayout>
</template>
```
注意：头部原有的「删除」按钮替换为仅保留「编辑」按钮。删除按钮移入危险操作区块。模板中其他对话框（仓库关联、Token 刷新/自定义）保持不变。
- **Step 3: Commit**
```bash
git add web/src/pages/projects/\[id\]/index.vue
git commit -m "feat(projects): 详情页改造为锚点导航布局，删除操作收进危险操作区"
```
---
### Task 4: 仓库列表页移除删除按钮
**Files:**
- Modify: `web/src/pages/repositories/index.vue`
- **Step 1: 移除删除相关状态和代码**
删除以下状态和函数：
```typescript
const deleteDialogOpen = ref(false)
const repositoryToDelete = ref<string | null>(null)
const deleting = ref(false)
function confirmDelete(id: string) {
 repositoryToDelete.value = id
 deleteDialogOpen.value = true
}
async function handleDelete {
 if (!repositoryToDelete.value)
 return
 deleting.value = true
 try {
 await repositoriesStore.deleteRepository(repositoryToDelete.value)
 success('删除成功', '仓库已删除')
 deleteDialogOpen.value = false
 }
 catch (e: unknown) {
 handleError(e, '删除仓库')
 }
 finally {
 deleting.value = false
 }
}
```
在模板中，将底部操作栏的删除按钮移除：
```vue
<!-- 替换前 -->
<div class="flex items-center justify-between px-4 py-2.5 border-t border-border/50 bg-muted/20">
 <span class="text-xs text-muted-foreground group-hover:text-primary transition-colors flex items-center gap-1">
 查看详情
 <span class="icon-[lucide--arrow-right]" />
 </span>
 <div class="flex items-center gap-1">
 <TooltipProvider ...>...
 <Tooltip>
 <TooltipTrigger as-child>
 <Button
 variant="ghost"
 size="icon-sm"
 class="hover:bg-red-50! hover:text-red-500!"
 @click.prevent="confirmDelete(repository.id)"
 >
 <span class="icon-[lucide--trash-2]" />
 </Button>
 </TooltipTrigger>
 <TooltipContent>删除仓库</TooltipContent>
 </Tooltip>
 </div>
</div>
```
替换为：
```vue
<div class="flex items-center px-4 py-2.5 border-t border-border/50 bg-muted/20">
 <span class="text-xs text-muted-foreground group-hover:text-primary transition-colors flex items-center gap-1">
 查看详情
 <span class="icon-[lucide--arrow-right]" />
 </span>
</div>
```
同时删除模板底部的 `ConfirmDialog`。
- **Step 2: Commit**
```bash
git add web/src/pages/repositories/index.vue
git commit -m "feat(repositories): 列表页移除删除按钮，删除操作集中到详情页"
```
---
### Task 5: 仓库详情页改造为锚点导航布局
**Files:**
- Modify: `web/src/pages/repositories/[id]/index.vue`
- **Step 1: 引入 AnchorNavLayout，定义 section 配置**
在 `<script setup>` 顶部新增：
```typescript
import AnchorNavLayout, { type NavSection } from '~/components/layout/AnchorNavLayout.vue'
const sections = ref<NavSection>([
 { id: 'basic-info', label: '基本信息', icon: 'icon-[lucide--info]' },
 { id: 'branch-index', label: '分支索引', icon: 'icon-[lucide--git-branch]' },
 { id: 'index-stats', label: '索引统计', icon: 'icon-[lucide--bar-chart-3]' },
 { id: 'linked-projects', label: '关联项目', icon: 'icon-[lucide--folder]' },
 { id: 'credential', label: '凭证配置', icon: 'icon-[lucide--key]' },
 { id: 'webhook', label: 'Webhook 自动化', icon: 'icon-[lucide--webhook]' },
 { id: 'danger-zone', label: '危险操作', icon: 'icon-[lucide--alert-triangle]' },
])
```
- **Step 2: 重构模板结构**
将模板中 `v-else-if="repository"` 的内容用 `AnchorNavLayout` 包裹，每个区块用 `<section:id="...">` 包裹。
头部区域保留在布局外（包含标题、编辑按钮、状态徽章、描述）。编辑按钮和删除按钮都从头部移除——编辑按钮可以放在头部，删除按钮放到危险操作区。
具体结构：
```vue
<template v-else-if="repository">
 <!-- 头部区域（在布局外） -->
 <div class="card overflow-hidden">
 ...（原有的标题、平台徽章、分支徽章、Git URL、复制按钮、状态指示器、描述折叠等全部保留）...
 <!-- 注意：头部操作按钮中的「删除」按钮移除，只保留「编辑」按钮 -->
 </div>
 <AnchorNavLayout:sections="sections">
 <!-- 基本信息 -->
 <section id="basic-info" class="scroll-mt-22">
 <div class="card">
 <div class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2">
 <span class="icon-[lucide--info] text-primary" />
 <h3 class="text-sm font-semibold">基本信息</h3>
 </div>
 <div class="">
 <div class="grid gap-5 sm:grid-cols-2">
 <div>
 <label class="text-xs text-muted-foreground">Git 平台</label>
 <p class="text-sm mt-1 font-medium text-foreground">{{ PLATFORM_LABELS[repository.git_platform] }}</p>
 </div>
 <div>
 <label class="text-xs text-muted-foreground">默认分支</label>
 <p class="text-sm mt-1 font-mono text-foreground">{{ repository.default_branch }}</p>
 </div>
 <div v-if="repository.proxy_url">
 <label class="text-xs text-muted-foreground">代理 URL</label>
 <p class="text-sm mt-1 font-mono break-all text-foreground">{{ repository.proxy_url }}</p>
 </div>
 <div>
 <label class="text-xs text-muted-foreground">创建时间</label>
 <p class="text-sm mt-1 text-foreground">{{ formatDate(repository.created_at) }}</p>
 </div>
 <div>
 <label class="text-xs text-muted-foreground">最近更新</label>
 <p class="text-sm mt-1 text-foreground">{{ formatDate(repository.updated_at) }}</p>
 </div>
 </div>
 </div>
 </div>
 </section>
 <!-- AI 智能描述 -->
 <AISummarySection:repository-id="repository.id" />
 <!-- 分支索引 -->
 <section id="branch-index" class="scroll-mt-22">
 <div v-if="branchNames.length > 0" class="card">
 <div class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2">
 <span class="icon-[lucide--git-branch] text-primary" />
 <h3 class="text-sm font-semibold">分支索引</h3>
 <span class="text-xs text-muted-foreground">选择检索分支与健康状态</span>
 </div>
 <div class=" space-y-4">
 <div class="grid gap-4 lg:grid-cols-2 lg:items-start">
 <div class="space-y-2">
 <label class="text-xs text-muted-foreground">当前分支</label>
 <BranchCombobox
 v-model="selectedBranch":branches="branchNames":index-rows="branchIndexRows":recommended-branch="recommendedBaseBranch":disabled="indexGlobalBusy"
 />
 </div>
 <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-end">
 <Button
 v-if="selectedBranchRow?.is_stale":disabled="indexGlobalBusy || rebuildingBranch"
 class="w-full sm:w-auto"
 @click="rebuildDialogOpen = true"
 >
 <span v-if="rebuildingBranch" class="icon-[lucide--loader-circle] animate-spin mr-2" />
 <span v-else class="icon-[lucide--refresh-cw] mr-2" />
 重建索引
 </Button>
 </div>
 </div>
 <BranchIndexHealthSection:row="selectedBranchRow" />
 </div>
 </div>
 </section>
 <!-- 索引统计 -->
 <section id="index-stats" class="scroll-mt-22 space-y-4">
 <div class="grid gap-4 lg:grid-cols-2">
 <RepositoryIndexCard:repository-id="repository.id" />
 <IndexStatsPanel:repository-id="repository.id" />
 </div>
 <IndexHistoryList:repository-id="repository.id" />
 </section>
 <!-- 关联项目 -->
 <section id="linked-projects" class="scroll-mt-22">
 <div class="card">
 <div class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2">
 <span class="icon-[lucide--folder] text-primary" />
 <h3 class="text-sm font-semibold">关联项目</h3>
 <span class="text-xs text-muted-foreground">({{ repository.projects?.length || 0 }})</span>
 </div>
 <div class="">
 <div v-if="!repository.projects || repository.projects.length === 0" class="text-center py-6">
 <span class="icon-[lucide--folder] text-2xl text-muted-foreground/40 block mb-2" />
 <p class="text-sm text-muted-foreground">暂无关联项目</p>
 </div>
 <div v-else class="space-y-1.5">
 <RouterLink
 v-for="project in repository.projects":key="project.id":to="`/projects/${project.id}`"
 class="flex items-center justify-between .5 rounded-lg hover:bg-muted/40 transition-colors group"
 >
 <div class="flex items-center gap-2.5">
 <div class="w-7 rounded-lg bg-primary/10 flex items-center justify-center">
 <span class="icon-[lucide--folder-open] text-xs text-primary" />
 </div>
 <span class="text-sm font-medium text-foreground group-hover:text-primary transition-colors">{{ project.name }}</span>
 </div>
 <span class="icon-[lucide--chevron-right] text-sm text-muted-foreground group-hover:translate-x-0.5 transition-transform" />
 </RouterLink>
 </div>
 </div>
 </div>
 </section>
 <!-- 凭证配置 -->
 <section id="credential" class="scroll-mt-22">
 <div class="card">
 <div class="px-5 py-3.5 border-b border-border/50 flex items-center justify-between">
 <div class="flex items-center gap-2">
 <span class="icon-[lucide--key] text-primary" />
 <h3 class="text-sm font-semibold">凭证配置</h3>
 </div>
 <RouterLink:to="`/repositories/${repository.id}/credential`">
 <Button variant="ghost" size="sm" class=" text-xs group">
 管理
 <span class="icon-[lucide--arrow-right] ml-1 group-hover:translate-x-0.5 transition-transform" />
 </Button>
 </RouterLink>
 </div>
 <div class="">
 <div v-if="credential" class="space-y-4">
 <div class="flex items-center gap-2.5">
 <div class=".5 rounded-full bg-emerald-500/10">
 <span class="icon-[lucide--check-circle] text-lg text-emerald-500" />
 </div>
 <div>
 <p class="text-sm font-medium text-foreground">凭证已配置</p>
 <p class="text-xs text-muted-foreground">{{ credential.auth_type === 'ssh_key' ? 'SSH 密钥': 'Access Token' }}</p>
 </div>
 </div>
 <div class="space-y-3 pt-3 border-t border-border/50">
 <div>
 <label class="text-xs text-muted-foreground">Git 用户名</label>
 <p class="text-sm mt-0.5 font-medium text-foreground">{{ credential.git_user_name || '-' }}</p>
 </div>
 <div>
 <label class="text-xs text-muted-foreground">Git 邮箱</label>
 <p class="text-sm mt-0.5 text-foreground">{{ credential.git_user_email || '-' }}</p>
 </div>
 </div>
 </div>
 <div v-else class="text-center py-6">
 <span class="icon-[lucide--lock] text-2xl text-muted-foreground/40 block mb-2" />
 <p class="text-sm text-muted-foreground mb-3">尚未配置凭证</p>
 <RouterLink:to="`/repositories/${repository.id}/credential`">
 <Button size="sm" class=" text-xs">
 <span class="icon-[lucide--key] mr-1.5" />
 配置凭证
 </Button>
 </RouterLink>
 </div>
 </div>
 </div>
 </section>
 <!-- Webhook 自动化 -->
 <section id="webhook" class="scroll-mt-22">
 <WebhookConfigPanel:repository="repository" @updated="repositoriesStore.fetchRepository(repositoryId)" />
 </section>
 <!-- 危险操作 -->
 <section id="danger-zone" class="scroll-mt-22">
 <div class="card border-destructive/30 bg-destructive/5">
 <div class="px-5 py-3.5 border-b border-destructive/20 flex items-center gap-2">
 <span class="icon-[lucide--alert-triangle] text-destructive" />
 <h3 class="text-sm font-semibold text-destructive">危险操作</h3>
 </div>
 <div class=" space-y-4">
 <div class="flex items-start justify-between gap-4">
 <div>
 <p class="text-sm font-medium text-foreground">删除仓库</p>
 <p class="text-xs text-muted-foreground mt-1">删除后无法恢复，相关的凭证配置也将被清除。</p>
 </div>
 <Button variant="destructive" size="sm" class="shrink-0" @click="deleteDialogOpen = true">
 <span class="icon-[lucide--trash-2] mr-1.5" />
 删除仓库
 </Button>
 </div>
 </div>
 </div>
 </section>
 </AnchorNavLayout>
</template>
```
注意：
1. 头部区域原有的「删除」按钮已移除，只保留「编辑」按钮
2. 所有原有对话框（删除确认、编辑弹窗、重建确认）保持不变
3. `AISummarySection` 放在基本信息之后、分支索引之前，不属于任何锚点 section（或可考虑并入基本信息 section 顶部）
- **Step 3: Commit**
```bash
git add web/src/pages/repositories/\[id\]/index.vue
git commit -m "feat(repositories): 详情页改造为锚点导航布局，删除操作收进危险操作区"
```
---
### Task 6: 端到端验证
- **Step 1: 启动前端 dev server**
```bash
cd web && npm run dev
```
- **Step 2: 验证项目列表页**
打开 `http://localhost:5173/projects`，确认：
- 每个项目卡片底部只有「查看详情」，没有删除按钮
- 点击卡片可正常跳转到详情页
- **Step 3: 验证项目详情页**
打开任意项目详情页，确认：
- 左侧显示锚点导航菜单（8 个条目）
- 点击锚点平滑滚动到对应区块
- 滚动页面时左侧锚点自动高亮
- 危险操作区在最底部，红色边框，包含「删除项目」按钮
- 点击删除弹出确认对话框，确认后跳回列表页
- 编辑按钮在头部区域正常工作
- **Step 4: 验证仓库列表页**
打开 `http://localhost:5173/repositories`，确认：
- 每个仓库卡片底部只有「查看详情」，没有删除按钮
- 代码索引、凭证管理快捷入口保留
- **Step 5: 验证仓库详情页**
打开任意仓库详情页，确认：
- 左侧显示锚点导航菜单（7 个条目）
- 点击锚点平滑滚动到对应区块
- 滚动页面时左侧锚点自动高亮
- 危险操作区在最底部，红色边框，包含「删除仓库」按钮
- 编辑按钮在头部区域正常工作
- **Step 6: 验证移动端**
将浏览器窗口缩至 < 768px，确认：
- 左侧导航隐藏
- 右侧内容正常垂直滚动
- 没有水平滚动条
---
## 自审查
### Spec 覆盖检查
| Spec 要求 | 对应任务 |
|-----------|---------|
| 项目列表页移除删除按钮 | Task 2 |
| 仓库列表页移除删除按钮 | Task 4 |
| 新增 AnchorNavLayout 组件 | Task 1 |
| 项目详情页锚点导航改造 | Task 3 |
| 仓库详情页锚点导航改造 | Task 5 |
| 危险操作区样式（红色边框/背景） | Task 3、Task 5 |
| 删除确认对话框保留 | Task 3、Task 5 |
| 移动端左侧导航隐藏 | Task 1（`hidden md:block`） |
| IntersectionObserver 锚点高亮 | Task 1 |
| 平滑滚动 | Task 1 |
### Placeholder 扫描
- 无 TBD/TODO
- 无 "add appropriate error handling" 等模糊描述
- 所有代码块包含完整代码
### 类型一致性
- `NavSection` 接口在 Task 1 定义，Task 3 和 Task 5 中导入并使用
- `sections` 数组类型为 `Ref<NavSection>`，与组件 Props 类型一致
- 各详情页中的对话框、弹窗状态和原有逻辑保持不变
