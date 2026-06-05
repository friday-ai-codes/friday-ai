<script setup lang="ts">
/**
 * AISafetyConfirm -- AI 节点真实执行确认对话框
 *
 * AI 节点在调试暂停时，用户点击「真实执行」需要二次确认。
 * 提醒用户真实执行会消耗 token 并产生费用，建议使用 Mock 替代。
 */
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '~/components/ui/alert-dialog'

const _props = defineProps<{
  open: boolean
  nodeName: string
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  'confirm': []
  'cancel': []
}>()

// 仅同步 open 状态。不要在这里 emit('cancel'),否则 reka-ui 在
// AlertDialogAction 点击时同步触发的 update:open=false 会先 emit cancel,
// 再 emit confirm,父级 @cancel 处理器在 @confirm 之前就被调用,
// 容易踩到逻辑顺序的坑。cancel 仅由用户点击取消按钮显式触发。
function handleOpenChange(value: boolean) {
  emit('update:open', value)
}
</script>

<template>
  <AlertDialog :open="open" @update:open="handleOpenChange">
    <AlertDialogContent class="bg-card/95 backdrop-blur-md border-border/50">
      <AlertDialogHeader>
        <AlertDialogTitle class="flex items-center gap-2">
          <span class="icon-[lucide--alert-triangle] w-5 h-5 text-amber-400" />
          确认真实执行 AI 节点
        </AlertDialogTitle>
        <AlertDialogDescription class="text-muted-foreground">
          即将保留节点「{{ nodeName }}」的真实 AI 输出并放行。
          在调试阶段建议使用 Mock 数据替代，以避免不必要的 token 消耗。
        </AlertDialogDescription>
      </AlertDialogHeader>
      <AlertDialogFooter>
        <AlertDialogCancel @click="emit('cancel')">
          取消
        </AlertDialogCancel>
        <AlertDialogAction
          class="bg-amber-600 hover:bg-amber-700 text-white"
          @click="emit('confirm')"
        >
          <span class="icon-[lucide--zap] w-4 h-4 mr-1" />
          确认执行
        </AlertDialogAction>
      </AlertDialogFooter>
    </AlertDialogContent>
  </AlertDialog>
</template>
