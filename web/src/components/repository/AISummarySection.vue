<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import type { AISummaryStatus, AISummaryStatusResponse } from '~/api/repositories'
import { ApiError } from '~/api/client'
import { repositoriesApi } from '~/api/repositories'
import { useToast } from '~/composables/useToast'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '~/components/ui/collapsible'
import { Skeleton } from '~/components/ui/skeleton'
import { MarkdownPreview } from '~/components/ui/markdown-editor'
const props = defineProps<{
 repositoryId: string
}>
const { success: toastSuccess, warning: toastWarning } = useToast
// 状态
const status = ref<AISummaryStatus>('not_started')
const summary = ref<string | null>(null)
const generatedAt = ref<string | null>(null)
const errorMsg = ref<string | null>(null)
const generating = ref(false)
// 轮询控制
let pollTimer: ReturnType<typeof setTimeout> | null = null
let pollCount = 0
// Collapsible 分段展开状态
const sections = reactive({
 overview: true,
 tech_stack: true,
 modules: true,
 entry_points: true,
 build_commands: true,
 testing_commands: true,
 conventions: true,
})
// 解析 JSON summary
const parsedSummary = computed( => {
 if (!summary.value) return null
 try {
 const parsed = JSON.parse(summary.value)
 if (typeof parsed === 'object' && parsed !== null) return parsed
 return null
 }
 catch {
 return null
 }
})
// Badge variant 映射
const badgeVariant = computed( => {
 const map: Record<AISummaryStatus, string> = {
 not_started: 'secondary',
 pending: 'warning',
 running: 'info',
 completed: 'success',
 failed: 'destructive',
 }
 return map[status.value]
})
// Badge 文案映射
const badgeText = computed( => {
 const map: Record<AISummaryStatus, string> = {
 not_started: '',
 pending: '排队中',
 running: '生成中',
 completed: '已完成',
 failed: '生成失败',
 }
 return map[status.value]
})
// 获取状态
async function fetchStatus {
 try {
 const res: AISummaryStatusResponse = await repositoriesApi.getSummaryStatus(props.repositoryId)
 status.value = res.status
 summary.value = res.summary
 generatedAt.value = res.generated_at
 errorMsg.value = res.error
 // 终态时停止轮询
 if (res.status === 'completed' || res.status === 'failed' || res.status === 'not_started') {
 stopPolling
 }
 }
 catch {
 // 静默处理
 }
}
// 启动轮询（setTimeout 递归，per ）
function startPolling {
 stopPolling
 pollCount = 0
 poll
}
function poll {
 const delay = pollCount < 3 ? 2000: 4000
 pollTimer = setTimeout(async => {
 await fetchStatus
 // 非终态时继续轮询
 if (status.value === 'pending' || status.value === 'running') {
 pollCount++
 poll
 }
 }, delay)
}
function stopPolling {
 if (pollTimer) {
 clearTimeout(pollTimer)
 pollTimer = null
 }
 pollCount = 0
}
// 触发生成
async function generateSummary {
 generating.value = true
 const isRegenerate = status.value === 'completed' || status.value === 'failed'
 try {
 await repositoriesApi.generateSummary(props.repositoryId)
 status.value = 'pending'
 toastSuccess(isRegenerate ? 'AI 描述重新生成任务已启动': 'AI 描述生成任务已启动')
 startPolling
 }
 catch (e: unknown) {
 if (e instanceof ApiError && e.status === 409) {
 toastWarning('描述正在生成中，请稍候')
 // 恢复 polling 以跟踪进度
 if (status.value !== 'pending' && status.value !== 'running') {
 status.value = 'running'
 }
 startPolling
 }
 }
 finally {
 generating.value = false
 }
}
// 分段配置
const sectionConfig = [
 { key: 'overview', title: '项目概览', icon: 'icon-[lucide--info]', type: 'markdown' },
 { key: 'tech_stack', title: '技术栈', icon: 'icon-[lucide--layers]', type: 'badges' },
 { key: 'modules', title: '模块结构', icon: 'icon-[lucide--folder-tree]', type: 'modules' },
 { key: 'entry_points', title: '入口文件', icon: 'icon-[lucide--file-code]', type: 'mono-list' },
 { key: 'build_commands', title: '构建命令', icon: 'icon-[lucide--terminal]', type: 'mono-list' },
 { key: 'testing_commands', title: '测试命令', icon: 'icon-[lucide--flask-conical]', type: 'mono-list' },
 { key: 'conventions', title: '代码规范', icon: 'icon-[lucide--book-open]', type: 'markdown' },
] as const
onMounted(async => {
 await fetchStatus
 if (status.value === 'pending' || status.value === 'running') {
 startPolling
 }
})
onUnmounted( => {
 stopPolling
})
</script>
<template>
 <div class="card overflow-hidden">
 <!-- 卡片头 -->
 <div class="flex items-center justify-between px-5 py-3.5 border-b border-border/50">
 <div class="flex items-center gap-2">
 <span class="icon-[lucide--sparkles] text-primary" />
 <h3 class="text-base font-semibold text-foreground">AI 智能描述</h3>
 </div>
 <div class="flex items-center gap-2">
 <!-- pending / running Badge -->
 <Badge v-if="status === 'pending'" variant="warning">
 <span class="icon-[lucide--clock] mr-1" />
 排队中
 </Badge>
 <Badge v-else-if="status === 'running'" variant="info">
 <span class="icon-[lucide--loader-2] mr-1 animate-spin" />
 生成中
 </Badge>
 <!-- completed: 时间戳 + 重新生成 -->
 <template v-else-if="status === 'completed'">
 <span v-if="generatedAt" class="text-xs text-muted-foreground">
 生成于 {{ new Date(generatedAt).toLocaleString('zh-CN') }}
 </span>
 <Button
 variant="ghost"
 size="sm":disabled="generating"
 @click="generateSummary"
 >
 <span class="icon-[lucide--sparkles] mr-1.5" />
 重新生成描述
 </Button>
 </template>
 <!-- failed: 重新生成 -->
 <template v-else-if="status === 'failed'">
 <Button
 variant="ghost"
 size="sm":disabled="generating"
 @click="generateSummary"
 >
 <span class="icon-[lucide--sparkles] mr-1.5" />
 重新生成描述
 </Button>
 </template>
 </div>
 </div>
 <!-- 卡片内容 -->
 <div class="">
 <!-- 状态 A: not_started 空状态 -->
 <div v-if="status === 'not_started'" class="flex flex-col items-center justify-center py-8 space-y-3">
 <span class="icon-[lucide--sparkles] text-2xl text-muted-foreground/40" />
 <p class="text-sm font-semibold text-foreground">尚未生成 AI 描述</p>
 <p class="text-xs text-muted-foreground text-center">
 点击下方按钮，AI 将自动分析仓库结构并生成智能描述
 </p>
 <Button
 variant="default"
 size="sm":disabled="generating"
 @click="generateSummary"
 >
 <span class="icon-[lucide--sparkles] mr-1.5" />
 生成 AI 描述
 </Button>
 </div>
 <!-- 状态 B: pending / running 加载骨架屏 -->
 <div v-else-if="status === 'pending' || status === 'running'" class="space-y-4">
 <div class="space-y-3">
 <Skeleton class=" w-full" />
 <Skeleton class=" w-4/5" />
 <Skeleton class=" w-3/5" />
 </div>
 <div class="flex items-center gap-2 text-sm text-muted-foreground">
 <span class="icon-[lucide--loader-2] animate-spin" />
 <span>{{ status === 'pending' ? '任务排队中...': 'AI 正在分析仓库结构...' }}</span>
 </div>
 </div>
 <!-- 状态 C: completed -->
 <div v-else-if="status === 'completed' && summary">
 <!-- 结构化 JSON 分段展示 -->
 <div v-if="parsedSummary" class="space-y-4">
 <template v-for="section in sectionConfig":key="section.key">
 <Collapsible
 v-if="parsedSummary[section.key]"
 v-model:open="sections[section.key]"
 default-open
 >
 <CollapsibleTrigger class="flex items-center gap-2 w-full px-3 py-2 rounded-lg hover:bg-muted/40 transition-colors">
 <span
 class="icon-[lucide--chevron-right] transition-transform":class="{ 'rotate-90': sections[section.key] }"
 />
 <span:class="section.icon" class="text-primary" />
 <span class="text-xs font-semibold text-foreground">{{ section.title }}</span>
 </CollapsibleTrigger>
 <CollapsibleContent>
 <div class="mt-1 ml-7 rounded-lg bg-muted/30 border border-border/40">
 <!-- Markdown 渲染 -->
 <template v-if="section.type === 'markdown'">
 <MarkdownPreview:content="String(parsedSummary[section.key])" />
 </template>
 <!-- 技术栈 Badge 列表 -->
 <template v-else-if="section.type === 'badges'">
 <div class="flex flex-wrap gap-2">
 <Badge
 v-for="(tech, idx) in (Array.isArray(parsedSummary[section.key])
 ? parsedSummary[section.key]: String(parsedSummary[section.key]).split(','))":key="idx"
 variant="secondary"
 class="font-mono text-sm"
 >
 {{ typeof tech === 'string' ? tech.trim: tech }}
 </Badge>
 </div>
 </template>
 <!-- 模块结构 -->
 <template v-else-if="section.type === 'modules'">
 <div class="space-y-2">
 <div
 v-for="(mod, idx) in (Array.isArray(parsedSummary[section.key]) ? parsedSummary[section.key]: )":key="idx"
 class="flex items-start gap-2"
 >
 <span class="text-sm font-semibold text-foreground shrink-0">
 {{ typeof mod === 'object' && mod?.name ? mod.name: mod }}
 </span>
 <span
 v-if="typeof mod === 'object' && mod?.description"
 class="text-sm text-muted-foreground"
 >
 {{ mod.description }}
 </span>
 </div>
 </div>
 </template>
 <!-- 等宽列表（入口文件/构建命令/测试命令） -->
 <template v-else-if="section.type === 'mono-list'">
 <div class="space-y-1">
 <div
 v-for="(item, idx) in (Array.isArray(parsedSummary[section.key]) ? parsedSummary[section.key]: )":key="idx"
 class="font-mono text-sm text-foreground"
 >
 {{ item }}
 </div>
 </div>
 </template>
 </div>
 </CollapsibleContent>
 </Collapsible>
 </template>
 </div>
 <!-- Markdown 降级模式 -->
 <div v-else class=" rounded-lg bg-muted/30 border border-border/40 max-h-[400px] overflow-y-auto">
 <MarkdownPreview:content="summary" />
 </div>
 </div>
 <!-- 状态 D: failed -->
 <div v-else-if="status === 'failed'" class="flex flex-col items-center justify-center py-8 space-y-3">
 <span class="icon-[lucide--alert-triangle] text-2xl text-destructive" />
 <p class="text-sm font-semibold text-foreground">描述生成失败</p>
 <p v-if="errorMsg" class="text-sm text-destructive text-center max-w-md">
 {{ errorMsg }}
 </p>
 <Button
 variant="outline"
 size="sm":disabled="generating"
 @click="generateSummary"
 >
 <span class="icon-[lucide--sparkles] mr-1.5" />
 重新生成描述
 </Button>
 </div>
 </div>
 </div>
</template>
