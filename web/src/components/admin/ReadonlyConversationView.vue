<script setup lang="ts">
/**
 * 轻量只读会话查看器（ADMVW-02）。
 *
 * 与普通 chat 渲染同源：用 `hydrateLegacyMessage` 把 legacy/parts 消息归一为有序
 * parts，再用 `getMarkdownRenderer` 渲染 text/thinking parts 的 markdown。
 *
 * **纯只读纪律**：组件内无任何写入入口——无 `<input>`/`<textarea>`、无发送/编辑/
 * 删除/导出按钮，且**不 import chatStore**（与 ChatMessageBubble 深耦合解耦）。
 * 不做流式、不做选择、不做工具调用交互，仅静态回放历史消息内容。
 */
import type { ConversationMessage, MessagePart } from '~/types/chat'
import { computed, ref, watch } from 'vue'
import { getMarkdownRenderer } from '~/composables/useMarkdownRenderer'
import { hydrateLegacyMessage } from '~/composables/useMessageParts'

const props = defineProps<{
  messages: ConversationMessage[]
}>()

interface HydratedMessage {
  id: string
  role: ConversationMessage['role']
  parts: MessagePart[]
}

const hydrated = computed<HydratedMessage[]>(() =>
  (props.messages ?? []).map(msg => ({
    id: msg.id,
    role: msg.role,
    parts: hydrateLegacyMessage(msg),
  })),
)

// partId → 渲染后的 markdown HTML（异步单例渲染器，渲染完成后填充）
const renderedHtml = ref<Record<string, string>>({})

watch(
  hydrated,
  async (list) => {
    const md = await getMarkdownRenderer()
    const next: Record<string, string> = {}
    for (const msg of list) {
      for (const part of msg.parts) {
        if (part.type === 'text' || part.type === 'thinking')
          next[part.id] = md.render(part.text ?? '')
      }
    }
    renderedHtml.value = next
  },
  { immediate: true },
)

function roleLabel(role: ConversationMessage['role']): string {
  switch (role) {
    case 'user':
      return '用户'
    case 'assistant':
      return '助手'
    case 'system':
      return '系统'
    case 'tool':
      return '工具'
    default:
      return role
  }
}
</script>

<template>
  <div class="readonly-conversation flex flex-col gap-4">
    <p
      v-if="hydrated.length === 0"
      class="py-12 text-center text-sm text-muted-foreground"
    >
      该会话暂无消息
    </p>

    <div
      v-for="msg in hydrated"
      :key="msg.id"
      class="flex flex-col gap-1.5"
      :class="msg.role === 'user' ? 'items-end' : 'items-start'"
    >
      <span class="px-1 text-xs font-medium text-muted-foreground">
        {{ roleLabel(msg.role) }}
      </span>
      <div
        class="max-w-[85%] rounded-2xl px-4 py-3 text-sm"
        :class="msg.role === 'user'
          ? 'bg-primary/10 text-foreground'
          : 'bg-muted/50 text-foreground border border-border/40'"
      >
        <template v-for="part in msg.parts" :key="part.id">
          <!-- text / thinking：markdown 渲染 -->
          <div
            v-if="part.type === 'text'"
            class="markdown-body break-words"
            v-html="renderedHtml[part.id] ?? ''"
          />
          <div
            v-else-if="part.type === 'thinking'"
            class="markdown-body break-words text-muted-foreground italic border-l-2 border-border/60 pl-3 my-1"
            v-html="renderedHtml[part.id] ?? ''"
          />
          <!-- tool_use：只读 chip，仅展示工具名（不可交互） -->
          <div
            v-else-if="part.type === 'tool_use'"
            class="my-1 inline-flex items-center gap-1.5 rounded-lg border border-border/50 bg-background/60 px-2 py-1 text-xs text-muted-foreground"
          >
            <span class="icon-[lucide--wrench] text-[0.85rem]" />
            <span class="font-mono">{{ part.name }}</span>
          </div>
          <!-- image：占位说明（只读不下载） -->
          <div
            v-else-if="part.type === 'image'"
            class="my-1 inline-flex items-center gap-1.5 rounded-lg border border-border/50 bg-background/60 px-2 py-1 text-xs text-muted-foreground"
          >
            <span class="icon-[lucide--image] text-[0.85rem]" />
            <span>{{ part.alt_text || '图片' }}</span>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>
