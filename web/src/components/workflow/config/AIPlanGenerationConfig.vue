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
const model = field('model', '') as import('vue').WritableComputedRef<string>
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
 <!-- ================================================================== -->
 <!-- Introduction Card -->
 <!-- ================================================================== -->
 <div class="rounded-xl bg-gradient-to-br from-violet-500/10 to-purple-400/5 border border-violet-500/20 ">
 <div class="flex items-start gap-2">
 <span class="icon-[lucide--sparkles] text-violet-500 text-lg shrink-0 mt-0.5" />
 <div class="space-y-1.5">
 <h4 class="text-sm font-medium">
 AI 方案生成
 </h4>
 <p class="text-xs text-muted-foreground leading-relaxed">
 基于 <span class="text-violet-500 font-medium">ReAct Agent</span> 自动分析多仓库代码，
 通过向量检索 (RAG) 理解代码上下文，生成结构化技术方案，
 支持自动验证和飞书多轮迭代。
 </p>
 <!-- Capability Tags -->
 <div class="flex flex-wrap gap-1 pt-0.5">
 <span class="px-1.5 py-0.5 rounded bg-violet-500/10 text-violet-500 text-[10px] font-medium">ReAct</span>
 <span class="px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-500 text-[10px] font-medium">RAG 向量检索</span>
 <span class="px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-500 text-[10px] font-medium">verify_plan</span>
 <span class="px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-500 text-[10px] font-medium">飞书交互</span>
 </div>
 </div>
 </div>
 </div>
 <!-- ================================================================== -->
 <!-- Phase Timeline -->
 <!-- ================================================================== -->
 <div class="relative pl-6">
 <!-- 左侧竖线 -->
 <div class="absolute left-[9px] top-2 bottom-2 w-px bg-gradient-to-b from-blue-500/40 via-violet-500/30 to-amber-500/20" />
 <!-- ============================================================== -->
 <!-- Phase: 需求输入 -->
 <!-- ============================================================== -->
 <div class="relative pb-5">
 <!-- 步骤圆点 -->
 <div class="absolute -left-6 top-0.5 flex items-center justify-center w-[19px] h-[19px] rounded-full bg-blue-500/15 border border-blue-500/30">
 <span class="text-[10px] font-bold text-blue-500">1</span>
 </div>
 <div class="space-y-2.5">
 <div>
 <h5 class="text-sm font-medium flex items-center gap-1.5">
 <span class="icon-[lucide--file-text] text-blue-500 text-sm" />
 需求输入
 </h5>
 <p class="text-[11px] text-muted-foreground mt-0.5">
 描述你的需求，AI 将以此为起点分析代码并生成方案
 </p>
 </div>
 <div class="space-y-1.5">
 <Label class="text-xs flex items-center gap-1">
 用户提示词
 <span class="text-destructive">*</span>
 </Label>
 <SmartMarkdownEditor
 v-model="userPrompt":workflow-nodes="workflowNodes":workflow-edges="workflowEdges":current-node-id="currentNodeId"
 placeholder="描述需求内容，输入 {{ 引用上游节点变量...":min-rows="5":show-toolbar="true":compact="true"
 @expand="userPromptModalOpen = true"
 />
 <p class="text-[10px] text-muted-foreground">
 支持 Markdown 和 <code class="text-[10px] px-1 py-0.5 bg-muted rounded">{'{{'}nodes.ID.field{'}}'}</code> 变量引用
 </p>
 </div>
 </div>
 </div>
 <!-- ============================================================== -->
 <!-- Phase: 代码检索 -->
 <!-- ============================================================== -->
 <div class="relative pb-5">
 <div class="absolute -left-6 top-0.5 flex items-center justify-center w-[19px] h-[19px] rounded-full bg-emerald-500/15 border border-emerald-500/30">
 <span class="text-[10px] font-bold text-emerald-500">2</span>
 </div>
 <div class="space-y-2.5">
 <div>
 <h5 class="text-sm font-medium flex items-center gap-1.5">
 <span class="icon-[lucide--search-code] text-emerald-500 text-sm" />
 代码检索
 <span class="px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-500 text-[9px] font-medium">RAG</span>
 </h5>
 <p class="text-[11px] text-muted-foreground mt-0.5">
 通过向量检索跨仓库搜索相关代码，分析依赖关系和代码结构
 </p>
 </div>
 <!-- Include Repos -->
 <div class="space-y-1.5">
 <Label class="text-xs text-muted-foreground">必须包含的仓库</Label>
 <div v-if="includeRepos.length" class="flex flex-wrap gap-1.5">
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
 </div>
 <!-- Exclude Repos -->
 <div class="space-y-1.5">
 <Label class="text-xs text-muted-foreground">必须排除的仓库</Label>
 <div v-if="excludeRepos.length" class="flex flex-wrap gap-1.5">
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
 <p class="text-[10px] text-muted-foreground">
 未指定的仓库由 AI 自动决定是否检索
 </p>
 </div>
 </div>
 </div>
 <!-- ============================================================== -->
 <!-- Phase: 方案生成 -->
 <!-- ============================================================== -->
 <div class="relative pb-5">
 <div class="absolute -left-6 top-0.5 flex items-center justify-center w-[19px] h-[19px] rounded-full bg-violet-500/15 border border-violet-500/30">
 <span class="text-[10px] font-bold text-violet-500">3</span>
 </div>
 <div class="space-y-2.5">
 <div>
 <h5 class="text-sm font-medium flex items-center gap-1.5">
 <span class="icon-[lucide--sparkles] text-violet-500 text-sm" />
 方案生成
 <span class="px-1.5 py-0.5 rounded bg-violet-500/10 text-violet-500 text-[9px] font-medium">ReAct</span>
 </h5>
 <p class="text-[11px] text-muted-foreground mt-0.5">
 ReAct Agent 循环推理，基于代码检索结果生成结构化技术方案
 </p>
 </div>
 <!-- System Prompt (collapsed) -->
 <Collapsible v-model:open="systemPromptOpen">
 <CollapsibleTrigger class="flex items-center justify-between w-full py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors">
 <span class="flex items-center gap-1.5">
 <span class="icon-[lucide--settings] text-sm" />
 自定义系统指令
 </span>
 <span
 class="icon-[lucide--chevron-down] text-xs transition-transform duration-200":class="{ 'rotate-180': systemPromptOpen }"
 />
 </CollapsibleTrigger>
 <CollapsibleContent class="space-y-1.5 pt-1.5">
 <SmartMarkdownEditor
 v-model="systemPrompt":workflow-nodes="workflowNodes":workflow-edges="workflowEdges":current-node-id="currentNodeId"
 placeholder="追加到系统默认提示词末尾的自定义指令...":min-rows="3":show-toolbar="true":compact="true"
 @expand="systemPromptModalOpen = true"
 />
 <p class="text-[10px] text-muted-foreground">
 追加到系统默认 System Prompt 末尾，留空使用默认配置
 </p>
 </CollapsibleContent>
 </Collapsible>
 <!-- Model & Iterations -->
 <Collapsible v-model:open="advancedOpen">
 <CollapsibleTrigger class="flex items-center justify-between w-full py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors">
 <span class="flex items-center gap-1.5">
 <span class="icon-[lucide--cpu] text-sm" />
 模型 & 参数
 </span>
 <span
 class="icon-[lucide--chevron-down] text-xs transition-transform duration-200":class="{ 'rotate-180': advancedOpen }"
 />
 </CollapsibleTrigger>
 <CollapsibleContent class="space-y-3 pt-1.5">
 <AIModelConfig
 v-model:use-custom-api="useCustomApi"
 v-model:api-base-url="apiBaseUrl"
 v-model:api-key="apiKey"
 v-model:model="model"
 model-description="方案生成使用的 LLM 模型"
 />
 <div class="space-y-1.5">
 <Label class="text-xs">最大迭代轮次</Label>
 <Input
 v-model="maxIterations"
 type="number":min="10":max="200"
 class="bg-background/50 text-sm"
 />
 <p class="text-[10px] text-muted-foreground">
 Agent 最多执行的 ReAct 循环次数 (10-200)
 </p>
 </div>
 </CollapsibleContent>
 </Collapsible>
 </div>
 </div>
 <!-- ============================================================== -->
 <!-- Phase: 自动验证 -->
 <!-- ============================================================== -->
 <div class="relative pb-5">
 <div class="absolute -left-6 top-0.5 flex items-center justify-center w-[19px] h-[19px] rounded-full bg-amber-500/15 border border-amber-500/30">
 <span class="text-[10px] font-bold text-amber-500">4</span>
 </div>
 <div>
 <h5 class="text-sm font-medium flex items-center gap-1.5">
 <span class="icon-[lucide--shield-check] text-amber-500 text-sm" />
 自动验证
 <span class="px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-500 text-[9px] font-medium">自动</span>
 </h5>
 <p class="text-[11px] text-muted-foreground mt-0.5">
 调用 <code class="text-[10px] px-1 py-0.5 bg-muted rounded">verify_plan</code> 验证方案格式和完整性，失败自动重试（最多 3 轮）
 </p>
 </div>
 </div>
 <!-- ============================================================== -->
 <!-- Phase: 飞书推送 -->
 <!-- ============================================================== -->
 <div class="relative">
 <div class="absolute -left-6 top-0.5 flex items-center justify-center w-[19px] h-[19px] rounded-full bg-cyan-500/15 border border-cyan-500/30">
 <span class="text-[10px] font-bold text-cyan-500">5</span>
 </div>
 <div class="space-y-2.5">
 <div>
 <h5 class="text-sm font-medium flex items-center gap-1.5">
 <span class="icon-[lucide--send] text-cyan-500 text-sm" />
 飞书推送
 </h5>
 <p class="text-[11px] text-muted-foreground mt-0.5">
 生成飞书文档并发送方案卡片，用户可在线审阅、反馈或确认
 </p>
 </div>
 <div class="space-y-1.5">
 <Label class="text-xs flex items-center gap-1.5">
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
 </div>
 </div>
 </div>
 <!-- ================================================================== -->
 <!-- Modals -->
 <!-- ================================================================== -->
 <MarkdownEditorModal
 v-model:open="systemPromptModalOpen"
 v-model="systemPrompt"
 title="编辑系统提示词"
 description="追加到系统默认提示词末尾的自定义指令":workflow-nodes="workflowNodes":workflow-edges="workflowEdges":current-node-id="currentNodeId"
 placeholder="追加到系统默认提示词末尾的自定义指令..."
 />
 <MarkdownEditorModal
 v-model:open="userPromptModalOpen"
 v-model="userPrompt"
 title="编辑用户提示词"
 description="描述需求内容，输入 {{ 引用上游节点变量":workflow-nodes="workflowNodes":workflow-edges="workflowEdges":current-node-id="currentNodeId"
 placeholder="描述需求内容，输入 {{ 引用上游节点变量..."
 />
 </div>
</template>
