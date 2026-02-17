import type { Component } from 'vue'
import { getTeleport, register } from '@antv/x6-vue-shape'
import { registerGradientEdge } from './edges'
import X6ActionNode from './nodes/X6ActionNode.vue'
import X6AgentNode from './nodes/X6AgentNode.vue'
import X6ConditionNode from './nodes/X6ConditionNode.vue'
import X6TriggerNode from './nodes/X6TriggerNode.vue'
import { getDefaultPortsForNodeType, workflowPortGroups } from './ports'
/**
 * Node registry for X6 graph nodes.
 * Maps shape names to Vue components.
 *
 * Each shape name corresponds to a node_type from the backend.
 * The component is rendered inside the X6 node via teleport.
 */
const nodeRegistry: Record<string, Component> = {
 // Trigger nodes (blue gradient)
 manual_trigger: X6TriggerNode,
 webhook_trigger: X6TriggerNode,
 feishu_event_trigger: X6TriggerNode,
 // Action nodes (purple gradient)
 http_request: X6ActionNode,
 code_implement: X6ActionNode,
 create_branch: X6ActionNode,
 fetch_work_item: X6ActionNode,
 fetch_project_info: X6ActionNode,
 ai_prompt: X6ActionNode,
 ai_coding_dispatcher: X6ActionNode,
 ai_variable_extractor: X6ActionNode,
 variable_extractor: X6ActionNode,
 context_retrieval: X6ActionNode,
 technical_plan: X6ActionNode,
 wait_feishu: X6ActionNode,
 // Condition nodes (amber gradient)
 condition: X6ConditionNode,
 approval: X6ConditionNode,
 // Specialized AI nodes
 ai_plan_generation: X6AgentNode,
 ai_plan_approval: X6ConditionNode, // Approval node uses condition style (dual outputs)
 ai_coding: X6AgentNode,
 ai_code_review: X6AgentNode,
}
/**
 * Default node dimensions.
 * Width/height chosen to align with 20px grid and fit horizontal layout.
 */
const DEFAULT_NODE_WIDTH = 220
const DEFAULT_NODE_HEIGHT = 60
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
 // Register gradient edge shape for connections
 registerGradientEdge
 for (const [shape, component] of Object.entries(nodeRegistry)) {
 register({
 shape,
 width: DEFAULT_NODE_WIDTH,
 height: DEFAULT_NODE_HEIGHT,
 component,
 ports: {
 groups: workflowPortGroups,
 items: getDefaultPortsForNodeType(shape),
 },
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
