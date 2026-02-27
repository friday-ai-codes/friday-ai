<script setup lang="ts">
import { getNodeVisual } from '../editor/nodes/nodeVisuals'
import NodePaletteItem from './NodePaletteItem.vue'
/**
 * 节点分组定义 — 名称和描述在这里维护，图标和颜色从 nodeVisuals 统一读取。
 */
interface PaletteGroup {
 name: string
 items: { type: string, name: string, description: string }
}
const nodeGroups: PaletteGroup = [
 {
 name: '触发器',
 items: [
 { type: 'manual_trigger', name: '手动触发', description: '手动启动工作流' },
 { type: 'webhook_trigger', name: 'Webhook', description: '通过 HTTP 请求触发' },
 { type: 'feishu_event_trigger', name: '飞书事件', description: '飞书事件触发' },
 ],
 },
 {
 name: '数据获取',
 items: [
 { type: 'fetch_work_item', name: '获取工作项', description: '从项目获取工作项信息' },
 { type: 'fetch_project_info', name: '获取项目信息', description: '获取项目详细信息' },
 { type: 'context_retrieval', name: '上下文检索', description: '检索相关上下文信息' },
 ],
 },
 {
 name: '操作',
 items: [
 { type: 'http_request', name: 'HTTP 请求', description: '发送 HTTP 请求' },
 { type: 'wait_feishu_field', name: '等待飞书', description: '等待飞书消息响应' },
 ],
 },
 {
 name: '集成',
 items: [
 { type: 'create_branch', name: '创建分支', description: '创建 Git 分支' },
 { type: 'create_pr', name: '创建 PR', description: '创建 Pull Request' },
 { type: 'merge_pr', name: '合并 PR', description: '合并 Pull Request' },
 { type: 'mcp_deploy', name: 'MCP 部署', description: 'MCP 服务部署' },
 ],
 },
 {
 name: '通知',
 items: [
 { type: 'notify_feishu', name: '飞书通知', description: '发送飞书消息通知' },
 ],
 },
 {
 name: 'AI',
 items: [
 { type: 'ai_prompt', name: 'AI Prompt', description: '调用 AI 大语言模型' },
 { type: 'ai_coding_dispatcher', name: 'AI 编码指派', description: '分析需求分配编码任务' },
 { type: 'ai_variable_extractor', name: 'AI 变量提取', description: 'AI 提取变量' },
 { type: 'variable_extractor', name: '变量提取', description: '提取变量值' },
 { type: 'ai_technical_plan', name: 'AI 技术方案', description: 'AI 生成技术方案' },
 { type: 'ai_plan_generation', name: 'AI 方案生成', description: 'AI 自动生成技术方案' },
 { type: 'ai_plan_approval', name: '方案审批', description: '审批技术方案' },
 { type: 'ai_coding', name: 'AI 编码执行', description: 'AI 自动编码并创建 MR' },
 { type: 'ai_code_review', name: 'AI 代码审查', description: 'AI 多维度代码审查' },
 ],
 },
 {
 name: '控制流',
 items: [
 { type: 'condition', name: '条件判断', description: '根据条件分支' },
 { type: 'human_approval', name: '人工审批', description: '等待人工审批' },
 { type: 'delay', name: '延时', description: '等待指定时长后继续' },
 { type: 'parallel', name: '并行分支', description: '并行执行多个分支' },
 { type: 'join', name: '汇聚', description: '等待所有并行分支完成' },
 ],
 },
]
/** 从 nodeVisuals 获取分组的主色 — 取第一个 item 的颜色 */
function getGroupColor(group: PaletteGroup): string {
 return getNodeVisual(group.items[0]?.type ?? '').color
}
function getCategoryGradient(color: string): string {
 const gradients: Record<string, string> = {
 blue: 'bg-gradient-to-r from-blue-500 to-cyan-400',
 green: 'bg-gradient-to-r from-emerald-500 to-teal-400',
 purple: 'bg-gradient-to-r from-violet-500 to-purple-400',
 orange: 'bg-gradient-to-r from-amber-500 to-orange-400',
 }
 return gradients[color] || gradients.blue
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
 <div v-for="group in nodeGroups":key="group.name">
 <!-- Category Header -->
 <div class="flex items-center gap-2 mb-2.5">
 <div
 class="text-[10px] font-semibold px-2.5 py-1 rounded-full text-white shadow-sm":class="getCategoryGradient(getGroupColor(group))"
 >
 {{ group.name }}
 </div>
 <div class="flex-1 h-px bg-gradient-to-r from-border/50 to-transparent" />
 </div>
 <!-- Node Items -->
 <div class="space-y-1.5">
 <NodePaletteItem
 v-for="item in group.items":key="item.type":node-type="item.type":name="item.name":description="item.description"
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
