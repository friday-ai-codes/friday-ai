<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { markRaw, onMounted } from 'vue'
import { useModal } from 'vue-final-modal'
import { useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
import CreateWorkflowModal from '~/components/workflow/CreateWorkflowModal.vue'
import WorkflowDataTable from '~/components/workflow/WorkflowDataTable.vue'
import WorkflowEmptyState from '~/components/workflow/WorkflowEmptyState.vue'
import WorkflowPageHeader from '~/components/workflow/WorkflowPageHeader.vue'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
const router = useRouter
const store = useWorkflowsStore
const { workflows, loading } = storeToRefs(store)
onMounted( => {
 store.fetchWorkflows
})
function navigateToEditor(id: string) {
 router.push(`/workflows/${id}`)
}
async function executeWorkflow(workflowId: string) {
 try {
 await store.fetchWorkflow(workflowId)
 const result = await store.executeWorkflow({})
 if (result?.execution_id) {
 toast.success('工作流已启动')
 router.push(`/executions/${result.execution_id}`)
 }
 }
 catch (e: any) {
 toast.error(`执行失败: ${e.message}`)
 }
}
async function handleDelete(workflow: any) {
 // eslint-disable-next-line no-alert
 if (!window.confirm('确定要删除该工作流吗？此操作无法撤销。'))
 return
 try {
 await store.deleteWorkflow(workflow.id)
 toast.success('工作流已删除')
 }
 catch (e: any) {
 toast.error(`删除失败: ${e.message}`)
 }
}
// 新建工作流弹窗
async function openCreateWorkflow {
 const { open } = useModal({
 component: markRaw(CreateWorkflowModal),
 attrs: {
 onConfirm: => {
 store.fetchWorkflows
 },
 },
 })
 await open
}
</script>
<template>
 <div class="max-w-[1400px] mx-auto pb-10 space-y-6">
 <WorkflowPageHeader @create="openCreateWorkflow" />
 <WorkflowEmptyState
 v-if="workflows.length === 0 && !loading"
 @create="openCreateWorkflow"
 />
 <WorkflowDataTable
 v-else:workflows="workflows":loading="loading"
 @click="navigateToEditor($event.id)"
 @execute="executeWorkflow($event.id)"
 @edit="navigateToEditor($event.id)"
 @delete="handleDelete"
 />
 </div>
</template>
