<script setup lang="ts">
import type { WritableComputedRef } from 'vue'
import type { WorkflowEdge, WorkflowNode } from '~/types/workflow/store'

import { computed } from 'vue'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { useConfigModel } from '~/composables/useConfigModel'

/**
 * AICodingConfig - AI 编码执行节点配置面板
 *
 * 配置项：
 * - timeout_seconds: 单个仓库的编码超时时间
 * - polling_interval: 检查 SubAgent 状态的时间间隔
 * - chat_id: 飞书群聊 ID，用于发送编码结果和分支确认卡片
 *
 * 容器镜像固定使用部署配置的默认 task 镜像，不再暴露给用户选择。
 */

interface AICodingConfig {
  timeout_seconds: number
  chat_id: string
  polling_interval: number
}

interface Props {
  config: AICodingConfig
  workflowNodes?: WorkflowNode[]
  workflowEdges?: WorkflowEdge[]
  currentNodeId?: string
}

const props = withDefaults(defineProps<Props>(), {
  workflowNodes: () => [],
  workflowEdges: () => [],
  currentNodeId: '',
})

const emit = defineEmits<{
  (e: 'update:config', value: AICodingConfig): void
}>()

const { field } = useConfigModel({
  config: () => props.config as unknown as Record<string, unknown>,
  emit: v => emit('update:config', v as unknown as AICodingConfig),
})

const timeoutSeconds = field('timeout_seconds', 1800) as WritableComputedRef<number>
const pollingInterval = field('polling_interval', 15) as WritableComputedRef<number>
const chatId = field('chat_id', '') as WritableComputedRef<string>

// 数值字段需要 string -> number 转换
const timeoutSecondsStr = computed({
  get: () => String(timeoutSeconds.value),
  set: (v: string) => { timeoutSeconds.value = Number(v) || 1800 },
})

const pollingIntervalStr = computed({
  get: () => String(pollingInterval.value),
  set: (v: string) => { pollingInterval.value = Number(v) || 15 },
})
</script>

<template>
  <div class="space-y-4">
    <!-- Introduction -->
    <div class="rounded-xl bg-primary/10 border border-primary/20 p-3">
      <div class="flex items-start gap-2">
        <span class="icon-[lucide--terminal] text-primary text-lg shrink-0 mt-0.5" />
        <div class="space-y-1.5">
          <h4 class="text-sm font-medium">
            AI 编码执行
          </h4>
          <p class="text-xs text-muted-foreground leading-relaxed">
            自动编码并创建 MR。按仓库并行分发 SubAgent，编码完成后自动创建 Merge Request。
          </p>

          <!-- Workflow Visual -->
          <div class="flex items-center gap-1 text-[10px] py-1.5 px-2 rounded-lg bg-muted/50">
            <span class="px-1.5 py-0.5 rounded bg-primary/10 text-primary font-medium">读取方案</span>
            <span class="icon-[lucide--arrow-right] text-muted-foreground" />
            <span class="px-1.5 py-0.5 rounded bg-primary/10 text-primary font-medium">SubAgent 编码</span>
            <span class="icon-[lucide--arrow-right] text-muted-foreground" />
            <span class="px-1.5 py-0.5 rounded bg-primary/10 text-primary font-medium">创建 MR</span>
            <span class="icon-[lucide--arrow-right] text-muted-foreground" />
            <span class="px-1.5 py-0.5 rounded bg-primary/10 text-primary font-medium">通知结果</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Timeout Seconds -->
    <div class="space-y-2">
      <Label class="flex items-center gap-1.5">
        <span class="icon-[lucide--timer] text-primary" />
        编码超时（秒）
      </Label>
      <Input
        v-model="timeoutSecondsStr"
        type="number"
        placeholder="1800"
        class="bg-background/50"
        min="60"
        max="7200"
      />
      <p class="text-xs text-muted-foreground">
        单个仓库的编码超时时间，默认 30 分钟
      </p>
    </div>

    <!-- Polling Interval -->
    <div class="space-y-2">
      <Label class="flex items-center gap-1.5">
        <span class="icon-[lucide--refresh-cw] text-primary" />
        轮询间隔（秒）
      </Label>
      <Input
        v-model="pollingIntervalStr"
        type="number"
        placeholder="15"
        class="bg-background/50"
        min="5"
        max="60"
      />
      <p class="text-xs text-muted-foreground">
        检查 SubAgent 状态的时间间隔
      </p>
    </div>

    <!-- Chat ID -->
    <div class="space-y-2">
      <Label class="flex items-center gap-1.5">
        <span class="icon-[lucide--message-circle] text-primary" />
        飞书群 ID
      </Label>
      <Input
        v-model="chatId"
        placeholder="输入飞书群 ID"
        class="bg-background/50"
      />
      <p class="text-xs text-muted-foreground">
        编码结果和分支确认卡片将发送到此群。留空则使用上游节点传递的 chat_id。
      </p>
    </div>
  </div>
</template>
