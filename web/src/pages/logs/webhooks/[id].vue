<script setup lang="ts">
import type { TriggerLogDetail } from '~/api/logs'
import { useClipboard } from '@vueuse/core'
import { useHead } from '@vueuse/head'
import { getTriggerLog } from '~/api/logs'
import StatusBadge from '~/components/common/StatusBadge.vue'
import { Button } from '~/components/ui/button'
import { Separator } from '~/components/ui/separator'

import { useErrorHandler } from '~/composables/useErrorHandler'

const route = useRoute('/logs/webhooks/[id]')
const router = useRouter()
const { handleError } = useErrorHandler()
const { success } = useToast()
const { copy } = useClipboard()

const logId = computed(() => route.params.id)

useHead({
  title: computed(() => `Webhook 日志 - Friday AI`),
})

// 加载数据
const loading = ref(true)
const log = ref<TriggerLogDetail | null>(null)

onMounted(async () => {
  try {
    log.value = await getTriggerLog(logId.value)
  }
  catch (e: unknown) {
    handleError(e, '加载日志详情')
  }
  finally {
    loading.value = false
  }
})

// 格式化日期
function formatDate(dateStr: string) {
  return new Date(dateStr).toLocaleString('zh-CN')
}

// 复制 JSON 到剪贴板
async function copyJson() {
  if (!log.value)
    return
  await copy(JSON.stringify(log.value.webhook_raw_request_parsed, null, 2))
  success('复制成功', 'JSON 已复制到剪贴板')
}
</script>

<template>
  <div class="space-y-6">
    <!-- 返回按钮 -->
    <RouterLink to="/logs" class="inline-flex items-center text-sm text-muted-foreground hover:text-foreground">
      <span class="icon-[lucide--arrow-left] mr-1" />
      返回日志列表
    </RouterLink>

    <!-- 加载状态 -->
    <LoadingState v-if="loading" variant="skeleton" :count="4" />

    <!-- 日志详情 -->
    <template v-else-if="log">
      <!-- 头部 -->
      <div class="flex items-start justify-between">
        <div class="space-y-2">
          <h1 class="text-2xl font-bold">
            Webhook 日志
          </h1>
          <div class="flex items-center gap-3">
            <StatusBadge type="triggerLog" :status="log.status" />
            <span v-if="log.event_type" class="text-muted-foreground">
              {{ log.event_type }}
            </span>
          </div>
        </div>
        <Button variant="outline" @click="copyJson">
          <span class="icon-[lucide--copy] mr-2" />
          复制 JSON
        </Button>
      </div>

      <!-- 基本信息卡片 -->
      <div class="card">
        <div class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2">
          <h3 class="text-sm font-semibold">
            基本信息
          </h3>
        </div>
        <div class="p-5 space-y-4">
          <div class="grid gap-4 md:grid-cols-2">
            <div>
              <label class="text-sm text-muted-foreground">日志 ID</label>
              <p class="font-mono text-sm">
                {{ log.id }}
              </p>
            </div>
            <div>
              <label class="text-sm text-muted-foreground">创建时间</label>
              <p class="text-sm">
                {{ formatDate(log.created_at) }}
              </p>
            </div>
          </div>
          <Separator />
          <div class="grid gap-4 md:grid-cols-2">
            <div>
              <label class="text-sm text-muted-foreground">事件 UUID</label>
              <p class="font-mono text-sm">
                {{ log.event_uuid || '-' }}
              </p>
            </div>
            <div>
              <label class="text-sm text-muted-foreground">事件类型</label>
              <p class="font-mono text-sm">
                {{ log.event_type || '-' }}
              </p>
            </div>
          </div>
          <Separator />
          <div class="grid gap-4 md:grid-cols-2">
            <div>
              <label class="text-sm text-muted-foreground">空间 ID</label>
              <p class="font-mono text-sm">
                {{ log.space_id || '-' }}
              </p>
            </div>
            <div>
              <label class="text-sm text-muted-foreground">日志 ID</label>
              <p class="font-mono text-sm">
                {{ log.id }}
              </p>
            </div>
          </div>
          <Separator v-if="log.error_message" />
          <div v-if="log.error_message">
            <label class="text-sm text-muted-foreground">错误信息</label>
            <p class="text-sm text-destructive">
              {{ log.error_message }}
            </p>
          </div>
        </div>
      </div>

      <!-- 原始请求卡片 -->
      <div class="card">
        <div class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2">
          <h3 class="text-sm font-semibold">
            原始请求数据
          </h3>
          <p class="text-xs text-muted-foreground mt-1">
            飞书 Webhook 发送的完整 JSON 请求体
          </p>
        </div>
        <div class="p-5 space-y-4">
          <div class="bg-muted rounded-lg p-4 overflow-auto max-h-[600px]">
            <pre class="text-sm font-mono whitespace-pre-wrap">{{ JSON.stringify(log.webhook_raw_request_parsed, null, 2) }}</pre>
          </div>
        </div>
      </div>
    </template>

    <!-- 日志不存在 -->
    <EmptyState
      v-else
      icon="lucide--help-circle"
      title="日志不存在"
      description="未找到该日志记录，可能已被删除"
      action-label="返回列表"
      @action="router.push('/logs')"
    />
  </div>
</template>
