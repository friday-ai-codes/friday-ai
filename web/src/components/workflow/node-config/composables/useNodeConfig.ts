import { watchDebounced } from '@vueuse/core'
import { storeToRefs } from 'pinia'
import { computed, defineAsyncComponent, onMounted, onUnmounted, ref, watch } from 'vue'

import { useDesignTimeVariables } from '~/composables/useDesignTimeVariables'
import { useNodeMeta } from '~/composables/useNodeMeta'
import { useNodeTypesStore } from '~/stores/useNodeTypesStore'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'

export function useNodeConfig() {
  const store = useWorkflowsStore()
  const nodeTypesStore = useNodeTypesStore()
  const { selectedNodeId, nodes, edges } = storeToRefs(store)

  // Esc 键关闭面板
  function onEscKey(e: KeyboardEvent) {
    if (e.key === 'Escape' && selectedNodeId.value) {
      store.selectNode(null)
    }
  }
  onMounted(() => document.addEventListener('keydown', onEscKey))
  onUnmounted(() => document.removeEventListener('keydown', onEscKey))

  // 选中节点计算属性
  const selectedNode = computed(() => {
    if (!selectedNodeId.value)
      return null
    return nodes.value.find(n => n.id === selectedNodeId.value) || null
  })

  // 节点元数据
  const { getDefinition, hasCustomConfig } = useNodeMeta()

  // 上游变量
  const { designTimeVariables } = useDesignTimeVariables(nodes, edges, selectedNodeId)

  // 本地表单状态
  const nodeName = ref('')
  const nodeDescription = ref('')
  const nodeConfig = ref<Record<string, any>>({})

  // 节点类型信息
  const nodeTypeInfo = computed(() => {
    if (!selectedNode.value)
      return null
    return nodeTypesStore.getNodeType(selectedNode.value.nodeType)
  })

  const currentNodeType = computed(() => {
    return selectedNode.value?.nodeType || ''
  })

  const nodeHasCustomConfig = computed(() => {
    return hasCustomConfig(currentNodeType.value)
  })

  const nodeDefinition = computed(() => {
    return getDefinition(currentNodeType.value)
  })

  // 动态配置组件
  const ConfigComponent = computed(() => {
    const def = nodeDefinition.value
    if (def?.configComponent) {
      return defineAsyncComponent(def.configComponent)
    }
    return null
  })

  // 监听节点切换，同步表单状态
  watch(() => selectedNode.value?.id, (newId) => {
    if (newId && selectedNode.value) {
      nodeName.value = selectedNode.value.name || ''
      nodeDescription.value = selectedNode.value.description || ''
      nodeConfig.value = { ...selectedNode.value.config }
    }
  }, { immediate: true })

  // 防抖同步配置到 store。
  // 仅当本地表单与 store 现值「确有差异」才写回——否则切换/选中节点触发的初始同步
  // 也会写回并把节点误标为「未保存」（dirty）。
  watchDebounced(
    [nodeName, nodeDescription, nodeConfig],
    () => {
      if (!selectedNodeId.value)
        return

      const node = nodes.value.find(n => n.id === selectedNodeId.value)
      if (!node)
        return

      const sameName = (node.name || '') === nodeName.value
      const sameDescription = (node.description || '') === nodeDescription.value
      const sameConfig
        = JSON.stringify(node.config ?? {}) === JSON.stringify(nodeConfig.value ?? {})
      if (sameName && sameDescription && sameConfig)
        return // 无实际改动（仅切换/选中节点的初始同步）→ 不写回、不标脏

      store.updateNodeData(selectedNodeId.value, {
        name: nodeName.value,
        description: nodeDescription.value,
        config: nodeConfig.value,
      })
    },
    { debounce: 300, deep: true },
  )

  function closeNodePanel() {
    store.selectNode(null)
  }

  function deleteNode() {
    if (selectedNodeId.value) {
      store.removeNode(selectedNodeId.value)
    }
  }

  // 配置值更新辅助函数
  function updateConfigValue(key: string, value: any) {
    nodeConfig.value = { ...nodeConfig.value, [key]: value }
  }

  function handleConfigUpdate(newConfig: Record<string, any>) {
    nodeConfig.value = { ...newConfig }
  }

  function updateJsonConfig(key: string, value: string) {
    try {
      updateConfigValue(key, JSON.parse(value))
    }
    catch {
      // JSON 解析错误在输入过程中忽略
    }
  }

  // 根据 schema 判断字段类型
  function getFieldType(schema: any): string {
    if (schema.enum)
      return 'select'
    if (schema.type === 'boolean')
      return 'switch'
    if (schema.type === 'number' || schema.type === 'integer')
      return 'number'
    if (schema.type === 'array')
      return 'array'
    if (schema.type === 'object')
      return 'object'
    return 'text'
  }

  return {
    selectedNode,
    selectedNodeId,
    nodes,
    edges,
    store,
    nodeTypesStore,
    nodeName,
    nodeDescription,
    nodeConfig,
    nodeTypeInfo,
    nodeHasCustomConfig,
    ConfigComponent,
    designTimeVariables,
    closeNodePanel,
    deleteNode,
    updateConfigValue,
    handleConfigUpdate,
    updateJsonConfig,
    getFieldType,
  }
}
