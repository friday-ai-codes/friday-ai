<script setup lang="ts">
/**
 * /feedback —— 已并入「消息中心」的「我的反馈」Tab。
 *
 * 保留该路由仅做重定向，兼容历史站内信链接（/feedback?id=<uuid>）：
 * 转跳到 /notifications?tab=feedback&fid=<uuid>。
 */
const route = useRoute()
const router = useRouter()

onMounted(() => {
  const id = route.query.id as string | undefined
  router.replace({
    path: '/notifications',
    query: { tab: 'feedback', ...(id ? { fid: id } : {}) },
  })
})
</script>

<template>
  <div class="flex h-64 items-center justify-center text-sm text-muted-foreground">
    <span class="icon-[lucide--loader-circle] mr-2 animate-spin" />
  </div>
</template>

<route lang="yaml">
meta:
  title: 消息中心
</route>
