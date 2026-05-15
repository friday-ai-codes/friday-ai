<script setup lang="ts">
import { useHead } from '@vueuse/head'
import DashboardKpiCards from '~/components/dashboard/DashboardKpiCards.vue'
import DashboardQuickActions from '~/components/dashboard/DashboardQuickActions.vue'
import DashboardRecentActivity from '~/components/dashboard/DashboardRecentActivity.vue'
useHead({
 title: '首页 - Friday AI',
})
const spacesStore = useSpacesStore
const executionsStore = useExecutionsStore
// 加载数据
const loading = ref(true)
onMounted(async => {
 try {
 await Promise.all([
 spacesStore.fetchSpaces,
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
 title: '空间总数',
 value: spacesStore.spaceCount,
 icon: 'lucide--folder-git-2',
 statIconClass: 'stat-icon-primary',
 link: '/spaces',
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
 title: '新建空间',
 description: '创建新的开发空间',
 link: '/spaces/new',
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
 <img
 src="/logo-mark.svg"
 alt="Friday"
 class="mx-auto w-20 mb-5 drop-shadow-[0_4px_20px_rgba(20,184,166,0.2)]"
 >
 <h1 class="sr-only">
 Friday AI
 </h1>
 <img
 src="/logo-wordmark.svg"
 alt="friday"
 aria-hidden="true"
 class="mx-auto md: w-auto mb-3"
 >
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
