<script setup lang="ts">
import { computed, ref } from 'vue'
import { DateRangePicker } from '~/components/ui/date-range-picker'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'

const props = defineProps<{
  modelValue: { from: string, to: string }
}>()

const emit = defineEmits<{
  'update:modelValue': [value: { from: string, to: string }]
}>()

type PresetOption = '7' | '30' | 'custom'

// 计算当前选中的预设
const selectedPreset = ref<PresetOption>('7')

const presetOptions = [
  { value: '7', label: '近 7 天' },
  { value: '30', label: '近 30 天' },
  { value: 'custom', label: '自定义范围' },
] as const

const showCustomInputs = computed(() => selectedPreset.value === 'custom')

// DateRangePicker 用 { start, end }，本组件对外为 { from, to }，两侧做映射。
const customRange = computed(() => ({ start: props.modelValue.from, end: props.modelValue.to }))

function getDateString(daysAgo: number): string {
  const d = new Date()
  d.setDate(d.getDate() - daysAgo)
  return d.toISOString().split('T')[0]
}

function onPresetChange(value: string | number | bigint | Record<string, any> | null) {
  if (typeof value !== 'string')
    return
  selectedPreset.value = value as PresetOption
  if (value === '7' || value === '30') {
    const days = Number.parseInt(value)
    emit('update:modelValue', {
      from: getDateString(days),
      to: getDateString(0),
    })
  }
}

function onCustomRangeChange(value: { start: string, end: string }) {
  emit('update:modelValue', { from: value.start, to: value.end })
}
</script>

<template>
  <div class="flex flex-wrap items-center gap-2.5">
    <Select :model-value="selectedPreset" @update:model-value="onPresetChange">
      <SelectTrigger class="h-9 w-[140px] rounded-lg bg-background/90">
        <span class="icon-[lucide--calendar-days] mr-1.5 text-base text-muted-foreground" />
        <SelectValue placeholder="时间范围" />
      </SelectTrigger>
      <SelectContent>
        <SelectItem v-for="opt in presetOptions" :key="opt.value" :value="opt.value">
          {{ opt.label }}
        </SelectItem>
      </SelectContent>
    </Select>

    <DateRangePicker
      v-if="showCustomInputs"
      :model-value="customRange"
      align="start"
      @update:model-value="onCustomRangeChange"
    />

    <!-- : Analytics 工具栏右侧扩展插槽（放分组维度 Selector 等） -->
    <slot name="right" />
  </div>
</template>
