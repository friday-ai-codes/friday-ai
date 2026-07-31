<script setup lang="ts">
/**
 * 筛选区域容器（通用件）。
 *
 * **契约来源：`web/DESIGN.md:198-211`** —— 那份设计文档早就把它的 API 写死了
 * （`props: { showClear?: boolean }` / `emits: ['clear']` / 默认 slot 承载筛选控件），
 * 但 `web/src/` 下一直**零实现**。本相位按既有契约把它补上，属新建而非改造。
 *
 * ⛔ **通用件不得引入任何业务专属 prop**：一旦为某一个页面加一个专用字段，下一个页面就复用
 * 不了它，DESIGN 里那份契约也就白写了。筛选控件本身（输入框 / 下拉 / chip）由调用方通过
 * 默认 slot 传进来，本组件只负责容器排版与右侧的清除按钮。
 */

import { useI18n } from 'vue-i18n'
import { Button } from '~/components/ui/button'

withDefaults(defineProps<{
  /** 是否有任一筛选生效 —— 为真时右侧渲染清除按钮。 */
  showClear?: boolean
}>(), {
  showClear: false,
})

const emit = defineEmits<{
  clear: []
}>()

const { t } = useI18n()
</script>

<template>
  <div class="card flex flex-wrap items-center gap-3 p-4" data-testid="filter-bar">
    <slot />

    <Button
      v-if="showClear"
      variant="ghost"
      size="sm"
      class="ml-auto"
      data-testid="filter-bar-clear"
      @click="emit('clear')"
    >
      <span class="icon-[lucide--x] mr-1" aria-hidden="true" />
      {{ t('common.clearFilters') }}
    </Button>
  </div>
</template>
