<script setup lang="ts">
import type { ExportCodingPlanToFeishuResponse, ExportToFeishuResponse } from '~/types/chat'
import type { ClarificationPayload, PlanClarificationPayload } from '~/types/clarification'
import { gsap } from 'gsap'
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
import MessageSelectBar from './MessageSelectBar.vue'
import PRConfirmCard from './PRConfirmCard.vue'
import ProviderCredentialMissingCard from './ProviderCredentialMissingCard.vue'
// ：switch_model 按钮透传给父页面（/pages/chat/[id].vue 监听后调用
// ChatHeader.focusModelSelect()）。cleanup_history 按钮走本地 CleanupDialog（下方 ref）。
const emit = defineEmits<{
  'open-model-select': []
}>()

const chatStore = useChatStore()

// ============================================================================
// 消息进场动效（GSAP）：新消息浮入。初次渲染历史消息不动画
// （TransitionGroup 默认不触发初始 enter），避免长对话开屏集体闪动。
// ============================================================================
function onMessageEnter(el: Element, done: () => void) {
  if (usePrefersReducedMotion()) {
    done()
    return
  }
  gsap.fromTo(
    el,
    { y: 16, autoAlpha: 0 },
    { y: 0, autoAlpha: 1, duration: 0.38, ease: 'power2.out', clearProps: 'all', onComplete: done },
  )
}

function onMessageLeave(_el: Element, done: () => void) {
  done()
}

/**
 * v-gsap-rise：元素挂载时浮入。用于流式气泡和各类 v-if 卡片
 * （编码进度 / 确认 / 结果 / 错误等），它们的出现时机由业务状态驱动，
 * 用指令比逐个包 Transition 更轻。
 */
const vGsapRise = {
  mounted(el: HTMLElement) {
    if (usePrefersReducedMotion())
      return
    gsap.fromTo(
      el,
      { y: 16, autoAlpha: 0 },
      { y: 0, autoAlpha: 1, duration: 0.38, ease: 'power2.out', clearProps: 'all' },
    )
  },
}

const cleanupDialogOpen = ref(false)
function handleCleanupConfirmed(_beforeId: string) {
  // 清理成功后重置 lastContextExceeded + 重新 fetch conversation 详情刷新消息列表
  chatStore.resetContextExceeded?.()
  if (chatStore.currentConversationId)
    chatStore.selectConversation(chatStore.currentConversationId)
}

// ：按角色分流 CTA。system_admin 走 /admin/providers 主按钮；其他走空间设置。
const currentSpaceIdRef = computed(() => {
  const conv = chatStore.conversations.find(c => c.id === chatStore.currentConversationId)
  return conv?.space_id ?? ''
})
const { isSystemAdmin, isSpaceAdmin, isViewer } = usePermission(currentSpaceIdRef)

type PermissionRole = 'system_admin' | 'project_admin' | 'member' | 'viewer'
const userRole = computed<PermissionRole>(() => {
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
const isAtBottom = computed(() => arrivedState.bottom)
const showScrollToBottom = computed(() => !isAtBottom.value && chatStore.messages.length > 0)

// UAT 2026-05-27 hotfix（284 round 2）：协商卡片按 conversation 维度过滤。
// 没有 conversation_id 的 legacy payload 一律渲染（保持向后兼容）。
// 详见 web/src/types/clarification.ts ClarificationPayload.conversation_id 文档。
const visibleClarifications = computed(() => {
  const currentConv = chatStore.currentConversationId
  return [...chatStore.pendingClarifications.values()].filter(
    p => !p.conversation_id || p.conversation_id === currentConv,
  )
})

// 91-05：plan 结构化澄清（多题多选），与上方单题澄清物理隔离，同样按
// conversation 维度过滤防跨会话串渲染。
const visiblePlanClarifications = computed(() => {
  const currentConv = chatStore.currentConversationId
  return [...chatStore.pendingPlanClarifications.values()].filter(
    p => !p.conversation_id || p.conversation_id === currentConv,
  )
})

// ============================================================================
// 澄清卡片内联锚定：卡片渲染在消息流中的触发位置，而不是堆在最底部。
// 答复后 resume 产出的新消息在卡片下方继续（沿着澄清位置往下走，符合交互直觉）。
//
// 锚点解析优先级（对每张卡）：
// 1) 消息里存在该澄清的「答复消息」（metadata.clarification_id 匹配）→ 卡片渲染在
//    答复消息**之前**（问题卡 → 「我选了X」→ 续推回复，顺序最精确）；
// 2) triggering_message_id / anchor_message_id 命中某条消息 → 渲染在该消息**之后**；
// 3) 均未命中（消息尚未落库等）→ 尾部渲染（跟在流式气泡后，即旧行为）。
// ============================================================================
type AnyClarification = ClarificationPayload | PlanClarificationPayload

const clarificationPlacement = computed(() => {
  const before = new Map<string, AnyClarification[]>()
  const after = new Map<string, AnyClarification[]>()
  const trailing: AnyClarification[] = []

  const msgs = chatStore.messages
  const idSet = new Set(msgs.map(m => m.id))
  // 答复消息索引：metadata.clarification_id → message id（取首条）。
  const answerMsgByClarId = new Map<string, string>()
  for (const m of msgs) {
    const cid = (m.metadata as Record<string, unknown> | undefined)?.clarification_id
    if (typeof cid === 'string' && cid && !answerMsgByClarId.has(cid))
      answerMsgByClarId.set(cid, m.id)
  }

  const push = (map: Map<string, AnyClarification[]>, key: string, p: AnyClarification) => {
    const arr = map.get(key)
    if (arr)
      arr.push(p)
    else
      map.set(key, [p])
  }

  for (const p of [...visibleClarifications.value, ...visiblePlanClarifications.value]) {
    const answerMsgId = answerMsgByClarId.get(p.clarification_id)
    if (answerMsgId) {
      push(before, answerMsgId, p)
      continue
    }
    const triggering = (p as ClarificationPayload).triggering_message_id
    const anchor
      = (triggering && idSet.has(triggering) ? triggering : '')
        || (p.anchor_message_id && idSet.has(p.anchor_message_id) ? p.anchor_message_id : '')
    if (anchor)
      push(after, anchor, p)
    else
      trailing.push(p)
  }
  return { before, after, trailing }
})

/**
 * UAT 2026-05-27 hotfix：自动跟随用户意图状态机（替代原 `|| chatStore.isStreaming`
 * 暴力强制下拉的逻辑）。
 *
 * 原 bug：watch 监听 streamingContent 等流式状态，每个 token 进来都跑回调；
 * 回调条件是 `isAtBottom || isStreaming || error`，OR 三态导致 streaming
 * 期间**完全忽略 isAtBottom**，用户向上滚后下一个 token 就把他拽回底部。
 *
 * 现行 chat UI 标准模式（ChatGPT / Cursor / Claude 同款）：
 * - `autoFollow=true`：用户在底部 → 新内容追加时自动跟随到底
 * - 用户主动向上滚动（wheel / touch / keydown）→ 检测距离底部超过 50px →
 *   `autoFollow=false` → 后续 streaming 不再骚扰用户
 * - 用户主动点「↓ 回到底部」按钮 → `autoFollow=true` 重新跟随
 * - error 信号永远强制滚到底（错误必须让用户看到）
 *
 * 注意：不能直接用 `isAtBottom` 做条件 — 新内容追加时 scrollHeight 增加 ε，
 * isAtBottom 会瞬间变 false（容器距底部 > 50px 阈值），导致"在底部跟随"功能
 * 失效。必须用「用户意图」状态机，只在用户**主动滚动**时重新评估。
 */
const autoFollow = ref(true)

function reevaluateAutoFollow(): void {
  const el = scrollContainer.value
  if (!el)
    return
  const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
  autoFollow.value = distFromBottom < 50
}

useEventListener(scrollContainer, ['wheel', 'touchmove', 'keydown'], reevaluateAutoFollow, { passive: true })

function scrollToBottom(behavior: ScrollBehavior = 'smooth') {
  if (scrollContainer.value) {
    scrollContainer.value.scrollTo({ top: scrollContainer.value.scrollHeight, behavior })
  }
}

/** 用户主动点「↓ 回到底部」按钮 — 重新开启自动跟随 */
function manualScrollToBottom() {
  autoFollow.value = true
  scrollToBottom('smooth')
}

watch(
  () => [chatStore.messages.length, chatStore.streamingContent, chatStore.deepAnalysisLogs.length, chatStore.error, chatStore.currentPhase, chatStore.codingProgress, chatStore.codingResult, chatStore.codingError],
  () => {
    if (autoFollow.value || chatStore.error)
      nextTick(() => scrollToBottom(chatStore.isStreaming ? 'instant' : 'smooth'))
  },
)

// 从消息历史 metadata 恢复编码结果（刷新页面后 codingResult/codingError 为空）
const historyCodingResult = computed(() => {
  for (let i = chatStore.messages.length - 1; i >= 0; i--) {
    const meta = chatStore.messages[i].metadata as Record<string, unknown> | undefined
    if (meta?.codingResult) {
      return meta.codingResult as { sessionId: string, prUrl: string, branchName: string, modifiedFilesCount: number, branchUrl?: string }
    }
  }
  return null
})

const historyCodingError = computed(() => {
  for (let i = chatStore.messages.length - 1; i >= 0; i--) {
    const meta = chatStore.messages[i].metadata as Record<string, unknown> | undefined
    if (meta?.codingError) {
      return meta.codingError as { sessionId: string, errorMessage: string }
    }
  }
  return null
})

watch(
  () => chatStore.currentConversationId,
  () => {
    // 切对话时重新启用自动跟随（新会话的初始位置应在最底部，符合用户直觉）
    autoFollow.value = true
    nextTick(() => scrollToBottom('instant'))
  },
)

// ============================================================================
// 编码确认流程事件
// ============================================================================

function handleCommitConfirmed(sessionId: string, commitMessage: string) {
  // 记录已完成步骤（D-04 折叠摘要）
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
// 导出到飞书
// ============================================================================

const showExportDialog = ref(false)
const exportDefaultTitle = ref('')
const exportSelectedIds = ref<string[]>([])

const currentTitle = computed(() => {
  const conv = chatStore.conversations.find(c => c.id === chatStore.currentConversationId)
  return conv?.title || '新对话'
})

function generateDefaultTitle() {
  const date = new Date().toISOString().slice(0, 10)
  return `${currentTitle.value} - ${date}`
}

/** 单条快速导出 (per D-04) */
function handleExportSingle(messageId: string) {
  exportSelectedIds.value = [messageId]
  exportDefaultTitle.value = generateDefaultTitle()
  showExportDialog.value = true
}

/** 多选导出确认 */
function handleMultiExport() {
  exportSelectedIds.value = [...chatStore.selectedMessageIds]
  exportDefaultTitle.value = generateDefaultTitle()
  showExportDialog.value = true
}

/**
 * 导出成功回调 (per D-14)。
 *
 * ：ExportConfirmDialog 的 success payload 升级为联合
 * 类型；这里只处理 conversation 模式（含 document_id / url），coding_plan
 * 模式没有 message metadata 需要回写，直接 noop。
 */
function handleExportSuccess(
  result: ExportToFeishuResponse | ExportCodingPlanToFeishuResponse,
) {
  if (!('document_id' in result)) {
    // coding_plan 模式：store 内已 patch CodingPlanRuntime，无需 message metadata 副作用
    chatStore.exitExportSelectMode()
    return
  }
  const exportedAt = result.exported_at || new Date().toISOString()
  const target = [...chatStore.messages]
    .filter(msg => exportSelectedIds.value.includes(msg.id) && msg.role === 'assistant')
    .at(-1)

  if (target) {
    const metadata = (target.metadata && typeof target.metadata === 'object')
      ? { ...target.metadata }
      : {}
    const existing = Array.isArray((metadata as Record<string, unknown>).feishu_exports)
      ? [...((metadata as Record<string, unknown>).feishu_exports as Array<Record<string, unknown>>)]
      : []

    if (!existing.some(item => item?.document_id === result.document_id)) {
      existing.push({
        document_id: result.document_id,
        url: result.url,
        title: result.title,
        exported_at: exportedAt,
      })
      ;(metadata as Record<string, unknown>).feishu_exports = existing
      target.metadata = metadata
    }
  }

  chatStore.exitExportSelectMode()
}
</script>

<template>
  <div class="chat-message-stage absolute inset-0 overflow-hidden">
    <!-- Loading 骨架屏 -->
    <div v-if="chatStore.messagesLoading" class="max-w-3xl mx-auto px-6 py-8 space-y-6">
      <div v-for="i in 3" :key="i">
        <div v-if="i % 2 === 0" class="flex justify-end">
          <Skeleton class="h-10 w-52 rounded-2xl" />
        </div>
        <div v-else class="space-y-2">
          <Skeleton class="h-4 w-96" />
          <Skeleton class="h-4 w-72" />
          <Skeleton class="h-4 w-48" />
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
        <!-- TransitionGroup 不渲染包裹元素，气泡仍是 stack 直接子元素（space-y 生效） -->
        <TransitionGroup :css="false" @enter="onMessageEnter" @leave="onMessageLeave">
          <template v-for="msg in chatStore.messages">
            <!-- 澄清卡片内联：锚定在答复消息之前（问题卡 → 答复 → 续推回复） -->
            <ClarificationCard
              v-for="payload in clarificationPlacement.before.get(msg.id) ?? []"
              :key="`clar-${payload.clarification_id}`"
              :payload="payload"
            />
            <!-- 会话内切换空间标记：渲染为分隔线，不进气泡 -->
            <ChatSpaceSwitchDivider
              v-if="msg.role === 'system' && msg.metadata?.type === 'space_switch'"
              :key="`divider-${msg.id}`"
              :message="msg"
            />
            <ChatMessageBubble
              v-else
              :key="msg.id"
              :message="msg"
              @export-single="handleExportSingle"
            />
            <!-- 澄清卡片内联：锚定在触发消息之后 -->
            <ClarificationCard
              v-for="payload in clarificationPlacement.after.get(msg.id) ?? []"
              :key="`clar-${payload.clarification_id}`"
              :payload="payload"
            />
          </template>
        </TransitionGroup>

        <!-- 流式消息 -->
        <ChatMessageBubble
          v-if="chatStore.isStreaming"
          v-gsap-rise
          :message="{
            id: 'streaming',
            role: 'assistant',
            content: '',
            created_at: new Date().toISOString(),
          }"
          :is-streaming="true"
          :streaming-content="chatStore.streamingContent"
          :streaming-thinking="chatStore.streamingThinking"
          :streaming-tool-calls="chatStore.streamingToolCalls"
          :streaming-timeline="chatStore.streamingTimeline"
          :streaming-status="chatStore.streamingStatus"
          :streaming-narrations="chatStore.streamingNarrations"
          :streaming-pending-text="chatStore.streamingPendingText"
          :deep-analysis-logs="chatStore.deepAnalysisLogs"
          :deep-analysis-sessions="chatStore.deepAnalysisSessions"
          :streaming-doc-summary="(chatStore.streamingMetadata?.docSummary as any) || null"
        />

        <!-- 澄清卡片尾部兜底：锚点未命中任何已落库消息时跟在流式气泡后渲染 -->
        <!-- （pending + answered 两态都保留；按 conversation 维度过滤防串单） -->
        <ClarificationCard
          v-for="payload in clarificationPlacement.trailing"
          :key="`clar-${payload.clarification_id}`"
          v-gsap-rise
          :payload="payload"
        />

        <!-- 编码进度卡片 (per D-03: inline 嵌入消息流) -->
        <CodingProgressCard
          v-if="chatStore.activeCodingSession?.status === 'running' && chatStore.codingProgress"
          v-gsap-rise
          :steps="chatStore.codingProgress.steps"
          :modified-files-count="chatStore.codingProgress.modifiedFilesCount"
          :is-complete="false"
          :modified-files="chatStore.codingProgress.modifiedFiles"
          :recent-tool-calls="chatStore.codingProgress.recentToolCalls"
        />

        <!-- Commit 确认卡片 (/, ) -->
        <CommitConfirmCard
          v-if="chatStore.activeCodingSession?.status === 'awaiting_confirmation'
            && chatStore.activeCodingSession.confirmationStep === 'commit_message'
            && chatStore.commitConfirmData"
          v-gsap-rise
          :session-id="chatStore.activeCodingSession.sessionId"
          :suggested-commit-message="chatStore.commitConfirmData.suggestedCommitMessage"
          :conflict-data="chatStore.commitConfirmData.conflictCheck"
          :completed-steps="chatStore.completedConfirmSteps"
          @confirmed="handleCommitConfirmed"
        />

        <!-- PR 确认卡片 (/, ) -->
        <PRConfirmCard
          v-if="chatStore.activeCodingSession?.status === 'awaiting_confirmation'
            && chatStore.activeCodingSession.confirmationStep === 'pr_review'
            && chatStore.prConfirmData"
          v-gsap-rise
          :session-id="chatStore.activeCodingSession.sessionId"
          :suggested-pr-title="chatStore.prConfirmData.suggestedPrTitle"
          :suggested-pr-description="chatStore.prConfirmData.suggestedPrDescription"
          :target-branch="chatStore.prConfirmData.targetBranch"
          :branch-url="chatStore.prConfirmData.branchUrl"
          :completed-steps="chatStore.completedConfirmSteps"
          @create-pr="handleCreatePR"
          @skip-pr="handleSkipPR"
        />

        <!-- 编码结果卡片 (per D-09) -->
        <CodingResultCard
          v-if="chatStore.codingResult || (!chatStore.codingError && historyCodingResult)"
          v-gsap-rise
          :pr-url="(chatStore.codingResult?.prUrl || historyCodingResult?.prUrl) ?? ''"
          :branch-name="(chatStore.codingResult?.branchName || historyCodingResult?.branchName) ?? ''"
          :modified-files-count="(chatStore.codingResult?.modifiedFilesCount || historyCodingResult?.modifiedFilesCount) ?? 0"
          :branch-url="(chatStore.codingResult?.branchUrl || (historyCodingResult as any)?.branchUrl) ?? ''"
        />

        <!-- 编码错误卡片 (per D-12) -->
        <CodingErrorCard
          v-if="chatStore.codingError || (!chatStore.codingResult && historyCodingError)"
          v-gsap-rise
          :error-message="(chatStore.codingError?.errorMessage || historyCodingError?.errorMessage) ?? ''"
        />

        <!-- /：凭证缺失结构化降级卡片 -->
        <ProviderCredentialMissingCard
          v-if="chatStore.credentialMissingPayload"
          v-gsap-rise
          :missing-provider="chatStore.credentialMissingPayload.missingProvider"
          :user-role="userRole"
          :space-id="currentSpaceIdRef"
        />

        <!-- /：上下文超限结构化引导卡片 + CleanupDialog -->
        <ContextExceededCard
          v-if="chatStore.lastContextExceeded"
          v-gsap-rise
          :estimated-tokens="chatStore.lastContextExceeded.estimated_tokens"
          :max-tokens="chatStore.lastContextExceeded.max_tokens"
          :exceeded-by="chatStore.lastContextExceeded.exceeded_by"
          :model="chatStore.lastContextExceeded.model"
          :recommended-actions="chatStore.lastContextExceeded.recommended_actions"
          @cleanup-click="cleanupDialogOpen = true"
          @switch-model-click="emit('open-model-select')"
        />

        <!-- 错误提示 -->
        <div v-if="chatStore.error" v-gsap-rise class="error-card">
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
                class="h-7 text-xs text-destructive border-destructive/20 hover:bg-destructive/5 gap-1.5 rounded-lg"
                :disabled="chatStore.isStreaming"
                @click="chatStore.retryLastMessage()"
              >
                <span class="icon-[lucide--refresh-cw] text-[10px]" />
                重试
              </Button>
            </div>
          </div>
          <button
            class="shrink-0 p-1 rounded-md hover:bg-destructive/8 transition-colors text-destructive/40 hover:text-destructive"
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
            v-if="chatStore.currentPhase && (chatStore.isStreaming || chatStore.restoredRuntimeConversationId)"
            :phase="chatStore.currentPhase"
            :task-progress="chatStore.taskProgress"
            :is-interrupting="chatStore.isInterrupting"
            @skip="chatStore.skipClarification()"
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
        @click="manualScrollToBottom()"
      >
        <span class="icon-[lucide--chevron-down] text-sm" />
      </button>
    </Transition>

    <!-- 导出确认弹窗 -->
    <ExportConfirmDialog
      v-model:open="showExportDialog"
      :selected-count="exportSelectedIds.length"
      :default-title="exportDefaultTitle"
      :selected-message-ids="exportSelectedIds"
      @success="handleExportSuccess"
    />

    <!-- ：对话历史清理弹窗（从 ContextExceededCard 的清理按钮触发） -->
    <CleanupDialog
      v-if="chatStore.currentConversationId"
      v-model:open="cleanupDialogOpen"
      :conversation-id="chatStore.currentConversationId"
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
