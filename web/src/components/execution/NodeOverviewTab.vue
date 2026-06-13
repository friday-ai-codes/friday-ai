<script setup lang="ts">
import type { NodeExecution } from '~/stores/useExecutionsStore'
/**
 * NodeOverviewTab — 抽屉概览标签页
 *
 * 展示节点基本信息、状态、时间线、瓶颈标识和错误详情。
 */
import { computed } from 'vue'
import StatusBadge from '~/components/common/StatusBadge.vue'
import Badge from '~/components/ui/badge/Badge.vue'
import { useNodeStyle } from '~/components/workflow/editor/nodes/composables/useNodeStyle'
import { getNodeVisual } from '~/components/workflow/editor/nodes/nodeVisuals'
import ExecutionProviderSnapshot from '~/components/workflow/execution/ExecutionProviderSnapshot.vue'

/** UX-02 D-09：AI 节点 Provider 快照（由上层 NodeDetailSheet 透传） */
interface NodeSnapshot {
  provider_type: 'anthropic' | 'openai_responses' | 'openai_chat' | 'gemini' | 'ollama'
  model: string
  source: 'node' | 'conversation' | 'project' | 'system'
  credential_id: string | null
}

const props = defineProps<{
  nodeExecution: NodeExecution
  bottleneckInfo?: { level: string, rank: number, durationPercent: number } | null
  /** UX-02 D-09：AI 节点快照；undefined 表示非 AI 节点（不渲染），null 表示历史 Execution 快照 miss */
  providerSnapshot?: NodeSnapshot | null
  /** Replay 可用性（execution.status ∈ completed/error/failed 等终态） */
  canReplaySnapshot?: boolean
}>()

const emit = defineEmits<{
  /** UX-02 D-09：用户点击 "使用此快照重放" */
  replaySnapshot: [nodeId: string]
}>()

/** 仅 AI 节点 + 有快照（或 null miss）时渲染；非 AI 节点 providerSnapshot 应为 undefined */
const showProviderSnapshot = computed(() => props.providerSnapshot !== undefined)

const visual = computed(() => getNodeVisual(props.nodeExecution.node_type))
const style = computed(() => useNodeStyle(visual.value.color).value)

function formatDuration(seconds: number | null): string {
  if (seconds == null)
    return '-'
  if (seconds < 60)
    return `${Math.round(seconds)}s`
  if (seconds < 3600)
    return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`
}

function formatTime(isoStr: string | null): string {
  if (!isoStr)
    return '-'
  return new Date(isoStr).toLocaleString('zh-CN')
}

// OBS-01：Phase 17/18 结构化错误约定为「中文摘要 \n 末行 JSON」。
// 解析出 summary（友好展示）+ detail（结构化引用/拓扑）；非 JSON 回退纯文本，不抛错（T-21-07-03）。
function parseStructuredError(msg: string): { summary: string, detail: Record<string, any> | null } {
  const lines = msg.split('\n')
  if (lines.length < 2)
    return { summary: msg, detail: null }
  const lastLine = lines[lines.length - 1].trim()
  try {
    const parsed = JSON.parse(lastLine)
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      return { summary: lines.slice(0, -1).join('\n').trim(), detail: parsed }
    }
    return { summary: msg, detail: null }
  }
  catch {
    return { summary: msg, detail: null }
  }
}

const parsedError = computed(() =>
  props.nodeExecution.error_message
    ? parseStructuredError(props.nodeExecution.error_message)
    : null,
)
</script>

<template>
  <div class="space-y-4">
    <!-- 瓶颈标识 -->
    <div v-if="bottleneckInfo" class="flex items-center gap-2">
      <Badge
        :variant="bottleneckInfo.level === 'critical' ? 'destructive' : 'warning'"
      >
        {{ bottleneckInfo.level === 'critical' ? `瓶颈 #${bottleneckInfo.rank}` : `瓶颈 #${bottleneckInfo.rank}` }}
        · 占总耗时 {{ bottleneckInfo.durationPercent }}%
      </Badge>
    </div>

    <!-- 节点信息卡片 -->
    <div class="bg-card/60 backdrop-blur-sm border border-border/50 rounded-xl p-4 space-y-3">
      <!-- 节点类型 + 图标 -->
      <div class="flex items-center gap-3">
        <div class="bg-linear-to-br rounded-lg p-2" :class="[style.iconBg]">
          <component :is="visual.icon" class="w-5 h-5" :class="style.iconColor" />
        </div>
        <div>
          <div class="text-sm font-medium text-foreground">
            {{ nodeExecution.node_name }}
          </div>
          <div class="text-xs text-muted-foreground">
            {{ nodeExecution.node_type }}
          </div>
        </div>
      </div>

      <!-- 信息行 -->
      <div class="grid grid-cols-2 gap-2 text-sm">
        <div class="text-muted-foreground">
          状态
        </div>
        <div class="flex items-center">
          <StatusBadge type="execution" :status="nodeExecution.status" />
        </div>

        <div class="text-muted-foreground">
          开始时间
        </div>
        <div>{{ formatTime(nodeExecution.started_at) }}</div>

        <div class="text-muted-foreground">
          完成时间
        </div>
        <div>{{ formatTime(nodeExecution.completed_at) }}</div>

        <div class="text-muted-foreground">
          耗时
        </div>
        <div class="tabular-nums font-medium">
          {{ formatDuration(nodeExecution.duration) }}
        </div>

        <div v-if="nodeExecution.attempt > 1" class="text-muted-foreground">
          重试次数
        </div>
        <div v-if="nodeExecution.attempt > 1">
          {{ nodeExecution.attempt - 1 }}
        </div>

        <!-- OBS-01：错误码行 -->
        <div v-if="nodeExecution.error_code" class="text-muted-foreground">
          错误码
        </div>
        <div v-if="nodeExecution.error_code" class="font-mono text-xs">
          {{ nodeExecution.error_code }}
        </div>
      </div>
    </div>

    <!-- UX-02 D-09：AI 节点 Provider 快照 -->
    <ExecutionProviderSnapshot
      v-if="showProviderSnapshot"
      :node-id="nodeExecution.node"
      :snapshot="providerSnapshot ?? null"
      :can-replay="!!canReplaySnapshot"
      @replay="emit('replaySnapshot', nodeExecution.node)"
    />

    <!-- 错误信息 -->
    <div
      v-if="nodeExecution.error_message"
      class="bg-red-50 dark:bg-red-900/20 border border-red-200/50 dark:border-red-800/50 rounded-xl p-4 space-y-2"
    >
      <div class="text-sm font-medium text-red-600 dark:text-red-400">
        错误信息
      </div>
      <!-- OBS-01：结构化错误展示 summary（纯文本）+ detail（友好 key-value）；非 JSON 回退纯文本 -->
      <pre class="text-xs text-red-700 dark:text-red-300 whitespace-pre-wrap wrap-break-word">{{ parsedError?.summary ?? nodeExecution.error_message }}</pre>
      <div v-if="parsedError?.detail" class="text-xs text-red-700 dark:text-red-300 space-y-1">
        <div v-for="(value, key) in parsedError.detail" :key="key" class="flex gap-2">
          <span class="text-red-500/80 shrink-0">{{ key }}:</span>
          <span class="font-mono wrap-break-word">{{ typeof value === 'object' ? JSON.stringify(value) : value }}</span>
        </div>
      </div>
      <details v-if="nodeExecution.error_traceback" class="mt-2">
        <summary class="text-xs text-red-500 cursor-pointer hover:text-red-600">
          查看堆栈
        </summary>
        <pre class="mt-1 text-xs text-red-600/80 dark:text-red-400/80 whitespace-pre-wrap wrap-break-word overflow-auto max-h-60">{{ nodeExecution.error_traceback }}</pre>
      </details>
    </div>
  </div>
</template>
