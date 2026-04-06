<route lang="yaml">
meta:
 layout: false
</route>
<script setup lang="ts">
/**
 * /chat 路由：自动切换到 Chat 模式并跳转到首页。
 * Chat 界面已集成在 default layout 中，不再需要独立页面。
 */
import { useAppMode } from '~/composables/useAppMode'
const { setMode } = useAppMode
const router = useRouter
const route = useRoute
onMounted( => {
 setMode('chat')
 const convId = route.query.conversation as string | undefined
 if (convId) {
 router.replace(`/?conversation=${convId}`)
 }
 else {
 router.replace('/')
 }
})
</script>
<template>
 <div class="h-screen flex items-center justify-center bg-background">
 <span class="icon-[lucide--loader-circle] text-2xl text-primary animate-spin" />
 </div>
</template>
