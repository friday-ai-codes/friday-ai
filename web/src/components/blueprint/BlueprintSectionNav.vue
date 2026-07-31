<script setup lang="ts">
/**
 * 窄屏（`< md`）的段跳转下拉（Phase 115-06，UI-SPEC §5.2）。
 *
 * ## ⛔ 为什么本组件**不**组合 `~/components/layout/AnchorNavLayout.vue`
 *
 * 那个既有件不是「一个导航条」，而是**整个两栏页面布局** —— 它的根是 `<div class="flex gap-8">`，
 * 里面依次是 `<aside class="hidden md:block w-48 shrink-0">`（左栏）与
 * `<div class="flex-1 min-w-0 space-y-6"><slot /></div>`（正文列）。它的滚动函数是私有的，
 * 既不 emit 也不 expose。把它嵌进一个只收 `sections` 的组件里，**正文将无处安放**。
 *
 * ⇒ 分工：`≥ md` 的左栏由**页面**直接使用 `AnchorNavLayout` 承担；本组件只负责 `< md` 那一档，
 * 容器 `md:hidden sticky top-14 z-20`，选中即 emit，滚动由页面统一处理（偏移常量与既有实现一致）。
 *
 * ⭐ **本组件不判断段是否有内容**：十段的容器由页面无条件渲染，`sections` 长度恒为 10；
 * 这里照单全收，⛔ 不做任何增删（增删会让下拉与左栏两份导航不一致）。
 */

import type { NavSection } from '~/components/layout/AnchorNavLayout.vue'
import { useI18n } from 'vue-i18n'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'

defineProps<{
  /** 与页面传给 `AnchorNavLayout` 的**同一个**数组（恒 10 项）。 */
  sections: NavSection[]
  /** 当前段 key；用于回显选中项。 */
  activeId: string
}>()

const emit = defineEmits<{
  navigate: [sectionId: string]
}>()

const { t } = useI18n()

function onChange(value: string | number | bigint | Record<string, any> | null): void {
  if (typeof value === 'string' && value)
    emit('navigate', value)
}
</script>

<template>
  <div
    class="md:hidden sticky top-14 z-20 -mx-1 bg-background/95 px-1 py-2 backdrop-blur"
    data-testid="blueprint-section-nav"
  >
    <Select :model-value="activeId" @update:model-value="onChange">
      <SelectTrigger class="h-9 w-full rounded-lg bg-background/90" :aria-label="t('knowledge.blueprints.viewer.sectionNavLabel')">
        <span class="icon-[lucide--list] mr-1.5 text-base text-muted-foreground" />
        <SelectValue :placeholder="t('knowledge.blueprints.viewer.sectionNavLabel')" />
      </SelectTrigger>
      <SelectContent>
        <SelectItem v-for="section in sections" :key="section.id" :value="section.id">
          {{ section.label }}
        </SelectItem>
      </SelectContent>
    </Select>
  </div>
</template>
