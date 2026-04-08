<script setup lang="ts">
/**
 * 导出确认弹窗 -- 显示可编辑标题和选中消息数，点击导出后调用 API。
 * 导出失败时弹窗不关闭，显示分类错误提示 (per,,, )。
 */
import type { ExportToFeishuResponse } from '~/types/chat'
import {
 Dialog,
 DialogContent,
 DialogDescription,
 DialogFooter,
 DialogHeader,
 DialogTitle,
} from '~/components/ui/dialog'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
const props = defineProps<{
 open: boolean
 selectedCount: number
 defaultTitle: string
 selectedMessageIds: string
}>
const emit = defineEmits<{
 'update:open': [value: boolean]
 success: [result: ExportToFeishuResponse]
}>
const chatStore = useChatStore
const docTitle = ref(props.defaultTitle)
const exporting = ref(false)
const errorMsg = ref('')
const errorType = ref<string | null>(null)
// defaultTitle 变化时重置
watch( => props.defaultTitle, (v) => { docTitle.value = v })
// 打开时重置错误
watch( => props.open, (v) => { if (v) { errorMsg.value = ''; errorType.value = null } })
async function handleExport {
 exporting.value = true
 errorMsg.value = ''
 errorType.value = null
 try {
 const result = await chatStore.doExportToFeishu(
 docTitle.value,
 props.selectedMessageIds,
 )
 emit('success', result)
 emit('update:open', false)
 }
 catch (e: any) {
 // 解析后端错误响应 (per: 弹窗不关闭)
 const data = e?.response?.data || e?.data
 if (data?.error_type) {
 errorType.value = data.error_type
 errorMsg.value = data.error
 }
 else {
 errorType.value = 'api_error'
 errorMsg.value = data?.error || e?.detail || e?.message || '导出失败'
 }
 }
 finally {
 exporting.value = false
 }
}
const projectId = computed( => chatStore.selectedProjectId)
</script>
<template>
 <Dialog:open="open" @update:open="emit('update:open', $event)">
 <DialogContent class="card rounded-2xl max-w-md">
 <DialogHeader>
 <DialogTitle>导出到飞书文档</DialogTitle>
 <DialogDescription>
 将选中的 {{ selectedCount }} 条 AI 回答导出为飞书文档
 </DialogDescription>
 </DialogHeader>
 <!-- 文档标题输入 -->
 <div class="space-y-2">
 <label class="text-sm font-medium">文档标题</label>
 <Input
 v-model="docTitle"
 class=" text-sm"
 placeholder="输入文档标题":disabled="exporting"
 />
 </div>
 <!-- 错误区域 -->
 <div v-if="errorMsg" class="mt-2 rounded-lg border animate-fade-in">
 <!-- 未配置知识库 -->
 <div v-if="errorType === 'not_configured'" class="flex items-start gap-2">
 <span class="icon-[lucide--folder-x] text-amber-500 text-base shrink-0 mt-0.5" />
 <div class="space-y-1">
 <p class="text-sm text-foreground">尚未配置导出知识库</p>
 <RouterLink:to="`/projects/${projectId}/feishu`"
 class="text-sm text-primary hover:underline"
 @click="emit('update:open', false)"
 >
 前往项目设置
 </RouterLink>
 </div>
 </div>
 <!-- 无写权限 -->
 <div v-else-if="errorType === 'permission_denied'" class="flex items-start gap-2">
 <span class="icon-[lucide--lock] text-destructive text-base shrink-0 mt-0.5" />
 <p class="text-sm text-foreground">飞书应用无该文件夹的写入权限</p>
 </div>
 <!-- 其他错误 -->
 <div v-else class="flex items-start gap-2">
 <span class="icon-[lucide--alert-circle] text-destructive text-base shrink-0 mt-0.5" />
 <div class="flex-1 space-y-1">
 <p class="text-sm text-foreground">{{ errorMsg }}</p>
 <button
 class="text-sm text-primary hover:underline cursor-pointer"
 @click="handleExport"
 >
 重试
 </button>
 </div>
 </div>
 </div>
 <DialogFooter>
 <Button variant="outline" @click="emit('update:open', false)">
 取消
 </Button>
 <Button:disabled="exporting || selectedCount === 0"
 @click="handleExport"
 >
 <span v-if="exporting" class="icon-[lucide--loader-2] animate-spin mr-1" />
 {{ exporting ? '导出中...': '导出' }}
 </Button>
 </DialogFooter>
 </DialogContent>
 </Dialog>
</template>
