<script setup lang="ts">
import { Button } from '~/components/ui/button'
import { ScrollArea } from '~/components/ui/scroll-area'
const chatStore = useChatStore
const router = useRouter
function handleNewConversation {
 chatStore.createNewConversation
}
function handleSelectConversation(id: string) {
 chatStore.selectConversation(id)
}
function handleDeleteConversation(id: string) {
 chatStore.removeConversation(id)
}
function handleGoHome {
 router.push('/')
}
// 格式化时间
function formatTime(dateStr: string) {
 const date = new Date(dateStr)
 const now = new Date
 const diff = now.getTime - date.getTime
 const days = Math.floor(diff / (1000 * 60 * 60 * 24))
 if (days === 0) return '今天'
 if (days === 1) return '昨天'
 if (days < 7) return `${days}天前`
 return date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}
</script>
<template>
 <aside
 class="border-r border-border/40 bg-background/80 backdrop-blur-xl transition-all duration-300 flex flex-col":class="chatStore.sidebarCollapsed ? 'w-16': 'w-72'"
 >
 <!-- 顶部操作区 -->
 <div class=" flex items-center gap-2 border-b border-border/40">
 <Button
 variant="ghost"
 size="icon"
 class="shrink-0"
 @click="chatStore.toggleSidebar"
 >
 <span v-if="!chatStore.sidebarCollapsed" class="icon-[lucide--panel-left-close] text-lg" />
 <span v-else class="icon-[lucide--panel-left-open] text-lg" />
 </Button>
 <template v-if="!chatStore.sidebarCollapsed">
 <Button
 variant="ghost"
 size="icon"
 class="shrink-0"
 @click="handleGoHome"
 >
 <span class="icon-[lucide--home] text-lg" />
 </Button>
 <div class="flex-1" />
 <Button
 variant="outline"
 size="sm"
 class="gap-1.5"
 @click="handleNewConversation"
 >
 <span class="icon-[lucide--plus] text-sm" />
 新对话
 </Button>
 </template>
 </div>
 <!-- 折叠态：仅显示图标按钮 -->
 <template v-if="chatStore.sidebarCollapsed">
 <div class=" flex flex-col items-center gap-2">
 <Button
 variant="ghost"
 size="icon"
 @click="handleGoHome"
 >
 <span class="icon-[lucide--home] text-lg" />
 </Button>
 <Button
 variant="ghost"
 size="icon"
 @click="handleNewConversation"
 >
 <span class="icon-[lucide--plus] text-lg" />
 </Button>
 </div>
 </template>
 <!-- 展开态：对话列表 -->
 <ScrollArea v-if="!chatStore.sidebarCollapsed" class="flex-1">
 <div class=" space-y-1">
 <!-- Loading -->
 <div v-if="chatStore.loading" class=" text-center text-sm text-muted-foreground">
 加载中...
 </div>
 <!-- 空状态 -->
 <div
 v-else-if="chatStore.conversations.length === 0"
 class=" text-center text-sm text-muted-foreground"
 >
 <span class="icon-[lucide--message-square-plus] text-2xl block mb-2 opacity-50" />
 暂无对话，点击上方新建
 </div>
 <!-- 对话列表项 -->
 <button
 v-for="conv in chatStore.conversations":key="conv.id"
 class="group w-full text-left px-3 py-2.5 rounded-xl transition-all duration-200 flex items-center gap-2":class="[
 chatStore.currentConversationId === conv.id
 ? 'bg-gradient-to-r from-primary/10 to-primary/5 text-foreground': 'text-muted-foreground hover:text-foreground hover:bg-muted/50',
 ]"
 @click="handleSelectConversation(conv.id)"
 >
 <span class="icon-[lucide--message-square] text-base shrink-0" />
 <div class="flex-1 min-w-0">
 <p class="text-sm font-medium truncate">
 {{ conv.title }}
 </p>
 <p class="text-xs opacity-60">
 {{ formatTime(conv.updated_at) }}
 </p>
 </div>
 <Button
 variant="ghost"
 size="icon"
 class=" w-6 opacity-0 group-hover:opacity-100 shrink-0"
 @click.stop="handleDeleteConversation(conv.id)"
 >
 <span class="icon-[lucide--trash-2] text-xs text-destructive" />
 </Button>
 </button>
 </div>
 </ScrollArea>
 </aside>
</template>
