<script setup lang="ts">
import type { DateValue } from '@internationalized/date'
import type { RangeCalendarRootEmits, RangeCalendarRootProps } from 'reka-ui'
import type { HTMLAttributes } from 'vue'
import { reactiveOmit } from '@vueuse/core'
import {
  RangeCalendarCell,
  RangeCalendarCellTrigger,
  RangeCalendarGrid,
  RangeCalendarGridBody,
  RangeCalendarGridHead,
  RangeCalendarGridRow,
  RangeCalendarHeadCell,
  RangeCalendarHeader,
  RangeCalendarHeading,
  RangeCalendarNext,
  RangeCalendarPrev,
  RangeCalendarRoot,
  useForwardPropsEmits,
} from 'reka-ui'
import { cn } from '~/lib/utils'

/**
 * 范围日历选择器（shadcn-vue 风格，底层 reka-ui RangeCalendarRoot）。
 * 选中区间高亮、端点用主题 primary 色，自动适配明暗主题。
 */
const props = withDefaults(
  defineProps<RangeCalendarRootProps & { class?: HTMLAttributes['class'] }>(),
  {
    weekdayFormat: 'short',
  },
)
const emits = defineEmits<RangeCalendarRootEmits>()

const delegatedProps = reactiveOmit(props, 'class')
const forwarded = useForwardPropsEmits(delegatedProps, emits)

const cellTriggerClass = cn(
  'relative flex size-8 items-center justify-center rounded-md p-0 text-sm font-normal tabular-nums outline-none transition-colors',
  'hover:bg-accent hover:text-accent-foreground focus-visible:ring-2 focus-visible:ring-ring/50',
  'data-[selected]:bg-primary data-[selected]:text-primary-foreground data-[selected]:hover:bg-primary data-[selected]:hover:text-primary-foreground',
  'data-[today]:font-medium',
  'data-[outside-view]:text-muted-foreground/40 data-[disabled]:pointer-events-none data-[disabled]:text-muted-foreground/40',
)
// 区间内（非端点）单元格：浅色填充，方角以拼接成连续色带。
const cellClass = cn(
  'relative size-8 p-0 text-center text-sm',
  '[&:has([data-selected])]:bg-accent first:[&:has([data-selected])]:rounded-l-md last:[&:has([data-selected])]:rounded-r-md',
  '[&:has([data-selection-start])]:rounded-l-md [&:has([data-selection-end])]:rounded-r-md',
)
</script>

<template>
  <RangeCalendarRoot
    v-slot="{ grid, weekDays }"
    :class="cn('p-3', props.class)"
    v-bind="forwarded"
  >
    <RangeCalendarHeader class="flex items-center justify-between pb-2">
      <RangeCalendarPrev
        class="inline-flex size-7 items-center justify-center rounded-md border border-border/60 bg-background/80 text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
      >
        <span class="icon-[lucide--chevron-left] text-base" />
      </RangeCalendarPrev>
      <RangeCalendarHeading class="text-sm font-medium" />
      <RangeCalendarNext
        class="inline-flex size-7 items-center justify-center rounded-md border border-border/60 bg-background/80 text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
      >
        <span class="icon-[lucide--chevron-right] text-base" />
      </RangeCalendarNext>
    </RangeCalendarHeader>

    <div class="flex flex-col gap-y-4">
      <RangeCalendarGrid
        v-for="month in grid"
        :key="month.value.toString()"
        class="w-full border-collapse select-none space-y-1"
      >
        <RangeCalendarGridHead>
          <RangeCalendarGridRow class="flex">
            <RangeCalendarHeadCell
              v-for="day in weekDays"
              :key="day"
              class="w-8 rounded-md text-[0.7rem] font-normal text-muted-foreground"
            >
              {{ day }}
            </RangeCalendarHeadCell>
          </RangeCalendarGridRow>
        </RangeCalendarGridHead>
        <RangeCalendarGridBody class="grid">
          <RangeCalendarGridRow
            v-for="(weekDates, index) in month.rows"
            :key="`weekDate-${index}`"
            class="mt-0.5 flex w-full"
          >
            <RangeCalendarCell
              v-for="weekDate in weekDates"
              :key="(weekDate as DateValue).toString()"
              :date="weekDate"
              :class="cellClass"
            >
              <RangeCalendarCellTrigger :day="weekDate" :month="month.value" :class="cellTriggerClass" />
            </RangeCalendarCell>
          </RangeCalendarGridRow>
        </RangeCalendarGridBody>
      </RangeCalendarGrid>
    </div>
  </RangeCalendarRoot>
</template>
