<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
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
import NodeConfigPanel from '~/components/workflow/NodeConfigPanel.vue'
import NodePalette from '~/components/workflow/NodePalette.vue'
import WorkflowCanvas from '~/components/workflow/WorkflowCanvas.vue'
import WorkflowToolbar from '~/components/workflow/WorkflowToolbar.vue'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
const route = useRoute('/workflows/[id]')
const router = useRouter
const id = route.params.id
const store = useWorkflowsStore
const { saving, canUndo, canRedo, hasUnsavedChanges, currentWorkflow: _currentWorkflow } = storeToRefs(store)
// Leave confirmation dialog state
const showLeaveDialog = ref(false)
const pendingNavigation = ref<( => void) | null>(null)
onMounted( => {
 store.fetchWorkflow(id)
 // Check if there's a draft to restore
 if (store.hasDraft) {
 const draftInfo = store.getDraftInfo
 if (draftInfo) {
 toast.info('发现未保存的草稿', {
 description: `保存于 ${new Date(draftInfo.savedAt).toLocaleString}`,
 action: {
 label: '恢复',
 onClick: => {
 store.loadDraft
 toast.success('草稿已恢复')
 },
 },
 duration: 10000,
 })
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
onBeforeRouteLeave((_to, _from, next) => {
 if (hasUnsavedChanges.value) {
 showLeaveDialog.value = true
 pendingNavigation.value = => next
 next(false)
 }
 else {
 next
 }
})
function confirmLeave {
 showLeaveDialog.value = false
 store.clearDraft
 if (pendingNavigation.value) {
 // Reset unsaved changes to allow navigation
 hasUnsavedChanges.value = false
 pendingNavigation.value
 pendingNavigation.value = null
 }
}
function cancelLeave {
 showLeaveDialog.value = false
 pendingNavigation.value = null
}
async function saveAndLeave {
 try {
 await store.saveWorkflow
 toast.success('工作流保存成功')
 showLeaveDialog.value = false
 if (pendingNavigation.value) {
 pendingNavigation.value
 pendingNavigation.value = null
 }
 }
 catch (e: any) {
 toast.error(`保存失败: ${e.message}`)
 }
}
function saveDraftAndLeave {
 store.saveDraft
 toast.success('草稿已保存')
 showLeaveDialog.value = false
 if (pendingNavigation.value) {
 hasUnsavedChanges.value = false
 pendingNavigation.value
 pendingNavigation.value = null
 }
}
async function onSave {
 try {
 await store.saveWorkflow
 toast.success('工作流保存成功')
 }
 catch (e: any) {
 toast.error(`保存失败: ${e.message}`)
 }
}
function onSaveDraft {
 store.saveDraft
 toast.success('草稿已保存到本地')
}
async function onExecute {
 try {
 const result = await store.executeWorkflow
 if (result?.execution_id) {
 toast.success('工作流开始执行')
 router.push(`/workflows/executions/${result.execution_id}`)
 }
 }
 catch (e: any) {
 toast.error(`执行失败: ${e.message}`)
 }
}
function onUndo {
 store.undo
}
function onRedo {
 store.redo
}
function onSettings {
 // Settings are shown in the right panel when no node is selected
 // 未选中节点时显示工作流设置
 store.selectNode(null)
}
</script>
<template>
 <div class="flex flex-col h-[calc(100vh-4rem)] w-full bg-background overflow-hidden relative">
 <!-- 背景装饰 -->
 <div class="absolute inset-0 -z-10 overflow-hidden">
 <div class="absolute -top-40 -right-40 w-80 bg-gradient-to-br from-primary/15 to-violet-500/20 rounded-full blur-3xl" />
 <div class="absolute top-1/2 -left-40 w-96 bg-gradient-to-tr from-blue-500/15 to-cyan-400/10 rounded-full blur-3xl" />
 <div class="absolute -bottom-20 right-1/3 w-64 bg-gradient-to-t from-emerald-500/10 to-transparent rounded-full blur-3xl" />
 </div>
 <!-- Toolbar -->
 <WorkflowToolbar:saving="saving":can-undo="canUndo":can-redo="canRedo":has-unsaved-changes="hasUnsavedChanges"
 @save="onSave"
 @save-draft="onSaveDraft"
 @execute="onExecute"
 @undo="onUndo"
 @redo="onRedo"
 @settings="onSettings"
 />
 <div class="flex flex-1 overflow-hidden">
 <!-- Left Sidebar: Components -->
 <NodePalette />
 <!-- Center: Canvas -->
 <div class="flex-1 relative my-3">
 <WorkflowCanvas:editable="true" />
 </div>
 <!-- Right Sidebar: Configuration -->
 <NodeConfigPanel />
 </div>
 <!-- Leave Confirmation Dialog -->
 <AlertDialog:open="showLeaveDialog">
 <AlertDialogContent>
 <AlertDialogHeader>
 <AlertDialogTitle>有未保存的更改</AlertDialogTitle>
 <AlertDialogDescription>
 您有未保存的工作流更改，离开前请选择操作：
 </AlertDialogDescription>
 </AlertDialogHeader>
 <AlertDialogFooter class="flex-col sm:flex-row gap-2">
 <AlertDialogCancel @click="cancelLeave">
 取消
 </AlertDialogCancel>
 <Button variant="outline" @click="saveDraftAndLeave">
 <span class="icon-[lucide--file-clock] w-4 mr-2" />
 存草稿
 </Button>
 <Button variant="outline" class="text-destructive hover:text-destructive" @click="confirmLeave">
 放弃更改
 </Button>
 <AlertDialogAction @click="saveAndLeave">
 <span class="icon-[lucide--save] w-4 mr-2" />
 保存
 </AlertDialogAction>
 </AlertDialogFooter>
 </AlertDialogContent>
 </AlertDialog>
 </div>
</template>
