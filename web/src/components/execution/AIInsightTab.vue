<script setup lang="ts">
import type { ActionLogDetail, ActionLogSummary, CostBreakdownNode } from '~/types/execution'
/**
 * AIInsightTab — AI 透视 Tab 组件
 *
 * 包含两个区域：ReAct 步骤流（按迭代分组）和节点级成本拆分。
 * 步骤默认折叠，展开时按需加载 payload 详情。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { getActionLogDetail, getCostBreakdown, getReactSteps } from '~/api/workflow'
import JsonHighlighter from '~/components/logs/JsonHighlighter.vue'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '~/components/ui/collapsible'
import { Skeleton } from '~/components/ui/skeleton'
const props = defineProps<{
 nodeExecutionId: string
 executionId: string
 nodeId?: string // workflow node UUID，用于精确过滤成本数据
}>
// ----- ReAct 步骤流 -----
const steps = ref<ActionLogSummary>
const stepsLoading = ref(false)
const stepsError = ref<string | null>(null)
// 详情缓存
const detailCache = new Map<number, ActionLogDetail>
const loadingDetails = ref(new Set<number>)
const loadedDetails = ref(new Map<number, ActionLogDetail>)
async function fetchSteps {
 stepsLoading.value = true
 stepsError.value = null
 try {
 steps.value = await getReactSteps(props.nodeExecutionId)
 }
 catch (e: any) {
 stepsError.value = e.message || '加载失败'
 }
 finally {
 stepsLoading.value = false
 }
}
async function loadDetail(stepId: number) {
 if (detailCache.has(stepId)) {
 loadedDetails.value.set(stepId, detailCache.get(stepId)!)
 return
 }
 loadingDetails.value.add(stepId)
 try {
 const detail = await getActionLogDetail(stepId)
 detailCache.set(stepId, detail)
 loadedDetails.value.set(stepId, detail)
 }
 catch {
 // 静默失败
 }
 finally {
 loadingDetails.value.delete(stepId)
 }
}
// 迭代分组
interface Iteration {
 index: number
 steps: ActionLogSummary
}
const iterations = computed<Iteration>( => {
 const result: Iteration =
 let current: ActionLogSummary =
 let idx = 0
 for (const step of steps.value) {
 if (step.action_type === 'llm_request' && current.length > 0) {
 result.push({ index: idx++, steps: current })
 current =
 }
 current.push(step)
 }
 if (current.length > 0) {
 result.push({ index: idx, steps: current })
 }
 return result
})
// ----- 节点成本 -----
const costLoading = ref(false)
const allNodeCosts = ref<CostBreakdownNode>
async function fetchNodeCost {
 costLoading.value = true
 try {
 const breakdown = await getCostBreakdown(props.executionId)
 if (props.nodeId) {
 // 精确过滤当前节点
 const nodeCostData = breakdown.nodes.find(n => n.node_id === props.nodeId)
 allNodeCosts.value = nodeCostData ? [nodeCostData]:
 }
 else {
 // 无 nodeId 时展示所有节点（降级行为）
 allNodeCosts.value = breakdown.nodes
 }
 }
 catch {
 allNodeCosts.value =
 }
 finally {
 costLoading.value = false
 }
}
// ----- 格式化工具 -----
function formatDuration(ms: number | null): string {
 if (ms == null)
 return '-'
 if (ms < 1000)
 return `${ms}ms`
 return `${(ms / 1000).toFixed(1)}s`
}
function formatTokenCount(count: number): string {
 if (count >= 1_000_000)
 return `${(count / 1_000_000).toFixed(1)}M`
 if (count >= 1_000)
 return `${(count / 1_000).toFixed(1)}k`
 return String(count)
}
const costFormatter = new Intl.NumberFormat('en-US', {
 style: 'currency',
 currency: 'USD',
 minimumFractionDigits: 2,
 maximumFractionDigits: 4,
})
function formatCost(costUsdString: string): string {
 const val = Number.parseFloat(costUsdString)
 if (Number.isNaN(val) || val === 0)
 return '$0.00'
 return costFormatter.format(val)
}
/** 步骤类型映射 */
function getStepMeta(actionType: string) {
 switch (actionType) {
 case 'llm_request':
 return { label: '思考', iconClass: 'icon-[lucide--brain]', colorClass: 'text-violet-500', bgClass: 'bg-violet-500/10' }
 case 'tool_call':
 return { label: '执行', iconClass: 'icon-[lucide--wrench]', colorClass: 'text-blue-500', bgClass: 'bg-blue-500/10' }
 case 'llm_response':
 return { label: '观察', iconClass: 'icon-[lucide--eye]', colorClass: 'text-emerald-500', bgClass: 'bg-emerald-500/10' }
 case 'state_change':
 return { label: '状态变更', iconClass: 'icon-[lucide--git-branch]', colorClass: 'text-amber-500', bgClass: 'bg-amber-500/10' }
 case 'decision':
 return { label: '决策', iconClass: 'icon-[lucide--compass]', colorClass: 'text-purple-500', bgClass: 'bg-purple-500/10' }
 default:
 return { label: actionType, iconClass: 'icon-[lucide--circle]', colorClass: 'text-gray-500', bgClass: 'bg-gray-500/10' }
 }
}
// ----- 生命周期 -----
onMounted( => {
 fetchSteps
 fetchNodeCost
})
watch( => props.nodeExecutionId, => {
 detailCache.clear
 loadedDetails.value.clear
 fetchSteps
 fetchNodeCost
})
</script>
<template>
 <div class="space-y-6">
 <!-- ===== ReAct 步骤流 ===== -->
 <div>
 <h3 class="text-sm font-semibold text-foreground mb-3 flex items-center gap-2">
 <span class="icon-[lucide--brain] w-4 text-violet-500" />
 ReAct 步骤流
 </h3>
 <!-- 加载状态 -->
 <div v-if="stepsLoading" class="space-y-3">
 <Skeleton v-for="i in 3":key="i" class=" w-full rounded-xl" />
 </div>
 <!-- 错误状态 -->
 <div v-else-if="stepsError" class="text-sm text-destructive bg-destructive/10 rounded-lg px-3 py-2">
 {{ stepsError }}
 </div>
 <!-- 空状态 -->
 <div v-else-if="iterations.length === 0" class="text-sm text-muted-foreground text-center py-4">
 暂无步骤数据
 </div>
 <!-- 迭代列表 -->
 <div v-else class="space-y-3">
 <div
 v-for="iteration in iterations":key="iteration.index"
 class="bg-card/80 backdrop-blur-sm border border-border/50 rounded-xl overflow-hidden"
 >
 <!-- 迭代标题 -->
 <div class="px-3 py-2 bg-muted/30 border-b border-border/30 text-xs font-medium text-muted-foreground">
 迭代 {{ iteration.index + 1 }}
 </div>
 <!-- 步骤列表 -->
 <div class="divide-y divide-border/30">
 <Collapsible
 v-for="step in iteration.steps":key="step.id"
 >
 <CollapsibleTrigger
 class="w-full px-3 py-2 flex items-center gap-2 text-left hover:bg-muted/20 transition-colors"
 @click="loadDetail(step.id)"
 >
 <!-- 步骤图标 -->
 <div
 class="w-6 rounded-md flex items-center justify-center shrink-0":class="getStepMeta(step.action_type).bgClass"
 >
 <span
 class="w-3.5 .5":class="[getStepMeta(step.action_type).iconClass, getStepMeta(step.action_type).colorClass]"
 />
 </div>
 <!-- 步骤类型 + 摘要 -->
 <div class="flex-1 min-w-0">
 <div class="flex items-center gap-1.5">
 <span
 class="text-xs font-medium":class="getStepMeta(step.action_type).colorClass"
 >
 {{ getStepMeta(step.action_type).label }}
 </span>
 <span class="text-[10px] text-muted-foreground">#{{ step.sequence }}</span>
 </div>
 <p
 v-if="step.payload_summary"
 class="text-[11px] text-muted-foreground truncate"
 >
 {{ step.payload_summary }}
 </p>
 </div>
 <!-- 耗时 + 超时警告 -->
 <div class="flex items-center gap-1 shrink-0">
 <span
 v-if="step.duration_ms != null && step.duration_ms > 30000"
 class="icon-[lucide--alert-triangle] w-3.5 .5 text-red-500"
 />
 <span
 class="text-[11px] tabular-nums":class="step.duration_ms != null && step.duration_ms > 30000
 ? 'text-red-500 font-medium': 'text-muted-foreground'"
 >
 {{ formatDuration(step.duration_ms) }}
 </span>
 </div>
 <!-- 展开箭头 -->
 <span class="icon-[lucide--chevron-down] w-3.5 .5 text-muted-foreground transition-transform" />
 </CollapsibleTrigger>
 <CollapsibleContent>
 <div class="px-3 pb-3">
 <!-- 加载中 -->
 <div v-if="loadingDetails.has(step.id)" class="py-2">
 <Skeleton class=" w-full rounded-lg" />
 </div>
 <!-- 详情 -->
 <div v-else-if="loadedDetails.has(step.id)" class="mt-1">
 <JsonHighlighter:json="(loadedDetails.get(step.id)?.payload as Record<string, unknown>) ?? null":show-copy="true"
 />
 </div>
 </div>
 </CollapsibleContent>
 </Collapsible>
 </div>
 </div>
 </div>
 </div>
 <!-- ===== 节点成本拆分 ===== -->
 <div>
 <h3 class="text-sm font-semibold text-foreground mb-3 flex items-center gap-2">
 <span class="icon-[lucide--coins] w-4 text-amber-500" />
 Token 消耗与成本
 </h3>
 <!-- 加载状态 -->
 <div v-if="costLoading" class="space-y-2">
 <Skeleton class=" w-full rounded-lg" />
 <Skeleton class=" w-full rounded-lg" />
 </div>
 <!-- 空状态 -->
 <div
 v-else-if="allNodeCosts.length === 0"
 class="text-sm text-muted-foreground text-center py-4"
 >
 暂无成本数据
 </div>
 <!-- 成本列表 -->
 <div v-else class="bg-card/80 backdrop-blur-sm border border-border/50 rounded-xl overflow-hidden">
 <div
 v-for="node in allNodeCosts":key="node.node_id"
 class="divide-y divide-border/30"
 >
 <div
 v-for="(modelData, modelName) in node.models":key="modelName"
 class="px-3 py-2 flex items-center justify-between text-xs"
 >
 <span class="font-medium text-foreground truncate max-w-[140px]">{{ modelName }}</span>
 <div class="flex items-center gap-3 text-muted-foreground tabular-nums">
 <span>{{ formatTokenCount(modelData.input_tokens) }} in</span>
 <span>{{ formatTokenCount(modelData.output_tokens) }} out</span>
 <span class="font-medium text-foreground">{{ formatCost(modelData.total_cost_usd) }}</span>
 </div>
 </div>
 </div>
 <!-- 总计行 -->
 <div class="px-3 py-2 bg-muted/30 border-t border-border/50 flex items-center justify-between text-xs font-medium">
 <span>总计</span>
 <div class="flex items-center gap-3 tabular-nums">
 <span class="text-muted-foreground">
 {{ formatTokenCount(
 allNodeCosts.reduce((sum, n) =>
 sum + Object.values(n.models).reduce((s, m) => s + m.input_tokens + m.output_tokens, 0), 0,
 ),
 ) }} tokens
 </span>
 <span>
 {{ formatCost(
 allNodeCosts.reduce((sum, n) =>
 sum + Object.values(n.models).reduce((s, m) => s + (parseFloat(m.total_cost_usd) || 0), 0), 0,
 ).toString,
 ) }}
 </span>
 </div>
 </div>
 </div>
 </div>
 </div>
</template>
