/**
 * Chat Store — 对话状态管理
 *
 * 管理对话列表、当前对话、消息列表、流式状态、用户偏好。
 * 使用 setup function 风格（与 projects.ts 一致）。
 */
import type { ChatRole, CodingErrorData, CodingPlanRuntime, CodingProgressData, CodingResultData, CodingSessionRuntime, Conversation, ConversationMessage, ConversationRuntime, DeepAnalysisLog, DeepAnalysisSession, ExportCodingPlanToFeishuRequest, ExportCodingPlanToFeishuResponse, ExportToFeishuRequest, ExportToFeishuResponse, ImagePart, MessagePart, PartCompletedPayload, PartStartedPayload, ProjectPlanToCodingResponse, SSEEvent, StreamTimelineItem, TextPart, ThinkingPart, ToolUsePart } from '~/types/chat'
import type { ClarificationAnswer, ClarificationPayload, PlanClarificationPayload } from '~/types/clarification'
import type { ProviderType } from '~/types/providerCredential'
import type { RoutingDecisionData } from '~/types/routing'
import {
  confirmCodingSession as apiConfirmCodingSession,
  confirmCodingSessionWithBranch as apiConfirmCodingSessionWithBranch,
  skipClarification as apiSkipClarification,
  createConversation,
  createSessionsForPlan,
  deleteConversation,
  exportCodingPlanToFeishu,
  exportToFeishu,
  forkConversationForMessage,
  getConversationDetail,
  getConversationRuntime,
  getFeishuExportAvailability,
  interruptConversation,
  listConversations,
  patchConversation,
  projectArtifactVersionToCodingPlan,
} from '~/api/chat'
import { ApiError, get as apiGet } from '~/api/client'
import { getChatPartsProtocol } from '~/composables/useChatPartsProtocol'
import { connectSSE } from '~/composables/useSSEStream'
import { useWebPush } from '~/composables/useWebPush'
import { useAuthStore } from '~/stores/auth'
import { useRoutingStore } from '~/stores/routing'
import { randomUUID } from '~/utils/uuid'
/** ：preflight missing payload 契约。 */
export interface CredentialMissingPayload {
  missingProvider: ProviderType
  scopeAttempted: string
  recommendedAction: string
}

/** ：SSE ERROR context_window_exceeded payload 契约。 */
export interface ContextExceededPayload {
  estimated_tokens: number
  max_tokens: number
  exceeded_by: number
  model: string
  recommended_actions: Array<{ id: string, label: string, action_type: string, target: string }>
}

/**
 * 把底层流式异常映射为对用户更友好的中文提示。
 *
 * 常见根因：复杂问题触发长链工具/分析（含上游 LLM 调用），整轮耗时超过浏览器/
 * 网关空闲超时 → 连接被中断，fetch 抛 "Failed to fetch"（即用户看到的 network
 * error）。此时后端可能仍在跑（已切 runtime 轮询兜底）；给出可操作的提示。
 */
function friendlyStreamError(e: unknown): string {
  const raw = e instanceof Error ? e.message : String(e ?? '')
  const lower = raw.toLowerCase()
  if (
    lower.includes('failed to fetch')
    || lower.includes('network')
    || lower.includes('networkerror')
    || lower.includes('load failed')
    || lower.includes('connection')
  ) {
    return '连接中断：本轮分析较长导致请求超时或网络中断。可点击重试；若问题涉及很多仓库，建议在提问中指定具体仓库以加快检索。'
  }
  return raw || '发送消息失败'
}

export const useChatStore = defineStore('chat', () => {
  const { requestAndEnableWebPush, webPushReady } = useWebPush()

  // ========================================================================
  // State
  // ========================================================================

  const conversations = ref<Conversation[]>([])
  const currentConversationId = ref<string | null>(null)
  const pendingConversation = ref<Conversation | null>(null)
  const messages = ref<ConversationMessage[]>([])
  const loading = ref(false)
  const messagesLoading = ref(false)
  const error = ref<string | null>(null)

  /**
   * 项目作用域绑定。
   *
   * 非空时：会话列表按 bound_project 过滤、新建/草稿会话自动 bound_project_id 绑定到
   * 该项目。供项目作战室中间对话区复用全局 chat（同 store / 同渲染器 / 同输入框）。
   * null 时（默认）：保持 /chat 全局行为不变。
   */
  const boundProjectId = ref<string | null>(null)

  // 流式状态
  const isStreaming = ref(false)
  const streamingContent = ref('')
  const streamingThinking = ref('')
  const streamingToolCalls = ref<Array<{
    id: string
    name: string
    input: Record<string, unknown>
    result?: string
    status: 'running' | 'done'
  }>>([])
  const streamingTimeline = ref<StreamTimelineItem[]>([])
  const streamingMessageId = ref('')
  const streamingMetadata = ref<Record<string, unknown> | null>(null)
  const abortController = ref<AbortController | null>(null)
  const streamingStatus = ref<'streaming' | 'interrupted' | 'budget_exceeded' | null>(null)
  const budgetWarning = ref<number | null>(null)

  // 叙述/正文分离：工具调用前后的文本归为叙述，最终文本为正文
  const streamingNarrations = ref<string[]>([])
  const streamingPendingText = ref('')

  // parts 数组（与后端 chat_runner._PartsCollector 同源）
  // 替代 streamingContent + streamingPendingText + streamingNarrations + streamingTimeline 四件套
  // 作为新协议下的单一权威；双轨期 legacy flag 下仍写入老 ref（不写本 ref）。
  const streamingParts = ref<MessagePart[]>([])

  // 深度分析实时日志
  const deepAnalysisLogs = ref<DeepAnalysisLog[]>([])
  const deepAnalysisSessionId = ref<string | null>(null)
  // 多个深度分析子会话各自独立的日志（按会话渲染 swiper）
  const deepAnalysisSessions = ref<DeepAnalysisSession[]>([])
  const restoredRuntimeConversationId = ref<string | null>(null)

  // 编码会话状态
  const activeCodingSession = ref<{
    sessionId: string
    status: 'draft' | 'confirmed' | 'running' | 'awaiting_confirmation' | 'completed' | 'failed'
    isConfirming: boolean
    confirmationStep?: 'branch_name' | 'commit_message' | 'pr_review'
  } | null>(null)
  const codingProgress = ref<CodingProgressData | null>(null)
  const codingResult = ref<CodingResultData | null>(null)
  const codingError = ref<CodingErrorData | null>(null)

  // ：当前对话最近 CodingPlan + 每仓 session 快照
  const activeCodingPlan = ref<CodingPlanRuntime | null>(null)

  // ：协商卡片状态机（按 clarification_id 唯一）
  // 不进 localStorage —— 与现有 streaming state pattern 对齐；刷新页面靠后端
  // streaming_snapshot restore 路径还原（plan 03 已落 pending_clarification 进 checkpoint）。
  const pendingClarifications = ref<Map<string, ClarificationPayload>>(new Map())

  // ：plan 结构化澄清（多题 + 多选）状态机（按 clarification_id 唯一）。
  // 与 chat 单题 pendingClarifications 物理隔离（独立 Map），仅由 91-04 runtime
  // `pending_plan_clarification` 回灌；按 conversation 维度绑定防跨会话串渲染。
  const pendingPlanClarifications = ref<Map<string, PlanClarificationPayload>>(new Map())

  // / ：仓库多选 modal 状态机
  const repoMultiSelectorState = ref<{
    open: boolean
    planId: string | null
    preselectedIds: string[]
    submitting: boolean
  }>({
    open: false,
    planId: null,
    preselectedIds: [],
    submitting: false,
  })

  // 编码确认数据
  const commitConfirmData = ref<{
    suggestedCommitMessage: string
    conflictCheck: {
      has_conflicts?: boolean
      conflicting_files?: string[]
      behind_by?: number
      suggestion?: string
    } | null
  } | null>(null)

  const prConfirmData = ref<{
    suggestedPrTitle: string
    suggestedPrDescription: string
    targetBranch: string
    branchUrl: string
  } | null>(null)

  const diffSummaryData = ref<{
    files?: Array<{ path: string, additions: number, deletions: number, change_type: string }>
    total_additions?: number
    total_deletions?: number
    truncated?: boolean
  } | null>(null)

  // ：凭证缺失前置探测 payload（供 ChatMessageArea 渲染 Card）
  const credentialMissingPayload = ref<CredentialMissingPayload | null>(null)

  // ：上下文超限 SSE payload（供 ChatMessageArea 渲染 ContextExceededCard）
  const lastContextExceeded = ref<ContextExceededPayload | null>(null)

  // 已完成确认步骤记录（D-04 折叠摘要）
  const completedConfirmSteps = ref<Array<{
    step: string
    summary: string
  }>>([])

  // 导出多选模式
  const isExportSelectMode = ref(false)
  const selectedMessageIds = ref<Set<string>>(new Set())

  // Phase 感知状态（graph 运行态）
  const currentPhase = ref<string | null>(null)
  const taskProgress = ref<{ completed: number, total: number } | null>(null)
  const isInterrupting = ref(false)
  let interruptTimeout: ReturnType<typeof setTimeout> | null = null

  let runtimePollTimer: ReturnType<typeof setTimeout> | null = null

  function isTimelineToolItem(item: StreamTimelineItem): item is Extract<StreamTimelineItem, { kind: 'tool' }> {
    return item.kind === 'tool'
  }

  // 重试状态：记录最后失败的用户消息
  const lastFailedContent = ref<string | null>(null)

  // 侧边栏状态
  const sidebarCollapsed = ref(false)

  // 草稿填充信号：欢迎页快捷提示点击后填充到 ChatInput（填充而非直发，
  // 给用户修改的机会，避免误触发送）。ChatInput watch 消费后置回 null。
  const draftPrompt = ref<string | null>(null)

  function prefillDraft(text: string) {
    draftPrompt.value = text
  }

  // 飞书导出可用性：未配置（无文件夹/无凭证/无空间）时隐藏「导出到飞书」入口。
  // 按 space 缓存探测结果，避免切消息/切会话重复请求。
  const feishuExportAvailable = ref(false)
  const _feishuAvailabilityBySpace = new Map<string, boolean>()

  async function refreshFeishuExportAvailability(spaceId: string | null | undefined) {
    if (!spaceId) {
      feishuExportAvailable.value = false
      return
    }
    if (_feishuAvailabilityBySpace.has(spaceId)) {
      feishuExportAvailable.value = _feishuAvailabilityBySpace.get(spaceId)!
      return
    }
    try {
      const result = await getFeishuExportAvailability(spaceId)
      _feishuAvailabilityBySpace.set(spaceId, result.available)
      feishuExportAvailable.value = result.available
    }
    catch {
      // 探测失败按不可用处理（按钮隐藏只是 UX 优化，后端仍有兜底校验）
      feishuExportAvailable.value = false
    }
  }

  // 用户偏好（localStorage 持久化）
  const selectedSpaceId = useLocalStorage<string | null>('chat-space-id', null)
  const selectedRole = useLocalStorage<ChatRole>('chat-role', 'developer')
  const selectedModel = useLocalStorage<string>('chat-model', '__default__')
  /**
   * 记忆上次选择的 credential+model 组合（格式：credentialId::modelId）。
   *
   * 用户级持久化（而非环境级）：localStorage 存 { [userId]: "credId::modelId" } 映射，
   * 不同用户在同一浏览器各自独立。未登录时落到 '__anon__' 键。
   */
  const _credentialModelByUser = useLocalStorage<Record<string, string>>(
    'chat-credential-model-by-user',
    {},
  )
  const selectedCredentialModel = computed<string>({
    get() {
      const uid = useAuthStore().user?.id ?? '__anon__'
      return _credentialModelByUser.value[uid] ?? ''
    },
    set(v: string) {
      const uid = useAuthStore().user?.id ?? '__anon__'
      _credentialModelByUser.value = { ..._credentialModelByUser.value, [uid]: v }
    },
  })
  const forceDeepAnalysis = useLocalStorage<boolean>('chat-force-deep-analysis', false)
  const notificationsEnabled = useLocalStorage<boolean>('chat-notifications-enabled', false)

  // ========================================================================
  // Getters
  // ========================================================================

  const currentConversation = computed(() =>
    conversations.value.find(c => c.id === currentConversationId.value)
    ?? (pendingConversation.value?.id === currentConversationId.value ? pendingConversation.value : null),
  )
  const hasConversation = computed(() => currentConversationId.value !== null)

  // ========================================================================
  // Actions
  // ========================================================================

  // 左侧列表默认展示最近 50 条会话（后端 top N）。
  const CONVERSATION_LIST_LIMIT = 50

  async function fetchConversations() {
    loading.value = true
    error.value = null
    try {
      conversations.value = await listConversations({
        limit: CONVERSATION_LIST_LIMIT,
        ...(boundProjectId.value ? { bound_project: boundProjectId.value } : {}),
      })
    }
    catch (e) {
      error.value = e instanceof Error ? e.message : '获取对话列表失败'
    }
    finally {
      loading.value = false
    }
  }

  /**
   * 进入项目作用域：项目作战室中间对话区挂载时调用。绑定项目 + 空间，拉取
   * 该项目的会话列表并自动选中第一条（无则进入草稿态）。与 /chat 共用同一 store，
   * 故离开项目页回到 /chat 时需调 exitProjectScope 解除过滤。
   */
  async function enterProjectScope(projectId: string, spaceId?: string | null) {
    boundProjectId.value = projectId
    if (spaceId)
      selectedSpaceId.value = spaceId
    clearCurrentConversation()
    await fetchConversations()
    const first = conversations.value[0]
    if (first)
      await selectConversation(first.id)
    // 建立/复用实时同步连接并订阅本项目共享分组。
    connectRealtime()
  }

  /** 退出项目作用域（/chat 页挂载时调用，恢复全局全量列表行为）。 */
  function exitProjectScope() {
    boundProjectId.value = null
  }

  /**
   * 在当前项目作用域内即时创建一条会话（区别于草稿懒建：共享会话需要在创建时
   * 就确定 visibility）。创建后置顶并选中。
   */
  async function createProjectConversation(visibility: 'personal' | 'shared' = 'personal') {
    const conv = await createConversation({
      space_id: selectedSpaceId.value || null,
      bound_project_id: boundProjectId.value || undefined,
      visibility,
      model: resolveModelForNewConversation(),
    })
    upsertConversationAtTop(conv)
    await selectConversation(conv.id)
    return conv
  }

  /** 切换会话可见性（项目个人 ↔ 项目共享），成功后同步本地列表。 */
  async function setConversationVisibility(id: string, visibility: 'personal' | 'shared') {
    const updated = await patchConversation(id, { visibility })
    patchConversationLocal(id, updated)
    return updated
  }

  // 已归档会话列表（「查看已归档」入口；与默认列表分开存放）。
  const archivedConversations = ref<Conversation[]>([])
  const archivedLoading = ref(false)

  async function fetchArchivedConversations() {
    archivedLoading.value = true
    try {
      archivedConversations.value = await listConversations({
        archived: true,
        limit: CONVERSATION_LIST_LIMIT,
      })
    }
    catch (e) {
      error.value = e instanceof Error ? e.message : '获取已归档对话失败'
    }
    finally {
      archivedLoading.value = false
    }
  }

  // 会话搜索：服务端匹配标题 + 消息内容（用户诉求「能搜到会话里面的内容」）。
  // 与 conversations（默认列表）分开存放，避免搜索结果污染主列表。
  const conversationSearchResults = ref<Conversation[]>([])
  const conversationSearching = ref(false)
  let searchSeq = 0

  async function searchConversations(keyword: string) {
    const q = keyword.trim()
    if (!q) {
      conversationSearchResults.value = []
      conversationSearching.value = false
      return
    }
    const seq = ++searchSeq
    conversationSearching.value = true
    try {
      const results = await listConversations({ q, limit: CONVERSATION_LIST_LIMIT })
      // 丢弃过期请求结果（用户快速输入时只认最后一次）。
      if (seq === searchSeq)
        conversationSearchResults.value = results
    }
    catch (e) {
      if (seq === searchSeq)
        error.value = e instanceof Error ? e.message : '搜索对话失败'
    }
    finally {
      if (seq === searchSeq)
        conversationSearching.value = false
    }
  }

  function clearConversationSearch() {
    searchSeq++
    conversationSearchResults.value = []
    conversationSearching.value = false
  }

  /** 同步更新某条会话在主列表 + 搜索结果里的字段（保持两处一致）。 */
  function patchConversationLocal(id: string, patch: Partial<Conversation>) {
    const apply = (list: Conversation[]) => {
      const idx = list.findIndex(c => c.id === id)
      if (idx !== -1)
        list[idx] = { ...list[idx], ...patch }
    }
    apply(conversations.value)
    apply(conversationSearchResults.value)
    if (pendingConversation.value?.id === id)
      pendingConversation.value = { ...pendingConversation.value, ...patch }
  }

  /** 重命名会话（PATCH title），成功后同步本地列表。 */
  async function renameConversation(id: string, title: string) {
    const trimmed = title.trim()
    if (!trimmed)
      return
    try {
      await patchConversation(id, { title: trimmed })
      patchConversationLocal(id, { title: trimmed })
    }
    catch (e) {
      error.value = e instanceof Error ? e.message : '重命名失败'
      throw e
    }
  }

  /**
   * 归档 / 取消归档会话，维护「活跃列表」与「已归档列表」两边一致：
   * - 归档：从活跃列表 / 搜索结果移除，置顶进已归档列表。
   * - 取消归档：从已归档列表移除，置顶回活跃列表。
   */
  async function archiveConversation(id: string, archived = true) {
    try {
      await patchConversation(id, { is_archived: archived })
      if (archived) {
        const item
          = conversations.value.find(c => c.id === id)
            ?? conversationSearchResults.value.find(c => c.id === id)
        conversations.value = conversations.value.filter(c => c.id !== id)
        conversationSearchResults.value = conversationSearchResults.value.filter(c => c.id !== id)
        if (item && !archivedConversations.value.some(c => c.id === id))
          archivedConversations.value = [{ ...item, is_archived: true }, ...archivedConversations.value]
        if (currentConversationId.value === id) {
          currentConversationId.value = null
          messages.value = []
        }
      }
      else {
        const item = archivedConversations.value.find(c => c.id === id)
        archivedConversations.value = archivedConversations.value.filter(c => c.id !== id)
        if (item && !conversations.value.some(c => c.id === id))
          conversations.value = [{ ...item, is_archived: false }, ...conversations.value]
        else
          patchConversationLocal(id, { is_archived: false })
      }
    }
    catch (e) {
      error.value = e instanceof Error ? e.message : '归档失败'
      throw e
    }
  }

  async function selectConversation(id: string) {
    // 守住整个切换窗口：期间的重置 / runtime 恢复都不写 localStorage，
    // 避免 sync watcher 把待恢复的瞬时态 localStorage 误删（详见 restoreTransientState）。
    _restoringTransient = true
    stopRuntimePolling()
    pendingConversation.value = null
    currentConversationId.value = id
    syncConversationToURL(id)
    messagesLoading.value = true
    error.value = null
    // UAT 2026-05-27 hotfix（284 round 2）：切换 conversation 时清空前一会话残留的
    // 协商卡片，防止跨会话串单（详见 ClarificationPayload.conversation_id 文档与
    // 284-UAT.md round 2 Gap）。createNewConversation / resetStreamingState 早已
    // 清空，selectConversation 此前漏调，导致用户切对话时旧卡片残留显示。
    clearAllClarifications()
    try {
      const detail = await getConversationDetail(id)
      messages.value = detail.messages
      // 回显已回复的协商卡（待回复态由 restoreConversationRuntime 从 runtime 恢复）
      if (Array.isArray(detail.clarifications)) {
        for (const c of detail.clarifications) {
          if (c?.clarification_id)
            upsertClarification({ ...c, conversation_id: id }, id)
        }
      }
      // hydrate 最新路由 trace，让 RelevanceBadge 等刷新后回显。
      // 契约：整对象透传，**不得**改成显式字段白名单——后端 payload 已含
      // router_version / degraded / degrade_reason / block_order（107-08 起共 9 键），
      // 白名单化会让刷新后降级横幅与分组分区消失。
      if (detail.routing_trace?.trace_id)
        routingStore.upsertTrace(detail.routing_trace, id)
      activeCodingSession.value = null
      codingProgress.value = null
      codingResult.value = null
      codingError.value = null
      commitConfirmData.value = null
      prConfirmData.value = null
      diffSummaryData.value = null
      completedConfirmSteps.value = []
      await restoreConversationRuntime(id)
      // 恢复瞬时动作态（error / 上下文超限 / 凭证缺失 / 预算警告 / 已完成步骤）。
      // 必须在 restoreConversationRuntime 之后 —— 它内部的 resetStreamingState 会清
      // budgetWarning 等，先恢复会被覆盖。
      restoreTransientState(id)
    }
    catch (e) {
      error.value = e instanceof Error ? e.message : '获取对话详情失败'
    }
    finally {
      _restoringTransient = false
      messagesLoading.value = false
    }
  }

  async function createNewConversation() {
    stopRuntimePolling()
    pendingConversation.value = null
    currentConversationId.value = null
    syncConversationToURL(null)
    messages.value = []
    error.value = null
    resetStreamingState()
    // ：清空协商卡片缓存（新对话开始时）
    clearAllClarifications()
  }

  async function removeConversation(id: string) {
    try {
      await deleteConversation(id)
      conversations.value = conversations.value.filter(c => c.id !== id)
      conversationSearchResults.value = conversationSearchResults.value.filter(c => c.id !== id)
      archivedConversations.value = archivedConversations.value.filter(c => c.id !== id)
      if (currentConversationId.value === id) {
        currentConversationId.value = null
        messages.value = []
      }
    }
    catch (e) {
      error.value = e instanceof Error ? e.message : '删除对话失败'
    }
  }

  /**
   * 把 ChatHeader pin-confirmed 接到后端。
   *
   * 流程：
   *   1. PATCH /chat/conversations/:id/ {provider_credential_id}
   *   2. 成功 → 用响应直接覆盖 conversations[] 中对应条目（含新 status + provider_credential_id）
   *      → currentConversation getter 反映新值 → ChatHeader props.currentCredentialId 反向回流
   *   3. 失败 → 写 error.value 并 rethrow，让 ChatHeader handleConfirm 既有 try/catch 接住
   *      （PinConfirmDialog 通过 defineExpose showError 弹错；store action 不能 swallow）
   */
  async function patchConversationCredential(credentialId: string) {
    if (!currentConversationId.value) {
      const msg = '当前没有活动对话，无法切换 Provider 凭证'
      error.value = msg
      throw new Error(msg)
    }
    try {
      const updated = await patchConversation(
        currentConversationId.value,
        { provider_credential_id: credentialId },
      )
      const idx = conversations.value.findIndex(c => c.id === updated.id)
      if (idx >= 0) {
        conversations.value[idx] = { ...conversations.value[idx], ...updated }
      }
      else if (pendingConversation.value?.id === updated.id) {
        pendingConversation.value = { ...pendingConversation.value, ...updated }
      }
      error.value = null
      return updated
    }
    catch (e) {
      error.value = e instanceof Error ? e.message : '切换 Provider 凭证失败'
      throw e
    }
  }

  /**
   * UX 重设计：chat 路径折叠「凭证 + 模型」为单选时，PATCH 双字段。
   *
   * 用户在 ChatInput model-selector 选择「凭证/模型组合」并通过 PinConfirmDialog
   * 确认后调本 action。与 patchConversationCredential 区别：单次请求同时携带
   * provider_credential_id + model，避免两次 PATCH 中间态出现「凭证已切但模型仍是旧
   * Provider 的」非法组合。
   *
   * 失败语义同 patchConversationCredential：throw + 写 error.value，
   * 由消费方（PinConfirmDialog defineExpose showError 或全局 toast）兜错。
   */
  async function patchConversationProviderAndModel(
    credentialId: string,
    model: string,
  ) {
    if (!currentConversationId.value) {
      const msg = '当前没有活动对话，无法切换 Provider / 模型'
      error.value = msg
      throw new Error(msg)
    }
    try {
      const updated = await patchConversation(
        currentConversationId.value,
        { provider_credential_id: credentialId, model },
      )
      const idx = conversations.value.findIndex(c => c.id === updated.id)
      if (idx >= 0) {
        conversations.value[idx] = { ...conversations.value[idx], ...updated }
      }
      else if (pendingConversation.value?.id === updated.id) {
        pendingConversation.value = { ...pendingConversation.value, ...updated }
      }
      error.value = null
      return updated
    }
    catch (e) {
      error.value = e instanceof Error ? e.message : '切换 Provider / 模型失败'
      throw e
    }
  }

  /**
   * 会话内切换空间。
   *
   * 流程：
   *   1. PATCH /chat/conversations/:id/ {space_id}（后端更新绑定 + 落库
   *      space_switch 系统消息，下一轮回答自动基于新空间）
   *   2. 成功 → 回填 conversations[] 条目 + 同步 selectedSpaceId 偏好
   *      （凭证列表 / 飞书导出等既有 watcher 自动联动）
   *   3. 刷新消息列表，让「已切换空间到 xxx」分隔线立即出现
   *
   * 流式 / running 态由 ChatHeader 禁用入口，这里再兜一层。
   */
  async function switchConversationSpace(spaceId: string | null) {
    if (!currentConversationId.value) {
      // 草稿态：没有会话可 PATCH，只更新偏好（影响下一个新建会话）
      selectedSpaceId.value = spaceId
      return
    }
    if (isStreaming.value || currentConversation.value?.status === 'running') {
      const msg = '对话进行中，无法切换空间'
      error.value = msg
      throw new Error(msg)
    }
    const id = currentConversationId.value
    try {
      const updated = await patchConversation(id, { space_id: spaceId })
      const idx = conversations.value.findIndex(c => c.id === updated.id)
      if (idx >= 0)
        conversations.value[idx] = { ...conversations.value[idx], ...updated }
      else if (pendingConversation.value?.id === updated.id)
        pendingConversation.value = { ...pendingConversation.value, ...updated }
      selectedSpaceId.value = spaceId
      error.value = null
      await hydrateConversationMessages(id)
      return updated
    }
    catch (e) {
      error.value = e instanceof Error ? e.message : '切换空间失败'
      throw e
    }
  }

  async function stopStreaming() {
    if (!currentConversationId.value)
      return
    // 乐观更新：立即进入"正在中断"过渡态
    isInterrupting.value = true
    streamingStatus.value = 'interrupted'

    // 3 秒超时：若仍未收到 message_complete，提示中断可能未完成
    if (interruptTimeout)
      clearTimeout(interruptTimeout)
    interruptTimeout = setTimeout(() => {
      if (isInterrupting.value) {
        console.warn('[Chat] 中断超时，中断可能未完成')
      }
    }, 3000)

    // 先调 interrupt API 通知后端取消 SDK task
    try {
      await interruptConversation(currentConversationId.value)
    }
    catch {
      // 忽略错误（对话可能已结束）
    }
    // 1 秒后强制 abort SSE 连接
    if (abortController.value) {
      const controller = abortController.value
      setTimeout(() => {
        if (abortController.value === controller) {
          controller.abort()
          abortController.value = null
          stopRuntimePolling()
          isStreaming.value = false
        }
      }, 1000)
    }
  }

  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  function resolveModelForNewConversation(): string | undefined {
    const providerStore = useProviderCredentialStore()
    const allModels = providerStore.allAvailableModels

    if (selectedCredentialModel.value) {
      const parts = selectedCredentialModel.value.split('::')
      if (parts.length === 2)
        return parts[1]
    }
    if (selectedModel.value !== '__default__' && selectedModel.value)
      return selectedModel.value
    if (allModels.length >= 1) {
      selectedModel.value = allModels[0].modelId
      selectedCredentialModel.value = `${allModels[0].credentialId}::${allModels[0].modelId}`
      return allModels[0].modelId
    }
    return undefined
  }

  function clearCurrentConversation() {
    stopRuntimePolling()
    pendingConversation.value = null
    currentConversationId.value = null
    syncConversationToURL(null)
    messages.value = []
    streamingContent.value = ''
    streamingThinking.value = ''
    streamingToolCalls.value = []
    streamingTimeline.value = []
    streamingMessageId.value = ''
    streamingMetadata.value = null
    streamingNarrations.value = []
    deepAnalysisLogs.value = []
    deepAnalysisSessionId.value = null
    deepAnalysisSessions.value = []
    streamingPendingText.value = ''
    streamingParts.value = []
    restoredRuntimeConversationId.value = null
    // ：切换 conversation 时清空协商状态防串台
    pendingClarifications.value = new Map()
    pendingPlanClarifications.value = new Map()
  }

  function upsertConversationAtTop(conversation: Conversation) {
    const idx = conversations.value.findIndex(c => c.id === conversation.id)
    if (idx >= 0)
      conversations.value.splice(idx, 1)
    conversations.value.unshift(conversation)
  }

  function resetForkRuntimeState() {
    stopRuntimePolling()
    resetStreamingState()
    activeCodingSession.value = null
    activeCodingPlan.value = null
    codingProgress.value = null
    codingResult.value = null
    codingError.value = null
    commitConfirmData.value = null
    prConfirmData.value = null
    diffSummaryData.value = null
    completedConfirmSteps.value = []
    pendingClarifications.value = new Map()
    pendingPlanClarifications.value = new Map()
    isExportSelectMode.value = false
    selectedMessageIds.value = new Set()
    lastFailedContent.value = null
    credentialMissingPayload.value = null
    lastContextExceeded.value = null
  }

  function resetStreamingState() {
    isStreaming.value = false
    streamingContent.value = ''
    streamingThinking.value = ''
    streamingToolCalls.value = []
    streamingTimeline.value = []
    streamingMessageId.value = ''
    streamingMetadata.value = null
    streamingStatus.value = null
    streamingNarrations.value = []
    streamingPendingText.value = ''
    streamingParts.value = []
    deepAnalysisLogs.value = []
    deepAnalysisSessionId.value = null
    deepAnalysisSessions.value = []
    budgetWarning.value = null
    restoredRuntimeConversationId.value = null
    currentPhase.value = null
    taskProgress.value = null
    isInterrupting.value = false
    commitConfirmData.value = null
    prConfirmData.value = null
    diffSummaryData.value = null
    // completedConfirmSteps 不清理（保留已确认步骤给后续卡片展示）
    // 不清理 activeCodingSession / codingResult / codingError（保留给 UI 展示）
    codingProgress.value = null
    if (interruptTimeout) {
      clearTimeout(interruptTimeout)
      interruptTimeout = null
    }
  }

  function stopRuntimePolling() {
    if (runtimePollTimer) {
      clearTimeout(runtimePollTimer)
      runtimePollTimer = null
    }
  }

  function scheduleRuntimePoll(id: string, delay = 2000) {
    stopRuntimePolling()
    runtimePollTimer = setTimeout(() => {
      void pollConversationRuntime(id)
    }, delay)
  }

  function applyRuntimeSnapshot(runtime: ConversationRuntime) {
    isStreaming.value = true
    streamingStatus.value = 'streaming'
    streamingContent.value = ''
    streamingThinking.value = ''
    streamingPendingText.value = ''
    streamingParts.value = []
    streamingMetadata.value = null
    streamingMessageId.value = ''
    deepAnalysisSessionId.value = runtime.session_id || null
    deepAnalysisLogs.value = runtime.logs || []
    deepAnalysisSessions.value = runtime.deep_sessions || []
    restoredRuntimeConversationId.value = runtime.conversation_id
    currentPhase.value = runtime.phase || null
    taskProgress.value = runtime.task_progress || null

    if (runtime.mode === 'deep_analysis') {
      // 刷新恢复时按子会话逐个生成 synthetic tool call，保证多个深度分析的
      // swiper 能显示全部子代理；无 deep_sessions 时回退到单条（向后兼容）。
      const sessions = runtime.deep_sessions && runtime.deep_sessions.length > 0
        ? runtime.deep_sessions
        : [{
            session_id: runtime.session_id || 'deep-analysis-runtime',
            task_description: runtime.task_description || '',
            status: runtime.status || 'running',
            logs: runtime.logs || [],
          } as DeepAnalysisSession]
      const synthetic = sessions.map(s => ({
        id: s.session_id || 'deep-analysis-runtime',
        name: 'mcp__chat-tools__deep_analysis',
        input: s.task_description ? { task_description: s.task_description } : {},
        status: 'running' as const,
      }))
      streamingToolCalls.value = synthetic
      streamingTimeline.value = synthetic.map(t => ({
        id: t.id,
        kind: 'tool' as const,
        name: t.name,
        input: t.input,
        status: t.status,
      }))
    }
    else if (runtime.mode === 'coding' && runtime.coding_session) {
      // 恢复编码会话状态
      const cs = runtime.coding_session as CodingSessionRuntime
      const csStatus = cs.status as 'draft' | 'confirmed' | 'running' | 'awaiting_confirmation' | 'completed' | 'failed'
      activeCodingSession.value = {
        sessionId: cs.id,
        status: csStatus,
        isConfirming: false,
        confirmationStep: (cs.confirmation_step as 'branch_name' | 'commit_message' | 'pr_review') || undefined,
      }

      // 恢复确认数据（D-23 页面刷新恢复）
      if (csStatus === 'awaiting_confirmation') {
        isStreaming.value = false // 确认态不锁定输入框
        if (cs.confirmation_step === 'commit_message') {
          commitConfirmData.value = {
            suggestedCommitMessage: cs.suggested_commit_message || '',
            conflictCheck: (cs.conflict_check_result as typeof commitConfirmData.value extends null ? never : NonNullable<typeof commitConfirmData.value>['conflictCheck']) || null,
          }
        }
        else if (cs.confirmation_step === 'pr_review') {
          prConfirmData.value = {
            suggestedPrTitle: cs.suggested_pr_title || '',
            suggestedPrDescription: cs.suggested_pr_description || '',
            targetBranch: cs.target_branch || 'main',
            branchUrl: cs.branch_url || '',
          }
        }
      }
      streamingToolCalls.value = []
      streamingTimeline.value = []

      // runtime restore： 切 polling 后遗漏的前端接线 ——
      // runtime.coding_session.coding_progress（由 conversation_service 从
      // SubAgentSession.last_output 透传）转写到 store.codingProgress，让
      // CodingProgressCard 渲染条件 `activeCodingSession?.status === 'running'
      // && codingProgress` 在 polling 路径下也能成立。SSE 路径 case
      // 'coding_progress' 保留双写不冲突。
      const cp = cs.coding_progress
      if (cp && (cp.modified_files?.length || cp.recent_tool_calls?.length)) {
        codingProgress.value = {
          sessionId: cs.id,
          steps: [], // polling 不发 steps；UI 已容忍空数组
          modifiedFilesCount: cp.modified_files?.length ?? 0,
          modifiedFiles: cp.modified_files ?? [],
          recentToolCalls: cp.recent_tool_calls ?? [],
        }
      }
      else if (codingProgress.value && codingProgress.value.sessionId !== cs.id) {
        // 切到不同 session（比如 fan-out 多仓时 polling pivot 漂移）→ 清旧进度
        codingProgress.value = null
      }
    }
    else {
      streamingToolCalls.value = []
      streamingTimeline.value = []
      if (runtime.progress_message)
        streamingPendingText.value = runtime.progress_message
    }

    // 后端 _StreamingSnapshot 把 SSE 流期间的累积态写到了 OrchestrationRun.metadata，
    // runtime API 透传 streaming_snapshot 字段。刷新场景：SSE 已断、SSE 内存状态全
    // 丢；用 snapshot 把 streaming UI 恢复到刷新前的样子，避免「空气泡 + 正在整理
    // 回答」窒息体验。
    //
    // 放在 mode 分支之后：snapshot 比 deep_analysis / coding 模式的「占位 tool」
    // 更准确（snapshot 里通常已经包含同名 tool 的真实进度），有 snapshot 时覆盖
    // 占位；老对话 / 老 runtime 没 snapshot 时退回到占位逻辑，保持向后兼容。
    const snap = runtime.streaming_snapshot
    const snapNonEmpty = !!snap && (
      !!snap.pending_text
      || !!snap.thinking
      || (Array.isArray(snap.tool_calls) && snap.tool_calls.length > 0)
      || (Array.isArray(snap.timeline) && snap.timeline.length > 0)
      || (Array.isArray(snap.narrations) && snap.narrations.length > 0)
    )
    if (snap && snapNonEmpty) {
      streamingPendingText.value = snap.pending_text || ''
      streamingThinking.value = snap.thinking || ''
      streamingNarrations.value = Array.isArray(snap.narrations) ? [...snap.narrations] : []
      streamingToolCalls.value = Array.isArray(snap.tool_calls)
        ? snap.tool_calls.map(tc => ({
            id: tc.id,
            name: tc.name,
            input: tc.input || {},
            result: tc.result ?? undefined,
            status: tc.status === 'done' ? 'done' : 'running',
            batch_id: tc.batch_id ?? undefined,
          }))
        : []
      streamingTimeline.value = Array.isArray(snap.timeline) ? [...snap.timeline] : []
    }

    // ：写入最新 coding_plan 快照（TechPlanCard 通过 store 订阅）
    // ：merge 保留本地已导出态，避免轮询竞态抹掉刚 patch 的 doc_url
    assignCodingPlanPreservingFeishu(runtime.coding_plan ?? null)
  }

  /**
   * 写入 activeCodingPlan，但在轮询竞态窗口内保留本地已导出态：
   * 若 incoming 与当前 activeCodingPlan 同一 plan_id，且 incoming 侧
   * feishu_doc_url 为空但本地已有非空值，则保留本地 feishu_doc_url/token。
   * 后端 落地后 runtime 通常已带值，此处是双保险。
   */
  function assignCodingPlanPreservingFeishu(incoming: CodingPlanRuntime | null) {
    const prev = activeCodingPlan.value
    if (
      incoming
      && prev
      && incoming.plan_id === prev.plan_id
      && !incoming.feishu_doc_url
      && prev.feishu_doc_url
    ) {
      activeCodingPlan.value = {
        ...incoming,
        feishu_doc_token: incoming.feishu_doc_token || prev.feishu_doc_token,
        feishu_doc_url: prev.feishu_doc_url,
      }
    }
    else {
      activeCodingPlan.value = incoming
    }
  }

  function appendTimelineText(kind: 'thinking' | 'narration', text: string) {
    if (!text)
      return
    const last = streamingTimeline.value[streamingTimeline.value.length - 1]
    if (last && last.kind === kind) {
      last.text += text
      return
    }
    streamingTimeline.value.push({
      id: randomUUID(),
      kind,
      text,
    })
  }

  function flushPendingNarrationToTimeline() {
    if (!streamingPendingText.value.trim())
      return
    appendTimelineText('narration', streamingPendingText.value)
    streamingNarrations.value.push(streamingPendingText.value)
    streamingPendingText.value = ''
  }

  async function hydrateConversationMessages(id: string) {
    const detail = await getConversationDetail(id)
    messages.value = detail.messages
  }

  async function pollConversationRuntime(id: string) {
    if (currentConversationId.value !== id)
      return

    try {
      const runtime = await getConversationRuntime(id)
      if (runtime.active) {
        applyRuntimeSnapshot(runtime)

        // 检查 deep analysis 是否已失败（后端回调丢失或 resume 出错）
        const failedStatuses = ['error', 'timeout', 'cancelled']
        if (
          runtime.mode === 'deep_analysis'
          && runtime.status
          && failedStatuses.includes(runtime.status)
        ) {
          error.value = runtime.progress_message || '深度分析任务失败'
          stopRuntimePolling()
          resetStreamingState()
          await hydrateConversationMessages(id)
          return
        }
        if (
          runtime.deep_analysis_status
          && failedStatuses.includes(runtime.deep_analysis_status)
        ) {
          error.value = runtime.deep_analysis_error || '深度分析任务失败'
          stopRuntimePolling()
          resetStreamingState()
          await hydrateConversationMessages(id)
          return
        }

        scheduleRuntimePoll(id)
        return
      }

      // 检查是否有编码完成/失败
      const cs = runtime.coding_session as CodingSessionRuntime | undefined
      if (cs && cs.status === 'completed') {
        codingResult.value = {
          sessionId: cs.id,
          prUrl: cs.pr_url || '',
          branchName: cs.branch_name || '',
          modifiedFilesCount: cs.affected_files?.length || 0,
          branchUrl: cs.branch_url || '',
        }
        if (activeCodingSession.value) {
          activeCodingSession.value.status = 'completed'
        }
      }
      else if (cs && cs.status === 'failed') {
        codingError.value = {
          sessionId: cs.id,
          errorMessage: cs.error_message || '编码失败',
        }
        if (activeCodingSession.value) {
          activeCodingSession.value.status = 'failed'
        }
      }

      // 检查 deep analysis 失败（非活跃态）
      const failedStatuses = ['error', 'timeout', 'cancelled']
      if (
        runtime.deep_analysis_status
        && failedStatuses.includes(runtime.deep_analysis_status)
      ) {
        error.value = runtime.deep_analysis_error || '深度分析任务失败'
      }

      stopRuntimePolling()
      const completedSessionId = deepAnalysisSessionId.value
      // 无条件刷新消息：deep_analysis 等异步任务完成后，消息已由后端落库，
      // 但前端 SSE 断开后可能尚未同步。wasRestoringRuntime 限制会漏掉
      // 任务极快失败（第一次轮询即终态）的场景。
      await hydrateConversationMessages(id)
      if (completedSessionId)
        _notifyConversationComplete({ isDeepAnalysis: true })
      resetStreamingState()
    }
    catch {
      scheduleRuntimePoll(id, 4000)
    }
  }

  async function restoreConversationRuntime(id: string) {
    try {
      const runtime = await getConversationRuntime(id)
      // 恢复待回复的澄清卡（与 streaming 解耦）：刷新 / 切回会话后仍能答复。
      // 澄清问题不落 Message，只在 checkpoint + ConversationIntentTrace，前端内存
      // pendingClarifications 刷新即丢 —— 这里从 runtime 回灌。
      const pc = runtime.pending_clarification
      if (pc && pc.clarification_id) {
        upsertClarification({
          clarification_id: pc.clarification_id,
          question: pc.question || '',
          options: Array.isArray(pc.options) ? pc.options : [],
          allow_freeform: pc.allow_freeform !== false,
          status: 'pending',
        }, id)
      }
      // 91-04 runtime 新键：plan 结构化澄清轮（多题），独立于上方 chat 单题，
      // 按 conversation 维度回灌，questions 非空才进 plan 澄清面（旧单题行不误入）。
      const ppc = runtime.pending_plan_clarification
      if (ppc && ppc.clarification_id && Array.isArray(ppc.questions) && ppc.questions.length > 0) {
        upsertPlanClarification({
          clarification_id: ppc.clarification_id,
          round_no: ppc.round_no,
          questions: ppc.questions,
          status: 'pending',
        }, id)
      }
      if (!runtime.active) {
        resetStreamingState()
        activeCodingPlan.value = runtime.coding_plan ?? null
        return
      }
      // active（含 waiting_clarification）：恢复 streaming_snapshot 里助手已产出的
      // 正文/工具，并继续轮询。waiting_clarification 阶段的「空气泡 + 打字光标」由
      // ChatMessageBubble 按 phase 抑制（见 hideEmptyBubble / typing-cursor），
      // 避免暂停等待时误显"正在输入"。
      applyRuntimeSnapshot(runtime)
      scheduleRuntimePoll(id)
    }
    catch {
      resetStreamingState()
    }
  }

  // ========================================================================
  // 瞬时动作态跨刷新保留（B 类回显）
  // ------------------------------------------------------------------------
  // error / 失败内容 / 上下文超限 / 凭证缺失 / 预算警告 / 已完成确认步骤 都是
  // 前端内存态，刷新即丢。按 conversation 维度持久化到 localStorage，切回/刷新
  // 时恢复。自清理：状态被清空（如下一次成功发送）时同步 removeItem，避免
  // 「旧错误卡永久复活」。用 flush:'sync' 保证 select 时的恢复不被异步 watcher 抢跑。
  // ========================================================================
  const TRANSIENT_KEY_PREFIX = 'friday-chat-transient:'
  let _restoringTransient = false

  function persistTransientState(convId: string | null) {
    if (!convId || _restoringTransient)
      return
    const blob = {
      error: error.value,
      lastFailedContent: lastFailedContent.value,
      lastContextExceeded: lastContextExceeded.value,
      credentialMissingPayload: credentialMissingPayload.value,
      budgetWarning: budgetWarning.value,
      completedConfirmSteps: completedConfirmSteps.value,
    }
    const hasAny = !!(
      blob.error
      || blob.lastFailedContent
      || blob.lastContextExceeded
      || blob.credentialMissingPayload
      || blob.budgetWarning != null
      || (blob.completedConfirmSteps && blob.completedConfirmSteps.length > 0)
    )
    try {
      if (hasAny)
        localStorage.setItem(TRANSIENT_KEY_PREFIX + convId, JSON.stringify(blob))
      else
        localStorage.removeItem(TRANSIENT_KEY_PREFIX + convId)
    }
    catch {}
  }

  // 读 localStorage 恢复瞬时态。调用方（selectConversation）负责用 _restoringTransient
  // 守住整个「重置 + runtime 恢复 + 本恢复」窗口，避免 sync watcher 在重置阶段把
  // localStorage 误删。
  function restoreTransientState(convId: string) {
    try {
      const raw = localStorage.getItem(TRANSIENT_KEY_PREFIX + convId)
      const blob = raw ? JSON.parse(raw) : null
      error.value = blob?.error ?? null
      lastFailedContent.value = blob?.lastFailedContent ?? null
      lastContextExceeded.value = blob?.lastContextExceeded ?? null
      credentialMissingPayload.value = blob?.credentialMissingPayload ?? null
      budgetWarning.value = blob?.budgetWarning ?? null
      completedConfirmSteps.value = Array.isArray(blob?.completedConfirmSteps)
        ? blob.completedConfirmSteps
        : []
    }
    catch {
      // 解析失败 → 全部清空（安全降级）
      error.value = null
      lastFailedContent.value = null
      lastContextExceeded.value = null
      credentialMissingPayload.value = null
      budgetWarning.value = null
      completedConfirmSteps.value = []
    }
  }

  watch(
    [error, lastFailedContent, lastContextExceeded, credentialMissingPayload, budgetWarning, completedConfirmSteps],
    () => persistTransientState(currentConversationId.value),
    { deep: true, flush: 'sync' },
  )

  // ========================================================================
  // SSE 流式消息 (, )
  // ========================================================================

  const routingStore = useRoutingStore()

  /**
   * ：从 tool_use_result 提取 routing trace 并写入 store。
   *
   * 两路径：
   *   (a) analyze_repository_relevance → 直接读 result.output.data；
   *   (b) deep_analysis → 扫 text 末尾 `[cross_repo_relevance:<trace_id>]\n<JSON>` 段。
   *
   * 同时把 trace_id 写入即将持久化的 streamingMessage metadata，让 RoutingDecisionPanel
   * 在 message 已渲染时也能反查 trace。
   */
  function maybeParseRoutingTraceFromToolResult(args: {
    toolName: string
    toolInput: Record<string, unknown>
    normalizedResult: string
  }): void {
    const conversationId = currentConversationId.value
    if (!conversationId)
      return

    try {
      if (args.toolName === 'analyze_repository_relevance') {
        const parsed = JSON.parse(args.normalizedResult) as {
          output?: { data?: Record<string, unknown> }
          data?: Record<string, unknown>
        }
        const data = (parsed?.output?.data ?? parsed?.data) as
          | {
            trace_id?: string
            candidates?: unknown[]
            threshold?: number
            router_version?: string
            degraded?: boolean
            degrade_reason?: RoutingDecisionData['degrade_reason']
            block_order?: RoutingDecisionData['block_order']
          }
          | undefined
        const traceId = data?.trace_id
        if (data && typeof traceId === 'string') {
          // 四个 trace 级事实按「有则透传、无则 undefined」写入——不填假值，
          // 缺字段的历史/legacy 工具输出要保持今日渲染（无横幅、平铺列表）。
          const trace: RoutingDecisionData = {
            trace_id: traceId,
            query: (args.toolInput.query as string) || '',
            candidates: (data.candidates as RoutingDecisionData['candidates']) || [],
            threshold: typeof data.threshold === 'number' ? data.threshold : 0.5,
            triggered_by: 'chat_tool',
            router_version: typeof data.router_version === 'string' ? data.router_version : undefined,
            degraded: typeof data.degraded === 'boolean' ? data.degraded : undefined,
            degrade_reason: data.degrade_reason,
            block_order: Array.isArray(data.block_order) ? data.block_order : undefined,
          }
          routingStore.upsertTrace(trace, conversationId)
          // 把 trace_id 挂到 streamingMetadata 让 message_complete 时持久化
          streamingMetadata.value = {
            ...(streamingMetadata.value || {}),
            routing_trace_id: traceId,
          }
        }
        return
      }

      if (args.toolName === 'deep_analysis') {
        // 后端 callbacks.py 把 candidates JSON 拼到 text_output 末尾：
        //   [cross_repo_relevance:<trace_id>]\n<JSON 数组>
        // result 可能是嵌套 ToolResult.output JSON / 或直接是裸 text；两路径都扫一遍
        const matcher = /\[cross_repo_relevance:([0-9a-fA-F-]+)\]\s*\n(\[.*?\])/s
        const m = args.normalizedResult.match(matcher)
        if (m) {
          const traceId = m[1]
          const candidates = JSON.parse(m[2]) as RoutingDecisionData['candidates']
          // 该 payload 只有候选数组（候选级 group / trust / score_ranked 随之透传），
          // 结果级四键在这条链上不存在 → 一律留 undefined，绝不填假值：
          // 把降级事实填成 false 等于把「未知」谎报成「没降级过」。
          const trace: RoutingDecisionData = {
            trace_id: traceId,
            query: '',
            candidates,
            threshold: 0.5,
            triggered_by: 'deep_analysis_completion',
          }
          routingStore.upsertTrace(trace, conversationId)
          streamingMetadata.value = {
            ...(streamingMetadata.value || {}),
            routing_trace_id: traceId,
          }
        }
      }
    }
    catch (err) {
      console.warn('[routing] failed to parse trace from tool result', err)
    }
  }

  /**
   * part_started 分派
   *
   * 按 index 维护 `streamingParts` array：若已有同 index 的 part（重连 / 重放）
   * 覆盖；否则按 index 插入。tool_use part 在此处即写完整 input / status=running，
   * tool_use_result 等价的 `part_completed` 事件再 mark done / error + write result。
   */
  function handlePartStarted(event: SSEEvent): void {
    const partPayload = event.part as PartStartedPayload | undefined
    if (!partPayload || typeof partPayload.type !== 'string')
      return
    const index = typeof event.index === 'number' ? event.index : partPayload.index
    if (typeof index !== 'number')
      return

    let next: MessagePart | null = null
    if (partPayload.type === 'text') {
      next = {
        type: 'text',
        id: partPayload.id || randomUUID(),
        index,
        text: partPayload.text || '',
        state: partPayload.state === 'done' ? 'done' : 'streaming',
      } satisfies TextPart
    }
    else if (partPayload.type === 'thinking') {
      next = {
        type: 'thinking',
        id: partPayload.id || randomUUID(),
        index,
        text: partPayload.text || '',
        state: partPayload.state === 'done' ? 'done' : 'streaming',
      } satisfies ThinkingPart
    }
    else if (partPayload.type === 'tool_use') {
      next = {
        type: 'tool_use',
        id: partPayload.id || randomUUID(),
        index,
        tool_call_id: partPayload.tool_call_id || '',
        name: partPayload.name || '',
        input: partPayload.input || {},
        status: partPayload.status || 'running',
        result: partPayload.result ?? null,
        batch_id: partPayload.batch_id ?? null,
      } satisfies ToolUsePart
    }
    if (!next)
      return
    const existingIdx = streamingParts.value.findIndex(p => p.index === index)
    if (existingIdx >= 0) {
      streamingParts.value.splice(existingIdx, 1, next)
    }
    else {
      streamingParts.value.push(next)
      // 按 index 升序排：通常事件顺序到达，少数 OOO 通过 sort 兜底
      streamingParts.value.sort((a, b) => a.index - b.index)
    }
  }

  /**
   * part_delta：当前仅支持 `delta_type: 'text_append'` —— text / thinking part 增量 append。
   * tool_use part 无 delta（后端 BE-03 始终在 start_tool_use 时 input 一次性发完）。
   */
  function handlePartDelta(event: SSEEvent): void {
    if (typeof event.index !== 'number')
      return
    const target = streamingParts.value.find(p => p.index === event.index)
    if (!target)
      return
    if (event.delta_type === 'text_append' && (target.type === 'text' || target.type === 'thinking')) {
      target.text = (target.text || '') + (event.text || '')
    }
  }

  /**
   * part_completed：text / thinking 标 `state=done`；tool_use 写 result + status + 触发 routing trace 解析。
   *
   * 把 `maybeParseRoutingTraceFromToolResult` 触发位置从
   * 旧 `tool_use_result` 事件迁到 `part_completed`（part.type === 'tool_use'）—— 同时保留
   * legacy flag 下的 `tool_use_result` 路径，确保 legacy 行为零回归。
   */
  function handlePartCompleted(event: SSEEvent): void {
    const partPayload = event.part as PartCompletedPayload | undefined
    const index = typeof event.index === 'number' ? event.index : partPayload?.index
    if (typeof index !== 'number')
      return
    const target = streamingParts.value.find(p => p.index === index)
    if (!target)
      return

    if (target.type === 'text' || target.type === 'thinking') {
      target.state = 'done'
      return
    }

    if (target.type === 'tool_use') {
      if (partPayload?.status)
        target.status = partPayload.status
      else
        target.status = 'done'
      if (partPayload?.result !== undefined)
        target.result = partPayload.result

      // routing trace 解析（FE-04：触发位置从 tool_use_result 迁来）
      const resultStr = typeof target.result === 'string' ? target.result : ''
      if (resultStr) {
        maybeParseRoutingTraceFromToolResult({
          toolName: target.name,
          toolInput: target.input,
          normalizedResult: resultStr,
        })

        // ：ask_clarification pending payload 解析（与旧路径同步保留）
        if (target.name === 'ask_clarification') {
          try {
            const parsed = JSON.parse(resultStr) as {
              clarification_id?: string
              pending?: boolean
              marker?: string
              question?: string
              options?: Array<{ id: string, label: string, hint?: string, implies?: Record<string, unknown> }>
              allow_freeform?: boolean
            }
            if (
              parsed.pending === true
              && parsed.marker === 'ask_clarification'
              && parsed.clarification_id
            ) {
              upsertClarification({
                clarification_id: parsed.clarification_id,
                question: parsed.question || '',
                options: parsed.options || [],
                allow_freeform: parsed.allow_freeform !== false,
                status: 'pending',
                triggering_message_id: streamingMessageId.value || undefined,
              }, currentConversationId.value ?? undefined)
            }
          }
          catch {
            // 静默
          }
        }
      }
    }
  }

  /**
   * SSE 事件分派。
   *
   * `ownerConversationId`：发起本次流式的会话 id（由 `sendMessage` 闭包捕获并注入）。
   * 跨会话串流防护核心 —— 当 owner 与当前会话不一致（用户已切走）时，后台流
   * **继续执行**（后端仍 finalize 落库），但事件**不写当前会话 UI** 的 streaming
   * state；唯一例外是 `title_generated`，仍把所属会话在列表里的标题更新（不触当前视图）。
   * 复用 ClarificationCard 的「写入按 conversation 维度过滤」范式。
   *
   * 未传 ownerConversationId 时（旧调用 / 单测 `_dispatchSSE`）按前台处理，行为零回归。
   */
  function handleSSEEvent(event: SSEEvent, ownerConversationId?: string) {
    const isForeground = !ownerConversationId || ownerConversationId === currentConversationId.value
    if (!isForeground) {
      // 后台会话流：仅允许更新所属会话在列表中的标题，其余一律不写当前 UI。
      if (event.type === 'title_generated' && event.title && ownerConversationId) {
        const conv = conversations.value.find(c => c.id === ownerConversationId)
        if (conv)
          conv.title = event.title
        else if (pendingConversation.value?.id === ownerConversationId)
          pendingConversation.value = { ...pendingConversation.value, title: event.title }
      }
      return
    }

    // 用户已中断，忽略后续事件（仅保留 message_complete 用于清理）
    if (streamingStatus.value === 'interrupted' && event.type !== 'message_complete')
      return

    // 双轨期协议分发
    //   - protocol === 'new'：消费 part_* 事件，旧 text_delta / thinking / tool_use_*
    //     直接 return（避免写入 streamingPendingText 等老 state 触发 narration-block 渲染）。
    //   - protocol === 'legacy'：保留当前 legacy 行为，part_* 直接 return。
    //   - message_complete 双轨都处理（同 legacy），final_answer / metadata / status 共用。
    const protocol = getChatPartsProtocol()
    if (protocol === 'new' && (event.type === 'text_delta' || event.type === 'thinking' || event.type === 'tool_use_start' || event.type === 'tool_use_result'))
      return
    if (protocol === 'legacy' && (event.type === 'part_started' || event.type === 'part_delta' || event.type === 'part_completed'))
      return

    switch (event.type) {
      case 'part_started':
        handlePartStarted(event)
        break
      case 'part_delta':
        handlePartDelta(event)
        break
      case 'part_completed':
        handlePartCompleted(event)
        break
      case 'text_delta':
        streamingPendingText.value += event.text || ''
        break
      case 'thinking':
        streamingThinking.value += event.thinking || ''
        appendTimelineText('thinking', event.thinking || '')
        break
      case 'tool_use_start': {
        // 工具调用前的文本归为叙述（如"让我搜索一下..."）
        flushPendingNarrationToTimeline()

        const existing = streamingToolCalls.value.find(t => t.id === event.tool_call_id)
        if (!existing) {
          streamingToolCalls.value.push({
            id: event.tool_call_id || '',
            name: event.tool_name || '',
            input: (event.input as Record<string, unknown>) || {},
            status: 'running',
          })
        }
        else if (event.input && Object.keys(event.input as Record<string, unknown>).length > 0) {
          existing.input = event.input as Record<string, unknown>
        }

        const timelineTool = streamingTimeline.value.find((item): item is Extract<StreamTimelineItem, { kind: 'tool' }> =>
          isTimelineToolItem(item) && item.id === event.tool_call_id,
        )
        if (!timelineTool) {
          streamingTimeline.value.push({
            id: event.tool_call_id || randomUUID(),
            kind: 'tool',
            name: event.tool_name || '',
            input: (event.input as Record<string, unknown>) || {},
            status: 'running',
            batch_id: event.batch_id || undefined,
          })
        }
        else {
          timelineTool.name = event.tool_name || timelineTool.name
          if (event.input && Object.keys(event.input as Record<string, unknown>).length > 0)
            timelineTool.input = event.input as Record<string, unknown>
          if (event.batch_id && !timelineTool.batch_id)
            timelineTool.batch_id = event.batch_id
        }
        break
      }
      case 'tool_use_result': {
        // 防御性序列化：后端历史路径里 chat_runner 曾经把 dict 直接塞进 result，
        // 前端直接 `as string` 会得到 object，后续 JSON.parse 会因为隐式 toString
        // 成 "[object Object]" 而失败（典型现象：CodingPlanCard 的 sessionId 解析
        // 为空 → confirm URL 变成 /coding-sessions//confirm/ → 404）。
        // 这里统一把任何非 string 的 result 序列化为 JSON 字符串。
        const normalizeResult = (raw: unknown): string | undefined => {
          if (raw === null || raw === undefined)
            return undefined
          if (typeof raw === 'string')
            return raw
          try {
            return JSON.stringify(raw)
          }
          catch {
            return String(raw)
          }
        }
        const normalizedResult = normalizeResult(event.result)
        const tc = streamingToolCalls.value.find(t => t.id === event.tool_call_id)
        if (tc) {
          if (event.input && Object.keys(event.input as Record<string, unknown>).length > 0)
            tc.input = event.input as Record<string, unknown>
          if (normalizedResult !== undefined)
            tc.result = normalizedResult
          tc.status = 'done'
        }
        const timelineTool = streamingTimeline.value.find((item): item is Extract<StreamTimelineItem, { kind: 'tool' }> =>
          isTimelineToolItem(item) && item.id === event.tool_call_id,
        )
        if (timelineTool) {
          if (event.input && Object.keys(event.input as Record<string, unknown>).length > 0)
            timelineTool.input = event.input as Record<string, unknown>
          if (normalizedResult !== undefined)
            timelineTool.result = normalizedResult
          timelineTool.status = 'done'
          if (event.batch_id && !timelineTool.batch_id)
            timelineTool.batch_id = event.batch_id
        }

        // ：解析跨仓路由 trace 两路径
        //   (a) tool_name === 'analyze_repository_relevance' → 直接读 output.data
        //   (b) tool_name === 'deep_analysis' → 扫描 result 文本中 [cross_repo_relevance:<trace_id>] 段
        if (tc && normalizedResult) {
          maybeParseRoutingTraceFromToolResult({
            toolName: tc.name,
            toolInput: tc.input,
            normalizedResult,
          })
        }

        // ：解析 ask_clarification 工具的 pending payload，
        // upsert 到 pendingClarifications 让 ChatMessageArea 渲染卡片。
        if (tc && tc.name === 'ask_clarification' && normalizedResult) {
          try {
            const parsed = JSON.parse(normalizedResult) as {
              clarification_id?: string
              pending?: boolean
              marker?: string
              question?: string
              options?: Array<{ id: string, label: string, hint?: string, implies?: Record<string, unknown> }>
              allow_freeform?: boolean
            }
            if (
              parsed.pending === true
              && parsed.marker === 'ask_clarification'
              && parsed.clarification_id
            ) {
              upsertClarification({
                clarification_id: parsed.clarification_id,
                question: parsed.question || '',
                options: parsed.options || [],
                allow_freeform: parsed.allow_freeform !== false,
                status: 'pending',
                triggering_message_id: streamingMessageId.value || undefined,
              }, currentConversationId.value ?? undefined)
            }
          }
          catch {
            // 静默：result 不是 JSON / 不含 marker → 不阻塞主流
          }
        }
        break
      }
      case 'message_complete': {
        // 新协议下后端 payload 携带完整 parts snapshot
        // —— 优先用 payload.parts 覆盖 streamingParts（兜底重连 / SSE OOO）
        if (Array.isArray(event.parts) && event.parts.length > 0) {
          streamingParts.value = event.parts.map((p, i) => ({ ...p, index: typeof p.index === 'number' ? p.index : i })) as MessagePart[]
        }
        // deep_analysis 返回结果在 final_answer/result 中（text_delta 被过滤）
        const finalAnswer = event.final_answer || event.result || ''
        if (finalAnswer) {
          streamingContent.value = finalAnswer
        }
        else if (streamingParts.value.length > 0) {
          // 新协议路径：从 parts 派生 content（与后端 PartsCollector.to_message_payload 同源）
          streamingContent.value = streamingParts.value
            .filter((p): p is TextPart => p.type === 'text')
            .map(p => p.text)
            .join('')
        }
        else {
          streamingContent.value = streamingPendingText.value
        }
        // ：deep_analysis 回灌 text 末尾可能含 routing trace 段
        if (currentConversationId.value && typeof streamingContent.value === 'string') {
          maybeParseRoutingTraceFromToolResult({
            toolName: 'deep_analysis',
            toolInput: {},
            normalizedResult: streamingContent.value,
          })
        }
        streamingPendingText.value = ''
        if (event.message_id)
          streamingMessageId.value = event.message_id
        streamingMetadata.value = {
          ...(streamingMetadata.value || {}),
          model: event.model,
          usage: event.usage,
          input_tokens: event.usage?.input_tokens,
          output_tokens: event.usage?.output_tokens,
          cost_usd: event.cost_usd,
          status: event.status,
          // max_turns 用尽时后端走 graceful degrade
          // (status=completed + degraded=true)，把 flag 透传到 metadata
          // 供 UI 差异化展示「已尽力但不完整」，不再当 error 处理。
          degraded: (event as { degraded?: boolean }).degraded,
          degraded_reason: (event as { degraded_reason?: string }).degraded_reason,
        }
        if (event.status === 'interrupted')
          streamingStatus.value = 'interrupted'
        if (event.status === 'budget_exceeded')
          streamingStatus.value = 'budget_exceeded'
        // 重置 phase 感知状态
        currentPhase.value = null
        taskProgress.value = null
        isInterrupting.value = false
        if (interruptTimeout) {
          clearTimeout(interruptTimeout)
          interruptTimeout = null
        }
        // 会话完成时发送浏览器通知（用户已开启且页面不在前台时）
        if (event.status !== 'interrupted')
          _notifyConversationComplete({ isDeepAnalysis: !!deepAnalysisSessionId.value })
        break
      }
      case 'phase_transition':
        currentPhase.value = event.phase || null
        if (event.blocking_task_count != null)
          taskProgress.value = { completed: 0, total: event.blocking_task_count }
        // 284 round 2 Fix C-1：编排层自动构造的 clarification（来自
        // _extract_relev_low_confidence_pending）只走 PHASE_TRANSITION 通道，
        // 不会有 tool_use_result(ask_clarification) 兜底。后端已扩展事件
        // payload 携带 question / options / allow_freeform，前端直接 upsert
        // 即可。LLM 主动调 ask_clarification 工具的路径仍保持原 tool_use_result
        // 兜底（双路径互补，去重靠 clarification_id 唯一）。
        if (
          event.phase === 'waiting_clarification'
          && event.clarification_id
          && typeof event.question === 'string'
          && event.question.length > 0
        ) {
          upsertClarification(
            {
              clarification_id: event.clarification_id,
              question: event.question,
              options: Array.isArray(event.options) ? event.options : [],
              allow_freeform: event.allow_freeform !== false,
              status: 'pending',
              triggering_message_id: streamingMessageId.value || undefined,
            },
            currentConversationId.value ?? undefined,
          )
        }
        break
      case 'task_progress':
        taskProgress.value = { completed: event.completed_count || 0, total: event.total_count || 0 }
        break
      case 'budget_warning':
        budgetWarning.value = event.budget_usage_percent || null
        break
      case 'deep_analysis_progress': {
        const logType = event.log_type || 'info'
        const logContent = event.content || ''
        const sid = event.session_id || ''
        if (sid && !deepAnalysisSessionId.value)
          deepAnalysisSessionId.value = sid
        if (logContent)
          deepAnalysisLogs.value.push({ type: logType, content: logContent, ts: Date.now() })
        break
      }
      case 'title_generated':
        // 更新当前对话标题
        if (event.title) {
          const conv = conversations.value.find(c => c.id === currentConversationId.value)
          if (conv)
            conv.title = event.title
          else if (pendingConversation.value?.id === currentConversationId.value)
            pendingConversation.value = { ...pendingConversation.value, title: event.title }
        }
        break
      case 'doc_summary':
        // 飞书文档摘要事件 -- 存入 streamingMetadata 供 ChatMessageBubble 渲染
        if (!streamingMetadata.value)
          streamingMetadata.value = {}
        streamingMetadata.value.docSummary = {
          type: 'summary' as const,
          title: event.doc_title,
          wordCount: event.word_count,
          preview: event.preview,
          truncated: event.truncated,
          truncatedLength: event.truncated_length,
        }
        break
      case 'doc_error':
        // 飞书文档错误事件 -- 存入 streamingMetadata 供 ChatMessageBubble 渲染
        if (!streamingMetadata.value)
          streamingMetadata.value = {}
        streamingMetadata.value.docSummary = {
          type: 'error' as const,
          errorType: event.error_type,
          errorMessage: event.message,
        }
        break
      case 'coding_progress': {
        codingProgress.value = {
          sessionId: event.coding_session_id || '',
          steps: event.steps || [],
          modifiedFilesCount: event.modified_files_count || 0,
          modifiedFiles: event.modified_files || [],
          recentToolCalls: event.recent_tool_calls || [],
        }
        if (activeCodingSession.value) {
          activeCodingSession.value.status = 'running'
        }
        break
      }
      case 'coding_complete': {
        codingResult.value = {
          sessionId: event.coding_session_id || '',
          prUrl: event.pr_url || '',
          branchName: event.branch_name || '',
          modifiedFilesCount: event.modified_files_count || 0,
          branchUrl: event.branch_url || '',
        }
        if (activeCodingSession.value) {
          activeCodingSession.value.status = 'completed'
        }
        isStreaming.value = false
        break
      }
      case 'coding_failed': {
        codingError.value = {
          sessionId: event.coding_session_id || '',
          errorMessage: event.message || '编码失败',
        }
        if (activeCodingSession.value) {
          activeCodingSession.value.status = 'failed'
        }
        isStreaming.value = false
        break
      }
      case 'awaiting_commit_confirm': {
        if (activeCodingSession.value) {
          activeCodingSession.value.status = 'awaiting_confirmation'
          activeCodingSession.value.confirmationStep = 'commit_message'
        }
        commitConfirmData.value = {
          suggestedCommitMessage: event.suggested_commit_message || '',
          conflictCheck: null,
        }
        // 恢复输入框（非 streaming 态）
        isStreaming.value = false
        break
      }
      case 'awaiting_pr_review': {
        if (activeCodingSession.value) {
          activeCodingSession.value.status = 'awaiting_confirmation'
          activeCodingSession.value.confirmationStep = 'pr_review'
        }
        prConfirmData.value = {
          suggestedPrTitle: event.suggested_pr_title || '',
          suggestedPrDescription: event.suggested_pr_description || '',
          targetBranch: event.target_branch || 'main',
          branchUrl: event.branch_url || '',
        }
        isStreaming.value = false
        break
      }
      case 'conflict_check': {
        if (commitConfirmData.value) {
          commitConfirmData.value.conflictCheck = {
            has_conflicts: event.has_conflicts,
            conflicting_files: event.conflicting_files,
            behind_by: event.behind_by,
            suggestion: event.suggestion,
          }
        }
        break
      }
      case 'error': {
        // ：SSE ERROR 结构化 payload 分派。
        // Pitfall 3 向后兼容：event.code 不存在时走 fallback 到既有 error.value。
        const code = (event as unknown as { code?: string }).code
        const data = (event as unknown as { data?: Record<string, unknown> }).data
        if (code === 'context_window_exceeded' && data) {
          lastContextExceeded.value = {
            estimated_tokens: Number(data.estimated_tokens ?? 0),
            max_tokens: Number(data.max_tokens ?? 0),
            exceeded_by: Number(data.exceeded_by ?? 0),
            model: String(data.model ?? ''),
            recommended_actions: Array.isArray(data.recommended_actions)
              ? (data.recommended_actions as ContextExceededPayload['recommended_actions'])
              : [],
          }
        }
        else {
          // provider_credential_missing 由 preflight 端点覆盖；
          // 其他未知 code 沿用旧行为（error toast 路径）
          error.value = event.message || '未知错误'
        }
        break
      }
      default:

        console.warn('[Chat] 收到未知 SSE 事件类型:', event.type, event)
        break
    }
  }

  /**
   * 确认编码方案 — 调用 confirm API 并启动 runtime 轮询
   */
  async function handleConfirmCodingSession(
    sessionId: string,
    branchName?: string,
    targetBranch?: string,
  ) {
    if (!currentConversationId.value)
      return
    if (activeCodingSession.value?.isConfirming)
      return

    // 乐观 UI: 立即显示 loading
    activeCodingSession.value = {
      sessionId,
      status: 'confirmed',
      isConfirming: true,
    }

    try {
      const result = (branchName || targetBranch)
        ? await apiConfirmCodingSessionWithBranch(sessionId, branchName, targetBranch)
        : await apiConfirmCodingSession(sessionId)
      activeCodingSession.value = {
        sessionId: result.id,
        status: result.status as 'draft' | 'confirmed' | 'running' | 'awaiting_confirmation' | 'completed' | 'failed',
        isConfirming: false,
      }

      // 编码 running 期间禁用输入
      isStreaming.value = true

      // 启动 runtime 轮询（与 deep_analysis 模式一致）
      scheduleRuntimePoll(currentConversationId.value, 3000)
    }
    catch (err) {
      // 回滚
      activeCodingSession.value = {
        sessionId,
        status: 'draft',
        isConfirming: false,
      }
      error.value = err instanceof Error ? err.message : '确认失败'
    }
  }

  function buildUserInputParts(content: string, imageParts: ImagePart[] = []): MessagePart[] | undefined {
    if (imageParts.length === 0)
      return undefined
    const parts: MessagePart[] = []
    if (content) {
      parts.push({
        type: 'text',
        id: randomUUID(),
        index: 0,
        text: content,
        state: 'done',
      })
    }
    const baseIndex = parts.length
    imageParts.forEach((part, offset) => {
      parts.push({
        ...part,
        index: baseIndex + offset,
      })
    })
    return parts
  }

  async function sendMessage(content: string, feishuDocId?: string, inputParts?: ImagePart[]) {
    if (isStreaming.value)
      return

    let materializedConversation: Conversation | null = null
    let createdForDraft = false

    // 注意：此处不置 loading —— loading 仅供侧边栏会话列表骨架屏使用，
    // 草稿首条消息创建会话时若置 loading，会话列表会闪一次骨架屏（页面抖动）。
    if (!currentConversationId.value) {
      try {
        // space_id 可空：未选空间时创建「通用对话」，任务涉及空间知识时由
        // AI（system prompt 引导）要求用户先选择空间
        materializedConversation = await createConversation({
          space_id: selectedSpaceId.value || null,
          model: resolveModelForNewConversation(),
          ...(boundProjectId.value ? { bound_project_id: boundProjectId.value } : {}),
        })
        pendingConversation.value = materializedConversation
        currentConversationId.value = materializedConversation.id
        // 立刻把会话 id 同步到 URL —— 必须发生在 SSE 流启动之前。
        // 否则用户在流式期间刷新页面，URL 退回到草稿空页（restoreFromURL 拿不到 id），
        // 被迫从侧栏点「运行中」对话回去；而此时 SSE 已经断、后端任务可能还没结束，
        // restoreConversationRuntime 看到 active=true 直接进 polling 等待，UI 一直
        // 是空 bubble + "正在整理回答..."。先 syncURL 才能让刷新无损 resume。
        syncConversationToURL(materializedConversation.id)
        createdForDraft = true

        if (selectedCredentialModel.value) {
          const parts = selectedCredentialModel.value.split('::')
          if (parts.length === 2)
            await patchConversationProviderAndModel(parts[0], parts[1])
        }
      }
      catch (e) {
        error.value = e instanceof Error ? e.message : '创建对话失败'
        if (materializedConversation) {
          try {
            await deleteConversation(materializedConversation.id)
          }
          catch {
            // 创建后的模型绑定失败时尽力清理后端空会话。
          }
        }
        pendingConversation.value = null
        currentConversationId.value = null
        syncConversationToURL(null)
        return
      }
    }

    const conversationId = currentConversationId.value
    if (!conversationId)
      return

    stopRuntimePolling()

    // 清除之前的流式状态
    streamingContent.value = ''
    streamingThinking.value = ''
    streamingToolCalls.value = []
    streamingTimeline.value = []
    streamingMessageId.value = ''
    streamingMetadata.value = null
    streamingNarrations.value = []
    streamingPendingText.value = ''
    streamingParts.value = []
    deepAnalysisLogs.value = []
    deepAnalysisSessionId.value = null
    deepAnalysisSessions.value = []
    error.value = null
    lastFailedContent.value = null
    // 重置 phase / restored runtime 痕迹 —— 否则刷新场景下 restoreConversationRuntime
    // 残留的 currentPhase=waiting / restoredRuntimeConversationId 会让本次发消息的
    // finally 走 waiting 早退分支（误以为是后台异步任务），导致流式内容永远不会
    // 合并到 messages，UI 永久 stuck 在空 bubble + "正在整理回答..." 状态条。
    currentPhase.value = null
    taskProgress.value = null
    restoredRuntimeConversationId.value = null
    streamingStatus.value = null

    // 添加用户消息到列表（乐观更新）
    const userInputParts = buildUserInputParts(content, inputParts || [])
    const userMessage: ConversationMessage = {
      id: randomUUID(),
      role: 'user',
      content,
      parts: userInputParts,
      created_at: new Date().toISOString(),
    }
    messages.value.push(userMessage)

    // 启动 SSE 流
    isStreaming.value = true
    const controller = new AbortController()
    abortController.value = controller
    // 本流独立的 run_id（按流持有，避免并发流互相覆盖；替代模块级 getCurrentRunId）
    const streamRunIdRef: { value: string | null } = { value: null }
    // 串流隔离：事件回写以发起会话为权威归属，由 handleSSEEvent 守护是否写当前 UI。
    const ownerConversationId = conversationId

    try {
      // 检索分支由 backend 自动按 base branch 选取，前端不再传 branch 字段
      // （历史 的检索分支 picker 已下线——用户从未感知多分支语义，
      // 选择面板反而误导成"每条消息可换分支"）。
      await connectSSE(
        conversationId,
        content,
        selectedRole.value,
        (event: SSEEvent) => handleSSEEvent(event, ownerConversationId),
        controller.signal,
        {
          forceDeepAnalysis: forceDeepAnalysis.value,
          feishuDocId,
          inputParts: userInputParts,
          onRunId: (id) => { streamRunIdRef.value = id },
        },
      )
    }
    catch (e) {
      if ((e as Error).name !== 'AbortError') {
        // SSE 断线恢复：连接异常但流仍在后端执行时，切换到 runtime 轮询。
        // 仅当用户仍停留在发起会话时才轮询当前会话（切走则后台由 DB finalize）。
        const runId = streamRunIdRef.value
        if (runId && !streamingContent.value) {
          if (ownerConversationId === currentConversationId.value)
            scheduleRuntimePoll(conversationId, 1000)
          return
        }
        // 错误仅在用户仍在发起会话时写当前 UI，避免把 A 的错误显示到 B。
        if (ownerConversationId === currentConversationId.value)
          error.value = friendlyStreamError(e)
      }
    }
    finally {
      // 串流隔离：用户是否仍停留在发起本次流式的会话。切走后，所有「写当前 UI」
      // 的收尾（merge 到 messages / 轮询当前会话 / 重置 streaming / 写 error）都
      // 跳过；后端已 finalize 落库，切回时由 selectConversation/runtime 恢复。
      // 草稿会话提升到侧栏列表（list 级，不触当前视图）仍无条件执行。
      const isCurrent = ownerConversationId === currentConversationId.value
      if (isCurrent) {
        isStreaming.value = false
        abortController.value = null
      }

      // —— 草稿会话收尾（最先处理，且必须早于「waiting → scheduleRuntimePoll + return」
      //     的早退逻辑；否则下面的 return 会跳过 pendingConversation 提升，
      //     deep_analysis 等 waiting 路径首次发送时侧栏看不到新对话）。
      //
      //   * 成功（有任何流响应 / waiting 后台接管）→ 把 pendingConversation
      //     提升到 conversations 列表，不再清 pending 之外的状态。
      //   * 首条消息失败（如模型不支持图片）→ **不再删除草稿会话**：保留它并
      //     提升到侧栏（草稿态），让用户能在会话内换模型后直接重发（输入框文本/
      //     图片由 ChatInput 在失败时保留）。早期版本会删掉刚建的草稿，导致
      //     「图片对话发失败 → 刷新就没了」的体验问题。
      const hadStreamingResponse
        = !!streamingContent.value
          || streamingToolCalls.value.length > 0
          || currentPhase.value === 'waiting'
          || currentPhase.value === 'waiting_clarification'
      if (createdForDraft) {
        const committed = pendingConversation.value ?? materializedConversation
        if (committed && !conversations.value.some(c => c.id === committed.id))
          conversations.value.unshift(committed)
        pendingConversation.value = null
        // 首条失败：记录失败内容供「重试」按钮使用，并短路掉下面 waiting / merge
        // 逻辑（无任何流内容，避免把空消息塞进 messages）；会话本身保留为草稿。
        // 仅在用户仍停留发起会话时写当前 UI（串流隔离）。
        if (isCurrent && error.value && !hadStreamingResponse) {
          lastFailedContent.value = content
          messages.value = messages.value.filter(m => m.id !== userMessage.id)
          resetStreamingState()
          return
        }
      }

      // 串流隔离：用户已切到其他会话 —— 不写当前 UI（merge/poll/reset/error 全跳过）。
      // 后端已 finalize 落库，切回发起会话时由 selectConversation/runtime 恢复内容。
      if (!isCurrent)
        return

      // ↓↓↓ 以下保持 legacy 之前的 finally 结构不变（流式合并 / waiting 早退）↓↓↓

      // graph 进入 WAITING（deep_analysis/coding 进行中）或
      // WAITING_CLARIFICATION（等用户答复澄清卡）后 SSE 正常结束，
      // 需要启动 runtime 轮询来恢复并跟踪后续状态 —— 否则用户提交澄清答复、
      // 后端 resume graph 之后，前端没有任何通道感知 phase/消息变化。
      if (
        (currentPhase.value === 'waiting' || currentPhase.value === 'waiting_clarification')
        && currentConversationId.value
      ) {
        scheduleRuntimePoll(currentConversationId.value, 1000)
        return
      }

      // 错误时：记录失败内容用于重试，移除乐观更新的用户消息
      if (error.value && !streamingContent.value) {
        lastFailedContent.value = content
        messages.value = messages.value.filter(m => m.id !== userMessage.id)
      }

      // 流结束后，将流式内容合并为正式消息
      if (streamingContent.value || streamingToolCalls.value.length > 0 || streamingParts.value.length > 0) {
        const finalMetadata: Record<string, unknown> = {
          ...(streamingMetadata.value || {}),
          ...(streamingStatus.value ? { status: streamingStatus.value } : {}),
        }
        // 持久化 thinking 内容
        if (streamingThinking.value)
          finalMetadata.thinking = streamingThinking.value
        // 持久化 narrations（工具调用间的叙述文本）
        if (streamingNarrations.value.length > 0)
          finalMetadata.narrations = [...streamingNarrations.value]
        if (streamingTimeline.value.length > 0)
          finalMetadata.timeline = [...streamingTimeline.value]
        // 持久化 tool calls 的 result
        if (streamingToolCalls.value.length > 0) {
          finalMetadata.tool_results = streamingToolCalls.value
            .filter(tc => tc.result)
            .map(tc => ({ id: tc.id, result: tc.result }))
        }

        // 从 streamingParts 派生 tool_calls 兼容字段
        // （与后端 PartsCollector.to_message_payload 同源算法）
        const partsToolCalls = streamingParts.value
          .filter((p): p is ToolUsePart => p.type === 'tool_use')
          .map(p => ({
            id: p.tool_call_id,
            name: p.name,
            input: p.input,
            result: p.result ?? undefined,
            status: (p.status === 'running' ? 'running' : 'done') as 'running' | 'done',
          }))
        const mergedToolCalls = partsToolCalls.length > 0
          ? partsToolCalls
          : (streamingToolCalls.value.length > 0
              ? streamingToolCalls.value.map(tc => ({
                  id: tc.id,
                  name: tc.name,
                  input: tc.input,
                  result: tc.result,
                  status: tc.status,
                }))
              : undefined)

        const assistantMessage: ConversationMessage = {
          id: streamingMessageId.value || randomUUID(),
          role: 'assistant',
          content: streamingContent.value,
          tool_calls: mergedToolCalls,
          // 持久化 parts 数组（与 content / tool_calls 三同源）
          parts: streamingParts.value.length > 0 ? [...streamingParts.value] : undefined,
          metadata: Object.keys({
            ...finalMetadata,
            ...(deepAnalysisLogs.value.length > 0 ? { deep_analysis_logs: [...deepAnalysisLogs.value] } : {}),
            ...(deepAnalysisSessionId.value ? { deep_analysis_session_id: deepAnalysisSessionId.value } : {}),
            ...(deepAnalysisSessions.value.length > 0 ? { deep_analysis_sessions: [...deepAnalysisSessions.value] } : {}),
          }).length > 0
            ? {
                ...finalMetadata,
                ...(deepAnalysisLogs.value.length > 0 ? { deep_analysis_logs: [...deepAnalysisLogs.value] } : {}),
                ...(deepAnalysisSessionId.value ? { deep_analysis_session_id: deepAnalysisSessionId.value } : {}),
                ...(deepAnalysisSessions.value.length > 0 ? { deep_analysis_sessions: [...deepAnalysisSessions.value] } : {}),
              }
            : undefined,
          created_at: new Date().toISOString(),
        }
        messages.value.push(assistantMessage)
        resetStreamingState()
      }
      else {
        resetStreamingState()
      }
    }
  }

  async function editMessageAndFork(
    messageId: string,
    content: string,
    images?: ImagePart[],
  ) {
    const trimmed = content.trim()
    if (!currentConversationId.value) {
      error.value = '当前没有活动对话，无法编辑历史提问'
      return
    }
    if (isStreaming.value) {
      error.value = '当前正在生成回复，请稍后再编辑历史提问'
      return
    }
    if (!trimmed && (!images || images.length === 0)) {
      error.value = '编辑后的内容不能为空'
      return
    }

    const sourceConversationId = currentConversationId.value
    // 同 sendMessage：不置 loading，避免编辑提问时侧边栏会话列表闪骨架屏
    error.value = null
    try {
      const forked = await forkConversationForMessage(sourceConversationId, messageId, {
        content: trimmed,
      })
      resetForkRuntimeState()
      pendingConversation.value = null
      currentConversationId.value = forked.id
      syncConversationToURL(forked.id)
      messages.value = [...forked.messages]
      upsertConversationAtTop(forked)
      // 纯图片（无文字）时给 sendMessage 一个兜底文案，与 ChatInput 行为一致
      await sendMessage(trimmed || '请分析这张图片', undefined, images)
    }
    catch (e) {
      error.value = e instanceof Error ? e.message : '编辑历史提问失败'
      throw e
    }
  }

  async function retryLastMessage() {
    if (!lastFailedContent.value)
      return
    const content = lastFailedContent.value
    lastFailedContent.value = null
    error.value = null
    await sendMessage(content)
  }

  // ========================================================================
  // URL 路由 — 对话 ID 持久化到地址栏
  // ========================================================================

  function syncConversationToURL(id: string | null) {
    const url = new URL(window.location.href)
    if (id) {
      url.searchParams.set('conversation', id)
    }
    else {
      url.searchParams.delete('conversation')
    }
    window.history.replaceState({}, '', url.toString())
  }

  async function restoreFromURL() {
    const url = new URL(window.location.href)
    const convId = url.searchParams.get('conversation')
    if (convId && convId !== currentConversationId.value) {
      await selectConversation(convId)
    }
  }

  // ========================================================================
  // 浏览器通知
  // ========================================================================

  function requestNotificationPermission() {
    if (notificationsEnabled.value)
      void requestAndEnableWebPush().catch(() => false)
  }

  async function toggleNotifications(enabled: boolean) {
    if (!enabled) {
      notificationsEnabled.value = false
      const { disableWebPush } = useWebPush()
      await disableWebPush()
      return
    }

    if (!('Notification' in window)) {
      notificationsEnabled.value = false
      return
    }

    if (Notification.permission === 'default') {
      const permission = await Notification.requestPermission()
      if (permission !== 'granted') {
        notificationsEnabled.value = false
        return
      }
    }
    else if (Notification.permission !== 'granted') {
      notificationsEnabled.value = false
      return
    }

    notificationsEnabled.value = true
    // Web Push 尽力注册；失败时仍保留本地 Notification 能力
    await requestAndEnableWebPush().catch(() => false)
  }

  function _notifyConversationComplete(options?: { isDeepAnalysis?: boolean }) {
    if (!notificationsEnabled.value)
      return
    // Web Push 已就绪时由 Service Worker 接收服务端推送，避免重复弹窗
    if (webPushReady.value)
      return
    if (!('Notification' in window) || Notification.permission !== 'granted')
      return
    if (document.visibilityState === 'visible' && document.hasFocus())
      return

    const isDeepAnalysis = options?.isDeepAnalysis ?? false
    const conv = conversations.value.find(c => c.id === currentConversationId.value)
    const title = conv?.title || '对话'
    const n = new Notification(isDeepAnalysis ? '深度分析完成' : 'AI 回复完成', {
      body: isDeepAnalysis
        ? `「${title}」的深度分析已完成，点击查看结果`
        : `「${title}」已有新回复，点击查看`,
      icon: '/favicon.ico',
      tag: `chat-complete-${currentConversationId.value || 'chat'}`,
    })
    n.onclick = () => {
      window.focus()
      n.close()
    }
  }

  // ========================================================================
  // 导出到飞书
  // ========================================================================

  /** 进入多选导出模式，默认选中最近一轮 AI 回答 (per D-01) */
  function enterExportSelectMode() {
    isExportSelectMode.value = true
    selectedMessageIds.value = new Set()
    // 默认选中最近一条 assistant 消息
    const lastAssistant = [...messages.value]
      .reverse()
      .find(m => m.role === 'assistant')
    if (lastAssistant) {
      selectedMessageIds.value.add(lastAssistant.id)
    }
  }

  /** 退出多选导出模式 */
  function exitExportSelectMode() {
    isExportSelectMode.value = false
    selectedMessageIds.value = new Set()
  }

  /** 切换消息选中状态 (per D-03: 仅 assistant 可选) */
  function toggleMessageSelect(messageId: string) {
    const msg = messages.value.find(m => m.id === messageId)
    if (!msg || msg.role !== 'assistant')
      return
    const next = new Set(selectedMessageIds.value)
    if (next.has(messageId)) {
      next.delete(messageId)
    }
    else {
      next.add(messageId)
    }
    selectedMessageIds.value = next
  }

  /** 全选所有 AI 回答 (per D-02) */
  function selectAllAssistant() {
    const ids = messages.value
      .filter(m => m.role === 'assistant')
      .map(m => m.id)
    selectedMessageIds.value = new Set(ids)
  }

  /** 执行导出到飞书 */
  async function doExportToFeishu(
    title: string,
    messageIds: string[],
    folderToken?: string,
  ): Promise<ExportToFeishuResponse> {
    if (!currentConversationId.value) {
      throw new Error('没有活动对话')
    }
    const data: ExportToFeishuRequest = {
      message_ids: messageIds,
      title,
      ...(folderToken ? { folder_token: folderToken } : {}),
    }
    return exportToFeishu(currentConversationId.value, data)
  }

  /**
   * ：导出 CodingPlan 到飞书，并把 doc_token / doc_url
   * 立即 patch 到本地 store 的 activeCodingPlan，避免要等下一次 polling。
   */
  async function doExportCodingPlanToFeishu(
    codingPlanId: string,
    title?: string,
    folderToken?: string,
  ): Promise<ExportCodingPlanToFeishuResponse> {
    const payload: ExportCodingPlanToFeishuRequest = {}
    if (title)
      payload.title = title
    if (folderToken)
      payload.folder_token = folderToken
    const result = await exportCodingPlanToFeishu(codingPlanId, payload)

    if (
      activeCodingPlan.value
      && activeCodingPlan.value.plan_id === codingPlanId
    ) {
      activeCodingPlan.value = {
        ...activeCodingPlan.value,
        feishu_doc_token: result.doc_token,
        feishu_doc_url: result.doc_url,
      }
    }
    return result
  }

  /**
   * ：对话凭证前置探测。
   *
   * 调用 GET /api/chat/conversations/{id}/preflight/：
   *   - 成功（200 status=ok）→ 清空 credentialMissingPayload，返回 true
   *   - 失败（400 code=provider_credential_missing）→ 写入 payload，返回 false
   *   - 其他错误 → 抛出，由 caller 走 ChatErrorCard（既有路径，D-06 non-provider_credential_missing 不归本 Card）
   */
  async function preflightConversation(conversationId: string): Promise<boolean> {
    try {
      await apiGet(`/chat/conversations/${conversationId}/preflight/`)
      credentialMissingPayload.value = null
      return true
    }
    catch (e) {
      if (e instanceof ApiError && e.status === 400) {
        const body = e.body as { code?: string, data?: Record<string, unknown> } | null
        if (body && body.code === 'provider_credential_missing' && body.data) {
          credentialMissingPayload.value = {
            missingProvider: String(body.data.missing_provider ?? '') as ProviderType,
            scopeAttempted: String(body.data.scope_attempted ?? 'system'),
            recommendedAction: String(body.data.recommended_action ?? ''),
          }
          return false
        }
      }
      throw e
    }
  }

  /** 清空 credentialMissingPayload（用户切到其他对话 / 手动关闭 Card 时调用）。 */
  function clearCredentialMissingPayload(): void {
    credentialMissingPayload.value = null
  }

  /** ：清空 lastContextExceeded（对话切换 / 清理历史后调用）。 */
  function resetContextExceeded(): void {
    lastContextExceeded.value = null
  }

  // ==========================================================================
  // / ：仓库多选 modal 状态机 + 批量创建 actions
  // ==========================================================================

  function openRepoMultiSelector(planId: string, preselectedIds: string[] = []): void {
    repoMultiSelectorState.value = {
      open: true,
      planId,
      preselectedIds: [...preselectedIds],
      submitting: false,
    }
  }

  function closeRepoMultiSelector(): void {
    repoMultiSelectorState.value = {
      open: false,
      planId: null,
      preselectedIds: [],
      submitting: false,
    }
  }

  /**
   * FAN-03：提交多选 → 调 createSessionsForPlan endpoint。不主动更新
   * activeCodingPlan，等下一次 pollConversationRuntime 自然刷新。
   */
  async function submitRepoMultiSelector(
    repositoryIds: string[],
    branchTemplate?: string,
    targetBranch?: string,
  ): Promise<{
    createdCount: number
    failedCount: number
    /**
     * coding-plan workflow fan-out endpoint 拒绝时第一条失败原因，
     * 给 UI toast 用，避免每次都得让用户开 DevTools 看 response。
     */
    firstFailedError?: string
  }> {
    const planId = repoMultiSelectorState.value.planId
    if (!planId)
      throw new Error('planId 缺失')
    repoMultiSelectorState.value.submitting = true
    try {
      const resp = await createSessionsForPlan(planId, {
        repository_ids: repositoryIds,
        branch_template: branchTemplate,
        target_branch: targetBranch,
      })
      for (const item of resp.created) {
        const confirmed = await apiConfirmCodingSession(item.session_id)
        activeCodingSession.value = {
          sessionId: confirmed.id,
          status: confirmed.status as 'draft' | 'confirmed' | 'running' | 'awaiting_confirmation' | 'completed' | 'failed',
          isConfirming: false,
        }
      }
      if (resp.created.length > 0 && currentConversationId.value) {
        isStreaming.value = true
        scheduleRuntimePoll(currentConversationId.value, 3000)
      }
      return {
        createdCount: resp.created.length,
        failedCount: resp.failed.length,
        firstFailedError: resp.failed[0]?.error,
      }
    }
    finally {
      repoMultiSelectorState.value.submitting = false
    }
  }

  /**
   * FAN-04：对单个 repository 重新发起编码（复用 FAN-02 endpoint）。
   * FAN-01 unique 约束允许（旧 failed session 是非 active 状态保留作历史）。
   */
  async function retrySingleRepository(
    planId: string,
    repositoryId: string,
  ): Promise<{ createdCount: number, failedCount: number }> {
    const prevState = repoMultiSelectorState.value
    repoMultiSelectorState.value = {
      open: false,
      planId,
      preselectedIds: [repositoryId],
      submitting: true,
    }
    try {
      return await submitRepoMultiSelector([repositoryId])
    }
    finally {
      repoMultiSelectorState.value = prevState
    }
  }

  /**
   * 109-04：把编排产出的方案版本惰性投影为 chat CodingPlan（SPINE-01 前端半边）。
   *
   * 只做三件事：调端点、排一次 runtime polling 让 sessions 状态跟上、原样返回响应。
   * 刻意**不**手工拼 `activeCodingPlan` —— 前端不得自行构造 CodingPlan 业务字段，
   * 且手工写入会与 runtime 刷新竞态；卡片的即时数据由投影响应直接喂 props 承担。
   * 错误不吞，交给组件走 toast。
   */
  async function projectPlanToCodingPlan(
    artifactVersionId: string,
  ): Promise<ProjectPlanToCodingResponse> {
    const resp = await projectArtifactVersionToCodingPlan(artifactVersionId)
    if (currentConversationId.value)
      scheduleRuntimePoll(currentConversationId.value, 3000)
    return resp
  }

  // ========================================================================
  // ：协商卡片 actions
  // ========================================================================

  function getClarification(id: string): ClarificationPayload | undefined {
    return pendingClarifications.value.get(id)
  }

  /**
   * UAT 2026-05-27 hotfix（284 round 2）：协商卡片写入时绑定 conversation 维度。
   *
   * `conversationId` 显式可选，调用方应当传当前 chat 上下文的 conversation id
   * （SSE handler 取 `currentConversationId.value`）。当 caller 未传时，回退到
   * 当前 conversation —— 既不破坏既有调用契约，也保证全部 upsert 都带 conv 维度。
   *
   * 与 `ChatMessageArea` 的 `currentConversationId` 过滤配合，防止跨会话串单。
   */
  /**
   * 计算「当前最后一条已落库消息」的 id，作为澄清卡片的内联锚点兜底。
   * 卡片按锚点内联在消息流中：答复后 resume 产出的新消息在卡片下方继续，
   * 卡片不会跳到整个会话最底部（交互直觉：沿着澄清位置往下走）。
   */
  function lastPersistedMessageId(): string {
    const list = messages.value
    return list.length > 0 ? list[list.length - 1].id : ''
  }

  function upsertClarification(payload: ClarificationPayload, conversationId?: string) {
    const conv = conversationId ?? payload.conversation_id ?? currentConversationId.value ?? undefined
    const existing = pendingClarifications.value.get(payload.clarification_id)
    pendingClarifications.value.set(payload.clarification_id, {
      ...payload,
      conversation_id: conv,
      // 锚点只取首次写入时的位置（re-upsert / 回灌不重算，避免锚点漂到新消息之后）。
      anchor_message_id:
        existing?.anchor_message_id || payload.anchor_message_id || lastPersistedMessageId(),
      triggering_message_id: payload.triggering_message_id || existing?.triggering_message_id,
    })
  }

  function markClarificationAnswered(id: string, answer: ClarificationAnswer) {
    const existing = pendingClarifications.value.get(id)
    if (!existing)
      return
    pendingClarifications.value.set(id, {
      ...existing,
      status: 'answered',
      answer,
      // 固化锚点为「答复时刻的最后一条消息」：resume 产出的新消息渲染在卡片下方，
      // 卡片留在原位（不跳最底部）。
      anchor_message_id: lastPersistedMessageId() || existing.anchor_message_id,
    })
    // 答复后后端在后台 resume graph 继续推理 —— 立刻 kick 一次 runtime 轮询，
    // 让状态条/消息能及时跟上 resume 进度（不依赖既有轮询是否在跑）。
    const convId = existing.conversation_id ?? currentConversationId.value
    if (convId && convId === currentConversationId.value)
      scheduleRuntimePoll(convId, 800)
  }

  function clearAllClarifications() {
    pendingClarifications.value = new Map()
    pendingPlanClarifications.value = new Map()
  }

  // ========================================================================
  // ：plan 结构化澄清（多题 + 多选）actions —— 与 chat 单题澄清物理隔离
  // ========================================================================

  function getPlanClarification(id: string): PlanClarificationPayload | undefined {
    return pendingPlanClarifications.value.get(id)
  }

  /**
   * 写入/更新 plan 多题澄清轮，绑定 conversation 维度（mirror upsertClarification
   * 防污染范式）。`conversationId` 缺省时回退当前会话上下文，保证带 conv 维度。
   */
  function upsertPlanClarification(payload: PlanClarificationPayload, conversationId?: string) {
    const conv = conversationId ?? payload.conversation_id ?? currentConversationId.value ?? undefined
    const existing = pendingPlanClarifications.value.get(payload.clarification_id)
    pendingPlanClarifications.value.set(payload.clarification_id, {
      ...payload,
      conversation_id: conv,
      // 同 upsertClarification：锚点只取首次写入时的位置，供消息流内联渲染。
      anchor_message_id:
        existing?.anchor_message_id || payload.anchor_message_id || lastPersistedMessageId(),
    })
  }

  /**
   * 提交 plan 多题答复后切「已回复」态。提交本身由组件调 api，store 只负责
   * 状态机 + kick 一次 runtime 轮询跟上后台续推（mirror markClarificationAnswered）。
   */
  function markPlanClarificationAnswered(id: string) {
    const existing = pendingPlanClarifications.value.get(id)
    if (!existing)
      return
    pendingPlanClarifications.value.set(id, {
      ...existing,
      status: 'answered',
      // 同 markClarificationAnswered：固化锚点，答复后新消息沿卡片下方继续。
      anchor_message_id: lastPersistedMessageId() || existing.anchor_message_id,
    })
    const convId = existing.conversation_id ?? currentConversationId.value
    if (convId && convId === currentConversationId.value)
      scheduleRuntimePoll(convId, 800)
  }

  /**
   * 跳过当前等待中的澄清提问（兜底出口）。
   *
   * 适配 waiting_clarification 卡死场景：卡片漏发 / 用户不想答时，调后端
   * 按 conversation 维度跳过，注入「跳过」指令让 LLM 基于现有信息直接作答。
   * 乐观更新：移除待答卡片 + 进入「正在执行」过渡态，并 kick 一次 runtime
   * 轮询拿 resume 后的最终回答（不依赖既有轮询是否在跑）。
   */
  async function skipClarification() {
    const convId = currentConversationId.value
    if (!convId)
      return
    try {
      const resp = await apiSkipClarification(convId)
      // no_pending：后端判定无等待中的 clarification（可能已被答复/已 resume），
      // 仅清掉本地残留卡片，不强行改 phase。
      if (resp.status === 'no_pending') {
        pendingClarifications.value = new Map()
        return
      }
    }
    catch (e) {
      error.value = e instanceof Error ? e.message : '跳过失败，请重试'
      return
    }
    // 乐观更新：移除待答卡片 + 进入恢复执行过渡态，等待后台 resume 产出结果。
    pendingClarifications.value = new Map()
    currentPhase.value = 'executing'
    restoredRuntimeConversationId.value = convId
    scheduleRuntimePoll(convId, 1200)
  }

  // ========================================================================
  // 实时同步（WebSocket）—— 项目共享会话多用户实时一致
  // ------------------------------------------------------------------------
  // 连接 ws/chat/（鉴权同 notifications，握手自动带 HTTP-only JWT cookie）。本人自动
  // 加入 user 分组（自有会话事件）；项目作用域下额外订阅 project 分组（成员可见共享会话）。
  // 后端在「新建 / 进行中 / 新消息 / 完成」广播，这里并进 conversations / messages。
  // best-effort：失败指数退避重连，绝不阻断 REST/SSE 主链路。
  // ========================================================================
  let chatWs: WebSocket | null = null
  let chatWsRetry = 0
  let chatWsRetryTimer: ReturnType<typeof setTimeout> | null = null

  function chatRealtimeUrl(): string {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${proto}//${location.host}/ws/chat/`
  }

  function sendProjectSubscription() {
    const pid = boundProjectId.value
    if (pid && chatWs && chatWs.readyState === WebSocket.OPEN)
      chatWs.send(JSON.stringify({ action: 'subscribe_project', project_id: pid }))
  }

  function applyRealtimeConversation(conv: Conversation, _event?: string) {
    // 项目作用域：只接受本项目会话，避免本人在别处的会话串进当前项目列表。
    if (boundProjectId.value && (conv as any).bound_project_id !== boundProjectId.value)
      return
    const idx = conversations.value.findIndex(c => c.id === conv.id)
    if (idx >= 0)
      conversations.value[idx] = { ...conversations.value[idx], ...conv }
    else
      conversations.value = [conv, ...conversations.value]
  }

  function applyRealtimeMessage(evt: { conversation_id?: string, conversation_status?: string, message?: ConversationMessage }) {
    const cid = evt.conversation_id
    if (!cid)
      return
    // 同步列表项状态（运行中/完成圆点实时变化）+ 置顶。
    const idx = conversations.value.findIndex(c => c.id === cid)
    if (idx >= 0) {
      const updated = { ...conversations.value[idx], ...(evt.conversation_status ? { status: evt.conversation_status as Conversation['status'] } : {}) }
      conversations.value.splice(idx, 1)
      conversations.value = [updated, ...conversations.value]
    }
    // 旁观者打字机收尾：本端非发起者(abortController 为空)但处于流式态(WS 驱动)，
    // 收到最终消息时先清掉打字机气泡，再按 id 去重追加正式消息。发起者(abortController
    // 非空)不动，靠 SSE/finalize 自行合并。
    if (cid === currentConversationId.value && evt.message?.id) {
      if (isStreaming.value && !abortController.value)
        resetStreamingState()
      if (!isStreaming.value && !messages.value.some(m => m.id === evt.message!.id))
        messages.value.push(evt.message)
    }
  }

  function applyRealtimeStream(evt: { conversation_id?: string, payload?: any }) {
    const cid = evt.conversation_id
    // 只渲染当前查看会话的流；发起者本人靠 SSE，跳过 WS 回声。
    if (!cid || cid !== currentConversationId.value || abortController.value)
      return
    const payload = evt.payload
    if (!payload || !payload.type)
      return
    // 旁观者收到首个流事件 → 进入流式态（清掉上一轮残留），后续复用同一 SSE 分派。
    if (!isStreaming.value) {
      resetStreamingState()
      isStreaming.value = true
    }
    handleSSEEvent(payload)
  }

  function handleRealtimeRaw(raw: string) {
    let msg: any
    try {
      msg = JSON.parse(raw)
    }
    catch {
      return
    }
    if (msg.type === 'conversation' && msg.conversation)
      applyRealtimeConversation(msg.conversation as Conversation, msg.event)
    else if (msg.type === 'message')
      applyRealtimeMessage(msg)
    else if (msg.type === 'stream')
      applyRealtimeStream(msg)
  }

  function connectRealtime() {
    if (typeof window === 'undefined' || typeof WebSocket === 'undefined')
      return
    if (chatWs && chatWs.readyState <= WebSocket.OPEN) {
      sendProjectSubscription()
      return
    }
    try {
      chatWs = new WebSocket(chatRealtimeUrl())
    }
    catch {
      return
    }
    chatWs.onopen = () => {
      chatWsRetry = 0
      sendProjectSubscription()
    }
    chatWs.onmessage = (e: MessageEvent) => handleRealtimeRaw(e.data)
    chatWs.onclose = (e: CloseEvent) => {
      chatWs = null
      if (e.code === 4401)
        return
      if (chatWsRetry >= 10)
        return
      const delay = Math.min(1000 * 2 ** chatWsRetry, 30000)
      chatWsRetry++
      chatWsRetryTimer = setTimeout(connectRealtime, delay)
    }
    chatWs.onerror = () => {}
  }

  function disconnectRealtime() {
    if (chatWsRetryTimer)
      clearTimeout(chatWsRetryTimer)
    chatWsRetryTimer = null
    chatWsRetry = 0
    chatWs?.close()
    chatWs = null
  }

  return {
    // State
    conversations,
    currentConversationId,
    messages,
    loading,
    messagesLoading,
    error,
    isStreaming,
    streamingContent,
    streamingThinking,
    streamingToolCalls,
    streamingTimeline,
    streamingMessageId,
    streamingMetadata,
    abortController,
    sidebarCollapsed,
    draftPrompt,
    prefillDraft,
    feishuExportAvailable,
    refreshFeishuExportAvailability,
    selectedSpaceId,
    selectedRole,
    selectedModel,
    selectedCredentialModel,
    forceDeepAnalysis,
    notificationsEnabled,
    streamingStatus,
    budgetWarning,
    lastFailedContent,
    streamingNarrations,
    streamingPendingText,
    streamingParts,
    deepAnalysisLogs,
    deepAnalysisSessionId,
    deepAnalysisSessions,
    restoredRuntimeConversationId,
    currentPhase,
    taskProgress,
    isInterrupting,
    webPushReady,
    // Getters
    currentConversation,
    hasConversation,
    // 会话搜索（标题 + 内容）
    conversationSearchResults,
    conversationSearching,
    searchConversations,
    clearConversationSearch,
    // 已归档会话
    archivedConversations,
    archivedLoading,
    fetchArchivedConversations,
    // Actions
    fetchConversations,
    // 项目作用域（项目作战室复用全局 chat）
    boundProjectId,
    enterProjectScope,
    exitProjectScope,
    createProjectConversation,
    setConversationVisibility,
    connectRealtime,
    disconnectRealtime,
    selectConversation,
    createNewConversation,
    removeConversation,
    renameConversation,
    archiveConversation,
    patchConversationCredential,
    patchConversationProviderAndModel,
    switchConversationSpace,
    stopStreaming,
    toggleSidebar,
    clearCurrentConversation,
    sendMessage,
    editMessageAndFork,
    retryLastMessage,
    restoreFromURL,
    restoreConversationRuntime,
    requestNotificationPermission,
    toggleNotifications,
    syncConversationToURL,
    // 编码会话
    activeCodingSession,
    codingProgress,
    codingResult,
    codingError,
    handleConfirmCodingSession,
    // 编码确认数据
    commitConfirmData,
    prConfirmData,
    diffSummaryData,
    completedConfirmSteps,
    // 导出到飞书
    isExportSelectMode,
    selectedMessageIds,
    enterExportSelectMode,
    exitExportSelectMode,
    toggleMessageSelect,
    selectAllAssistant,
    doExportToFeishu,
    // ：CodingPlan 导出到飞书
    doExportCodingPlanToFeishu,
    // 凭证缺失前置探测
    credentialMissingPayload,
    preflightConversation,
    clearCredentialMissingPayload,
    // 上下文超限引导
    lastContextExceeded,
    resetContextExceeded,
    // / /
    activeCodingPlan,
    repoMultiSelectorState,
    openRepoMultiSelector,
    closeRepoMultiSelector,
    submitRepoMultiSelector,
    retrySingleRepository,
    // 109-04：编排产出 → CodingPlan 惰性投影
    projectPlanToCodingPlan,
    // ：协商卡片状态
    pendingClarifications,
    getClarification,
    upsertClarification,
    markClarificationAnswered,
    clearAllClarifications,
    skipClarification,
    // plan 结构化澄清（多题多选，91-05）
    pendingPlanClarifications,
    getPlanClarification,
    upsertPlanClarification,
    markPlanClarificationAnswered,
    // 单测专用 SSE dispatch 入口
    //   生产路径走 sendMessage → connectSSE → onEvent callback；本字段把内部
    //   闭包暴露给 vitest，避免反射 / sendMessage mock 的开销。
    _dispatchSSE: handleSSEEvent,
  }
})
