<script setup lang="ts">
/**
 * 旧版执行详情页重定向
 *
 * 所有执行查看已统一到 DAG 视图 (/executions/[id])。
 * 保留此文件确保旧书签和分享链接永久有效。
 */
import { onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

onMounted(() => {
  const id = (route.params as { id: string }).id
  router.replace(`/executions/${id}`)
})
</script>

<template>
  <div />
</template>
