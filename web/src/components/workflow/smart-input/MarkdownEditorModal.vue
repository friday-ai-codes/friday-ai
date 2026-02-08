<script setup lang="ts">
import type { WorkflowEdge, WorkflowNode } from '~/types/workflow/store'
import { ref, watch } from 'vue'
import { Button } from '~/components/ui/button'
import {
 Dialog,
 DialogContent,
 DialogDescription,
 DialogFooter,
 DialogHeader,
 DialogTitle,
} from '~/components/ui/dialog'
import SmartMarkdownEditor from './SmartMarkdownEditor.vue'
interface Props {
 open: boolean
 title?: string
 description?: string
 modelValue: string
 workflowNodes: WorkflowNode
 workflowEdges: WorkflowEdge
 currentNodeId: string
 placeholder?: string
}
const props = withDefaults(defineProps<Props>, {
 title: '编辑提示词',
 description: '',
 placeholder: '',
})
const emit = defineEmits<{
 'update:open': [value: boolean]
 'update:modelValue': [value: string]
 'confirm': [value: string]
}>
// Local copy for editing
const localValue = ref(props.modelValue)
// Sync when modal opens
watch( => props.open, (isOpen) => {
 if (isOpen) {
 localValue.value = props.modelValue
 }
})
// Also sync when modelValue changes while open
watch( => props.modelValue, (newValue) => {
 if (props.open) {
 localValue.value = newValue
 }
})
function handleConfirm {
 emit('update:modelValue', localValue.value)
 emit('confirm', localValue.value)
 emit('update:open', false)
}
function handleCancel {
 emit('update:open', false)
}
</script>
<template>
 <Dialog:open="open" @update:open="$emit('update:open', $event)">
 <DialogContent class="max-w-4xl max-h-[90vh] flex flex-col">
 <DialogHeader>
 <DialogTitle>{{ title }}</DialogTitle>
 <DialogDescription v-if="description">
 {{ description }}
 </DialogDescription>
 </DialogHeader>
 <div class="flex-1 min- overflow-hidden py-4">
 <SmartMarkdownEditor
 v-model="localValue":workflow-nodes="workflowNodes":workflow-edges="workflowEdges":current-node-id="currentNodeId":placeholder="placeholder":show-toolbar="true":compact="false":min-rows="12"
 class="h-full [&_.max-]:max-h-[60vh]"
 />
 </div>
 <DialogFooter>
 <Button variant="outline" @click="handleCancel">
 取消
 </Button>
 <Button @click="handleConfirm">
 确定
 </Button>
 </DialogFooter>
 </DialogContent>
 </Dialog>
</template>
