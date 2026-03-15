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
interface NavItem {
 to: string
 label: string
 icon: string
 requiresAdmin?: boolean
}
const authStore = useAuthStore
const router = useRouter
const route = useRoute
const { isSystemAdmin } = usePermission
// 收缩状态持久化到 localStorage
const isCollapsed = useLocalStorage('sidebar-collapsed', false)
function toggleCollapse {
 isCollapsed.value = !isCollapsed.value
}
// 主导航项
const mainNavItems: NavItem = [
 { to: '/', label: '首页', icon: 'lucide--home' },
 { to: '/projects', label: '项目', icon: 'lucide--folder-git-2' },
 { to: '/repositories', label: '仓库', icon: 'lucide--git-branch' },
 { to: '/workflows', label: '工作流', icon: 'lucide--workflow' },
 { to: '/executions', label: '执行', icon: 'lucide--play-circle' },
 { to: '/analytics', label: '分析', icon: 'lucide--bar-chart-3' },
 { to: '/runners', label: 'Runner', icon: 'lucide--server' },
 { to: '/logs', label: '日志', icon: 'lucide--file-text' },
]
// 底部导航项（受权限控制）
const bottomNavItems: NavItem = [
 { to: '/settings', label: '设置', icon: 'lucide--settings', requiresAdmin: true },
]
// 判断当前路由是否激活
function isActive(path: string) {
 if (path === '/') {
 return route.path === '/'
 }
 return route.path.startsWith(path)
}
// 退出登录
async function handleLogout {
 await authStore.logout
 router.push('/login')
}
</script>
<template>
 <TooltipProvider:delay-duration="300">
 <aside
 class="relative flex flex-col h-screen shrink-0 border-r border-border/50 bg-card/80 backdrop-blur-xl transition-all duration-300 ease-in-out":class="isCollapsed ? 'w-16': 'w-60'"
 >
 <!-- 顶部区域：Logo + 收缩按钮 -->
 <div class="flex items-center px-3 border-b border-border/40">
 <RouterLink
 to="/"
 class="group flex items-center gap-2.5 overflow-hidden"
 >
 <div class="relative shrink-0">
 <div class="absolute inset-0 bg-gradient-to-br from-primary to-primary/50 rounded-lg blur-md opacity-50 group-hover:opacity-75 transition-opacity" />
 <div class="relative .5 rounded-lg bg-gradient-to-br from-primary to-primary/80 flex items-center justify-center">
 <span class="icon-[lucide--bot] text-lg text-white" />
 </div>
 </div>
 <span
 v-if="!isCollapsed"
 class="text-lg font-bold bg-gradient-to-r from-primary to-primary/70 bg-clip-text text-transparent whitespace-nowrap"
 >
 Friday AI
 </span>
 </RouterLink>
 <button
 v-if="!isCollapsed"
 class="ml-auto .5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
 @click="toggleCollapse"
 >
 <span class="icon-[lucide--panel-left-close] text-lg" />
 </button>
 </div>
 <!-- 收缩模式下的展开按钮 -->
 <div
 v-if="isCollapsed"
 class="flex justify-center py-2 border-b border-border/40"
 >
 <button
 class=".5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
 @click="toggleCollapse"
 >
 <span class="icon-[lucide--panel-left-open] text-lg" />
 </button>
 </div>
 <!-- 主导航区域 -->
 <nav class="flex-1 overflow-y-auto py-2 px-2">
 <template
 v-for="item in mainNavItems":key="item.to"
 >
 <Tooltip v-if="isCollapsed">
 <TooltipTrigger as-child>
 <RouterLink:to="item.to"
 class="relative flex items-center justify-center rounded-lg transition-all duration-200 mb-0.5":class="[
 isActive(item.to)
 ? 'bg-primary/10 text-primary': 'text-muted-foreground hover:text-foreground hover:bg-muted/50',
 ]"
 >
 <!-- 激活指示条 -->
 <div
 v-if="isActive(item.to)"
 class="absolute left-0 top-1.5 bottom-1.5 w-0.5 rounded-full bg-primary"
 />
 <span class="text-lg":class="[`icon-[${item.icon}]`]" />
 </RouterLink>
 </TooltipTrigger>
 <TooltipContent side="right">
 {{ item.label }}
 </TooltipContent>
 </Tooltip>
 <RouterLink
 v-else:to="item.to"
 class="relative flex items-center gap-3 px-3 rounded-lg text-sm font-medium transition-all duration-200 mb-0.5":class="[
 isActive(item.to)
 ? 'bg-primary/10 text-primary': 'text-muted-foreground hover:text-foreground hover:bg-muted/50',
 ]"
 >
 <!-- 激活指示条 -->
 <div
 v-if="isActive(item.to)"
 class="absolute left-0 top-1.5 bottom-1.5 w-0.5 rounded-full bg-primary"
 />
 <span class="text-lg shrink-0":class="[`icon-[${item.icon}]`]" />
 <span class="truncate">{{ item.label }}</span>
 </RouterLink>
 </template>
 </nav>
 <!-- 底部导航区域（设置等受权限控制的项） -->
 <div class="px-2 pb-1">
 <template
 v-for="item in bottomNavItems":key="item.to"
 >
 <template v-if="!item.requiresAdmin || isSystemAdmin">
 <Tooltip v-if="isCollapsed">
 <TooltipTrigger as-child>
 <RouterLink:to="item.to"
 class="relative flex items-center justify-center rounded-lg transition-all duration-200 mb-0.5":class="[
 isActive(item.to)
 ? 'bg-primary/10 text-primary': 'text-muted-foreground hover:text-foreground hover:bg-muted/50',
 ]"
 >
 <div
 v-if="isActive(item.to)"
 class="absolute left-0 top-1.5 bottom-1.5 w-0.5 rounded-full bg-primary"
 />
 <span class="text-lg":class="[`icon-[${item.icon}]`]" />
 </RouterLink>
 </TooltipTrigger>
 <TooltipContent side="right">
 {{ item.label }}
 </TooltipContent>
 </Tooltip>
 <RouterLink
 v-else:to="item.to"
 class="relative flex items-center gap-3 px-3 rounded-lg text-sm font-medium transition-all duration-200 mb-0.5":class="[
 isActive(item.to)
 ? 'bg-primary/10 text-primary': 'text-muted-foreground hover:text-foreground hover:bg-muted/50',
 ]"
 >
 <div
 v-if="isActive(item.to)"
 class="absolute left-0 top-1.5 bottom-1.5 w-0.5 rounded-full bg-primary"
 />
 <span class="text-lg shrink-0":class="[`icon-[${item.icon}]`]" />
 <span class="truncate">{{ item.label }}</span>
 </RouterLink>
 </template>
 </template>
 </div>
 <!-- 分隔线 -->
 <div class="mx-2 border-t border-border/40" />
 <!-- 底部用户区 -->
 <div class="px-2 py-2">
 <DropdownMenu>
 <DropdownMenuTrigger as-child>
 <button
 class="flex items-center w-full gap-3 px-2 py-2 rounded-lg text-sm font-medium text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors":class="isCollapsed ? 'justify-center': ''"
 >
 <!-- 用户头像 -->
 <div class="relative shrink-0">
 <img
 v-if="authStore.gravatarUrl":src="authStore.gravatarUrl":alt="authStore.displayName"
 class="w-7 rounded-full ring-1 ring-border/50"
 >
 <div
 v-else
 class="w-7 rounded-full bg-gradient-to-br from-primary/20 to-primary/10 flex items-center justify-center ring-1 ring-border/50"
 >
 <span class="icon-[lucide--user] text-sm text-primary" />
 </div>
 </div>
 <!-- 展开模式下显示用户名 -->
 <template v-if="!isCollapsed">
 <span class="truncate flex-1 text-left">{{ authStore.displayName || '用户' }}</span>
 <span class="icon-[lucide--chevrons-up-down] text-xs shrink-0" />
 </template>
 </button>
 </DropdownMenuTrigger>
 <DropdownMenuContent:side="isCollapsed ? 'right': 'top'":align="isCollapsed ? 'start': 'start'"
 class="w-48"
 >
 <!-- 用户信息头 -->
 <div class="px-2 py-1.5">
 <p class="text-sm font-medium">{{ authStore.displayName || '用户' }}</p>
 <p class="text-xs text-muted-foreground">{{ authStore.user?.username }}</p>
 </div>
 <DropdownMenuSeparator />
 <DropdownMenuItem class="cursor-pointer" @click="router.push('/profile')">
 <span class="icon-[lucide--user] mr-2" />
 个人资料
 </DropdownMenuItem>
 <DropdownMenuItem class="cursor-pointer" @click="router.push('/settings/account')">
 <span class="icon-[lucide--user-cog] mr-2" />
 账号设置
 </DropdownMenuItem>
 <DropdownMenuSeparator />
 <DropdownMenuItem
 class="cursor-pointer text-destructive focus:text-destructive"
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
