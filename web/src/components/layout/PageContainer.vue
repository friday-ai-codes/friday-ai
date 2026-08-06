<script setup lang="ts">
/**
 * 统一的页面容器组件
 * 用于所有列表页面，提供一致的宽度、间距和背景装饰
 */
defineProps<{
  /** 是否显示背景装饰 */
  showBackground?: boolean
  /**
   * 放宽容器上限（1400 → 1760）：供「左导航 + 正文 + 批注栏」三栏工作台类页面
   * （如蓝图查看器）使用——固定开销（左右栏）吃掉 ~560px 后，1400 封顶会把
   * 正文读写区压到 700px 以下。列表页保持默认，⛔ 不要全局放宽。
   */
  fluid?: boolean
}>()
</script>

<template>
  <div class="relative mx-auto pb-10 space-y-6" :class="fluid ? 'max-w-440' : 'max-w-350'">
    <!-- 背景装饰 -->
    <div v-if="showBackground" class="absolute inset-0 -z-10 overflow-hidden pointer-events-none">
      <div class="absolute inset-x-0 top-0 h-48 bg-linear-to-b from-primary/6 to-transparent" />
    </div>

    <slot />
  </div>
</template>
