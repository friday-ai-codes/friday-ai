<script setup lang="ts">
/**
 * GraphAutoBuildToggle — 仓库自动构图开关
 *
 * 用法（Plan RepositoryGraphCard header 内一行嵌入）：
 * <GraphAutoBuildToggle
 *:repository-id="repo.id"
 *:initial="repo.auto_build_graph_enabled"
 * @update:enabled="onAutoBuildChanged"
 * />
 *
 * 实现要点：
 * - optimistic update：先翻视觉态再发请求；失败时把视觉态回滚到 prev
 * - saving 期间禁用 Switch 避免重复点击
 * - 走 repositoriesApi.update PATCH（与现有 auto_index_enabled 同款）
 */
import { ref, watch } from 'vue'
import { repositoriesApi } from '~/api/repositories'
import { Switch } from '~/components/ui/switch'
import {
 Tooltip,
 TooltipContent,
 TooltipProvider,
 TooltipTrigger,
} from '~/components/ui/tooltip'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'
const props = defineProps<{
 repositoryId: string
 initial: boolean
}>
const emit = defineEmits<{
 'update:enabled': [next: boolean]
}>
const enabled = ref<boolean>(props.initial)
const saving = ref<boolean>(false)
const { success } = useToast
const { handleError } = useErrorHandler
watch( => props.initial, (next) => {
 if (!saving.value)
 enabled.value = next
})
async function toggle(next: boolean): Promise<void> {
 if (saving.value)
 return
 const prev = enabled.value
 enabled.value = next
 saving.value = true
 try {
 await repositoriesApi.update(props.repositoryId, { auto_build_graph_enabled: next })
 emit('update:enabled', next)
 success(next ? '已开启自动构建图谱': '已关闭自动构建图谱')
 }
 catch (err) {
 enabled.value = prev
 handleError(err, '更新自动构建开关')
 }
 finally {
 saving.value = false
 }
}
</script>
<template>
 <div class="flex items-center gap-1.5">
 <TooltipProvider>
 <Tooltip>
 <TooltipTrigger as-child>
 <Switch:model-value="enabled":disabled="saving"
 aria-label="自动构建代码图谱"
 @update:model-value="toggle"
 />
 </TooltipTrigger>
 <TooltipContent>
 <p class="text-xs">
 关闭后索引完成不会自动构建图谱，可点&quot;立即构建&quot;手动触发
 </p>
 </TooltipContent>
 </Tooltip>
 </TooltipProvider>
 <span class="text-xs text-muted-foreground">自动</span>
 </div>
</template>
