<script setup lang="ts">
import AppModeSwitcher from '~/components/layout/AppModeSwitcher.vue'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '~/components/ui/dropdown-menu'
import { ScrollArea } from '~/components/ui/scroll-area'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '~/components/ui/tooltip'
import { usePermission } from '~/composables/usePermission'
import { useAuthStore } from '~/stores/auth'

interface NavItem {
  to: string
  label: string
  icon: string
  exact?: boolean
}

const authStore = useAuthStore()
const chatStore = useChatStore()
const router = useRouter()
const route = useRoute()
const { isSystemAdmin } = usePermission()
const appVersion = __APP_VERSION__
const displayMode = computed(() => route.path === '/chat' ? 'chat' : 'friday')

// 收缩状态持久化到 localStorage
const isCollapsed = useLocalStorage('sidebar-collapsed', false)

function toggleCollapse() {
  isCollapsed.value = !isCollapsed.value
}

// ==================== 工作台导航 ====================
const mainNavItems: NavItem[] = [
  { to: '/', label: '首页', icon: 'lucide--home', exact: true },
  { to: '/spaces', label: '空间', icon: 'lucide--folder-git-2' },
  { to: '/repositories', label: '仓库', icon: 'lucide--git-branch' },
  { to: '/workflows', label: '工作流', icon: 'lucide--workflow' },
  { to: '/executions', label: '执行', icon: 'lucide--play-circle' },
  { to: '/analytics', label: '分析', icon: 'lucide--bar-chart-3' },
  { to: '/runners', label: 'Runner', icon: 'lucide--server' },
  { to: '/logs', label: '日志', icon: 'lucide--file-text' },
]

const adminNavItems: NavItem[] = [
  { to: '/admin', label: '系统设置', icon: 'lucide--settings', exact: true },
  { to: '/admin/users', label: '用户管理', icon: 'lucide--users' },
  { to: '/admin/oidc', label: 'OIDC 认证', icon: 'lucide--shield-check' },
  { to: '/admin/prompts', label: 'Prompt 管理', icon: 'lucide--file-text' },
  { to: '/codegraph/galaxy', label: 'Galaxy 图谱', icon: 'lucide--sparkles' },
  { to: '/codegraph/playground', label: 'Playground', icon: 'lucide--flask-conical' },
]

// ==================== Chat 对话 ====================
function handleNewConversation() {
  chatStore.createNewConversation()
}

function handleSelectConversation(id: string) {
  chatStore.selectConversation(id)
}

function handleDeleteConversation(id: string) {
  chatStore.removeConversation(id)
}

function formatTime(dateStr: string) {
  const date = new Date(dateStr)
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  const days = Math.floor(diff / (1000 * 60 * 60 * 24))
  if (days === 0)
    return '今天'
  if (days === 1)
    return '昨天'
  if (days < 7)
    return `${days}天前`
  return date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}

// ==================== 退出登录 ====================
async function handleLogout() {
  await authStore.logout()
  router.push('/login')
}
</script>

<template>
  <TooltipProvider :delay-duration="300">
    <aside
      class="sidebar-s2a sticky top-0 flex flex-col h-screen shrink-0 transition-all duration-300 ease-in-out"
      :class="isCollapsed ? 'w-[72px]' : 'w-64'"
    >
      <!-- ==================== 顶部：Logo + 收缩按钮 ==================== -->
      <div
        class="flex items-center h-16 border-b border-border/40"
        :class="isCollapsed ? 'justify-center px-2' : 'px-5 gap-3'"
      >
        <RouterLink
          to="/"
          class="group flex items-center gap-2.5 overflow-hidden"
        >
          <img
            src="/logo-mark.svg"
            alt="Friday"
            class="shrink-0 w-9 h-9 transition-transform duration-200 group-hover:scale-105"
          >
          <div v-if="!isCollapsed" class="flex flex-col gap-0.5">
            <img src="/logo-wordmark.svg" alt="friday" class="h-4 w-auto">
            <span class="text-[10px] text-muted-foreground leading-none">v{{ appVersion }}</span>
          </div>
        </RouterLink>

        <button
          v-if="!isCollapsed"
          class="ml-auto p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
          @click="toggleCollapse"
        >
          <span class="icon-[lucide--panel-left-close] text-lg" />
        </button>
      </div>

      <!-- ==================== 模式切换器 ==================== -->
      <div :class="isCollapsed ? 'px-2' : 'px-3'" class="pt-3 pb-2">
        <AppModeSwitcher :collapsed="isCollapsed" />
      </div>

      <!-- ==================== 中间内容区（模式相关） ==================== -->

      <!-- ===== 工作台模式：导航菜单 ===== -->
      <nav v-if="displayMode === 'friday'" class="flex-1 overflow-y-auto py-1 scrollbar-hide" :class="isCollapsed ? 'px-2' : 'px-3'">
        <template
          v-for="item in mainNavItems"
          :key="item.to"
        >
          <RouterLink v-slot="{ isActive, isExactActive, navigate, href }" :to="item.to" custom>
            <Tooltip v-if="isCollapsed">
              <TooltipTrigger as-child>
                <a
                  :href="href"
                  class="flex items-center justify-center h-10 rounded-xl transition-all duration-200 mb-0.5"
                  :class="(item.exact ? isExactActive : isActive) ? 'sidebar-s2a-link-active' : 'sidebar-s2a-link'"
                  @click="navigate"
                >
                  <span class="text-lg" :class="[`icon-[${item.icon}]`]" />
                </a>
              </TooltipTrigger>
              <TooltipContent side="right">
                {{ item.label }}
              </TooltipContent>
            </Tooltip>

            <a
              v-else
              :href="href"
              class="sidebar-s2a-link mb-0.5"
              :class="{ 'sidebar-s2a-link-active': item.exact ? isExactActive : isActive }"
              @click="navigate"
            >
              <span class="text-lg shrink-0" :class="[`icon-[${item.icon}]`]" />
              <span class="truncate">{{ item.label }}</span>
            </a>
          </RouterLink>
        </template>

        <!-- 管理区域（仅 admin 可见） -->
        <template v-if="isSystemAdmin">
          <div class="my-2 border-t border-border/40 mx-1" />
          <template
            v-for="item in adminNavItems"
            :key="item.to"
          >
            <RouterLink v-slot="{ isActive, isExactActive, navigate, href }" :to="item.to" custom>
              <Tooltip v-if="isCollapsed">
                <TooltipTrigger as-child>
                  <a
                    :href="href"
                    class="flex items-center justify-center h-10 rounded-xl transition-all duration-200 mb-0.5"
                    :class="(item.exact ? isExactActive : isActive) ? 'sidebar-s2a-link-active' : 'sidebar-s2a-link'"
                    @click="navigate"
                  >
                    <span class="text-lg" :class="[`icon-[${item.icon}]`]" />
                  </a>
                </TooltipTrigger>
                <TooltipContent side="right">
                  {{ item.label }}
                </TooltipContent>
              </Tooltip>

              <a
                v-else
                :href="href"
                class="sidebar-s2a-link mb-0.5"
                :class="{ 'sidebar-s2a-link-active': item.exact ? isExactActive : isActive }"
                @click="navigate"
              >
                <span class="text-lg shrink-0" :class="[`icon-[${item.icon}]`]" />
                <span class="truncate">{{ item.label }}</span>
              </a>
            </RouterLink>
          </template>
        </template>
      </nav>

      <!-- ===== Chat 模式：对话列表 ===== -->
      <template v-else>
        <!-- 新建对话按钮 -->
        <div :class="isCollapsed ? 'px-2' : 'px-3'" class="pb-2">
          <Tooltip v-if="isCollapsed">
            <TooltipTrigger as-child>
              <button
                class="sidebar-s2a-link w-full justify-center"
                @click="handleNewConversation"
              >
                <span class="icon-[lucide--plus] text-lg" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="right">
              新建对话
            </TooltipContent>
          </Tooltip>
          <button
            v-else
            class="chat-new-button"
            @click="handleNewConversation"
          >
            <span class="chat-new-button__icon icon-[lucide--plus] text-sm" />
            <span>新建对话</span>
          </button>
        </div>

        <!-- 对话列表 -->
        <ScrollArea class="flex-1" :class="isCollapsed ? 'px-2' : ''">
          <div v-if="!isCollapsed" class="chat-conversation-list px-2 pb-2">
            <div v-if="chatStore.loading" class="p-3 text-center text-sm text-muted-foreground">
              加载中...
            </div>
            <div
              v-else-if="chatStore.conversations.length === 0"
              class="card p-5 text-center"
            >
              <div class="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10">
                <span class="icon-[lucide--message-square-plus] text-2xl text-primary" />
              </div>
              <p class="text-sm font-medium text-foreground">
                暂无对话
              </p>
              <p class="mt-1 text-xs text-muted-foreground">
                点击上方按钮开始新对话
              </p>
            </div>
            <div
              v-for="conv in chatStore.conversations"
              :key="conv.id"
              role="button"
              tabindex="0"
              class="chat-conversation-item group"
              :class="{ 'chat-conversation-item--active': chatStore.currentConversationId === conv.id }"
              @click="handleSelectConversation(conv.id)"
              @keydown.enter="handleSelectConversation(conv.id)"
            >
              <span class="chat-conversation-icon">
                <span class="icon-[lucide--message-square] text-[15px]" />
              </span>
              <div class="flex-1 min-w-0">
                <p class="chat-conversation-title">
                  {{ conv.title }}
                </p>
                <p class="chat-conversation-meta">
                  <span>{{ formatTime(conv.updated_at) }}</span>
                  <span v-if="conv.status === 'running'" class="chat-conversation-state chat-conversation-state--running">运行中</span>
                  <span v-else-if="conv.status === 'completed'" class="chat-conversation-state chat-conversation-state--done">已完成</span>
                  <span v-else class="chat-conversation-state">草稿</span>
                </p>
              </div>
              <button
                class="chat-conversation-delete"
                aria-label="删除对话"
                @click.stop="handleDeleteConversation(conv.id)"
              >
                <span class="icon-[lucide--trash-2] text-xs" />
              </button>
            </div>
          </div>
        </ScrollArea>
      </template>

      <!-- ==================== 底部：收缩按钮 ==================== -->
      <div v-if="isCollapsed" class="px-2 pb-1">
        <Tooltip>
          <TooltipTrigger as-child>
            <button
              class="sidebar-s2a-link w-full justify-center mb-0.5"
              @click="toggleCollapse"
            >
              <span class="icon-[lucide--panel-left-open] text-lg" />
            </button>
          </TooltipTrigger>
          <TooltipContent side="right">
            展开侧边栏
          </TooltipContent>
        </Tooltip>
      </div>

      <!-- 分隔线 -->
      <div class="mx-3 border-t border-border/40" />

      <!-- ==================== 底部：用户菜单 ==================== -->
      <div :class="isCollapsed ? 'px-2' : 'px-3'" class="py-2">
        <DropdownMenu>
          <DropdownMenuTrigger as-child>
            <button
              class="sidebar-s2a-link w-full"
              :class="isCollapsed ? 'justify-center' : ''"
            >
              <div class="relative shrink-0">
                <img
                  v-if="authStore.gravatarUrl"
                  :src="authStore.gravatarUrl"
                  :alt="authStore.displayName"
                  class="w-8 h-8 rounded-xl ring-1 ring-border/50 object-cover"
                >
                <div
                  v-else
                  class="w-8 h-8 rounded-xl flex items-center justify-center text-sm font-medium text-white gradient-primary"
                >
                  {{ (authStore.displayName || '用')[0].toUpperCase() }}
                </div>
              </div>
              <template v-if="!isCollapsed">
                <span class="truncate flex-1 text-left">{{ authStore.displayName || '用户' }}</span>
                <span class="icon-[lucide--chevrons-up-down] text-xs shrink-0" />
              </template>
            </button>
          </DropdownMenuTrigger>

          <DropdownMenuContent
            :side="isCollapsed ? 'right' : 'top'"
            :align="isCollapsed ? 'start' : 'start'"
            class="w-56"
          >
            <div class="px-3 py-3 flex items-center gap-3">
              <div class="shrink-0">
                <img
                  v-if="authStore.gravatarUrl"
                  :src="authStore.gravatarUrl"
                  :alt="authStore.displayName"
                  class="w-10 h-10 rounded-xl object-cover"
                >
                <div
                  v-else
                  class="w-10 h-10 rounded-xl flex items-center justify-center text-sm font-semibold text-white gradient-primary"
                >
                  {{ (authStore.displayName || '用')[0].toUpperCase() }}
                </div>
              </div>
              <div class="min-w-0">
                <p class="text-sm font-semibold text-foreground truncate">
                  {{ authStore.displayName || '用户' }}
                </p>
                <p class="text-xs text-muted-foreground truncate">
                  {{ authStore.user?.username }}
                </p>
              </div>
            </div>
            <DropdownMenuSeparator />
            <DropdownMenuItem class="cursor-pointer" @click="router.push('/profile')">
              <span class="icon-[lucide--user] mr-2 text-muted-foreground" />
              个人资料
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              class="cursor-pointer text-destructive focus:text-destructive focus:bg-destructive/5"
              @click="handleLogout"
            >
              <span class="icon-[lucide--log-out] mr-2" />
              退出登录
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </aside>
  </TooltipProvider>
</template>

<style scoped>
.chat-new-button {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  width: 100%;
  min-height: 2.75rem;
  border-radius: 1rem;
  border: 1px solid hsl(168 76% 42% / 0.28);
  background: linear-gradient(135deg, hsl(168 72% 48%), hsl(174 68% 36%)), hsl(168 76% 42%);
  color: white;
  font-size: 0.9375rem;
  font-weight: 700;
  letter-spacing: 0.01em;
  cursor: pointer;
  box-shadow:
    0 8px 18px hsl(168 76% 42% / 0.16),
    inset 0 1px 0 hsl(0 0% 100% / 0.22);
  transition:
    transform 0.18s ease,
    box-shadow 0.18s ease,
    filter 0.18s ease;
}

.chat-new-button:hover {
  transform: translateY(-1px);
  filter: saturate(1.08);
  box-shadow:
    0 10px 22px hsl(168 76% 42% / 0.2),
    inset 0 1px 0 hsl(0 0% 100% / 0.25);
}

.chat-new-button:focus-visible,
.chat-conversation-item:focus-visible,
.chat-conversation-delete:focus-visible {
  outline: 2px solid hsl(168 76% 42% / 0.5);
  outline-offset: 2px;
}

.chat-new-button__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.25rem;
  height: 1.25rem;
  border-radius: 9999px;
  background: hsl(0 0% 100% / 0.16);
}

.chat-conversation-list {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.chat-conversation-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  width: 100%;
  min-height: 3.5rem;
  padding: 0.5rem 0.625rem;
  border: 1px solid transparent;
  border-radius: 0.875rem;
  color: hsl(215 20% 43%);
  cursor: pointer;
  transition:
    background-color 0.18s ease,
    border-color 0.18s ease,
    box-shadow 0.18s ease,
    transform 0.18s ease,
    color 0.18s ease;
}

.chat-conversation-item:hover {
  border-color: hsl(214 32% 88% / 0.8);
  background: hsl(0 0% 100% / 0.58);
  color: hsl(215 28% 22%);
  box-shadow: 0 1px 2px hsl(215 28% 17% / 0.05);
}

.chat-conversation-item--active {
  border-color: hsl(168 76% 42% / 0.18);
  background: hsl(168 76% 42% / 0.08);
  color: hsl(168 64% 28%);
  box-shadow: none;
}

.chat-conversation-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 2.125rem;
  height: 2.125rem;
  border-radius: 0.75rem;
  background: hsl(210 40% 96% / 0.72);
  color: hsl(215 16% 47%);
  flex-shrink: 0;
  box-shadow: inset 0 0 0 1px hsl(214 32% 91% / 0.75);
}

.chat-conversation-item--active .chat-conversation-icon {
  background: hsl(168 76% 42% / 0.12);
  color: hsl(168 76% 34%);
  box-shadow: inset 0 0 0 1px hsl(168 76% 42% / 0.2);
}

.chat-conversation-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.875rem;
  font-weight: 650;
  line-height: 1.25rem;
  letter-spacing: -0.01em;
}

.chat-conversation-meta {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-width: 0;
  margin-top: 0.125rem;
  font-size: 0.6875rem;
  font-weight: 600;
  color: hsl(215 16% 52% / 0.72);
}

.chat-conversation-state {
  color: hsl(215 16% 52% / 0.74);
  white-space: nowrap;
}

.chat-conversation-state--running {
  color: hsl(38 82% 34%);
}

.chat-conversation-state--done {
  color: hsl(142 66% 30%);
}

.chat-conversation-delete {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 1.75rem;
  height: 1.75rem;
  border-radius: 0.625rem;
  color: hsl(215 16% 47% / 0.45);
  opacity: 0;
  flex-shrink: 0;
  cursor: pointer;
  transition:
    opacity 0.18s ease,
    background-color 0.18s ease,
    color 0.18s ease;
}

.chat-conversation-item:hover .chat-conversation-delete,
.chat-conversation-delete:focus-visible {
  opacity: 1;
}

.chat-conversation-delete:hover {
  color: hsl(0 72% 51%);
  background: hsl(0 72% 51% / 0.08);
}
</style>
