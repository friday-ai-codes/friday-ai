<script setup lang="ts">
import { useHead } from '@vueuse/head'
import { Badge } from '~/components/ui/badge'
useHead({
 title: '首页 - Friday AI',
})
const projectsStore = useProjectsStore
const executionsStore = useExecutionsStore
// 加载数据
const loading = ref(true)
onMounted(async => {
 try {
 await Promise.all([
 projectsStore.fetchProjects,
 executionsStore.fetchExecutions,
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
 statIconClass: 'stat-icon-primary',
 link: '/projects',
 },
 {
 title: '执行总数',
 value: executionsStore.stats.total,
 icon: 'lucide--layers',
 statIconClass: 'stat-icon-violet',
 link: '/executions',
 },
 {
 title: '运行中',
 value: executionsStore.stats.running,
 icon: 'lucide--zap',
 statIconClass: 'stat-icon-amber',
 link: '/executions?status=running',
 },
 {
 title: '待审批',
 value: executionsStore.stats.waitingApproval,
 icon: 'lucide--scan-eye',
 statIconClass: 'stat-icon-emerald',
 link: '/executions?status=waiting_approval',
 },
])
// 快捷操作
const quickActions = [
 {
 icon: 'lucide--plus',
 title: '新建项目',
 description: '创建新的开发项目',
 link: '/projects/new',
 iconBg: 'stat-icon-primary',
 },
 {
 icon: 'lucide--workflow',
 title: '工作流管理',
 description: '编排自动化流程',
 link: '/workflows',
 iconBg: 'stat-icon-violet',
 },
 {
 icon: 'lucide--play-circle',
 title: '执行监控',
 description: '查看运行状态',
 link: '/executions',
 iconBg: 'stat-icon-amber',
 },
 {
 icon: 'lucide--git-branch',
 title: '仓库管理',
 description: '管理代码仓库',
 link: '/repositories',
 iconBg: 'stat-icon-emerald',
 },
]
// 执行状态配置
const statusConfig: Record<string, { label: string, color: string }> = {
 pending: { label: '等待中', color: 'bg-gray-100 text-gray-700' },
 running: { label: '运行中', color: 'bg-blue-100 text-blue-700' },
 completed: { label: '已完成', color: 'bg-emerald-100 text-emerald-700' },
 failed: { label: '失败', color: 'bg-red-100 text-red-700' },
 waiting_approval: { label: '待审批', color: 'bg-amber-100 text-amber-700' },
}
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
 <div class="max-w-[1200px] mx-auto space-y-8">
 <!-- Hero 区域 — sub2api 风格简洁 -->
 <section class="text-center pt-6 pb-2">
 <div class="inline-flex items-center justify-center w-20 rounded-2xl gradient-primary mb-5 shadow-[0_0_20px_rgba(20,184,166,0.25)]">
 <span class="icon-[lucide--bot] text-4xl text-white" />
 </div>
 <h1 class="text-3xl md:text-4xl font-bold text-foreground mb-3">
 Friday AI
 </h1>
 <p class="text-muted-foreground text-base max-w-lg mx-auto">
 AI 驱动的敏捷开发自动化系统
 </p>
 <p class="text-primary text-sm mt-1">
 无缝集成飞书项目管理和 Claude Code
 </p>
 </section>
 <!-- 统计卡片 — sub2api stat-card 风格 -->
 <section class="grid gap-5 grid-cols-2 lg:grid-cols-4">
 <RouterLink
 v-for="stat in stats":key="stat.title":to="stat.link"
 class="card card-interactive group flex items-start gap-4"
 >
 <!-- 图标 -->
 <div class="stat-icon":class="stat.statIconClass">
 <span class="text-xl":class="`icon-[${stat.icon}]`" />
 </div>
 <!-- 内容 -->
 <div class="min-w-0 flex-1">
 <p class="text-sm text-muted-foreground mb-1">
 {{ stat.title }}
 </p>
 <p class="text-2xl font-bold text-foreground truncate">
 <template v-if="loading">
 <span class="inline-block w-10 bg-muted animate-pulse rounded" />
 </template>
 <template v-else>
 {{ stat.value }}
 </template>
 </p>
 </div>
 <!-- 箭头 -->
 <span class="icon-[lucide--arrow-up-right] text-muted-foreground/30 group-hover:text-primary transition-colors" />
 </RouterLink>
 </section>
 <!-- 快捷操作 — 紧凑横排 -->
 <section class="flex flex-wrap gap-3">
 <RouterLink
 v-for="action in quickActions":key="action.title":to="action.link"
 class="group inline-flex items-center gap-2.5 px-4 py-2.5 rounded-xl bg-white border border-border/60 hover:border-primary/40 hover:shadow-md transition-all duration-200"
 >
 <span class="text-base text-muted-foreground group-hover:text-primary transition-colors":class="`icon-[${action.icon}]`" />
 <span class="text-sm font-medium text-foreground group-hover:text-primary transition-colors">{{ action.title }}</span>
 </RouterLink>
 </section>
 <!-- 最近执行 — sub2api card 风格 -->
 <section>
 <div class="card overflow-hidden">
 <!-- 标题栏 -->
 <div class="flex items-center justify-between px-6 py-4 border-b border-border/50">
 <div class="flex items-center gap-3">
 <div class="stat-icon stat-icon-primary">
 <span class="icon-[lucide--clock] text-lg" />
 </div>
 <div>
 <h2 class="text-base font-semibold text-foreground">
 最近执行
 </h2>
 <p class="text-xs text-muted-foreground">
 最近的工作流执行记录
 </p>
 </div>
 </div>
 <RouterLink to="/executions">
 <span class="text-sm font-medium text-muted-foreground hover:text-primary transition-colors group inline-flex items-center">
 查看全部
 <span class="icon-[lucide--arrow-right] ml-1 group-hover:translate-x-1 transition-transform" />
 </span>
 </RouterLink>
 </div>
 <!-- 执行列表 -->
 <div class="">
 <!-- 加载状态 -->
 <div v-if="loading" class="space-y-2">
 <div v-for="i in 3":key="i" class="flex items-center gap-4 rounded-xl">
 <div class="w-10 rounded-lg bg-muted animate-pulse" />
 <div class="flex-1 space-y-2">
 <div class=" w-2/3 bg-muted animate-pulse rounded" />
 <div class=" w-1/4 bg-muted animate-pulse rounded" />
 </div>
 <div class=" w-16 bg-muted animate-pulse rounded-full" />
 </div>
 </div>
 <!-- 空状态 -->
 <div v-else-if="executionsStore.executions.length === 0" class="py-12 text-center">
 <div class="stat-icon stat-icon-primary mx-auto mb-4 w-16 text-2xl">
 <span class="icon-[lucide--play-circle]" />
 </div>
 <h3 class="text-base font-medium text-foreground mb-1">
 暂无执行记录
 </h3>
 <p class="text-sm text-muted-foreground mb-5">
 创建工作流并运行，执行记录将显示在这里
 </p>
 <RouterLink to="/workflows">
 <button class="btn btn-primary">
 <span class="icon-[lucide--workflow]" />
 查看工作流
 </button>
 </RouterLink>
 </div>
 <!-- 执行列表 -->
 <div v-else class="space-y-1">
 <RouterLink
 v-for="(execution, index) in executionsStore.executions.slice(0, 5)":key="execution.id":to="`/executions/${execution.id}`"
 class="group flex items-center gap-4 rounded-xl hover:bg-muted/50 transition-colors duration-200"
 >
 <!-- 序号 -->
 <div class="flex-shrink-0 w-10 rounded-lg bg-muted/50 flex items-center justify-center font-medium text-muted-foreground text-sm group-hover:bg-primary/10 group-hover:text-primary transition-colors">
 {{ index + 1 }}
 </div>
 <!-- 内容 -->
 <div class="flex-1 min-w-0">
 <p class="text-sm font-medium text-foreground truncate group-hover:text-primary transition-colors">
 {{ execution.workflow_name }}
 </p>
 <p class="text-xs text-muted-foreground mt-0.5">
 {{ formatDate(execution.created_at) }}
 </p>
 </div>
 <!-- 状态 -->
 <Badge:class="statusConfig[execution.status]?.color || statusConfig.pending.color" class="text-xs">
 {{ statusConfig[execution.status]?.label || execution.status }}
 </Badge>
 <!-- 箭头 -->
 <span class="icon-[lucide--chevron-right] text-muted-foreground/30 group-hover:text-primary group-hover:translate-x-0.5 transition-all" />
 </RouterLink>
 </div>
 </div>
 </div>
 </section>
 </div>
</template>
