import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import api from '~/api/client'

export interface PortSchema {
  type: string
  description?: string
  properties?: Record<string, PortSchema>
  items?: PortSchema
}

export interface NodePort {
  name: string
  label: string
  type: string
  required: boolean
  description: string
  schema?: PortSchema | null
  // 端口能力契约形状（92-01 后端 get_schema 写入、93-00 经 /node-types/ 真实回传）。
  // 空串/undefined = 通配（default/error 等通用端口恒空），是连接契约校验的零回归命门。
  shape?: string
}

export interface NodeType {
  node_type: string
  display_name: string
  description: string
  icon: string
  category: 'trigger' | 'action' | 'control' | 'integration' | 'ai'
  config_schema: Record<string, any>
  inputs: NodePort[]
  outputs: NodePort[]
  requires_container: boolean
  is_blocking: boolean
  // 后端 NodeTypeSerializer 暴露的字段（19-01）：前端运行时驱动所需
  ui_schema?: Record<string, any> | null
  default_config?: Record<string, any>
  execution_mode?: string
}

export const useNodeTypesStore = defineStore('nodeTypes', () => {
  const nodeTypes = ref<NodeType[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  // Group node types by category
  const nodeTypesByCategory = computed(() => {
    const groups: Record<string, NodeType[]> = {
      trigger: [],
      action: [],
      control: [],
      integration: [],
      ai: [],
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

  async function fetchNodeTypes() {
    loading.value = true
    error.value = null
    try {
      const data = await api.get<any>('/node-types/')
      nodeTypes.value = data.results || data
    }
    catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '加载失败'
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
