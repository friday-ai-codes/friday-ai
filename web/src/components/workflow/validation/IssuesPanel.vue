<script setup lang="ts">
import { ref } from 'vue'
import { storeToRefs } from 'pinia'
import { AlertTriangle, ChevronDown } from 'lucide-vue-next'
import { useVueFlow } from '@vue-flow/core'
import { useWorkflowValidationStore } from '~/stores/useWorkflowValidationStore'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
import { Badge } from '~/components/ui/badge'
import {
 Collapsible,
 CollapsibleContent,
 CollapsibleTrigger,
} from '~/components/ui/collapsible'
const validationStore = useWorkflowValidationStore
const workflowStore = useWorkflowsStore
const { warningsList, warningCount, hasWarnings } = storeToRefs(validationStore)
const { nodes } = storeToRefs(workflowStore)
const { setCenter } = useVueFlow
// Get node name by ID
function getNodeName(nodeId: string): string {
 const node = nodes.value.find(n => n.id === nodeId)
 return node?.data?.name || node?.label || nodeId.slice(0, 8)
}
// Handle clicking a warning - center on the edge
function handleWarningClick(warning: typeof warningsList.value[0]) {
 // Find source and target nodes to calculate edge center
 const sourceNode = nodes.value.find(n => n.id === warning.sourceNodeId)
 const targetNode = nodes.value.find(n => n.id === warning.targetNodeId)
 if (sourceNode && targetNode) {
 const centerX = (sourceNode.position.x + targetNode.position.x) / 2
 const centerY = (sourceNode.position.y + targetNode.position.y) / 2
 setCenter(centerX, centerY, { zoom: 1.5, duration: 300 })
 }
}
// Panel open state - auto-open when warnings exist
const isOpen = ref(true)
</script>
<template>
 <Collapsible
 v-if="hasWarnings"
 v-model:open="isOpen"
 class="rounded-xl bg-amber-500/10 border border-amber-500/30 overflow-hidden"
 >
 <CollapsibleTrigger class="w-full">
 <div class="flex items-center justify-between hover:bg-amber-500/5 transition-colors">
 <div class="flex items-center gap-2">
 <div class=".5 rounded-lg bg-amber-500/20">
 <AlertTriangle class="w-4 text-amber-600" />
 </div>
 <span class="text-sm font-medium">问题</span>
 <Badge variant="secondary" class="bg-amber-500/20 text-amber-700">
 {{ warningCount }}
 </Badge>
 </div>
 <ChevronDown
 class="w-4 text-muted-foreground transition-transform":class="{ 'rotate-180': isOpen }"
 />
 </div>
 </CollapsibleTrigger>
 <CollapsibleContent>
 <div class="px-3 pb-3 space-y-2">
 <button
 v-for="warning in warningsList":key="warning.id"
 class="w-full text-left .5 rounded-lg bg-background/50 hover:bg-background/80 transition-colors group"
 @click="handleWarningClick(warning)"
 >
 <div class="flex items-start gap-2">
 <AlertTriangle class="w-4 text-amber-500 mt-0.5 flex-shrink-0" />
 <div class="flex-1 min-w-0">
 <p class="text-sm font-medium truncate">
 {{ warning.message }}
 </p>
 <p class="text-xs text-muted-foreground mt-0.5">
 {{ getNodeName(warning.sourceNodeId) }}
 <span class="mx-1">→</span>
 {{ getNodeName(warning.targetNodeId) }}
 </p>
 </div>
 </div>
 </button>
 </div>
 </CollapsibleContent>
 </Collapsible>
</template>
