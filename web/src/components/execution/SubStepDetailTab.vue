<script setup lang="ts">
import type { SubStep } from '~/types/execution'
/**
 * SubStepDetailTab — 子步骤详情 Tab
 *
 * 在 NodeDetailSheet 中展示 AI 节点的子步骤列表，
 * 每个子步骤可展开查看输入/输出数据、状态和耗时。
 */
import { computed, onMounted, ref, watch } from 'vue'
import StatusBadge from '~/components/common/StatusBadge.vue'
import Badge from '~/components/ui/badge/Badge.vue'
import { useExecutionsStore } from '~/stores/useExecutionsStore'
const props = defineProps<{
 nodeExecutionId: string
 /** 外部传入的聚焦子步骤 ID（从时间线点击跳转） */
 focusStepId?: string
}>
const store = useExecutionsStore
const expandedStepId = ref<string | null>(null)
// 从 store 获取子步骤
const steps = computed<SubStep>( => store.subSteps[props.nodeExecutionId] ?? )
// 首次加载
onMounted( => {
 if (steps.value.length === 0) {
 store.fetchSubSteps(props.nodeExecutionId)
 }
})
// 外部聚焦
watch( => props.focusStepId, (id) => {
 if (id)
 expandedStepId.value = id
}, { immediate: true })
function statusColor(status: string): string {
 const map: Record<string, string> = {
 pending: 'bg-gray-300',
 running: 'bg-primary animate-pulse',
 completed: 'bg-green-400',
 failed: 'bg-red-400',
 }
 return map[status] ?? 'bg-gray-300'
}
function formatDuration(step: SubStep): string {
 if (!step.started_at || !step.completed_at)
 return '-'
 const ms = new Date(step.completed_at).getTime - new Date(step.started_at).getTime
 if (ms < 1000)
 return `${ms}ms`
 return `${(ms / 1000).toFixed(1)}s`
}
</script>
<template>
 <div class="space-y-2">
 <div v-if="steps.length === 0" class="text-sm text-muted-foreground text-center py-8">
 暂无子步骤数据
 </div>
 <div
 v-for="step in steps":key="step.id"
 class="rounded-xl border border-border/50 overflow-hidden transition-colors":class="step.status === 'failed' ? 'border-red-400/30': ''"
 >
 <!-- 步骤头部（可点击展开） -->
 <button
 class="w-full flex items-center gap-3 px-3 py-2.5 text-left hover:bg-muted/30 transition-colors"
 @click="expandedStepId = expandedStepId === step.id ? null: step.id"
 >
 <!-- 状态圆点 -->
 <div class="w-2.5 .5 rounded-full shrink-0":class="statusColor(step.status)" />
 <!-- 名称 -->
 <span class="text-sm flex-1 truncate">{{ step.name }}</span>
 <!-- 类型 Badge -->
 <Badge variant="outline" class="text-[10px] shrink-0">
 {{ step.step_type }}
 </Badge>
 <!-- 耗时 -->
 <span class="text-[11px] text-muted-foreground tabular-nums shrink-0">
 {{ formatDuration(step) }}
 </span>
 <!-- 展开指示 -->
 <span
 class="icon-[lucide--chevron-down] w-3.5 .5 text-muted-foreground transition-transform duration-200":class="{ 'rotate-180': expandedStepId === step.id }"
 />
 </button>
 <!-- 展开详情 -->
 <div v-if="expandedStepId === step.id" class="px-3 pb-3 space-y-3 border-t border-border/30">
 <!-- 状态行 -->
 <div class="flex items-center gap-2 pt-2 text-xs text-muted-foreground flex-wrap">
 <span>状态:</span>
 <StatusBadge type="execution":status="step.status" size="sm" />
 <span v-if="step.started_at">
 开始: {{ new Date(step.started_at).toLocaleTimeString }}
 </span>
 <span v-if="step.completed_at">
 结束: {{ new Date(step.completed_at).toLocaleTimeString }}
 </span>
 </div>
 <!-- 输入数据 -->
 <div v-if="Object.keys(step.input_data).length > 0">
 <div class="text-xs font-medium text-muted-foreground mb-1">
 输入
 </div>
 <pre class="text-[11px] bg-muted/30 rounded-lg overflow-x-auto max- overflow-y-auto font-mono">{{ JSON.stringify(step.input_data, null, 2) }}</pre>
 </div>
 <!-- 输出数据 -->
 <div v-if="Object.keys(step.output_data).length > 0">
 <div class="text-xs font-medium text-muted-foreground mb-1">
 输出
 </div>
 <pre
 class="text-[11px] bg-muted/30 rounded-lg overflow-x-auto max- overflow-y-auto font-mono":class="step.status === 'failed' ? 'text-red-400': ''"
 >{{ JSON.stringify(step.output_data, null, 2) }}</pre>
 </div>
 </div>
 </div>
 </div>
</template>
