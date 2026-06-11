<script setup lang="ts">
/**
 * 空间仓库管理页（已降级为 redirect-only）
 *
 * 仓库关联管理已由空间详情页内嵌的「关联仓库」区块 + 穿梭框弹窗承载
 * （见 `pages/spaces/[id]/index.vue` 的 #repositories section），本页功能重复。
 * 本文件仅保留 unplugin-vue-router 的 redirect 声明，把旧书签 URL
 * `/spaces/[id]/repositories` 重定向到 `/spaces/[id]#repositories`
 * （锚点定位到关联仓库区块），确保旧链接不 404。
 */
definePage({
  redirect: (to) => {
    const id = (to.params as { id: string }).id
    return {
      path: `/spaces/${id}`,
      hash: '#repositories',
    }
  },
})
</script>

<template>
  <div />
</template>
