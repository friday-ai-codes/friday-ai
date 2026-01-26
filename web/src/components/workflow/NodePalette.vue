<script setup lang="ts">
import { Clock, GitBranch, Globe, MessageSquare, Play, Terminal, Webhook } from 'lucide-vue-next'
import { computed } from 'vue'
import { Card, CardContent, CardHeader, CardTitle } from '~/components/ui/card'
import { useNodeTypesStore } from '~/stores/useNodeTypesStore'
const nodeTypesStore = useNodeTypesStore
// 静态节点类型定义（备用，当 API 未加载时使用）
const staticNodeTypes = [
 {
 category: '触发器',
 categoryKey: 'trigger',
 color: 'blue',
 items: [
 { type: 'manual_trigger', label: '手动触发', icon: Play, description: '手动启动工作流' },
 { type: 'webhook_trigger', label: 'Webhook', icon: Webhook, description: '通过 HTTP 请求触发' },
 { type: 'schedule_trigger', label: '定时调度', icon: Clock, description: '按计划自动执行' },
 ],
 },
 {
 category: '操作',
 categoryKey: 'action',
 color: 'green',
 items: [
 { type: 'http_request', label: 'HTTP 请求', icon: Globe, description: '发送 HTTP 请求' },
 { type: 'create_branch', label: '创建分支', icon: GitBranch, description: '创建 Git 分支' },
 { type: 'code_implement', label: 'AI 编码', icon: Terminal, description: 'AI 自动实现代码' },
 ],
 },
 {
 category: '逻辑',
 categoryKey: 'control',
 color: 'purple',
 items: [
 { type: 'condition', label: '条件判断', icon: GitBranch, description: '根据条件分支' },
 { type: 'approval', label: '人工审批', icon: MessageSquare, description: '等待人工审批' },
 ],
 },
]
// 合并 API 返回的节点类型和静态定义
const nodeTypes = computed( => {
 // 如果 API 已加载，可以使用动态数据，这里先用静态数据
 return staticNodeTypes
})
function onDragStart(event: DragEvent, nodeType: string) {
 if (event.dataTransfer) {
 event.dataTransfer.setData('application/vueflow', nodeType)
 event.dataTransfer.effectAllowed = 'move'
 // 设置拖拽图像（可选，提升体验）
 const target = event.target as HTMLElement
 if (target) {
 // 创建一个克隆元素作为拖拽预览
 const ghost = target.cloneNode(true) as HTMLElement
 ghost.style.position = 'absolute'
 ghost.style.top = '-1000px'
 ghost.style.opacity = '0.8'
 ghost.style.transform = 'scale(0.8)'
 document.body.appendChild(ghost)
 event.dataTransfer.setDragImage(ghost, 50, 20)
 // 清理
 setTimeout( => {
 document.body.removeChild(ghost)
 }, 0)
 }
 }
}
const getCategoryColor = (color: string) => {
 const colors: Record<string, string> = {
 blue: 'bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 border-blue-200 dark:border-blue-800',
 green: 'bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400 border-green-200 dark:border-green-800',
 purple: 'bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400 border-purple-200 dark:border-purple-800',
 }
 return colors[color] || colors.blue
}
const getIconBgColor = (color: string) => {
 const colors: Record<string, string> = {
 blue: 'bg-blue-500/10 text-blue-600 dark:text-blue-400',
 green: 'bg-green-500/10 text-green-600 dark:text-green-400',
 purple: 'bg-purple-500/10 text-purple-600 dark:text-purple-400',
 }
 return colors[color] || colors.blue
}
</script>
<template>
 <Card class="h-full w-64 border-r rounded-none flex flex-col bg-card/50 backdrop-blur-sm">
 <CardHeader class="pb-3 border-b">
 <CardTitle class="text-base font-semibold flex items-center gap-2">
 <div class="w-2 rounded-full bg-primary animate-pulse" />
 节点库
 </CardTitle>
 <p class="text-xs text-muted-foreground mt-1">
 拖拽节点到画布上
 </p>
 </CardHeader>
 <CardContent class="flex-1 overflow-y-auto space-y-4">
 <div v-for="category in nodeTypes":key="category.category">
 <!-- Category Header -->
 <div class="flex items-center gap-2 mb-2">
 <div
 class="text-xs font-medium px-2 py-0.5 rounded-full border":class="getCategoryColor(category.color)"
 >
 {{ category.category }}
 </div>
 </div>
 <!-- Node Items -->
 <div class="space-y-1.5">
 <div
 v-for="item in category.items":key="item.type"
 class="group flex items-center gap-3 .5 text-sm border rounded-lg cursor-grab
 bg-background hover:bg-accent/50 hover:border-primary/30
 transition-all duration-200 hover:shadow-sm
 active:cursor-grabbing active:scale-[0.98]":draggable="true"
 @dragstart="onDragStart($event, item.type)"
 >
 <!-- Icon -->
 <div
 class=".5 rounded-md transition-colors":class="getIconBgColor(category.color)"
 >
 <component:is="item.icon" class="w-4 " />
 </div>
 <!-- Text -->
 <div class="flex-1 min-w-0">
 <div class="font-medium text-foreground text-sm leading-tight">
 {{ item.label }}
 </div>
 <div class="text-[10px] text-muted-foreground truncate mt-0.5">
 {{ item.description }}
 </div>
 </div>
 <!-- Drag indicator -->
 <div class="opacity-0 group-hover:opacity-100 transition-opacity">
 <svg class="w-4 text-muted-foreground" viewBox="0 0 24 24" fill="currentColor">
 <circle cx="9" cy="6" r="1.5" />
 <circle cx="15" cy="6" r="1.5" />
 <circle cx="9" cy="12" r="1.5" />
 <circle cx="15" cy="12" r="1.5" />
 <circle cx="9" cy="18" r="1.5" />
 <circle cx="15" cy="18" r="1.5" />
 </svg>
 </div>
 </div>
 </div>
 </div>
 </CardContent>
 </Card>
</template>
