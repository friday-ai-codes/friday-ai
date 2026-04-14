<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { computed, markRaw, onBeforeUnmount, onMounted, ref } from 'vue'
import { useModal } from 'vue-final-modal'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import ExecutionHistoryList from '~/components/execution/ExecutionHistoryList.vue'
import {
 AlertDialog,
 AlertDialogAction,
 AlertDialogCancel,
 AlertDialogContent,
 AlertDialogDescription,
 AlertDialogFooter,
 AlertDialogHeader,
 AlertDialogTitle,
} from '~/components/ui/alert-dialog'
import { Button } from '~/components/ui/button'
import {
 Sheet,
 SheetContent,
 SheetHeader,
 SheetTitle,
} from '~/components/ui/sheet'
import { TRIGGER_NODE_TYPES } from '~/components/workflow/editor/utils/portConfig'
import WorkflowCanvas from '~/components/workflow/editor/WorkflowCanvas.vue'
import ExecuteWorkflowModal from '~/components/workflow/ExecuteWorkflowModal.vue'
import NodeConfigPanel from '~/components/workflow/node-config/NodeConfigPanel.vue'
import NodePalette from '~/components/workflow/sidebar/NodePalette.vue'
import WorkflowToolbar from '~/components/workflow/WorkflowToolbar.vue'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'
import { useNodeTypesStore } from '~/stores/useNodeTypesStore'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
interface NodePaletteItemData { type: string, name: string, description: string }
const route = useRoute('/workflows/[id]')
const router = useRouter
const id = route.params.id
const store = useWorkflowsStore
const nodeTypesStore = useNodeTypesStore
const { saving, canUndo, canRedo, hasUnsavedChanges, currentWorkflow } = storeToRefs(store)
const { nodes } = storeToRefs(store)
const { handleError } = useErrorHandler
const { success, info } = useToast
// Leave confirmation dialog state
const showLeaveDialog = ref(false)
const pendingRoute = ref<string | null>(null)
const historySheetOpen = ref(false)
const hasTriggers = computed( =>
 nodes.value.some(node => TRIGGER_NODE_TYPES.includes(node.nodeType)),
)
onMounted(async => {
 // Fetch node types and workflow data in parallel
 await Promise.all([
 nodeTypesStore.fetchNodeTypes,
 store.fetchWorkflow(id),
 ])
 // Check if there's a draft to restore
 if (store.hasDraft) {
 const draftInfo = store.getDraftInfo
 if (draftInfo) {
 info(`发现未保存的草稿，保存于 ${new Date(draftInfo.savedAt).toLocaleString}`)
 // 自动恢复草稿
 store.loadDraft
 success('草稿已恢复')
 }
 }
})
// Handle browser refresh/close
function handleBeforeUnload(e: BeforeUnloadEvent) {
 if (hasUnsavedChanges.value) {
 e.preventDefault
 e.returnValue = ''
 }
}
onMounted( => {
 window.addEventListener('beforeunload', handleBeforeUnload)
})
onBeforeUnmount( => {
 window.removeEventListener('beforeunload', handleBeforeUnload)
})
// Handle Vue Router navigation
onBeforeRouteLeave((to) => {
 if (hasUnsavedChanges.value) {
 showLeaveDialog.value = true
 pendingRoute.value = to.fullPath
 return false
 }
})
function confirmLeave {
 showLeaveDialog.value = false
 store.clearDraft
 hasUnsavedChanges.value = false
 if (pendingRoute.value) {
 const route = pendingRoute.value
 pendingRoute.value = null
 router.push(route)
 }
}
function cancelLeave {
 showLeaveDialog.value = false
 pendingRoute.value = null
}
async function saveAndLeave {
 try {
 await store.saveWorkflow
 success('工作流保存成功')
 showLeaveDialog.value = false
 if (pendingRoute.value) {
 const route = pendingRoute.value
 pendingRoute.value = null
 router.push(route)
 }
 }
 catch (e: unknown) {
 handleError(e, '保存工作流')
 }
}
async function onSave {
 try {
 await store.saveWorkflow
 success('工作流保存成功')
 }
 catch (e: unknown) {
 handleError(e, '保存工作流')
 }
}
function onSaveDraft {
 store.saveDraft
 success('草稿已保存到本地')
}
function onExecute {
 if (!currentWorkflow.value)
 return
 const { open, close } = useModal({
 component: markRaw(ExecuteWorkflowModal),
 attrs: {
 workflow: currentWorkflow.value,
 onConfirm: async (inputData: Record<string, any>, debugMode: boolean) => {
 close
 await executeWorkflowAction(inputData, debugMode)
 },
 onCancel: => {
 close
 },
 },
 })
 open
}
async function executeWorkflowAction(inputData: Record<string, any>, debugMode: boolean = false) {
 try {
 const result = await store.executeWorkflow(inputData, debugMode)
 if (result?.execution_id) {
 success('工作流已启动')
 router.push(`/executions/${result.execution_id}`)
 }
 }
 catch (e: unknown) {
 handleError(e, '执行工作流')
 }
}
function onUndo {
 store.undo
}
function onRedo {
 store.redo
}
function onBack {
 router.push('/workflows')
}
function handleNodeDragStart(nodeData: NodePaletteItemData, event: MouseEvent) {
 // VueFlow drag-and-drop: set data on the native drag event
 // The canvas component handles the drop via @dragover/@drop
 const dragEvent = event as unknown as DragEvent
 dragEvent.dataTransfer?.setData('application/workflow-node', JSON.stringify({
 type: nodeData.type,
 name: nodeData.name,
 description: nodeData.description,
 }))
}
function onUpdateWorkflowName(name: string) {
 if (currentWorkflow.value) {
 store.updateWorkflowSettings({ ...currentWorkflow.value, name })
 }
}
function onUpdateWorkflowDescription(description: string) {
 if (currentWorkflow.value) {
 store.updateWorkflowSettings({ ...currentWorkflow.value, description })
 }
}
async function onUpdateIsActive(isActive: boolean) {
 if (currentWorkflow.value) {
 try {
 await store.toggleWorkflowActive(currentWorkflow.value.id, isActive)
 success(isActive ? '工作流已启用': '工作流已禁用')
 }
 catch (e: unknown) {
 handleError(e, '切换工作流状态')
 }
 }
}
</script>
<template>
 <div class="flex flex-col h-[calc(100vh-4rem)] w-full bg-background overflow-hidden relative">
 <!-- 背景装饰 -->
 <div class="absolute inset-0 -z-10 overflow-hidden">
 <div class="absolute -top-40 -right-40 w-80 bg-primary/10 rounded-full blur-3xl" />
 <div class="absolute top-1/2 -left-40 w-96 bg-gradient-to-tr from-primary/15 to-primary/10 rounded-full blur-3xl" />
 <div class="absolute -bottom-20 right-1/3 w-64 bg-primary/10 rounded-full blur-3xl" />
 </div>
 <!-- Toolbar -->
 <WorkflowToolbar:workflow-name="currentWorkflow?.name":workflow-description="currentWorkflow?.description":workflow-id="id":is-active="currentWorkflow?.is_active ?? true":saving="saving":can-undo="canUndo":can-redo="canRedo":has-unsaved-changes="hasUnsavedChanges":has-triggers="hasTriggers"
 @save="onSave"
 @save-draft="onSaveDraft"
 @execute="onExecute"
 @undo="onUndo"
 @redo="onRedo"
 @back="onBack"
 @history="historySheetOpen = true"
 @update:workflow-name="onUpdateWorkflowName"
 @update:workflow-description="onUpdateWorkflowDescription"
 @update:is-active="onUpdateIsActive"
 />
 <div class="flex flex-1 overflow-hidden">
 <!-- Left Sidebar: Components -->
 <NodePalette @drag-start="handleNodeDragStart" />
 <!-- Center: Canvas with Config Panel overlay -->
 <div class="flex-1 relative my-3">
 <WorkflowCanvas />
 <!-- Right Sidebar: Configuration (floating over canvas) -->
 <NodeConfigPanel />
 </div>
 </div>
 <!-- Execution History Sheet -->
 <Sheet v-model:open="historySheetOpen">
 <SheetContent side="right" class="w-[420px] sm:max-w-[420px] flex flex-col">
 <SheetHeader class="px-4 py-3 border-b border-border/50 shrink-0">
 <SheetTitle>执行历史</SheetTitle>
 </SheetHeader>
 <div class="flex-1 overflow-y-auto ">
 <ExecutionHistoryList:workflow-id="id"
 @execute="onExecute"
 />
 </div>
 </SheetContent>
 </Sheet>
 <!-- Leave Confirmation Dialog -->
 <AlertDialog:open="showLeaveDialog">
 <AlertDialogContent @escape-key-down="cancelLeave">
 <AlertDialogHeader>
 <AlertDialogTitle>有未保存的更改</AlertDialogTitle>
 <AlertDialogDescription>
 您有未保存的工作流更改，是否保存后再离开？
 </AlertDialogDescription>
 </AlertDialogHeader>
 <AlertDialogFooter class="flex-col sm:flex-row gap-2">
 <AlertDialogCancel @click="cancelLeave">
 取消
 </AlertDialogCancel>
 <Button variant="outline" class="text-destructive hover:text-destructive hover:bg-destructive/10" @click="confirmLeave">
 不保存退出
 </Button>
 <AlertDialogAction @click="saveAndLeave">
 保存并退出
 </AlertDialogAction>
 </AlertDialogFooter>
 </AlertDialogContent>
 </AlertDialog>
 </div>
</template>
