<script setup lang="ts">
import { useAppMode } from '~/composables/useAppMode'
defineProps<{
 collapsed?: boolean
}>
const { mode, setMode } = useAppMode
</script>
<template>
 <!-- 收缩态：竖排图标 -->
 <div v-if="collapsed" class="flex flex-col gap-1">
 <button
 class="flex items-center justify-center w-full rounded-lg transition-all duration-200":class="mode === 'friday'
 ? 'bg-primary/10 text-primary shadow-sm': 'text-muted-foreground hover:text-foreground hover:bg-muted/60'"
 @click="setMode('friday')"
 >
 <span class="icon-[lucide--layout-dashboard] text-lg" />
 </button>
 <button
 class="flex items-center justify-center w-full rounded-lg transition-all duration-200":class="mode === 'chat'
 ? 'bg-primary/10 text-primary shadow-sm': 'text-muted-foreground hover:text-foreground hover:bg-muted/60'"
 @click="setMode('chat')"
 >
 <span class="icon-[lucide--message-square] text-lg" />
 </button>
 </div>
 <!-- 展开态：横排 pill toggle -->
 <div v-else class="flex items-center bg-muted/50 rounded-lg border border-border/40">
 <button
 class="flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all duration-200":class="mode === 'friday'
 ? 'bg-background text-foreground shadow-sm': 'text-muted-foreground hover:text-foreground'"
 @click="setMode('friday')"
 >
 <span class="icon-[lucide--layout-dashboard]" />
 工作台
 </button>
 <button
 class="flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all duration-200":class="mode === 'chat'
 ? 'bg-background text-foreground shadow-sm': 'text-muted-foreground hover:text-foreground'"
 @click="setMode('chat')"
 >
 <span class="icon-[lucide--message-square]" />
 AI 对话
 </button>
 </div>
</template>
