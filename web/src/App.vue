<script setup lang="ts">
import { useHead } from '@vueuse/head'
import { ModalsContainer } from 'vue-final-modal'
import GlobalConfirmDialog from '~/components/GlobalConfirmDialog.vue'
import { usePermissionSync } from '~/composables/usePermissionSync'
// 设置页面默认标题
useHead({
 title: 'Friday AI',
 meta: [
 { name: 'description', content: 'AI 驱动的敏捷开发自动化系统' },
 ],
})
// 全局权限同步：定期轮询检测权限变更
usePermissionSync
</script>
<template>
 <RouterView />
 <ModalsContainer />
 <GlobalConfirmDialog />
</template>
