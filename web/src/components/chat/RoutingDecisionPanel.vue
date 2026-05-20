<script setup lang="ts">
/**
 * Phase / 07 / 08：路由决策可视化卡片。
 *
 * - 来源：RoutingDecisionData via useRoutingStore（trace_id 由 ChatMessageBubble
 * 通过 props 传入；store 内部维护双索引 + latest 指针）。
 * - 双向勾选：Checkbox v-model 反映 candidate.selected_by_user_final；
 * debounce 300ms 触发 routingStore.applyManualOverride → POST /override/。
 * - 「基于这些仓库创建编码方案」按钮 emit `create-coding-plan-from-trace`
 * 事件给父组件 ChatMessageBubble，后者发一条 user message 让 LLM 主导
 * create_coding_plan tool call。
 * - 优雅降级：store 无对应 trace → v-if 整个组件不渲染。
 *
 * 视觉：glassmorphism（DESIGN.md）+ shadcn-vue Card/Badge/Tooltip/Checkbox/Button +
 * Tailwind（禁内联样式）。
 */
import type { ManualOverrideRequestCandidate, RoutingCandidate, RoutingLevel } from '~/types/routing'
import { useDebounceFn } from '@vueuse/core'
import { computed, ref } from 'vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Card } from '~/components/ui/card'
import { Checkbox } from '~/components/ui/checkbox'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '~/components/ui/tooltip'
import { useRoutingStore } from '~/stores/routing'
const props = defineProps<{
 traceId: string
 conversationId: string
 messageId?: string
}>
const emit = defineEmits<{
 createCodingPlanFromTrace: [traceId: string]
 manualSelectRequested: [traceId: string]
}>
const routingStore = useRoutingStore
/**
 * 状态来源是 store 中**最新** trace（manual_override 后实时反映），而非 props 初始 trace_id。
 */
const effectiveTraceId = computed( => {
 return routingStore.getLatestTraceId(props.conversationId) ?? props.traceId
})
const trace = computed( => routingStore.getTrace(effectiveTraceId.value))
const sortedCandidates = computed<RoutingCandidate>( => {
 if (!trace.value)
 return
 return [...trace.value.candidates].sort((a, b) => b.score - a.score)
})
const levelCounts = computed( => {
 const counts: Record<RoutingLevel, number> = { high: 0, medium: 0, low: 0 }
 for (const c of sortedCandidates.value)
 counts[c.level]++
 return counts
})
const collapsed = ref(false)
function variantOf(level: RoutingLevel): 'success' | 'warning' | 'secondary' {
 if (level === 'high')
 return 'success'
 if (level === 'medium')
 return 'warning'
 return 'secondary'
}
function labelOf(level: RoutingLevel): string {
 return ({ high: '高', medium: '中', low: '低' } as const)[level]
}
/**
 * pendingOverrides 累积当前 debounce 窗口内的勾选变化；
 * sync 触发后清空。失败回滚由 store 内部返回 null 通知调用方处理。
 */
const pendingOverrides = ref<Map<string, boolean>>(new Map)
async function syncPending {
 if (pendingOverrides.value.size === 0)
 return
 const payload: ManualOverrideRequestCandidate = Array.from(
 pendingOverrides.value,
 ([rid, sel]) => ({ repository_id: rid, selected: sel }),
 )
 pendingOverrides.value = new Map
 const result = await routingStore.applyManualOverride(
 props.conversationId,
 effectiveTraceId.value,
 payload,
 )
 if (!result) {
 console.warn('manual override 失败，下一次操作时会重试')
 }
}
const debouncedSync = useDebounceFn(syncPending, 300)
function onToggle(repoId: string, value: boolean | string | undefined) {
 pendingOverrides.value.set(repoId, value === true)
 debouncedSync
}
function checkedFor(c: RoutingCandidate): boolean {
 if (pendingOverrides.value.has(c.repository_id))
 return pendingOverrides.value.get(c.repository_id) === true
 return c.selected_by_user_final
}
function onCreateCodingPlan {
 emit('createCodingPlanFromTrace', effectiveTraceId.value)
}
function onOpenManualSelect {
 emit('manualSelectRequested', effectiveTraceId.value)
}
</script>
<template>
 <Card
 v-if="trace"
 class="relative my-2 rounded-md border border-zinc-200 bg-white/60 backdrop-blur"
 >
 <button
 type="button"
 class="flex w-full items-center justify-between text-left text-sm font-medium text-zinc-800 transition-colors hover:text-zinc-950"
 @click="collapsed = !collapsed"
 >
 <span class="inline-flex items-center gap-2">
 <span>→ 路由决策（{{ sortedCandidates.length }} 个仓库相关）</span>
 <span class="text-xs text-zinc-500">
 高 {{ levelCounts.high }} · 中 {{ levelCounts.medium }} · 低 {{ levelCounts.low }}
 </span>
 </span>
 <span class="text-xs text-zinc-400">
 {{ collapsed ? '展开': '收起' }}
 </span>
 </button>
 <div v-if="!collapsed" class="mt-3 space-y-2">
 <div v-if="trace.query" class="text-xs text-zinc-500">
 query: <span class="text-zinc-700">{{ trace.query }}</span>
 <span class="ml-2">阈值 {{ trace.threshold.toFixed(2) }}</span>
 </div>
 <TooltipProvider:delay-duration="200">
 <ul class="space-y-1.5">
 <li
 v-for="c in sortedCandidates":key="c.repository_id"
 class="flex items-start gap-3 rounded px-1 py-1.5 hover:bg-zinc-50"
 >
 <Checkbox:model-value="checkedFor(c)"
 class="mt-0.5"
 @update:model-value="(v) => onToggle(c.repository_id, v)"
 />
 <span class="min-w-0 flex-1 truncate text-sm font-medium text-zinc-900">
 {{ c.repository_name }}
 </span>
 <Badge:variant="variantOf(c.level)" class="shrink-0">
 {{ Math.round(c.score * 100) }}% {{ labelOf(c.level) }}
 </Badge>
 <Tooltip>
 <TooltipTrigger as-child>
 <p class="hidden max-w-[18rem] cursor-help truncate text-xs text-zinc-500 sm:block">
 {{ c.evidence }}
 </p>
 </TooltipTrigger>
 <TooltipContent class="max-w-[24rem] text-xs">
 {{ c.evidence }}
 </TooltipContent>
 </Tooltip>
 </li>
 </ul>
 </TooltipProvider>
 <div class="mt-3 flex flex-wrap gap-2">
 <Button size="sm" @click="onCreateCodingPlan">
 基于这些仓库创建编码方案
 </Button>
 <Button size="sm" variant="ghost" @click="onOpenManualSelect">
 手动调整选择
 </Button>
 </div>
 </div>
 </Card>
</template>
