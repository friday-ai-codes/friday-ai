import type { DesignTimeVariable } from '~/composables/useDesignTimeVariables'
import type { WorkflowEdge, WorkflowNode } from '~/types/workflow/store'
/**
 * Variable node attributes stored in TipTap document
 */
export interface VariableNodeAttrs {
 /** Full variable path like `nodes.xxx.output_name` */
 path: string
 /** Display label like `召回上下文.检索结果` */
 label: string
 /** Source node ID */
 nodeId: string
 /** Output port name */
 outputName: string
}
/**
 * Function node attributes stored in TipTap document
 */
export interface FunctionNodeAttrs {
 /** Function name like `concat`, `if`, `upper` */
 name: string
 /** Argument values (can be literals or nested variable syntax) */
 args: string
}
/**
 * Props for SmartInput and SmartTextarea components
 */
export interface SmartInputProps {
 /** v-model value - serialized content with {{path}} syntax */
 modelValue: string
 /** Workflow nodes for variable discovery */
 workflowNodes: WorkflowNode
 /** Workflow edges for DAG traversal */
 workflowEdges: WorkflowEdge
 /** Current node ID to determine upstream variables */
 currentNodeId: string
 /** Placeholder text when empty */
 placeholder?: string
 /** Enable multiline editing (SmartTextarea) */
 multiline?: boolean
}
/**
 * Suggestion item - extends DesignTimeVariable for autocomplete
 */
export type SuggestionItem = DesignTimeVariable
/**
 * Suggestion group - groups variables by source node
 */
export interface SuggestionGroup {
 /** Source node ID */
 nodeId: string
 /** Node display label */
 nodeLabel: string
 /** Node type for icon selection */
 nodeType: string
 /** Icon component or name */
 icon?: string
 /** Variables from this node */
 items: SuggestionItem
}
