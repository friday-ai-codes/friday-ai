<script setup lang="ts">
import type { WorkflowFocusContext } from '~/components/workflow/workflowFocus'
import { storeToRefs } from 'pinia'
import { computed, markRaw, onBeforeUnmount, onMounted, provide, reactive, ref } from 'vue'
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
import WorkflowCanvas from '~/components/workflow/editor/WorkflowCanvas.vue'
import ExecuteWorkflowModal from '~/components/workflow/ExecuteWorkflowModal.vue'
import NodeConfigPanel from '~/components/workflow/node-config/NodeConfigPanel.vue'
import NodePalette from '~/components/workflow/sidebar/NodePalette.vue'
import { WorkflowFocusKey } from '~/components/workflow/workflowFocus'
import WorkflowToolbar from '~/components/workflow/WorkflowToolbar.vue'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'
import { useNodeTypesStore } from '~/stores/useNodeTypesStore'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'

interface NodePaletteItemData { type: string, name: string, description: string }

const route = useRoute('/workflows/[id]')
const router = useRouter()
const id = route.params.id

const store = useWorkflowsStore()
const nodeTypesStore = useNodeTypesStore()
const { saving, canUndo, canRedo, hasUnsavedChanges, currentWorkflow } = storeToRefs(store)
const { nodes } = storeToRefs(store)
const { handleError } = useErrorHandler()
const { success, info } = useToast()

// 画布聚焦持有器：WorkflowCanvas（VueFlow 上下文内）挂载后写入 focusNode，
// 兄弟组件 IssuesPanel 注入后调用，实现"点击问题 → 画布居中"（provide/inject 跨兄弟）。
const workflowFocus = reactive<WorkflowFocusContext>({ focusNode: null, autoLayout: null })
provide(WorkflowFocusKey, workflowFocus)

// Leave confirmation dialog state
const showLeaveDialog = ref(false)
const pendingRoute = ref<string | null>(null)
const historySheetOpen = ref(false)

// 触发器判定由后端 category 派生（不再用硬编码触发器类型列表，SSOT-02）
const hasTriggers = computed(() =>
  nodes.value.some(node => nodeTypesStore.getNodeType(node.nodeType)?.category === 'trigger'),
)

onMounted(async () => {
  // 顺序化：先 fetchNodeTypes 再 fetchWorkflow（RESEARCH Pitfall 4）。
  // 保证 toStoreEdges→migratePortId 与画布 Handle 渲染时后端端口/类型已就绪，
  // 避免存量 edge 句柄退化为 default、首帧空 Handle。
  await nodeTypesStore.fetchNodeTypes()
  await store.fetchWorkflow(id)

  // Check if there's a draft to restore
  if (store.hasDraft()) {
    const draftInfo = store.getDraftInfo()
    if (draftInfo) {
      info(`发现未保存的草稿，保存于 ${new Date(draftInfo.savedAt).toLocaleString()}`)
      // 自动恢复草稿
      store.loadDraft()
      success('草稿已恢复')
    }
  }
})

// Handle browser refresh/close
function handleBeforeUnload(e: BeforeUnloadEvent) {
  if (hasUnsavedChanges.value) {
    e.preventDefault()
    e.returnValue = ''
  }
}

onMounted(() => {
  window.addEventListener('beforeunload', handleBeforeUnload)
})

onBeforeUnmount(() => {
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

function confirmLeave() {
  showLeaveDialog.value = false
  store.clearDraft()
  hasUnsavedChanges.value = false
  if (pendingRoute.value) {
    const route = pendingRoute.value
    pendingRoute.value = null
    router.push(route)
  }
}

function cancelLeave() {
  showLeaveDialog.value = false
  pendingRoute.value = null
}

async function saveAndLeave() {
  try {
    await store.saveWorkflow()
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

async function onSave() {
  try {
    await store.saveWorkflow()
    success('工作流保存成功')
  }
  catch (e: unknown) {
    handleError(e, '保存工作流')
  }
}

function onSaveDraft() {
  store.saveDraft()
  success('草稿已保存到本地')
}

function onExecute() {
  if (!currentWorkflow.value)
    return
  const { open, close } = useModal({
    component: markRaw(ExecuteWorkflowModal),
    attrs: {
      workflow: currentWorkflow.value,
      onConfirm: async (inputData: Record<string, any>, debugMode: boolean) => {
        close()
        await executeWorkflowAction(inputData, debugMode)
      },
      onCancel: () => {
        close()
      },
    },
  })
  open()
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

function onUndo() {
  store.undo()
}

function onAutoLayout() {
  workflowFocus.autoLayout?.()
}

function onRedo() {
  store.redo()
}

function onExportJSON() {
  const ok = store.exportWorkflowJSON()
  if (ok) {
    success('工作流已导出为 JSON')
  }
  else {
    info('当前无工作流可导出')
  }
}

function onBack() {
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
      success(isActive ? '工作流已启用' : '工作流已禁用')
    }
    catch (e: unknown) {
      handleError(e, '切换工作流状态')
    }
  }
}
</script>

<template>
  <div class="flex flex-col h-[calc(100vh-4rem)] w-full bg-background bg-mesh-gradient overflow-hidden relative">
    <!-- 背景装饰 -->
    <div class="absolute inset-0 -z-10 overflow-hidden">
      <div class="absolute inset-x-0 top-0 h-48 bg-linear-to-b from-primary/8 to-transparent" />
    </div>

    <!-- Toolbar -->
    <WorkflowToolbar
      :workflow-name="currentWorkflow?.name"
      :workflow-description="currentWorkflow?.description"
      :workflow-id="id"
      :is-active="currentWorkflow?.is_active ?? true"
      :saving="saving"
      :can-undo="canUndo"
      :can-redo="canRedo"
      :has-unsaved-changes="hasUnsavedChanges"
      :has-triggers="hasTriggers"
      @save="onSave"
      @save-draft="onSaveDraft"
      @execute="onExecute"
      @undo="onUndo"
      @redo="onRedo"
      @auto-layout="onAutoLayout"
      @back="onBack"
      @history="historySheetOpen = true"
      @export-j-s-o-n="onExportJSON"
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
      <SheetContent side="right" class="w-[420px] sm:max-w-[420px] p-0 flex flex-col">
        <SheetHeader class="px-4 py-3 border-b border-border/50 shrink-0">
          <SheetTitle>执行历史</SheetTitle>
        </SheetHeader>
        <div class="flex-1 overflow-y-auto p-4">
          <ExecutionHistoryList
            :workflow-id="id"
            @execute="onExecute"
          />
        </div>
      </SheetContent>
    </Sheet>

    <!-- Leave Confirmation Dialog -->
    <AlertDialog :open="showLeaveDialog">
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
