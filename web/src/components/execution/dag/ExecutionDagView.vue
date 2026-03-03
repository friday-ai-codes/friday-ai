<script setup lang="ts">
/**
 * ExecutionDagView — Vue Flow 只读画布，渲染执行 DAG
 *
 * 禁用拖拽/连线，保留缩放/平移/选中。
 * 通过 execution prop 响应式更新节点状态（WebSocket 驱动）。
 */
import type { NodeMouseEvent } from '@vue-flow/core'
import { VueFlow, useVueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import '@vue-flow/controls/dist/style.css'
import { computed, toRef } from 'vue'
import type { WorkflowExecution, NodeExecution, TimelineData } from '~/stores/useExecutionsStore'
import { useExecutionDag, executionNodeTypes, executionEdgeTypes } from './composables/useExecutionDag'
import { useNodeTimer } from './composables/useNodeTimer'
const props = defineProps<{
 execution: WorkflowExecution
 timelineData?: TimelineData | null
}>
const emit = defineEmits<{
 'node-click': [nodeExecution: NodeExecution | null, nodeId: string]
}>
const executionRef = toRef(props, 'execution')
const timelineRef = computed( => props.timelineData ?? null)
const { dagNodes, dagEdges } = useExecutionDag(executionRef, timelineRef)
// 运行中节点实时计时
const nodeExecutionsRef = computed( => props.execution.node_executions ?? )
const { elapsedMap } = useNodeTimer(nodeExecutionsRef)
// 将 elapsedMap 注入到 dagNodes 的 data.elapsed 中
const nodesWithElapsed = computed( => {
 return dagNodes.value.map(node => {
 const elapsed = elapsedMap.value[node.id]
 if (elapsed !== undefined) {
 return {
 ...node,
 data: {
 ...node.data,
 elapsed,
 },
 }
 }
 return node
 })
})
const { onNodeClick } = useVueFlow
// 处理节点点击 — 查找对应的 NodeExecution 并 emit
onNodeClick(({ node }: NodeMouseEvent) => {
 const ne = props.execution.node_executions?.find(
 ne => ne.node === node.id,
 ) ?? null
 emit('node-click', ne, node.id)
})
</script>
<template>
 <div class="h-full w-full bg-background">
 <VueFlow:nodes="nodesWithElapsed":edges="dagEdges":node-types="executionNodeTypes":edge-types="executionEdgeTypes":nodes-draggable="false":nodes-connectable="false":elements-selectable="true":zoom-on-scroll="true":pan-on-scroll="true":pan-on-drag="true"
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
