<script setup lang="ts">
import type { NodeType } from '~/stores/useNodeTypesStore'
import type { DeliveryKnowledgeSearchConfig } from '~/types/workflow'
import type { WorkflowEdge, WorkflowNode } from '~/types/workflow/store'

import { Label } from '~/components/ui/label'
import { Separator } from '~/components/ui/separator'
import { SliderSingle } from '~/components/ui/slider'
import { Switch } from '~/components/ui/switch'
import NodePortsDisplay from '~/components/workflow/NodePortsDisplay.vue'
import SmartInput from '~/components/workflow/smart-input/SmartInput.vue'
import { useConfigModel } from '~/composables/useConfigModel'
import { deliveryKnowledgeSearchConfigSchema } from '~/types/workflow'

interface Props {
  config: DeliveryKnowledgeSearchConfig
  workflowNodes?: WorkflowNode[]
  workflowEdges?: WorkflowEdge[]
  currentNodeId?: string | null
  nodeTypeInfo?: NodeType | null
}

const props = withDefaults(defineProps<Props>(), {
  workflowNodes: () => [],
  workflowEdges: () => [],
  currentNodeId: null,
  nodeTypeInfo: null,
})

const emit = defineEmits<{
  (e: 'update:config', value: DeliveryKnowledgeSearchConfig): void
}>()

const { field } = useConfigModel({
  config: () => props.config,
  emit: v => emit('update:config', v),
  schema: deliveryKnowledgeSearchConfigSchema,
})

const query = field('query', '')
const topK = field('top_k', 5)
const asOf = field('as_of', '')
const includeSuperseded = field('include_superseded', false)
</script>

<template>
  <div class="space-y-4">
    <NodePortsDisplay v-if="nodeTypeInfo" :node-type="nodeTypeInfo" />

    <div class="space-y-2">
      <Label>检索 query</Label>
      <SmartInput
        v-model="query"
        :workflow-nodes="workflowNodes"
        :workflow-edges="workflowEdges"
        :current-node-id="currentNodeId"
        placeholder="例如 {{global.requirement_text}}"
      />
    </div>

    <div class="space-y-2">
      <Label>返回数量 (top_k)</Label>
      <SliderSingle v-model="topK" :min="1" :max="20" :step="1" />
    </div>

    <div class="space-y-2">
      <Label>历史时点 (as_of ISO8601)</Label>
      <SmartInput
        v-model="asOf"
        :workflow-nodes="workflowNodes"
        :workflow-edges="workflowEdges"
        :current-node-id="currentNodeId"
        placeholder="可选，如 2026-05-31T23:59:59+08:00"
      />
    </div>

    <div class="flex items-center justify-between">
      <Label for="include-superseded">显示已取代版本</Label>
      <Switch id="include-superseded" v-model:checked="includeSuperseded" />
    </div>

    <Separator />
  </div>
</template>
