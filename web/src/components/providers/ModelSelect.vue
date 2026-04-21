<script setup lang="ts">
/**
 * 模型下拉组件（Phase + CONTEXT / ）
 *
 * 数据源:store.getModelsForCredential(id) — cache hit(available_models 非空)
 * 秒级返回;miss 才走后端 /refresh-models/
 *
 * 行为:
 * - watch credentialId immediate:变化时清空 models 并重拉
 * - 若旧 modelValue 不在新 list 中,自动 emit('update:modelValue', null) 清空
 * - capability 过滤:
 * * requiresTools=true 且 m.supports_tools===false → 排除
 * * requiresVision=true 且 m.supports_vision!==true → 排除
 * - option 标签:`${display_name} [${Math.round(ctx/1000)}K]`(work item §Placeholder)
 * - loading 态:loader-2 animate-spin + "加载模型清单中…"
 * - filteredModels 为空:"无可用模型"
 */
import { computed, ref, watch } from 'vue'
import { useProviderCredentialStore } from '~/stores/providerCredential'
import type { AvailableModel } from '~/types/providerCredential'
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from '~/components/ui/select'
interface Props {
 credentialId: string | null
 requiresTools?: boolean
 requiresVision?: boolean
 modelValue: string | null
}
const props = withDefaults(defineProps<Props>, {
 requiresTools: false,
 requiresVision: false,
})
const emit = defineEmits<{
 (e: 'update:modelValue', v: string | null): void
}>
const store = useProviderCredentialStore
const models = ref<AvailableModel>
const loading = ref(false)
watch(
 => props.credentialId,
 async (id) => {
 models.value =
 if (!id)
 return
 loading.value = true
 try {
 models.value = await store.getModelsForCredential(id)
 //:旧 model 在新 Provider 下不可用 → 清空,由父组件负责提示文案
 if (props.modelValue && !models.value.some(m => m.id === props.modelValue))
 emit('update:modelValue', null)
 }
 catch {
 // 错误由 store 层已记录 lastError;此处保持 models 空,由模板渲染"无可用模型"
 }
 finally {
 loading.value = false
 }
 },
 { immediate: true },
)
const filteredModels = computed<AvailableModel>( => {
 return models.value.filter((m) => {
 if (props.requiresTools && m.supports_tools === false)
 return false
 if (props.requiresVision && m.supports_vision !== true)
 return false
 return true
 })
})
function formatLabel(m: AvailableModel): string {
 if (typeof m.context_length === 'number' && m.context_length > 0)
 return `${m.display_name} [${Math.round(m.context_length / 1000)}K]`
 return m.display_name
}
function onChange(id: unknown) {
 const v = typeof id === 'string' && id.length > 0 ? id: null
 emit('update:modelValue', v)
}
</script>
<template>
 <Select:model-value="props.modelValue ?? ''"
 @update:model-value="onChange"
 >
 <SelectTrigger>
 <SelectValue placeholder="请选择模型" />
 </SelectTrigger>
 <SelectContent>
 <template v-if="loading">
 <div class="px-3 py-2 text-sm text-muted-foreground inline-flex items-center gap-1">
 <span class="icon-[lucide--loader-2] animate-spin w-3 " />
 加载模型清单中…
 </div>
 </template>
 <template v-else-if="filteredModels.length === 0">
 <div class="px-3 py-2 text-sm text-muted-foreground">
 无可用模型
 </div>
 </template>
 <template v-else>
 <SelectItem
 v-for="m in filteredModels":key="m.id":value="m.id"
 >
 {{ formatLabel(m) }}
 </SelectItem>
 </template>
 </SelectContent>
 </Select>
</template>
