<script setup lang="ts">
/**
 * 触发日志详情页（已降级为 redirect-only）
 *
 * 日志详情已统一为日志列表页内的 TriggerLogDetailModal 弹窗（见
 * `components/logs/TriggerLogDetailModal.vue` + `pages/logs/index.vue`）。
 * 本文件仅保留 unplugin-vue-router 的 redirect 声明，把旧书签 URL
 * `/logs/triggers/[id]` 重定向到 `/logs?detail=[id]`
 * （列表页检测到 detail 查询参数后自动打开弹窗），确保旧链接不 404。
 */
definePage({
  redirect: (to) => {
    const id = (to.params as { id: string }).id
    return {
      path: '/logs',
      query: { detail: id },
    }
  },
})
</script>

<template>
  <div />
</template>
