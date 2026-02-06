import type { Cell, Graph } from '@antv/x6'
import type { Ref, ShallowRef } from 'vue'
import { MiniMap } from '@antv/x6-plugin-minimap'
import { watch } from 'vue'
export interface UseMinimapOptions {
 /**
 * Width of the minimap in pixels.
 * @default 150
 */
 width?: number
 /**
 * Height of the minimap in pixels.
 * @default 100
 */
 height?: number
 /**
 * Padding inside the minimap in pixels.
 * @default 10
 */
 padding?: number
}
/**
 * Composable for enabling a minimap navigation panel on the X6 graph.
 *
 * The minimap shows a thumbnail of the entire canvas in the provided container.
 * Users can click to navigate or drag to move the viewport.
 *
 * IMPORTANT: The container element must be created in the component template.
 * This composable only attaches the minimap to the provided container ref.
 *
 * Recommended container styling (glassmorphism):
 * ```html
 * <div
 * ref="minimapContainerRef"
 * class="absolute right-4 bottom-4 rounded-xl
 * bg-card/70 backdrop-blur-sm border border-border/50
 * shadow-lg overflow-hidden"
 * />
 * ```
 *
 * @param graph - ShallowRef to the X6 Graph instance
 * @param containerRef - Ref to the container DOM element for the minimap
 * @param options - Optional configuration (width, height, padding)
 *
 * @example
 * ```vue
 * <script setup lang="ts">
 * const { graph } = useGraph(containerRef)
 * const minimapContainerRef = ref<HTMLDivElement>
 * useMinimap(graph, minimapContainerRef)
 * </script>
 *
 * <template>
 * <div ref="containerRef" class="relative w-full h-full">
 * <div
 * ref="minimapContainerRef"
 * class="absolute right-4 bottom-4 rounded-xl
 * bg-card/70 backdrop-blur-sm border border-border/50
 * shadow-lg overflow-hidden"
 * />
 * </div>
 * </template>
 * ```
 */
export function useMinimap(
 graph: ShallowRef<Graph | null>,
 containerRef: Ref<HTMLDivElement | undefined>,
 options: UseMinimapOptions = {},
) {
 const { width = 150, height = 100, padding = 10 } = options
 watch(
 [graph, containerRef],
 ([g, container]) => {
 // Wait for both graph and container to be available
 if (!g || !container) return
 g.use(
 new MiniMap({
 container,
 width,
 height,
 padding,
 scalable: false, // Disable zoom on minimap itself
 graphOptions: {
 // Return null for edges to skip rendering them in minimap.
 // Nodes render as simple rectangles by default when Vue shapes
 // can't be instantiated in the minimap's internal graph.
 createCellView(cell: Cell) {
 if (cell.isEdge) {
 return null
 }
 return undefined // Use default view for nodes
 },
 },
 }),
 )
 },
 { immediate: true },
 )
}
