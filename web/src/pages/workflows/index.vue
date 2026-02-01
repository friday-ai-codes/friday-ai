<script setup lang="ts">
import type { Workflow } from '~/stores/useWorkflowsStore'
import { storeToRefs } from 'pinia'
import { markRaw, onMounted, ref } from 'vue'
import { useModal } from 'vue-final-modal'
import { useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
import CreateWorkflowModal from '~/components/workflow/CreateWorkflowModal.vue'
import ExecuteWorkflowModal from '~/components/workflow/ExecuteWorkflowModal.vue'
import PageContainer from '~/components/layout/PageContainer.vue'
import WorkflowDataTable from '~/components/workflow/WorkflowDataTable.vue'
import WorkflowEmptyState from '~/components/workflow/WorkflowEmptyState.vue'
import WorkflowPageHeader from '~/components/workflow/WorkflowPageHeader.vue'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
const router = useRouter
const store = useWorkflowsStore
const { workflows, loading } = storeToRefs(store)
// 当前要执行的工作流
const workflowToExecute = ref<Workflow | null>(null)
onMounted( => {
 store.fetchWorkflows
})
function navigateToEditor(id: string) {
 router.push(`/workflows/${id}`)
}
// 打开执行弹窗
async function openExecuteModal(workflowId: string) {
 try {
 await store.fetchWorkflow(workflowId)
 if (store.currentWorkflow) {
 workflowToExecute.value = store.currentWorkflow
 const { open, close } = useModal({
 component: markRaw(ExecuteWorkflowModal),
 attrs: {
 workflow: workflowToExecute.value,
 onConfirm: async (inputData: Record<string, any>) => {
 close
 await executeWorkflow(inputData)
 },
 onCancel: => {
 close
 },
 },
 })
 await open
 }
 }
 catch (e: any) {
 toast.error(`加载工作流失败: ${e.message}`)
 }
}
// 执行工作流
async function executeWorkflow(inputData: Record<string, any>) {
 try {
 const result = await store.executeWorkflow(inputData)
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
async function handleToggleActive(workflow: any, isActive: boolean) {
 try {
 await store.toggleWorkflowActive(workflow.id, isActive)
 toast.success(isActive ? '工作流已启用': '工作流已禁用')
 }
 catch (e: any) {
 toast.error(`操作失败: ${e.message}`)
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
 <PageContainer>
 <WorkflowPageHeader @create="openCreateWorkflow" />
 <WorkflowEmptyState
 v-if="workflows.length === 0 && !loading"
 @create="openCreateWorkflow"
 />
 <WorkflowDataTable
 v-else:workflows="workflows":loading="loading"
 @click="navigateToEditor($event.id)"
 @execute="openExecuteModal($event.id)"
 @edit="navigateToEditor($event.id)"
 @delete="handleDelete"
 @toggle-active="handleToggleActive"
 />
 </PageContainer>
</template>
