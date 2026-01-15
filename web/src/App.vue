<script setup lang="ts">
import { useHead } from '@vueuse/head'
// 设置页面默认标题
useHead({
 title: 'Friday AI',
 meta: [
 { name: 'description', content: 'AI 驱动的敏捷开发自动化系统' },
 ],
})
</script>
<template>
 <RouterView />
</template>
