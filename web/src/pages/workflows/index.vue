<script setup lang="ts">
import type { Workflow } from '~/stores/useWorkflowsStore'
import { storeToRefs } from 'pinia'
import { markRaw, onMounted, ref } from 'vue'
import { useModal } from 'vue-final-modal'
import { useRouter } from 'vue-router'
import PageContainer from '~/components/layout/PageContainer.vue'
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '~/components/ui/alert-dialog'
import { Button } from '~/components/ui/button'

import CreateWorkflowModal from '~/components/workflow/CreateWorkflowModal.vue'
import ExecuteWorkflowModal from '~/components/workflow/ExecuteWorkflowModal.vue'
import WorkflowDataTable from '~/components/workflow/WorkflowDataTable.vue'
import WorkflowEmptyState from '~/components/workflow/WorkflowEmptyState.vue'
import WorkflowPageHeader from '~/components/workflow/WorkflowPageHeader.vue'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'

const router = useRouter()
const store = useWorkflowsStore()
const { workflows, loading } = storeToRefs(store)
const { handleError } = useErrorHandler()
const { success } = useToast()

// 当前要执行的工作流
const workflowToExecute = ref<Workflow | null>(null)
const workflowToDelete = ref<Workflow | null>(null)
const deletingWorkflow = ref(false)

onMounted(() => {
  store.fetchWorkflows()
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
            close()
            await executeWorkflow(inputData, debugMode)
          },
          onCancel: () => {
            close()
          },
        },
      })
      await open()
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

function requestDelete(workflow: Workflow) {
  workflowToDelete.value = workflow
}

function cancelDelete() {
  if (deletingWorkflow.value)
    return
  workflowToDelete.value = null
}

async function handleDelete() {
  const target = workflowToDelete.value
  if (!target || deletingWorkflow.value)
    return

  deletingWorkflow.value = true
  try {
    await store.deleteWorkflow(target.id)
    success('工作流已删除')
    workflowToDelete.value = null
  }
  catch (e: unknown) {
    handleError(e, '删除工作流')
  }
  finally {
    deletingWorkflow.value = false
  }
}

async function handleToggleActive(workflow: any, isActive: boolean) {
  try {
    await store.toggleWorkflowActive(workflow.id, isActive)
    success(isActive ? '工作流已启用' : '工作流已禁用')
  }
  catch (e: unknown) {
    handleError(e, '切换工作流状态')
  }
}

// 新建工作流弹窗
async function openCreateWorkflow() {
  const { open, close } = useModal({
    component: markRaw(CreateWorkflowModal),
    attrs: {
      onClose: () => {
        close()
      },
      onConfirm: () => {
        close()
        store.fetchWorkflows()
      },
      onCancel: () => {
        close()
      },
    },
  })
  await open()
}
</script>

<template>
  <PageContainer>
    <WorkflowPageHeader @create="openCreateWorkflow" />

    <WorkflowEmptyState
      v-if="workflows.length === 0 && !loading"
      @create="openCreateWorkflow"
    />

    <!-- 骨架屏只在首次加载（无缓存数据）时出现；store 已有数据时直接展示，后台静默刷新，避免页面抖动 -->
    <WorkflowDataTable
      v-else
      :workflows="workflows"
      :loading="loading && workflows.length === 0"
      @click="navigateToEditor($event.id)"
      @execute="openExecuteModal($event.id)"
      @edit="navigateToEditor($event.id)"
      @request-delete="requestDelete"
      @toggle-active="handleToggleActive"
    />

    <AlertDialog :open="!!workflowToDelete" @update:open="(open) => { if (!open) cancelDelete() }">
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>删除工作流</AlertDialogTitle>
          <AlertDialogDescription>
            确定要删除
            <span class="font-medium text-foreground">{{ workflowToDelete?.name }}</span>
            吗？此操作无法撤销。
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel :disabled="deletingWorkflow" @click="cancelDelete">
            取消
          </AlertDialogCancel>
          <Button
            type="button"
            variant="destructive"
            :disabled="deletingWorkflow"
            @click="handleDelete"
          >
            <span v-if="deletingWorkflow" class="icon-[lucide--loader-circle] animate-spin" />
            {{ deletingWorkflow ? '删除中' : '删除' }}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </PageContainer>
</template>
