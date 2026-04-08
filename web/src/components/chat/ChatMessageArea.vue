<script setup lang="ts">
import type { ConversationMessage, ExportToFeishuResponse } from '~/types/chat'
import { Button } from '~/components/ui/button'
import { Skeleton } from '~/components/ui/skeleton'
import ChatMessageBubble from './ChatMessageBubble.vue'
import ChatStatusBar from './ChatStatusBar.vue'
import ChatWelcome from './ChatWelcome.vue'
import ExportConfirmDialog from './ExportConfirmDialog.vue'
import CodingErrorCard from './CodingErrorCard.vue'
import CodingProgressCard from './CodingProgressCard.vue'
import CodingResultCard from './CodingResultCard.vue'
import ExportSuccessCard from './ExportSuccessCard.vue'
import MessageSelectBar from './MessageSelectBar.vue'
const chatStore = useChatStore
const scrollContainer = ref<HTMLElement | null>(null)
const { arrivedState } = useScroll(scrollContainer, { offset: { bottom: 50 } })
const isAtBottom = computed( => arrivedState.bottom)
const showScrollToBottom = computed( => !isAtBottom.value && chatStore.messages.length > 0)
function scrollToBottom(behavior: ScrollBehavior = 'smooth') {
 if (scrollContainer.value) {
 scrollContainer.value.scrollTo({ top: scrollContainer.value.scrollHeight, behavior })
 }
}
watch(
 => [chatStore.messages.length, chatStore.streamingContent, chatStore.deepAnalysisLogs.length, chatStore.error, chatStore.currentPhase, chatStore.codingProgress, chatStore.codingResult, chatStore.codingError],
 => {
 if (isAtBottom.value || chatStore.isStreaming || chatStore.error)
 nextTick( => scrollToBottom(chatStore.isStreaming ? 'instant': 'smooth'))
 },
)
// 从消息历史 metadata 恢复编码结果（刷新页面后 codingResult/codingError 为空）
const historyCodingResult = computed( => {
 for (let i = chatStore.messages.length - 1; i >= 0; i--) {
 const meta = chatStore.messages[i].metadata as Record<string, unknown> | undefined
 if (meta?.codingResult) {
 return meta.codingResult as { sessionId: string; prUrl: string; branchName: string; modifiedFilesCount: number }
 }
 }
 return null
})
const historyCodingError = computed( => {
 for (let i = chatStore.messages.length - 1; i >= 0; i--) {
 const meta = chatStore.messages[i].metadata as Record<string, unknown> | undefined
 if (meta?.codingError) {
 return meta.codingError as { sessionId: string; errorMessage: string }
 }
 }
 return null
})
watch(
 => chatStore.currentConversationId,
 => nextTick( => scrollToBottom('instant')),
)
// ============================================================================
// 导出到飞书 (Phase)
// ============================================================================
const showExportDialog = ref(false)
const exportDefaultTitle = ref('')
const exportSelectedIds = ref<string>
type FeishuExportHistoryItem = ExportToFeishuResponse & { exportedAt: string }
const currentTitle = computed( => {
 const conv = chatStore.conversations.find(c => c.id === chatStore.currentConversationId)
 return conv?.title || '新对话'
})
function generateDefaultTitle {
 const date = new Date.toISOString.slice(0, 10)
 return `${currentTitle.value} - ${date}`
}
/** 单条快速导出 (per ) */
function handleExportSingle(messageId: string) {
 exportSelectedIds.value = [messageId]
 exportDefaultTitle.value = generateDefaultTitle
 showExportDialog.value = true
}
/** 多选导出确认 */
function handleMultiExport {
 exportSelectedIds.value = [...chatStore.selectedMessageIds]
 exportDefaultTitle.value = generateDefaultTitle
 showExportDialog.value = true
}
function readExportHistory(msg: ConversationMessage): FeishuExportHistoryItem {
 const metadata = msg.metadata
 if (!metadata || typeof metadata !== 'object')
 return
 const raw = (metadata as Record<string, unknown>).feishu_exports
 if (!Array.isArray(raw))
 return
 return raw.flatMap((item) => {
 if (!item || typeof item !== 'object')
 return
 const record = item as Record<string, unknown>
 const documentId = typeof record.document_id === 'string' ? record.document_id: ''
 const url = typeof record.url === 'string' ? record.url: ''
 const title = typeof record.title === 'string' ? record.title: ''
 const exportedAt = typeof record.exported_at === 'string'
 ? record.exported_at: new Date.toISOString
 if (!documentId || !url || !title)
 return
 return [{
 document_id: documentId,
 url,
 title,
 exportedAt,
 exported_at: exportedAt,
 }]
 })
}
const exportResults = computed<FeishuExportHistoryItem>( => {
 const deduped = new Map<string, FeishuExportHistoryItem>
 for (const msg of chatStore.messages) {
 for (const item of readExportHistory(msg)) {
 deduped.set(item.document_id, item)
 }
 }
 return [...deduped.values].sort((a, b) => a.exportedAt.localeCompare(b.exportedAt))
})
/** 导出成功回调 (per ) */
function handleExportSuccess(result: ExportToFeishuResponse) {
 const exportedAt = result.exported_at || new Date.toISOString
 const target = [...chatStore.messages]
 .filter(msg => exportSelectedIds.value.includes(msg.id) && msg.role === 'assistant')
 .at(-1)
 if (target) {
 const metadata = (target.metadata && typeof target.metadata === 'object')
 ? { ...target.metadata }: {}
 const existing = Array.isArray((metadata as Record<string, unknown>).feishu_exports)
 ? [...((metadata as Record<string, unknown>).feishu_exports as Array<Record<string, unknown>>)]:
 if (!existing.some(item => item?.document_id === result.document_id)) {
 existing.push({
 document_id: result.document_id,
 url: result.url,
 title: result.title,
 exported_at: exportedAt,
 });(metadata as Record<string, unknown>).feishu_exports = existing
 target.metadata = metadata
 }
 }
 chatStore.exitExportSelectMode
}
</script>
<template>
 <div class="absolute inset-0 overflow-hidden">
 <!-- Loading 骨架屏 -->
 <div v-if="chatStore.messagesLoading" class="max-w-3xl mx-auto px-6 py-8 space-y-6">
 <div v-for="i in 3":key="i">
 <div v-if="i % 2 === 0" class="flex justify-end">
 <Skeleton class=" w-52 rounded-2xl" />
 </div>
 <div v-else class="space-y-2">
 <Skeleton class=" w-96" />
 <Skeleton class=" w-72" />
 <Skeleton class=" w-48" />
 </div>
 </div>
 </div>
 <!-- 空对话欢迎页 -->
 <ChatWelcome
 v-else-if="!chatStore.hasConversation || (chatStore.messages.length === 0 && !chatStore.isStreaming)"
 />
 <!-- 消息列表 -->
 <div v-else ref="scrollContainer" class="h-full overflow-y-auto">
 <!-- 多选操作条 -->
 <MessageSelectBar
 v-if="chatStore.isExportSelectMode"
 @export="handleMultiExport"
 />
 <div class="max-w-3xl mx-auto px-6 pt-8 pb-40 space-y-7">
 <ChatMessageBubble
 v-for="msg in chatStore.messages":key="msg.id":message="msg"
 @export-single="handleExportSingle"
 />
 <!-- 流式消息 -->
 <ChatMessageBubble
 v-if="chatStore.isStreaming":message="{
 id: 'streaming',
 role: 'assistant',
 content: '',
 created_at: new Date.toISOString,
 }":is-streaming="true":streaming-content="chatStore.streamingContent":streaming-thinking="chatStore.streamingThinking":streaming-tool-calls="chatStore.streamingToolCalls":streaming-timeline="chatStore.streamingTimeline":streaming-status="chatStore.streamingStatus":streaming-narrations="chatStore.streamingNarrations":streaming-pending-text="chatStore.streamingPendingText":deep-analysis-logs="chatStore.deepAnalysisLogs":streaming-doc-summary="(chatStore.streamingMetadata?.docSummary as any) || null"
 />
 <!-- 编码进度卡片 (per: inline 嵌入消息流) -->
 <CodingProgressCard
 v-if="chatStore.activeCodingSession?.status === 'running' && chatStore.codingProgress":steps="chatStore.codingProgress.steps":modified-files-count="chatStore.codingProgress.modifiedFilesCount":is-complete="false"
 />
 <!-- 编码结果卡片 (per ) -->
 <CodingResultCard
 v-if="chatStore.codingResult || (!chatStore.codingError && historyCodingResult)":pr-url="(chatStore.codingResult?.prUrl || historyCodingResult?.prUrl) ?? ''":branch-name="(chatStore.codingResult?.branchName || historyCodingResult?.branchName) ?? ''":modified-files-count="(chatStore.codingResult?.modifiedFilesCount || historyCodingResult?.modifiedFilesCount) ?? 0"
 />
 <!-- 编码错误卡片 (per ) -->
 <CodingErrorCard
 v-if="chatStore.codingError || (!chatStore.codingResult && historyCodingError)":error-message="(chatStore.codingError?.errorMessage || historyCodingError?.errorMessage) ?? ''"
 />
 <!-- 导出成功卡片 (per ) -->
 <ExportSuccessCard
 v-for="(result, idx) in exportResults":key="`export-${idx}`":title="result.title":url="result.url":exported-at="result.exportedAt"
 />
 <!-- 错误提示 -->
 <div v-if="chatStore.error" class="error-card">
 <div class="error-icon">
 <span class="icon-[lucide--alert-circle] text-sm" />
 </div>
 <div class="flex-1 min-w-0">
 <p class="text-[13px] font-medium text-destructive">
 请求失败
 </p>
 <p class="text-xs text-destructive/70 mt-0.5">
 {{ chatStore.error }}
 </p>
 <div v-if="chatStore.lastFailedContent" class="mt-2.5 flex items-center gap-2">
 <Button
 variant="outline"
 size="sm"
 class=" text-xs text-destructive border-destructive/20 hover:bg-destructive/5 gap-1.5 rounded-lg":disabled="chatStore.isStreaming"
 @click="chatStore.retryLastMessage"
 >
 <span class="icon-[lucide--refresh-cw] text-[10px]" />
 重试
 </Button>
 </div>
 </div>
 <button
 class="shrink-0 rounded-md hover:bg-destructive/8 transition-colors text-destructive/40 hover:text-destructive"
 @click="chatStore.error = null; chatStore.lastFailedContent = null"
 >
 <span class="icon-[lucide--x] text-xs" />
 </button>
 </div>
 <!-- 运行态 status bar -->
 <Transition
 enter-active-class="transition-all duration-300 ease-out"
 enter-from-class="opacity-0 translate-y-2"
 enter-to-class="opacity-100 translate-y-0"
 leave-active-class="transition-all duration-200 ease-in"
 leave-from-class="opacity-100 translate-y-0"
 leave-to-class="opacity-0 translate-y-2"
 >
 <ChatStatusBar
 v-if="chatStore.currentPhase && (chatStore.isStreaming || chatStore.restoredRuntimeConversationId)":phase="chatStore.currentPhase":task-progress="chatStore.taskProgress":is-interrupting="chatStore.isInterrupting"
 />
 </Transition>
 </div>
 </div>
 <!-- 回到底部 -->
 <Transition
 enter-active-class="transition-all duration-200 ease-out"
 enter-from-class="opacity-0 translate-y-2"
 enter-to-class="opacity-100 translate-y-0"
 leave-active-class="transition-all duration-150 ease-in"
 leave-from-class="opacity-100 translate-y-0"
 leave-to-class="opacity-0 translate-y-2"
 >
 <button
 v-if="showScrollToBottom"
 class="scroll-btn"
 @click="scrollToBottom"
 >
 <span class="icon-[lucide--chevron-down] text-sm" />
 </button>
 </Transition>
 <!-- 导出确认弹窗 -->
 <ExportConfirmDialog
 v-model:open="showExportDialog":selected-count="exportSelectedIds.length":default-title="exportDefaultTitle":selected-message-ids="exportSelectedIds"
 @success="handleExportSuccess"
 />
 </div>
</template>
<style scoped>
.error-card {
 display: flex;
 align-items: flex-start;
 gap: 0.625rem;
 padding: 0.75rem 1rem;
 border-radius: 0.75rem;
 background: hsl(0 72% 51% / 0.04);
 border: 1px solid hsl(0 72% 51% / 0.1);
}
.error-icon {
 display: flex;
 align-items: center;
 justify-content: center;
 width: 1.5rem;
 height: 1.5rem;
 border-radius: 50%;
 background: hsl(0 72% 51% / 0.08);
 color: hsl(0 72% 51%);
 flex-shrink: 0;
 margin-top: 0.0625rem;
}
.scroll-btn {
 position: absolute;
 bottom: 8rem;
 left: 50%;
 transform: translateX(-50%);
 display: flex;
 align-items: center;
 justify-content: center;
 width: 2rem;
 height: 2rem;
 border-radius: 50%;
 background: white;
 border: 1px solid hsl(214 32% 91%);
 color: hsl(215 16% 47%);
 cursor: pointer;
 box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
 transition: all 0.15s;
}
.scroll-btn:hover {
 border-color: hsl(168 76% 42% / 0.3);
 color: hsl(168 76% 42%);
 box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
}
</style>
