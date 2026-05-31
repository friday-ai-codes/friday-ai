<script setup lang="ts">
/**
 * Claude Code 编码配置面板（Quick 问题②⑥）
 *
 * 多 Provider 场景下选定一个凭证供 Claude Code 编码容器使用，并把
 * opus/sonnet/haiku 三档模型别名映射到该凭证的具体模型（cc-switch 风格）。
 *
 * - 凭证下拉：active 凭证全集（优先 anthropic，但允许任意 Anthropic 兼容网关凭证）。
 * - 三档模型：数据源为所选凭证的 available_models；为空时降级为手动输入。
 * - 读 GET /api/providers/claude-code-config/，存 PUT 同路径。
 */
import type { AvailableModel, ProviderCredentialDto } from '~/types/providerCredential'
import { computed, onMounted, ref, watch } from 'vue'
import { providerCredentialsApi } from '~/api/providerCredentials'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from '~/components/ui/select'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'
import { useProviderCredentialStore } from '~/stores/providerCredential'
type ModelTier = 'opus' | 'sonnet' | 'haiku'
const store = useProviderCredentialStore
const toast = useToast
const { handleError } = useErrorHandler
const loading = ref(true)
const saving = ref(false)
const selectedCredentialId = ref<string>('')
const mapping = ref<Record<ModelTier, string>>({ opus: '', sonnet: '', haiku: '' })
const TIERS: { key: ModelTier, label: string, hint: string } = [
 { key: 'opus', label: 'Opus（最强）', hint: '复杂规划 / 高难度任务' },
 { key: 'sonnet', label: 'Sonnet（主力）', hint: '默认主模型，日常编码' },
 { key: 'haiku', label: 'Haiku（轻量）', hint: '子代理 / 后台快速任务' },
]
/** 候选凭证：active 全集，anthropic 排前。 */
const candidateCredentials = computed<ProviderCredentialDto>( => {
 return [...store.activeCredentials].sort((a, b) => {
 if (a.provider_type === b.provider_type)
 return a.name.localeCompare(b.name)
 if (a.provider_type === 'anthropic')
 return -1
 if (b.provider_type === 'anthropic')
 return 1
 return a.provider_type.localeCompare(b.provider_type)
 })
})
const selectedCredential = computed<ProviderCredentialDto | null>( =>
 candidateCredentials.value.find(c => c.id === selectedCredentialId.value) ?? null,
)
/** 所选凭证的可用模型；为空时三档降级为手动输入。 */
const availableModels = computed<AvailableModel>(
 => selectedCredential.value?.available_models ??,
)
const hasModelOptions = computed( => availableModels.value.length > 0)
async function load {
 loading.value = true
 try {
 await Promise.all([
 store.fetchCredentials({ scope: 'system', force: true }),
 store.fetchProviderTypes,
 ])
 const cfg = await providerCredentialsApi.getClaudeCodeConfig
 selectedCredentialId.value = cfg.credential_id ?? ''
 mapping.value = {
 opus: cfg.model_mapping?.opus ?? '',
 sonnet: cfg.model_mapping?.sonnet ?? '',
 haiku: cfg.model_mapping?.haiku ?? '',
 }
 }
 catch (e) {
 handleError(e, '加载 Claude Code 配置')
 }
 finally {
 loading.value = false
 }
}
// 切换凭证时，若已选模型不在新凭证 available_models 中则清空（仅当有候选清单）
watch(selectedCredentialId, => {
 if (!hasModelOptions.value)
 return
 const ids = new Set(availableModels.value.map(m => m.id))
 for (const tier of ['opus', 'sonnet', 'haiku'] as ModelTier) {
 if (mapping.value[tier] && !ids.has(mapping.value[tier]))
 mapping.value[tier] = ''
 }
})
async function save {
 saving.value = true
 try {
 await providerCredentialsApi.updateClaudeCodeConfig({
 credential_id: selectedCredentialId.value,
 model_mapping: { ...mapping.value },
 })
 toast.success('Claude Code 配置已保存')
 }
 catch (e) {
 handleError(e, '保存 Claude Code 配置')
 }
 finally {
 saving.value = false
 }
}
onMounted(load)
</script>
<template>
 <div class="space-y-5">
 <div v-if="loading" class="flex items-center gap-2 py-6 text-sm text-muted-foreground">
 <span class="icon-[lucide--loader-2] w-4 animate-spin" />
 加载中…
 </div>
 <template v-else>
 <!-- 凭证选择 -->
 <div class="space-y-1.5">
 <label class="text-sm font-normal">编码 Provider 凭证</label>
 <Select v-model="selectedCredentialId">
 <SelectTrigger>
 <SelectValue placeholder="选择 Claude Code 使用的凭证" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem
 v-for="c in candidateCredentials":key="c.id":value="c.id"
 >
 {{ c.name }}（{{ c.provider_type }}）
 </SelectItem>
 </SelectContent>
 </Select>
 <p class="text-xs text-muted-foreground">
 Claude Code 编码容器走 Anthropic 协议，优先选 anthropic 凭证；也支持任意 Anthropic
 兼容网关（自定义 Base URL）。未选则回退系统默认 anthropic 凭证。
 </p>
 </div>
 <!-- 三档模型映射 -->
 <div class="space-y-3">
 <p class="text-sm font-normal">
 模型映射（opus / sonnet / haiku）
 </p>
 <div
 v-for="tier in TIERS":key="tier.key"
 class="grid grid-cols-[7rem_1fr] items-center gap-3"
 >
 <div>
 <p class="text-sm">
 {{ tier.label }}
 </p>
 <p class="text-xs text-muted-foreground">
 {{ tier.hint }}
 </p>
 </div>
 <Select
 v-if="hasModelOptions"
 v-model="mapping[tier.key]"
 >
 <SelectTrigger>
 <SelectValue placeholder="选择模型（留空回退主模型）" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem
 v-for="m in availableModels":key="m.id":value="m.id"
 >
 {{ m.display_name || m.id }}
 </SelectItem>
 </SelectContent>
 </Select>
 <Input
 v-else
 v-model="mapping[tier.key]"
 placeholder="手动输入模型名，例如 claude-sonnet-4-20250514"
 class="text-sm"
 />
 </div>
 <p v-if="selectedCredentialId && !hasModelOptions" class="text-xs text-muted-foreground">
 所选凭证暂无模型清单，可在 Provider 列表点「刷新模型清单」后再来选择，或直接手动输入模型名。
 </p>
 </div>
 <div class="flex justify-end">
 <Button:disabled="saving" @click="save">
 <span v-if="saving" class="icon-[lucide--loader-2] w-4 mr-1 animate-spin" />
 保存 Claude Code 配置
 </Button>
 </div>
 </template>
 </div>
</template>
