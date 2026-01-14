<script setup lang="ts">
import { useHead } from '@vueuse/head'
useHead({
 title: '任务列表 - Friday AI',
})
// 模拟任务数据
const tasks = ref([
 {
 id: '1',
 title: '实现用户认证模块',
 status: 'completed',
 createdAt: '2024-01-10',
 },
 {
 id: '2',
 title: '添加任务状态流转',
 status: 'in_progress',
 createdAt: '2024-01-12',
 },
 {
 id: '3',
 title: '集成飞书 Webhook',
 status: 'pending',
 createdAt: '2024-01-14',
 },
])
const getStatusColor = (status: string) => {
 switch (status) {
 case 'completed':
 return 'bg-green-100 text-green-800'
 case 'in_progress':
 return 'bg-blue-100 text-blue-800'
 case 'pending':
 return 'bg-gray-100 text-gray-800'
 default:
 return 'bg-gray-100 text-gray-800'
 }
}
const getStatusText = (status: string) => {
 switch (status) {
 case 'completed':
 return '已完成'
 case 'in_progress':
 return '进行中'
 case 'pending':
 return '待处理'
 default:
 return status
 }
}
</script>
<template>
 <div class="space-y-6">
 <div class="flex items-center justify-between">
 <h1 class="text-2xl font-bold">任务列表</h1>
 </div>
 <!-- 任务表格 -->
 <div class="rounded-lg border bg-card">
 <div class="grid grid-cols-4 gap-4 border-b font-medium text-muted-foreground">
 <div>任务名称</div>
 <div>状态</div>
 <div>创建时间</div>
 <div>操作</div>
 </div>
 <div v-for="task in tasks":key="task.id" class="grid grid-cols-4 gap-4 border-b last:border-0">
 <div class="font-medium">{{ task.title }}</div>
 <div>
 <span:class="[
 'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium',
 getStatusColor(task.status)
 ]"
 >
 {{ getStatusText(task.status) }}
 </span>
 </div>
 <div class="text-muted-foreground">{{ task.createdAt }}</div>
 <div>
 <RouterLink:to="`/tasks/${task.id}`"
 class="text-primary hover:underline"
 >
 查看详情
 </RouterLink>
 </div>
 </div>
 </div>
 </div>
</template>