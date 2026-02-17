import type { WorkflowEdge } from '~/types/workflow/store'
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
/**
 * Validation warning for a workflow connection
 */
export interface ValidationWarning {
 /** Warning ID (usually edge ID) */
 id: string
 /** The edge with the warning */
 edgeId: string
 /** Warning type */
 type: 'schema_mismatch'
 /** Human-readable message */
 message: string
 /** Source node ID */
 sourceNodeId: string
 /** Target node ID */
 targetNodeId: string
}
/**
 * Centralized warning state management for workflow validation
 *
 * Aggregates all validation warnings for display in the issues panel
 * and provides per-edge warning lookup for edge styling.
 *
 * @example
 * ```ts
 * const validationStore = useWorkflowValidationStore
 *
 * // Add a warning
 * validationStore.addWarning({
 * id: 'edge-1',
 * edgeId: 'edge-1',
 * type: 'schema_mismatch',
 * message: '类型不匹配: string -> number',
 * sourceNodeId: 'node-1',
 * targetNodeId: 'node-2',
 * })
 *
 * // Check for warnings
 * const warning = validationStore.getWarningForEdge('edge-1')
 *
 * // Display in issues panel
 * validationStore.warningsList.forEach(w => { /* handle warning */ })
 * ```
 */
export const useWorkflowValidationStore = defineStore('workflowValidation', => {
 // State: Map of warnings keyed by edge ID
 const warnings = ref<Map<string, ValidationWarning>>(new Map)
 // Getters
 const warningsList = computed(: ValidationWarning => {
 return Array.from(warnings.value.values)
 })
 const warningCount = computed(: number => {
 return warnings.value.size
 })
 const hasWarnings = computed(: boolean => {
 return warnings.value.size > 0
 })
 /**
 * Get warning for a specific edge
 * @param edgeId - The edge ID to look up
 * @returns The warning if exists, undefined otherwise
 */
 function getWarningForEdge(edgeId: string): ValidationWarning | undefined {
 return warnings.value.get(edgeId)
 }
 // Actions
 /**
 * Add or update a warning
 * @param warning - The warning to add
 */
 function addWarning(warning: ValidationWarning): void {
 warnings.value.set(warning.edgeId, warning)
 }
 /**
 * Remove a warning by edge ID
 * @param edgeId - The edge ID to remove warning for
 */
 function removeWarning(edgeId: string): void {
 warnings.value.delete(edgeId)
 }
 /**
 * Clear all warnings
 */
 function clearAllWarnings: void {
 warnings.value.clear
 }
 /**
 * Sync warnings with current edges
 * Removes orphaned warnings for edges that no longer exist
 * @param edges - Current edges in the workflow
 */
 function syncWithEdges(edges: WorkflowEdge): void {
 const edgeIds = new Set(edges.map(e => e.id))
 // Remove warnings for edges that no longer exist
 for (const edgeId of warnings.value.keys) {
 if (!edgeIds.has(edgeId)) {
 warnings.value.delete(edgeId)
 }
 }
 }
 return {
 // State
 warnings,
 // Getters
 warningsList,
 warningCount,
 hasWarnings,
 getWarningForEdge,
 // Actions
 addWarning,
 removeWarning,
 clearAllWarnings,
 syncWithEdges,
 }
})
