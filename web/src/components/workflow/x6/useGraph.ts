import type { Ref } from 'vue'
import type { Options as GraphOptions } from '@antv/x6'
import { Graph } from '@antv/x6'
import { Selection } from '@antv/x6-plugin-selection'
import { nextTick, onMounted, onUnmounted, shallowRef } from 'vue'
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
 const g = new Graph(mergedOptions)
 // Add selection plugin if enabled
 if (config?.selecting) {
 g.use(new Selection({
 enabled: true,
 rubberband: true,
 showNodeSelectionBox: true,
 }))
 }
 graph.value = g
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
