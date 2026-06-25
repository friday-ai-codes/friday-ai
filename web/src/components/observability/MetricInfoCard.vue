<script setup lang="ts">
/**
 * 通用信息卡（UI-SPEC §2.3）：图标芯片 + 标题 + 大字主值（可着色）+ 分位/分列副行 + 副注。
 *
 * 纯展示组件——所有数据由父页（index.vue）取数后传入，6 张信息卡（请求汇总 / SLA /
 * 请求错误 / 请求时长 / TTFT / 上游错误）复用同一形状。色彩不作唯一信号：tone 仅作大字
 * 着色，语义由 mainLabel/subItems 文案承载（对齐 UI-SPEC §0.3/§0.5 a11y）。
 */
import { computed } from 'vue'
import { Card, CardContent } from '~/components/ui/card'
import { Skeleton } from '~/components/ui/skeleton'

interface SubItem {
  label: string
  value: string
  /** 可选着色 class（如阈值变色），默认 muted。 */
  class?: string
}

const props = withDefaults(defineProps<{
  title: string
  /** lucide 图标名（不含 `icon-[]` 包裹），如 'lucide--activity'。 */
  icon: string
  /** 大字主值字符串（已格式化）。 */
  mainValue: string
  /** 大字下方副标，如 'P95' / '可用率'。 */
  mainLabel?: string
  /** 分位/分列副行。 */
  subItems?: SubItem[]
  /** 副注（极小灰字），如 SLA 口径说明。 */
  footnote?: string
  /** 大字着色语义档（default/success/warning/danger）。 */
  tone?: 'default' | 'success' | 'warning' | 'danger'
  /** 图标芯片配色。 */
  iconClass?: string
  loading?: boolean
}>(), {
  tone: 'default',
  iconClass: 'bg-primary/10 text-primary',
  loading: false,
})

const toneClass = computed(() => {
  switch (props.tone) {
    case 'success':
      return 'text-emerald-500'
    case 'warning':
      return 'text-amber-500'
    case 'danger':
      return 'text-rose-500'
    default:
      return 'text-foreground'
  }
})
</script>

<template>
  <Card
    class="overflow-hidden rounded-xl border-border/70 shadow-[0_1px_3px_rgba(15,23,42,0.05)] transition-all duration-200 hover:border-primary/25 hover:shadow-md"
  >
    <CardContent class="space-y-3 p-4">
      <div class="flex items-center gap-2.5">
        <div
          class="flex size-8 shrink-0 items-center justify-center rounded-lg"
          :class="iconClass"
        >
          <span class="text-base" :class="`icon-[${icon}]`" />
        </div>
        <span class="truncate text-sm font-medium text-muted-foreground">{{ title }}</span>
      </div>

      <template v-if="loading">
        <Skeleton class="h-8 w-24" />
        <Skeleton class="h-12 w-full" />
      </template>

      <template v-else>
        <div class="flex items-baseline gap-1.5">
          <span class="text-2xl font-bold tabular-nums sm:text-3xl" :class="toneClass">
            {{ mainValue }}
          </span>
          <span v-if="mainLabel" class="text-xs font-medium text-muted-foreground">
            {{ mainLabel }}
          </span>
        </div>

        <dl
          v-if="subItems?.length"
          class="grid grid-cols-2 gap-x-3 gap-y-1.5 border-t border-border/40 pt-2.5"
        >
          <div
            v-for="item in subItems"
            :key="item.label"
            class="flex items-center justify-between gap-2"
          >
            <dt class="text-[11px] text-muted-foreground">
              {{ item.label }}
            </dt>
            <dd class="text-xs font-semibold tabular-nums" :class="item.class || 'text-foreground/90'">
              {{ item.value }}
            </dd>
          </div>
        </dl>

        <p v-if="footnote" class="text-[11px] leading-tight text-muted-foreground/70">
          {{ footnote }}
        </p>
      </template>
    </CardContent>
  </Card>
</template>
