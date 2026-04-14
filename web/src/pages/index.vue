<script setup lang="ts">
import { useHead } from '@vueuse/head'
import DashboardKpiCards from '~/components/dashboard/DashboardKpiCards.vue'
import DashboardQuickActions from '~/components/dashboard/DashboardQuickActions.vue'
import DashboardRecentActivity from '~/components/dashboard/DashboardRecentActivity.vue'
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
 statIconClass: 'stat-icon-primary',
 link: '/executions',
 },
 {
 title: '运行中',
 value: executionsStore.stats.running,
 icon: 'lucide--zap',
 statIconClass: 'stat-icon-primary',
 link: '/executions?status=running',
 },
 {
 title: '待审批',
 value: executionsStore.stats.waitingApproval,
 icon: 'lucide--scan-eye',
 statIconClass: 'stat-icon-primary',
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
 iconBg: 'stat-icon-primary',
 },
 {
 icon: 'lucide--play-circle',
 title: '执行监控',
 description: '查看运行状态',
 link: '/executions',
 iconBg: 'stat-icon-primary',
 },
 {
 icon: 'lucide--git-branch',
 title: '仓库管理',
 description: '管理代码仓库',
 link: '/repositories',
 iconBg: 'stat-icon-primary',
 },
 {
 icon: 'lucide--message-square',
 title: 'AI 对话',
 description: '与 AI 助手交流',
 link: '/chat',
 iconBg: 'stat-icon-primary',
 },
]
</script>
<template>
 <div class="max-w-[1200px] mx-auto space-y-8">
 <!-- Hero 区域 — sub2api 风格简洁 -->
 <section class="text-center pt-6 pb-2">
 <div class="inline-flex items-center justify-center w-20 rounded-2xl gradient-primary mb-5 shadow-glow">
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
 <!-- 统计卡片 — KPI widget -->
 <DashboardKpiCards:stats="stats":loading="loading" />
 <!-- 快捷操作 — 紧凑横排 -->
 <DashboardQuickActions:actions="quickActions" />
 <!-- 最近执行 — 活动 widget -->
 <DashboardRecentActivity:executions="executionsStore.executions":loading="loading" />
 </div>
</template>
