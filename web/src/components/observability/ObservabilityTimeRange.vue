<script setup lang="ts">
import { computed, ref } from 'vue'
import { Button } from '~/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'
import { Switch } from '~/components/ui/switch'

/**
 * 运维时间范围选择器（5m / 1h / 24h / 自定义）+ 自动刷新开关。
 *
 * 职责边界：本组件只负责 UI 与 emit，**不自持定时器**——自动刷新状态以
 * `autoRefresh` 受控 v-model 暴露，定时逻辑由各页 onMounted 读取 autoRefresh 自行实现，
 * 「立即刷新」按钮 emit('refresh') 触发父页一次性拉取。预设选中时按 now 反推 ISO 起止。
 */
const props = withDefaults(defineProps<{
  /** ISO8601 起止时间。 */
  modelValue: { start: string, end: string }
  /** 自动刷新开关（受控，默认开）。 */
  autoRefresh?: boolean
}>(), {
  autoRefresh: true,
})

const emit = defineEmits<{
  'update:modelValue': [value: { start: string, end: string }]
  'update:autoRefresh': [value: boolean]
  'refresh': []
}>()

type PresetOption = '5m' | '1h' | '24h' | 'custom'

const PRESET_MS: Record<Exclude<PresetOption, 'custom'>, number> = {
  '5m': 5 * 60 * 1000,
  '1h': 60 * 60 * 1000,
  '24h': 24 * 60 * 60 * 1000,
}

const presetOptions = [
  { value: '5m', label: '近 5 分钟' },
  { value: '1h', label: '近 1 小时' },
  { value: '24h', label: '近 24 小时' },
  { value: 'custom', label: '自定义范围' },
] as const

const selectedPreset = ref<PresetOption>('1h')
// datetime-local 输入值（绑定到自定义起止）。
const customStart = ref('')
const customEnd = ref('')

const showCustomInputs = computed(() => selectedPreset.value === 'custom')

function emitRange(start: string, end: string) {
  emit('update:modelValue', { start, end })
}

function applyPreset(preset: Exclude<PresetOption, 'custom'>) {
  const now = Date.now()
  emitRange(new Date(now - PRESET_MS[preset]).toISOString(), new Date(now).toISOString())
}

function onPresetChange(value: any) {
  if (typeof value !== 'string')
    return
  selectedPreset.value = value as PresetOption
  if (value !== 'custom')
    applyPreset(value as Exclude<PresetOption, 'custom'>)
}

function onCustomDateChange() {
  if (customStart.value && customEnd.value) {
    // datetime-local 无时区，按本地时区转 ISO（与后端 _parse_iso naive 补 UTC 对齐由后端处理）。
    emitRange(new Date(customStart.value).toISOString(), new Date(customEnd.value).toISOString())
  }
}

function onAutoRefreshChange(value: boolean) {
  emit('update:autoRefresh', value)
}
</script>

<template>
  <div class="flex flex-wrap items-center gap-2.5">
    <Select :model-value="selectedPreset" @update:model-value="onPresetChange">
      <SelectTrigger class="h-9 w-[140px] rounded-lg bg-background/90">
        <span class="icon-[lucide--clock] mr-1.5 text-sm text-muted-foreground" />
        <SelectValue placeholder="时间范围" />
      </SelectTrigger>
      <SelectContent>
        <SelectItem v-for="opt in presetOptions" :key="opt.value" :value="opt.value">
          {{ opt.label }}
        </SelectItem>
      </SelectContent>
    </Select>

    <template v-if="showCustomInputs">
      <input
        v-model="customStart"
        type="datetime-local"
        aria-label="开始时间"
        class="h-9 cursor-pointer rounded-lg border border-border/60 bg-background/90 px-3 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
        @change="onCustomDateChange"
      >
      <span class="text-muted-foreground text-sm">至</span>
      <input
        v-model="customEnd"
        type="datetime-local"
        aria-label="结束时间"
        class="h-9 cursor-pointer rounded-lg border border-border/60 bg-background/90 px-3 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
        @change="onCustomDateChange"
      >
    </template>

    <!-- 右侧扩展插槽（放分组维度切换器等，对齐 analytics 范式） -->
    <slot name="right" />

    <div class="ml-auto flex items-center gap-3">
      <label class="flex cursor-pointer items-center gap-2 text-sm text-muted-foreground select-none">
        <Switch :model-value="props.autoRefresh" aria-label="自动刷新" @update:model-value="onAutoRefreshChange" />
        <span>自动刷新</span>
      </label>
      <Button
        variant="outline"
        size="sm"
        aria-label="立即刷新"
        class="gap-1.5"
        @click="emit('refresh')"
      >
        <span class="icon-[lucide--refresh-cw] text-sm" />
        立即刷新
      </Button>
    </div>
  </div>
</template>
