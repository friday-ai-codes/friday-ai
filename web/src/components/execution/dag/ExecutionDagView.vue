<script setup lang="ts">
/**
 * ExecutionDagView — Vue Flow 只读画布，渲染执行 DAG
 *
 * 禁用拖拽/连线，保留缩放/平移/选中。
 * 通过 execution prop 响应式更新节点状态（WebSocket 驱动）。
 */
import type { NodeMouseEvent } from '@vue-flow/core'
import type { NodeExecution, TimelineData, WorkflowExecution } from '~/stores/useExecutionsStore'
import type { CostBreakdown, NodeCost } from '~/types/execution'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { useVueFlow, VueFlow } from '@vue-flow/core'
import { computed, toRef } from 'vue'
import { executionEdgeTypes, executionNodeTypes, useExecutionDag } from './composables/useExecutionDag'
import { useNodeTimer } from './composables/useNodeTimer'
import '@vue-flow/controls/dist/style.css'
const props = defineProps<{
 execution: WorkflowExecution
 timelineData?: TimelineData | null
 costData?: CostBreakdown | null
 /** 工作流定义是否在执行后发生变更（Phase） */
 definitionChanged?: boolean
 /** Phase: 已设置断点的节点 ID 集合 */
 breakpoints?: Set<string>
 /** Phase: 是否为调试执行 */
 isDebugExecution?: boolean
}>
const emit = defineEmits<{
 nodeClick: [nodeExecution: NodeExecution | null, nodeId: string]
 /** Phase: 失败节点「从此继续」点击 */
 resumeClick: [nodeId: string]
 /** Phase: 子步骤详情跳转 */
 subStepClick: [nodeExecutionId: string, subStepId: string]
 /** Phase: 调试放行 */
 debugRelease: [nodeId: string]
 /** Phase: 调试跳过 */
 debugSkip: [nodeId: string]
 /** Phase: 切换断点 */
 toggleBreakpoint: [nodeId: string]
}>
const executionRef = toRef(props, 'execution')
const timelineRef = computed( => props.timelineData ?? null)
const definitionChangedRef = computed( => props.definitionChanged ?? false)
const { dagNodes, dagEdges } = useExecutionDag(executionRef, timelineRef, definitionChangedRef)
// 运行中节点实时计时
const nodeExecutionsRef = computed( => props.execution.node_executions ?? )
const { elapsedMap } = useNodeTimer(nodeExecutionsRef)
// 从 costData 构建节点成本 map
const nodeCostMap = computed<Record<string, NodeCost>>( => {
 if (!props.costData?.nodes)
 return {}
 const map: Record<string, NodeCost> = {}
 for (const node of props.costData.nodes) {
 let totalTokens = 0
 let totalCostUsd = 0
 for (const model of Object.values(node.models)) {
 totalTokens += model.input_tokens + model.output_tokens
 totalCostUsd += Number.parseFloat(model.total_cost_usd) || 0
 }
 map[node.node_id] = {
 totalCostUsd: totalCostUsd.toString,
 totalTokens,
 models: node.models,
 }
 }
 return map
})
// 将 elapsedMap 和 costMap 注入到 dagNodes，同时注入 resume 回调
const nodesWithData = computed( => {
 return dagNodes.value.map((node) => {
 const elapsed = elapsedMap.value[node.id]
 const cost = nodeCostMap.value[node.id]
 return {
 ...node,
 data: {
 ...node.data,
 ...(elapsed !== undefined && { elapsed }),
 ...(cost && { cost }),
 onResumeClick: (nodeId: string) => emit('resumeClick', nodeId),
 onSubStepClick: (nodeExecutionId: string, subStepId: string) =>
 emit('subStepClick', nodeExecutionId, subStepId),
 // Phase: 调试操作回调
 onDebugRelease: (nodeId: string) => emit('debugRelease', nodeId),
 onDebugSkip: (nodeId: string) => emit('debugSkip', nodeId),
 // Phase: 断点数据
 hasBreakpoint: props.breakpoints?.has(node.id) ?? false,
 onToggleBreakpoint: (nodeId: string) => emit('toggleBreakpoint', nodeId),
 isDebugExecution: props.isDebugExecution ?? false,
 },
 }
 })
})
const { onNodeClick } = useVueFlow
// 处理节点点击 — 查找对应的 NodeExecution 并 emit
onNodeClick(({ node }: NodeMouseEvent) => {
 const ne = props.execution.node_executions?.find(
 ne => ne.node === node.id,
 ) ?? null
 emit('nodeClick', ne, node.id)
})
</script>
<template>
 <div class="h-full w-full bg-background">
 <VueFlow:nodes="nodesWithData":edges="dagEdges":node-types="executionNodeTypes":edge-types="executionEdgeTypes":nodes-draggable="false":nodes-connectable="false":elements-selectable="true":zoom-on-scroll="true":pan-on-scroll="true":pan-on-drag="true"
 fit-view-on-init:max-zoom="1.5":min-zoom="0.2"
 >
 <Background
 variant="dots":gap="35":size="1.5"
 color="#3b82f620"
 />
 <Controls
 position="bottom-left":show-zoom="true":show-fit-view="true":show-interactive="false"
 class="!bg-card/80 !backdrop-blur-sm !border !border-border/50 !rounded-2xl !shadow-lg"
 />
 </VueFlow>
 </div>
</template>
