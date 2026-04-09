<script setup lang="ts">
/**
 * 编码方案卡片 -- 在对话消息流中展示 AI 生成的技术方案。
 *
 * 包含：Markdown 渲染的技术方案 + 影响文件列表 + "开始编码"按钮。
 * 状态流转：draft -> confirming -> confirmed -> running -> completed/failed
 */
import { ref, watchEffect, onMounted } from 'vue'
import type MarkdownIt from 'markdown-it'
import { Button } from '~/components/ui/button'
import { Badge } from '~/components/ui/badge'
import { getMarkdownRenderer } from '~/composables/useMarkdownRenderer'
const props = defineProps<{
 sessionId: string
 techPlan: string
 affectedFiles: Array<{ path: string; change_type: string }>
 status: 'draft' | 'confirmed' | 'running' | 'completed' | 'failed'
 isConfirming: boolean
}>
const emit = defineEmits<{
 confirm: [sessionId: string]
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
const badgeClass = computed( => {
 if (props.status === 'confirmed' || props.status === 'running') {
 return 'text-blue-500 border-blue-500/30 bg-blue-500/5'
 }
 if (props.status === 'completed') {
 return 'text-emerald-500 border-emerald-500/30 bg-emerald-500/5'
 }
 return ''
})
const badgeText = computed( => {
 if (props.status === 'confirmed' || props.status === 'running') return '已确认'
 if (props.status === 'completed') return '已完成'
 if (props.status === 'failed') return '失败'
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
 v-if="status !== 'draft'":variant="status === 'failed' ? 'destructive': 'outline'":class="['ml-auto', badgeClass]"
 >
 {{ badgeText }}
 </Badge>
 </div>
 <!-- 内容区：Markdown 渲染 -->
 <div class=" space-y-3">
 <div v-if="mdReady" class="prose prose-sm max-w-none" v-html="renderedPlan" />
 <!-- 影响文件列表 -->
 <div v-if="affectedFiles.length > 0" class="space-y-1">
 <p class="text-xs text-muted-foreground font-medium">影响文件</p>
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
 <Button class="w-full":disabled="isConfirming" @click="emit('confirm', sessionId)">
 <span v-if="isConfirming" class="icon-[lucide--loader-2] animate-spin mr-2" />
 开始编码
 </Button>
 </div>
 <!-- 已确认提示 -->
 <div v-else-if="status === 'confirmed' || status === 'running'" class="px-4 pb-3">
 <div class="text-xs text-muted-foreground flex items-center gap-1">
 <span class="icon-[lucide--check] text-emerald-500" />
 已确认，正在启动编码...
 </div>
 </div>
 </div>
</template>
