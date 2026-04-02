<script setup lang="ts">
import type { CostBreakdown } from '~/types/execution'
import type { NodeExecution, TimelineData, WorkflowExecution } from '~/stores/useExecutionsStore'
import CostSummaryBar from '~/components/execution/CostSummaryBar.vue'
import ExecutionDagView from '~/components/execution/dag/ExecutionDagView.vue'
import ProviderCostTable from '~/components/execution/ProviderCostTable.vue'
import { Button } from '~/components/ui/button'
import { Card, CardContent } from '~/components/ui/card'
interface Props {
 loading: boolean
 error: string | null
 currentExecution: WorkflowExecution | null
 costData: CostBreakdown | null
 costLoading: boolean
 timelineData: TimelineData | null
 definitionChanged: boolean
 breakpoints: Set<string>
 isDebugExecution: boolean
 isPreExecutionFailure: boolean
 isTerminalStatus: boolean
}
defineProps<Props>
const emit = defineEmits<{
 nodeClick: [nodeExecution: NodeExecution | null, nodeId: string]
 resumeClick: [nodeId: string]
 debugRelease: [nodeId: string]
 debugSkip: [nodeId: string]
 toggleBreakpoint: [nodeId: string]
 retry:
}>
</script>
<template>
 <!-- 加载状态 -->
 <div v-if="loading && !currentExecution" class="flex-1 flex items-center justify-center">
 <span class="icon-[lucide--loader-2] w-8 animate-spin text-primary" />
 </div>
 <!-- 错误状态 -->
 <div v-else-if="error" class="flex-1 flex items-center justify-center ">
 <Card class="border-destructive max-w-md w-full">
 <CardContent class="py-6 text-center text-destructive">
 <span class="icon-[lucide--x-circle] w-12 mx-auto mb-4" />
 <p>{{ error }}</p>
 </CardContent>
 </Card>
 </div>
 <!-- DAG 画布 -->
 <div v-else-if="currentExecution" class="flex-1 min- relative">
 <!-- 无 workflow_definition 时的回退提示 -->
 <div
 v-if="!currentExecution.workflow_definition?.nodes?.length"
 class="h-full flex items-center justify-center text-muted-foreground"
 >
 <div class="text-center space-y-2">
 <span class="icon-[lucide--layout-grid] w-12 mx-auto opacity-30" />
 <p class="text-sm">
 此执行没有保存工作流定义快照，无法渲染 DAG 视图
 </p>
 <p class="text-xs text-muted-foreground/60">
 该执行可能在快照功能上线前创建
 </p>
 </div>
 </div>
 <!-- DAG 视图 -->
 <ExecutionDagView
 v-else:execution="currentExecution":timeline-data="timelineData":cost-data="costData":definition-changed="definitionChanged":breakpoints="breakpoints":is-debug-execution="isDebugExecution"
 @node-click="emit('nodeClick', $event, $event)"
 @resume-click="emit('resumeClick', $event)"
 @debug-release="emit('debugRelease', $event)"
 @debug-skip="emit('debugSkip', $event)"
 @toggle-breakpoint="emit('toggleBreakpoint', $event)"
 />
 <!-- 成本摘要浮层 -->
 <div class="absolute top-3 right-3 z-10 space-y-2">
 <CostSummaryBar:cost-summary="costData?.summary ?? null":loading="costLoading"
 />
 <ProviderCostTable
 v-if="costData && isTerminalStatus":cost-data="costData"
 />
 </div>
 <!-- 预执行失败：居中醒目展示 -->
 <div
 v-if="isPreExecutionFailure"
 class="absolute inset-0 z-20 flex items-center justify-center bg-background/60 backdrop-blur-sm"
 >
 <div class="max-w-md w-full mx-4">
 <div class="bg-red-50 dark:bg-red-900/20 border border-red-200/60 dark:border-red-800/50 rounded-2xl shadow-xl space-y-3">
 <div class="flex items-center gap-3">
 <div class="shrink-0 w-10 rounded-full bg-red-100 dark:bg-red-900/40 flex items-center justify-center">
 <span class="icon-[lucide--alert-triangle] w-5 text-red-500" />
 </div>
 <div>
 <h3 class="text-sm font-semibold text-red-700 dark:text-red-300">
 工作流启动失败
 </h3>
 <p class="text-xs text-red-500/70 dark:text-red-400/70">
 执行在节点运行前终止
 </p>
 </div>
 </div>
 <pre class="text-sm text-red-700 dark:text-red-300 whitespace-pre-wrap break-words bg-red-100/50 dark:bg-red-900/30 rounded-xl px-4 py-3">{{ currentExecution.error_message }}</pre>
 <div class="flex justify-end">
 <Button
 variant="outline"
 size="sm"
 class="border-red-200 dark:border-red-800 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/30"
 @click="emit('retry')"
 >
 <span class="icon-[lucide--rotate-ccw] w-3.5 .5 mr-1.5" />
 重新执行
 </Button>
 </div>
 </div>
 </div>
 </div>
 <!-- 运行时错误信息浮层 -->
 <Transition
 enter-active-class="transition-all duration-300 ease-out"
 enter-from-class="translate-y-2 opacity-0"
 enter-to-class="translate-y-0 opacity-100"
 leave-active-class="transition-all duration-200 ease-in"
 leave-from-class="translate-y-0 opacity-100"
 leave-to-class="translate-y-2 opacity-0"
 >
 <div
 v-if="currentExecution.error_message && !isPreExecutionFailure"
 class="absolute bottom-4 left-4 right-4 max-w-lg mx-auto z-10"
 >
 <div class="bg-red-50 dark:bg-red-900/30 backdrop-blur-sm border border-red-200/50 dark:border-red-800/50 rounded-2xl px-4 py-3 shadow-lg">
 <div class="flex items-start gap-2">
 <span class="icon-[lucide--alert-circle] w-4 text-red-500 mt-0.5 shrink-0" />
 <p class="text-sm text-red-700 dark:text-red-300 line-clamp-3">
 {{ currentExecution.error_message }}
 </p>
 </div>
 </div>
 </div>
 </Transition>
 </div>
</template>
