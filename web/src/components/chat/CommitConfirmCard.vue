<script setup lang="ts">
import { confirmCommit } from '~/api/chat'
import { Badge } from '~/components/ui/badge'
/**
 * Commit 确认卡片 -- 展示 AI 建议的 commit message，支持用户编辑后确认。
 *
 * 嵌入冲突警告（: Warning Alert，建议性质不阻断操作 ）。
 * 顶部展示已完成确认步骤折叠摘要。
 */
import { Button } from '~/components/ui/button'
import { Textarea } from '~/components/ui/textarea'
import { useToast } from '~/composables/useToast'
const props = defineProps<{
 sessionId: string
 suggestedCommitMessage: string
 conflictData: {
 has_conflicts?: boolean
 conflicting_files?: string
 behind_by?: number
 suggestion?: string
 } | null
 completedSteps: Array<{ step: string, summary: string }>
}>
const emit = defineEmits<{
 confirmed: [sessionId: string, commitMessage: string]
}>
const { error: toastError } = useToast
const commitMessage = ref(props.suggestedCommitMessage)
const submitting = ref(false)
const textareaRef = ref<InstanceType<typeof Textarea> | null>(null)
// commit message 字符数（: 最大 5000）
const charCount = computed( => commitMessage.value.length)
const isValid = computed( => commitMessage.value.trim.length > 0 && charCount.value <= 5000)
/** Textarea 自动调高，最大 200px */
function autoResize(event: Event) {
 const el = event.target as HTMLTextAreaElement
 el.style.height = 'auto'
 el.style.height = `${Math.min(el.scrollHeight, 200)}px`
}
onMounted( => {
 // 初始调高
 nextTick( => {
 const el = textareaRef.value?.$el?.querySelector?.('textarea') as HTMLTextAreaElement | null
 if (el) {
 el.style.height = 'auto'
 el.style.height = `${Math.min(el.scrollHeight, 200)}px`
 }
 })
})
async function handleConfirm {
 if (!isValid.value || submitting.value)
 return
 submitting.value = true
 try {
 await confirmCommit(props.sessionId, commitMessage.value)
 emit('confirmed', props.sessionId, commitMessage.value)
 }
 catch {
 toastError('Commit 确认失败，请重试')
 }
 finally {
 submitting.value = false
 }
}
</script>
<template>
 <div class="card mt-2 animate-fade-in">
 <!-- 头部 -->
 <div class="px-4 py-3 border-b border-border/50 flex items-center gap-2">
 <span class="icon-[lucide--git-commit-horizontal] text-primary" />
 <span class="text-sm font-semibold">确认 Commit</span>
 <Badge variant="info" class="ml-auto">
 待确认
 </Badge>
 </div>
 <!-- 内容区 -->
 <div class=" space-y-3">
 <!-- 已完成步骤摘要区 -->
 <div v-if="completedSteps.length > 0" class="space-y-1 mb-3">
 <div
 v-for="(step, idx) in completedSteps":key="idx"
 class="text-xs text-muted-foreground flex items-center gap-1.5"
 >
 <span class="icon-[lucide--check] text-emerald-500 text-[10px]" />
 <span>{{ step.summary }}</span>
 </div>
 </div>
 <!-- 冲突警告区 -->
 <div
 v-if="conflictData?.has_conflicts"
 class=" rounded-lg border border-amber-500/30 bg-amber-500/5 mb-3"
 >
 <div class="flex items-start gap-2">
 <span class="icon-[lucide--alert-triangle] text-amber-500 shrink-0 mt-0.5" />
 <div class="space-y-1 min-w-0">
 <p class="text-sm font-medium text-foreground">
 {{ conflictData.behind_by
 ? `检测到潜在合并冲突（落后 ${conflictData.behind_by} 个提交）`: '检测到潜在合并冲突'
 }}
 </p>
 <p v-if="conflictData.suggestion" class="text-xs text-muted-foreground">
 {{ conflictData.suggestion }}
 </p>
 <div
 v-if="conflictData.conflicting_files?.length"
 class="flex flex-wrap gap-1 mt-1"
 >
 <Badge
 v-for="file in conflictData.conflicting_files":key="file"
 variant="warning"
 class="text-xs"
 >
 {{ file }}
 </Badge>
 </div>
 </div>
 </div>
 </div>
 <!-- 表单区 -->
 <div class="space-y-3">
 <label class="text-xs text-muted-foreground font-medium">Commit Message</label>
 <Textarea
 ref="textareaRef"
 v-model="commitMessage":disabled="submitting"
 rows="3"
 class="font-mono text-sm"
 @input="autoResize"
 />
 <p
 class="text-xs text-right":class="charCount > 5000 ? 'text-destructive': 'text-muted-foreground'"
 >
 {{ charCount }}/5000
 </p>
 </div>
 </div>
 <!-- 底部操作区 -->
 <div class="px-4 pb-4 pt-2">
 <Button
 class="w-full":disabled="submitting || !isValid"
 @click="handleConfirm"
 >
 <span v-if="submitting" class="icon-[lucide--loader-2] animate-spin mr-2" />
 确认 Commit
 </Button>
 </div>
 </div>
</template>
