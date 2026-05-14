<script setup lang="ts">
/**
 * GraphRAG 二跳扩散画布主入口（Phase Plan，work item §5.2）
 *
 * 复用 Plan 已 freeze 的 props/emit 契约：
 * props: hop1Neighbors / hop2Neighbors / sourceChunks / loading
 * emit: node-click(chunkId)
 *
 * 子结构：
 * - useDiffusionGraph composable 做数据 → Vue Flow Node/Edge 转换 + dagre 布局
 * - <DiffusionNode> / <DiffusionEdge> 自定义节点 / 边
 * - Background / Controls / MiniMap + 图例 Panel(top-left) + 折叠按钮 Panel(bottom-right)
 * - 截断 banner / 空状态 / loading 遮罩
 *
 * 折叠 / 截断模板已挂 v-if 占位，但本 plan composable 永远返回 false（Plan 接力
 * 扩展 useDiffusionGraph 即可激活，**不再改本组件**，保证 Wave 真并行）。
 */
import type { Edge, EdgeComponent, EdgeTypesObject, Node, NodeComponent, NodeTypesObject } from '@vue-flow/core'
import type { NeighborMetadata } from '~/api/codegraph'
import type { SourceChunk } from '~/composables/useDiffusionGraph'
import type { EdgeType } from '~/lib/diffusionEdgeColors'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { Panel, VueFlow } from '@vue-flow/core'
import { MiniMap } from '@vue-flow/minimap'
import { markRaw, toRef } from 'vue'
import { useDiffusionGraph } from '~/composables/useDiffusionGraph'
import { DIFFUSION_EDGE_COLORS } from '~/lib/diffusionEdgeColors'
import DiffusionEdge from './DiffusionEdge.vue'
import DiffusionNode from './DiffusionNode.vue'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/controls/dist/style.css'
import '@vue-flow/minimap/dist/style.css'
const props = defineProps<{
 hop1Neighbors: NeighborMetadata
 hop2Neighbors: NeighborMetadata
 sourceChunks: SourceChunk
 loading: boolean
}>
const emit = defineEmits<{
 (e: 'node-click', chunkId: string): void
}>
const nodeTypes: NodeTypesObject = { diffusion: markRaw(DiffusionNode) as NodeComponent }
const edgeTypes: EdgeTypesObject = { diffusion: markRaw(DiffusionEdge) as EdgeComponent }
const {
 flowNodes,
 flowEdges,
 totalNeighbors,
 foldedCount,
 hasFoldedNeighbors,
 truncated,
 expandFolded,
} = useDiffusionGraph(
 toRef(props, 'hop1Neighbors'),
 toRef(props, 'hop2Neighbors'),
 toRef(props, 'sourceChunks'),
)
const EDGE_TYPES_LEGEND: EdgeType = [
 'CALL',
 'IMPORT',
 'SAME_FILE',
 'TEST_OF',
 'CO_CHANGED',
 'SEMANTIC',
]
function onVueFlowNodeClick(evt: { node: Pick<Node, 'id'> }) {
 // eslint-disable-next-line vue/custom-event-name-casing -- Plan freeze 的契约 (@node-click) 使用 kebab-case
 emit('node-click', evt.node.id)
}
defineExpose({ onVueFlowNodeClick })
</script>
<template>
 <div class="h-[520px] relative">
 <!-- 截断警告 banner（>200 节点；work item §5.6）—— Plan 激活 -->
 <div
 v-if="truncated"
 class="absolute top-3 left-1/2 -translate-x-1/2 z-20 flex items-center gap-2 px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-500/40 text-xs text-amber-800"
 role="alert"
 >
 <span class="icon-[lucide--alert-triangle] w-3.5 .5" />
 扩散图节点过多，已截断到 200，请收窄查询条件
 </div>
 <!-- 无数据空状态 -->
 <div
 v-if="!loading && totalNeighbors === 0"
 class="flex flex-col items-center justify-center h-full text-center"
 role="status"
 >
 <span class="icon-[lucide--git-fork] text-4xl text-muted-foreground mb-3" />
 <p class="text-base font-semibold">
 无关联代码
 </p>
 <p class="text-sm text-muted-foreground mt-1">
 当前查询未召回任何图谱邻居，请尝试更具体的查询
 </p>
 </div>
 <!-- Vue Flow 画布 -->
 <VueFlow
 v-else:nodes="flowNodes as Node":edges="flowEdges as Edge":node-types="nodeTypes":edge-types="edgeTypes":min-zoom="0.2":max-zoom="2.0":fit-view-on-init="true":pan-on-scroll="false":prevent-scrolling="true":nodes-draggable="true":nodes-connectable="false"
 @node-click="onVueFlowNodeClick"
 >
 <Background />
 <Controls />
 <MiniMap />
 <!-- 图例（top-left）：6 类 edge_type 颜色 + 文字 -->
 <Panel
 position="top-left"
 class="bg-card/80 backdrop-blur-sm rounded-lg px-3 py-2 flex flex-wrap items-center gap-3 max-w-[420px]"
 >
 <span
 v-for="type in EDGE_TYPES_LEGEND":key="type"
 class="text-xs text-muted-foreground flex items-center gap-1.5"
 >
 <svg width="10" height="10" viewBox="0 0 10 10">
 <circle cx="5" cy="5" r="5":fill="DIFFUSION_EDGE_COLORS[type]" />
 </svg>
 {{ type }}
 </span>
 </Panel>
 <!-- "显示更多 (N+)" 按钮：Plan 激活 -->
 <Panel
 v-if="hasFoldedNeighbors"
 position="bottom-right"
 class="flex gap-2"
 >
 <button
 type="button"
 class="bg-card/90 backdrop-blur-sm text-xs inline-flex items-center px-3 rounded-md border border-border/50 hover:bg-muted/40"
 @click="expandFolded"
 >
 <span class="icon-[lucide--chevron-down] mr-1.5 w-3.5 .5" />
 显示更多 ({{ foldedCount }}+)
 </button>
 </Panel>
 </VueFlow>
 <!-- 加载遮罩 -->
 <div
 v-if="loading"
 class="absolute inset-0 flex items-center justify-center bg-background/50 z-10"
 >
 <span class="icon-[lucide--loader-circle] animate-spin w-8 text-primary" />
 </div>
 </div>
</template>
