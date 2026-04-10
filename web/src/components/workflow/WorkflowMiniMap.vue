<script setup lang="ts">
import { computed } from 'vue'
import { NODE_REGISTRY } from '~/types/workflow/registry'
interface NodeSummary {
 id: string
 node_type: string
 name: string
 position_x: number
 position_y: number
}
interface EdgeSummary {
 source_node_id: string
 target_node_id: string
}
const props = defineProps<{
 nodes: NodeSummary
 edges: EdgeSummary
 width?: number
 height?: number
}>
const svgWidth = computed( => props.width ?? 280)
const svgHeight = computed( => props.height ?? 100)
const NODE_RADIUS = 6
const PADDING = 14
const colorMap: Record<string, string> = {
 trigger: '#f59e0b',
 action: '#10b981',
 control: '#f59e0b',
 integration: '#10b981',
 ai: '#8b5cf6',
}
function getNodeColor(nodeType: string): string {
 const def = NODE_REGISTRY[nodeType as keyof typeof NODE_REGISTRY]
 if (def) return colorMap[def.category] ?? '#64748b'
 return '#64748b'
}
const layout = computed( => {
 const nodeList = props.nodes
 if (nodeList.length === 0) return { nodes:, edges: }
 const xs = nodeList.map(n => n.position_x)
 const ys = nodeList.map(n => n.position_y)
 const minX = Math.min(...xs)
 const maxX = Math.max(...xs)
 const minY = Math.min(...ys)
 const maxY = Math.max(...ys)
 const rangeX = maxX - minX || 1
 const rangeY = maxY - minY || 1
 const drawW = svgWidth.value - PADDING * 2
 const drawH = svgHeight.value - PADDING * 2
 const scale = Math.min(drawW / rangeX, drawH / rangeY, 1)
 const scaledW = rangeX * scale
 const scaledH = rangeY * scale
 const offsetX = PADDING + (drawW - scaledW) / 2
 const offsetY = PADDING + (drawH - scaledH) / 2
 const posMap = new Map<string, { x: number, y: number, color: string, nodeType: string, name: string }>
 const mappedNodes = nodeList.map((n) => {
 const x = nodeList.length === 1
 ? svgWidth.value / 2: offsetX + (n.position_x - minX) * scale
 const y = nodeList.length === 1
 ? svgHeight.value / 2: offsetY + (n.position_y - minY) * scale
 const color = getNodeColor(n.node_type)
 posMap.set(String(n.id), { x, y, color, nodeType: n.node_type, name: n.name })
 return { id: String(n.id), x, y, color, nodeType: n.node_type, name: n.name }
 })
 const mappedEdges = props.edges
 .map((e) => {
 const src = posMap.get(String(e.source_node_id))
 const tgt = posMap.get(String(e.target_node_id))
 if (!src || !tgt) return null
 return { x1: src.x, y1: src.y, x2: tgt.x, y2: tgt.y, color: src.color }
 })
 .filter(Boolean) as { x1: number, y1: number, x2: number, y2: number, color: string }
 return { nodes: mappedNodes, edges: mappedEdges }
})
</script>
<template>
 <svg:width="svgWidth":height="svgHeight":viewBox="`0 0 ${svgWidth} ${svgHeight}`"
 class="workflow-minimap"
 >
 <defs>
 <filter id="glow">
 <feGaussianBlur stdDeviation="2" result="blur" />
 <feMerge>
 <feMergeNode in="blur" />
 <feMergeNode in="SourceGraphic" />
 </feMerge>
 </filter>
 </defs>
 <!-- Edges -->
 <line
 v-for="(edge, i) in layout.edges":key="`e-${i}`":x1="edge.x1":y1="edge.y1":x2="edge.x2":y2="edge.y2":stroke="edge.color"
 stroke-opacity="0.3"
 stroke-width="1.5"
 />
 <!-- Nodes -->
 <g v-for="node in layout.nodes":key="node.id">
 <circle:cx="node.x":cy="node.y":r="NODE_RADIUS":fill="node.color"
 fill-opacity="0.2":stroke="node.color"
 stroke-opacity="0.6"
 stroke-width="1"
 />
 <circle:cx="node.x":cy="node.y":r="NODE_RADIUS * 0.45":fill="node.color"
 fill-opacity="0.8"
 />
 </g>
 <!-- Empty state -->
 <text
 v-if="layout.nodes.length === 0":x="svgWidth / 2":y="svgHeight / 2"
 text-anchor="middle"
 dominant-baseline="central"
 fill="currentColor"
 opacity="0.3"
 font-size="11"
 >
 暂无节点
 </text>
 </svg>
</template>
<style scoped>
.workflow-minimap {
 display: block;
 border-radius: 0.5rem;
}
</style>
