<script setup lang="ts">
/**
 * OIDC 认证配置页（已降级为 redirect-only）
 *
 * OIDC 配置已合并为系统设置页的「OIDC 认证」Tab（见
 * `pages/admin/index.vue` 的 settingsTabs）。
 * 本文件仅保留 unplugin-vue-router 的 redirect 声明，把旧书签 URL
 * `/admin/oidc` 重定向到 `/admin#oidc`
 * （系统设置页检测到 #oidc hash 后自动切换 Tab），确保旧链接不 404。
 */
definePage({
  redirect: {
    path: '/admin',
    hash: '#oidc',
  },
})
</script>

<template>
  <div />
</template>
