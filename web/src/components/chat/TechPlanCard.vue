<script setup lang="ts">
import type MarkdownIt from 'markdown-it'
/**
 * 技术方案卡片 — Phase 落地。
 *
 * CodingPlan 的主展示组件。承载 Markdown 渲染 + affected_files
 * 列表 + 分支名编辑 + 折叠/展开。与 CodingSession 解耦：通过 planId
 * 标识独立方案，sessionId 作为执行会话引用（可选）。
 *
 * Phase 阶段：completed / failed 状态保留最小占位（一行 fallback
 * 提示，避免空白）；详细的绿框 / PR 链接 / 红框 / 重试按钮 / Skeleton
 * 落在 Phase。
 */
import { computed, onMounted, ref, watch, watchEffect } from 'vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '~/components/ui/select'
import { useBranchValidation } from '~/composables/useBranchValidation'
import { getMarkdownRenderer } from '~/composables/useMarkdownRenderer'
const props = withDefaults(defineProps<{
 planId: string
 title?: string
 techPlan: string
 affectedFiles: Array<{ file_path?: string, path?: string, change_type: string }>
 status: 'draft' | 'confirmed' | 'running' | 'awaiting_confirmation' | 'completed' | 'failed'
 isConfirming: boolean
 sessionId?: string
 branchName?: string
 defaultCollapsed?: boolean
 // Phase：completed 状态可选展示 PR / branch 链接
 prUrl?: string
 branchUrl?: string
 // Phase：failed 状态可选展示错误原因
 errorMessage?: string
}>, {
 // 显式保留 undefined（Vue 默认会把缺省 Boolean prop coerce 成 false，
 // 那样会破坏 initialCollapsed 的 fallback 判定）
 defaultCollapsed: undefined,
})
const emit = defineEmits<{
 confirm: [planId: string, sessionId: string | undefined, branchName?: string]
 // Phase：failed 状态下用户点击重试；接通 endpoint 留 Phase/
 retry: [planId: string, sessionId: string | undefined]
}>
// ---------------------------------------------------------------------------
// 折叠状态：默认 draft 展开、其它状态折叠（用户可点击切换）
// ---------------------------------------------------------------------------
function computedInitialCollapsed: boolean {
 if (props.defaultCollapsed !== undefined)
 return props.defaultCollapsed
 return props.status !== 'draft'
}
const collapsed = ref<boolean>(computedInitialCollapsed)
function toggleCollapsed {
 collapsed.value = !collapsed.value
}
// ---------------------------------------------------------------------------
// affected_files schema 软回退（兼容 backend 还没归一化的旧 path）
// ---------------------------------------------------------------------------
function filePath(file: { file_path?: string, path?: string }): string {
 return file.file_path ?? file.path ?? ''
}
// ---------------------------------------------------------------------------
// Markdown 渲染
// ---------------------------------------------------------------------------
const renderedPlan = ref('')
const mdReady = ref(false)
const mdInstance = ref<MarkdownIt | null>(null)
onMounted(async => {
 mdInstance.value = await getMarkdownRenderer
 mdReady.value = true
})
watchEffect( => {
 if (mdInstance.value && props.techPlan) {
 renderedPlan.value = mdInstance.value.render(props.techPlan)
 }
})
// ---------------------------------------------------------------------------
// 分支名编辑（沿用 CodingPlanCard 逻辑； / ）
// ---------------------------------------------------------------------------
const { parseBranchName, buildBranchName, validateShortDesc } = useBranchValidation
const parsed = computed( => props.branchName ? parseBranchName(props.branchName): null)
const branchType = ref(parsed.value?.type || 'feat')
const branchDate = computed( => parsed.value?.date || '')
const shortDesc = ref(parsed.value?.shortDesc || '')
const validation = computed( => validateShortDesc(shortDesc.value))
const previewBranchName = computed( =>
 branchDate.value ? buildBranchName(branchType.value, branchDate.value, shortDesc.value): '',
)
watch( => props.branchName, (newVal) => {
 if (newVal) {
 const p = parseBranchName(newVal)
 if (p) {
 branchType.value = p.type
 shortDesc.value = p.shortDesc
 }
 }
}, { immediate: true })
function handleConfirm {
 const editedBranch = previewBranchName.value || undefined
 emit('confirm', props.planId, props.sessionId, editedBranch)
}
function handleRetry {
 emit('retry', props.planId, props.sessionId)
}
// ---------------------------------------------------------------------------
// Phase：completed/failed 状态卡片整体染色
// ---------------------------------------------------------------------------
const cardClass = computed( => {
 if (props.status === 'completed')
 return 'ring-1 ring-emerald-500/30 border-emerald-500/30'
 if (props.status === 'failed')
 return 'ring-1 ring-destructive/30 border-destructive/30'
 return ''
})
// ---------------------------------------------------------------------------
// 状态徽章
// ---------------------------------------------------------------------------
const badgeClass = computed( => {
 if (props.status === 'confirmed' || props.status === 'running' || props.status === 'awaiting_confirmation') {
 return 'text-primary border-primary/30 bg-primary/5'
 }
 if (props.status === 'completed') {
 return 'text-emerald-500 border-emerald-500/30 bg-emerald-500/5'
 }
 return ''
})
const badgeText = computed( => {
 if (props.status === 'confirmed' || props.status === 'running')
 return '已确认'
 if (props.status === 'awaiting_confirmation')
 return '确认中'
 if (props.status === 'completed')
 return '已完成'
 if (props.status === 'failed')
 return '失败'
 return ''
})
</script>
<template>
 <div class="card mt-2 animate-fade-in":class="cardClass">
 <!-- 头部（可点击折叠） -->
 <button
 class="px-4 py-3 border-b border-border/50 flex items-center gap-2 w-full text-left"
 type="button"
 @click="toggleCollapsed"
 >
 <span class="icon-[lucide--file-code] text-primary" />
 <span class="text-sm font-semibold">{{ title || '编码方案' }}</span>
 <Badge
 v-if="status !== 'draft'":variant="status === 'failed' ? 'destructive': 'outline'"
 class="ml-auto":class="[badgeClass]"
 >
 {{ badgeText }}
 </Badge>
 <span
 class="icon-[lucide--chevron-right] text-xs transition-transform":class="[
 status === 'draft' ? 'ml-auto': 'ml-1',
 { 'rotate-90': !collapsed },
 ]"
 />
 </button>
 <!-- 展开内容 -->
 <template v-if="!collapsed">
 <!-- Markdown + affected_files -->
 <div class=" space-y-3">
 <!-- Phase：markdown 异步初始化期间的 skeleton 占位 -->
 <div v-if="!mdReady" class="space-y-2 animate-pulse" data-test="md-skeleton">
 <div class=" rounded bg-muted/60 w-3/4" />
 <div class=" rounded bg-muted/60 w-1/2" />
 <div class=" rounded bg-muted/60 w-2/3" />
 </div>
 <div v-else class="prose prose-sm max-w-none" v-html="renderedPlan" />
 <div v-if="affectedFiles.length > 0" class="space-y-1">
 <p class="text-xs text-muted-foreground font-medium">
 影响文件
 </p>
 <div
 v-for="(file, i) in affectedFiles":key="i"
 class="text-xs text-muted-foreground flex items-center gap-1"
 >
 <span class="icon-[lucide--file] text-[10px]" />
 <code class="text-xs">{{ filePath(file) }}</code>
 <span class="text-muted-foreground/60">({{ file.change_type }})</span>
 </div>
 </div>
 </div>
 <!-- draft：分支名编辑 + 开始编码 -->
 <div v-if="status === 'draft'" class="px-4 pb-4">
 <div v-if="branchName" class="space-y-3 mb-3">
 <p class="text-xs text-muted-foreground font-medium">
 功能分支
 </p>
 <div class="flex items-end gap-2">
 <Select v-model="branchType">
 <SelectTrigger class="w-24 ">
 <SelectValue />
 </SelectTrigger>
 <SelectContent>
 <SelectItem value="feat">
 feat
 </SelectItem>
 <SelectItem value="fix">
 fix
 </SelectItem>
 <SelectItem value="chore">
 chore
 </SelectItem>
 </SelectContent>
 </Select>
 <span class="text-xs font-mono text-muted-foreground shrink-0 pb-2">{{ branchDate }}.</span>
 <Input
 v-model="shortDesc"
 class="flex-1 font-mono text-sm"
 placeholder="简短描述（英文）":disabled="isConfirming"
 />
 </div>
 <p v-if="shortDesc && !validation.valid" class="text-xs text-destructive mt-1">
 {{ validation.error }}
 </p>
 <div v-if="previewBranchName" class="text-xs font-mono text-foreground bg-muted/50 rounded px-2 py-1">
 分支名预览: {{ previewBranchName }}
 </div>
 </div>
 <Button
 class="w-full":disabled="isConfirming || (branchName && (!validation.valid || !shortDesc.trim) ? true: false)"
 @click="handleConfirm"
 >
 <span v-if="isConfirming" class="icon-[lucide--loader-2] animate-spin mr-2" />
 开始编码
 </Button>
 </div>
 <!-- confirmed / running：等待 / 编码中提示 -->
 <div v-else-if="status === 'confirmed' || status === 'running'" class="px-4 pb-3">
 <div class="text-xs text-muted-foreground flex items-center gap-1">
 <span class="icon-[lucide--loader-2] animate-spin text-primary" />
 {{ status === 'running' ? '正在编码中…': '已确认，正在启动编码…' }}
 </div>
 </div>
 <!-- awaiting_confirmation：等待用户确认下一步 -->
 <div v-else-if="status === 'awaiting_confirmation'" class="px-4 pb-3">
 <div class="text-xs text-muted-foreground flex items-center gap-1">
 <span class="icon-[lucide--pause-circle] text-primary" />
 等待用户确认下一步
 </div>
 </div>
 <!-- completed：绿框 + PR/branch 链接（缺失时显示占位） -->
 <div v-else-if="status === 'completed'" class="px-4 pb-4 space-y-2">
 <div class="text-xs text-emerald-600 dark:text-emerald-400 flex items-center gap-1">
 <span class="icon-[lucide--check-circle-2]" />
 编码完成
 </div>
 <div v-if="prUrl" class="text-xs">
 <a:href="prUrl"
 target="_blank"
 rel="noopener noreferrer"
 class="text-primary underline-offset-4 hover:underline inline-flex items-center gap-1"
 >
 <span class="icon-[lucide--git-pull-request]" />
 查看 PR
 </a>
 </div>
 <div v-if="branchUrl" class="text-xs">
 <a:href="branchUrl"
 target="_blank"
 rel="noopener noreferrer"
 class="text-muted-foreground hover:text-foreground inline-flex items-center gap-1"
 >
 <span class="icon-[lucide--git-branch]" />
 查看分支
 </a>
 </div>
 <div v-if="!prUrl && !branchUrl" class="text-xs text-muted-foreground/80">
 PR 链接将由 multi-confirm 流程回填
 </div>
 </div>
 <!-- failed：红框 + 错误原因 + 重试按钮 -->
 <div v-else-if="status === 'failed'" class="px-4 pb-4 space-y-2">
 <div class="text-xs text-destructive flex items-start gap-1">
 <span class="icon-[lucide--alert-triangle] mt-0.5 shrink-0" />
 <span>{{ errorMessage || '编码失败，未提供错误信息' }}</span>
 </div>
 <Button
 variant="outline"
 size="sm"
 class=""
 @click="handleRetry"
 >
 <span class="icon-[lucide--refresh-cw] mr-1.5" />
 重试
 </Button>
 </div>
 </template>
 <!-- 折叠态：一行摘要 -->
 <template v-else>
 <div class="px-4 py-2 text-xs text-muted-foreground truncate">
 {{ techPlan.split('\n')[0] || '（无方案文本）' }}
 </div>
 </template>
 </div>
</template>
