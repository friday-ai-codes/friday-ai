<script setup lang="ts">
import type { ResolvedProvider } from '~/types/providerCredential'
import { Trash2 } from 'lucide-vue-next'

import { computed, ref, watch } from 'vue'
import ResolvedSourceBadge from '~/components/providers/ResolvedSourceBadge.vue'
import { Button } from '~/components/ui/button'
import { ScrollArea } from '~/components/ui/scroll-area'
import { useNodeMeta } from '~/composables/useNodeMeta'
import { useProviderCredentialStore } from '~/stores/providerCredential'

import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
import IssuesPanel from '../validation/IssuesPanel.vue'
import OverrideConfirmDialog from '../validation/OverrideConfirmDialog.vue'
import { useAutoFill } from './composables/useAutoFill'
import { useNodeConfig } from './composables/useNodeConfig'
import { useNodeSchema } from './composables/useNodeSchema'
import NodeConfigForm from './NodeConfigForm.vue'
import NodeConfigHeader from './NodeConfigHeader.vue'
import NodeErrorConfig from './NodeErrorConfig.vue'
import NodeSchemaDisplay from './NodeSchemaDisplay.vue'

// 组合 3 个 composables
const {
  selectedNode,
  selectedNodeId,
  nodes,
  edges,
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
} = useNodeConfig()

const {
  overrideDialogOpen,
  fieldsToOverride,
  handleAutoFill,
  handleOverrideConfirm,
} = useAutoFill(nodeTypeInfo, designTimeVariables, nodeConfig)

const {
  inputSchemaOpen,
  outputSchemaOpen,
  directPredecessorOutputs,
  hasPredecessor,
  getOutputPath,
  getInputPath,
  getOutputFieldCount,
} = useNodeSchema(selectedNode, selectedNodeId, nodes, edges)

const { getDefinition } = useNodeMeta()
const nodeDefinition = computed(() => {
  const nodeType = selectedNode.value?.nodeType || ''
  return getDefinition(nodeType)
})

// ============================================================================
// ：四层 Provider 解析 Inspector
//
// 节点选中后 / 节点变化时，调 providerCredentialStore.getResolvedProvider
// 拉取 workflow + node 的 resolved_provider（含 4 层 chain）；用于 Provider
// 下拉旁展示 ResolvedSourceBadge 优先级链 tooltip。
// 失败或全链路 miss 时 resolvedProvider 为 null，Badge 不渲染（优雅降级）。
// ============================================================================
const workflowsStore = useWorkflowsStore()
const providerCredentialStore = useProviderCredentialStore()
const resolvedProvider = ref<ResolvedProvider | null>(null)

async function loadResolvedProvider() {
  const workflowId = workflowsStore.currentWorkflow?.id
  const nodeId = selectedNodeId.value
  if (!workflowId || !nodeId) {
    resolvedProvider.value = null
    return
  }
  try {
    resolvedProvider.value = await providerCredentialStore.getResolvedProvider({
      workflowId,
      nodeId,
    })
  }
  catch {
    // 失败降级：不挂 badge，不阻塞其他配置面板功能
    resolvedProvider.value = null
  }
}

watch(selectedNodeId, () => {
  void loadResolvedProvider()
}, { immediate: true })

// 表单事件处理
function onNameUpdate(value: string) {
  nodeName.value = value
}

function onDescriptionUpdate(value: string) {
  nodeDescription.value = value
}

function onConfigValueUpdate(key: string, value: any) {
  updateConfigValue(key, value)
}

function onJsonConfigUpdate(key: string, value: string) {
  updateJsonConfig(key, value)
}

// 错误处理配置 — 从 selectedNode 的 store data 读取
// selectedNode 来自 useNodeConfig()，已经是 store 格式（WorkflowNodeStore）
const nodeOnError = computed(() => {
  const node = selectedNode.value as Record<string, unknown> | undefined
  return (node?.onError as 'abort' | 'retry' | 'ignore') ?? 'abort'
})
const nodeRetryTimes = computed(() => {
  const node = selectedNode.value as Record<string, unknown> | undefined
  return (node?.retryTimes as number) ?? 0
})
const nodeRetryDelay = computed(() => {
  const node = selectedNode.value as Record<string, unknown> | undefined
  return (node?.retryDelay as number) ?? 5
})
const nodeTimeoutSeconds = computed(() => {
  const node = selectedNode.value as Record<string, unknown> | undefined
  return (node?.nodeTimeoutSeconds as number | null) ?? null
})
const nodeFallbackValues = computed(() => {
  const node = selectedNode.value as Record<string, unknown> | undefined
  return (node?.fallbackValues as Record<string, unknown> | null) ?? null
})

function updateErrorField(field: string, value: unknown) {
  if (!selectedNodeId.value)
    return
  const storeNode = workflowsStore.nodes.find(n => n.id === selectedNodeId.value)
  if (storeNode) {
    ;(storeNode as Record<string, unknown>)[field] = value
  }
}
</script>

<template>
  <!-- 选中节点时显示 -->
  <Transition
    enter-active-class="transition-all duration-300 ease-out"
    enter-from-class="opacity-0 translate-x-8"
    enter-to-class="opacity-100 translate-x-0"
    leave-active-class="transition-all duration-200 ease-in"
    leave-from-class="opacity-100 translate-x-0"
    leave-to-class="opacity-0 translate-x-8"
  >
    <div
      v-if="selectedNode"
      class="absolute top-0 right-3 bottom-0 w-[400px] z-20 flex flex-col rounded-2xl bg-card/90 backdrop-blur-md border border-border/50 shadow-xl overflow-hidden"
    >
      <!-- 标题栏 -->
      <NodeConfigHeader
        :node-type-display-name="nodeTypeInfo?.display_name"
        :has-inputs="!!(nodeTypeInfo?.inputs?.length)"
        :selected-node-short-id="selectedNode?.shortId || ''"
        :selected-node-id="selectedNodeId || ''"
        @auto-fill="handleAutoFill"
        @close="closeNodePanel"
      />

      <ScrollArea class="flex-1">
        <div class="p-4 space-y-5">
          <!-- Issues Panel -->
          <IssuesPanel />

          <!-- ：四层 Provider 解析 Inspector（Provider 区块旁） -->
          <div v-if="resolvedProvider" class="flex items-center gap-2">
            <span class="text-xs text-muted-foreground">Provider 解析</span>
            <ResolvedSourceBadge
              :source="resolvedProvider.source"
              :chain="resolvedProvider.chain"
            />
          </div>

          <!-- 配置表单 -->
          <NodeConfigForm
            :node-name="nodeName"
            :node-description="nodeDescription"
            :node-has-custom-config="nodeHasCustomConfig"
            :config-component="ConfigComponent"
            :node-config="nodeConfig"
            :node-type-info="nodeTypeInfo"
            :ui-schema="nodeDefinition?.uiSchema"
            :workflow-nodes="nodes"
            :workflow-edges="edges"
            :current-node-id="selectedNodeId"
            @update:name="onNameUpdate"
            @update:description="onDescriptionUpdate"
            @update-config="handleConfigUpdate"
            @update-config-value="onConfigValueUpdate"
            @update-json-config="onJsonConfigUpdate"
          />

          <!-- 错误处理配置 -->
          <NodeErrorConfig
            :on-error="nodeOnError"
            :retry-times="nodeRetryTimes"
            :retry-delay="nodeRetryDelay"
            :node-timeout-seconds="nodeTimeoutSeconds"
            :fallback-values="nodeFallbackValues"
            @update:on-error="(v: string) => updateErrorField('onError', v)"
            @update:retry-times="(v: number) => updateErrorField('retryTimes', v)"
            @update:retry-delay="(v: number) => updateErrorField('retryDelay', v)"
            @update:node-timeout-seconds="(v: number | null) => updateErrorField('nodeTimeoutSeconds', v)"
            @update:fallback-values="(v: Record<string, unknown> | null) => updateErrorField('fallbackValues', v)"
          />

          <!-- Schema 展示 -->
          <NodeSchemaDisplay
            :direct-predecessor-outputs="directPredecessorOutputs"
            :has-predecessor="hasPredecessor"
            :node-type-info="nodeTypeInfo"
            :input-schema-open="inputSchemaOpen"
            :output-schema-open="outputSchemaOpen"
            :output-field-count="getOutputFieldCount(nodeTypeInfo)"
            :get-output-path="getOutputPath"
            :get-input-path="getInputPath"
            @update:input-schema-open="inputSchemaOpen = $event"
            @update:output-schema-open="outputSchemaOpen = $event"
          />
        </div>
      </ScrollArea>

      <!-- 底部操作 -->
      <div class="p-4 border-t border-border/50">
        <Button variant="outline" class="w-full hover:border-destructive/50 hover:text-destructive" @click="deleteNode">
          <Trash2 class="w-4 h-4 mr-2" />
          删除节点
        </Button>
      </div>
    </div>
  </Transition>

  <!-- Override 确认对话框 -->
  <OverrideConfirmDialog
    v-model:open="overrideDialogOpen"
    :fields="fieldsToOverride"
    @confirm="handleOverrideConfirm"
  />
</template>
