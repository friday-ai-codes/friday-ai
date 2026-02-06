import type { Graph } from '@antv/x6'
import type { ShallowRef } from 'vue'
import { Snapline } from '@antv/x6-plugin-snapline'
import { watch } from 'vue'
import './snapline.css'
export interface UseSnaplineOptions {
 /**
 * Snap tolerance in pixels (how close nodes need to be to trigger alignment).
 * Recommended range: 5-10px.
 * @default 8
 */
 tolerance?: number
}
/**
 * Composable for enabling alignment snaplines on the X6 graph.
 *
 * Shows visual alignment guides when dragging nodes near other node edges.
 * Nodes automatically snap to aligned positions when guides appear.
 *
 * Uses theme primary color for snapline styling via snapline.css.
 *
 * @param graph - ShallowRef to the X6 Graph instance
 * @param options - Optional configuration (tolerance)
 *
 * @example
 * ```vue
 * <script setup lang="ts">
 * const { graph } = useGraph(containerRef)
 * useSnapline(graph, { tolerance: 8 })
 * </script>
 * ```
 */
export function useSnapline(
 graph: ShallowRef<Graph | null>,
 options: UseSnaplineOptions = {},
) {
 const { tolerance = 8 } = options
 watch(
 graph,
 (g) => {
 if (!g) return
 g.use(
 new Snapline({
 enabled: true,
 tolerance,
 sharp: false, // Full-length snaplines (not just at intersection)
 resizing: true, // Show snaplines during node resize
 className: 'x6-snapline-primary', // Custom class for theme styling
 }),
 )
 },
 { immediate: true },
 )
}
