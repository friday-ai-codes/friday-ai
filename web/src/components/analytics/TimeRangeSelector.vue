<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'

const _props = defineProps<{
  modelValue: { from: string, to: string }
}>()

const emit = defineEmits<{
  'update:modelValue': [value: { from: string, to: string }]
}>()

type PresetOption = '7' | '30' | 'custom'

// 计算当前选中的预设
const selectedPreset = ref<PresetOption>('7')

// 自定义日期输入
const customFrom = ref('')
const customTo = ref('')

const presetOptions = [
  { value: '7', label: '近 7 天' },
  { value: '30', label: '近 30 天' },
  { value: 'custom', label: '自定义范围' },
] as const

const showCustomInputs = computed(() => selectedPreset.value === 'custom')

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

function onCustomDateChange() {
  if (customFrom.value && customTo.value) {
    emit('update:modelValue', {
      from: customFrom.value,
      to: customTo.value,
    })
  }
}
</script>

<template>
  <div class="flex flex-wrap items-center gap-2.5">
    <Select :model-value="selectedPreset" @update:model-value="onPresetChange">
      <SelectTrigger class="h-9 w-[140px] rounded-lg bg-background/90">
        <span class="icon-[lucide--calendar-days] mr-1.5 text-sm text-muted-foreground" />
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
        v-model="customFrom"
        type="date"
        class="h-9 rounded-lg border border-border/60 bg-background/90 px-3 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
        @change="onCustomDateChange"
      >
      <span class="text-muted-foreground text-sm">至</span>
      <input
        v-model="customTo"
        type="date"
        class="h-9 rounded-lg border border-border/60 bg-background/90 px-3 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
        @change="onCustomDateChange"
      >
    </template>

    <!-- : Analytics 工具栏右侧扩展插槽（放分组维度 Selector 等） -->
    <slot name="right" />
  </div>
</template>
