<script setup lang="ts">
/**
 * Phase Plan — PinConfirmDialog（ 对话切换 Provider 确认弹窗）
 *
 * 触发时机：active 态对话（status ∈ {running, paused, interrupted}）用户在 ChatHeader
 * 下拉选中新 Provider / 模型 → 弹出本组件二次确认 → 确认后调 PATCH 更新 conversation。
 *
 * work item §Copywriting Contract 硬锁文案：
 * - 标题：切换 Provider 将固定当前 Provider 到本对话
 * - 正文：本对话已存在 {N} 条历史消息。切换后，此对话后续所有消息将使用新 Provider
 * {newProviderName} / {newModel} 计费与归因。原 Provider {oldProviderName} /
 * {oldModel} 的历史消息 token 统计不受影响。
 * - 按钮：取消 / 确认切换
 *
 * Analog: web/src/components/chat/ExportConfirmDialog.vue（PATTERNS §Pattern 1 ）。
 * Style: Sub2API Clean Card（禁用 backdrop-blur）；shadcn-vue Dialog 默认动效。
 */
import { ref, watch } from 'vue'
import { Button } from '~/components/ui/button'
import {
 Dialog,
 DialogContent,
 DialogDescription,
 DialogFooter,
 DialogHeader,
 DialogTitle,
} from '~/components/ui/dialog'
const props = defineProps<{
 open: boolean
 oldProviderName: string
 oldModel: string
 newProviderName: string
 newModel: string
 messageCount: number
}>
const emit = defineEmits<{
 'update:open': [value: boolean]
 'confirm':
 'cancel':
}>
const submitting = ref(false)
const errorMsg = ref('')
// 打开时重置错误 + loading 态
watch(
 => props.open,
 (v) => {
 if (v) {
 errorMsg.value = ''
 submitting.value = false
 }
 },
)
function handleConfirm {
 submitting.value = true
 emit('confirm')
}
function handleCancel {
 emit('cancel')
 emit('update:open', false)
}
/** 父组件通过 `showError(msg)` 让弹窗保持打开并显示错误（失败不关闭，参考 ExportConfirmDialog 模式）。 */
function showError(msg: string) {
 errorMsg.value = msg
 submitting.value = false
}
defineExpose({ showError })
</script>
<template>
 <Dialog:open="open" @update:open="emit('update:open', $event)">
 <DialogContent
 class="card rounded-2xl max-w-md"
 role="alertdialog"
 aria-labelledby="pin-dialog-title"
 aria-describedby="pin-dialog-description"
 >
 <DialogHeader>
 <DialogTitle id="pin-dialog-title" class="text-base font-semibold">
 切换 Provider 将固定当前 Provider 到本对话
 </DialogTitle>
 <DialogDescription id="pin-dialog-description" class="text-sm font-normal leading-6">
 本对话已存在 <span class="font-mono">{{ messageCount }}</span> 条历史消息。切换后，此对话后续所有消息将使用新 Provider
 <span class="font-semibold">{{ newProviderName }}</span> /
 <span class="font-mono">{{ newModel }}</span>
 计费与归因。原 Provider
 <span class="font-semibold">{{ oldProviderName }}</span> /
 <span class="font-mono">{{ oldModel }}</span>
 的历史消息 token 统计不受影响。
 </DialogDescription>
 </DialogHeader>
 <!-- Provider / 模型 diff 区块（原 → 新） -->
 <div class="space-y-2 rounded-lg border border-border/60 ">
 <div class="flex items-center gap-2 text-sm">
 <span class="text-muted-foreground w-10 shrink-0">原：</span>
 <span class="text-muted-foreground font-normal">{{ oldProviderName }}</span>
 <span class="text-muted-foreground">·</span>
 <span class="text-muted-foreground font-mono">{{ oldModel }}</span>
 </div>
 <div class="flex items-center gap-2 text-sm">
 <span class="text-foreground w-10 shrink-0">新：</span>
 <span class="text-foreground font-semibold">{{ newProviderName }}</span>
 <span class="text-foreground">·</span>
 <span class="text-foreground font-mono">{{ newModel }}</span>
 </div>
 </div>
 <!-- 错误区域（失败不关闭 Dialog） -->
 <div
 v-if="errorMsg"
 class="mt-2 rounded-lg border border-destructive/30 bg-destructive/5 flex items-start gap-2 animate-fade-in"
 >
 <span class="icon-[lucide--alert-circle] text-destructive text-base shrink-0 mt-0.5" />
 <p class="text-sm text-foreground">{{ errorMsg }}</p>
 </div>
 <DialogFooter class="gap-2">
 <Button
 variant="outline":disabled="submitting"
 @click="handleCancel"
 >
 取消
 </Button>
 <Button
 variant="default":disabled="submitting"
 @click="handleConfirm"
 >
 <span v-if="submitting" class="icon-[lucide--loader-2] animate-spin mr-1" />
 {{ submitting ? '切换中…': '确认切换' }}
 </Button>
 </DialogFooter>
 </DialogContent>
 </Dialog>
</template>
