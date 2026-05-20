<script setup lang="ts">
import type MarkdownIt from 'markdown-it'
import type { CodingPlanRuntime, RepoSelectableItem } from '~/types/chat'
/**
 * 技术方案卡片 — Phase 落地，Phase 扩展为多仓 fan-out 入口。
 *
 * CodingPlan 的主展示组件。承载 Markdown 渲染 + affected_files 列表 + 折叠/展开。
 *
 * Phase 新增两种交互入口：
 * - 创建态（无 sessions）：codingPlanId 提供时，把旧的「开始编码」单仓按钮
 * 替换为内嵌 RepoMultiSelector，让用户一次性挑多个仓库 fan-out。
 * - 追加态（已有 sessions）：右上角「+ 对新仓库编码」按钮 + Dialog 弹层
 * 选新仓库；已选 active sessions 的 repo 在 selector 内 disabled。
 *
 * codingPlanId 未提供时（旧 ChatMessageBubble 单仓路径）保留原 draft 按钮，
 * 向后兼容不破。
 */
import { computed, onMounted, ref, watch, watchEffect } from 'vue'
import { storeToRefs } from 'pinia'
import CodingSessionStatusRow from '~/components/chat/CodingSessionStatusRow.vue'
import ExportConfirmDialog from '~/components/chat/ExportConfirmDialog.vue'
import RepoMultiSelector from '~/components/chat/RepoMultiSelector.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import {
 Dialog,
 DialogContent,
 DialogDescription,
 DialogHeader,
 DialogTitle,
} from '~/components/ui/dialog'
import { Input } from '~/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '~/components/ui/select'
import { useBranchValidation } from '~/composables/useBranchValidation'
import { getMarkdownRenderer } from '~/composables/useMarkdownRenderer'
import { useToast } from '~/composables/useToast'
import { useChatStore } from '~/stores/chat'
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
 // Phase：多仓 fan-out 入口
 //
 // codingPlanId 提供时启用 multi-repo 流程（创建态 / 追加态 / 重试 / 状态行
 // 列表）；不提供时保留旧的 single-session draft 流程（向后兼容
 // ChatMessageBubble 历史调用）。
 codingPlanId?: string | null
 availableRepositories?: RepoSelectableItem
 repositoryGitUrls?: Record<string, string>
 recommendedRepositoryIds?: string
}>, {
 // 显式保留 undefined（Vue 默认会把缺省 Boolean prop coerce 成 false，
 // 那样会破坏 initialCollapsed 的 fallback 判定）
 defaultCollapsed: undefined,
 availableRepositories: =>,
 repositoryGitUrls: => ({}),
 recommendedRepositoryIds: =>,
})
const emit = defineEmits<{
 confirm: [planId: string, sessionId: string | undefined, branchName?: string]
 // Phase：failed 状态下用户点击重试；Phase 起当 codingPlanId
 // 存在时由 store.retrySingleRepository 接管，emit 仍保留作旧接口兜底。
 retry: [planId: string, sessionId: string | undefined]
}>
// ---------------------------------------------------------------------------
// Phase：多仓 fan-out 状态机
// ---------------------------------------------------------------------------
const chatStore = useChatStore
const { activeCodingPlan, repoMultiSelectorState } = storeToRefs(chatStore)
const { success: toastSuccess, error: toastError } = useToast
const codingPlanRuntime = computed<CodingPlanRuntime | null>(
 => activeCodingPlan.value,
)
const sessions = computed( => codingPlanRuntime.value?.sessions ?? )
const hasSessions = computed( => sessions.value.length > 0)
const ACTIVE_STATUSES = new Set(['draft', 'confirmed', 'running', 'awaiting_confirmation'])
const existingActiveRepoIds = computed( =>
 sessions.value
 .filter(s => ACTIVE_STATUSES.has(s.status))
 .map(s => s.repository_id),
)
const showInlineSelector = computed(
 => !!props.codingPlanId && !hasSessions.value,
)
const dialogOpen = ref(false)
const dialogSelectedIds = ref<string>
function openAppendDialog {
 if (!props.codingPlanId)
 return
 dialogSelectedIds.value =
 chatStore.openRepoMultiSelector(props.codingPlanId, )
 dialogOpen.value = true
}
async function handleMultiConfirm(repoIds: string) {
 if (!props.codingPlanId)
 return
 try {
 chatStore.openRepoMultiSelector(props.codingPlanId, repoIds)
 const result = await chatStore.submitRepoMultiSelector(repoIds)
 const suffix = result.failedCount > 0 ? `；${result.failedCount} 个失败`: ''
 toastSuccess(`${result.createdCount} 个仓库已加入编码${suffix}`)
 dialogOpen.value = false
 dialogSelectedIds.value =
 }
 catch (e: any) {
 toastError(e?.message || '批量创建编码失败')
 }
 finally {
 chatStore.closeRepoMultiSelector
 }
}
// ---------------------------------------------------------------------------
// Phase：导出到飞书三态按钮
// ---------------------------------------------------------------------------
const showExportDialog = ref(false)
/** 已导出的飞书文档 URL（来自 store CodingPlanRuntime / patch；空串视为未导出）。 */
const feishuDocUrl = computed<string>(
 => codingPlanRuntime.value?.feishu_doc_url || '',
)
function triggerExport {
 if (!props.codingPlanId)
 return
 showExportDialog.value = true
}
function openFeishu {
 if (!feishuDocUrl.value)
 return
 window.open(feishuDocUrl.value, '_blank', 'noopener,noreferrer')
}
async function handleSessionRowRetry(rowSessionId: string) {
 const session = sessions.value.find(s => s.session_id === rowSessionId)
 if (!session || !props.codingPlanId)
 return
 try {
 const result = await chatStore.retrySingleRepository(
 props.codingPlanId,
 session.repository_id,
 )
 if (result.createdCount > 0)
 toastSuccess('已重新发起编码')
 else
 toastError('重试失败')
 }
 catch (e: any) {
 toastError(e?.message || '重试失败')
 }
}
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
 <!-- Phase：导出到飞书三态按钮 -->
 <div v-if="codingPlanId" class="px-4 pb-3 pt-1 flex items-center gap-2">
 <Button
 v-if="!feishuDocUrl"
 variant="outline"
 size="sm"
 class="text-xs"
 @click="triggerExport"
 >
 <span class="icon-[lucide--file-up] mr-1" />
 导出到飞书
 </Button>
 <template v-else>
 <Button
 variant="outline"
 size="sm"
 class="text-xs"
 @click="openFeishu"
 >
 <span class="icon-[lucide--external-link] mr-1" />
 在飞书打开
 </Button>
 <Button
 variant="ghost"
 size="icon"
 aria-label="重新导出"
 class=" w-7"
 @click="triggerExport"
 >
 <span class="icon-[lucide--refresh-cw] text-sm" />
 </Button>
 </template>
 </div>
 <!-- Phase /：已加入的仓库 sessions 列表 -->
 <div v-if="hasSessions" class="px-4 pb-3 pt-2 space-y-1">
 <div class="flex items-center justify-between">
 <p class="text-xs text-muted-foreground font-medium">
 目标仓库（{{ sessions.length }}）
 </p>
 <Button
 v-if="codingPlanId"
 variant="ghost"
 size="sm"
 class="text-xs"
 @click="openAppendDialog"
 >
 <span class="icon-[lucide--plus] mr-1" />
 对新仓库编码
 </Button>
 </div>
 <div class="divide-y divide-border/30">
 <CodingSessionStatusRow
 v-for="s in sessions":key="s.session_id":session="s":repo-git-url="repositoryGitUrls[s.repository_id] ?? ''"
 @retry="handleSessionRowRetry"
 />
 </div>
 </div>
 <!-- Phase：创建态内嵌 selector（替代旧的「开始编码」单仓按钮） -->
 <div v-if="showInlineSelector" class="px-4 pb-4 pt-2">
 <p class="text-xs text-muted-foreground font-medium mb-2">
 选择目标仓库
 </p>
 <RepoMultiSelector:repositories="availableRepositories":model-value="dialogSelectedIds":disabled-ids="existingActiveRepoIds":recommended-ids="recommendedRepositoryIds":submitting="repoMultiSelectorState.submitting"
 @update:model-value="(v: string) => dialogSelectedIds = v"
 @confirm="handleMultiConfirm"
 />
 </div>
 <!-- draft：分支名编辑 + 开始编码（codingPlanId 未提供时的向后兼容路径） -->
 <div v-if="!codingPlanId && status === 'draft'" class="px-4 pb-4">
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
 <!-- Phase：追加态 Dialog -->
 <Dialog v-model:open="dialogOpen">
 <DialogContent class="max-w-2xl">
 <DialogHeader>
 <DialogTitle>对新仓库追加编码</DialogTitle>
 <DialogDescription>
 选择尚未加入的仓库；已有进行中编码的仓库将被禁用。
 </DialogDescription>
 </DialogHeader>
 <RepoMultiSelector:repositories="availableRepositories":model-value="dialogSelectedIds":disabled-ids="existingActiveRepoIds":recommended-ids="recommendedRepositoryIds":submitting="repoMultiSelectorState.submitting"
 @update:model-value="(v: string) => dialogSelectedIds = v"
 @confirm="handleMultiConfirm"
 />
 </DialogContent>
 </Dialog>
 <!-- Phase：导出技术方案到飞书 -->
 <ExportConfirmDialog
 v-if="codingPlanId":open="showExportDialog":default-title="title || codingPlanRuntime?.title || '编码方案'"
 mode="coding_plan":coding-plan-id="codingPlanId"
 @update:open="(v: boolean) => showExportDialog = v"
 />
 </div>
</template>
