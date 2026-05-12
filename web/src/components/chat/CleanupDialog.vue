<script setup lang="ts">
/**
 * Phase Plan — CleanupDialog
 *
 * 对话历史清理弹窗：展示最早 N 条消息 preview + 批量勾选 + 二次确认 AlertDialog
 * + 调用 DELETE /api/chat/conversations/{id}/messages/?before_id=X 硬删。
 *
 * 契约（Plan Task 2 behavior C-G）：
 * - open=true 时拉取对话详情（GET /chat/conversations/{id}/），取前 20 条消息 preview
 * - 默认全选最早 5 条（或全部，若少于 5 条）
 * - 选中至少 1 条 + 点击"永久删除选中消息"→ AlertDialog 二次确认
 * - 确认后计算 before_id = 当前选中集合中最晚的消息 id 的下一条（即删除 < lastSelected.created_at）
 * - DELETE 成功：emit('confirm', beforeId) + emit('update:open', false)
 * - DELETE 失败：Dialog 保持开，errorMsg 展示
 */
import { computed, ref, watch } from 'vue'
import { toast } from 'vue-sonner'
import { del as apiDel, get as apiGet } from '~/api/client'
import {
 AlertDialog,
 AlertDialogAction,
 AlertDialogCancel,
 AlertDialogContent,
 AlertDialogDescription,
 AlertDialogFooter,
 AlertDialogHeader,
 AlertDialogTitle,
 AlertDialogTrigger,
} from '~/components/ui/alert-dialog'
import { Button } from '~/components/ui/button'
import { Checkbox } from '~/components/ui/checkbox'
import {
 Dialog,
 DialogContent,
 DialogDescription,
 DialogFooter,
 DialogHeader,
 DialogTitle,
} from '~/components/ui/dialog'
import { ScrollArea } from '~/components/ui/scroll-area'
interface MessagePreview {
 id: string
 role: 'user' | 'assistant' | 'system' | 'tool' | string
 content: string
 created_at: string
}
const props = defineProps<{
 open: boolean
 conversationId: string
}>
const emit = defineEmits<{
 'update:open': [value: boolean]
 'confirm': [beforeId: string]
 'cancel':
}>
const messages = ref<MessagePreview>
const selectedIds = ref<Set<string>>(new Set)
const loading = ref(false)
const deleting = ref(false)
const errorMsg = ref('')
const PREVIEW_LIMIT = 20
const DEFAULT_SELECT_COUNT = 5
const selectedCount = computed( => selectedIds.value.size)
async function loadMessages: Promise<void> {
 loading.value = true
 errorMsg.value = ''
 try {
 const resp = await apiGet<{ messages?: MessagePreview } | MessagePreview>(
 `/chat/conversations/${props.conversationId}/`,
 )
 const rawList: MessagePreview = Array.isArray(resp)
 ? resp: (resp?.messages ?? )
 // 按 created_at 升序取前 PREVIEW_LIMIT 条
 const sorted = [...rawList].sort((a, b) => a.created_at.localeCompare(b.created_at))
 messages.value = sorted.slice(0, PREVIEW_LIMIT)
 // 默认全选最早 DEFAULT_SELECT_COUNT 条（若少于则全选）
 const defaultPick = messages.value.slice(0, DEFAULT_SELECT_COUNT)
 selectedIds.value = new Set(defaultPick.map(m => m.id))
 }
 catch (e: any) {
 errorMsg.value = e?.message || '加载消息失败'
 }
 finally {
 loading.value = false
 }
}
watch(
 => props.open,
 (v) => {
 if (v) {
 loadMessages
 }
 },
 { immediate: true },
)
function toggleSelection(id: string): void {
 const next = new Set(selectedIds.value)
 if (next.has(id))
 next.delete(id)
 else next.add(id)
 selectedIds.value = next
}
function roleLabel(role: string): string {
 if (role === 'user')
 return '用户'
 if (role === 'assistant')
 return '助手'
 if (role === 'system')
 return '系统'
 if (role === 'tool')
 return '工具'
 return role
}
async function handleConfirmDelete: Promise<void> {
 if (selectedIds.value.size === 0)
 return
 deleting.value = true
 errorMsg.value = ''
 try {
 // before_id = 当前选中集合中时间最晚的消息的"下一条"（messages 已按升序排）
 // 策略：删除 < target.created_at → target 取 "选中之后的第一条未选消息"（若无则选最后选中的下一条）
 // 简化：取选中集合中最后（按消息列表顺序）一条的"下一条"消息 id；若为最后一条，用该消息 id 本身
 const selectedSet = selectedIds.value
 const lastSelectedIdx = messages.value.reduce((acc, m, idx) => (
 selectedSet.has(m.id) ? idx: acc
 ), -1)
 if (lastSelectedIdx < 0) {
 errorMsg.value = '未选中任何消息'
 return
 }
 // Phase Plan：末尾边界 — 选中 preview 列表最后一条时，拒绝提交
 // 避免 targetMsg fallback 到选中消息本身 → DELETE ?before_id=<self.id> 导致一条都删不掉
 // Pitfall 4：简化版（REVIEW 推荐方案）— 文案锁定自 work item §Fix 3
 if (lastSelectedIdx + 1 >= messages.value.length) {
 errorMsg.value = '请保留至少 1 条未选中消息作为清理边界（该消息自身不会被删）'
 return
 }
 // before_id = 下一条的 id（删 < 它的 created_at 即删除所有选中）；若无下一条则用当前选中
 const targetMsg = messages.value[lastSelectedIdx + 1] ?? messages.value[lastSelectedIdx]
 const beforeId = targetMsg.id
 await apiDel(
 `/chat/conversations/${props.conversationId}/messages/?before_id=${encodeURIComponent(beforeId)}`,
 )
 toast.success(`已清理 ${selectedIds.value.size} 条消息`)
 emit('confirm', beforeId)
 emit('update:open', false)
 }
 catch (e: any) {
 errorMsg.value = (e?.body as { detail?: string })?.detail
 || e?.detail
 || e?.message
 || '消息清理失败'
 }
 finally {
 deleting.value = false
 }
}
function handleCancel: void {
 emit('update:open', false)
 emit('cancel')
}
</script>
<template>
 <Dialog:open="props.open" @update:open="emit('update:open', $event)">
 <DialogContent class="card rounded-2xl max-w-lg">
 <DialogHeader>
 <DialogTitle>清理对话历史</DialogTitle>
 <DialogDescription>
 将删除以下最早 {{ selectedCount }} 条消息，此操作不可撤销。
 删除后该对话剩余消息将重新估算 token 用量。
 </DialogDescription>
 </DialogHeader>
 <ScrollArea class="max-">
 <div v-if="loading" class=" text-sm text-muted-foreground">
 加载中...
 </div>
 <div v-else-if="messages.length === 0" class=" text-sm text-muted-foreground">
 暂无可清理的消息
 </div>
 <ul v-else class="space-y-2 ">
 <li
 v-for="msg in messages":key="msg.id"
 class="flex items-start gap-2 rounded-md border border-border/50"
 >
 <Checkbox:id="`clean-msg-${msg.id}`":model-value="selectedIds.has(msg.id)":aria-label="`选择消息 ${roleLabel(msg.role)} ${msg.created_at}`"
 @update:model-value=" => toggleSelection(msg.id)"
 />
 <div class="flex-1 min-w-0 text-sm">
 <p class="text-xs text-muted-foreground">
 {{ roleLabel(msg.role) }} · {{ msg.created_at }}
 </p>
 <p class="line-clamp-1 break-all">
 {{ msg.content }}
 </p>
 </div>
 </li>
 </ul>
 </ScrollArea>
 <p v-if="errorMsg" class="text-sm text-destructive px-1">
 {{ errorMsg }}
 </p>
 <DialogFooter>
 <Button variant="outline":disabled="deleting" @click="handleCancel">
 取消
 </Button>
 <AlertDialog>
 <AlertDialogTrigger as-child>
 <Button
 variant="destructive":disabled="selectedCount === 0 || deleting":aria-label="`永久删除选中的 ${selectedCount} 条消息`"
 >
 永久删除选中消息
 </Button>
 </AlertDialogTrigger>
 <AlertDialogContent>
 <AlertDialogHeader>
 <AlertDialogTitle>
 确定要删除 {{ selectedCount }} 条消息吗？
 </AlertDialogTitle>
 <AlertDialogDescription>
 此操作不可撤销。被删除的消息无法通过任何方式恢复。
 </AlertDialogDescription>
 </AlertDialogHeader>
 <AlertDialogFooter>
 <AlertDialogCancel>取消</AlertDialogCancel>
 <AlertDialogAction @click="handleConfirmDelete">
 确认删除
 </AlertDialogAction>
 </AlertDialogFooter>
 </AlertDialogContent>
 </AlertDialog>
 </DialogFooter>
 </DialogContent>
 </Dialog>
</template>
