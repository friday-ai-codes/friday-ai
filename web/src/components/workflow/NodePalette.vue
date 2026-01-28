<script setup lang="ts">
import { Bot, Clock, Download, GitBranch, Globe, MessageSquare, Play, Terminal, Webhook } from 'lucide-vue-next'
import { computed } from 'vue'
import { useNodeTypesStore } from '~/stores/useNodeTypesStore'
const nodeTypesStore = useNodeTypesStore
void nodeTypesStore // Used for future API loading
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
 { type: 'feishu_event_trigger', label: '飞书事件', icon: Webhook, description: '监听飞书工作项事件' },
 ],
 },
 {
 category: '数据获取',
 categoryKey: 'integration',
 color: 'orange',
 items: [
 { type: 'fetch_work_item', label: '获取工作项', icon: Download, description: '获取飞书工作项详情' },
 ],
 },
 {
 category: 'AI',
 categoryKey: 'ai',
 color: 'purple',
 items: [
 { type: 'ai_prompt', label: 'AI Prompt', icon: MessageSquare, description: '调用 AI 大语言模型' },
 { type: 'ai_coding_dispatcher', label: 'AI 编码指派', icon: Bot, description: '分析需求分配编码任务' },
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
 color: 'cyan',
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
// 分类标签渐变样式
function getCategoryGradient(color: string) {
 const gradients: Record<string, string> = {
 blue: 'bg-gradient-to-r from-blue-500 to-cyan-400',
 green: 'bg-gradient-to-r from-emerald-500 to-teal-400',
 purple: 'bg-gradient-to-r from-violet-500 to-purple-400',
 orange: 'bg-gradient-to-r from-amber-500 to-orange-400',
 cyan: 'bg-gradient-to-r from-cyan-500 to-blue-400',
 }
 return gradients[color] || gradients.blue
}
// 图标渐变背景
function getIconGradient(color: string) {
 const gradients: Record<string, string> = {
 blue: 'bg-gradient-to-br from-blue-500/20 to-cyan-400/10',
 green: 'bg-gradient-to-br from-emerald-500/20 to-teal-400/10',
 purple: 'bg-gradient-to-br from-violet-500/20 to-purple-400/10',
 orange: 'bg-gradient-to-br from-amber-500/20 to-orange-400/10',
 cyan: 'bg-gradient-to-br from-cyan-500/20 to-blue-400/10',
 }
 return gradients[color] || gradients.blue
}
// 图标颜色
function getIconColor(color: string) {
 const colors: Record<string, string> = {
 blue: 'text-blue-500',
 green: 'text-emerald-500',
 purple: 'text-violet-500',
 orange: 'text-amber-500',
 cyan: 'text-cyan-500',
 }
 return colors[color] || colors.blue
}
// 悬浮光晕颜色
function getHoverGlow(color: string) {
 const glows: Record<string, string> = {
 blue: 'group-hover:shadow-blue-500/10 group-hover:border-blue-500/30',
 green: 'group-hover:shadow-emerald-500/10 group-hover:border-emerald-500/30',
 purple: 'group-hover:shadow-violet-500/10 group-hover:border-violet-500/30',
 orange: 'group-hover:shadow-amber-500/10 group-hover:border-amber-500/30',
 cyan: 'group-hover:shadow-cyan-500/10 group-hover:border-cyan-500/30',
 }
 return glows[color] || glows.blue
}
</script>
<template>
 <div class="h-full w-64 flex flex-col rounded-2xl bg-card/70 backdrop-blur-sm border border-border/50 overflow-hidden">
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
 <!-- Content -->
 <div class="flex-1 overflow-y-auto space-y-5">
 <div v-for="category in nodeTypes":key="category.category">
 <!-- Category Header -->
 <div class="flex items-center gap-2 mb-2.5">
 <div
 class="text-[10px] font-semibold px-2.5 py-1 rounded-full text-white shadow-sm":class="getCategoryGradient(category.color)"
 >
 {{ category.category }}
 </div>
 <div class="flex-1 h-px bg-gradient-to-r from-border/50 to-transparent" />
 </div>
 <!-- Node Items -->
 <div class="space-y-1.5">
 <div
 v-for="item in category.items":key="item.type"
 class="group flex items-center gap-3 text-sm rounded-xl cursor-grab
 bg-background/80 border border-border/40
 transition-all duration-200
 hover:bg-background hover:shadow-md hover:border-border/60
 active:cursor-grabbing active:scale-[0.98]":class="getHoverGlow(category.color)":draggable="true"
 @dragstart="onDragStart($event, item.type)"
 >
 <!-- Icon -->
 <div
 class=" rounded-lg transition-transform duration-200 group-hover:scale-105":class="getIconGradient(category.color)"
 >
 <component:is="item.icon" class="w-4 ":class="getIconColor(category.color)" />
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
 <div class="opacity-0 group-hover:opacity-100 transition-opacity duration-200">
 <span class="icon-[lucide--grip-vertical] text-lg text-muted-foreground/40" />
 </div>
 </div>
 </div>
 </div>
 </div>
 <!-- Footer hint -->
 <div class=" border-t border-border/30">
 <div class="flex items-center justify-center gap-2 text-[10px] text-muted-foreground/60">
 <span class="icon-[lucide--mouse-pointer-click]" />
 <span>拖拽添加 · 点击配置</span>
 </div>
 </div>
 </div>
</template>
