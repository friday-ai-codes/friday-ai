<script setup lang="ts">
import type { ReplaySpeed } from '../dag/composables/useExecutionReplay'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '~/components/ui/select'
const props = defineProps<{
 isPlaying: boolean
 speed: ReplaySpeed
 canStepForward: boolean
 canStepBackward: boolean
}>
const emit = defineEmits<{
 play:
 pause:
 stepForward:
 stepBackward:
 speedChange: [speed: ReplaySpeed]
}>
const speedOptions: { label: string; value: ReplaySpeed } = [
 { label: '0.5x', value: 0.5 },
 { label: '1x', value: 1 },
 { label: '2x', value: 2 },
 { label: '4x', value: 4 },
 { label: '即时', value: 0 },
]
function togglePlay {
 if (props.isPlaying)
 emit('pause')
 else
 emit('play')
}
</script>
<template>
 <div class="flex items-center gap-3 px-4 py-2">
 <!-- 播放/暂停 -->
 <button
 type="button"
 class="flex items-center justify-center w-9 rounded-full bg-primary text-primary-foreground hover:bg-primary/90 transition-colors":aria-label="isPlaying ? '暂停': '播放'"
 @click="togglePlay"
 >
 <span
 class="w-5 ":class="isPlaying ? 'icon-[lucide--pause]': 'icon-[lucide--play]'"
 />
 </button>
 <!-- 步进控制 -->
 <button
 type="button"
 class="flex items-center justify-center w-9 rounded-lg hover:bg-secondary transition-colors disabled:opacity-30":disabled="!canStepBackward"
 aria-label="上一步"
 @click="emit('stepBackward')"
 >
 <span class="w-4 icon-[lucide--skip-back]" />
 </button>
 <button
 type="button"
 class="flex items-center justify-center w-9 rounded-lg hover:bg-secondary transition-colors disabled:opacity-30":disabled="!canStepForward"
 aria-label="下一步"
 @click="emit('stepForward')"
 >
 <span class="w-4 icon-[lucide--skip-forward]" />
 </button>
 <!-- 速度选择 -->
 <Select:model-value="String(speed)" @update:model-value="v => emit('speedChange', Number(v) as ReplaySpeed)">
 <SelectTrigger class="w-20 text-xs">
 <SelectValue />
 </SelectTrigger>
 <SelectContent>
 <SelectItem v-for="opt in speedOptions":key="opt.value":value="String(opt.value)">
 {{ opt.label }}
 </SelectItem>
 </SelectContent>
 </Select>
 </div>
</template>
