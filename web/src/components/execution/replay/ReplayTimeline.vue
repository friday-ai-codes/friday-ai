<script setup lang="ts">
import type { NodeExecution } from '~/stores/useExecutionsStore'
import { Slider } from '~/components/ui/slider'
import { computed } from 'vue'
const props = defineProps<{
 currentTime: number
 totalDuration: number
 nodeExecutions: NodeExecution
}>
const emit = defineEmits<{
 seek: [timeMs: number]
}>
function formatTime(ms: number): string {
 const totalSeconds = Math.floor(ms / 1000)
 const m = Math.floor(totalSeconds / 60)
 const s = totalSeconds % 60
 return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}
function getStatusColor(status: string): string {
 switch (status) {
 case 'completed':
 return 'bg-green-400'
 case 'failed':
 case 'timeout':
 return 'bg-red-400'
 case 'running':
 return 'bg-primary'
 case 'skipped':
 return 'bg-slate-300'
 default:
 return 'bg-slate-200'
 }
}
const executionStartMs = computed( => {
 const first = props.nodeExecutions.find(ne => ne.started_at)
 return first ? new Date(first.started_at!).getTime: 0
})
const timelineNodes = computed( => {
 const start = executionStartMs.value
 return props.nodeExecutions.map((ne) => {
 const neStart = ne.started_at ? new Date(ne.started_at).getTime - start: null
 const neEnd = ne.completed_at ? new Date(ne.completed_at).getTime - start: null
 const left = neStart !== null ? (neStart / props.totalDuration) * 100: 0
 const width = neStart !== null && neEnd !== null
 ? ((neEnd - neStart) / props.totalDuration) * 100: 0
 return {
 id: ne.node,
 name: ne.node_name || ne.node,
 left: Math.max(0, Math.min(100, left)),
 width: Math.max(0, Math.min(100, width)),
 status: ne.status,
 }
 })
})
const sliderValue = computed({
 get: => [props.currentTime],
 set: (v) => {
 if (v && v[0] !== undefined)
 emit('seek', v[0])
 },
})
</script>
<template>
 <div class="px-4 pb-3 space-y-2">
 <!-- 时间显示 + 滑块 -->
 <div class="flex items-center gap-3">
 <span class="text-xs text-muted-foreground font-mono tabular-nums w-14 text-right">
 {{ formatTime(currentTime) }}
 </span>
 <Slider
 v-model="sliderValue":max="totalDuration":step="100"
 class="flex-1"
 aria-label="回放进度"
 />
 <span class="text-xs text-muted-foreground font-mono tabular-nums w-14">
 {{ formatTime(totalDuration) }}
 </span>
 </div>
 <!-- 节点甘特图 -->
 <div class="space-y-1">
 <div
 v-for="node in timelineNodes":key="node.id"
 class="flex items-center gap-2"
 >
 <span class="text-xs text-muted-foreground w-24 truncate shrink-0">
 {{ node.name }}
 </span>
 <div class="flex-1 bg-muted rounded-full relative overflow-hidden">
 <div
 class="absolute h-full rounded-full transition-all duration-150":class="getStatusColor(node.status)":style="{ left: `${node.left}%`, width: `${node.width}%` }"
 />
 </div>
 </div>
 </div>
 </div>
</template>
