<script setup lang="ts">
import type { NodeExecution } from '~/stores/useExecutionsStore'
import { ChevronDown, ChevronRight, AlertCircle, CheckCircle2, Loader2, Wrench, Brain, Eye } from 'lucide-vue-next'
import { computed, ref } from 'vue'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '~/components/ui/collapsible'
/**
 * AgentExecutionLog - Agent node execution log with tool timeline and thinking process.
 *
 * Features:
 * - Vertical timeline layout for tool calls
 * - Think-Act-Observe cycle grouping
 * - Expandable tool input/output details
 * - Error highlighting
 * - Glassmorphism styling
 */
interface ToolCall {
 id: string
 name: string
 input: Record<string, unknown>
 output?: unknown
 status: 'running' | 'success' | 'error'
 duration?: number
 error?: string
}
interface ThinkActObserve {
 think?: string
 act?: ToolCall
 observe?: string
}
interface AgentOutput {
 iterations?: ThinkActObserve
 tool_calls?: ToolCall
 final_result?: string
 error?: string
}
interface Props {
 nodeExecution: NodeExecution
 agentOutput?: AgentOutput
}
const props = defineProps<Props>
// Track expanded states for tool calls
const expandedTools = ref<Set<string>>(new Set)
function toggleTool(toolId: string) {
 if (expandedTools.value.has(toolId)) {
 expandedTools.value.delete(toolId)
 } else {
 expandedTools.value.add(toolId)
 }
}
// Parse agent output from nodeExecution or props
const parsedOutput = computed<AgentOutput>( => {
 if (props.agentOutput) {
 return props.agentOutput
 }
 const outputData = props.nodeExecution.output_data
 if (!outputData) return {}
 // Try to parse standard agent output format
 if (outputData.iterations) {
 return outputData as AgentOutput
 }
 // Try to parse tool_calls array
 if (outputData.tool_calls) {
 return { tool_calls: outputData.tool_calls as ToolCall }
 }
 // Try to parse output array (common format)
 if (Array.isArray(outputData.output)) {
 const iterations: ThinkActObserve =
 let currentIteration: ThinkActObserve = {}
 for (const item of outputData.output) {
 if (item.type === 'thinking' || item.type === 'text') {
 if (currentIteration.act) {
 iterations.push(currentIteration)
 currentIteration = {}
 }
 currentIteration.think = item.content || item.text
 } else if (item.type === 'tool_use') {
 currentIteration.act = {
 id: item.id || String(Date.now),
 name: item.name || 'unknown',
 input: item.input || {},
 status: 'running',
 }
 } else if (item.type === 'tool_result') {
 if (currentIteration.act) {
 currentIteration.act.status = item.is_error ? 'error': 'success'
 currentIteration.act.output = item.content
 if (item.is_error) {
 currentIteration.act.error = String(item.content)
 }
 }
 currentIteration.observe = typeof item.content === 'string'
 ? item.content: JSON.stringify(item.content, null, 2)
 iterations.push(currentIteration)
 currentIteration = {}
 }
 }
 if (currentIteration.think || currentIteration.act) {
 iterations.push(currentIteration)
 }
 return { iterations }
 }
 return {}
})
// Get all tool calls for timeline view
const toolCalls = computed<ToolCall>( => {
 if (parsedOutput.value.tool_calls) {
 return parsedOutput.value.tool_calls
 }
 if (parsedOutput.value.iterations) {
 return parsedOutput.value.iterations
 .filter(iter => iter.act)
 .map(iter => iter.act!)
 }
 return
})
// Check if we have iterations (Think-Act-Observe format)
const hasIterations = computed( => {
 return parsedOutput.value.iterations && parsedOutput.value.iterations.length > 0
})
// Format duration
function formatDuration(ms?: number): string {
 if (!ms) return ''
 if (ms < 1000) return `${ms}ms`
 return `${(ms / 1000).toFixed(1)}s`
}
// Truncate text for summary
function truncate(text: string, maxLength: number = 100): string {
 if (!text) return ''
 if (text.length <= maxLength) return text
 return text.slice(0, maxLength) + '...'
}
// Get status icon component
function getStatusIcon(status: string) {
 switch (status) {
 case 'success':
 return CheckCircle2
 case 'error':
 return AlertCircle
 default:
 return Loader2
 }
}
// Get status color class
function getStatusColor(status: string): string {
 switch (status) {
 case 'success':
 return 'text-emerald-500'
 case 'error':
 return 'text-red-500'
 default:
 return 'text-blue-500'
 }
}
// Check for errors
const hasError = computed( => {
 return props.nodeExecution.error_message || parsedOutput.value.error
})
const errorMessage = computed( => {
 return props.nodeExecution.error_message || parsedOutput.value.error || ''
})
</script>
<template>
 <div class="agent-execution-log space-y-4">
 <!-- Error Display -->
 <div
 v-if="hasError"
 class="bg-red-500/10 border border-red-500/30 rounded-xl "
 >
 <div class="flex items-start gap-3">
 <AlertCircle class="w-5 text-red-500 shrink-0 mt-0.5" />
 <div class="flex-1 min-w-0">
 <div class="font-medium text-red-500 mb-1">执行错误</div>
 <div class="text-sm text-red-400 whitespace-pre-wrap break-words">
 {{ errorMessage }}
 </div>
 </div>
 </div>
 </div>
 <!-- Think-Act-Observe Iterations -->
 <div v-if="hasIterations" class="space-y-3">
 <div class="text-sm font-medium text-muted-foreground mb-2">
 执行过程 ({{ parsedOutput.iterations?.length }} 轮)
 </div>
 <div
 v-for="(iteration, index) in parsedOutput.iterations":key="index"
 class="bg-card/80 backdrop-blur-sm border border-border/50 rounded-xl overflow-hidden"
 >
 <!-- Iteration Header -->
 <div class="px-4 py-2 bg-muted/30 border-b border-border/30">
 <span class="text-xs font-medium text-muted-foreground">
 第 {{ index + 1 }} 轮
 </span>
 </div>
 <div class=" space-y-3">
 <!-- Think Section -->
 <div v-if="iteration.think" class="flex gap-3">
 <div class="shrink-0 rounded-lg bg-gradient-to-br from-violet-500/20 to-purple-400/10">
 <Brain class="w-4 text-violet-500" />
 </div>
 <div class="flex-1 min-w-0">
 <div class="text-xs font-medium text-violet-500 mb-1">思考</div>
 <Collapsible>
 <CollapsibleTrigger class="group flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors">
 <ChevronRight class="w-3 transition-transform group-data-[state=open]:rotate-90" />
 <span class="truncate">{{ truncate(iteration.think, 80) }}</span>
 </CollapsibleTrigger>
 <CollapsibleContent>
 <div class="mt-2 text-sm text-foreground whitespace-pre-wrap bg-muted/30 rounded-lg ">
 {{ iteration.think }}
 </div>
 </CollapsibleContent>
 </Collapsible>
 </div>
 </div>
 <!-- Act Section (Tool Call) -->
 <div v-if="iteration.act" class="flex gap-3">
 <div class="shrink-0 rounded-lg bg-gradient-to-br from-blue-500/20 to-cyan-400/10">
 <Wrench class="w-4 text-blue-500" />
 </div>
 <div class="flex-1 min-w-0">
 <div class="flex items-center gap-2 mb-1">
 <span class="text-xs font-medium text-blue-500">执行</span>
 <span class="text-xs font-mono bg-muted/50 px-1.5 py-0.5 rounded">
 {{ iteration.act.name }}
 </span>
 <component:is="getStatusIcon(iteration.act.status)":class="[
 'w-3.5 .5',
 getStatusColor(iteration.act.status),
 iteration.act.status === 'running' && 'animate-spin'
 ]"
 />
 <span v-if="iteration.act.duration" class="text-xs text-muted-foreground">
 {{ formatDuration(iteration.act.duration) }}
 </span>
 </div>
 <Collapsible>
 <CollapsibleTrigger class="group flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors">
 <ChevronRight class="w-3 transition-transform group-data-[state=open]:rotate-90" />
 查看输入/输出
 </CollapsibleTrigger>
 <CollapsibleContent>
 <div class="mt-2 space-y-2">
 <div class="bg-muted/30 rounded-lg ">
 <div class="text-xs font-medium text-muted-foreground mb-1">输入</div>
 <pre class="text-xs overflow-x-auto">{{ JSON.stringify(iteration.act.input, null, 2) }}</pre>
 </div>
 <div v-if="iteration.act.output !== undefined" class="bg-muted/30 rounded-lg ">
 <div class="text-xs font-medium text-muted-foreground mb-1">输出</div>
 <pre class="text-xs overflow-x-auto whitespace-pre-wrap">{{ typeof iteration.act.output === 'string' ? iteration.act.output: JSON.stringify(iteration.act.output, null, 2) }}</pre>
 </div>
 <div v-if="iteration.act.error" class="bg-red-500/10 border border-red-500/30 rounded-lg ">
 <div class="text-xs font-medium text-red-500 mb-1">错误</div>
 <pre class="text-xs text-red-400 overflow-x-auto whitespace-pre-wrap">{{ iteration.act.error }}</pre>
 </div>
 </div>
 </CollapsibleContent>
 </Collapsible>
 </div>
 </div>
 <!-- Observe Section -->
 <div v-if="iteration.observe" class="flex gap-3">
 <div class="shrink-0 rounded-lg bg-gradient-to-br from-emerald-500/20 to-teal-400/10">
 <Eye class="w-4 text-emerald-500" />
 </div>
 <div class="flex-1 min-w-0">
 <div class="text-xs font-medium text-emerald-500 mb-1">观察</div>
 <Collapsible>
 <CollapsibleTrigger class="group flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors">
 <ChevronRight class="w-3 transition-transform group-data-[state=open]:rotate-90" />
 <span class="truncate">{{ truncate(iteration.observe, 80) }}</span>
 </CollapsibleTrigger>
 <CollapsibleContent>
 <div class="mt-2 text-sm text-foreground whitespace-pre-wrap bg-muted/30 rounded-lg overflow-x-auto">
 {{ iteration.observe }}
 </div>
 </CollapsibleContent>
 </Collapsible>
 </div>
 </div>
 </div>
 </div>
 </div>
 <!-- Tool Calls Timeline (fallback if no iterations) -->
 <div v-else-if="toolCalls.length > 0" class="space-y-3">
 <div class="text-sm font-medium text-muted-foreground mb-2">
 工具调用时间线 ({{ toolCalls.length }})
 </div>
 <div class="relative">
 <!-- Timeline Line -->
 <div class="absolute left-[15px] top-4 bottom-4 w-0.5 bg-border/50" />
 <div class="space-y-3">
 <div
 v-for="(tool, index) in toolCalls":key="tool.id || index"
 class="relative flex gap-3"
 >
 <!-- Timeline Dot -->
 <div:class="[
 'relative z-10 shrink-0 w-8 rounded-full flex items-center justify-center border-2',
 tool.status === 'success' && 'bg-emerald-500/20 border-emerald-500',
 tool.status === 'error' && 'bg-red-500/20 border-red-500',
 tool.status === 'running' && 'bg-blue-500/20 border-blue-500',
 ]"
 >
 <component:is="getStatusIcon(tool.status)":class="[
 'w-4 ',
 getStatusColor(tool.status),
 tool.status === 'running' && 'animate-spin'
 ]"
 />
 </div>
 <!-- Tool Card -->
 <div class="flex-1 bg-muted/30 rounded-lg ">
 <div class="flex items-center justify-between mb-2">
 <div class="flex items-center gap-2">
 <span class="font-mono text-sm font-medium">{{ tool.name }}</span>
 <span:class="[
 'text-xs px-1.5 py-0.5 rounded-full',
 tool.status === 'success' && 'bg-emerald-500/20 text-emerald-500',
 tool.status === 'error' && 'bg-red-500/20 text-red-500',
 tool.status === 'running' && 'bg-blue-500/20 text-blue-500',
 ]"
 >
 {{ tool.status === 'success' ? '成功': tool.status === 'error' ? '失败': '运行中' }}
 </span>
 </div>
 <span v-if="tool.duration" class="text-xs text-muted-foreground">
 {{ formatDuration(tool.duration) }}
 </span>
 </div>
 <Collapsible:open="expandedTools.has(tool.id)" @update:open="toggleTool(tool.id)">
 <CollapsibleTrigger class="group flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors">
 <component:is="expandedTools.has(tool.id) ? ChevronDown: ChevronRight"
 class="w-3 "
 />
 查看详情
 </CollapsibleTrigger>
 <CollapsibleContent>
 <div class="mt-2 space-y-2">
 <div class="bg-card/50 rounded-lg ">
 <div class="text-xs font-medium text-muted-foreground mb-1">输入</div>
 <pre class="text-xs overflow-x-auto">{{ JSON.stringify(tool.input, null, 2) }}</pre>
 </div>
 <div v-if="tool.output !== undefined" class="bg-card/50 rounded-lg ">
 <div class="text-xs font-medium text-muted-foreground mb-1">输出</div>
 <pre class="text-xs overflow-x-auto whitespace-pre-wrap">{{ typeof tool.output === 'string' ? tool.output: JSON.stringify(tool.output, null, 2) }}</pre>
 </div>
 <div v-if="tool.error" class="bg-red-500/10 border border-red-500/30 rounded-lg ">
 <div class="text-xs font-medium text-red-500 mb-1">错误</div>
 <pre class="text-xs text-red-400 overflow-x-auto whitespace-pre-wrap">{{ tool.error }}</pre>
 </div>
 </div>
 </CollapsibleContent>
 </Collapsible>
 </div>
 </div>
 </div>
 </div>
 </div>
 <!-- Empty State -->
 <div
 v-else-if="!hasError"
 class="text-center py-8 text-muted-foreground"
 >
 <Loader2 class="w-8 mx-auto mb-2 animate-spin text-blue-500" />
 <div class="text-sm">正在执行...</div>
 </div>
 <!-- Final Result -->
 <div
 v-if="parsedOutput.final_result"
 class="bg-card/80 backdrop-blur-sm border border-emerald-500/30 rounded-xl "
 >
 <div class="flex items-start gap-3">
 <CheckCircle2 class="w-5 text-emerald-500 shrink-0 mt-0.5" />
 <div class="flex-1 min-w-0">
 <div class="font-medium text-emerald-500 mb-1">执行结果</div>
 <div class="text-sm whitespace-pre-wrap">
 {{ parsedOutput.final_result }}
 </div>
 </div>
 </div>
 </div>
 </div>
</template>
<style scoped>
.agent-execution-log pre {
 font-family: ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace;
 font-size: 0.75rem;
 line-height: 1.5;
}
</style>
