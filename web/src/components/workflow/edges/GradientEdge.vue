<script setup lang="ts">
/**
 * GradientEdge - Custom Vue Flow edge with gradient coloring and glow effect
 *
 * Used for "perfect match" connections to visually distinguish them from regular edges.
 * Features:
 * - SVG linearGradient from source to target node colors
 * - Glow effect using feGaussianBlur filter
 * - Thicker stroke (3px) compared to default edges (2px)
 * - Warning variant with red dashed stroke for schema mismatch
 */
import type { EdgeProps } from '@vue-flow/core'
import { getBezierPath } from '@vue-flow/core'
import { computed } from 'vue'
const props = defineProps<EdgeProps>
// Warning state from edge data
const hasWarning = computed( => props.data?.hasWarning === true)
const warningMessage = computed( => (props.data?.warning as string) || '')
// Warning color (red-500)
const warningColor = 'hsl(0 84% 60%)'
// Unique gradient ID per edge to avoid conflicts
const gradientId = computed( => `gradient-${props.id}`)
const glowFilterId = computed( => `glow-${props.id}`)
// Calculate bezier path for the edge
const pathData = computed( => {
 const [path, labelX, labelY] = getBezierPath({
 sourceX: props.sourceX,
 sourceY: props.sourceY,
 targetX: props.targetX,
 targetY: props.targetY,
 sourcePosition: props.sourcePosition,
 targetPosition: props.targetPosition,
 })
 return { path, labelX, labelY }
})
// Node type to color mapping
const nodeColorMap: Record<string, string> = {
 // Triggers - blue
 manual_trigger: '#3b82f6',
 webhook_trigger: '#3b82f6',
 schedule_trigger: '#3b82f6',
 feishu_event_trigger: '#3b82f6',
 // AI nodes - purple
 ai_prompt: '#8b5cf6',
 ai_coding_dispatcher: '#8b5cf6',
 ai_variable_extractor: '#8b5cf6',
 context_retrieval: '#8b5cf6',
 ai_technical_plan: '#8b5cf6',
 // Integration - orange
 fetch_work_item: '#f59e0b',
 fetch_project_info: '#f59e0b',
 // Data/Control - cyan
 variable_extractor: '#06b6d4',
 condition: '#06b6d4',
 wait_feishu_field: '#06b6d4',
 delay: '#06b6d4',
 parallel: '#06b6d4',
 // Actions - green
 http_request: '#10b981',
 create_branch: '#10b981',
 code_implement: '#10b981',
 approval: '#10b981',
 human_approval: '#10b981',
}
// Default color if node type not found
const defaultColor = '#6366f1' // indigo as fallback
// Extract colors from edge data or use defaults based on node type
const sourceColor = computed( => {
 if (props.data?.sourceColor) {
 return props.data.sourceColor as string
 }
 const nodeType = props.data?.sourceNodeType as string | undefined
 return nodeType ? (nodeColorMap[nodeType] || defaultColor): defaultColor
})
const targetColor = computed( => {
 if (props.data?.targetColor) {
 return props.data.targetColor as string
 }
 const nodeType = props.data?.targetNodeType as string | undefined
 return nodeType ? (nodeColorMap[nodeType] || defaultColor): defaultColor
})
</script>
<template>
 <defs>
 <!-- Gradient definition with userSpaceOnUse for correct direction -->
 <linearGradient:id="gradientId"
 gradientUnits="userSpaceOnUse":x1="sourceX":y1="sourceY":x2="targetX":y2="targetY"
 >
 <stop offset="0%":stop-color="sourceColor" />
 <stop offset="100%":stop-color="targetColor" />
 </linearGradient>
 <!-- Glow filter for visual emphasis -->
 <filter:id="glowFilterId" x="-50%" y="-50%" width="200%" height="200%">
 <feGaussianBlur stdDeviation="3" result="blur" />
 <feMerge>
 <feMergeNode in="blur" />
 <feMergeNode in="SourceGraphic" />
 </feMerge>
 </filter>
 </defs>
 <!-- Glow layer (behind main edge) -->
 <path:d="pathData.path":stroke="hasWarning ? warningColor: `url(#${gradientId})`"
 stroke-width="6"
 fill="none":filter="`url(#${glowFilterId})`":opacity="hasWarning ? 0.3: 0.4"
 class="vue-flow__edge-path-glow"
 />
 <!-- Main edge path -->
 <path:id="id":d="pathData.path":stroke="hasWarning ? warningColor: `url(#${gradientId})`":stroke-dasharray="hasWarning ? '8 4': undefined"
 stroke-width="3"
 fill="none"
 class="vue-flow__edge-path"
 />
 <!-- Warning indicator at edge midpoint -->
 <g v-if="hasWarning":transform="`translate(${pathData.labelX}, ${pathData.labelY})`">
 <circle r="10":fill="warningColor" />
 <text
 text-anchor="middle"
 dy="4"
 fill="white"
 font-size="12"
 font-weight="bold"
 >!</text>
 <!-- Tooltip title -->
 <title>{{ warningMessage }}</title>
 </g>
</template>
