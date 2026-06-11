<script setup lang="ts">
/**
 * 空间成员管理页（已降级为 redirect-only）
 *
 * 成员管理已迁入空间详情页内的 SpaceMembersModal 弹窗（见
 * `components/space/SpaceMembersModal.vue` + `pages/spaces/[id]/index.vue`）。
 * 本文件仅保留 unplugin-vue-router 的 redirect 声明，把旧书签 URL
 * `/spaces/[id]/members` 重定向到 `/spaces/[id]#members`
 * （详情页检测到 #members hash 后自动打开弹窗），确保旧链接不 404。
 */
definePage({
  redirect: (to) => {
    const id = (to.params as { id: string }).id
    return {
      path: `/spaces/${id}`,
      hash: '#members',
    }
  },
})
</script>

<template>
  <div />
</template>
