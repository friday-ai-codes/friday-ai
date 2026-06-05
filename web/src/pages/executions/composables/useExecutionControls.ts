import type { Ref } from 'vue'
import type { NodeExecution, useExecutionsStore } from '~/stores/useExecutionsStore'
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'

export function useExecutionControls(
  executionId: Ref<string>,
  store: ReturnType<typeof useExecutionsStore>,
  selectedNodeExecution: Ref<NodeExecution | null>,
) {
  const router = useRouter()
  const { handleError } = useErrorHandler()
  const { success } = useToast()

  // ----- 操作按钮 loading 态 -----
  const isPausing = ref(false)
  const isResuming = ref(false)
  const isCancelling = ref(false)
  const isRetrying = ref(false)

  // ----- 对话框状态（审批 + 触发） -----
  const approvalDialogOpen = ref(false)
  const approvalComment = ref('')
  const approving = ref(false)
  const triggerDialogOpen = ref(false)
  const triggerInputData = ref('')
  const triggering = ref(false)

  // ----- 顶部栏操作按钮 -----
  async function handlePause() {
    if (isPausing.value)
      return
    isPausing.value = true
    try {
      await store.pauseExecution(executionId.value)
      success('工作流已暂停')
    }
    catch (e: unknown) {
      handleError(e, '暂停')
    }
    finally {
      isPausing.value = false
    }
  }

  async function handleResume() {
    if (isResuming.value)
      return
    isResuming.value = true
    try {
      await store.resumeExecution(executionId.value)
      success('工作流已恢复')
    }
    catch (e: unknown) {
      handleError(e, '恢复')
    }
    finally {
      isResuming.value = false
    }
  }

  async function handleCancel() {
    if (isCancelling.value)
      return
    isCancelling.value = true
    try {
      await store.cancelExecution(executionId.value)
      success('工作流已取消')
    }
    catch (e: unknown) {
      handleError(e, '取消')
    }
    finally {
      isCancelling.value = false
    }
  }

  async function handleRetry() {
    if (isRetrying.value)
      return
    isRetrying.value = true
    try {
      const { retryExecution } = await import('~/api/workflow')
      const result = await retryExecution(executionId.value)
      if (result?.execution_id) {
        success('工作流重新执行成功')
        router.push(`/executions/${result.execution_id}`)
      }
    }
    catch (e: unknown) {
      handleError(e, '重试')
    }
    finally {
      isRetrying.value = false
    }
  }

  // ----- 审批/触发对话框 -----
  async function handleApprove() {
    if (!selectedNodeExecution.value)
      return
    approving.value = true
    try {
      await store.approveNode(selectedNodeExecution.value.id, approvalComment.value)
      approvalDialogOpen.value = false
      approvalComment.value = ''
      success('节点已批准')
    }
    catch (e: unknown) {
      handleError(e, '批准')
    }
    finally {
      approving.value = false
    }
  }

  async function handleReject() {
    if (!selectedNodeExecution.value)
      return
    approving.value = true
    try {
      await store.rejectNode(selectedNodeExecution.value.id, approvalComment.value)
      approvalDialogOpen.value = false
      approvalComment.value = ''
      success('节点已拒绝')
    }
    catch (e: unknown) {
      handleError(e, '拒绝')
    }
    finally {
      approving.value = false
    }
  }

  async function handleTrigger() {
    if (!selectedNodeExecution.value)
      return
    triggering.value = true
    try {
      let inputData = {}
      if (triggerInputData.value.trim()) {
        try {
          inputData = JSON.parse(triggerInputData.value)
        }
        catch {
          handleError(new Error('输入数据格式错误，请输入有效的 JSON'), '解析输入')
          triggering.value = false
          return
        }
      }
      await store.triggerNode(selectedNodeExecution.value.id, inputData)
      triggerDialogOpen.value = false
      triggerInputData.value = '{}'
      success('节点已触发')
    }
    catch (e: unknown) {
      handleError(e, '触发')
    }
    finally {
      triggering.value = false
    }
  }

  return {
    isPausing,
    isResuming,
    isCancelling,
    isRetrying,
    approvalDialogOpen,
    approvalComment,
    approving,
    triggerDialogOpen,
    triggerInputData,
    triggering,
    handlePause,
    handleResume,
    handleCancel,
    handleRetry,
    handleApprove,
    handleReject,
    handleTrigger,
  }
}
