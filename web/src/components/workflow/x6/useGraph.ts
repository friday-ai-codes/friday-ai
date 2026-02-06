import type { Options as GraphOptions } from '@antv/x6'
import type { Ref } from 'vue'
import { Graph, Selection } from '@antv/x6'
import { History } from '@antv/x6-plugin-history'
import { Keyboard } from '@antv/x6-plugin-keyboard'
import { nextTick, onMounted, onUnmounted, shallowRef } from 'vue'
import { applyEdgeGradientFromNodes } from './edges'
import { getConnectingConfig } from './ports'
import './edges/edge-animations.css'
import './selection.css'
/**
 * Default Graph configuration optimized for workflow editing.
 *
 * - autoResize: Automatically resize graph when container changes
 * - grid: Dot pattern grid for visual alignment
 * - panning: Enable drag to pan the canvas
 * - mousewheel: Ctrl/Cmd + scroll to zoom
 */
const defaultOptions: Partial<GraphOptions> = {
 autoResize: true,
 grid: {
 visible: true,
 type: 'dot',
 size: 20,
 args: {
 color: 'rgba(160, 160, 160, 0.4)',
 thickness: 1,
 },
 },
 panning: {
 enabled: true,
 },
 mousewheel: {
 enabled: true,
 factor: 1.1,
 modifiers: ['ctrl', 'meta'],
 },
}
export interface UseGraphOptions {
 /** Override default Graph configuration */
 options?: Partial<GraphOptions>
 /** Enable selection plugin */
 selecting?: boolean
 /** Enable port-based connecting with validation (default: true) */
 connecting?: boolean
 /**
 * Enable history plugin for undo/redo.
 * - `true`: Enable with default stackSize of 50
 * - `{ stackSize: number }`: Enable with custom stack size
 * - `false` or omitted: Disabled
 *
 * When enabled, also binds keyboard shortcuts:
 * - Ctrl+Z / Cmd+Z: Undo
 * - Ctrl+Shift+Z / Cmd+Shift+Z: Redo
 *
 * Note: For full control over history (e.g., canUndo/canRedo state for toolbar),
 * use the separate `useHistory` composable instead.
 */
 history?: boolean | { stackSize?: number }
}
/**
 * Composable for managing X6 Graph instance lifecycle.
 *
 * IMPORTANT: Uses shallowRef to prevent Vue's deep reactivity from
 * breaking Graph internals. Automatically disposes the Graph on
 * component unmount to prevent memory leaks.
 *
 * @param containerRef - Ref to the container DOM element
 * @param config - Optional configuration overrides
 * @returns Object containing the graph shallowRef
 *
 * @example
 * ```vue
 * <script setup lang="ts">
 * const containerRef = ref<HTMLDivElement>
 * const { graph } = useGraph(containerRef)
 *
 * // Access graph instance (may be null before mount)
 * watchEffect( => {
 * if (graph.value) {
 * graph.value.addNode({ ... })
 * }
 * })
 * </script>
 *
 * <template>
 * <div ref="containerRef" class="w-full h-full" />
 * </template>
 * ```
 */
export function useGraph(
 containerRef: Ref<HTMLDivElement | undefined>,
 config?: UseGraphOptions,
) {
 // CRITICAL: Use shallowRef to avoid Vue's deep reactivity proxy
 // wrapping the Graph instance, which breaks its internal state.
 const graph = shallowRef<Graph | null>(null)
 onMounted(async => {
 // Wait for DOM to be fully rendered
 await nextTick
 if (!containerRef.value) {
 console.error('[useGraph] Container element not found')
 return
 }
 // Merge user options with defaults
 const mergedOptions: GraphOptions = {
 ...defaultOptions,
 ...config?.options,
 container: containerRef.value,
 }
 // Add selecting config if enabled (X6 3.x built-in)
 // Use type assertion as X6 types don't fully expose plugin options
 if (config?.selecting) {;(mergedOptions as Record<string, unknown>).selecting = {
 enabled: true,
 rubberband: true,
 multiple: true,
 movable: true,
 showNodeSelectionBox: true,
 }
 }
 // Add connecting config with port validation (enabled by default)
 if (config?.connecting !== false) {
 const connectingConfig = getConnectingConfig
 mergedOptions.connecting = {
 ...connectingConfig,
 // Use gradient-edge shape for new connections
 createEdge {
 return this.createEdge({
 shape: 'gradient-edge',
 attrs: {
 line: {
 stroke: '#5B8FF9',
 strokeWidth: 2,
 },
 },
 })
 },
 }
 }
 const graphInstance = new Graph(mergedOptions)
 // Enable Selection plugin if requested (X6 3.x requires explicit plugin use)
 if (config?.selecting) {
 graphInstance.use(new Selection({
 enabled: true,
 rubberband: true,
 multiple: true,
 movable: true,
 showNodeSelectionBox: true,
 }))
 }
 // Enable History plugin if requested
 if (config?.history) {
 const stackSize = typeof config.history === 'object'
 ? config.history.stackSize ?? 50: 50
 graphInstance.use(new History({
 enabled: true,
 stackSize,
 }))
 // Enable Keyboard plugin for undo/redo shortcuts
 graphInstance.use(new Keyboard({
 enabled: true,
 global: true, // Bind to document for shortcuts to work without focus
 }))
 // Bind undo shortcuts (Ctrl+Z on Windows/Linux, Cmd+Z on Mac)
 graphInstance.bindKey(['ctrl+z', 'cmd+z'], => {
 if (graphInstance.canUndo) {
 graphInstance.undo
 }
 return false // Prevent default browser undo
 })
 // Bind redo shortcuts (Ctrl+Shift+Z on Windows/Linux, Cmd+Shift+Z on Mac)
 graphInstance.bindKey(['ctrl+shift+z', 'cmd+shift+z'], => {
 if (graphInstance.canRedo) {
 graphInstance.redo
 }
 return false // Prevent default browser redo
 })
 // Batch drag operations so entire drag = one undo step
 let isBatching = false
 graphInstance.on('node:move', => {
 if (!isBatching) {
 graphInstance.startBatch('node-move')
 isBatching = true
 }
 })
 graphInstance.on('node:moved', => {
 if (isBatching) {
 graphInstance.stopBatch('node-move')
 isBatching = false
 }
 })
 }
 // Apply gradient coloring when edge connection completes
 graphInstance.on('edge:connected', ({ edge }) => {
 applyEdgeGradientFromNodes(graphInstance, edge.id)
 })
 graph.value = graphInstance
 })
 onUnmounted( => {
 // CRITICAL: Must dispose Graph to prevent memory leaks.
 // Graph holds references to DOM elements, event listeners,
 // and internal state that won't be garbage collected otherwise.
 if (graph.value) {
 graph.value.dispose
 graph.value = null
 }
 })
 return {
 /** The X6 Graph instance (null before mount, null after unmount) */
 graph,
 }
}
