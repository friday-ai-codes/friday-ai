<script setup lang="ts">
import type { Graph, Node } from '@antv/x6'
import { computed, inject, onMounted, onUnmounted, ref } from 'vue'
/**
 * X6BaseNode - Base component for X6 graph nodes.
 *
 * Uses X6's inject pattern to access node and graph instances.
 * Provides reactive state for selection/hover and exposes data via scoped slot.
 *
 * Glassmorphism styling per CONTEXT.md decisions:
 * - backdrop-blur-sm (light blur)
 * - border-border (standard border)
 * - shadow-md (medium shadow)
 * - rounded-xl (12px radius)
 */
// X6 inject pattern - these are provided by @antv/x6-vue-shape
const getNode = inject< => Node>('getNode')!
const getGraph = inject< => Graph>('getGraph')!
const node = getNode
const graph = getGraph
// Reactive state
const nodeData = ref<Record<string, unknown>>(node.getData || {})
const isSelected = ref(false)
const isHovered = ref(false)
// Computed properties for common node data
const isDragPreview = computed( => {
 return nodeData.value.isDragPreview === true
})
const label = computed( => {
 const data = nodeData.value
 return (data.name as string) || (data.label as string) || 'Untitled'
})
const description = computed( => {
 return (nodeData.value.description as string) || ''
})
const nodeType = computed( => {
 return (nodeData.value.node_type as string) || ''
})
// shortId for display (from node data, set by loadFromStore)
// Falls back to truncated UUID for new nodes before save
const shortId = computed( => {
 return (nodeData.value.shortId as string) || node.id.slice(0, 8)
})
const nodeId = computed( => node.id)
const isDisabled = computed( => {
 return (nodeData.value.disabled as boolean) || false
})
// Event handlers
function handleDataChange({ current }: { current: Record<string, unknown> }) {
 nodeData.value = current || {}
}
function handleCellSelected({ cell }: { cell: { id: string } }) {
 if (cell.id === node.id) {
 isSelected.value = true
 }
}
function handleCellUnselected({ cell }: { cell: { id: string } }) {
 if (cell.id === node.id) {
 isSelected.value = false
 }
}
function handleNodeMouseEnter({ node: targetNode }: { node: Node }) {
 if (targetNode.id === node.id) {
 isHovered.value = true
 }
}
function handleNodeMouseLeave({ node: targetNode }: { node: Node }) {
 if (targetNode.id === node.id) {
 isHovered.value = false
 }
}
// Setup event listeners
onMounted( => {
 // Node data changes
 node.on('change:data', handleDataChange)
 // Selection state from graph
 graph.on('cell:selected', handleCellSelected)
 graph.on('cell:unselected', handleCellUnselected)
 // Hover state from graph
 graph.on('node:mouseenter', handleNodeMouseEnter)
 graph.on('node:mouseleave', handleNodeMouseLeave)
 // Check initial selection state
 isSelected.value = graph.isSelected(node)
})
// Cleanup event listeners to prevent memory leaks
onUnmounted( => {
 node.off('change:data', handleDataChange)
 graph.off('cell:selected', handleCellSelected)
 graph.off('cell:unselected', handleCellUnselected)
 graph.off('node:mouseenter', handleNodeMouseEnter)
 graph.off('node:mouseleave', handleNodeMouseLeave)
})
</script>
<template>
 <div
 class="x6-node":class="{
 'x6-node--selected': isSelected,
 'x6-node--hovered': isHovered,
 'x6-node--disabled': isDisabled,
 'x6-node--preview': isDragPreview,
 }"
 >
 <slot:node-data="nodeData":node-id="nodeId":short-id="shortId":label="label":description="description":node-type="nodeType":is-selected="isSelected":is-hovered="isHovered":is-disabled="isDisabled"
 />
 </div>
</template>
<style scoped>
/**
 * X6 Base Node Styles
 *
 * Glassmorphism styling per CONTEXT.md decisions:
 * - Blur: backdrop-blur-sm (light blur, more transparent)
 * - Border: border-border (standard, clear boundary)
 * - Shadow: shadow-md (medium, layered feel)
 * - Radius: rounded-xl (12px)
 * - Transition: transition-all duration-300
 *
 * Dimensions per discretion:
 * - Min: 160x60
 * - Max: 280x160
 */
.x6-node {
 /* Dimensions */
 min-width: 160px;
 max-width: 280px;
 min-height: 60px;
 max-height: 160px;
 /* Glassmorphism background */
 background: color-mix(in srgb, var(--color-card, #fff) 80%, transparent);
 backdrop-filter: blur(4px); /* sm blur */
 /* Border */
 border: 1px solid var(--color-border, hsl(219 30% 85%));
 border-radius: 12px; /* rounded-xl */
 /* Shadow - shadow-md equivalent */
 box-shadow:
 0 4px 6px -1px rgb(0 0 0 / 0.1),
 0 2px 4px -2px rgb(0 0 0 / 0.1);
 /* Transition */
 transition: all 0.3s ease;
 /* Layout */
 box-sizing: border-box;
 overflow: hidden;
}
/* Hovered state - lighter border highlight */
.x6-node--hovered {
 border-color: color-mix(in srgb, var(--color-primary, hsl(213 47% 47%)) 30%, var(--color-border, hsl(219 30% 85%)));
}
/* Selected state - primary border */
.x6-node--selected {
 border-color: var(--color-primary, hsl(213 47% 47%));
 box-shadow:
 0 0 0 2px color-mix(in srgb, var(--color-primary, hsl(213 47% 47%)) 20%, transparent),
 0 4px 6px -1px rgb(0 0 0 / 0.1),
 0 2px 4px -2px rgb(0 0 0 / 0.1);
}
/* Disabled state */
.x6-node--disabled {
 filter: grayscale(1);
 opacity: 0.5;
 pointer-events: none;
}
/* Preview state - 50% opacity during drag */
.x6-node--preview {
 opacity: 0.5;
}
</style>
