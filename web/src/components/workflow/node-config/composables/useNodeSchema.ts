import type { Ref } from 'vue'
import type { WorkflowEdgeStore, WorkflowNodeStore } from '~/types/workflow/store'
import { computed, ref } from 'vue'

import { useNodeTypesStore } from '~/stores/useNodeTypesStore'
import { buildNodeRef, buildPrefixRef } from '~/utils/variableRef'

// 输入字段项类型
export interface InputFieldItem {
  nodeId: string
  nodeShortId: string
  nodeLabel: string
  fieldName: string
  fieldLabel: string
  type: string
  description?: string
  isNested?: boolean
  parentOutput?: string
}

export function useNodeSchema(
  selectedNode: Ref<WorkflowNodeStore | null>,
  selectedNodeId: Ref<string | null>,
  nodes: Ref<WorkflowNodeStore[]>,
  edges: Ref<WorkflowEdgeStore[]>,
) {
  const nodeTypesStore = useNodeTypesStore()

  // 折叠状态
  const inputSchemaOpen = ref(true)
  const outputSchemaOpen = ref(true)

  // 获取直接前置节点的输出字段
  const directPredecessorOutputs = computed((): InputFieldItem[] => {
    if (!selectedNodeId.value)
      return []

    const incomingEdges = edges.value.filter(e => e.target === selectedNodeId.value)
    if (incomingEdges.length === 0)
      return []

    const outputs: InputFieldItem[] = []

    for (const edge of incomingEdges) {
      const sourceNode = nodes.value.find(n => n.id === edge.source)
      if (!sourceNode)
        continue

      const sourceNodeType = nodeTypesStore.getNodeType(sourceNode.nodeType)
      if (!sourceNodeType?.outputs)
        continue

      const nodeLabel = sourceNode.name || sourceNodeType.display_name
      // shortId 缺失时留空，绝不回退 UUID 截断形式（锁定决策 VAR-03）
      const nodeShortId = sourceNode.shortId || ''

      for (const output of sourceNodeType.outputs) {
        if (output.schema?.properties) {
          for (const [propKey, propSchema] of Object.entries(output.schema.properties)) {
            const schema = propSchema as { type?: string, description?: string }
            outputs.push({
              nodeId: sourceNode.id,
              nodeShortId,
              nodeLabel,
              fieldName: propKey,
              fieldLabel: schema.description || propKey,
              type: schema.type || 'any',
              description: schema.description,
              isNested: true,
              parentOutput: output.name,
            })
          }
        }
        else {
          outputs.push({
            nodeId: sourceNode.id,
            nodeShortId,
            nodeLabel,
            fieldName: output.name,
            fieldLabel: output.label,
            type: output.type,
            description: output.description,
            isNested: false,
          })
        }
      }
    }

    return outputs
  })

  const hasPredecessor = computed(() => directPredecessorOutputs.value.length > 0)

  // 端口类型颜色
  function getPortTypeColor(type: string): string {
    const colors: Record<string, string> = {
      string: 'text-green-500',
      number: 'text-primary',
      boolean: 'text-amber-500',
      object: 'text-purple-500',
      array: 'text-cyan-500',
      any: 'text-muted-foreground',
    }
    return colors[type] || 'text-muted-foreground'
  }

  // 生成输出变量引用路径（使用权威 shortId）
  // shortId 缺失时返回空串：展示层显示空优于显示必坏的 UUID 引用（锁定决策 VAR-03）
  function getOutputPath(outputName: string): string {
    const shortId = selectedNode.value?.shortId ?? ''
    return shortId ? buildNodeRef(shortId, outputName) : ''
  }

  // 生成输入变量引用路径
  function getInputPath(outputName: string): string {
    return buildPrefixRef('input', outputName)
  }

  // 计算输出字段总数（包含 schema 详细字段）
  function getOutputFieldCount(nodeTypeInfo: any): number {
    if (!nodeTypeInfo?.outputs)
      return 0
    let count = 0
    for (const output of nodeTypeInfo.outputs) {
      if (output.schema?.properties) {
        count += Object.keys(output.schema.properties).length
      }
      else {
        count += 1
      }
    }
    return count
  }

  return {
    inputSchemaOpen,
    outputSchemaOpen,
    directPredecessorOutputs,
    hasPredecessor,
    getPortTypeColor,
    getOutputPath,
    getInputPath,
    getOutputFieldCount,
  }
}
