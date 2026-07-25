<script setup lang="ts">
import type { NodeExecution, WorkflowDefinition } from '~/stores/useExecutionsStore'
/**
 * NodeDataTab -- 抽屉输入/输出数据标签页
 *
 * 以 JSON 格式展示节点的输入数据和输出数据。
 * AI 节点的输出数据中，文本字段自动以 Markdown 渲染，
 * 非文本字段仍以 JSON 展示。可切换回原始 JSON 视图。
 *
 * 调试暂停时支持编辑输出 / Mock 输出 / 放行操作：
 * - 编辑模式：编辑现有输出 -> 保存（本地） -> 独立放行
 * - Mock 模式：填写自定义数据 -> 提交 Mock
 * - AI 节点默认进入 Mock 模式，真实执行需确认
 */
import { computed, ref, watch } from 'vue'
import { Button } from '~/components/ui/button'
import { useDebugDataEditor } from '~/composables/useDebugDataEditor'
import { checkMissingKeys, getDownstreamVarDeps } from '~/composables/useDownstreamVarCheck'
import { useExecutionsStore } from '~/stores/useExecutionsStore'
import AISafetyConfirm from './AISafetyConfirm.vue'
import DownstreamVarWarning from './DownstreamVarWarning.vue'
import JsonEditor from './JsonEditor.vue'
import JsonViewer from './JsonViewer.vue'
import MarkdownRenderer from './MarkdownRenderer.vue'

const props = defineProps<{
  nodeExecution: NodeExecution
  isDebugPaused?: boolean
  workflowDefinition?: WorkflowDefinition | null
}>()

const store = useExecutionsStore()

/**
 * AI 节点类型常量
 *
 * ai_plan_generation 已随 Chassis v2 退役（编辑态由迁移 0034 迁到 ai_plan_research），
 * 但历史 NodeExecution 仍带该 node_type，保留以正确渲染旧执行记录。
 */
const AI_NODE_TYPES = [
  'ai_prompt',
  'ai_coding',
  'ai_plan_generation',
  'ai_coding_dispatcher',
] as const

const isAINode = computed(() =>
  AI_NODE_TYPES.includes(props.nodeExecution.node_type as typeof AI_NODE_TYPES[number]),
)

/** "查看原始数据"切换 */
const showRawOutput = ref(false)

/** 编辑/Mock 模式状态 */
type EditMode = 'none' | 'edit' | 'mock'
const currentMode = ref<EditMode>('none')

/** 本地保存的编辑数据（编辑模式下"保存修改"后存储） */
const savedEditedOutput = ref<Record<string, any> | null>(null)
/** 保存成功提示 */
const showSavedHint = ref(false)

/** AI 安全确认对话框 */
const showAISafetyDialog = ref(false)

/** 输出数据的 ref（供 useDebugDataEditor 使用） */
const outputDataRef = computed(() => props.nodeExecution.output_data ?? null)

/** 使用编辑状态管理 composable */
const {
  editedJson,
  isEditing,
  isDirty,
  jsonError,
  startEdit,
  resetEdit,
  cancelEdit,
  getEditedData,
} = useDebugDataEditor(outputDataRef)

/** 切换节点时重置所有状态 */
watch(() => props.nodeExecution.id, () => {
  showRawOutput.value = false
  exitMode()
})

/** AI 节点调试暂停时默认进入 Mock 模式 */
watch(
  [() => props.isDebugPaused, () => props.nodeExecution.id],
  ([paused]) => {
    if (paused && isAINode.value && currentMode.value === 'none') {
      enterMockMode()
    }
  },
  { immediate: true },
)

/** 进入编辑模式 */
function enterEditMode() {
  currentMode.value = 'edit'
  startEdit()
  savedEditedOutput.value = null
  showSavedHint.value = false
}

/** 进入 Mock 模式 */
function enterMockMode() {
  currentMode.value = 'mock'
  // Mock 模式初始化为空对象
  editedJson.value = '{}'
  isEditing.value = true
  savedEditedOutput.value = null
  showSavedHint.value = false
}

/** 退出当前模式 */
function exitMode() {
  currentMode.value = 'none'
  cancelEdit()
  savedEditedOutput.value = null
  showSavedHint.value = false
}

/** 保存修改（仅本地，不发送 WS） */
function handleSave() {
  const data = getEditedData()
  if (data) {
    savedEditedOutput.value = data
    // 重新设定 editedJson 使 isDirty 回到 false 的效果
    showSavedHint.value = true
    setTimeout(() => {
      showSavedHint.value = false
    }, 2000)
  }
}

/** 重置编辑 */
function handleReset() {
  resetEdit()
  savedEditedOutput.value = null
  showSavedHint.value = false
}

/** 取消编辑 */
function handleCancel() {
  exitMode()
}

/** 放行操作（编辑模式） */
function handleRelease() {
  const data: Record<string, any> = {}
  // 优先使用已保存的数据，否则使用当前编辑数据（如果有修改的话）
  if (savedEditedOutput.value) {
    data.edited_output = savedEditedOutput.value
  }
  else if (isDirty.value) {
    const edited = getEditedData()
    if (edited) {
      data.edited_output = edited
    }
  }
  store.sendDebugAction('release', data)
}

/** 提交 Mock */
function handleSubmitMock() {
  const mockData = getEditedData()
  store.sendDebugAction('mock', { mock_output: mockData ?? {} })
}

/** AI 节点真实执行（先确认） */
function handleAIRealExecute() {
  showAISafetyDialog.value = true
}

/** AI 节点确认真实执行 */
function handleAIConfirmExecute() {
  showAISafetyDialog.value = false
  store.sendDebugAction('release')
}

// ----- 下游变量警告 -----
const downstreamWarnings = computed(() => {
  if (!isEditing.value || !props.workflowDefinition)
    return []

  const editedData = getEditedData()
  if (!editedData)
    return []

  const { nodes, edges } = props.workflowDefinition
  const deps = getDownstreamVarDeps(
    nodes,
    edges,
    props.nodeExecution.node,
  )
  return checkMissingKeys(editedData, deps)
})

// ----- 原有的 Markdown 渲染逻辑 -----

/** 智能文本字段检测：判断某个字段是否应该以 Markdown 渲染 */
function isMarkdownField(key: string, value: unknown): boolean {
  if (typeof value !== 'string')
    return false
  if (value.length < 20)
    return false
  const textFieldNames = [
    'text',
    'content',
    'output',
    'result',
    'summary',
    'description',
    'plan',
    'review',
    'analysis',
    'response',
    'final_result',
    'text_output',
  ]
  if (textFieldNames.some(name => key.toLowerCase().includes(name)))
    return true
  const mdPatterns = /^#{1,6}\s|^\*\*|^- |^\d+\.\s|```|^\|.*\|$/m
  return mdPatterns.test(value)
}

/** 分离输出数据：Markdown 可渲染字段 */
const markdownFields = computed(() => {
  if (!isAINode.value || showRawOutput.value)
    return []
  const output = props.nodeExecution.output_data
  if (!output)
    return []
  return Object.entries(output)
    .filter(([key, value]) => isMarkdownField(key, value))
    .map(([key, value]) => ({ key, value: value as string }))
})

/** 分离输出数据：剩余 JSON 字段 */
const jsonFields = computed(() => {
  if (!isAINode.value || showRawOutput.value)
    return props.nodeExecution.output_data
  const output = props.nodeExecution.output_data
  if (!output)
    return null
  const mdKeys = new Set(markdownFields.value.map(f => f.key))
  const remaining = Object.fromEntries(
    Object.entries(output).filter(([key]) => !mdKeys.has(key)),
  )
  return Object.keys(remaining).length > 0 ? remaining : null
})
</script>

<template>
  <div class="space-y-4">
    <!-- 输入数据 -->
    <div class="space-y-2">
      <div class="text-sm font-medium text-foreground">
        输入数据
      </div>
      <JsonViewer :data="nodeExecution.input_data" max-height="250px" />
    </div>

    <!-- 输出数据 -->
    <div class="space-y-2">
      <div class="flex items-center justify-between gap-2">
        <div class="text-sm font-medium text-foreground">
          输出数据
        </div>
        <div class="flex items-center gap-1.5">
          <!-- AI 节点：原始数据 / 智能渲染 切换按钮 -->
          <button
            v-if="isAINode && markdownFields.length > 0 && currentMode === 'none'"
            class="text-xs text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1"
            @click="showRawOutput = !showRawOutput"
          >
            <span class="icon-[lucide--code-2] w-3.5 h-3.5" />
            {{ showRawOutput ? '智能渲染' : '查看原始数据' }}
          </button>
          <!-- 调试暂停时：编辑/Mock 按钮 -->
          <template v-if="isDebugPaused && currentMode === 'none'">
            <Button
              variant="outline"
              size="sm"
              class="h-7 text-xs"
              @click="enterEditMode"
            >
              <span class="icon-[lucide--edit-3] w-3.5 h-3.5 mr-1" />
              编辑输出
            </Button>
            <Button
              variant="outline"
              size="sm"
              class="h-7 text-xs"
              @click="enterMockMode"
            >
              <span class="icon-[lucide--flask-conical] w-3.5 h-3.5 mr-1" />
              Mock 输出
            </Button>
          </template>
        </div>
      </div>

      <!-- 编辑/Mock 模式 -->
      <template v-if="currentMode !== 'none' && isEditing">
        <div class="space-y-3">
          <!-- 模式标签 -->
          <div class="flex items-center gap-2">
            <span
              class="text-xs font-medium px-2 py-0.5 rounded-full"
              :class="currentMode === 'edit' ? 'bg-primary/10 text-primary border border-primary/30' : 'bg-purple-500/10 text-purple-400 border border-purple-500/30'"
            >
              {{ currentMode === 'edit' ? '编辑模式' : 'Mock 模式' }}
            </span>
          </div>

          <!-- 可编辑 JsonEditor -->
          <JsonEditor
            v-model="editedJson"
            height="250px"
          />

          <!-- JSON 错误提示 -->
          <div v-if="jsonError" class="text-xs text-red-400 flex items-center gap-1">
            <span class="icon-[lucide--alert-circle] w-3.5 h-3.5" />
            JSON 格式错误: {{ jsonError }}
          </div>

          <!-- 下游变量警告 -->
          <DownstreamVarWarning :warnings="downstreamWarnings" />

          <!-- 编辑模式操作按钮 -->
          <template v-if="currentMode === 'edit'">
            <div class="flex items-center gap-2 flex-wrap">
              <Button
                variant="secondary"
                size="sm"
                class="h-7 text-xs"
                :disabled="!!jsonError || !isDirty"
                @click="handleSave"
              >
                <span class="icon-[lucide--save] w-3.5 h-3.5 mr-1" />
                {{ showSavedHint ? '已保存' : '保存修改' }}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                class="h-7 text-xs"
                @click="handleReset"
              >
                <span class="icon-[lucide--rotate-ccw] w-3.5 h-3.5 mr-1" />
                重置
              </Button>
              <Button
                variant="ghost"
                size="sm"
                class="h-7 text-xs"
                @click="handleCancel"
              >
                取消
              </Button>
            </div>
            <!-- 独立放行按钮 -->
            <Button
              size="sm"
              class="w-full h-8 text-xs"
              :disabled="!!jsonError"
              @click="handleRelease"
            >
              <span class="icon-[lucide--play] w-3.5 h-3.5 mr-1" />
              放行
            </Button>
          </template>

          <!-- Mock 模式操作按钮 -->
          <template v-if="currentMode === 'mock'">
            <div class="flex items-center gap-2">
              <Button
                size="sm"
                class="h-7 text-xs"
                :disabled="!!jsonError"
                @click="handleSubmitMock"
              >
                <span class="icon-[lucide--flask-conical] w-3.5 h-3.5 mr-1" />
                提交 Mock
              </Button>
              <Button
                variant="ghost"
                size="sm"
                class="h-7 text-xs"
                @click="handleCancel"
              >
                取消
              </Button>
            </div>
          </template>

          <!-- AI 节点额外的真实执行按钮 -->
          <Button
            v-if="isAINode && isDebugPaused"
            variant="outline"
            size="sm"
            class="w-full h-8 text-xs border-amber-500/30 text-amber-400 hover:bg-amber-500/10"
            @click="handleAIRealExecute"
          >
            <span class="icon-[lucide--zap] w-3.5 h-3.5 mr-1" />
            真实执行
          </Button>
        </div>
      </template>

      <!-- 只读模式 -->
      <template v-else>
        <!-- AI 节点智能渲染模式 -->
        <template v-if="isAINode && !showRawOutput && markdownFields.length > 0">
          <!-- Markdown 字段 -->
          <div
            v-for="field in markdownFields"
            :key="field.key"
            class="space-y-1 mb-4"
          >
            <div class="text-xs font-medium text-muted-foreground">
              {{ field.key }}
            </div>
            <div class="card p-4">
              <MarkdownRenderer :content="field.value" />
            </div>
          </div>

          <!-- 剩余 JSON 字段 -->
          <div v-if="jsonFields" class="space-y-1">
            <div class="text-xs font-medium text-muted-foreground">
              其他数据
            </div>
            <JsonViewer :data="jsonFields" max-height="250px" />
          </div>
        </template>

        <!-- 原始 JSON 模式（非 AI 节点 / showRawOutput） -->
        <template v-else>
          <JsonViewer :data="nodeExecution.output_data" max-height="400px" />
        </template>

        <!-- 只读模式下调试暂停时的快捷放行按钮 -->
        <template v-if="isDebugPaused && currentMode === 'none'">
          <Button
            v-if="isAINode"
            variant="outline"
            size="sm"
            class="w-full h-8 text-xs border-amber-500/30 text-amber-400 hover:bg-amber-500/10"
            @click="handleAIRealExecute"
          >
            <span class="icon-[lucide--zap] w-3.5 h-3.5 mr-1" />
            真实执行
          </Button>
        </template>
      </template>
    </div>

    <!-- AI 安全确认对话框 -->
    <AISafetyConfirm
      v-model:open="showAISafetyDialog"
      :node-name="nodeExecution.node_name"
      @confirm="handleAIConfirmExecute"
      @cancel="showAISafetyDialog = false"
    />
  </div>
</template>
