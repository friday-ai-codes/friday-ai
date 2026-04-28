<script setup lang="ts">
defineProps<{
 collapsed?: boolean
}>
const router = useRouter
const route = useRoute
function switchToChat {
 router.push('/chat')
}
function switchToFriday {
 if (route.path === '/chat') {
 router.push('/')
 }
}
</script>
<template>
 <!-- 收缩态：竖排图标 -->
 <div v-if="collapsed" class="flex flex-col gap-1">
 <button
 class="flex items-center justify-center w-full rounded-lg transition-all duration-200":class="route.path !== '/chat' ? 'bg-primary/10 text-primary shadow-sm': 'text-muted-foreground hover:text-foreground hover:bg-muted/60'"
 @click="switchToFriday"
 >
 <span class="icon-[lucide--layout-dashboard] text-lg" />
 </button>
 <button
 class="flex items-center justify-center w-full rounded-lg transition-all duration-200":class="route.path === '/chat' ? 'bg-primary/10 text-primary shadow-sm': 'text-muted-foreground hover:text-foreground hover:bg-muted/60'"
 @click="switchToChat"
 >
 <span class="icon-[lucide--message-square] text-lg" />
 </button>
 </div>
 <!-- 展开态：横排 pill toggle -->
 <div v-else class="flex items-center bg-muted/50 rounded-lg border border-border/40">
 <button
 class="flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all duration-200":class="route.path !== '/chat' ? 'bg-background text-foreground shadow-sm': 'text-muted-foreground hover:text-foreground'"
 @click="switchToFriday"
 >
 <span class="icon-[lucide--layout-dashboard]" />
 工作台
 </button>
 <button
 class="flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all duration-200":class="route.path === '/chat' ? 'bg-background text-foreground shadow-sm': 'text-muted-foreground hover:text-foreground'"
 @click="switchToChat"
 >
 <span class="icon-[lucide--message-square]" />
 AI 对话
 </button>
 </div>
</template>
