<script setup lang="ts">
import type MarkdownIt from 'markdown-it'
import type { ProcessStep } from './ToolProcessGroup.vue'
import type { ConversationMessage, DeepAnalysisSession, ImagePart, MessagePart, PlanResearchSession, StreamTimelineItem, TextPart, ToolCallData, ToolUsePart } from '~/types/chat'
import { shallowRef } from 'vue'
import { Checkbox } from '~/components/ui/checkbox'
import { useEditImages } from '~/composables/useEditImages'
import { getMarkdownRenderer } from '~/composables/useMarkdownRenderer'
import { vMediumZoom } from '~/composables/useMediumZoom'
import { hydrateLegacyMessage } from '~/composables/useMessageParts'
import { collectRepoNames, relevanceCandidates, repoInitial, toolAction, toolLabel } from '~/composables/useToolDisplay'
import DeepAnalysisGroup from './DeepAnalysisGroup.vue'
import DocSummaryCard from './DocSummaryCard.vue'
import OrchestratedPlanCard from './OrchestratedPlanCard.vue'
import OrchestrationStageTimeline from './OrchestrationStageTimeline.vue'
import PlanResearchLogGroup from './PlanResearchLogGroup.vue'
import StructuredJsonView from './StructuredJsonView.vue'
import TechPlanCard from './TechPlanCard.vue'
import ToolProcessGroup from './ToolProcessGroup.vue'

const props = defineProps<{
  message: ConversationMessage
  isStreaming?: boolean
  streamingContent?: string
  streamingThinking?: string
  streamingToolCalls?: Array<{ id: string, name: string, input: Record<string, unknown>, result?: string, status: 'running' | 'done' }>
  streamingTimeline?: StreamTimelineItem[]
  streamingStatus?: 'streaming' | 'interrupted' | 'budget_exceeded' | null
  streamingNarrations?: string[]
  streamingPendingText?: string
  deepAnalysisLogs?: Array<{ type: string, content: string, ts: number }>
  deepAnalysisSessions?: DeepAnalysisSession[]
  streamingDocSummary?: {
    type: 'summary' | 'error' | 'loading'
    title?: string
    wordCount?: number
    preview?: string
    truncated?: boolean
    truncatedLength?: number
    errorType?: 'permission_denied' | 'not_found' | 'not_configured' | 'unknown'
    errorMessage?: string
  } | null
}>()

const emit = defineEmits<{
  exportSingle: [messageId: string]
}>()

const API_BASE = import.meta.env.VITE_API_BASE || '/api'

const chatStore = useChatStore()
const repositoriesStore = useRepositoriesStore()

const isSelected = computed(() =>
  chatStore.selectedMessageIds.has(props.message.id),
)

const isEditingUserMessage = ref(false)
const editedUserContent = ref('')
const isSubmittingEdit = ref(false)
const editTextareaRef = ref<HTMLTextAreaElement | null>(null)
const editFileInput = ref<HTMLInputElement | null>(null)

// 编辑态图片管理（已有图片 + 新贴图片），见 useEditImages
const {
  items: editImageItems,
  seed: seedEditImages,
  addFiles: addEditImageFiles,
  handlePaste: handleEditPaste,
  handleDrop: handleEditDrop,
  remove: removeEditImage,
  clear: clearEditImages,
  resolveAll: resolveEditImages,
  uploading: editImagesUploading,
  count: editImagesCount,
  isFull: editImagesFull,
} = useEditImages()

const canEditUserMessage = computed(() =>
  props.message.role === 'user' && !props.isStreaming,
)

// 内容或图片任一变化才视为「有改动」（允许仅增删图片就重新发送）
const editDirty = computed(() => {
  if (editedUserContent.value.trim() !== props.message.content.trim())
    return true
  if (editImageItems.value.length !== userImageParts.value.length)
    return true
  return editImageItems.value.some(i => i.kind === 'pending')
})

const editSubmitDisabled = computed(() => {
  if (isSubmittingEdit.value || editImagesUploading.value)
    return true
  const hasContent = !!editedUserContent.value.trim() || editImagesCount.value > 0
  if (!hasContent)
    return true
  return !editDirty.value
})

function startEditingUserMessage() {
  editedUserContent.value = props.message.content
  seedEditImages(userImageParts.value, userImageSrc)
  isEditingUserMessage.value = true
  nextTick(() => {
    const el = editTextareaRef.value
    if (el) {
      el.focus()
      el.setSelectionRange(el.value.length, el.value.length)
    }
  })
}

function cancelEditingUserMessage() {
  isEditingUserMessage.value = false
  editedUserContent.value = ''
  clearEditImages()
}

function openEditFilePicker() {
  if (editImagesFull.value)
    return
  editFileInput.value?.click()
}

function handleEditFileSelect(event: Event) {
  const input = event.target as HTMLInputElement
  if (input.files)
    addEditImageFiles(Array.from(input.files))
  if (editFileInput.value)
    editFileInput.value.value = ''
}

async function submitUserMessageEdit() {
  if (editSubmitDisabled.value)
    return
  isSubmittingEdit.value = true
  try {
    const images = await resolveEditImages()
    await chatStore.editMessageAndFork(props.message.id, editedUserContent.value, images)
    cancelEditingUserMessage()
  }
  finally {
    isSubmittingEdit.value = false
  }
}

function handleUserEditKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    event.preventDefault()
    cancelEditingUserMessage()
    return
  }
  if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
    event.preventDefault()
    void submitUserMessageEdit()
  }
}

// 飞书文档摘要数据：流式来自 prop，历史来自消息 metadata
const docSummary = computed(() => {
  if (props.isStreaming && props.streamingDocSummary) {
    return props.streamingDocSummary
  }
  const meta = props.message.metadata as Record<string, unknown> | undefined
  return (meta?.docSummary as typeof props.streamingDocSummary) || null
})

// Markdown renderer 共享单例。每个 text part 独立
// 渲染 HTML，避免老路径下 contentSource 整段重渲染时的「截断渲染」问题。
const mdInstance = shallowRef<MarkdownIt | null>(null)
const mdReady = ref(false)

onMounted(async () => {
  mdInstance.value = await getMarkdownRenderer()
  mdReady.value = true
})

/**
 * displayParts —— 渲染单一权威。
 *
 * - 流式（isStreaming）：优先用 `chatStore.streamingParts`；
 *   若 legacy flag 下 streamingParts 为空，则合成 ConversationMessage 喂给
 *   hydrateLegacyMessage，保留 legacy flag 下的过渡渲染能力。
 * - 非流式：直接对 `props.message` 走 hydrate adapter（coding-plan workflow+ 新消息走
 *   规则 A 直接返回；legacy 历史消息走规则 B/C/D 合成）。
 */
const displayParts = computed<MessagePart[]>(() => {
  if (props.isStreaming) {
    if (chatStore.streamingParts.length > 0)
      return chatStore.streamingParts
    // legacy flag 下兜底：从 streaming state 合成 message-shape 给 hydrate
    return hydrateLegacyMessage({
      id: 'streaming',
      role: 'assistant',
      content: props.streamingContent || props.streamingPendingText || '',
      tool_calls: (props.streamingToolCalls || []).map(tc => ({
        id: tc.id,
        name: tc.name,
        input: tc.input,
        result: tc.result,
        status: tc.status,
      })),
      metadata: {
        narrations: props.streamingNarrations || [],
        timeline: props.streamingTimeline || [],
      },
      created_at: '',
    })
  }
  return hydrateLegacyMessage(props.message)
})

const userImageParts = computed<ImagePart[]>(() => {
  if (props.message.role !== 'user')
    return []
  return hydrateLegacyMessage(props.message)
    .filter((part): part is ImagePart => part.type === 'image')
})

function userImageSrc(part: ImagePart): string {
  if (part.source_url)
    return part.source_url
  const storage_ref = part.storage_ref || ''
  const fileName = storage_ref.split('/').pop()
  return fileName ? `${API_BASE}/chat/images/${encodeURIComponent(fileName)}/` : ''
}

/**
 * 每个 text part 的 HTML 渲染缓存。基于 mdReady 触发首次渲染；后续 part 文本
 * 变更（streaming text_append）通过 computed 自动重算。
 */
const renderedPartHtml = computed<Record<string, string>>(() => {
  if (!mdReady.value || !mdInstance.value)
    return {}
  const out: Record<string, string> = {}
  for (const p of displayParts.value) {
    if (p.type === 'text')
      out[p.id] = p.text ? mdInstance.value.render(p.text) : ''
  }
  return out
})

// Thinking：流式来自 props，历史来自 metadata
const thinkingText = computed(() => {
  if (props.isStreaming)
    return props.streamingThinking || ''
  const meta = props.message.metadata as Record<string, unknown> | undefined
  return (meta?.thinking as string) || ''
})
const hasThinking = computed(() => !!thinkingText.value)
const thinkingStartTime = ref<number | null>(null)
const thinkingDuration = ref(0)
const showThinking = ref(!!props.isStreaming)

watch(() => props.streamingThinking, (val) => {
  if (val && !thinkingStartTime.value)
    thinkingStartTime.value = Date.now()
})
watch(() => props.isStreaming, (streaming) => {
  if (!streaming && thinkingStartTime.value)
    thinkingDuration.value = Math.round((Date.now() - thinkingStartTime.value) / 1000)
})
watch(() => props.message.id, () => {
  showThinking.value = !!props.isStreaming
})

const messageStatus = computed(() => {
  if (props.streamingStatus === 'interrupted' || props.streamingStatus === 'budget_exceeded')
    return props.streamingStatus
  const meta = props.message.metadata as Record<string, unknown> | undefined
  return (meta?.status as string) || null
})

const tokenDisplay = computed(() => {
  const m = props.message.metadata as Record<string, unknown> | undefined
  const input = m?.input_tokens as number | undefined
  const output = m?.output_tokens as number | undefined
  if (!input && !output)
    return ''
  return `${fmt(input || 0)} in · ${fmt(output || 0)} out`
})

function fmt(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n)
}

function formatTime(dateStr: string) {
  return new Date(dateStr).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

const metadata = computed(() => props.message.metadata as { model?: string } | undefined)

// 降级回答（max_turns 耗尽但已产出 partial）：展示提示徽章
const degradedInfo = computed(() => {
  const m = props.message.metadata as Record<string, unknown> | undefined
  if (!m?.degraded)
    return null
  return { reason: (m.degraded_reason as string) || '' }
})

// ：消息级导出就地三态。读取 metadata.feishu_exports 最新一条
// （handleExportSuccess 以 push 追加，末位即最新），item 形状与
// ChatMessageArea.handleExportSuccess 写入一致：{ document_id, url, title, exported_at }。
const exportedDoc = computed<{ url: string, title: string } | null>(() => {
  const meta = props.message.metadata as Record<string, unknown> | undefined
  if (!meta || typeof meta !== 'object')
    return null
  const raw = meta.feishu_exports
  if (!Array.isArray(raw) || raw.length === 0)
    return null
  const latest = raw.at(-1)
  if (!latest || typeof latest !== 'object')
    return null
  const record = latest as Record<string, unknown>
  const url = typeof record.url === 'string' ? record.url : ''
  if (!url)
    return null
  const title = typeof record.title === 'string' ? record.title : ''
  return { url, title }
})

// 防 tab-napping：与 TechPlanCard.openFeishu 行为一致
function openFeishu() {
  if (!exportedDoc.value)
    return
  window.open(exportedDoc.value.url, '_blank', 'noopener,noreferrer')
}

const [copied, toggleCopied] = useToggle(false)
function copyContent() {
  // 从 parts 派生纯文本（与后端 PartsCollector.to_message_payload 同源）
  const fromParts = displayParts.value
    .filter((p): p is TextPart => p.type === 'text')
    .map(p => p.text)
    .join('')
  const content = fromParts || (props.isStreaming ? (props.streamingContent || '') : props.message.content)
  if (content) {
    navigator.clipboard.writeText(content)
    toggleCopied(true)
    setTimeout(toggleCopied, 2000, false)
  }
}

// 工具调用数据（流式或历史），含 id 去重（SAFE-02）
// 优先从 displayParts 派生（new 协议路径下 streaming
// 期间 streamingToolCalls 不再被写入），fallback 到 props.streamingToolCalls /
// message.tool_calls 老路径（legacy flag + legacy 历史消息）。
const toolCalls = computed(() => {
  let calls: Array<{ id: string, name: string, input: Record<string, unknown>, result?: string, status: string }>

  // 优先：从 displayParts 中抽 tool_use parts
  const fromParts = displayParts.value
    .filter((p): p is ToolUsePart => p.type === 'tool_use')
    .map(p => ({
      id: p.tool_call_id || p.id,
      name: p.name,
      input: p.input,
      result: p.result ?? undefined,
      status: p.status === 'running' ? 'running' : 'done',
    }))
  if (fromParts.length > 0) {
    calls = fromParts
  }
  else if (props.isStreaming && props.streamingToolCalls && props.streamingToolCalls.length > 0) {
    calls = props.streamingToolCalls
  }
  else if (props.message.tool_calls && props.message.tool_calls.length > 0) {
    const mapped = props.message.tool_calls.map((tc: ToolCallData) => ({
      ...tc,
      status: tc.status || 'done',
      result: tc.result || undefined,
    }))
    const deepCalls = mapped.filter(tc => isDeepAnalysisTool(tc.name))
    if (deepCalls.length > 1) {
      const primary = deepCalls.find(tc => tc.result || (tc.input && Object.keys(tc.input).length > 0)) || deepCalls[0]
      const ghostIds = new Set(deepCalls.filter(tc => tc.id !== primary.id).map(tc => tc.id))
      calls = mapped.filter(tc => !ghostIds.has(tc.id))
    }
    else {
      calls = mapped
    }
  }
  else {
    return []
  }

  // 按 id 去重，保留首次出现
  const seen = new Set<string>()
  return calls.filter((tc) => {
    if (seen.has(tc.id))
      return false
    seen.add(tc.id)
    return true
  })
})

// 工具标签 / 描述逻辑统一抽到 useToolDisplay 组合式（供 ToolProcessGroup 共用）。
// toolLabel / toolAction 通过 import 获得；这里只保留会话级 repository_id → name
// 映射，让搜索 / 相关性等工具展示仓库名称而非裸 UUID（用户诉求 2 / 3）。

/**
 * 会话级 repository_id → 仓库名称映射。来源（按可信度合并）：
 *   1. analyze_repository_relevance 结果里的候选仓库（含 repository_name）。
 *   2. create_coding_plan / update_coding_plan 推荐仓库。
 *   3. repositories store（若已加载；chat 页 onMounted 会惰性拉取）。
 * 跨消息扫描整个会话，并叠加当前流式消息的 parts（尚未入 messages）。
 */
const repoNames = computed<Record<string, string>>(() => {
  const map: Record<string, string> = {}
  for (const r of repositoriesStore.repositories)
    map[r.id] = r.name

  const scanToolCall = (name: string, input: Record<string, unknown> | undefined, result: unknown) => {
    Object.assign(map, collectRepoNames(name, input, result))
  }

  for (const m of chatStore.messages) {
    if (Array.isArray(m.tool_calls)) {
      for (const tc of m.tool_calls)
        scanToolCall(tc.name, tc.input, tc.result)
    }
    if (Array.isArray(m.parts)) {
      for (const p of m.parts) {
        if (p.type === 'tool_use')
          scanToolCall(p.name, p.input, p.result ?? undefined)
      }
    }
  }

  for (const p of displayParts.value) {
    if (p.type === 'tool_use')
      scanToolCall(p.name, p.input, p.result ?? undefined)
  }

  return map
})

/**
 * 本条回答涉及的仓库「编号 + 名称」索引（借鉴 open-webui Citations 的编号来源）。
 * 排序：相关性候选（按返回顺序，通常 score 倒序）→ 搜索/浏览命中的 repository_id
 * → 编码方案推荐仓库。用于：① 过程面板里给搜索步骤标编号；② 相关性候选 pill 编号；
 * ③ 答案底部「引用仓库」图例，点击跳回过程面板（结论 ↔ 证据闭环）。
 */
interface RepoRef { index: number, id: string, name: string }
const repoRefs = computed<RepoRef[]>(() => {
  const refs: RepoRef[] = []
  const seen = new Set<string>()
  const add = (id: string, name?: string) => {
    if (!id || seen.has(id))
      return
    seen.add(id)
    const fallback = id.length > 8 ? `${id.slice(0, 8)}…` : id
    refs.push({ index: refs.length + 1, id, name: name || repoNames.value[id] || fallback })
  }
  const tools = displayParts.value.filter((p): p is ToolUsePart => p.type === 'tool_use')
  // 1. 相关性候选优先
  for (const p of tools) {
    if (p.name.replace(/^mcp__[^_]+__/, '') === 'analyze_repository_relevance') {
      for (const c of relevanceCandidates(p.result ?? undefined))
        add(c.id, c.name)
    }
  }
  // 2. 搜索 / 浏览等显式指定的 repository_id
  for (const p of tools) {
    const rid = (p.input?.repository_id as string) || ''
    if (rid)
      add(rid)
  }
  // 3. 编码方案推荐仓库
  for (const p of tools) {
    const contributed = collectRepoNames(p.name, p.input, p.result ?? undefined)
    for (const [id, name] of Object.entries(contributed))
      add(id, name)
  }
  return refs
})

const repoIndexById = computed<Map<string, number>>(() => {
  const m = new Map<string, number>()
  for (const r of repoRefs.value)
    m.set(r.id, r.index)
  return m
})

// 删除 narration / pendingNarration / showNarrations
// / timelineItems / hasTimeline —— 由 parts-flow 渲染替代（narration 不再是独立
// 类型，融入 text part 主流；timeline 渲染由 groupedDisplayItems 单一权威驱动）。

// 工具调用详情展开
const expandedTools = ref<Set<string>>(new Set())
function toggleTool(id: string) {
  if (expandedTools.value.has(id))
    expandedTools.value.delete(id)
  else
    expandedTools.value.add(id)
}

// 拥有专属卡片渲染的工具不并入「分析过程」折叠面板：
//   - deep_analysis → DeepAnalysisGroup（独立 swiper）
//   - create/update_coding_plan → TechPlanCard（独立交互卡片）
//   - start_plan_research / start_feature_solution → OrchestratedPlanCard（109-04）
//
// 🔴 静默失守点：专属卡片的渲染分支只存在于 `item.kind === 'tool'` 的单例分支
// 里。工具漏登记进本集合会被 isProcessTool 归入「分析过程」折叠面板，那条路径
// 不渲染专属卡片 —— 不报错、不崩，只是入口彻底不见。改动本集合务必同步测试
// （chatMessageBubble.parts.spec.ts 有显式断言）。
const UNGROUPABLE_TOOLS = new Set([
  'deep_analysis',
  'create_coding_plan',
  'update_coding_plan',
  'start_plan_research',
  'start_feature_solution',
])
function isProcessTool(name: string): boolean {
  return !UNGROUPABLE_TOOLS.has(name.replace(/^mcp__[^_]+__/, ''))
}

interface ToolItemShape {
  id: string
  name: string
  input: Record<string, unknown>
  result?: string
  status: 'running' | 'done'
}

// parts-flow 渲染节点类型。
//   - 'text'：正文 markdown（顶层渲染）。
//   - 'thinking'：独立（不与工具相邻）的思考节点，保留 inline timeline 预览。
//   - 'process-group'：连续的「思考 + 工具调用」收拢为一个 Cursor 风格折叠面板。
//   - 'tool'：coding_plan 单工具（pill + TechPlanCard）。
//   - 'deep-analysis-group'：连续 deep_analysis（DeepAnalysisGroup）。
//   - 'unknown'：未知 part type 兜底（forward-compat）。
interface DisplayTextNode { kind: 'text', _key: string, part: TextPart }
interface DisplayThinkingNode { kind: 'thinking', _key: string, id: string, text: string, state: 'streaming' | 'done' }
interface DisplayProcessNode { kind: 'process-group', _key: string, steps: ProcessStep[] }
interface DisplayToolNode extends ToolItemShape { kind: 'tool', _key: string }
interface DisplayUnknownNode { kind: 'unknown', _key: string, type: string }
interface DisplayDeepGroupNode { kind: 'deep-analysis-group', _key: string, items: ToolItemShape[] }

type PartsDisplayItem
  = | DisplayTextNode
    | DisplayThinkingNode
    | DisplayProcessNode
    | DisplayToolNode
    | DisplayDeepGroupNode
    | DisplayUnknownNode

/**
 * parts → 渲染节点（用户诉求 1：收拢工具调用）。
 *
 * 算法：顺序扫描 displayParts，把连续的「思考 + 普通工具调用」累积成一个
 * process run。遇到正文 / deep_analysis / coding_plan / 未知 part 时 flush：
 *   - run 含至少 1 个工具 → 渲染为 ToolProcessGroup（三层折叠）。
 *   - run 只有思考 → 退化为 inline timeline-step（保留旧的思考预览契约）。
 */
const groupedDisplayItems = computed<PartsDisplayItem[]>(() => {
  const out: PartsDisplayItem[] = []
  const parts = displayParts.value
  let run: ProcessStep[] = []

  const flushRun = () => {
    if (run.length === 0)
      return
    const hasTool = run.some(s => s.kind === 'tool')
    if (hasTool) {
      out.push({ kind: 'process-group', _key: `pg-${run[0].id}`, steps: run })
    }
    else {
      // 思考-only run：逐条还原为顶层 inline 思考节点。
      for (const s of run) {
        if (s.kind === 'thinking')
          out.push({ kind: 'thinking', _key: s.id, id: s.id, text: s.text, state: 'done' })
      }
    }
    run = []
  }

  let i = 0
  while (i < parts.length) {
    const cur = parts[i]
    if (cur.type === 'text') {
      flushRun()
      out.push({ kind: 'text', _key: cur.id, part: cur })
      i++
      continue
    }
    if (cur.type === 'thinking') {
      run.push({ kind: 'thinking', id: cur.id, text: cur.text })
      i++
      continue
    }
    if (cur.type === 'tool_use') {
      // deep_analysis：flush 当前 run，收拢连续 deep_analysis 为独立 swiper 组。
      if (isDeepAnalysisTool(cur.name)) {
        flushRun()
        const group: ToolItemShape[] = []
        let k = i
        while (k < parts.length) {
          const p = parts[k]
          if (p.type !== 'tool_use' || !isDeepAnalysisTool(p.name))
            break
          group.push({
            id: p.tool_call_id || p.id,
            name: p.name,
            input: p.input,
            result: p.result ?? undefined,
            status: (p.status === 'running' ? 'running' : 'done') as 'running' | 'done',
          })
          k++
        }
        out.push({ kind: 'deep-analysis-group', _key: `da-${cur.id}`, items: group })
        i = k
        continue
      }
      // coding_plan：flush 当前 run，单独成块（TechPlanCard）。
      if (!isProcessTool(cur.name)) {
        flushRun()
        out.push({
          kind: 'tool',
          _key: cur.id,
          id: cur.tool_call_id || cur.id,
          name: cur.name,
          input: cur.input,
          result: cur.result ?? undefined,
          status: (cur.status === 'running' ? 'running' : 'done') as 'running' | 'done',
        })
        i++
        continue
      }
      // 普通工具：并入当前 process run。
      run.push({
        kind: 'tool',
        id: cur.tool_call_id || cur.id,
        name: cur.name,
        input: cur.input,
        result: cur.result ?? undefined,
        status: (cur.status === 'running' ? 'running' : 'done') as 'running' | 'done',
      })
      i++
      continue
    }
    // 未知 part type（schema version forward-compat）
    flushRun()
    out.push({ kind: 'unknown', _key: (cur as { id: string }).id || `unk-${i}`, type: (cur as { type: string }).type })
    i++
  }
  flushRun()
  return out
})

// 答案底部「引用仓库」图例 → 过程面板的跳转联动（结论 ↔ 证据闭环）。
const firstProcessGroupKey = computed(() => {
  const node = groupedDisplayItems.value.find(i => i.kind === 'process-group')
  return node ? node._key : ''
})
// 是否展示图例：有引用仓库且确实存在过程面板。
const showRepoLegend = computed(() => repoRefs.value.length > 0 && !!firstProcessGroupKey.value)
// 递增触发 ToolProcessGroup 展开 + 闪烁。
const processJump = ref(0)
async function jumpToProcess() {
  processJump.value++
  await nextTick()
  const key = firstProcessGroupKey.value
  if (!key)
    return
  const el = document.querySelector(`[data-process-group="${key}"]`)
  el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

// 单条 thinking item 的展开状态（默认收起，仅显示首行预览）
const expandedThinking = ref<Set<string>>(new Set())
function toggleThinking(id: string) {
  if (expandedThinking.value.has(id))
    expandedThinking.value.delete(id)
  else
    expandedThinking.value.add(id)
}
function thinkingPreview(text: string): string {
  const trimmed = text.trim()
  const firstLine = trimmed.split('\n')[0] || ''
  return firstLine.length > 80 ? `${firstLine.slice(0, 80)}…` : firstLine
}
function thinkingIsMultiline(text: string): boolean {
  const trimmed = text.trim()
  return trimmed.includes('\n') || trimmed.length > 80
}

// 深度分析实时日志（旧 flat 数组，仅作回退用）
const resolvedDeepAnalysisLogs = computed(() => {
  if (props.isStreaming)
    return props.deepAnalysisLogs || []
  const meta = props.message.metadata as Record<string, unknown> | undefined
  const logs = meta?.deep_analysis_logs
  return Array.isArray(logs) ? logs as Array<{ type: string, content: string, ts: number }> : []
})

/**
 * 多个深度分析子会话各自独立的日志。
 * - 流式：来自 store（props.deepAnalysisSessions）。
 * - 历史：来自 message.metadata.deep_analysis_sessions（finalize 落库）。
 * - 回退：旧消息只有 flat logs + session_id → 合成单会话，保证不破坏历史渲染。
 */
const resolvedDeepSessions = computed<DeepAnalysisSession[]>(() => {
  if (props.isStreaming)
    return props.deepAnalysisSessions || []
  const meta = props.message.metadata as Record<string, unknown> | undefined
  const fromMeta = meta?.deep_analysis_sessions
  if (Array.isArray(fromMeta) && fromMeta.length > 0)
    return fromMeta as DeepAnalysisSession[]
  const logs = resolvedDeepAnalysisLogs.value
  if (logs.length > 0) {
    const sid = (meta?.deep_analysis_session_id as string) || ''
    return [{ session_id: sid, task_description: '', logs }]
  }
  return []
})

function isDeepAnalysisTool(name: string): boolean {
  return name.replace(/^mcp__[^_]+__/, '') === 'deep_analysis'
}

/** 从 deep_analysis tool part 的 result/placeholder 中解析子会话 session_id */
function deepAnalysisSessionIdOf(item: { result?: string, input?: Record<string, unknown> }): string {
  const raw = item.result
  if (raw) {
    const str = typeof raw === 'string' ? raw : JSON.stringify(raw)
    try {
      const parsed = JSON.parse(str)
      const sid = parsed?.data?.session_id || parsed?.session_id || parsed?.task_id
      if (sid)
        return String(sid)
    }
    catch {
      // 非 JSON，落到正则
    }
    const m = str.match(/deep-[0-9a-f]{6,}/)
    if (m)
      return m[0]
  }
  return ''
}

/** 把一组 deep_analysis tool parts 配对到各自的子会话，构造 swiper items */
function buildDeepItems(items: ToolItemShape[]): Array<{ session: DeepAnalysisSession, taskLabel: string, status: 'running' | 'done' }> {
  const sessions = resolvedDeepSessions.value
  return items.map((it, idx) => {
    const sid = deepAnalysisSessionIdOf(it)
    let session = sid ? sessions.find(s => s.session_id === sid) : undefined
    // session_id 解析失败但数量一致时按顺序对应
    if (!session && sessions.length === items.length)
      session = sessions[idx]
    // 仍无 → 合成空会话（running 占位 / 尚无日志）
    if (!session) {
      session = {
        session_id: sid || it.id,
        task_description: (it.input?.task_description as string) || '',
        status: it.status === 'running' ? 'RUNNING' : undefined,
        logs: [],
      }
    }
    const taskLabel = session.task_description || (it.input?.task_description as string) || ''
    return { session, taskLabel, status: it.status }
  })
}

function isCodingPlanTool(name: string): boolean {
  const bare = name.replace(/^mcp__[^_]+__/, '')
  return bare === 'create_coding_plan' || bare === 'update_coding_plan'
}

/**
 * 109-04：编排入口工具判定（SPINE-01）。
 *
 * 🔴 必须同时覆盖两个工具：`start_plan_research` 与 `start_feature_solution`
 * 返回体同形，只登记前者会让另一条编排入口继续没有编码入口。
 */
function isOrchestrationTool(name: string): boolean {
  const bare = name.replace(/^mcp__[^_]+__/, '')
  return bare === 'start_plan_research' || bare === 'start_feature_solution'
}

/**
 * 109-04：编排工具终态产出的方案版本 id。
 *
 * 仅在 result 解析得 `status === 'done'` 且 `artifact_version_id` 为非空字符串时
 * 返回数据，否则返回 null —— 编排在途（`__blocking_task__` 形态，无该字段）与
 * 失败一律不渲染卡片，这是裁决 D-4「在途完全不呈现」的机械抓手。
 *
 * 🔴 必须按**传入的那一条** tool call 解析，不能在 toolCalls 里 find 第一条编排工具。
 * 异步路径（跨仓调研的常态）上 `waiting → executing` 会二次运行 SDK，同一条消息里
 * 因此累积两条同名编排工具：第一条 result 是 `__blocking_task__`（无 artifact_version_id），
 * 第二条才是 `status === 'done'`。用 find 取到的恒是第一条 ⇒ 卡片永远不渲染，
 * SPINE-01 的「进入编码」入口在正常路径上直接消失。
 *
 * 解析沿用 codingPlanData 的防御性双轨：result 可能是 JSON string 也可能是
 * dict，两种都吃，解析失败返回 null 不抛。
 */
function resolveOrchestratedPlanData(
  result: unknown,
): { artifactVersionId: string } | null {
  if (!result)
    return null

  let parsed: { status?: string, artifact_version_id?: string | null } | null = null
  if (typeof result === 'string') {
    try {
      parsed = JSON.parse(result)
    }
    catch {
      parsed = null
    }
  }
  else if (typeof result === 'object') {
    parsed = result as { status?: string, artifact_version_id?: string | null }
  }
  if (!parsed || parsed.status !== 'done')
    return null

  const versionId = parsed.artifact_version_id
  if (typeof versionId !== 'string' || versionId === '')
    return null
  return { artifactVersionId: versionId }
}

/**
 * 110-07：从编排工具 result 里取编排会话 id。
 *
 * 解析沿用 `resolveOrchestratedPlanData` 的防御性双轨（result 可能是 JSON string
 * 也可能是 dict，两种都吃，失败返回空串不抛）。
 */
function resolveOrchestrationSessionId(result: unknown): string {
  if (!result)
    return ''

  let parsed: unknown = null
  if (typeof result === 'string') {
    try {
      parsed = JSON.parse(result)
    }
    catch {
      parsed = null
    }
  }
  else if (typeof result === 'object') {
    parsed = result
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed))
    return ''

  const sessionId = (parsed as { session_id?: unknown }).session_id
  return typeof sessionId === 'string' ? sessionId : ''
}

/**
 * 110-07：本 tool item 绑定的编排会话 id（UI-SPEC §A.7 的绑定顺序）。
 *
 * 🔴 顺序是 result 优先、store 兜底，不能反过来：
 * 在途的五个阶段（拆分 / 路由 / 召回 / 澄清 / 并行调研）全部发生在 tool result
 * **之前**（tool pill 一路是 `running`），所以只靠解析 result 会让在途期间绑不到
 * 会话、时间线整段不出现——store 的 `activeOrchestrationSessionId` 是这段时间里
 * 唯一的来源。但 result 一旦出现（挂起 marker 与终态 result 都带 `session_id`），
 * 它**明确属于这个气泡**，优先级最高：同一对话里跑第二轮编排时，store 的活跃 id
 * 已经指向新会话，只有 result 能把第一条气泡钉回它自己那次编排。
 */
function orchestrationSessionIdFor(item: ToolItemShape): string {
  return resolveOrchestrationSessionId(item.result) || chatStore.activeOrchestrationSessionId || ''
}

/**
 * 110-07：本条消息里**最后一个**编排 tool item 的 id（无则空串）。
 *
 * 异步路径（跨仓调研的常态）上 `waiting → executing` 会二次运行 SDK，同一条消息
 * 因此累积两条同名编排 tool call：第一条 result 是 `__blocking_task__`，第二条才是
 * 终态。两者绑定**同一个 session_id**，不加这个判定会让同一份进度渲染两遍。
 *
 * 🔴 这不是 `.find` 的复活：它只用于**去重渲染位置**。`OrchestratedPlanCard` 的
 * **取数**仍严格走 `resolveOrchestratedPlanData(item.result)` 逐条解析（109 载重
 * 不变量），两件事不要合并——把卡片的渲染条件也改成依赖这个 computed，就等于把
 * 109 修好的那个「卡片永不渲染」的缺口重新打开。
 */
const lastOrchestrationToolItemId = computed(() => {
  let last = ''
  for (const item of groupedDisplayItems.value) {
    if (item.kind === 'tool' && isOrchestrationTool(item.name))
      last = item.id
  }
  return last
})

/**
 * 110-07：过滤到**本气泡绑定的那次编排会话**的调研容器（F-21）。
 *
 * 🔴 两块新 UI 的「不重复」保护强度并不对等，这层过滤只有日志组需要：
 * - 时间线取 `orchestrationSessions[sessionId]`，store 按 `session_id` 分桶，
 *   换一个会话就是换一个桶，**天然自限**；
 * - 而 `planResearchSessions` 是一个**会话级的扁平数组**，每份 runtime 快照
 *   **整体替换**它（110-04 全量列表语义），后端又只装本对话**最近一次**编排的容器。
 *
 * ⇒ 一段对话里跑两轮编排时，快照里装的是第二轮的容器。若不按 `plan_session_id`
 * 过滤，第一条编排消息会照样渲染出这一组——用户看到两处「方案调研 · N 个仓库」，
 * 其中一份挂在了**错误的方案**上。
 *
 * `plan_session_id` 由 110-03 在每条 `PlanResearchSession` 上给出
 * （`= str(ConvergenceSession.id)`），与 `orchestrationSessionIdFor(item)` 同源同值。
 */
function planResearchSessionsFor(item: ToolItemShape): PlanResearchSession[] {
  const sid = orchestrationSessionIdFor(item)
  if (!sid)
    return []
  const sessions = chatStore.planResearchSessions
  return Array.isArray(sessions) ? sessions.filter(s => s?.plan_session_id === sid) : []
}

// 从 toolCalls 中提取 coding plan 数据
const codingPlanData = computed(() => {
  const planTool = toolCalls.value.find(tc => isCodingPlanTool(tc.name))
  if (!planTool)
    return null

  // tech_plan 和 affected_files 的**历史消息兜底**来源：tool input。
  //
  // 109-06：SPINE-02 已把这两个入参从 create/update_coding_plan 的 schema 里删掉，
  // 因此**新消息**的 input 无此两键，这里取值恒为空串 / 空数组。
  // 🔴 这段不可删除：SPINE-02 之前的消息里 tech_plan 仍在 input 里，砍掉这里会让
  // 历史会话的方案卡集体变空。
  const input = planTool.input || {}
  const inputTechPlan = (input.tech_plan as string) || ''
  // ：兼容 file_path / path 两种 schema 字段名
  const inputAffectedFiles = (input.affected_files as Array<{ file_path?: string, path?: string, change_type: string }>) || []

  // session_id / status / coding_plan_id 来自 tool result。
  // 防御性双轨：result 在快照(snapshot) / langchain_runner 路径里是 JSON string，
  // 但历史上 chat_runner 曾直接发 dict（未序列化）—— 这里两种形态都吃。
  let sessionId = ''
  let planId = ''
  let sessionStatus: string = 'draft'
  let repositoryId = ''
  let repositoryName = ''
  let recommendedRepositories: Array<{ id: string, name: string }> = []
  // 109-REVIEW HI-02：正文 / 影响文件 / 来源标志改由 **tool result** 承载。
  //
  // 修复前这三者对「非最新那一份 plan」的卡片同时取不到：input 里已无正文（SPINE-02
  // 收窄），而 runtime 的语义是「对话内**最近**一条 CodingPlan」⇒ 会话里一有第二份
  // 方案，第一张卡就变成「（暂无方案正文）」并被误挂「本方案未经代码调研」横幅——
  // 一次内容丢失回归 + 一次 RELY-01 误报（误报发生在主路径的常见形态上，用户很快
  // 就会学会忽略这条横幅，信号自己把自己拆掉了）。
  let resultTechPlan = ''
  let resultAffectedFiles: Array<{ file_path?: string, path?: string, change_type: string }> = []
  let provenance: string | null | undefined
  if (planTool.result) {
    const raw: unknown = planTool.result
    let parsed: {
      session_id?: string
      coding_session_id?: string
      coding_plan_id?: string
      repository_id?: string
      repository_name?: string
      recommended_repositories?: Array<{ id?: string, name?: string }>
      tech_plan?: string
      affected_files?: Array<{ file_path?: string, path?: string, change_type: string }>
      provenance?: string | null
      status?: string
    } | null = null
    if (typeof raw === 'string') {
      try {
        parsed = JSON.parse(raw)
      }
      catch {
        parsed = null
      }
    }
    else if (typeof raw === 'object') {
      parsed = raw as { session_id?: string, coding_session_id?: string, coding_plan_id?: string, status?: string }
    }
    if (parsed) {
      // ：优先用 coding_session_id（新返回），回退到 session_id（兼容 alias）
      sessionId = parsed.coding_session_id || parsed.session_id || ''
      planId = parsed.coding_plan_id || ''
      repositoryId = parsed.repository_id || ''
      repositoryName = parsed.repository_name || ''
      recommendedRepositories = Array.isArray(parsed.recommended_repositories)
        ? parsed.recommended_repositories.flatMap(repo =>
            repo?.id && repo?.name ? [{ id: repo.id, name: repo.name }] : [],
          )
        : []
      resultTechPlan = typeof parsed.tech_plan === 'string' ? parsed.tech_plan : ''
      resultAffectedFiles = Array.isArray(parsed.affected_files) ? parsed.affected_files : []
      // 🔴 不做任何归一化 / 兜底取值：`undefined` 必须原样传给 TechPlanCard，让它
      // 走保守分支（标注）。在这里补一个默认值等于替后端签名。
      provenance = typeof parsed.provenance === 'string' ? parsed.provenance : undefined
      sessionStatus = parsed.status || 'draft'
      // coding-plan workflow 工具不再产 session，新 status='plan_only' 映射回
      // 'draft' 让 TechPlanCard 走 showInlineSelector 渲染（hasSessions=false 时
      // 由 RepoMultiSelector 接管确认动作，session 由 fan-out endpoint 创建）。
      if (sessionStatus === 'plan_only')
        sessionStatus = 'draft'
    }
  }

  const targetRepositories = recommendedRepositories.length > 0
    ? recommendedRepositories
    : repositoryId && repositoryName
      ? [{ id: repositoryId, name: repositoryName }]
      : []

  // 工具结果优先、tool input 兜底：新消息走前者，SPINE-02 之前的历史消息走后者。
  const techPlan = resultTechPlan || inputTechPlan
  const affectedFiles = resultAffectedFiles.length > 0 ? resultAffectedFiles : inputAffectedFiles

  return {
    sessionId,
    planId,
    techPlan,
    affectedFiles,
    provenance,
    status: sessionStatus,
    targetRepositories,
  }
})

// 编码方案的实时状态（优先使用 store 中的 activeCodingSession）
const codingPlanStatus = computed(() => {
  const data = codingPlanData.value
  if (!data)
    return 'draft'
  const active = chatStore.activeCodingSession
  if (active && active.sessionId === data.sessionId) {
    return active.status
  }
  return data.status as 'draft' | 'confirmed' | 'running' | 'completed' | 'failed'
})

const codingPlanConfirming = computed(() => {
  const data = codingPlanData.value
  if (!data)
    return false
  const active = chatStore.activeCodingSession
  return !!(active && active.sessionId === data.sessionId && active.isConfirming)
})

// 从 tool result 中提取分支名（D-06: 服务端推断的分支名传给 CodingPlanCard）
const codingPlanBranchName = computed(() => {
  const data = codingPlanData.value
  if (!data)
    return undefined
  const active = chatStore.activeCodingSession
  if (active && active.sessionId === data.sessionId && active.status === 'draft') {
    // 同 codingPlanData：result 可能是 JSON string（snapshot 路径）也可能是 object
    // （chat_runner 历史路径），两种都吃。
    const raw: unknown = toolCalls.value.find(tc => isCodingPlanTool(tc.name))?.result
    if (!raw)
      return undefined
    let parsed: { branch_name?: string } | null = null
    if (typeof raw === 'string') {
      try {
        parsed = JSON.parse(raw)
      }
      catch {
        parsed = null
      }
    }
    else if (typeof raw === 'object') {
      parsed = raw as { branch_name?: string }
    }
    return parsed?.branch_name || undefined
  }
  return undefined
})

// waiting / waiting_clarification 阶段空内容时隐藏空 bubble，让 ChatStatusBar /
// ClarificationCard 单独呈现（避免暂停等待时一个空气泡 + 打字光标）。
const hideEmptyBubble = computed(() =>
  props.isStreaming
  && displayParts.value.length === 0
  && (chatStore.currentPhase === 'waiting' || chatStore.currentPhase === 'waiting_clarification'),
)

// 暂停等待用户答复澄清时，不显示"正在输入"光标（语义上并非在流式输出）
const suppressTypingCursor = computed(() => chatStore.currentPhase === 'waiting_clarification')
</script>

<template>
  <!-- ======================== 用户消息 ======================== -->
  <div v-if="message.role === 'user'" class="user-message-row">
    <div class="user-message-stack">
      <div
        v-if="isEditingUserMessage"
        class="user-edit-panel"
        @paste="handleEditPaste"
        @dragover.prevent
        @drop.prevent="handleEditDrop"
      >
        <textarea
          ref="editTextareaRef"
          v-model="editedUserContent"
          data-test="edit-user-message-input"
          class="user-edit-textarea"
          rows="3"
          placeholder="编辑消息，可粘贴或添加图片…"
          aria-label="编辑用户消息"
          @keydown="handleUserEditKeydown"
        />

        <!-- 图片预览：已有图片 + 新贴图片，可逐个移除 -->
        <div v-if="editImageItems.length > 0" class="edit-image-strip">
          <div
            v-for="img in editImageItems"
            :key="img.id"
            class="edit-image-chip"
            :class="{ 'edit-image-chip--error': img.status === 'error' }"
          >
            <img :src="img.previewUrl" alt="" class="edit-image-thumb">
            <span v-if="img.status === 'uploading'" class="edit-image-overlay">
              <span class="icon-[lucide--loader-circle] animate-spin text-[14px]" />
            </span>
            <button
              type="button"
              class="edit-image-remove"
              title="移除图片"
              :disabled="img.status === 'uploading'"
              @click="removeEditImage(img.id)"
            >
              <span class="icon-[lucide--x] text-[11px]" />
            </button>
          </div>
        </div>

        <input
          ref="editFileInput"
          type="file"
          class="sr-only"
          accept="image/png,image/jpeg,image/gif,image/webp"
          multiple
          @change="handleEditFileSelect"
        >

        <div class="user-edit-actions">
          <div class="user-edit-actions-left">
            <button
              type="button"
              class="user-edit-icon-btn"
              title="添加图片"
              :disabled="editImagesFull"
              @click="openEditFilePicker"
            >
              <span class="icon-[lucide--image-plus] text-[14px]" />
            </button>
            <span class="user-edit-hint">⌘ + Enter 发送 · Esc 取消 · 可粘贴图片</span>
          </div>
          <div class="flex items-center gap-2">
            <button
              type="button"
              data-test="cancel-user-message-edit"
              class="user-edit-btn user-edit-btn--ghost"
              @click="cancelEditingUserMessage"
            >
              取消
            </button>
            <button
              type="button"
              data-test="submit-user-message-edit"
              class="user-edit-btn user-edit-btn--primary"
              :disabled="editSubmitDisabled"
              @click="submitUserMessageEdit"
            >
              <span v-if="isSubmittingEdit" class="icon-[lucide--loader-circle] text-[11px] animate-spin" />
              <span v-else class="icon-[lucide--corner-down-left] text-[11px]" />
              {{ isSubmittingEdit ? '发送中...' : '重新发送' }}
            </button>
          </div>
        </div>
      </div>
      <template v-else>
        <div v-if="message.content" class="user-bubble">
          {{ message.content }}
        </div>
        <div v-if="userImageParts.length > 0" class="image-preview-grid">
          <img
            v-for="part in userImageParts"
            :key="part.id"
            v-medium-zoom
            class="image-preview-thumb"
            :src="userImageSrc(part)"
            :alt="part.alt_text || '图片'"
            loading="lazy"
          >
        </div>
        <button
          v-if="canEditUserMessage"
          type="button"
          data-test="edit-user-message"
          class="user-edit-trigger"
          title="编辑并重新发送"
          @click="startEditingUserMessage"
        >
          <span class="icon-[lucide--pencil] text-[11px]" />
          <span>编辑</span>
        </button>
      </template>
    </div>
  </div>

  <!-- ======================== AI 消息 ======================== -->
  <div v-else-if="!hideEmptyBubble" class="ai-message group">
    <!-- 多选模式 Checkbox (per D-01, D-03) -->
    <div v-if="chatStore.isExportSelectMode && props.message.role === 'assistant'" class="mr-2 flex items-center shrink-0">
      <Checkbox :checked="isSelected" @update:checked="chatStore.toggleMessageSelect(props.message.id)" />
    </div>
    <div class="assistant-avatar">
      <img src="/logo-mark.svg" alt="" aria-hidden="true" class="assistant-avatar-logo">
    </div>
    <div class="assistant-message-shell">
      <div class="assistant-message-header">
        <div class="assistant-title">
          <span>Friday AI</span>
          <span v-if="metadata?.model" class="assistant-model">{{ metadata.model }}</span>
        </div>
        <span class="assistant-time">{{ formatTime(message.created_at) }}</span>
      </div>
      <!-- 飞书文档摘要卡片 -- 在 AI 回答之前展示 -->
      <DocSummaryCard
        v-if="docSummary && message.role === 'assistant'"
        :type="docSummary.type"
        :title="docSummary.title"
        :word-count="docSummary.wordCount"
        :preview="docSummary.preview"
        :truncated="docSummary.truncated"
        :truncated-length="docSummary.truncatedLength"
        :error-type="docSummary.errorType"
        :error-message="docSummary.errorMessage"
      />

      <!--
        Thinking 折叠块（兼容路径）：
        - 仅当 timeline 为空但有 thinking 文本时显示（老消息 / 老后端不带
          thinking 时间线节点的情况）。
        - 有 timeline 时，thinking 会作为 timeline-step 节点直接交错渲染
          在工具批次之间，不走此块。
      -->
      <div v-if="groupedDisplayItems.length === 0 && hasThinking" class="thinking-block">
        <button class="thinking-header" @click="showThinking = !showThinking">
          <span class="thinking-icon" :class="isStreaming ? 'animate-pulse' : ''">
            <span class="icon-[lucide--sparkles] text-[10px]" />
          </span>
          <span v-if="isStreaming">思考中...</span>
          <span v-else-if="thinkingDuration > 0">思考过程 · {{ thinkingDuration }}s</span>
          <span v-else>思考过程</span>
          <span
            class="icon-[lucide--chevron-right] ml-auto text-[10px] text-muted-foreground transition-transform duration-150"
            :class="showThinking ? 'rotate-90' : ''"
          />
        </button>
        <div v-if="showThinking" class="thinking-content">
          {{ thinkingText }}
        </div>
      </div>

      <!--
        parts-flow 渲染 —— 按 displayParts 顺序
        统一渲染 text / thinking / process-group / tool / unknown。
        text part 升为顶层渲染，不放进分析过程折叠容器。
      -->
      <div v-if="groupedDisplayItems.length > 0" class="timeline-flow">
        <template v-for="item in groupedDisplayItems" :key="item._key">
          <!-- text part：正文 markdown（顶层渲染，永远不被任何容器包裹） -->
          <div
            v-if="item.kind === 'text'"
            class="ai-prose"
            v-html="renderedPartHtml[item.part.id] || ''"
          />

          <!-- thinking part：默认显示首行预览，多行/超长时点开看全文 -->
          <div
            v-else-if="item.kind === 'thinking'"
            class="timeline-step timeline-step--thinking"
            :class="{ 'is-expandable': thinkingIsMultiline(item.text), 'is-expanded': expandedThinking.has(item.id) }"
            @click="thinkingIsMultiline(item.text) && toggleThinking(item.id)"
          >
            <div class="timeline-step-label">
              <span class="icon-[lucide--sparkles] text-[10px]" />
              思考
              <span
                v-if="thinkingIsMultiline(item.text)"
                class="icon-[lucide--chevron-right] ml-auto text-[10px] text-muted-foreground/50 transition-transform duration-150"
                :class="expandedThinking.has(item.id) ? 'rotate-90' : ''"
              />
            </div>
            <div v-if="expandedThinking.has(item.id) || !thinkingIsMultiline(item.text)" class="timeline-step-text">
              {{ item.text.trim() }}
            </div>
            <div v-else class="timeline-step-text timeline-step-text--preview">
              {{ thinkingPreview(item.text) }}
            </div>
          </div>

          <!-- 未知 part type 兜底（forward-compat schema versioning，） -->
          <div v-else-if="item.kind === 'unknown'" class="unknown-part">
            [未知 part: {{ item.type }}]
          </div>

          <!-- 工作过程：连续「思考 + 工具调用」收拢为三层折叠面板（默认收起） -->
          <ToolProcessGroup
            v-else-if="item.kind === 'process-group'"
            :steps="item.steps"
            :repo-names="repoNames"
            :repo-index="repoIndexById"
            :group-id="item._key"
            :expand-signal="processJump"
            :default-expanded="!!isStreaming"
          />

          <!-- 深度分析组：单个直显，多个 → 横向 swiper（各子代理独立日志） -->
          <DeepAnalysisGroup
            v-else-if="item.kind === 'deep-analysis-group'"
            :items="buildDeepItems(item.items)"
          />

          <!-- 单例 tool（含特殊工具：coding_plan） -->
          <div v-else-if="item.kind === 'tool'" class="tool-inline">
            <div class="tool-pill" @click="toggleTool(item.id)">
              <span v-if="item.status === 'running'" class="tool-dot tool-dot--running" />
              <span v-else class="tool-dot tool-dot--done" />
              <span class="tool-pill-name">{{ toolLabel(item.name) }}</span>
              <span class="tool-pill-desc">{{ toolAction(item.name, item.input || {}, item.result) }}</span>
              <span
                v-if="item.input && Object.keys(item.input).length > 0"
                class="icon-[lucide--chevron-right] text-[9px] text-muted-foreground/40 transition-transform duration-150"
                :class="expandedTools.has(item.id) ? 'rotate-90' : ''"
              />
            </div>
            <TechPlanCard
              v-if="isCodingPlanTool(item.name) && item.status === 'done' && codingPlanData"
              :plan-id="codingPlanData.planId"
              :coding-plan-id="codingPlanData.planId"
              :session-id="codingPlanData.sessionId"
              :tech-plan="codingPlanData.techPlan"
              :affected-files="codingPlanData.affectedFiles"
              :provenance="codingPlanData.provenance"
              :status="codingPlanStatus"
              :is-confirming="codingPlanConfirming"
              :branch-name="codingPlanBranchName"
              :target-repositories="codingPlanData.targetRepositories"
              :available-repositories="codingPlanData.targetRepositories"
              :recommended-repository-ids="codingPlanData.targetRepositories.map(r => r.id)"
              @confirm="(_planId, sessionId, branchName, targetBranch) => sessionId && chatStore.handleConfirmCodingSession(sessionId, branchName, targetBranch)"
            />
            <!--
              110-07：编排在途的阶段时间线。挂在**最后一条**编排 tool item 上，
              避免同一条消息里的「在途 + 终态」两条 tool call 把同一份进度画两遍。
              「桶存在 + 至少一条已知事实」两道门在组件内部，此处不重复。
            -->
            <OrchestrationStageTimeline
              v-if="isOrchestrationTool(item.name) && item.id === lastOrchestrationToolItemId && orchestrationSessionIdFor(item)"
              :session-id="orchestrationSessionIdFor(item)"
            />
            <!--
              110-07：调研容器日志组（每仓一张卡）。
              🔴 `v-if` 与 `:sessions` 必须是**同一个表达式** —— 用未过滤的
              `planResearchSessions` 判条件、却传过滤后的数组（或反过来）会造出
              一个「渲染了一个空组」的形态。
            -->
            <PlanResearchLogGroup
              v-if="isOrchestrationTool(item.name) && item.id === lastOrchestrationToolItemId && planResearchSessionsFor(item).length > 0"
              :sessions="planResearchSessionsFor(item)"
              :repo-names="repoNames"
            />
            <!--
              109-04：编排产出「进入编码」入口。三条渲染条件同时成立才渲染。
              🔴 按 item.result 逐条解析——异步路径上同一消息有两条同名编排工具，
              只有携带 artifact_version_id 的那一条才渲染卡片。
            -->
            <OrchestratedPlanCard
              v-if="isOrchestrationTool(item.name) && item.status === 'done' && resolveOrchestratedPlanData(item.result)"
              :artifact-version-id="resolveOrchestratedPlanData(item.result)!.artifactVersionId"
            />
            <!--
              编排工具的详情面板只在「卡片已渲染」时才抑制。若无条件按工具名抑制，
              在途 / 失败态（按裁决 D-4 不渲染卡片）下箭头会转但面板永不出现，
              整条 pill 变成一个点了没反应的可点元素。
            -->
            <div
              v-if="expandedTools.has(item.id) && !isCodingPlanTool(item.name) && !(isOrchestrationTool(item.name) && resolveOrchestratedPlanData(item.result))"
              class="tool-detail"
            >
              <div class="tool-detail-section">
                <span class="tool-detail-label">输入</span>
                <StructuredJsonView :value="item.input" :tool-name="item.name" kind="input" />
              </div>
              <div v-if="item.result" class="tool-detail-section">
                <span class="tool-detail-label">输出</span>
                <StructuredJsonView :value="item.result" :tool-name="item.name" kind="output" />
              </div>
            </div>
          </div>
        </template>
      </div>

      <!--
        引用仓库图例（借鉴 open-webui Citations）：把本条回答涉及的仓库以
        「编号 + 名称」呈现，点击跳回并高亮上方过程面板，形成结论 ↔ 证据闭环。
      -->
      <div v-if="showRepoLegend" class="repo-legend">
        <span class="repo-legend-title">
          <span class="icon-[lucide--folder-git-2] text-[11px]" />
          引用仓库
        </span>
        <button
          v-for="r in repoRefs"
          :key="r.id"
          type="button"
          class="repo-legend-item"
          :title="`跳转到过程中对 ${r.name} 的检索`"
          @click="jumpToProcess"
        >
          <span class="repo-legend-avatar">{{ repoInitial(r.name) }}</span>
          <span class="repo-legend-num">{{ r.index }}</span>
          <span class="repo-legend-name">{{ r.name }}</span>
        </button>
      </div>

      <!--
        流式但 displayParts 为空 → 显示打字光标占位。
        正文 markdown 已经由上方 parts-flow 中 text part 直接渲染（顶层 ai-prose），
        不再需要独立的 ai-prose 块。
      -->
      <div v-if="isStreaming && !suppressTypingCursor && groupedDisplayItems.length === 0" class="flex items-center py-2">
        <span class="typing-cursor" />
      </div>
      <span v-else-if="isStreaming && !suppressTypingCursor" class="typing-cursor" />

      <!-- 状态 Badge -->
      <div v-if="messageStatus === 'interrupted'" class="status-badge status-badge--interrupted">
        <span class="icon-[lucide--octagon-x] text-[10px]" />
        已中断
      </div>
      <div v-else-if="messageStatus === 'budget_exceeded'" class="status-badge status-badge--budget">
        <span class="icon-[lucide--wallet] text-[10px]" />
        已达到预算上限
      </div>
      <div v-if="degradedInfo" class="status-badge status-badge--degraded" :title="degradedInfo.reason">
        <span class="icon-[lucide--triangle-alert] text-[10px]" />
        降级回答{{ degradedInfo.reason ? ` · ${degradedInfo.reason}` : '' }}
      </div>

      <!-- 操作栏 -->
      <div class="action-bar">
        <button class="action-btn" @click="copyContent">
          <span v-if="copied" class="icon-[lucide--check] text-primary" />
          <span v-else class="icon-[lucide--copy]" />
          <span class="action-label">{{ copied ? '已复制' : '复制' }}</span>
        </button>
        <!-- 飞书导出入口仅在空间配置可用时展示（chatStore.feishuExportAvailable） -->
        <template v-if="props.message.role === 'assistant' && (chatStore.feishuExportAvailable || exportedDoc)">
          <!-- 未导出态：单个「导出到飞书」按钮（向后兼容） -->
          <button
            v-if="!exportedDoc"
            class="action-btn action-btn--feishu"
            title="导出到飞书"
            @click="emit('exportSingle', props.message.id)"
          >
            <svg
              class="feishu-logo"
              viewBox="0 0 48 48"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
              aria-hidden="true"
            >
              <path d="M10 8c0 1 7 3.5 14.745 16.744 0 0 4.184-4.363 6.255-5.744 1.5-1 2.712-1.332 2.712-1.332C33.712 15.156 29.5 8 28 8z" fill="#00d6b9" />
              <path d="M43.5 18.5c-1-.667-3.65-1.771-6.5-1.5a15 15 0 0 0-3.288.668S32.5 18 31 19c-2.07 1.38-6.255 5.744-6.255 5.744-1.428 1.397-3.05 2.732-5.245 3.756 0 0 7 3 11.5 3 5.063 0 7-3.5 7-3.5 1.5-3.305 3.5-7 5.5-9.5" fill="#163c9a" />
              <path d="M4 17.5v17c0 1 6 5.5 15 5.5 10 0 17.05-7.705 19-12 0 0-1.937 3.5-7 3.5-4.5 0-11.5-3-11.5-3-5.117-2.239-10.03-6.577-12.906-9.117C4.974 17.953 4 17.093 4 17.5" fill="#3370ff" />
            </svg>
            <span class="action-label">导出到飞书</span>
          </button>
          <!-- 已导出态：在飞书打开 + 重新导出（与 285-04 TechPlanCard 三态对齐） -->
          <template v-else>
            <button
              class="action-btn action-btn--feishu"
              title="在飞书打开"
              @click="openFeishu"
            >
              <span class="icon-[lucide--external-link]" />
              <span class="action-label">在飞书打开</span>
            </button>
            <button
              v-if="chatStore.feishuExportAvailable"
              class="action-btn"
              aria-label="重新导出"
              title="重新导出"
              @click="emit('exportSingle', props.message.id)"
            >
              <span class="icon-[lucide--refresh-cw]" />
            </button>
          </template>
        </template>
        <span class="action-divider" />
        <span class="action-meta">{{ formatTime(message.created_at) }}</span>
        <template v-if="metadata?.model">
          <span class="action-meta">·</span>
          <span class="action-meta">{{ metadata.model }}</span>
        </template>
        <template v-if="tokenDisplay">
          <span class="action-meta">·</span>
          <span class="action-meta font-mono">{{ tokenDisplay }}</span>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ============ User Bubble ============ */
.user-message-row {
  display: flex;
  justify-content: flex-end;
  padding-left: 3.5rem;
}

.user-message-stack {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.375rem;
  max-width: min(100%, 38rem);
}

.user-bubble {
  max-width: min(100%, 38rem);
  padding: 0.75rem 1.0625rem;
  border-radius: 1.25rem 1.25rem 0.4375rem 1.25rem;
  border: 1px solid hsl(168 76% 42% / 0.13);
  /* 主题色淡渐变：与欢迎页 / 输入卡片同一视觉语言 */
  background: linear-gradient(135deg, hsl(168 56% 95.5%), hsl(176 48% 93.5%));
  color: hsl(215 30% 22%);
  font-size: 0.9rem;
  font-weight: 480;
  line-height: 1.7;
  letter-spacing: -0.005em;
  white-space: pre-wrap;
  word-break: break-word;
  box-shadow: 0 1px 2px hsl(168 60% 30% / 0.05);
}

.image-preview-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(8rem, 12rem));
  justify-content: end;
  gap: 0.5rem;
  width: min(100%, 38rem);
}

.image-preview-thumb {
  width: 100%;
  aspect-ratio: 4 / 3;
  border-radius: 0.75rem;
  border: 1px solid hsl(214 32% 86% / 0.9);
  background: hsl(210 40% 96%);
  object-fit: cover;
  box-shadow: 0 1px 2px hsl(215 28% 17% / 0.06);
  cursor: zoom-in;
  transition:
    transform 0.18s ease,
    box-shadow 0.18s ease;
}
.image-preview-thumb:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px hsl(215 28% 17% / 0.12);
}
/* medium-zoom 放大时的图层在 body 上，保证盖过对话内容 */
:global(.medium-zoom-overlay),
:global(.medium-zoom-image--opened) {
  z-index: 999;
}

.user-edit-trigger {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.25rem 0.5rem;
  border-radius: 9999px;
  color: hsl(215 16% 45%);
  font-size: 0.6875rem;
  font-weight: 700;
  opacity: 0;
  transition:
    opacity 0.15s ease,
    background-color 0.15s ease,
    color 0.15s ease;
}

.user-message-row:hover .user-edit-trigger,
.user-edit-trigger:focus-visible {
  opacity: 1;
}

.user-edit-trigger:hover,
.user-edit-trigger:focus-visible {
  background: hsl(168 76% 42% / 0.08);
  color: hsl(168 76% 32%);
  outline: none;
}

/* 编辑面板：复用主输入卡片的视觉语言（圆角卡 + 无内边框 textarea + 底部操作条） */
.user-edit-panel {
  width: min(100%, 38rem);
  border-radius: 1.25rem;
  border: 1px solid hsl(168 76% 42% / 0.45);
  background: hsl(0 0% 100%);
  box-shadow:
    0 0 0 3px hsl(168 76% 42% / 0.08),
    0 12px 32px hsl(215 28% 17% / 0.1);
  overflow: hidden;
}

.user-edit-textarea {
  display: block;
  width: 100%;
  min-height: 3.25rem;
  max-height: 18rem;
  resize: vertical;
  border: none;
  outline: none;
  background: transparent;
  padding: 0.75rem 1rem 0.25rem;
  color: hsl(215 28% 18%);
  font-size: 0.9rem;
  font-weight: 450;
  line-height: 1.7;
  white-space: pre-wrap;
  text-align: left;
}
.user-edit-textarea::placeholder {
  color: hsl(215 16% 62%);
}

/* 编辑态图片预览条 */
.edit-image-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  padding: 0.25rem 1rem 0.125rem;
}

.edit-image-chip {
  position: relative;
  width: 4rem;
  height: 4rem;
  border-radius: 0.625rem;
  overflow: hidden;
  border: 1px solid hsl(214 32% 86% / 0.9);
  background: hsl(210 40% 96%);
}
.edit-image-chip--error {
  border-color: hsl(0 72% 51% / 0.4);
}

.edit-image-thumb {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.edit-image-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: hsl(215 28% 17% / 0.45);
  color: white;
}

.edit-image-remove {
  position: absolute;
  top: 0.1875rem;
  right: 0.1875rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.125rem;
  height: 1.125rem;
  border-radius: 9999px;
  background: hsl(215 28% 17% / 0.62);
  color: white;
  transition:
    background-color 0.15s ease,
    opacity 0.15s ease;
}
.edit-image-remove:hover:not(:disabled) {
  background: hsl(0 72% 51%);
}
.edit-image-remove:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.user-edit-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.375rem 0.625rem 0.625rem 0.625rem;
  border-top: 1px solid hsl(214 32% 91% / 0.6);
  margin-top: 0.25rem;
}

.user-edit-actions-left {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  min-width: 0;
}

.user-edit-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.875rem;
  height: 1.875rem;
  border-radius: 0.5rem;
  color: hsl(215 16% 50%);
  flex-shrink: 0;
  transition:
    background-color 0.15s ease,
    color 0.15s ease;
}
.user-edit-icon-btn:hover:not(:disabled) {
  background: hsl(168 76% 42% / 0.1);
  color: hsl(168 76% 34%);
}
.user-edit-icon-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.user-edit-hint {
  font-size: 0.6875rem;
  color: hsl(215 16% 60%);
  user-select: none;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.user-edit-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.3125rem;
  min-height: 2rem;
  padding: 0 0.875rem;
  border-radius: 9999px;
  font-size: 0.75rem;
  font-weight: 600;
  white-space: nowrap;
  transition:
    opacity 0.15s ease,
    background-color 0.15s ease,
    color 0.15s ease,
    box-shadow 0.15s ease;
}

.user-edit-btn--ghost {
  color: hsl(215 16% 45%);
}

.user-edit-btn--ghost:hover,
.user-edit-btn--ghost:focus-visible {
  background: hsl(215 16% 47% / 0.08);
  color: hsl(215 28% 25%);
  outline: none;
}

.user-edit-btn--primary {
  background: hsl(168 76% 42%);
  color: white;
  box-shadow: 0 1px 3px hsl(168 76% 42% / 0.3);
}

.user-edit-btn--primary:hover:not(:disabled),
.user-edit-btn--primary:focus-visible:not(:disabled) {
  background: hsl(167 76% 36%);
  outline: none;
}

.user-edit-btn:disabled {
  cursor: not-allowed;
  opacity: 0.45;
  box-shadow: none;
}

/* ============ AI Message ============ */
.ai-message {
  display: flex;
  align-items: flex-start;
  gap: 0.875rem;
}

.assistant-avatar {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 2.375rem;
  height: 2.375rem;
  margin-top: 0.125rem;
  border-radius: 0.875rem;
  background: hsl(0 0% 100% / 0.84);
  border: 1px solid hsl(168 76% 42% / 0.18);
  box-shadow: 0 1px 2px hsl(215 28% 17% / 0.06);
  flex-shrink: 0;
}

.assistant-avatar-logo {
  width: 1.45rem;
  height: 1.45rem;
  object-fit: contain;
}

.assistant-message-shell {
  flex: 1;
  min-width: 0;
  max-width: 100%;
  padding: 0.95rem 1.125rem 0.7rem;
  border-radius: 1.25rem 1.25rem 1.25rem 0.4375rem;
  border: 1px solid hsl(214 32% 89% / 0.7);
  background: hsl(0 0% 100% / 0.82);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  box-shadow: 0 1px 3px hsl(215 28% 17% / 0.04);
}

.assistant-message-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 0.75rem;
}

.assistant-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-width: 0;
  color: hsl(215 28% 18%);
  font-size: 0.75rem;
  font-weight: 800;
  letter-spacing: 0.01em;
}

.assistant-model {
  overflow: hidden;
  max-width: 14rem;
  padding: 0.125rem 0.4375rem;
  border-radius: 9999px;
  background: hsl(215 16% 47% / 0.08);
  color: hsl(215 16% 45%);
  font-size: 0.625rem;
  font-family: 'SF Mono', 'Fira Code', 'JetBrains Mono', ui-monospace, monospace;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.assistant-time {
  color: hsl(215 16% 60% / 0.82);
  font-size: 0.6875rem;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
}

.timeline-flow + .ai-prose,
.tool-flow + .ai-prose {
  margin-top: 0.95rem;
  padding-top: 0.95rem;
  border-top: 1px solid hsl(214 32% 90% / 0.9);
}

/* ============ Timeline ============ */
.timeline-flow {
  display: flex;
  flex-direction: column;
  /* 同一时间线内部紧凑，让 tool group / 单 pill 自然成块 */
  gap: 0.375rem;
}

.timeline-step {
  border-radius: 0.625rem;
  border: 1px solid hsl(214 32% 91% / 0.5);
  background: hsl(210 40% 98% / 0.55);
  padding: 0.5rem 0.625rem;
}

.timeline-step--thinking {
  background: hsl(168 76% 96% / 0.55);
}
.timeline-step--thinking.is-expandable {
  cursor: pointer;
  transition: background-color 0.15s ease;
}
.timeline-step--thinking.is-expandable:hover {
  background: hsl(168 76% 94% / 0.7);
}

/* timeline-step--narration 已删除 */

.unknown-part {
  font-size: 0.6875rem;
  color: hsl(215 16% 47% / 0.6);
  padding: 0.25rem 0.5rem;
  border-radius: 0.375rem;
  border: 1px dashed hsl(214 32% 86%);
  background: hsl(0 0% 100% / 0.6);
  font-family: 'SF Mono', 'Fira Code', ui-monospace, monospace;
}

.timeline-step-label {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.6875rem;
  font-weight: 600;
  color: hsl(215 16% 42% / 0.8);
  margin-bottom: 0.25rem;
}

.timeline-step-text {
  font-size: 0.75rem;
  line-height: 1.7;
  color: hsl(215 16% 35%);
  white-space: pre-wrap;
  word-break: break-word;
}
.timeline-step-text--preview {
  /* 收起态首行预览：单行省略 + 颜色弱化 */
  color: hsl(215 16% 50% / 0.85);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ============ Tool Flow — 行内 pill ============ */
.tool-flow {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.tool-inline {
  display: flex;
  flex-direction: column;
}

.tool-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.3125rem 0.75rem;
  border-radius: 0.5rem;
  font-size: 0.75rem;
  cursor: pointer;
  transition:
    background-color 0.15s ease,
    border-color 0.15s ease;
  width: fit-content;
  max-width: 100%;
  /* button reset：用作 <button> 时 */
  border: 0;
  background: transparent;
  text-align: left;
  font-family: inherit;
}
.tool-pill:hover {
  background: hsl(210 40% 96%);
}
.tool-pill:focus-visible {
  outline: 2px solid hsl(168 76% 42% / 0.4);
  outline-offset: 1px;
}

.tool-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  flex-shrink: 0;
}
.tool-dot--running {
  background: hsl(168 76% 42%);
  animation: pulse-dot 1.5s infinite;
}
.tool-dot--done {
  background: hsl(142 71% 45%);
}

.tool-pill-name {
  font-weight: 600;
  color: hsl(215 28% 17%);
  white-space: nowrap;
}

.tool-pill-desc {
  /* §6 color-accessible-pairs：提高对比度 0.7 → 0.85 */
  color: hsl(215 16% 42%);
  font-size: 0.6875rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

/* Tool detail (展开) */
.tool-detail {
  margin-left: 1.25rem;
  padding: 0.375rem 0.5rem;
  border-left: 2px solid hsl(214 32% 91% / 0.6);
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.tool-detail-section {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}

.tool-detail-label {
  font-size: 0.5625rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: hsl(215 16% 47% / 0.5);
}

/* ============ Thinking — 全量展示 ============ */
.thinking-block {
  border-radius: 0.625rem;
  border: 1px solid hsl(214 32% 91% / 0.5);
  background: hsl(210 40% 98% / 0.6);
  overflow: hidden;
}

.thinking-header {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.375rem 0.625rem;
  font-size: 0.6875rem;
  color: hsl(215 16% 47% / 0.7);
  border-bottom: 1px solid hsl(214 32% 91% / 0.4);
  width: 100%;
  background: transparent;
  border-left: 0;
  border-right: 0;
  border-top: 0;
  text-align: left;
  cursor: pointer;
}

.thinking-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 1.125rem;
  height: 1.125rem;
  border-radius: 0.3125rem;
  background: hsl(168 76% 42% / 0.08);
  color: hsl(168 76% 42%);
}

.thinking-content {
  padding: 0.5rem 0.625rem;
  font-size: 0.75rem;
  line-height: 1.7;
  color: hsl(215 16% 35%);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 30rem;
  overflow-y: auto;
}

/* ============ Prose ============ */
.ai-prose {
  font-size: 0.9375rem;
  line-height: 1.75;
  color: hsl(215 28% 17%);
}

.ai-prose :deep(h1) {
  font-size: 1.375rem;
  font-weight: 700;
  letter-spacing: -0.01em;
  margin: 1.75rem 0 0.75rem;
  color: hsl(215 28% 12%);
}
.ai-prose :deep(h1:first-child) {
  margin-top: 0;
}

.ai-prose :deep(h2) {
  font-size: 1.175rem;
  font-weight: 650;
  letter-spacing: -0.005em;
  margin: 1.5rem 0 0.5rem;
  color: hsl(215 28% 12%);
}
.ai-prose :deep(h2:first-child) {
  margin-top: 0;
}

.ai-prose :deep(h3) {
  font-size: 1rem;
  font-weight: 600;
  margin: 1.25rem 0 0.375rem;
  color: hsl(215 28% 15%);
}
.ai-prose :deep(h3:first-child) {
  margin-top: 0;
}

.ai-prose :deep(p) {
  margin: 0.625rem 0;
}
.ai-prose :deep(p:first-child) {
  margin-top: 0;
}
.ai-prose :deep(p:last-child) {
  margin-bottom: 0;
}

.ai-prose :deep(strong) {
  font-weight: 600;
  color: hsl(215 28% 12%);
}

.ai-prose :deep(a) {
  color: hsl(168 76% 36%);
  text-decoration: none;
  border-bottom: 1px solid hsl(168 76% 42% / 0.3);
  transition: border-color 0.15s;
}
.ai-prose :deep(a:hover) {
  border-bottom-color: hsl(168 76% 42%);
}

.ai-prose :deep(ul) {
  list-style: disc;
  padding-left: 1.375rem;
  margin: 0.5rem 0;
}
.ai-prose :deep(ol) {
  list-style: decimal;
  padding-left: 1.375rem;
  margin: 0.5rem 0;
}
.ai-prose :deep(li) {
  margin: 0.25rem 0;
  padding-left: 0.25rem;
}
.ai-prose :deep(li > p) {
  margin: 0.125rem 0;
}
.ai-prose :deep(li::marker) {
  color: hsl(215 16% 60%);
}

.ai-prose :deep(code) {
  font-size: 0.8125rem;
  font-weight: 500;
  padding: 0.125rem 0.375rem;
  border-radius: 0.3125rem;
  background: hsl(168 76% 42% / 0.07);
  color: hsl(168 56% 30%);
  font-family: 'SF Mono', 'Fira Code', 'JetBrains Mono', ui-monospace, monospace;
}

.ai-prose :deep(pre) {
  margin: 0.875rem 0;
  border-radius: 0.75rem;
  border: 1px solid hsl(214 32% 91% / 0.5);
  overflow-x: auto;
  font-size: 0.8125rem;
  line-height: 1.6;
}
.ai-prose :deep(pre code) {
  background: transparent;
  padding: 0;
  border-radius: 0;
  color: inherit;
  font-weight: 400;
}

.ai-prose :deep(blockquote) {
  border-left: 3px solid hsl(168 76% 42% / 0.4);
  padding: 0.25rem 0 0.25rem 1rem;
  margin: 0.75rem 0;
  color: hsl(215 16% 47%);
}
.ai-prose :deep(blockquote p) {
  margin: 0.25rem 0;
}

.ai-prose :deep(hr) {
  border: none;
  border-top: 1px solid hsl(214 32% 91%);
  margin: 1.5rem 0;
}

.ai-prose :deep(table) {
  display: block;
  width: max-content;
  min-width: 100%;
  max-width: 100%;
  overflow-x: auto;
  border-collapse: collapse;
  font-size: 0.8125rem;
  margin: 0.875rem 0;
  border: 1px solid hsl(214 32% 91% / 0.8);
  border-radius: 0.875rem;
  scrollbar-width: thin;
}
.ai-prose :deep(th) {
  text-align: left;
  font-weight: 600;
  padding: 0.625rem 0.875rem;
  border-bottom: 2px solid hsl(214 32% 91%);
  white-space: nowrap;
}
.ai-prose :deep(td) {
  padding: 0.625rem 0.875rem;
  border-bottom: 1px solid hsl(214 32% 91% / 0.6);
  vertical-align: top;
  white-space: nowrap;
}
.ai-prose :deep(td code),
.ai-prose :deep(th code) {
  white-space: nowrap;
}
.ai-prose :deep(tr:last-child td) {
  border-bottom: none;
}

/* ============ Typing Cursor ============ */
.typing-cursor {
  display: inline-block;
  width: 2px;
  height: 1.125rem;
  background: hsl(168 76% 42%);
  border-radius: 1px;
  animation: blink 1s step-end infinite;
  vertical-align: text-bottom;
  margin-left: 1px;
}
@keyframes blink {
  50% {
    opacity: 0;
  }
}

/* ============ Status Badge ============ */
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.25rem 0.625rem;
  border-radius: 9999px;
  font-size: 0.6875rem;
  font-weight: 500;
}
.status-badge--interrupted {
  background: hsl(0 72% 51% / 0.06);
  color: hsl(0 72% 51%);
  border: 1px solid hsl(0 72% 51% / 0.12);
}
.status-badge--budget {
  background: hsl(38 92% 50% / 0.06);
  color: hsl(38 80% 40%);
  border: 1px solid hsl(38 92% 50% / 0.12);
}
.status-badge--degraded {
  background: hsl(38 92% 50% / 0.06);
  color: hsl(38 80% 40%);
  border: 1px solid hsl(38 92% 50% / 0.12);
}

/* ============ 引用仓库图例（borrowed from open-webui Citations） ============ */
.repo-legend {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.375rem;
  margin-top: 0.75rem;
  padding-top: 0.625rem;
  border-top: 1px dashed hsl(214 32% 90% / 0.9);
}

.repo-legend-title {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 0.6875rem;
  font-weight: 600;
  color: hsl(215 16% 45%);
}

.repo-legend-item {
  display: inline-flex;
  align-items: center;
  gap: 0.3125rem;
  padding: 0.1875rem 0.5rem 0.1875rem 0.1875rem;
  border-radius: 9999px;
  border: 1px solid hsl(214 32% 88% / 0.9);
  background: hsl(0 0% 100% / 0.8);
  font-size: 0.6875rem;
  color: hsl(215 28% 25%);
  cursor: pointer;
  font-family: inherit;
  transition:
    background-color 0.15s ease,
    border-color 0.15s ease;
}
.repo-legend-item:hover {
  border-color: hsl(168 76% 42% / 0.4);
  background: hsl(168 76% 96% / 0.6);
}

.repo-legend-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.125rem;
  height: 1.125rem;
  border-radius: 9999px;
  background: hsl(217 91% 60% / 0.16);
  color: hsl(217 70% 42%);
  font-size: 0.5625rem;
  font-weight: 700;
}

.repo-legend-num {
  font-size: 0.5625rem;
  font-weight: 700;
  color: hsl(168 70% 32%);
  font-variant-numeric: tabular-nums;
}

.repo-legend-name {
  font-weight: 600;
}

.dark .repo-legend-item {
  background: hsl(220 20% 16% / 0.8);
  border-color: hsl(214 32% 28% / 0.7);
  color: hsl(215 16% 78%);
}

/* ============ Action Bar ============ */
.action-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem;
  padding-top: 0.75rem;
}

.action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.375rem;
  min-height: 1.875rem;
  padding: 0.3125rem 0.625rem;
  border-radius: 9999px;
  border: 1px solid hsl(214 32% 88% / 0.9);
  background: hsl(0 0% 100% / 0.72);
  font-size: 0.75rem;
  font-weight: 600;
  color: hsl(215 16% 42%);
  cursor: pointer;
  transition:
    background-color 0.15s ease,
    border-color 0.15s ease,
    color 0.15s ease;
}
.action-btn:hover {
  border-color: hsl(214 32% 82%);
  background: hsl(210 40% 98%);
  color: hsl(215 28% 17%);
}

.action-btn--feishu {
  border-color: hsl(168 76% 42% / 0.22);
  color: hsl(168 70% 28%);
}

.action-btn--feishu:hover {
  border-color: hsl(168 76% 42% / 0.34);
  background: hsl(168 76% 42% / 0.06);
}

.action-label {
  line-height: 1rem;
  white-space: nowrap;
}

.feishu-logo {
  display: inline-block;
  width: 1rem;
  height: 1rem;
  flex-shrink: 0;
}

.action-divider {
  width: 1px;
  height: 1rem;
  background: hsl(214 32% 91%);
  margin: 0 0.125rem;
}
.action-meta {
  font-size: 0.6875rem;
  color: hsl(215 16% 60% / 0.7);
}

@keyframes pulse-dot {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.4;
  }
}
</style>
