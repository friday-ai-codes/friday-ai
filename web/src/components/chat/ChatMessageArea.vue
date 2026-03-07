<script setup lang="ts">
import { Avatar, AvatarFallback } from '~/components/ui/avatar'
import { ScrollArea } from '~/components/ui/scroll-area'
import { Skeleton } from '~/components/ui/skeleton'
const chatStore = useChatStore
// 格式化时间
function formatMessageTime(dateStr: string) {
 return new Date(dateStr).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}
</script>
<template>
 <div class="flex-1 overflow-hidden relative">
 <!-- Loading 骨架屏 -->
 <div v-if="chatStore.messagesLoading" class=" space-y-6">
 <div v-for="i in 3":key="i" class="flex gap-3":class="i % 2 === 0 ? 'flex-row-reverse': ''">
 <Skeleton class=" w-8 rounded-full shrink-0" />
 <div class="space-y-2">
 <Skeleton class=" w-48" />
 <Skeleton class=" w-64 rounded-2xl" />
 </div>
 </div>
 </div>
 <!-- 空对话提示 -->
 <div
 v-else-if="!chatStore.hasConversation || chatStore.messages.length === 0"
 class="h-full flex items-center justify-center"
 >
 <div class="text-center max-w-md px-4">
 <div class="mb-6">
 <div class="inline-flex rounded-2xl bg-gradient-to-br from-primary/20 to-primary/10">
 <span class="icon-[lucide--bot] text-4xl text-primary" />
 </div>
 </div>
 <h2 class="text-xl font-semibold mb-2">
 开始新的对话
 </h2>
 <p class="text-sm text-muted-foreground">
 选择一个项目，输入你的问题
 </p>
 </div>
 </div>
 <!-- 消息列表 -->
 <ScrollArea v-else class="h-full">
 <div class="max-w-3xl mx-auto px-4 py-6 space-y-6">
 <div
 v-for="msg in chatStore.messages":key="msg.id"
 class="flex gap-3":class="msg.role === 'user' ? 'flex-row-reverse': ''"
 >
 <!-- 头像 -->
 <Avatar class=" w-8 shrink-0">
 <AvatarFallback:class="msg.role === 'user'
 ? 'bg-gradient-to-br from-blue-500 to-cyan-400 text-white': 'bg-gradient-to-br from-primary/20 to-primary/10 text-primary'"
 >
 <span v-if="msg.role === 'user'" class="icon-[lucide--user] text-sm" />
 <span v-else class="icon-[lucide--bot] text-sm" />
 </AvatarFallback>
 </Avatar>
 <!-- 气泡 -->
 <div class="max-w-[80%] space-y-1">
 <div
 class="rounded-2xl px-4 py-3":class="msg.role === 'user'
 ? 'bg-gradient-to-r from-blue-500 to-cyan-400 text-white': 'bg-card/80 backdrop-blur-sm border border-border/50'"
 >
 <div v-if="msg.role === 'user'" class="text-sm whitespace-pre-wrap">
 {{ msg.content }}
 </div>
 <div v-else class="text-sm prose prose-sm dark:prose-invert max-w-none">
 {{ msg.content }}
 </div>
 </div>
 <!-- 元信息 -->
 <div
 class="px-1 text-[10px] text-muted-foreground/60":class="msg.role === 'user' ? 'text-right': ''"
 >
 {{ formatMessageTime(msg.created_at) }}
 </div>
 </div>
 </div>
 </div>
 </ScrollArea>
 </div>
</template>
