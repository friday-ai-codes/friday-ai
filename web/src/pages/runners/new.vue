<script setup lang="ts">
/**
 * 新建 Runner 页（已降级为 redirect-only）
 *
 * 创建 Runner 已迁入 Runner 列表页内的 CreateRunnerModal 弹窗（见
 * `components/runners/CreateRunnerModal.vue` + `pages/runners/index.vue`）。
 * 本文件仅保留 unplugin-vue-router 的 redirect 声明，把旧书签 URL
 * `/runners/new` 重定向到 `/runners#new`
 * （列表页检测到 #new hash 后自动打开弹窗），确保旧链接不 404。
 */
definePage({
  redirect: {
    path: '/runners',
    hash: '#new',
  },
})
</script>

<template>
  <div />
</template>
