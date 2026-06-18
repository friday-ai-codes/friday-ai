<script setup lang="ts">
/**
 * 只读会话查看器（ADMVW-02）。
 *
 * 视觉与正式聊天（ChatMessageBubble）同源：助手头像 + 「Friday AI」头 + `.ai-prose`
 * markdown 正文 + 把连续「思考 / 工具调用」收拢为「分析过程」折叠面板（复用聊天同款
 * `ToolProcessGroup`）。用户消息走聊天同款气泡。
 *
 * **纯只读纪律**：组件内无任何写入入口——无 `<input>`/`<textarea>`、无发送/编辑/
 * 删除/导出/确认按钮，且**不 import chatStore / repositoriesStore**（与
 * ChatMessageBubble 的流式 / 选择 / 编码确认深耦合彻底解耦）。仅静态回放历史消息。
 */
import type { ProcessStep } from '~/components/chat/ToolProcessGroup.vue'
import type { ConversationMessage, ImagePart, MessagePart, TextPart, ToolUsePart } from '~/types/chat'
import { computed, ref, watch } from 'vue'
import ToolProcessGroup from '~/components/chat/ToolProcessGroup.vue'
import { getMarkdownRenderer } from '~/composables/useMarkdownRenderer'
import { hydrateLegacyMessage } from '~/composables/useMessageParts'
import { bareName, collectRepoNames, relevanceCandidates } from '~/composables/useToolDisplay'

const props = defineProps<{
  messages: ConversationMessage[]
}>()

const API_BASE = import.meta.env.VITE_API_BASE || '/api'

// --- parts-flow 渲染节点（与聊天 groupedDisplayItems 同构，去掉流式 / 特殊卡片）---
interface TextNode { kind: 'text', _key: string, id: string }
interface ThinkingNode { kind: 'thinking', _key: string, id: string, text: string }
interface ProcessNode { kind: 'process-group', _key: string, steps: ProcessStep[] }
interface ImageNode { kind: 'image', _key: string, part: ImagePart }
type DisplayNode = TextNode | ThinkingNode | ProcessNode | ImageNode

interface RenderMessage {
  id: string
  role: ConversationMessage['role']
  /** 用户气泡正文（拼接所有 text part） */
  text: string
  images: ImagePart[]
  nodes: DisplayNode[]
}

/**
 * parts → 渲染节点。顺序扫描，把连续的「思考 + 工具调用」累积成一个 process run：
 *   - run 含至少 1 个工具 → ToolProcessGroup（折叠面板）。
 *   - run 只有思考 → 退化为顶层 inline 思考节点。
 */
function buildNodes(parts: MessagePart[]): DisplayNode[] {
  const out: DisplayNode[] = []
  let run: ProcessStep[] = []

  const flush = () => {
    if (run.length === 0)
      return
    if (run.some(s => s.kind === 'tool')) {
      out.push({ kind: 'process-group', _key: `pg-${run[0].id}`, steps: run })
    }
    else {
      for (const s of run) {
        if (s.kind === 'thinking')
          out.push({ kind: 'thinking', _key: s.id, id: s.id, text: s.text })
      }
    }
    run = []
  }

  for (let i = 0; i < parts.length; i++) {
    const cur = parts[i]
    if (cur.type === 'text') {
      flush()
      out.push({ kind: 'text', _key: cur.id, id: cur.id })
    }
    else if (cur.type === 'thinking') {
      run.push({ kind: 'thinking', id: cur.id, text: cur.text ?? '' })
    }
    else if (cur.type === 'tool_use') {
      run.push({
        kind: 'tool',
        id: cur.tool_call_id || cur.id,
        name: cur.name,
        input: cur.input,
        result: cur.result ?? undefined,
        status: cur.status === 'running' ? 'running' : 'done',
      })
    }
    else if (cur.type === 'image') {
      flush()
      out.push({ kind: 'image', _key: cur.id, part: cur })
    }
  }
  flush()
  return out
}

const renderMessages = computed<RenderMessage[]>(() =>
  (props.messages ?? []).map((msg) => {
    const parts = hydrateLegacyMessage(msg)
    return {
      id: msg.id,
      role: msg.role,
      text: parts.filter((p): p is TextPart => p.type === 'text').map(p => p.text).join('')
        || (msg.role === 'user' ? msg.content : ''),
      images: parts.filter((p): p is ImagePart => p.type === 'image'),
      nodes: buildNodes(parts),
    }
  }),
)

// 全部 tool_use part（跨消息），用于会话级仓库名映射 + 编号来源（与聊天一致，但不依赖 store）
const allToolParts = computed<ToolUsePart[]>(() =>
  (props.messages ?? []).flatMap(msg =>
    hydrateLegacyMessage(msg).filter((p): p is ToolUsePart => p.type === 'tool_use'),
  ),
)

const repoNames = computed<Record<string, string>>(() => {
  const map: Record<string, string> = {}
  for (const p of allToolParts.value)
    Object.assign(map, collectRepoNames(p.name, p.input, p.result ?? undefined))
  return map
})

const repoIndex = computed<Map<string, number>>(() => {
  const m = new Map<string, number>()
  const add = (id: string) => {
    if (id && !m.has(id))
      m.set(id, m.size + 1)
  }
  for (const p of allToolParts.value) {
    if (bareName(p.name) === 'analyze_repository_relevance') {
      for (const c of relevanceCandidates(p.result ?? undefined))
        add(c.id)
    }
  }
  for (const p of allToolParts.value)
    add((p.input?.repository_id as string) || '')
  return m
})

// text part → markdown HTML（异步单例渲染器）
const renderedHtml = ref<Record<string, string>>({})
watch(
  () => props.messages,
  async (list) => {
    const md = await getMarkdownRenderer()
    const next: Record<string, string> = {}
    for (const msg of list ?? []) {
      for (const part of hydrateLegacyMessage(msg)) {
        if (part.type === 'text')
          next[part.id] = md.render(part.text ?? '')
      }
    }
    renderedHtml.value = next
  },
  { immediate: true },
)

// 标准独立思考节点的展开态（默认收起，仅显示首行预览）
const expandedThinking = ref<Set<string>>(new Set())
function toggleThinking(id: string) {
  if (expandedThinking.value.has(id))
    expandedThinking.value.delete(id)
  else
    expandedThinking.value.add(id)
}
function thinkingPreview(text: string): string {
  const firstLine = text.trim().split('\n')[0] || ''
  return firstLine.length > 80 ? `${firstLine.slice(0, 80)}…` : firstLine
}
function thinkingIsMultiline(text: string): boolean {
  const trimmed = text.trim()
  return trimmed.includes('\n') || trimmed.length > 80
}

function imageSrc(part: ImagePart): string {
  if (part.source_url)
    return part.source_url
  const fileName = (part.storage_ref || '').split('/').pop()
  return fileName ? `${API_BASE}/chat/images/${encodeURIComponent(fileName)}/` : ''
}

function roleTitle(role: ConversationMessage['role']): string {
  switch (role) {
    case 'assistant': return 'Friday AI'
    case 'system': return '系统'
    case 'tool': return '工具'
    default: return String(role)
  }
}
</script>

<template>
  <div class="readonly-conversation">
    <p
      v-if="renderMessages.length === 0"
      class="py-12 text-center text-sm text-muted-foreground"
    >
      该会话暂无消息
    </p>

    <template v-for="msg in renderMessages" :key="msg.id">
      <!-- ============ 用户消息 ============ -->
      <div v-if="msg.role === 'user'" class="user-message-row">
        <div class="user-message-stack">
          <div v-if="msg.text" class="user-bubble">
            {{ msg.text }}
          </div>
          <div v-if="msg.images.length > 0" class="image-preview-grid">
            <img
              v-for="part in msg.images"
              :key="part.id"
              class="image-preview-thumb"
              :src="imageSrc(part)"
              :alt="part.alt_text || '图片'"
              loading="lazy"
            >
          </div>
        </div>
      </div>

      <!-- ============ AI / 系统 / 工具消息 ============ -->
      <div v-else class="ai-message">
        <div class="assistant-avatar">
          <img src="/logo-mark.svg" alt="" aria-hidden="true" class="assistant-avatar-logo">
        </div>
        <div class="assistant-message-shell">
          <div class="assistant-message-header">
            <div class="assistant-title">
              <span>{{ roleTitle(msg.role) }}</span>
            </div>
          </div>

          <p
            v-if="msg.nodes.length === 0"
            class="text-sm text-muted-foreground/60 italic"
          >
            （无内容）
          </p>

          <div v-else class="timeline-flow">
            <template v-for="node in msg.nodes" :key="node._key">
              <!-- 正文 markdown -->
              <div
                v-if="node.kind === 'text'"
                class="ai-prose"
                v-html="renderedHtml[node.id] || ''"
              />

              <!-- 独立思考：默认首行预览，多行/超长点开看全文 -->
              <div
                v-else-if="node.kind === 'thinking'"
                class="timeline-step timeline-step--thinking"
                :class="{ 'is-expandable': thinkingIsMultiline(node.text), 'is-expanded': expandedThinking.has(node.id) }"
                @click="thinkingIsMultiline(node.text) && toggleThinking(node.id)"
              >
                <div class="timeline-step-label">
                  <span class="icon-[lucide--sparkles] text-[10px]" />
                  思考
                  <span
                    v-if="thinkingIsMultiline(node.text)"
                    class="icon-[lucide--chevron-right] ml-auto text-[10px] text-muted-foreground/50 transition-transform duration-150"
                    :class="expandedThinking.has(node.id) ? 'rotate-90' : ''"
                  />
                </div>
                <div v-if="expandedThinking.has(node.id) || !thinkingIsMultiline(node.text)" class="timeline-step-text">
                  {{ node.text.trim() }}
                </div>
                <div v-else class="timeline-step-text timeline-step-text--preview">
                  {{ thinkingPreview(node.text) }}
                </div>
              </div>

              <!-- 工作过程：连续思考 + 工具调用折叠面板（只读，默认收起） -->
              <ToolProcessGroup
                v-else-if="node.kind === 'process-group'"
                :steps="node.steps"
                :repo-names="repoNames"
                :repo-index="repoIndex"
                :group-id="node._key"
                :default-expanded="false"
              />

              <!-- 图片 -->
              <img
                v-else-if="node.kind === 'image'"
                class="image-preview-thumb image-preview-thumb--inline"
                :src="imageSrc(node.part)"
                :alt="node.part.alt_text || '图片'"
                loading="lazy"
              >
            </template>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.readonly-conversation {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  /* 关键：作为 Dialog grid 子项，min-width:0 才能让内部超长代码块横向滚动
     而不是把整个弹窗撑破 max-w（否则 pre 的 overflow-x:auto 不生效）。 */
  min-width: 0;
  max-width: 100%;
}

/* ============ User Bubble（与 ChatMessageBubble 同源） ============ */
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
}
.image-preview-thumb--inline {
  max-width: 16rem;
  margin: 0.25rem 0;
}

/* ============ AI Message（与 ChatMessageBubble 同源） ============ */
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
  padding: 0.95rem 1.125rem 0.85rem;
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

/* ============ Timeline ============ */
.timeline-flow {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
  min-width: 0;
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
  color: hsl(215 16% 50% / 0.85);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ============ Prose（与 ChatMessageBubble .ai-prose 同源） ============ */
.ai-prose {
  font-size: 0.9375rem;
  line-height: 1.75;
  color: hsl(215 28% 17%);
  /* 与 timeline-flow 一起构成 min-width:0 链，约束超长代码块/表格在容器内滚动 */
  min-width: 0;
  max-width: 100%;
  overflow-wrap: break-word;
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
  max-width: 100%;
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
  white-space: pre;
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
.ai-prose :deep(tr:last-child td) {
  border-bottom: none;
}
</style>
