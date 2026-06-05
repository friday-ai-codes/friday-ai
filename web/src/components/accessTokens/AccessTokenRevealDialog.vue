<script setup lang="ts">
/**
 * Access Token 一次性明文展示弹窗（，安全核心 /02）
 *
 * 仿 pages/runners/new.vue 的一次性令牌展示范式：amber 警告框 + code 展示 + 复制。
 *
 * 安全：明文仅经 `token` prop 传入并以文本插值渲染（Vue 自动 HTML 转义，不使用裸 HTML 注入）；
 * 组件内不打印明文、不写任何浏览器存储。关闭（update:open=false）后由父组件
 * 负责清空内存 ref。
 */
import { useClipboard } from '@vueuse/core'
import { Button } from '~/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '~/components/ui/dialog'
import { useToast } from '~/composables/useToast'

const props = defineProps<{
  open: boolean
  token: string | null
}>()

const emit = defineEmits<{
  (e: 'update:open', v: boolean): void
}>()

const { copy } = useClipboard()
const toast = useToast()

async function onCopy() {
  if (!props.token)
    return
  await copy(props.token)
  toast.success('已复制 Access Token')
}
</script>

<template>
  <Dialog :open="open" @update:open="emit('update:open', $event)">
    <DialogContent class="max-w-lg">
      <DialogHeader>
        <DialogTitle>Access Token 已创建</DialogTitle>
        <DialogDescription>
          请立即复制并妥善保管你的 Access Token。
        </DialogDescription>
      </DialogHeader>

      <div class="space-y-4">
        <!-- 一次性警告框 -->
        <div class="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-700 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-400">
          <span class="icon-[lucide--alert-triangle] mr-1.5 align-text-bottom" aria-hidden="true" />
          此 Access Token 仅显示一次，关闭后无法再次查看，请立即复制并妥善保管。
        </div>

        <!-- 明文 + 复制（明文仅经 prop 渲染，无持久化、无打印） -->
        <div class="flex items-center gap-2">
          <code class="flex-1 break-all rounded-lg bg-muted p-3 font-mono text-sm">{{ token }}</code>
          <Button variant="outline" size="sm" @click="onCopy">
            <span class="icon-[lucide--copy] mr-1.5" aria-hidden="true" />复制
          </Button>
        </div>
      </div>
    </DialogContent>
  </Dialog>
</template>
