import type { Ref } from 'vue'
import type { Router } from 'vue-router'
import type { ResumePreviewNode } from '~/api/workflow'
import type { WorkflowExecution } from '~/stores/useExecutionsStore'
import { ref } from 'vue'
import { toast } from 'vue-sonner'
import { ApiError } from '~/api/client'
import { resumeFromFailed, resumePreview } from '~/api/workflow'
export function useResumeLogic(
 executionId: Ref<string>,
 currentExecution: Ref<WorkflowExecution | null>,
 definitionChanged: Ref<boolean>,
 router: Router,
) {
 const resumeDialogOpen = ref(false)
 const resumeNodeId = ref<string | null>(null)
 const resumeNodeName = ref('')
 const resumeSkipCount = ref(0)
 const resuming = ref(false)
 const resumeSkipNodes = ref<ResumePreviewNode>
 const resumeRerunNodes = ref<ResumePreviewNode>
 const resumePreviewLoading = ref(false)
 async function handleResumeClick(nodeId: string) {
 const exec = currentExecution.value
 if (!exec?.workflow_definition)
 return
 const defNode = exec.workflow_definition.nodes.find(n => n.id === nodeId)
 resumeNodeName.value = defNode?.name ?? nodeId
 resumeNodeId.value = nodeId
 resumeDialogOpen.value = true
 resumePreviewLoading.value = true
 resumeSkipNodes.value =
 resumeRerunNodes.value =
 try {
 const preview = await resumePreview(executionId.value, nodeId)
 resumeSkipNodes.value = preview.skip_nodes
 resumeRerunNodes.value = preview.rerun_nodes
 resumeSkipCount.value = preview.total_skip
 }
 catch {
 resumeSkipCount.value = (exec.completed_nodes ?? 0) + (exec.skipped_nodes ?? 0)
 }
 finally {
 resumePreviewLoading.value = false
 }
 }
 async function handleResumeFromFailed {
 if (!resumeNodeId.value)
 return
 resuming.value = true
 try {
 const result = await resumeFromFailed(executionId.value, resumeNodeId.value)
 if (result?.execution_id) {
 toast.success('已从失败节点继续执行')
 resumeDialogOpen.value = false
 router.push(`/executions/${result.execution_id}`)
 }
 }
 catch (e: unknown) {
 if (e instanceof ApiError && e.status === 409) {
 toast.error('工作流定义已修改，无法从此继续')
 definitionChanged.value = true
 resumeDialogOpen.value = false
 }
 else {
 const message = e instanceof ApiError ? e.detail: (e instanceof Error ? e.message: '未知错误')
 toast.error(`继续执行失败: ${message}`)
 }
 }
 finally {
 resuming.value = false
 }
 }
 return {
 resumeDialogOpen,
 resumeNodeId,
 resumeNodeName,
 resumeSkipCount,
 resuming,
 resumeSkipNodes,
 resumeRerunNodes,
 resumePreviewLoading,
 handleResumeClick,
 handleResumeFromFailed,
 }
}
