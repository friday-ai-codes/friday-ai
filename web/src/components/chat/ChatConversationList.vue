<script setup lang="ts">
import type { Conversation } from '~/types/chat'
import { ScrollArea } from '~/components/ui/scroll-area'

const chatStore = useChatStore()

const searchKeyword = ref('')

const filteredConversations = computed(() => {
  const kw = searchKeyword.value.trim().toLowerCase()
  if (!kw)
    return chatStore.conversations
  return chatStore.conversations.filter(c => c.title.toLowerCase().includes(kw))
})

interface ConversationGroup {
  label: string
  items: Conversation[]
}

/** ChatGPT 风格时间分组：今天 / 昨天 / 近 7 天 / 更早 */
const groupedConversations = computed<ConversationGroup[]>(() => {
  const groups: ConversationGroup[] = [
    { label: '今天', items: [] },
    { label: '昨天', items: [] },
    { label: '近 7 天', items: [] },
    { label: '更早', items: [] },
  ]
  const startOfToday = new Date()
  startOfToday.setHours(0, 0, 0, 0)
  const dayMs = 24 * 60 * 60 * 1000

  for (const conv of filteredConversations.value) {
    const t = new Date(conv.updated_at).getTime()
    if (t >= startOfToday.getTime())
      groups[0].items.push(conv)
    else if (t >= startOfToday.getTime() - dayMs)
      groups[1].items.push(conv)
    else if (t >= startOfToday.getTime() - 6 * dayMs)
      groups[2].items.push(conv)
    else
      groups[3].items.push(conv)
  }
  return groups.filter(g => g.items.length > 0)
})

function handleNewConversation() {
  chatStore.createNewConversation()
}

function handleSelectConversation(id: string) {
  chatStore.selectConversation(id)
}

function handleDeleteConversation(id: string) {
  chatStore.removeConversation(id)
}
</script>

<template>
  <div class="conv-panel flex flex-col h-full shrink-0">
    <!-- 顶部：标题 + 新建 -->
    <div class="flex items-center justify-between h-16 px-4 shrink-0">
      <h2 class="text-sm font-semibold text-foreground tracking-wide">
        对话
      </h2>
      <button
        class="conv-new-btn"
        title="新建对话"
        @click="handleNewConversation"
      >
        <span class="icon-[lucide--square-pen] text-[15px]" />
      </button>
    </div>

    <!-- 搜索 -->
    <div class="px-3 pb-2 shrink-0">
      <div class="conv-search">
        <span class="icon-[lucide--search] text-[13px] text-muted-foreground/70 shrink-0" />
        <input
          v-model="searchKeyword"
          type="text"
          placeholder="搜索对话..."
          class="conv-search-input"
        >
        <button
          v-if="searchKeyword"
          class="conv-search-clear"
          aria-label="清空搜索"
          @click="searchKeyword = ''"
        >
          <span class="icon-[lucide--x] text-[12px]" />
        </button>
      </div>
    </div>

    <!-- 列表 -->
    <ScrollArea class="flex-1 min-h-0">
      <div class="px-2 pb-3">
        <!-- Loading（仅首次加载、无缓存数据时显示，避免已有列表被骨架屏顶替造成抖动） -->
        <div v-if="chatStore.loading && chatStore.conversations.length === 0" class="space-y-2 px-1 pt-1">
          <div v-for="i in 5" :key="i" class="conv-skeleton" />
        </div>

        <!-- 空状态 -->
        <div
          v-else-if="chatStore.conversations.length === 0"
          class="px-3 py-10 text-center"
        >
          <div class="mx-auto mb-3 flex h-11 w-11 items-center justify-center rounded-xl bg-primary/8 text-primary">
            <span class="icon-[lucide--message-square-plus] text-xl" />
          </div>
          <p class="text-[13px] font-medium text-foreground">
            还没有对话
          </p>
          <p class="mt-1 text-xs text-muted-foreground leading-relaxed">
            在右侧输入框发出第一条消息，<br>对话会自动出现在这里
          </p>
        </div>

        <!-- 搜索无结果 -->
        <div
          v-else-if="groupedConversations.length === 0"
          class="px-3 py-10 text-center"
        >
          <p class="text-[13px] text-muted-foreground">
            没有匹配「{{ searchKeyword }}」的对话
          </p>
        </div>

        <!-- 分组列表 -->
        <template v-for="group in groupedConversations" :key="group.label">
          <p class="conv-group-label">
            {{ group.label }}
          </p>
          <div
            v-for="conv in group.items"
            :key="conv.id"
            role="button"
            tabindex="0"
            class="chat-conversation-item group"
            :class="{ 'chat-conversation-item--active': chatStore.currentConversationId === conv.id }"
            @click="handleSelectConversation(conv.id)"
            @keydown.enter="handleSelectConversation(conv.id)"
          >
            <span
              v-if="conv.status === 'running'"
              class="conv-status-dot conv-status-dot--running"
              title="运行中"
            />
            <p class="chat-conversation-title flex-1 min-w-0">
              {{ conv.title }}
            </p>
            <button
              class="chat-conversation-delete"
              aria-label="删除对话"
              @click.stop="handleDeleteConversation(conv.id)"
            >
              <span class="icon-[lucide--trash-2] text-xs" />
            </button>
          </div>
        </template>
      </div>
    </ScrollArea>
  </div>
</template>

<style scoped>
.conv-panel {
  width: 16rem;
  border-right: 1px solid hsl(214 32% 91% / 0.7);
  background: hsl(210 40% 98%);
}

.conv-new-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 2rem;
  height: 2rem;
  border-radius: 0.625rem;
  color: hsl(215 16% 47%);
  cursor: pointer;
  transition:
    background-color 0.15s ease,
    color 0.15s ease;
}

.conv-new-btn:hover {
  background: hsl(168 76% 42% / 0.1);
  color: hsl(168 76% 36%);
}

.conv-search {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  height: 2.125rem;
  padding: 0 0.625rem;
  border-radius: 0.625rem;
  border: 1px solid hsl(214 32% 91% / 0.9);
  background: hsl(0 0% 100% / 0.7);
  transition:
    border-color 0.15s ease,
    box-shadow 0.15s ease;
}

.conv-search:focus-within {
  border-color: hsl(168 76% 42% / 0.45);
  box-shadow: 0 0 0 3px hsl(168 76% 42% / 0.07);
}

.conv-search-input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: transparent;
  font-size: 0.8125rem;
  color: hsl(215 28% 17%);
}

.conv-search-input::placeholder {
  color: hsl(215 16% 60%);
}

.conv-search-clear {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 1.125rem;
  height: 1.125rem;
  border-radius: 9999px;
  color: hsl(215 16% 55%);
  cursor: pointer;
}

.conv-search-clear:hover {
  background: hsl(214 32% 91%);
  color: hsl(215 28% 22%);
}

.conv-group-label {
  padding: 0.875rem 0.625rem 0.375rem;
  font-size: 0.6875rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: hsl(215 16% 55%);
  user-select: none;
}

.conv-skeleton {
  height: 2.25rem;
  border-radius: 0.625rem;
  background: linear-gradient(90deg, hsl(214 32% 93%) 25%, hsl(214 32% 96%) 50%, hsl(214 32% 93%) 75%);
  background-size: 200% 100%;
  animation: conv-shimmer 1.4s ease infinite;
}

@keyframes conv-shimmer {
  0% {
    background-position: 200% 0;
  }
  100% {
    background-position: -200% 0;
  }
}

.chat-conversation-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  width: 100%;
  min-height: 2.25rem;
  padding: 0.4375rem 0.625rem;
  border-radius: 0.625rem;
  color: hsl(215 20% 38%);
  cursor: pointer;
  transition:
    background-color 0.15s ease,
    color 0.15s ease;
}

.chat-conversation-item:hover {
  background: hsl(214 32% 91% / 0.55);
  color: hsl(215 28% 18%);
}

.chat-conversation-item--active {
  background: hsl(168 76% 42% / 0.1);
  color: hsl(168 64% 24%);
}

.chat-conversation-item--active .chat-conversation-title {
  font-weight: 600;
}

.chat-conversation-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.8125rem;
  font-weight: 450;
  line-height: 1.25rem;
}

.conv-status-dot {
  width: 0.4375rem;
  height: 0.4375rem;
  border-radius: 9999px;
  flex-shrink: 0;
}

.conv-status-dot--running {
  background: hsl(38 92% 50%);
  box-shadow: 0 0 0 3px hsl(38 92% 50% / 0.15);
  animation: conv-pulse 1.6s ease infinite;
}

@keyframes conv-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.45;
  }
}

.chat-conversation-delete {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 1.5rem;
  height: 1.5rem;
  border-radius: 0.5rem;
  color: hsl(215 16% 47% / 0.5);
  opacity: 0;
  flex-shrink: 0;
  cursor: pointer;
  transition:
    opacity 0.15s ease,
    background-color 0.15s ease,
    color 0.15s ease;
}

.chat-conversation-item:hover .chat-conversation-delete,
.chat-conversation-delete:focus-visible {
  opacity: 1;
}

.chat-conversation-delete:hover {
  color: hsl(0 72% 51%);
  background: hsl(0 72% 51% / 0.08);
}

.chat-conversation-item:focus-visible,
.chat-conversation-delete:focus-visible,
.conv-new-btn:focus-visible {
  outline: 2px solid hsl(168 76% 42% / 0.5);
  outline-offset: 1px;
}
</style>
