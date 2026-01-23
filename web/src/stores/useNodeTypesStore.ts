import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
export interface NodePort {
 name: string
 label: string
 type: string
 required: boolean
 description: string
}
export interface NodeType {
 node_type: string
 display_name: string
 description: string
 icon: string
 category: 'trigger' | 'action' | 'control' | 'integration' | 'ai'
 config_schema: Record<string, any>
 inputs: NodePort
 outputs: NodePort
 requires_container: boolean
 is_blocking: boolean
}
export const useNodeTypesStore = defineStore('nodeTypes', => {
 const nodeTypes = ref<NodeType>
 const loading = ref(false)
 const error = ref<string | null>(null)
 // Group node types by category
 const nodeTypesByCategory = computed( => {
 const groups: Record<string, NodeType> = {
 trigger:,
 action:,
 control:,
 integration:,
 ai:,
 }
 for (const nodeType of nodeTypes.value) {
 if (groups[nodeType.category]) {
 groups[nodeType.category].push(nodeType)
 }
 }
 return groups
 })
 // Get a specific node type
 const getNodeType = (type: string): NodeType | undefined => {
 return nodeTypes.value.find(nt => nt.node_type === type)
 }
 async function fetchNodeTypes {
 loading.value = true
 error.value = null
 try {
 const response = await fetch('/api/node-types/')
 if (!response.ok)
 throw new Error('Failed to fetch node types')
 const data = await response.json
 nodeTypes.value = data.results || data
 }
 catch (e: any) {
 error.value = e.message
 console.error(e)
 }
 finally {
 loading.value = false
 }
 }
 return {
 nodeTypes,
 nodeTypesByCategory,
 loading,
 error,
 fetchNodeTypes,
 getNodeType,
 }
})
