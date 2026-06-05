<script setup lang="ts">
/**
 * 仓库凭证配置页（已降级为 redirect-only，）
 *
 * 凭证管理已迁入详情页内的 CredentialModal 弹窗（见
 * `components/repository/CredentialModal.vue` + `pages/repositories/[id]/index.vue`）。
 * 本文件仅保留 unplugin-vue-router 的 redirect 声明，把旧书签 URL
 * `/repositories/[id]/credential` 重定向到 `/repositories/[id]/#credential`
 * （保留 id 参数 + 凭证段 hash 锚点），确保旧链接不 404。
 */
definePage({
  redirect: (to) => {
    const id = (to.params as { id: string }).id
    return {
      path: `/repositories/${id}`,
      hash: '#credential',
    }
  },
})
</script>

<template>
  <div />
</template>
