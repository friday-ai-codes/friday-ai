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
const TIERS: { key: ModelTier, label: string, hint: string, dot: string, icon: string } = [
 { key: 'opus', label: 'Opus', hint: '复杂规划 / 高难度任务', dot: 'bg-violet-500', icon: 'icon-[lucide--gem]' },
 { key: 'sonnet', label: 'Sonnet', hint: '默认主模型，日常编码', dot: 'bg-primary', icon: 'icon-[lucide--zap]' },
 { key: 'haiku', label: 'Haiku', hint: '子代理 / 后台快速任务', dot: 'bg-slate-400', icon: 'icon-[lucide--feather]' },
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
 <label class="text-xs font-medium uppercase tracking-wider text-muted-foreground">
 编码 Provider 凭证
 </label>
 <Select v-model="selectedCredentialId">
 <SelectTrigger class="max-w-md">
 <SelectValue placeholder="选择 Claude Code 使用的凭证" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem
 v-for="c in candidateCredentials":key="c.id":value="c.id"
 >
 {{ c.name }} · {{ c.provider_type }}
 </SelectItem>
 </SelectContent>
 </Select>
 <p class="text-xs text-muted-foreground">
 优先选 anthropic 凭证，未选则用系统默认。
 </p>
 </div>
 <!-- 三档模型映射 -->
 <div class="space-y-2.5">
 <label class="text-xs font-medium uppercase tracking-wider text-muted-foreground">
 模型映射
 </label>
 <div class="overflow-hidden rounded-xl border border-border/60">
 <div
 v-for="(tier, idx) in TIERS":key="tier.key"
 class="flex items-center gap-4 px-5 py-4":class="{ 'border-t border-border/50': idx > 0 }"
 >
 <!-- 档位身份：色点 + 名称 + 一行说明（whitespace-nowrap 避免挤压换行） -->
 <div class="flex w-48 shrink-0 items-center gap-3">
 <span class=".5 w-2.5 shrink-0 rounded-full":class="tier.dot" aria-hidden="true" />
 <div class="min-w-0">
 <p class="flex items-center gap-1.5 text-sm font-semibold text-foreground">
 <span class=" w-4 text-muted-foreground":class="tier.icon" aria-hidden="true" />
 {{ tier.label }}
 </p>
 <p class="whitespace-nowrap text-xs text-muted-foreground">
 {{ tier.hint }}
 </p>
 </div>
 </div>
 <!-- 模型选择：占据剩余空间，撑开层次 -->
 <div class="min-w-0 flex-1">
 <Select
 v-if="hasModelOptions"
 v-model="mapping[tier.key]"
 >
 <SelectTrigger class="">
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
 placeholder="手动输入模型名，如 claude-sonnet-4-20250514"
 class=" text-sm"
 />
 </div>
 </div>
 </div>
 <p v-if="selectedCredentialId && !hasModelOptions" class="text-xs text-muted-foreground">
 所选凭证暂无模型清单，可先在上方「刷新模型清单」，或手动输入模型名。
 </p>
 </div>
 <div class="flex justify-end border-t border-border/50 pt-4">
 <Button:disabled="saving" @click="save">
 <span v-if="saving" class="icon-[lucide--loader-2] w-4 mr-1.5 animate-spin" />
 <span v-else class="icon-[lucide--save] w-4 mr-1.5" />
 保存配置
 </Button>
 </div>
 </template>
 </div>
</template>
