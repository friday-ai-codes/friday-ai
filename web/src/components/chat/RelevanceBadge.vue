<script setup lang="ts">
/**
 * ：可复用的「跨仓相关性徽章」。
 *
 * 从 useRoutingStore 最新 trace 中查找对应 repository 的 candidate；
 * 自动按 level 渲染颜色（high=success / medium=warning / low=secondary）+
 * Tooltip 展示 evidence。
 *
 * 优雅降级：store 无对应 conversation trace / repository 不在 candidates →
 * `v-if="candidate"` 整个组件不渲染，避免「无数据」噪声。
 *
 * 与 RepoMultiSelector 共享 store；manual_override 写新 trace → store
 * latestTraceId 更新 → 本组件自动重渲染。
 */
import type { RoutingLevel } from '~/types/routing'
import { computed } from 'vue'
import { Badge } from '~/components/ui/badge'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '~/components/ui/tooltip'
import { useRoutingStore } from '~/stores/routing'

const props = defineProps<{
  repositoryId: string
  conversationId: string
}>()

const routingStore = useRoutingStore()

const candidate = computed(() => {
  const traceId = routingStore.latestTraceIdByConversationId.get(props.conversationId)
  if (!traceId)
    return null
  const trace = routingStore.tracesByTraceId.get(traceId)
  if (!trace)
    return null
  return trace.candidates.find(c => c.repository_id === props.repositoryId) ?? null
})

const variant = computed<'success' | 'warning' | 'secondary'>(() => {
  if (!candidate.value)
    return 'secondary'
  switch (candidate.value.level) {
    case 'high':
      return 'success'
    case 'medium':
      return 'warning'
    default:
      return 'secondary'
  }
})

const label = computed(() => {
  if (!candidate.value)
    return ''
  const pct = Math.round(candidate.value.score * 100)
  const cn: Record<RoutingLevel, string> = { high: '高', medium: '中', low: '低' }
  return `${pct}% ${cn[candidate.value.level]}`
})
</script>

<template>
  <TooltipProvider v-if="candidate" :delay-duration="200">
    <Tooltip>
      <TooltipTrigger as-child>
        <Badge :variant="variant" class="shrink-0 cursor-help text-[10px]">
          {{ label }}
        </Badge>
      </TooltipTrigger>
      <TooltipContent class="max-w-[24rem] text-xs">
        {{ candidate.evidence }}
      </TooltipContent>
    </Tooltip>
  </TooltipProvider>
</template>
