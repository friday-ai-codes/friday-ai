<script setup lang="ts">
import type MarkdownIt from 'markdown-it'
/**
 * 编码方案卡片 -- 在对话消息流中展示 AI 生成的技术方案。
 *
 * 包含：Markdown 渲染的技术方案 + 影响文件列表 + 分支名编辑区 + "开始编码"按钮。
 * 状态流转：draft -> confirming -> confirmed -> running -> completed/failed
 * 分支名编辑区：类型 Select + 只读日期 + 短描述 Input + 实时校验 + 预览
 */
import { computed, onMounted, ref, watch, watchEffect } from 'vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '~/components/ui/select'
import { useBranchValidation } from '~/composables/useBranchValidation'
import { getMarkdownRenderer } from '~/composables/useMarkdownRenderer'
const props = defineProps<{
 sessionId: string
 techPlan: string
 affectedFiles: Array<{ path: string, change_type: string }>
 status: 'draft' | 'confirmed' | 'running' | 'awaiting_confirmation' | 'completed' | 'failed'
 isConfirming: boolean
 branchName?: string
}>
const emit = defineEmits<{
 confirm: [sessionId: string, branchName?: string]
}>
const renderedPlan = ref('')
const mdReady = ref(false)
let mdInstance: MarkdownIt | null = null
onMounted(async => {
 mdInstance = await getMarkdownRenderer
 mdReady.value = true
})
watchEffect( => {
 if (mdInstance && props.techPlan) {
 renderedPlan.value = mdInstance.render(props.techPlan)
 }
})
// 分支名编辑状态
const { parseBranchName, buildBranchName, validateShortDesc } = useBranchValidation
// 解析服务端返回的分支名为三段
const parsed = computed( => props.branchName ? parseBranchName(props.branchName): null)
const branchType = ref(parsed.value?.type || 'feat')
const branchDate = computed( => parsed.value?.date || '')
const shortDesc = ref(parsed.value?.shortDesc || '')
// 实时校验
const validation = computed( => validateShortDesc(shortDesc.value))
// 实时预览
const previewBranchName = computed( =>
 branchDate.value ? buildBranchName(branchType.value, branchDate.value, shortDesc.value): '',
)
// 当 props.branchName 变化时更新本地状态
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
 emit('confirm', props.sessionId, editedBranch)
}
const badgeClass = computed( => {
 if (props.status === 'confirmed' || props.status === 'running') {
 return 'text-primary border-primary/30 bg-primary/5'
 }
 if (props.status === 'awaiting_confirmation') {
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
 <div class="card mt-2 animate-fade-in">
 <!-- 头部 -->
 <div class="px-4 py-3 border-b border-border/50 flex items-center gap-2">
 <span class="icon-[lucide--file-code] text-primary" />
 <span class="text-sm font-semibold">编码方案</span>
 <Badge
 v-if="status !== 'draft'":variant="status === 'failed' ? 'destructive': 'outline'"
 class="ml-auto":class="[badgeClass]"
 >
 {{ badgeText }}
 </Badge>
 </div>
 <!-- 内容区：Markdown 渲染 -->
 <div class=" space-y-3">
 <div v-if="mdReady" class="prose prose-sm max-w-none" v-html="renderedPlan" />
 <!-- 影响文件列表 -->
 <div v-if="affectedFiles.length > 0" class="space-y-1">
 <p class="text-xs text-muted-foreground font-medium">
 影响文件
 </p>
 <div
 v-for="(file, i) in affectedFiles":key="i"
 class="text-xs text-muted-foreground flex items-center gap-1"
 >
 <span class="icon-[lucide--file] text-[10px]" />
 <code class="text-xs">{{ file.path }}</code>
 <span class="text-muted-foreground/60">({{ file.change_type }})</span>
 </div>
 </div>
 </div>
 <!-- 底部操作区：draft 状态显示"开始编码"按钮 -->
 <div v-if="status === 'draft'" class="px-4 pb-4">
 <!-- 分支名编辑区 -->
 <div v-if="branchName" class="space-y-3 mb-3">
 <p class="text-xs text-muted-foreground font-medium">
 功能分支
 </p>
 <div class="flex items-end gap-2">
 <!-- 分支类型 Select -->
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
 <!-- 日期（只读） -->
 <span class="text-xs font-mono text-muted-foreground shrink-0 pb-2">{{ branchDate }}.</span>
 <!-- 短描述 Input -->
 <Input
 v-model="shortDesc"
 class="flex-1 font-mono text-sm"
 placeholder="简短描述（英文）":disabled="isConfirming"
 />
 </div>
 <!-- 校验错误 -->
 <p v-if="shortDesc && !validation.valid" class="text-xs text-destructive mt-1">
 {{ validation.error }}
 </p>
 <!-- 分支名预览 -->
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
 <!-- 已确认提示 -->
 <div v-else-if="status === 'confirmed' || status === 'running'" class="px-4 pb-3">
 <div class="text-xs text-muted-foreground flex items-center gap-1">
 <span class="icon-[lucide--check] text-primary" />
 已确认，正在启动编码...
 </div>
 </div>
 </div>
</template>
