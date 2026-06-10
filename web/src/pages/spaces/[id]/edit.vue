<script setup lang="ts">
/**
 * 编辑空间页（已降级为 redirect-only）
 *
 * 编辑空间已迁入空间详情页内的 EditSpaceModal 弹窗（见
 * `components/space/EditSpaceModal.vue` + `pages/spaces/[id]/index.vue`）。
 * 本文件仅保留 unplugin-vue-router 的 redirect 声明，把旧书签 URL
 * `/spaces/[id]/edit` 重定向到 `/spaces/[id]#edit`
 * （详情页检测到 #edit hash 后自动打开弹窗），确保旧链接不 404。
 */
definePage({
  redirect: (to) => {
    const id = (to.params as { id: string }).id
    return {
      path: `/spaces/${id}`,
      hash: '#edit',
    }
  },
})
</script>

<template>
  <div />
</template>
