<script setup lang="ts">
import type { ConversationMessage, ExportCodingPlanToFeishuResponse, ExportToFeishuResponse } from '~/types/chat'
import { Button } from '~/components/ui/button'
import { Skeleton } from '~/components/ui/skeleton'
import { usePermission } from '~/composables/usePermission'
import ChatMessageBubble from './ChatMessageBubble.vue'
import ChatStatusBar from './ChatStatusBar.vue'
import ChatWelcome from './ChatWelcome.vue'
import ClarificationCard from './ClarificationCard.vue'
import CleanupDialog from './CleanupDialog.vue'
import CodingErrorCard from './CodingErrorCard.vue'
import CodingProgressCard from './CodingProgressCard.vue'
import CodingResultCard from './CodingResultCard.vue'
import CommitConfirmCard from './CommitConfirmCard.vue'
import ContextExceededCard from './ContextExceededCard.vue'
import ExportConfirmDialog from './ExportConfirmDialog.vue'
import ExportSuccessCard from './ExportSuccessCard.vue'
import MessageSelectBar from './MessageSelectBar.vue'
import PRConfirmCard from './PRConfirmCard.vue'
import ProviderCredentialMissingCard from './ProviderCredentialMissingCard.vue'
// Phase：switch_model 按钮透传给父页面（/pages/chat/[id].vue 监听后调用
// ChatHeader.focusModelSelect）。cleanup_history 按钮走本地 CleanupDialog（下方 ref）。
const emit = defineEmits<{
 'open-model-select':
}>
const chatStore = useChatStore
const cleanupDialogOpen = ref(false)
function handleCleanupConfirmed(_beforeId: string) {
 // 清理成功后重置 lastContextExceeded + 重新 fetch conversation 详情刷新消息列表
 chatStore.resetContextExceeded?.
 if (chatStore.currentConversationId)
 chatStore.selectConversation(chatStore.currentConversationId)
}
// Phase：按角色分流 CTA。system_admin 走 /admin/providers 主按钮；其他走空间设置。
const currentSpaceIdRef = computed( => {
 const conv = chatStore.conversations.find(c => c.id === chatStore.currentConversationId)
 return conv?.space_id ?? ''
})
const { isSystemAdmin, isSpaceAdmin, isViewer } = usePermission(currentSpaceIdRef)
type PermissionRole = 'system_admin' | 'project_admin' | 'member' | 'viewer'
const userRole = computed<PermissionRole>( => {
 if (isSystemAdmin.value)
 return 'system_admin'
 if (isSpaceAdmin.value)
 return 'project_admin'
 if (isViewer.value)
 return 'viewer'
 return 'member'
})
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
 return meta.codingResult as { sessionId: string, prUrl: string, branchName: string, modifiedFilesCount: number, branchUrl?: string }
 }
 }
 return null
})
const historyCodingError = computed( => {
 for (let i = chatStore.messages.length - 1; i >= 0; i--) {
 const meta = chatStore.messages[i].metadata as Record<string, unknown> | undefined
 if (meta?.codingError) {
 return meta.codingError as { sessionId: string, errorMessage: string }
 }
 }
 return null
})
watch(
 => chatStore.currentConversationId,
 => nextTick( => scrollToBottom('instant')),
)
// ============================================================================
// 编码确认流程事件 (Phase)
// ============================================================================
function handleCommitConfirmed(sessionId: string, commitMessage: string) {
 // 记录已完成步骤（ 折叠摘要）
 chatStore.completedConfirmSteps.push({
 step: 'commit_message',
 summary: `Commit: ${commitMessage.split('\n')[0].slice(0, 60)}`,
 })
 // Store 状态将由后端 SSE 事件（awaiting_pr_review）驱动更新
 // 如果后端通过 Runtime 轮询而非 SSE，启动轮询
 if (chatStore.currentConversationId) {
 chatStore.isStreaming = true
 }
}
function handleCreatePR(sessionId: string, data: { title: string, description: string, target_branch: string }) {
 chatStore.completedConfirmSteps.push({
 step: 'pr_review',
 summary: `PR: ${data.title.slice(0, 60)}`,
 })
}
function handleSkipPR(sessionId: string) {
 chatStore.completedConfirmSteps.push({
 step: 'pr_review',
 summary: 'PR: 已跳过',
 })
}
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
/** 导出成功回调 (per )。
 *
 * Phase：ExportConfirmDialog 的 success payload 升级为联合
 * 类型；这里只处理 conversation 模式（含 document_id / url），coding_plan
 * 模式没有 message metadata 需要回写，直接 noop。
 */
function handleExportSuccess(
 result: ExportToFeishuResponse | ExportCodingPlanToFeishuResponse,
) {
 if (!('document_id' in result)) {
 // coding_plan 模式：store 内已 patch CodingPlanRuntime，无需 message metadata 副作用
 chatStore.exitExportSelectMode
 return
 }
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
 <div class="chat-message-stage absolute inset-0 overflow-hidden">
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
 <!-- 空对话欢迎页：有错误时不显示，让错误卡片在消息列表分支中渲染 -->
 <ChatWelcome
 v-else-if="!chatStore.error && (!chatStore.hasConversation || (chatStore.messages.length === 0 && !chatStore.isStreaming))"
 />
 <!-- 消息列表 -->
 <div v-else ref="scrollContainer" class="chat-message-scroll h-full overflow-y-auto">
 <!-- 多选操作条 -->
 <MessageSelectBar
 v-if="chatStore.isExportSelectMode"
 @export="handleMultiExport"
 />
 <div class="chat-message-stack mx-auto pt-8 pb-40 space-y-7">
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
 <!-- Phase：协商卡片（pending + answered 两态都保留） -->
 <ClarificationCard
 v-for="payload in chatStore.pendingClarifications.values":key="payload.clarification_id":payload="payload"
 />
 <!-- 编码进度卡片 (per: inline 嵌入消息流) -->
 <CodingProgressCard
 v-if="chatStore.activeCodingSession?.status === 'running' && chatStore.codingProgress":steps="chatStore.codingProgress.steps":modified-files-count="chatStore.codingProgress.modifiedFilesCount":is-complete="false":modified-files="chatStore.codingProgress.modifiedFiles":recent-tool-calls="chatStore.codingProgress.recentToolCalls"
 />
 <!-- Commit 确认卡片 (/, Phase) -->
 <CommitConfirmCard
 v-if="chatStore.activeCodingSession?.status === 'awaiting_confirmation'
 && chatStore.activeCodingSession.confirmationStep === 'commit_message'
 && chatStore.commitConfirmData":session-id="chatStore.activeCodingSession.sessionId":suggested-commit-message="chatStore.commitConfirmData.suggestedCommitMessage":conflict-data="chatStore.commitConfirmData.conflictCheck":completed-steps="chatStore.completedConfirmSteps"
 @confirmed="handleCommitConfirmed"
 />
 <!-- PR 确认卡片 (/, Phase) -->
 <PRConfirmCard
 v-if="chatStore.activeCodingSession?.status === 'awaiting_confirmation'
 && chatStore.activeCodingSession.confirmationStep === 'pr_review'
 && chatStore.prConfirmData":session-id="chatStore.activeCodingSession.sessionId":suggested-pr-title="chatStore.prConfirmData.suggestedPrTitle":suggested-pr-description="chatStore.prConfirmData.suggestedPrDescription":target-branch="chatStore.prConfirmData.targetBranch":branch-url="chatStore.prConfirmData.branchUrl":completed-steps="chatStore.completedConfirmSteps"
 @create-pr="handleCreatePR"
 @skip-pr="handleSkipPR"
 />
 <!-- 编码结果卡片 (per ) -->
 <CodingResultCard
 v-if="chatStore.codingResult || (!chatStore.codingError && historyCodingResult)":pr-url="(chatStore.codingResult?.prUrl || historyCodingResult?.prUrl) ?? ''":branch-name="(chatStore.codingResult?.branchName || historyCodingResult?.branchName) ?? ''":modified-files-count="(chatStore.codingResult?.modifiedFilesCount || historyCodingResult?.modifiedFilesCount) ?? 0":branch-url="(chatStore.codingResult?.branchUrl || (historyCodingResult as any)?.branchUrl) ?? ''"
 />
 <!-- 编码错误卡片 (per ) -->
 <CodingErrorCard
 v-if="chatStore.codingError || (!chatStore.codingResult && historyCodingError)":error-message="(chatStore.codingError?.errorMessage || historyCodingError?.errorMessage) ?? ''"
 />
 <!-- 导出成功卡片 (per ) -->
 <ExportSuccessCard
 v-for="(result, idx) in exportResults":key="`export-${idx}`":title="result.title":url="result.url":exported-at="result.exportedAt"
 />
 <!-- Phase /：凭证缺失结构化降级卡片 -->
 <ProviderCredentialMissingCard
 v-if="chatStore.credentialMissingPayload":missing-provider="chatStore.credentialMissingPayload.missingProvider":user-role="userRole":space-id="currentSpaceIdRef"
 />
 <!-- Phase /：上下文超限结构化引导卡片 + CleanupDialog -->
 <ContextExceededCard
 v-if="chatStore.lastContextExceeded":estimated-tokens="chatStore.lastContextExceeded.estimated_tokens":max-tokens="chatStore.lastContextExceeded.max_tokens":exceeded-by="chatStore.lastContextExceeded.exceeded_by":model="chatStore.lastContextExceeded.model":recommended-actions="chatStore.lastContextExceeded.recommended_actions"
 @cleanup-click="cleanupDialogOpen = true"
 @switch-model-click="emit('open-model-select')"
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
 <!-- Phase：对话历史清理弹窗（从 ContextExceededCard 的清理按钮触发） -->
 <CleanupDialog
 v-if="chatStore.currentConversationId"
 v-model:open="cleanupDialogOpen":conversation-id="chatStore.currentConversationId"
 @confirm="handleCleanupConfirmed"
 />
 </div>
</template>
<style scoped>
.chat-message-stage {
 background:
 radial-gradient(circle at 22% 8%, hsl(168 76% 42% / 0.055), transparent 24rem),
 radial-gradient(circle at 76% 4%, hsl(199 89% 48% / 0.04), transparent 22rem),
 linear-gradient(180deg, hsl(210 40% 98.5%), hsl(210 40% 96.5%));
}
.chat-message-scroll {
 scrollbar-gutter: stable;
}
.chat-message-stack {
 position: relative;
 width: min(48rem, calc(100% - 2rem));
 max-width: 48rem;
}
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
