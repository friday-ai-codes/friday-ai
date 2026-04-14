<script setup lang="ts">
import { Trash2 } from 'lucide-vue-next'
import { Button } from '~/components/ui/button'
import { ScrollArea } from '~/components/ui/scroll-area'
import IssuesPanel from '../validation/IssuesPanel.vue'
import OverrideConfirmDialog from '../validation/OverrideConfirmDialog.vue'
import { useAutoFill } from './composables/useAutoFill'
import { useNodeConfig } from './composables/useNodeConfig'
import { useNodeSchema } from './composables/useNodeSchema'
import NodeConfigForm from './NodeConfigForm.vue'
import NodeConfigHeader from './NodeConfigHeader.vue'
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
} = useNodeConfig
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
 <NodeConfigHeader:node-type-display-name="nodeTypeInfo?.display_name":has-inputs="!!(nodeTypeInfo?.inputs?.length)":selected-node-short-id="selectedNode?.shortId || ''":selected-node-id="selectedNodeId || ''"
 @auto-fill="handleAutoFill"
 @close="closeNodePanel"
 />
 <ScrollArea class="flex-1">
 <div class=" space-y-5">
 <!-- Issues Panel -->
 <IssuesPanel />
 <!-- 配置表单 -->
 <NodeConfigForm:node-name="nodeName":node-description="nodeDescription":node-has-custom-config="nodeHasCustomConfig":config-component="ConfigComponent":node-config="nodeConfig":node-type-info="nodeTypeInfo":workflow-nodes="nodes":workflow-edges="edges":current-node-id="selectedNodeId"
 @update:name="onNameUpdate"
 @update:description="onDescriptionUpdate"
 @update-config="handleConfigUpdate"
 @update-config-value="onConfigValueUpdate"
 @update-json-config="onJsonConfigUpdate"
 />
 <!-- Schema 展示 -->
 <NodeSchemaDisplay:direct-predecessor-outputs="directPredecessorOutputs":has-predecessor="hasPredecessor":node-type-info="nodeTypeInfo":input-schema-open="inputSchemaOpen":output-schema-open="outputSchemaOpen":output-field-count="getOutputFieldCount(nodeTypeInfo)":get-output-path="getOutputPath":get-input-path="getInputPath"
 @update:input-schema-open="inputSchemaOpen = $event"
 @update:output-schema-open="outputSchemaOpen = $event"
 />
 </div>
 </ScrollArea>
 <!-- 底部操作 -->
 <div class=" border-t border-border/50">
 <Button variant="outline" class="w-full hover:border-destructive/50 hover:text-destructive" @click="deleteNode">
 <Trash2 class="w-4 mr-2" />
 删除节点
 </Button>
 </div>
 </div>
 </Transition>
 <!-- Override 确认对话框 -->
 <OverrideConfirmDialog
 v-model:open="overrideDialogOpen":fields="fieldsToOverride"
 @confirm="handleOverrideConfirm"
 />
</template>
