/**
 * useChatSession — 可实例化的项目作用域对话会话（项目作战室 P3）。
 *
 * 与全局单例 `useChatStore` **解耦**：每个项目页大盘的 AI 会话栏持有一个独立实例，
 * 固定 `bound_project`，自己管理会话列表 / 当前会话 / 消息 / SSE 流，互不污染。
 * 复用 `connectSSE` 原语与 chat REST API；流式期间累积文本气泡，message_complete
 * 后回拉详情取权威落库消息（避免重实现 parts/tool 复杂渲染）。
 */
import type { MaybeRefOrGetter } from 'vue'
import type {
  Conversation,
  ConversationMessage,
  ConversationVisibility,
  SSEEvent,
} from '~/types/chat'
import { computed, ref, toValue } from 'vue'
import {
  cloneConversation,
  createConversation,
  deleteConversation,
  getConversationDetail,
  listConversations,
  patchConversation,
} from '~/api/chat'
import { connectSSE } from '~/composables/useSSEStream'
import { useAuthStore } from '~/stores/auth'

export interface ChatSessionGroups {
  /** 项目共享会话（全员只读可见）。 */
  shared: Conversation[]
  /** 我的项目个人会话。 */
  mine: Conversation[]
}

export function useChatSession(boundProjectId: MaybeRefOrGetter<string>) {
  const auth = useAuthStore()

  const conversations = ref<Conversation[]>([])
  const currentId = ref<string | null>(null)
  const messages = ref<ConversationMessage[]>([])
  const loadingList = ref(false)
  const loadingMessages = ref(false)
  const streamingText = ref('')
  const isStreaming = ref(false)
  const error = ref<string | null>(null)

  let controller: AbortController | null = null

  const projectId = () => toValue(boundProjectId)
  const myId = computed(() => auth.user?.id ?? null)

  const current = computed<Conversation | null>(
    () => conversations.value.find(c => c.id === currentId.value) ?? null,
  )

  /** 共享会话且非本人创建 → 只读（需 clone 后才能发言）。 */
  const isReadOnly = computed(() => {
    const c = current.value
    if (!c)
      return false
    return c.visibility === 'shared' && (c.created_by?.id ?? null) !== myId.value
  })

  /** 三组：项目共享 / 我的项目个人（通用个人会话不在项目栏展示）。 */
  const groups = computed<ChatSessionGroups>(() => {
    const shared: Conversation[] = []
    const mine: Conversation[] = []
    for (const c of conversations.value) {
      if (c.is_archived)
        continue
      if (c.visibility === 'shared')
        shared.push(c)
      else
        mine.push(c)
    }
    return { shared, mine }
  })

  async function loadConversations() {
    loadingList.value = true
    error.value = null
    try {
      conversations.value = await listConversations({ bound_project: projectId(), limit: 100 })
      // 自动选中：保留当前选择，否则选第一个我的会话 / 共享会话。
      if (!currentId.value || !conversations.value.some(c => c.id === currentId.value)) {
        const first = groups.value.mine[0] ?? groups.value.shared[0] ?? null
        if (first)
          await selectConversation(first.id)
        else
          currentId.value = null
      }
    }
    catch (e: unknown) {
      error.value = e instanceof Error ? e.message : String(e)
    }
    finally {
      loadingList.value = false
    }
  }

  async function selectConversation(id: string) {
    currentId.value = id
    loadingMessages.value = true
    messages.value = []
    try {
      const detail = await getConversationDetail(id)
      messages.value = detail.messages ?? []
      // 详情带回 created_by / visibility / duration_ms，回填到列表项保持一致。
      const idx = conversations.value.findIndex(c => c.id === id)
      if (idx >= 0)
        conversations.value[idx] = { ...conversations.value[idx], ...detail }
    }
    catch (e: unknown) {
      error.value = e instanceof Error ? e.message : String(e)
    }
    finally {
      loadingMessages.value = false
    }
  }

  async function newConversation(visibility: ConversationVisibility = 'personal') {
    const conv = await createConversation({
      space_id: null,
      bound_project_id: projectId(),
      visibility,
      title: '新对话',
    })
    conversations.value = [conv, ...conversations.value]
    currentId.value = conv.id
    messages.value = []
    return conv
  }

  /** 克隆共享会话为「我的项目个人会话」并切换过去（clone 贡献）。 */
  async function cloneCurrent() {
    if (!currentId.value)
      return
    const { conversation_id } = await cloneConversation(currentId.value)
    await loadConversations()
    await selectConversation(conversation_id)
    return conversation_id
  }

  async function send(text: string) {
    const content = text.trim()
    if (!content || isStreaming.value)
      return
    // 无会话先建个人会话；只读共享会话先 clone 再发。
    if (!currentId.value)
      await newConversation('personal')
    if (isReadOnly.value)
      await cloneCurrent()
    const convId = currentId.value
    if (!convId)
      return

    messages.value.push({
      id: `local-${Date.now()}`,
      role: 'user',
      content,
      created_at: new Date().toISOString(),
    })
    isStreaming.value = true
    streamingText.value = ''
    error.value = null
    controller = new AbortController()

    const onEvent = (event: SSEEvent) => {
      if (event.type === 'text_delta') {
        streamingText.value += event.text || ''
      }
      else if (event.type === 'part_delta' && (event as any).delta_type === 'text_append') {
        streamingText.value += event.text || ''
      }
      else if (event.type === 'error') {
        error.value = (event as any).message || '对话出错'
      }
    }

    try {
      await connectSSE(convId, content, 'developer', onEvent, controller.signal)
      // message_complete 后回拉权威落库消息（含最终 assistant parts）。
      await selectConversation(convId)
    }
    catch (e: unknown) {
      error.value = e instanceof Error ? e.message : String(e)
    }
    finally {
      isStreaming.value = false
      streamingText.value = ''
      controller = null
      // 列表 updated_at 变化 → 刷新排序/时长。
      loadConversations().catch(() => {})
    }
  }

  function stop() {
    controller?.abort()
    isStreaming.value = false
  }

  async function archive(id: string, archived: boolean) {
    await patchConversation(id, { is_archived: archived })
    await loadConversations()
  }

  async function remove(id: string) {
    await deleteConversation(id)
    if (currentId.value === id)
      currentId.value = null
    await loadConversations()
  }

  async function setVisibility(id: string, visibility: ConversationVisibility) {
    const updated = await patchConversation(id, { visibility })
    const idx = conversations.value.findIndex(c => c.id === id)
    if (idx >= 0)
      conversations.value[idx] = { ...conversations.value[idx], ...updated }
    await loadConversations()
  }

  return {
    conversations,
    currentId,
    current,
    messages,
    groups,
    myId,
    isReadOnly,
    loadingList,
    loadingMessages,
    isStreaming,
    streamingText,
    error,
    loadConversations,
    selectConversation,
    newConversation,
    cloneCurrent,
    send,
    stop,
    archive,
    remove,
    setVisibility,
  }
}
