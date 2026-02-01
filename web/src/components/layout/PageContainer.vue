<script setup lang="ts">
/**
 * 统一的页面容器组件
 * 用于所有列表页面，提供一致的宽度、间距和背景装饰
 */
defineProps<{
 /** 是否显示背景装饰 */
 showBackground?: boolean
}>
</script>
<template>
 <div class="relative max-w-[1400px] mx-auto pb-10 space-y-6">
 <!-- 背景装饰 -->
 <div v-if="showBackground" class="absolute inset-0 -z-10 overflow-hidden pointer-events-none">
 <div class="absolute -top-40 -right-40 w-80 bg-gradient-to-br from-primary/20 to-secondary/40 rounded-full blur-3xl" />
 <div class="absolute top-1/2 -left-40 w-96 bg-gradient-to-tr from-secondary/30 to-primary/10 rounded-full blur-3xl" />
 </div>
 <slot />
 </div>
</template>
