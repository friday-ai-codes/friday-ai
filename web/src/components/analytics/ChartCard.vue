<script setup lang="ts">
/**
 * Analytics 图表卡片：统一的 shadcn Card 外壳。
 * 头部 = 图标芯片 + 标题 + 描述（可选）+ 右侧扩展插槽，内容区交给调用方。
 */
import { Card, CardContent, CardHeader, CardTitle } from '~/components/ui/card'

defineProps<{
  title: string
  description?: string
  icon?: string
  /** 图标芯片配色，如 'bg-primary/10 text-primary' */
  iconClass?: string
}>()

defineSlots<{
  default: () => unknown
  actions: () => unknown
}>()
</script>

<template>
  <Card class="overflow-hidden rounded-xl border-border/70 shadow-[0_1px_3px_rgba(15,23,42,0.06)] transition-all duration-200 hover:shadow-md hover:border-primary/25">
    <CardHeader class="flex-row items-center gap-3 space-y-0 border-b border-border/40 bg-muted/20 p-4">
      <div
        class="flex size-9 shrink-0 items-center justify-center rounded-lg"
        :class="iconClass || 'bg-primary/10 text-primary'"
      >
        <span class="text-base" :class="`icon-[${icon || 'lucide--bar-chart-3'}]`" />
      </div>
      <div class="min-w-0 flex-1">
        <CardTitle class="text-sm font-semibold leading-5">
          {{ title }}
        </CardTitle>
        <p v-if="description" class="mt-0.5 truncate text-xs text-muted-foreground">
          {{ description }}
        </p>
      </div>
      <slot name="actions" />
    </CardHeader>
    <CardContent class="p-4">
      <slot />
    </CardContent>
  </Card>
</template>
