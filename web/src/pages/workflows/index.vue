<script setup lang="ts">
import type { Workflow } from '~/stores/useWorkflowsStore'
import { storeToRefs } from 'pinia'
import { markRaw, onMounted, ref } from 'vue'
import { useModal } from 'vue-final-modal'
import { useRouter } from 'vue-router'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'
import PageContainer from '~/components/layout/PageContainer.vue'
import CreateWorkflowModal from '~/components/workflow/CreateWorkflowModal.vue'
import ExecuteWorkflowModal from '~/components/workflow/ExecuteWorkflowModal.vue'
import WorkflowDataTable from '~/components/workflow/WorkflowDataTable.vue'
import WorkflowEmptyState from '~/components/workflow/WorkflowEmptyState.vue'
import WorkflowPageHeader from '~/components/workflow/WorkflowPageHeader.vue'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
const router = useRouter
const store = useWorkflowsStore
const { workflows, loading } = storeToRefs(store)
const { handleError } = useErrorHandler
const { success } = useToast
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
 onConfirm: async (inputData: Record<string, any>, debugMode: boolean) => {
 close
 await executeWorkflow(inputData, debugMode)
 },
 onCancel: => {
 close
 },
 },
 })
 await open
 }
 }
 catch (e: unknown) {
 handleError(e, '加载工作流')
 }
}
// 执行工作流
async function executeWorkflow(inputData: Record<string, any>, debugMode: boolean = false) {
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
async function handleDelete(workflow: any) {
 // eslint-disable-next-line no-alert
 if (!window.confirm('确定要删除该工作流吗？此操作无法撤销。'))
 return
 try {
 await store.deleteWorkflow(workflow.id)
 success('工作流已删除')
 }
 catch (e: unknown) {
 handleError(e, '删除工作流')
 }
}
async function handleToggleActive(workflow: any, isActive: boolean) {
 try {
 await store.toggleWorkflowActive(workflow.id, isActive)
 success(isActive ? '工作流已启用': '工作流已禁用')
 }
 catch (e: unknown) {
 handleError(e, '切换工作流状态')
 }
}
// 新建工作流弹窗
async function openCreateWorkflow {
 const { open, close } = useModal({
 component: markRaw(CreateWorkflowModal),
 attrs: {
 onClose: => {
 close
 },
 onConfirm: => {
 close
 store.fetchWorkflows
 },
 onCancel: => {
 close
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
