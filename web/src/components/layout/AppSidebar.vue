<script setup lang="ts">
import AppModeSwitcher from '~/components/layout/AppModeSwitcher.vue'
import { Button } from '~/components/ui/button'
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
import { useAppMode } from '~/composables/useAppMode'
import { usePermission } from '~/composables/usePermission'
import { useAuthStore } from '~/stores/auth'
interface NavItem {
 to: string
 label: string
 icon: string
 exact?: boolean
}
const authStore = useAuthStore
const chatStore = useChatStore
const router = useRouter
const { isSystemAdmin } = usePermission
const { mode } = useAppMode
const appVersion = __APP_VERSION__
// 收缩状态持久化到 localStorage
const isCollapsed = useLocalStorage('sidebar-collapsed', false)
function toggleCollapse {
 isCollapsed.value = !isCollapsed.value
}
// ==================== 工作台导航 ====================
const mainNavItems: NavItem = [
 { to: '/', label: '首页', icon: 'lucide--home', exact: true },
 { to: '/projects', label: '项目', icon: 'lucide--folder-git-2' },
 { to: '/repositories', label: '仓库', icon: 'lucide--git-branch' },
 { to: '/workflows', label: '工作流', icon: 'lucide--workflow' },
 { to: '/executions', label: '执行', icon: 'lucide--play-circle' },
 { to: '/analytics', label: '分析', icon: 'lucide--bar-chart-3' },
 { to: '/runners', label: 'Runner', icon: 'lucide--server' },
 { to: '/logs', label: '日志', icon: 'lucide--file-text' },
]
const adminNavItems: NavItem = [
 { to: '/admin', label: '系统设置', icon: 'lucide--settings', exact: true },
 { to: '/admin/users', label: '用户管理', icon: 'lucide--users' },
 { to: '/admin/oidc', label: 'OIDC 认证', icon: 'lucide--shield-check' },
]
// ==================== Chat 对话 ====================
function handleNewConversation {
 chatStore.createNewConversation
}
function handleSelectConversation(id: string) {
 chatStore.selectConversation(id)
}
function handleDeleteConversation(id: string) {
 chatStore.removeConversation(id)
}
function formatTime(dateStr: string) {
 const date = new Date(dateStr)
 const now = new Date
 const diff = now.getTime - date.getTime
 const days = Math.floor(diff / (1000 * 60 * 60 * 24))
 if (days === 0) return '今天'
 if (days === 1) return '昨天'
 if (days < 7) return `${days}天前`
 return date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}
// ==================== 退出登录 ====================
async function handleLogout {
 await authStore.logout
 router.push('/login')
}
</script>
<template>
 <TooltipProvider:delay-duration="300">
 <aside
 class="sidebar-s2a sticky top-0 flex flex-col h-screen shrink-0 transition-all duration-300 ease-in-out":class="isCollapsed ? 'w-[72px]': 'w-64'"
 >
 <!-- ==================== 顶部：Logo + 收缩按钮 ==================== -->
 <div
 class="flex items-center border-b border-border/40":class="isCollapsed ? 'justify-center px-2': 'px-5 gap-3'"
 >
 <RouterLink
 to="/"
 class="group flex items-center gap-2.5 overflow-hidden"
 >
 <div class="relative shrink-0 flex items-center justify-center w-9 rounded-xl overflow-hidden shadow-[0_0_12px_rgba(20,184,166,0.3)]">
 <div class="absolute inset-0 gradient-primary" />
 <span class="icon-[lucide--bot] text-lg text-white relative z-10" />
 </div>
 <div v-if="!isCollapsed" class="flex flex-col">
 <span class="text-lg font-bold text-foreground whitespace-nowrap">Friday AI</span>
 <span class="text-[10px] text-muted-foreground leading-none">v{{ appVersion }}</span>
 </div>
 </RouterLink>
 <button
 v-if="!isCollapsed"
 class="ml-auto .5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
 @click="toggleCollapse"
 >
 <span class="icon-[lucide--panel-left-close] text-lg" />
 </button>
 </div>
 <!-- ==================== 模式切换器 ==================== -->
 <div:class="isCollapsed ? 'px-2': 'px-3'" class="pt-3 pb-2">
 <AppModeSwitcher:collapsed="isCollapsed" />
 </div>
 <!-- ==================== 中间内容区（模式相关） ==================== -->
 <!-- ===== 工作台模式：导航菜单 ===== -->
 <nav v-if="mode === 'friday'" class="flex-1 overflow-y-auto py-1 scrollbar-hide":class="isCollapsed ? 'px-2': 'px-3'">
 <template
 v-for="item in mainNavItems":key="item.to"
 >
 <RouterLink v-slot="{ isActive, isExactActive, navigate, href }":to="item.to" custom>
 <Tooltip v-if="isCollapsed">
 <TooltipTrigger as-child>
 <a:href="href"
 class="flex items-center justify-center rounded-xl transition-all duration-200 mb-0.5":class="(item.exact ? isExactActive: isActive) ? 'sidebar-s2a-link-active': 'sidebar-s2a-link'"
 @click="navigate"
 >
 <span class="text-lg":class="[`icon-[${item.icon}]`]" />
 </a>
 </TooltipTrigger>
 <TooltipContent side="right">
 {{ item.label }}
 </TooltipContent>
 </Tooltip>
 <a
 v-else:href="href"
 class="sidebar-s2a-link mb-0.5":class="{ 'sidebar-s2a-link-active': item.exact ? isExactActive: isActive }"
 @click="navigate"
 >
 <span class="text-lg shrink-0":class="[`icon-[${item.icon}]`]" />
 <span class="truncate">{{ item.label }}</span>
 </a>
 </RouterLink>
 </template>
 <!-- 管理区域（仅 admin 可见） -->
 <template v-if="isSystemAdmin">
 <div class="my-2 border-t border-border/40 mx-1" />
 <template
 v-for="item in adminNavItems":key="item.to"
 >
 <RouterLink v-slot="{ isActive, isExactActive, navigate, href }":to="item.to" custom>
 <Tooltip v-if="isCollapsed">
 <TooltipTrigger as-child>
 <a:href="href"
 class="flex items-center justify-center rounded-xl transition-all duration-200 mb-0.5":class="(item.exact ? isExactActive: isActive) ? 'sidebar-s2a-link-active': 'sidebar-s2a-link'"
 @click="navigate"
 >
 <span class="text-lg":class="[`icon-[${item.icon}]`]" />
 </a>
 </TooltipTrigger>
 <TooltipContent side="right">
 {{ item.label }}
 </TooltipContent>
 </Tooltip>
 <a
 v-else:href="href"
 class="sidebar-s2a-link mb-0.5":class="{ 'sidebar-s2a-link-active': item.exact ? isExactActive: isActive }"
 @click="navigate"
 >
 <span class="text-lg shrink-0":class="[`icon-[${item.icon}]`]" />
 <span class="truncate">{{ item.label }}</span>
 </a>
 </RouterLink>
 </template>
 </template>
 </nav>
 <!-- ===== Chat 模式：对话列表 ===== -->
 <template v-else>
 <!-- 新建对话按钮 -->
 <div:class="isCollapsed ? 'px-2': 'px-3'" class="pb-2">
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
 <Button
 v-else
 variant="outline"
 size="sm"
 class="w-full gap-1.5"
 @click="handleNewConversation"
 >
 <span class="icon-[lucide--plus] text-sm" />
 新建对话
 </Button>
 </div>
 <!-- 对话列表 -->
 <ScrollArea class="flex-1":class="isCollapsed ? 'px-2': ''">
 <div v-if="!isCollapsed" class="px-2 pb-2 space-y-0.5">
 <div v-if="chatStore.loading" class=" text-center text-sm text-muted-foreground">
 加载中...
 </div>
 <div
 v-else-if="chatStore.conversations.length === 0"
 class=" text-center text-sm text-muted-foreground"
 >
 <span class="icon-[lucide--message-square-plus] text-2xl block mb-2 opacity-50" />
 暂无对话
 </div>
 <button
 v-for="conv in chatStore.conversations":key="conv.id"
 class="group w-full text-left px-3 py-2.5 rounded-xl transition-all duration-200 flex items-center gap-2":class="chatStore.currentConversationId === conv.id
 ? 'sidebar-s2a-link-active': 'sidebar-s2a-link'"
 @click="handleSelectConversation(conv.id)"
 >
 <span class="icon-[lucide--message-square] text-base shrink-0" />
 <div class="flex-1 min-w-0">
 <p class="text-sm font-medium truncate">
 {{ conv.title }}
 </p>
 <p class="text-xs opacity-60">
 {{ formatTime(conv.updated_at) }}
 </p>
 </div>
 <button
 class=" w-6 flex items-center justify-center rounded-md opacity-0 group-hover:opacity-100 hover:bg-destructive/10 shrink-0 transition-opacity"
 @click.stop="handleDeleteConversation(conv.id)"
 >
 <span class="icon-[lucide--trash-2] text-xs text-destructive" />
 </button>
 </button>
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
 <div:class="isCollapsed ? 'px-2': 'px-3'" class="py-2">
 <DropdownMenu>
 <DropdownMenuTrigger as-child>
 <button
 class="sidebar-s2a-link w-full":class="isCollapsed ? 'justify-center': ''"
 >
 <div class="relative shrink-0">
 <img
 v-if="authStore.gravatarUrl":src="authStore.gravatarUrl":alt="authStore.displayName"
 class="w-8 rounded-xl ring-1 ring-border/50 object-cover"
 >
 <div
 v-else
 class="w-8 rounded-xl flex items-center justify-center text-sm font-medium text-white gradient-primary"
 >
 {{ (authStore.displayName || '用')[0].toUpperCase }}
 </div>
 </div>
 <template v-if="!isCollapsed">
 <span class="truncate flex-1 text-left">{{ authStore.displayName || '用户' }}</span>
 <span class="icon-[lucide--chevrons-up-down] text-xs shrink-0" />
 </template>
 </button>
 </DropdownMenuTrigger>
 <DropdownMenuContent:side="isCollapsed ? 'right': 'top'":align="isCollapsed ? 'start': 'start'"
 class="w-56"
 >
 <div class="px-3 py-3 flex items-center gap-3">
 <div class="shrink-0">
 <img
 v-if="authStore.gravatarUrl":src="authStore.gravatarUrl":alt="authStore.displayName"
 class="w-10 rounded-xl object-cover"
 >
 <div
 v-else
 class="w-10 rounded-xl flex items-center justify-center text-sm font-semibold text-white gradient-primary"
 >
 {{ (authStore.displayName || '用')[0].toUpperCase }}
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
