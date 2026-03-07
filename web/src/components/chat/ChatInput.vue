<script setup lang="ts">
import { Button } from '~/components/ui/button'
import { Textarea } from '~/components/ui/textarea'
const chatStore = useChatStore
const inputContent = ref('')
async function handleSend {
 const content = inputContent.value.trim
 if (!content || chatStore.isStreaming) return
 // 如果没有当前对话，先创建
 if (!chatStore.currentConversationId) {
 await chatStore.createNewConversation
 if (!chatStore.currentConversationId) return // 创建失败（如未选项目）
 }
 inputContent.value = ''
 await chatStore.sendMessage(content)
}
function handleKeydown(e: KeyboardEvent) {
 // Enter 发送，Shift+Enter 换行
 if (e.key === 'Enter' && !e.shiftKey) {
 e.preventDefault
 handleSend
 }
}
</script>
<template>
 <div class="border-t border-border/40 bg-background/80 backdrop-blur-sm ">
 <div class="max-w-3xl mx-auto">
 <!-- 停止生成按钮 -->
 <div v-if="chatStore.isStreaming" class="flex justify-center mb-2">
 <Button
 variant="destructive"
 size="sm"
 class="gap-1.5"
 @click="chatStore.stopStreaming"
 >
 <span class="icon-[lucide--square] text-xs" />
 停止生成
 </Button>
 </div>
 <div class="flex gap-2 items-end">
 <Textarea
 v-model="inputContent"
 placeholder="输入消息... (Enter 发送，Shift+Enter 换行)"
 class="min-h-[44px] max- resize-none rounded-xl bg-muted/50 border-border/50"
 rows="1":disabled="chatStore.isStreaming"
 @keydown="handleKeydown"
 />
 <Button
 size="icon"
 class="shrink-0 w-11 rounded-xl bg-gradient-to-r from-blue-500 to-cyan-400 hover:from-blue-600 hover:to-cyan-500":disabled="!inputContent.trim || chatStore.isStreaming"
 @click="handleSend"
 >
 <span class="icon-[lucide--send] text-white" />
 </Button>
 </div>
 </div>
 </div>
</template>
