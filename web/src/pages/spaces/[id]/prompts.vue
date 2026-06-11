<script setup lang="ts">
/**
 * 空间 Prompt 覆盖页（已降级为 redirect-only）
 *
 * Prompt 覆盖管理已迁入空间详情页内的 SpacePromptsModal 弹窗（见
 * `components/space/SpacePromptsModal.vue` + `pages/spaces/[id]/index.vue`）。
 * 本文件仅保留 unplugin-vue-router 的 redirect 声明，把旧书签 URL
 * `/spaces/[id]/prompts` 重定向到 `/spaces/[id]#prompts`
 * （详情页检测到 #prompts hash 后自动打开弹窗），确保旧链接不 404。
 */
definePage({
  redirect: (to) => {
    const id = (to.params as { id: string }).id
    return {
      path: `/spaces/${id}`,
      hash: '#prompts',
    }
  },
})
</script>

<template>
  <div />
</template>
