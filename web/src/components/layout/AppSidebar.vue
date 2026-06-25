<script setup lang="ts">
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '~/components/ui/dropdown-menu'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '~/components/ui/tooltip'
import { usePermission } from '~/composables/usePermission'
import { useAuthStore } from '~/stores/auth'
import { useNotificationsStore } from '~/stores/notifications'

interface NavItem {
  to: string
  label: string
  icon: string
  exact?: boolean
  /** 该入口展示的未读角标数（如消息中心），0 不展示 */
  badge?: () => number
}

const authStore = useAuthStore()
const router = useRouter()
const { isSystemAdmin } = usePermission()
const notificationsStore = useNotificationsStore()
const appVersion = __APP_VERSION__

/** 侧边栏入口未读角标（消息中心）。 */
function navBadge(item: NavItem): number {
  return item.badge ? item.badge() : 0
}
function badgeText(count: number): string {
  return count > 99 ? '99+' : String(count)
}

// ==================== 版本号悬停展示当前版本 changelog ====================
// 数据来源：GitHub Release（git-cliff 生成的 release notes），首次悬停时懒加载并缓存
const changelogState = ref<'idle' | 'loading' | 'loaded' | 'error'>('idle')
const changelogHtml = ref('')

// dev 启动时版本号是 git describe 形态（如 0.2.1-12-gabc1234-dirty），
// 剥掉后缀回退到最近的正式 tag 去取对应 release 的日志
const releaseTag = computed(() => `v${appVersion.replace(/(-\d+-g[0-9a-f]+)?(-dirty)?$/, '')}`)

// 侧边栏空间有限：dev 形态只展示「基线版本-dev」，完整版本放进悬浮层
const isDevVersion = computed(() => `v${appVersion}` !== releaseTag.value)
const displayVersion = computed(() => isDevVersion.value ? `${releaseTag.value}-dev` : `v${appVersion}`)

async function loadChangelog(open: boolean) {
  if (!open || changelogState.value === 'loading' || changelogState.value === 'loaded')
    return
  changelogState.value = 'loading'
  try {
    const resp = await fetch(
      `https://api.github.com/repos/friday-ai-codes/friday-ai/releases/tags/${releaseTag.value}`,
    )
    if (!resp.ok)
      throw new Error(`HTTP ${resp.status}`)
    const data = await resp.json()
    if (!data.body)
      throw new Error('empty release notes')
    const md = await getMarkdownRenderer()
    changelogHtml.value = md.render(data.body)
    changelogState.value = 'loaded'
  }
  catch {
    changelogState.value = 'error'
  }
}

// 收缩状态持久化到 localStorage
const isCollapsed = useLocalStorage('sidebar-collapsed', false)

function toggleCollapse() {
  isCollapsed.value = !isCollapsed.value
}

// ==================== 导航 ====================
// AI 对话作为一级导航入口（会话列表在 /chat 页面内部展示，
// 不再劫持全局侧边栏 — 入口信息架构重构）
const chatNavItem: NavItem = { to: '/chat', label: 'AI 对话', icon: 'lucide--message-circle' }

const mainNavItems: NavItem[] = [
  { to: '/', label: '首页', icon: 'lucide--home', exact: true },
  { to: '/spaces', label: '空间', icon: 'lucide--folder-git-2' },
  { to: '/repositories', label: '仓库', icon: 'lucide--git-branch' },
  { to: '/knowledge', label: '知识', icon: 'lucide--book-open' },
  { to: '/workflows', label: '工作流', icon: 'lucide--workflow' },
  { to: '/executions', label: '执行', icon: 'lucide--play-circle' },
  { to: '/analytics', label: '分析', icon: 'lucide--bar-chart-3' },
  { to: '/logs', label: '日志', icon: 'lucide--file-text' },
  { to: '/specs', label: 'SDD', icon: 'lucide--scroll-text' },
  { to: '/notifications', label: '消息中心', icon: 'lucide--inbox', badge: () => notificationsStore.totalUnread },
]

const adminNavItems: NavItem[] = [
  { to: '/admin', label: '系统设置', icon: 'lucide--settings', exact: true },
  { to: '/tasks', label: '任务中心', icon: 'lucide--list-checks' },
  { to: '/admin/observability', label: '运维监控', icon: 'lucide--activity' },
  { to: '/runners', label: 'Runner', icon: 'lucide--server' },
  { to: '/admin/users', label: '用户管理', icon: 'lucide--users' },
  { to: '/admin/conversations', label: '会话管理', icon: 'lucide--messages-square' },
  { to: '/admin/prompts', label: 'Prompt 管理', icon: 'lucide--file-text' },
  { to: '/admin/audit', label: '操作审计', icon: 'lucide--shield-check' },
  { to: '/admin/feedback', label: '反馈管理', icon: 'lucide--message-square-warning' },
  { to: '/admin/announcements', label: '系统公告', icon: 'lucide--megaphone' },
  { to: '/codegraph/galaxy', label: 'Galaxy 图谱', icon: 'lucide--sparkles' },
  { to: '/codegraph/playground', label: 'Playground', icon: 'lucide--flask-conical' },
]

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
            <Tooltip @update:open="loadChangelog">
              <TooltipTrigger as-child>
                <span class="text-[10px] text-muted-foreground leading-none cursor-default w-fit whitespace-nowrap">{{ displayVersion }}</span>
              </TooltipTrigger>
              <TooltipContent
                side="right"
                :side-offset="12"
                class="max-w-xs max-h-80 overflow-y-auto bg-popover text-popover-foreground border border-border shadow-lg p-3 font-normal"
              >
                <div class="text-xs font-semibold mb-1.5">
                  {{ releaseTag }} 更新日志
                </div>
                <div v-if="isDevVersion" class="text-[10px] text-muted-foreground mb-1.5 break-all">
                  当前构建：v{{ appVersion }}
                </div>
                <div v-if="changelogState === 'loading' || changelogState === 'idle'" class="text-xs text-muted-foreground">
                  加载中…
                </div>
                <div v-else-if="changelogState === 'error'" class="text-xs text-muted-foreground">
                  暂无该版本的更新日志
                </div>
                <!-- eslint-disable-next-line vue/no-v-html — markdown-it 以 html:false 渲染，无 XSS 风险 -->
                <div v-else class="changelog-content text-xs" v-html="changelogHtml" />
              </TooltipContent>
            </Tooltip>
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

      <!-- ==================== 导航菜单 ==================== -->
      <nav class="flex-1 overflow-y-auto py-3 scrollbar-hide" :class="isCollapsed ? 'px-2' : 'px-3'">
        <!-- AI 对话入口（一级导航，置顶突出） -->
        <RouterLink v-slot="{ isActive, navigate, href }" :to="chatNavItem.to" custom>
          <Tooltip v-if="isCollapsed">
            <TooltipTrigger as-child>
              <a
                :href="href"
                class="flex items-center justify-center h-10 rounded-xl transition-all duration-200 mb-0.5"
                :class="isActive ? 'sidebar-s2a-link-active' : 'sidebar-s2a-link'"
                @click="navigate"
              >
                <span class="text-lg" :class="[`icon-[${chatNavItem.icon}]`]" />
              </a>
            </TooltipTrigger>
            <TooltipContent side="right">
              {{ chatNavItem.label }}
            </TooltipContent>
          </Tooltip>

          <a
            v-else
            :href="href"
            class="sidebar-s2a-link mb-0.5"
            :class="{ 'sidebar-s2a-link-active': isActive }"
            @click="navigate"
          >
            <span class="text-lg shrink-0" :class="[`icon-[${chatNavItem.icon}]`]" />
            <span class="truncate">{{ chatNavItem.label }}</span>
          </a>
        </RouterLink>

        <div class="my-2 border-t border-border/40 mx-1" />

        <template
          v-for="item in mainNavItems"
          :key="item.to"
        >
          <RouterLink v-slot="{ isActive, isExactActive, navigate, href }" :to="item.to" custom>
            <Tooltip v-if="isCollapsed">
              <TooltipTrigger as-child>
                <a
                  :href="href"
                  class="relative flex items-center justify-center h-10 rounded-xl transition-all duration-200 mb-0.5"
                  :class="(item.exact ? isExactActive : isActive) ? 'sidebar-s2a-link-active' : 'sidebar-s2a-link'"
                  @click="navigate"
                >
                  <span class="text-lg" :class="[`icon-[${item.icon}]`]" />
                  <span
                    v-if="navBadge(item) > 0"
                    class="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-red-500 ring-2 ring-background"
                    aria-hidden="true"
                  />
                </a>
              </TooltipTrigger>
              <TooltipContent side="right">
                {{ item.label }}{{ navBadge(item) > 0 ? ` · ${badgeText(navBadge(item))}` : '' }}
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
              <span
                v-if="navBadge(item) > 0"
                class="ml-auto inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-red-500 px-1.5 text-[11px] font-semibold leading-none text-white tabular-nums"
                :aria-label="`${navBadge(item)} 条未读`"
              >
                {{ badgeText(navBadge(item)) }}
              </span>
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
/* ==================== 版本 changelog 悬浮内容（v-html 渲染，需 :deep） ==================== */
.changelog-content :deep(h1),
.changelog-content :deep(h2),
.changelog-content :deep(h3) {
  font-size: 0.75rem;
  font-weight: 600;
  margin: 0.5rem 0 0.25rem;
}

.changelog-content :deep(ul) {
  list-style: disc;
  padding-left: 1rem;
  margin: 0.25rem 0;
}

.changelog-content :deep(li) {
  margin: 0.125rem 0;
}

.changelog-content :deep(p) {
  margin: 0.25rem 0;
}

.changelog-content :deep(a) {
  color: hsl(var(--primary, 222 89% 55%));
  text-decoration: underline;
}

.changelog-content :deep(code) {
  font-size: 0.6875rem;
  padding: 0 0.25rem;
  border-radius: 0.25rem;
  background: hsl(215 16% 47% / 0.12);
}
</style>
