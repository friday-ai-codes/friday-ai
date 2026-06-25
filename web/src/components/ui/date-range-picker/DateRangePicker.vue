<script setup lang="ts">
import type { DateRange, DateValue } from 'reka-ui'
import type { HTMLAttributes } from 'vue'
import { CalendarDate } from '@internationalized/date'
import { computed, ref, shallowRef, watch } from 'vue'
import { Button } from '~/components/ui/button'
import { RangeCalendar } from '~/components/ui/calendar'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { Popover, PopoverContent, PopoverTrigger } from '~/components/ui/popover'
import { cn } from '~/lib/utils'

/**
 * 日期范围选择器（Popover + RangeCalendar）。
 *
 * - `withTime=false`：modelValue 为 `yyyy-MM-dd` 字符串（用于按天统计）。
 * - `withTime=true`：modelValue 为本地时区推导的 ISO8601 字符串（用于运维分钟级范围），
 *   日历选日期，下方时间输入选时分。
 */
const props = withDefaults(defineProps<{
  modelValue: { start: string, end: string }
  withTime?: boolean
  align?: 'start' | 'center' | 'end'
  placeholder?: string
  triggerClass?: HTMLAttributes['class']
}>(), {
  withTime: false,
  align: 'start',
  placeholder: '选择时间范围',
})

const emit = defineEmits<{
  'update:modelValue': [value: { start: string, end: string }]
}>()

const open = ref(false)

function pad(n: number) {
  return String(n).padStart(2, '0')
}

function parseToCalendarDate(value: string): DateValue | undefined {
  if (!value)
    return undefined
  const d = props.withTime ? new Date(value) : new Date(`${value}T00:00:00`)
  if (Number.isNaN(d.getTime()))
    return undefined
  // reka-ui 的 DateValue 是 @internationalized/date 联合类型，CalendarDate 是其成员；
  // 跨包类型解析下显式 cast 以消除联合分支推断噪声。
  return new CalendarDate(d.getFullYear(), d.getMonth() + 1, d.getDate()) as unknown as DateValue
}

function parseToTime(value: string): string {
  if (!value)
    return ''
  const d = new Date(value)
  if (Number.isNaN(d.getTime()))
    return ''
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

// 草稿状态（仅在 Popover 内编辑，应用后才 emit）。
// shallowRef：避免 Vue UnwrapRef 深解包 @internationalized/date 类实例（含 #private
// 字段）导致的类型坍塌；本组件总是整体重新赋值 range.value，浅层响应已足够。
const range = shallowRef<DateRange>({ start: undefined, end: undefined })
const startTime = ref('00:00')
const endTime = ref('23:59')

function syncFromModel() {
  range.value = {
    start: parseToCalendarDate(props.modelValue.start),
    end: parseToCalendarDate(props.modelValue.end),
  }
  if (props.withTime) {
    startTime.value = parseToTime(props.modelValue.start) || '00:00'
    endTime.value = parseToTime(props.modelValue.end) || '23:59'
  }
}

watch(() => props.modelValue, syncFromModel, { immediate: true, deep: true })

function calendarDateToOutput(date: DateValue, time: string): string {
  if (!props.withTime)
    return `${date.year}-${pad(date.month)}-${pad(date.day)}`
  const [hh, mm] = (time || '00:00').split(':').map(Number)
  const local = new Date(date.year, date.month - 1, date.day, hh || 0, mm || 0, 0, 0)
  return local.toISOString()
}

const canApply = computed(() => Boolean(range.value.start && range.value.end))

function applyRange() {
  if (!range.value.start || !range.value.end)
    return
  emit('update:modelValue', {
    start: calendarDateToOutput(range.value.start, startTime.value),
    end: calendarDateToOutput(range.value.end, props.withTime ? endTime.value : startTime.value),
  })
  open.value = false
}

function clearRange() {
  range.value = { start: undefined, end: undefined }
}

const triggerLabel = computed(() => {
  const { start, end } = props.modelValue
  if (!start || !end)
    return props.placeholder
  if (props.withTime)
    return `${start.replace('T', ' ').slice(0, 16)} → ${end.replace('T', ' ').slice(0, 16)}`
  return `${start} → ${end}`
})

// 重新打开时把草稿同步回当前 modelValue。
watch(open, (v) => {
  if (v)
    syncFromModel()
})
</script>

<template>
  <Popover v-model:open="open">
    <PopoverTrigger as-child>
      <Button
        variant="outline"
        :class="cn('h-9 gap-1.5 rounded-lg bg-background/90 font-normal', props.triggerClass)"
        aria-label="选择自定义时间范围"
      >
        <span class="icon-[lucide--calendar-range] text-base text-muted-foreground" />
        <span class="tabular-nums">{{ triggerLabel }}</span>
        <span class="icon-[lucide--chevron-down] ml-0.5 text-xs text-muted-foreground" />
      </Button>
    </PopoverTrigger>
    <PopoverContent class="w-auto p-0" :align="props.align">
      <RangeCalendar v-model="range" :number-of-months="props.withTime ? 1 : 2" />

      <div v-if="props.withTime" class="grid grid-cols-2 gap-3 border-t border-border/50 px-3 py-3">
        <div class="space-y-1.5">
          <Label class="text-xs text-muted-foreground">开始时间</Label>
          <Input v-model="startTime" type="time" class="h-8 tabular-nums" aria-label="开始时间" />
        </div>
        <div class="space-y-1.5">
          <Label class="text-xs text-muted-foreground">结束时间</Label>
          <Input v-model="endTime" type="time" class="h-8 tabular-nums" aria-label="结束时间" />
        </div>
      </div>

      <div class="flex items-center justify-between border-t border-border/50 px-3 py-2.5">
        <Button variant="ghost" size="sm" :disabled="!range.start && !range.end" @click="clearRange">
          清除
        </Button>
        <Button size="sm" :disabled="!canApply" @click="applyRange">
          应用
        </Button>
      </div>
    </PopoverContent>
  </Popover>
</template>
