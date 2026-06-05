<script setup lang="ts">
/**
 * 统一的页面容器组件
 * 用于所有列表页面，提供一致的宽度、间距和背景装饰
 */
defineProps<{
  /** 是否显示背景装饰 */
  showBackground?: boolean
}>()
</script>

<template>
  <div class="relative max-w-[1400px] mx-auto pb-10 space-y-6">
    <!-- 背景装饰 -->
    <div v-if="showBackground" class="absolute inset-0 -z-10 overflow-hidden pointer-events-none">
      <div class="absolute inset-x-0 top-0 h-48 bg-linear-to-b from-primary/6 to-transparent" />
    </div>

    <slot />
  </div>
</template>
