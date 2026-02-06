import type { Graph } from '@antv/x6'
import type { ShallowRef } from 'vue'
import { History, Keyboard } from '@antv/x6'
import { computed, ref, watch } from 'vue'
import { toast } from 'vue-sonner'
export interface UseHistoryOptions {
 /** Maximum number of undo steps (default: 50) */
 stackSize?: number
 /** Enable keyboard shortcuts for undo/redo (default: true) */
 enableKeyboard?: boolean
}
/**
 * Composable for managing undo/redo history on X6 Graph.
 *
 * Integrates History and Keyboard plugins to provide:
 * - Undo/redo operations with reactive canUndo/canRedo state
 * - Keyboard shortcuts: Ctrl+Z (undo), Ctrl+Shift+Z (redo)
 * - Drag operation batching (entire drag = single undo step)
 * - Toast feedback on undo/redo execution
 *
 * @param graph - ShallowRef to the X6 Graph instance
 * @param options - Configuration options
 *
 * @example
 * ```vue
 * <script setup lang="ts">
 * const containerRef = ref<HTMLDivElement>
 * const { graph } = useGraph(containerRef)
 * const { canUndo, canRedo, undo, redo } = useHistory(graph)
 * </script>
 * ```
 */
export function useHistory(
 graph: ShallowRef<Graph | null>,
 options: UseHistoryOptions = {},
) {
 const { stackSize = 50, enableKeyboard = true } = options
 // Track batching state for drag operations
 const isBatching = ref(false)
 // Reactive state for UI binding
 const canUndo = computed( => graph.value?.canUndo ?? false)
 const canRedo = computed( => graph.value?.canRedo ?? false)
 // Initialize plugins when graph becomes available
 watch(graph, (g) => {
 if (!g) return
 // History plugin for undo/redo stack
 g.use(new History({
 enabled: true,
 stackSize,
 }))
 // Keyboard plugin for shortcuts
 if (enableKeyboard) {
 g.use(new Keyboard({
 enabled: true,
 global: true, // Bind to document for shortcuts to work without focus
 }))
 // Bind undo shortcuts (Ctrl+Z on Windows/Linux, Cmd+Z on Mac)
 g.bindKey(['ctrl+z', 'cmd+z'], => {
 undo
 return false // Prevent default browser undo
 })
 // Bind redo shortcuts (Ctrl+Shift+Z on Windows/Linux, Cmd+Shift+Z on Mac)
 g.bindKey(['ctrl+shift+z', 'cmd+shift+z'], => {
 redo
 return false // Prevent default browser redo
 })
 }
 // Batch drag operations so entire drag = one undo step
 // node:move fires continuously during drag
 g.on('node:move', => {
 if (!isBatching.value) {
 g.startBatch('node-move')
 isBatching.value = true
 }
 })
 // node:moved fires once when drag completes
 g.on('node:moved', => {
 if (isBatching.value) {
 g.stopBatch('node-move')
 isBatching.value = false
 }
 })
 // Update reactive state when history changes
 g.on('history:change', => {
 // Force reactivity update by accessing the graph
 // The computed properties will re-evaluate
 })
 }, { immediate: true })
 /**
 * Undo the last operation.
 * Shows a Toast notification on success.
 */
 function undo {
 if (graph.value?.canUndo) {
 graph.value.undo
 toast.success('已撤销', { duration: 1500 })
 }
 }
 /**
 * Redo the last undone operation.
 * Shows a Toast notification on success.
 */
 function redo {
 if (graph.value?.canRedo) {
 graph.value.redo
 toast.success('已重做', { duration: 1500 })
 }
 }
 /**
 * Clear all history (both undo and redo stacks).
 */
 function clear {
 graph.value?.cleanHistory?.
 }
 return {
 /** Whether undo is available */
 canUndo,
 /** Whether redo is available */
 canRedo,
 /** Undo the last operation */
 undo,
 /** Redo the last undone operation */
 redo,
 /** Clear all history */
 clear,
 }
}
