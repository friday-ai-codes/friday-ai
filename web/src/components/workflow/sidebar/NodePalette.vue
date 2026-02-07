<script setup lang="ts">
import { Bot, Clock, GitBranch, Globe, MessageSquare, Play, Terminal, Webhook } from 'lucide-vue-next'
import NodePaletteItem from './NodePaletteItem.vue'
import type { NodePaletteItemData } from './NodePaletteItem.vue'
const emit = defineEmits<{
 dragStart: [nodeType: string, event: MouseEvent]
}>
/**
 * Node type categories with their items.
 * Each category has a color theme for consistent styling.
 */
interface NodeCategory {
 name: string
 color: string
 items: NodePaletteItemData
}
/**
 * Default node types organized by category.
 * Can be replaced with dynamic data from API in the future.
 */
const nodeCategories: NodeCategory = [
 {
 name: '触发器',
 color: 'blue',
 items: [
 { type: 'manual_trigger', name: '手动触发', description: '手动启动工作流', icon: Play, color: 'blue' },
 { type: 'webhook_trigger', name: 'Webhook', description: '通过 HTTP 请求触发', icon: Webhook, color: 'blue' },
 { type: 'schedule_trigger', name: '定时调度', description: '按计划自动执行', icon: Clock, color: 'blue' },
 ],
 },
 {
 name: '操作',
 color: 'green',
 items: [
 { type: 'http_request', name: 'HTTP 请求', description: '发送 HTTP 请求', icon: Globe, color: 'green' },
 { type: 'code_implement', name: 'AI 编码', description: 'AI 自动实现代码', icon: Terminal, color: 'green' },
 ],
 },
 {
 name: 'AI',
 color: 'purple',
 items: [
 { type: 'ai_prompt', name: 'AI Prompt', description: '调用 AI 大语言模型', icon: MessageSquare, color: 'purple' },
 { type: 'ai_coding_dispatcher', name: 'AI 编码指派', description: '分析需求分配编码任务', icon: Bot, color: 'purple' },
 ],
 },
 {
 name: '逻辑',
 color: 'cyan',
 items: [
 { type: 'condition', name: '条件判断', description: '根据条件分支', icon: GitBranch, color: 'cyan' },
 { type: 'approval', name: '人工审批', description: '等待人工审批', icon: MessageSquare, color: 'cyan' },
 ],
 },
]
/**
 * Get gradient classes for category badge.
 */
function getCategoryGradient(color: string): string {
 const gradients: Record<string, string> = {
 blue: 'bg-gradient-to-r from-blue-500 to-cyan-400',
 green: 'bg-gradient-to-r from-emerald-500 to-teal-400',
 purple: 'bg-gradient-to-r from-violet-500 to-purple-400',
 orange: 'bg-gradient-to-r from-amber-500 to-orange-400',
 cyan: 'bg-gradient-to-r from-cyan-500 to-blue-400',
 }
 return gradients[color] || gradients.blue
}
/**
 * Forward dragStart event from child item to parent.
 */
function handleDragStart(nodeType: string, event: MouseEvent) {
 emit('dragStart', nodeType, event)
}
</script>
<template>
 <div class="h-full w-64 shrink-0 flex flex-col rounded-2xl bg-card/70 backdrop-blur-sm border border-border/50 overflow-hidden ">
 <!-- Header -->
 <div class=" border-b border-border/50">
 <div class="flex items-center gap-3">
 <div class=".5 rounded-xl bg-gradient-to-br from-primary/20 to-secondary/10">
 <span class="icon-[lucide--boxes] text-xl text-primary" />
 </div>
 <div>
 <h3 class="text-base font-semibold flex items-center gap-2">
 <div class="w-2 rounded-full bg-gradient-to-r from-primary to-secondary animate-pulse" />
 节点库
 </h3>
 <p class="text-xs text-muted-foreground">
 拖拽节点到画布上
 </p>
 </div>
 </div>
 </div>
 <!-- Content: Scrollable list of categories -->
 <div class="flex-1 overflow-y-auto space-y-5">
 <div v-for="category in nodeCategories":key="category.name">
 <!-- Category Header -->
 <div class="flex items-center gap-2 mb-2.5">
 <div
 class="text-[10px] font-semibold px-2.5 py-1 rounded-full text-white shadow-sm":class="getCategoryGradient(category.color)"
 >
 {{ category.name }}
 </div>
 <div class="flex-1 h-px bg-gradient-to-r from-border/50 to-transparent" />
 </div>
 <!-- Node Items -->
 <div class="space-y-1.5">
 <NodePaletteItem
 v-for="item in category.items":key="item.type":node="item"
 @drag-start="handleDragStart"
 />
 </div>
 </div>
 </div>
 <!-- Footer hint -->
 <div class=" border-t border-border/30">
 <div class="flex items-center justify-center gap-2 text-[10px] text-muted-foreground/60">
 <span class="icon-[lucide--grip-vertical]" />
 <span>拖拽手柄添加节点</span>
 </div>
 </div>
 </div>
</template>
