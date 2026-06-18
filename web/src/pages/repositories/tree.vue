<script setup lang="ts">
import { useRouter } from 'vue-router'

// 知识树已迁入「知识」页签（/knowledge?tab=tree）。
// 旧路由保留为重定向，避免历史书签失效。
const router = useRouter()
router.replace({ path: '/knowledge', query: { tab: 'tree' } })
</script>

<template>
  <div />
</template>
