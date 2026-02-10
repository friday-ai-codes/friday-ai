<script setup lang="ts">
import type { WorkflowEdge, WorkflowNode } from '~/types/workflow/store'
import { ref } from 'vue'
import {
 Collapsible,
 CollapsibleContent,
 CollapsibleTrigger,
} from '~/components/ui/collapsible'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { Separator } from '~/components/ui/separator'
import AIModelConfig from '~/components/workflow/config/AIModelConfig.vue'
import { MarkdownEditorModal, SmartMarkdownEditor, SmartTextarea } from '~/components/workflow/smart-input'
import { useConfigModel } from '~/composables/useConfigModel'
/**
 * AIPlanGenerationConfig - Configuration panel for AI Plan Generation node.
 *
 * Features:
 * - Repository selection: include/exclude dual tag lists
 * - User Prompt: Markdown editor with variable support (expanded by default)
 * - System Prompt: Markdown editor (collapsed by default)
 * - Advanced options: model, max iterations, chat ID, custom API
 */
// ============================================================================
// Types
// ============================================================================
interface AIPlanGenerationConfig {
 system_prompt: string
 user_prompt: string
 include_repos: string
 exclude_repos: string
 max_iterations: number
 enabled_tools: string
 chat_id: string
 use_custom_api: boolean
 api_base_url: string
 api_key: string
 model: string
}
// ============================================================================
// Props & Emits
// ============================================================================
interface Props {
 config: AIPlanGenerationConfig
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
 (e: 'update:config', value: AIPlanGenerationConfig): void
}>
// ============================================================================
// Config Model
// ============================================================================
const { field } = useConfigModel({
 config: => props.config as unknown as Record<string, unknown>,
 emit: v => emit('update:config', v as unknown as AIPlanGenerationConfig),
})
const systemPrompt = field('system_prompt', '') as import('vue').WritableComputedRef<string>
const userPrompt = field('user_prompt', '') as import('vue').WritableComputedRef<string>
const includeRepos = field('include_repos', ) as import('vue').WritableComputedRef<string>
const excludeRepos = field('exclude_repos', ) as import('vue').WritableComputedRef<string>
const maxIterations = field('max_iterations', 50) as import('vue').WritableComputedRef<number>
const chatId = field('chat_id', '') as import('vue').WritableComputedRef<string>
// API 配置
const useCustomApi = computed({
 get: => props.config.use_custom_api ?? false,
 set: v => emit('update:config', { ...props.config, use_custom_api: v }),
})
const apiBaseUrl = field('api_base_url', '') as import('vue').WritableComputedRef<string>
const apiKey = field('api_key', '') as import('vue').WritableComputedRef<string>
const model = field('model', 'claude-sonnet-4-20250514') as import('vue').WritableComputedRef<string>
// ============================================================================
// Tag Input State
// ============================================================================
const includeInput = ref('')
const excludeInput = ref('')
function addIncludeRepo {
 const value = includeInput.value.trim
 if (value && !includeRepos.value.includes(value)) {
 includeRepos.value = [...includeRepos.value, value]
 }
 includeInput.value = ''
}
function removeIncludeRepo(repo: string) {
 includeRepos.value = includeRepos.value.filter(r => r !== repo)
}
function addExcludeRepo {
 const value = excludeInput.value.trim
 if (value && !excludeRepos.value.includes(value)) {
 excludeRepos.value = [...excludeRepos.value, value]
 }
 excludeInput.value = ''
}
function removeExcludeRepo(repo: string) {
 excludeRepos.value = excludeRepos.value.filter(r => r !== repo)
}
// ============================================================================
// Modal & Collapsible State
// ============================================================================
const systemPromptOpen = ref(false)
const systemPromptModalOpen = ref(false)
const userPromptModalOpen = ref(false)
const advancedOpen = ref(false)
</script>
<template>
 <div class="space-y-4">
 <!-- Introduction -->
 <div class="rounded-xl bg-gradient-to-br from-emerald-500/10 to-teal-400/5 border border-emerald-500/20 ">
 <div class="flex items-start gap-2">
 <span class="icon-[lucide--file-text] text-emerald-500 text-lg shrink-0 mt-0.5" />
 <div class="space-y-1.5">
 <h4 class="text-sm font-medium">
 AI 方案生成
 </h4>
 <p class="text-xs text-muted-foreground leading-relaxed">
 自动分析多仓库代码结构，生成结构化技术方案。支持
 <span class="text-emerald-600 font-medium">verify_plan 验证</span>
 和飞书卡片多轮迭代。
 </p>
 <!-- Workflow Visual -->
 <div class="flex items-center gap-1 text-[10px] py-1.5 px-2 rounded-lg bg-muted/50">
 <span class="px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-600 font-medium">分析仓库</span>
 <span class="icon-[lucide--arrow-right] text-muted-foreground" />
 <span class="px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-600 font-medium">生成方案</span>
 <span class="icon-[lucide--arrow-right] text-muted-foreground" />
 <span class="px-1.5 py-0.5 rounded bg-violet-500/20 text-violet-600 font-medium">验证</span>
 <span class="icon-[lucide--arrow-right] text-muted-foreground" />
 <span class="px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-600 font-medium">用户审阅</span>
 </div>
 <!-- Feature Tags -->
 <div class="flex flex-wrap gap-1 pt-0.5">
 <span class="px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-600 text-[9px] font-medium">多仓库分析</span>
 <span class="px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-600 text-[9px] font-medium">自动验证</span>
 <span class="px-1.5 py-0.5 rounded bg-violet-500/10 text-violet-600 text-[9px] font-medium">飞书审阅</span>
 <span class="px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-600 text-[9px] font-medium">多轮迭代</span>
 </div>
 </div>
 </div>
 </div>
 <!-- Repository Configuration -->
 <div class="space-y-3">
 <div class="flex items-center gap-2">
 <span class="icon-[lucide--folder-git-2] text-emerald-500" />
 <Label class="text-sm font-medium">仓库配置</Label>
 </div>
 <!-- Include Repos -->
 <div class="space-y-1.5">
 <Label class="text-xs text-muted-foreground">必须包含</Label>
 <div class="flex flex-wrap gap-1.5 min-h-[28px]">
 <span
 v-for="repo in includeRepos":key="repo"
 class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-600 border border-emerald-500/20"
 >
 {{ repo }}
 <button
 type="button"
 class="icon-[lucide--x] text-[10px] hover:text-destructive transition-colors"
 @click="removeIncludeRepo(repo)"
 />
 </span>
 </div>
 <Input
 v-model="includeInput"
 placeholder="输入仓库名，回车添加"
 class="bg-background/50 text-sm"
 @keydown.enter.prevent="addIncludeRepo"
 />
 <p class="text-[10px] text-muted-foreground">
 未指定的仓库由 AI 自动决定是否分析
 </p>
 </div>
 <!-- Exclude Repos -->
 <div class="space-y-1.5">
 <Label class="text-xs text-muted-foreground">必须排除</Label>
 <div class="flex flex-wrap gap-1.5 min-h-[28px]">
 <span
 v-for="repo in excludeRepos":key="repo"
 class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-red-500/10 text-red-600 border border-red-500/20"
 >
 {{ repo }}
 <button
 type="button"
 class="icon-[lucide--x] text-[10px] hover:text-destructive transition-colors"
 @click="removeExcludeRepo(repo)"
 />
 </span>
 </div>
 <Input
 v-model="excludeInput"
 placeholder="输入要排除的仓库名"
 class="bg-background/50 text-sm"
 @keydown.enter.prevent="addExcludeRepo"
 />
 </div>
 </div>
 <Separator />
 <!-- User Prompt (expanded by default) -->
 <div class="space-y-2">
 <Label class="flex items-center gap-2">
 用户提示词
 <span class="text-destructive">*</span>
 </Label>
 <SmartMarkdownEditor
 v-model="userPrompt":workflow-nodes="workflowNodes":workflow-edges="workflowEdges":current-node-id="currentNodeId"
 placeholder="描述需求内容，输入 {{ 引用上游节点变量...":min-rows="5":show-toolbar="true":compact="true"
 @expand="userPromptModalOpen = true"
 />
 <p class="text-xs text-muted-foreground">
 描述需求内容，支持引用上游节点变量
 </p>
 </div>
 <Separator />
 <!-- System Prompt (collapsed by default) -->
 <Collapsible v-model:open="systemPromptOpen">
 <CollapsibleTrigger class="flex items-center justify-between w-full py-2 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors">
 <span class="flex items-center gap-2">
 <span class="icon-[lucide--settings] text-base" />
 系统提示词（高级）
 </span>
 <span
 class="icon-[lucide--chevron-down] transition-transform duration-200":class="{ 'rotate-180': systemPromptOpen }"
 />
 </CollapsibleTrigger>
 <CollapsibleContent class="space-y-2 pt-2">
 <SmartMarkdownEditor
 v-model="systemPrompt":workflow-nodes="workflowNodes":workflow-edges="workflowEdges":current-node-id="currentNodeId"
 placeholder="追加到系统默认提示词末尾的自定义指令...":min-rows="3":show-toolbar="true":compact="true"
 @expand="systemPromptModalOpen = true"
 />
 <p class="text-[10px] text-muted-foreground">
 追加到系统默认提示词末尾。留空使用默认配置。
 </p>
 </CollapsibleContent>
 </Collapsible>
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
 <!-- AI 模型配置 -->
 <AIModelConfig
 v-model:use-custom-api="useCustomApi"
 v-model:api-base-url="apiBaseUrl"
 v-model:api-key="apiKey"
 v-model:model="model"
 model-description="方案生成使用的 LLM 模型"
 />
 <Separator />
 <!-- Max Iterations -->
 <div class="space-y-1.5">
 <Label class="text-xs">最大迭代轮次</Label>
 <Input
 v-model="maxIterations"
 type="number":min="10":max="200"
 class="bg-background/50 text-sm"
 />
 <p class="text-[10px] text-muted-foreground">
 Agent 最多执行的思考-行动循环次数 (10-200)
 </p>
 </div>
 <Separator />
 <!-- Chat ID -->
 <div class="space-y-1.5">
 <Label class="text-xs flex items-center gap-1.5">
 <span class="icon-[lucide--message-circle] text-blue-500" />
 飞书群聊 ID
 </Label>
 <SmartTextarea
 v-model="chatId":workflow-nodes="workflowNodes":workflow-edges="workflowEdges":current-node-id="currentNodeId"
 placeholder="输入 {{ 选择变量，如 fetch_project.fields...":min-rows="1"
 class="bg-background/50"
 />
 <p class="text-[10px] text-muted-foreground">
 方案卡片发送的目标群聊，支持变量引用
 </p>
 </div>
 </CollapsibleContent>
 </Collapsible>
 <!-- System Prompt Modal -->
 <MarkdownEditorModal
 v-model:open="systemPromptModalOpen"
 v-model="systemPrompt"
 title="编辑系统提示词"
 description="追加到系统默认提示词末尾的自定义指令":workflow-nodes="workflowNodes":workflow-edges="workflowEdges":current-node-id="currentNodeId"
 placeholder="追加到系统默认提示词末尾的自定义指令..."
 />
 <!-- User Prompt Modal -->
 <MarkdownEditorModal
 v-model:open="userPromptModalOpen"
 v-model="userPrompt"
 title="编辑用户提示词"
 description="描述需求内容，输入 {{ 引用上游节点变量":workflow-nodes="workflowNodes":workflow-edges="workflowEdges":current-node-id="currentNodeId"
 placeholder="描述需求内容，输入 {{ 引用上游节点变量..."
 />
 </div>
</template>
