<script setup lang="ts">
import type { Conversation } from '~/types/chat'
import {
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuPortal,
  ContextMenuRoot,
  ContextMenuTrigger,
} from 'reka-ui'
import { ScrollArea } from '~/components/ui/scroll-area'
import { useConfirmDialog } from '~/composables/useConfirmDialog'

const chatStore = useChatStore()
const { confirm } = useConfirmDialog()

const searchKeyword = ref('')

// 视图模式：active = 活跃会话列表；archived = 已归档列表。
const viewMode = ref<'active' | 'archived'>('active')

// 搜索态：关键词非空时走服务端搜索（标题 + 消息内容），否则展示默认 top 50。
const isSearchMode = computed(() => searchKeyword.value.trim().length > 0)
const displayConversations = computed(() => {
  if (viewMode.value === 'archived')
    return chatStore.archivedConversations
  return isSearchMode.value ? chatStore.conversationSearchResults : chatStore.conversations
})

// 进入页面时预取已归档数量，让底部入口显示角标 + 切换即时。
onMounted(() => {
  chatStore.fetchArchivedConversations()
})

function openArchived() {
  searchKeyword.value = ''
  viewMode.value = 'archived'
  chatStore.fetchArchivedConversations()
}

function backToActive() {
  viewMode.value = 'active'
}

// 关键词防抖：250ms 后请求服务端，避免逐字符打接口。
let searchTimer: ReturnType<typeof setTimeout> | null = null
watch(searchKeyword, (kw) => {
  if (searchTimer)
    clearTimeout(searchTimer)
  const q = kw.trim()
  if (!q) {
    chatStore.clearConversationSearch()
    return
  }
  // 立刻进入「搜索中」，消除防抖窗口内的空态闪烁。
  chatStore.conversationSearching = true
  searchTimer = setTimeout(() => chatStore.searchConversations(q), 250)
})
onBeforeUnmount(() => {
  if (searchTimer)
    clearTimeout(searchTimer)
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

  for (const conv of displayConversations.value) {
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
  // 重命名进行中时点击行不切换会话。
  if (renamingId.value === id)
    return
  chatStore.selectConversation(id)
}

// ── 右键 / ⋯ 菜单动作 ──────────────────────────────────────────────
type ConvAction = 'rename' | 'archive' | 'unarchive' | 'delete'
interface ActionDef { key: ConvAction, label: string, icon: string, danger?: boolean }
const ACTIVE_ACTIONS: ActionDef[] = [
  { key: 'rename', label: '重命名', icon: 'icon-[lucide--pencil-line]' },
  { key: 'archive', label: '归档', icon: 'icon-[lucide--archive]' },
  { key: 'delete', label: '删除', icon: 'icon-[lucide--trash-2]', danger: true },
]
const ARCHIVED_ACTIONS: ActionDef[] = [
  { key: 'rename', label: '重命名', icon: 'icon-[lucide--pencil-line]' },
  { key: 'unarchive', label: '取消归档', icon: 'icon-[lucide--archive-restore]' },
  { key: 'delete', label: '删除', icon: 'icon-[lucide--trash-2]', danger: true },
]
const convActions = computed(() =>
  viewMode.value === 'archived' ? ARCHIVED_ACTIONS : ACTIVE_ACTIONS,
)

// 菜单内容 / 菜单项的共享样式（dropdown 与 context menu 同款）。
const MENU_CONTENT_CLASS = 'z-50 min-w-36 overflow-hidden rounded-xl border border-gray-100 bg-popover p-1.5 text-popover-foreground shadow-[0_4px_24px_rgba(0,0,0,0.12)]'
const MENU_ITEM_CLASS = 'relative flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-[13px] text-foreground outline-none select-none data-[highlighted]:bg-accent'

function runAction(key: ConvAction, conv: Conversation) {
  if (key === 'rename')
    startRename(conv)
  else if (key === 'archive')
    handleArchive(conv)
  else if (key === 'unarchive')
    chatStore.archiveConversation(conv.id, false)
  else if (key === 'delete')
    handleDelete(conv)
}

// ── 重命名（行内编辑）──────────────────────────────────────────────
const renamingId = ref<string | null>(null)
const renameDraft = ref('')

async function startRename(conv: Conversation) {
  renamingId.value = conv.id
  renameDraft.value = conv.title
  await nextTick()
  const el = document.querySelector<HTMLInputElement>('.conv-rename-input')
  el?.focus()
  el?.select()
}

async function commitRename() {
  const id = renamingId.value
  if (!id)
    return
  const title = renameDraft.value.trim()
  renamingId.value = null
  if (title)
    await chatStore.renameConversation(id, title)
}

function cancelRename() {
  renamingId.value = null
}

// ── 归档 / 删除 ────────────────────────────────────────────────────
async function handleArchive(conv: Conversation) {
  await chatStore.archiveConversation(conv.id, true)
}

async function handleDelete(conv: Conversation) {
  const ok = await confirm({
    title: '删除对话',
    description: `确定删除「${conv.title || '未命名对话'}」吗？此操作不可恢复。`,
    confirmText: '删除',
    variant: 'destructive',
  })
  if (ok)
    await chatStore.removeConversation(conv.id)
}
</script>

<template>
  <div class="conv-panel flex flex-col h-full shrink-0">
    <!-- 顶部：标题 + 新建（archived 模式显示返回） -->
    <div class="flex items-center justify-between h-16 px-4 shrink-0">
      <template v-if="viewMode === 'archived'">
        <button class="conv-back-btn" title="返回对话列表" @click="backToActive">
          <span class="icon-[lucide--chevron-left] text-base" />
          <span class="text-sm font-semibold tracking-wide">已归档</span>
        </button>
      </template>
      <template v-else>
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
      </template>
    </div>

    <!-- 搜索（archived 模式隐藏） -->
    <div v-if="viewMode === 'active'" class="px-3 pb-2 shrink-0">
      <div class="conv-search">
        <span class="icon-[lucide--search] text-[13px] text-muted-foreground/70 shrink-0" />
        <input
          v-model="searchKeyword"
          type="text"
          placeholder="搜索对话或内容..."
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
        <!-- 已归档：加载中 -->
        <div
          v-if="viewMode === 'archived' && chatStore.archivedLoading && groupedConversations.length === 0"
          class="px-3 py-10 text-center"
        >
          <span class="icon-[lucide--loader-circle] animate-spin text-base text-muted-foreground/70" />
          <p class="mt-2 text-[13px] text-muted-foreground">
            加载中…
          </p>
        </div>

        <!-- 已归档：空 -->
        <div
          v-else-if="viewMode === 'archived' && groupedConversations.length === 0"
          class="px-3 py-10 text-center"
        >
          <div class="mx-auto mb-3 flex h-11 w-11 items-center justify-center rounded-xl bg-muted text-muted-foreground">
            <span class="icon-[lucide--archive] text-xl" />
          </div>
          <p class="text-[13px] text-muted-foreground">
            暂无已归档对话
          </p>
        </div>

        <!-- Loading（仅首次加载、无缓存数据时显示，避免已有列表被骨架屏顶替造成抖动） -->
        <div v-else-if="viewMode === 'active' && !isSearchMode && chatStore.loading && chatStore.conversations.length === 0" class="space-y-2 px-1 pt-1">
          <div v-for="i in 5" :key="i" class="conv-skeleton" />
        </div>

        <!-- 空状态（非搜索态、无任何对话） -->
        <div
          v-else-if="viewMode === 'active' && !isSearchMode && chatStore.conversations.length === 0"
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

        <!-- 搜索中 -->
        <div
          v-else-if="isSearchMode && chatStore.conversationSearching && groupedConversations.length === 0"
          class="px-3 py-10 text-center"
        >
          <span class="icon-[lucide--loader-circle] animate-spin text-base text-muted-foreground/70" />
          <p class="mt-2 text-[13px] text-muted-foreground">
            正在搜索…
          </p>
        </div>

        <!-- 搜索无结果 -->
        <div
          v-else-if="isSearchMode && groupedConversations.length === 0"
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
          <ContextMenuRoot
            v-for="conv in group.items"
            :key="conv.id"
          >
            <ContextMenuTrigger as-child>
              <div
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
                <!-- 行内重命名 -->
                <input
                  v-if="renamingId === conv.id"
                  v-model="renameDraft"
                  class="conv-rename-input flex-1 min-w-0"
                  maxlength="200"
                  @click.stop
                  @keydown.enter.prevent="commitRename"
                  @keydown.esc.prevent="cancelRename"
                  @blur="commitRename"
                >
                <p v-else class="chat-conversation-title flex-1 min-w-0">
                  {{ conv.title }}
                </p>
                <!-- 草稿态徽标：尚未成功发出首条消息的会话（如模型不支持图片导致首发失败后保留） -->
                <span
                  v-if="renamingId !== conv.id && conv.status === 'draft'"
                  class="conv-draft-badge"
                  title="草稿：尚未成功发送消息，可在会话内更换模型后重试"
                >草稿</span>

                <!-- SDD / 编码 / 方案 徽标（非重命名态显示） -->
                <ConversationBadges
                  v-if="renamingId !== conv.id"
                  :conversation="conv"
                />

                <!-- ⋯ 更多操作（hover 显示） -->
                <DropdownMenu v-if="renamingId !== conv.id">
                  <DropdownMenuTrigger as-child>
                    <button
                      class="chat-conversation-more"
                      aria-label="更多操作"
                      @click.stop
                    >
                      <span class="icon-[lucide--ellipsis] text-sm" />
                    </button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" :side-offset="4" class="min-w-36">
                    <DropdownMenuItem
                      v-for="action in convActions"
                      :key="action.key"
                      :class="action.danger ? 'text-red-600 focus:text-red-700' : ''"
                      @select="runAction(action.key, conv)"
                    >
                      <span :class="action.icon" />
                      {{ action.label }}
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            </ContextMenuTrigger>

            <!-- 右键菜单 -->
            <ContextMenuPortal>
              <ContextMenuContent :class="MENU_CONTENT_CLASS">
                <ContextMenuItem
                  v-for="action in convActions"
                  :key="action.key"
                  :class="[MENU_ITEM_CLASS, action.danger ? 'text-red-600 data-[highlighted]:text-red-700' : '']"
                  @select="runAction(action.key, conv)"
                >
                  <span :class="action.icon" />
                  {{ action.label }}
                </ContextMenuItem>
              </ContextMenuContent>
            </ContextMenuPortal>
          </ContextMenuRoot>
        </template>
      </div>
    </ScrollArea>

    <!-- 底部：查看已归档入口（仅活跃模式显示） -->
    <button
      v-if="viewMode === 'active'"
      class="conv-archived-entry shrink-0"
      @click="openArchived"
    >
      <span class="icon-[lucide--archive] text-[13px]" />
      <span class="flex-1 text-left">已归档</span>
      <span v-if="chatStore.archivedConversations.length" class="conv-archived-count">
        {{ chatStore.archivedConversations.length }}
      </span>
      <span class="icon-[lucide--chevron-right] text-[13px] opacity-50" />
    </button>
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

.conv-back-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  color: hsl(215 28% 17%);
  cursor: pointer;
  border-radius: 0.5rem;
  padding: 0.25rem 0.375rem 0.25rem 0.125rem;
  transition:
    background-color 0.15s ease,
    color 0.15s ease;
}

.conv-back-btn:hover {
  color: hsl(168 76% 30%);
}

/* 底部「已归档」入口 */
.conv-archived-entry {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  width: 100%;
  padding: 0.625rem 1rem;
  border-top: 1px solid hsl(214 32% 91% / 0.7);
  color: hsl(215 16% 47%);
  font-size: 0.8125rem;
  font-weight: 450;
  cursor: pointer;
  transition:
    background-color 0.15s ease,
    color 0.15s ease;
}

.conv-archived-entry:hover {
  color: hsl(215 28% 18%);
  background: hsl(214 32% 91% / 0.5);
}

.conv-archived-count {
  min-width: 1.125rem;
  height: 1.125rem;
  padding: 0 0.3125rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 9999px;
  background: hsl(214 32% 91%);
  color: hsl(215 16% 40%);
  font-size: 0.6875rem;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
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

.conv-draft-badge {
  flex-shrink: 0;
  border-radius: 0.25rem;
  border: 1px solid hsl(214 32% 88%);
  background: hsl(210 40% 96%);
  padding: 0 0.3125rem;
  font-size: 0.625rem;
  line-height: 1.6;
  color: hsl(215 16% 47%);
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

.chat-conversation-more {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 1.5rem;
  height: 1.5rem;
  border-radius: 0.5rem;
  color: hsl(215 16% 47% / 0.6);
  opacity: 0;
  flex-shrink: 0;
  cursor: pointer;
  transition:
    opacity 0.15s ease,
    background-color 0.15s ease,
    color 0.15s ease;
}

.chat-conversation-item:hover .chat-conversation-more,
.chat-conversation-more:focus-visible,
.chat-conversation-more[data-state='open'] {
  opacity: 1;
}

.chat-conversation-more:hover,
.chat-conversation-more[data-state='open'] {
  color: hsl(215 28% 22%);
  background: hsl(214 32% 91%);
}

/* 行内重命名输入框 */
.conv-rename-input {
  border: 1px solid hsl(168 76% 42% / 0.5);
  outline: none;
  border-radius: 0.375rem;
  padding: 0.0625rem 0.375rem;
  background: hsl(0 0% 100%);
  font-size: 0.8125rem;
  font-weight: 450;
  line-height: 1.25rem;
  color: hsl(215 28% 17%);
  box-shadow: 0 0 0 3px hsl(168 76% 42% / 0.1);
}

.chat-conversation-item:focus-visible,
.chat-conversation-more:focus-visible,
.conv-new-btn:focus-visible {
  outline: 2px solid hsl(168 76% 42% / 0.5);
  outline-offset: 1px;
}
</style>
