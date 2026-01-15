<script setup lang="ts">
import { useHead } from '@vueuse/head'
import { Button } from '~/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '~/components/ui/card'
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
 color: 'text-blue-600',
 link: '/projects',
 },
 {
 title: '任务总数',
 value: tasksStore.stats.total,
 icon: 'lucide--list-checks',
 color: 'text-purple-600',
 link: '/tasks',
 },
 {
 title: '运行中',
 value: tasksStore.stats.running,
 icon: 'lucide--loader-circle',
 color: 'text-orange-600',
 link: '/tasks?status=planning',
 },
 {
 title: '待审核',
 value: tasksStore.stats.review,
 icon: 'lucide--eye',
 color: 'text-yellow-600',
 link: '/tasks?status=plan_review',
 },
])
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
 <div class="space-y-8">
 <!-- Hero 区域 -->
 <section class="text-center py-8 md:py-12">
 <div class="flex items-center justify-center gap-3 mb-4">
 <span class="icon-[lucide--bot] text-4xl md:text-5xl text-primary" />
 <h1 class="text-3xl md:text-4xl font-bold tracking-tight">
 Friday AI
 </h1>
 </div>
 <p class="text-lg md:text-xl text-muted-foreground max-w-2xl mx-auto">
 AI 驱动的敏捷开发自动化系统，无缝集成飞书项目管理和 Claude Code
 </p>
 </section>
 <!-- 统计卡片 -->
 <section class="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
 <Card v-for="stat in stats":key="stat.title" class="hover:shadow-md transition-shadow">
 <RouterLink:to="stat.link" class="block">
 <CardHeader class="flex flex-row items-center justify-between space-y-0 pb-2">
 <CardTitle class="text-sm font-medium text-muted-foreground">
 {{ stat.title }}
 </CardTitle>
 <span class="text-2xl":class="[`icon-[${stat.icon}]`, stat.color]" />
 </CardHeader>
 <CardContent>
 <div class="text-3xl font-bold":class="[stat.color]">
 <template v-if="loading">
 <span class="inline-block w-8 bg-muted animate-pulse rounded" />
 </template>
 <template v-else>
 {{ stat.value }}
 </template>
 </div>
 </CardContent>
 </RouterLink>
 </Card>
 </section>
 <!-- 功能介绍 -->
 <section class="grid gap-6 md:grid-cols-3">
 <Card>
 <CardHeader>
 <CardTitle class="flex items-center gap-2">
 <span class="icon-[lucide--cpu] text-xl text-primary" />
 <span>智能任务执行</span>
 </CardTitle>
 </CardHeader>
 <CardContent>
 <CardDescription>
 自动监听飞书工作项，利用 AI 生成实现方案和代码，提升开发效率
 </CardDescription>
 </CardContent>
 </Card>
 <Card>
 <CardHeader>
 <CardTitle class="flex items-center gap-2">
 <span class="icon-[lucide--shield-check] text-xl text-primary" />
 <span>安全隔离</span>
 </CardTitle>
 </CardHeader>
 <CardContent>
 <CardDescription>
 每个任务在独立 Docker 容器中执行，确保环境安全和资源隔离
 </CardDescription>
 </CardContent>
 </Card>
 <Card>
 <CardHeader>
 <CardTitle class="flex items-center gap-2">
 <span class="icon-[lucide--user-check] text-xl text-primary" />
 <span>人工审核</span>
 </CardTitle>
 </CardHeader>
 <CardContent>
 <CardDescription>
 完整的状态流转管理和人工审核机制，确保代码质量可控
 </CardDescription>
 </CardContent>
 </Card>
 </section>
 <!-- 最近任务 -->
 <section>
 <Card>
 <CardHeader class="flex flex-row items-center justify-between">
 <div>
 <CardTitle>最近任务</CardTitle>
 <CardDescription>最近创建的任务列表</CardDescription>
 </div>
 <RouterLink to="/tasks">
 <Button variant="outline" size="sm">
 <span class="icon-[lucide--arrow-right] mr-1" />
 查看全部
 </Button>
 </RouterLink>
 </CardHeader>
 <CardContent>
 <div v-if="loading" class="space-y-4">
 <div v-for="i in 3":key="i" class="flex items-center gap-4">
 <div class=" w-1/3 bg-muted animate-pulse rounded" />
 <div class=" w-20 bg-muted animate-pulse rounded" />
 <div class=" w-24 bg-muted animate-pulse rounded" />
 </div>
 </div>
 <div v-else-if="tasksStore.tasks.length === 0" class="text-center py-8 text-muted-foreground">
 <span class="icon-[lucide--inbox] text-4xl block mb-2" />
 暂无任务
 </div>
 <div v-else class="space-y-4">
 <RouterLink
 v-for="task in tasksStore.tasks.slice(0, 5)":key="task.id":to="`/tasks/${task.id}`"
 class="flex items-center justify-between rounded-lg hover:bg-muted/50 transition-colors"
 >
 <div class="flex items-center gap-4 flex-1 min-w-0">
 <span class="font-medium truncate">{{ task.title }}</span>
 <TaskStatusBadge:status="task.status" />
 </div>
 <span class="text-sm text-muted-foreground">
 {{ formatDate(task.created_at) }}
 </span>
 </RouterLink>
 </div>
 </CardContent>
 </Card>
 </section>
 <!-- 快速操作 -->
 <section class="flex justify-center gap-4">
 <RouterLink to="/projects/new">
 <Button>
 <span class="icon-[lucide--plus] mr-2" />
 新建项目
 </Button>
 </RouterLink>
 <RouterLink to="/tasks">
 <Button variant="outline">
 <span class="icon-[lucide--list-checks] mr-2" />
 查看任务
 </Button>
 </RouterLink>
 </section>
 </div>
</template>
