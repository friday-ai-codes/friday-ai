<script setup lang="ts">
/**
 * PR 确认卡片 -- 支持编辑 PR 标题/描述/目标分支，创建或跳过 PR。
 *
 * 嵌入 Diff 摘要（: Collapsible + 文件列表，: 截断提示，: 绿/红数字）。
 * 顶部展示已完成确认步骤折叠摘要。
 */
import { Button } from '~/components/ui/button'
import { Badge } from '~/components/ui/badge'
import { Input } from '~/components/ui/input'
import { Textarea } from '~/components/ui/textarea'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '~/components/ui/collapsible'
import { confirmPR, getDiffSummary } from '~/api/chat'
import { useToast } from '~/composables/useToast'
const props = defineProps<{
 sessionId: string
 suggestedPrTitle: string
 suggestedPrDescription: string
 targetBranch: string
 branchUrl: string
 completedSteps: Array<{ step: string; summary: string }>
}>
const emit = defineEmits<{
 'create-pr': [sessionId: string, data: { title: string; description: string; target_branch: string }]
 'skip-pr': [sessionId: string]
}>
const { error: toastError } = useToast
const prTitle = ref(props.suggestedPrTitle)
const prDescription = ref(props.suggestedPrDescription)
const targetBranchInput = ref(props.targetBranch)
const submitting = ref(false)
const submitAction = ref<'create' | 'skip' | null>(null)
const completed = ref(false)
const completedResult = ref<{ type: 'pr' | 'branch'; url: string } | null>(null)
// Diff 摘要数据
const diffData = ref<{
 files?: Array<{ path: string; additions: number; deletions: number; change_type: string }>
 total_additions?: number
 total_deletions?: number
 truncated?: boolean
} | null>(null)
const diffLoading = ref(false)
const isValid = computed( => prTitle.value.trim.length > 0 && prTitle.value.length <= 200)
onMounted(async => {
 diffLoading.value = true
 try {
 diffData.value = await getDiffSummary(props.sessionId)
 } catch {
 // 静默失败 -- diff 摘要为增强功能，不阻断 PR 操作
 toastError('加载 Diff 摘要失败')
 } finally {
 diffLoading.value = false
 }
})
/** Textarea 自动调高，最大 300px (per work item) */
function autoResize(event: Event) {
 const el = event.target as HTMLTextAreaElement
 el.style.height = 'auto'
 el.style.height = `${Math.min(el.scrollHeight, 300)}px`
}
async function handleCreatePR {
 if (!isValid.value || submitting.value) return
 submitting.value = true
 submitAction.value = 'create'
 try {
 const result = await confirmPR(props.sessionId, {
 title: prTitle.value,
 description: prDescription.value,
 target_branch: targetBranchInput.value,
 })
 completed.value = true
 completedResult.value = { type: 'pr', url: (result as Record<string, unknown>).pr_url as string || '' }
 emit('create-pr', props.sessionId, {
 title: prTitle.value,
 description: prDescription.value,
 target_branch: targetBranchInput.value,
 })
 } catch {
 toastError('PR 创建失败，请重试')
 } finally {
 submitting.value = false
 submitAction.value = null
 }
}
async function handleSkipPR {
 if (submitting.value) return
 submitting.value = true
 submitAction.value = 'skip'
 try {
 await confirmPR(props.sessionId, { skip: true })
 completed.value = true
 completedResult.value = { type: 'branch', url: props.branchUrl }
 emit('skip-pr', props.sessionId)
 } catch {
 toastError('跳过 PR 失败，请重试')
 } finally {
 submitting.value = false
 submitAction.value = null
 }
}
</script>
<template>
 <!-- 完成态 -->
 <div v-if="completed && completedResult" class="card mt-2 animate-fade-in">
 <div class="px-4 py-3 border-b border-border/50 flex items-center gap-2">
 <span class="icon-[lucide--git-pull-request] text-primary" />
 <span class="text-sm font-semibold">
 {{ completedResult.type === 'pr' ? 'PR 已创建': '编码完成' }}
 </span>
 <Badge variant="success" class="ml-auto">编码完成</Badge>
 </div>
 <div class=" space-y-1.5">
 <!-- 已完成步骤摘要 -->
 <div v-if="completedSteps.length > 0" class="space-y-1 mb-3">
 <div
 v-for="(step, idx) in completedSteps":key="idx"
 class="text-xs text-muted-foreground flex items-center gap-1.5"
 >
 <span class="icon-[lucide--check] text-emerald-500 text-[10px]" />
 <span>{{ step.summary }}</span>
 </div>
 </div>
 <!-- 链接 -->
 <a
 v-if="completedResult.type === 'pr'":href="completedResult.url"
 target="_blank"
 rel="noopener noreferrer"
 class="text-sm text-primary hover:underline flex items-center gap-1"
 >
 查看 Pull Request
 <span class="icon-[lucide--external-link] text-[10px]" />
 </a>
 <a
 v-else:href="completedResult.url"
 target="_blank"
 rel="noopener noreferrer"
 class="text-sm text-primary hover:underline flex items-center gap-1"
 >
 查看分支
 <span class="icon-[lucide--external-link] text-[10px]" />
 </a>
 </div>
 </div>
 <!-- 编辑态 -->
 <div v-else class="card mt-2 animate-fade-in">
 <!-- 头部 -->
 <div class="px-4 py-3 border-b border-border/50 flex items-center gap-2">
 <span class="icon-[lucide--git-pull-request] text-primary" />
 <span class="text-sm font-semibold">创建 Pull Request</span>
 <Badge variant="info" class="ml-auto">待确认</Badge>
 </div>
 <!-- 内容区 -->
 <div class=" space-y-3">
 <!-- 已完成步骤摘要 -->
 <div v-if="completedSteps.length > 0" class="space-y-1 mb-3">
 <div
 v-for="(step, idx) in completedSteps":key="idx"
 class="text-xs text-muted-foreground flex items-center gap-1.5"
 >
 <span class="icon-[lucide--check] text-emerald-500 text-[10px]" />
 <span>{{ step.summary }}</span>
 </div>
 </div>
 <!-- Diff 摘要 Collapsible -->
 <Collapsible v-if="diffData && diffData.files?.length">
 <CollapsibleTrigger
 class="flex items-center gap-1 text-xs text-muted-foreground cursor-pointer hover:text-foreground transition-colors"
 >
 <span class="icon-[lucide--git-compare] text-primary" />
 Diff 摘要（{{ diffData.files?.length || 0 }} 个文件）
 <span class="text-emerald-600 font-mono">+{{ diffData.total_additions || 0 }}</span>
 <span class="text-red-500 font-mono">-{{ diffData.total_deletions || 0 }}</span>
 </CollapsibleTrigger>
 <CollapsibleContent class="mt-2">
 <div class="space-y-1">
 <div
 v-for="file in diffData.files":key="file.path"
 class="flex items-center justify-between text-xs py-0.5"
 >
 <code class="text-muted-foreground truncate">{{ file.path }}</code>
 <div class="flex gap-2 shrink-0">
 <span class="text-emerald-600 font-mono">+{{ file.additions }}</span>
 <span class="text-red-500 font-mono">-{{ file.deletions }}</span>
 </div>
 </div>
 </div>
 <p v-if="diffData.truncated" class="text-xs text-muted-foreground mt-2 italic">
 仅显示前 {{ diffData.files?.length }} 个文件，共有更多文件变更
 </p>
 </CollapsibleContent>
 </Collapsible>
 <!-- Diff 加载中 -->
 <div v-else-if="diffLoading" class="flex items-center gap-1 text-xs text-muted-foreground">
 <span class="icon-[lucide--loader-2] animate-spin text-primary" />
 加载 Diff 摘要...
 </div>
 <!-- 表单区 -->
 <div class="space-y-3 mt-3">
 <div>
 <label class="text-xs text-muted-foreground font-medium">PR 标题</label>
 <Input
 v-model="prTitle":disabled="submitting"
 maxlength="200"
 class="mt-1"
 />
 </div>
 <div>
 <label class="text-xs text-muted-foreground font-medium">PR 描述</label>
 <Textarea
 v-model="prDescription":disabled="submitting"
 rows="5"
 class="mt-1"
 @input="autoResize"
 />
 </div>
 <div>
 <label class="text-xs text-muted-foreground font-medium">目标分支</label>
 <Input
 v-model="targetBranchInput":disabled="submitting"
 class="mt-1"
 />
 </div>
 </div>
 </div>
 <!-- 底部操作区 -->
 <div class="px-4 pb-4 pt-2 flex gap-2">
 <Button
 class="flex-1":disabled="submitting || !isValid"
 @click="handleCreatePR"
 >
 <span v-if="submitting && submitAction === 'create'" class="icon-[lucide--loader-2] animate-spin mr-2" />
 创建 PR
 </Button>
 <Button
 variant="outline"
 class="flex-1":disabled="submitting"
 @click="handleSkipPR"
 >
 <span v-if="submitting && submitAction === 'skip'" class="icon-[lucide--loader-2] animate-spin mr-2" />
 跳过
 </Button>
 </div>
 </div>
</template>
