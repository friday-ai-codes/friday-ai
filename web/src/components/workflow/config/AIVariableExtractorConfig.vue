<script setup lang="ts">
import type { AIVariableDefinition, AIVariableExtractorConfig } from '~/types/workflow'
import { computed, ref } from 'vue'
import { Button } from '~/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '~/components/ui/collapsible'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { Separator } from '~/components/ui/separator'
import { Switch } from '~/components/ui/switch'
import { Textarea } from '~/components/ui/textarea'
import {
 Tooltip,
 TooltipContent,
 TooltipProvider,
 TooltipTrigger,
} from '~/components/ui/tooltip'
import ModelSelect from '~/components/providers/ModelSelect.vue'
import ProviderCredentialDropdown from '~/components/providers/ProviderCredentialDropdown.vue'
import AIModelConfig from '~/components/workflow/config/AIModelConfig.vue'
import { useConfigModel } from '~/composables/useConfigModel'
import { useProviderCredentialStore } from '~/stores/providerCredential'
import {
 aiVariableExtractorConfigSchema,
} from '~/types/workflow'
// ============================================================================
// Props & Emits
// ============================================================================
interface Props {
 config: AIVariableExtractorConfig
}
const props = defineProps<Props>
const emit = defineEmits<{
 (e: 'update:config', value: AIVariableExtractorConfig): void
}>
// ============================================================================
// Config Model
// ============================================================================
const { field } = useConfigModel({
 config: => props.config,
 emit: v => emit('update:config', v),
 schema: aiVariableExtractorConfigSchema,
})
const inputSource = field('input_source', '')
const additionalPrompt = field('additional_prompt', '')
const model = field('model', '')
const useCustomApi = field('use_custom_api', false)
const apiBaseUrl = field('api_base_url', '')
const apiKey = field('api_key', '')
// Provider 凭证(Phase) + capability 推导
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
const variables = computed({
 get: => props.config.variables ??,
 set: v => emit('update:config', { ...props.config, variables: v }),
})
// ============================================================================
// 变量定义管理
// ============================================================================
function addVariable {
 const newVar: AIVariableDefinition = {
 key: '',
 name: '',
 desc: '',
 required: false,
 }
 variables.value = [...variables.value, newVar]
}
function removeVariable(index: number) {
 variables.value = variables.value.filter((_, i) => i !== index)
}
function updateVariable(index: number, field: keyof AIVariableDefinition, value: any) {
 const updated = [...variables.value]
 updated[index] = { ...updated[index], [field]: value }
 variables.value = updated
}
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
 <!-- 模型(变量提取不需要 tool use, requires-tools=false) -->
 <div class="space-y-2">
 <Label class="font-normal">
 模型
 </Label>
 <ModelSelect:credential-id="providerCredentialId":requires-tools="false":model-value="model"
 @update:model-value="v => model = v ?? ''"
 />
 <p class="text-xs text-muted-foreground">
 按当前 Provider 凭证过滤可用模型
 </p>
 </div>
 <!-- AI 模型配置(保留以兼容自定义 API 场景) -->
 <AIModelConfig
 v-model:model="model"
 v-model:use-custom-api="useCustomApi"
 v-model:api-base-url="apiBaseUrl"
 v-model:api-key="apiKey"
 />
 <Separator />
 <!-- 输入来源 -->
 <div class="space-y-2">
 <Label>输入来源</Label>
 <Input
 v-model="inputSource"
 placeholder="$.data.content 或 {{ trigger.payload.description }}"
 class="font-mono text-sm"
 />
 <p class="text-xs text-muted-foreground">
 支持 JSONPath 或模板语法，留空则自动从上游节点获取
 </p>
 </div>
 <Separator />
 <!-- 目标变量定义 -->
 <div class="space-y-3">
 <div class="flex items-center justify-between">
 <Label>目标变量</Label>
 <Button size="sm" variant="outline" @click="addVariable">
 <span class="icon-[lucide--plus] mr-1" />
 添加变量
 </Button>
 </div>
 <div v-if="variables.length === 0" class="text-center py-8 text-muted-foreground">
 <span class="icon-[lucide--sparkles] text-4xl mb-2 block opacity-50" />
 <p>暂无目标变量</p>
 <p class="text-xs">
 定义需要 AI 从文本中提取的变量
 </p>
 </div>
 <div
 v-for="(variable, index) in variables":key="index"
 class="rounded-lg border border-border/50 bg-card/50 space-y-3"
 >
 <div class="flex items-start justify-between">
 <div class="flex items-center gap-2">
 <div class=".5 rounded-md bg-primary/10">
 <span class="icon-[lucide--sparkles] text-primary" />
 </div>
 <span class="font-medium text-sm">{{ variable.name || '未命名变量' }}</span>
 <span v-if="variable.required" class="text-xs text-destructive">必填</span>
 </div>
 <Button
 variant="ghost"
 size="sm"
 class="text-muted-foreground hover:text-destructive"
 @click="removeVariable(index)"
 >
 <span class="icon-[lucide--trash-2]" />
 </Button>
 </div>
 <div class="grid grid-cols-2 gap-3">
 <!-- 显示名称 -->
 <div class="space-y-1">
 <Label class="text-xs">显示名称</Label>
 <Input:model-value="variable.name"
 placeholder="如：技术栈"
 @update:model-value="v => updateVariable(index, 'name', v)"
 />
 </div>
 <!-- 变量标识符 -->
 <div class="space-y-1">
 <Label class="text-xs">变量 Key</Label>
 <Input:model-value="variable.key"
 placeholder="如：techStack"
 class="font-mono text-sm"
 @update:model-value="v => updateVariable(index, 'key', v)"
 />
 </div>
 </div>
 <!-- 提取描述 -->
 <div class="space-y-1">
 <Label class="text-xs flex items-center gap-1">
 提取描述
 <span class="text-destructive">*</span>
 </Label>
 <Textarea:model-value="variable.desc"
 placeholder="描述如何从文本中提取该变量，例如：文本中提到的技术栈列表，包括编程语言、框架等"
 rows="2"
 @update:model-value="v => updateVariable(index, 'desc', v)"
 />
 <p class="text-xs text-muted-foreground">
 详细描述帮助 AI 更准确地提取
 </p>
 </div>
 <!-- 必填开关 -->
 <div class="flex items-center justify-between pt-1">
 <div>
 <Label class="text-xs">必填变量</Label>
 <p class="text-xs text-muted-foreground">
 提取失败时节点将报错
 </p>
 </div>
 <Switch:checked="variable.required"
 @update:checked="(v: boolean) => updateVariable(index, 'required', v)"
 />
 </div>
 </div>
 </div>
 <Separator />
 <!-- 额外提取指导 -->
 <div class="space-y-2">
 <Label>额外提取指导（选填）</Label>
 <Textarea
 v-model="additionalPrompt"
 placeholder="给 AI 的额外指导，如：优先提取明确提到的内容，不要推测..."
 rows="2"
 />
 </div>
 <!-- 高级设置 -->
 <Separator />
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
 <!-- 使用提示 -->
 <div class="rounded-lg bg-muted/50 ">
 <p class="text-xs text-muted-foreground">
 <span class="icon-[lucide--info] mr-1" />
 AI 将根据变量描述智能提取信息，提取结果可通过
 <code v-pre class="bg-muted px-1 py-0.5 rounded text-primary">{{ global.variableKey }}</code>
 引用
 </p>
 </div>
 </div>
</template>
