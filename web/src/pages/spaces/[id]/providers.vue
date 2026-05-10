<script setup lang="ts">
/**
 * /spaces/:id/providers — 空间级 Provider 凭证管理页（Phase / / ）
 *
 * 路由：由 unplugin-vue-router 文件系统扫描自动注册 `/spaces/:id/providers`
 *
 * 职责：
 * - useRoute 读取:id 参数作为 spaceId
 * - 复用 Plan 交付的 scope-aware ProviderSettings 容器（scope='space' + spaceId）
 * - 后端纵深防御（Plan Permission + queryset 双层）才是权限权威；
 * 前端仅 UX 层渲染，非空间成员 API 会返空列表/404（T- / T-）
 *
 * 与 /admin/providers 的差异：scope 由 'system' 切到 'space'，
 * ProviderSettings 内部按 scope computed PageHeader 标题 / 空态图标 / 空态文案 / CTA。
 */
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import ProviderSettings from '~/components/providers/ProviderSettings.vue'
const route = useRoute('/spaces/[id]/providers')
// route.params.id 类型是 string，unplugin-vue-router 的 typed-route 已锁死。
// 这里再做一次运行时正规化兜底，防御 memoryHistory 下可能的 string 形态。
const spaceId = computed<string>( => {
 const id = route.params.id as string | string | undefined
 if (Array.isArray(id))
 return id[0] ?? ''
 return id ?? ''
})
</script>
<template>
 <main class="container mx-auto max-w-screen-2xl px-6 py-12">
 <ProviderSettings scope="project":space-id="spaceId" />
 </main>
</template>
