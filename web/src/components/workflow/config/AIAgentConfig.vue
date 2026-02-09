<script setup lang="ts">
import type { WorkflowEdge, WorkflowNode } from '~/types/workflow/store'
import { onMounted, ref } from 'vue'
import { get } from '~/api/client'
import {
 Collapsible,
 CollapsibleContent,
 CollapsibleTrigger,
} from '~/components/ui/collapsible'
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
 config: => props.config as unknown as Record<string, unknown>,
 emit: v => emit('update:config', v as unknown as AIAgentConfig),
})
const systemPrompt = field('system_prompt', '') as import('vue').WritableComputedRef<string>
const userPrompt = field('user_prompt', '') as import('vue').WritableComputedRef<string>
const enabledTools = field('enabled_tools', ) as import('vue').WritableComputedRef<string>
const maxIterations = field('max_iterations', 25) as import('vue').WritableComputedRef<number>
const timeoutHours = field('timeout_hours', 24) as import('vue').WritableComputedRef<number>
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
 const data = await get<{ tools: Tool }>('/agents/tools/')
 tools.value = data.tools ||
 }
 catch (error) {
 console.error('Failed to fetch tools:', error)
 toolsError.value = error instanceof Error ? error.message: 'Unknown error'
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
const advancedOpen = ref(false)
</script>
<template>
 <div class="space-y-4">
 <!-- Introduction -->
 <div class="rounded-xl bg-gradient-to-br from-violet-500/10 to-blue-400/5 border border-violet-500/20 ">
 <div class="flex items-start gap-2">
 <span class="icon-[lucide--brain-circuit] text-violet-500 text-lg shrink-0 mt-0.5" />
 <div class="space-y-2">
 <h4 class="text-sm font-medium">Friday AI Agent</h4>
 <p class="text-xs text-muted-foreground leading-relaxed">
 自主决策的智能代理，通过 <span class="text-violet-600 font-medium">Think-Act-Observe</span> 循环完成复杂任务。
 </p>
 <!-- ReAct Workflow Visual -->
 <div class="flex items-center gap-1 text-[10px] py-1.5 px-2 rounded-lg bg-muted/50">
 <span class="px-1.5 py-0.5 rounded bg-violet-500/20 text-violet-600 font-medium">Think</span>
 <span class="icon-[lucide--arrow-right] text-muted-foreground" />
 <span class="px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-600 font-medium">Act</span>
 <span class="icon-[lucide--arrow-right] text-muted-foreground" />
 <span class="px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-600 font-medium">Observe</span>
 <span class="icon-[lucide--repeat] text-muted-foreground ml-1" />
 </div>
 <!-- Core Capabilities with descriptions -->
 <div class="space-y-1.5 text-[10px]">
 <div class="flex items-start gap-1.5">
 <span class="icon-[lucide--bot] text-violet-500 shrink-0 mt-0.5" />
 <div>
 <span class="font-medium">SubAgent 编码</span>
 <span class="text-muted-foreground"> - 分派任务给 Claude Code 执行代码修改</span>
 </div>
 </div>
 <div class="flex items-start gap-1.5">
 <span class="icon-[lucide--message-circle] text-blue-500 shrink-0 mt-0.5" />
 <div>
 <span class="font-medium">飞书交互</span>
 <span class="text-muted-foreground"> - 发送卡片消息，等待用户回复后继续</span>
 </div>
 </div>
 <div class="flex items-start gap-1.5">
 <span class="icon-[lucide--search-code] text-emerald-500 shrink-0 mt-0.5" />
 <div>
 <span class="font-medium">代码搜索</span>
 <span class="text-muted-foreground"> - 语义搜索项目代码库 (Qdrant)</span>
 </div>
 </div>
 <div class="flex items-start gap-1.5">
 <span class="icon-[lucide--pause-circle] text-amber-500 shrink-0 mt-0.5" />
 <div>
 <span class="font-medium">挂起恢复</span>
 <span class="text-muted-foreground"> - 等待用户/SubAgent 响应，自动恢复执行</span>
 </div>
 </div>
 </div>
 <!-- Feature Tags -->
 <div class="flex flex-wrap gap-1 pt-1">
 <span class="px-1.5 py-0.5 rounded bg-violet-500/10 text-violet-600 text-[9px] font-medium">ReAct Loop</span>
 <span class="px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-600 text-[9px] font-medium">多 LLM</span>
 <span class="px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-600 text-[9px] font-medium">工具调用</span>
 <span class="px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-600 text-[9px] font-medium">状态持久</span>
 </div>
 </div>
 </div>
 </div>
 <!-- Input/Output Hints -->
 <div class="grid grid-cols-2 gap-2">
 <div class="rounded-lg bg-muted/30 border border-border/50 ">
 <div class="flex items-center gap-1.5 text-[10px] font-medium text-muted-foreground mb-1">
 <span class="icon-[lucide--arrow-right-to-line] text-blue-500" />
 推荐上游节点
 </div>
 <div class="text-[10px] text-muted-foreground space-y-0.5">
 <div>• 获取工作项</div>
 <div>• 获取项目信息</div>
 <div>• 召回上下文</div>
 </div>
 </div>
 <div class="rounded-lg bg-muted/30 border border-border/50 ">
 <div class="flex items-center gap-1.5 text-[10px] font-medium text-muted-foreground mb-1">
 <span class="icon-[lucide--arrow-left-from-line] text-emerald-500" />
 输出字段
 </div>
 <div class="text-[10px] text-muted-foreground space-y-0.5">
 <div><code class="text-[9px]">final_answer</code> 最终回答</div>
 <div><code class="text-[9px]">output</code> 执行过程</div>
 <div><code class="text-[9px]">usage</code> Token 用量</div>
 </div>
 </div>
 </div>
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
 <SmartMarkdownEditor
 v-model="userPrompt":workflow-nodes="workflowNodes":workflow-edges="workflowEdges":current-node-id="currentNodeId"
 placeholder="输入 {{ 触发变量自动补全...":min-rows="4":show-toolbar="true":compact="true"
 @expand="userPromptModalOpen = true"
 />
 <p class="text-xs text-muted-foreground">
 初始任务指令，输入 <code v-pre class="bg-muted px-1 py-0.5 rounded text-primary">{{</code> 触发变量自动补全
 </p>
 </div>
 <Separator />
 <!-- Advanced Options (Collapsible) -->
 <Collapsible v-model:open="advancedOpen">
 <CollapsibleTrigger class="flex items-center justify-between w-full py-2 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors">
 <span class="flex items-center gap-2">
 <span class="icon-[lucide--settings-2] text-base" />
 高级选项
 </span>
 <span
 class="icon-[lucide--chevron-down] transition-transform duration-200":class="{ 'rotate-180': advancedOpen }"
 />
 </CollapsibleTrigger>
 <CollapsibleContent class="space-y-4 pt-2">
 <!-- Tool Selection -->
 <div class="space-y-2">
 <div v-if="toolsLoading" class="flex items-center gap-2 text-xs text-muted-foreground">
 <span class="icon-[lucide--loader-2] animate-spin" />
 加载工具列表...
 </div>
 <div v-else-if="toolsError" class="text-xs text-destructive">
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
 <div class="space-y-1.5">
 <Label class="text-xs">最大迭代次数</Label>
 <Input
 v-model="maxIterations"
 type="number":min="1":max="100"
 class="bg-background/50 text-sm"
 />
 <p class="text-[10px] text-muted-foreground">
 Agent 最多执行的思考-行动循环次数 (1-100)
 </p>
 </div>
 <!-- Timeout Hours -->
 <div class="space-y-1.5">
 <Label class="text-xs">挂起超时 (小时)</Label>
 <Input
 v-model="timeoutHours"
 type="number":min="1":max="168"
 class="bg-background/50 text-sm"
 />
 <p class="text-[10px] text-muted-foreground">
 Agent 挂起等待用户响应的最长时间
 </p>
 </div>
 </CollapsibleContent>
 </Collapsible>
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
