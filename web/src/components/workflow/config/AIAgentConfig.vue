<script setup lang="ts">
import type { WorkflowEdge, WorkflowNode } from '~/types/workflow/store'
import { onMounted, ref } from 'vue'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { Separator } from '~/components/ui/separator'
import { MarkdownEditorModal, SmartMarkdownEditor, SmartTextarea } from '~/components/workflow/smart-input'
import { useConfigModel } from '~/composables/useConfigModel'
import ToolSelector from './ToolSelector.vue'
/**
 * AIAgentConfig - Configuration panel for AI Agent workflow node.
 *
 * Features:
 * - System Prompt: Markdown editor with variable support
 * - User Prompt: Required, supports template variables
 * - Tool Selection: Multi-select with search/filter
 * - Max Iterations: 1-100, default 25
 * - Timeout Hours: Default 24
 */
// ============================================================================
// Types
// ============================================================================
interface AIAgentConfig {
 system_prompt: string
 user_prompt: string
 enabled_tools: string
 max_iterations: number
 timeout_hours: number
}
interface Tool {
 name: string
 description: string
 category?: string
}
// ============================================================================
// Props & Emits
// ============================================================================
interface Props {
 config: AIAgentConfig
 workflowNodes?: WorkflowNode
 workflowEdges?: WorkflowEdge
 currentNodeId?: string
}
const props = withDefaults(defineProps<Props>, {
 workflowNodes: =>,
 workflowEdges: =>,
 currentNodeId: '',
})
const emit = defineEmits<{
 (e: 'update:config', value: AIAgentConfig): void
}>
// ============================================================================
// Config Model
// ============================================================================
const { field } = useConfigModel({
 config: => props.config,
 emit: v => emit('update:config', v),
})
const systemPrompt = field('system_prompt', '')
const userPrompt = field('user_prompt', '')
const enabledTools = field('enabled_tools', )
const maxIterations = field('max_iterations', 25)
const timeoutHours = field('timeout_hours', 24)
// ============================================================================
// Tools Data
// ============================================================================
const tools = ref<Tool>
const toolsLoading = ref(false)
const toolsError = ref<string | null>(null)
async function fetchTools {
 toolsLoading.value = true
 toolsError.value = null
 try {
 const response = await fetch('/api/agents/tools/')
 if (!response.ok) {
 throw new Error(`Failed to fetch tools: ${response.status}`)
 }
 const data = await response.json
 tools.value = data.tools || data ||
 }
 catch (error) {
 console.error('Failed to fetch tools:', error)
 toolsError.value = error instanceof Error ? error.message: 'Unknown error'
 // Fallback to empty array
 tools.value =
 }
 finally {
 toolsLoading.value = false
 }
}
onMounted( => {
 fetchTools
})
// ============================================================================
// Modal State
// ============================================================================
const systemPromptModalOpen = ref(false)
const userPromptModalOpen = ref(false)
</script>
<template>
 <div class="space-y-4">
 <!-- System Prompt -->
 <div class="space-y-2">
 <Label>系统提示词</Label>
 <SmartMarkdownEditor
 v-model="systemPrompt":workflow-nodes="workflowNodes":workflow-edges="workflowEdges":current-node-id="currentNodeId"
 placeholder="定义 Agent 的角色和行为规范...":min-rows="3":show-toolbar="true":compact="true"
 @expand="systemPromptModalOpen = true"
 />
 <p class="text-xs text-muted-foreground">
 定义 AI Agent 的角色、能力范围和行为准则
 </p>
 </div>
 <!-- User Prompt -->
 <div class="space-y-2">
 <Label class="flex items-center gap-2">
 用户提示词
 <span class="text-destructive">*</span>
 </Label>
 <SmartTextarea
 v-model="userPrompt":workflow-nodes="workflowNodes":workflow-edges="workflowEdges":current-node-id="currentNodeId"
 placeholder="输入 {{ 触发变量自动补全...":min-rows="4"
 @expand="userPromptModalOpen = true"
 />
 <p class="text-xs text-muted-foreground">
 初始任务指令，输入 <code v-pre class="bg-muted px-1 py-0.5 rounded text-primary">{{</code> 触发变量自动补全
 </p>
 </div>
 <Separator />
 <!-- Tool Selection -->
 <div class="space-y-2">
 <div v-if="toolsLoading" class="flex items-center gap-2 text-sm text-muted-foreground">
 <span class="icon-[lucide--loader-2] animate-spin" />
 加载工具列表...
 </div>
 <div v-else-if="toolsError" class="text-sm text-destructive">
 加载工具失败: {{ toolsError }}
 <button
 type="button"
 class="ml-2 text-primary hover:underline"
 @click="fetchTools"
 >
 重试
 </button>
 </div>
 <ToolSelector
 v-else
 v-model="enabledTools":tools="tools"
 />
 </div>
 <Separator />
 <!-- Max Iterations -->
 <div class="space-y-2">
 <Label>最大迭代次数</Label>
 <Input
 v-model="maxIterations"
 type="number":min="1":max="100"
 class="bg-background/50"
 />
 <p class="text-xs text-muted-foreground">
 Agent 最多执行的思考-行动循环次数 (1-100)
 </p>
 </div>
 <!-- Timeout Hours -->
 <div class="space-y-2">
 <Label>挂起超时 (小时)</Label>
 <Input
 v-model="timeoutHours"
 type="number":min="1":max="168"
 class="bg-background/50"
 />
 <p class="text-xs text-muted-foreground">
 Agent 挂起等待用户响应的最长时间
 </p>
 </div>
 <!-- System Prompt Modal -->
 <MarkdownEditorModal
 v-model:open="systemPromptModalOpen"
 v-model="systemPrompt"
 title="编辑系统提示词"
 description="定义 AI Agent 的角色、能力范围和行为准则":workflow-nodes="workflowNodes":workflow-edges="workflowEdges":current-node-id="currentNodeId"
 placeholder="定义 Agent 的角色和行为规范..."
 />
 <!-- User Prompt Modal -->
 <MarkdownEditorModal
 v-model:open="userPromptModalOpen"
 v-model="userPrompt"
 title="编辑用户提示词"
 description="输入 {{ 触发变量自动补全":workflow-nodes="workflowNodes":workflow-edges="workflowEdges":current-node-id="currentNodeId"
 placeholder="输入 {{ 触发变量自动补全..."
 />
 </div>
</template>
