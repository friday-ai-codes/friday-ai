<script setup lang="ts">
import ExecutionStatusBadge from '~/components/execution/ExecutionStatusBadge.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Progress } from '~/components/ui/progress'

interface Props {
  workflowName: string
  executionId: string
  status: string | undefined
  progress: number
  duration: string
  triggerLogId?: string | null
  retryFromId: string | null
  resumedFromId: string | null
  isPausing: boolean
  isResuming: boolean
  isCancelling: boolean
  isRetrying: boolean
  /** : 是否可进入回放模式（终态执行） */
  canReplay?: boolean
  /** : 当前是否在回放模式 */
  isReplayMode?: boolean
}

defineProps<Props>()

const emit = defineEmits<{
  pause: []
  resume: []
  cancel: []
  retry: []
  refresh: []
  back: []
  /** : 进入/退出回放 */
  replay: []
}>()
</script>

<template>
  <header
    class="shrink-0 flex items-center justify-between px-4 py-2 h-14 bg-background/80 backdrop-blur-sm border-b border-border/50 z-20"
  >
    <!-- 左侧：返回 + 名称 -->
    <div class="flex items-center gap-3 min-w-0">
      <Button variant="ghost" size="icon" class="shrink-0 h-8 w-8" @click="emit('back')">
        <span class="icon-[lucide--arrow-left] w-4 h-4" />
      </Button>
      <div class="min-w-0">
        <div class="text-sm font-semibold truncate">
          {{ workflowName || '工作流执行' }}
        </div>
        <div class="flex items-center gap-2">
          <span class="text-[10px] text-muted-foreground font-mono truncate">
            {{ executionId }}
          </span>
          <RouterLink
            v-if="triggerLogId"
            :to="`/logs/triggers/${triggerLogId}`"
            class="inline-flex items-center gap-0.5 text-[10px] text-muted-foreground hover:text-primary transition-colors shrink-0"
            @click.stop
          >
            <span class="icon-[lucide--file-text] w-3 h-3" />
            来源日志
          </RouterLink>
        </div>
      </div>
    </div>

    <!-- 中部：状态 + 进度 + 耗时 -->
    <div v-if="status" class="flex items-center gap-3">
      <ExecutionStatusBadge :status="status" size="sm" />
      <!-- 重试来源标记 -->
      <div v-if="retryFromId" class="flex items-center gap-1.5">
        <Badge variant="warning" class="text-[10px] px-1.5 py-0">
          重试
        </Badge>
        <RouterLink
          :to="`/executions/${retryFromId}`"
          class="inline-flex items-center gap-0.5 text-[10px] text-muted-foreground hover:text-primary transition-colors"
        >
          原始执行
          <span class="icon-[lucide--external-link] w-2.5 h-2.5" />
        </RouterLink>
      </div>
      <!-- 从此继续来源标记 -->
      <div v-if="resumedFromId" class="flex items-center gap-1.5">
        <Badge variant="outline" class="text-[10px] px-1.5 py-0">
          继续
        </Badge>
        <RouterLink
          :to="`/executions/${resumedFromId}`"
          class="inline-flex items-center gap-0.5 text-[10px] text-muted-foreground hover:text-primary transition-colors"
        >
          原始执行
          <span class="icon-[lucide--external-link] w-2.5 h-2.5" />
        </RouterLink>
      </div>
      <div class="hidden sm:flex items-center gap-2 text-xs text-muted-foreground">
        <Progress :model-value="progress" class="w-24 h-1.5" />
        <span class="tabular-nums whitespace-nowrap">{{ Math.round(progress) }}%</span>
      </div>
      <div class="text-xs text-muted-foreground tabular-nums whitespace-nowrap">
        {{ duration }}
      </div>
    </div>

    <!-- 右侧：操作按钮 -->
    <div class="flex items-center gap-1.5">
      <Button
        v-if="status === 'running'"
        variant="outline"
        size="sm"
        class="h-7 text-xs"
        :disabled="isPausing"
        @click="emit('pause')"
      >
        <span v-if="isPausing" class="icon-[lucide--loader-2] w-3.5 h-3.5 mr-1 animate-spin" />
        <span v-else class="icon-[lucide--pause] w-3.5 h-3.5 mr-1" />
        暂停
      </Button>
      <Button
        v-if="status === 'paused'"
        variant="outline"
        size="sm"
        class="h-7 text-xs"
        :disabled="isResuming"
        @click="emit('resume')"
      >
        <span v-if="isResuming" class="icon-[lucide--loader-2] w-3.5 h-3.5 mr-1 animate-spin" />
        <span v-else class="icon-[lucide--play] w-3.5 h-3.5 mr-1" />
        继续
      </Button>
      <Button
        v-if="['running', 'paused', 'pending', 'waiting_approval', 'waiting_event', 'suspended'].includes(status || '')"
        variant="destructive"
        size="sm"
        class="h-7 text-xs"
        :disabled="isCancelling"
        @click="emit('cancel')"
      >
        <span v-if="isCancelling" class="icon-[lucide--loader-2] w-3.5 h-3.5 mr-1 animate-spin" />
        <span v-else class="icon-[lucide--square] w-3.5 h-3.5 mr-1" />
        取消
      </Button>
      <Button
        v-if="status === 'failed' || status === 'cancelled'"
        variant="default"
        size="sm"
        class="h-7 text-xs"
        :disabled="isRetrying"
        @click="emit('retry')"
      >
        <span v-if="isRetrying" class="icon-[lucide--loader-2] w-3.5 h-3.5 mr-1 animate-spin" />
        <span v-else class="icon-[lucide--rotate-ccw] w-3.5 h-3.5 mr-1" />
        重试
      </Button>
      <!-- : 回放执行 -->
      <Button
        v-if="canReplay && !isReplayMode"
        variant="outline"
        size="sm"
        class="h-7 text-xs"
        @click="emit('replay')"
      >
        <span class="icon-[lucide--play-circle] w-3.5 h-3.5 mr-1" />
        回放执行
      </Button>
      <Button
        v-if="isReplayMode"
        variant="outline"
        size="sm"
        class="h-7 text-xs"
        @click="emit('replay')"
      >
        <span class="icon-[lucide--x-circle] w-3.5 h-3.5 mr-1" />
        退出回放
      </Button>
      <Button variant="ghost" size="icon" class="h-7 w-7" @click="emit('refresh')">
        <span class="icon-[lucide--refresh-cw] w-3.5 h-3.5" />
      </Button>
    </div>
  </header>
</template>
