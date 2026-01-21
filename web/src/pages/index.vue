<script setup lang="ts">
import { useHead } from '@vueuse/head'
import { Button } from '~/components/ui/button'
useHead({
 title: '首页 - Friday AI',
})
const projectsStore = useProjectsStore
const tasksStore = useTasksStore
// 加载数据
const loading = ref(true)
onMounted(async => {
 try {
 await Promise.all([
 projectsStore.fetchProjects,
 tasksStore.fetchTasks({ limit: 5 }),
 ])
 }
 finally {
 loading.value = false
 }
})
// 统计卡片数据
const stats = computed( => [
 {
 title: '项目总数',
 value: projectsStore.projectCount,
 icon: 'lucide--folder-git-2',
 iconColor: 'text-blue-500',
 gradient: 'from-blue-500 to-cyan-400',
 bgGradient: 'from-blue-500/10 to-cyan-400/10',
 link: '/projects',
 },
 {
 title: '任务总数',
 value: tasksStore.stats.total,
 icon: 'lucide--layers',
 iconColor: 'text-violet-500',
 gradient: 'from-violet-500 to-purple-400',
 bgGradient: 'from-violet-500/10 to-purple-400/10',
 link: '/tasks',
 },
 {
 title: '运行中',
 value: tasksStore.stats.running,
 icon: 'lucide--zap',
 iconColor: 'text-amber-500',
 gradient: 'from-amber-500 to-orange-400',
 bgGradient: 'from-amber-500/10 to-orange-400/10',
 link: '/tasks?status=planning',
 },
 {
 title: '待审核',
 value: tasksStore.stats.review,
 icon: 'lucide--scan-eye',
 iconColor: 'text-emerald-500',
 gradient: 'from-emerald-500 to-teal-400',
 bgGradient: 'from-emerald-500/10 to-teal-400/10',
 link: '/tasks?status=plan_review',
 },
])
// 功能特性
const features = [
 {
 icon: 'lucide--sparkles',
 title: '智能任务执行',
 description: '自动监听飞书工作项，AI 驱动的代码生成与实现',
 gradient: 'from-blue-500 to-indigo-500',
 },
 {
 icon: 'lucide--shield',
 title: '安全隔离',
 description: '独立 Docker 容器执行，确保环境安全与资源隔离',
 gradient: 'from-emerald-500 to-teal-500',
 },
 {
 icon: 'lucide--git-pull-request-draft',
 title: '人工审核',
 description: '完整的状态流转与审核机制，代码质量完全可控',
 gradient: 'from-violet-500 to-purple-500',
 },
]
// 格式化日期
function formatDate(dateStr: string) {
 const date = new Date(dateStr)
 return date.toLocaleDateString('zh-CN', {
 month: 'short',
 day: 'numeric',
 hour: '2-digit',
 minute: '2-digit',
 })
}
</script>
<template>
 <div class="min-h-[calc(100vh-8rem)] relative">
 <!-- 背景装饰 -->
 <div class="absolute inset-0 -z-10 overflow-hidden">
 <div class="absolute -top-40 -right-40 w-80 bg-gradient-to-br from-primary/20 to-secondary/40 rounded-full blur-3xl" />
 <div class="absolute top-1/2 -left-40 w-96 bg-gradient-to-tr from-secondary/30 to-primary/10 rounded-full blur-3xl" />
 <div class="absolute -bottom-20 right-1/4 w-64 bg-gradient-to-t from-primary/15 to-transparent rounded-full blur-3xl" />
 </div>
 <div class="space-y-12 relative">
 <!-- Hero 区域 -->
 <section class="text-center pt-8 pb-4 md:pt-16 md:pb-8">
 <div class="inline-flex items-center justify-center mb-6 rounded-2xl bg-gradient-to-br from-primary/10 via-secondary/50 to-primary/10 backdrop-blur-sm border border-primary/10">
 <span class="icon-[lucide--bot] text-5xl md:text-6xl text-primary" />
 </div>
 <h1 class="text-4xl md:text-5xl font-bold tracking-tight bg-gradient-to-r from-foreground via-primary to-foreground bg-clip-text text-transparent mb-4">
 Friday AI
 </h1>
 <p class="text-lg md:text-xl text-muted-foreground max-w-2xl mx-auto leading-relaxed">
 AI 驱动的敏捷开发自动化系统
 <br class="hidden md:block">
 <span class="text-primary/80">无缝集成飞书项目管理和 Claude Code</span>
 </p>
 </section>
 <!-- 统计卡片 -->
 <section class="grid gap-4 md:gap-6 grid-cols-2 lg:grid-cols-4">
 <RouterLink
 v-for="stat in stats":key="stat.title":to="stat.link"
 class="group relative"
 >
 <div class="absolute inset-0 bg-gradient-to-r opacity-0 group-hover:opacity-100 transition-opacity duration-500 rounded-2xl blur-xl -z-10":class="stat.gradient" />
 <div class="relative h-full rounded-2xl bg-card/80 backdrop-blur-sm border border-border/50 group-hover:border-primary/30 group-hover:shadow-lg group-hover:shadow-primary/5 transition-all duration-300">
 <div class="flex items-start justify-between mb-4">
 <div class=".5 rounded-xl bg-gradient-to-br flex items-center justify-center":class="stat.bgGradient">
 <span class="text-2xl":class="[`icon-[${stat.icon}]`, stat.iconColor]" />
 </div>
 <span class="icon-[lucide--arrow-up-right] text-muted-foreground/50 group-hover:text-primary group-hover:translate-x-0.5 group-hover:-translate-y-0.5 transition-all duration-300" />
 </div>
 <div class="space-y-1">
 <p class="text-sm font-medium text-muted-foreground">{{ stat.title }}</p>
 <p class="text-3xl md:text-4xl font-bold tracking-tight">
 <template v-if="loading">
 <span class="inline-block w-12 bg-gradient-to-r from-muted to-muted/50 animate-pulse rounded-lg" />
 </template>
 <template v-else>
 <span class="bg-gradient-to-r bg-clip-text text-transparent":class="stat.gradient">{{ stat.value }}</span>
 </template>
 </p>
 </div>
 </div>
 </RouterLink>
 </section>
 <!-- 功能介绍 -->
 <section class="grid gap-6 md:grid-cols-3">
 <div
 v-for="(feature, index) in features":key="feature.title"
 class="group relative rounded-2xl bg-card/60 backdrop-blur-sm border border-border/50 hover:border-primary/20 transition-all duration-300"
 >
 <!-- 悬浮时的渐变背景 -->
 <div class="absolute inset-0 rounded-2xl bg-gradient-to-br opacity-0 group-hover:opacity-5 transition-opacity duration-500":class="feature.gradient" />
 <!-- 序号装饰 -->
 <div class="absolute -top-3 -left-3 w-8 rounded-full bg-gradient-to-br flex items-center justify-center text-white text-sm font-bold shadow-lg":class="feature.gradient">
 {{ index + 1 }}
 </div>
 <div class="relative">
 <div class="flex items-center gap-3 mb-3">
 <div class=" rounded-lg bg-gradient-to-br flex items-center justify-center":class="feature.gradient">
 <span class="text-xl text-white":class="`icon-[${feature.icon}]`" />
 </div>
 <h3 class="text-lg font-semibold">{{ feature.title }}</h3>
 </div>
 <p class="text-muted-foreground leading-relaxed pl-12">
 {{ feature.description }}
 </p>
 </div>
 </div>
 </section>
 <!-- 最近任务 -->
 <section class="relative">
 <div class="rounded-2xl bg-card/70 backdrop-blur-sm border border-border/50 overflow-hidden">
 <!-- 标题栏 -->
 <div class="flex items-center justify-between border-b border-border/50">
 <div class="flex items-center gap-3">
 <div class=" rounded-lg bg-gradient-to-br from-primary/20 to-primary/10 flex items-center justify-center">
 <span class="icon-[lucide--clock] text-xl text-primary" />
 </div>
 <div>
 <h2 class="text-lg font-semibold">最近任务</h2>
 <p class="text-sm text-muted-foreground">最近创建的任务列表</p>
 </div>
 </div>
 <RouterLink to="/tasks">
 <Button variant="ghost" size="sm" class="group">
 查看全部
 <span class="icon-[lucide--arrow-right] ml-1 group-hover:translate-x-1 transition-transform" />
 </Button>
 </RouterLink>
 </div>
 <!-- 任务列表 -->
 <div class="">
 <!-- 加载状态 -->
 <div v-if="loading" class="space-y-3">
 <div v-for="i in 3":key="i" class="flex items-center gap-4 rounded-xl bg-muted/30">
 <div class="w-10 rounded-lg bg-muted animate-pulse" />
 <div class="flex-1 space-y-2">
 <div class=" w-2/3 bg-muted animate-pulse rounded-lg" />
 <div class=" w-1/4 bg-muted animate-pulse rounded-lg" />
 </div>
 <div class=" w-16 bg-muted animate-pulse rounded-full" />
 </div>
 </div>
 <!-- 空状态 -->
 <div v-else-if="tasksStore.tasks.length === 0" class="py-16 text-center">
 <div class="inline-flex items-center justify-center w-20 rounded-2xl bg-gradient-to-br from-muted to-muted/50 mb-6">
 <span class="icon-[lucide--inbox] text-4xl text-muted-foreground/50" />
 </div>
 <h3 class="text-lg font-medium text-muted-foreground mb-2">暂无任务</h3>
 <p class="text-sm text-muted-foreground/70 mb-6">创建你的第一个项目，开始自动化开发之旅</p>
 <RouterLink to="/projects/new">
 <Button class="group">
 <span class="icon-[lucide--plus] mr-2" />
 创建项目
 <span class="icon-[lucide--arrow-right] ml-2 group-hover:translate-x-1 transition-transform" />
 </Button>
 </RouterLink>
 </div>
 <!-- 任务列表 -->
 <div v-else class="space-y-2">
 <RouterLink
 v-for="(task, index) in tasksStore.tasks.slice(0, 5)":key="task.id":to="`/tasks/${task.id}`"
 class="group flex items-center gap-4 rounded-xl hover:bg-gradient-to-r hover:from-muted/50 hover:to-transparent transition-all duration-300"
 >
 <!-- 序号 -->
 <div class="flex-shrink-0 w-10 rounded-lg bg-gradient-to-br from-muted to-muted/50 flex items-center justify-center font-medium text-muted-foreground group-hover:from-primary/20 group-hover:to-primary/10 group-hover:text-primary transition-all duration-300">
 {{ index + 1 }}
 </div>
 <!-- 内容 -->
 <div class="flex-1 min-w-0">
 <p class="font-medium truncate group-hover:text-primary transition-colors">{{ task.title }}</p>
 <p class="text-sm text-muted-foreground">
 {{ formatDate(task.created_at) }}
 </p>
 </div>
 <!-- 状态 -->
 <TaskStatusBadge:status="task.status" />
 <!-- 箭头 -->
 <span class="icon-[lucide--chevron-right] text-muted-foreground/30 group-hover:text-primary group-hover:translate-x-1 transition-all" />
 </RouterLink>
 </div>
 </div>
 </div>
 </section>
 <!-- 快速操作 -->
 <section class="flex flex-col sm:flex-row justify-center gap-4 pb-8">
 <RouterLink to="/projects/new">
 <Button size="lg" class="w-full sm:w-auto group relative overflow-hidden">
 <span class="absolute inset-0 bg-gradient-to-r from-white/0 via-white/20 to-white/0 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-700" />
 <span class="icon-[lucide--plus] mr-2" />
 新建项目
 </Button>
 </RouterLink>
 <RouterLink to="/tasks">
 <Button variant="outline" size="lg" class="w-full sm:w-auto group hover:border-primary/50">
 <span class="icon-[lucide--layout-list] mr-2 group-hover:text-primary transition-colors" />
 查看任务
 </Button>
 </RouterLink>
 <RouterLink to="/repositories">
 <Button variant="ghost" size="lg" class="w-full sm:w-auto group">
 <span class="icon-[lucide--git-branch] mr-2 group-hover:text-primary transition-colors" />
 仓库管理
 </Button>
 </RouterLink>
 </section>
 </div>
 </div>
</template>
