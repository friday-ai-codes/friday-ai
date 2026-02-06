import type { Component } from 'vue'
import { getTeleport, register } from '@antv/x6-vue-shape'
/**
 * Node registry for X6 graph nodes.
 * Maps shape names to Vue components.
 *
 * Placeholders - real components will be added in 29-02
 */
const nodeRegistry: Record<string, Component> = {
 // Will be populated with type-specific node components:
 // manual_trigger: X6TriggerNode,
 // feishu_event: X6TriggerNode,
 // claude_code: X6ActionNode,
 // ...
}
/**
 * Default node dimensions.
 * Width/height chosen to align with 20px grid.
 */
const DEFAULT_NODE_WIDTH = 200
const DEFAULT_NODE_HEIGHT = 80
/**
 * Flag to prevent double registration.
 * X6 throws error if same shape is registered twice.
 */
let isRegistered = false
/**
 * Register all node shapes with X6.
 * Must be called before creating a Graph that uses these shapes.
 *
 * @example
 * ```ts
 * import { registerAllNodes } from './nodeRegistry'
 *
 * // Call once at app startup
 * registerAllNodes
 *
 * // Then create graph
 * const graph = new Graph({ ... })
 * ```
 */
export function registerAllNodes: void {
 if (isRegistered) {
 return
 }
 for (const [shape, component] of Object.entries(nodeRegistry)) {
 register({
 shape,
 width: DEFAULT_NODE_WIDTH,
 height: DEFAULT_NODE_HEIGHT,
 component,
 })
 }
 isRegistered = true
}
/**
 * TeleportContainer component for Vue 3 teleport rendering.
 * Must be included in the template where X6 graph is rendered.
 *
 * @example
 * ```vue
 * <template>
 * <div ref="containerRef" class="graph-container" />
 * <TeleportContainer />
 * </template>
 * ```
 */
export const TeleportContainer = getTeleport
