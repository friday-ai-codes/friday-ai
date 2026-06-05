<script setup lang="ts">
/**
 * Analytics 页面分组维度切换器（ — ）
 *
 * 3 选一：不分组 / 按 Provider / 按空间
 * v-model 支持；与 TimeRangeSelector 并列在 Analytics 页面顶部工具栏。
 */

import type { AnalyticsGrouping } from '~/stores/analyticsFilters'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'

defineProps<{
  modelValue: AnalyticsGrouping
}>()

const emit = defineEmits<{
  'update:modelValue': [value: AnalyticsGrouping]
}>()

const labels: Record<AnalyticsGrouping, string> = {
  none: '不分组',
  provider_type: '按 Provider',
  project: '按空间',
}

function onChange(value: string | number | bigint | Record<string, unknown> | null): void {
  if (typeof value !== 'string')
    return
  if (value === 'none' || value === 'provider_type' || value === 'project')
    emit('update:modelValue', value)
}
</script>

<template>
  <Select :model-value="modelValue" @update:model-value="onChange">
    <SelectTrigger class="w-[140px] bg-card/80 backdrop-blur-sm border-border/50" aria-label="数据分组维度">
      <SelectValue>
        {{ labels[modelValue] }}
      </SelectValue>
    </SelectTrigger>
    <SelectContent>
      <SelectItem value="none">
        不分组
      </SelectItem>
      <SelectItem value="provider_type">
        按 Provider
      </SelectItem>
      <SelectItem value="project">
        按空间
      </SelectItem>
    </SelectContent>
  </Select>
</template>
