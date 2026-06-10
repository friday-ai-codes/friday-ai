<script setup lang="ts">
/**
 * 导出确认弹窗 -- 显示可编辑标题和选中消息数，点击导出后调用 API。
 * 导出失败时弹窗不关闭，显示分类错误提示 (per D-06, D-07, D-13, D-15)。
 *
 * 扩展：新增 `mode` prop 支持 `coding_plan` 分支。
 * 默认 `conversation`（ 路径完全兼容），mode='coding_plan' 时改
 * 走 `chatStore.doExportCodingPlanToFeishu`、隐藏"选中消息数"描述、改文案
 * 为"将技术方案导出为飞书文档"。错误 UI 三态完全复用。
 */
import type { ExportCodingPlanToFeishuResponse, ExportToFeishuResponse } from '~/types/chat'
import { Button } from '~/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '~/components/ui/dialog'

const props = withDefaults(defineProps<{
  open: boolean
  defaultTitle: string
  selectedCount?: number
  selectedMessageIds?: string[]
  mode?: 'conversation' | 'coding_plan'
  codingPlanId?: string
}>(), {
  mode: 'conversation',
  selectedCount: 0,
  selectedMessageIds: () => [],
})

const emit = defineEmits<{
  'update:open': [value: boolean]
  'success': [result: ExportToFeishuResponse | ExportCodingPlanToFeishuResponse]
}>()

const chatStore = useChatStore()
const docTitle = ref(props.defaultTitle)
const exporting = ref(false)
const errorMsg = ref('')
const errorType = ref<string | null>(null)

// defaultTitle 变化时重置
watch(() => props.defaultTitle, (v) => { docTitle.value = v })
// 打开时重置错误
watch(() => props.open, (v) => { if (v) { errorMsg.value = ''; errorType.value = null } })

async function handleExport() {
  exporting.value = true
  errorMsg.value = ''
  errorType.value = null
  try {
    if (props.mode === 'coding_plan') {
      if (!props.codingPlanId)
        throw new Error('缺少 codingPlanId')
      const result = await chatStore.doExportCodingPlanToFeishu(
        props.codingPlanId,
        docTitle.value,
      )
      emit('success', result)
    }
    else {
      const result = await chatStore.doExportToFeishu(
        docTitle.value,
        props.selectedMessageIds,
      )
      emit('success', result)
    }
    emit('update:open', false)
  }
  catch (e: any) {
    // 解析后端错误响应 (per D-15: 弹窗不关闭)
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

const spaceId = computed(() => chatStore.selectedSpaceId)
// coding_plan 模式下导出按钮不需要"选中消息"才能 enable
const exportDisabled = computed(() => {
  if (exporting.value)
    return true
  if (props.mode === 'coding_plan')
    return !props.codingPlanId
  return props.selectedCount === 0
})
</script>

<template>
  <Dialog :open="open" @update:open="emit('update:open', $event)">
    <DialogContent class="rounded-2xl max-w-md bg-white border-border/60 shadow-xl">
      <DialogHeader>
        <div class="export-dialog-icon">
          <svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" class="w-5 h-5">
            <path d="M10 8c0 1 7 3.5 14.745 16.744 0 0 4.184-4.363 6.255-5.744 1.5-1 2.712-1.332 2.712-1.332C33.712 15.156 29.5 8 28 8z" fill="#00d6b9" />
            <path d="M43.5 18.5c-1-.667-3.65-1.771-6.5-1.5a15 15 0 0 0-3.288.668S32.5 18 31 19c-2.07 1.38-6.255 5.744-6.255 5.744-1.428 1.397-3.05 2.732-5.245 3.756 0 0 7 3 11.5 3 5.063 0 7-3.5 7-3.5 1.5-3.305 3.5-7 5.5-9.5" fill="#163c9a" />
            <path d="M4 17.5v17c0 1 6 5.5 15 5.5 10 0 17.05-7.705 19-12 0 0-1.937 3.5-7 3.5-4.5 0-11.5-3-11.5-3-5.117-2.239-10.03-6.577-12.906-9.117C4.974 17.953 4 17.093 4 17.5" fill="#3370ff" />
          </svg>
        </div>
        <DialogTitle v-if="mode === 'conversation'">
          导出到飞书文档
        </DialogTitle>
        <DialogTitle v-else>
          导出技术方案到飞书
        </DialogTitle>
        <DialogDescription v-if="mode === 'conversation'">
          将选中的 {{ selectedCount }} 条 AI 回答导出为一篇飞书文档
        </DialogDescription>
        <DialogDescription v-else>
          将技术方案导出为飞书文档
        </DialogDescription>
      </DialogHeader>

      <!-- 文档标题输入 -->
      <div class="space-y-1.5">
        <label class="text-[13px] font-medium text-foreground/80">文档标题</label>
        <input
          v-model="docTitle"
          type="text"
          class="export-title-input"
          placeholder="输入文档标题"
          :disabled="exporting"
        >
      </div>

      <!-- 错误区域 -->
      <div v-if="errorMsg" class="mt-2 p-3 rounded-lg border animate-fade-in">
        <!-- 未配置文件夹 -->
        <div v-if="errorType === 'not_configured'" class="flex items-start gap-2">
          <span class="icon-[lucide--folder-x] text-amber-500 text-base shrink-0 mt-0.5" />
          <div class="space-y-1">
            <p class="text-sm text-foreground">
              尚未配置导出目标文件夹
            </p>
            <RouterLink
              :to="{ path: `/spaces/${spaceId}`, hash: '#feishu' }"
              class="text-sm text-primary hover:underline"
              @click="emit('update:open', false)"
            >
              前往空间设置
            </RouterLink>
          </div>
        </div>

        <!-- 无写权限 -->
        <div v-else-if="errorType === 'permission_denied'" class="flex items-start gap-2">
          <span class="icon-[lucide--lock] text-destructive text-base shrink-0 mt-0.5" />
          <p class="text-sm text-foreground">
            飞书应用无该文件夹的写入权限
          </p>
        </div>

        <!-- 其他错误 -->
        <div v-else class="flex items-start gap-2">
          <span class="icon-[lucide--alert-circle] text-destructive text-base shrink-0 mt-0.5" />
          <div class="flex-1 space-y-1">
            <p class="text-sm text-foreground">
              {{ errorMsg }}
            </p>
            <button
              class="text-sm text-primary hover:underline cursor-pointer"
              @click="handleExport"
            >
              重试
            </button>
          </div>
        </div>
      </div>

      <DialogFooter class="gap-2">
        <Button variant="ghost" class="rounded-xl" @click="emit('update:open', false)">
          取消
        </Button>
        <Button
          class="rounded-xl px-5"
          :disabled="exportDisabled"
          @click="handleExport"
        >
          <span v-if="exporting" class="icon-[lucide--loader-2] animate-spin mr-1" />
          <span v-else class="icon-[lucide--upload] mr-1 text-[13px]" />
          {{ exporting ? '导出中...' : '导出' }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>

<style scoped>
.export-dialog-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 2.5rem;
  height: 2.5rem;
  margin-bottom: 0.375rem;
  border-radius: 0.875rem;
  background: hsl(217 91% 60% / 0.08);
  border: 1px solid hsl(217 91% 60% / 0.15);
}

.export-title-input {
  display: block;
  width: 100%;
  height: 2.5rem;
  padding: 0 0.875rem;
  border-radius: 0.75rem;
  border: 1px solid hsl(214 32% 86%);
  background: hsl(0 0% 100%);
  color: hsl(215 28% 17%);
  font-size: 0.875rem;
  font-weight: 500;
  transition:
    border-color 0.15s ease,
    box-shadow 0.15s ease;
}

.export-title-input::placeholder {
  color: hsl(215 16% 62%);
  font-weight: 400;
}

.export-title-input:focus {
  outline: none;
  border-color: hsl(168 76% 42% / 0.55);
  box-shadow: 0 0 0 3px hsl(168 76% 42% / 0.1);
}

.export-title-input:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.export-title-input::selection {
  background: hsl(168 76% 42% / 0.2);
  color: hsl(215 28% 17%);
}
</style>
