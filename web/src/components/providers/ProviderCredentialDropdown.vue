<script setup lang="ts">
import type { ProviderCredentialDto, ProviderType } from '~/types/providerCredential'
/**
 * Provider 凭证选择下拉（Phase + CONTEXT ）
 *
 * 数据源:store.activeCredentials(按 is_active=true 过滤)
 * 展现:按 provider_type 分组(SelectGroup) + 名称 + scope 标注
 * 空态:根据 usePermission.isSystemAdmin 分流 CTA
 * - 系统管理员 → /admin/providers
 * - 普通用户 → /projects/:id/settings#providers 或 /projects
 *
 * Typography: SelectLabel 显式 font-normal 覆盖默认字重(work item §Typography)。
 */
import { computed, onMounted, watch } from 'vue'
import { RouterLink } from 'vue-router'
import {
 Select,
 SelectContent,
 SelectGroup,
 SelectItem,
 SelectLabel,
 SelectTrigger,
 SelectValue,
} from '~/components/ui/select'
import { usePermission } from '~/composables/usePermission'
import { useProviderCredentialStore } from '~/stores/providerCredential'
interface Props {
 modelValue: string | null
 providerFilter?: ProviderType
 scope: 'system' | 'project'
 projectId?: string
}
const props = withDefaults(defineProps<Props>, {
 providerFilter: undefined,
 projectId: undefined,
})
const emit = defineEmits<{
 (e: 'update:modelValue', v: string | null): void
 (e: 'change', cred: ProviderCredentialDto | null): void
}>
const store = useProviderCredentialStore
const { isSystemAdmin } = usePermission
onMounted( => {
 void store.fetchCredentials({ scope: props.scope, projectId: props.projectId })
})
// scope / projectId 变化 → 强制刷新(跨上下文不能命中 30s TTL 缓存)
watch(
 => [props.scope, props.projectId],
 => {
 void store.fetchCredentials({
 scope: props.scope,
 projectId: props.projectId,
 force: true,
 })
 },
)
const availableCredentials = computed<ProviderCredentialDto>( => {
 const base = store.activeCredentials
 if (!props.providerFilter || props.providerFilter.length === 0)
 return base
 const filter = props.providerFilter
 return base.filter(c => filter.includes(c.provider_type))
})
const groupedByProvider = computed<Record<string, ProviderCredentialDto>>( => {
 const groups: Record<string, ProviderCredentialDto> = {}
 for (const c of availableCredentials.value) {
 if (!groups[c.provider_type])
 groups[c.provider_type] =
 groups[c.provider_type].push(c)
 }
 return groups
})
const emptyCta = computed( => {
 if (isSystemAdmin.value)
 return { text: '去添加凭证 →', to: '/admin/providers' }
 return {
 text: '去项目设置添加凭证 →',
 to: props.projectId ? `/projects/${props.projectId}/settings#providers`: '/projects',
 }
})
// reka-ui Select `@update:model-value` 的签名是 AcceptableValue(含 bigint / Record),
// 实践中 Select value 始终为 string,这里做安全归一。
function onChange(id: unknown) {
 const idStr = typeof id === 'string' && id.length > 0 ? id: null
 const cred = idStr
 ? (availableCredentials.value.find(c => c.id === idStr) ?? null): null
 emit('update:modelValue', idStr)
 emit('change', cred)
}
</script>
<template>
 <Select:model-value="props.modelValue ?? ''"
 @update:model-value="onChange"
 >
 <SelectTrigger>
 <SelectValue placeholder="请选择凭证" />
 </SelectTrigger>
 <SelectContent>
 <template v-if="availableCredentials.length === 0">
 <div class="px-3 py-4 flex flex-col items-center gap-2">
 <span class="icon-[lucide--alert-triangle] w-4 text-muted-foreground" />
 <p class="text-sm text-muted-foreground">
 暂无可用凭证
 </p>
 <RouterLink:to="emptyCta.to"
 class="text-sm text-primary hover:underline"
 >
 {{ emptyCta.text }}
 </RouterLink>
 </div>
 </template>
 <template v-else>
 <SelectGroup
 v-for="(creds, providerType) in groupedByProvider":key="providerType"
 >
 <SelectLabel class="font-normal text-xs text-muted-foreground">
 {{ providerType }}
 </SelectLabel>
 <SelectItem
 v-for="c in creds":key="c.id":value="c.id"
 >
 <span>{{ c.name }}</span>
 <span class="ml-2 text-xs text-muted-foreground">
 {{ c.scope === 'system' ? '系统默认': '仅本项目' }}
 </span>
 </SelectItem>
 </SelectGroup>
 </template>
 </SelectContent>
 </Select>
</template>
