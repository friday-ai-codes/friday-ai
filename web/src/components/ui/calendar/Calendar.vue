<script setup lang="ts">
import type { DateValue } from '@internationalized/date'
import type { CalendarRootEmits, CalendarRootProps } from 'reka-ui'
import type { HTMLAttributes } from 'vue'
import { reactiveOmit } from '@vueuse/core'
import {
  CalendarCell,
  CalendarCellTrigger,
  CalendarGrid,
  CalendarGridBody,
  CalendarGridHead,
  CalendarGridRow,
  CalendarHeadCell,
  CalendarHeader,
  CalendarHeading,
  CalendarNext,
  CalendarPrev,
  CalendarRoot,
  useForwardPropsEmits,
} from 'reka-ui'
import { cn } from '~/lib/utils'

/**
 * 单日历选择器（shadcn-vue 风格，底层 reka-ui CalendarRoot）。
 * 样式走主题 token，自动适配明暗与 teal 主题色。
 */
const props = withDefaults(
  defineProps<CalendarRootProps & { class?: HTMLAttributes['class'] }>(),
  {
    weekdayFormat: 'short',
  },
)
const emits = defineEmits<CalendarRootEmits>()

const delegatedProps = reactiveOmit(props, 'class')
const forwarded = useForwardPropsEmits(delegatedProps, emits)

const cellTriggerClass = cn(
  'relative flex size-8 items-center justify-center rounded-md p-0 text-sm font-normal tabular-nums outline-none transition-colors',
  'hover:bg-accent hover:text-accent-foreground focus-visible:ring-2 focus-visible:ring-ring/50',
  'data-[selected]:bg-primary data-[selected]:text-primary-foreground data-[selected]:hover:bg-primary',
  'data-[today]:bg-accent/60 data-[today]:font-medium',
  'data-[outside-view]:text-muted-foreground/40 data-[disabled]:pointer-events-none data-[disabled]:text-muted-foreground/40',
)
</script>

<template>
  <CalendarRoot
    v-slot="{ grid, weekDays }"
    :class="cn('p-3', props.class)"
    v-bind="forwarded"
  >
    <CalendarHeader class="flex items-center justify-between pb-2">
      <CalendarPrev
        class="inline-flex size-7 items-center justify-center rounded-md border border-border/60 bg-background/80 text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
      >
        <span class="icon-[lucide--chevron-left] text-base" />
      </CalendarPrev>
      <CalendarHeading class="text-sm font-medium" />
      <CalendarNext
        class="inline-flex size-7 items-center justify-center rounded-md border border-border/60 bg-background/80 text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
      >
        <span class="icon-[lucide--chevron-right] text-base" />
      </CalendarNext>
    </CalendarHeader>

    <div class="flex flex-col gap-y-4">
      <CalendarGrid
        v-for="month in grid"
        :key="month.value.toString()"
        class="w-full border-collapse select-none space-y-1"
      >
        <CalendarGridHead>
          <CalendarGridRow class="flex">
            <CalendarHeadCell
              v-for="day in weekDays"
              :key="day"
              class="w-8 rounded-md text-[0.7rem] font-normal text-muted-foreground"
            >
              {{ day }}
            </CalendarHeadCell>
          </CalendarGridRow>
        </CalendarGridHead>
        <CalendarGridBody class="grid">
          <CalendarGridRow
            v-for="(weekDates, index) in month.rows"
            :key="`weekDate-${index}`"
            class="mt-0.5 flex w-full"
          >
            <CalendarCell
              v-for="weekDate in weekDates"
              :key="(weekDate as DateValue).toString()"
              :date="weekDate"
              class="relative size-8 p-0 text-center text-sm"
            >
              <CalendarCellTrigger :day="weekDate" :month="month.value" :class="cellTriggerClass" />
            </CalendarCell>
          </CalendarGridRow>
        </CalendarGridBody>
      </CalendarGrid>
    </div>
  </CalendarRoot>
</template>
