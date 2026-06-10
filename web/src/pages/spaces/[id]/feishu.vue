<script setup lang="ts">
/**
 * 飞书配置页（已降级为 redirect-only）
 *
 * 飞书配置管理已迁入空间详情页内的 FeishuConfigModal 弹窗（见
 * `components/space/FeishuConfigModal.vue` + `pages/spaces/[id]/index.vue`）。
 * 本文件仅保留 unplugin-vue-router 的 redirect 声明，把旧书签 URL
 * `/spaces/[id]/feishu` 重定向到 `/spaces/[id]#feishu`
 * （详情页检测到 #feishu hash 后自动打开弹窗），确保旧链接不 404。
 */
definePage({
  redirect: (to) => {
    const id = (to.params as { id: string }).id
    return {
      path: `/spaces/${id}`,
      hash: '#feishu',
    }
  },
})
</script>

<template>
  <div />
</template>
