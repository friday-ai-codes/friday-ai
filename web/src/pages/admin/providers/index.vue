<script setup lang="ts">
/**
 * /admin/providers — 系统级 Provider 凭证管理页（Phase）
 *
 * 路由：由 unplugin-vue-router 根据文件系统扫描自动注册 `/admin/providers`。
 * 守卫：definePage({ meta: { requiresAdmin: true } }) —— 与既有 admin 子页（prompts/users/oidc/index）
 * 完全一致，由全局导航守卫拦截非 system_admin（is_superuser=false）用户。
 *
 * 后端纵深防御：即使前端守卫被绕过，ProviderCredentialViewSet 的 Permission 仍会
 * 过滤出空 queryset，页面会走空态路径，不存在信息泄漏（参见 threat_model T-）。
 */
import ProviderSettings from '~/components/providers/ProviderSettings.vue'
definePage({ meta: { requiresAdmin: true } })
</script>
<template>
 <main class="container mx-auto max-w-screen-2xl px-6 py-12">
 <ProviderSettings scope="system" />
 </main>
</template>
