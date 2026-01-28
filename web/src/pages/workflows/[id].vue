<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
import NodeConfigPanel from '~/components/workflow/NodeConfigPanel.vue'
import NodePalette from '~/components/workflow/NodePalette.vue'
import WorkflowCanvas from '~/components/workflow/WorkflowCanvas.vue'
import WorkflowToolbar from '~/components/workflow/WorkflowToolbar.vue'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
const route = useRoute
const router = useRouter
const id = route.params.id as string
const store = useWorkflowsStore
const { saving, canUndo, canRedo, currentWorkflow: _currentWorkflow } = storeToRefs(store)
onMounted( => {
 store.fetchWorkflow(id)
})
async function onSave {
 try {
 await store.saveWorkflow
 toast.success('工作流保存成功')
 }
 catch (e: any) {
 toast.error(`保存失败: ${e.message}`)
 }
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
 <WorkflowToolbar:saving="saving":can-undo="canUndo":can-redo="canRedo"
 @save="onSave"
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
 </div>
</template>
