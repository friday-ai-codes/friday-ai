<script setup lang="ts">
import type { NodePaletteItemData } from './NodePaletteItem.vue'
import {
 Bot,
 Briefcase,
 CheckCircle,
 CloudUpload,
 FileCode,
 FileText,
 FolderGit2,
 GitBranch,
 GitMerge,
 GitPullRequest,
 Globe,
 Hourglass,
 MessageSquare,
 Play,
 Search,
 SearchCode,
 Send,
 Terminal,
 Variable,
 Webhook,
} from 'lucide-vue-next'
import NodePaletteItem from './NodePaletteItem.vue'
const emit = defineEmits<{
 dragStart: [nodeData: NodePaletteItemData, event: MouseEvent]
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
 { type: 'feishu_event_trigger', name: '飞书事件', description: '飞书事件触发', icon: MessageSquare, color: 'blue' },
 ],
 },
 {
 name: '数据获取',
 color: 'orange',
 items: [
 { type: 'fetch_work_item', name: '获取工作项', description: '从项目获取工作项信息', icon: Briefcase, color: 'orange' },
 { type: 'fetch_project_info', name: '获取项目信息', description: '获取项目详细信息', icon: FileText, color: 'orange' },
 { type: 'context_retrieval', name: '上下文检索', description: '检索相关上下文信息', icon: Search, color: 'orange' },
 ],
 },
 {
 name: '操作',
 color: 'green',
 items: [
 { type: 'http_request', name: 'HTTP 请求', description: '发送 HTTP 请求', icon: Globe, color: 'green' },
 { type: 'wait_feishu_field', name: '等待飞书', description: '等待飞书消息响应', icon: Hourglass, color: 'green' },
 ],
 },
 {
 name: '集成',
 color: 'blue',
 items: [
 { type: 'create_branch', name: '创建分支', description: '创建 Git 分支', icon: FolderGit2, color: 'blue' },
 { type: 'create_pr', name: '创建 PR', description: '创建 Pull Request', icon: GitPullRequest, color: 'blue' },
 { type: 'merge_pr', name: '合并 PR', description: '合并 Pull Request', icon: GitMerge, color: 'blue' },
 { type: 'mcp_deploy', name: 'MCP 部署', description: 'MCP 服务部署', icon: CloudUpload, color: 'blue' },
 ],
 },
 {
 name: '通知',
 color: 'orange',
 items: [
 { type: 'notify_feishu', name: '飞书通知', description: '发送飞书消息通知', icon: Send, color: 'orange' },
 ],
 },
 {
 name: 'AI',
 color: 'purple',
 items: [
 { type: 'ai_prompt', name: 'AI Prompt', description: '调用 AI 大语言模型', icon: MessageSquare, color: 'purple' },
 { type: 'ai_coding_dispatcher', name: 'AI 编码指派', description: '分析需求分配编码任务', icon: Bot, color: 'purple' },
 { type: 'ai_variable_extractor', name: 'AI 变量提取', description: 'AI 提取变量', icon: Variable, color: 'purple' },
 { type: 'variable_extractor', name: '变量提取', description: '提取变量值', icon: Variable, color: 'purple' },
 { type: 'ai_plan_generation', name: 'AI 方案生成', description: 'AI 自动生成技术方案', icon: FileCode, color: 'purple' },
 { type: 'ai_plan_approval', name: '方案审批', description: '审批技术方案', icon: CheckCircle, color: 'purple' },
 { type: 'ai_coding', name: 'AI 编码执行', description: 'AI 自动编码并创建 MR', icon: Terminal, color: 'purple' },
 { type: 'ai_code_review', name: 'AI 代码审查', description: 'AI 多维度代码审查', icon: SearchCode, color: 'purple' },
 ],
 },
 {
 name: '控制流',
 color: 'purple',
 items: [
 { type: 'condition', name: '条件判断', description: '根据条件分支', icon: GitBranch, color: 'purple' },
 { type: 'human_approval', name: '人工审批', description: '等待人工审批', icon: MessageSquare, color: 'purple' },
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
function handleDragStart(nodeData: NodePaletteItemData, event: MouseEvent) {
 emit('dragStart', nodeData, event)
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
