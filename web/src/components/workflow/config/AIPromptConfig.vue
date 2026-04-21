<script setup lang="ts">
import type { AIPromptConfig } from '~/types/workflow'
import type { WorkflowEdge, WorkflowNode } from '~/types/workflow/store'
import { computed, ref } from 'vue'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '~/components/ui/collapsible'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from '~/components/ui/select'
import { Separator } from '~/components/ui/separator'
import { Slider } from '~/components/ui/slider'
import {
 Tooltip,
 TooltipContent,
 TooltipProvider,
 TooltipTrigger,
} from '~/components/ui/tooltip'
import ModelSelect from '~/components/providers/ModelSelect.vue'
import ProviderCredentialDropdown from '~/components/providers/ProviderCredentialDropdown.vue'
import AIModelConfig from '~/components/workflow/config/AIModelConfig.vue'
import { MarkdownEditorModal, SmartMarkdownEditor } from '~/components/workflow/smart-input'
import { useConfigModel } from '~/composables/useConfigModel'
import { useProviderCredentialStore } from '~/stores/providerCredential'
import {
 aiPromptConfigSchema,
 OUTPUT_FORMATS,
} from '~/types/workflow'
// ============================================================================
// Props & Emits
// ============================================================================
interface Props {
 config: AIPromptConfig
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
 (e: 'update:config', value: AIPromptConfig): void
}>
// ============================================================================
// Config Model
// ============================================================================
const { field } = useConfigModel({
 config: => props.config,
 emit: v => emit('update:config', v),
 schema: aiPromptConfigSchema,
})
// API 配置
const useCustomApi = computed({
 get: => props.config.use_custom_api ?? false,
 set: v => emit('update:config', { ...props.config, use_custom_api: v }),
})
const apiBaseUrl = field('api_base_url', '')
const apiKey = field('api_key', '')
const model = field('model', '')
// Provider 凭证(Phase) + capability 推导
// field 在 schema 用 `.optional` 时推断为 `string | null | undefined`,
// 此处用 computed 归一为 `string | null`,契合 Dropdown / ModelSelect props。
const providerStore = useProviderCredentialStore
const providerCredentialIdField = field('provider_credential_id', null as string | null)
const providerCredentialId = computed<string | null>({
 get: => providerCredentialIdField.value ?? null,
 set: (v: string | null) => { providerCredentialIdField.value = v },
})
const currentCredential = computed( => {
 const id = providerCredentialId.value
 return id ? providerStore.getCredentialById(id): null
})
const currentProviderType = computed( => currentCredential.value?.provider_type ?? null)
const currentProviderMeta = computed( => {
 const type = currentProviderType.value
 return type ? (providerStore.providerTypes.find(p => p.provider_type === type) ?? null): null
})
const thinkingSupported = computed( => currentProviderMeta.value?.supports_thinking ?? false)
// AIPromptConfig 本身不渲染 reasoning_effort 字段,故不声明 reasoningSupported。
// 若未来需要,可参考 Plan action 步骤 2(5) 扩展,读 currentModelMeta.supports_reasoning
// 字段权威值,字段缺失则 fallback 到 /^(o[134]|gpt-5|o4)/i.test(model.value)。
// 提示词配置
const systemPrompt = field('system_prompt', '')
const userPrompt = field('user_prompt', '')
const maxTokens = field('max_tokens', 4096)
const outputFormat = field('output_format', 'text')
// Slider 需要数组格式的特殊处理
const temperature = computed({
 get: => [props.config.temperature ?? 0.7],
 set: v => emit('update:config', { ...props.config, temperature: v[0] }),
})
// 高级设置
const maxThinkingTokens = field('max_thinking_tokens', null)
const maxBudgetUsd = field('max_budget_usd', null)
// Input 组件不接受 null，转换为 undefined
const maxThinkingTokensInput = computed({
 get: => maxThinkingTokens.value ?? undefined,
 set: (v: string | number | undefined) => { maxThinkingTokens.value = (v != null ? Number(v): null) as number | null },
})
const maxBudgetUsdInput = computed({
 get: => maxBudgetUsd.value ?? undefined,
 set: (v: string | number | undefined) => { maxBudgetUsd.value = (v != null ? Number(v): null) as number | null },
})
const advancedOpen = ref(false)
// ============================================================================
// Modal State
// ============================================================================
const systemPromptModalOpen = ref(false)
const userPromptModalOpen = ref(false)
</script>
<template>
 <div class="space-y-4">
 <!-- Provider 凭证(Phase/05/06) -->
 <div class="space-y-2">
 <Label class="font-normal">
 Provider 凭证
 </Label>
 <ProviderCredentialDropdown:model-value="providerCredentialId"
 scope="system"
 @update:model-value="v => providerCredentialId = v"
 />
 <p class="text-xs text-muted-foreground">
 选择一条启用中的 Provider 凭证,未选择则走系统默认
 </p>
 </div>
 <!-- 模型(按 credential 维度 + capability 过滤;) -->
 <div class="space-y-2">
 <Label class="font-normal">
 模型
 </Label>
 <ModelSelect:credential-id="providerCredentialId":requires-tools="true":model-value="model"
 @update:model-value="v => model = v ?? ''"
 />
 <p class="text-xs text-muted-foreground">
 仅列出当前 Provider 支持 tool use 的模型
 </p>
 </div>
 <!-- AI 模型配置(通用组件,保留以兼容自定义 API 场景) -->
 <AIModelConfig
 v-model:use-custom-api="useCustomApi"
 v-model:api-base-url="apiBaseUrl"
 v-model:api-key="apiKey"
 v-model:model="model"
 />
 <Separator />
 <!-- System Prompt -->
 <div class="space-y-2">
 <Label>系统提示词</Label>
 <SmartMarkdownEditor
 v-model="systemPrompt":workflow-nodes="workflowNodes":workflow-edges="workflowEdges":current-node-id="currentNodeId"
 placeholder="设定 AI 的角色和行为规范...":min-rows="3":show-toolbar="true":compact="true"
 @expand="systemPromptModalOpen = true"
 />
 <p class="text-xs text-muted-foreground">
 定义 AI 的角色、能力范围和输出要求
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
 输入 <code v-pre class="bg-muted px-1 py-0.5 rounded text-primary">{{</code> 触发变量自动补全
 </p>
 </div>
 <!-- 温度 -->
 <div class="space-y-2">
 <div class="flex items-center justify-between">
 <Label>温度 (Temperature)</Label>
 <span class="text-sm text-muted-foreground font-mono">
 {{ temperature[0].toFixed(1) }}
 </span>
 </div>
 <Slider
 v-model="temperature":min="0":max="2":step="0.1"
 class="w-full"
 />
 <p class="text-xs text-muted-foreground">
 较低值输出更确定，较高值更有创造性
 </p>
 </div>
 <!-- 最大 Token -->
 <div class="space-y-2">
 <Label>最大 Token 数</Label>
 <Input
 v-model="maxTokens"
 type="number":min="100":max="100000"
 />
 </div>
 <!-- 输出格式 -->
 <div class="space-y-2">
 <Label>输出格式</Label>
 <Select v-model="outputFormat">
 <SelectTrigger>
 <SelectValue placeholder="选择输出格式" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem
 v-for="option in OUTPUT_FORMATS":key="option.value":value="option.value"
 >
 {{ option.label }}
 </SelectItem>
 </SelectContent>
 </Select>
 <p class="text-xs text-muted-foreground">
 JSON 格式会自动解析为对象，便于后续节点使用
 </p>
 </div>
 <Separator />
 <!-- 高级设置 -->
 <Collapsible v-model:open="advancedOpen">
 <CollapsibleTrigger class="flex items-center gap-2 w-full py-2 text-sm text-muted-foreground hover:text-foreground transition-colors">
 <span
 class="icon-[lucide--chevron-right] w-4 transition-transform duration-200":class="{ 'rotate-90': advancedOpen }"
 />
 高级设置
 </CollapsibleTrigger>
 <CollapsibleContent class="space-y-4 pt-2">
 <!-- 最大思考 Token 数(:非 Anthropic 禁用 + tooltip) -->
 <TooltipProvider:delay-duration="100">
 <Tooltip>
 <TooltipTrigger as-child>
 <div
 class="space-y-2":class="{ 'opacity-60': !thinkingSupported }"
 >
 <Label>最大思考 Token 数</Label>
 <Input
 v-model="maxThinkingTokensInput"
 type="number":min="1024":max="128000"
 placeholder="留空使用默认值":disabled="!thinkingSupported"
 />
 <p class="text-xs text-muted-foreground">
 Claude 扩展思考的 token 上限。仅 Claude 模型支持，其他模型将忽略此参数
 </p>
 </div>
 </TooltipTrigger>
 <TooltipContent v-if="!thinkingSupported">
 仅 Anthropic Provider 支持 extended thinking
 </TooltipContent>
 </Tooltip>
 </TooltipProvider>
 <!-- 预算上限 -->
 <div class="space-y-2">
 <Label>预算上限 (USD)</Label>
 <Input
 v-model="maxBudgetUsdInput"
 type="number":min="0.01":max="100":step="0.01"
 placeholder="留空不限制"
 />
 <p class="text-xs text-muted-foreground">
 单次调用的美元成本上限，超出后终止执行
 </p>
 </div>
 </CollapsibleContent>
 </Collapsible>
 <!-- System Prompt Modal -->
 <MarkdownEditorModal
 v-model:open="systemPromptModalOpen"
 v-model="systemPrompt"
 title="编辑系统提示词"
 description="定义 AI 的角色、能力范围和输出要求":workflow-nodes="workflowNodes":workflow-edges="workflowEdges":current-node-id="currentNodeId"
 placeholder="设定 AI 的角色和行为规范..."
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
