<script setup lang="ts">
/**
 * 空间 Provider 凭证管理页（已降级为 redirect-only）
 *
 * Provider 凭证管理已迁入空间详情页内的 SpaceProvidersModal 弹窗（见
 * `components/space/SpaceProvidersModal.vue` + `pages/spaces/[id]/index.vue`）。
 * 本文件仅保留 unplugin-vue-router 的 redirect 声明，把旧书签 URL
 * `/spaces/[id]/providers` 重定向到 `/spaces/[id]#providers`
 * （详情页检测到 #providers hash 后自动打开弹窗），确保旧链接不 404。
 */
definePage({
  redirect: (to) => {
    const id = (to.params as { id: string }).id
    return {
      path: `/spaces/${id}`,
      hash: '#providers',
    }
  },
})
</script>

<template>
  <div />
</template>
